"""Application lifecycle endpoints (§3.2, §3.3, §3.4)."""
from store import db, stamp_new, touch, public, sort_key, now_iso
from common import (
    endpoint, object_response, get_body, req_int, req_str, req_enum, opt_str, ApiError,
)
from calc import (
    compute_fpl_pct, benefit_tier_from_pct, compute_benefit_amount, referral_priority,
    ELIGIBILITY_FPL_PCT,
)
from helpers import get_path, get_ref, list_collection, forbid

APP_COMPONENTS = {"HEATING", "COOLING"}


def _compute_benefit(income_cents, household):
    """Return (pct_decimal, tier, amount_cents)."""
    pct = compute_fpl_pct(income_cents, household["household_size"])
    tier = benefit_tier_from_pct(pct)
    vulnerable = household["has_elderly_or_disabled"] or household["has_child_under_6"]
    amount = compute_benefit_amount(tier, household["household_size"],
                                    household["heating_source"], vulnerable)
    return pct, tier, amount


def register(app):
    @app.route("/liheap/applications", methods=["POST"])
    @endpoint(["Applicant", "Caseworker"])
    def create_application(role, user_id):
        body = get_body()
        household_id = req_str(body, "household_id")
        season_year = req_int(body, "season_year")
        program_component = req_enum(body, "program_component", APP_COMPONENTS)
        # Ownership (403) before FK existence (422).
        if role == "Applicant" and household_id != user_id:
            forbid()
        get_ref(db.households, household_id)
        application = {
            "household_id": household_id,
            "season_year": season_year,
            "program_component": program_component,
            "fpl_pct": None,
            "income_eligible": None,
            "benefit_tier": None,
            "benefit_amount_cents": 0,
            "benefit_variant": None,
            "status": "DRAFT",
            "submitted_at": None,
            "denial_reason": None,
        }
        stamp_new(application)
        db.applications[application["id"]] = application
        return object_response(public(application), 201)

    @app.route("/liheap/applications/<id_>", methods=["GET"])
    @endpoint(["Applicant", "Caseworker", "ProgramAdmin"])
    def get_application(role, user_id, id_):
        application = get_path(db.applications, id_)
        if role == "Applicant" and application["household_id"] != user_id:
            forbid()
        return object_response(public(application), 200)

    @app.route("/liheap/applications", methods=["GET"])
    @endpoint(["Caseworker", "ProgramAdmin"])
    def list_applications(role, user_id):
        from flask import request
        filters = {
            "household_id": request.args.get("household_id"),
            "season_year": _int_or_none(request.args.get("season_year")),
            "program_component": request.args.get("program_component"),
            "status": request.args.get("status"),
        }
        return list_collection(db.applications, "applications", filters)

    @app.route("/liheap/applications/<id_>/submit", methods=["POST"])
    @endpoint(["Applicant"])
    def submit_application(role, user_id, id_):
        application = get_path(db.applications, id_)
        if application["household_id"] != user_id:
            forbid()
        status = application["status"]
        if status not in ("DRAFT", "INFO_REQUESTED"):
            raise ApiError("ERR_INVALID_STATE", "Application cannot be submitted from %s" % status)
        household = db.households[application["household_id"]]
        # ERR_SEASON_CLOSED: a matching, non-closed pool must exist.
        if not _matching_open_pool(application["season_year"], application["program_component"]):
            raise ApiError("ERR_SEASON_CLOSED", "No open funding pool for this season/component")
        # ERR_DUPLICATE_APPLICATION only on the first submit (from DRAFT).
        if status == "DRAFT" and _has_active_duplicate(application):
            raise ApiError("ERR_DUPLICATE_APPLICATION", "An active application already exists")
        # Provisional income eligibility (self-reported income).
        pct, tier, amount = _compute_benefit(household["annual_income_cents"], household)
        if pct > ELIGIBILITY_FPL_PCT:
            raise ApiError("ERR_INCOME_INELIGIBLE", "fpl_pct exceeds 150.00")
        application["fpl_pct"] = float(pct)
        application["income_eligible"] = True
        application["benefit_tier"] = tier
        application["benefit_amount_cents"] = amount
        application["benefit_variant"] = "PROVISIONAL"
        application["submitted_at"] = now_iso()
        application["status"] = "SUBMITTED"
        touch(application)
        return object_response(public(application), 200)

    @app.route("/liheap/applications/<id_>/request-info", methods=["POST"])
    @endpoint(["Caseworker"])
    def request_info_application(role, user_id, id_):
        application = get_path(db.applications, id_)
        if application["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "Application is not SUBMITTED")
        application["status"] = "INFO_REQUESTED"
        touch(application)
        return object_response(public(application), 200)

    @app.route("/liheap/applications/<id_>/approve", methods=["POST"])
    @endpoint(["Caseworker"])
    def approve_application(role, user_id, id_):
        application = get_path(db.applications, id_)
        if application["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "Application is not SUBMITTED")
        verified = _verified_docs(application["id"])
        if not verified:
            raise ApiError("ERR_INCOME_NOT_VERIFIED", "No VERIFIED income document")
        latest = max(verified, key=sort_key)
        household = db.households[application["household_id"]]
        pct, tier, amount = _compute_benefit(latest["verified_income_cents"], household)
        if pct > ELIGIBILITY_FPL_PCT:
            raise ApiError("ERR_INCOME_INELIGIBLE", "Verified fpl_pct exceeds 150.00")
        application["fpl_pct"] = float(pct)
        application["income_eligible"] = True
        application["benefit_tier"] = tier
        application["benefit_amount_cents"] = amount
        application["benefit_variant"] = "FINAL"
        application["status"] = "APPROVED"
        touch(application)
        if tier == "TIER_1":
            _auto_refer(application, household)
        return object_response(public(application), 200)

    @app.route("/liheap/applications/<id_>/deny", methods=["POST"])
    @endpoint(["Caseworker"])
    def deny_application(role, user_id, id_):
        application = get_path(db.applications, id_)
        body = get_body(required=False)
        denial_reason = opt_str(body, "denial_reason", None)
        if application["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "Application is not SUBMITTED")
        application["status"] = "DENIED"
        application["denial_reason"] = denial_reason
        touch(application)
        return object_response(public(application), 200)


def _int_or_none(value):
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return object()  # a value that matches nothing


def _matching_open_pool(season_year, program_component):
    for pool in db.funding_pools.values():
        if (pool["season_year"] == season_year
                and pool["program_component"] == program_component
                and not pool.get("_closed")):
            return True
    return False


def _has_active_duplicate(application):
    for other in db.applications.values():
        if other["id"] == application["id"]:
            continue
        if (other["household_id"] == application["household_id"]
                and other["season_year"] == application["season_year"]
                and other["program_component"] == application["program_component"]
                and other["status"] in ("SUBMITTED", "INFO_REQUESTED", "APPROVED")):
            return True
    return False


def _verified_docs(application_id):
    return [d for d in db.income_documents.values()
            if d["application_id"] == application_id and d["status"] == "VERIFIED"]


def _auto_refer(application, household):
    referral = {
        "household_id": household["id"],
        "application_id": application["id"],
        "referral_reason": "TIER_1_AUTO",
        "priority": referral_priority("TIER_1_AUTO",
                                      household["has_elderly_or_disabled"],
                                      household["has_child_under_6"]),
        "status": "REFERRED",
    }
    stamp_new(referral)
    db.weatherization_referrals[referral["id"]] = referral
