"""Pricing exception request, decision and the retroactive void cascade (PRD §3.6)."""

from flask import Blueprint

import lookup
from auth import (
    ROLE_BRAND_CHANNEL_MANAGER, ROLE_BRAND_LEGAL_COUNSEL, STAFF_AND_RESELLER, authenticate,
)
from calc import dec, floor_int, rhu_int
from envelope import created, ok, ok_list
from errors import fail
from store import days, dt_of, new_row, now_dt, parse_iso, serialize, sort_rows, store, touch
from validate import (
    CHANNEL_SCOPES, DEALER_INPUT_SOURCES, EXCEPTION_TYPES, body, opt_enum, opt_int,
    req_dt, req_enum, req_str,
)

bp = Blueprint("exceptions", __name__)

MAX_WINDOW_DAYS = 180
MAX_RETROACTIVE_DAYS = 30
FLOOR_BAND_FRACTION = "0.50"
DECISIONS = ["APPROVE", "REJECT"]
LIVE_EXCEPTION_STATUSES = ("REQUESTED", "APPROVED")
COVERED_VIOLATION_STATUSES = ("DETECTED", "NOTICED", "DISPUTED")


def _scopes_intersect(left, right):
    return left == right or left == "ALL" or right == "ALL"


@bp.post("/pricing-exceptions")
def request_exception():
    ctx = authenticate([ROLE_BRAND_CHANNEL_MANAGER])
    b = body()
    product_id = req_str(b, "product_id")
    exception_type = req_enum(b, "exception_type", EXCEPTION_TYPES)
    starts_at = req_dt(b, "starts_at")
    ends_at = req_dt(b, "ends_at")
    channel_scope = opt_enum(b, "channel_scope", CHANNEL_SCOPES, "ALL")
    requested_floor = opt_int(b, "requested_override_floor_cents", 1, None)
    dealer_input_source = opt_enum(b, "dealer_input_source", DEALER_INPUT_SOURCES, "NONE")

    starts = parse_iso(starts_at)
    ends = parse_iso(ends_at)
    if ends <= starts:
        fail("ERR_VALIDATION", "ends_at must be strictly after starts_at.")
    if ends - starts > days(MAX_WINDOW_DAYS):
        fail("ERR_VALIDATION", "An exception window may not span more than 180 days.")
    if exception_type in ("BUNDLE", "PROMOTIONAL_EVENT") and requested_floor is None:
        fail("ERR_VALIDATION",
             "requested_override_floor_cents is required for %s exceptions." % exception_type)

    lookup.product(product_id)

    if dealer_input_source == "RESELLER_PRICING_REQUEST":
        fail("ERR_ANTITRUST_DEALER_PRICE_INPUT",
             "An exception may not be sourced from a dealer's price request.")

    for other in store.exceptions.values():
        if other["product_id"] != product_id or other["status"] not in LIVE_EXCEPTION_STATUSES:
            continue
        if not _scopes_intersect(channel_scope, other["channel_scope"]):
            continue
        other_starts = dt_of(other, "starts_at")
        other_ends = dt_of(other, "ends_at")
        if other_starts is None or other_ends is None:
            continue
        # Half-open semantics: adjacency is legal, true intersection is not.
        if starts < other_ends and other_starts < ends:
            fail("ERR_EXCEPTION_WINDOW_OVERLAP",
                 "The window intersects a live exception on the same product.")

    now = now_dt()
    retroactive = starts < now
    if retroactive and starts < now - days(MAX_RETROACTIVE_DAYS):
        fail("ERR_RETROACTIVE_WINDOW_TOO_OLD",
             "A retroactive exception may not reach back more than 30 days.")

    row = new_row({
        "product_id": product_id,
        "exception_type": exception_type,
        "channel_scope": channel_scope,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "requested_override_floor_cents": requested_floor,
        "override_floor_cents": None,
        "status": "REQUESTED",
        "retroactive": retroactive,
        "dealer_input_source": dealer_input_source,
        "requested_by_user_id": ctx.user_id,
        "approved_by_user_id": None,
        "decision_reason": None,
        "voided_violation_count": 0,
    })
    store.exceptions[row["id"]] = row
    return created(serialize(row))


@bp.post("/pricing-exceptions/<exception_id>/decision")
def decide_exception(exception_id):
    ctx = authenticate([ROLE_BRAND_LEGAL_COUNSEL])
    b = body()
    decision = req_enum(b, "decision", DECISIONS)
    decision_reason = req_str(b, "decision_reason", 1, None)
    exception = lookup.exception(exception_id)
    if exception["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE", "Only a REQUESTED exception may be decided.")

    if decision == "REJECT":
        exception["status"] = "REJECTED"
        exception["decision_reason"] = decision_reason
        exception["approved_by_user_id"] = ctx.user_id
        touch(exception)
        return ok(serialize(exception))

    product = store.products.get(exception["product_id"])
    if product is None or product["lifecycle_status"] == "DISCONTINUED":
        fail("ERR_INVALID_STATE", "A discontinued product may not receive an approved exception.")
    if exception["exception_type"] == "CLEARANCE":
        if product["lifecycle_status"] != "CLEARANCE":
            fail("ERR_PRODUCT_NOT_IN_CLEARANCE",
                 "A CLEARANCE exception requires the product to be in lifecycle CLEARANCE.")
        override = rhu_int(
            dec(product["standard_map_floor_cents"])
            * (dec(1) - dec(product["clearance_discount_pct"]))
        )
    else:
        override = exception["requested_override_floor_cents"]
        lower = floor_int(dec(product["standard_map_floor_cents"]) * dec(FLOOR_BAND_FRACTION))
        if override >= product["standard_map_floor_cents"] or override < lower:
            fail("ERR_OVERRIDE_FLOOR_OUT_OF_RANGE",
                 "The override floor must sit below the standard floor and at or above half of it.")

    exception["status"] = "APPROVED"
    exception["override_floor_cents"] = override
    exception["approved_by_user_id"] = ctx.user_id
    exception["decision_reason"] = decision_reason
    product["open_exception_count"] = product["open_exception_count"] + 1
    touch(product)

    exception["voided_violation_count"] = _retroactive_void_cascade(exception, override)
    touch(exception)
    return ok(serialize(exception))


def _retroactive_void_cascade(exception, override):
    """Void every covered violation the new floor lifts back into compliance."""
    starts = dt_of(exception, "starts_at")
    ends = dt_of(exception, "ends_at")
    scope = exception["channel_scope"]
    voided = 0
    for violation in sort_rows(list(store.violations.values())):
        if violation["status"] not in COVERED_VIOLATION_STATUSES:
            continue
        observation = store.observations.get(violation["observation_id"])
        if observation is None or observation["product_id"] != exception["product_id"]:
            continue
        if scope != "ALL" and observation["channel"] != scope:
            continue
        observed = dt_of(observation, "observed_at")
        if observed is None or not (starts <= observed < ends):
            continue
        advertised = observation.get("effective_advertised_price_cents")
        if advertised is None or advertised < override:
            continue

        violation["status"] = "VOIDED"
        violation["resolution_reason"] = "RETROACTIVE_EXCEPTION"
        points = violation.get("assessed_points")
        if points is not None:
            reseller = store.resellers.get(violation["reseller_id"])
            if reseller is not None:
                reseller["violation_points_total"] = reseller["violation_points_total"] - points
                touch(reseller)
            violation["assessed_points"] = None
        touch(violation)
        for notice in sort_rows(list(store.notices.values())):
            if notice["violation_id"] != violation["id"]:
                continue
            if notice["status"] not in ("ISSUED", "ACKNOWLEDGED"):
                continue
            notice["status"] = "RESCINDED"
            notice["closed_reason"] = "RETROACTIVE_EXCEPTION"
            touch(notice)
        voided += 1
    return voided


@bp.get("/pricing-exceptions/<exception_id>")
def read_exception(exception_id):
    authenticate(STAFF_AND_RESELLER)
    return ok(serialize(lookup.exception(exception_id)))


@bp.get("/pricing-exceptions")
def list_exceptions():
    authenticate(STAFF_AND_RESELLER)
    rows = lookup.filtered("exceptions", {
        "product_id": "product_id",
        "exception_type": "exception_type",
        "status": "status",
    })
    return ok_list(rows)
