"""ServiceLine routing, financial split, voiding and the billing bubble-up.

calculations.service_line_route_assignment (4) and
calculations.service_line_financial_split (5).
"""
from flask import g

import constants as C
from store import db, new_row, by_seq, touch, touch_force


def select_policy(membership):
    """Candidate set: ACTIVE policies of the membership's household, ranked by
    created_at DESC.  Empty-set fallback is handled by the caller."""
    candidates = [
        p
        for p in db.policies.values()
        if p["family_id"] == membership["family_id"] and p["status"] == "ACTIVE"
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda p: p["_seq"], reverse=True)[0]


def assign_route(membership, service_code, plan, booking):
    """Exactly one route; branches are mutually exclusive, evaluated top to bottom."""
    if service_code in C.MEMBERSHIP_COVERED_SERVICE_CODES:
        return "COVERED_BY_MEMBERSHIP", None
    if service_code == "AFTER_HOURS_SURCHARGE":
        if plan is not None and plan["after_hours_surcharge_waived"]:
            return "COVERED_BY_MEMBERSHIP", None
        return "PATIENT_RESPONSIBILITY", None
    if service_code in ("LACTATION_CONSULT", "SLEEP_CONSULT"):
        if booking is not None and booking["coverage_route"] == "ENTITLEMENT":
            return "COVERED_BY_MEMBERSHIP", None
        return "PATIENT_RESPONSIBILITY", None
    if service_code in C.INSURANCE_ELIGIBLE_SERVICE_CODES:
        policy = select_policy(membership)
        if policy is not None:
            return "BILLED_TO_INSURANCE", policy
        return "PATIENT_RESPONSIBILITY", None
    return "PATIENT_RESPONSIBILITY", None


def create_service_line(
    membership,
    service_code,
    billed_amount_cents,
    plan,
    submitted_by,
    encounter_id=None,
    consult_booking_id=None,
    well_visit_id=None,
    booking=None,
):
    route, policy = assign_route(membership, service_code, plan, booking)

    fields = {
        "membership_id": membership["id"],
        "encounter_id": encounter_id,
        "consult_booking_id": consult_booking_id,
        "well_visit_id": well_visit_id,
        "policy_id": None,
        "service_code": service_code,
        "route": route,
        "billed_amount_cents": billed_amount_cents,
        "allowed_amount_cents": None,
        "write_off_cents": 0,
        "deductible_applied_cents": 0,
        "coinsurance_cents": 0,
        "plan_paid_cents": 0,
        "patient_responsibility_cents": 0,
        "membership_covered_cents": 0,
        "payment_received_cents": 0,
        "submitted_by_user_id": submitted_by,
        "adjudicated_by_user_id": None,
        "status": "ROUTED",
    }

    if route == "COVERED_BY_MEMBERSHIP":
        fields["allowed_amount_cents"] = billed_amount_cents
        fields["membership_covered_cents"] = billed_amount_cents
        fields["patient_responsibility_cents"] = 0
        fields["status"] = "SETTLED"
    elif route == "PATIENT_RESPONSIBILITY":
        fields["allowed_amount_cents"] = billed_amount_cents
        fields["patient_responsibility_cents"] = billed_amount_cents
        fields["membership_covered_cents"] = 0
        fields["status"] = "SETTLED"
    else:  # BILLED_TO_INSURANCE
        fields["policy_id"] = policy["id"]
        fields["allowed_amount_cents"] = None
        fields["status"] = "ROUTED"

    return new_row(db.service_lines, fields)


def lines_of_encounter(encounter_id):
    return by_seq(
        [l for l in db.service_lines.values() if l["encounter_id"] == encounter_id]
    )


def bubble_billing_axis(encounter):
    """BILLING_ROUTED -> BILLING_CLOSED once every child line is terminal."""
    if encounter is None or encounter["billing_status"] != "BILLING_ROUTED":
        return False
    lines = lines_of_encounter(encounter["id"])
    if not lines:
        return False
    for line in lines:
        if line["status"] not in ("SETTLED", "VOID"):
            return False
    encounter["billing_status"] = "BILLING_CLOSED"
    return True


def void_encounter_lines(encounter):
    """Void ROUTED/ADJUDICATED lines; reverse the deductible each ADJUDICATED
    insurance line consumed (the compensating action of PRD 2.10)."""
    for line in lines_of_encounter(encounter["id"]):
        if line["status"] not in ("ROUTED", "ADJUDICATED"):
            continue  # SETTLED lines are NOT voided
        was_adjudicated = line["status"] == "ADJUDICATED"
        line["status"] = "VOID"
        touch(line, g.touched)
        if was_adjudicated and line["route"] == "BILLED_TO_INSURANCE":
            policy = db.policies.get(line["policy_id"])
            if policy is not None:
                policy["deductible_met_cents"] -= line["deductible_applied_cents"]
                touch_force(policy, g.touched)
