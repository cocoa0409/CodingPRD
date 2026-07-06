"""Device Orders: intake, prior-auth submission, fabrication, delivery, cancel,
billing summary, compliance checks (PRD §3.3, §3.4, §3.5)."""
from flask import Blueprint, request

from db import db, base_common_fields, base_audit_fields
from errors import ApiError
from middleware import get_auth, require_roles
from response import ok_object, ok_array
from validation import (get_json_body, require_str, require_int, lookup,
                        parse_pagination, paginate)
from clock import parse_iso, parse_date, add_months, add_days, add_years
from services import (touch, calc_prior_auth_requirement, dmepos_compliance_gate,
                      calc_warranty_expiry, recompute_order_allowed_total,
                      calc_claim_line_allowed_final)
from serializers import device_order_out, prior_auth_out, compliance_check_out

bp = Blueprint("device_orders", __name__)

NON_TERMINAL_AUTH = ("SUBMITTED", "PENDED", "APPROVED")


def _bubble_order_to_fabrication(order):
    """CASCADE: an APPROVED PriorAuth moves AUTH_PENDING->FABRICATION when at
    least one milestone exists (PRD §3.4)."""
    if order["status"] != "AUTH_PENDING":
        return
    has_milestone = any(m["device_order_id"] == order["id"] for m in db.fabrication_milestones.values())
    if has_milestone:
        order["status"] = "FABRICATION"
        touch(order)


@bp.route("/op/device-orders", methods=["POST"])
def create_device_order():
    _, role = get_auth()
    require_roles(role, {"BillingSpecialist"})
    body = get_json_body()

    prescription_id = require_str(body, "prescription_id")
    supplier_id = require_str(body, "supplier_id")
    fitting_practitioner_id = require_str(body, "fitting_practitioner_id")

    # Existence (priority 3), body FKs left-to-right.
    rx = lookup(db.prescriptions, prescription_id)
    supplier = lookup(db.suppliers, supplier_id)
    fitting = lookup(db.physicians, fitting_practitioner_id)

    patient = db.patients.get(rx["patient_id"])
    # Referential consistency (priority 4): the Rx must resolve to a valid
    # patient chain.
    if patient is None:
        raise ApiError("ERR_REFERENTIAL_MISMATCH", "Prescription patient chain is inconsistent.")

    # State legality (priority 5) is not applicable to creation here; the Rx
    # status / window / pecos gates are domain business rules (priority 8-10),
    # but the PRD §3.10 lists state legality before them. Order creation has no
    # state-transition target, so we proceed to business rules in their
    # documented order: RX_NOT_SIGNED (9) is checked, RX_EXPIRED (8) is checked,
    # PHYSICIAN_NOT_PECOS (10), SAME_SIMILAR_OVERLAP (17). The PRD §3.3 lists the
    # surface order: referential, not-signed, expired, pecos, overlap. We follow
    # the validation-table priority: expired(8) before not-signed(9)? PRD §3.3
    # narrative checks not-signed then expired; §1.4 priorities are 8 then 9.
    # PRD prose wins: §3.3 lists "must be SIGNED ... rejected ERR_RX_NOT_SIGNED.
    # The logical clock must fall ... ERR_RX_EXPIRED." -> not-signed first.
    if rx["status"] != "SIGNED":
        raise ApiError("ERR_RX_NOT_SIGNED", "Prescription is not in SIGNED status.")

    clock = parse_iso(db.current_utc)
    window_end = add_months(parse_date(rx["face_to_face_date"]), 6)
    if clock > window_end:
        raise ApiError("ERR_RX_EXPIRED", "Prescription is past its 6-month validity window.")

    if patient["payer_type"] == "MEDICARE":
        prescribing = db.physicians.get(rx["physician_id"])
        if not (prescribing and prescribing["pecos_enrolled"]):
            raise ApiError("ERR_PHYSICIAN_NOT_PECOS", "Prescribing physician is not PECOS-enrolled.")

    # Same-or-similar overlap (priority 17): closed-closed 5-year RUL window,
    # keyed on patient + device_category.
    for o in db.device_orders.values():
        if o["status"] != "DELIVERED" or o["delivery_date"] is None:
            continue
        o_rx = db.prescriptions.get(o["prescription_id"])
        if o_rx is None:
            continue
        if o_rx["patient_id"] != patient["id"]:
            continue
        if o_rx["device_category"] != rx["device_category"]:
            continue
        start = parse_iso(o["delivery_date"])
        end = add_years(start, 5)
        if start <= clock <= end:
            raise ApiError("ERR_SAME_SIMILAR_OVERLAP",
                           "Patient already has a DELIVERED order of the same category within its RUL window.")

    # Create order.
    order = base_common_fields()
    order.update({
        "prescription_id": prescription_id,
        "supplier_id": supplier_id,
        "fitting_practitioner_id": fitting_practitioner_id,
        "status": "INTAKE",
        "requires_prior_auth": calc_prior_auth_requirement(patient["payer_type"], rx["device_category"]),
        "milestone_progress_pct": 0,
        "delivery_date": None,
        "warranty_expiry": None,
        "allowed_total_cents": 0,
    })
    db.device_orders[order["id"]] = order

    # CASCADE: consume the prescription SIGNED->CONSUMED, bump its version.
    rx["status"] = "CONSUMED"
    touch(rx)

    return ok_object(device_order_out(order), 201)


@bp.route("/op/device-orders/<rid>", methods=["GET"])
def get_device_order(rid):
    _, role = get_auth()
    require_roles(role, {"BillingSpecialist", "ComplianceOfficer", "Practitioner"})
    order = lookup(db.device_orders, rid)
    return ok_object(device_order_out(order), 200)


@bp.route("/op/device-orders", methods=["GET"])
def list_device_orders():
    _, role = get_auth()
    require_roles(role, {"BillingSpecialist", "ComplianceOfficer", "Practitioner"})
    limit, offset = parse_pagination()

    items = list(db.device_orders.values())
    prescription_id = request.args.get("prescription_id")
    supplier_id = request.args.get("supplier_id")
    fitting_practitioner_id = request.args.get("fitting_practitioner_id")
    if prescription_id is not None:
        items = [o for o in items if o["prescription_id"] == prescription_id]
    if supplier_id is not None:
        items = [o for o in items if o["supplier_id"] == supplier_id]
    if fitting_practitioner_id is not None:
        items = [o for o in items if o["fitting_practitioner_id"] == fitting_practitioner_id]

    page, total = paginate(items, limit, offset)
    return ok_array([device_order_out(o) for o in page], limit, offset, total, 200)


@bp.route("/op/device-orders/<rid>/submit-auth", methods=["POST"])
def submit_auth(rid):
    _, role = get_auth()
    require_roles(role, {"BillingSpecialist"})
    order = lookup(db.device_orders, rid)

    # State legality (priority 5): submit-auth defined only from INTAKE.
    if order["status"] != "INTAKE":
        raise ApiError("ERR_INVALID_STATE", "Order is not in INTAKE.")
    # requires_prior_auth must be true (transition precondition; treated as
    # invalid-state since the transition is undefined otherwise).
    if not order["requires_prior_auth"]:
        raise ApiError("ERR_INVALID_STATE", "Order does not require prior authorization.")

    # Single-active-auth (priority 18): reject if a non-terminal auth exists.
    for a in db.prior_auths.values():
        if a["device_order_id"] == order["id"] and a["status"] in NON_TERMINAL_AUTH:
            raise ApiError("ERR_AUTH_ALREADY_OPEN", "Order already owns a non-terminal prior authorization.")

    # CASCADE: order INTAKE->AUTH_PENDING and create PriorAuth SUBMITTED.
    order["status"] = "AUTH_PENDING"
    touch(order)

    clock = parse_iso(db.current_utc)
    from clock import to_iso_z
    auth = base_common_fields()
    auth.update({
        "device_order_id": order["id"],
        "status": "SUBMITTED",
        "auth_number": None,
        "submission_round": 1,
        "decision_deadline": to_iso_z(add_days(clock, 14)),
    })
    db.prior_auths[auth["id"]] = auth
    return ok_object(prior_auth_out(auth), 201)


@bp.route("/op/device-orders/<rid>/start-fabrication", methods=["POST"])
def start_fabrication(rid):
    _, role = get_auth()
    require_roles(role, {"Practitioner"})
    order = lookup(db.device_orders, rid)

    if order["status"] != "INTAKE":
        raise ApiError("ERR_INVALID_STATE", "Order is not in INTAKE.")
    if order["requires_prior_auth"]:
        raise ApiError("ERR_INVALID_STATE", "Order requires prior authorization.")
    has_milestone = any(m["device_order_id"] == order["id"] for m in db.fabrication_milestones.values())
    if not has_milestone:
        raise ApiError("ERR_MILESTONE_REQUIRED", "At least one fabrication milestone is required.")

    order["status"] = "FABRICATION"
    touch(order)
    return ok_object(device_order_out(order), 200)


@bp.route("/op/device-orders/<rid>/deliver", methods=["POST"])
def deliver(rid):
    _, role = get_auth()
    require_roles(role, {"Practitioner"})
    order = lookup(db.device_orders, rid)
    body = get_json_body()

    # State legality (priority 5): deliver defined only from READY_FOR_FITTING.
    if order["status"] != "READY_FOR_FITTING":
        raise ApiError("ERR_INVALID_STATE", "Order is not in READY_FOR_FITTING.")

    # Business rules. Per PRD §3.5 the three preconditions surface in order:
    # compliance gate (excluding segregation), segregation, then OCC version.
    # PRD §1.4 priorities: compliance(6), segregation(7), OCC(15). PRD §3.5
    # lists OCC first ("First, the supplied version must match"), then gate,
    # then segregation. PRD prose §3.5 wins: version -> gate -> segregation.
    expected = body.get("expected_device_order_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST", "expected_device_order_version is required and must be an integer.")
    if expected != order["version"]:
        raise ApiError("ERR_STALE_ORDER_VERSION", "expected_device_order_version does not match current version.")

    passed, reasons = dmepos_compliance_gate(order)
    if not passed:
        # Segregation surfaces as its own distinct rejection; any other failure
        # is ERR_COMPLIANCE_GATE_FAILED.
        non_seg = [r for r in reasons if r != "SEGREGATION_VIOLATION"]
        if non_seg:
            raise ApiError("ERR_COMPLIANCE_GATE_FAILED", "DMEPOS compliance gate failed: %s." % ", ".join(reasons))
        # Only segregation failed.
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "Fitting practitioner must differ from prescribing physician.")

    # Write append-only ComplianceCheck.
    check = base_audit_fields()
    check.update({
        "device_order_id": order["id"],
        "passed": passed,
        "failure_reasons": reasons,
    })
    db.compliance_checks[check["id"]] = check

    # Stamp delivery_date and compute warranty_expiry.
    from clock import to_iso_z
    clock = parse_iso(db.current_utc)
    order["delivery_date"] = to_iso_z(clock)
    rx = db.prescriptions.get(order["prescription_id"])
    order["warranty_expiry"] = to_iso_z(calc_warranty_expiry(clock, rx["device_category"]))
    order["status"] = "DELIVERED"

    # CASCADE: every DRAFT ClaimLine -> SUBMITTED (each bumps its own version).
    for cl in db.claim_lines.values():
        if cl["device_order_id"] == order["id"] and cl["adjudication_status"] == "DRAFT":
            cl["adjudication_status"] = "SUBMITTED"
            touch(cl)

    touch(order)
    return ok_object(device_order_out(order), 200)


@bp.route("/op/device-orders/<rid>/cancel", methods=["POST"])
def cancel(rid):
    _, role = get_auth()
    require_roles(role, {"BillingSpecialist"})
    order = lookup(db.device_orders, rid)

    if order["status"] not in ("INTAKE", "AUTH_PENDING"):
        raise ApiError("ERR_INVALID_STATE", "Order cannot be cancelled from its current state.")

    order["status"] = "CANCELLED"
    # CASCADE: covering PriorAuth in {SUBMITTED, PENDED} -> DENIED.
    for a in db.prior_auths.values():
        if a["device_order_id"] == order["id"] and a["status"] in ("SUBMITTED", "PENDED"):
            a["status"] = "DENIED"
            touch(a)
    touch(order)
    return ok_object(device_order_out(order), 200)


@bp.route("/op/device-orders/<rid>/billing-summary", methods=["GET"])
def billing_summary(rid):
    _, role = get_auth()
    require_roles(role, {"BillingSpecialist", "ComplianceOfficer"})
    order = lookup(db.device_orders, rid)

    lines = [c for c in db.claim_lines.values() if c["device_order_id"] == order["id"]]
    # Provisional: over SUBMITTED lines, billed amount with no modifier reduction.
    provisional = sum(c["fee_schedule_cents"] * c["billed_units"]
                      for c in lines if c["adjudication_status"] == "SUBMITTED")
    # Final: persisted allowed_cents over ADJUDICATED lines.
    final = sum(c["allowed_cents"] for c in lines if c["adjudication_status"] == "ADJUDICATED")

    data = {
        "device_order_id": order["id"],
        "provisional_allowed_total_cents": provisional,
        "final_allowed_total_cents": final,
    }
    return ok_object(data, 200)


@bp.route("/op/device-orders/<rid>/compliance-checks", methods=["GET"])
def list_compliance_checks(rid):
    _, role = get_auth()
    require_roles(role, {"ComplianceOfficer", "BillingSpecialist"})
    order = lookup(db.device_orders, rid)
    limit, offset = parse_pagination()

    items = [c for c in db.compliance_checks.values() if c["device_order_id"] == order["id"]]
    page, total = paginate(items, limit, offset)
    return ok_array([compliance_check_out(c) for c in page], limit, offset, total, 200)
