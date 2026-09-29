"""Reseller applications, the independent supply axis and the compliance summary."""

from flask import Blueprint

import lookup
from auth import (
    ALL_ROLES, ROLE_BRAND_CHANNEL_MANAGER, STAFF_AND_RESELLER, authenticate, require_owner,
)
from calc import (
    RUNG_BY_ORDINAL, compute_review_required, contributing_violations,
    highest_served_ordinal, select_rung, thresholds_for_reseller,
)
from envelope import created, ok, ok_list
from errors import fail
from store import new_row, now_dt, parse_iso, serialize, store, touch
from validate import (
    CHANNELS, HOLD_REASONS, SUPPLY_STATUSES, body, opt_enum, opt_str, query_dt,
    req_enum, req_str,
)

bp = Blueprint("resellers", __name__)

# Policy defaults (PRD §3.1) — used when a reseller has no governing policy at all.
FALLBACK_THRESHOLDS = {"suspension_points_threshold": 6, "termination_points_threshold": 12}

RELEASABLE_HOLD_REASONS = ("QUALITY_OBLIGATION", "AGREEMENT_EXPIRED")


@bp.post("/resellers")
def record_application():
    authenticate([ROLE_BRAND_CHANNEL_MANAGER])
    b = body()
    legal_name = req_str(b, "legal_name", 1, None)
    contact_email = req_str(b, "contact_email", 1, None)
    primary_channel = req_enum(b, "primary_channel", CHANNELS)
    sourcing_distributor_id = opt_str(b, "sourcing_distributor_id", 1, None)
    if sourcing_distributor_id is not None:
        lookup.distributor(sourcing_distributor_id)

    row = new_row({
        "legal_name": legal_name,
        "contact_email": contact_email,
        "primary_channel": primary_channel,
        "authorization_status": "APPLIED",
        "supply_status": "HOLD",
        "hold_reason": "PENDING_AUTHORIZATION",
        "violation_points_total": 0,
        "review_required": False,
        "sourcing_distributor_id": sourcing_distributor_id,
        "suspension_ends_at": None,
        "last_suspension_ended_at": None,
        "terminated_at": None,
    })
    # PRD §2.11 — the flag is evaluated once at creation.
    row["review_required"] = compute_review_required(row)
    store.resellers[row["id"]] = row
    return created(serialize(row))


@bp.post("/resellers/<reseller_id>/supply-status")
def move_supply_axis(reseller_id):
    authenticate([ROLE_BRAND_CHANNEL_MANAGER])
    b = body()
    target = req_enum(b, "supply_status", SUPPLY_STATUSES)
    opt_enum(b, "hold_reason", HOLD_REASONS)
    opt_str(b, "note", 0, None)
    reseller = lookup.reseller(reseller_id)

    if target == "HOLD":
        if reseller["supply_status"] != "OPEN":
            fail("ERR_INVALID_STATE", "Only an OPEN reseller may be placed on hold.")
        if reseller["authorization_status"] == "TERMINATED":
            fail("ERR_RESELLER_TERMINATED", "A terminated reseller's supply axis may not be moved.")
        reseller["supply_status"] = "HOLD"
        reseller["hold_reason"] = "QUALITY_OBLIGATION"
    elif target == "OPEN":
        if reseller["supply_status"] != "HOLD":
            fail("ERR_INVALID_STATE", "Only a reseller on HOLD may have its hold released.")
        if reseller["hold_reason"] not in RELEASABLE_HOLD_REASONS:
            fail("ERR_SUPPLY_BLOCKED_BY_AUTHORIZATION",
                 "A %s hold may not be released on the supply route." % reseller["hold_reason"])
        if reseller["authorization_status"] != "AUTHORIZED":
            fail("ERR_SUPPLY_BLOCKED_BY_AUTHORIZATION",
                 "Supply may only be opened for an AUTHORIZED reseller.")
        reseller["supply_status"] = "OPEN"
        reseller["hold_reason"] = "NONE"
    else:
        fail("ERR_INVALID_STATE", "CUT_OFF is only reached through the authorization axis.")
    touch(reseller)
    return ok(serialize(reseller))


@bp.get("/resellers/<reseller_id>")
def read_reseller(reseller_id):
    ctx = authenticate(ALL_ROLES)
    row = lookup.reseller(reseller_id)
    require_owner(ctx, row, reseller_field="id")
    return ok(serialize(row))


@bp.get("/resellers")
def list_resellers():
    authenticate(ALL_ROLES)
    rows = lookup.filtered("resellers", {
        "sourcing_distributor_id": "sourcing_distributor_id",
        "authorization_status": "authorization_status",
        "supply_status": "supply_status",
        "review_required": "review_required",
    })
    return ok_list(rows)


@bp.get("/resellers/<reseller_id>/compliance-summary")
def compliance_summary(reseller_id):
    ctx = authenticate(STAFF_AND_RESELLER)
    as_of_raw = query_dt("as_of")
    reseller = lookup.reseller(reseller_id)
    require_owner(ctx, reseller, reseller_field="id")
    as_of = parse_iso(as_of_raw) if as_of_raw else now_dt()

    contributors = contributing_violations(reseller["id"])
    summed = sum(v["assessed_points"] for v in contributors)
    policy = thresholds_for_reseller(reseller, as_of) or FALLBACK_THRESHOLDS
    total = reseller["violation_points_total"]
    highest = highest_served_ordinal(reseller["id"])
    return ok({
        "reseller_id": reseller["id"],
        "violation_points_total": total,
        "contributing_violation_count": len(contributors),
        "summed_assessed_points": summed,
        "highest_issued_rung": RUNG_BY_ORDINAL.get(highest),
        "next_rung": select_rung(reseller["id"], total, policy),
        "points_to_suspension": max(0, policy["suspension_points_threshold"] - total),
        "points_to_termination": max(0, policy["termination_points_threshold"] - total),
    })
