"""Property-Tax Appeal API — Flask application.

In-memory storage only (see store.py). Boots empty on every invocation; the
test harness restarts this server via start.sh before each test.
"""

import datetime
import os

from flask import Flask, request

import calc
import domain
from common import (
    ApiError, ok, err, require_auth, require_role, forbidden_owner,
    serialize, base_record, touch, get_body, need, need_int, need_num,
    need_str, need_enum, need_dt, opt_int, opt_num, opt_str, opt_bool,
    must_exist, paginate,
)
from store import db, now, parse_dt

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return err(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def _handle_404(e):
    return err("ERR_NOT_FOUND", 404, "resource not found")


@app.errorhandler(405)
def _handle_405(e):
    return err("ERR_NOT_FOUND", 404, "method not allowed")


@app.errorhandler(Exception)
def _handle_unexpected(e):
    if isinstance(e, ApiError):
        return err(e.error_id, e.http_status, e.message)
    return err("ERR_INTERNAL", 500, "internal error: %s" % e)


# ==========================================================================
# Logical clock
# ==========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_role(require_auth()[1], {"FirmAdmin"})
    b = get_body()
    db.clock = need_dt(b, "to_iso8601")
    return ok({}, 200)


# ==========================================================================
# Analyst
# ==========================================================================
@app.route("/api/analysts", methods=["POST"])
def create_analyst():
    uid, role = require_auth()
    require_role(role, {"FirmAdmin"})
    b = get_body()
    full_name = need_str(b, "full_name")
    email = need_str(b, "email")
    license_number = need_str(b, "license_number")
    active = opt_bool(b, "active", True)
    for a in db.analysts.values():
        if a["email"] == email:
            raise ApiError("ERR_DUPLICATE", 409, "analyst email already exists")
    rec = base_record()
    rec.update({"full_name": full_name, "email": email,
                "license_number": license_number, "active": active})
    db.analysts[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/api/analysts/<rid>", methods=["GET"])
def get_analyst(rid):
    uid, role = require_auth()
    require_role(role, {"FirmAdmin", "Analyst", "Billing"})
    rec = must_exist(db.analysts, rid)
    return ok(serialize(rec), 200)


# ==========================================================================
# Client
# ==========================================================================
@app.route("/api/clients", methods=["POST"])
def create_client():
    uid, role = require_auth()
    require_role(role, {"FirmAdmin"})
    b = get_body()
    full_name = need_str(b, "full_name")
    email = need_str(b, "email")
    entity_type = need_enum(b, "entity_type", {"INDIVIDUAL", "BUSINESS"})
    portal_enabled = opt_bool(b, "portal_enabled", True)
    for c in db.clients.values():
        if c["email"] == email:
            raise ApiError("ERR_DUPLICATE", 409, "client email already exists")
    rec = base_record()
    rec.update({"full_name": full_name, "email": email, "entity_type": entity_type,
                "portal_enabled": portal_enabled,
                "lifetime_fees_billed_cents": 0, "outstanding_balance_cents": 0})
    db.clients[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/api/clients/<rid>", methods=["GET"])
def get_client(rid):
    uid, role = require_auth()
    require_role(role, {"FirmAdmin", "Billing", "Client"})
    if role == "Client" and rid != uid:
        forbidden_owner()
    rec = must_exist(db.clients, rid)
    return ok(serialize(rec), 200)


# ==========================================================================
# Jurisdiction
# ==========================================================================
@app.route("/api/jurisdictions", methods=["POST"])
def create_jurisdiction():
    uid, role = require_auth()
    require_role(role, {"FirmAdmin"})
    b = get_body()
    name = need_str(b, "name")
    state_code = need_str(b, "state_code")
    filing_window_days = need_int(b, "filing_window_days")
    equalization_ratio = need_num(b, "equalization_ratio")
    if filing_window_days < 1:
        raise ApiError("ERR_INVALID_REQUEST", 422, "filing_window_days must be >= 1")
    if not (0 < equalization_ratio <= 1):
        raise ApiError("ERR_INVALID_REQUEST", 422, "equalization_ratio must be in (0, 1]")
    informal = opt_bool(b, "informal_review_available", True)
    capacity = opt_int(b, "hearing_room_capacity", 3)
    buffer_min = opt_int(b, "rep_travel_buffer_minutes", 60)
    rec = base_record()
    rec.update({"name": name, "state_code": state_code,
                "filing_window_days": filing_window_days,
                "equalization_ratio": equalization_ratio,
                "informal_review_available": informal,
                "hearing_room_capacity": capacity,
                "rep_travel_buffer_minutes": buffer_min})
    db.jurisdictions[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/api/jurisdictions/<rid>", methods=["GET"])
def get_jurisdiction(rid):
    uid, role = require_auth()
    require_role(role, {"FirmAdmin", "Analyst"})
    rec = must_exist(db.jurisdictions, rid)
    return ok(serialize(rec), 200)


# ==========================================================================
# FeeAgreement
# ==========================================================================
@app.route("/api/fee-agreements", methods=["POST"])
def create_fee_agreement():
    uid, role = require_auth()
    require_role(role, {"FirmAdmin"})
    b = get_body()
    client_id = b.get("client_id")
    if client_id is not None and client_id not in db.clients:
        raise ApiError("ERR_NOT_FOUND", 404, "client does not exist")
    client_id = need_str(b, "client_id")
    rec = base_record()
    rec.update({
        "client_id": client_id,
        "contingency_tier1_pct": opt_num(b, "contingency_tier1_pct", 0.40),
        "contingency_tier2_pct": opt_num(b, "contingency_tier2_pct", 0.33),
        "contingency_tier3_pct": opt_num(b, "contingency_tier3_pct", 0.25),
        "tier1_ceiling_cents": opt_int(b, "tier1_ceiling_cents", 50000),
        "tier2_ceiling_cents": opt_int(b, "tier2_ceiling_cents", 150000),
        "minimum_fee_cents": opt_int(b, "minimum_fee_cents", 15000),
        "status": "PENDING",
        "accepted_at": None,
    })
    db.fee_agreements[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/api/fee-agreements/<rid>", methods=["GET"])
def get_fee_agreement(rid):
    uid, role = require_auth()
    require_role(role, {"FirmAdmin", "Billing", "Client"})
    rec = must_exist(db.fee_agreements, rid)
    if role == "Client" and rec["client_id"] != uid:
        forbidden_owner()
    return ok(serialize(rec), 200)


@app.route("/api/fee-agreements", methods=["GET"])
def list_fee_agreements():
    uid, role = require_auth()
    require_role(role, {"FirmAdmin", "Billing", "Client"})
    items = list(db.fee_agreements.values())
    client_id = request.args.get("client_id")
    if client_id is not None:
        items = [r for r in items if r["client_id"] == client_id]
    if role == "Client":
        items = [r for r in items if r["client_id"] == uid]
    data, pg = paginate(items)
    return ok(data, 200, "array", pg)


@app.route("/api/fee-agreements/<rid>/accept", methods=["POST"])
def accept_fee_agreement(rid):
    uid, role = require_auth()
    require_role(role, {"Client"})
    rec = must_exist(db.fee_agreements, rid)
    if rec["client_id"] != uid:
        forbidden_owner()
    if rec["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "fee agreement is not PENDING")
    rec["status"] = "ACTIVE"
    rec["accepted_at"] = now()
    touch(rec)
    return ok(serialize(rec), 200)


# ==========================================================================
# Parcel
# ==========================================================================
@app.route("/api/parcels", methods=["POST"])
def create_parcel():
    uid, role = require_auth()
    require_role(role, {"Analyst"})
    b = get_body()
    client_id = b.get("client_id")
    if client_id is not None and client_id not in db.clients:
        raise ApiError("ERR_NOT_FOUND", 404, "client does not exist")
    jurisdiction_id = b.get("jurisdiction_id")
    if jurisdiction_id is not None and jurisdiction_id not in db.jurisdictions:
        raise ApiError("ERR_NOT_FOUND", 404, "jurisdiction does not exist")
    client_id = need_str(b, "client_id")
    jurisdiction_id = need_str(b, "jurisdiction_id")
    apn = need_str(b, "apn")
    address = need_str(b, "address")
    property_class = need_enum(b, "property_class",
                               {"RESIDENTIAL", "COMMERCIAL", "INDUSTRIAL", "LAND"})
    building_area_sqft = opt_int(b, "building_area_sqft", 0)
    for p in db.parcels.values():
        if p["jurisdiction_id"] == jurisdiction_id and p["apn"] == apn:
            raise ApiError("ERR_DUPLICATE", 409, "apn already exists in jurisdiction")
    rec = base_record()
    rec.update({"client_id": client_id, "jurisdiction_id": jurisdiction_id,
                "apn": apn, "address": address, "property_class": property_class,
                "building_area_sqft": building_area_sqft})
    db.parcels[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/api/parcels/<rid>", methods=["GET"])
def get_parcel(rid):
    uid, role = require_auth()
    require_role(role, {"FirmAdmin", "Analyst", "Client"})
    rec = must_exist(db.parcels, rid)
    if role == "Client" and rec["client_id"] != uid:
        forbidden_owner()
    return ok(serialize(rec), 200)


@app.route("/api/parcels", methods=["GET"])
def list_parcels():
    uid, role = require_auth()
    require_role(role, {"FirmAdmin", "Analyst", "Client"})
    items = list(db.parcels.values())
    client_id = request.args.get("client_id")
    jurisdiction_id = request.args.get("jurisdiction_id")
    if client_id is not None:
        items = [r for r in items if r["client_id"] == client_id]
    if jurisdiction_id is not None:
        items = [r for r in items if r["jurisdiction_id"] == jurisdiction_id]
    if role == "Client":
        items = [r for r in items if r["client_id"] == uid]
    data, pg = paginate(items)
    return ok(data, 200, "array", pg)


# ==========================================================================
# Assessment
# ==========================================================================
@app.route("/api/assessments", methods=["POST"])
def create_assessment():
    uid, role = require_auth()
    require_role(role, {"Analyst"})
    b = get_body()
    parcel_id = b.get("parcel_id")
    if parcel_id is not None and parcel_id not in db.parcels:
        raise ApiError("ERR_NOT_FOUND", 404, "parcel does not exist")
    parcel_id = need_str(b, "parcel_id")
    tax_year = need_int(b, "tax_year")
    original = need_int(b, "original_assessed_value_cents")
    millage_rate = need_num(b, "millage_rate")
    notice_date = need_dt(b, "notice_date")
    if original < 0:
        raise ApiError("ERR_INVALID_REQUEST", 422, "original_assessed_value_cents must be >= 0")
    if millage_rate <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 422, "millage_rate must be > 0")
    land = opt_int(b, "land_value_cents", 0)
    improvement = opt_int(b, "improvement_value_cents", 0)
    for a in db.assessments.values():
        if a["parcel_id"] == parcel_id and a["tax_year"] == tax_year:
            raise ApiError("ERR_DUPLICATE", 409, "assessment already exists for parcel/tax_year")
    rec = base_record()
    rec.update({
        "parcel_id": parcel_id, "tax_year": tax_year,
        "original_assessed_value_cents": original,
        "land_value_cents": land, "improvement_value_cents": improvement,
        "millage_rate": millage_rate, "notice_date": notice_date,
        "assessed_value_cents": original,
        "total_approved_exemption_cents": 0,
        "projected_annual_tax_cents": 0,
        "status": "NOTICED",
    })
    domain.recompute_assessment_tax(rec)
    db.assessments[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/api/assessments/<rid>", methods=["GET"])
def get_assessment(rid):
    uid, role = require_auth()
    require_role(role, {"FirmAdmin", "Analyst", "Client"})
    rec = must_exist(db.assessments, rid)
    if role == "Client" and domain.client_of_assessment(rec) != uid:
        forbidden_owner()
    return ok(serialize(rec), 200)


@app.route("/api/assessments", methods=["GET"])
def list_assessments():
    uid, role = require_auth()
    require_role(role, {"FirmAdmin", "Analyst", "Client"})
    items = list(db.assessments.values())
    parcel_id = request.args.get("parcel_id")
    if parcel_id is not None:
        items = [r for r in items if r["parcel_id"] == parcel_id]
    if role == "Client":
        items = [r for r in items if domain.client_of_assessment(r) == uid]
    data, pg = paginate(items)
    return ok(data, 200, "array", pg)


# ==========================================================================
# ExemptionClaim
# ==========================================================================
@app.route("/api/exemption-claims", methods=["POST"])
def create_exemption_claim():
    uid, role = require_auth()
    require_role(role, {"Analyst", "Client"})
    b = get_body()
    parcel_id = b.get("parcel_id")
    if parcel_id is not None and parcel_id not in db.parcels:
        raise ApiError("ERR_NOT_FOUND", 404, "parcel does not exist")
    parcel_id = need_str(b, "parcel_id")
    tax_year = need_int(b, "tax_year")
    exemption_type = need_enum(b, "exemption_type",
                               {"HOMESTEAD", "SENIOR", "VETERAN", "AGRICULTURAL", "DISABLED"})
    exemption_value = need_int(b, "exemption_value_cents")
    if exemption_value < 0:
        raise ApiError("ERR_INVALID_REQUEST", 422, "exemption_value_cents must be >= 0")
    rec = base_record()
    rec.update({"parcel_id": parcel_id, "tax_year": tax_year,
                "exemption_type": exemption_type,
                "exemption_value_cents": exemption_value, "status": "DRAFT"})
    db.exemption_claims[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/api/exemption-claims/<rid>", methods=["GET"])
def get_exemption_claim(rid):
    uid, role = require_auth()
    require_role(role, {"FirmAdmin", "Analyst", "Client"})
    rec = must_exist(db.exemption_claims, rid)
    if role == "Client" and domain.client_of_exemption(rec) != uid:
        forbidden_owner()
    return ok(serialize(rec), 200)


@app.route("/api/exemption-claims", methods=["GET"])
def list_exemption_claims():
    uid, role = require_auth()
    require_role(role, {"FirmAdmin", "Analyst", "Client"})
    items = list(db.exemption_claims.values())
    parcel_id = request.args.get("parcel_id")
    if parcel_id is not None:
        items = [r for r in items if r["parcel_id"] == parcel_id]
    if role == "Client":
        items = [r for r in items if domain.client_of_exemption(r) == uid]
    data, pg = paginate(items)
    return ok(data, 200, "array", pg)


@app.route("/api/exemption-claims/<rid>/submit", methods=["POST"])
def submit_exemption_claim(rid):
    uid, role = require_auth()
    require_role(role, {"Analyst", "Client"})
    rec = must_exist(db.exemption_claims, rid)
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "exemption claim is not DRAFT")
    rec["status"] = "SUBMITTED"
    touch(rec)
    return ok(serialize(rec), 200)


@app.route("/api/exemption-claims/<rid>/decide", methods=["POST"])
def decide_exemption_claim(rid):
    uid, role = require_auth()
    require_role(role, {"FirmAdmin"})
    rec = must_exist(db.exemption_claims, rid)
    b = get_body()
    decision = need_enum(b, "decision", {"APPROVE", "DENY"})
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "exemption claim is not SUBMITTED")
    # Locate the matching assessment for (parcel_id, tax_year).
    match = None
    for a in db.assessments.values():
        if a["parcel_id"] == rec["parcel_id"] and a["tax_year"] == rec["tax_year"]:
            match = a
            break
    if decision == "APPROVE":
        if match is None:
            raise ApiError("ERR_INVALID_STATE", 409,
                           "no assessment exists for the claim's parcel/tax_year")
        rec["status"] = "APPROVED"
        touch(rec)
        # CASCADE link1: recompute assessment exemption total + projected tax.
        domain.recompute_assessment_tax(match)
        touch(match)
        # CASCADE link2: recompute projected_client_tax_bill for any non-terminal appeal.
        for ap in db.appeals.values():
            if ap["assessment_id"] == match["id"] and ap["status"] in domain.NON_TERMINAL_APPEAL:
                if ap.get("requested_value_cents") is not None:
                    domain.recompute_projected_client_tax_bill(ap)
                touch(ap)
    else:
        rec["status"] = "DENIED"
        touch(rec)
        # Denial carries no cascade (approved total unchanged).
    return ok(serialize(rec), 200)


# ==========================================================================
# Appeal — CRUD + evidence
# ==========================================================================
@app.route("/api/appeals", methods=["POST"])
def create_appeal():
    uid, role = require_auth()
    require_role(role, {"Analyst"})
    b = get_body()
    assessment_id = b.get("assessment_id")
    if assessment_id is not None and assessment_id not in db.assessments:
        raise ApiError("ERR_NOT_FOUND", 404, "assessment does not exist")
    analyst_id = b.get("analyst_id")
    if analyst_id is not None and analyst_id not in db.analysts:
        raise ApiError("ERR_NOT_FOUND", 404, "analyst does not exist")
    fee_agreement_id = b.get("fee_agreement_id")
    if fee_agreement_id is not None and fee_agreement_id not in db.fee_agreements:
        raise ApiError("ERR_NOT_FOUND", 404, "fee agreement does not exist")
    assessment_id = need_str(b, "assessment_id")
    analyst_id = need_str(b, "analyst_id")
    fee_agreement_id = need_str(b, "fee_agreement_id")
    valuation_method = need_enum(b, "valuation_method",
                                 {"SALES_COMPARISON", "ASSESSMENT_EQUITY"})
    for ap in db.appeals.values():
        if ap["assessment_id"] == assessment_id and ap["status"] in domain.NON_TERMINAL_APPEAL:
            raise ApiError("ERR_DUPLICATE", 409, "a non-terminal appeal already exists")
    rec = base_record()
    rec.update({
        "assessment_id": assessment_id, "analyst_id": analyst_id,
        "fee_agreement_id": fee_agreement_id, "valuation_method": valuation_method,
        "requested_value_cents": None, "filed_date": None,
        "decision_value_cents": None, "settlement_value_cents": None,
        "projected_savings_cents": None, "projected_fee_cents": None,
        "projected_client_tax_bill_cents": None, "realized_savings_cents": None,
        "outcome_source": None, "decision_date": None, "status": "DRAFT",
    })
    db.appeals[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/api/appeals/<rid>", methods=["GET"])
def get_appeal(rid):
    uid, role = require_auth()
    require_role(role, {"FirmAdmin", "Analyst", "Billing", "Client"})
    rec = must_exist(db.appeals, rid)
    if role == "Client" and domain.client_of_appeal(rec) != uid:
        forbidden_owner()
    return ok(serialize(rec), 200)


@app.route("/api/appeals", methods=["GET"])
def list_appeals():
    uid, role = require_auth()
    require_role(role, {"FirmAdmin", "Analyst", "Client"})
    items = list(db.appeals.values())
    for key in ("assessment_id", "analyst_id", "fee_agreement_id"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r[key] == val]
    if role == "Client":
        items = [r for r in items if domain.client_of_appeal(r) == uid]
    data, pg = paginate(items)
    return ok(data, 200, "array", pg)


@app.route("/api/appeals/<rid>/evidence", methods=["POST"])
def create_evidence(rid):
    uid, role = require_auth()
    require_role(role, {"Analyst"})
    appeal = must_exist(db.appeals, rid)
    b = get_body()
    comp_address = need_str(b, "comp_address")
    sale_price = need_int(b, "sale_price_cents")
    sale_date = need_dt(b, "sale_date")
    comp_assessed = need_int(b, "comp_assessed_value_cents")
    if sale_price < 0:
        raise ApiError("ERR_INVALID_REQUEST", 422, "sale_price_cents must be >= 0")
    if comp_assessed < 0:
        raise ApiError("ERR_INVALID_REQUEST", 422, "comp_assessed_value_cents must be >= 0")
    adjustment_pct = opt_num(b, "adjustment_pct", 0.0)
    included = opt_bool(b, "included", True)
    rec = base_record()
    rec.update({
        "appeal_id": appeal["id"], "comp_address": comp_address,
        "sale_price_cents": sale_price, "sale_date": sale_date,
        "comp_assessed_value_cents": comp_assessed,
        "adjustment_pct": adjustment_pct,
        "adjusted_sale_value_cents": calc.adjusted_sale_value(sale_price, adjustment_pct),
        "included": included,
    })
    db.evidence[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/api/appeals/<rid>/evidence", methods=["GET"])
def list_evidence(rid):
    uid, role = require_auth()
    require_role(role, {"FirmAdmin", "Analyst"})
    must_exist(db.appeals, rid)
    items = [e for e in db.evidence.values() if e["appeal_id"] == rid]
    data, pg = paginate(items)
    return ok(data, 200, "array", pg)


# ==========================================================================
# Appeal — lifecycle actions
# ==========================================================================
@app.route("/api/appeals/<rid>/file", methods=["POST"])
def file_appeal(rid):
    uid, role = require_auth()
    require_role(role, {"Analyst"})
    appeal = must_exist(db.appeals, rid)
    if appeal["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "appeal is not DRAFT")
    assessment = domain.assessment_of_appeal(appeal)
    if assessment["status"] != "NOTICED":
        raise ApiError("ERR_ASSESSMENT_NOT_APPEALABLE", 409, "assessment is not NOTICED")
    jur = domain.jurisdiction_of_appeal(appeal)
    deadline = assessment["notice_date"].date() + datetime.timedelta(days=jur["filing_window_days"])
    if now().date() > deadline:
        raise ApiError("ERR_FILING_DEADLINE_PASSED", 409, "filing window has closed")
    included = domain.included_evidence(appeal["id"])
    if len(included) == 0:
        raise ApiError("ERR_NO_EVIDENCE", 422, "no included evidence for appeal")
    fa = domain.fee_agreement_of_appeal(appeal)
    requested = calc.opinion_of_value(appeal["valuation_method"], included, jur["equalization_ratio"])
    original = assessment["original_assessed_value_cents"]
    projected_savings = calc.tax_savings(original, requested, assessment["millage_rate"])
    appeal["requested_value_cents"] = requested
    appeal["projected_savings_cents"] = projected_savings
    appeal["projected_fee_cents"] = calc.contingency_fee(projected_savings, fa)
    appeal["projected_client_tax_bill_cents"] = calc.projected_client_tax_bill(
        requested, assessment["total_approved_exemption_cents"], assessment["millage_rate"])
    appeal["filed_date"] = now()
    appeal["status"] = "FILED"
    touch(appeal)
    # CASCADE: parent Assessment NOTICED -> UNDER_APPEAL.
    assessment["status"] = "UNDER_APPEAL"
    touch(assessment)
    return ok(serialize(appeal), 200)


@app.route("/api/appeals/<rid>/request-informal-review", methods=["POST"])
def request_informal_review(rid):
    uid, role = require_auth()
    require_role(role, {"Analyst"})
    appeal = must_exist(db.appeals, rid)
    if appeal["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409, "appeal is not FILED")
    jur = domain.jurisdiction_of_appeal(appeal)
    if not jur["informal_review_available"]:
        raise ApiError("ERR_INVALID_STATE", 409, "jurisdiction does not offer informal review")
    appeal["status"] = "INFORMAL_REVIEW"
    touch(appeal)
    return ok(serialize(appeal), 200)


def _overlaps(s1, e1, s2, e2):
    # half-open [s,e) intersection
    return s1 < e2 and s2 < e1


@app.route("/api/appeals/<rid>/hearings", methods=["POST"])
def schedule_hearing(rid):
    uid, role = require_auth()
    require_role(role, {"Analyst"})
    appeal = must_exist(db.appeals, rid)
    b = get_body()
    representative_id = b.get("representative_id")
    if representative_id is not None and representative_id not in db.analysts:
        raise ApiError("ERR_NOT_FOUND", 404, "representative does not exist")
    representative_id = need_str(b, "representative_id")
    docket_room = need_str(b, "docket_room")
    scheduled_start = need_dt(b, "scheduled_start")
    scheduled_end = need_dt(b, "scheduled_end")
    if appeal["status"] not in ("FILED", "INFORMAL_REVIEW"):
        raise ApiError("ERR_INVALID_STATE", 409, "appeal cannot schedule a hearing")
    jur = domain.jurisdiction_of_appeal(appeal)
    buffer_min = jur["rep_travel_buffer_minutes"]
    capacity = jur["hearing_room_capacity"]

    # Consider only SCHEDULED hearings in the same jurisdiction.
    scheduled = []
    for h in db.hearings.values():
        if h["status"] != "SCHEDULED":
            continue
        hj = domain.jurisdiction_of_appeal(db.appeals[h["appeal_id"]])
        if hj is None or hj["id"] != jur["id"]:
            continue
        scheduled.append(h)

    # (1) Representative travel buffer.
    for h in scheduled:
        if h["representative_id"] != representative_id:
            continue
        hs, he = h["scheduled_start"], h["scheduled_end"]
        if scheduled_start >= he:
            gap = (scheduled_start - he).total_seconds() / 60.0
        elif hs >= scheduled_end:
            gap = (hs - scheduled_end).total_seconds() / 60.0
        else:
            gap = -1.0  # overlapping intervals
        if gap < buffer_min:
            raise ApiError("ERR_REPRESENTATIVE_UNAVAILABLE", 409,
                           "representative lacks required travel buffer")

    # (2) Docket-room capacity.
    overlapping = 0
    for h in scheduled:
        if h["docket_room"] != docket_room:
            continue
        if _overlaps(scheduled_start, scheduled_end, h["scheduled_start"], h["scheduled_end"]):
            overlapping += 1
    if overlapping >= capacity:
        raise ApiError("ERR_DOCKET_ROOM_FULL", 409, "docket room is at capacity")

    # (3) Interval validity.
    if scheduled_end <= scheduled_start:
        raise ApiError("ERR_INVALID_VALUE", 422, "scheduled_end must be after scheduled_start")

    rec = base_record()
    rec.update({
        "appeal_id": appeal["id"], "representative_id": representative_id,
        "docket_room": docket_room, "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end, "status": "SCHEDULED", "outcome_note": None,
    })
    db.hearings[rec["id"]] = rec
    appeal["status"] = "HEARING_SCHEDULED"
    touch(appeal)
    return ok(serialize(rec), 201)


@app.route("/api/appeals/<rid>/record-decision", methods=["POST"])
def record_decision(rid):
    uid, role = require_auth()
    require_role(role, {"Analyst"})
    appeal = must_exist(db.appeals, rid)
    b = get_body()
    decision_value = need_int(b, "decision_value_cents")
    if appeal["status"] != "HEARING_SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "appeal is not HEARING_SCHEDULED")
    held = any(h["appeal_id"] == appeal["id"] and h["status"] == "HELD"
               for h in db.hearings.values())
    if not held:
        raise ApiError("ERR_NO_HELD_HEARING", 409, "no HELD hearing on the appeal")
    assessment = domain.assessment_of_appeal(appeal)
    original = assessment["original_assessed_value_cents"]
    if not (0 <= decision_value <= original):
        raise ApiError("ERR_INVALID_VALUE", 422, "decision_value_cents out of range")
    appeal["decision_value_cents"] = decision_value
    appeal["outcome_source"] = "HEARING_DECISION"
    appeal["decision_date"] = now()
    appeal["realized_savings_cents"] = calc.tax_savings(original, decision_value, assessment["millage_rate"])
    appeal["status"] = "DECIDED"
    touch(appeal)
    # CASCADE link1: Assessment UNDER_APPEAL -> FINALIZED.
    domain.finalize_assessment(assessment, decision_value)
    # CASCADE link2: always create a DRAFT invoice.
    domain.create_terminal_invoice(appeal, appeal["realized_savings_cents"])
    return ok(serialize(appeal), 200)


@app.route("/api/appeals/<rid>/withdraw", methods=["POST"])
def withdraw_appeal(rid):
    uid, role = require_auth()
    require_role(role, {"Analyst"})
    appeal = must_exist(db.appeals, rid)
    if appeal["status"] not in ("FILED", "INFORMAL_REVIEW", "HEARING_SCHEDULED"):
        raise ApiError("ERR_INVALID_STATE", 409, "appeal cannot be withdrawn")
    appeal["status"] = "WITHDRAWN"
    touch(appeal)
    # COMPENSATION: Assessment UNDER_APPEAL -> NOTICED (assessed_value unchanged).
    assessment = domain.assessment_of_appeal(appeal)
    if assessment["status"] == "UNDER_APPEAL":
        assessment["status"] = "NOTICED"
        touch(assessment)
    # Void any DRAFT invoice for this appeal.
    for inv in db.invoices.values():
        if inv["appeal_id"] == appeal["id"] and inv["status"] == "DRAFT":
            inv["status"] = "VOID"
            touch(inv)
    return ok(serialize(appeal), 200)


# ==========================================================================
# SettlementOffer — create + list (under appeal)
# ==========================================================================
@app.route("/api/appeals/<rid>/settlement-offers", methods=["POST"])
def create_settlement_offer(rid):
    uid, role = require_auth()
    require_role(role, {"Analyst"})
    appeal = must_exist(db.appeals, rid)
    b = get_body()
    proposed_by = need_enum(b, "proposed_by", {"FIRM", "JURISDICTION"})
    offer_value = need_int(b, "offer_value_cents")
    expires_at = need_dt(b, "expires_at")
    expected_version = need_int(b, "expected_appeal_version")
    if offer_value < 0:
        raise ApiError("ERR_INVALID_VALUE", 422, "offer_value_cents must be >= 0")
    if expected_version != appeal["version"]:
        raise ApiError("ERR_STALE_APPEAL_VERSION", 412, "expected_appeal_version is stale")
    rec = base_record()
    rec.update({
        "appeal_id": appeal["id"], "proposed_by": proposed_by,
        "offer_value_cents": offer_value, "round_number": 1,
        "created_by_analyst_id": uid, "accepted_by_analyst_id": None,
        "expires_at": expires_at, "status": "PROPOSED",
    })
    db.settlement_offers[rec["id"]] = rec
    # Successful create bumps the parent appeal's version.
    touch(appeal)
    return ok(serialize(rec), 201)


@app.route("/api/appeals/<rid>/settlement-offers", methods=["GET"])
def list_settlement_offers(rid):
    uid, role = require_auth()
    require_role(role, {"FirmAdmin", "Analyst", "Client"})
    appeal = must_exist(db.appeals, rid)
    if role == "Client" and domain.client_of_appeal(appeal) != uid:
        forbidden_owner()
    items = [o for o in db.settlement_offers.values() if o["appeal_id"] == rid]
    data, pg = paginate(items)
    return ok(data, 200, "array", pg)


# ==========================================================================
# SettlementOffer — fetch / counter / accept / reject
# ==========================================================================
@app.route("/api/settlement-offers/<rid>", methods=["GET"])
def get_settlement_offer(rid):
    uid, role = require_auth()
    require_role(role, {"FirmAdmin", "Analyst", "Client"})
    rec = must_exist(db.settlement_offers, rid)
    if role == "Client" and domain.client_of_offer(rec) != uid:
        forbidden_owner()
    return ok(serialize(rec), 200)


@app.route("/api/settlement-offers/<rid>/counter", methods=["POST"])
def counter_settlement_offer(rid):
    uid, role = require_auth()
    require_role(role, {"Analyst", "Client"})
    rec = must_exist(db.settlement_offers, rid)
    b = get_body()
    offer_value = need_int(b, "offer_value_cents")
    if offer_value < 0:
        raise ApiError("ERR_INVALID_VALUE", 422, "offer_value_cents must be >= 0")
    appeal = db.appeals.get(rec["appeal_id"])
    if rec["status"] == "PROPOSED":
        if appeal is None or appeal["status"] not in domain.LIVE_APPEAL:
            raise ApiError("ERR_INVALID_STATE", 409, "parent appeal is not in a live state")
        rec["offer_value_cents"] = offer_value
        rec["proposed_by"] = "JURISDICTION" if rec["proposed_by"] == "FIRM" else "FIRM"
        rec["status"] = "COUNTERED"
    elif rec["status"] == "COUNTERED":
        rec["round_number"] += 1
        rec["status"] = "PROPOSED"
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "offer cannot be countered")
    touch(rec)
    return ok(serialize(rec), 200)


@app.route("/api/settlement-offers/<rid>/accept", methods=["POST"])
def accept_settlement_offer(rid):
    uid, role = require_auth()
    require_role(role, {"Analyst"})
    rec = must_exist(db.settlement_offers, rid)
    if rec["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "offer is not PROPOSED")
    if uid == rec["created_by_analyst_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403, "acceptor must differ from creator")
    if now() > rec["expires_at"]:
        raise ApiError("ERR_OFFER_EXPIRED", 409, "offer has expired")
    appeal = db.appeals.get(rec["appeal_id"])
    if appeal is None or appeal["status"] not in domain.LIVE_APPEAL:
        raise ApiError("ERR_INVALID_STATE", 409, "parent appeal is not in a live state")
    # Accept the offer.
    rec["status"] = "ACCEPTED"
    rec["accepted_by_analyst_id"] = uid
    touch(rec)
    # Drive the appeal to SETTLED.
    assessment = domain.assessment_of_appeal(appeal)
    settlement_value = rec["offer_value_cents"]
    appeal["settlement_value_cents"] = settlement_value
    appeal["outcome_source"] = "SETTLEMENT"
    appeal["realized_savings_cents"] = calc.tax_savings(
        assessment["original_assessed_value_cents"], settlement_value, assessment["millage_rate"])
    appeal["status"] = "SETTLED"
    touch(appeal)
    domain.finalize_assessment(assessment, settlement_value)
    domain.create_terminal_invoice(appeal, appeal["realized_savings_cents"])
    return ok(serialize(rec), 200)


@app.route("/api/settlement-offers/<rid>/reject", methods=["POST"])
def reject_settlement_offer(rid):
    uid, role = require_auth()
    require_role(role, {"Analyst", "Client"})
    rec = must_exist(db.settlement_offers, rid)
    if rec["status"] not in ("PROPOSED", "COUNTERED"):
        raise ApiError("ERR_INVALID_STATE", 409, "offer cannot be rejected")
    rec["status"] = "REJECTED"
    touch(rec)
    return ok(serialize(rec), 200)


# ==========================================================================
# Hearing — fetch / list / hold / cancel
# ==========================================================================
@app.route("/api/hearings/<rid>", methods=["GET"])
def get_hearing(rid):
    uid, role = require_auth()
    require_role(role, {"FirmAdmin", "Analyst"})
    rec = must_exist(db.hearings, rid)
    return ok(serialize(rec), 200)


@app.route("/api/hearings", methods=["GET"])
def list_hearings():
    uid, role = require_auth()
    require_role(role, {"FirmAdmin", "Analyst"})
    items = list(db.hearings.values())
    for key in ("appeal_id", "representative_id"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r[key] == val]
    data, pg = paginate(items)
    return ok(data, 200, "array", pg)


@app.route("/api/hearings/<rid>/hold", methods=["POST"])
def hold_hearing(rid):
    uid, role = require_auth()
    require_role(role, {"Analyst"})
    rec = must_exist(db.hearings, rid)
    b = get_body()
    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "hearing is not SCHEDULED")
    rec["outcome_note"] = opt_str(b, "outcome_note", rec.get("outcome_note"))
    rec["status"] = "HELD"
    touch(rec)
    return ok(serialize(rec), 200)


@app.route("/api/hearings/<rid>/cancel", methods=["POST"])
def cancel_hearing(rid):
    uid, role = require_auth()
    require_role(role, {"Analyst"})
    rec = must_exist(db.hearings, rid)
    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "hearing is not SCHEDULED")
    rec["status"] = "CANCELLED"
    touch(rec)
    return ok(serialize(rec), 200)


# ==========================================================================
# Invoice / Payment
# ==========================================================================
@app.route("/api/invoices/<rid>", methods=["GET"])
def get_invoice(rid):
    uid, role = require_auth()
    require_role(role, {"FirmAdmin", "Billing", "Client"})
    rec = must_exist(db.invoices, rid)
    if role == "Client" and domain.client_of_invoice(rec) != uid:
        forbidden_owner()
    return ok(serialize(rec), 200)


@app.route("/api/invoices", methods=["GET"])
def list_invoices():
    uid, role = require_auth()
    require_role(role, {"FirmAdmin", "Billing", "Client"})
    items = list(db.invoices.values())
    appeal_id = request.args.get("appeal_id")
    if appeal_id is not None:
        items = [r for r in items if r["appeal_id"] == appeal_id]
    if role == "Client":
        items = [r for r in items if domain.client_of_invoice(r) == uid]
    data, pg = paginate(items)
    return ok(data, 200, "array", pg)


@app.route("/api/invoices/<rid>/issue", methods=["POST"])
def issue_invoice(rid):
    uid, role = require_auth()
    require_role(role, {"Billing"})
    rec = must_exist(db.invoices, rid)
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "invoice is not DRAFT")
    appeal = db.appeals.get(rec["appeal_id"])
    fa = domain.fee_agreement_of_appeal(appeal) if appeal else None
    if fa is None or fa["status"] != "ACTIVE":
        raise ApiError("ERR_FEE_AGREEMENT_NOT_ACTIVE", 409, "fee agreement is not ACTIVE")
    if rec["gross_savings_cents"] <= 0:
        raise ApiError("ERR_NO_BILLABLE_SAVINGS", 409, "no positive savings to bill")
    rec["issued_date"] = now()
    rec["status"] = "ISSUED"
    touch(rec)
    cid = domain.client_of_invoice(rec)
    client = db.clients.get(cid)
    if client is not None:
        client["lifetime_fees_billed_cents"] += rec["fee_amount_cents"]
        client["outstanding_balance_cents"] += rec["fee_amount_cents"]
        touch(client)
    return ok(serialize(rec), 200)


@app.route("/api/invoices/<rid>/void", methods=["POST"])
def void_invoice(rid):
    uid, role = require_auth()
    require_role(role, {"FirmAdmin"})
    rec = must_exist(db.invoices, rid)
    if rec["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "invoice is not ISSUED")
    rec["status"] = "VOID"
    touch(rec)
    cid = domain.client_of_invoice(rec)
    client = db.clients.get(cid)
    if client is not None:
        client["lifetime_fees_billed_cents"] -= rec["fee_amount_cents"]
        client["outstanding_balance_cents"] -= (rec["fee_amount_cents"] - rec["amount_paid_cents"])
        touch(client)
    return ok(serialize(rec), 200)


@app.route("/api/invoices/<rid>/payments", methods=["POST"])
def create_payment(rid):
    uid, role = require_auth()
    require_role(role, {"Billing", "Client"})
    invoice = must_exist(db.invoices, rid)
    b = get_body()
    amount = need_int(b, "amount_cents")
    method = need_enum(b, "method", {"CHECK", "CARD", "ACH"})
    if amount <= 0:
        raise ApiError("ERR_INVALID_VALUE", 422, "amount_cents must be > 0")
    if invoice["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "invoice is not ISSUED")
    pay = base_record(with_version=False)
    pay.update({"invoice_id": invoice["id"], "amount_cents": amount,
                "method": method, "received_date": now()})
    db.payments[pay["id"]] = pay
    # Recompute amount_paid from all payments on this invoice.
    invoice["amount_paid_cents"] = sum(
        p["amount_cents"] for p in db.payments.values() if p["invoice_id"] == invoice["id"])
    if invoice["amount_paid_cents"] >= invoice["fee_amount_cents"] and invoice["status"] == "ISSUED":
        invoice["status"] = "PAID"
        invoice["paid_date"] = now()
    touch(invoice)
    cid = domain.client_of_invoice(invoice)
    client = db.clients.get(cid)
    if client is not None:
        client["outstanding_balance_cents"] -= amount
        touch(client)
    return ok(serialize(pay), 201)


@app.route("/api/invoices/<rid>/payments", methods=["GET"])
def list_payments(rid):
    uid, role = require_auth()
    require_role(role, {"FirmAdmin", "Billing", "Client"})
    invoice = must_exist(db.invoices, rid)
    if role == "Client" and domain.client_of_invoice(invoice) != uid:
        forbidden_owner()
    items = [p for p in db.payments.values() if p["invoice_id"] == rid]
    data, pg = paginate(items)
    return ok(data, 200, "array", pg)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
