"""Consuming parts draws them off the shelf and out of the earmark together."""
from test_helpers import (
    TECHNICIAN_1,
    TECHNICIAN_HEADERS,
    ApiErrorId,
    api_client,
    assert_spare_part_unit_conservation,
    create_dispatch,
    drive_dispatch_to_on_site,
    ingest_and_classify_outage,
    read_dispatch,
    read_part_reservation,
    read_spare_part,
    reserve_parts,
    setup_operational_station,
    setup_spare_part_with_stock,
    validate_error,
    validate_success,
)


def test_consume_is_illegal_before_arrival_and_leaves_the_unencumbered_figure_alone():
    """CONSUME and RELEASE differ in exactly one counter, which is easy to swap.

    PRD §3.6: "`CONSUME` is the technician's action and is permitted only by the
    dispatch's assigned technician (otherwise `ERR_NOT_ASSIGNED_TECHNICIAN`), only
    from `RESERVED`, and only while the owning dispatch is in `ON_SITE` or
    `PARTS_HOLD`.  It moves the reservation `RESERVED → CONSUMED`, lowers the
    part's `on_hand_qty` and `reserved_qty` each by the reservation's quantity, and
    raises `consumed_qty_lifetime` by the same quantity — leaving the unencumbered
    figure exactly where it was, because the units left the shelf and the earmark
    at the same time."  PRD §2.11, rule 8: "Transition legality: the target
    resource occupies a state from which the requested transition exists in the
    relevant dimension ... including the sub-selector carried in the body for
    exclusion actions, progress events and reservation dispositions —
    `ERR_INVALID_STATE`."  PRD §3.6 on the conserved figure: "`unencumbered_qty` —
    the figure the reserve/release pair conserves — is `on_hand_qty` less
    `reserved_qty`."

    Design: Corner/endpoints/consuming_a_reservation_draws_the_parts_out_of_on_hand_stock
    """
    scenario = setup_operational_station(
        clock="2026-08-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        port_count=1,
        committed_service_capacity_kw=400.00,
    )
    port_id = scenario["ports"][0]["id"]

    part = setup_spare_part_with_stock(
        part_number="SP-1", part_class="DISPENSER", lead_time_days=3, on_hand_qty=10
    )
    outage = ingest_and_classify_outage(
        port_id, "2026-08-01T00:00:00Z", fault_class="MAJOR", fault_code="EVSE-MAJ-11"
    )
    dispatch = create_dispatch(
        outage["id"],
        port_id,
        window_start_at="2026-08-01T01:00:00Z",
        window_end_at="2026-08-01T09:00:00Z",
        technician_user_id=TECHNICIAN_1,
    )
    reservation = reserve_parts(dispatch["id"], part["id"], 4, part["version"])

    assert reservation["state"] == "RESERVED"
    before = read_spare_part(part["id"])
    assert before["on_hand_qty"] == 10
    assert before["reserved_qty"] == 4
    assert before["unencumbered_qty"] == 6
    assert before["consumed_qty_lifetime"] == 0
    assert_spare_part_unit_conservation(before)
    assert read_dispatch(dispatch["id"])["state"] == "CREATED"

    early = api_client.dispose_part_reservation(
        reservation["id"], "CONSUME", TECHNICIAN_HEADERS
    )

    validate_error(early, ApiErrorId.ERR_INVALID_STATE, 409)

    untouched = read_spare_part(part["id"])
    assert untouched["on_hand_qty"] == 10
    assert untouched["reserved_qty"] == 4
    assert untouched["unencumbered_qty"] == 6
    assert untouched["consumed_qty_lifetime"] == 0
    assert read_part_reservation(reservation["id"])["state"] == "RESERVED"

    on_site = drive_dispatch_to_on_site(dispatch["id"], TECHNICIAN_1)
    assert on_site["state"] == "ON_SITE"

    data = validate_success(
        api_client.dispose_part_reservation(reservation["id"], "CONSUME", TECHNICIAN_HEADERS)
    )

    assert data["state"] == "CONSUMED"
    assert data["qty"] == 4

    after = read_spare_part(part["id"])
    assert after["on_hand_qty"] == 6
    assert after["reserved_qty"] == 0
    assert after["unencumbered_qty"] == 6, "the units left the shelf and the earmark together"
    assert after["consumed_qty_lifetime"] == 4
    assert after["backordered_qty"] == 0
    assert_spare_part_unit_conservation(after)
