"""Business logic: state transitions, cascades, and EBT reconciliation.

Each function operates on the in-memory store dicts. Versioned entities are
mutated through db.touch() so updated_at/version stay consistent (PRD §2.4, §2.6).
"""
from db import db, touch
import calculations as calc


# =============================================================================
# EBT helpers
# =============================================================================
def ebt_for_participant(participant_id):
    for acc in db.ebt_accounts.values():
        if acc["participant_id"] == participant_id:
            return acc
    return None


def recompute_remaining(acc):
    """remaining_value_cents = issued - redeemed - voided (PRD §3.8). Also the
    conserved invariant: == sum(balance_units[c] * price[c]). We maintain both
    sides explicitly so they stay equal; remaining is never negative."""
    remaining = acc["issued_value_cents"] - acc["redeemed_value_cents"] - acc["voided_value_cents"]
    if remaining < 0:
        remaining = 0
    acc["remaining_value_cents"] = remaining


# =============================================================================
# Approval cascade (depth-3): Application APPROVED -> Certification ACTIVE
#   -> Participant ACTIVE + caseload++ + EbtAccount(OPEN)
# =============================================================================
def approve_cascade(application, participant, household, agency, certifier_user_id):
    application["certified_by_user_id"] = certifier_user_id
    application["status"] = "APPROVED"
    touch(application)

    category = participant["category"]
    period_start_dt = agency["_current_utc_dt"]
    cert_length_days, period_end_dt = calc.cert_period(category, period_start_dt)

    from response import iso_ms
    cert = _new_cert_record()
    cert.update({
        "participant_id": participant["id"],
        "application_id": application["id"],
        "period_start_utc": iso_ms(period_start_dt),
        "period_end_utc": iso_ms(period_end_dt),
        "_period_end_dt": period_end_dt,
        "cert_length_days": cert_length_days,
        "status": "ACTIVE",
    })
    db.certifications[cert["id"]] = cert

    # Level 2: participant APPLICANT -> ACTIVE, priority set, caseload debit,
    # EbtAccount created if absent.
    participant["status"] = "ACTIVE"
    participant["priority_level"] = calc.PRIORITY_BY_CATEGORY[category]
    touch(participant)

    agency["active_caseload_count"] += 1
    touch(agency)

    if ebt_for_participant(participant["id"]) is None:
        acc = _new_ebt_record()
        acc.update({
            "participant_id": participant["id"],
            "balance_units": {},
            "issued_value_cents": 0,
            "redeemed_value_cents": 0,
            "voided_value_cents": 0,
            "remaining_value_cents": 0,
            "status": "OPEN",
        })
        db.ebt_accounts[acc["id"]] = acc

    return cert


def _new_cert_record():
    from db import new_common
    return new_common()


def _new_ebt_record():
    from db import new_common
    return new_common()


# =============================================================================
# Certification suspend / reinstate
# =============================================================================
def suspend_cert(cert):
    cert["status"] = "SUSPENDED"
    touch(cert)
    participant = db.participants[cert["participant_id"]]
    participant["status"] = "SUSPENDED"
    touch(participant)
    acc = ebt_for_participant(participant["id"])
    if acc is not None and acc["status"] == "OPEN":
        acc["status"] = "FROZEN"
        touch(acc)
    # caseload unchanged — slot held during suspension


def reinstate_cert(cert):
    cert["status"] = "ACTIVE"
    touch(cert)
    participant = db.participants[cert["participant_id"]]
    participant["status"] = "ACTIVE"
    touch(participant)
    acc = ebt_for_participant(participant["id"])
    if acc is not None and acc["status"] == "FROZEN":
        acc["status"] = "OPEN"
        touch(acc)


# =============================================================================
# Certification termination / expiry (depth-3 cascade)
# =============================================================================
def _void_prescriptions_and_freeze(cert, agency):
    """Cascade L2/L3 shared by terminate and expiry: void outstanding
    prescriptions, move unredeemed value to EBT voided, zero balances, freeze."""
    participant = db.participants[cert["participant_id"]]
    acc = ebt_for_participant(participant["id"])

    prescriptions = [p for p in db.food_prescriptions.values()
                     if p["certification_id"] == cert["id"]
                     and p["status"] in ("ISSUED", "REDEEMED_PARTIAL")]
    # deterministic order
    prescriptions.sort(key=lambda p: p["_created_seq"])

    for presc in prescriptions:
        # unredeemed value remaining on this prescription
        unredeemed_cents = 0
        for fc, units in presc["_remaining_units"].items():
            unredeemed_cents += units * calc.UNIT_PRICE_CENTS[fc]
        presc["status"] = "VOIDED"
        # zero this prescription's remaining contribution
        if acc is not None and unredeemed_cents > 0:
            acc["voided_value_cents"] += unredeemed_cents
            for fc, units in presc["_remaining_units"].items():
                if units > 0:
                    cur = acc["balance_units"].get(fc, 0) - units
                    if cur < 0:
                        cur = 0
                    if cur == 0:
                        acc["balance_units"].pop(fc, None)
                    else:
                        acc["balance_units"][fc] = cur
        presc["_remaining_units"] = {}
        touch(presc)

    if acc is not None:
        recompute_remaining(acc)
        acc["status"] = "FROZEN"
        touch(acc)


def terminate_cert(cert, agency):
    participant = db.participants[cert["participant_id"]]
    cert["status"] = "TERMINATED"
    touch(cert)
    participant["status"] = "TERMINATED"
    touch(participant)
    agency["active_caseload_count"] -= 1
    if agency["active_caseload_count"] < 0:
        agency["active_caseload_count"] = 0
    touch(agency)
    _void_prescriptions_and_freeze(cert, agency)


def expire_cert(cert, agency):
    participant = db.participants[cert["participant_id"]]
    cert["status"] = "EXPIRED"
    touch(cert)
    participant["status"] = "TERMINATED"
    touch(participant)
    agency["active_caseload_count"] -= 1
    if agency["active_caseload_count"] < 0:
        agency["active_caseload_count"] = 0
    touch(agency)
    _void_prescriptions_and_freeze(cert, agency)


# =============================================================================
# Food prescription issuance (EBT top-up)
# =============================================================================
def issue_prescription(presc, acc):
    """presc carries _issued_units (food_category -> units) and
    prescribed_value_cents already computed. Tops up the EBT account."""
    acc["issued_value_cents"] += presc["prescribed_value_cents"]
    for fc, units in presc["_issued_units"].items():
        acc["balance_units"][fc] = acc["balance_units"].get(fc, 0) + units
    recompute_remaining(acc)
    touch(acc)


# =============================================================================
# Redemption draw-down (FIFO across prescriptions of the account)
# =============================================================================
def apply_redemption(acc, food_category, units):
    """Debits the account balance for the category, drawing down across the
    account's prescriptions in creation order (chronological), and advances each
    affected prescription's status. Caller has already validated sufficiency.
    Returns nothing; mutates account + prescriptions."""
    value_cents = units * calc.UNIT_PRICE_CENTS[food_category]

    # debit account balance
    cur = acc["balance_units"].get(food_category, 0) - units
    if cur <= 0:
        acc["balance_units"].pop(food_category, None)
    else:
        acc["balance_units"][food_category] = cur
    acc["redeemed_value_cents"] += value_cents
    recompute_remaining(acc)
    touch(acc)

    # draw down prescriptions FIFO for this category
    remaining_to_draw = units
    prescriptions = [p for p in db.food_prescriptions.values()
                     if p["participant_id"] == acc["participant_id"]
                     and p["status"] in ("ISSUED", "REDEEMED_PARTIAL")]
    prescriptions.sort(key=lambda p: p["_created_seq"])
    for presc in prescriptions:
        if remaining_to_draw <= 0:
            break
        avail = presc["_remaining_units"].get(food_category, 0)
        if avail <= 0:
            continue
        take = min(avail, remaining_to_draw)
        left = avail - take
        if left == 0:
            presc["_remaining_units"].pop(food_category, None)
        else:
            presc["_remaining_units"][food_category] = left
        remaining_to_draw -= take
        # advance prescription status
        any_left = any(v > 0 for v in presc["_remaining_units"].values())
        if any_left:
            presc["status"] = "REDEEMED_PARTIAL"
        else:
            presc["status"] = "REDEEMED_FULL"
        touch(presc)


# =============================================================================
# Vendor violation
# =============================================================================
def record_violation(vendor, points):
    vendor["violation_points"] += points
    if vendor["violation_points"] >= calc.SUSPENSION_THRESHOLD:
        vendor["status"] = "SUSPENDED"
    touch(vendor)


# =============================================================================
# Expiration sweep
# =============================================================================
def advance_expirations(agency):
    current_dt = agency["_current_utc_dt"]
    expired_ids = []
    # snapshot to avoid mutation-during-iteration issues
    certs = [c for c in db.certifications.values()
             if c["status"] == "ACTIVE"]
    certs.sort(key=lambda c: c["_created_seq"])
    for cert in certs:
        # only certs whose participant belongs to this agency
        participant = db.participants.get(cert["participant_id"])
        if participant is None or participant.get("agency_id") != agency["id"]:
            continue
        if current_dt >= cert["_period_end_dt"]:
            expire_cert(cert, agency)
            expired_ids.append(cert["id"])
    return expired_ids
