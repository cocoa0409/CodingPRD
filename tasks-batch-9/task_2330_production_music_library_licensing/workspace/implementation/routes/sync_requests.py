"""SyncRequest lifecycle (PRD §3.4)."""

from datetime import timedelta

from flask import Blueprint, request

from db import DB, fmt_ts
from errors import fail
from middleware import (
    body,
    opt_bool,
    opt_enum,
    opt_int,
    opt_int_array,
    opt_string,
    req_datetime,
    req_enum,
    req_int,
    req_string,
    require_role,
)
from response import object_response, page_response, pagination
from routes.common import (
    MEDIA_TYPES,
    PREFIX,
    SCALES,
    guard_licensee,
    require_state,
    set_clock_dt,
    set_dt,
)
from services import calc
from services.cascade import bump_once
from services.derive import (
    committed_spend_cents,
    lookup,
    reserved_spend_cents,
    rows,
    serialize_sync_request,
)

bp = Blueprint("sync_requests", __name__)

OPEN_STATES = ("SUBMITTED", "UNDER_REVIEW", "QUOTED", "REVISION_REQUESTED")


def _tier_scale_check(tier, media_type, distribution_scale):
    """Ladder step 27."""
    if distribution_scale not in tier["allowed_scales"] or media_type != tier["media_type"]:
        fail(
            "ERR_SCALE_NOT_ALLOWED_FOR_TIER",
            "the tier does not price this media type / distribution scale.",
        )


def _clear_quote(row):
    row["quoted_fee_cents"] = None
    row["quoted_spend_basis_cents"] = None
    row["_quoted_discount_pct"] = None
    row["quote_expires_at"] = None
    row["_quote_expires_at_dt"] = None


@bp.post(PREFIX + "/sync-requests")
def create_sync_request():
    data = body()
    composition_id = req_string(data, "composition_id")
    licensee_id = req_string(data, "licensee_id")
    tier_id = req_string(data, "tier_id")
    media_type = req_enum(data, "media_type", MEDIA_TYPES)
    scale = req_enum(data, "distribution_scale", SCALES)
    raw_start, start = req_datetime(data, "requested_term_start")
    term_months = req_int(data, "requested_term_months", 1, 120)
    exclusive = opt_bool(data, "exclusive_requested", False)
    custom_edit = opt_bool(data, "custom_edit_requested", False)
    stems = opt_bool(data, "stems_requested", False)
    alternates = opt_int_array(data, "alternate_lengths_sec", 5, 300, 0, 4)
    rush = opt_bool(data, "rush_requested", False)
    brief_note = opt_string(data, "brief_note")

    composition = lookup("compositions", composition_id)          # 3, declared order
    licensee = lookup("licensees", licensee_id)
    tier = lookup("tiers", tier_id)
    require_role("Licensee", "LicensingAgent")                    # 4
    guard_licensee(licensee["id"])                                # 5
    if (
        composition["catalog_status"] != "CATALOGED"
        or composition["availability_status"] == "WITHDRAWN"
    ):                                                            # 14
        fail("ERR_COMPOSITION_NOT_LICENSABLE", "the work is not licensable.")
    _tier_scale_check(tier, media_type, scale)                    # 27

    row = DB.new_row()
    row.update(
        {
            "composition_id": composition["id"],
            "licensee_id": licensee["id"],
            "tier_id": tier["id"],
            "media_type": media_type,
            "distribution_scale": scale,
            "requested_term_months": term_months,
            "exclusive_requested": exclusive,
            "custom_edit_requested": custom_edit,
            "stems_requested": stems,
            "alternate_lengths_sec": alternates,
            "rush_requested": rush,
            "brief_note": brief_note,
            "status": "SUBMITTED",
            "revision_round": 0,
            "license_id": None,
            "decline_reason": None,
            "delivered_asset_count": None,
        }
    )
    set_dt(row, "requested_term_start", raw_start, start)
    _clear_quote(row)
    DB.sync_requests[row["id"]] = row
    return object_response(serialize_sync_request(row), 201)


@bp.get(PREFIX + "/sync-requests/<sync_request_id>")
def get_sync_request(sync_request_id):
    row = lookup("sync_requests", sync_request_id)
    require_role("LicensingAgent", "CatalogAdmin", "RightsManager", "Licensee")
    guard_licensee(row["licensee_id"])
    return object_response(serialize_sync_request(row))


@bp.get(PREFIX + "/sync-requests")
def list_sync_requests():
    limit, offset = pagination(request.args)
    require_role("LicensingAgent", "CatalogAdmin", "RightsManager")
    result = rows("sync_requests")
    for name in ("composition_id", "licensee_id", "tier_id", "license_id", "status"):
        wanted = request.args.get(name)
        if wanted not in (None, ""):
            result = [r for r in result if r[name] == wanted]
    return page_response(result, limit, offset, serialize_sync_request)


@bp.post(PREFIX + "/sync-requests/<sync_request_id>/review")
def review(sync_request_id):
    row = lookup("sync_requests", sync_request_id)
    require_role("LicensingAgent")
    require_state(row, "status", ("SUBMITTED",), "sync_request")
    row["status"] = "UNDER_REVIEW"
    bump_once(row)
    return object_response(serialize_sync_request(row))


@bp.post(PREFIX + "/sync-requests/<sync_request_id>/quote")
def quote(sync_request_id):
    data = body()
    valid_days = opt_int(data, "quote_valid_days", 1, 365, 14)
    row = lookup("sync_requests", sync_request_id)
    require_role("LicensingAgent")
    require_state(row, "status", ("UNDER_REVIEW", "REVISION_REQUESTED"), "sync_request")

    composition = DB.compositions[row["composition_id"]]
    agreement = DB.agreements.get(composition["agreement_id"])
    if agreement is None or agreement["status"] != "ACTIVE":                # 13
        fail("ERR_AGREEMENT_NOT_ACTIVE", "the governing agreement is not ACTIVE.")
    if (
        composition["catalog_status"] != "CATALOGED"
        or composition["availability_status"] == "WITHDRAWN"
    ):                                                                     # 14
        fail("ERR_COMPOSITION_NOT_LICENSABLE", "the work is not licensable.")
    tier = DB.tiers[row["tier_id"]]
    if not (tier["min_term_months"] <= row["requested_term_months"] <= tier["max_term_months"]):
        fail("ERR_TERM_OUTSIDE_TIER_RANGE", "the requested term is outside the tier range.")

    licensee = DB.licensees[row["licensee_id"]]
    committed = committed_spend_cents(licensee["id"])
    reserved = reserved_spend_cents(licensee["id"])
    fee, basis, pct, _pre = calc.license_fee(
        tier["base_rate_cents"],
        row["media_type"],
        row["distribution_scale"],
        row["requested_term_months"],
        row["exclusive_requested"],
        row["rush_requested"],
        row["custom_edit_requested"],
        row["stems_requested"],
        len(row["alternate_lengths_sec"]),
        committed,
    )
    if committed + reserved + fee > licensee["credit_limit_cents"]:         # 29
        fail("ERR_CREDIT_LIMIT_EXCEEDED", "this quote would exceed the licensee credit limit.")

    row["status"] = "QUOTED"
    row["quoted_fee_cents"] = fee
    row["quoted_spend_basis_cents"] = basis
    row["_quoted_discount_pct"] = calc.dp2(pct)
    expires = DB.now + timedelta(days=valid_days)
    row["quote_expires_at"] = fmt_ts(expires)
    row["_quote_expires_at_dt"] = expires
    bump_once(row)
    bump_once(licensee)
    return object_response(serialize_sync_request(row))


@bp.post(PREFIX + "/sync-requests/<sync_request_id>/request-revision")
def request_revision(sync_request_id):
    data = body()
    req_string(data, "revision_note", allow_empty=False)
    revised_term = opt_int(data, "revised_term_months", 1, 120)
    revised_scale = opt_enum(data, "revised_distribution_scale", SCALES)
    revised_exclusive = opt_bool(data, "revised_exclusive_requested")
    row = lookup("sync_requests", sync_request_id)
    require_role("Licensee")
    guard_licensee(row["licensee_id"])
    require_state(row, "status", ("QUOTED",), "sync_request")

    tier = DB.tiers[row["tier_id"]]
    scale = revised_scale if revised_scale is not None else row["distribution_scale"]
    _tier_scale_check(tier, row["media_type"], scale)                      # 27
    if row["revision_round"] >= 3:                                         # 30
        fail("ERR_REVISION_LIMIT_REACHED", "three revisions have already been requested.")

    row["status"] = "REVISION_REQUESTED"
    row["revision_round"] = row["revision_round"] + 1
    if revised_term is not None:
        row["requested_term_months"] = revised_term
    if revised_scale is not None:
        row["distribution_scale"] = revised_scale
    if revised_exclusive is not None:
        row["exclusive_requested"] = revised_exclusive
    _clear_quote(row)
    bump_once(row)
    bump_once(DB.licensees.get(row["licensee_id"]))
    return object_response(serialize_sync_request(row))


@bp.post(PREFIX + "/sync-requests/<sync_request_id>/accept")
def accept(sync_request_id):
    row = lookup("sync_requests", sync_request_id)
    require_role("Licensee")
    guard_licensee(row["licensee_id"])
    require_state(row, "status", ("QUOTED",), "sync_request")
    if row["_quote_expires_at_dt"] is not None and DB.now > row["_quote_expires_at_dt"]:
        fail("ERR_QUOTE_EXPIRED", "the quote has expired.")                # 16
    row["status"] = "ACCEPTED"
    bump_once(row)
    return object_response(serialize_sync_request(row))


@bp.post(PREFIX + "/sync-requests/<sync_request_id>/decline")
def decline(sync_request_id):
    data = body()
    reason = req_string(data, "reason", allow_empty=False)
    row = lookup("sync_requests", sync_request_id)
    require_role("LicensingAgent")
    require_state(row, "status", OPEN_STATES, "sync_request")
    was_reserving = row["status"] == "QUOTED" and row["license_id"] is None
    row["status"] = "DECLINED"
    row["decline_reason"] = reason
    bump_once(row)
    if was_reserving:
        bump_once(DB.licensees.get(row["licensee_id"]))
    return object_response(serialize_sync_request(row))


@bp.post(PREFIX + "/sync-requests/<sync_request_id>/start-edit")
def start_edit(sync_request_id):
    data = body()
    opt_string(data, "edit_note")
    row = lookup("sync_requests", sync_request_id)
    require_role("CatalogAdmin")
    require_state(row, "status", ("ACCEPTED",), "sync_request")
    if not (
        row["custom_edit_requested"]
        or row["stems_requested"]
        or row["alternate_lengths_sec"]
    ):                                                                     # 32
        fail("ERR_NO_EDIT_WORK_REQUESTED", "no edit work was requested on this brief.")
    row["status"] = "EDIT_IN_PROGRESS"
    bump_once(row)
    return object_response(serialize_sync_request(row))


@bp.post(PREFIX + "/sync-requests/<sync_request_id>/deliver")
def deliver(sync_request_id):
    data = body()
    delivered = req_int(data, "delivered_asset_count")
    opt_string(data, "delivery_note")
    row = lookup("sync_requests", sync_request_id)
    require_role("CatalogAdmin")
    require_state(row, "status", ("ACCEPTED", "EDIT_IN_PROGRESS"), "sync_request")

    edit_work = (
        row["custom_edit_requested"]
        or row["stems_requested"]
        or bool(row["alternate_lengths_sec"])
    )
    if row["status"] == "ACCEPTED" and edit_work:                           # 33
        fail("ERR_EDIT_PASS_REQUIRED", "the requested edit pass was skipped.")
    if row["license_id"] is None:                                          # 34
        fail("ERR_LICENSE_NOT_ISSUED", "no licence has been issued for this request.")
    required = 1 + (1 if row["stems_requested"] else 0) + len(row["alternate_lengths_sec"])
    if delivered < required:                                               # 35
        fail("ERR_DELIVERABLE_COUNT_SHORT", "%d assets are required." % required)

    row["status"] = "DELIVERED"
    row["delivered_asset_count"] = delivered
    bump_once(row)
    return object_response(serialize_sync_request(row))
