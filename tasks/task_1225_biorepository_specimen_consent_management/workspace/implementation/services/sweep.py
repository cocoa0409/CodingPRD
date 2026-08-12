"""Due-date sweep: withdrawals (with cascade), kit/agreement/grant expiry, reservation completion."""
import db
from clock import now
from services.common import touch, make_audit_record
from services.destruction import create_destruction_order
from services.specimen import recompute_volumes


def finalize_withdrawal(consent):
    """WITHDRAWAL_PENDING -> WITHDRAWN with the full 3-depth cascade."""
    current = now()
    consent["status"] = "WITHDRAWN"
    touch(consent)

    donor_id = consent["donor_id"]
    affected_specimens = [
        s for s in db.specimens.values()
        if s["donor_id"] == donor_id and s["lifecycle_status"] in ("ACCESSIONED", "IN_STORAGE")
    ]
    affected_specimen_ids = {s["id"] for s in affected_specimens}

    compromised_request_ids = set()
    # Depth 1+2: specimens -> DESTRUCTION_PENDING, one order each; aliquots flip; keys revoked.
    for sp in affected_specimens:
        flipped = []
        for a in db.aliquots.values():
            if a["specimen_id"] == sp["id"] and a["status"] in ("IN_STORAGE", "RESERVED", "QUARANTINED"):
                if a["status"] == "RESERVED" and a["reserved_for_request_id"]:
                    compromised_request_ids.add(a["reserved_for_request_id"])
                a["status"] = "DESTRUCTION_PENDING"
                touch(a)
                flipped.append(a)
        sp["lifecycle_status"] = "DESTRUCTION_PENDING"
        touch(sp)
        if flipped:
            recompute_volumes(sp)
        create_destruction_order(
            sp["id"],
            reason="CONSENT_WITHDRAWAL",
            created_by_user_id="system",
            consent_record_id=consent["id"],
        )
        for k in db.deidentification_keys.values():
            if k["specimen_id"] == sp["id"] and k["status"] == "ACTIVE":
                k["status"] = "REVOKED"
                touch(k)

    # Depth 3a: compromised requests + agreement release compensation.
    for req_id in compromised_request_ids:
        req = db.sample_requests.get(req_id)
        if req is None:
            continue
        if req["status"] == "APPROVED":
            req["status"] = "COMPROMISED"
            touch(req)
        agreement = db.sharing_agreements.get(req["sharing_agreement_id"])
        if agreement is not None and req["charged_volume_ml"]:
            charge = req["charged_volume_ml"]
            agreement["reserved_volume_ml"] = round(agreement["reserved_volume_ml"] - charge, 3)
            agreement["remaining_volume_ml"] = round(agreement["remaining_volume_ml"] + charge, 3)
            touch(agreement)

    # Depth 3b: recall flags for requests with already-DISTRIBUTED aliquots of the
    # affected specimens. reserved_for_request_id is cleared at checkout, so the
    # durable link is checked_out_for_request_id, stamped during checkout.
    for req in db.sample_requests.values():
        if req["status"] in ("APPROVED", "FULFILLED") and not req["recall_required"]:
            for a in db.aliquots.values():
                if (
                    a["specimen_id"] in affected_specimen_ids
                    and a["status"] == "DISTRIBUTED"
                    and a.get("checked_out_for_request_id") == req["id"]
                ):
                    req["recall_required"] = True
                    touch(req)
                    break


def run_sweep():
    current = now()
    withdrawals_finalized = 0
    kits_expired = 0
    agreements_expired = 0
    grants_expired = 0
    reservations_completed = 0

    # 1. Finalize due consent withdrawals (inclusive boundary).
    for consent in list(db.consent_records.values()):
        if (
            consent["status"] == "WITHDRAWAL_PENDING"
            and consent["grace_deadline"] is not None
            and current >= consent["grace_deadline"]
        ):
            finalize_withdrawal(consent)
            withdrawals_finalized += 1

    # 2. Expire kits (inclusive boundary; only IN_STOCK or DISTRIBUTED).
    for kit in list(db.collection_kits.values()):
        if kit["status"] in ("IN_STOCK", "DISTRIBUTED") and current >= kit["expires_at"]:
            kit["status"] = "EXPIRED"
            touch(kit)
            make_audit_record(db.custody_events, {
                "kit_id": kit["id"],
                "event_type": "EXPIRED",
                "actor_user_id": "system",
                "location": None,
                "note": None,
            })
            kits_expired += 1

    # 3. Expire agreements (inclusive boundary).
    for ag in list(db.sharing_agreements.values()):
        if ag["status"] == "ACTIVE" and current >= ag["effective_to"]:
            ag["status"] = "EXPIRED"
            touch(ag)
            agreements_expired += 1

    # 4. Expire grants (strict boundary: current > ends_at).
    for g in list(db.key_access_grants.values()):
        if g["status"] == "ACTIVE" and current > g["ends_at"]:
            g["status"] = "EXPIRED"
            touch(g)
            grants_expired += 1

    # 5. Complete slot reservations (inclusive boundary: ends_at <= now).
    for r in list(db.slot_reservations.values()):
        if r["status"] == "BOOKED" and r["ends_at"] <= current:
            r["status"] = "COMPLETED"
            touch(r)
            reservations_completed += 1

    return {
        "withdrawals_finalized": withdrawals_finalized,
        "kits_expired": kits_expired,
        "agreements_expired": agreements_expired,
        "grants_expired": grants_expired,
        "reservations_completed": reservations_completed,
    }
