"""Site endpoints (§3.1, §3.2, §3.3, §3.5, §3.7): lifecycle, OCC patch, cascades."""
from flask import Blueprint

import clock
from db import store
from errors import ApiError, invalid_request
from middleware import ALL_ROLES, authed
from response import ok
from routes import list_response, require_state
from services.budget import recompute_program_rollup, recompute_site_budget
from services.forecast import compute_forecast, recompute_commitment_for_site, commitment_of_site
from util import bump, new_entity, parse_date, serialize
from validate import (body_fk, get_or_404, is_int, json_body, opt_str, req_date,
                      req_int, req_str)

bp = Blueprint("sites", __name__)

TERMINAL = ("OPEN", "REMOVED")


def _commitment_fields_for_new_site(site):
    """Initial commitment values: forecasts computed, posture starts PROTECTED
    (§3.1 — the auto-created commitment's posture reads PROTECTED)."""
    forecast_open, forecast_opt, slip, _posture = compute_forecast(site)
    return forecast_open, forecast_opt, slip


@bp.route("/rollout/sites", methods=["POST"], strict_slashes=False)
@authed(["ProgramDirector"])
def create_site():
    body = json_body()
    program = body_fk(body, "program_id", store.programs)
    market = body_fk(body, "market_id", store.markets)
    municipality_code = req_str(body, "municipality_code")
    address = req_str(body, "address")
    square_footage = req_int(body, "square_footage")
    phase_wave = req_int(body, "phase_wave")
    budget_allocation = req_int(body, "budget_allocation_cents")
    target_open = req_date(body, "target_open_date")
    if program is None:
        invalid_request("field 'program_id' is required")
    if market is None:
        invalid_request("field 'market_id' is required")

    site = new_entity(store)
    site.update({
        "program_id": program["id"],
        "market_id": market["id"],
        "municipality_code": municipality_code,
        "address": address,
        "square_footage": square_footage,
        "phase_wave": phase_wave,
        "budget_allocation_cents": budget_allocation,
        "target_open_date": target_open.isoformat(),
        "base_contract_cents": 0,
        "approved_co_cents": 0,
        "proposed_co_cents": 0,
        "committed_cents": 0,
        "variance_ratio_final_bp": 0,
        "variance_ratio_provisional_bp": 0,
        "budget_posture": "WITHIN",
        "actuals_cents": 0,
        "permit_fees_paid_cents": 0,
        "readiness_posture": "ROUGH",
        "punch_open_critical_count": 0,
        "punch_open_total_count": 0,
        "status": "LISTED",
    })
    store.sites[site["id"]] = site

    forecast_open, forecast_opt, slip = _commitment_fields_for_new_site(site)
    commitment = new_entity(store)
    commitment.update({
        "site_id": site["id"],
        "committed_open_on": target_open.isoformat(),
        "forecast_open_on": forecast_open,
        "forecast_optimistic_on": forecast_opt,
        "slip_days": slip,
        "protection_posture": "PROTECTED",
    })
    store.commitments[commitment["id"]] = commitment
    return ok(serialize(site), status=201)


@bp.route("/rollout/sites", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def list_sites():
    return list_response(store.sites, [
        ("program_id", "program_id", "str"),
        ("market_id", "market_id", "str"),
        ("status", "status", "str"),
        ("phase_wave", "phase_wave", "int"),
    ])


@bp.route("/rollout/sites/<siteId>", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def get_site(siteId):
    return ok(serialize(get_or_404(store.sites, siteId, "site")))


@bp.route("/rollout/sites/<siteId>", methods=["PATCH"], strict_slashes=False)
@authed(["ProgramDirector"])
def patch_site(siteId):
    body = json_body()
    site = get_or_404(store.sites, siteId, "site")

    # Step 6 — optimistic concurrency (before the temporal lock at step 9).
    esv = body.get("expected_site_version")
    if is_int(esv) and esv != site["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_site_version does not match current Site.version")

    # Step 9 — grand-opening date lock once past LISTED/DESIGN.
    new_target = None
    if "target_open_date" in body and body.get("target_open_date") is not None:
        try:
            new_target = parse_date(body.get("target_open_date"))
        except (ValueError, TypeError):
            new_target = None  # malformed — deferred to step-12 shape check
        if new_target is not None and new_target.isoformat() != site["target_open_date"]:
            override = body.get("director_override_reason")
            if site["status"] not in ("LISTED", "DESIGN") and not override:
                raise ApiError("ERR_OPEN_DATE_LOCKED", 409,
                               "target_open_date is locked past DESIGN without "
                               "director_override_reason")

    # Step 12 — request shape.
    if not is_int(esv):
        invalid_request("field 'expected_site_version' is required and must be an integer")
    if "target_open_date" in body and body.get("target_open_date") is not None:
        new_target = req_date(body, "target_open_date")
    new_budget = None
    if "budget_allocation_cents" in body and body.get("budget_allocation_cents") is not None:
        new_budget = req_int(body, "budget_allocation_cents")
    new_wave = None
    if "phase_wave" in body and body.get("phase_wave") is not None:
        new_wave = req_int(body, "phase_wave")
    opt_str(body, "director_override_reason")

    date_changed = (new_target is not None
                    and new_target.isoformat() != site["target_open_date"])
    if new_target is not None:
        site["target_open_date"] = new_target.isoformat()
    if new_budget is not None:
        site["budget_allocation_cents"] = new_budget
    if new_wave is not None:
        site["phase_wave"] = new_wave
    bump(site)  # every accepted update increments the site's version

    if date_changed:
        commitment = commitment_of_site(site)
        if commitment is not None:
            commitment["committed_open_on"] = new_target.isoformat()
            bump(commitment)
            recompute_commitment_for_site(site)
    return ok(serialize(site))


@bp.route("/rollout/sites/<siteId>/advance-design", methods=["POST"], strict_slashes=False)
@authed(["DesignManager"])
def advance_design(siteId):
    site = get_or_404(store.sites, siteId, "site")
    require_state(site, ("LISTED",), TERMINAL)
    site["status"] = "DESIGN"
    bump(site)
    return ok(serialize(site))


@bp.route("/rollout/sites/<siteId>/submit-design", methods=["POST"], strict_slashes=False)
@authed(["DesignManager"])
def submit_design(siteId):
    site = get_or_404(store.sites, siteId, "site")
    require_state(site, ("DESIGN",), TERMINAL)
    approved = any(
        d["program_id"] == site["program_id"]
        and d["jurisdiction_code"] == site["municipality_code"]
        and d["status"] == "APPROVED"
        for d in store.drawings.values()
    )
    if not approved:
        raise ApiError("ERR_DRAWING_NOT_APPROVED", 409,
                       "no APPROVED drawing set for the site's municipality")
    site["status"] = "PERMITTING"
    bump(site)
    return ok(serialize(site))


@bp.route("/rollout/sites/<siteId>/mark-permitted", methods=["POST"], strict_slashes=False)
@authed(["PermitCoordinator"])
def mark_permitted(siteId):
    site = get_or_404(store.sites, siteId, "site")
    require_state(site, ("PERMITTING",), TERMINAL)
    building = [p for p in store.permits.values()
                if p["site_id"] == site["id"] and p["permit_type"] == "BUILDING"]
    latest = None
    if building:
        latest = max(building, key=lambda p: (p["created_at"], p["_seq"]))
    today = clock.today()
    if latest is not None and (
        latest["status"] == "EXPIRED"
        or (latest["status"] == "ISSUED"
            and latest["expires_on"] is not None
            and parse_date(latest["expires_on"]) <= today)
    ):
        raise ApiError("ERR_PERMIT_EXPIRED", 409,
                       "latest BUILDING permit is expired")
    if latest is None or latest["status"] != "ISSUED":
        raise ApiError("ERR_PERMIT_NOT_ISSUED", 409,
                       "no ISSUED BUILDING permit for the site")
    site["status"] = "MOBILIZED"
    bump(site)
    return ok(serialize(site))


@bp.route("/rollout/sites/<siteId>/start-build", methods=["POST"], strict_slashes=False)
@authed(["SiteSuperintendent"])
def start_build(siteId):
    site = get_or_404(store.sites, siteId, "site")
    require_state(site, ("MOBILIZED",), TERMINAL)
    market = store.markets.get(site["market_id"])
    if market is None or market["status"] != "AWARDED":
        raise ApiError("ERR_MARKET_NOT_AWARDED", 409, "site's market is not AWARDED")
    site["status"] = "IN_BUILD"
    bump(site)
    return ok(serialize(site))


@bp.route("/rollout/sites/<siteId>/open", methods=["POST"], strict_slashes=False)
@authed(["OperationsLead"])
def open_site(siteId):
    site = get_or_404(store.sites, siteId, "site")
    require_state(site, ("TURNOVER",), TERMINAL)
    accepted = any(
        t["site_id"] == site["id"] and t["status"] == "ACCEPTED"
        for t in store.turnovers.values()
    )
    if not accepted:
        raise ApiError("ERR_TURNOVER_NOT_ACCEPTED", 409,
                       "no ACCEPTED turnover exists for the site")
    site["status"] = "OPEN"
    bump(site)
    commitment = commitment_of_site(site)
    if commitment is not None:
        commitment["protection_posture"] = "MET"
        bump(commitment)
    return ok(serialize(site))


@bp.route("/rollout/sites/<siteId>/remove", methods=["POST"], strict_slashes=False)
@authed(["ProgramDirector"])
def remove_site(siteId):
    site = get_or_404(store.sites, siteId, "site")
    require_state(site, ("LISTED", "DESIGN", "PERMITTING", "MOBILIZED",
                         "IN_BUILD", "PUNCH", "TURNOVER"), TERMINAL)
    on_site = any(
        m["site_id"] == site["id"] and m["status"] == "ON_SITE"
        for m in store.mobilizations.values()
    )
    if on_site:
        raise ApiError("ERR_ACTIVE_VENDOR_ON_SITE", 409,
                       "a vendor crew is physically on site")

    prior_status = site["status"]
    if prior_status in ("LISTED", "IN_BUILD", "PUNCH", "TURNOVER"):
        for m in store.mobilizations.values():
            if m["site_id"] == site["id"] and m["status"] in ("PLANNED", "SCHEDULED"):
                m["status"] = "CANCELLED"
                bump(m)
    for co in store.change_orders.values():
        if co["site_id"] == site["id"] and co["status"] == "PROPOSED":
            co["status"] = "REJECTED"
            bump(co)
    for t in store.turnovers.values():
        if t["site_id"] == site["id"] and t["status"] == "REQUESTED":
            t["status"] = "SUPERSEDED"
            bump(t)

    site["status"] = "REMOVED"
    bump(site)
    recompute_site_budget(site)  # PROPOSED buckets drop out (coalesced bump)
    program = store.programs.get(site["program_id"])
    if program is not None:
        recompute_program_rollup(program)  # REMOVED sites fall out of aggregates
    return ok(serialize(site))
