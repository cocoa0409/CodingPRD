"""Program endpoints: creation, OCC-guarded amendment, open, archive."""

from flask import Blueprint, request

from errors import raise_err, ERR_VALIDATION, ERR_STALE_VERSION, \
    ERR_PROGRAM_NOT_OPEN, ERR_PROGRAM_HAS_ACTIVE_SUBSCRIPTIONS, \
    ERR_PROGRAM_HOLDING_ACCOUNT_MISSING
from store import STORE, new_id, next_seq, now_ts
from util import auth, require_role, ok_object, body_json, req_str, opt_str, \
    req_int, opt_int, req_enum, req_list, opt_list, get_or_404, TECHNOLOGIES
from services import program_committed_capacity_kw, \
    program_retired_mwh_current_year, waitlist_promotion_scan, touch
from routes.generators import list_with_serializer

bp = Blueprint("programs", __name__)

LIVE_SUB_STATUSES = ("PENDING", "ACTIVE", "WAITLISTED", "SUSPENDED")


def serialize_program(p):
    out = {k: v for k, v in p.items() if not k.startswith("_")}
    out["committed_capacity_kw"] = program_committed_capacity_kw(p["id"])
    out["retired_mwh_current_year"] = program_retired_mwh_current_year(p["id"])
    return out


def _validate_rate_tiers(value):
    tiers = value
    if not isinstance(tiers, list):
        raise_err(ERR_VALIDATION, "rate_tiers must be an array")
    for i, tier in enumerate(tiers):
        if not isinstance(tier, dict):
            raise_err(ERR_VALIDATION, "rate_tiers[%d] must be an object" % i)
        if "up_to_kwh" not in tier:
            raise_err(ERR_VALIDATION, "rate_tiers[%d].up_to_kwh is required" % i)
        up_to = tier["up_to_kwh"]
        if up_to is not None and (not isinstance(up_to, int) or isinstance(up_to, bool) or up_to <= 0):
            raise_err(ERR_VALIDATION, "rate_tiers[%d].up_to_kwh must be null or a positive integer" % i)
        rate = tier.get("rate_cents_per_kwh")
        if not isinstance(rate, int) or isinstance(rate, bool) or rate < 0:
            raise_err(ERR_VALIDATION, "rate_tiers[%d].rate_cents_per_kwh must be a non-negative integer" % i)
    return [{"up_to_kwh": t["up_to_kwh"], "rate_cents_per_kwh": t["rate_cents_per_kwh"]}
            for t in tiers]


def _validate_str_list(value, field):
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise_err(ERR_VALIDATION, "%s must be an array of strings" % field)
    return list(value)


def _validate_tech_list(value, field):
    items = _validate_str_list(value, field)
    for v in items:
        if v not in TECHNOLOGIES:
            raise_err(ERR_VALIDATION, "%s entries must be valid technologies" % field)
    return items


@bp.post("/greenpower/programs")
def create_program():
    uid, role = auth()
    require_role(role, "RegistryAdmin")
    body = body_json()
    name = req_str(body, "name")
    market_class = req_enum(body, "market_class", {"VOLUNTARY", "COMPLIANCE"})
    if "eligible_region_codes" not in body or body["eligible_region_codes"] is None:
        raise_err(ERR_VALIDATION, "Missing required field: eligible_region_codes")
    eligible_regions = _validate_str_list(body["eligible_region_codes"], "eligible_region_codes")
    if "eligible_technologies" not in body or body["eligible_technologies"] is None:
        raise_err(ERR_VALIDATION, "Missing required field: eligible_technologies")
    eligible_techs = _validate_tech_list(body["eligible_technologies"], "eligible_technologies")
    capacity_cap_kw = req_int(body, "capacity_cap_kw")
    if capacity_cap_kw <= 0:
        raise_err(ERR_VALIDATION, "capacity_cap_kw must be a positive integer")
    if "rate_tiers" not in body or body["rate_tiers"] is None:
        raise_err(ERR_VALIDATION, "Missing required field: rate_tiers")
    rate_tiers = _validate_rate_tiers(body["rate_tiers"])
    annual_claim_cap_mwh = req_int(body, "annual_claim_cap_mwh")
    if annual_claim_cap_mwh <= 0:
        raise_err(ERR_VALIDATION, "annual_claim_cap_mwh must be a positive integer")
    vintage_window_months = opt_int(body, "vintage_window_months", 12)
    if vintage_window_months <= 0:
        raise_err(ERR_VALIDATION, "vintage_window_months must be a positive integer")
    kwh_per_kw_monthly = opt_int(body, "kwh_per_kw_monthly", 100)
    if kwh_per_kw_monthly <= 0:
        raise_err(ERR_VALIDATION, "kwh_per_kw_monthly must be a positive integer")
    holding_account_id = opt_str(body, "holding_account_id")
    if holding_account_id is not None:
        get_or_404(STORE["accounts"], holding_account_id, "Account")
    now = now_ts()
    program = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "name": name,
        "market_class": market_class,
        "eligible_region_codes": eligible_regions,
        "eligible_technologies": eligible_techs,
        "vintage_window_months": vintage_window_months,
        "capacity_cap_kw": capacity_cap_kw,
        "kwh_per_kw_monthly": kwh_per_kw_monthly,
        "rate_tiers": rate_tiers,
        "annual_claim_cap_mwh": annual_claim_cap_mwh,
        "holding_account_id": holding_account_id,
        "status": "DRAFT",
        "_seq": next_seq(),
    }
    STORE["programs"][program["id"]] = program
    return ok_object(serialize_program(program), 201)


@bp.get("/greenpower/programs")
def list_programs():
    auth()
    filters = {
        "status": request.args.get("status"),
        "market_class": request.args.get("market_class"),
        "holding_account_id": request.args.get("holding_account_id"),
    }
    return list_with_serializer(list(STORE["programs"].values()), filters,
                                serialize_program)


@bp.get("/greenpower/programs/<pid>")
def get_program(pid):
    auth()
    program = get_or_404(STORE["programs"], pid, "Program")
    return ok_object(serialize_program(program))


@bp.patch("/greenpower/programs/<pid>")
def patch_program(pid):
    uid, role = auth()
    require_role(role, "RegistryAdmin")
    body = body_json()
    expected = req_int(body, "expected_program_version")
    # Validate any provided optional fields before applying.
    updates = {}
    if "name" in body and body["name"] is not None:
        updates["name"] = req_str(body, "name")
    if "capacity_cap_kw" in body and body["capacity_cap_kw"] is not None:
        cap = req_int(body, "capacity_cap_kw")
        if cap <= 0:
            raise_err(ERR_VALIDATION, "capacity_cap_kw must be a positive integer")
        updates["capacity_cap_kw"] = cap
    if "rate_tiers" in body and body["rate_tiers"] is not None:
        updates["rate_tiers"] = _validate_rate_tiers(body["rate_tiers"])
    if "eligible_region_codes" in body and body["eligible_region_codes"] is not None:
        updates["eligible_region_codes"] = _validate_str_list(body["eligible_region_codes"], "eligible_region_codes")
    if "eligible_technologies" in body and body["eligible_technologies"] is not None:
        updates["eligible_technologies"] = _validate_tech_list(body["eligible_technologies"], "eligible_technologies")
    if "vintage_window_months" in body and body["vintage_window_months"] is not None:
        v = req_int(body, "vintage_window_months")
        if v <= 0:
            raise_err(ERR_VALIDATION, "vintage_window_months must be a positive integer")
        updates["vintage_window_months"] = v
    if "annual_claim_cap_mwh" in body and body["annual_claim_cap_mwh"] is not None:
        v = req_int(body, "annual_claim_cap_mwh")
        if v <= 0:
            raise_err(ERR_VALIDATION, "annual_claim_cap_mwh must be a positive integer")
        updates["annual_claim_cap_mwh"] = v
    if "holding_account_id" in body:
        updates["holding_account_id"] = opt_str(body, "holding_account_id")

    program = get_or_404(STORE["programs"], pid, "Program")
    if updates.get("holding_account_id") is not None:
        get_or_404(STORE["accounts"], updates["holding_account_id"], "Account")
    if expected != program["version"]:
        raise_err(ERR_STALE_VERSION, "expected_program_version does not match the current program version")

    old_cap = program["capacity_cap_kw"]
    for key, value in updates.items():
        program[key] = value
    touch(program)
    # Raising the capacity cap releases capacity -> waitlist promotion scan.
    if program["capacity_cap_kw"] > old_cap:
        waitlist_promotion_scan(program)
    return ok_object(serialize_program(program))


@bp.post("/greenpower/programs/<pid>/open")
def open_program(pid):
    uid, role = auth()
    require_role(role, "RegistryAdmin")
    program = get_or_404(STORE["programs"], pid, "Program")
    if program["status"] != "DRAFT":
        raise_err(ERR_PROGRAM_NOT_OPEN, "Only a DRAFT program may be opened")
    holding_id = program.get("holding_account_id")
    holding = STORE["accounts"].get(holding_id) if holding_id else None
    if (holding is None or holding["account_type"] != "PROGRAM"
            or holding.get("program_id") != pid):
        raise_err(ERR_PROGRAM_HOLDING_ACCOUNT_MISSING,
                  "Opening requires a wired PROGRAM holding account")
    program["status"] = "OPEN"
    touch(program)
    return ok_object(serialize_program(program))


@bp.post("/greenpower/programs/<pid>/archive")
def archive_program(pid):
    uid, role = auth()
    require_role(role, "RegistryAdmin")
    program = get_or_404(STORE["programs"], pid, "Program")
    if program["status"] != "OPEN":
        raise_err(ERR_PROGRAM_NOT_OPEN, "Only an OPEN program may be archived")
    for s in STORE["subscriptions"].values():
        if s["program_id"] == pid and s["status"] in LIVE_SUB_STATUSES:
            raise_err(ERR_PROGRAM_HAS_ACTIVE_SUBSCRIPTIONS,
                      "The program still has live subscriptions")
    program["status"] = "ARCHIVED"
    touch(program)
    return ok_object(serialize_program(program))
