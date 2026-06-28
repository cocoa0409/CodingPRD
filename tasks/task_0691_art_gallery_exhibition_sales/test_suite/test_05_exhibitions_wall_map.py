"""Exhibitions and the wall map: the open-requires-a-slot boundary, the cancel
cascade to events and RSVPs, run-window overlap for a shared artwork, capacity
and position-uniqueness guards, the wall-slot version OCC check, invalid cancel,
and the filtered wall-slot listing."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    setup_gallery_artist_artwork, setup_exhibition_with_placed_artwork,
    create_gallery, create_artist, create_artwork, create_exhibition,
    place_wall_slot, create_opening_event, create_rsvp, set_clock,
    TEST_USERS,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["gallery_admin_headers"]
SALES = TEST_USERS["sales_associate_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


class TestOpenRequiresSlot:
    def test_open_with_zero_slots_rejected(self, api):
        """PRD §3.3: "A `GalleryAdmin` opens it — moving `PLANNED → OPEN` — only
        when the show is `PLANNED`, at least one slot is occupied, and the clock
        has reached or passed `opens_utc`".

        Design: Difficulty/boundary_precision_check/exhibition_open_requires_at_least_one_slot_empty_set
        """
        gallery, artist, artwork = setup_gallery_artist_artwork(
            artwork_overrides={"list_price_cents": 100_000, "insured_value_cents": 100_000})
        exhibition = create_exhibition(gallery["id"], wall_capacity=2,
                                       opens_utc="2026-04-10T00:00:00Z",
                                       closes_utc="2026-05-10T00:00:00Z")
        set_clock("2026-04-15T00:00:00Z")  # past opens, but zero slots occupied.
        resp = api.open_exhibition(exhibition["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_open_succeeds_after_one_slot_placed(self, api):
        """PRD §3.3: "A `GalleryAdmin` opens it — moving `PLANNED → OPEN` — only
        when the show is `PLANNED`, at least one slot is occupied, and the clock
        has reached or passed `opens_utc`; once open, further placements are still
        allowed up to capacity."

        Design: Difficulty/boundary_precision_check/exhibition_open_requires_at_least_one_slot_empty_set
        """
        gallery, artist, artwork = setup_gallery_artist_artwork(
            artwork_overrides={"list_price_cents": 100_000, "insured_value_cents": 100_000})
        exhibition = create_exhibition(gallery["id"], wall_capacity=2,
                                       opens_utc="2026-04-10T00:00:00Z",
                                       closes_utc="2026-05-10T00:00:00Z")
        set_clock("2026-04-15T00:00:00Z")
        place_wall_slot(exhibition["id"], artwork["id"], 0, exhibition["version"],
                        wall_label="S-1")
        opened = validate_success(api.open_exhibition(exhibition["id"], ADMIN))
        assert opened["status"] == "OPEN", "one occupied slot at/after opens enables open"


class TestCancelCascade:
    def test_cancel_exhibition_cancels_event_and_rsvp(self, api):
        """PRD §3.3: "Alternatively a `GalleryAdmin` cancels it, moving
        `PLANNED → CANCELLED`, which fans out: ... every `OpeningEvent` for the
        show still in `SCHEDULED` status is moved to `CANCELLED`; and every
        `CONFIRMED` or `WAITLISTED` RSVP on those events is moved to `CANCELLED`."

        Design: Difficulty/transitive_cascade/exhibition_cancel_cascade_event_rsvp_depth3
        """
        gallery = create_gallery()
        exhibition = create_exhibition(gallery["id"], wall_capacity=3,
                                       opens_utc="2026-05-01T00:00:00Z",
                                       closes_utc="2026-06-01T00:00:00Z")
        event = create_opening_event(exhibition["id"], capacity=10,
                                     starts_utc="2026-05-01T18:00:00Z",
                                     rsvp_deadline_utc="2026-04-30T00:00:00Z")
        rsvp = create_rsvp(event["id"], "Vi", party_size=2)
        assert rsvp["status"] == "CONFIRMED"
        cancelled = validate_success(api.cancel_exhibition(exhibition["id"], ADMIN))
        assert cancelled["status"] == "CANCELLED", "hop 1: exhibition CANCELLED"
        event_after = get_success_data(api.get_opening_event(event["id"], ADMIN))
        assert event_after["status"] == "CANCELLED", "hop 2: SCHEDULED event CANCELLED"
        rsvp_after = get_success_data(api.get_rsvp(rsvp["id"], ADMIN))
        assert rsvp_after["status"] == "CANCELLED", "hop 3: CONFIRMED RSVP CANCELLED"

    def test_cancel_exhibition_releases_slots(self, api):
        """PRD §3.3: "every `PLACED` wall slot on the show is set `RELEASED` and
        `slots_occupied` drops to 0".

        Design: Difficulty/transitive_cascade/exhibition_cancel_cascade_event_rsvp_depth3
        """
        gallery, artist, artwork, exhibition, wall_slot = \
            setup_exhibition_with_placed_artwork(wall_capacity=2)
        assert get_success_data(
            api.get_exhibition(exhibition["id"], ADMIN))["slots_occupied"] == 1
        validate_success(api.cancel_exhibition(exhibition["id"], ADMIN))
        ex_after = get_success_data(api.get_exhibition(exhibition["id"], ADMIN))
        assert ex_after["slots_occupied"] == 0, "all placed slots released on cancel"
        slot_after = get_success_data(api.get_wall_slot(wall_slot["id"], ADMIN))
        assert slot_after["status"] == "RELEASED"


class TestExhibitionRunWindowOverlap:
    def test_overlapping_run_window_for_shared_artwork_rejected(self, api):
        """PRD §3.3: "A placement is rejected with `ERR_SCHEDULE_CONFLICT` when the
        same artwork is already `PLACED` in another non-terminal exhibition — one
        whose status is `PLANNED` or `OPEN` — whose run window intersects this
        show's run window. For exhibitions the overlap test is on closed intervals:
        two shows conflict if their `[opens_utc, closes_utc]` ranges touch at all".

        Design: Difficulty/resource_temporal_overlap/exhibition_run_window_overlap_for_shared_artwork
        """
        gallery, artist, artwork = setup_gallery_artist_artwork(
            artwork_overrides={"list_price_cents": 300_000, "insured_value_cents": 300_000})
        ex_x = create_exhibition(gallery["id"], title="X", wall_capacity=3,
                                 opens_utc="2026-04-10T00:00:00Z",
                                 closes_utc="2026-05-10T00:00:00Z")
        place_wall_slot(ex_x["id"], artwork["id"], 0, ex_x["version"], wall_label="X-1")
        ex_y = create_exhibition(gallery["id"], title="Y", wall_capacity=3,
                                 opens_utc="2026-05-01T00:00:00Z",  # overlaps X's window
                                 closes_utc="2026-06-01T00:00:00Z")
        resp = api.place_wall_slot(
            ex_y["id"],
            f.wall_slot_payload(artwork["id"], 0, ex_y["version"], wall_label="Y-1"),
            REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT.value)

    def test_shared_boundary_instant_counts_as_conflict(self, api):
        """PRD §3.3: "two shows conflict if their `[opens_utc, closes_utc]` ranges
        touch at all, and sharing a single boundary instant counts as a conflict.
        This is stricter than the loan calendar, which treats its boundaries as
        half-open (see §3.7)."

        Design: Difficulty/resource_temporal_overlap/exhibition_run_window_overlap_for_shared_artwork
        """
        gallery, artist, artwork = setup_gallery_artist_artwork(
            artwork_overrides={"list_price_cents": 300_000, "insured_value_cents": 300_000})
        ex_x = create_exhibition(gallery["id"], title="X", wall_capacity=3,
                                 opens_utc="2026-04-10T00:00:00Z",
                                 closes_utc="2026-05-10T00:00:00Z")
        place_wall_slot(ex_x["id"], artwork["id"], 0, ex_x["version"], wall_label="X-1")
        # Y opens exactly at X's close instant: closed intervals share a boundary.
        ex_y = create_exhibition(gallery["id"], title="Y", wall_capacity=3,
                                 opens_utc="2026-05-10T00:00:00Z",
                                 closes_utc="2026-06-01T00:00:00Z")
        resp = api.place_wall_slot(
            ex_y["id"],
            f.wall_slot_payload(artwork["id"], 0, ex_y["version"], wall_label="Y-1"),
            REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT.value)


class TestWallMapGuards:
    def test_cancel_open_exhibition_rejected(self, api):
        """PRD §3.3: "Alternatively a `GalleryAdmin` cancels it, moving
        `PLANNED → CANCELLED`".

        Design: Corner/state_machines/cancel_exhibition_from_open_returns_invalid_state
        """
        gallery, artist, artwork = setup_gallery_artist_artwork(
            artwork_overrides={"list_price_cents": 100_000, "insured_value_cents": 100_000})
        exhibition = create_exhibition(gallery["id"], wall_capacity=2,
                                       opens_utc="2026-04-10T00:00:00Z",
                                       closes_utc="2026-05-10T00:00:00Z")
        place_wall_slot(exhibition["id"], artwork["id"], 0, exhibition["version"],
                        wall_label="O-1")
        set_clock("2026-04-15T00:00:00Z")
        opened = validate_success(api.open_exhibition(exhibition["id"], ADMIN))
        assert opened["status"] == "OPEN"
        resp = api.cancel_exhibition(exhibition["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_placement_beyond_capacity_rejected(self, api):
        """PRD §3.3: "a placement that would push the occupied count past
        `wall_capacity`, or that reuses a `position_index` already taken by a
        `PLACED` slot of the same exhibition, is rejected with
        `ERR_WALL_CAPACITY_EXCEEDED`."

        Design: Corner/validations/wall_capacity_exceeded_rejected
        """
        gallery = create_gallery()
        artist = create_artist(gallery["id"])
        aw1 = create_artwork(gallery["id"], artist["id"],
                             list_price_cents=100_000, insured_value_cents=100_000)
        aw2 = create_artwork(gallery["id"], artist["id"],
                             list_price_cents=100_000, insured_value_cents=100_000)
        exhibition = create_exhibition(gallery["id"], wall_capacity=1,
                                       opens_utc="2026-04-10T00:00:00Z",
                                       closes_utc="2026-05-10T00:00:00Z")
        first = place_wall_slot(exhibition["id"], aw1["id"], 0, exhibition["version"],
                                wall_label="C-1")
        # Re-read exhibition for current version after the placement bumped it.
        ex_now = get_success_data(api.get_exhibition(exhibition["id"], ADMIN))
        resp = api.place_wall_slot(
            exhibition["id"],
            f.wall_slot_payload(aw2["id"], 1, ex_now["version"], wall_label="C-2"),
            REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_WALL_CAPACITY_EXCEEDED.value)

    def test_duplicate_position_index_rejected(self, api):
        """PRD §3.3: "or that reuses a `position_index` already taken by a `PLACED`
        slot of the same exhibition, is rejected with `ERR_WALL_CAPACITY_EXCEEDED`."

        Design: Corner/validations/duplicate_position_index_rejected
        """
        gallery = create_gallery()
        artist = create_artist(gallery["id"])
        aw1 = create_artwork(gallery["id"], artist["id"],
                             list_price_cents=100_000, insured_value_cents=100_000)
        aw2 = create_artwork(gallery["id"], artist["id"],
                             list_price_cents=100_000, insured_value_cents=100_000)
        exhibition = create_exhibition(gallery["id"], wall_capacity=3,
                                       opens_utc="2026-04-10T00:00:00Z",
                                       closes_utc="2026-05-10T00:00:00Z")
        place_wall_slot(exhibition["id"], aw1["id"], 0, exhibition["version"],
                        wall_label="P-0")
        ex_now = get_success_data(api.get_exhibition(exhibition["id"], ADMIN))
        # Same position_index 0 as the placed slot.
        resp = api.place_wall_slot(
            exhibition["id"],
            f.wall_slot_payload(aw2["id"], 0, ex_now["version"], wall_label="P-0dup"),
            REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_WALL_CAPACITY_EXCEEDED.value)

    def test_stale_exhibition_version_on_placement_rejected(self, api):
        """PRD §2.9: "Placing a wall slot on an exhibition requires the field
        `expected_exhibition_version` in the request body, carrying the `version`
        of the target `Exhibition` that the client last observed. If that value
        does not equal the exhibition's current `version`, the placement is
        rejected with `ERR_STALE_VERSION` at HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/occ_wallslot_stale_exhibition_version_excluded
        """
        gallery = create_gallery()
        artist = create_artist(gallery["id"])
        aw1 = create_artwork(gallery["id"], artist["id"],
                             list_price_cents=100_000, insured_value_cents=100_000)
        aw2 = create_artwork(gallery["id"], artist["id"],
                             list_price_cents=100_000, insured_value_cents=100_000)
        exhibition = create_exhibition(gallery["id"], wall_capacity=2,
                                       opens_utc="2026-04-10T00:00:00Z",
                                       closes_utc="2026-05-10T00:00:00Z")
        stale_version = exhibition["version"]
        # First placement consumes the version and bumps it.
        place_wall_slot(exhibition["id"], aw1["id"], 0, stale_version, wall_label="OC-1")
        # Second placement against the stale (pre-bump) version is rejected.
        resp = api.place_wall_slot(
            exhibition["id"],
            f.wall_slot_payload(aw2["id"], 1, stale_version, wall_label="OC-2"),
            REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


class TestWallSlotListing:
    def test_filtered_wall_slot_list_by_artwork(self, api):
        """PRD §2.4: "A child record is tied to its gallery not through a nested URL
        but through a foreign key carried in the request body on creation and
        offered as a filter on its list endpoint."
        PRD §2.3: "Each list response carries `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the envelope".

        Design: Corner/endpoints/wallslot_filtered_list_by_artwork
        """
        gallery, artist, artwork, exhibition, wall_slot = \
            setup_exhibition_with_placed_artwork(wall_capacity=2)
        resp = api.list_wall_slots(ADMIN, params={"artwork_id": artwork["id"]})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1, "exactly one slot for this artwork"
        assert data[0]["id"] == wall_slot["id"], "the filtered slot is returned"
