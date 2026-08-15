"""Site-of-care redirection endpoints (PRD 3.5)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_AUTH_NOT_APPROVED,
    ERR_REDIRECTION_NOT_OFFERED, ERR_PROVIDER_SCOPE_VIOLATION,
)
from middleware import authorized
from response import success_object
from routes.helpers import (
    apply_filters, get_body, get_or_404, list_response, public, read_all,
)
from services.pricing import redirection_incentive_estimate, touch

bp = Blueprint("redirections", __name__)

CANDIDATE_SITES = ("OFFICE", "HOME", "AMBULATORY")


def _redirection_provider_id(red):
    auth = db["prior_authorizations"].get(red["auth_id"])
    return auth["provider_account_id"] if auth is not None else None


@bp.get("/api/redirections")
def list_redirections():
    caller = read_all()
    items = list(db["redirections"].values())
    if caller.role == "ProviderRep":
        afilter = request.args.get("auth_id")
        if afilter is not None:
            a = db["prior_authorizations"].get(afilter)
            if a is not None and a["provider_account_id"] != caller.user_id:
                raise_error(ERR_PROVIDER_SCOPE_VIOLATION, "auth_id filter is foreign")
        # scope resolved through the owning authorization
        items = [r for r in items if _redirection_provider_id(r) == caller.user_id]
    items = apply_filters(items, ["auth_id", "status"])
    return list_response(items)


@bp.get("/api/redirections/<redirectionId>")
def get_redirection(redirectionId):
    # single-redirection reads are not scope-guarded (PRD 2.1 lists only the collection)
    read_all()
    red = get_or_404("redirections", redirectionId)
    return success_object(public(red))


@bp.post("/api/redirections/<redirectionId>/accept")
def accept_redirection(redirectionId):
    authorized(["CaseManager"])
    body = get_body()
    # ---- shape (stage 4): accepted_site must be one of the offered candidates ----
    accepted_site = body.get("accepted_site")
    if not isinstance(accepted_site, str) or accepted_site not in CANDIDATE_SITES:
        raise_error(ERR_INVALID_REQUEST, "accepted_site must be one of the candidate_sites")
    # ---- existence (stage 5) ----
    red = get_or_404("redirections", redirectionId)
    # ---- target state (stage 7) ----
    if red["status"] != "OFFERED":
        raise_error(ERR_REDIRECTION_NOT_OFFERED, "accept requires an OFFERED redirection")
    # ---- cross-entity state (stage 8) ----
    auth = db["prior_authorizations"][red["auth_id"]]
    if auth["status"] != "APPROVED":
        raise_error(ERR_AUTH_NOT_APPROVED, "accept requires an APPROVED authorization")
    # ---- fiscal: incentive estimate needs an ASP rate effective today ----
    incentive = redirection_incentive_estimate(red)
    red["status"] = "ACCEPTED"
    red["accepted_site"] = accepted_site
    red["member_incentive_cents"] = incentive
    touch(red)
    return success_object(public(red))


@bp.post("/api/redirections/<redirectionId>/decline")
def decline_redirection(redirectionId):
    authorized(["CaseManager"])
    get_body()
    red = get_or_404("redirections", redirectionId)
    if red["status"] != "OFFERED":
        raise_error(ERR_REDIRECTION_NOT_OFFERED, "decline requires an OFFERED redirection")
    red["status"] = "DECLINED"
    touch(red)
    return success_object(public(red))
