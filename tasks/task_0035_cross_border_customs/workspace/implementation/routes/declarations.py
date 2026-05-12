"""Declaration + DeclarationLine endpoints (the bulk of the workflow)."""

from datetime import timedelta

from flask import Blueprint, g, request

from clock import now, to_iso, parse_iso
from db import DB, LOCK
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_DECLARATION_ALREADY_EXISTS,
    ERR_DECLARATION_INCOMPLETE,
    ERR_LINES_HAVE_PENDING_OVERRIDE,
    ERR_REWORK_LIMIT_EXCEEDED,
    ERR_HS_CODE_DEPRECATED,
    ERR_OVERRIDE_NOT_ALLOWED,
    ERR_IMPORTER_SUSPENDED,
    ERR_INSPECTION_PENDING,
    ERR_CHANNEL_NOT_GUARANTEE,
    forbidden,
    not_found,
)
from middleware import require_roles
from response import success_object, success_array
from services.calculations import compute_tax_totals
from services.cascades import cascade_order_on_declaration_status
from services.common import (
    check_occ,
    emit_audit,
    get_body,
    paginate,
    parse_pagination,
    sort_by_created_at,
    stamp_create,
    stamp_create_minimal,
    touch,
)
from services.serializers import serialize_declaration, serialize_line


bp = Blueprint("declarations", __name__)


def _get_declaration_or_404(declaration_id: str) -> dict:
    dec = DB.declarations.get(declaration_id)
    if dec is None:
        raise not_found("Declaration not found")
    return dec


def _can_user_view_declaration(dec: dict) -> bool:
    role = g.role
    if role in ("CustomsOfficer", "Auditor"):
        return True
    if role == "Declarant":
        return dec["declarant_id"] == g.user_id
    if role == "Importer":
        order = DB.orders.get(dec["order_id"])
        return order is not None and order["importer_id"] == g.user_id
    return False


# ---------------------------------------------------------------------------
# POST /declarations
# ---------------------------------------------------------------------------

@bp.route("/declarations", methods=["POST"])
@require_roles("Declarant")
def create_declaration():
    body = get_body()
    order_id = body.get("order_id")
    method = body.get("dutiable_value_method")

    if not isinstance(order_id, str):
        raise APIError(ERR_INVALID_REQUEST, "order_id required", 400)
    if method not in ("TRANSACTION_VALUE", "DEDUCTIVE_VALUE", "COMPUTED_VALUE"):
        raise APIError(ERR_INVALID_REQUEST, "Invalid dutiable_value_method", 400)

    with LOCK:
        order = DB.orders.get(order_id)
        if order is None:
            raise not_found("Order not found")

        # Importer must be ACTIVE
        importer = DB.importers.get(order["importer_id"])
        if importer is None:
            raise not_found("Importer not found")
        if importer["status"] != "ACTIVE":
            raise APIError(ERR_IMPORTER_SUSPENDED, "Importer is suspended", 409)

        # Uniqueness — at most one declaration per order in a non-superseded state.
        # PRD §3.3: existing declaration in any state other than "REJECTED-superseded"
        # blocks creation. We treat all existing declarations except those in REJECTED
        # as blocking. (REJECTED allows creation of a fresh declaration only if the
        # workflow chose to abandon — but the standard path is to resubmit the
        # existing REJECTED record.)
        for d in DB.declarations.values():
            if d["order_id"] == order_id and d["status"] != "REJECTED":
                raise APIError(ERR_DECLARATION_ALREADY_EXISTS,
                               "A declaration already exists for this order", 409)

        dec = {
            "order_id": order_id,
            "declarant_id": order["declarant_id"],
            "trade_mode": order["trade_mode"],
            "destination_country": order["destination_country"],
            "dutiable_value_method": method,
            "importer_id_card_number": body.get("importer_id_card_number"),
            "bonded_zone_code": body.get("bonded_zone_code"),
            "contract_number": body.get("contract_number"),
            "dutiable_value_cny_minor": None,
            "tariff_amount_cny_minor": None,
            "vat_amount_cny_minor": None,
            "consumption_tax_cny_minor": None,
            "total_tax_cny_minor": None,
            "tax_mode": None,
            "exchange_rate_date_used": None,
            "status": "DRAFT",
            "submission_count": 0,
            "query_id": None,
            "rejection_reason": None,
            "release_condition": None,
            "pickup_coordinated_at": None,
        }
        stamp_create(dec)
        DB.declarations[dec["id"]] = dec
        return success_object(serialize_declaration(dec), status=201)


# ---------------------------------------------------------------------------
# POST /declarations/{id}/lines
# ---------------------------------------------------------------------------

@bp.route("/declarations/<declaration_id>/lines", methods=["POST"])
@require_roles("Declarant")
def add_line(declaration_id):
    body = get_body()
    order_line_index = body.get("order_line_index")
    hs_code_id = body.get("hs_code_id")
    classification_source = body.get("classification_source")

    if not isinstance(order_line_index, int) or isinstance(order_line_index, bool) or order_line_index < 0:
        raise APIError(ERR_INVALID_REQUEST, "order_line_index must be non-negative integer", 400)
    if not isinstance(hs_code_id, str):
        raise APIError(ERR_INVALID_REQUEST, "hs_code_id required", 400)
    if classification_source not in ("AUTO_SUGGESTED", "MANUAL_OVERRIDE", "RULE_ENGINE"):
        raise APIError(ERR_INVALID_REQUEST, "Invalid classification_source", 400)

    with LOCK:
        dec = _get_declaration_or_404(declaration_id)
        if dec["status"] != "DRAFT":
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "Lines can only be added in DRAFT", 409)
        if dec["declarant_id"] != g.user_id:
            raise forbidden("Declarant does not own this declaration")

        hs = DB.hs_codes.get(hs_code_id)
        if hs is None:
            raise not_found("HsCode not found")
        if hs["status"] != "ACTIVE":
            raise APIError(ERR_HS_CODE_DEPRECATED, "HS code is deprecated", 409)

        order = DB.orders.get(dec["order_id"])
        line_items = (order or {}).get("line_items") or []
        if order_line_index >= len(line_items):
            raise APIError(ERR_INVALID_REQUEST, "order_line_index out of range", 400)

        override_status = "PENDING" if classification_source == "MANUAL_OVERRIDE" else "NOT_APPLICABLE"

        line = {
            "declaration_id": declaration_id,
            "order_line_index": int(order_line_index),
            "hs_code_id": hs_code_id,
            "classification_source": classification_source,
            "override_review_status": override_status,
            "declared_value_minor": None,
            "line_dutiable_value_cny_minor": None,
        }
        stamp_create_minimal(line)
        DB.declaration_lines[line["id"]] = line
        # Bump declaration's updated_at/version since it owns lines.
        touch(dec)
        return success_object(serialize_line(line), status=201)


# ---------------------------------------------------------------------------
# POST /declarations/{id}/lines/{line_id}/override
# ---------------------------------------------------------------------------

@bp.route("/declarations/<declaration_id>/lines/<line_id>/override", methods=["POST"])
@require_roles("CustomsOfficer")
def override_line(declaration_id, line_id):
    body = get_body()
    decision = body.get("decision")
    if decision not in ("APPROVE", "REJECT"):
        raise APIError(ERR_INVALID_REQUEST, "decision must be APPROVE or REJECT", 400)

    with LOCK:
        dec = _get_declaration_or_404(declaration_id)
        line = DB.declaration_lines.get(line_id)
        if line is None or line["declaration_id"] != declaration_id:
            raise not_found("DeclarationLine not found")
        if dec["status"] != "DRAFT":
            raise APIError(ERR_OVERRIDE_NOT_ALLOWED,
                           "Override allowed only in DRAFT", 409)
        if line["classification_source"] != "MANUAL_OVERRIDE":
            raise APIError(ERR_OVERRIDE_NOT_ALLOWED,
                           "Line is not a MANUAL_OVERRIDE", 409)
        line["override_review_status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
        touch(dec)
        return success_object(serialize_line(line), status=200)


# ---------------------------------------------------------------------------
# POST /declarations/{id}/submit
# ---------------------------------------------------------------------------

def _check_template_completeness(dec):
    tm = dec["trade_mode"]
    if tm == "B2C_DIRECT_MAIL":
        return bool(dec.get("importer_id_card_number"))
    if tm == "BONDED_WAREHOUSE":
        return bool(dec.get("bonded_zone_code"))
    if tm == "GENERAL_TRADE":
        return bool(dec.get("contract_number"))
    return False


def _do_submit(dec):
    """Compute taxes, increment submission_count, audit. Caller has the lock."""
    order = DB.orders.get(dec["order_id"])
    if order is None:
        raise not_found("Order not found")

    importer = DB.importers.get(order["importer_id"])
    declarant = DB.declarants.get(order["declarant_id"])

    # Priority 6 — importer status
    if importer is None or importer["status"] != "ACTIVE":
        raise APIError(ERR_IMPORTER_SUSPENDED, "Importer is suspended", 409)
    # Priority — declarant status
    if declarant is None or declarant["status"] != "ACTIVE":
        raise APIError(ERR_IMPORTER_SUSPENDED, "Declarant is suspended", 409)

    # Priority 8 — template completeness
    if not _check_template_completeness(dec):
        raise APIError(ERR_DECLARATION_INCOMPLETE,
                       "Required template field missing for trade_mode", 422)

    # Priority 9 — no PENDING/REJECTED lines
    lines = [ln for ln in DB.declaration_lines.values() if ln["declaration_id"] == dec["id"]]
    if not lines:
        raise APIError(ERR_DECLARATION_INCOMPLETE,
                       "Declaration has no lines", 422)
    for ln in lines:
        if ln["override_review_status"] in ("PENDING", "REJECTED"):
            raise APIError(ERR_LINES_HAVE_PENDING_OVERRIDE,
                           "Some lines are PENDING or REJECTED override review", 409)

    # Priority 10 — rework limit
    if int(dec.get("submission_count") or 0) >= 3:
        raise APIError(ERR_REWORK_LIMIT_EXCEEDED, "Rework limit exceeded", 409)

    submission_iso = to_iso(now())
    before = {"status": dec["status"], "total_tax_cny_minor": dec.get("total_tax_cny_minor")}
    totals = compute_tax_totals(dec, lines, order, submission_iso)
    dec.update(totals)
    dec["submission_count"] = int(dec.get("submission_count") or 0) + 1
    if dec["status"] == "REJECTED":
        dec["rejection_reason"] = None
    dec["status"] = "SUBMITTED"
    touch(dec)

    after = {"status": "SUBMITTED", "total_tax_cny_minor": dec["total_tax_cny_minor"]}
    emit_audit("DECLARATION", dec["id"], "DECLARATION_STATUS_CHANGE",
               before_value=before, after_value=after)
    emit_audit("DECLARATION", dec["id"], "TAX_RECOMPUTED",
               before_value={"total_tax_cny_minor": before["total_tax_cny_minor"]},
               after_value={"total_tax_cny_minor": dec["total_tax_cny_minor"]})
    emit_audit("DECLARATION", dec["id"], "EXTERNAL_SYNC",
               before_value={},
               after_value={"external_system": "CUSTOMS_SINGLE_WINDOW_ACK"})


@bp.route("/declarations/<declaration_id>/submit", methods=["POST"])
@require_roles("Declarant")
def submit_declaration(declaration_id):
    body = get_body()
    with LOCK:
        dec = _get_declaration_or_404(declaration_id)
        if dec["declarant_id"] != g.user_id:
            raise forbidden("Declarant does not own this declaration")
        if dec["status"] not in ("DRAFT", "REJECTED"):
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "Submit allowed only in DRAFT or REJECTED", 409)
        check_occ(dec, body)
        _do_submit(dec)
        return success_object(serialize_declaration(dec), status=200)


# ---------------------------------------------------------------------------
# POST /declarations/{id}/start_review
# ---------------------------------------------------------------------------

@bp.route("/declarations/<declaration_id>/start_review", methods=["POST"])
@require_roles("CustomsOfficer")
def start_review(declaration_id):
    body = get_body()
    with LOCK:
        dec = _get_declaration_or_404(declaration_id)
        if dec["status"] != "SUBMITTED":
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "start_review only from SUBMITTED", 409)
        check_occ(dec, body)
        before = {"status": "SUBMITTED"}
        dec["status"] = "UNDER_REVIEW"
        touch(dec)
        emit_audit("DECLARATION", dec["id"], "DECLARATION_STATUS_CHANGE",
                   before_value=before, after_value={"status": "UNDER_REVIEW"})
        return success_object(serialize_declaration(dec), status=200)


# ---------------------------------------------------------------------------
# POST /declarations/{id}/queries
# ---------------------------------------------------------------------------

@bp.route("/declarations/<declaration_id>/queries", methods=["POST"])
@require_roles("CustomsOfficer")
def open_query(declaration_id):
    body = get_body()
    question = body.get("question")
    required_documents = body.get("required_documents")
    if not isinstance(question, str):
        raise APIError(ERR_INVALID_REQUEST, "question required", 400)
    if not isinstance(required_documents, list):
        raise APIError(ERR_INVALID_REQUEST, "required_documents must be array", 400)

    with LOCK:
        dec = _get_declaration_or_404(declaration_id)
        if dec["status"] != "UNDER_REVIEW":
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "Queries can only be opened from UNDER_REVIEW", 409)
        # Block if any SCHEDULED inspection exists for the declaration
        for ap in DB.inspections.values():
            if ap["declaration_id"] == declaration_id and ap["status"] == "SCHEDULED":
                raise APIError(ERR_INSPECTION_PENDING,
                               "An inspection is scheduled; cannot open query", 409)

        q = {
            "declaration_id": declaration_id,
            "question": question,
            "required_documents": list(required_documents),
            "response_text": None,
            "response_documents": None,
            "status": "OPEN",
        }
        stamp_create(q)
        DB.queries[q["id"]] = q
        before = {"status": "UNDER_REVIEW", "query_id": dec.get("query_id")}
        dec["query_id"] = q["id"]
        dec["status"] = "QUERIED"
        touch(dec)
        emit_audit("DECLARATION", dec["id"], "DECLARATION_STATUS_CHANGE",
                   before_value=before, after_value={"status": "QUERIED", "query_id": q["id"]})
        from services.serializers import serialize_query
        return success_object(serialize_query(q), status=201)


# ---------------------------------------------------------------------------
# POST /declarations/{id}/inspection_appointments
# ---------------------------------------------------------------------------

@bp.route("/declarations/<declaration_id>/inspection_appointments", methods=["POST"])
@require_roles("CustomsOfficer")
def schedule_inspection(declaration_id):
    from errors import ERR_INSPECTION_SLOT_TAKEN
    body = get_body()
    scheduled_at = body.get("scheduled_at")
    bay_code = body.get("bay_code")
    if not isinstance(scheduled_at, str):
        raise APIError(ERR_INVALID_REQUEST, "scheduled_at required", 400)
    if not isinstance(bay_code, str):
        raise APIError(ERR_INVALID_REQUEST, "bay_code required", 400)

    new_start = parse_iso(scheduled_at)
    new_end = new_start + timedelta(minutes=60)

    with LOCK:
        dec = _get_declaration_or_404(declaration_id)
        # Inspection generally legal during UNDER_REVIEW or QUERIED; let it through
        # without enforcing strict status — overlap check is the real guard.
        if dec["status"] not in ("UNDER_REVIEW", "SUBMITTED", "QUERIED"):
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "Cannot schedule inspection in current state", 409)
        for ap in DB.inspections.values():
            if ap["bay_code"] != bay_code:
                continue
            if ap["status"] != "SCHEDULED":
                continue
            ex_start = parse_iso(ap["scheduled_at"])
            ex_end = ex_start + timedelta(minutes=60)
            # overlap if new_start < ex_end and ex_start < new_end
            if new_start < ex_end and ex_start < new_end:
                raise APIError(ERR_INSPECTION_SLOT_TAKEN,
                               "Bay-time slot conflicts with another scheduled inspection",
                               409)
        ap = {
            "declaration_id": declaration_id,
            "scheduled_at": scheduled_at,
            "bay_code": bay_code,
            "status": "SCHEDULED",
        }
        stamp_create_minimal(ap)
        DB.inspections[ap["id"]] = ap
        from services.serializers import serialize_inspection
        return success_object(serialize_inspection(ap), status=201)


# ---------------------------------------------------------------------------
# POST /declarations/{id}/reject
# ---------------------------------------------------------------------------

@bp.route("/declarations/<declaration_id>/reject", methods=["POST"])
@require_roles("CustomsOfficer")
def reject_declaration(declaration_id):
    body = get_body()
    rejection_reason = body.get("rejection_reason")
    if not isinstance(rejection_reason, str) or rejection_reason.strip() == "":
        raise APIError(ERR_INVALID_REQUEST, "rejection_reason required", 400)

    with LOCK:
        dec = _get_declaration_or_404(declaration_id)
        if dec["status"] != "UNDER_REVIEW":
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "Reject only from UNDER_REVIEW", 409)
        check_occ(dec, body)
        before = {"status": "UNDER_REVIEW"}
        dec["status"] = "REJECTED"
        dec["rejection_reason"] = rejection_reason
        touch(dec)
        emit_audit("DECLARATION", dec["id"], "DECLARATION_STATUS_CHANGE",
                   before_value=before, after_value={"status": "REJECTED",
                                                     "rejection_reason": rejection_reason})
        return success_object(serialize_declaration(dec), status=200)


# ---------------------------------------------------------------------------
# POST /declarations/{id}/approve
# ---------------------------------------------------------------------------

@bp.route("/declarations/<declaration_id>/approve", methods=["POST"])
@require_roles("CustomsOfficer")
def approve_declaration(declaration_id):
    body = get_body()
    with LOCK:
        dec = _get_declaration_or_404(declaration_id)
        if dec["status"] != "UNDER_REVIEW":
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "Approve only from UNDER_REVIEW", 409)
        if dec.get("query_id"):
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "Cannot approve while a query is open", 409)
        for ap in DB.inspections.values():
            if ap["declaration_id"] == declaration_id and ap["status"] == "SCHEDULED":
                raise APIError(ERR_INSPECTION_PENDING,
                               "Pending inspection must be completed first", 409)
        check_occ(dec, body)

        before = {"status": "UNDER_REVIEW"}
        dec["status"] = "APPROVED"
        touch(dec)

        # PaymentNotice creation — amount snapshot from declaration
        due_at = to_iso(now() + timedelta(hours=168))
        pn = {
            "declaration_id": dec["id"],
            "amount_cny_minor": int(dec.get("total_tax_cny_minor") or 0),
            "due_at": due_at,
            "payment_channel": None,
            "voucher_url": None,
            "status": "PENDING",
            "idempotency_key": None,
        }
        stamp_create(pn)
        DB.payment_notices[pn["id"]] = pn

        # Order cascade
        order = DB.orders.get(dec["order_id"])
        if order is not None:
            cascade_order_on_declaration_status(order, dec, "UNDER_REVIEW", "APPROVED")

        emit_audit("DECLARATION", dec["id"], "DECLARATION_STATUS_CHANGE",
                   before_value=before, after_value={"status": "APPROVED",
                                                     "payment_notice_id": pn["id"]})
        return success_object(serialize_declaration(dec), status=200)


# ---------------------------------------------------------------------------
# POST /declarations/{id}/conditional_release
# ---------------------------------------------------------------------------

@bp.route("/declarations/<declaration_id>/conditional_release", methods=["POST"])
@require_roles("CustomsOfficer")
def conditional_release(declaration_id):
    body = get_body()
    with LOCK:
        dec = _get_declaration_or_404(declaration_id)
        if dec["status"] != "APPROVED":
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "Conditional release only from APPROVED", 409)
        # Find the linked payment notice
        pn = None
        for n in DB.payment_notices.values():
            if n["declaration_id"] == declaration_id:
                pn = n
                break
        if pn is None or pn.get("payment_channel") != "GUARANTEE_DEDUCTION":
            raise APIError(ERR_CHANNEL_NOT_GUARANTEE,
                           "Conditional release requires GUARANTEE_DEDUCTION channel", 409)
        check_occ(dec, body)
        before = {"status": "APPROVED"}
        dec["status"] = "CONDITIONALLY_RELEASED"
        dec["release_condition"] = "guarantee_deposit_required"
        touch(dec)

        order = DB.orders.get(dec["order_id"])
        if order is not None:
            cascade_order_on_declaration_status(order, dec, "APPROVED", "CONDITIONALLY_RELEASED")
        emit_audit("DECLARATION", dec["id"], "DECLARATION_STATUS_CHANGE",
                   before_value=before, after_value={"status": "CONDITIONALLY_RELEASED"})
        return success_object(serialize_declaration(dec), status=200)


# ---------------------------------------------------------------------------
# POST /declarations/{id}/amend
# ---------------------------------------------------------------------------

@bp.route("/declarations/<declaration_id>/amend", methods=["POST"])
@require_roles("Declarant")
def amend_declaration(declaration_id):
    body = get_body()
    lines_edits = body.get("lines") or []
    if not isinstance(lines_edits, list):
        raise APIError(ERR_INVALID_REQUEST, "lines must be array", 400)

    with LOCK:
        dec = _get_declaration_or_404(declaration_id)
        if dec["status"] != "RELEASED":
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "Amend only from RELEASED", 409)
        if dec["declarant_id"] != g.user_id:
            raise forbidden("Declarant does not own this declaration")

        # PaymentNotice must be PAID
        pn = None
        for n in DB.payment_notices.values():
            if n["declaration_id"] == declaration_id:
                pn = n
                break
        if pn is None or pn["status"] != "PAID":
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "PaymentNotice must be PAID for amendment", 409)
        # No EXECUTED Refund
        for rf in DB.refunds.values():
            if rf["declaration_id"] == declaration_id and rf["status"] == "EXECUTED":
                raise APIError(ERR_INVALID_STATE_TRANSITION,
                               "An EXECUTED refund exists", 409)
        check_occ(dec, body)

        # Apply line edits
        for edit in lines_edits:
            if not isinstance(edit, dict):
                continue
            line_id = edit.get("line_id")
            if line_id is None:
                continue
            line = DB.declaration_lines.get(line_id)
            if line is None or line["declaration_id"] != declaration_id:
                raise not_found("DeclarationLine not found")
            if "hs_code_id" in edit and edit["hs_code_id"] is not None:
                new_hs = DB.hs_codes.get(edit["hs_code_id"])
                if new_hs is None:
                    raise not_found("HsCode not found")
                # Note: amendment does not require ACTIVE status (PRD only blocks
                # adding new lines to a fresh declaration with deprecated codes).
                line["hs_code_id"] = edit["hs_code_id"]
        if "dutiable_value_method" in body and body["dutiable_value_method"] is not None:
            method = body["dutiable_value_method"]
            if method not in ("TRANSACTION_VALUE", "DEDUCTIVE_VALUE", "COMPUTED_VALUE"):
                raise APIError(ERR_INVALID_REQUEST, "Invalid dutiable_value_method", 400)
            dec["dutiable_value_method"] = method

        order = DB.orders.get(dec["order_id"])
        lines = [ln for ln in DB.declaration_lines.values() if ln["declaration_id"] == dec["id"]]
        submission_iso = to_iso(now())
        before_total = dec.get("total_tax_cny_minor")
        totals = compute_tax_totals(dec, lines, order, submission_iso)
        dec.update(totals)
        before = {"status": "RELEASED"}
        dec["status"] = "AMENDED"
        touch(dec)

        emit_audit("DECLARATION", dec["id"], "DECLARATION_FIELD_CHANGE",
                   before_value=before, after_value={"status": "AMENDED"})
        emit_audit("DECLARATION", dec["id"], "TAX_RECOMPUTED",
                   before_value={"total_tax_cny_minor": before_total},
                   after_value={"total_tax_cny_minor": dec["total_tax_cny_minor"]})
        return success_object(serialize_declaration(dec), status=200)


# ---------------------------------------------------------------------------
# POST /declarations/{id}/finalize_amendment
# ---------------------------------------------------------------------------

@bp.route("/declarations/<declaration_id>/finalize_amendment", methods=["POST"])
@require_roles("CustomsOfficer")
def finalize_amendment(declaration_id):
    body = get_body()
    with LOCK:
        dec = _get_declaration_or_404(declaration_id)
        if dec["status"] != "AMENDED":
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "Finalize only from AMENDED", 409)
        check_occ(dec, body)
        before = {"status": "AMENDED"}
        dec["status"] = "RELEASED"
        touch(dec)
        emit_audit("DECLARATION", dec["id"], "DECLARATION_STATUS_CHANGE",
                   before_value=before, after_value={"status": "RELEASED"})
        return success_object(serialize_declaration(dec), status=200)


# ---------------------------------------------------------------------------
# GET /declarations/{id}
# ---------------------------------------------------------------------------

@bp.route("/declarations/<declaration_id>", methods=["GET"])
@require_roles("Declarant", "CustomsOfficer", "Importer", "Auditor")
def get_declaration(declaration_id):
    dec = _get_declaration_or_404(declaration_id)
    if not _can_user_view_declaration(dec):
        raise forbidden("You cannot view this declaration")
    return success_object(serialize_declaration(dec), status=200)


# ---------------------------------------------------------------------------
# GET /declarations
# ---------------------------------------------------------------------------

@bp.route("/declarations", methods=["GET"])
@require_roles("Declarant", "CustomsOfficer", "Auditor")
def list_declarations():
    limit, offset = parse_pagination()
    importer_id = request.args.get("importer_id")
    declarant_id = request.args.get("declarant_id")
    status = request.args.get("status")
    trade_mode = request.args.get("trade_mode")

    items = list(DB.declarations.values())
    if status:
        items = [d for d in items if d["status"] == status]
    if trade_mode:
        items = [d for d in items if d["trade_mode"] == trade_mode]
    if declarant_id:
        items = [d for d in items if d["declarant_id"] == declarant_id]
    if importer_id:
        importer_decs = []
        for d in items:
            order = DB.orders.get(d["order_id"])
            if order and order["importer_id"] == importer_id:
                importer_decs.append(d)
        items = importer_decs

    # Role visibility filter
    if g.role == "Declarant":
        items = [d for d in items if d["declarant_id"] == g.user_id]

    items = sort_by_created_at(items)
    sliced, total, has_more = paginate(items, limit, offset)
    return success_array([serialize_declaration(d) for d in sliced],
                         limit=limit, offset=offset, total_count=total, has_more=has_more)
