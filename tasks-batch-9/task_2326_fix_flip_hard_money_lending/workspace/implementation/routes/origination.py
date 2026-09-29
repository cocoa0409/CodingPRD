"""Sponsor, property, contractor, application and scope-line endpoints."""

from flask import Blueprint

import calc
import serialize as ser
import services as svc
from core import (
    ROLE_BORROWER, ROLE_CONTRACTOR, ROLE_CREDIT_COMMITTEE, ROLE_DRAW_INSPECTOR,
    ROLE_LOAN_OFFICER, ROLE_LOAN_SERVICER, ROLE_PLATFORM_ADMIN,
    ApiError, authenticate, caller_id, caller_role, clock_instant, conflict, db,
    f_bool, f_date, f_enum, f_int, f_str, invalid, json_body, new_record, ok,
    ok_list, paginate, q_enum, q_str, require_borrower_owner,
    require_contractor_owner, touch,
)

bp = Blueprint("origination", __name__)

APPLICATION_STATUSES = ("DRAFT", "SIZED", "APPROVED", "DECLINED", "CLOSED", "WITHDRAWN")
SCOPE_LINE_STATUSES = ("PROPOSED", "REVISION_REQUESTED", "APPROVED", "REJECTED",
                       "FULLY_RELEASED", "VOID")
WAIVER_STATUSES = ("COLLECTED", "DISPUTED")


# ---------------------------------------------------------------------------
# Borrowers
# ---------------------------------------------------------------------------
@bp.post("/borrowers")
def create_borrower():
    authenticate((ROLE_LOAN_OFFICER, ROLE_PLATFORM_ADMIN))
    body = json_body()
    legal_entity_name = f_str(body, "legal_entity_name")
    entity_type = f_enum(body, "entity_type", calc.ENTITY_TYPES)
    guarantor_name = f_str(body, "guarantor_name")
    flips_last_24mo = f_int(body, "flips_last_24mo", minimum=0)
    flips_lifetime = f_int(body, "flips_lifetime", minimum=0)
    credit_score = f_int(body, "credit_score", minimum=300, maximum=850)
    liquidity_cents = f_int(body, "liquidity_cents", minimum=0)
    prior_default_count = f_int(body, "prior_default_count", minimum=0)
    declared_target_loan_cents = f_int(body, "declared_target_loan_cents", minimum=1)
    if flips_last_24mo > flips_lifetime:
        raise invalid("flips_last_24mo may not exceed flips_lifetime.")

    rec = new_record()
    rec.update({
        "legal_entity_name": legal_entity_name,
        "entity_type": entity_type,
        "guarantor_name": guarantor_name,
        "flips_last_24mo": flips_last_24mo,
        "flips_lifetime": flips_lifetime,
        "credit_score": credit_score,
        "liquidity_cents": liquidity_cents,
        "prior_default_count": prior_default_count,
        "declared_target_loan_cents": declared_target_loan_cents,
        "intake_experience_score": None,
        "recertified_experience_score": None,
        "recertified_at": None,
        "guarantee_status": "PENDING",
        "guarantee_effective_date": None,
        "status": "PROSPECT",
        "suspension_reason": None,
    })
    rec["intake_experience_score"] = calc.intake_experience_score(rec)
    db.borrowers[rec["id"]] = rec
    return ok(ser.borrower_out(rec), 201)


@bp.get("/borrowers/<rec_id>")
def read_borrower(rec_id):
    authenticate((ROLE_LOAN_OFFICER, ROLE_CREDIT_COMMITTEE, ROLE_LOAN_SERVICER,
                  ROLE_BORROWER, ROLE_PLATFORM_ADMIN))
    borrower = ser.find_borrower(rec_id)
    require_borrower_owner(borrower["id"])
    return ok(ser.borrower_out(borrower))


@bp.post("/borrowers/<rec_id>/status")
def borrower_status(rec_id):
    authenticate((ROLE_CREDIT_COMMITTEE, ROLE_PLATFORM_ADMIN))
    body = json_body()
    action = f_enum(body, "action", ("APPROVE_SPONSOR", "RECERTIFY", "SUSPEND", "REINSTATE"))
    f_str(body, "note", required=False)
    borrower = ser.find_borrower(rec_id)

    if action == "APPROVE_SPONSOR":
        if borrower["status"] != "PROSPECT":
            raise conflict("ERR_BORROWER_STATE_INVALID",
                           "Only a PROSPECT sponsor can be approved.")
        if borrower["entity_type"] == "SOLE_PROP":
            raise conflict("ERR_ENTITY_TYPE_NOT_ELIGIBLE",
                           "A SOLE_PROP entity cannot borrow on an entity-based loan.")
        if borrower["guarantee_status"] != "EXECUTED":
            raise conflict("ERR_GUARANTEE_NOT_EXECUTED",
                           "The personal guarantee has not been executed.")
        if calc.experience_tier(borrower) == "TIER_D":
            raise conflict("ERR_BORROWER_NOT_ELIGIBLE",
                           "The sponsor's experience tier is TIER_D.")
        borrower["status"] = "APPROVED_SPONSOR"
        touch(borrower)

    elif action == "RECERTIFY":
        if borrower["status"] != "APPROVED_SPONSOR":
            raise conflict("ERR_BORROWER_STATE_INVALID",
                           "Only an APPROVED_SPONSOR can be recertified.")
        if borrower["guarantee_status"] != "EXECUTED":
            raise conflict("ERR_GUARANTEE_NOT_EXECUTED",
                           "The personal guarantee has not been executed.")
        score = calc.recert_experience_score(borrower)
        borrower["recertified_experience_score"] = score
        borrower["recertified_at"] = clock_instant()
        if score < calc.TIER_C_MIN:
            svc.suspend_borrower(borrower, "RECERT_BELOW_FLOOR")
        else:
            touch(borrower)

    elif action == "SUSPEND":
        if borrower["status"] != "APPROVED_SPONSOR":
            raise conflict("ERR_BORROWER_STATE_INVALID",
                           "Only an APPROVED_SPONSOR can be suspended.")
        svc.suspend_borrower(borrower, "ADMIN_SUSPENSION")

    else:  # REINSTATE
        if borrower["status"] != "SUSPENDED":
            raise conflict("ERR_BORROWER_STATE_INVALID",
                           "Only a SUSPENDED sponsor can be reinstated.")
        for loan in ser.borrower_loans(borrower["id"]):
            if loan["payment_status"] in ("DEFAULT", "CHARGED_OFF"):
                raise conflict("ERR_BORROWER_NOT_ELIGIBLE",
                               "A loan of this sponsor is in DEFAULT or CHARGED_OFF.")
        if calc.experience_tier(borrower) == "TIER_D":
            raise conflict("ERR_BORROWER_NOT_ELIGIBLE",
                           "The sponsor's experience tier is TIER_D.")
        borrower["status"] = "APPROVED_SPONSOR"
        borrower["suspension_reason"] = None
        touch(borrower)

    return ok(ser.borrower_out(borrower))


@bp.post("/borrowers/<rec_id>/guarantee")
def borrower_guarantee(rec_id):
    authenticate((ROLE_LOAN_OFFICER, ROLE_BORROWER, ROLE_PLATFORM_ADMIN))
    body = json_body()
    guarantor_name = f_str(body, "guarantor_name")
    f_str(body, "signature_ref")
    effective_date = f_date(body, "effective_date")
    borrower = ser.find_borrower(rec_id)
    require_borrower_owner(borrower["id"])
    borrower["guarantor_name"] = guarantor_name
    borrower["guarantee_status"] = "EXECUTED"
    borrower["guarantee_effective_date"] = effective_date
    touch(borrower)
    return ok(ser.borrower_out(borrower))


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------
@bp.post("/properties")
def create_property():
    authenticate((ROLE_LOAN_OFFICER, ROLE_PLATFORM_ADMIN))
    body = json_body()
    rec = new_record()
    rec.update({
        "address_line": f_str(body, "address_line"),
        "county_code": f_str(body, "county_code"),
        "purchase_price_cents": f_int(body, "purchase_price_cents", minimum=1),
        "as_is_value_cents": f_int(body, "as_is_value_cents", minimum=1),
        "arv_cents": f_int(body, "arv_cents", minimum=1),
        "appraisal_date": f_date(body, "appraisal_date"),
        "status": "UNDER_CONTRACT",
        "valuation_revision_count": 0,
    })
    db.properties[rec["id"]] = rec
    return ok(ser.property_out(rec), 201)


@bp.get("/properties/<rec_id>")
def read_property(rec_id):
    authenticate((ROLE_LOAN_OFFICER, ROLE_CREDIT_COMMITTEE, ROLE_LOAN_SERVICER,
                  ROLE_DRAW_INSPECTOR, ROLE_PLATFORM_ADMIN))
    return ok(ser.property_out(ser.find_property(rec_id)))


@bp.patch("/properties/<rec_id>/valuation")
def revise_valuation(rec_id):
    authenticate((ROLE_LOAN_OFFICER, ROLE_PLATFORM_ADMIN))
    body = json_body()
    appraisal_date = f_date(body, "appraisal_date")
    arv_cents = f_int(body, "arv_cents", required=False, minimum=1)
    as_is_value_cents = f_int(body, "as_is_value_cents", required=False, minimum=1)
    prop = ser.find_property(rec_id)

    prop["appraisal_date"] = appraisal_date
    if arv_cents is not None:
        prop["arv_cents"] = arv_cents
    if as_is_value_cents is not None:
        prop["as_is_value_cents"] = as_is_value_cents
    prop["valuation_revision_count"] += 1
    touch(prop)

    for app in db.applications.values():
        if app["property_id"] == prop["id"] and app["status"] == "SIZED":
            app["_sizing_stale"] = True
            touch(app)
    return ok(ser.property_out(prop))


# ---------------------------------------------------------------------------
# Contractors
# ---------------------------------------------------------------------------
@bp.post("/contractors")
def create_contractor():
    authenticate((ROLE_LOAN_OFFICER, ROLE_PLATFORM_ADMIN))
    body = json_body()
    rec = new_record()
    rec.update({
        "business_name": f_str(body, "business_name"),
        "license_number": f_str(body, "license_number"),
        "license_expires_on": f_date(body, "license_expires_on"),
        "w9_on_file": f_bool(body, "w9_on_file"),
        "joint_check_required": f_bool(body, "joint_check_required"),
    })
    db.contractors[rec["id"]] = rec
    return ok(ser.contractor_out(rec), 201)


@bp.get("/contractors/<rec_id>")
def read_contractor(rec_id):
    authenticate((ROLE_LOAN_OFFICER, ROLE_LOAN_SERVICER, ROLE_CONTRACTOR, ROLE_PLATFORM_ADMIN))
    contractor = ser.find_contractor(rec_id)
    require_contractor_owner(contractor["id"])
    return ok(ser.contractor_out(contractor))


@bp.get("/contractors/<rec_id>/rehab-line-items")
def list_contractor_lines(rec_id):
    authenticate((ROLE_LOAN_OFFICER, ROLE_LOAN_SERVICER, ROLE_CONTRACTOR, ROLE_PLATFORM_ADMIN))
    status = q_enum("status", SCOPE_LINE_STATUSES)
    contractor = ser.find_contractor(rec_id)
    require_contractor_owner(contractor["id"])
    rows = [l for l in db.rehab_line_items.values() if l["contractor_id"] == contractor["id"]]
    if status is not None:
        rows = [l for l in rows if l["status"] == status]
    items, meta = paginate(rows, ser.rehab_line_item_out)
    return ok_list(items, meta)


@bp.get("/contractors/<rec_id>/lien-waivers")
def list_contractor_waivers(rec_id):
    authenticate((ROLE_LOAN_OFFICER, ROLE_LOAN_SERVICER, ROLE_CONTRACTOR, ROLE_PLATFORM_ADMIN))
    status = q_enum("status", WAIVER_STATUSES)
    contractor = ser.find_contractor(rec_id)
    require_contractor_owner(contractor["id"])
    rows = [w for w in db.lien_waivers.values() if w["contractor_id"] == contractor["id"]]
    if status is not None:
        rows = [w for w in rows if w["status"] == status]
    items, meta = paginate(rows, ser.lien_waiver_out)
    return ok_list(items, meta)


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
@bp.post("/applications")
def create_application():
    authenticate((ROLE_LOAN_OFFICER, ROLE_PLATFORM_ADMIN))
    body = json_body()
    borrower_id = f_str(body, "borrower_id")
    property_id = f_str(body, "property_id")
    term_months = f_int(body, "term_months", minimum=6, maximum=18)
    quoted_rate_bps = f_int(body, "quoted_rate_bps", minimum=800, maximum=1800)
    interest_reserve_months = f_int(body, "interest_reserve_months", minimum=0, maximum=12)
    day_count_convention = f_enum(body, "day_count_convention",
                                  calc.DAY_COUNT_CONVENTIONS, required=False)
    borrower = ser.find_borrower(borrower_id)
    prop = ser.find_property(property_id)

    if borrower["entity_type"] == "SOLE_PROP":
        raise conflict("ERR_ENTITY_TYPE_NOT_ELIGIBLE",
                       "A SOLE_PROP entity cannot borrow on an entity-based loan.")

    rec = new_record()
    rec.update({
        "borrower_id": borrower["id"],
        "property_id": prop["id"],
        "term_months": term_months,
        "quoted_rate_bps": quoted_rate_bps,
        "interest_reserve_months": interest_reserve_months,
        "day_count_convention": day_count_convention or "PER_DIEM_360",
        "intake_experience_score": calc.effective_score(borrower),
        "pricing_tier": calc.experience_tier(borrower),
        "approved_rehab_total_cents": 0,
        "cap_purchase_advance_cents": None,
        "cap_ltc_cents": None,
        "cap_ltarv_cents": None,
        "max_total_loan_cents": None,
        "sized_committed_amount_cents": None,
        "sized_initial_funding_cents": None,
        "sized_interest_reserve_cents": None,
        "sizing_arv_cents": None,
        "sizing_rate_bps": None,
        "approved_loan_amount_cents": None,
        "approved_rate_bps": None,
        "alloc_initial_funding_cents": None,
        "alloc_interest_reserve_cents": None,
        "alloc_rehab_holdback_cents": None,
        "status": "DRAFT",
        "decline_reason": None,
        "_sizing_stale": False,
        "_sizing_rehab_total_cents": None,
        "_sized_by_user_id": None,
    })
    db.applications[rec["id"]] = rec
    return ok(ser.application_out(rec), 201)


@bp.get("/applications/<rec_id>")
def read_application(rec_id):
    authenticate((ROLE_LOAN_OFFICER, ROLE_CREDIT_COMMITTEE, ROLE_LOAN_SERVICER,
                  ROLE_BORROWER, ROLE_PLATFORM_ADMIN))
    app = ser.find_application(rec_id)
    require_borrower_owner(app["borrower_id"])
    return ok(ser.application_out(app))


@bp.get("/applications")
def list_applications():
    authenticate((ROLE_LOAN_OFFICER, ROLE_CREDIT_COMMITTEE, ROLE_LOAN_SERVICER,
                  ROLE_BORROWER, ROLE_PLATFORM_ADMIN))
    borrower_id = q_str("borrower_id")
    property_id = q_str("property_id")
    status = q_enum("status", APPLICATION_STATUSES)
    if borrower_id is not None:
        require_borrower_owner(borrower_id)
    rows = list(db.applications.values())
    if caller_role() == ROLE_BORROWER:
        rows = [a for a in rows if a["borrower_id"] == caller_id()]
    if borrower_id is not None:
        rows = [a for a in rows if a["borrower_id"] == borrower_id]
    if property_id is not None:
        rows = [a for a in rows if a["property_id"] == property_id]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    items, meta = paginate(rows, ser.application_out)
    return ok_list(items, meta)


# ---------------------------------------------------------------------------
# Scope lines
# ---------------------------------------------------------------------------
@bp.post("/applications/<rec_id>/rehab-line-items")
def create_rehab_line_item(rec_id):
    authenticate((ROLE_LOAN_OFFICER, ROLE_BORROWER, ROLE_PLATFORM_ADMIN))
    body = json_body()
    scope_code = f_enum(body, "scope_code", calc.SCOPE_CODES)
    description = f_str(body, "description")
    cost_cents = f_int(body, "cost_cents", minimum=1)
    contractor_id = f_str(body, "contractor_id")
    app = ser.find_application(rec_id)
    contractor = ser.find_contractor(contractor_id)
    require_borrower_owner(app["borrower_id"])

    if app["status"] not in ("DRAFT", "SIZED"):
        raise conflict("ERR_APPLICATION_STATE_INVALID",
                       "Scope lines may only be added to a DRAFT or SIZED application.")
    for line in ser.live_lines(app["id"]):
        if line["scope_code"] == scope_code:
            raise conflict("ERR_DUPLICATE_SCOPE_CODE",
                           "A live scope line already uses this scope_code.")

    rec = new_record()
    rec.update({
        "application_id": app["id"],
        "contractor_id": contractor["id"],
        "scope_code": scope_code,
        "description": description,
        "cost_cents": cost_cents,
        "approved_cost_cents": None,
        "released_cents": 0,
        "status": "PROPOSED",
        "revision_round": 0,
        "reviewer_note": None,
    })
    db.rehab_line_items[rec["id"]] = rec
    if app["status"] == "SIZED":
        app["_sizing_stale"] = True
        touch(app)
    return ok(ser.rehab_line_item_out(rec), 201)


@bp.get("/applications/<rec_id>/rehab-line-items")
def list_application_lines(rec_id):
    authenticate((ROLE_LOAN_OFFICER, ROLE_CREDIT_COMMITTEE, ROLE_LOAN_SERVICER,
                  ROLE_BORROWER, ROLE_CONTRACTOR, ROLE_PLATFORM_ADMIN))
    status = q_enum("status", SCOPE_LINE_STATUSES)
    app = ser.find_application(rec_id)
    require_borrower_owner(app["borrower_id"])
    rows = ser.application_lines(app["id"])
    if status is not None:
        rows = [l for l in rows if l["status"] == status]
    items, meta = paginate(rows, ser.rehab_line_item_out)
    return ok_list(items, meta)


@bp.get("/rehab-line-items/<rec_id>")
def read_rehab_line_item(rec_id):
    authenticate((ROLE_LOAN_OFFICER, ROLE_CREDIT_COMMITTEE, ROLE_LOAN_SERVICER,
                  ROLE_BORROWER, ROLE_CONTRACTOR, ROLE_PLATFORM_ADMIN))
    line = ser.find_rehab_line_item(rec_id)
    app = db.applications.get(line["application_id"])
    if app is not None:
        require_borrower_owner(app["borrower_id"])
    return ok(ser.rehab_line_item_out(line))


@bp.post("/rehab-line-items/<rec_id>/review")
def review_rehab_line_item(rec_id):
    authenticate((ROLE_LOAN_OFFICER, ROLE_PLATFORM_ADMIN))
    body = json_body()
    decision = f_enum(body, "decision", ("APPROVE", "REQUEST_REVISION", "REJECT"))
    approved_cost_cents = f_int(body, "approved_cost_cents", required=False, minimum=0)
    reviewer_note = f_str(body, "reviewer_note", required=False)
    line = ser.find_rehab_line_item(rec_id)
    app = ser.find_application(line["application_id"])

    if app["status"] not in ("DRAFT", "SIZED"):
        raise conflict("ERR_APPLICATION_STATE_INVALID",
                       "The owning application must be DRAFT or SIZED.")

    if decision == "APPROVE":
        if line["status"] != "PROPOSED":
            raise conflict("ERR_REHAB_LINE_STATE_INVALID",
                           "Only a PROPOSED scope line can be approved.")
        approved = approved_cost_cents if approved_cost_cents is not None else line["cost_cents"]
        if approved > line["cost_cents"]:
            raise conflict("ERR_SCOPE_LINE_CAP_EXCEEDED",
                           "approved_cost_cents may not exceed the proposed cost_cents.")
        total = approved
        for sibling in ser.application_lines(app["id"]):
            if sibling["id"] == line["id"]:
                continue
            if sibling["status"] in ("PROPOSED", "REVISION_REQUESTED"):
                total += sibling["cost_cents"]
            elif sibling["status"] == "APPROVED" and sibling["approved_cost_cents"] is not None:
                total += sibling["approved_cost_cents"]
        cap = calc.floor_cents(calc.SINGLE_LINE_CAP_PCT * calc.Decimal(total))
        if approved > cap:
            raise conflict("ERR_SCOPE_LINE_CAP_EXCEEDED",
                           "approved_cost_cents exceeds the single-line concentration cap.")
        line["approved_cost_cents"] = approved
        line["status"] = "APPROVED"
        if reviewer_note is not None:
            line["reviewer_note"] = reviewer_note
        touch(line)
        svc.recompute_application_total(app)
        svc.mark_sizing_stale(app)
        touch(app)

    elif decision == "REQUEST_REVISION":
        if line["status"] not in ("PROPOSED", "APPROVED"):
            raise conflict("ERR_REHAB_LINE_STATE_INVALID",
                           "Only a PROPOSED or APPROVED scope line can be sent back for revision.")
        if line["status"] == "APPROVED" and line["released_cents"] != 0:
            raise conflict("ERR_REHAB_LINE_STATE_INVALID",
                           "A scope line with released cash cannot be de-approved.")
        was_approved = line["status"] == "APPROVED"
        line["status"] = "REVISION_REQUESTED"
        line["approved_cost_cents"] = None
        line["revision_round"] += 1
        line["reviewer_note"] = reviewer_note
        touch(line)
        if was_approved:
            svc.recompute_application_total(app)
            svc.mark_sizing_stale(app)
            touch(app)

    else:  # REJECT
        if line["status"] != "PROPOSED":
            raise conflict("ERR_REHAB_LINE_STATE_INVALID",
                           "Only a PROPOSED scope line can be rejected.")
        line["status"] = "REJECTED"
        line["reviewer_note"] = reviewer_note
        touch(line)

    return ok(ser.rehab_line_item_out(line))


@bp.patch("/rehab-line-items/<rec_id>")
def resubmit_rehab_line_item(rec_id):
    authenticate((ROLE_BORROWER, ROLE_LOAN_OFFICER, ROLE_PLATFORM_ADMIN))
    body = json_body()
    cost_cents = f_int(body, "cost_cents", required=False, minimum=1)
    description = f_str(body, "description", required=False)
    scope_code = f_enum(body, "scope_code", calc.SCOPE_CODES, required=False)
    contractor_id = f_str(body, "contractor_id", required=False)
    line = ser.find_rehab_line_item(rec_id)
    app = ser.find_application(line["application_id"])
    contractor = ser.find_contractor(contractor_id) if contractor_id is not None else None
    require_borrower_owner(app["borrower_id"])

    if app["status"] not in ("DRAFT", "SIZED"):
        raise conflict("ERR_APPLICATION_STATE_INVALID",
                       "The owning application must be DRAFT or SIZED.")
    if line["status"] != "REVISION_REQUESTED":
        raise conflict("ERR_REHAB_LINE_STATE_INVALID",
                       "Only a REVISION_REQUESTED scope line can be resubmitted.")

    target_code = scope_code or line["scope_code"]
    for sibling in ser.live_lines(app["id"]):
        if sibling["id"] == line["id"]:
            continue
        if sibling["scope_code"] == target_code:
            raise conflict("ERR_DUPLICATE_SCOPE_CODE",
                           "A live scope line already uses this scope_code.")
    if line["revision_round"] >= calc.MAX_REVISION_ROUNDS:
        raise conflict("ERR_REVISION_LIMIT_REACHED",
                       "This scope line has exhausted its revision rounds.")

    if cost_cents is not None:
        line["cost_cents"] = cost_cents
    if description is not None:
        line["description"] = description
    if scope_code is not None:
        line["scope_code"] = scope_code
    if contractor is not None:
        line["contractor_id"] = contractor["id"]
    line["approved_cost_cents"] = None
    line["status"] = "PROPOSED"
    touch(line)
    return ok(ser.rehab_line_item_out(line))


# ---------------------------------------------------------------------------
# Sizing, decision, closing
# ---------------------------------------------------------------------------
@bp.post("/applications/<rec_id>/size")
def size_application(rec_id):
    authenticate((ROLE_LOAN_OFFICER, ROLE_PLATFORM_ADMIN))
    json_body()
    app = ser.find_application(rec_id)
    if app["status"] not in ("DRAFT", "SIZED"):
        raise conflict("ERR_APPLICATION_STATE_INVALID",
                       "Only a DRAFT or SIZED application can be sized.")
    borrower = ser.find_borrower(app["borrower_id"])
    if borrower["status"] != "APPROVED_SPONSOR":
        raise conflict("ERR_BORROWER_NOT_ELIGIBLE",
                       "The sponsor is not an APPROVED_SPONSOR.")

    lines = ser.application_lines(app["id"])
    if app["status"] == "DRAFT":
        for line in lines:
            if line["status"] in ("PROPOSED", "REVISION_REQUESTED"):
                raise conflict("ERR_SCOPE_NOT_VALIDATED",
                               "Every scope line must be validated before sizing.")
    if not any(l["status"] == "APPROVED" for l in lines):
        raise conflict("ERR_SCOPE_NOT_VALIDATED",
                       "At least one APPROVED scope line is required to size.")

    prop = ser.find_property(app["property_id"])
    svc.recompute_application_total(app)
    rehab = app["approved_rehab_total_cents"]
    cap_purchase, cap_ltc, cap_ltarv, max_total = calc.loan_sizing_max(
        app["pricing_tier"], prop["purchase_price_cents"], prop["arv_cents"], rehab)
    committed, initial, reserve = calc.sizing_pass(
        cap_purchase, max_total, rehab, app["quoted_rate_bps"], app["interest_reserve_months"])

    app.update({
        "cap_purchase_advance_cents": cap_purchase,
        "cap_ltc_cents": cap_ltc,
        "cap_ltarv_cents": cap_ltarv,
        "max_total_loan_cents": max_total,
        "sized_committed_amount_cents": committed,
        "sized_initial_funding_cents": initial,
        "sized_interest_reserve_cents": reserve,
        "sizing_arv_cents": prop["arv_cents"],
        "sizing_rate_bps": app["quoted_rate_bps"],
        "status": "SIZED",
        "_sizing_stale": False,
        "_sizing_rehab_total_cents": rehab,
        "_sized_by_user_id": caller_id(),
    })
    touch(app)
    return ok(ser.application_out(app))


@bp.post("/applications/<rec_id>/decision")
def decide_application(rec_id):
    authenticate((ROLE_CREDIT_COMMITTEE, ROLE_PLATFORM_ADMIN))
    body = json_body()
    decision = f_enum(body, "decision", ("APPROVE", "DECLINE"))
    approved_loan_amount_cents = f_int(body, "approved_loan_amount_cents",
                                       required=False, minimum=1)
    rate_bps = f_int(body, "rate_bps", required=False, minimum=0)
    decline_reason = f_str(body, "decline_reason", required=False)
    app = ser.find_application(rec_id)

    if app["status"] not in ("DRAFT", "SIZED"):
        raise conflict("ERR_APPLICATION_STATE_INVALID",
                       "Only a SIZED application can be decided.")
    if app["_sized_by_user_id"] is not None and app["_sized_by_user_id"] == caller_id():
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "The operator that sized the application may not decide it.")

    borrower = ser.find_borrower(app["borrower_id"])
    if decision == "APPROVE":
        if borrower["status"] != "APPROVED_SPONSOR":
            raise conflict("ERR_BORROWER_NOT_ELIGIBLE",
                           "The sponsor is not an APPROVED_SPONSOR.")
        if borrower["guarantee_status"] != "EXECUTED":
            raise conflict("ERR_GUARANTEE_NOT_EXECUTED",
                           "The personal guarantee has not been executed.")

    if app["status"] != "SIZED":
        raise conflict("ERR_SIZING_REQUIRED", "The application has never been sized.")
    if ser.sizing_stale(app):
        raise conflict("ERR_SIZING_STALE", "The application's sizing is stale.")

    if decision == "APPROVE":
        amount = (approved_loan_amount_cents if approved_loan_amount_cents is not None
                  else app["sized_committed_amount_cents"])
        if amount > app["max_total_loan_cents"]:
            raise conflict("ERR_LOAN_AMOUNT_EXCEEDS_LIMIT",
                           "The approved amount exceeds max_total_loan_cents.")
        rehab = app["approved_rehab_total_cents"]
        initial, reserve, holdback = calc.decision_pass(
            amount, rehab, app["quoted_rate_bps"], app["interest_reserve_months"])
        app.update({
            "approved_loan_amount_cents": amount,
            "approved_rate_bps": rate_bps if rate_bps is not None else app["quoted_rate_bps"],
            "alloc_initial_funding_cents": initial,
            "alloc_interest_reserve_cents": reserve,
            "alloc_rehab_holdback_cents": holdback,
            "status": "APPROVED",
        })
        touch(app)
    else:
        app["status"] = "DECLINED"
        app["decline_reason"] = decline_reason
        svc.void_live_lines(app)
        touch(app)

    return ok(ser.application_out(app))


@bp.post("/applications/<rec_id>/close")
def close_application(rec_id):
    authenticate((ROLE_LOAN_SERVICER, ROLE_PLATFORM_ADMIN))
    body = json_body()
    closing_date = f_date(body, "closing_date")
    app = ser.find_application(rec_id)

    if app["status"] != "APPROVED":
        raise conflict("ERR_APPLICATION_STATE_INVALID",
                       "Only an APPROVED application can be closed.")
    prop = ser.find_property(app["property_id"])
    if prop["status"] != "UNDER_CONTRACT":
        raise conflict("ERR_PROPERTY_STATE_INVALID",
                       "The subject property must still be UNDER_CONTRACT.")
    borrower = ser.find_borrower(app["borrower_id"])
    if borrower["status"] != "APPROVED_SPONSOR":
        raise conflict("ERR_BORROWER_NOT_ELIGIBLE",
                       "The sponsor is not an APPROVED_SPONSOR.")
    if borrower["guarantee_status"] != "EXECUTED":
        raise conflict("ERR_GUARANTEE_NOT_EXECUTED",
                       "The personal guarantee has not been executed.")

    lines = ser.application_lines(app["id"])
    for line in lines:
        if line["status"] in ("PROPOSED", "REVISION_REQUESTED"):
            raise conflict("ERR_SCOPE_NOT_VALIDATED",
                           "Every scope line must be settled before closing.")
    for line in lines:
        if line["status"] == "APPROVED":
            contractor = db.contractors.get(line["contractor_id"])
            if contractor is None or not calc.payable(contractor):
                raise conflict("ERR_CONTRACTOR_NOT_PAYABLE",
                               "A contractor on an approved scope line is not payable.")

    loan = new_record()
    note_rate = app["approved_rate_bps"]
    loan.update({
        "application_id": app["id"],
        "borrower_id": app["borrower_id"],
        "closing_date": closing_date,
        "term_months": app["term_months"],
        "note_rate_bps": note_rate,
        "default_rate_bps": note_rate + calc.DEFAULT_RATE_SPREAD_BPS,
        "day_count_convention": app["day_count_convention"],
        "committed_amount_cents": app["approved_loan_amount_cents"],
        "funded_principal_cents": app["alloc_initial_funding_cents"],
        "repaid_principal_cents": 0,
        "reserved_release_cents": 0,
        "undisbursed_holdback_cents": app["alloc_rehab_holdback_cents"],
        "interest_reserve_balance_cents": app["alloc_interest_reserve_cents"],
        "interest_reserve_funded_cents": app["alloc_interest_reserve_cents"],
        "decommitted_holdback_cents": 0,
        "accrued_interest_unpaid_cents": 0,
        "fee_balance_cents": 0,
        "last_accrual_through": None,
        "delinquent_since": None,
        "default_effective_date": None,
        "extension_count": 0,
        "extension_months_total": 0,
        "payment_status": "CURRENT",
        "construction_status": "NOT_STARTED",
        "exit_status": "NOT_LISTED",
        "recovery_cents": None,
        "charge_off_cents": None,
        "surplus_returned_cents": None,
        "_days_on_market_frozen": None,
    })
    loan["maturity_date"] = calc.maturity_date_for(loan)
    db.loans[loan["id"]] = loan

    svc.write_ledger(loan, "INITIAL_FUNDING", app["alloc_initial_funding_cents"],
                     closing_date, "Initial funding at closing", app["id"])
    prop["status"] = "BORROWER_OWNED"
    touch(prop)
    app["status"] = "CLOSED"
    touch(app)
    return ok(ser.loan_out(loan), 201)
