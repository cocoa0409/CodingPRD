"""Two enum-legal but business-illegal payloads that must be caught by rule."""
from test_helpers import (
    OPERATOR_HEADERS,
    TECHNICIAN_1,
    ApiErrorId,
    api_client,
    assert_spare_part_unit_conservation,
    assert_version_unchanged,
    create_dispatch,
    create_part_reservation_payload,
    ingest_and_classify_outage,
    read_charging_port,
    read_outage_event,
    read_spare_part,
    read_station,
    setup_spare_part_with_stock,
    setup_station,
    validate_error,
    validate_success,
)


def _draft_station_with_one_plain_dispenser(station_code="ST-1", site_code="HS-1"):
    scenario = setup_station(
        clock="2026-08-01T00:00:00Z",
        site_code=site_code,
        station_code=station_code,
        committed_service_capacity_kw=400.00,
        power_class="DCFC_150",
        declared_port_count=1,
        ports=[{"dispenser_serial": "DS-1", "terminal_model": "PT-4"}],
        stop_at="DRAFT",
    )
    return scenario["station"]["id"], scenario["ports"][0]["id"]


def test_an_exclusion_requested_on_the_none_cause_never_opens_a_review():
    """NONE is inside the enum, so only the business rule can stop it.

    PRD §3.4: "An optional `excluded_cause_claim` may be asserted at ingestion; it
    defaults to `NONE` and is drawn from `NONE`, `UTILITY_OUTAGE`,
    `NATURAL_DISASTER`, `VANDALISM`, `HOST_SITE_CLOSURE`, and
    `EVSE_MANUFACTURER_RECALL`.  A claim of `NONE` is not eligible for
    exclusion."  And: "A request is permitted only from `CLASSIFIED` or
    `RESOLVED`, only while the dispenser is not `RETIRED`, and only while
    `excluded_cause_claim` is something other than `NONE` — a claim of `NONE` is
    rejected with `ERR_EXCLUSION_CAUSE_NOT_ELIGIBLE`.  The outage moves to
    `EXCLUSION_REVIEW` and records which state it came from in
    `pre_exclusion_state`: `CLASSIFIED` when requested from `CLASSIFIED`."

    Design: Corner/validations/exclusion_request_without_an_eligible_cause_is_rejected
    """
    station_id, port_id = _draft_station_with_one_plain_dispenser()

    outage = ingest_and_classify_outage(
        port_id, "2026-08-01T00:00:00Z", fault_class="MAJOR", fault_code="EVSE-MAJ-11"
    )
    assert outage["excluded_cause_claim"] == "NONE", "the declared default"
    assert read_charging_port(port_id)["service_state"] == "OUT_OF_SERVICE"

    response = api_client.submit_exclusion_action(
        outage["id"], {"action": "REQUEST", "excluded_cause_claim": "NONE"}, OPERATOR_HEADERS
    )

    validate_error(response, ApiErrorId.ERR_EXCLUSION_CAUSE_NOT_ELIGIBLE, 422)

    refused = read_outage_event(outage["id"])
    assert refused["state"] == "CLASSIFIED"
    assert refused["excluded_cause_claim"] == "NONE"
    assert refused["pre_exclusion_state"] is None

    data = validate_success(
        api_client.submit_exclusion_action(
            outage["id"],
            {"action": "REQUEST", "excluded_cause_claim": "VANDALISM"},
            OPERATOR_HEADERS,
        )
    )

    assert data["state"] == "EXCLUSION_REVIEW"
    assert data["excluded_cause_claim"] == "VANDALISM"
    assert data["pre_exclusion_state"] == "CLASSIFIED"

    assert read_charging_port(port_id)["service_state"] == "OUT_OF_SERVICE"
    assert read_station(station_id)["status"] == "DRAFT"


def test_a_zero_quantity_reservation_is_refused_without_touching_the_depot():
    """A zero line would still be a considered reservation on the next parts hold.

    PRD §3.6: "A `NetworkOperator` creates a reservation naming the `dispatch_id`
    the parts are for, the `spare_part_id` being earmarked, the `qty` of units,
    and the `expected_spare_part_version` guard of §2.7.  The quantity must be at
    least 1; anything lower is rejected with `ERR_RESERVATION_QTY_INVALID`."  And:
    "If the quantity is covered, the reservation is created in `RESERVED`, the
    part's `reserved_qty` rises by that quantity, and `expected_available_at`
    stays null."  PRD §3.6 on the figure that must not move: "`unencumbered_qty` —
    the figure the reserve/release pair conserves — is `on_hand_qty` less
    `reserved_qty`."

    Design: Corner/validations/reservation_quantity_must_be_at_least_one
    """
    _station_id, port_id = _draft_station_with_one_plain_dispenser()

    outage = ingest_and_classify_outage(
        port_id, "2026-08-01T00:00:00Z", fault_class="MINOR", fault_code="OCPP-MIN-01"
    )
    dispatch = create_dispatch(
        outage["id"],
        port_id,
        window_start_at="2026-08-01T01:00:00Z",
        window_end_at="2026-08-01T09:00:00Z",
        technician_user_id=TECHNICIAN_1,
    )
    part = setup_spare_part_with_stock(
        part_number="SP-1", part_class="DISPENSER", lead_time_days=3, on_hand_qty=5
    )

    response = api_client.create_part_reservation(
        create_part_reservation_payload(dispatch["id"], part["id"], 0, part["version"]),
        OPERATOR_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_RESERVATION_QTY_INVALID, 422)

    untouched = read_spare_part(part["id"])
    assert untouched["on_hand_qty"] == 5
    assert untouched["reserved_qty"] == 0
    assert untouched["unencumbered_qty"] == 5
    assert_spare_part_unit_conservation(untouched)
    assert_version_unchanged(untouched, part["version"], "SparePart")

    data = validate_success(
        api_client.create_part_reservation(
            create_part_reservation_payload(dispatch["id"], part["id"], 1, part["version"]),
            OPERATOR_HEADERS,
        ),
        201,
    )

    assert data["state"] == "RESERVED", "the still-valid pinned version was reusable"
    assert data["qty"] == 1
    assert data["expected_available_at"] is None

    after = read_spare_part(part["id"])
    assert after["reserved_qty"] == 1
    assert after["unencumbered_qty"] == 4
    assert_spare_part_unit_conservation(after)
