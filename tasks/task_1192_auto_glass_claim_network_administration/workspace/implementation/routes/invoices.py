"""Invoice lifecycle: create (DRAFT), submit/resubmit, audit decisions, pay."""

from flask import Blueprint, request

from db import store, base_fields, touch, sorted_created, now_iso, now_dt
from errors import (
    ApiError,
    ERR_WORK_ORDER_NOT_FOUND,
    ERR_INVOICE_NOT_FOUND,
    ERR_RESOURCE_OWNERSHIP_MISMATCH,
    ERR_WORK_ORDER_NOT_COMPLETED,
    ERR_INVOICE_NOT_SUBMITTABLE,
    ERR_INVOICE_NOT_SUBMITTED,
    ERR_INVOICE_NOT_APPROVED,
    ERR_INVOICE_EMPTY,
    ERR_INVALID_REQUEST,
    ERR_SEGREGATION_OF_DUTIES_VIOLATION,
    ERR_AUDIT_INCOMPLETE,
)
from middleware import (
    get_context,
    body_json,
    pagination_params,
    paginate,
    ALL_ROLES,
    ROLE_SHOP_OPERATOR,
    ROLE_NETWORK_AUDITOR,
)
from response import success_object, success_list
from serialize import invoice_view, line_item_view
from services.pricing import (
    check_part_existence,
    price_and_build_lines,
    compute_totals,
    compute_oem_upcharge,
)
from services.scoring import record_approve_event

bp = Blueprint("invoices", __name__)

AUDIT_ACTIONS = {"APPROVE", "DISPUTE", "REJECT"}
APPROVED_ORIGINS = {"OEM", "AFTERMARKET"}


def _get_wo(wid):
    wo = store.work_orders.get(wid)
    if wo is None:
        raise ApiError(ERR_WORK_ORDER_NOT_FOUND, 404, "Work order does not exist")
    return wo


def _get_invoice(iid):
    invoice = store.invoices.get(iid)
    if invoice is None:
        raise ApiError(ERR_INVOICE_NOT_FOUND, 404, "Invoice does not exist")
    return invoice


def _invoice_lines(invoice_id):
    return sorted_created([l for l in store.invoice_lines.values() if l["invoice_id"] == invoice_id])


def _check_shop_ownership(wo, uid):
    if wo["shop_id"] != uid:
        raise ApiError(
            ERR_RESOURCE_OWNERSHIP_MISMATCH,
            403,
            "ShopOperator may act only on work orders whose shop_id matches their identity",
        )


def _regulation_for(claim):
    return store.state_regulations.get(store.state_reg_by_code.get(claim["incident_state_code"]))


def _create_line_records(invoice_id, priced_lines):
    records = []
    for fields in priced_lines:
        line = base_fields()
        line.update({"invoice_id": invoice_id})
        line.update(fields)
        store.invoice_lines[line["id"]] = line
        records.append(line)
    return records


def _parse_line_items(data, field_name="line_items"):
    items = data.get(field_name)
    if items is None:
        if field_name == "line_items":
            raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'line_items' is required")
        return None
    if not isinstance(items, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{field_name}' must be an array")
    return items


@bp.route("/work-orders/<wid>/invoices", methods=["POST"])
def create_invoice(wid):
    uid, _role = get_context([ROLE_SHOP_OPERATOR])
    wo = _get_wo(wid)
    _check_shop_ownership(wo, uid)
    data = body_json(required=True)
    line_items = _parse_line_items(data)
    # Priority 4: body resource references resolve before state checks.
    check_part_existence(line_items)
    if wo["status"] != "COMPLETED":
        raise ApiError(ERR_WORK_ORDER_NOT_COMPLETED, 409, "Invoice creation requires WorkOrder COMPLETED")
    claim = store.claims.get(wo["claim_id"])
    shop = store.shops.get(wo["shop_id"])
    regulation = _regulation_for(claim)
    priced = price_and_build_lines(line_items, shop, wo)
    submitted, tax = compute_totals(priced, regulation)

    invoice = base_fields()
    invoice.update(
        {
            "work_order_id": wid,
            "status": "DRAFT",
            "submitted_total_cents": submitted,
            "tax_amount_cents": tax,
            "approved_total_cents": 0,
            "adjustment_total_cents": submitted,
            "audited_by_user_id": None,
            "paid_at": None,
        }
    )
    store.invoices[invoice["id"]] = invoice
    _create_line_records(invoice["id"], priced)
    return success_object(invoice_view(invoice), status=201)


@bp.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    get_context(ALL_ROLES)
    return success_object(invoice_view(_get_invoice(iid)))


@bp.route("/work-orders/<wid>/invoices", methods=["GET"])
def list_wo_invoices(wid):
    get_context(ALL_ROLES)
    _get_wo(wid)
    limit, offset = pagination_params()
    items = sorted_created([i for i in store.invoices.values() if i["work_order_id"] == wid])
    page, total = paginate(items, limit, offset)
    return success_list([invoice_view(i) for i in page], limit, offset, total)


@bp.route("/invoices/<iid>/line-items", methods=["GET"])
def list_invoice_lines(iid):
    get_context(ALL_ROLES)
    _get_invoice(iid)
    limit, offset = pagination_params()
    items = _invoice_lines(iid)
    page, total = paginate(items, limit, offset)
    return success_list([line_item_view(l) for l in page], limit, offset, total)


@bp.route("/invoices/<iid>/submit", methods=["POST"])
def submit_invoice(iid):
    uid, _role = get_context([ROLE_SHOP_OPERATOR])
    invoice = _get_invoice(iid)
    wo = store.work_orders.get(invoice["work_order_id"])
    if wo is not None:
        _check_shop_ownership(wo, uid)
    data = body_json(required=False)
    revised = _parse_line_items(data, "revised_line_items")
    if revised is not None:
        check_part_existence(revised)
    if invoice["status"] not in ("DRAFT", "DISPUTED"):
        raise ApiError(
            ERR_INVOICE_NOT_SUBMITTABLE,
            409,
            "submit requires Invoice in {DRAFT, DISPUTED}",
        )
    was_draft = invoice["status"] == "DRAFT"
    claim = store.claims.get(wo["claim_id"]) if wo is not None else None
    shop = store.shops.get(wo["shop_id"]) if wo is not None else None
    regulation = _regulation_for(claim) if claim is not None else None

    if revised is not None:
        priced = price_and_build_lines(revised, shop, wo)
        # Replace line items wholesale.
        for line in [l for l in store.invoice_lines.values() if l["invoice_id"] == iid]:
            del store.invoice_lines[line["id"]]
        _create_line_records(iid, priced)
        submitted, tax = compute_totals(priced, regulation)
        invoice["submitted_total_cents"] = submitted
        invoice["tax_amount_cents"] = tax
        invoice["approved_total_cents"] = 0
        invoice["adjustment_total_cents"] = submitted
    else:
        lines = _invoice_lines(iid)
        if len(lines) == 0:
            raise ApiError(ERR_INVOICE_EMPTY, 409, "submit requires at least one line item")
        for line in lines:
            line["approved_amount_cents"] = None
            line["approved_origin"] = None
        invoice["approved_total_cents"] = 0
        invoice["adjustment_total_cents"] = invoice["submitted_total_cents"]

    if len(_invoice_lines(iid)) == 0:
        raise ApiError(ERR_INVOICE_EMPTY, 409, "submit requires at least one line item")

    invoice["status"] = "SUBMITTED"
    touch(invoice)
    if was_draft and claim is not None and claim["status"] == "WORK_COMPLETED":
        claim["status"] = "INVOICED"
        touch(claim)
    return success_object(invoice_view(invoice))


def _line_ref(entry, lines):
    for key in ("line_item_id", "invoice_line_item_id", "line_id", "id"):
        value = entry.get(key)
        if isinstance(value, str):
            return value
    index = entry.get("line_index")
    if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(lines):
        return lines[index]["id"]
    return None


@bp.route("/invoices/<iid>/audit-decisions", methods=["POST"])
def audit_decision(iid):
    uid, _role = get_context([ROLE_NETWORK_AUDITOR])
    invoice = _get_invoice(iid)
    if invoice["status"] != "SUBMITTED":
        raise ApiError(ERR_INVOICE_NOT_SUBMITTED, 409, "audit-decisions requires Invoice SUBMITTED")
    data = body_json(required=True)
    action = data.get("action")
    if not isinstance(action, str) or action not in AUDIT_ACTIONS:
        raise ApiError(ERR_INVALID_REQUEST, 400, "action must be one of APPROVE, DISPUTE, REJECT")
    wo = store.work_orders.get(invoice["work_order_id"])
    claim = store.claims.get(wo["claim_id"]) if wo is not None else None
    if claim is not None and uid == claim.get("coverage_verified_by_user_id"):
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES_VIOLATION,
            403,
            "The adjuster who verified this claim's coverage may not audit its invoices",
        )

    lines = _invoice_lines(iid)
    adjustments = {}
    if action in ("APPROVE", "DISPUTE"):
        adjustment_lines = data.get("adjustment_lines")
        if not isinstance(adjustment_lines, list):
            raise ApiError(
                ERR_AUDIT_INCOMPLETE,
                422,
                "adjustment_lines must cover every line item exactly once",
            )
        seen = set()
        for entry in adjustment_lines:
            if not isinstance(entry, dict):
                raise ApiError(ERR_AUDIT_INCOMPLETE, 422, "adjustment_lines entries must be objects")
            ref = _line_ref(entry, lines)
            amount = entry.get("approved_amount_cents")
            approved_origin = entry.get("approved_origin")
            if ref is None or ref in seen:
                raise ApiError(
                    ERR_AUDIT_INCOMPLETE,
                    422,
                    "adjustment_lines must cover every line item exactly once",
                )
            line = next((l for l in lines if l["id"] == ref), None)
            if line is None:
                raise ApiError(
                    ERR_AUDIT_INCOMPLETE,
                    422,
                    "adjustment_lines must cover every line item exactly once",
                )
            if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0 or amount > line["line_total_cents"]:
                raise ApiError(
                    ERR_AUDIT_INCOMPLETE,
                    422,
                    "approved_amount_cents must be an integer between 0 and the line total",
                )
            if approved_origin is not None and approved_origin not in APPROVED_ORIGINS:
                raise ApiError(ERR_INVALID_REQUEST, 400, "approved_origin must be OEM or AFTERMARKET")
            seen.add(ref)
            adjustments[ref] = (amount, approved_origin)
        if seen != {l["id"] for l in lines}:
            raise ApiError(
                ERR_AUDIT_INCOMPLETE,
                422,
                "adjustment_lines must cover every line item exactly once",
            )

    if action == "APPROVE":
        for line in lines:
            amount, approved_origin = adjustments[line["id"]]
            line["approved_amount_cents"] = amount
            if approved_origin is not None:
                line["approved_origin"] = approved_origin
            touch(line)
        invoice["approved_total_cents"] = sum(a for a, _ in adjustments.values()) + invoice["tax_amount_cents"]
        invoice["adjustment_total_cents"] = invoice["submitted_total_cents"] - invoice["approved_total_cents"]
        invoice["audited_by_user_id"] = uid
        invoice["status"] = "APPROVED"
        touch(invoice)
        if claim is not None:
            policy = store.policies.get(claim["policy_id"])
            updated_lines = _invoice_lines(iid)
            claim["oem_upcharge_cents"] = compute_oem_upcharge(updated_lines, policy)
            deductible = claim.get("deductible_applied_cents") or 0
            claim["customer_responsibility_cents"] = min(
                invoice["approved_total_cents"], deductible + claim["oem_upcharge_cents"]
            )
            claim["insurer_payment_cents"] = max(
                0, invoice["approved_total_cents"] - claim["customer_responsibility_cents"]
            )
            touch(claim)
        shop = store.shops.get(wo["shop_id"]) if wo is not None else None
        if shop is not None:
            record_approve_event(shop, invoice)
    elif action == "DISPUTE":
        for line in lines:
            amount, approved_origin = adjustments[line["id"]]
            line["approved_amount_cents"] = amount
            if approved_origin is not None:
                line["approved_origin"] = approved_origin
            touch(line)
        invoice["approved_total_cents"] = 0
        invoice["adjustment_total_cents"] = invoice["submitted_total_cents"]
        invoice["audited_by_user_id"] = uid
        invoice["status"] = "DISPUTED"
        touch(invoice)
    else:  # REJECT
        invoice["status"] = "REJECTED"
        touch(invoice)
        if claim is not None and claim["status"] == "INVOICED":
            claim["status"] = "DENIED"
            touch(claim)
    return success_object(invoice_view(invoice))


@bp.route("/invoices/<iid>/pay", methods=["POST"])
def pay_invoice(iid):
    get_context([ROLE_NETWORK_AUDITOR])
    invoice = _get_invoice(iid)
    if invoice["status"] != "APPROVED":
        raise ApiError(ERR_INVOICE_NOT_APPROVED, 409, "pay requires Invoice APPROVED")
    invoice["paid_at"] = now_iso()
    invoice["status"] = "PAID"
    touch(invoice)
    wo = store.work_orders.get(invoice["work_order_id"])
    claim = store.claims.get(wo["claim_id"]) if wo is not None else None
    if claim is not None and claim["status"] == "INVOICED":
        claim["status"] = "SETTLED"
        touch(claim)
    return success_object(invoice_view(invoice))
