"""Grantee counters, postures, the patient-majority calculation and the
freeze / unfreeze cascades (PRD 2.8, 2.9, 3.2)."""

import db
from validation import dec, minus_months, num


# --------------------------------------------------------------------------- #
# child selectors
# --------------------------------------------------------------------------- #


def sites_of(hc_id):
    return [s for s in db.db.service_sites.values() if s["health_center_id"] == hc_id]


def services_of(hc_id):
    return [s for s in db.db.service_definitions.values() if s["health_center_id"] == hc_id]


def board_of(hc_id):
    return [b for b in db.db.board_members.values() if b["health_center_id"] == hc_id]


def findings_of(hc_id):
    return [f for f in db.db.site_visit_findings.values() if f["health_center_id"] == hc_id]


def requests_of(hc_id):
    return [r for r in db.db.scope_change_requests.values() if r["health_center_id"] == hc_id]


def schedules_of(hc_id):
    return [f for f in db.db.fee_schedules.values() if f["health_center_id"] == hc_id]


def encounters_of_hc(hc_id):
    out = []
    for enc in db.db.encounters.values():
        site = db.db.service_sites.get(enc["service_site_id"])
        if site is not None and site["health_center_id"] == hc_id:
            out.append(enc)
    return out


def health_center_of_encounter(enc):
    site = db.db.service_sites.get(enc["service_site_id"])
    if site is None:
        return None
    return db.db.health_centers.get(site["health_center_id"])


# --------------------------------------------------------------------------- #
# conserved counters (PRD 2.8) — recounted on every read, zero drift
# --------------------------------------------------------------------------- #


def in_scope_site_count(hc_id):
    return sum(1 for s in sites_of(hc_id) if s["status"] == "IN_SCOPE")


def in_scope_service_count(hc_id):
    return sum(1 for s in services_of(hc_id) if s["status"] == "IN_SCOPE")


def seated_board_count(hc_id):
    return sum(1 for b in board_of(hc_id) if b["status"] == "SEATED")


def counts_as_open_condition(finding):
    """A finding contributes to open_condition_count once it has escalated and
    until an accepted plan resolves it: PRD 3.8 pins that a finding which has
    already escalated *remains counted* while its plan is under consideration
    (status CAP_SUBMITTED), so only RESOLVED drops it out."""
    return finding["escalated_at"] is not None and finding["status"] != "RESOLVED"


def open_condition_count(hc_id):
    return sum(1 for f in findings_of(hc_id) if counts_as_open_condition(f))


def wraparound_receivable_cents(hc_id):
    total = 0
    for enc in encounters_of_hc(hc_id):
        if enc["wraparound_status"] in ("PENDING", "CLAIMED", "REBILL_REQUIRED"):
            total += enc["wraparound_due_cents"]
    return total


def operational_status(hc_id):
    return "ACTIVE" if open_condition_count(hc_id) == 0 else "CONDITIONS_IMPOSED"


def scope_posture(hc_id):
    return "OPEN" if operational_status(hc_id) == "ACTIVE" else "CHANGE_FROZEN"


# --------------------------------------------------------------------------- #
# patient-majority governance (PRD 3.2 steps G1..G5)
# --------------------------------------------------------------------------- #


def patient_seat_qualified(member):
    """Step G2."""
    if member["status"] != "SEATED":
        return False
    if member["seat_type"] != "PATIENT" or member.get("patient_id") is None:
        return False
    boundary = minus_months(db.now(), 24)
    for enc in db.db.encounters.values():
        if enc["patient_id"] != member["patient_id"]:
            continue
        if enc["pps_claim_status"] == "VOID":
            continue
        if enc["encounter_date"] < boundary:
            continue
        site = db.db.service_sites.get(enc["service_site_id"])
        if site is None or site["status"] != "IN_SCOPE":
            continue
        if site["health_center_id"] != member["health_center_id"]:
            continue
        return True
    return False


def governance(hc_id):
    """Steps G1..G5.  Returns every intermediate the majority test uses."""
    seated = [b for b in board_of(hc_id) if b["status"] == "SEATED"]
    seated_count = len(seated)
    qualified = sum(1 for b in seated if patient_seat_qualified(b))
    non_patient = sum(1 for b in seated if b["seat_type"] == "NON_PATIENT")
    healthcare_industry = sum(
        1
        for b in seated
        if b["seat_type"] == "NON_PATIENT" and b.get("derives_over_10pct_income_from_healthcare")
    )

    if seated_count == 0:
        pct = num(0, 2)
    else:
        pct = num(dec(qualified * 100) / dec(seated_count), 2)

    compliant = (
        seated_count >= 3
        and seated_count <= 25
        and pct >= 51.00
        and healthcare_industry <= (non_patient // 2)
    )
    return {
        "seated_board_count": seated_count,
        "qualified_patient_seat_count": qualified,
        "non_patient_seat_count": non_patient,
        "healthcare_industry_seat_count": healthcare_industry,
        "patient_seat_pct": pct,
        "governance_posture": "GOVERNANCE_COMPLIANT" if compliant else "GOVERNANCE_DEFICIENT",
    }


def governance_posture(hc_id):
    return governance(hc_id)["governance_posture"]


# --------------------------------------------------------------------------- #
# derived snapshot / version bookkeeping
# --------------------------------------------------------------------------- #


def derived(hc):
    hc_id = hc["id"]
    gov = governance(hc_id)
    open_conditions = open_condition_count(hc_id)
    op_status = "ACTIVE" if open_conditions == 0 else "CONDITIONS_IMPOSED"
    return {
        "operational_status": op_status,
        "scope_posture": "OPEN" if op_status == "ACTIVE" else "CHANGE_FROZEN",
        "open_condition_count": open_conditions,
        "in_scope_site_count": in_scope_site_count(hc_id),
        "in_scope_service_count": in_scope_service_count(hc_id),
        "seated_board_count": gov["seated_board_count"],
        "patient_seat_pct": gov["patient_seat_pct"],
        "governance_posture": gov["governance_posture"],
        "wraparound_receivable_cents": wraparound_receivable_cents(hc_id),
    }


def bump(hc):
    """A recomputation of a derived field counts as a mutation (PRD 2.4)."""
    db.touch(hc)


# --------------------------------------------------------------------------- #
# scope freeze / unfreeze cascades (PRD 3.8)
# --------------------------------------------------------------------------- #


def freeze_scope(hc_id):
    """Escalation cascade hops 4 and 5: park pending requests, then their
    proposed target sites."""
    for req in db.in_creation_order(requests_of(hc_id)):
        if req["status"] in ("SUBMITTED", "UNDER_REVIEW"):
            req["held_from_status"] = req["status"]
            req["status"] = "HELD"
            db.touch(req)
            if req["request_type"] == "ADD_SITE" and req.get("target_site_id"):
                site = db.db.service_sites.get(req["target_site_id"])
                if site is not None and site["status"] == "PROPOSED":
                    site["status"] = "ON_HOLD"
                    site["hold_reason"] = "SCOPE_FROZEN"
                    db.touch(site)


def unfreeze_scope(hc_id):
    """Compensating cascade hops 3 and 4: restore held requests exactly, then
    return their parked target sites to PROPOSED."""
    for req in db.in_creation_order(requests_of(hc_id)):
        if req["status"] == "HELD":
            restored = req["held_from_status"]
            req["status"] = restored if restored else "SUBMITTED"
            req["held_from_status"] = None
            db.touch(req)
            if req["request_type"] == "ADD_SITE" and req.get("target_site_id"):
                site = db.db.service_sites.get(req["target_site_id"])
                if site is not None and site["status"] == "ON_HOLD":
                    site["status"] = "PROPOSED"
                    site["hold_reason"] = None
                    db.touch(site)


def apply_posture_side_effects(hc_id):
    """Propagate a posture flip through its dependent rows in the same request."""
    if scope_posture(hc_id) == "CHANGE_FROZEN":
        freeze_scope(hc_id)
    else:
        unfreeze_scope(hc_id)


# --------------------------------------------------------------------------- #
# patient ledger (PRD 2.8)
# --------------------------------------------------------------------------- #


def patient_balance_cents(patient_id):
    total = 0
    for enc in db.db.encounters.values():
        if enc["patient_id"] != patient_id:
            continue
        if enc["pps_claim_status"] == "VOID":
            continue
        total += enc["patient_charge_cents"] - enc["waived_amount_cents"]
    return total


def sliding_fee_status(patient_id):
    clock = db.now()
    verifications = [
        v for v in db.db.income_verifications.values() if v["patient_id"] == patient_id
    ]
    for v in verifications:
        if v["status"] == "VERIFIED" and v["effective_date"] <= clock <= v["expires_at"]:
            return "VERIFIED"
    if any(v["status"] == "EXPIRED" for v in verifications):
        return "EXPIRED"
    return "UNVERIFIED"
