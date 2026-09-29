"""Warranty claims filed with the OEM on the servicer's behalf."""

from db import db, base_row, fmt, now, parse_stored, touch, whole_days_between
from errors import ApiError
from flask import Blueprint
from middleware import authenticate
from response import created, ok, ok_list
from services import calc, flows, serialize
from validation import parse_body, pagination, q_str

bp = Blueprint("warranty", __name__)

ALL_ROLES = ("PlatformAdmin", "WarrantyAdmin", "CreditManager", "PricingAdmin",
             "BranchCounterRep", "Servicer")
WARRANTY_WRITERS = ("WarrantyAdmin", "PlatformAdmin")
CREDIT_WRITERS = ("CreditManager", "PlatformAdmin")
OUTCOMES = {"APPROVED", "DENIED", "INFO_REQUESTED"}
SHIPPED_STATUSES = ("SHIPPED", "RETURNED")


def _claim_or_404(claim_id):
    return flows.find(db.warranty_claims, claim_id, "ERR_WARRANTY_CLAIM_NOT_FOUND")


def _require_claim_status(claim, allowed):
    """Rule 15."""
    if claim["claim_status"] not in allowed:
        raise ApiError("ERR_CLAIM_STATE_INVALID",
                       "A claim in %s does not accept this operation"
                       % claim["claim_status"])


def _order_of(claim):
    line = db.order_lines.get(claim["order_line_id"])
    if line is None:
        return None, None
    return line, db.part_orders.get(line["part_order_id"])


@bp.post("/warranty-claims")
def create_claim():
    authenticate(WARRANTY_WRITERS)
    body = parse_body([
        ("servicer_account_id", "str", True),
        ("order_line_id", "str", True),
        ("defect_code", "str", True),
        ("appliance_model_number", "str", True),
    ])
    line = flows.line_or_404(body["order_line_id"])
    account = flows.account_or_404(body["servicer_account_id"])
    if line["line_status"] not in SHIPPED_STATUSES:
        raise ApiError("ERR_LINE_NOT_SHIPPED",
                       "A warranty claim may only target a shipped line")
    part = db.parts.get(line["resolved_part_id"])
    if part is None:
        raise ApiError("ERR_PART_NOT_FOUND", "The line's resolved part is missing")
    flows.check_oem_authorization(account, part)

    row = base_row()
    row.update({
        "servicer_account_id": account["id"],
        "order_line_id": line["id"],
        "oem_code": part["oem_code"],
        "defect_code": body["defect_code"],
        "appliance_model_number": body["appliance_model_number"],
        "claim_status": "DRAFT",
        "resubmission_count": 0,
        "submitted_at": None,
        "oem_reference": None,
        "claim_amount_cents": None,
        "credit_amount_cents": None,
    })
    db.warranty_claims[row["id"]] = row
    return created(serialize.warranty_claim(row))


@bp.post("/warranty-claims/<claim_id>/submit")
def submit_claim(claim_id):
    authenticate(WARRANTY_WRITERS)
    body = parse_body([("oem_reference", "str", False)])
    claim = _claim_or_404(claim_id)
    account = db.servicer_accounts.get(claim["servicer_account_id"])
    if account is None or account["account_status"] != "ACTIVE":
        raise ApiError("ERR_SERVICER_NOT_ACTIVE",
                       "The servicer account is not ACTIVE")
    _require_claim_status(claim, ("DRAFT",))

    # rule 25 precedes rule 35
    holds_cert = False
    for cert in flows.account_certs(account["id"]):
        if cert["oem_code"] == claim["oem_code"] and flows.cert_is_effective(cert):
            holds_cert = True
            break
    if not holds_cert:
        raise ApiError("ERR_TECHNICIAN_CERT_REQUIRED",
                       "An effective certification for OEM %s is required"
                       % claim["oem_code"])

    line, order = _order_of(claim)
    fulfilled_at = order.get("fulfilled_at") if order else None
    if fulfilled_at is None:
        raise ApiError("ERR_WARRANTY_PERIOD_EXPIRED",
                       "The order behind this claim was never fulfilled")
    elapsed = whole_days_between(parse_stored(fulfilled_at), now())
    if elapsed > calc.WARRANTY_CLAIM_WINDOW_DAYS:
        raise ApiError("ERR_WARRANTY_PERIOD_EXPIRED",
                       "%d whole days have elapsed since fulfillment, beyond the "
                       "%d-day warranty window"
                       % (elapsed, calc.WARRANTY_CLAIM_WINDOW_DAYS))

    claim["claim_status"] = "SUBMITTED"
    claim["submitted_at"] = fmt(now())
    if "oem_reference" in body:
        claim["oem_reference"] = body["oem_reference"]
    if claim["claim_amount_cents"] is None and line is not None:
        billable = line["quantity"] - (line["returned_units"] or 0)
        if billable < 0:
            billable = 0
        unit = line.get("invoiced_unit_price_cents") or 0
        claim["claim_amount_cents"] = unit * billable
    touch(claim)
    return ok(serialize.warranty_claim(claim))


@bp.post("/warranty-claims/<claim_id>/oem-response")
def record_oem_response(claim_id):
    authenticate(WARRANTY_WRITERS)
    body = parse_body([
        ("outcome", "enum", True, OUTCOMES),
        ("oem_reference", "str", False),
        ("oem_note", "str", False),
    ])
    claim = _claim_or_404(claim_id)
    _require_claim_status(claim, ("SUBMITTED",))
    if "oem_reference" in body:
        claim["oem_reference"] = body["oem_reference"]
    outcome = body["outcome"]
    if outcome == "APPROVED":
        claim["claim_status"] = "OEM_APPROVED"
    elif outcome == "DENIED":
        claim["claim_status"] = "OEM_DENIED"
    else:
        claim["claim_status"] = "OEM_INFO_REQUESTED"
    touch(claim)
    return ok(serialize.warranty_claim(claim))


@bp.post("/warranty-claims/<claim_id>/resubmit")
def resubmit_claim(claim_id):
    authenticate(WARRANTY_WRITERS)
    parse_body([("additional_info", "str", True)])
    claim = _claim_or_404(claim_id)
    _require_claim_status(claim, ("OEM_INFO_REQUESTED",))
    if claim["resubmission_count"] >= calc.MAX_RESUBMISSIONS:
        raise ApiError("ERR_RESUBMISSION_LIMIT_REACHED",
                       "This claim has already been resubmitted %d times"
                       % claim["resubmission_count"])
    claim["claim_status"] = "SUBMITTED"
    claim["resubmission_count"] = claim["resubmission_count"] + 1
    claim["submitted_at"] = fmt(now())
    touch(claim)
    return ok(serialize.warranty_claim(claim))


@bp.post("/warranty-claims/<claim_id>/credit")
def close_claim(claim_id):
    authenticate(CREDIT_WRITERS)
    parse_body([])
    claim = _claim_or_404(claim_id)
    _require_claim_status(claim, ("OEM_APPROVED", "OEM_DENIED"))
    if claim["claim_status"] == "OEM_APPROVED":
        claim["claim_status"] = "CREDITED"
        claim["credit_amount_cents"] = claim["claim_amount_cents"] or 0
        touch(claim)
        account = db.servicer_accounts.get(claim["servicer_account_id"])
        if account is not None:
            flows.sync_account(account)
    else:
        claim["claim_status"] = "VOID"
        claim["credit_amount_cents"] = 0
        touch(claim)
    return ok(serialize.warranty_claim(claim))


@bp.get("/warranty-claims")
def list_claims():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = flows.rows_sorted(db.warranty_claims)
    for field in ("servicer_account_id", "order_line_id", "claim_status",
                  "oem_code"):
        value = q_str(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = serialize.paginate(rows, limit, offset)
    return ok_list([serialize.warranty_claim(r) for r in page],
                   limit, offset, total)


@bp.get("/warranty-claims/<claim_id>")
def get_claim(claim_id):
    authenticate(ALL_ROLES)
    return ok(serialize.warranty_claim(_claim_or_404(claim_id)))
