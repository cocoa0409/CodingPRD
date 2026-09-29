"""Borrower intake and geocoding, loan products, technical-assistance sessions."""
from datetime import timedelta
from decimal import Decimal

import calc
import services as svc
import shape
from auth import authenticate, scope
from envelope import created, ok, page, pagination, qs, qs_bool
from errors import fail
from flask import Blueprint
from store import base_row, db, fmt_dt, now, ordered, parse_dt, touch

bp = Blueprint("borrowers", __name__)

BORROWER_LIST_INST_ROLES = ("InstitutionOfficer", "CreditUnderwriter",
                            "ComplianceAnalyst")
BORROWER_READ_ROLES = ("InstitutionOfficer", "CreditUnderwriter",
                       "CreditCommittee", "ComplianceAnalyst")
BORROWER_LIST_ROLES = ("ComplianceAnalyst", "CreditUnderwriter", "CreditCommittee")
GEOCODE_ROLES = ("InstitutionOfficer", "ComplianceAnalyst")
PRODUCT_LIST_INST_ROLES = ("InstitutionOfficer", "CreditUnderwriter",
                           "CreditCommittee", "ComplianceAnalyst")
PRODUCT_READ_ROLES = ("InstitutionOfficer", "CreditUnderwriter",
                      "CreditCommittee", "ComplianceAnalyst")
PRODUCT_LIST_ROLES = ("ComplianceAnalyst", "CreditUnderwriter", "CreditCommittee")
ENGAGEMENT_ROLES = ("InstitutionOfficer", "CreditUnderwriter",
                    "CreditCommittee", "ComplianceAnalyst")
GEOCODE_OUTCOMES = ("MATCHED", "UNMATCHED")
CREDIT_FEATURES = ("REPORTS_TO_BUREAUS", "SAVINGS_MATCH", "RATE_STEP_DOWN",
                   "DEFERRED_FIRST_PAYMENT")
TA_TOPICS = ("CREDIT_BUILDING", "BUSINESS_PLANNING", "HOMEBUYER_EDUCATION",
             "FINANCIAL_COACHING")
TA_OUTCOMES = ("COMPLETED", "NO_SHOW")
TA_BUFFER = timedelta(minutes=30)


# --------------------------------------------------------------------------- #
# borrowers
# --------------------------------------------------------------------------- #
@bp.post("/institutions/<institution_id>/borrowers")
def create_borrower(institution_id):
    caller = authenticate(("InstitutionOfficer",))
    scope(caller, institution_id)
    svc.get_institution(institution_id)
    data = shape.body()
    full_name = shape.req_str(data, "full_name", 1)
    street_address = shape.req_str(data, "street_address", 1)
    postal_code = shape.req_str(data, "postal_code", 1)
    household = shape.req_int(data, "household_income_cents", minimum=0)
    ami = shape.req_int(data, "area_median_income_cents", minimum=1)
    credit_score = shape.opt_int(data, "credit_score", minimum=300, maximum=850)
    row = base_row()
    row.update({
        "institution_id": institution_id,
        "full_name": full_name,
        "street_address": street_address,
        "postal_code": postal_code,
        "household_income_cents": household,
        "area_median_income_cents": ami,
        "credit_score": credit_score,
        "income_pct_ami": calc.income_pct_ami(household, ami),
        "census_tract_code": None,
        "geocode_state": "UNGEOCODED",
        "geocode_attempts": 0,
        "in_target_market": False,
        "matched_target_market_type": None,
        "ta_hours_total": Decimal("0.00"),
    })
    db.borrowers[row["id"]] = row
    return created(row)


def _filter_borrowers(rows):
    geocode_state = qs("geocode_state")
    in_market = qs_bool("in_target_market")
    if geocode_state is not None:
        rows = [r for r in rows if r["geocode_state"] == geocode_state]
    if in_market is not None:
        rows = [r for r in rows if r["in_target_market"] is in_market]
    return rows


@bp.get("/institutions/<institution_id>/borrowers")
def list_institution_borrowers(institution_id):
    caller = authenticate(BORROWER_LIST_INST_ROLES)
    scope(caller, institution_id)
    svc.get_institution(institution_id)
    limit, offset = pagination()
    rows = ordered([b for b in db.borrowers.values()
                    if b["institution_id"] == institution_id])
    return page(_filter_borrowers(rows), limit, offset)


@bp.get("/borrowers")
def list_borrowers():
    authenticate(BORROWER_LIST_ROLES)
    limit, offset = pagination()
    rows = ordered(db.borrowers.values())
    institution_id = qs("institution_id")
    if institution_id is not None:
        rows = [r for r in rows if r["institution_id"] == institution_id]
    return page(_filter_borrowers(rows), limit, offset)


@bp.get("/borrowers/<borrower_id>")
def read_borrower(borrower_id):
    caller = authenticate(BORROWER_READ_ROLES)
    existing = db.borrowers.get(borrower_id)
    scope(caller, existing["institution_id"] if existing else None)
    return ok(svc.get_borrower(borrower_id))


@bp.post("/borrowers/<borrower_id>/geocode")
def geocode_borrower(borrower_id):
    caller = authenticate(GEOCODE_ROLES)
    existing = db.borrowers.get(borrower_id)
    scope(caller, existing["institution_id"] if existing else None)
    borrower = svc.get_borrower(borrower_id)
    data = shape.body()
    outcome = shape.req_enum(data, "outcome", GEOCODE_OUTCOMES)
    tract = shape.opt_str(data, "census_tract_code", 1)
    if outcome == "MATCHED" and tract is None:
        fail("ERR_INVALID_REQUEST")
    borrower["geocode_attempts"] = borrower["geocode_attempts"] + 1
    if outcome == "MATCHED":
        borrower["geocode_state"] = "GEOCODED"
        borrower["census_tract_code"] = tract
    else:
        borrower["geocode_state"] = "GEOCODE_FAILED"
    # Attribution is re-derived on every attempt; it never rewrites the
    # origination snapshot already frozen on a disbursed loan.
    svc.reattribute_borrower(borrower)
    touch(borrower)
    return ok(borrower)


# --------------------------------------------------------------------------- #
# loan products
# --------------------------------------------------------------------------- #
@bp.post("/institutions/<institution_id>/loan-products")
def create_loan_product(institution_id):
    caller = authenticate(("InstitutionOfficer",))
    scope(caller, institution_id)
    svc.get_institution(institution_id)
    data = shape.body()
    name = shape.req_str(data, "name", 1)
    base_rate = shape.req_int(data, "base_rate_bps", minimum=0, maximum=3600)
    term_months = shape.req_int(data, "term_months", minimum=1, maximum=360)
    max_dti = shape.req_dec(data, "max_dti_pct", places=2, exclusive_min=0,
                            maximum=60)
    min_score = shape.req_int(data, "min_credit_score", minimum=300, maximum=850)
    allow_no_score = shape.opt_bool(data, "allow_no_credit_score", default=False)
    features = shape.opt_str_array(data, "credit_building_features",
                                   allowed=CREDIT_FEATURES, default=[])
    requires_ta = shape.opt_bool(data, "requires_ta_completion", default=False)
    cap = shape.req_int(data, "product_cap_cents", minimum=1)
    row = base_row()
    row.update({
        "institution_id": institution_id,
        "name": name,
        "base_rate_bps": base_rate,
        "term_months": term_months,
        "max_dti_pct": max_dti,
        "min_credit_score": min_score,
        "allow_no_credit_score": allow_no_score,
        "credit_building_features": features,
        "requires_ta_completion": requires_ta,
        "product_cap_cents": cap,
        "committed_principal_cents": 0,
    })
    db.loan_products[row["id"]] = row
    return created(row)


def _filter_products(rows):
    requires_ta = qs_bool("requires_ta_completion")
    if requires_ta is not None:
        rows = [r for r in rows if r["requires_ta_completion"] is requires_ta]
    return rows


@bp.get("/institutions/<institution_id>/loan-products")
def list_institution_products(institution_id):
    caller = authenticate(PRODUCT_LIST_INST_ROLES)
    scope(caller, institution_id)
    svc.get_institution(institution_id)
    limit, offset = pagination()
    rows = ordered([p for p in db.loan_products.values()
                    if p["institution_id"] == institution_id])
    return page(_filter_products(rows), limit, offset)


@bp.get("/loan-products")
def list_products():
    authenticate(PRODUCT_LIST_ROLES)
    limit, offset = pagination()
    rows = ordered(db.loan_products.values())
    institution_id = qs("institution_id")
    if institution_id is not None:
        rows = [r for r in rows if r["institution_id"] == institution_id]
    return page(_filter_products(rows), limit, offset)


@bp.get("/loan-products/<product_id>")
def read_product(product_id):
    caller = authenticate(PRODUCT_READ_ROLES)
    existing = db.loan_products.get(product_id)
    scope(caller, existing["institution_id"] if existing else None)
    return ok(svc.get_product(product_id))


# --------------------------------------------------------------------------- #
# technical-assistance engagements
# --------------------------------------------------------------------------- #
@bp.post("/institutions/<institution_id>/ta-engagements")
def create_engagement(institution_id):
    caller = authenticate(("InstitutionOfficer",))
    scope(caller, institution_id)
    svc.get_institution(institution_id)
    data = shape.body()
    borrower = svc.get_borrower(shape.body_id(data, "borrower_id"), institution_id)
    loan_ref = shape.body_id(data, "loan_id")
    if loan_ref is not None:
        svc.get_loan(loan_ref)
    topic = shape.req_enum(data, "topic", TA_TOPICS)
    start_raw, start = shape.req_dt(data, "scheduled_start_at")
    end_raw, end = shape.req_dt(data, "scheduled_end_at")
    planned = shape.req_dec(data, "planned_hours", places=2, exclusive_min=0,
                            maximum=8)
    # The slot-conflict test runs BEFORE the bounds-ordering test (PRD 2.8).
    for other in db.ta_engagements.values():
        if other["borrower_id"] != borrower["id"]:
            continue
        if other["state"] not in ("SCHEDULED", "COMPLETED"):
            continue
        other_start = parse_dt(other["scheduled_start_at"])
        other_end = parse_dt(other["scheduled_end_at"])
        if start <= other_end + TA_BUFFER and other_start <= end + TA_BUFFER:
            fail("ERR_TA_SLOT_CONFLICT")
    if not end > start:
        fail("ERR_PERIOD_BOUNDS_INVALID")
    row = base_row()
    row.update({
        "institution_id": institution_id,
        "borrower_id": borrower["id"],
        "loan_id": loan_ref,
        "topic": topic,
        "scheduled_start_at": start_raw,
        "scheduled_end_at": end_raw,
        "planned_hours": planned,
        "actual_hours": Decimal("0.00"),
        "competency_verified": False,
        "state": "SCHEDULED",
        "closed_at": None,
    })
    db.ta_engagements[row["id"]] = row
    return created(row)


@bp.get("/ta-engagements/<engagement_id>")
def read_engagement(engagement_id):
    caller = authenticate(ENGAGEMENT_ROLES)
    existing = db.ta_engagements.get(engagement_id)
    scope(caller, existing["institution_id"] if existing else None)
    return ok(svc.get_engagement(engagement_id))


@bp.get("/ta-engagements")
def list_engagements():
    caller = authenticate(ENGAGEMENT_ROLES)
    institution_id = qs("institution_id")
    scope(caller, institution_id)
    limit, offset = pagination()
    rows = ordered(db.ta_engagements.values())
    if institution_id is not None:
        rows = [r for r in rows if r["institution_id"] == institution_id]
    borrower_id = qs("borrower_id")
    loan_id = qs("loan_id")
    state = qs("state")
    if borrower_id is not None:
        rows = [r for r in rows if r["borrower_id"] == borrower_id]
    if loan_id is not None:
        rows = [r for r in rows if r["loan_id"] == loan_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    return page(rows, limit, offset)


@bp.post("/ta-engagements/<engagement_id>/close")
def close_engagement(engagement_id):
    caller = authenticate(("InstitutionOfficer",))
    existing = db.ta_engagements.get(engagement_id)
    scope(caller, existing["institution_id"] if existing else None)
    eng = svc.get_engagement(engagement_id)
    data = shape.body()
    outcome = shape.req_enum(data, "outcome", TA_OUTCOMES)
    actual = shape.opt_dec(data, "actual_hours", places=2, exclusive_min=0)
    verified = shape.opt_bool(data, "competency_verified", default=False)
    if outcome == "COMPLETED" and actual is None:
        fail("ERR_INVALID_REQUEST")
    if eng["state"] != "SCHEDULED":
        fail("ERR_ENGAGEMENT_NOT_SCHEDULED")
    eng["closed_at"] = fmt_dt(now())
    if outcome == "COMPLETED":
        eng["state"] = "COMPLETED"
        eng["actual_hours"] = actual
        eng["competency_verified"] = verified
        touch(eng)
        borrower = db.borrowers.get(eng["borrower_id"])
        if borrower is not None:
            svc.recompute_ta_hours(borrower)
    else:
        # A no-show credits no hours and releases the borrower's calendar slot.
        eng["state"] = "NO_SHOW"
        eng["actual_hours"] = Decimal("0.00")
        eng["competency_verified"] = False
        touch(eng)
    return ok(eng)
