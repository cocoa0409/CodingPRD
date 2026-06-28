"""Warranty claim lifecycle: info-request revision loop, approval callback, window, buffer.

Translates difficulty rules: non_linear_state_machine (claim info-request cycle),
cross_entity_state_dependency (approve requires COMPLETED request),
resource_temporal_overlap (buffered callback conflict); plus the corner validations
warranty-window-expired instance.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_customer_headers, make_mechanic_headers,
    set_clock, create_customer, create_mechanic, create_service_request,
    send_quote, approve_quote, dispatch, finish_visit, file_warranty_claim,
    setup_completed_request,
    create_approve_warranty_payload,
)
from test_helpers.test_users import TEST_USERS

DISPATCHER = TEST_USERS["dispatcher_headers"]


def _completed_retail_request(email, vin, mechanic_tier="TIER2", mechanic_rate=9000):
    """Drive a retail request to COMPLETED. Returns (customer, mechanic, sr)."""
    customer = create_customer(home_zone_code="Z1", email=email)
    mechanic = create_mechanic(zone_code="Z1", skill_tier=mechanic_tier,
                               labor_rate_cents_per_hour=mechanic_rate)
    sr = create_service_request(customer["id"], vehicle_vin=vin)
    quote = send_quote(sr["id"], mechanic["id"], estimated_labor_hours=1.0,
                       estimated_parts_cents=0, labor_rate_cents_per_hour=mechanic_rate)
    approve_quote(quote["id"], customer["id"], sr["id"])
    jv = dispatch(sr["id"], mechanic["id"], routing_mode="ON_SITE",
                  scheduled_start_utc="2026-04-02T08:00:00Z",
                  scheduled_end_utc="2026-04-02T09:00:00Z")
    mech_headers = make_mechanic_headers(mechanic["id"])
    get_success_data(api_client.depart(jv["id"], mech_headers))
    get_success_data(api_client.start_work(jv["id"], mech_headers))
    finish_visit(jv["id"], mechanic["id"], logged_labor_hours=1.0, payment_method="CARD")
    return customer, mechanic, sr


# ── Difficulty: warranty claim info-request revision loop ──

def test_warranty_claim_info_request_revision_cycle(api):
    """PRD §3.8: "a dispatcher may move it `UNDER_REVIEW → INFO_REQUESTED`, and the
    customer may then supply the requested information to move it back
    `INFO_REQUESTED → UNDER_REVIEW`, and this cycle may repeat any number of rounds."

    Design: Difficulty/non_linear_state_machine/warranty_claim_info_request_revision_cycle
    """
    set_clock()
    customer, mechanic, sr = _completed_retail_request("m6@x.com", "1HGCM82633A004357")
    claim = file_warranty_claim(sr["id"], customer["id"], reason_text="fault returned")
    get_success_data(api.request_info(claim["id"], DISPATCHER))

    res = api.supply_info(claim["id"], make_customer_headers(customer["id"]))
    claim_after = validate_success(res, 200)
    assert claim_after["status"] == "UNDER_REVIEW"


def test_warranty_claim_cycle_bumps_version_each_round(api):
    """PRD §2.8: "Whenever a resource is mutated as part of such a cascade ... its
    `updated_at` is refreshed and its `version` is incremented by one."
    PRD §3.8: "a dispatcher may move it `UNDER_REVIEW → INFO_REQUESTED`, and the customer
    may then supply the requested information to move it back
    `INFO_REQUESTED → UNDER_REVIEW`".

    Design: Difficulty/non_linear_state_machine/warranty_claim_info_request_revision_cycle
    """
    set_clock()
    customer, mechanic, sr = _completed_retail_request("m6b@x.com", "1HGCM82633A004387")
    claim = file_warranty_claim(sr["id"], customer["id"], reason_text="fault returned")
    assert claim["version"] == 1
    get_success_data(api.request_info(claim["id"], DISPATCHER))   # version -> 2
    res = api.supply_info(claim["id"], make_customer_headers(customer["id"]))  # version -> 3
    claim_after = validate_success(res, 200)
    assert claim_after["status"] == "UNDER_REVIEW"
    assert claim_after["version"] == 3


# ── Difficulty: warranty approval requires COMPLETED request, creates callback ──

def test_warranty_approve_requires_request_completed_happy_path(api):
    """PRD §3.8: "It is permitted only while the claim is `UNDER_REVIEW`, only when the
    referenced service request is `COMPLETED`".
    PRD §3.8: "the system creates a free callback `JobVisit` in `SCHEDULED` status with
    `ON_SITE` routing for the same mechanic and zone, records that visit's identifier in
    the claim's `callback_visit_id`, moves the claim to `APPROVED`".

    Design: Difficulty/cross_entity_state_dependency/warranty_approve_requires_request_completed
    """
    set_clock()
    customer, mechanic, sr = _completed_retail_request("m14@x.com", "1HGCM82633A004365")
    claim = file_warranty_claim(sr["id"], customer["id"], reason_text="fault recurred")

    res = api.approve_warranty_claim(
        claim["id"], create_approve_warranty_payload(
            mechanic["id"], scheduled_start_utc="2026-04-05T09:00:00Z",
            scheduled_end_utc="2026-04-05T10:00:00Z"), DISPATCHER)
    claim_after = validate_success(res, 200)
    assert claim_after["status"] == "APPROVED"
    assert claim_after["callback_visit_id"] is not None

    callback = validate_success(api.get_job_visit(claim_after["callback_visit_id"],
                                                  DISPATCHER), 200)
    assert callback["visit_status"] == "SCHEDULED"
    assert callback["routing_mode"] == "ON_SITE"


def test_warranty_approve_callback_for_same_mechanic(api):
    """PRD §3.8: "the system creates a free callback `JobVisit` in `SCHEDULED` status with
    `ON_SITE` routing for the same mechanic and zone".

    Design: Difficulty/cross_entity_state_dependency/warranty_approve_requires_request_completed
    """
    set_clock()
    customer, mechanic, sr = _completed_retail_request("m14b@x.com", "1HGCM82633A004395")
    claim = file_warranty_claim(sr["id"], customer["id"], reason_text="fault recurred")
    res = api.approve_warranty_claim(
        claim["id"], create_approve_warranty_payload(
            mechanic["id"], scheduled_start_utc="2026-04-05T09:00:00Z",
            scheduled_end_utc="2026-04-05T10:00:00Z"), DISPATCHER)
    claim_after = validate_success(res, 200)
    callback = validate_success(api.get_job_visit(claim_after["callback_visit_id"],
                                                  DISPATCHER), 200)
    assert callback["mechanic_id"] == mechanic["id"]


# ── Difficulty: buffered callback overlap rejected ──

def test_warranty_callback_buffered_overlap_rejected(api):
    """PRD §3.8: "The callback slot is also protected against double-booking with a
    buffer: the proposed callback interval, extended by thirty minutes on each side, must
    not overlap any existing non-terminal visit for the same mechanic; a buffered
    conflict is rejected with `ERR_CALLBACK_SLOT_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/warranty_callback_buffered_overlap_rejected
    """
    set_clock()
    # Completed request + claim for the warranty mechanic.
    customer, mechanic, sr = _completed_retail_request("m16@x.com", "1HGCM82633A004368")
    claim = file_warranty_claim(sr["id"], customer["id"], reason_text="recurred")

    # A second request dispatched ON_SITE to the SAME mechanic at [12:00,13:00) on 04-05.
    cust_b = create_customer(home_zone_code="Z1", email="m16b@x.com", full_name="M16b")
    sr_b = create_service_request(cust_b["id"], vehicle_vin="1HGCM82633A004369")
    qb = send_quote(sr_b["id"], mechanic["id"], estimated_labor_hours=1.0,
                    estimated_parts_cents=0, labor_rate_cents_per_hour=9000)
    approve_quote(qb["id"], cust_b["id"], sr_b["id"])
    dispatch(sr_b["id"], mechanic["id"], routing_mode="ON_SITE",
             scheduled_start_utc="2026-04-05T12:00:00Z",
             scheduled_end_utc="2026-04-05T13:00:00Z")

    # Callback at [13:15,14:00): raw gap 15 min < 30-min buffer -> conflict.
    res = api.approve_warranty_claim(
        claim["id"], create_approve_warranty_payload(
            mechanic["id"], scheduled_start_utc="2026-04-05T13:15:00Z",
            scheduled_end_utc="2026-04-05T14:00:00Z"), DISPATCHER)
    validate_error(res, "ERR_CALLBACK_SLOT_CONFLICT", expected_status=409)
    claim_after = validate_success(api.get_warranty_claim(claim["id"], DISPATCHER), 200)
    assert claim_after["status"] == "UNDER_REVIEW"
    assert claim_after["callback_visit_id"] is None


def test_warranty_callback_buffer_does_not_block_distant_slot(api):
    """PRD §3.8: "the proposed callback interval, extended by thirty minutes on each side,
    must not overlap any existing non-terminal visit for the same mechanic; a buffered
    conflict is rejected with `ERR_CALLBACK_SLOT_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/warranty_callback_buffered_overlap_rejected
    """
    set_clock()
    customer, mechanic, sr = _completed_retail_request("m16c@x.com", "1HGCM82633A004378")
    claim = file_warranty_claim(sr["id"], customer["id"], reason_text="recurred")

    # An existing ON_SITE visit at [12:00,13:00) for the same mechanic.
    cust_b = create_customer(home_zone_code="Z1", email="m16d@x.com", full_name="M16d")
    sr_b = create_service_request(cust_b["id"], vehicle_vin="1HGCM82633A004379")
    qb = send_quote(sr_b["id"], mechanic["id"], estimated_labor_hours=1.0,
                    estimated_parts_cents=0, labor_rate_cents_per_hour=9000)
    approve_quote(qb["id"], cust_b["id"], sr_b["id"])
    dispatch(sr_b["id"], mechanic["id"], routing_mode="ON_SITE",
             scheduled_start_utc="2026-04-05T12:00:00Z",
             scheduled_end_utc="2026-04-05T13:00:00Z")

    # Callback at [14:00,15:00): one hour gap > 30-min buffer -> allowed.
    res = api.approve_warranty_claim(
        claim["id"], create_approve_warranty_payload(
            mechanic["id"], scheduled_start_utc="2026-04-05T14:00:00Z",
            scheduled_end_utc="2026-04-05T15:00:00Z"), DISPATCHER)
    claim_after = validate_success(res, 200)
    assert claim_after["status"] == "APPROVED"
    assert claim_after["callback_visit_id"] is not None

# NOTE: Corner/validations/warranty_window_expired_rejected is SKIPPED.
# The instance files the claim at the same clock instant as completion (within window)
# and only then advances the clock before approval — but PRD §3.8 measures the window as
# "the elapsed time from the request's completion to the claim's `filed_at_utc`", which is
# ~0 days here and uniquely derives a PASS (claim approved), not ERR_WARRANTY_WINDOW_EXPIRED.
# The asserted rejection is therefore not uniquely derivable from PRD prose; gap left as a gap.
