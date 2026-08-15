"""Cross-entity cascades, revert checks, sweep logic."""

from db import store
from services.common import touch
from services.calc import OPEN_OFFER_STATUSES, mtm_rent_cents
from timeutil import parse_date, clock_date


def void_pending_concessions_for_offer(offer_id: str):
    """SUBMITTED/APPROVED ConcessionApprovals for the offer -> VOIDED."""
    for c in store.concession_approvals.values():
        if c["offer_id"] != offer_id:
            continue
        if c["status"] in ("SUBMITTED", "APPROVED"):
            c["status"] = "VOIDED"
            touch(c)


def lease_revert_check(lease: dict):
    """If lease is RENEWAL_PENDING and no open offers remain, revert to status_before_offer."""
    if lease["status"] != "RENEWAL_PENDING":
        return
    has_open = any(
        o["lease_id"] == lease["id"] and o["status"] in OPEN_OFFER_STATUSES
        for o in store.renewal_offers.values()
    )
    if has_open:
        return
    prior = lease.get("status_before_offer")
    if prior in ("ACTIVE", "MTM"):
        lease["status"] = prior
    lease["status_before_offer"] = None
    touch(lease)


def withdraw_offer_cascade(offer: dict):
    """Move offer to WITHDRAWN, void pending concessions, run revert check."""
    offer["status"] = "WITHDRAWN"
    touch(offer)
    void_pending_concessions_for_offer(offer["id"])
    lease = store.leases.get(offer["lease_id"])
    if lease is not None:
        lease_revert_check(lease)


def sweep(now_date=None):
    """Apply all due time-based transitions in fixed sweep order. Returns count of mutated entities."""
    if now_date is None:
        now_date = clock_date()
    transitions_applied = 0

    # (1) Notice cure-lapse: SERVED notices past cure_deadline -> CONFIRMED
    for n in list(store.non_renewal_notices.values()):
        if n["status"] != "SERVED":
            continue
        cure = n.get("cure_deadline_date")
        if cure and now_date > parse_date(cure):
            n["status"] = "CONFIRMED"
            touch(n)
            transitions_applied += 1

    # (2) Notice enforcement: CONFIRMED notices with effective_date reached -> ENFORCED
    for n in list(store.non_renewal_notices.values()):
        if n["status"] != "CONFIRMED":
            continue
        eff = n.get("effective_date")
        if eff and now_date >= parse_date(eff):
            n["status"] = "ENFORCED"
            touch(n)
            transitions_applied += 1
            lease = store.leases.get(n["lease_id"])
            if lease is not None and lease["status"] != "ENDED":
                lease["status"] = "ENDED"
                lease["status_before_offer"] = None
                touch(lease)
                transitions_applied += 1
                # ACCEPTED offer (if any) -> VOIDED; its GENERATED/RESIDENT_SIGNED doc -> VOIDED
                for o in store.renewal_offers.values():
                    if o["lease_id"] != lease["id"]:
                        continue
                    if o["status"] == "ACCEPTED":
                        o["status"] = "VOIDED"
                        touch(o)
                        transitions_applied += 1
                        void_pending_concessions_for_offer(o["id"])
                        for d in store.renewal_documents.values():
                            if d["offer_id"] == o["id"] and d["status"] in ("GENERATED", "RESIDENT_SIGNED"):
                                d["status"] = "VOIDED"
                                touch(d)
                                transitions_applied += 1
                # Also void pending concessions on this lease's other offers
                for o in store.renewal_offers.values():
                    if o["lease_id"] == lease["id"]:
                        for c in store.concession_approvals.values():
                            if c["offer_id"] == o["id"] and c["status"] in ("SUBMITTED", "APPROVED"):
                                c["status"] = "VOIDED"
                                touch(c)
                                transitions_applied += 1

    # (3) Offer expiry/void
    for o in list(store.renewal_offers.values()):
        if o["status"] in ("ISSUED", "COUNTERED"):
            rd = o.get("response_deadline_date")
            if rd and now_date > parse_date(rd):
                o["status"] = "EXPIRED"
                touch(o)
                transitions_applied += 1
                void_pending_concessions_for_offer(o["id"])
                lease = store.leases.get(o["lease_id"])
                if lease is not None:
                    lease_revert_check(lease)
        elif o["status"] == "ACCEPTED":
            ed = o.get("execution_deadline_date")
            if ed and now_date > parse_date(ed):
                o["status"] = "VOIDED"
                touch(o)
                transitions_applied += 1
                void_pending_concessions_for_offer(o["id"])
                for d in store.renewal_documents.values():
                    if d["offer_id"] == o["id"] and d["status"] in ("GENERATED", "RESIDENT_SIGNED"):
                        d["status"] = "VOIDED"
                        touch(d)
                        transitions_applied += 1
                lease = store.leases.get(o["lease_id"])
                if lease is not None:
                    lease_revert_check(lease)

    # (4) Lease MTM conversion
    for lease in list(store.leases.values()):
        if lease["status"] not in ("ACTIVE", "RENEWAL_PENDING"):
            continue
        te = lease.get("term_end_date")
        if not te:
            continue
        if now_date >= parse_date(te):
            # Get policy for mtm rent
            prop = store.properties.get(lease["property_id"])
            policy = store.rent_cap_policies.get(prop["rent_cap_policy_id"]) if prop else None
            if policy is not None:
                lease["monthly_rent_cents"] = mtm_rent_cents(lease, policy)
            lease["mtm_converted_on"] = now_date.strftime("%Y-%m-%d")
            # if offer cycle open, set status_before_offer = MTM
            has_open = any(
                o["lease_id"] == lease["id"] and o["status"] in OPEN_OFFER_STATUSES
                for o in store.renewal_offers.values()
            )
            lease["status"] = "MTM"
            lease["status_before_offer"] = "MTM" if has_open else None
            touch(lease)
            transitions_applied += 1

    return transitions_applied
