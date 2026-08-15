"""Guarantor and income-verification routes."""

from decimal import Decimal

from flask import Blueprint, request

from db import store
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_APPLICATION_TERMINAL,
    ERR_INVALID_INCOME_VERIFICATION_STATE,
    ERR_INVALID_GUARANTOR_STATE,
    ERR_INCOME_VERIFICATION_EXISTS,
)
from middleware import (
    get_context, require_role,
    check_landlord_ownership, check_applicant_ownership,
)
from response import success_object, success_list
from services.core import round_half_up_cents, application_income_verification
from util import (
    get_body, req_string, req_int, req_enum,
    pagination_params, paginate, stamp_new, touch, serialize,
)

bp = Blueprint("people", __name__)

TERMINAL = ("APPROVED", "DENIED", "WITHDRAWN", "CANCELLED")


def _get_application_or_404(aid):
    app = store.applications.get(aid)
    if app is None:
        raise ApiError(ERR_NOT_FOUND, "Application not found", 404)
    return app


def _scoped_read_check(user_id, role, app):
    if role == "Landlord":
        check_landlord_ownership(user_id, role, app["landlord_id"])
    elif role == "Applicant":
        check_applicant_ownership(user_id, role, app["applicant_id"])


# ---------------------------------------------------------------------------
# Guarantors
# ---------------------------------------------------------------------------

@bp.route("/api/applications/<aid>/guarantors", methods=["POST"])
def create_guarantor(aid):
    user_id, role = get_context()
    require_role(role, ["Landlord"])
    app = _get_application_or_404(aid)
    check_landlord_ownership(user_id, role, app["landlord_id"])
    if app["status"] in TERMINAL:
        raise ApiError(ERR_APPLICATION_TERMINAL, "Application is in a terminal state", 409)
    body = get_body()
    guarantor = stamp_new({
        "application_id": app["id"],
        "full_name": req_string(body, "full_name"),
        "stated_monthly_income_cents": req_int(body, "stated_monthly_income_cents"),
        "verified_monthly_income_cents": None,
        "credit_score": None,
        "qualification_policy_used": None,
        "status": "PENDING",
    })
    store.guarantors[guarantor["id"]] = guarantor
    return success_object(serialize(guarantor), 201)


@bp.route("/api/guarantors", methods=["GET"])
def list_guarantors():
    user_id, role = get_context()
    require_role(role, ["ComplianceAdmin", "Screener", "Landlord", "Applicant"])
    items = sorted(store.guarantors.values(), key=lambda g: g["created_at"])
    if role in ("Landlord", "Applicant"):
        scoped = []
        for g in items:
            app = store.applications.get(g["application_id"])
            if app is None:
                continue
            if role == "Landlord" and app["landlord_id"] == user_id:
                scoped.append(g)
            elif role == "Applicant" and app["applicant_id"] == user_id:
                scoped.append(g)
        items = scoped
    application_id = request.args.get("application_id")
    if application_id is not None:
        items = [g for g in items if g["application_id"] == application_id]
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize(g) for g in page], limit, offset, total)


@bp.route("/api/guarantors/<gid>", methods=["GET"])
def get_guarantor(gid):
    user_id, role = get_context()
    require_role(role, ["ComplianceAdmin", "Screener", "Landlord", "Applicant"])
    g = store.guarantors.get(gid)
    if g is None:
        raise ApiError(ERR_NOT_FOUND, "Guarantor not found", 404)
    app = store.applications.get(g["application_id"])
    if app is not None:
        _scoped_read_check(user_id, role, app)
    return success_object(serialize(g))


@bp.route("/api/guarantors/<gid>/evaluate", methods=["POST"])
def evaluate_guarantor(gid):
    user_id, role = get_context()
    require_role(role, ["Screener"])
    g = store.guarantors.get(gid)
    if g is None:
        raise ApiError(ERR_NOT_FOUND, "Guarantor not found", 404)
    app = store.applications.get(g["application_id"])
    if app is None:
        raise ApiError(ERR_NOT_FOUND, "Application not found", 404)

    body = get_body()
    verified_income = req_int(body, "verified_monthly_income_cents")
    credit_score = req_int(body, "credit_score")

    # From-state: guarantor PENDING; application non-terminal.
    if g["status"] != "PENDING":
        raise ApiError(ERR_INVALID_GUARANTOR_STATE, "Guarantor not in PENDING", 409)
    if app["status"] in TERMINAL:
        raise ApiError(ERR_APPLICATION_TERMINAL, "Application is in a terminal state", 409)

    criteria = store.criteria.get(app.get("criteria_id"))
    policy = criteria["guarantor_policy"] if criteria is not None else None

    iv = application_income_verification(app["id"])
    applicant_verified = (
        iv["verified_monthly_income_cents"]
        if iv is not None and iv["status"] == "VERIFIED" and iv["verified_monthly_income_cents"] is not None
        else 0
    )

    qualifies = False
    if criteria is not None:
        if policy == "INDEPENDENT_ONLY":
            threshold = round_half_up_cents(
                Decimal(str(criteria["guarantor_income_multiplier"])) * app["monthly_rent_cents"]
            )
            qualifies = verified_income >= threshold
        elif policy == "COMBINED_ALLOWED":
            threshold = round_half_up_cents(
                Decimal(str(criteria["income_multiplier"])) * app["monthly_rent_cents"]
            )
            qualifies = (applicant_verified + verified_income) >= threshold

    g["verified_monthly_income_cents"] = verified_income
    g["credit_score"] = credit_score
    g["qualification_policy_used"] = policy
    g["status"] = "APPROVED" if qualifies else "DECLINED"
    touch(g)
    return success_object(serialize(g))


# ---------------------------------------------------------------------------
# Income verifications
# ---------------------------------------------------------------------------

@bp.route("/api/applications/<aid>/income-verifications", methods=["POST"])
def create_income_verification(aid):
    user_id, role = get_context()
    require_role(role, ["Screener"])
    app = _get_application_or_404(aid)
    if app["status"] in TERMINAL:
        raise ApiError(ERR_APPLICATION_TERMINAL, "Application is in a terminal state", 409)
    if application_income_verification(app["id"]) is not None:
        raise ApiError(
            ERR_INCOME_VERIFICATION_EXISTS,
            "An income verification already exists for this application",
            409,
        )
    body = get_body()
    iv = stamp_new({
        "application_id": app["id"],
        "employer_name": req_string(body, "employer_name"),
        "verified_monthly_income_cents": None,
        "status": "PENDING",
        "failure_reason": None,
    })
    store.income_verifications[iv["id"]] = iv
    return success_object(serialize(iv), 201)


@bp.route("/api/income-verifications", methods=["GET"])
def list_income_verifications():
    user_id, role = get_context()
    require_role(role, ["ComplianceAdmin", "Screener", "Landlord", "Applicant"])
    items = sorted(store.income_verifications.values(), key=lambda v: v["created_at"])
    if role in ("Landlord", "Applicant"):
        scoped = []
        for v in items:
            app = store.applications.get(v["application_id"])
            if app is None:
                continue
            if role == "Landlord" and app["landlord_id"] == user_id:
                scoped.append(v)
            elif role == "Applicant" and app["applicant_id"] == user_id:
                scoped.append(v)
        items = scoped
    application_id = request.args.get("application_id")
    if application_id is not None:
        items = [v for v in items if v["application_id"] == application_id]
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize(v) for v in page], limit, offset, total)


@bp.route("/api/income-verifications/<vid>", methods=["GET"])
def get_income_verification(vid):
    user_id, role = get_context()
    require_role(role, ["ComplianceAdmin", "Screener", "Landlord", "Applicant"])
    iv = store.income_verifications.get(vid)
    if iv is None:
        raise ApiError(ERR_NOT_FOUND, "Income verification not found", 404)
    app = store.applications.get(iv["application_id"])
    if app is not None:
        _scoped_read_check(user_id, role, app)
    return success_object(serialize(iv))


@bp.route("/api/income-verifications/<vid>/resolve", methods=["POST"])
def resolve_income_verification(vid):
    user_id, role = get_context()
    require_role(role, ["Screener"])
    iv = store.income_verifications.get(vid)
    if iv is None:
        raise ApiError(ERR_NOT_FOUND, "Income verification not found", 404)
    body = get_body()
    outcome = req_enum(body, "outcome", ("VERIFIED", "FAILED"))
    if iv["status"] != "PENDING":
        raise ApiError(
            ERR_INVALID_INCOME_VERIFICATION_STATE,
            "Income verification not in PENDING",
            409,
        )
    if outcome == "VERIFIED":
        amount = body.get("verified_monthly_income_cents")
        if amount is None:
            raise ApiError(ERR_INVALID_REQUEST, "Missing required field: verified_monthly_income_cents", 400)
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise ApiError(ERR_INVALID_REQUEST, "Field 'verified_monthly_income_cents' must be an integer", 400)
        iv["verified_monthly_income_cents"] = amount
        iv["failure_reason"] = None
        iv["status"] = "VERIFIED"
    else:
        reason = body.get("failure_reason")
        if reason is None:
            raise ApiError(ERR_INVALID_REQUEST, "Missing required field: failure_reason", 400)
        if not isinstance(reason, str):
            raise ApiError(ERR_INVALID_REQUEST, "Field 'failure_reason' must be a string", 400)
        iv["failure_reason"] = reason
        iv["verified_monthly_income_cents"] = None
        iv["status"] = "FAILED"
    touch(iv)
    return success_object(serialize(iv))


@bp.route("/api/income-verifications/<vid>/retry", methods=["POST"])
def retry_income_verification(vid):
    user_id, role = get_context()
    require_role(role, ["Screener"])
    iv = store.income_verifications.get(vid)
    if iv is None:
        raise ApiError(ERR_NOT_FOUND, "Income verification not found", 404)
    if iv["status"] != "FAILED":
        raise ApiError(
            ERR_INVALID_INCOME_VERIFICATION_STATE,
            "Income verification not in FAILED",
            409,
        )
    iv["status"] = "PENDING"
    iv["failure_reason"] = None
    iv["verified_monthly_income_cents"] = None
    touch(iv)
    return success_object(serialize(iv))
