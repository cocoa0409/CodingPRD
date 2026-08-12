"""Firmware campaigns, rings and rollouts (PRD 3.9)."""

from flask import Blueprint, request

import serializers as S
from counters import (device_has_rma_in_flight, recompute_ring_counters, ring_rollouts)
from envelope import created, ok, ok_list, paginate, read_pagination
from errors import ApiError
from firmware_svc import maybe_complete_campaign, maybe_halt_campaign
from ladder import (bad_request, begin, gates, invalid_state, req_enum, req_id,
                    req_instant, req_int, req_str, resolve, scope_household, touch)
from money import (FIRMWARE_DEFAULT_HALT_FAILURE_RATE_PCT, FIRMWARE_DEFER_MAX_DAYS,
                   FIRMWARE_MAX_RETRY_COUNT, as_decimal)
from store import clock, db, new_row, sort_rows
from timeutil import add_days, try_parse_instant

bp = Blueprint("firmware", __name__)
PREFIX = "/smart-home-support"

CAMPAIGN_ROLES = ("PlatformAdmin", "SupportAgent")
ROLLOUT_READ_ROLES = ("PlatformAdmin", "SupportAgent", "Technician", "Owner")


# --------------------------------------------------------------------------
# Campaigns
# --------------------------------------------------------------------------
@bp.post(PREFIX + "/firmware-campaigns")
def create_campaign():
    ctx = begin(("PlatformAdmin",))
    body = ctx.body
    found = resolve(catalog=body.get("catalog_entry_id"))
    catalog = found.get("catalog")
    if catalog is None:
        req_id(body, "catalog_entry_id")
    kind = req_enum(body, "kind")
    target_firmware_version = req_str(body, "target_firmware_version", 1)
    halt = body.get("halt_failure_rate_pct")
    if halt is None:
        halt_value = FIRMWARE_DEFAULT_HALT_FAILURE_RATE_PCT
    else:
        if isinstance(halt, bool) or not isinstance(halt, (int, float)):
            bad_request("halt_failure_rate_pct must be a number.")
        halt_value = as_decimal(halt)
        if not (halt_value > 0 and halt_value <= 1):
            bad_request("halt_failure_rate_pct must be greater than 0 and at most 1.")

    row = new_row()
    row.update({
        "catalog_entry_id": catalog["id"],
        "kind": kind,
        "target_firmware_version": target_firmware_version,
        "halt_failure_rate_pct": float(halt_value),
        "status": "DRAFT",
        "current_ring_index": 0,
        "ring_window_start_at": None,
        "ring_window_end_at": None,
        "ring_device_count": 0,
        "ring_failed_count": 0,
        "ring_failure_rate": 0,
    })
    db.firmware_campaigns[row["id"]] = row
    return created(S.firmware_campaign(row))


@bp.get(PREFIX + "/firmware-campaigns")
def list_campaigns():
    begin(CAMPAIGN_ROLES)
    limit, offset = read_pagination(request.args)
    cid = request.args.get("catalog_entry_id")
    rows = [r for r in db.firmware_campaigns.values()
            if cid is None or r.get("catalog_entry_id") == cid]
    page, total = paginate(sort_rows(rows), limit, offset)
    return ok_list([S.firmware_campaign(r) for r in page], limit, offset, total)


@bp.get(PREFIX + "/firmware-campaigns/<cid>")
def read_campaign(cid):
    begin(CAMPAIGN_ROLES)
    found = resolve(campaign=cid)
    return ok(S.firmware_campaign(found["campaign"]))


@bp.post(PREFIX + "/firmware-campaigns/<cid>/launch-ring")
def launch_ring(cid):
    ctx = begin(("PlatformAdmin",))
    body = ctx.body
    device_ids = body.get("device_ids")
    if not isinstance(device_ids, list):
        found = resolve(campaign=cid)
        bad_request("device_ids must be an array of device ids.")
    found = resolve(device=device_ids, campaign=cid)
    campaign = found["campaign"]
    devices = found["device"]
    if len(devices) != len(device_ids):
        bad_request("Every entry of device_ids must be a string.")
    ring_index = req_int(body, "ring_index", 0)
    window_start_raw, window_start = req_instant(body, "window_start_at")
    window_end_raw, window_end = req_instant(body, "window_end_at")

    status = campaign.get("status")
    if status == "DRAFT":
        pass
    elif status == "RING_ACTIVE":
        # The self-loop requires an emptied current ring and the next index.
        for rollout in ring_rollouts(campaign):
            if rollout.get("status") == "PENDING":
                invalid_state("A rollout of the current ring is still PENDING.")
        if ring_index != (campaign.get("current_ring_index") or 0) + 1:
            invalid_state("ring_index must be current_ring_index + 1.")
    else:
        invalid_state("Only a DRAFT or RING_ACTIVE campaign may launch a ring.")

    # Rung 27 -- every listed device must be ACTIVE, of the campaign's model,
    # and carry a firmware_status that is neither BLOCKED nor DEFERRED.  The
    # launch is all-or-nothing: no rollout row is created when any listed
    # device is unacceptable.
    for device in devices:
        if device.get("lifecycle_status") != "ACTIVE":
            invalid_state("Every listed device must be ACTIVE.")
        if device.get("catalog_entry_id") != campaign.get("catalog_entry_id"):
            invalid_state("Every listed device must be a unit of the campaign's model.")
        if device.get("firmware_status") in ("BLOCKED", "DEFERRED"):
            invalid_state("A listed device's firmware_status is BLOCKED or DEFERRED.")
    # Rung 34 -- an in-flight RMA case blocks a launch of either kind.
    for device in devices:
        if device_has_rma_in_flight(device["id"]):
            raise ApiError("ERR_RMA_IN_FLIGHT")
    # Rung 35 -- FEATURE_OPTIONAL campaigns only.
    if campaign.get("kind") == "FEATURE_OPTIONAL":
        for device in devices:
            for ticket in db.tickets.values():
                if ticket.get("device_id") != device["id"]:
                    continue
                if ticket.get("workflow_status") not in ("RESOLVED", "CLOSED"):
                    raise ApiError("ERR_OPEN_TICKET_BLOCKS_ROLLOUT")
    # Rung 36 -- rollout windows are CLOSED intervals with no buffer, so
    # touching endpoints DO conflict (the opposite of the visit-slot rule).
    for device in devices:
        for rollout in db.firmware_rollouts.values():
            if rollout.get("device_id") != device["id"] or rollout.get("status") != "PENDING":
                continue
            r_start = try_parse_instant(rollout["window_start_at"])
            r_end = try_parse_instant(rollout["window_end_at"])
            if r_start <= window_end and window_start <= r_end:
                raise ApiError("ERR_ROLLOUT_WINDOW_OVERLAP")

    campaign["status"] = "RING_ACTIVE"
    campaign["current_ring_index"] = ring_index
    # Caller-supplied instants, echoed verbatim and propagated unchanged (G2).
    campaign["ring_window_start_at"] = window_start_raw
    campaign["ring_window_end_at"] = window_end_raw
    for device in devices:
        row = new_row()
        row.update({
            "campaign_id": campaign["id"],
            "device_id": device["id"],
            "ring_index": campaign["current_ring_index"],
            "window_start_at": campaign["ring_window_start_at"],
            "window_end_at": campaign["ring_window_end_at"],
            "status": "PENDING",
            "last_result": None,
            "retry_count": 0,
            "deferred_until": None,
            "result_reported_at": None,
        })
        db.firmware_rollouts[row["id"]] = row
        if device.get("firmware_status") in ("CURRENT", "ROLLED_BACK"):
            device["firmware_status"] = "UPDATE_PENDING"
        touch(device)
    recompute_ring_counters(campaign)
    touch(campaign)
    return ok(S.firmware_campaign(campaign))


@bp.post(PREFIX + "/firmware-campaigns/<cid>/resume")
def resume_campaign(cid):
    begin(("PlatformAdmin",))
    found = resolve(campaign=cid)
    campaign = found["campaign"]
    if campaign.get("status") != "HALTED":
        invalid_state("Only a HALTED campaign may be resumed.")
    campaign["status"] = "RING_ACTIVE"
    for rollout in ring_rollouts(campaign):
        if rollout.get("status") != "BLOCKED_BY_HALT":
            continue
        rollout["status"] = "PENDING"
        touch(rollout)
        device = db.devices.get(rollout.get("device_id"))
        if device is not None and device.get("firmware_status") == "BLOCKED":
            device["firmware_status"] = "UPDATE_PENDING"
            touch(device)
    recompute_ring_counters(campaign)
    touch(campaign)
    return ok(S.firmware_campaign(campaign))


# --------------------------------------------------------------------------
# Rollouts
# --------------------------------------------------------------------------
@bp.get(PREFIX + "/firmware-rollouts")
def list_rollouts():
    begin(ROLLOUT_READ_ROLES)
    limit, offset = read_pagination(request.args)
    cid = request.args.get("campaign_id")
    did = request.args.get("device_id")
    rows = []
    for row in db.firmware_rollouts.values():
        if cid is not None and row.get("campaign_id") != cid:
            continue
        if did is not None and row.get("device_id") != did:
            continue
        rows.append(row)
    page, total = paginate(sort_rows(rows), limit, offset)
    return ok_list([S.firmware_rollout(r) for r in page], limit, offset, total)


def _rollout_scope(ctx, rollout):
    device = db.devices.get(rollout.get("device_id"))
    # Row scope for a rollout is the household behind the device (PRD 2.1).
    scope_household(ctx, device.get("household_id") if device else None)
    return device


@bp.get(PREFIX + "/firmware-rollouts/<rid>")
def read_rollout(rid):
    ctx = begin(ROLLOUT_READ_ROLES)
    found = resolve(rollout=rid)
    rollout = found["rollout"]
    _rollout_scope(ctx, rollout)
    return ok(S.firmware_rollout(rollout))


@bp.post(PREFIX + "/firmware-rollouts/<rid>/report-result")
def report_result(rid):
    ctx = begin(("Technician", "PlatformAdmin"))
    found = resolve(rollout=rid)
    rollout = found["rollout"]
    device = _rollout_scope(ctx, rollout)
    result = req_enum(ctx.body, "result")
    household = db.households.get(device.get("household_id")) if device else None
    gates(household=household, device=device)

    campaign = db.firmware_campaigns.get(rollout.get("campaign_id"))
    if rollout.get("status") != "PENDING":
        invalid_state("Only a PENDING rollout may report a result.")
    if campaign is None or campaign.get("status") != "RING_ACTIVE":
        invalid_state("The owning campaign must be RING_ACTIVE.")

    rollout["last_result"] = result
    rollout["result_reported_at"] = clock.now_iso()
    if result == "SUCCESS":
        rollout["status"] = "APPLIED"
        if device is not None:
            if device.get("firmware_status") == "UPDATE_PENDING":
                device["firmware_status"] = "CURRENT"
            device["firmware_version"] = campaign["target_firmware_version"]
            touch(device)
    else:
        rollout["status"] = "ROLLED_BACK"
        if device is not None:
            if device.get("firmware_status") == "UPDATE_PENDING":
                device["firmware_status"] = "ROLLED_BACK"
            # firmware_version is deliberately left unchanged.
            touch(device)
    touch(rollout)

    recompute_ring_counters(campaign)
    if not maybe_halt_campaign(campaign):
        maybe_complete_campaign(campaign)
    touch(campaign)
    return ok(S.firmware_rollout(rollout))


@bp.post(PREFIX + "/firmware-rollouts/<rid>/defer")
def defer_rollout(rid):
    ctx = begin(("Owner",))
    found = resolve(rollout=rid)
    rollout = found["rollout"]
    device = _rollout_scope(ctx, rollout)
    defer_raw, defer_dt = req_instant(ctx.body, "defer_until")
    household = db.households.get(device.get("household_id")) if device else None
    gates(household=household, device=device)

    campaign = db.firmware_campaigns.get(rollout.get("campaign_id"))
    if rollout.get("status") != "PENDING":
        invalid_state("Only a PENDING rollout may be deferred.")
    # Rung 38 -- FEATURE_OPTIONAL only, and no further than the clock + 14 days.
    if campaign is None or campaign.get("kind") != "FEATURE_OPTIONAL":
        raise ApiError("ERR_DEFER_NOT_ALLOWED")
    if defer_dt > add_days(clock.now(), FIRMWARE_DEFER_MAX_DAYS):
        raise ApiError("ERR_DEFER_NOT_ALLOWED")

    # Caller-supplied instant, echoed verbatim (G2).
    rollout["deferred_until"] = defer_raw
    rollout["status"] = "DEFERRED"
    touch(rollout)
    if device is not None and device.get("firmware_status") == "UPDATE_PENDING":
        device["firmware_status"] = "DEFERRED"
        touch(device)
    recompute_ring_counters(campaign)
    # A deferral can take the last PENDING row out of PENDING and complete the ring.
    maybe_complete_campaign(campaign)
    touch(campaign)
    return ok(S.firmware_rollout(rollout))


@bp.post(PREFIX + "/firmware-rollouts/<rid>/retry")
def retry_rollout(rid):
    begin(("PlatformAdmin",))
    found = resolve(rollout=rid)
    rollout = found["rollout"]
    device = db.devices.get(rollout.get("device_id"))
    household = db.households.get(device.get("household_id")) if device else None
    gates(household=household, device=device)

    campaign = db.firmware_campaigns.get(rollout.get("campaign_id"))
    if rollout.get("status") not in ("ROLLED_BACK", "DEFERRED"):
        invalid_state("Only a ROLLED_BACK or DEFERRED rollout may be retried.")
    # Rung 37 -- only retry can ever reach this rung.
    if campaign is not None and campaign.get("status") == "HALTED":
        raise ApiError("ERR_CAMPAIGN_HALTED")
    # Rung 39 -- the third retry is always refused.
    if (rollout.get("retry_count") or 0) >= FIRMWARE_MAX_RETRY_COUNT:
        raise ApiError("ERR_RETRY_CAP_EXCEEDED")

    rollout["retry_count"] = (rollout.get("retry_count") or 0) + 1
    rollout["status"] = "PENDING"
    rollout["deferred_until"] = None
    touch(rollout)
    if device is not None and device.get("firmware_status") in ("ROLLED_BACK", "DEFERRED"):
        device["firmware_status"] = "UPDATE_PENDING"
        touch(device)
    recompute_ring_counters(campaign)
    touch(campaign)
    return ok(S.firmware_rollout(rollout))
