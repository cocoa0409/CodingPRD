"""TIF District & Increment Accounting API — Flask entry point."""
import os

from flask import Flask, request, g

import calc
from core import (
    ApiError, db, make_entity, bump, serialize, success, error_response,
    list_response, authenticate, require_role, get_body, require_present,
    as_int, as_number, as_str, as_enum, now_iso,
)

app = Flask(__name__)
app.url_map.strict_slashes = False

TERMINAL_OBLIGATION = {"SATISFIED", "DEFEASED", "DEFAULTED", "REJECTED"}


# ---------------------------------------------------------------------------
# Error handling + keep-alive avoidance
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(_e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(_e):
    return error_response(ApiError("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_INTERNAL", 500, str(err)))


@app.after_request
def add_conn_close(resp):
    resp.headers["Connection"] = "close"
    return resp


# ---------------------------------------------------------------------------
# Entity getters (raise not-found)
# ---------------------------------------------------------------------------
def get_district(did):
    d = db.districts.get(did)
    if d is None:
        raise ApiError("ERR_DISTRICT_NOT_FOUND", 404, "District not found")
    return d


def get_taxing_body(tid):
    t = db.taxing_bodies.get(tid)
    if t is None:
        raise ApiError("ERR_TAXING_BODY_NOT_FOUND", 404, "Taxing body not found")
    return t


def get_developer(did):
    d = db.developers.get(did)
    if d is None:
        raise ApiError("ERR_DEVELOPER_NOT_FOUND", 404, "Developer not found")
    return d


def get_obligation(oid):
    o = db.obligations.get(oid)
    if o is None:
        raise ApiError("ERR_OBLIGATION_NOT_FOUND", 404, "Obligation not found")
    return o


def get_increment_record(rid):
    r = db.increment_records.get(rid)
    if r is None:
        raise ApiError("ERR_INCREMENT_RECORD_NOT_FOUND", 404, "Increment record not found")
    return r


def get_disbursement(did):
    d = db.disbursements.get(did)
    if d is None:
        raise ApiError("ERR_DISBURSEMENT_NOT_FOUND", 404, "Disbursement not found")
    return d


def get_annual_report(rid):
    r = db.annual_reports.get(rid)
    if r is None:
        raise ApiError("ERR_ANNUAL_REPORT_NOT_FOUND", 404, "Annual report not found")
    return r


def get_fund(district_id):
    for f in db.project_funds.values():
        if f["district_id"] == district_id:
            return f
    return None


def district_taxing_bodies(district_id):
    return [t for t in db.taxing_bodies.values() if t["district_id"] == district_id]


def district_obligations(district_id):
    return [o for o in db.obligations.values() if o["district_id"] == district_id]


def recompute_obligations_cleared(district):
    obs = district_obligations(district["id"])
    if obs:
        district["obligations_cleared"] = all(o["status"] in TERMINAL_OBLIGATION for o in obs)
    else:
        district["obligations_cleared"] = False


# ---------------------------------------------------------------------------
# TifDistrict
# ---------------------------------------------------------------------------
@app.post("/tif-districts")
def create_district():
    authenticate()
    require_role(["MunicipalAdmin"])
    body = get_body()
    name = as_str(require_present(body, "name"), "name")
    municipality_name = as_str(require_present(body, "municipality_name"), "municipality_name")
    base_tax_year = as_int(require_present(body, "base_tax_year"), "base_tax_year")
    base_eav_cents = as_int(require_present(body, "base_eav_cents"), "base_eav_cents", exclusive_min=0)
    term_years = as_int(require_present(body, "term_years"), "term_years", minimum=1, maximum=23)
    surplus_policy = body.get("surplus_policy")
    if surplus_policy is None:
        surplus_policy = "GROSS"
    else:
        surplus_policy = as_enum(surplus_policy, "surplus_policy", {"GROSS", "NET"})

    ent = make_entity({
        "name": name,
        "municipality_name": municipality_name,
        "base_tax_year": base_tax_year,
        "base_eav_cents": base_eav_cents,
        "term_years": term_years,
        "surplus_policy": surplus_policy,
        "certification_date": None,
        "expiration_tax_year": None,
        "aggregate_tax_rate": None,
        "obligations_cleared": False,
        "status": "DRAFT",
    })
    db.districts[ent["id"]] = ent
    return success(serialize(ent), status=201)


@app.get("/tif-districts")
def list_districts():
    authenticate()
    items = list(db.districts.values())
    status = request.args.get("status")
    if status:
        items = [d for d in items if d["status"] == status]
    return list_response(items)


@app.get("/tif-districts/<did>")
def read_district(did):
    authenticate()
    return success(serialize(get_district(did)))


@app.post("/tif-districts/<did>/certify")
def certify_district(did):
    authenticate()
    require_role(["MunicipalAdmin"])
    d = get_district(did)
    if d["status"] != "DRAFT":
        raise ApiError("ERR_DISTRICT_NOT_DRAFT", 409, "District is not in DRAFT")
    bodies = district_taxing_bodies(did)
    if len(bodies) < 1:
        raise ApiError("ERR_NO_TAXING_BODIES", 409, "District has no taxing bodies")
    if d["base_eav_cents"] <= 0:
        raise ApiError("ERR_VALIDATION", 422, "base_eav_cents must be > 0")

    agg_dec = sum((calc.dec(b["tax_rate"]) for b in bodies), calc.Decimal(0))
    d["_agg_rate_dec"] = agg_dec
    d["aggregate_tax_rate"] = float(agg_dec)
    d["expiration_tax_year"] = d["base_tax_year"] + d["term_years"]
    d["certification_date"] = now_iso()
    d["status"] = "CERTIFIED"
    bump(d)

    fund = make_entity({
        "district_id": did,
        "balance_cents": 0,
        "lifetime_increment_cents": 0,
        "lifetime_disbursed_cents": 0,
        "lifetime_surplus_cents": 0,
        "lifetime_admin_fee_cents": 0,
        "status": "OPEN",
    })
    db.project_funds[fund["id"]] = fund
    return success(serialize(d))


def _agg_rate_dec(district):
    dec_val = district.get("_agg_rate_dec")
    if dec_val is None:
        # fall back to stored float
        dec_val = calc.dec(district.get("aggregate_tax_rate") or 0)
    return dec_val


@app.post("/tif-districts/<did>/decertify")
def decertify_district(did):
    authenticate()
    require_role(["MunicipalAdmin"])
    d = get_district(did)
    body = get_body()
    termination_type = as_enum(require_present(body, "termination_type"),
                               "termination_type", {"EXPIRATION", "EARLY"})
    termination_tax_year = as_int(require_present(body, "termination_tax_year"),
                                  "termination_tax_year")

    if d["status"] == "DECERTIFIED":
        raise ApiError("ERR_DISTRICT_ALREADY_DECERTIFIED", 409, "District already decertified")
    if d["status"] != "CERTIFIED":
        raise ApiError("ERR_DISTRICT_NOT_CERTIFIED", 409, "District is not CERTIFIED")

    if termination_type == "EXPIRATION":
        if termination_tax_year < d["expiration_tax_year"]:
            raise ApiError("ERR_TERM_NOT_EXPIRED", 409, "Term not expired")
    else:  # EARLY
        if termination_tax_year >= d["expiration_tax_year"]:
            raise ApiError("ERR_EARLY_TERM_NOT_ALLOWED", 409, "Early termination not allowed")

    # Senior bond obligations must be cleared.
    for o in district_obligations(did):
        if o["obligation_type"] == "BOND" and o["status"] == "REGISTERED":
            raise ApiError("ERR_SENIOR_OBLIGATION_OUTSTANDING", 409,
                           "A senior bond obligation is still outstanding")

    # Resolve subordinate developer notes.
    for o in district_obligations(did):
        if o["obligation_type"] == "DEVELOPER_NOTE" and o["status"] == "REGISTERED":
            if termination_type == "EXPIRATION":
                o["principal_remaining_cents"] = 0
                o["accrued_interest_cents"] = 0
                o["outstanding_balance_cents"] = 0
                o["status"] = "DEFEASED"
            else:
                o["status"] = "DEFAULTED"
            bump(o)

    # Sweep remaining fund balance to taxing bodies.
    fund = get_fund(did)
    swept = 0
    if fund is not None:
        swept = fund["balance_cents"]
        if swept > 0:
            _distribute_surplus(d, fund, swept, termination_tax_year, "DECERTIFICATION")
        fund["balance_cents"] = 0
        fund["lifetime_surplus_cents"] += swept
        fund["status"] = "CLOSED"
        bump(fund)

    d["obligations_cleared"] = True
    d["status"] = "DECERTIFIED"
    bump(d)
    return success(serialize(d))


def _distribute_surplus(district, fund, amount, report_tax_year, source):
    """Create SurplusDistribution rows for every taxing body. amount > 0."""
    bodies = sorted(district_taxing_bodies(district["id"]),
                    key=lambda b: (b["created_at"], b["_seq"]))
    agreements = [a for a in db.surplus_agreements.values()
                  if a["district_id"] == district["id"]]
    allocation = calc.surplus_split(bodies, agreements, report_tax_year, amount)
    for row in allocation:
        b = row["body"]
        dist = make_entity({
            "district_id": district["id"],
            "taxing_body_id": b["id"],
            "source": source,
            "report_tax_year": report_tax_year,
            "amount_cents": row["amount_cents"],
            "share_ppm": row["share_ppm"],
        }, common=False)
        db.surplus_distributions[dist["id"]] = dist
        b["total_surplus_received_cents"] += row["amount_cents"]
        bump(b)


# ---------------------------------------------------------------------------
# TifDistrict reverse lookups
# ---------------------------------------------------------------------------
@app.get("/tif-districts/<did>/project-fund")
def district_project_fund(did):
    authenticate()
    get_district(did)
    fund = get_fund(did)
    return list_response([fund] if fund is not None else [])


@app.get("/tif-districts/<did>/taxing-bodies")
def district_taxing_bodies_list(did):
    authenticate()
    get_district(did)
    return list_response(district_taxing_bodies(did))


@app.get("/tif-districts/<did>/obligations")
def district_obligations_list(did):
    authenticate()
    get_district(did)
    items = district_obligations(did)
    status = request.args.get("status")
    if status:
        items = [o for o in items if o["status"] == status]
    return list_response(items)


@app.get("/tif-districts/<did>/increment-records")
def district_increment_records(did):
    authenticate()
    get_district(did)
    items = [r for r in db.increment_records.values() if r["district_id"] == did]
    return list_response(items)


@app.get("/tif-districts/<did>/annual-reports")
def district_annual_reports(did):
    authenticate()
    get_district(did)
    items = [r for r in db.annual_reports.values() if r["district_id"] == did]
    return list_response(items)


@app.get("/tif-districts/<did>/surplus-agreements")
def district_surplus_agreements(did):
    authenticate()
    get_district(did)
    items = [a for a in db.surplus_agreements.values() if a["district_id"] == did]
    return list_response(items)


@app.get("/tif-districts/<did>/surplus-distributions")
def district_surplus_distributions(did):
    authenticate()
    get_district(did)
    items = [s for s in db.surplus_distributions.values() if s["district_id"] == did]
    source = request.args.get("source")
    if source:
        items = [s for s in items if s["source"] == source]
    return list_response(items)


# ---------------------------------------------------------------------------
# TaxingBody
# ---------------------------------------------------------------------------
@app.post("/tif-districts/<did>/taxing-bodies")
def create_taxing_body(did):
    authenticate()
    require_role(["MunicipalAdmin"])
    d = get_district(did)
    body = get_body()
    name = as_str(require_present(body, "name"), "name")
    body_type = as_enum(require_present(body, "body_type"), "body_type",
                        {"SCHOOL", "COUNTY", "MUNICIPAL", "PARK", "LIBRARY", "OTHER"})
    tax_rate = as_number(require_present(body, "tax_rate"), "tax_rate")
    if not (0 < tax_rate < 1):
        raise ApiError("ERR_VALIDATION", 422, "tax_rate must be > 0 and < 1")
    if d["status"] != "DRAFT":
        raise ApiError("ERR_DISTRICT_NOT_DRAFT", 409, "District is not in DRAFT")

    ent = make_entity({
        "district_id": did,
        "name": name,
        "body_type": body_type,
        "tax_rate": tax_rate,
        "total_surplus_received_cents": 0,
    })
    db.taxing_bodies[ent["id"]] = ent
    return success(serialize(ent), status=201)


@app.get("/taxing-bodies/<tid>")
def read_taxing_body(tid):
    authenticate()
    return success(serialize(get_taxing_body(tid)))


@app.get("/taxing-bodies/<tid>/surplus-distributions")
def taxing_body_distributions(tid):
    authenticate()
    get_taxing_body(tid)
    items = [s for s in db.surplus_distributions.values() if s["taxing_body_id"] == tid]
    return list_response(items)


@app.get("/taxing-bodies/<tid>/surplus-agreements")
def taxing_body_agreements(tid):
    authenticate()
    get_taxing_body(tid)
    items = [a for a in db.surplus_agreements.values() if a["taxing_body_id"] == tid]
    return list_response(items)


# ---------------------------------------------------------------------------
# Developer
# ---------------------------------------------------------------------------
@app.post("/developers")
def create_developer():
    authenticate()
    require_role(["MunicipalAdmin"])
    body = get_body()
    legal_name = as_str(require_present(body, "legal_name"), "legal_name")
    contact_email = as_str(require_present(body, "contact_email"), "contact_email")
    ent = make_entity({
        "legal_name": legal_name,
        "contact_email": contact_email,
    })
    db.developers[ent["id"]] = ent
    return success(serialize(ent), status=201)


@app.get("/developers/<did>")
def read_developer(did):
    authenticate()
    return success(serialize(get_developer(did)))


@app.get("/developers/<did>/obligations")
def developer_obligations(did):
    authenticate()
    get_developer(did)
    items = [o for o in db.obligations.values() if o.get("developer_id") == did]
    return list_response(items)


# ---------------------------------------------------------------------------
# Obligation
# ---------------------------------------------------------------------------
@app.post("/obligations")
def create_obligation():
    authenticate()
    require_role(["Developer", "MunicipalAdmin"])
    body = get_body()

    # Ownership / role-type gate (authorization) before field validation.
    otype_raw = body.get("obligation_type")
    dev_id_raw = body.get("developer_id")
    if g.role == "Developer":
        if otype_raw != "DEVELOPER_NOTE":
            raise ApiError("ERR_UNAUTHORIZED", 403, "Developer may only propose developer notes")
        if dev_id_raw != g.user_id:
            raise ApiError("ERR_UNAUTHORIZED", 403, "Developer may only act on its own notes")
    else:  # MunicipalAdmin
        if otype_raw == "DEVELOPER_NOTE":
            raise ApiError("ERR_UNAUTHORIZED", 403, "MunicipalAdmin proposes bonds only")

    district_id = as_str(require_present(body, "district_id"), "district_id")
    obligation_type = as_enum(require_present(body, "obligation_type"),
                              "obligation_type", {"DEVELOPER_NOTE", "BOND"})
    principal_cents = as_int(require_present(body, "principal_cents"),
                             "principal_cents", exclusive_min=0)
    interest_rate_bps = as_int(require_present(body, "interest_rate_bps"),
                               "interest_rate_bps", minimum=0)
    issue_tax_year = as_int(require_present(body, "issue_tax_year"), "issue_tax_year")
    final_maturity_tax_year = as_int(require_present(body, "final_maturity_tax_year"),
                                     "final_maturity_tax_year")
    if final_maturity_tax_year < issue_tax_year:
        raise ApiError("ERR_VALIDATION", 422, "final_maturity_tax_year < issue_tax_year")
    annual_cap_cents = body.get("annual_cap_cents")
    if annual_cap_cents is not None:
        annual_cap_cents = as_int(annual_cap_cents, "annual_cap_cents", exclusive_min=0)

    developer_id = None
    if obligation_type == "DEVELOPER_NOTE":
        developer_id = as_str(require_present(body, "developer_id"), "developer_id")

    # Referential integrity.
    get_district(district_id)
    if obligation_type == "DEVELOPER_NOTE":
        get_developer(developer_id)

    ent = make_entity({
        "district_id": district_id,
        "developer_id": developer_id,
        "obligation_type": obligation_type,
        "principal_cents": principal_cents,
        "interest_rate_bps": interest_rate_bps,
        "issue_tax_year": issue_tax_year,
        "final_maturity_tax_year": final_maturity_tax_year,
        "annual_cap_cents": annual_cap_cents,
        "seniority": None,
        "priority_rank": None,
        "principal_remaining_cents": 0,
        "accrued_interest_cents": 0,
        "outstanding_balance_cents": 0,
        "registered_by_user_id": None,
        "status": "PROPOSED",
    })
    db.obligations[ent["id"]] = ent
    return success(serialize(ent), status=201)


@app.get("/obligations/<oid>")
def read_obligation(oid):
    authenticate()
    return success(serialize(get_obligation(oid)))


@app.post("/obligations/<oid>/submit")
def submit_obligation(oid):
    authenticate()
    require_role(["Developer", "MunicipalAdmin"])
    o = get_obligation(oid)
    if g.role == "Developer":
        if o["obligation_type"] != "DEVELOPER_NOTE" or o.get("developer_id") != g.user_id:
            raise ApiError("ERR_UNAUTHORIZED", 403, "Developer may only submit its own note")
    if o["status"] != "PROPOSED":
        raise ApiError("ERR_OBLIGATION_INVALID_STATE", 409, "Obligation is not PROPOSED")
    o["status"] = "UNDER_REVIEW"
    bump(o)
    return success(serialize(o))


@app.post("/obligations/<oid>/register")
def register_obligation(oid):
    authenticate()
    require_role(["MunicipalAdmin"])
    o = get_obligation(oid)
    body = get_body()
    priority_rank = as_int(require_present(body, "priority_rank"), "priority_rank")
    expected_district_version = as_int(require_present(body, "expected_district_version"),
                                       "expected_district_version")

    if o["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_OBLIGATION_NOT_IN_REVIEW", 409, "Obligation is not UNDER_REVIEW")
    d = get_district(o["district_id"])
    if d["status"] != "CERTIFIED":
        raise ApiError("ERR_DISTRICT_NOT_CERTIFIED", 409, "District is not CERTIFIED")
    if o["final_maturity_tax_year"] > d["expiration_tax_year"]:
        raise ApiError("ERR_BOND_MATURITY_OUT_OF_TERM", 409, "Maturity beyond district term")
    if expected_district_version != d["version"]:
        raise ApiError("ERR_STALE_DISTRICT_VERSION", 412, "Stale district version")

    o["seniority"] = "SENIOR" if o["obligation_type"] == "BOND" else "SUBORDINATE"
    o["priority_rank"] = priority_rank
    o["principal_remaining_cents"] = o["principal_cents"]
    o["accrued_interest_cents"] = 0
    o["outstanding_balance_cents"] = o["principal_cents"]
    o["registered_by_user_id"] = g.user_id
    o["status"] = "REGISTERED"
    bump(o)
    bump(d)
    return success(serialize(o))


@app.post("/obligations/<oid>/return")
def return_obligation(oid):
    authenticate()
    require_role(["MunicipalAdmin"])
    o = get_obligation(oid)
    if o["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_OBLIGATION_NOT_IN_REVIEW", 409, "Obligation is not UNDER_REVIEW")
    o["status"] = "PROPOSED"
    bump(o)
    return success(serialize(o))


@app.post("/obligations/<oid>/reject")
def reject_obligation(oid):
    authenticate()
    require_role(["MunicipalAdmin"])
    o = get_obligation(oid)
    if o["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_OBLIGATION_NOT_IN_REVIEW", 409, "Obligation is not UNDER_REVIEW")
    o["status"] = "REJECTED"
    bump(o)
    recompute_obligations_cleared(get_district(o["district_id"]))
    return success(serialize(o))


@app.post("/obligations/<oid>/accrue-interest")
def accrue_interest_obligation(oid):
    authenticate()
    require_role(["MunicipalAdmin"])
    o = get_obligation(oid)
    body = get_body()
    as_int(require_present(body, "accrual_tax_year"), "accrual_tax_year")
    if o["status"] != "REGISTERED":
        raise ApiError("ERR_OBLIGATION_INVALID_STATE", 409, "Obligation is not REGISTERED")
    period = calc.accrue_interest(o["principal_remaining_cents"], o["interest_rate_bps"])
    o["accrued_interest_cents"] += period
    o["outstanding_balance_cents"] = o["principal_remaining_cents"] + o["accrued_interest_cents"]
    bump(o)
    return success(serialize(o))


# ---------------------------------------------------------------------------
# Disbursement
# ---------------------------------------------------------------------------
@app.post("/obligations/<oid>/disbursements")
def create_disbursement(oid):
    authenticate()
    require_role(["MunicipalAdmin"])
    o = get_obligation(oid)
    body = get_body()

    # Body well-formedness.
    if "amount_cents" not in body or body["amount_cents"] is None:
        raise ApiError("ERR_VALIDATION", 422, "Missing required field: amount_cents")
    amount_cents = body["amount_cents"]
    if isinstance(amount_cents, bool) or not isinstance(amount_cents, int):
        raise ApiError("ERR_VALIDATION", 422, "amount_cents must be an integer")
    if amount_cents <= 0:
        raise ApiError("ERR_AMOUNT_NOT_POSITIVE", 422, "amount_cents must be > 0")
    disbursement_tax_year = as_int(require_present(body, "disbursement_tax_year"),
                                   "disbursement_tax_year")
    expected_fund_version = as_int(require_present(body, "expected_fund_version"),
                                   "expected_fund_version")

    # State.
    if o["status"] != "REGISTERED":
        raise ApiError("ERR_OBLIGATION_NOT_REGISTERED", 409, "Obligation is not REGISTERED")
    d = get_district(o["district_id"])
    if d["status"] != "CERTIFIED":
        raise ApiError("ERR_DISTRICT_NOT_CERTIFIED", 409, "District is not CERTIFIED")

    # Four-eyes segregation of duties.
    if g.user_id == o.get("registered_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403, "Registrar may not disburse")

    # Seniority ordering.
    if o["seniority"] == "SUBORDINATE":
        for other in district_obligations(d["id"]):
            if other["seniority"] == "SENIOR" and other["outstanding_balance_cents"] > 0:
                raise ApiError("ERR_SENIORITY_ORDER_VIOLATION", 409,
                               "Senior obligation still outstanding")

    fund = get_fund(d["id"])
    balance = fund["balance_cents"] if fund else 0
    outstanding = o["outstanding_balance_cents"]

    # Annual cap remaining.
    if o["annual_cap_cents"] is not None:
        paid_this_year = sum(
            x["amount_cents"] for x in db.disbursements.values()
            if x["obligation_id"] == oid and x["status"] == "PAID"
            and x["disbursement_tax_year"] == disbursement_tax_year
        )
        cap_remaining = o["annual_cap_cents"] - paid_this_year
    else:
        cap_remaining = None

    # Fiscal capacity.
    if amount_cents > balance:
        raise ApiError("ERR_INSUFFICIENT_FUND_BALANCE", 402, "Amount exceeds fund balance")
    if cap_remaining is not None and amount_cents > cap_remaining:
        raise ApiError("ERR_DISBURSEMENT_CAP_EXCEEDED", 402, "Amount exceeds annual cap")
    if amount_cents > outstanding:
        raise ApiError("ERR_DISBURSEMENT_CAP_EXCEEDED", 402, "Amount exceeds outstanding balance")

    # OCC.
    if expected_fund_version != fund["version"]:
        raise ApiError("ERR_STALE_FUND_VERSION", 412, "Stale fund version")

    interest_portion = min(amount_cents, o["accrued_interest_cents"])
    principal_portion = amount_cents - interest_portion

    o["accrued_interest_cents"] -= interest_portion
    o["principal_remaining_cents"] -= principal_portion
    o["outstanding_balance_cents"] -= amount_cents

    caused_satisfy = False
    if o["outstanding_balance_cents"] == 0:
        o["status"] = "SATISFIED"
        caused_satisfy = True
    bump(o)
    if caused_satisfy:
        recompute_obligations_cleared(d)

    fund["balance_cents"] -= amount_cents
    fund["lifetime_disbursed_cents"] += amount_cents
    bump(fund)

    dis = make_entity({
        "obligation_id": oid,
        "amount_cents": amount_cents,
        "interest_portion_cents": interest_portion,
        "principal_portion_cents": principal_portion,
        "disbursement_tax_year": disbursement_tax_year,
        "status": "PAID",
    })
    dis["_caused_satisfy"] = caused_satisfy
    db.disbursements[dis["id"]] = dis
    return success(serialize(dis), status=201)


@app.get("/obligations/<oid>/disbursements")
def list_disbursements(oid):
    authenticate()
    get_obligation(oid)
    items = [x for x in db.disbursements.values() if x["obligation_id"] == oid]
    return list_response(items)


@app.post("/disbursements/<did>/void")
def void_disbursement(did):
    authenticate()
    require_role(["MunicipalAdmin"])
    dis = get_disbursement(did)
    if dis["status"] != "PAID":
        raise ApiError("ERR_DISBURSEMENT_NOT_VOIDABLE", 409, "Disbursement is not PAID")

    o = db.obligations.get(dis["obligation_id"])
    o["accrued_interest_cents"] += dis["interest_portion_cents"]
    o["principal_remaining_cents"] += dis["principal_portion_cents"]
    o["outstanding_balance_cents"] += dis["amount_cents"]
    if dis.get("_caused_satisfy") and o["status"] == "SATISFIED":
        o["status"] = "REGISTERED"
    bump(o)

    fund = get_fund(o["district_id"])
    if fund is not None:
        fund["balance_cents"] += dis["amount_cents"]
        fund["lifetime_disbursed_cents"] -= dis["amount_cents"]
        bump(fund)

    dis["status"] = "VOIDED"
    bump(dis)
    recompute_obligations_cleared(get_district(o["district_id"]))
    return success(serialize(dis))


# ---------------------------------------------------------------------------
# IncrementRecord
# ---------------------------------------------------------------------------
@app.post("/tif-districts/<did>/increment-records")
def create_increment_record(did):
    authenticate()
    require_role(["CountyClerk"])
    d = get_district(did)
    body = get_body()
    tax_year = as_int(require_present(body, "tax_year"), "tax_year")
    current_eav_cents = as_int(require_present(body, "current_eav_cents"),
                               "current_eav_cents", minimum=0)

    if d["status"] != "CERTIFIED":
        raise ApiError("ERR_DISTRICT_NOT_CERTIFIED", 409, "District is not CERTIFIED")
    for r in db.increment_records.values():
        if r["district_id"] == did and r["tax_year"] == tax_year:
            raise ApiError("ERR_INCREMENT_YEAR_EXISTS", 409, "Increment year already exists")
    if not (tax_year > d["base_tax_year"] and tax_year <= d["expiration_tax_year"]):
        raise ApiError("ERR_VALIDATION", 422, "tax_year out of district range")

    agg = _agg_rate_dec(d)
    vals = calc.increment_capture(current_eav_cents, d["base_eav_cents"], agg, None)

    ent = make_entity({
        "district_id": did,
        "tax_year": tax_year,
        "current_eav_cents": current_eav_cents,
        "incremental_eav_cents": vals["incremental_eav_cents"],
        "gross_increment_cents": vals["gross_increment_cents"],
        "admin_fee_cents": vals["admin_fee_cents"],
        "captured_increment_cents": vals["captured_increment_cents"],
        "collection_rate": None,
        "variant_state": "PROVISIONAL",
        "status": "CERTIFIED",
    })
    ent["_prov_captured"] = vals["captured_increment_cents"]
    ent["_prov_admin"] = vals["admin_fee_cents"]
    ent["_prov_gross"] = vals["gross_increment_cents"]
    db.increment_records[ent["id"]] = ent

    fund = get_fund(did)
    if fund is not None:
        fund["balance_cents"] += vals["captured_increment_cents"]
        fund["lifetime_increment_cents"] += vals["captured_increment_cents"]
        fund["lifetime_admin_fee_cents"] += vals["admin_fee_cents"]
        bump(fund)
    return success(serialize(ent), status=201)


@app.post("/increment-records/<rid>/finalize")
def finalize_increment_record(rid):
    authenticate()
    require_role(["CountyClerk"])
    r = get_increment_record(rid)
    body = get_body()
    collection_rate = as_number(require_present(body, "collection_rate"), "collection_rate")
    if not (0 < collection_rate <= 1):
        raise ApiError("ERR_VALIDATION", 422, "collection_rate must be > 0 and <= 1")
    if r["status"] != "CERTIFIED":
        raise ApiError("ERR_INCREMENT_INVALID_STATE", 409, "Record is not CERTIFIED")

    d = get_district(r["district_id"])
    agg = _agg_rate_dec(d)
    vals = calc.increment_capture(r["current_eav_cents"], d["base_eav_cents"], agg, collection_rate)

    delta_captured = vals["captured_increment_cents"] - r["_prov_captured"]
    delta_admin = vals["admin_fee_cents"] - r["_prov_admin"]

    fund = get_fund(r["district_id"])
    if fund is not None:
        fund["balance_cents"] += delta_captured
        fund["lifetime_increment_cents"] += delta_captured
        fund["lifetime_admin_fee_cents"] += delta_admin
        bump(fund)

    r["gross_increment_cents"] = vals["gross_increment_cents"]
    r["admin_fee_cents"] = vals["admin_fee_cents"]
    r["captured_increment_cents"] = vals["captured_increment_cents"]
    r["collection_rate"] = collection_rate
    r["variant_state"] = "FINAL"
    r["status"] = "FINALIZED"
    bump(r)
    return success(serialize(r))


@app.post("/increment-records/<rid>/reopen")
def reopen_increment_record(rid):
    authenticate()
    require_role(["CountyClerk"])
    r = get_increment_record(rid)
    if r["status"] != "FINALIZED":
        raise ApiError("ERR_INCREMENT_INVALID_STATE", 409, "Record is not FINALIZED")

    delta_captured = r["captured_increment_cents"] - r["_prov_captured"]
    delta_admin = r["admin_fee_cents"] - r["_prov_admin"]

    fund = get_fund(r["district_id"])
    if fund is not None:
        fund["balance_cents"] -= delta_captured
        fund["lifetime_increment_cents"] -= delta_captured
        fund["lifetime_admin_fee_cents"] -= delta_admin
        bump(fund)

    r["gross_increment_cents"] = r["_prov_gross"]
    r["admin_fee_cents"] = r["_prov_admin"]
    r["captured_increment_cents"] = r["_prov_captured"]
    r["collection_rate"] = None
    r["variant_state"] = "PROVISIONAL"
    r["status"] = "CERTIFIED"
    bump(r)
    return success(serialize(r))


# ---------------------------------------------------------------------------
# AnnualReport
# ---------------------------------------------------------------------------
@app.post("/tif-districts/<did>/annual-reports")
def create_annual_report(did):
    authenticate()
    require_role(["CountyClerk"])
    get_district(did)
    body = get_body()
    report_tax_year = as_int(require_present(body, "report_tax_year"), "report_tax_year")
    ent = make_entity({
        "district_id": did,
        "report_tax_year": report_tax_year,
        "total_increment_cents": None,
        "total_disbursed_cents": None,
        "ending_balance_cents": None,
        "obligation_reserve_cents": None,
        "surplus_declared_cents": None,
        "surplus_basis": None,
        "status": "DRAFT",
    })
    db.annual_reports[ent["id"]] = ent
    return success(serialize(ent), status=201)


@app.post("/annual-reports/<rid>/file")
def file_annual_report(rid):
    authenticate()
    require_role(["CountyClerk"])
    r = get_annual_report(rid)
    if r["status"] != "DRAFT":
        raise ApiError("ERR_REPORT_INVALID_STATE", 409, "Report is not DRAFT")
    d = get_district(r["district_id"])
    if d["status"] != "CERTIFIED":
        raise ApiError("ERR_DISTRICT_NOT_CERTIFIED", 409, "District is not CERTIFIED")
    fund = get_fund(d["id"])
    r["total_increment_cents"] = fund["lifetime_increment_cents"] if fund else 0
    r["total_disbursed_cents"] = fund["lifetime_disbursed_cents"] if fund else 0
    r["status"] = "FILED"
    bump(r)
    return success(serialize(r))


@app.post("/annual-reports/<rid>/accept")
def accept_annual_report(rid):
    authenticate()
    require_role(["MunicipalAdmin"])
    r = get_annual_report(rid)
    body = get_body()
    expected_fund_version = as_int(require_present(body, "expected_fund_version"),
                                   "expected_fund_version")
    if r["status"] != "FILED":
        raise ApiError("ERR_REPORT_INVALID_STATE", 409, "Report is not FILED")
    d = get_district(r["district_id"])
    fund = get_fund(d["id"])
    if fund is None or expected_fund_version != fund["version"]:
        raise ApiError("ERR_STALE_FUND_VERSION", 412, "Stale fund version")

    ending_balance = fund["balance_cents"]
    basis = d["surplus_policy"]
    senior = [o for o in district_obligations(d["id"])
              if o["status"] == "REGISTERED" and o["seniority"] == "SENIOR"]
    reserve = calc.obligation_reserve(senior, basis)
    surplus = max(0, ending_balance - reserve)

    r["ending_balance_cents"] = ending_balance
    r["surplus_basis"] = basis
    r["obligation_reserve_cents"] = reserve
    r["surplus_declared_cents"] = surplus

    if surplus > 0:
        _distribute_surplus(d, fund, surplus, r["report_tax_year"], "ANNUAL")
        fund["balance_cents"] -= surplus
        fund["lifetime_surplus_cents"] += surplus
        bump(fund)

    r["status"] = "ACCEPTED"
    bump(r)
    return success(serialize(r))


@app.post("/annual-reports/<rid>/return")
def return_annual_report(rid):
    authenticate()
    require_role(["MunicipalAdmin"])
    r = get_annual_report(rid)
    if r["status"] != "FILED":
        raise ApiError("ERR_REPORT_INVALID_STATE", 409, "Report is not FILED")
    r["status"] = "DRAFT"
    bump(r)
    return success(serialize(r))


# ---------------------------------------------------------------------------
# SurplusAgreement
# ---------------------------------------------------------------------------
@app.post("/tif-districts/<did>/surplus-agreements")
def create_surplus_agreement(did):
    authenticate()
    require_role(["MunicipalAdmin"])
    d = get_district(did)
    body = get_body()
    taxing_body_id = as_str(require_present(body, "taxing_body_id"), "taxing_body_id")
    start_tax_year = as_int(require_present(body, "start_tax_year"), "start_tax_year")
    end_tax_year = as_int(require_present(body, "end_tax_year"), "end_tax_year")
    if end_tax_year <= start_tax_year:
        raise ApiError("ERR_VALIDATION", 422, "end_tax_year must be > start_tax_year")
    ppm = as_int(require_present(body, "surplus_share_ppm_override"),
                 "surplus_share_ppm_override", minimum=0, maximum=1000000)

    # Referential: taxing body must belong to the path district.
    tb = db.taxing_bodies.get(taxing_body_id)
    if tb is None or tb["district_id"] != did:
        raise ApiError("ERR_TAXING_BODY_NOT_IN_DISTRICT", 409,
                       "Taxing body does not belong to district")

    # Temporal overlap vs existing agreements for same body (half-open).
    for a in db.surplus_agreements.values():
        if a["taxing_body_id"] == taxing_body_id and a["district_id"] == did:
            if start_tax_year < a["end_tax_year"] and a["start_tax_year"] < end_tax_year:
                raise ApiError("ERR_AGREEMENT_PERIOD_OVERLAP", 409, "Agreement window overlaps")

    ent = make_entity({
        "district_id": did,
        "taxing_body_id": taxing_body_id,
        "start_tax_year": start_tax_year,
        "end_tax_year": end_tax_year,
        "surplus_share_ppm_override": ppm,
    }, common=False)
    db.surplus_agreements[ent["id"]] = ent
    return success(serialize(ent), status=201)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
