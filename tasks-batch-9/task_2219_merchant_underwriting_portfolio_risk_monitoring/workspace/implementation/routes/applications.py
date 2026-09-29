"""Category rules, application intake, verification, screening and underwriting."""
from flask import Blueprint

from db import by_seq, db, new_row, serialize, serialize_all
from errors import fail
from middleware import (
    authenticate,
    body,
    filter_enum,
    filter_str,
    find_application,
    find_owner,
    opt_id,
    opt_int,
    own_application,
    pagination,
    req_bool,
    req_date,
    req_enum,
    req_id,
    req_int,
    req_number,
    req_str,
    req_str_list,
    touch,
)
from response import object_response, paged_response
from services.calc import reserve_requirement
from services.metrics import (
    assessments_of,
    merchant_of_application,
    owners_of,
    rule_for_mcc,
    verifications_of,
)

bp = Blueprint("applications", __name__)

APPLICATION_STATES = (
    "DRAFT", "SUBMITTED", "IN_VERIFICATION", "INFO_REQUESTED",
    "UNDERWRITING", "APPROVED", "DECLINED", "WITHDRAWN",
)
TERMINAL_APPLICATION_STATES = ("APPROVED", "DECLINED", "WITHDRAWN")
DECLINE_REASONS = ("PROHIBITED_CATEGORY", "INSUFFICIENT_CREDIT",
                   "VERIFICATION_FAILED", "OWNERSHIP_UNVERIFIED")
VERIFICATION_ITEM_ORDER = (
    ("registry_match", "REGISTRY_MATCH"),
    ("address_match", "ADDRESS_MATCH"),
    ("tax_id_match", "TAX_ID_MATCH"),
    ("bank_account_match", "BANK_ACCOUNT_MATCH"),
)

READ_STAFF = ("UnderwritingOfficer", "RiskAnalyst", "RiskCommitteeApprover", "PortfolioController")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _ownership_total(application_id):
    total_hundredths = sum(
        int(round(owner["ownership_pct"] * 100)) for owner in owners_of(application_id)
    )
    return total_hundredths / 100.0


def _derive_disposition(mcc_code):
    rule = rule_for_mcc(mcc_code)
    if rule is None:
        return "ALLOWED"
    return "PROHIBITED" if rule["disposition"] == "PROHIBITED" else "RESTRICTED_REVIEW"


def _require_state(app, allowed):
    if app["state"] not in allowed:
        fail("ERR_APPLICATION_STATE_INVALID",
             "Application state '%s' does not permit this operation." % app["state"])


# --------------------------------------------------------------------------
# prohibited category rules
# --------------------------------------------------------------------------
@bp.post("/prohibited-category-rules")
def create_category_rule():
    user_id, _ = authenticate(["UnderwritingOfficer"])
    payload = body()
    mcc_code = req_str(payload, "mcc_code", pattern=r"^[0-9]{4}$")
    category = req_str(payload, "category", max_len=200)
    disposition = req_enum(payload, "disposition", ("PROHIBITED", "RESTRICTED_REVIEW"))
    uplift = opt_int(payload, "reserve_uplift_bps", default=0, lo=0, hi=2000)

    if rule_for_mcc(mcc_code) is not None:
        fail("ERR_DUPLICATE_CATEGORY_RULE",
             "A screening rule already exists for mcc_code '%s'." % mcc_code)

    rule = new_row(versioned=False)
    rule.update({
        "mcc_code": mcc_code,
        "category": category,
        "disposition": disposition,
        "reserve_uplift_bps": uplift,
        "created_by_user_id": user_id,
    })
    db.category_rules[rule["id"]] = rule

    for app in by_seq(list(db.applications.values())):
        if app["mcc_code"] == mcc_code and app["state"] in ("DRAFT", "SUBMITTED"):
            app["mcc_disposition"] = _derive_disposition(mcc_code)
            touch(app)

    return object_response(serialize(rule), 201)


@bp.get("/prohibited-category-rules")
def list_category_rules():
    authenticate(["UnderwritingOfficer", "RiskAnalyst", "PortfolioController"])
    disposition = filter_enum("disposition", ("PROHIBITED", "RESTRICTED_REVIEW"))
    limit, offset = pagination()
    rows = sorted(db.category_rules.values(), key=lambda r: (r["mcc_code"], r["_seq"]))
    if disposition:
        rows = [r for r in rows if r["disposition"] == disposition]
    return paged_response(serialize_all(rows), limit, offset)


# --------------------------------------------------------------------------
# applications
# --------------------------------------------------------------------------
@bp.post("/merchant-applications")
def create_application():
    user_id, _ = authenticate(["Applicant"])
    payload = body()
    legal_business_name = req_str(payload, "legal_business_name", max_len=200)
    tax_id = req_str(payload, "tax_id", pattern=r"^[0-9]{2}-[0-9]{7}$")
    mcc_code = req_str(payload, "mcc_code", pattern=r"^[0-9]{4}$")
    country_code = req_enum(payload, "country_code", ("US", "CA"))
    requested_volume = req_int(payload, "requested_monthly_volume_cents", lo=100000)
    average_ticket = req_int(payload, "average_ticket_cents", lo=1)
    lag_days = req_int(payload, "avg_delivery_lag_days", lo=0, hi=365)
    history_months = req_int(payload, "prior_processing_history_months", lo=0, hi=600)
    credit_score = req_int(payload, "credit_score", lo=300, hi=850)
    declared_ratio = req_int(payload, "declared_chargeback_ratio_bps", lo=0, hi=10000)
    supersedes_id = opt_id(payload, "supersedes_application_id")

    superseded = None
    if supersedes_id is not None:
        superseded = find_application(supersedes_id)
        own_application(supersedes_id)
        prior_merchant = merchant_of_application(supersedes_id)
        if (superseded["state"] != "APPROVED"
                or prior_merchant is None
                or prior_merchant["account_state"] != "TERMINATED"):
            fail("ERR_SUPERSEDED_APPLICATION_INVALID",
                 "The superseded application must be APPROVED with a TERMINATED merchant.")

    app = new_row()
    app.update({
        "legal_business_name": legal_business_name,
        "tax_id": tax_id,
        "mcc_code": mcc_code,
        "country_code": country_code,
        "requested_monthly_volume_cents": requested_volume,
        "average_ticket_cents": average_ticket,
        "avg_delivery_lag_days": lag_days,
        "prior_processing_history_months": history_months,
        "credit_score": credit_score,
        "declared_chargeback_ratio_bps": declared_ratio,
        "supersedes_application_id": supersedes_id,
        "state": "DRAFT",
        "outstanding_info_items": [],
        "decline_reason_code": None,
        "verification_attempt_count": 0,
        "owner_ownership_pct_total": 0.0,
        "mcc_disposition": _derive_disposition(mcc_code),
        "current_assessment_method": None,
        "current_reserve_pct_bps": None,
        "current_reserve_cap_cents": None,
        "current_reserve_type": None,
        "decision_officer_user_id": None,
        "decided_at": None,
    })
    db.applications[app["id"]] = app
    return object_response(serialize(app), 201)


@bp.get("/merchant-applications/<app_id>")
def get_application(app_id):
    authenticate(["Applicant"] + list(READ_STAFF))
    app = find_application(app_id)
    own_application(app_id)
    return object_response(serialize(app))


@bp.get("/merchant-applications")
def list_applications():
    authenticate(list(READ_STAFF))
    state = filter_enum("state", APPLICATION_STATES)
    mcc_code = filter_str("mcc_code")
    limit, offset = pagination()
    rows = by_seq(list(db.applications.values()))
    if state:
        rows = [r for r in rows if r["state"] == state]
    if mcc_code:
        rows = [r for r in rows if r["mcc_code"] == mcc_code]
    return paged_response(serialize_all(rows), limit, offset)


@bp.get("/merchant-applications/<app_id>/superseding-applications")
def list_superseding(app_id):
    authenticate(["UnderwritingOfficer", "RiskAnalyst"])
    limit, offset = pagination()
    find_application(app_id)
    rows = [r for r in by_seq(list(db.applications.values()))
            if r["supersedes_application_id"] == app_id]
    return paged_response(serialize_all(rows), limit, offset)


@bp.post("/merchant-applications/<app_id>/submit")
def submit_application(app_id):
    authenticate(["Applicant"])
    app = find_application(app_id)
    own_application(app_id)
    _require_state(app, ("DRAFT", "INFO_REQUESTED"))
    if not owners_of(app_id):
        fail("ERR_BENEFICIAL_OWNERS_REQUIRED",
             "At least one beneficial owner must be disclosed before submission.")
    app["state"] = "SUBMITTED"
    app["outstanding_info_items"] = []
    app["owner_ownership_pct_total"] = _ownership_total(app_id)
    app["mcc_disposition"] = _derive_disposition(app["mcc_code"])
    touch(app)
    return object_response(serialize(app))


@bp.post("/merchant-applications/<app_id>/request-info")
def request_info(app_id):
    authenticate(["UnderwritingOfficer"])
    app = find_application(app_id)
    payload = body()
    items = req_str_list(payload, "outstanding_info_items")
    _require_state(app, ("IN_VERIFICATION", "UNDERWRITING"))
    app["state"] = "INFO_REQUESTED"
    app["outstanding_info_items"] = items
    touch(app)
    return object_response(serialize(app))


@bp.post("/merchant-applications/<app_id>/withdraw")
def withdraw_application(app_id):
    authenticate(["Applicant"])
    app = find_application(app_id)
    own_application(app_id)
    _require_state(app, ("DRAFT", "SUBMITTED", "IN_VERIFICATION",
                         "INFO_REQUESTED", "UNDERWRITING"))
    app["state"] = "WITHDRAWN"
    app["decided_at"] = db.clock_iso()
    touch(app)
    return object_response(serialize(app))


# --------------------------------------------------------------------------
# beneficial owners
# --------------------------------------------------------------------------
@bp.post("/beneficial-owners")
def create_owner():
    authenticate(["Applicant"])
    payload = body()
    application_id = req_id(payload, "application_id")
    full_name = req_str(payload, "full_name", max_len=200)
    ownership_pct = req_number(payload, "ownership_pct", lo=0.01, hi=100)
    date_of_birth = req_date(payload, "date_of_birth")
    government_id_last4 = req_str(payload, "government_id_last4", pattern=r"^[0-9]{4}$")
    country_code = req_enum(payload, "country_code", ("US", "CA"))

    app = find_application(application_id)
    own_application(application_id)
    _require_state(app, ("DRAFT",))

    owner = new_row()
    owner.update({
        "application_id": application_id,
        "full_name": full_name,
        "ownership_pct": ownership_pct,
        "date_of_birth": date_of_birth,
        "government_id_last4": government_id_last4,
        "country_code": country_code,
        "sanctions_hit": False,
        "pep_flag": False,
        "id_verified": False,
        "status": "PENDING",
        "screened_at": None,
    })
    db.owners[owner["id"]] = owner

    app["owner_ownership_pct_total"] = _ownership_total(application_id)
    touch(app)
    return object_response(serialize(owner), 201)


@bp.get("/merchant-applications/<app_id>/beneficial-owners")
def list_owners(app_id):
    authenticate(["Applicant", "UnderwritingOfficer", "RiskAnalyst"])
    status = filter_enum("status", ("PENDING", "CLEARED", "FLAGGED_PEP",
                                    "ID_UNVERIFIED", "SANCTIONS_HIT"))
    limit, offset = pagination()
    find_application(app_id)
    own_application(app_id)
    rows = owners_of(app_id)
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paged_response(serialize_all(rows), limit, offset)


@bp.post("/beneficial-owners/<owner_id>/screen")
def screen_owner(owner_id):
    authenticate(["UnderwritingOfficer"])
    payload = body()
    sanctions_hit = req_bool(payload, "sanctions_hit")
    pep_flag = req_bool(payload, "pep_flag")
    id_verified = req_bool(payload, "id_verified")

    owner = find_owner(owner_id)
    app = find_application(owner["application_id"])
    _require_state(app, ("SUBMITTED", "IN_VERIFICATION"))

    owner["sanctions_hit"] = sanctions_hit
    owner["pep_flag"] = pep_flag
    owner["id_verified"] = id_verified
    if sanctions_hit:
        owner["status"] = "SANCTIONS_HIT"
    elif not id_verified:
        owner["status"] = "ID_UNVERIFIED"
    elif pep_flag:
        owner["status"] = "FLAGGED_PEP"
    else:
        owner["status"] = "CLEARED"
    owner["screened_at"] = db.clock_iso()
    touch(owner)
    return object_response(serialize(owner))


# --------------------------------------------------------------------------
# business verifications
# --------------------------------------------------------------------------
@bp.post("/business-verifications")
def create_verification():
    user_id, _ = authenticate(["UnderwritingOfficer"])
    payload = body()
    application_id = req_id(payload, "application_id")
    flags = {
        "registry_match": req_bool(payload, "registry_match"),
        "tax_id_match": req_bool(payload, "tax_id_match"),
        "bank_account_match": req_bool(payload, "bank_account_match"),
        "address_match": req_bool(payload, "address_match"),
    }
    app = find_application(application_id)
    _require_state(app, ("SUBMITTED",))

    mismatch_count = sum(1 for value in flags.values() if not value)
    existing = verifications_of(application_id)
    attempt_index = (max(v["attempt_index"] for v in existing) + 1) if existing else 1

    verification = new_row()
    verification.update({
        "application_id": application_id,
        "registry_match": flags["registry_match"],
        "tax_id_match": flags["tax_id_match"],
        "bank_account_match": flags["bank_account_match"],
        "address_match": flags["address_match"],
        "mismatch_count": mismatch_count,
        "attempt_index": attempt_index,
        "status": "PASSED" if mismatch_count == 0 else "FAILED",
        "verified_by_user_id": user_id,
    })
    db.verifications[verification["id"]] = verification

    app["verification_attempt_count"] = app["verification_attempt_count"] + 1
    app["state"] = "IN_VERIFICATION"
    touch(app)

    if verification["status"] == "FAILED":
        app["state"] = "INFO_REQUESTED"
        app["outstanding_info_items"] = [
            label for field, label in VERIFICATION_ITEM_ORDER if not flags[field]
        ]
        touch(app)

    return object_response(serialize(verification), 201)


@bp.get("/merchant-applications/<app_id>/business-verifications")
def list_verifications(app_id):
    authenticate(["UnderwritingOfficer", "RiskAnalyst"])
    limit, offset = pagination()
    find_application(app_id)
    return paged_response(serialize_all(verifications_of(app_id)), limit, offset)


# --------------------------------------------------------------------------
# the underwriting gate
# --------------------------------------------------------------------------
@bp.post("/merchant-applications/<app_id>/advance-to-underwriting")
def advance_to_underwriting(app_id):
    authenticate(["UnderwritingOfficer"])
    app = find_application(app_id)
    body()  # reviewer_note is accepted and not persisted
    _require_state(app, ("IN_VERIFICATION",))

    if app["mcc_disposition"] == "PROHIBITED":
        fail("ERR_PROHIBITED_BUSINESS_CATEGORY",
             "The application's merchant category is prohibited.")
    owners = owners_of(app_id)
    if any(owner["status"] == "SANCTIONS_HIT" for owner in owners):
        fail("ERR_SANCTIONED_BENEFICIAL_OWNER",
             "A beneficial owner has a sanctions-list match.")
    if any(owner["status"] == "PENDING" for owner in owners):
        fail("ERR_OWNER_SCREENING_INCOMPLETE",
             "Every beneficial owner must be screened before underwriting.")
    if app["owner_ownership_pct_total"] < 75.0:
        fail("ERR_OWNERSHIP_COVERAGE_INSUFFICIENT",
             "Disclosed beneficial ownership must reach 75.00 percent.")
    attempts = verifications_of(app_id)
    if not attempts or attempts[-1]["status"] != "PASSED":
        fail("ERR_VERIFICATION_NOT_PASSED",
             "The authoritative business verification attempt has not passed.")

    app["state"] = "UNDERWRITING"
    touch(app)
    return object_response(serialize(app))


# --------------------------------------------------------------------------
# credit assessments
# --------------------------------------------------------------------------
@bp.post("/credit-assessments")
def create_assessment():
    user_id, _ = authenticate(["UnderwritingOfficer"])
    payload = body()
    application_id = req_id(payload, "application_id")
    method = req_enum(payload, "method", ("LAG_WEIGHTED", "CHARGEBACK_WEIGHTED"))
    expected_version = req_int(payload, "expected_application_version")

    app = find_application(application_id)
    if expected_version != app["version"]:
        fail("ERR_STALE_APPLICATION_VERSION",
             "expected_application_version %s does not match the current version %s."
             % (expected_version, app["version"]))
    _require_state(app, ("UNDERWRITING",))

    existing = assessments_of(application_id)
    sequence = (max(a["assessment_sequence"] for a in existing) + 1) if existing else 1
    computed = reserve_requirement(app, method)

    assessment = new_row()
    assessment.update({
        "application_id": application_id,
        "method": method,
        "assessment_sequence": sequence,
        "credit_band": computed["credit_band"],
        "base_reserve_bps": computed["base_reserve_bps"],
        "lag_uplift_bps": computed["lag_uplift_bps"],
        "thin_file_uplift_bps": computed["thin_file_uplift_bps"],
        "mcc_uplift_bps": computed["mcc_uplift_bps"],
        "chargeback_uplift_bps": computed["chargeback_uplift_bps"],
        "reserve_pct_bps": computed["reserve_pct_bps"],
        "exposure_estimate_cents": computed["exposure_estimate_cents"],
        "reserve_cap_cents": computed["reserve_cap_cents"],
        "reserve_type": computed["reserve_type"],
        "assessed_by_user_id": user_id,
    })
    db.assessments[assessment["id"]] = assessment

    app["current_assessment_method"] = method
    app["current_reserve_pct_bps"] = computed["reserve_pct_bps"]
    app["current_reserve_cap_cents"] = computed["reserve_cap_cents"]
    app["current_reserve_type"] = computed["reserve_type"]
    touch(app)

    return object_response(serialize(assessment), 201)


@bp.get("/merchant-applications/<app_id>/credit-assessments")
def list_assessments(app_id):
    authenticate(list(READ_STAFF))
    method = filter_enum("method", ("LAG_WEIGHTED", "CHARGEBACK_WEIGHTED"))
    limit, offset = pagination()
    find_application(app_id)
    rows = assessments_of(app_id)
    if method:
        rows = [r for r in rows if r["method"] == method]
    return paged_response(serialize_all(rows), limit, offset)


# --------------------------------------------------------------------------
# the committee decision
# --------------------------------------------------------------------------
@bp.post("/merchant-applications/<app_id>/decision")
def decide_application(app_id):
    user_id, _ = authenticate(["RiskCommitteeApprover"])
    payload = body()
    decision = req_enum(payload, "decision", ("APPROVE", "DECLINE"))
    decline_reason_code = None
    if decision == "DECLINE":
        decline_reason_code = req_enum(payload, "decline_reason_code", DECLINE_REASONS)

    app = find_application(app_id)
    _require_state(app, ("UNDERWRITING",))
    assessments = assessments_of(app_id)
    if not assessments:
        fail("ERR_CREDIT_ASSESSMENT_REQUIRED",
             "The application must be priced by at least one credit assessment.")

    app["decision_officer_user_id"] = user_id
    app["decided_at"] = db.clock_iso()

    if decision == "DECLINE":
        app["state"] = "DECLINED"
        app["decline_reason_code"] = decline_reason_code
        touch(app)
        return object_response(serialize(app))

    app["state"] = "APPROVED"
    touch(app)

    authoritative = assessments[-1]
    merchant = new_row()
    merchant.update({
        "application_id": app["id"],
        "legal_business_name": app["legal_business_name"],
        "mcc_code": app["mcc_code"],
        "monthly_volume_limit_cents": app["requested_monthly_volume_cents"],
        "account_state": "ACTIVE",
        "funding_state": "NORMAL",
        "delayed_payout_days": 0,
        "remediation_required": False,
        "pinned_reserve_pct_bps": authoritative["reserve_pct_bps"],
        "pinned_reserve_cap_cents": authoritative["reserve_cap_cents"],
        "pinned_reserve_type": authoritative["reserve_type"],
        "pinned_assessment_method": authoritative["method"],
        "metrics_as_of_date": None,
        "trailing_30d_txn_count": 0,
        "trailing_30d_volume_cents": 0,
        "trailing_30d_chargeback_count": 0,
        "trailing_30d_chargeback_amount_cents": 0,
        "rolling_chargeback_ratio_bps": 0,
        "amount_based_chargeback_ratio_bps": 0,
        "reserve_balance_cents": 0,
        "pending_payout_cents": 0,
        "lifetime_reversed_cents": 0,
        "open_alert_count": 0,
        "last_monitoring_run_date": None,
        "funding_hold_reason_code": None,
        "terminated_at": None,
        "reinstated_at": None,
    })
    db.merchants[merchant["id"]] = merchant

    account = new_row()
    account.update({
        "merchant_id": merchant["id"],
        "reserve_type": merchant["pinned_reserve_type"],
        "reserve_pct_bps": merchant["pinned_reserve_pct_bps"],
        "reserve_cap_cents": merchant["pinned_reserve_cap_cents"],
        "release_lag_days": 90 if merchant["pinned_reserve_type"] == "ROLLING" else 180,
        "total_accrued_cents": 0,
        "released_to_date_cents": 0,
        "offset_to_date_cents": 0,
        "held_balance_cents": 0,
        "state": "ACCRUING",
        "last_release_tranche_end_date": None,
    })
    db.reserve_accounts[account["id"]] = account

    return object_response(serialize(app))


@bp.get("/merchant-applications/<app_id>/onboarded-merchants")
def list_onboarded(app_id):
    authenticate(list(READ_STAFF))
    limit, offset = pagination()
    find_application(app_id)
    merchant = merchant_of_application(app_id)
    rows = [merchant] if merchant is not None else []
    return paged_response(serialize_all(rows), limit, offset)
