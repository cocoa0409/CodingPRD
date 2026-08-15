"""Monitor visits: window overlap, clock-gated start, reconciliation close, and
the book-vs-physical dual variant (PRD §2.10, §3.9)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId,
    setup_pharmacy, setup_returned_kit, setup_book_vs_physical_scenario,
    setup_started_visit, create_monitor_visit, start_visit,
    create_monitor_visit_payload, get_kit,
)
from test_helpers import TEST_USERS

SPONSOR = TEST_USERS["sponsor_admin_headers"]
MONITOR = TEST_USERS["monitor_headers"]


def test_monitor_visit_half_open_adjacency_allowed():
    """PRD §3.9: "Visit windows at a site behave as half-open intervals: a new
    visit whose interval intersects an existing `SCHEDULED` or `IN_PROGRESS`
    visit at the same site is rejected with `ERR_MONITOR_VISIT_OVERLAP`, while
    adjacency is permitted — a visit beginning exactly when another ends does
    not conflict."

    Design: Difficulty/resource_temporal_overlap/monitor_visit_half_open_adjacency_allowed
    """
    world = setup_pharmacy(protocol_number="P-OVL-1", kit_numbers=())
    site_id = world["site"]["id"]
    first = validate_success(api_client.create_monitor_visit(
        create_monitor_visit_payload(site_id, "2026-08-10T09:00:00Z", "2026-08-10T12:00:00Z",
                                     monitor_name="CRA A"),
        MONITOR), expected_status=201)
    adjacent = validate_success(api_client.create_monitor_visit(
        create_monitor_visit_payload(site_id, "2026-08-10T12:00:00Z", "2026-08-10T15:00:00Z",
                                     monitor_name="CRA B"),
        MONITOR), expected_status=201)
    assert first["status"] == "SCHEDULED"
    assert adjacent["status"] == "SCHEDULED", (
        "[12:00,15:00) begins exactly when [09:00,12:00) ends — adjacency permitted"
    )


def test_monitor_visit_overlap_rejected():
    """PRD §3.9: "a new visit whose interval intersects an existing `SCHEDULED`
    or `IN_PROGRESS` visit at the same site is rejected with
    `ERR_MONITOR_VISIT_OVERLAP`".

    Design: Difficulty/resource_temporal_overlap/monitor_visit_half_open_adjacency_allowed
    """
    world = setup_pharmacy(protocol_number="P-OVL-1B", kit_numbers=())
    site_id = world["site"]["id"]
    create_monitor_visit(site_id, "2026-08-10T09:00:00Z", "2026-08-10T12:00:00Z")
    create_monitor_visit(site_id, "2026-08-10T12:00:00Z", "2026-08-10T15:00:00Z")
    resp = api_client.create_monitor_visit(
        create_monitor_visit_payload(site_id, "2026-08-10T11:00:00Z", "2026-08-10T13:00:00Z",
                                     monitor_name="CRA C"),
        MONITOR)
    validate_error(resp, ApiErrorId.ERR_MONITOR_VISIT_OVERLAP.value, expected_status=409)


def test_monitor_close_with_unverified_return_rejected():
    """PRD §3.9: "Two preconditions guard the close: every drug return recorded
    against dispensing records at this site must already be `VERIFIED`
    (`ERR_UNVERIFIED_RETURN_PENDING`)".

    Design: Corner/validations/monitor_close_with_unverified_return_rejected
    """
    world = setup_pharmacy(protocol_number="P-VAL-10", kit_numbers=("K-UR",),
                           pharmacist_license="L-VAL-10")
    returned = setup_returned_kit(world, subject_number="SUB-UR", quantity=4)
    assert returned["return"]["status"] == "RECORDED", "return never verified"
    visit = setup_started_visit(world)
    resp = api_client.close_monitor_visit(
        visit["id"], {"counts": [{"kit_id": returned["kit"]["id"], "physical_units": 10}]},
        MONITOR)
    validate_error(resp, ApiErrorId.ERR_UNVERIFIED_RETURN_PENDING.value, expected_status=422)
    assert get_success_data(api_client.get_monitor_visit(visit["id"], SPONSOR))["status"] == "IN_PROGRESS"


def test_monitor_close_with_incomplete_counts_rejected():
    """PRD §3.9: "the submitted counts must cover every kit at the site in an
    on-hand state — `AVAILABLE`, `ALLOCATED`, `QUARANTINED_EXCURSION`,
    `EXPIRED`, `RETURNED`, or `DESTRUCTION_PENDING` — exactly once
    (`ERR_COUNT_INCOMPLETE`)".

    Design: Corner/validations/monitor_close_with_incomplete_counts_rejected
    """
    world = setup_pharmacy(protocol_number="P-VAL-11", kit_numbers=("K-IC1", "K-IC2"),
                           pharmacist_license="L-VAL-11")
    visit = setup_started_visit(world)
    resp = api_client.close_monitor_visit(
        visit["id"], {"counts": [{"kit_id": world["kits"][0]["id"], "physical_units": 10}]},
        MONITOR)
    validate_error(resp, ApiErrorId.ERR_COUNT_INCOMPLETE.value, expected_status=422)
    assert get_success_data(api_client.get_monitor_visit(visit["id"], SPONSOR))["status"] == "IN_PROGRESS"


def test_monitor_close_with_empty_counts_reconciles_clean():
    """PRD §3.9: "the submitted counts must cover every kit at the site in an
    on-hand state ... exactly once (`ERR_COUNT_INCOMPLETE`). ... The visit's
    `discrepancy_count` records how many counted kits carried a nonzero
    adjustment; when every count matches the book, the visit closes
    `CLOSED_RECONCILED`, and with one or more discrepancies it closes
    `CLOSED_DISCREPANCY`."

    Design: Corner/endpoints/monitor_close_with_empty_counts_reconciles_clean
    """
    world = setup_pharmacy(protocol_number="P-EP-1", kit_numbers=(),
                           study_overrides={"max_dose_per_visit_mg": 200})
    # No kits at the site: empty counts are complete coverage.
    visit = setup_started_visit(world)
    resp = api_client.close_monitor_visit(visit["id"], {"counts": []}, MONITOR)
    data = validate_success(resp)
    assert data["status"] == "CLOSED_RECONCILED"
    assert data["discrepancy_count"] == 0


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / kit_accountability_book_balance_vs_physical_count
# ---------------------------------------------------------------------------

def test_book_balance_vs_physical_count_books_signed_discrepancy():
    """PRD §2.10: "Outside any monitor visit, `on_hand_units` is a pure
    projection of the kit's counters — a replay of its dispensing, return,
    destruction, and loss events. At a monitor-visit close, the monitor's
    physical count replaces the projection: the signed delta between the book
    balance and the physical count is booked into `units_lost`, so that after
    the close the two variants agree. Whenever a genuine discrepancy exists, the
    two variants report different on-hand numbers for identical counter data —
    that difference is precisely what the monitor visit exists to capture."

    Design: Difficulty/dual_variant_calc/kit_accountability_book_balance_vs_physical_count
    """
    world = setup_book_vs_physical_scenario()
    kit_id = world["kit"]["id"]
    before = get_kit(kit_id)
    assert before["on_hand_units"] == 10, "projection: 10 - 4 + 4 - 0 - 0"
    closed = get_success_data(api_client.close_monitor_visit(
        world["visit"]["id"], {"counts": [{"kit_id": kit_id, "physical_units": 9}]}, MONITOR))
    assert closed["status"] == "CLOSED_DISCREPANCY"
    assert closed["discrepancy_count"] == 1
    after = get_kit(kit_id)
    assert after["units_lost"] == 1, "book 10 minus physical 9 books +1 (missing)"
    assert after["on_hand_units"] == 9, "after close the physical variant is authoritative"


def test_verified_returned_dispensing_reconciled_at_close():
    """PRD §3.9: "Either way, every dispensing record at the site in `RETURNED`
    whose drug return is `VERIFIED` advances to the terminal `RECONCILED`, and
    both closed visit states are terminal."

    Design: Difficulty/dual_variant_calc/kit_accountability_book_balance_vs_physical_count
    """
    world = setup_book_vs_physical_scenario()
    get_success_data(api_client.close_monitor_visit(
        world["visit"]["id"],
        {"counts": [{"kit_id": world["kit"]["id"], "physical_units": 9}]}, MONITOR))
    record = get_success_data(api_client.get_dispensing_record(world["record"]["id"], SPONSOR))
    assert record["status"] == "RECONCILED"
