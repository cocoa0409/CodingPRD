"""Category schedules, appraisers and the appraisal lifecycle (PRD 3.4)."""

import calc
import cascades
import derive
import serializers
import store
from constants import (
    APPRAISAL_BUFFER_HOURS,
    APPRAISAL_SCOPES,
    ITEM_CATEGORIES,
    VOID_REASONS,
)
from errors import ApiError
from registry import endpoint
from routes.common import field, list_response, one
from timeutil import add_hours, clock, parse_instant


# ------------------------------------------------------- category schedules
@endpoint(
    "POST",
    "/vault/category-schedules",
    roles=["PlatformAdmin"],
    code=201,
    mutating=True,
    body={
        "category": ("string", True),
        "useful_life_months": ("integer", True),
        "annual_depreciation_pct": ("number", True),
        "salvage_floor_pct": ("number", True),
        "blanket_sublimit_cents": ("integer", True),
        "appraisal_scope": ("string", True),
        "serial_required": ("boolean", False),
    },
    enums={"category": ITEM_CATEGORIES, "appraisal_scope": APPRAISAL_SCOPES},
)
def create_category_schedule(ctx):
    serial_required = ctx.body.get("serial_required")
    row = store.new_row(
        store.category_schedules,
        common_fields=False,
        category=ctx.body["category"],
        useful_life_months=ctx.body["useful_life_months"],
        annual_depreciation_pct=ctx.body["annual_depreciation_pct"],
        salvage_floor_pct=ctx.body["salvage_floor_pct"],
        blanket_sublimit_cents=ctx.body["blanket_sublimit_cents"],
        appraisal_scope=ctx.body["appraisal_scope"],
        serial_required=False if serial_required is None else serial_required,
    )
    return one(serializers.category_schedule(row), 201)


@endpoint(
    "GET",
    "/vault/category-schedules",
    roles=["PlatformAdmin", "Homeowner", "HouseholdMember", "InsuranceAgent"],
)
def list_category_schedules(ctx):
    return list_response(
        store.all_of(store.category_schedules),
        ctx.args,
        serializers.category_schedule,
        {"category": field("category")},
    )


# ------------------------------------------------------------- appraisers
@endpoint(
    "POST",
    "/vault/appraisers",
    roles=["PlatformAdmin"],
    code=201,
    mutating=True,
    body={
        "display_name": ("string", True),
        "credential_id": ("string", True),
        "scope_categories": ("array", True),
        "linked_member_id": ("string", False),
    },
    array_enums={"scope_categories": APPRAISAL_SCOPES},
)
def create_appraiser(ctx):
    row = store.new_row(
        store.appraisers,
        display_name=ctx.body["display_name"],
        credential_id=ctx.body["credential_id"],
        scope_categories=list(ctx.body["scope_categories"]),
        linked_member_id=ctx.body.get("linked_member_id"),
        status="ACTIVE",
    )
    return one(serializers.appraiser(row), 201)


@endpoint(
    "GET",
    "/vault/appraisers/{appraiser_id}",
    roles=["PlatformAdmin", "Homeowner", "Appraiser"],
)
def read_appraiser(ctx):
    return one(serializers.appraiser(ctx.row("appraiser_id")))


@endpoint("GET", "/vault/appraisers", roles=["PlatformAdmin", "Homeowner", "Appraiser"])
def list_appraisers(ctx):
    return list_response(
        store.all_of(store.appraisers),
        ctx.args,
        serializers.appraiser,
        {"linked_member_id": field("linked_member_id"), "status": field("status")},
    )


@endpoint(
    "POST",
    "/vault/appraisers/{appraiser_id}/suspend",
    roles=["PlatformAdmin"],
    mutating=True,
)
def suspend_appraiser(ctx):
    row = ctx.row("appraiser_id")
    row["status"] = "SUSPENDED"
    store.touch(row)
    return one(serializers.appraiser(row))


# -------------------------------------------------------------- appraisals
def _appraisal(ctx):
    return ctx.row("appraisal_id")


def _appraisal_item(ctx):
    return store.items.get(_appraisal(ctx)["item_id"])


def _appraisal_household(ctx):
    item = _appraisal_item(ctx)
    return item["household_id"] if item else None


def _request_item(ctx):
    return store.items.get(ctx.body.get("item_id"))


def _request_household(ctx):
    item = _request_item(ctx)
    return item["household_id"] if item else None


def _window_check(ctx):
    start = ctx.body.get("inspection_start_at")
    end = ctx.body.get("inspection_end_at")
    start_dt = parse_instant(start) if isinstance(start, str) else None
    end_dt = parse_instant(end) if isinstance(end, str) else None
    if start_dt is not None and end_dt is not None and end_dt <= start_dt:
        raise ApiError("ERR_INVALID_REQUEST", "inspection_end_at must be after inspection_start_at.")


def _request_rung12(ctx):
    item = _request_item(ctx)
    if item is not None and item["lifecycle_state"] == "FROZEN":
        raise ApiError("ERR_ITEM_FROZEN")


def _request_rung15(ctx):
    item = _request_item(ctx)
    appraiser = store.appraisers[ctx.body["appraiser_id"]]
    sched = calc.category_schedule_for(item["category"])
    scope = sched["appraisal_scope"] if sched is not None else None
    if scope is None or scope not in (appraiser.get("scope_categories") or []):
        raise ApiError("ERR_APPRAISER_SCOPE_MISMATCH")


def _request_rung16(ctx):
    item = _request_item(ctx)
    appraiser = store.appraisers[ctx.body["appraiser_id"]]
    linked = appraiser.get("linked_member_id")
    if linked is not None and linked == item.get("declared_by_member_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")


def _request_rung17(ctx):
    """Closed interval widened by APPRAISAL_BUFFER_HOURS on BOTH sides against
    the un-widened closed interval of an existing hold; touching counts."""
    item = _request_item(ctx)
    new_lo = add_hours(parse_instant(ctx.body["inspection_start_at"]), -APPRAISAL_BUFFER_HOURS)
    new_hi = add_hours(parse_instant(ctx.body["inspection_end_at"]), APPRAISAL_BUFFER_HOURS)
    for other in store.all_of(store.appraisals):
        if other["item_id"] != item["id"] or other["status"] not in ("REQUESTED", "CERTIFIED"):
            continue
        other_lo = other.get("_inspection_start_at_dt")
        other_hi = other.get("_inspection_end_at_dt")
        if other_lo is None or other_hi is None:
            continue
        if new_lo <= other_hi and other_lo <= new_hi:
            raise ApiError("ERR_APPRAISAL_WINDOW_CONFLICT")


def _request_rung34(ctx):
    item = _request_item(ctx)
    sub = derive.subscription_of(item["household_id"])
    if sub is None or sub["appraisal_credits_remaining"] <= 0:
        raise ApiError("ERR_NO_APPRAISAL_CREDITS")


@endpoint(
    "POST",
    "/vault/appraisals",
    roles=["Homeowner"],
    code=201,
    mutating=True,
    owner_only=True,
    body={
        "item_id": ("string", True),
        "appraiser_id": ("string", True),
        "inspection_start_at": ("datetime", True),
        "inspection_end_at": ("datetime", True),
    },
    fks=("item_id", "appraiser_id"),
    household=_request_household,
    scope_household=_request_household,
    rung3_extra=_window_check,
    rungs={
        12: _request_rung12,
        15: _request_rung15,
        16: _request_rung16,
        17: _request_rung17,
        34: _request_rung34,
    },
)
def request_appraisal(ctx):
    item = _request_item(ctx)
    sub = derive.subscription_of(item["household_id"])
    row = store.new_row(
        store.appraisals,
        item_id=item["id"],
        appraiser_id=ctx.body["appraiser_id"],
        requested_by_member_id=ctx.user_id,
        status="REQUESTED",
        appraised_value_cents=None,
        credit_consumed=False,
        void_reason=None,
    )
    derive.keep_raw(row, "inspection_start_at", ctx.body["inspection_start_at"])
    derive.keep_raw(row, "inspection_end_at", ctx.body["inspection_end_at"])
    derive.stamp(row, "certified_at", None)
    derive.stamp(row, "valid_until_at", None)
    sub["appraisal_credits_remaining"] -= 1
    row["credit_consumed"] = True
    store.touch(sub)
    return one(serializers.appraisal(row), 201)


@endpoint(
    "GET",
    "/vault/appraisals/{appraisal_id}",
    roles=["Homeowner", "Appraiser", "InsuranceAgent", "PlatformAdmin"],
    scope_household=_appraisal_household,
    appraisal_target=_appraisal,
)
def read_appraisal(ctx):
    return one(serializers.appraisal(_appraisal(ctx)))


@endpoint(
    "GET",
    "/vault/appraisals",
    roles=["Homeowner", "Appraiser", "InsuranceAgent", "PlatformAdmin"],
)
def list_appraisals(ctx):
    return list_response(
        store.all_of(store.appraisals),
        ctx.args,
        serializers.appraisal,
        {
            "item_id": field("item_id"),
            "appraiser_id": field("appraiser_id"),
            "requested_by_member_id": field("requested_by_member_id"),
            "status": field("status"),
        },
    )


def _certify_rung12(ctx):
    item = _appraisal_item(ctx)
    if item is not None and item["lifecycle_state"] == "FROZEN":
        raise ApiError("ERR_ITEM_FROZEN")


def _certify_rung13(ctx):
    if _appraisal(ctx)["status"] in ("VOIDED", "EXPIRED"):
        raise ApiError("ERR_ALREADY_TERMINAL")


def _certify_rung14(ctx):
    appraisal = _appraisal(ctx)
    if appraisal["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE")
    appraiser = store.appraisers.get(appraisal["appraiser_id"])
    if appraiser is None or appraiser["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    end = appraisal.get("_inspection_end_at_dt")
    if end is None or clock.now < end:
        raise ApiError("ERR_INVALID_STATE")


@endpoint(
    "POST",
    "/vault/appraisals/{appraisal_id}/certify",
    roles=["Appraiser"],
    mutating=True,
    body={"appraised_value_cents": ("integer", True)},
    household=_appraisal_household,
    appraisal_target=_appraisal,
    rungs={12: _certify_rung12, 13: _certify_rung13, 14: _certify_rung14},
)
def certify_appraisal(ctx):
    appraisal = _appraisal(ctx)
    item = _appraisal_item(ctx)
    appraisal["status"] = "CERTIFIED"
    appraisal["appraised_value_cents"] = ctx.body["appraised_value_cents"]
    derive.stamp(appraisal, "certified_at", clock.now)
    derive.stamp(appraisal, "valid_until_at", derive.certified_valid_until(clock.now))
    store.touch(appraisal)
    if item is not None:
        derive.refresh_item(item, bump=False)
        store.touch(item)
        household = store.households.get(item["household_id"])
        if household is not None:
            derive.recompute_household(household, bump=True)
            store.touch(household)
        for policy in derive.household_policies(item["household_id"]):
            derive.recompute_policy(policy, bump=True)
    return one(serializers.appraisal(appraisal))


def _void_rung13(ctx):
    if _appraisal(ctx)["status"] in ("VOIDED", "EXPIRED"):
        raise ApiError("ERR_ALREADY_TERMINAL")


def _void_rung14(ctx):
    if _appraisal(ctx)["status"] not in ("REQUESTED", "CERTIFIED"):
        raise ApiError("ERR_INVALID_STATE")


@endpoint(
    "POST",
    "/vault/appraisals/{appraisal_id}/void",
    roles=["PlatformAdmin"],
    mutating=True,
    body={"void_reason": ("string", True)},
    enums={"void_reason": VOID_REASONS},
    household=_appraisal_household,
    rungs={13: _void_rung13, 14: _void_rung14},
)
def void_appraisal(ctx):
    appraisal = _appraisal(ctx)
    item = _appraisal_item(ctx)
    was_certified = appraisal["status"] == "CERTIFIED"
    appraisal["status"] = "VOIDED"
    appraisal["void_reason"] = ctx.body["void_reason"]
    store.touch(appraisal)
    # The consumed credit is never refunded on either path.
    if was_certified and item is not None:
        derive.refresh_item(item, bump=False)
        store.touch(item)
        cascades.appraisal_void_cascade(appraisal, item)
    return one(serializers.appraisal(appraisal))
