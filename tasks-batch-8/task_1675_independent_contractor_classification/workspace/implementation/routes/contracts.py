"""ContractAgreement and ContractAmendment endpoints."""

from flask import Blueprint, request

from db import store, new_id, parse_date
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_CONTRACT_PERIOD_OVERLAP, ERR_CONTRACTOR_NOT_VERIFIED,
    ERR_INSURANCE_BELOW_MINIMUM, ERR_EXCEPTION_REQUIRED, ERR_EXCEPTION_EXPIRED,
    ERR_STALE_CONTRACT_VERSION,
)
from middleware import require_auth, ALL_ROLES
from response import success, paginate
from services.core import (
    stamp_new, touch, get_engagement_or_404, lazy_expire_contract,
    lazy_expire_grant, recompute_scope_creep, require_high_tier_exception,
)

bp = Blueprint("contracts", __name__)

RATE_UNITS = {"HOURLY", "DAILY", "PROJECT"}


@bp.route("/api/engagements/<eid>/contracts", methods=["POST"])
def create_contract(eid):
    require_auth(["EngagementManager"])
    body = request.get_json(silent=True) or {}
    start_date = body.get("start_date")
    end_date = body.get("end_date")
    rate_cents = body.get("rate_cents")
    rate_unit = body.get("rate_unit")

    sd = parse_date(start_date)
    ed = parse_date(end_date)
    if sd is None or ed is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "start_date/end_date must be ISO dates")
    if ed <= sd:
        raise ApiError(ERR_INVALID_REQUEST, 400, "end_date must be > start_date")
    if rate_cents is None or not isinstance(rate_cents, int) or isinstance(rate_cents, bool) or rate_cents <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "rate_cents must be an integer > 0")
    if rate_unit not in RATE_UNITS:
        raise ApiError(ERR_INVALID_REQUEST, 400, "invalid rate_unit")

    eng = get_engagement_or_404(eid)
    if eng["status"] not in ("APPROVED", "ACTIVE"):
        raise ApiError(ERR_INVALID_STATE, 409, "Contract drafting requires APPROVED or ACTIVE engagement")

    # half-open overlap per (contractor_id, jurisdiction_id)
    for c in store.contracts.values():
        if c["contractor_id"] != eng["contractor_id"]:
            continue
        if c["jurisdiction_id"] != eng["jurisdiction_id"]:
            continue
        lazy_expire_contract(c)
        if c["status"] not in ("DRAFT", "EXECUTED", "SUSPENDED"):
            continue
        csd = parse_date(c["start_date"])
        ced = parse_date(c["end_date"])
        if sd < ced and csd < ed:
            raise ApiError(ERR_CONTRACT_PERIOD_OVERLAP, 409, "Contract period overlaps an existing contract")

    contract = {
        "id": new_id(),
        "engagement_id": eid,
        "contractor_id": eng["contractor_id"],
        "jurisdiction_id": eng["jurisdiction_id"],
        "start_date": start_date,
        "end_date": end_date,
        "rate_cents": rate_cents,
        "rate_unit": rate_unit,
        "status": "DRAFT",
        "original_rate_cents": None,
    }
    stamp_new(contract)
    store.contracts[contract["id"]] = contract
    return success(contract, status=201)


@bp.route("/api/engagements/<eid>/contracts", methods=["GET"])
def list_engagement_contracts(eid):
    require_auth(ALL_ROLES)
    get_engagement_or_404(eid)
    items = [c for c in store.contracts.values() if c["engagement_id"] == eid]
    for c in items:
        lazy_expire_contract(c)
    items.sort(key=lambda c: c["created_at"])
    page, pg = paginate(items, request.args)
    return success(page, pagination=pg)


@bp.route("/api/contracts/<cid>", methods=["GET"])
def get_contract(cid):
    require_auth(ALL_ROLES)
    c = store.contracts.get(cid)
    if c is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Contract not found")
    lazy_expire_contract(c)
    return success(c)


@bp.route("/api/contracts", methods=["GET"])
def list_contracts():
    require_auth(ALL_ROLES)
    items = list(store.contracts.values())
    for key in ("contractor_id", "jurisdiction_id", "engagement_id", "status"):
        v = request.args.get(key)
        if v:
            items = [c for c in items if c.get(key) == v]
    for c in items:
        lazy_expire_contract(c)
    items.sort(key=lambda c: c["created_at"])
    page, pg = paginate(items, request.args)
    return success(page, pagination=pg)


@bp.route("/api/contracts/<cid>/execute", methods=["POST"])
def execute_contract(cid):
    require_auth(["EngagementManager"])
    c = store.contracts.get(cid)
    if c is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Contract not found")
    lazy_expire_contract(c)
    if c["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "execute requires DRAFT")

    contractor = store.contractors.get(c["contractor_id"])
    eng = store.engagements.get(c["engagement_id"])
    jur = store.jurisdictions.get(c["jurisdiction_id"])

    if contractor is None or contractor["verification_status"] != "VERIFIED":
        raise ApiError(ERR_CONTRACTOR_NOT_VERIFIED, 422, "Contractor is not VERIFIED")
    if contractor["insurance_coverage_cents"] < jur["min_insurance_cents"]:
        raise ApiError(ERR_INSURANCE_BELOW_MINIMUM, 422, "Insurance below jurisdiction minimum")
    if eng is not None and eng.get("risk_tier") == "HIGH":
        require_high_tier_exception(eng)

    c["status"] = "EXECUTED"
    if c.get("original_rate_cents") is None:
        c["original_rate_cents"] = c["rate_cents"]
    touch(c)
    if eng is not None:
        recompute_scope_creep(eng)
    return success(c)


# ---------------------------------------------------------------------------
# amendments
# ---------------------------------------------------------------------------

@bp.route("/api/contracts/<cid>/amendments", methods=["POST"])
def create_amendment(cid):
    require_auth(["EngagementManager"])
    body = request.get_json(silent=True) or {}
    expected = body.get("expected_contract_version")
    scope_change_summary = body.get("scope_change_summary")
    new_rate_cents = body.get("new_rate_cents")
    new_end_date = body.get("new_end_date")
    exception_grant_id = body.get("exception_grant_id")

    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_contract_version is required")
    if not scope_change_summary or not isinstance(scope_change_summary, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "scope_change_summary is required")
    if new_rate_cents is not None:
        if not isinstance(new_rate_cents, int) or isinstance(new_rate_cents, bool) or new_rate_cents <= 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "new_rate_cents must be an integer > 0")
    if new_end_date is not None and parse_date(new_end_date) is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "new_end_date must be an ISO date")
    if exception_grant_id is not None and not isinstance(exception_grant_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "exception_grant_id must be a string")

    c = store.contracts.get(cid)
    if c is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Contract not found")
    lazy_expire_contract(c)

    if expected != c["version"]:
        raise ApiError(ERR_STALE_CONTRACT_VERSION, 412, "Stale contract version")

    eng = store.engagements.get(c["engagement_id"])

    # HIGH risk tier: exception_grant_id required; referenced grant must not be expired
    if eng is not None and eng.get("risk_tier") == "HIGH":
        if not exception_grant_id:
            raise ApiError(ERR_EXCEPTION_REQUIRED, 422,
                           "exception_grant_id required for HIGH risk tier amendments")
        g = store.exceptions.get(exception_grant_id)
        if g is None:
            raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Exception grant not found")
        lazy_expire_grant(g)
        if g["status"] == "EXPIRED":
            raise ApiError(ERR_EXCEPTION_EXPIRED, 422, "Referenced exception grant has expired")
    elif exception_grant_id is not None:
        g = store.exceptions.get(exception_grant_id)
        if g is None:
            raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Exception grant not found")
        lazy_expire_grant(g)
        if g["status"] == "EXPIRED":
            raise ApiError(ERR_EXCEPTION_EXPIRED, 422, "Referenced exception grant has expired")

    am = {
        "id": new_id(),
        "contract_id": cid,
        "new_rate_cents": new_rate_cents,
        "new_end_date": new_end_date,
        "scope_change_summary": scope_change_summary,
        "exception_grant_id": exception_grant_id,
        "status": "PROPOSED",
    }
    stamp_new(am)
    store.amendments[am["id"]] = am
    touch(c)  # proposal bumps contract version
    return success(am, status=201)


@bp.route("/api/contracts/<cid>/amendments", methods=["GET"])
def list_amendments(cid):
    require_auth(ALL_ROLES)
    c = store.contracts.get(cid)
    if c is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Contract not found")
    items = [a for a in store.amendments.values() if a["contract_id"] == cid]
    items.sort(key=lambda a: a["created_at"])
    page, pg = paginate(items, request.args)
    return success(page, pagination=pg)


@bp.route("/api/amendments/<aid>/approve", methods=["POST"])
def adjudicate_amendment(aid):
    require_auth(["LegalApprover"])
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    if decision not in ("APPROVED", "REJECTED"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "decision must be APPROVED or REJECTED")
    am = store.amendments.get(aid)
    if am is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Amendment not found")
    if am["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE, 409, "Amendment is not PROPOSED")

    if decision == "REJECTED":
        am["status"] = "REJECTED"
        touch(am)
        return success(am)

    c = store.contracts.get(am["contract_id"])
    if c is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Contract not found")
    lazy_expire_contract(c)
    if c["status"] != "EXECUTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Parent contract must be EXECUTED")

    # compound: PROPOSED -> APPROVED -> APPLIED in the same request
    am["status"] = "APPLIED"
    touch(am)
    if am.get("new_rate_cents") is not None:
        c["rate_cents"] = am["new_rate_cents"]
    if am.get("new_end_date") is not None:
        c["end_date"] = am["new_end_date"]
    touch(c)
    eng = store.engagements.get(c["engagement_id"])
    if eng is not None:
        recompute_scope_creep(eng)
    return success(am)
