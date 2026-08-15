"""Adverse action notice and consistency audit routes."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import store
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_INVALID_NOTICE_STATE,
    ERR_UNGROUNDED_ADVERSE_REASON,
)
from middleware import (
    get_context, require_role,
    check_landlord_ownership, check_applicant_ownership,
)
from response import success_object, success_list
from services.core import application_income_verification, DISPUTE_WINDOW_DAYS
from util import (
    clock, get_body, pagination_params, paginate,
    stamp_new, touch, serialize, serialize_audit,
)

bp = Blueprint("notices", __name__)

ALL_REASON_CODES = (
    "CREDIT_SCORE_BELOW_MINIMUM",
    "RENT_TO_INCOME_BELOW_REQUIRED",
    "INCOME_UNVERIFIABLE",
    "EVICTION_RECORD",
    "CRIMINAL_RECORD",
)


def _scoped_read_check(user_id, role, app):
    if app is None:
        return
    if role == "Landlord":
        check_landlord_ownership(user_id, role, app["landlord_id"])
    elif role == "Applicant":
        check_applicant_ownership(user_id, role, app["applicant_id"])


def _grounded(reason_codes, app):
    """Every code must be grounded in the application's current data."""
    criteria = store.criteria.get(app.get("criteria_id"))
    iv = application_income_verification(app["id"])
    for code in reason_codes:
        if code == "CREDIT_SCORE_BELOW_MINIMUM":
            if app.get("credit_score") is None or criteria is None:
                return False
            if not app["credit_score"] < criteria["min_credit_score"]:
                return False
        elif code == "EVICTION_RECORD":
            if (app.get("eviction_included_count") or 0) <= 0:
                return False
        elif code == "CRIMINAL_RECORD":
            if (app.get("criminal_included_count") or 0) <= 0:
                return False
        elif code == "INCOME_UNVERIFIABLE":
            if iv is None or iv["status"] != "FAILED":
                return False
        elif code == "RENT_TO_INCOME_BELOW_REQUIRED":
            if app.get("affordability_passes") is not False:
                return False
            if iv is None or iv["status"] != "VERIFIED":
                return False
        else:
            return False
    return True


# ---------------------------------------------------------------------------
# Adverse action notices
# ---------------------------------------------------------------------------

@bp.route("/api/adverse-action-notices", methods=["GET"])
def list_notices():
    user_id, role = get_context()
    require_role(role, ["ComplianceAdmin", "Screener", "Landlord", "Applicant"])
    items = sorted(store.notices.values(), key=lambda n: n["created_at"])
    if role in ("Landlord", "Applicant"):
        scoped = []
        for n in items:
            app = store.applications.get(n["application_id"])
            if app is None:
                continue
            if role == "Landlord" and app["landlord_id"] == user_id:
                scoped.append(n)
            elif role == "Applicant" and app["applicant_id"] == user_id:
                scoped.append(n)
        items = scoped
    application_id = request.args.get("application_id")
    if application_id is not None:
        items = [n for n in items if n["application_id"] == application_id]
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize(n) for n in page], limit, offset, total)


@bp.route("/api/adverse-action-notices/<nid>", methods=["GET"])
def get_notice(nid):
    user_id, role = get_context()
    require_role(role, ["ComplianceAdmin", "Screener", "Landlord", "Applicant"])
    n = store.notices.get(nid)
    if n is None:
        raise ApiError(ERR_NOT_FOUND, "Notice not found", 404)
    _scoped_read_check(user_id, role, store.applications.get(n["application_id"]))
    return success_object(serialize(n))


@bp.route("/api/adverse-action-notices/<nid>/issue", methods=["POST"])
def issue_notice(nid):
    user_id, role = get_context()
    require_role(role, ["Landlord"])
    n = store.notices.get(nid)
    if n is None:
        raise ApiError(ERR_NOT_FOUND, "Notice not found", 404)
    app = store.applications.get(n["application_id"])
    if app is None:
        raise ApiError(ERR_NOT_FOUND, "Application not found", 404)
    check_landlord_ownership(user_id, role, app["landlord_id"])

    body = get_body()
    override = body.get("reason_codes")
    if override is not None:
        if not isinstance(override, list) or any(not isinstance(x, str) for x in override):
            raise ApiError(ERR_INVALID_REQUEST, "Field 'reason_codes' must be an array of strings", 400)
        effective = override
    else:
        effective = list(n["reason_codes"])

    if n["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_NOTICE_STATE, "Notice not in DRAFT", 409)

    if not effective or not _grounded(effective, app):
        raise ApiError(
            ERR_UNGROUNDED_ADVERSE_REASON,
            "Adverse action reason codes must be non-empty and each grounded in the application's current data",
            422,
        )

    at = clock()
    n["reason_codes"] = effective
    n["status"] = "ISSUED"
    n["issued_at"] = at
    n["dispute_deadline"] = at + timedelta(days=DISPUTE_WINDOW_DAYS)
    touch(n)
    return success_object(serialize(n))


@bp.route("/api/adverse-action-notices/<nid>/rescind", methods=["POST"])
def rescind_notice(nid):
    user_id, role = get_context()
    require_role(role, ["Landlord"])
    n = store.notices.get(nid)
    if n is None:
        raise ApiError(ERR_NOT_FOUND, "Notice not found", 404)
    app = store.applications.get(n["application_id"])
    if app is None:
        raise ApiError(ERR_NOT_FOUND, "Application not found", 404)
    check_landlord_ownership(user_id, role, app["landlord_id"])
    if n["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_NOTICE_STATE, "Notice not in ISSUED", 409)
    n["status"] = "RESCINDED"
    n["rescinded_at"] = clock()
    touch(n)
    return success_object(serialize(n))


# ---------------------------------------------------------------------------
# Consistency audits
# ---------------------------------------------------------------------------

@bp.route("/api/landlords/<lid>/consistency-audits", methods=["POST"])
def run_audit(lid):
    user_id, role = get_context()
    require_role(role, ["ComplianceAdmin"])
    landlord = store.landlords.get(lid)
    if landlord is None:
        raise ApiError(ERR_NOT_FOUND, "Landlord not found", 404)

    decided = [
        a for a in store.applications.values()
        if a["landlord_id"] == lid and a["status"] in ("APPROVED", "DENIED")
    ]
    decided.sort(key=lambda a: a["created_at"])

    inconsistent_ids = []
    for a in decided:
        if a["decision"] == "APPROVE" and a.get("recommendation") == "RECOMMEND_DENY":
            inconsistent_ids.append(a["id"])
        elif a["decision"] == "DENY" and a.get("recommendation") == "RECOMMEND_APPROVE":
            inconsistent_ids.append(a["id"])

    examined = len(decided)
    found = len(inconsistent_ids)
    if examined == 0:
        deviation_rate = 0
    else:
        deviation_rate = float(
            (Decimal(found) / Decimal(examined)).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
        )

    run = stamp_new({
        "landlord_id": lid,
        "run_at": clock(),
        "applications_examined": examined,
        "inconsistencies_found": found,
        "inconsistent_application_ids": inconsistent_ids,
        "deviation_rate": deviation_rate,
    }, with_common=False)
    store.audit_runs[run["id"]] = run
    return success_object(serialize_audit(run), 201)


@bp.route("/api/landlords/<lid>/consistency-audits", methods=["GET"])
def list_audits(lid):
    user_id, role = get_context()
    require_role(role, ["ComplianceAdmin", "Screener", "Landlord", "Applicant"])
    landlord = store.landlords.get(lid)
    if landlord is None:
        raise ApiError(ERR_NOT_FOUND, "Landlord not found", 404)
    check_landlord_ownership(user_id, role, lid)
    items = sorted(
        (r for r in store.audit_runs.values() if r["landlord_id"] == lid),
        key=lambda r: r["created_at"],
    )
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_audit(r) for r in page], limit, offset, total)
