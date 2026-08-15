"""Destruction booking, witnessing, finalization, facility-window buffer, and
terminal-state lockdown (PRD §2.6, §3.7)."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    setup_pharmacy, setup_returned_kit, setup_returned_kit_for_destruction,
    create_destruction_payload, get_kit,
)
from test_helpers import TEST_USERS, make_pharmacist_headers

SPONSOR = TEST_USERS["sponsor_admin_headers"]


def test_destruction_quantity_must_equal_book_on_hand():
    """PRD §3.7: "The `quantity_destroyed` must equal the kit's current book
    on-hand balance — units received minus units dispensed plus units returned —
    otherwise the booking is rejected with `ERR_QUANTITY_MISMATCH`."

    Design: Corner/validations/destruction_quantity_must_equal_book_on_hand
    """
    world = setup_returned_kit_for_destruction(protocol_number="P-VAL-9",
                                               pharmacist_license="L-VAL-9a",
                                               witness_license="L-VAL-9b")
    kit = world["kit"]
    # Book on-hand is 10 (10 received - 4 dispensed + 4 returned); booking 9 fails.
    resp = api_client.create_destruction_record(
        create_destruction_payload(kit["id"], world["site"]["id"],
                                   world["witness"]["id"], quantity_destroyed=9),
        world["pharmacist_headers"])
    validate_error(resp, ApiErrorId.ERR_QUANTITY_MISMATCH.value, expected_status=422)
    assert get_kit(kit["id"])["status"] == "RETURNED"


def test_finalize_draft_destruction_returns_invalid_state():
    """PRD §3.7: "A `WITNESSED` record finalized by a `Pharmacist` moves the kit
    from `DESTRUCTION_PENDING` to the terminal `DESTROYED`". PRD §2.6: "the
    generic `ERR_INVALID_STATE` covers every other state-precondition failure."

    Design: Corner/errors/finalize_draft_destruction_returns_invalid_state
    """
    world = setup_returned_kit_for_destruction(protocol_number="P-ERR-2",
                                               pharmacist_license="L-ERR-2a",
                                               witness_license="L-ERR-2b")
    kit = world["kit"]
    record = get_success_data(api_client.create_destruction_record(
        create_destruction_payload(kit["id"], world["site"]["id"],
                                   world["witness"]["id"], quantity_destroyed=10),
        world["pharmacist_headers"]))
    assert record["status"] == "DRAFT"
    resp = api_client.finalize_destruction_record(record["id"], world["pharmacist_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    assert get_success_data(api_client.get_destruction_record(record["id"], SPONSOR))["status"] == "DRAFT"
    assert get_kit(kit["id"])["status"] == "DESTRUCTION_PENDING"


def test_destroyed_kit_is_terminal_for_all_actions():
    """PRD §2.6: "Acting on an entity that has already reached a terminal state
    — a `DESTROYED` kit, a `CLOSED` study or site, a `COMPLETED` or `WITHDRAWN`
    subject, a `FINALIZED` or `VOIDED` destruction record, or a closed monitor
    visit — is rejected with `ERR_ALREADY_TERMINAL`." PRD §3.7: "A `WITNESSED`
    record finalized by a `Pharmacist` moves the kit from `DESTRUCTION_PENDING`
    to the terminal `DESTROYED`, sets the kit's `units_destroyed` to the
    record's `quantity_destroyed`, and recomputes `on_hand_units`, which reaches
    zero."

    Design: Corner/state_machines/destroyed_kit_is_terminal_for_all_actions
    """
    world = setup_returned_kit_for_destruction(protocol_number="P-SM-2",
                                               pharmacist_license="L-SM-2a",
                                               witness_license="L-SM-2b")
    kit = world["kit"]
    record = get_success_data(api_client.create_destruction_record(
        create_destruction_payload(kit["id"], world["site"]["id"],
                                   world["witness"]["id"], quantity_destroyed=10),
        world["pharmacist_headers"]))
    get_success_data(api_client.attest_destruction_record(
        record["id"], {}, make_pharmacist_headers(world["witness"]["id"])))
    get_success_data(api_client.finalize_destruction_record(
        record["id"], world["pharmacist_headers"]))
    destroyed = get_kit(kit["id"])
    assert destroyed["status"] == "DESTROYED"
    assert destroyed["units_destroyed"] == 10
    assert destroyed["on_hand_units"] == 0
    resp = api_client.release_kit(kit["id"], world["pharmacist_headers"])
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL.value, expected_status=409)
    assert get_kit(kit["id"])["status"] == "DESTROYED"


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / destruction_window_requires_buffer_between_bookings
# ---------------------------------------------------------------------------

def _world_with_two_returned_kits():
    """Two subjects each dispensed 4 and returned 4; both kits RETURNED with
    book on-hand 10; staff p2 is the designated witness."""
    world = setup_pharmacy(protocol_number="P-OVL-2", kit_numbers=("K-X1", "K-X2"),
                           pharmacist_license="L-OVL-1", extra_licenses=("L-OVL-2",),
                           lot_overrides={"lot_number": "LOT-OVL-2"})
    first = setup_returned_kit(world, subject_number="SUB-D1", quantity=4,
                               kit_numbers=["K-X1", "K-X2"])
    # After the first subject's slot upload the study version advanced; upload
    # the remaining slot for the second subject.
    second = setup_returned_kit(world, subject_number="SUB-D2", quantity=4,
                                kit_numbers=["K-X2"])
    return world, first, second, world["staff"][1]


def test_destruction_window_inside_30_minute_buffer_rejected():
    """PRD §3.7: "Facility windows at a site are treated as closed intervals
    with a turnaround buffer: a booking whose window intersects another
    non-`VOIDED` destruction window at the same site, or that begins within
    thirty minutes after such a window ends, is rejected with
    `ERR_DESTRUCTION_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/destruction_window_requires_buffer_between_bookings
    """
    world, first, second, witness = _world_with_two_returned_kits()
    headers = world["pharmacist_headers"]
    first_record = get_success_data(api_client.create_destruction_record(
        create_destruction_payload(first["kit"]["id"], world["site"]["id"], witness["id"],
                                   quantity_destroyed=10,
                                   window_start="2026-08-20T10:00:00Z",
                                   window_end="2026-08-20T11:00:00Z"),
        headers))
    assert first_record["status"] == "DRAFT"
    # 11:15 begins within thirty minutes after the 11:00 end.
    resp = api_client.create_destruction_record(
        create_destruction_payload(second["kit"]["id"], world["site"]["id"], witness["id"],
                                   quantity_destroyed=10,
                                   window_start="2026-08-20T11:15:00Z",
                                   window_end="2026-08-20T12:00:00Z"),
        headers)
    validate_error(resp, ApiErrorId.ERR_DESTRUCTION_WINDOW_CONFLICT.value, expected_status=409)


def test_destruction_window_at_exactly_end_plus_buffer_accepted():
    """PRD §3.7: "a booking whose window intersects another non-`VOIDED`
    destruction window at the same site, or that begins within thirty minutes
    after such a window ends, is rejected with
    `ERR_DESTRUCTION_WINDOW_CONFLICT`." A start at exactly end + 30 minutes is
    not "within thirty minutes after", so it is accepted; the kit then moves to
    `DESTRUCTION_PENDING` per "On acceptance ... opens the record in `DRAFT`,
    and moves the kit to `DESTRUCTION_PENDING`."

    Design: Difficulty/resource_temporal_overlap/destruction_window_requires_buffer_between_bookings
    """
    world, first, second, witness = _world_with_two_returned_kits()
    headers = world["pharmacist_headers"]
    get_success_data(api_client.create_destruction_record(
        create_destruction_payload(first["kit"]["id"], world["site"]["id"], witness["id"],
                                   quantity_destroyed=10,
                                   window_start="2026-08-20T10:00:00Z",
                                   window_end="2026-08-20T11:00:00Z"),
        headers))
    second_record = get_success_data(api_client.create_destruction_record(
        create_destruction_payload(second["kit"]["id"], world["site"]["id"], witness["id"],
                                   quantity_destroyed=10,
                                   window_start="2026-08-20T11:30:00Z",
                                   window_end="2026-08-20T12:30:00Z"),
        headers))
    assert second_record["status"] == "DRAFT"
    assert get_kit(first["kit"]["id"])["status"] == "DESTRUCTION_PENDING"
    assert get_kit(second["kit"]["id"])["status"] == "DESTRUCTION_PENDING"
