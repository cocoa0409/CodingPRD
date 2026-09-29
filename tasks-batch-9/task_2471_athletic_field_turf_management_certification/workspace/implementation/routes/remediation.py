"""Discharging remediation orders through two separate hands (PRD 3.4)."""

import derive
import middleware
import response
import validate
from db import bump, db, now
from errors import ApiError
from routes.blueprint import bp
from routes.common import listing

FILTERS = {
    "field_id": "field_id",
    "source_assessment_id": "source_assessment_id",
    "verification_assessment_id": "verification_assessment_id",
    "submitted_by_staff_member_id": "submitted_by_staff_member_id",
    "severity": "severity",
    "status": "status",
}


@bp.get("/remediation-orders")
def list_orders():
    middleware.authenticate(middleware.ALL_ROLES)
    return listing(db.remediation_orders, FILTERS)


@bp.get("/remediation-orders/<order_id>")
def read_order(order_id):
    middleware.authenticate(middleware.ALL_ROLES)
    return response.ok(middleware.order_or_404(order_id))


@bp.post("/remediation-orders/<order_id>/submit-verification")
def submit_verification(order_id):
    user_id, _role = middleware.authenticate(["TurfAgronomist"])
    order = middleware.order_or_404(order_id)

    # priority 15 - segregation of duties, before the body is parsed
    source = db.safety_assessments[order["source_assessment_id"]]
    middleware.deny_self(user_id, source["inspector_staff_member_id"])

    body = validate.Body(required=["verification_assessment_id",
                                   "submitted_by_staff_member_id",
                                   "remediation_notes"])
    verification_id = body.string("verification_assessment_id")
    submitted_by = body.string("submitted_by_staff_member_id")
    notes = body.string("remediation_notes", 1, 2000)

    middleware.body_staff(submitted_by)                          # priority 19
    verification = middleware.body_assessment(verification_id)   # priority 20

    # priority 37 - the order must still be OPEN
    if order["status"] != "OPEN":
        raise ApiError("ERR_ORDER_NOT_OPEN", 409,
                       "Only an OPEN remediation order accepts a verification.")

    # priority 58 - the nominated re-test must genuinely be a re-test
    if (verification["field_id"] != order["field_id"]
            or verification["assessment_type"] != source["assessment_type"]
            or verification["status"] != "RECORDED"
            or verification["assessed_at_utc"].dt < order["opened_at_utc"].dt):
        raise ApiError("ERR_VERIFICATION_ASSESSMENT_INVALID", 422,
                       "The nominated assessment is not a valid re-test of this order.")

    order["status"] = "VERIFICATION_SUBMITTED"
    order["verification_assessment_id"] = verification_id
    order["submitted_by_staff_member_id"] = submitted_by
    order["remediation_notes"] = notes
    bump(order)
    # PRD 3.4: the posture is left entirely alone - the order still counts as open.
    return response.ok(order)


@bp.post("/remediation-orders/<order_id>/decide-verification")
def decide_verification(order_id):
    user_id, _role = middleware.authenticate(["SafetyInspector"])
    order = middleware.order_or_404(order_id)

    # priority 15 - the decider may not be the submitter
    middleware.deny_self(user_id, order["submitted_by_staff_member_id"])

    body = validate.Body(required=["decision"], optional=["decision_notes"])
    decision = body.enum("decision", ["ACCEPT", "REJECT"])
    body.string("decision_notes", 1, 2000)

    # priority 38 - the order must be awaiting a decision
    if order["status"] != "VERIFICATION_SUBMITTED":
        raise ApiError("ERR_ORDER_NOT_AWAITING_DECISION", 409,
                       "The order is not awaiting a verification decision.")

    field = db.fields[order["field_id"]]

    if decision == "ACCEPT":
        # priority 56 - an ADVISORY or FAIL re-test is not evidence of remediation
        verification = db.safety_assessments[order["verification_assessment_id"]]
        if verification["result"] != "PASS":
            raise ApiError("ERR_VERIFICATION_NOT_PASSING", 422,
                           "The verification assessment did not PASS.")
        order["status"] = "CLOSED_VERIFIED"
        order["closed_at_utc"] = now()
        bump(order)
        derive.touch_field(field)
        return response.ok(order)

    # REJECT is the cycle: back to OPEN, remediation_notes retained for audit.
    order["status"] = "OPEN"
    order["rejection_count"] = order["rejection_count"] + 1
    order["verification_assessment_id"] = None
    order["submitted_by_staff_member_id"] = None
    bump(order)
    return response.ok(order)
