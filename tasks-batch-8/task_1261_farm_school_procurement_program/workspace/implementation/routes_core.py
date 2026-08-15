"""Program years, farms, compliance documents, products."""
import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

from db import clock_date, new_record, store, touch
from errors import ApiError
from services import (CLAIM_PAST_REVIEW, claim_totals, docs_compliant, grant_drawn,
                      posture, reinstate_farm_cascade, ser_doc, ser_farm, ser_product,
                      ser_year, suspend_farm_cascade)
from util import (body, ctx, list_response, ok_object, opt_enum, opt_int, req_date,
                  req_enum, req_int, req_number, req_str, require_role, parse_month)

bp = Blueprint("core", __name__)

DPA = "DistrictProgramAdmin"
FM = "FarmManager"
KM = "KitchenManager"
CC = "ClaimsCoordinator"
SGA = "StateGrantAuditor"


def get_or_404(collection, rid, error_id):
    rec = store[collection].get(rid)
    if rec is None:
        raise ApiError(error_id, "Resource %s not found" % rid, 404)
    return rec


# ---------------------------------------------------------------------------
# ProgramYear
# ---------------------------------------------------------------------------

@bp.route("/f2s/program-years", methods=["POST"])
def create_program_year():
    uid, role = ctx()
    b = body()
    label = req_str(b, "school_year_label")
    start = req_date(b, "start_date")
    end = req_date(b, "end_date")
    radius = req_int(b, "local_radius_miles", mn=25)
    model = opt_enum(b, "preference_model", {"LINEAR", "TIERED"}, default="LINEAR")
    award = req_int(b, "grant_award_cents", mn=0)
    target = req_number(b, "local_spend_target_pct")
    require_role(role, DPA)
    if end <= start:
        raise ApiError("ERR_INVALID_DATE_RANGE", "end_date must be after start_date", 400)
    rec = new_record()
    rec.update({
        "school_year_label": label,
        "start_date": start,
        "end_date": end,
        "local_radius_miles": radius,
        "preference_model": model,
        "grant_award_cents": award,
        "local_spend_target_pct": target,
        "status": "DRAFT",
    })
    store["program_years"][rec["id"]] = rec
    return ok_object(ser_year(rec), 201)


@bp.route("/f2s/program-years", methods=["GET"])
def list_program_years():
    ctx()
    return list_response(store["program_years"].values(), ser_year, {"status": "status"})


@bp.route("/f2s/program-years/<rid>", methods=["GET"])
def get_program_year(rid):
    ctx()
    rec = get_or_404("program_years", rid, "ERR_PROGRAM_YEAR_NOT_FOUND")
    return ok_object(ser_year(rec))


@bp.route("/f2s/program-years/<rid>/open", methods=["POST"])
def open_program_year(rid):
    uid, role = ctx()
    require_role(role, DPA)
    rec = get_or_404("program_years", rid, "ERR_PROGRAM_YEAR_NOT_FOUND")
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_PROGRAM_YEAR_NOT_DRAFT", "open requires status DRAFT", 409)
    rec["status"] = "OPEN"
    touch(rec)
    return ok_object(ser_year(rec))


@bp.route("/f2s/program-years/<rid>/close", methods=["POST"])
def close_program_year(rid):
    uid, role = ctx()
    require_role(role, DPA)
    rec = get_or_404("program_years", rid, "ERR_PROGRAM_YEAR_NOT_FOUND")
    if rec["status"] != "OPEN":
        raise ApiError("ERR_PROGRAM_YEAR_NOT_OPEN", "close requires status OPEN", 409)
    for c in store["claims"].values():
        if c["program_year_id"] == rid and c["status"] in ("OPEN", "SUBMITTED", "UNDER_REVIEW"):
            raise ApiError("ERR_CLAIMS_UNRESOLVED",
                           "Year close blocked by unresolved reimbursement claims", 409)
    rec["status"] = "CLOSED"
    touch(rec)
    return ok_object(ser_year(rec))


@bp.route("/f2s/program-years/<rid>/report", methods=["GET"])
def program_year_report(rid):
    ctx()
    rec = get_or_404("program_years", rid, "ERR_PROGRAM_YEAR_NOT_FOUND")
    from flask import request
    raw_month = request.args.get("month")
    if raw_month is None:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter month is required", 400)
    y, m = parse_month(raw_month, "month")
    month = "%04d-%02d" % (y, m)

    accrual_total = accrual_local = cash_total = cash_local = 0
    for inv in store["invoices"].values():
        ag = store["agreements"].get(inv["agreement_id"])
        if not ag or ag["program_year_id"] != rid:
            continue
        if inv["status"] == "VOIDED":
            continue
        dlv = store["deliveries"].get(inv["delivery_id"])
        dlv_month = dlv["delivery_date"].isoformat()[:7] if dlv else None
        if inv["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "PAID") and dlv_month == month:
            accrual_total += inv["subtotal_cents"]
            if ag["local_eligible"]:
                accrual_local += inv["subtotal_cents"]
        if inv["status"] == "PAID" and inv.get("paid_at") and inv["paid_at"][:7] == month:
            cash_total += inv["subtotal_cents"]
            if ag["local_eligible"]:
                cash_local += inv["subtotal_cents"]

    def share(local, total):
        if total == 0:
            return Decimal("0.00")
        return (Decimal(100) * Decimal(local) / Decimal(total)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)

    cash_share = share(cash_local, cash_total)
    accrual_share = share(accrual_local, accrual_total)
    target = Decimal(str(rec["local_spend_target_pct"]))

    match_prov_total = 0
    match_final_total = 0
    for c in store["claims"].values():
        if c["program_year_id"] != rid:
            continue
        _, _, prov, fin = claim_totals(c)
        match_prov_total += prov
        if c["status"] in CLAIM_PAST_REVIEW and fin is not None:
            match_final_total += fin

    drawn = grant_drawn(rid)
    out = {
        "month": month,
        "cash_local_spend_cents": cash_local,
        "accrual_local_spend_cents": accrual_local,
        "cash_total_spend_cents": cash_total,
        "accrual_total_spend_cents": accrual_total,
        "cash_local_share_pct": float(cash_share),
        "accrual_local_share_pct": float(accrual_share),
        "meets_target_cash": bool(cash_share >= target),
        "meets_target_accrual": bool(accrual_share >= target),
        "grant_award_cents": rec["grant_award_cents"],
        "grant_drawn_cents": drawn,
        "grant_remaining_cents": rec["grant_award_cents"] - drawn,
        "match_provisional_cents": match_prov_total,
        "match_final_cents": match_final_total,
    }
    return ok_object(out)


# ---------------------------------------------------------------------------
# Farm
# ---------------------------------------------------------------------------

@bp.route("/f2s/farms", methods=["POST"])
def create_farm():
    uid, role = ctx()
    b = body()
    legal_name = req_str(b, "legal_name")
    contact_email = req_str(b, "contact_email")
    distance = req_int(b, "distance_miles_to_hub", mn=0)
    acres = req_number(b, "acres")
    if acres <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "acres must be greater than 0", 400)
    require_role(role, DPA)
    is_small = acres <= 500
    rec = new_record()
    rec.update({
        "legal_name": legal_name,
        "contact_email": contact_email,
        "distance_miles_to_hub": distance,
        "acres": acres,
        "is_small_farm": is_small,
        "required_insurance_cents": 500000 if is_small else 1000000,
        "status": "APPLIED",
    })
    store["farms"][rec["id"]] = rec
    return ok_object(ser_farm(rec), 201)


@bp.route("/f2s/farms", methods=["GET"])
def list_farms():
    ctx()
    return list_response(store["farms"].values(), ser_farm, {"status": "status"})


@bp.route("/f2s/farms/<rid>", methods=["GET"])
def get_farm(rid):
    ctx()
    rec = get_or_404("farms", rid, "ERR_FARM_NOT_FOUND")
    return ok_object(ser_farm(rec))


@bp.route("/f2s/farms/<rid>/approve", methods=["POST"])
def approve_farm(rid):
    uid, role = ctx()
    require_role(role, DPA)
    rec = get_or_404("farms", rid, "ERR_FARM_NOT_FOUND")
    if rec["status"] != "APPLIED":
        raise ApiError("ERR_FARM_NOT_APPLIED", "approve requires status APPLIED", 409)
    if not docs_compliant(rec, clock_date()):
        raise ApiError("ERR_FARM_COMPLIANCE_INCOMPLETE",
                       "Farm approval lacks a valid safety cert or sufficient insurance "
                       "at the current date", 422)
    rec["status"] = "APPROVED"
    touch(rec)
    return ok_object(ser_farm(rec))


@bp.route("/f2s/farms/<rid>/suspend", methods=["POST"])
def suspend_farm(rid):
    uid, role = ctx()
    require_role(role, DPA, SGA)
    rec = get_or_404("farms", rid, "ERR_FARM_NOT_FOUND")
    if rec["status"] != "APPROVED":
        raise ApiError("ERR_FARM_NOT_APPROVED", "suspend requires status APPROVED", 409)
    rec["status"] = "SUSPENDED"
    touch(rec)
    suspend_farm_cascade(rec)
    return ok_object(ser_farm(rec))


@bp.route("/f2s/farms/<rid>/reinstate", methods=["POST"])
def reinstate_farm(rid):
    uid, role = ctx()
    require_role(role, DPA)
    rec = get_or_404("farms", rid, "ERR_FARM_NOT_FOUND")
    if rec["status"] != "SUSPENDED":
        raise ApiError("ERR_FARM_NOT_SUSPENDED", "reinstate requires status SUSPENDED", 409)
    if not docs_compliant(rec, clock_date()):
        raise ApiError("ERR_FARM_NOT_COMPLIANT",
                       "Farm compliance posture at the current date is NON_COMPLIANT", 422)
    rec["status"] = "APPROVED"
    touch(rec)
    reinstate_farm_cascade(rec)
    return ok_object(ser_farm(rec))


# ---------------------------------------------------------------------------
# ComplianceDocument
# ---------------------------------------------------------------------------

@bp.route("/f2s/compliance-documents", methods=["POST"])
def create_document():
    uid, role = ctx()
    b = body()
    farm_id = req_str(b, "farm_id")
    doc_type = req_enum(b, "doc_type", {"SAFETY_CERT", "LIABILITY_INSURANCE"})
    issuer = req_str(b, "issuer")
    coverage = opt_int(b, "coverage_cents")
    effective = req_date(b, "effective_on")
    expires = req_date(b, "expires_on")
    if doc_type == "LIABILITY_INSURANCE" and coverage is None:
        raise ApiError("ERR_COVERAGE_REQUIRED",
                       "LIABILITY_INSURANCE document requires coverage_cents", 400)
    require_role(role, FM)
    farm = store["farms"].get(farm_id)
    if farm is None:
        raise ApiError("ERR_FARM_NOT_FOUND", "Farm %s not found" % farm_id, 404)
    if farm_id != uid:
        raise ApiError("ERR_RESOURCE_OWNERSHIP",
                       "FarmManager may only act on its own farm", 403)
    if doc_type == "LIABILITY_INSURANCE" and coverage < farm["required_insurance_cents"]:
        raise ApiError("ERR_COVERAGE_BELOW_MINIMUM",
                       "Insurance coverage_cents is below required_insurance_cents", 422)
    if expires <= effective:
        raise ApiError("ERR_INVALID_DATE_RANGE", "expires_on must be after effective_on", 400)
    rec = new_record()
    rec.update({
        "farm_id": farm_id,
        "doc_type": doc_type,
        "issuer": issuer,
        "coverage_cents": coverage,
        "effective_on": effective,
        "expires_on": expires,
        "status": "ACTIVE",
    })
    store["documents"][rec["id"]] = rec
    return ok_object(ser_doc(rec), 201)


@bp.route("/f2s/compliance-documents", methods=["GET"])
def list_documents():
    ctx()
    return list_response(store["documents"].values(), ser_doc,
                         {"farm_id": "farm_id", "doc_type": "doc_type", "status": "status"})


@bp.route("/f2s/compliance-documents/<rid>", methods=["GET"])
def get_document(rid):
    ctx()
    rec = get_or_404("documents", rid, "ERR_DOCUMENT_NOT_FOUND")
    return ok_object(ser_doc(rec))


@bp.route("/f2s/compliance-documents/<rid>/revoke", methods=["POST"])
def revoke_document(rid):
    uid, role = ctx()
    require_role(role, SGA)
    rec = get_or_404("documents", rid, "ERR_DOCUMENT_NOT_FOUND")
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_DOCUMENT_NOT_ACTIVE", "revoke requires status ACTIVE", 409)
    rec["status"] = "REVOKED"
    touch(rec)
    return ok_object(ser_doc(rec))


# ---------------------------------------------------------------------------
# Product
# ---------------------------------------------------------------------------

@bp.route("/f2s/products", methods=["POST"])
def create_product():
    uid, role = ctx()
    b = body()
    name = req_str(b, "name")
    category = req_enum(b, "category", {"PRODUCE", "DAIRY", "PROTEIN", "GRAIN"})
    unit = req_enum(b, "unit", {"LB", "CASE", "GALLON", "DOZEN"})
    s_start = req_int(b, "season_start_week", mn=1, mx=52)
    s_end = req_int(b, "season_end_week", mn=1, mx=52)
    require_role(role, DPA)
    rec = new_record()
    rec.update({
        "name": name,
        "category": category,
        "unit": unit,
        "season_start_week": s_start,
        "season_end_week": s_end,
        "status": "ACTIVE",
    })
    store["products"][rec["id"]] = rec
    return ok_object(ser_product(rec), 201)


@bp.route("/f2s/products", methods=["GET"])
def list_products():
    ctx()
    return list_response(store["products"].values(), ser_product,
                         {"category": "category", "status": "status"})


@bp.route("/f2s/products/<rid>", methods=["GET"])
def get_product(rid):
    ctx()
    rec = get_or_404("products", rid, "ERR_PRODUCT_NOT_FOUND")
    return ok_object(ser_product(rec))


@bp.route("/f2s/products/<rid>/discontinue", methods=["POST"])
def discontinue_product(rid):
    uid, role = ctx()
    require_role(role, DPA)
    rec = get_or_404("products", rid, "ERR_PRODUCT_NOT_FOUND")
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_PRODUCT_NOT_ACTIVE", "discontinue requires status ACTIVE", 409)
    rec["status"] = "DISCONTINUED"
    touch(rec)
    return ok_object(ser_product(rec))
