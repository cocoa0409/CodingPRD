"""Turnover endpoints (§3.7): request with pinned readiness snapshot, the
acceptance gate with OCC and optional minor-waiver sweep, rejection revert."""
from flask import Blueprint

from db import store
from errors import ApiError, invalid_request, invalid_state
from middleware import ALL_ROLES, authed
from response import ok
from routes import list_response, require_state
from services.budget import recompute_punch_counts, recompute_program_rollup
from services.forecast import commitment_of_site
from util import bump, new_entity, serialize
from validate import body_fk, get_or_404, is_int, json_body, opt_bool, req_str

bp = Blueprint("turnovers", __name__)

TERMINAL = ("ACCEPTED", "REJECTED", "SUPERSEDED")


@bp.route("/rollout/turnovers", methods=["POST"], strict_slashes=False)
@authed(["SiteSuperintendent"])
def create_turnover():
    body = json_body()
    site = body_fk(body, "site_id", store.sites)
    # Step 5 — site must be PUNCH; no second REQUESTED turnover.
    if site is not None and site["status"] != "PUNCH":
        invalid_state("site is not in PUNCH")
    if site is not None:
        requested = any(
            t["site_id"] == site["id"] and t["status"] == "REQUESTED"
            for t in store.turnovers.values()
        )
        if requested:
            raise ApiError("ERR_TURNOVER_ALREADY_REQUESTED", 409,
                           "a turnover is already REQUESTED for the site")
        # Step 10 — zero open critical punch items.
        if site["punch_open_critical_count"] > 0:
            raise ApiError("ERR_PUNCH_CRITICAL_OPEN", 409,
                           "critical punch items remain open")
    if site is None:
        invalid_request("field 'site_id' is required")

    commitment = commitment_of_site(site)
    snapshot = {
        "readiness_posture": site["readiness_posture"],
        "punch_open_critical_count": site["punch_open_critical_count"],
        "punch_open_total_count": site["punch_open_total_count"],
        "forecast_open_on": commitment["forecast_open_on"] if commitment else None,
    }
    turnover = new_entity(store)
    turnover.update({
        "site_id": site["id"],
        "readiness_snapshot": snapshot,
        "rejection_reason": None,
        "status": "REQUESTED",
    })
    store.turnovers[turnover["id"]] = turnover
    site["status"] = "TURNOVER"  # automatic advance on the request
    bump(site)
    return ok(serialize(turnover), status=201)


@bp.route("/rollout/turnovers", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def list_turnovers():
    return list_response(store.turnovers, [
        ("site_id", "site_id", "str"),
        ("status", "status", "str"),
    ])


@bp.route("/rollout/turnovers/<turnoverId>", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def get_turnover(turnoverId):
    return ok(serialize(get_or_404(store.turnovers, turnoverId, "turnover")))


@bp.route("/rollout/turnovers/<turnoverId>/accept", methods=["POST"], strict_slashes=False)
@authed(["OperationsLead"])
def accept_turnover(turnoverId):
    body = json_body()
    turnover = get_or_404(store.turnovers, turnoverId, "turnover")
    require_state(turnover, ("REQUESTED",), TERMINAL)
    site = store.sites.get(turnover["site_id"])

    # Step 6 — optimistic concurrency on the site's version.
    esv = body.get("expected_site_version")
    if is_int(esv) and site is not None and esv != site["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_site_version does not match current Site.version")

    # Step 10 — punch gate: every CRITICAL and MAJOR item VERIFIED; MINOR
    # items VERIFIED or WAIVED, unless waive_open_minor sweeps them.
    waive_minor = body.get("waive_open_minor")
    waive_minor = waive_minor if isinstance(waive_minor, bool) else False
    if site is not None:
        items = [p for p in store.punch_items.values() if p["site_id"] == site["id"]]
        hard_block = any(
            p["severity"] in ("CRITICAL", "MAJOR") and p["status"] != "VERIFIED"
            for p in items
        )
        minor_open = any(
            p["severity"] == "MINOR" and p["status"] in ("OPEN", "RESOLVED")
            for p in items
        )
        if hard_block or (minor_open and not waive_minor):
            raise ApiError("ERR_PUNCH_ITEMS_OUTSTANDING", 409,
                           "punch items remain outstanding for acceptance")

    # Step 12 — request shape.
    if not is_int(esv):
        invalid_request("field 'expected_site_version' is required and must be an integer")
    opt_bool(body, "waive_open_minor", False)

    turnover["status"] = "ACCEPTED"
    bump(turnover)
    if site is not None:
        if waive_minor:
            for p in store.punch_items.values():
                if (p["site_id"] == site["id"] and p["severity"] == "MINOR"
                        and p["status"] in ("OPEN", "RESOLVED")):
                    p["status"] = "WAIVED"
                    bump(p)
        site["actuals_cents"] = site["committed_cents"]  # final reconciliation
        bump(site)
        recompute_punch_counts(site)
        program = store.programs.get(site["program_id"])
        if program is not None:
            recompute_program_rollup(program)  # turnover accept rollup trigger
    return ok(serialize(turnover))


@bp.route("/rollout/turnovers/<turnoverId>/reject", methods=["POST"], strict_slashes=False)
@authed(["OperationsLead"])
def reject_turnover(turnoverId):
    body = json_body()
    turnover = get_or_404(store.turnovers, turnoverId, "turnover")
    require_state(turnover, ("REQUESTED",), TERMINAL)
    reason = req_str(body, "rejection_reason")
    turnover["status"] = "REJECTED"
    turnover["rejection_reason"] = reason
    bump(turnover)
    site = store.sites.get(turnover["site_id"])
    if site is not None and site["status"] == "TURNOVER":
        site["status"] = "PUNCH"  # automatic revert for another round of work
        bump(site)
    return ok(serialize(turnover))
