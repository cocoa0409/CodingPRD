"""The enforcement ladder: notice issuance, acknowledgement and rescission (PRD §3.7)."""

from flask import Blueprint

import lookup
from auth import (
    ROLE_BRAND_CHANNEL_MANAGER, ROLE_BRAND_LEGAL_COUNSEL, ROLE_RESELLER,
    STAFF_AND_RESELLER, authenticate, require_owner,
)
from calc import (
    governing_suspension_notice, resolve_floor, select_rung, violation_points,
)
from cascade import rescind_notice, strip_assessed_points, terminate_reseller
from envelope import created, ok, ok_list
from errors import fail
from store import days, dt_of, fmt, new_row, now_dt, now_iso, parse_iso, serialize, store, touch
from validate import (
    DELIVERY_CHANNELS, RUNGS, body, opt_bool, opt_dt, opt_enum, req_enum, req_int, req_str,
)

bp = Blueprint("notices", __name__)

MAX_SUSPENSION_WINDOW_DAYS = 90
LIVE_SUSPENSION_STATUSES = ("ISSUED", "ACKNOWLEDGED", "SATISFIED")


@bp.post("/enforcement-notices")
def issue_notice():
    ctx = authenticate([ROLE_BRAND_CHANNEL_MANAGER, ROLE_BRAND_LEGAL_COUNSEL])
    b = body()
    reseller_id = req_str(b, "reseller_id")
    violation_id = req_str(b, "violation_id")
    delivery_channel = req_enum(b, "delivery_channel", DELIVERY_CHANNELS)
    expected_version = req_int(b, "expected_reseller_version", 1, None)
    asserted_rung = opt_enum(b, "rung", RUNGS)
    suspension_starts_at = opt_dt(b, "suspension_starts_at")
    suspension_ends_at = opt_dt(b, "suspension_ends_at")
    contains_pricing_discussion = opt_bool(b, "contains_pricing_discussion", False)
    if suspension_starts_at is not None and suspension_ends_at is not None:
        starts = parse_iso(suspension_starts_at)
        ends = parse_iso(suspension_ends_at)
        if ends - starts > days(MAX_SUSPENSION_WINDOW_DAYS):
            fail("ERR_VALIDATION", "A suspension window may not exceed 90 days.")

    reseller = lookup.reseller(reseller_id)
    violation = lookup.violation(violation_id)

    if violation["status"] != "DETECTED":
        fail("ERR_VIOLATION_NOT_NOTICEABLE", "Only a DETECTED violation may be noticed.")
    if reseller["authorization_status"] == "TERMINATED":
        fail("ERR_RESELLER_TERMINATED", "A terminated reseller may not be noticed again.")
    if expected_version != reseller["version"]:
        fail("ERR_STALE_RESELLER_VERSION",
             "expected_reseller_version does not match the reseller's current version.")
    if contains_pricing_discussion:
        fail("ERR_ANTITRUST_NEGOTIATION_PROHIBITED",
             "An enforcement notice may not open a pricing dialogue.")

    policy = store.policies.get(violation.get("cited_policy_id"))
    if policy is None or policy["status"] != "PUBLISHED":
        fail("ERR_POLICY_NOT_PUBLISHED",
             "The violation's cited policy must still be PUBLISHED at issuance.")
    if violation["reseller_id"] != reseller_id:
        fail("ERR_VIOLATION_RESELLER_MISMATCH",
             "reseller_id must equal the cited violation's reseller_id.")

    # --- final points recomputation at the issuance instant (PRD §3.5) ---
    observation = store.observations.get(violation["observation_id"])
    product = store.products.get(observation["product_id"]) if observation else None
    now = now_dt()
    final_floor, _source, _exc = resolve_floor(
        product, observation["channel"], now, bool(observation.get("is_bundle")))
    final_points, _dev_cents, _dev_pct = violation_points(
        reseller_id, violation["id"], observation["channel"], final_floor,
        observation["effective_advertised_price_cents"], now)

    cumulative = reseller["violation_points_total"] + final_points
    computed_rung = select_rung(reseller_id, cumulative, policy)

    if computed_rung == "SUSPENSION":
        if suspension_starts_at is None or suspension_ends_at is None:
            fail("ERR_VALIDATION",
                 "suspension_starts_at and suspension_ends_at are required for a suspension.")
        _check_suspension_window(reseller, policy, suspension_starts_at, suspension_ends_at)

    if asserted_rung is not None and asserted_rung != computed_rung:
        fail("ERR_LADDER_RUNG_MISMATCH",
             "The asserted rung does not match the computed rung %s." % computed_rung)
    if computed_rung == "TERMINATION":
        if ctx.role != ROLE_BRAND_LEGAL_COUNSEL:
            fail("ERR_TERMINATION_REQUIRES_COUNSEL",
                 "Only BrandLegalCounsel may issue a termination notice.")
        governing = governing_suspension_notice(reseller_id)
        if governing is not None and governing.get("issued_by_user_id") == ctx.user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The suspending counsel may not also terminate the same partner.")
    if final_points <= 0:
        fail("ERR_NO_BREACH_AT_FINAL_FLOOR",
             "The violation no longer breaches the floor in force at issuance.")

    # --- multi-row write ---
    violation["status"] = "NOTICED"
    violation["assessed_floor_cents"] = final_floor
    violation["assessed_points"] = final_points
    violation["cure_deadline_at"] = fmt(now + days(policy["cure_window_days"]))
    touch(violation)

    reseller["violation_points_total"] = cumulative
    touch(reseller)

    notice = new_row({
        "violation_id": violation["id"],
        "reseller_id": reseller_id,
        "rung": computed_rung,
        "status": "ISSUED",
        "issued_by_user_id": ctx.user_id,
        "cumulative_points_at_issue": cumulative,
        "assessed_points": final_points,
        "suspension_starts_at": suspension_starts_at,
        "suspension_ends_at": suspension_ends_at,
        "delivery_channel": delivery_channel,
        "contains_pricing_discussion": contains_pricing_discussion,
        "acknowledged_at": None,
        "closed_reason": None,
    })
    store.notices[notice["id"]] = notice

    if computed_rung == "SUSPENSION":
        reseller["authorization_status"] = "SUSPENDED"
        reseller["supply_status"] = "HOLD"
        reseller["hold_reason"] = "SUSPENSION"
        reseller["suspension_ends_at"] = suspension_ends_at
        touch(reseller)
    elif computed_rung == "TERMINATION":
        terminate_reseller(reseller)
    return created(serialize(notice))


def _check_suspension_window(reseller, policy, starts_raw, ends_raw):
    """PRD §3.7 — intersection with a live window, then the cooling-off buffer."""
    starts = parse_iso(starts_raw)
    ends = parse_iso(ends_raw)
    for notice in store.notices.values():
        if notice["reseller_id"] != reseller["id"] or notice["rung"] != "SUSPENSION":
            continue
        if notice["status"] == "RESCINDED":
            continue
        other_starts = dt_of(notice, "suspension_starts_at")
        other_ends = dt_of(notice, "suspension_ends_at")
        if other_starts is None or other_ends is None:
            continue
        # Closed intervals: touching endpoints do count as an intersection.
        if starts <= other_ends and other_starts <= ends:
            fail("ERR_SUSPENSION_COOLING_OFF",
                 "The suspension window intersects an existing suspension window.")
    last_ended = dt_of(reseller, "last_suspension_ended_at")
    if last_ended is not None:
        earliest = last_ended + days(policy["suspension_cooling_off_days"])
        if starts < earliest:
            fail("ERR_SUSPENSION_COOLING_OFF",
                 "The suspension window does not respect the cooling-off buffer.")


@bp.post("/enforcement-notices/<notice_id>/acknowledge")
def acknowledge(notice_id):
    ctx = authenticate([ROLE_RESELLER])
    body()
    notice = lookup.notice(notice_id)
    require_owner(ctx, notice, reseller_field="reseller_id")
    if notice["status"] != "ISSUED":
        fail("ERR_INVALID_STATE", "Only an ISSUED notice may be acknowledged.")
    notice["status"] = "ACKNOWLEDGED"
    notice["acknowledged_at"] = now_iso()
    touch(notice)
    return ok(serialize(notice))


@bp.post("/enforcement-notices/<notice_id>/rescind")
def rescind(notice_id):
    authenticate([ROLE_BRAND_LEGAL_COUNSEL])
    b = body()
    rescinded_reason = req_str(b, "rescinded_reason", 1, None)
    notice = lookup.notice(notice_id)
    if notice["status"] not in ("ISSUED", "ACKNOWLEDGED"):
        fail("ERR_INVALID_STATE", "Only an ISSUED or ACKNOWLEDGED notice may be rescinded.")
    if notice["rung"] == "TERMINATION":
        fail("ERR_TERMINATION_NOT_RESCINDABLE", "A termination notice may not be rescinded.")

    violation = store.violations.get(notice["violation_id"])
    if violation is not None:
        violation["status"] = "DETECTED"
        strip_assessed_points(violation)
        touch(violation)
    rescind_notice(notice, rescinded_reason)
    return ok(serialize(notice))


@bp.get("/enforcement-notices/<notice_id>")
def read_notice(notice_id):
    ctx = authenticate(STAFF_AND_RESELLER)
    row = lookup.notice(notice_id)
    require_owner(ctx, row, reseller_field="reseller_id")
    return ok(serialize(row))


@bp.get("/enforcement-notices")
def list_notices():
    authenticate(STAFF_AND_RESELLER)
    rows = lookup.filtered("notices", {
        "reseller_id": "reseller_id",
        "violation_id": "violation_id",
        "rung": "rung",
        "status": "status",
    })
    return ok_list(rows)
