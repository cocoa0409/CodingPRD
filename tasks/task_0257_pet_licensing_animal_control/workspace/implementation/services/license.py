"""License state machine (PRD §3.2-§3.5, SCAFFOLD §1.2).

States: DRAFT, SUBMITTED, UNDER_REVIEW, NEEDS_VACCINATION_PROOF, APPROVED,
ACTIVE, GRACE, EXPIRED, REJECTED, REVOKED. (REJECTED, REVOKED terminal.)
"""
from db import db
from errors import err
from services import calc
from services.core import (
    add_years, append_audit, days_between_floored, licenses_of_pet,
    parse_iso, pet_has_valid_rabies, recompute_kennel_occupied_slots,
    recompute_owner_active_license_count, recompute_owner_outstanding_penalty,
    touch,
)


def _rabies_record_valid(license_rec):
    """Approval gate (PRD §3.3): vaccination_record_id set, record is RABIES,
    unexpired vs current_utc."""
    vr_id = license_rec.get("vaccination_record_id")
    if not vr_id:
        return False
    vr = db.vaccination_records.get(vr_id)
    if vr is None or vr["vaccine_type"] != "RABIES":
        return False
    return parse_iso(vr["expires_on"]) > db.current_utc


def _mint_tag(license_rec):
    from services.core import stamp_create
    serial = db.next_tag_serial()
    tag = {
        "license_id": license_rec["id"],
        "serial": serial,
        "status": "ISSUED",
        "issued_on": _now_iso(),
    }
    stamp_create(tag, common_fields=True)
    db.tags[tag["id"]] = tag
    license_rec["tag_serial"] = serial
    return tag


def _now_iso():
    from db import now_iso
    return now_iso()


def _current_tag(license_rec):
    """The tag whose serial currently sits on the license (ISSUED)."""
    serial = license_rec.get("tag_serial")
    if serial is None:
        return None
    for t in db.tags.values():
        if t["license_id"] == license_rec["id"] and t["serial"] == serial:
            return t
    return None


# --------------------------------------------------------------------------- #
# DRAFT -> SUBMITTED  (Owner)
# --------------------------------------------------------------------------- #
def submit(license_rec):
    if license_rec["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "License is not in DRAFT.")

    pet = db.pets[license_rec["pet_id"]]
    if pet["status"] != "ACTIVE":
        raise err("ERR_PET_NOT_ACTIVE", "Pet is not ACTIVE.")

    owner = db.owners[license_rec["owner_id"]]
    if owner["status"] != "ACTIVE":
        raise err("ERR_OWNER_DELINQUENT", "Owner is DELINQUENT.")

    kind = license_rec["license_kind"]
    kennel_id = license_rec.get("kennel_id")
    if kind == "KENNEL":
        kennel = db.kennels.get(kennel_id) if kennel_id else None
        if kennel is None or kennel["status"] != "OPEN":
            raise err("ERR_LICENSE_KIND_MISMATCH",
                      "KENNEL license requires an OPEN kennel.")
        if kennel["occupied_slots"] >= kennel["slot_capacity"]:
            raise err("ERR_KENNEL_FULL", "Kennel has no free slots.")
    else:  # INDIVIDUAL
        if kennel_id is not None:
            raise err("ERR_LICENSE_KIND_MISMATCH",
                      "INDIVIDUAL license requires kennel_id null.")

    # provisional fee: declared is_altered, occupied_slots as of submission,
    # never the dangerous surcharge.
    occupied = 0
    if kind == "KENNEL":
        occupied = db.kennels[kennel_id]["occupied_slots"]
    license_rec["provisional_fee_cents"] = calc.license_fee(
        kind, pet["is_altered"], occupied, "provisional")
    license_rec["status"] = "SUBMITTED"
    touch(license_rec)
    append_audit("LICENSE", license_rec["id"], "LICENSE_SUBMITTED", _actor())


def start_review(license_rec):
    if license_rec["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "License is not SUBMITTED.")
    license_rec["status"] = "UNDER_REVIEW"
    touch(license_rec)
    append_audit("LICENSE", license_rec["id"], "LICENSE_REVIEW_STARTED", _actor())


def request_vaccination_proof(license_rec):
    if license_rec["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "License is not UNDER_REVIEW.")
    license_rec["status"] = "NEEDS_VACCINATION_PROOF"
    touch(license_rec)
    append_audit("LICENSE", license_rec["id"], "VACCINATION_PROOF_REQUESTED", _actor())


def attach_vaccination(license_rec, vaccination_record_id):
    if license_rec["status"] != "NEEDS_VACCINATION_PROOF":
        raise err("ERR_INVALID_STATE", "License is not NEEDS_VACCINATION_PROOF.")
    vr = db.vaccination_records.get(vaccination_record_id)
    if vr is None:
        raise err("ERR_NOT_FOUND", "Vaccination record not found.")
    if vr["pet_id"] != license_rec["pet_id"]:
        raise err("ERR_VACCINATION_MISMATCH", "Vaccination record pet mismatch.")
    if vr["vaccine_type"] != "RABIES":
        raise err("ERR_RABIES_PROOF_REQUIRED", "Vaccination is not RABIES.")
    if parse_iso(vr["expires_on"]) <= db.current_utc:
        raise err("ERR_VACCINATION_EXPIRED", "Vaccination has expired.")
    license_rec["vaccination_record_id"] = vaccination_record_id
    license_rec["status"] = "UNDER_REVIEW"
    touch(license_rec)
    append_audit("LICENSE", license_rec["id"], "VACCINATION_ATTACHED", _actor())


def approve(license_rec):
    if license_rec["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "License is not UNDER_REVIEW.")
    if not _rabies_record_valid(license_rec):
        raise err("ERR_RABIES_PROOF_REQUIRED", "Valid RABIES proof required.")
    pet = db.pets[license_rec["pet_id"]]
    if pet["status"] != "ACTIVE":
        raise err("ERR_PET_NOT_ACTIVE", "Pet is not ACTIVE.")

    occupied = 0
    if license_rec["license_kind"] == "KENNEL":
        occupied = db.kennels[license_rec["kennel_id"]]["occupied_slots"]
    surcharge = _active_designation_surcharge(pet["id"]) if pet["is_dangerous"] else 0
    license_rec["final_fee_cents"] = calc.license_fee(
        license_rec["license_kind"], pet["is_altered"], occupied, "final",
        pet_is_dangerous=pet["is_dangerous"], dangerous_surcharge_cents=surcharge)
    license_rec["status"] = "APPROVED"
    touch(license_rec)
    append_audit("LICENSE", license_rec["id"], "LICENSE_APPROVED", _actor())


def _active_designation_surcharge(pet_id):
    """Surcharge from the pet's currently-DESIGNATED case (for final fee at
    approval). Mirrors the cascade that adds surcharge to active licenses."""
    for case in db.dangerous_dog_cases.values():
        if case["pet_id"] == pet_id and case["status"] == "DESIGNATED":
            return case["surcharge_cents"]
    return 0


def reject(license_rec):
    if license_rec["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "License is not UNDER_REVIEW.")
    license_rec["status"] = "REJECTED"
    touch(license_rec)
    append_audit("LICENSE", license_rec["id"], "LICENSE_REJECTED", _actor())


# --------------------------------------------------------------------------- #
# APPROVED -> ACTIVE  (issue-tag, LicensingClerk)
# --------------------------------------------------------------------------- #
def issue_tag(license_rec):
    if license_rec["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "License is not APPROVED.")
    pet = db.pets[license_rec["pet_id"]]

    # dangerous-dog hold (PRD §3.4): permitted only if pet not dangerous, or any
    # case sits in OVERTURNED/DISMISSED; an open DESIGNATED case blocks.
    if pet["is_dangerous"]:
        raise err("ERR_DANGEROUS_DOG_HOLD", "Pet under a dangerous-dog hold.")

    now = db.current_utc
    new_start = now
    new_end = add_years(now, license_rec["term_years"])
    for other in licenses_of_pet(pet["id"]):
        if other["id"] == license_rec["id"]:
            continue
        if other["status"] in ("ACTIVE", "GRACE"):
            o_start = parse_iso(other["issued_on"])
            o_end = parse_iso(other["expires_on"])
            if o_start is None or o_end is None:
                continue
            # half-open overlap: [o_start, o_end) overlaps [new_start, new_end)
            if o_start < new_end and new_start < o_end:
                raise err("ERR_LICENSE_PERIOD_OVERLAP",
                          "License period overlaps a live license.")

    _mint_tag(license_rec)
    license_rec["issued_on"] = _now_iso()
    license_rec["expires_on"] = _iso(new_end)
    license_rec["status"] = "ACTIVE"
    touch(license_rec)

    recompute_owner_active_license_count(license_rec["owner_id"])
    if license_rec.get("kennel_id"):
        recompute_kennel_occupied_slots(license_rec["kennel_id"])
    append_audit("LICENSE", license_rec["id"], "TAG_ISSUED", _actor())


def _iso(dt):
    from db import iso
    return iso(dt)


# --------------------------------------------------------------------------- #
# renew  (Owner): GRACE->ACTIVE or EXPIRED->ACTIVE
# --------------------------------------------------------------------------- #
def renew(license_rec, pay_penalty_cents):
    status = license_rec["status"]
    if status not in ("GRACE", "EXPIRED"):
        raise err("ERR_INVALID_STATE", "License is not GRACE or EXPIRED.")

    if status == "EXPIRED":
        # penalty must be settled (already paid, or settled in full now)
        if not license_rec["penalty_paid"]:
            if pay_penalty_cents != license_rec["late_penalty_cents"]:
                raise err("ERR_PENALTY_UNPAID", "Penalty not settled in full.")
        if not pet_has_valid_rabies(license_rec["pet_id"]):
            raise err("ERR_RABIES_PROOF_REQUIRED", "Valid RABIES proof required.")
        license_rec["penalty_paid"] = True
    else:  # GRACE
        if not pet_has_valid_rabies(license_rec["pet_id"]):
            raise err("ERR_RABIES_PROOF_REQUIRED", "Valid RABIES proof required.")

    # mint replacement tag, supersede prior
    prior = _current_tag(license_rec)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)
    _mint_tag(license_rec)

    new_end = add_years(db.current_utc, license_rec["term_years"])
    license_rec["expires_on"] = _iso(new_end)
    license_rec["status"] = "ACTIVE"
    touch(license_rec)

    recompute_owner_outstanding_penalty(license_rec["owner_id"])
    recompute_owner_active_license_count(license_rec["owner_id"])
    if license_rec.get("kennel_id"):
        recompute_kennel_occupied_slots(license_rec["kennel_id"])

    action = "LICENSE_RENEWED_FROM_GRACE" if status == "GRACE" else "LICENSE_RENEWED_FROM_EXPIRED"
    append_audit("LICENSE", license_rec["id"], action, _actor())


# --------------------------------------------------------------------------- #
# pay-penalty  (Owner): EXPIRED self-loop
# --------------------------------------------------------------------------- #
def pay_penalty(license_rec, pay_penalty_cents):
    if license_rec["status"] != "EXPIRED":
        raise err("ERR_INVALID_STATE", "License is not EXPIRED.")
    if license_rec["penalty_paid"] is not False:
        raise err("ERR_INVALID_STATE", "Penalty already settled.")
    if pay_penalty_cents != license_rec["late_penalty_cents"]:
        raise err("ERR_PENALTY_UNPAID", "Penalty not settled in full.")
    license_rec["penalty_paid"] = True
    touch(license_rec)  # license stays EXPIRED
    recompute_owner_outstanding_penalty(license_rec["owner_id"])
    append_audit("LICENSE", license_rec["id"], "PENALTY_SETTLED", _actor())


# --------------------------------------------------------------------------- #
# revoke  (AnimalControlOfficer): ACTIVE/GRACE -> REVOKED
# --------------------------------------------------------------------------- #
def revoke(license_rec):
    if license_rec["status"] not in ("ACTIVE", "GRACE"):
        raise err("ERR_INVALID_STATE", "License is not ACTIVE or GRACE.")
    tag = _current_tag(license_rec)
    if tag is not None:
        tag["status"] = "VOID"
        touch(tag)
    license_rec["status"] = "REVOKED"
    touch(license_rec)
    recompute_owner_active_license_count(license_rec["owner_id"])
    if license_rec.get("kennel_id"):
        recompute_kennel_occupied_slots(license_rec["kennel_id"])
    append_audit("LICENSE", license_rec["id"], "LICENSE_REVOKED", _actor())


# --------------------------------------------------------------------------- #
# auto-transitions on clock advance (PRD §3.5)
# --------------------------------------------------------------------------- #
def evaluate_clock_transitions():
    """Re-evaluate ACTIVE->GRACE and GRACE->EXPIRED against current_utc.

    The transitions are applied in sequence, so a clock jump past both the
    expiry instant and the end of the grace window walks ACTIVE -> GRACE ->
    EXPIRED in one advance (each transition is recorded in the audit trail).
    """
    now = db.current_utc
    grace_delta = _grace_delta()
    for lic in list(db.licenses.values()):
        # ACTIVE -> GRACE the moment the clock is at/after expires_on
        if lic["status"] == "ACTIVE":
            expires = parse_iso(lic["expires_on"])
            if expires is not None and now >= expires:
                lic["status"] = "GRACE"
                touch(lic)
                # GRACE is still counted in occupied_slots, so occupancy is
                # unchanged here (recomputed only on EXPIRED/REVOKE/etc.).
                append_audit("LICENSE", lic["id"], "LICENSE_ENTERED_GRACE", "system")
        # GRACE -> EXPIRED once the clock is at/after the end of the grace window
        if lic["status"] == "GRACE":
            expires = parse_iso(lic["expires_on"])
            if expires is not None and now >= expires + grace_delta:
                _expire(lic, expires, grace_delta)


def _expire(lic, expires, grace_delta):
    grace_end = expires + grace_delta
    days_late = days_between_floored(db.current_utc, grace_end)
    lic["late_penalty_cents"] = calc.late_penalty(days_late, lic["final_fee_cents"])
    lic["penalty_paid"] = False
    lic["status"] = "EXPIRED"
    touch(lic)
    recompute_owner_outstanding_penalty(lic["owner_id"])
    recompute_owner_active_license_count(lic["owner_id"])
    if lic.get("kennel_id"):
        recompute_kennel_occupied_slots(lic["kennel_id"])
    append_audit("LICENSE", lic["id"], "LICENSE_EXPIRED", "system")


def _grace_delta():
    from datetime import timedelta
    return timedelta(days=calc.GRACE_DAYS)


# --------------------------------------------------------------------------- #
# actor role for audit provenance
# --------------------------------------------------------------------------- #
def _actor():
    from flask import request
    return request.headers.get("X-User-Role", "")
