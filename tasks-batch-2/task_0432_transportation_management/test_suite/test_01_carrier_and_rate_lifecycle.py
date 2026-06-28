"""Carrier roster, contract rates, and their lifecycle rules.

Covers carrier/rate creation defaults, suspend/reinstate, retire, SCAC
uniqueness, mode-match referential checks, the closed-interval rate-window
overlap rule, and role isolation on carrier creation.
"""
from test_helpers import (
    api_client, TEST_USERS,
    validate_success, validate_error, validate_paginated,
    assert_carrier, assert_contract_rate,
    ApiErrorId,
    create_carrier_payload, create_contract_rate_payload,
    setup_carrier_rate,
)

CARRIER = TEST_USERS["carrier_ops_headers"]
SHIPPER = TEST_USERS["shipper_ops_headers"]


def test_create_carrier_returns_201_with_defaults(api):
    """PRD §3.1: "A new carrier starts `ACTIVE`, with its `delivered_count`,
    `on_time_count`, and `claim_count` all initialized to zero, its `on_time_pct`
    null, and its `scorecard_grade` at `PROBATION`."

    Design: Corner/entities/create_carrier_returns_201_with_defaults
    """
    resp = api.create_carrier(create_carrier_payload(scac="ACME"), CARRIER)
    data = validate_success(resp, 201)
    assert_carrier(data)
    assert data["status"] == "ACTIVE"
    assert data["delivered_count"] == 0
    assert data["on_time_count"] == 0
    assert data["claim_count"] == 0
    assert data["on_time_pct"] is None
    assert data["scorecard_grade"] == "PROBATION"


def test_list_carriers_paginated_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`,
    and `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_carriers_paginated_envelope
    """
    api.create_carrier(create_carrier_payload(name="Acme TL", scac="ACME", mode="TL"), CARRIER)
    api.create_carrier(create_carrier_payload(name="Best LTL", scac="BEST", mode="LTL"), CARRIER)
    resp = api.list_carriers(SHIPPER, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_create_contract_rate_default_fuel_surcharge_zero(api):
    """PRD §3.2: "an optional `fuel_surcharge_pct` (a fraction such that 0.15
    means fifteen percent, defaulting to 0 when omitted)"

    Design: Corner/entities/create_contract_rate_default_fuel_surcharge_zero
    """
    carrier = validate_success(api.create_carrier(create_carrier_payload(scac="ACME"), CARRIER), 201)
    payload = create_contract_rate_payload(carrier_id=carrier["id"], base_rate_per_mile_cents=200)
    payload.pop("fuel_surcharge_pct")
    resp = api.create_contract_rate(payload, CARRIER)
    data = validate_success(resp, 201)
    assert_contract_rate(data)
    assert data["fuel_surcharge_pct"] == 0
    assert data["status"] == "ACTIVE"


def test_suspend_already_suspended_carrier_returns_not_active(api):
    """PRD §3.1: "suspending a carrier requires it to currently be `ACTIVE`,
    otherwise `ERR_CARRIER_NOT_ACTIVE`"

    Design: Corner/state_machines/suspend_already_suspended_carrier_returns_invalid_state
    """
    carrier = validate_success(api.create_carrier(create_carrier_payload(scac="ACME"), CARRIER), 201)
    validate_success(api.suspend_carrier(carrier["id"], CARRIER), 200)
    resp = api.suspend_carrier(carrier["id"], CARRIER)
    validate_error(resp, ApiErrorId.ERR_CARRIER_NOT_ACTIVE.value)


def test_duplicate_scac_rejected(api):
    """PRD §3.1: "The `scac` must be unique across all carriers; a collision is
    rejected with `ERR_DUPLICATE_SCAC`."

    Design: Corner/validations/duplicate_scac_rejected
    """
    validate_success(api.create_carrier(create_carrier_payload(name="Acme TL", scac="ACME", mode="TL"), CARRIER), 201)
    resp = api.create_carrier(create_carrier_payload(name="Acme Two", scac="ACME", mode="LTL"), CARRIER)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SCAC.value)


def test_contract_rate_mode_mismatch_rejected(api):
    """PRD §3.2: "The rate's `mode` must equal the carrier's own mode, or the
    request is rejected with `ERR_MODE_MISMATCH`."

    Design: Corner/validations/contract_rate_mode_mismatch_rejected
    """
    carrier = validate_success(api.create_carrier(create_carrier_payload(scac="ACME", mode="TL"), CARRIER), 201)
    payload = create_contract_rate_payload(
        carrier_id=carrier["id"], mode="LTL", base_rate_per_mile_cents=200, fuel_surcharge_pct=0.10)
    resp = api.create_contract_rate(payload, CARRIER)
    validate_error(resp, ApiErrorId.ERR_MODE_MISMATCH.value)


class TestRateWindowOverlapClosedPerLane:
    """The closed-interval rate-window overlap rule (resource_temporal_overlap)."""

    def test_sharing_endpoint_minute_is_overlap(self, api):
        """PRD §3.2: "When a newly created `ACTIVE` rate's closed window
        `[effective_start_minute, effective_end_minute]` would overlap an existing
        `ACTIVE` rate on the same lane in this sense, the create is rejected with
        `ERR_RATE_WINDOW_OVERLAP`."
        PRD §3.2: "two `ACTIVE` rates on the same carrier, mode, origin zone, and
        destination zone lane overlap if their inclusive intervals share any minute
        at all — including the case where one window's endpoint minute coincides
        with the other's endpoint minute."

        Design: Difficulty/resource_temporal_overlap/contract_rate_window_overlap_closed_per_lane
        """
        carrier = validate_success(api.create_carrier(create_carrier_payload(scac="ACME", mode="TL"), CARRIER), 201)
        validate_success(api.create_contract_rate(create_contract_rate_payload(
            carrier_id=carrier["id"], effective_start_minute=0, effective_end_minute=60), CARRIER), 201)
        resp = api.create_contract_rate(create_contract_rate_payload(
            carrier_id=carrier["id"], base_rate_per_mile_cents=300,
            effective_start_minute=60, effective_end_minute=120), CARRIER)
        validate_error(resp, ApiErrorId.ERR_RATE_WINDOW_OVERLAP.value)

    def test_overlapping_interior_minutes_is_overlap(self, api):
        """PRD §3.2: "two `ACTIVE` rates on the same carrier, mode, origin zone, and
        destination zone lane overlap if their inclusive intervals share any minute
        at all"

        Design: Difficulty/resource_temporal_overlap/contract_rate_window_overlap_closed_per_lane
        """
        carrier = validate_success(api.create_carrier(create_carrier_payload(scac="ACME", mode="TL"), CARRIER), 201)
        validate_success(api.create_contract_rate(create_contract_rate_payload(
            carrier_id=carrier["id"], effective_start_minute=0, effective_end_minute=100), CARRIER), 201)
        resp = api.create_contract_rate(create_contract_rate_payload(
            carrier_id=carrier["id"], base_rate_per_mile_cents=300,
            effective_start_minute=50, effective_end_minute=150), CARRIER)
        validate_error(resp, ApiErrorId.ERR_RATE_WINDOW_OVERLAP.value)


def test_shipperops_cannot_create_carrier_forbidden(api):
    """PRD §2.1: "When a role attempts an operation it is not permitted to perform,
    the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §2.1: "A `CarrierOps` operator creates carriers, suspends and reinstates
    them, creates and retires contract rates, accepts and declines tenders, and
    drives physical execution by departing and delivering shipments."

    Design: Corner/rbac/shipperops_cannot_create_carrier_forbidden
    """
    resp = api.create_carrier(create_carrier_payload(name="Sneaky", scac="SNK", mode="TL"), SHIPPER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
