"""The two interval rules pull in opposite directions: the county slot is a closed
interval widened by half an hour, the lot window is half-open with no buffer."""

from test_helpers import (
    CLOCK_SETUP,
    COUNTY_PRIMARY,
    COUNTY_SECONDARY,
    TEST_USERS,
    add_lot,
    add_lot_payload,
    api_client,
    create_auction_event_payload,
    create_event,
    disclosed_asset,
    list_events,
    list_lots,
    read_event,
    read_listing,
    set_clock,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["auction_ops_headers"]

ANCHOR_START = "2026-09-15T17:00:00Z"
ANCHOR_END = "2026-09-15T19:00:00Z"
CANDIDATE_AT_BUFFER_EDGE = "2026-09-15T19:30:00Z"
CANDIDATE_ONE_SECOND_LATER = "2026-09-15T19:30:01Z"
CANDIDATE_END = "2026-09-15T21:00:00Z"


def _anchor_event():
    """One scheduled Alameda session running 17:00 to 19:00."""
    set_clock(CLOCK_SETUP)
    return create_event(
        title="Alameda Anchor Session",
        county_code=COUNTY_PRIMARY,
        starts_at=ANCHOR_START,
        ends_at=ANCHOR_END,
    )


class TestCountySlotBuffer:
    def test_candidate_starting_exactly_thirty_minutes_after_is_rejected(self):
        """Both comparisons in the county-slot test are inclusive, so a session
        beginning exactly at the buffer edge still collides with the anchor.

        PRD: "Both comparisons are inclusive, which makes the rule adjacency-hostile:
        a candidate starting exactly thirty minutes after another event's end still
        conflicts, and clearance requires a gap strictly greater than thirty minutes on
        whichever side is adjacent."

        Design: Difficulty/resource_temporal_overlap/county_slot_buffer_is_inclusive_at_thirty_minutes
        """
        anchor = _anchor_event()

        response = api_client.create_auction_event(
            create_auction_event_payload(
                title="Alameda Buffer Edge Session",
                county_code=COUNTY_PRIMARY,
                starts_at=CANDIDATE_AT_BUFFER_EDGE,
                ends_at=CANDIDATE_END,
            ),
            OPS,
        )
        validate_error(response, "ERR_COUNTY_SLOT_CONFLICT", 409)

        # The rejected candidate was never written and the anchor was not touched.
        assert len(list_events(county_code=COUNTY_PRIMARY)) == 1
        assert read_event(anchor["id"])["version"] == anchor["version"]

    def test_candidate_one_second_past_the_buffer_is_accepted(self):
        """A gap strictly greater than thirty minutes clears the rule, so the same
        window shifted one second later is created.

        PRD: "A candidate event conflicts with another event of the same county whose
        `event_status` is `SCHEDULED`, `LIVE` or `POSTPONED` when the candidate's start
        is at or before that other event's end plus the buffer **and** that other
        event's start is at or before the candidate's end plus the buffer."

        Design: Difficulty/resource_temporal_overlap/county_slot_buffer_is_inclusive_at_thirty_minutes
        """
        _anchor_event()

        response = api_client.create_auction_event(
            create_auction_event_payload(
                title="Alameda Cleared Session",
                county_code=COUNTY_PRIMARY,
                starts_at=CANDIDATE_ONE_SECOND_LATER,
                ends_at=CANDIDATE_END,
            ),
            OPS,
        )
        created = validate_success(response, expected_status=201)

        assert created["event_status"] == "SCHEDULED"
        assert created["county_code"] == COUNTY_PRIMARY
        assert len(list_events(county_code=COUNTY_PRIMARY)) == 2

    def test_the_slot_is_keyed_on_the_county(self):
        """The contended resource is the pair of a county and a window, so the window
        rejected in Alameda is accepted in the neighbouring county.

        PRD: "The contended resource is the pair of a `county_code` and an event window
        running from `starts_at` to `ends_at`, widened symmetrically by a buffer of half
        an hour on each side — thirty minutes of settling time between sessions in the
        same jurisdiction."

        Design: Difficulty/resource_temporal_overlap/county_slot_buffer_is_inclusive_at_thirty_minutes
        """
        _anchor_event()
        validate_error(
            api_client.create_auction_event(
                create_auction_event_payload(
                    title="Alameda Buffer Edge Session",
                    county_code=COUNTY_PRIMARY,
                    starts_at=CANDIDATE_AT_BUFFER_EDGE,
                    ends_at=CANDIDATE_END,
                ),
                OPS,
            ),
            "ERR_COUNTY_SLOT_CONFLICT",
            409,
        )

        neighbour = create_event(
            title="Contra Costa Same Window Session",
            county_code=COUNTY_SECONDARY,
            starts_at=CANDIDATE_AT_BUFFER_EDGE,
            ends_at=CANDIDATE_END,
        )

        assert neighbour["county_code"] == COUNTY_SECONDARY
        assert neighbour["event_status"] == "SCHEDULED"
        assert len(list_events(county_code=COUNTY_PRIMARY)) == 1
        assert len(list_events(county_code=COUNTY_SECONDARY)) == 1


def _asset_on_two_events():
    """One asset, an Alameda session running 17:00 to 18:00 that already carries it
    as a lot, and a Contra Costa session running 18:00 to 19:00 that does not."""
    set_clock(CLOCK_SETUP)
    bundle = disclosed_asset(
        org_name="Bay Ridge Holdings",
        seller_type="PRIVATE_SELLER",
        contact_email="owner@bayridge.example",
        settlement_account_ref="ACH-BAY-8",
        street_address="5 Bay Ridge Ln",
        estimated_value_cents=31000000,
    )
    event_a = create_event(
        title="Alameda Early Session",
        county_code=COUNTY_PRIMARY,
        starts_at="2026-09-15T17:00:00Z",
        ends_at="2026-09-15T18:00:00Z",
    )
    event_b = create_event(
        title="Contra Costa Late Session",
        county_code=COUNTY_SECONDARY,
        starts_at="2026-09-15T18:00:00Z",
        ends_at="2026-09-15T19:00:00Z",
    )
    lot_a = add_lot(
        event_a["id"],
        bundle.listing_id,
        lot_number=1,
        lot_window_start_at="2026-09-15T17:00:00Z",
        lot_window_end_at="2026-09-15T18:00:00Z",
    )
    return bundle, event_a, event_b, lot_a


class TestLotWindowHalfOpen:
    def test_touching_windows_for_the_same_asset_are_accepted(self):
        """A second lot for the same asset may begin at exactly the instant the first
        lot's window ends, even though the two lots sit on different events.

        PRD: "Both comparisons are strict, making the rule adjacency-friendly: a
        candidate beginning at exactly the instant another lot's window ends does not
        conflict, so back-to-back windows for the same asset in two different events
        are legal."

        Design: Difficulty/resource_temporal_overlap/same_asset_lot_windows_are_half_open_across_events
        """
        bundle, _event_a, event_b, lot_a = _asset_on_two_events()

        touching = add_lot(
            event_b["id"],
            bundle.listing_id,
            lot_number=1,
            lot_window_start_at="2026-09-15T18:00:00Z",
            lot_window_end_at="2026-09-15T19:00:00Z",
        )

        assert touching["lot_status"] == "PENDING"
        assert touching["lot_window_start_at"].replace(".000Z", "Z") == lot_a[
            "lot_window_end_at"
        ].replace(".000Z", "Z")
        assert len(list_lots(auction_event_id=event_b["id"])) == 1

    def test_genuinely_overlapping_window_for_the_same_asset_is_rejected(self):
        """A window that starts strictly before the touching lot's end conflicts, and
        the conflict is reported as a lot-window collision rather than as a stale
        version or an out-of-event window.

        PRD: "A candidate lot conflicts with another lot of the same asset — across
        all events, not merely within one — whose `lot_status` is `PENDING`, `OPEN`,
        `EXTENDED` or `SUSPENDED` when the candidate's start is strictly before that
        lot's end **and** that lot's start is strictly before the candidate's end."

        Design: Difficulty/resource_temporal_overlap/same_asset_lot_windows_are_half_open_across_events
        """
        bundle, _event_a, event_b, _lot_a = _asset_on_two_events()
        add_lot(
            event_b["id"],
            bundle.listing_id,
            lot_number=1,
            lot_window_start_at="2026-09-15T18:00:00Z",
            lot_window_end_at="2026-09-15T19:00:00Z",
        )

        current_version = read_event(event_b["id"])["version"]
        response = api_client.add_lot(
            event_b["id"],
            add_lot_payload(
                bundle.listing_id,
                current_version,
                lot_number=2,
                lot_window_start_at="2026-09-15T18:30:00Z",
                lot_window_end_at="2026-09-15T19:00:00Z",
            ),
            OPS,
        )
        validate_error(response, "ERR_LOT_WINDOW_CONFLICT", 409)

        assert len(list_lots(auction_event_id=event_b["id"])) == 1
        assert read_event(event_b["id"])["lot_count"] == 1
        assert read_listing(bundle.listing_id)["listing_status"] == "LISTED"
