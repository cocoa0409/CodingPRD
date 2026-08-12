"""Authority singleton and logical clock endpoints."""

from flask import Blueprint

from auth import ALL_ROLES, require_roles
from envelope import ok_list, ok_object
from errors import (ApiError, ERR_DISSOLUTION_BLOCKED, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_NO_DEFAULT_PRODUCT,
                    ERR_NOT_FOUND, ERR_STALE_AUTHORITY_VERSION,
                    ERR_UNIQUENESS_CONFLICT)
from serializers import ser_authority
from services import advance_epoch, default_product_ok
from store import STORE
from util import (as_enum, as_int, as_number, as_str, fmt_dt, get_body, parse_dt,
                  req_present)

bp = Blueprint("authority", __name__)

TERRITORIES = {"PGE", "SCE", "SDGE"}
RATE_POLICIES = {"COST_PLUS", "DISCOUNT_TO_INCUMBENT", "VALUE_BASED"}


def _authority_or_404():
    auth = STORE.authority()
    if auth is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Authority not found")
    return auth


@bp.post("/cca/authority")
@require_roles("BoardDirector")
def create_authority():
    body = get_body(__import__("flask").request)
    # Singleton uniqueness (priority 11) before field validity (priority 16).
    if STORE.authority() is not None:
        raise ApiError(ERR_UNIQUENESS_CONFLICT, 409,
                       "An Authority already exists for this deployment")
    display_name = as_str(req_present(body, "display_name"), "display_name")
    territory = as_enum(req_present(body, "utility_territory_code"),
                        "utility_territory_code", TERRITORIES)
    erba = as_str(req_present(body, "er_balancing_authority"), "er_balancing_authority")
    policy = as_enum(req_present(body, "rate_setting_policy"),
                     "rate_setting_policy", RATE_POLICIES)
    floor = body.get("discount_floor_bps", 0)
    floor = as_int(floor, "discount_floor_bps")
    if not (0 <= floor <= 2000):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "discount_floor_bps must lie between 0 and 2000 inclusive")
    rps = as_number(req_present(body, "rps_target_pct"), "rps_target_pct")
    if not (0 < float(rps) <= 1.0):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "rps_target_pct must be > 0 and <= 1.0")
    cap = body.get("bad_debt_trueup_cap_pct", 0.01)
    cap = as_number(cap, "bad_debt_trueup_cap_pct")
    if not (0 <= float(cap) <= 0.05):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "bad_debt_trueup_cap_pct must lie between 0 and 0.05 inclusive")

    rec = STORE.new_record()
    rec.update({
        "display_name": display_name,
        "utility_territory_code": territory,
        "er_balancing_authority": erba,
        "rate_setting_policy": policy,
        "discount_floor_bps": floor,
        "rps_target_pct": rps,
        "bad_debt_trueup_cap_pct": cap,
        "climate_reserve_balance_cents": 0,
        "status": "FORMING",
    })
    STORE.authorities[rec["id"]] = rec
    return ok_object(ser_authority(rec), status=201)


@bp.get("/cca/authority")
@require_roles(*ALL_ROLES)
def read_authority():
    auth = STORE.authority()
    items = [ser_authority(auth)] if auth is not None else []
    return ok_list(items, pagination={
        "limit": len(items) if items else 10,
        "offset": 0,
        "total_count": len(items),
        "has_more": False,
    })


@bp.patch("/cca/authority")
@require_roles("BoardDirector")
def patch_authority():
    auth = _authority_or_404()
    body = get_body(__import__("flask").request)
    expected = req_present(body, "expected_authority_version")
    expected = as_int(expected, "expected_authority_version")
    if expected != auth["version"]:
        raise ApiError(ERR_STALE_AUTHORITY_VERSION, 412,
                       "expected_authority_version does not match the authority's current version")
    if "rate_setting_policy" in body and body["rate_setting_policy"] is not None:
        auth["rate_setting_policy"] = as_enum(body["rate_setting_policy"],
                                              "rate_setting_policy", RATE_POLICIES)
    if "discount_floor_bps" in body and body["discount_floor_bps"] is not None:
        floor = as_int(body["discount_floor_bps"], "discount_floor_bps")
        if not (0 <= floor <= 2000):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "discount_floor_bps must lie between 0 and 2000 inclusive")
        auth["discount_floor_bps"] = floor
    if "rps_target_pct" in body and body["rps_target_pct"] is not None:
        rps = as_number(body["rps_target_pct"], "rps_target_pct")
        if not (0 < float(rps) <= 1.0):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "rps_target_pct must be > 0 and <= 1.0")
        auth["rps_target_pct"] = rps
    if "bad_debt_trueup_cap_pct" in body and body["bad_debt_trueup_cap_pct"] is not None:
        cap = as_number(body["bad_debt_trueup_cap_pct"], "bad_debt_trueup_cap_pct")
        if not (0 <= float(cap) <= 0.05):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "bad_debt_trueup_cap_pct must lie between 0 and 0.05 inclusive")
        auth["bad_debt_trueup_cap_pct"] = cap
    STORE.touch(auth)
    return ok_object(ser_authority(auth))


@bp.post("/cca/authority/activate")
@require_roles("BoardDirector")
def activate_authority():
    auth = _authority_or_404()
    if auth["status"] != "FORMING":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Authority in status {auth['status']} cannot be activated")
    if not default_product_ok(STORE.now()):
        raise ApiError(ERR_NO_DEFAULT_PRODUCT, 422,
                       "Activation requires an ADOPTED default product with an ADOPTED "
                       "rate schedule covering the current date")
    auth["status"] = "ACTIVE"
    STORE.touch(auth)
    return ok_object(ser_authority(auth))


@bp.post("/cca/authority/suspend")
@require_roles("BoardDirector")
def suspend_authority():
    auth = _authority_or_404()
    if auth["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Authority in status {auth['status']} cannot be suspended")
    for n in STORE.notices.values():
        if n["status"] == "ENROLLING":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Cannot suspend while an enrollment notice is ENROLLING")
    # Cascade: ISSUED waves are cancelled; their NOTICED accounts revert to PROSPECT.
    for n in STORE.notices.values():
        if n["status"] == "ISSUED":
            n["status"] = "CANCELLED"
            STORE.touch(n)
            for a in STORE.accounts.values():
                if (a["current_enrollment_notice_id"] == n["id"]
                        and a["enrollment_state"] == "NOTICED"):
                    a["enrollment_state"] = "PROSPECT"
                    a["current_enrollment_notice_id"] = None
                    STORE.touch(a)
    auth["status"] = "SUSPENDED"
    STORE.touch(auth)
    return ok_object(ser_authority(auth))


@bp.post("/cca/authority/reinstate")
@require_roles("BoardDirector")
def reinstate_authority():
    auth = _authority_or_404()
    if auth["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Authority in status {auth['status']} cannot be reinstated")
    auth["status"] = "ACTIVE"
    STORE.touch(auth)
    return ok_object(ser_authority(auth))


@bp.post("/cca/authority/dissolve")
@require_roles("BoardDirector")
def dissolve_authority():
    auth = _authority_or_404()
    if auth["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Authority in status {auth['status']} cannot be dissolved")
    if any(a["enrollment_state"] == "ENROLLED" for a in STORE.accounts.values()):
        raise ApiError(ERR_DISSOLUTION_BLOCKED, 409,
                       "Dissolution blocked: enrolled accounts remain")
    year = STORE.now().year
    trailing = {year - 3, year - 2, year - 1, year}
    for f in STORE.filings.values():
        if f["compliance_year"] in trailing and f["status"] not in ("ACCEPTED_BY_CPUC", "WITHDRAWN"):
            raise ApiError(ERR_DISSOLUTION_BLOCKED, 409,
                           "Dissolution blocked: open compliance filings in the trailing four years")
    for p in STORE.pools.values():
        if p["status"] != "TRUED_UP":
            raise ApiError(ERR_DISSOLUTION_BLOCKED, 409,
                           "Dissolution blocked: bad-debt pools not trued up")
    auth["status"] = "DISSOLVED"
    STORE.touch(auth)
    return ok_object(ser_authority(auth))


# --- logical clock (test-driving) -------------------------------------------

@bp.post("/cca/_clock/set_current_utc")
@require_roles("BoardDirector")
def set_clock():
    body = get_body(__import__("flask").request)
    to_iso = req_present(body, "to_iso8601")
    dt = parse_dt(to_iso, "to_iso8601")
    STORE.clock_now = dt
    return ok_object({"current_utc": fmt_dt(STORE.now())})


@bp.post("/cca/_clock/advance_epoch")
@require_roles("BoardDirector")
def advance_epoch_endpoint():
    notices, accounts, contracts = advance_epoch()
    return ok_object({
        "advanced_notices": notices,
        "flipped_accounts": accounts,
        "advanced_contracts": contracts,
    })
