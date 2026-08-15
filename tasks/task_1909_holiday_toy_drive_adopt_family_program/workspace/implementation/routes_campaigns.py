"""Campaign lifecycle, SeasonSettings singleton, and the test-driving clock."""

from datetime import timedelta

from flask import Blueprint, request

import clock
import db
from domain import (
    make_row, touch, sort_rows, audit, get_settings,
    recheck_age_bands_on_distribution_shift, cascade_family_rejected,
    expire_adoption_cascade, adoption_covered_children,
    ser_campaign, ser_settings,
)
from errors import (
    err_invalid_request, err_not_found, err_invalid_state, err_stale_version,
    err_duplicate,
)
from middleware import require_roles
from response import success_object, success_created, success_list
from util import (
    get_body, req_field, opt_field, as_int, as_str, as_enum, as_bool,
    parse_datetime, format_ts,
)

bp = Blueprint("campaigns", __name__)

ALL_ROLES = ("PlatformAdmin", "CaseWorker", "AgencyCoordinator", "Donor", "DistributionVolunteer")
CAMPAIGN_PATCHABLE = (
    "intake_open_at", "intake_close_at", "gift_return_deadline", "distribution_date",
    "max_children_per_family", "max_gift_value_cents", "min_gift_value_cents",
    "backfill_budget_cents", "privacy_mode",
)


def _validate_campaign_numbers(body, base=None):
    """Validate numeric/enum campaign constraints on create/patch. 400 on failure."""
    merged = dict(base) if base else {}
    merged.update({k: v for k, v in body.items() if k in CAMPAIGN_PATCHABLE or k == "season_year"})

    if "season_year" in body:
        v = as_int(body["season_year"], "season_year")
        if v < 2020 or v > 2100:
            raise err_invalid_request("season_year must be between 2020 and 2100")
    if "max_children_per_family" in merged:
        v = merged["max_children_per_family"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 1 or v > 12:
            raise err_invalid_request("max_children_per_family must be between 1 and 12")
    if "max_gift_value_cents" in merged:
        v = merged["max_gift_value_cents"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 1000 or v > 100000:
            raise err_invalid_request("max_gift_value_cents must be between 1000 and 100000")
    if "min_gift_value_cents" in merged:
        v = merged["min_gift_value_cents"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise err_invalid_request("min_gift_value_cents must be >= 0")
        if "max_gift_value_cents" in merged and v >= merged["max_gift_value_cents"]:
            raise err_invalid_request("min_gift_value_cents must be < max_gift_value_cents")
    if "backfill_budget_cents" in merged:
        v = merged["backfill_budget_cents"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise err_invalid_request("backfill_budget_cents must be >= 0")
    if "privacy_mode" in merged and merged["privacy_mode"] is not None:
        as_enum(merged["privacy_mode"], "privacy_mode", ("STRICT", "STANDARD"))


@bp.route("/campaigns", methods=["POST"])
@require_roles("PlatformAdmin")
def create_campaign(actor):
    body = get_body(required=True)
    season_year = as_int(req_field(body, "season_year"), "season_year")
    intake_open_at = parse_datetime(req_field(body, "intake_open_at"), "intake_open_at")
    intake_close_at = parse_datetime(req_field(body, "intake_close_at"), "intake_close_at")
    gift_return_deadline = parse_datetime(req_field(body, "gift_return_deadline"), "gift_return_deadline")
    distribution_date = parse_datetime(req_field(body, "distribution_date"), "distribution_date")
    max_children = as_int(req_field(body, "max_children_per_family"), "max_children_per_family")
    max_gift = as_int(req_field(body, "max_gift_value_cents"), "max_gift_value_cents")
    min_gift = as_int(req_field(body, "min_gift_value_cents"), "min_gift_value_cents")
    backfill_budget = as_int(req_field(body, "backfill_budget_cents"), "backfill_budget_cents")
    privacy_mode = opt_field(body, "privacy_mode", "STRICT")

    _validate_campaign_numbers(body)

    for c in db.campaigns.values():
        if c["season_year"] == season_year:
            raise err_duplicate("season_year must be unique across campaigns")

    row = make_row()
    row.update(
        season_year=season_year,
        status="DRAFT",
        intake_open_at=intake_open_at,
        intake_close_at=intake_close_at,
        gift_return_deadline=gift_return_deadline,
        distribution_date=distribution_date,
        max_children_per_family=max_children,
        max_gift_value_cents=max_gift,
        min_gift_value_cents=min_gift,
        backfill_budget_cents=backfill_budget,
        backfill_spent_cents=0,
        privacy_mode=privacy_mode,
    )
    db.campaigns[row["id"]] = row
    return success_created(ser_campaign(row))


@bp.route("/campaigns", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_campaigns(actor):
    rows = list(db.campaigns.values())
    status = request.args.get("status")
    season_year = request.args.get("season_year")
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    if season_year is not None:
        try:
            sy = int(season_year)
        except ValueError:
            raise err_invalid_request("season_year must be an integer")
        rows = [c for c in rows if c["season_year"] == sy]
    return success_list(sort_rows(rows), ser_campaign)


def _get_campaign(cid):
    row = db.campaigns.get(cid)
    if row is None:
        raise err_not_found("Campaign not found")
    return row


@bp.route("/campaigns/<cid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_campaign(actor, cid):
    return success_object(ser_campaign(_get_campaign(cid)))


@bp.route("/campaigns/<cid>", methods=["PATCH"])
@require_roles("PlatformAdmin")
def patch_campaign(actor, cid):
    campaign = _get_campaign(cid)
    body = get_body()
    touched_fields = [k for k in body.keys() if k in CAMPAIGN_PATCHABLE]
    if campaign["status"] == "DRAFT":
        allowed = set(CAMPAIGN_PATCHABLE)
    elif campaign["status"] == "INTAKE_OPEN":
        allowed = {"distribution_date"}
    else:
        raise err_invalid_state("Campaign in %s may not be patched" % campaign["status"])
    illegal = [k for k in touched_fields if k not in allowed]
    if illegal:
        raise err_invalid_state(
            "Campaign in %s may only patch distribution_date" % campaign["status"]
        )

    for f in ("intake_open_at", "intake_close_at", "gift_return_deadline", "distribution_date"):
        if f in body:
            body[f] = parse_datetime(body[f], f)
    for f in ("max_children_per_family", "max_gift_value_cents", "min_gift_value_cents", "backfill_budget_cents"):
        if f in body:
            as_int(body[f], f)
    if "privacy_mode" in body:
        as_enum(body["privacy_mode"], "privacy_mode", ("STRICT", "STANDARD"))

    merged = {
        "max_children_per_family": body.get("max_children_per_family", campaign["max_children_per_family"]),
        "max_gift_value_cents": body.get("max_gift_value_cents", campaign["max_gift_value_cents"]),
        "min_gift_value_cents": body.get("min_gift_value_cents", campaign["min_gift_value_cents"]),
        "backfill_budget_cents": body.get("backfill_budget_cents", campaign["backfill_budget_cents"]),
        "privacy_mode": body.get("privacy_mode", campaign["privacy_mode"]),
    }
    _validate_campaign_numbers({}, base=merged)

    dist_changed = (
        "distribution_date" in body and body["distribution_date"] != campaign["distribution_date"]
    )
    for k in touched_fields:
        campaign[k] = body[k]
    if dist_changed:
        recheck_age_bands_on_distribution_shift(campaign, actor)
    touch(campaign)
    return success_object(ser_campaign(campaign))


@bp.route("/campaigns/<cid>/open-intake", methods=["POST"])
@require_roles("PlatformAdmin")
def open_intake(actor, cid):
    campaign = _get_campaign(cid)
    get_body()
    if campaign["status"] != "DRAFT":
        raise err_invalid_state("open-intake requires campaign in DRAFT")
    now = clock.now()
    if not (campaign["intake_open_at"] <= now <= campaign["intake_close_at"]):
        raise err_invalid_state("Current time is outside the declared intake window")
    campaign["status"] = "INTAKE_OPEN"
    touch(campaign)
    return success_object(ser_campaign(campaign))


@bp.route("/campaigns/<cid>/close-intake", methods=["POST"])
@require_roles("PlatformAdmin")
def close_intake(actor, cid):
    campaign = _get_campaign(cid)
    get_body()
    if campaign["status"] != "INTAKE_OPEN":
        raise err_invalid_state("close-intake requires campaign in INTAKE_OPEN")
    now = clock.now()
    if now < campaign["intake_close_at"]:
        raise err_invalid_state("Cannot close intake before intake_close_at")
    campaign["status"] = "MATCHING"
    touch(campaign)
    for fam in sort_rows([f for f in db.families.values() if f["campaign_id"] == cid]):
        if fam["status"] in ("REFERRED", "UNDER_REVIEW"):
            cascade_family_rejected(fam, actor, "INTAKE_CLOSED_INCOMPLETE")
    return success_object(ser_campaign(campaign))


@bp.route("/campaigns/<cid>/advance", methods=["POST"])
@require_roles("PlatformAdmin")
def advance_campaign(actor, cid):
    campaign = _get_campaign(cid)
    body = get_body(required=True)
    expected = req_field(body, "expected_campaign_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_campaign_version must be an integer")

    status = campaign["status"]
    if status not in ("MATCHING", "DISTRIBUTION_PREP", "DISTRIBUTION"):
        raise err_invalid_state("advance is not defined from campaign status %s" % status)
    if expected != campaign["version"]:
        raise err_stale_version("expected_campaign_version does not match current campaign version")

    now = clock.now()
    if status == "MATCHING":
        if now < campaign["gift_return_deadline"]:
            raise err_invalid_state("Cannot advance before gift_return_deadline")
        # expiry sweep: unfulfilled adoptions whose return deadline has passed
        for a in sort_rows([x for x in db.adoptions.values() if x["campaign_id"] == cid]):
            if a["status"] not in ("PLEDGED", "CONFIRMED"):
                continue
            deadline = a["return_deadline"]
            if a["status"] == "CONFIRMED" and deadline is not None and not (deadline < now):
                continue
            a["status"] = "EXPIRED"
            touch(a)
            expire_adoption_cascade(a, actor)
        campaign["status"] = "DISTRIBUTION_PREP"
    elif status == "DISTRIBUTION_PREP":
        qualifying = any(
            e["campaign_id"] == cid
            and e["status"] in ("OPEN_FOR_SLOTS", "SORTING", "LOCKED", "COMPLETED")
            for e in db.distribution_events.values()
        )
        if not qualifying:
            raise err_invalid_state(
                "At least one DistributionEvent must be OPEN_FOR_SLOTS or later"
            )
        campaign["status"] = "DISTRIBUTION"
    else:  # DISTRIBUTION
        unfinished = any(
            e["campaign_id"] == cid and e["status"] not in ("COMPLETED", "CANCELLED")
            for e in db.distribution_events.values()
        )
        if unfinished:
            raise err_invalid_state("Every DistributionEvent must be COMPLETED or CANCELLED")
        campaign["status"] = "RECONCILIATION"
        for fam in sort_rows([f for f in db.families.values() if f["campaign_id"] == cid]):
            if fam["status"] in ("MATCHED", "PARTIALLY_FULFILLED", "FULFILLED", "BACKFILLED"):
                fam["status"] = "CLOSED"
                touch(fam)
    touch(campaign)
    return success_object(ser_campaign(campaign))


@bp.route("/campaigns/<cid>/close", methods=["POST"])
@require_roles("PlatformAdmin")
def close_campaign(actor, cid):
    campaign = _get_campaign(cid)
    get_body()
    if campaign["status"] != "RECONCILIATION":
        raise err_invalid_state("close requires campaign in RECONCILIATION")
    open_adoptions = any(
        a["campaign_id"] == cid and a["status"] in ("PLEDGED", "CONFIRMED", "PARTIALLY_RECEIVED")
        for a in db.adoptions.values()
    )
    if open_adoptions:
        raise err_invalid_state("Active adoptions remain under this campaign")
    family_ids = {f["id"] for f in db.families.values() if f["campaign_id"] == cid}
    open_flags = any(
        fl["status"] == "OPEN"
        and (fl["family_id"] in family_ids or fl["other_family_id"] in family_ids)
        for fl in db.duplicate_flags.values()
    )
    if open_flags:
        raise err_invalid_state("OPEN duplicate flags remain under this campaign")
    campaign["status"] = "CLOSED"
    touch(campaign)
    return success_object(ser_campaign(campaign))


# ---------------------------------------------------------------------------
# SeasonSettings singleton
# ---------------------------------------------------------------------------

@bp.route("/season-settings", methods=["GET"])
@require_roles("PlatformAdmin")
def get_season_settings(actor):
    return success_object(ser_settings(get_settings()))


@bp.route("/season-settings", methods=["PUT"])
@require_roles("PlatformAdmin")
def put_season_settings(actor):
    settings = get_settings()
    body = get_body(required=True)
    expected = req_field(body, "expected_settings_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_settings_version must be an integer")
    if expected != settings["version"]:
        raise err_stale_version("expected_settings_version does not match current settings version")

    if "duplicate_auto_detect_enabled" in body:
        settings["duplicate_auto_detect_enabled"] = as_bool(
            body["duplicate_auto_detect_enabled"], "duplicate_auto_detect_enabled"
        )
    if "duplicate_hash_salt" in body:
        if not isinstance(body["duplicate_hash_salt"], str):
            raise err_invalid_request("duplicate_hash_salt must be a string")
        settings["duplicate_hash_salt"] = body["duplicate_hash_salt"]
    if "late_donor_grace_hours" in body:
        v = as_int(body["late_donor_grace_hours"], "late_donor_grace_hours")
        if v < 0 or v > 72:
            raise err_invalid_request("late_donor_grace_hours must be between 0 and 72")
        settings["late_donor_grace_hours"] = v
    if "major_donor_threshold_cents" in body:
        v = as_int(body["major_donor_threshold_cents"], "major_donor_threshold_cents")
        if v < 0:
            raise err_invalid_request("major_donor_threshold_cents must be >= 0")
        settings["major_donor_threshold_cents"] = v
    touch(settings)
    return success_object(ser_settings(settings))


# ---------------------------------------------------------------------------
# Test-driving clock
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("PlatformAdmin")
def set_clock(actor):
    body = get_body(required=True)
    to = parse_datetime(req_field(body, "to_iso8601"), "to_iso8601")
    current = clock.set_current(to)
    return success_object({"current_utc": format_ts(current)})
