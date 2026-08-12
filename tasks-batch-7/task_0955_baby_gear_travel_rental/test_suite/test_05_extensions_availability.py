"""Extensions, optimistic concurrency on extension create, and the
forward-looking availability readout with cleaning-buffer semantics."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    approve_extension,
    create_catalog_item,
    create_customer,
    create_extension,
    create_quoted_reservation,
    create_unit,
    confirm_reservation,
    get_availability,
    get_extension,
    get_reservation,
    get_reservation_version,
    make_customer_headers,
    setup_confirmed_reservation,
    validate_error,
    validate_success,
)


def _ops():
    return TEST_USERS["ops_admin_headers"]


class TestExtensionApproveRequiresUnitFree:
    def test_extension_window_conflict_rejected(self, api):
        """PRD 3.7: "Approval requires the reservation to be `CONFIRMED` or
        `DELIVERED` — anything else is `ERR_INVALID_STATE` — and an
        availability sweep: for every allocated unit, no other reservation's
        committed interval, cleaning buffer included, may overlap the extension
        window running from the current `end_date` to the
        `requested_end_date`; a collision is rejected with
        `ERR_EXTENSION_WINDOW_CONFLICT`."

        res1 [06-10, 06-13) and res2 [06-14, 06-17) share the single unit
        (res2 starts exactly at res1's buffered end, which half-open semantics
        allows); extending res1 to 06-15 collides with res2 and is rejected.

        Design: Difficulty/cross_entity_state_dependency/extension_approve_requires_unit_free
        """
        customer = create_customer()
        catalog = create_catalog_item()
        create_unit(catalog["id"])
        res1 = create_quoted_reservation(
            customer["id"],
            lines=[{"catalog_item_id": catalog["id"]}],
            start_date="2026-06-10",
            end_date="2026-06-13",
        )
        confirm_reservation(res1["id"], customer["id"])
        res2 = create_quoted_reservation(
            customer["id"],
            lines=[{"catalog_item_id": catalog["id"]}],
            delivery_address="22 Nutmeg Rd",
            start_date="2026-06-14",
            end_date="2026-06-17",
        )
        confirm_reservation(res2["id"], customer["id"])
        ext = create_extension(res1["id"], customer["id"], "2026-06-15")
        res = api.approve_extension(ext["id"], _ops())
        validate_error(res, "ERR_EXTENSION_WINDOW_CONFLICT", expected_status=409)
        assert get_extension(ext["id"])["status"] == "PENDING"
        assert get_reservation(res1["id"])["end_date"] == "2026-06-13"
        assert get_reservation(res2["id"])["status"] == "CONFIRMED"

    def test_extension_approved_when_window_free(self, api):
        """PRD 3.7: "On approval the extension charge is computed per allocated
        line against the `unit_rate_cents` snapshot: the first two extension
        days are billed per day at the unit rate times 1.20, rounded half-up,
        and every day from the third onward at the unit rate times 1.50,
        rounded half-up, and the line charges are summed into the request's
        `extension_charge_cents`."
        PRD 3.7: "The reservation then absorbs the extension: `end_date` moves
        to `requested_end_date`, `extension_days` and `extension_charge_cents`
        accumulate the new values, and the reservation's `version` bumps."

        A 2-day extension over a free window: per-line charge
        round_half_up(3000 x 1.20) x 2 = 7200.

        Design: Difficulty/cross_entity_state_dependency/extension_approve_requires_unit_free
        """
        ctx = setup_confirmed_reservation()
        reservation = ctx["reservation"]
        customer = ctx["customer"]
        ext = create_extension(reservation["id"], customer["id"], "2026-06-15")
        approved = approve_extension(ext["id"])
        assert approved["status"] == "APPROVED"
        assert approved["extension_charge_cents"] == 7200
        after = get_reservation(reservation["id"])
        assert after["end_date"] == "2026-06-15"
        assert after["extension_days"] == 2
        assert after["extension_charge_cents"] == 7200


class TestUnitBufferBlocksAdjacentBooking:
    def test_window_inside_cleaning_buffer_has_zero_availability(self, api):
        """PRD 3.4: "The committed interval runs from the reservation's
        `start_date` midnight UTC to its `end_date` midnight UTC plus the
        catalog item's `cleaning_turnaround_hours`; overlap is half-open, so a
        follow-up rental may begin exactly at the buffered end of a prior
        commitment."

        A confirmed rental [06-10, 06-13) with a 24h turnaround buffers the
        unit until 06-14T00:00Z; a window starting 06-13 overlaps the buffer,
        so available_count is 0.

        Design: Difficulty/resource_temporal_overlap/unit_buffer_blocks_adjacent_booking
        """
        ctx = setup_confirmed_reservation()
        catalog = ctx["catalog"]
        count = get_availability(catalog["id"], "2026-06-13", "2026-06-16")
        assert count == 0, "window inside the cleaning buffer must see 0 units"

    def test_window_starting_at_buffered_end_is_allowed(self, api):
        """PRD 3.4: "overlap is half-open, so a follow-up rental may begin
        exactly at the buffered end of a prior commitment."
        PRD 3.4: "The same filter and ranking power the forward-looking
        availability readout on the catalog, which answers a window query with
        the catalog item id, the queried `start_date` and `end_date`, and the
        `available_count` of eligible units."

        The window [06-14, 06-17) starts exactly at the buffered end
        06-14T00:00Z of the [06-10, 06-13) + 24h commitment, so the unit counts
        again: available_count is 1.

        Design: Difficulty/resource_temporal_overlap/unit_buffer_blocks_adjacent_booking
        """
        ctx = setup_confirmed_reservation()
        catalog = ctx["catalog"]
        count = get_availability(catalog["id"], "2026-06-14", "2026-06-17")
        assert count == 1, "adjacency at the buffered end must be allowed"


class TestStateBeatsTemporalOnExtensionCreate:
    def test_extension_create_on_cancelled_reservation_reports_state(self, api):
        """PRD 2.8: "When several checks could reject the same request, they
        are evaluated in a fixed order, and the first failing check determines
        the response."
        PRD 2.8: "State-machine preconditions — the transition must be legal
        from the current state, terminal states are locked, ... — else
        `ERR_INVALID_STATE` (409)."

        State (check 6) precedes temporal overlap (check 9): an extension
        created against a terminally CANCELLED reservation — whose window would
        also collide with a follow-up booking on the released unit — surfaces
        ERR_INVALID_STATE, not ERR_EXTENSION_WINDOW_CONFLICT.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_extension_create
        """
        customer = create_customer()
        catalog = create_catalog_item()
        create_unit(catalog["id"])
        res1 = create_quoted_reservation(
            customer["id"],
            lines=[{"catalog_item_id": catalog["id"]}],
            start_date="2026-06-10",
            end_date="2026-06-13",
        )
        confirm_reservation(res1["id"], customer["id"])
        cancelled = validate_success(
            api.cancel_reservation(
                res1["id"], make_customer_headers(customer["id"])
            ),
            200,
        )
        res2 = create_quoted_reservation(
            customer["id"],
            lines=[{"catalog_item_id": catalog["id"]}],
            delivery_address="11 Holly Ave",
            start_date="2026-06-14",
            end_date="2026-06-17",
        )
        confirm_reservation(res2["id"], customer["id"])
        res = api.create_extension_request(
            res1["id"],
            {
                "requested_end_date": "2026-06-15",
                "expected_reservation_version": cancelled["version"],
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_extension_create_rejection_creates_no_request(self, api):
        """PRD 2.8: "State-machine preconditions — the transition must be legal
        from the current state, terminal states are locked, a stop can only
        complete on a `DISPATCHED` route, settlement requires a `RETURNED`
        reservation, claim approval requires a `RETURNED` line and reservation,
        a route can only complete once every stop is terminal, a recall can
        only close when no unit of the recalled item remains `QUARANTINED`, and
        a cleaning ticket can only be opened for a unit that is
        `AWAITING_CLEANING` or `QUARANTINED` with no other `OPEN` ticket — else
        `ERR_INVALID_STATE` (409)."

        The rejected creation is atomic: the CANCELLED reservation keeps its
        state and version, and no extension request exists for it afterwards.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_extension_create
        """
        customer = create_customer()
        catalog = create_catalog_item()
        create_unit(catalog["id"])
        res1 = create_quoted_reservation(
            customer["id"],
            lines=[{"catalog_item_id": catalog["id"]}],
            start_date="2026-06-10",
            end_date="2026-06-13",
        )
        confirm_reservation(res1["id"], customer["id"])
        cancelled = validate_success(
            api.cancel_reservation(
                res1["id"], make_customer_headers(customer["id"])
            ),
            200,
        )
        res = api.create_extension_request(
            res1["id"],
            {
                "requested_end_date": "2026-06-15",
                "expected_reservation_version": cancelled["version"],
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
        after = get_reservation(res1["id"])
        assert after["status"] == "CANCELLED"
        assert after["version"] == cancelled["version"]
        extensions = validate_success(
            api.list_reservation_extensions(res1["id"], _ops()), 200
        )
        assert extensions == []


def test_extension_supersedes_pending_request(api):
    """PRD 3.7: "Creation supersedes any prior `PENDING` extension, moving it
    to `SUPERSEDED`, and bumps the reservation's `version` by one."

    Creating a second extension while one is PENDING flips the first to
    SUPERSEDED; only the newest stays PENDING.

    Design: Corner/state_machines/extension_supersedes_pending_request
    """
    ctx = setup_confirmed_reservation()
    reservation = ctx["reservation"]
    customer = ctx["customer"]
    ext1 = create_extension(reservation["id"], customer["id"], "2026-06-15")
    ext2 = create_extension(reservation["id"], customer["id"], "2026-06-16")
    assert get_extension(ext1["id"])["status"] == "SUPERSEDED"
    assert ext2["status"] == "PENDING"


def test_occ_extension_stale_version_returns_412(api):
    """PRD 3.7: "A customer whose trip runs long files an extension request
    naming a `requested_end_date` strictly after the reservation's current
    `end_date`, carrying `expected_reservation_version` under the OCC contract
    — a stale view is refused with `ERR_STALE_VERSION`, because a newly created
    extension legitimately supersedes a prior `PENDING` one and a writer
    holding an outdated view must not supersede blindly."

    Extension creation bumps the reservation's version; a second create
    carrying the pre-first-create version is rejected 412.

    Design: Corner/cross_cutting_layers/occ_extension_stale_version_returns_412
    """
    ctx = setup_confirmed_reservation()
    reservation = ctx["reservation"]
    customer = ctx["customer"]
    observed_version = get_reservation_version(reservation["id"])
    first = api.create_extension_request(
        reservation["id"],
        {
            "requested_end_date": "2026-06-15",
            "expected_reservation_version": observed_version,
        },
        make_customer_headers(customer["id"]),
    )
    ext1 = validate_success(first, 201)
    assert ext1["status"] == "PENDING"
    second = api.create_extension_request(
        reservation["id"],
        {
            "requested_end_date": "2026-06-16",
            "expected_reservation_version": observed_version,
        },
        make_customer_headers(customer["id"]),
    )
    validate_error(second, "ERR_STALE_VERSION", expected_status=412)


def test_availability_excludes_retired_units(api, ops_headers):
    """PRD 3.4: "A unit is eligible for a requested window when it belongs to
    the line's catalog item, when its status is one of `AVAILABLE`, `RESERVED`,
    or `RENTED_OUT` — units in `QUARANTINED`, `AWAITING_CLEANING`,
    `IN_CLEANING`, or `RETIRED` never count — when its `blocked_until` is
    either null or no later than the window's start midnight, and when no other
    reservation in `CONFIRMED` or `DELIVERED` holds a line assigned to that
    unit whose committed interval overlaps the request."

    With two units and one retired, availability over any window is 1.

    Design: Corner/calculations/availability_excludes_retired_units
    """
    catalog = create_catalog_item()
    unit1 = create_unit(catalog["id"])
    create_unit(catalog["id"], condition_grade="A")
    validate_success(api.retire_inventory_unit(unit1["id"], ops_headers), 200)
    assert get_availability(catalog["id"], "2026-06-10", "2026-06-13") == 1


def test_availability_computed_read_no_bookings(api):
    """PRD 3.4: "The same filter and ranking power the forward-looking
    availability readout on the catalog, which answers a window query with the
    catalog item id, the queried `start_date` and `end_date`, and the
    `available_count` of eligible units."

    With two units and zero bookings, the availability read returns
    available_count 2 for any window.

    Design: Corner/endpoints/availability_computed_read_no_bookings
    """
    catalog = create_catalog_item()
    create_unit(catalog["id"])
    create_unit(catalog["id"], condition_grade="B")
    assert get_availability(catalog["id"], "2026-06-10", "2026-06-13") == 2
