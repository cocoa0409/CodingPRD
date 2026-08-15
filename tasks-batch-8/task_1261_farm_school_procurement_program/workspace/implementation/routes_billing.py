"""Invoices, reimbursement claims, claim lines, substitution requests, logical clock."""
import calendar
from datetime import date

from flask import Blueprint

from db import clock_date, clock_now, new_record, set_clock, store, touch
from errors import ApiError
from routes_core import CC, DPA, FM, SGA, get_or_404
from services import (claim_lines_of, claim_totals, grant_drawn, incentive_credit,
                      line_awarded, line_coverage, posture, run_clock_sweeps,
                      ser_claim, ser_claim_line, ser_invoice, ser_substitution,
                      substitution_cap_check)
from util import (body, ctx, list_response, ok_empty, ok_object, parse_iso8601,
                  parse_month, req_enum, req_int, req_str, require_role)

bp = Blueprint("billing", __name__)


def _invoice_farm(inv):
    return store["farms"][inv["farm_id"]]


# ---------------------------------------------------------------------------
# Invoice
# ---------------------------------------------------------------------------

@bp.route("/f2s/invoices", methods=["POST"])
def create_invoice():
    uid, role = ctx()
    b = body()
    delivery_id = req_str(b, "delivery_id")
    invoice_number = req_str(b, "invoice_number")
    require_role(role, FM)
    dlv = store["deliveries"].get(delivery_id)
    if dlv is None:
        raise ApiError("ERR_DELIVERY_NOT_FOUND", "Delivery %s not found" % delivery_id, 404)
    ag = store["agreements"][dlv["agreement_id"]]
    off = store["offerings"][ag["offering_id"]]
    farm = store["farms"][off["farm_id"]]
    if farm["id"] != uid:
        raise ApiError("ERR_RESOURCE_OWNERSHIP",
                       "FarmManager may only invoice its own farm's deliveries", 403)
    if dlv["status"] != "ACCEPTED":
        raise ApiError("ERR_DELIVERY_NOT_ACCEPTED",
                       "Invoice creation requires an ACCEPTED delivery", 409)
    for inv in store["invoices"].values():
        if inv["farm_id"] == farm["id"] and inv["invoice_number"] == invoice_number:
            raise ApiError("ERR_DUPLICATE_INVOICE_NUMBER",
                           "invoice_number is already used by this farm", 409)
    for inv in store["invoices"].values():
        if inv["delivery_id"] == delivery_id:
            raise ApiError("ERR_INVOICE_EXISTS_FOR_DELIVERY",
                           "Delivery already has an invoice", 409)
    qty = dlv["accepted_quantity"]
    price = ag["unit_price_cents"]
    subtotal = qty * price
    incentive = incentive_credit(farm["id"], ag["program_year_id"], ag["local_eligible"],
                                 subtotal)
    compliant_snapshot = posture(farm, dlv["delivery_date"]) == "COMPLIANT"
    rec = new_record()
    rec.update({
        "farm_id": farm["id"],
        "delivery_id": delivery_id,
        "agreement_id": ag["id"],
        "invoice_number": invoice_number,
        "quantity_billed": qty,
        "unit_price_cents": price,
        "subtotal_cents": subtotal,
        "incentive_credit_cents": incentive,
        "total_cents": subtotal + incentive,
        "farm_compliant_at_delivery": compliant_snapshot,
        "approved_by_user_id": None,
        "paid_at": None,
        "status": "DRAFT",
    })
    store["invoices"][rec["id"]] = rec
    return ok_object(ser_invoice(rec), 201)


@bp.route("/f2s/invoices", methods=["GET"])
def list_invoices():
    ctx()
    return list_response(store["invoices"].values(), ser_invoice, {
        "farm_id": "farm_id", "delivery_id": "delivery_id",
        "agreement_id": "agreement_id", "status": "status",
    })


@bp.route("/f2s/invoices/<rid>", methods=["GET"])
def get_invoice(rid):
    ctx()
    rec = get_or_404("invoices", rid, "ERR_INVOICE_NOT_FOUND")
    return ok_object(ser_invoice(rec))


def _owned_invoice(rid, uid):
    rec = get_or_404("invoices", rid, "ERR_INVOICE_NOT_FOUND")
    if rec["farm_id"] != uid:
        raise ApiError("ERR_RESOURCE_OWNERSHIP",
                       "FarmManager may only act on its own farm's invoices", 403)
    return rec


@bp.route("/f2s/invoices/<rid>/submit", methods=["POST"])
def submit_invoice(rid):
    uid, role = ctx()
    require_role(role, FM)
    rec = _owned_invoice(rid, uid)
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVOICE_NOT_SUBMITTABLE", "submit requires status DRAFT", 409)
    farm = _invoice_farm(rec)
    if farm["status"] != "APPROVED":
        raise ApiError("ERR_FARM_NOT_APPROVED", "submit requires farm APPROVED", 409)
    rec["status"] = "SUBMITTED"
    touch(rec)
    return ok_object(ser_invoice(rec))


@bp.route("/f2s/invoices/<rid>/approve", methods=["POST"])
def approve_invoice(rid):
    uid, role = ctx()
    require_role(role, DPA)
    rec = get_or_404("invoices", rid, "ERR_INVOICE_NOT_FOUND")
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVOICE_NOT_APPROVABLE", "approve requires status SUBMITTED", 409)
    rec["status"] = "APPROVED"
    rec["approved_by_user_id"] = uid
    touch(rec)
    return ok_object(ser_invoice(rec))


@bp.route("/f2s/invoices/<rid>/reject", methods=["POST"])
def reject_invoice(rid):
    uid, role = ctx()
    b = body()
    req_str(b, "reason")
    require_role(role, DPA)
    rec = get_or_404("invoices", rid, "ERR_INVOICE_NOT_FOUND")
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVOICE_NOT_APPROVABLE", "reject requires status SUBMITTED", 409)
    rec["status"] = "REJECTED"
    touch(rec)
    return ok_object(ser_invoice(rec))


@bp.route("/f2s/invoices/<rid>/revise", methods=["POST"])
def revise_invoice(rid):
    uid, role = ctx()
    require_role(role, FM)
    rec = _owned_invoice(rid, uid)
    if rec["status"] != "REJECTED":
        raise ApiError("ERR_INVOICE_NOT_REVISABLE", "revise requires status REJECTED", 409)
    rec["status"] = "DRAFT"
    touch(rec)
    return ok_object(ser_invoice(rec))


@bp.route("/f2s/invoices/<rid>/pay", methods=["POST"])
def pay_invoice(rid):
    uid, role = ctx()
    require_role(role, DPA)
    rec = get_or_404("invoices", rid, "ERR_INVOICE_NOT_FOUND")
    if rec["status"] != "APPROVED":
        raise ApiError("ERR_INVOICE_NOT_PAYABLE", "pay requires status APPROVED", 409)
    rec["status"] = "PAID"
    from db import now_iso
    rec["paid_at"] = now_iso()
    touch(rec)
    return ok_object(ser_invoice(rec))


# ---------------------------------------------------------------------------
# ReimbursementClaim
# ---------------------------------------------------------------------------

@bp.route("/f2s/reimbursement-claims", methods=["POST"])
def create_claim():
    uid, role = ctx()
    b = body()
    year_id = req_str(b, "program_year_id")
    period = req_str(b, "period_month")
    y, m = parse_month(period, "period_month")
    require_role(role, CC)
    year = store["program_years"].get(year_id)
    if year is None:
        raise ApiError("ERR_PROGRAM_YEAR_NOT_FOUND", "ProgramYear %s not found" % year_id, 404)
    if year["status"] != "OPEN":
        raise ApiError("ERR_PROGRAM_YEAR_NOT_OPEN",
                       "Claim creation requires an OPEN program year", 409)
    mstart = date(y, m, 1)
    mend = date(y, m, calendar.monthrange(y, m)[1])
    if mend < year["start_date"] or mstart > year["end_date"]:
        raise ApiError("ERR_PERIOD_OUTSIDE_YEAR",
                       "Claim period_month does not overlap the program year", 409)
    rec = new_record()
    rec.update({
        "program_year_id": year_id,
        "period_month": period,
        "submitted_by_user_id": None,
        "status": "OPEN",
    })
    store["claims"][rec["id"]] = rec
    return ok_object(ser_claim(rec), 201)


@bp.route("/f2s/reimbursement-claims", methods=["GET"])
def list_claims():
    ctx()
    return list_response(store["claims"].values(), ser_claim, {
        "program_year_id": "program_year_id", "status": "status",
        "period_month": "period_month",
    })


@bp.route("/f2s/reimbursement-claims/<rid>", methods=["GET"])
def get_claim(rid):
    ctx()
    rec = get_or_404("claims", rid, "ERR_CLAIM_NOT_FOUND")
    return ok_object(ser_claim(rec))


@bp.route("/f2s/reimbursement-claims/<rid>/lines", methods=["POST"])
def add_claim_line(rid):
    uid, role = ctx()
    b = body()
    invoice_id = req_str(b, "invoice_id")
    expected = req_int(b, "expected_claim_version")
    require_role(role, CC)
    claim = get_or_404("claims", rid, "ERR_CLAIM_NOT_FOUND")
    inv = store["invoices"].get(invoice_id)
    if inv is None:
        raise ApiError("ERR_INVOICE_NOT_FOUND", "Invoice %s not found" % invoice_id, 404)
    if claim["status"] != "OPEN":
        raise ApiError("ERR_CLAIM_NOT_OPEN", "line add requires claim OPEN", 409)
    if not inv["farm_compliant_at_delivery"]:
        raise ApiError("ERR_LINE_FARM_NONCOMPLIANT",
                       "Invoice snapshot farm_compliant_at_delivery is false", 422)
    dlv = store["deliveries"][inv["delivery_id"]]
    if dlv["delivery_date"].isoformat()[:7] != claim["period_month"]:
        raise ApiError("ERR_INVOICE_OUTSIDE_PERIOD",
                       "Invoice delivery month differs from claim period_month", 409)
    for l in store["claim_lines"].values():
        if l["invoice_id"] == invoice_id:
            raise ApiError("ERR_INVOICE_ALREADY_CLAIMED",
                           "Invoice already appears on a claim line", 409)
    ag = store["agreements"][inv["agreement_id"]]
    if not ag["local_eligible"]:
        raise ApiError("ERR_LINE_NOT_LOCAL",
                       "Invoice's agreement is not local_eligible; not grant-reimbursable",
                       409)
    if expected != claim["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_claim_version does not match the current claim version",
                       412)
    rec = new_record()
    rec.update({
        "claim_id": rid,
        "invoice_id": invoice_id,
        "claimed_amount_cents": inv["total_cents"],
        "audit_status": "PENDING",
        "disallowed_amount_cents": 0,
        "disallowance_reason": None,
    })
    store["claim_lines"][rec["id"]] = rec
    touch(claim)
    return ok_object(ser_claim_line(rec), 201)


@bp.route("/f2s/reimbursement-claims/<rid>/submit", methods=["POST"])
def submit_claim(rid):
    uid, role = ctx()
    require_role(role, CC)
    rec = get_or_404("claims", rid, "ERR_CLAIM_NOT_FOUND")
    if rec["status"] != "OPEN":
        raise ApiError("ERR_CLAIM_NOT_OPEN", "submit requires claim OPEN", 409)
    lines = claim_lines_of(rid)
    if len(lines) < 1:
        raise ApiError("ERR_CLAIM_EMPTY", "submit requires at least one claim line", 409)
    for l in lines:
        inv = store["invoices"][l["invoice_id"]]
        if inv.get("approved_by_user_id") is not None and inv["approved_by_user_id"] == uid:
            raise ApiError("ERR_SOD_VIOLATION",
                           "Claim submitter is the same user that approved an included "
                           "invoice", 403)
    rec["status"] = "SUBMITTED"
    rec["submitted_by_user_id"] = uid
    touch(rec)
    return ok_object(ser_claim(rec))


@bp.route("/f2s/reimbursement-claims/<rid>/start-review", methods=["POST"])
def start_review_claim(rid):
    uid, role = ctx()
    require_role(role, SGA)
    rec = get_or_404("claims", rid, "ERR_CLAIM_NOT_FOUND")
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_NOT_SUBMITTED", "start-review requires status SUBMITTED",
                       409)
    rec["status"] = "UNDER_REVIEW"
    touch(rec)
    return ok_object(ser_claim(rec))


@bp.route("/f2s/reimbursement-claims/<rid>/reconcile", methods=["POST"])
def reconcile_claim(rid):
    uid, role = ctx()
    require_role(role, SGA)
    rec = get_or_404("claims", rid, "ERR_CLAIM_NOT_FOUND")
    if rec["status"] not in ("AWARDED", "PARTIALLY_AWARDED"):
        raise ApiError("ERR_CLAIM_NOT_AWARDED",
                       "reconcile requires status AWARDED or PARTIALLY_AWARDED", 409)
    year = store["program_years"][rec["program_year_id"]]
    remaining = year["grant_award_cents"] - grant_drawn(year["id"])
    _, awarded, _, _ = claim_totals(rec)
    if awarded > remaining:
        raise ApiError("ERR_GRANT_EXHAUSTED",
                       "Claim total_awarded_cents exceeds the program year's "
                       "grant_remaining_cents", 402)
    rec["status"] = "RECONCILED"
    touch(rec)
    return ok_object(ser_claim(rec))


@bp.route("/f2s/reimbursement-claims/<rid>/reverse", methods=["POST"])
def reverse_claim(rid):
    uid, role = ctx()
    require_role(role, SGA)
    rec = get_or_404("claims", rid, "ERR_CLAIM_NOT_FOUND")
    if rec["status"] != "RECONCILED":
        raise ApiError("ERR_CLAIM_NOT_RECONCILED", "reverse requires status RECONCILED", 409)
    rec["status"] = "REVERSED"
    touch(rec)
    return ok_object(ser_claim(rec))


# ---------------------------------------------------------------------------
# ClaimLine
# ---------------------------------------------------------------------------

@bp.route("/f2s/claim-lines", methods=["GET"])
def list_claim_lines():
    ctx()
    return list_response(store["claim_lines"].values(), ser_claim_line, {
        "claim_id": "claim_id", "invoice_id": "invoice_id", "audit_status": "audit_status",
    })


@bp.route("/f2s/claim-lines/<rid>", methods=["GET"])
def get_claim_line(rid):
    ctx()
    rec = get_or_404("claim_lines", rid, "ERR_CLAIM_LINE_NOT_FOUND")
    return ok_object(ser_claim_line(rec))


def _maybe_close_claim(claim):
    lines = claim_lines_of(claim["id"])
    if any(l["audit_status"] == "PENDING" for l in lines):
        return
    awarded = sum(line_awarded(l) for l in lines)
    if all(l["audit_status"] == "ALLOWED" for l in lines):
        claim["status"] = "AWARDED"
    elif awarded > 0:
        claim["status"] = "PARTIALLY_AWARDED"
    else:
        claim["status"] = "REJECTED"
    touch(claim)


def _adjudication_gates(rec):
    claim = store["claims"][rec["claim_id"]]
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_CLAIM_NOT_UNDER_REVIEW",
                       "Line adjudication requires claim UNDER_REVIEW", 409)
    if rec["audit_status"] != "PENDING":
        raise ApiError("ERR_CLAIM_LINE_NOT_PENDING",
                       "allow/disallow requires line PENDING", 409)
    return claim


@bp.route("/f2s/claim-lines/<rid>/allow", methods=["POST"])
def allow_claim_line(rid):
    uid, role = ctx()
    require_role(role, SGA)
    rec = get_or_404("claim_lines", rid, "ERR_CLAIM_LINE_NOT_FOUND")
    claim = _adjudication_gates(rec)
    rec["audit_status"] = "ALLOWED"
    touch(rec)
    _maybe_close_claim(claim)
    return ok_object(ser_claim_line(rec))


@bp.route("/f2s/claim-lines/<rid>/disallow", methods=["POST"])
def disallow_claim_line(rid):
    uid, role = ctx()
    b = body()
    disallowed = req_int(b, "disallowed_amount_cents")
    reason = b.get("reason")
    if reason is None:
        reason = b.get("disallowance_reason")
    if not isinstance(reason, str) or reason == "":
        raise ApiError("ERR_INVALID_REQUEST",
                       "A reason is required when disallowing a claim line", 400)
    require_role(role, SGA)
    rec = get_or_404("claim_lines", rid, "ERR_CLAIM_LINE_NOT_FOUND")
    claim = _adjudication_gates(rec)
    if not (1 <= disallowed <= rec["claimed_amount_cents"]):
        raise ApiError("ERR_DISALLOWANCE_OUT_OF_RANGE",
                       "disallowed_amount_cents must be between 1 and "
                       "claimed_amount_cents", 422)
    rec["audit_status"] = "DISALLOWED"
    rec["disallowed_amount_cents"] = disallowed
    rec["disallowance_reason"] = reason
    touch(rec)
    _maybe_close_claim(claim)
    return ok_object(ser_claim_line(rec))


# ---------------------------------------------------------------------------
# SubstitutionRequest
# ---------------------------------------------------------------------------

@bp.route("/f2s/substitution-requests", methods=["POST"])
def create_substitution():
    uid, role = ctx()
    b = body()
    line_id = req_str(b, "forecast_line_id")
    sub_id = req_str(b, "substitute_product_id")
    quantity = req_int(b, "quantity", mn=1)
    reason = req_enum(b, "reason", {"SEASONALITY_GAP", "SUPPLY_SHORTFALL", "QUALITY_FAILURE"})
    require_role(role, DPA)
    line = store["forecast_lines"].get(line_id)
    if line is None:
        raise ApiError("ERR_FORECAST_LINE_NOT_FOUND",
                       "Forecast line %s not found" % line_id, 404)
    sub = store["products"].get(sub_id)
    if sub is None:
        raise ApiError("ERR_PRODUCT_NOT_FOUND", "Product %s not found" % sub_id, 404)
    year = store["program_years"][line["program_year_id"]]
    if year["status"] != "OPEN":
        raise ApiError("ERR_PROGRAM_YEAR_NOT_OPEN",
                       "Substitution creation requires an OPEN program year", 409)
    if sub_id == line["product_id"]:
        raise ApiError("ERR_SAME_PRODUCT_SUBSTITUTION",
                       "substitute_product_id equals the forecast line's product", 422)
    _, uncovered = line_coverage(line)
    if uncovered == 0:
        raise ApiError("ERR_NO_SEASONALITY_GAP",
                       "The forecast line has no uncovered quantity", 409)
    if quantity > uncovered:
        raise ApiError("ERR_SUBSTITUTION_EXCEEDS_GAP",
                       "quantity exceeds the forecast line's uncovered_quantity", 409)
    if not substitution_cap_check(line["program_year_id"], line["product_id"], quantity):
        raise ApiError("ERR_SUBSTITUTION_CAP_EXCEEDED",
                       "Approval would exceed the 20% product-year substitution cap", 409)
    rec = new_record()
    rec.update({
        "forecast_line_id": line_id,
        "substitute_product_id": sub_id,
        "quantity": quantity,
        "reason": reason,
        "status": "REQUESTED",
    })
    store["substitutions"][rec["id"]] = rec
    return ok_object(ser_substitution(rec), 201)


@bp.route("/f2s/substitution-requests", methods=["GET"])
def list_substitutions():
    ctx()
    return list_response(store["substitutions"].values(), ser_substitution, {
        "forecast_line_id": "forecast_line_id",
        "substitute_product_id": "substitute_product_id",
        "status": "status",
    })


@bp.route("/f2s/substitution-requests/<rid>", methods=["GET"])
def get_substitution(rid):
    ctx()
    rec = get_or_404("substitutions", rid, "ERR_SUBSTITUTION_NOT_FOUND")
    return ok_object(ser_substitution(rec))


@bp.route("/f2s/substitution-requests/<rid>/approve", methods=["POST"])
def approve_substitution(rid):
    uid, role = ctx()
    require_role(role, SGA)
    rec = get_or_404("substitutions", rid, "ERR_SUBSTITUTION_NOT_FOUND")
    if rec["status"] != "REQUESTED":
        raise ApiError("ERR_SUBSTITUTION_NOT_PENDING",
                       "approve requires status REQUESTED", 409)
    line = store["forecast_lines"][rec["forecast_line_id"]]
    if not substitution_cap_check(line["program_year_id"],
                                  line["product_id"], rec["quantity"]):
        raise ApiError("ERR_SUBSTITUTION_CAP_EXCEEDED",
                       "Approval would exceed the 20% product-year substitution cap", 409)
    rec["status"] = "APPROVED"
    touch(rec)
    return ok_object(ser_substitution(rec))


@bp.route("/f2s/substitution-requests/<rid>/deny", methods=["POST"])
def deny_substitution(rid):
    uid, role = ctx()
    require_role(role, SGA)
    rec = get_or_404("substitutions", rid, "ERR_SUBSTITUTION_NOT_FOUND")
    if rec["status"] != "REQUESTED":
        raise ApiError("ERR_SUBSTITUTION_NOT_PENDING", "deny requires status REQUESTED", 409)
    rec["status"] = "DENIED"
    touch(rec)
    return ok_object(ser_substitution(rec))


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.route("/f2s/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    uid, role = ctx()
    b = body()
    to = parse_iso8601(b.get("to_iso8601"), "to_iso8601") if b.get("to_iso8601") is not None \
        else None
    if to is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field: to_iso8601", 400)
    require_role(role, DPA)
    if to < clock_now():
        raise ApiError("ERR_CLOCK_REGRESSION",
                       "Cannot move the logical clock to an earlier instant", 400)
    set_clock(to)
    run_clock_sweeps()
    return ok_empty(200)
