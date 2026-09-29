"""Sample allocation, cancellation, delivery and loss reporting."""

from flask import Blueprint

import clock
import db as store
import serializers
from db import db, new_row, ordered, touch
from errors import ApiError
from middleware import endpoint
from response import collection, single
from services import calculations as calc
from services.cascades import cancel_shipment
from services.gates import (check_enrollment_version, must_exist,
                            require_campaign_status, require_not_banned,
                            require_posture_not_frozen)
from validation import field, paginate, parse_body, parse_query

bp = Blueprint("sample_shipments", __name__)

SHIPMENT_STATUSES = ("ALLOCATED", "SHIPPED", "DELIVERED", "LOST", "CANCELLED")
SUPERSEDABLE_STATUSES = ("CANCELLED", "LOST")

CREATE_FIELDS = [
    field("enrollment_id", "id", required=True),
    field("fulfillment_wave_id", "id", required=True),
    field("expected_enrollment_version", "integer", required=True),
    field("surcharge_cents", "integer", default=0, minimum=0),
    field("supersedes_shipment_id", "id"),
]

LIST_FILTERS = [
    field("enrollment_id", "string"),
    field("fulfillment_wave_id", "string"),
    field("supersedes_shipment_id", "string"),
    field("status", "enum", values=SHIPMENT_STATUSES),
]


@bp.post("/sample-shipments")
@endpoint(["FulfillmentOps"])
def allocate_shipment():
    body, _ = parse_body(CREATE_FIELDS)

    # rung 8 — body foreign keys in input-list order
    enrollment = must_exist("enrollments", body["enrollment_id"], "Enrollment")
    wave = must_exist("fulfillment_waves", body["fulfillment_wave_id"],
                      "Fulfillment wave")
    superseded = None
    if body["supersedes_shipment_id"] is not None:
        superseded = must_exist("sample_shipments", body["supersedes_shipment_id"],
                                "Sample shipment")

    # rung 10 — pinned sub-order
    if enrollment["screening_status"] != "SCREEN_PASSED":
        raise ApiError("ERR_INVALID_SHIPMENT_STATE",
                       "The enrollment is not SCREEN_PASSED")
    if enrollment["obligation_status"] not in ("NONE", "FORFEITED"):
        raise ApiError("ERR_INVALID_SHIPMENT_STATE",
                       "Obligation status '%s' cannot receive a new allocation"
                       % enrollment["obligation_status"])
    if superseded is not None and superseded["status"] not in SUPERSEDABLE_STATUSES:
        raise ApiError("ERR_INVALID_SHIPMENT_STATE",
                       "Shipment status '%s' cannot be superseded" % superseded["status"])
    if wave["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_WAVE_STATE",
                       "Wave status is '%s', not PLANNED" % wave["status"])

    campaign = store.campaign_of_enrollment(enrollment)
    require_campaign_status(campaign, ("SAMPLING_ACTIVE",))
    check_enrollment_version(enrollment, body["expected_enrollment_version"])
    require_not_banned(store.panelist_of_enrollment(enrollment))
    require_posture_not_frozen(campaign)

    # rung 25
    if enrollment["holdout_flag"]:
        raise ApiError("ERR_HOLDOUT_ENROLLMENT_NOT_SAMPLEABLE",
                       "A holdout enrollment is never sampled")

    # rung 27
    active_lines = calc.active_kit_lines(campaign["id"])
    if not active_lines:
        raise ApiError("ERR_CAMPAIGN_KIT_EMPTY", "The campaign has no ACTIVE kit line")

    kit_unit_total = sum(line["quantity_per_kit"] for line in active_lines)

    # rungs 28 and 29
    capacity_error = calc.wave_capacity_error(wave, kit_unit_total)
    if capacity_error:
        raise ApiError(capacity_error, "The allocation exceeds a pick capacity ceiling")

    # rung 30 — all-or-nothing reservation, nothing written on failure
    reservation, stock_error = calc.kit_reservation(campaign["id"])
    if stock_error:
        raise ApiError(stock_error, "A kit line lacks sufficient available stock")
    reserved_line_units, kit_unit_total = reservation

    center = store.center_of_wave(wave)
    committed = campaign["kit_assembly_unit_cost_cents"] + center["freight_cents_per_kit"]

    # rung 33
    if campaign["budget_available_cents"] < committed:
        raise ApiError("ERR_CAMPAIGN_BUDGET_EXHAUSTED",
                       "The campaign's available budget cannot cover %d cents" % committed)

    row = new_row()
    row.update({
        "enrollment_id": enrollment["id"],
        "fulfillment_wave_id": wave["id"],
        "supersedes_shipment_id": body["supersedes_shipment_id"],
        "surcharge_cents": body["surcharge_cents"],
        "status": "ALLOCATED",
        "committed_cost_cents": committed,
        "reserved_line_units": dict(reserved_line_units),
        "kit_unit_total": kit_unit_total,
        "shipped_at": None,
        "delivered_at": None,
    })
    db.sample_shipments[row["id"]] = row

    for line_id, units in reserved_line_units.items():
        line = db.kit_lines[line_id]
        line["units_available"] -= units
        line["units_reserved"] += units
        touch(line)

    wave["planned_unit_count"] += kit_unit_total
    touch(wave)

    campaign["budget_committed_cents"] += committed
    campaign["budget_available_cents"] -= committed
    campaign["allocated_sample_count"] += 1
    calc.refresh_provisional_cost(campaign)
    touch(campaign)

    if superseded is not None and enrollment["obligation_status"] == "FORFEITED":
        enrollment["obligation_status"] = "NONE"
    touch(enrollment)

    return single(serializers.sample_shipment(row), 201)


@bp.get("/sample-shipments/<sample_shipment_id>")
@endpoint(["FulfillmentOps", "CampaignManager", "ComplianceModerator", "PlatformAdmin"])
def get_shipment(sample_shipment_id):
    parse_body([])
    row = must_exist("sample_shipments", sample_shipment_id, "Sample shipment")
    return single(serializers.sample_shipment(row))


@bp.get("/sample-shipments")
@endpoint(["FulfillmentOps", "CampaignManager", "ComplianceModerator", "PlatformAdmin"])
def list_shipments():
    query = parse_query(LIST_FILTERS)
    rows = ordered(db.sample_shipments.values())
    if query["enrollment_id"] is not None:
        rows = [r for r in rows if r["enrollment_id"] == query["enrollment_id"]]
    if query["fulfillment_wave_id"] is not None:
        rows = [r for r in rows
                if r["fulfillment_wave_id"] == query["fulfillment_wave_id"]]
    if query["supersedes_shipment_id"] is not None:
        rows = [r for r in rows
                if r["supersedes_shipment_id"] == query["supersedes_shipment_id"]]
    if query["status"] is not None:
        rows = [r for r in rows if r["status"] == query["status"]]
    page = paginate(rows, query["limit"], query["offset"])
    return collection([serializers.sample_shipment(r) for r in page], len(rows),
                      query["limit"], query["offset"])


@bp.post("/sample-shipments/<sample_shipment_id>/cancel")
@endpoint(["FulfillmentOps"])
def cancel(sample_shipment_id):
    parse_body([])
    shipment = must_exist("sample_shipments", sample_shipment_id, "Sample shipment")
    if shipment["status"] != "ALLOCATED":
        raise ApiError("ERR_INVALID_SHIPMENT_STATE",
                       "Shipment status is '%s', not ALLOCATED" % shipment["status"])
    cancel_shipment(shipment)
    return single(serializers.sample_shipment(shipment))


@bp.post("/sample-shipments/<sample_shipment_id>/deliver")
@endpoint(["FulfillmentOps"])
def deliver(sample_shipment_id):
    parse_body([])
    shipment = must_exist("sample_shipments", sample_shipment_id, "Sample shipment")
    if shipment["status"] != "SHIPPED":
        raise ApiError("ERR_INVALID_SHIPMENT_STATE",
                       "Shipment status is '%s', not SHIPPED" % shipment["status"])

    now = clock.now()
    shipment["status"] = "DELIVERED"
    shipment["delivered_at"] = clock.fmt(now)
    touch(shipment)

    campaign = store.campaign_of_shipment(shipment)
    campaign["delivered_sample_count"] += 1
    calc.refresh_final_cost(campaign)
    calc.refresh_posture(campaign)
    touch(campaign)

    enrollment = store.enrollment_of_shipment(shipment)
    if enrollment is not None and enrollment["obligation_status"] == "SAMPLE_SENT":
        enrollment["obligation_status"] = "REVIEW_DUE"
        enrollment["review_due_at"] = clock.fmt(
            now + clock.days(campaign["review_due_days"]))
        touch(enrollment)

    return single(serializers.sample_shipment(shipment))


@bp.post("/sample-shipments/<sample_shipment_id>/report-lost")
@endpoint(["FulfillmentOps"])
def report_lost(sample_shipment_id):
    parse_body([])
    shipment = must_exist("sample_shipments", sample_shipment_id, "Sample shipment")
    if shipment["status"] != "SHIPPED":
        raise ApiError("ERR_INVALID_SHIPMENT_STATE",
                       "Shipment status is '%s', not SHIPPED" % shipment["status"])

    shipment["status"] = "LOST"
    touch(shipment)

    campaign = store.campaign_of_shipment(shipment)
    calc.refresh_final_cost(campaign)
    touch(campaign)

    enrollment = store.enrollment_of_shipment(shipment)
    if enrollment is not None and enrollment["obligation_status"] == "SAMPLE_SENT":
        live = [s for s in store.enrollment_shipments(enrollment["id"])
                if s["id"] != shipment["id"]
                and s["status"] in ("ALLOCATED", "SHIPPED", "DELIVERED")]
        if not live:
            enrollment["obligation_status"] = "FORFEITED"
            touch(enrollment)

    return single(serializers.sample_shipment(shipment))
