"""Interval contention and conserved quantities.

Two families of rules live here.

The first is *interval contention*: two resources whose intervals may touch but
may never share an interior point. Spectrum coordination contests a sector's
occupied frequency block, where the requester's proposal is first inflated by
its `guard_band_mhz` on each side; the outage calendar contests a tower's
half-open `started_at`/`ended_at` window with no buffer at all. Both are tested
on the accepted touch case and on the refused one-unit overlap.

The second is *conserved quantities*: a forward write followed by its
compensating write must return every roll-up to exactly the value it held
before, with no residue and no double subtraction. Bandwidth in Mbps is
conserved across a capacity reservation and its release; money in cents is
conserved across a service-level credit's application and its reversal.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_capacity_hold,
    assert_interference_coordination,
    assert_outage_credit,
    assert_outage_event,
    assert_sector_ledger_invariants,
    assert_version_advanced_by,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    CREDIT_APPROVER_HEADERS,
    CREDIT_APPROVER_USER_ID,
    CREDIT_PREPARER_USER_ID,
    activate_sector,
    close_outage,
    create_outage,
    create_sector,
    create_tower,
    get_capacity_hold,
    get_outage,
    get_sector,
    get_serviceability_request,
    get_subscriber,
    reserve_bandwidth,
    set_clock,
    setup_active_plant,
    setup_applied_credit,
    setup_held_reservation,
    setup_prepared_credit,
    setup_qualified_request,
)

# --------------------------------------------------------------------------
# Spectrum geometry shared by the guard-band tests.
#
# Every licence in play spans 3550.0-3650.0 MHz with `max_eirp_dbm` 47.0, so the
# proposal below sits well inside the licence envelope and the only test that can
# fail is the guard-band disjointness test.
#
# Proposal: centre 3580.0, width 10.0 -> block 3575.0-3585.0, which a
# `guard_band_mhz` of 2.0 inflates to 3573.0-3587.0.
#   touching neighbour   3592.0/10.0 -> occupied 3587.0-3597.0 (edges meet at 3587.0)
#   overlapping neighbour 3591.0/10.0 -> occupied 3586.0-3596.0 (1 MHz of overlap)
# --------------------------------------------------------------------------

PROPOSAL_CENTER_MHZ = 3580.0
PROPOSAL_WIDTH_MHZ = 10.0
PROPOSAL_EIRP_DBM = 42.0
GUARD_BAND_MHZ = 2.0

TOUCHING_NEIGHBOUR_CENTER_MHZ = 3592.0
OVERLAPPING_NEIGHBOUR_CENTER_MHZ = 3591.0
NEIGHBOUR_WIDTH_MHZ = 10.0


def _coordination_payload(requesting_sector_id, neighbor_sector_id, guard_band_mhz=GUARD_BAND_MHZ):
    return {
        "requesting_sector_id": requesting_sector_id,
        "neighbor_sector_id": neighbor_sector_id,
        "proposed_channel_center_mhz": PROPOSAL_CENTER_MHZ,
        "proposed_channel_width_mhz": PROPOSAL_WIDTH_MHZ,
        "proposed_eirp_dbm": PROPOSAL_EIRP_DBM,
        "guard_band_mhz": guard_band_mhz,
        "effective_from": "2026-09-01T00:00:00Z",
    }


def _setup_guard_band_neighbours():
    """Two ACTIVE towers, each with accepted transport and a clock-effective licence.

    Returns a dict with:
      "local"       — the requesting plant, its sector on azimuth 90.0.
      "touching"    — an ACTIVE sector on the second tower, azimuth 135.0, whose
                      occupied block starts exactly where the inflated proposal ends.
      "overlapping" — an ACTIVE sector on the second tower, azimuth 135.0, whose
                      occupied block starts one MHz lower, so it truly overlaps.
      "away"        — the same overlapping block on azimuth 150.0, a circular
                      separation of exactly 60 degrees from the requester.
    """
    local = setup_active_plant()
    neighbor = setup_active_plant(
        tower_overrides={"latitude": 41.31, "longitude": -104.71},
        sector_overrides={
            "azimuth_deg": 135.0,
            "channel_center_mhz": TOUCHING_NEIGHBOUR_CENTER_MHZ,
            "channel_width_mhz": NEIGHBOUR_WIDTH_MHZ,
        },
    )
    overlapping = create_sector(
        neighbor["tower"]["id"],
        neighbor["license"]["id"],
        azimuth_deg=135.0,
        channel_center_mhz=OVERLAPPING_NEIGHBOUR_CENTER_MHZ,
        channel_width_mhz=NEIGHBOUR_WIDTH_MHZ,
    )
    overlapping = activate_sector(overlapping["id"])
    away = create_sector(
        neighbor["tower"]["id"],
        neighbor["license"]["id"],
        azimuth_deg=150.0,
        channel_center_mhz=OVERLAPPING_NEIGHBOUR_CENTER_MHZ,
        channel_width_mhz=NEIGHBOUR_WIDTH_MHZ,
    )
    away = activate_sector(away["id"])
    return {
        "local": local,
        "neighbor": neighbor,
        "touching": neighbor["sector"],
        "overlapping": overlapping,
        "away": away,
    }


class TestGuardBandInflatedChannelOverlap:
    """The requester's block, inflated by its guard band, against the neighbour's."""

    def test_inflated_proposal_touching_neighbour_lower_edge_is_accepted(
        self, api, network_engineer
    ):
        """PRD §3.4: "Concretely, either the inflated proposed upper edge must be
        strictly below the neighbour's `lower_edge_mhz`, or the inflated proposed
        lower edge must be strictly above the neighbour's `upper_edge_mhz`. Because
        both comparisons are strict, blocks whose edges touch exactly are accepted.
        Failure is refused with `ERR_CHANNEL_OVERLAP_GUARD_BAND`."
        PRD §3.4: "A newly opened coordination sits in `REQUESTED` `status` with
        `round_number` at 1 and `decision_note`, `decided_by_user_id` and
        `last_response_at` all absent."

        Design: Difficulty/resource_temporal_overlap/guard_band_inflated_channel_may_touch_but_not_overlap_neighbour
        """
        plant = _setup_guard_band_neighbours()
        requester = plant["local"]["sector"]
        neighbour = plant["touching"]

        assert neighbour["lower_edge_mhz"] == 3587.0, (
            "the touching neighbour must occupy 3587.0-3597.0 MHz, got "
            f"{neighbour['lower_edge_mhz']}-{neighbour['upper_edge_mhz']}"
        )

        response = api.create_coordination(
            _coordination_payload(requester["id"], neighbour["id"]), network_engineer
        )
        coordination = validate_success(response, 201)
        assert_interference_coordination(coordination)

        assert coordination["status"] == "REQUESTED", (
            "an inflated proposal whose upper edge 3587.0 only touches the neighbour's "
            f"lower edge 3587.0 must be accepted, got status {coordination['status']!r}"
        )
        assert coordination["round_number"] == 1, (
            f"a newly opened coordination sits at round_number 1, got {coordination['round_number']}"
        )
        assert coordination["guard_band_mhz"] == pytest.approx(GUARD_BAND_MHZ, abs=0.001)
        assert coordination["requesting_sector_id"] == requester["id"]
        assert coordination["neighbor_sector_id"] == neighbour["id"]

    def test_inflated_proposal_overlapping_neighbour_by_one_mhz_is_refused(
        self, api, network_engineer
    ):
        """PRD §3.4: "Concretely, either the inflated proposed upper edge must be
        strictly below the neighbour's `lower_edge_mhz`, or the inflated proposed
        lower edge must be strictly above the neighbour's `upper_edge_mhz`. Because
        both comparisons are strict, blocks whose edges touch exactly are accepted.
        Failure is refused with `ERR_CHANNEL_OVERLAP_GUARD_BAND`."

        Design: Difficulty/resource_temporal_overlap/guard_band_inflated_channel_may_touch_but_not_overlap_neighbour
        """
        plant = _setup_guard_band_neighbours()
        requester = plant["local"]["sector"]
        neighbour = plant["overlapping"]

        assert neighbour["lower_edge_mhz"] == 3586.0, (
            "the overlapping neighbour must occupy 3586.0-3596.0 MHz, got "
            f"{neighbour['lower_edge_mhz']}-{neighbour['upper_edge_mhz']}"
        )

        response = api.create_coordination(
            _coordination_payload(requester["id"], neighbour["id"]), network_engineer
        )
        validate_error(response, ApiErrorId.ERR_CHANNEL_OVERLAP_GUARD_BAND, 422)

    def test_refused_guard_band_proposal_creates_no_coordination_and_leaves_sectors_alone(
        self, api, network_engineer
    ):
        """PRD §3.4: "Concretely, either the inflated proposed upper edge must be
        strictly below the neighbour's `lower_edge_mhz`, or the inflated proposed
        lower edge must be strictly above the neighbour's `upper_edge_mhz`. Because
        both comparisons are strict, blocks whose edges touch exactly are accepted.
        Failure is refused with `ERR_CHANNEL_OVERLAP_GUARD_BAND`."
        PRD §2.3: "the global coordination listing filters on `requesting_sector_id`,
        `neighbor_sector_id`, and `status`"

        Design: Difficulty/resource_temporal_overlap/guard_band_inflated_channel_may_touch_but_not_overlap_neighbour
        """
        plant = _setup_guard_band_neighbours()
        requester = plant["local"]["sector"]
        neighbour = plant["overlapping"]

        response = api.create_coordination(
            _coordination_payload(requester["id"], neighbour["id"]), network_engineer
        )
        validate_error(response, ApiErrorId.ERR_CHANNEL_OVERLAP_GUARD_BAND, 422)

        rows, meta = validate_paginated(
            api.list_coordinations(
                network_engineer, params={"neighbor_sector_id": neighbour["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            "a proposal refused on the guard-band test must not leave a coordination "
            f"row behind, got total_count {meta['total_count']}"
        )
        assert rows == [], f"expected no coordination rows for the neighbour, got {rows}"

        requester_after = get_sector(requester["id"])
        assert requester_after["channel_center_mhz"] == requester["channel_center_mhz"], (
            "a refused proposal must not move the requesting sector's channel"
        )
        assert requester_after["upper_edge_mhz"] == requester["upper_edge_mhz"], (
            "a refused proposal must not move the requesting sector's upper edge"
        )
        neighbour_after = get_sector(neighbour["id"])
        assert neighbour_after["lower_edge_mhz"] == 3586.0, (
            "the neighbour keeps the block the test was decided against"
        )

    def test_overlapping_block_is_accepted_when_beams_are_sixty_degrees_apart(
        self, api, network_engineer
    ):
        """PRD §3.4: "Take the two sectors' `azimuth_deg` values, form the absolute
        difference, and if that difference exceeds 180 degrees subtract it from 360
        to get the short way round the compass. This circular separation is compared
        against a minimum of 60 degrees."
        PRD §3.4: "When the circular separation is **60 degrees or more** the beams
        are considered to be pointing away from each other and no spectrum
        disjointness is required at all — the proposal passes this test regardless
        of channel."

        Design: Difficulty/resource_temporal_overlap/guard_band_inflated_channel_may_touch_but_not_overlap_neighbour
        """
        plant = _setup_guard_band_neighbours()
        requester = plant["local"]["sector"]
        away = plant["away"]

        assert requester["azimuth_deg"] == pytest.approx(90.0, abs=0.05)
        assert away["azimuth_deg"] == pytest.approx(150.0, abs=0.05)
        assert away["lower_edge_mhz"] == 3586.0, (
            "the off-boresight neighbour occupies the same overlapping block, so only "
            "the beam geometry can decide the outcome"
        )

        response = api.create_coordination(
            _coordination_payload(requester["id"], away["id"]), network_engineer
        )
        coordination = validate_success(response, 201)
        assert coordination["status"] == "REQUESTED", (
            "a circular separation of exactly 60 degrees requires no spectrum "
            f"disjointness at all, got status {coordination['status']!r}"
        )

    def test_uninflated_proposal_clear_of_the_neighbour_is_accepted(
        self, api, network_engineer
    ):
        """PRD §3.4: "When the circular separation is **strictly less than** 60
        degrees, the requester's proposed block inflated by `guard_band_mhz` on each
        side must be disjoint from the neighbour's occupied block."
        PRD §3.4: "Concretely, either the inflated proposed upper edge must be
        strictly below the neighbour's `lower_edge_mhz`, or the inflated proposed
        lower edge must be strictly above the neighbour's `upper_edge_mhz`. Because
        both comparisons are strict, blocks whose edges touch exactly are accepted.
        Failure is refused with `ERR_CHANNEL_OVERLAP_GUARD_BAND`."

        Design: Difficulty/resource_temporal_overlap/guard_band_inflated_channel_may_touch_but_not_overlap_neighbour
        """
        plant = _setup_guard_band_neighbours()
        requester = plant["local"]["sector"]
        neighbour = plant["overlapping"]

        # The bare proposal occupies 3575.0-3585.0, strictly below the neighbour's
        # 3586.0 lower edge; only the 2.0 MHz guard band pushed it into collision.
        response = api.create_coordination(
            _coordination_payload(requester["id"], neighbour["id"], guard_band_mhz=0.0),
            network_engineer,
        )
        coordination = validate_success(response, 201)
        assert coordination["status"] == "REQUESTED", (
            "an uninflated proposed upper edge of 3585.0 lies strictly below the "
            f"neighbour's lower edge 3586.0, got status {coordination['status']!r}"
        )
        assert coordination["guard_band_mhz"] == pytest.approx(0.0, abs=0.001)


# --------------------------------------------------------------------------
# The outage calendar of one tower.
#
# The reference closed window is 2026-08-05T00:00:00Z (inclusive) to
# 2026-08-06T04:00:00Z (exclusive): 28 hours, so `duration_minutes` 1680. Its
# cause is WEATHER_WIND with a `peak_wind_mph` of 41.0, below the 58.0 exclusion
# threshold, so it is a chargeable outage rather than force majeure.
# --------------------------------------------------------------------------

CLOSED_WINDOW_START = "2026-08-05T00:00:00Z"
CLOSED_WINDOW_END = "2026-08-06T04:00:00Z"
CLOSED_WINDOW_MINUTES = 1680


def _setup_outage_calendar():
    """A tower carrying exactly one CLOSED outage over the reference window.

    Returns {"tower", "closed"}. The clock is moved to 2026-08-20T00:00:00Z so
    every instant the tests name lies in the past.
    """
    tower = create_tower()
    set_clock("2026-08-20T00:00:00Z")
    outage = create_outage(
        tower["id"], cause="WEATHER_WIND", started_at=CLOSED_WINDOW_START
    )
    closed = close_outage(outage["id"], ended_at=CLOSED_WINDOW_END, peak_wind_mph=41.0)
    return {"tower": tower, "closed": closed}


class TestOutageWindowsOnOneTower:
    """A tower's outage calendar: abutting windows are legal, sharing a minute is not."""

    def test_reference_window_closes_with_its_duration_and_exclusion_flag(self):
        """PRD §3.9: "Closure stores `ended_at` and `peak_wind_mph`, computes
        `duration_minutes` as the whole minutes between the two instants with any
        fractional minute discarded, and fixes `sla_excluded`."
        PRD §3.9: "A `WEATHER_WIND` outage is excluded when `peak_wind_mph` — treated
        as 0.0 when it was never supplied — is at or above 58.0 miles per hour."

        Design: Difficulty/resource_temporal_overlap/outage_windows_may_abut_but_not_share_a_minute_on_one_tower
        """
        calendar = _setup_outage_calendar()
        closed = calendar["closed"]
        assert_outage_event(closed)

        assert closed["status"] == "CLOSED", (
            f"the reference outage must be CLOSED, got {closed['status']!r}"
        )
        assert closed["duration_minutes"] == CLOSED_WINDOW_MINUTES, (
            "2026-08-05T00:00:00Z to 2026-08-06T04:00:00Z is 1680 whole minutes, got "
            f"{closed['duration_minutes']}"
        )
        assert closed["sla_excluded"] is False, (
            "a peak_wind_mph of 41.0 is below the 58.0 exclusion threshold, so the "
            "outage is not service-level excluded"
        )

    def test_window_starting_exactly_where_the_closed_one_ends_is_accepted(
        self, api, network_engineer
    ):
        """PRD §3.9: "And the closed interval, taken as inclusive of `started_at` and
        exclusive of `ended_at`, must share no minute with any other already-`CLOSED`
        outage on the same tower, else `ERR_OUTAGE_WINDOW_OVERLAP`; because the
        interval is half-open, two outages that merely abut — one ending at exactly
        the instant the next begins — are accepted, while any genuine overlap of even
        one minute is refused."

        Design: Difficulty/resource_temporal_overlap/outage_windows_may_abut_but_not_share_a_minute_on_one_tower
        """
        calendar = _setup_outage_calendar()
        abutting = create_outage(
            calendar["tower"]["id"], cause="POWER", started_at=CLOSED_WINDOW_END
        )

        response = api.close_outage_event(
            abutting["id"], {"ended_at": "2026-08-06T05:00:00Z"}, network_engineer
        )
        closed = validate_success(response, 200)

        assert closed["status"] == "CLOSED", (
            "a window opening at exactly the instant the previous one ended merely "
            f"abuts it and must close successfully, got status {closed['status']!r}"
        )
        assert closed["duration_minutes"] == 60, (
            f"2026-08-06T04:00:00Z to 2026-08-06T05:00:00Z is 60 whole minutes, got {closed['duration_minutes']}"
        )
        assert closed["started_at"] == calendar["closed"]["ended_at"], (
            "the accepted window starts at exactly the instant the earlier one ended, "
            f"got {closed['started_at']!r} against {calendar['closed']['ended_at']!r}"
        )

    def test_window_ending_exactly_where_the_closed_one_starts_is_accepted(
        self, api, network_engineer
    ):
        """PRD §3.9: "And the closed interval, taken as inclusive of `started_at` and
        exclusive of `ended_at`, must share no minute with any other already-`CLOSED`
        outage on the same tower, else `ERR_OUTAGE_WINDOW_OVERLAP`; because the
        interval is half-open, two outages that merely abut — one ending at exactly
        the instant the next begins — are accepted, while any genuine overlap of even
        one minute is refused."

        Design: Difficulty/resource_temporal_overlap/outage_windows_may_abut_but_not_share_a_minute_on_one_tower
        """
        calendar = _setup_outage_calendar()
        earlier = create_outage(
            calendar["tower"]["id"], cause="POWER", started_at="2026-08-04T23:00:00Z"
        )

        response = api.close_outage_event(
            earlier["id"], {"ended_at": CLOSED_WINDOW_START}, network_engineer
        )
        closed = validate_success(response, 200)

        assert closed["status"] == "CLOSED", (
            "a window ending at exactly the instant the CLOSED one begins shares no "
            f"minute with it and must close successfully, got {closed['status']!r}"
        )
        assert closed["duration_minutes"] == 60, (
            f"2026-08-04T23:00:00Z to 2026-08-05T00:00:00Z is 60 whole minutes, got {closed['duration_minutes']}"
        )

    def test_window_inside_the_closed_one_is_refused_and_stays_open(
        self, api, network_engineer
    ):
        """PRD §3.9: "And the closed interval, taken as inclusive of `started_at` and
        exclusive of `ended_at`, must share no minute with any other already-`CLOSED`
        outage on the same tower, else `ERR_OUTAGE_WINDOW_OVERLAP`; because the
        interval is half-open, two outages that merely abut — one ending at exactly
        the instant the next begins — are accepted, while any genuine overlap of even
        one minute is refused."
        PRD §3.9: "The outage opens in `OPEN` `status` with `ended_at`,
        `peak_wind_mph` and `duration_minutes` all absent, `sla_excluded` false and
        `total_credited_cents` zero."

        Design: Difficulty/resource_temporal_overlap/outage_windows_may_abut_but_not_share_a_minute_on_one_tower
        """
        calendar = _setup_outage_calendar()
        inside = create_outage(
            calendar["tower"]["id"], cause="EQUIPMENT", started_at="2026-08-05T12:00:00Z"
        )

        response = api.close_outage_event(
            inside["id"], {"ended_at": "2026-08-05T13:00:00Z"}, network_engineer
        )
        validate_error(response, ApiErrorId.ERR_OUTAGE_WINDOW_OVERLAP, 409)

        after = get_outage(inside["id"])
        assert after["status"] == "OPEN", (
            f"a refused closure leaves the outage OPEN, got {after['status']!r}"
        )
        assert after.get("ended_at") is None, (
            f"a refused closure stores no ended_at, got {after.get('ended_at')!r}"
        )
        assert after.get("duration_minutes") is None, (
            f"a refused closure computes no duration_minutes, got {after.get('duration_minutes')!r}"
        )

    def test_window_sharing_exactly_one_minute_with_the_closed_one_is_refused(
        self, api, network_engineer
    ):
        """PRD §3.9: "And the closed interval, taken as inclusive of `started_at` and
        exclusive of `ended_at`, must share no minute with any other already-`CLOSED`
        outage on the same tower, else `ERR_OUTAGE_WINDOW_OVERLAP`; because the
        interval is half-open, two outages that merely abut — one ending at exactly
        the instant the next begins — are accepted, while any genuine overlap of even
        one minute is refused."

        Design: Difficulty/resource_temporal_overlap/outage_windows_may_abut_but_not_share_a_minute_on_one_tower
        """
        calendar = _setup_outage_calendar()
        # 03:59 to 04:00 is the single minute this window shares with the CLOSED one.
        one_minute_over = create_outage(
            calendar["tower"]["id"], cause="POWER", started_at="2026-08-06T03:59:00Z"
        )

        response = api.close_outage_event(
            one_minute_over["id"], {"ended_at": "2026-08-06T05:00:00Z"}, network_engineer
        )
        validate_error(response, ApiErrorId.ERR_OUTAGE_WINDOW_OVERLAP, 409)

        after = get_outage(one_minute_over["id"])
        assert after["status"] == "OPEN", (
            "an overlap of even one minute is refused and the outage stays OPEN, got "
            f"{after['status']!r}"
        )

    def test_open_outage_never_blocks_another_window_on_the_same_tower(
        self, api, network_engineer
    ):
        """PRD §3.9: "And the closed interval, taken as inclusive of `started_at` and
        exclusive of `ended_at`, must share no minute with any other already-`CLOSED`
        outage on the same tower, else `ERR_OUTAGE_WINDOW_OVERLAP`; because the
        interval is half-open, two outages that merely abut — one ending at exactly
        the instant the next begins — are accepted, while any genuine overlap of even
        one minute is refused."

        Design: Difficulty/resource_temporal_overlap/outage_windows_may_abut_but_not_share_a_minute_on_one_tower
        """
        calendar = _setup_outage_calendar()
        still_open = create_outage(
            calendar["tower"]["id"], cause="EQUIPMENT", started_at="2026-08-10T00:00:00Z"
        )
        overlapping_the_open_one = create_outage(
            calendar["tower"]["id"], cause="POWER", started_at="2026-08-10T01:00:00Z"
        )

        response = api.close_outage_event(
            overlapping_the_open_one["id"],
            {"ended_at": "2026-08-10T02:00:00Z"},
            network_engineer,
        )
        closed = validate_success(response, 200)

        assert closed["status"] == "CLOSED", (
            "only an already-CLOSED outage contests the calendar, so a window inside "
            f"an OPEN one closes successfully, got {closed['status']!r}"
        )
        assert closed["duration_minutes"] == 60, (
            f"expected 60 whole minutes, got {closed['duration_minutes']}"
        )
        assert get_outage(still_open["id"])["status"] == "OPEN", (
            "the outage that was never closed is untouched by the other closure"
        )

    def test_identical_window_on_a_second_tower_is_accepted(self, api, network_engineer):
        """PRD §3.9: "And the closed interval, taken as inclusive of `started_at` and
        exclusive of `ended_at`, must share no minute with any other already-`CLOSED`
        outage on the same tower, else `ERR_OUTAGE_WINDOW_OVERLAP`; because the
        interval is half-open, two outages that merely abut — one ending at exactly
        the instant the next begins — are accepted, while any genuine overlap of even
        one minute is refused."

        Design: Difficulty/resource_temporal_overlap/outage_windows_may_abut_but_not_share_a_minute_on_one_tower
        """
        calendar = _setup_outage_calendar()
        second_tower = create_tower()
        twin = create_outage(
            second_tower["id"], cause="POWER", started_at=CLOSED_WINDOW_START
        )

        response = api.close_outage_event(
            twin["id"], {"ended_at": CLOSED_WINDOW_END}, network_engineer
        )
        closed = validate_success(response, 200)

        assert closed["status"] == "CLOSED", (
            "the disjointness test is scoped to one tower, so the identical window on "
            f"another tower closes successfully, got {closed['status']!r}"
        )
        assert closed["duration_minutes"] == CLOSED_WINDOW_MINUTES, (
            f"expected 1680 whole minutes, got {closed['duration_minutes']}"
        )
        assert closed["tower_id"] == second_tower["id"]


# --------------------------------------------------------------------------
# Bandwidth conservation across a reservation and its release.
#
# The reference sector has `capacity_mbps` 25 and `max_oversubscription_ratio`
# 8.0, so its ceiling is floor(25 * 8.0) = 200 Mbps. The reference plan is 50
# Mbps downstream, which is what a reservation for it is worth.
#   opening ledger  sold 0  held 0   committed 0   ratio 0.000  remaining 200
#   with the hold   sold 0  held 50  committed 50  ratio 2.000  remaining 150
#   after release   sold 0  held 0   committed 0   ratio 0.000  remaining 200
# --------------------------------------------------------------------------

SECTOR_CEILING_MBPS = 200
RESERVATION_MBPS = 50


def _hold_payload(request_id, expected_sector_version):
    return {
        "serviceability_request_id": request_id,
        "expected_sector_version": expected_sector_version,
    }


class TestHoldThenReleaseConservesSectorBandwidth:
    """`sold_mbps` plus `held_mbps` returns to its opening value after a release."""

    def test_release_returns_every_ledger_roll_up_to_its_opening_value(
        self, api, sales_agent, capacity_planner
    ):
        """PRD §3.3: "`committed_mbps` is simply `sold_mbps` plus `held_mbps`, and
        `oversubscription_ratio` is `committed_mbps` divided by `capacity_mbps`,
        rounded half up to three decimal places."
        PRD §3.6: "Its side effects on the sector are immediate: `held_mbps` rises by
        the reserved amount, `committed_mbps`, `oversubscription_ratio`,
        `remaining_allowance_mbps` and `capacity_posture` are all recomputed, and the
        sector's `version` is incremented — which invalidates any other caller's
        `expected_sector_version` and forces them to re-read."
        PRD §3.6: "The sector's `held_mbps` falls by the reservation's `held_mbps`,
        `committed_mbps`, `oversubscription_ratio`, `remaining_allowance_mbps` and
        `capacity_posture` are recomputed, the sector's `version` is incremented, and
        the enquiry the reservation was protecting, if still `QUALIFIED`, moves to
        `EXPIRED` with its `qualified_sector_id` cleared."

        Design: Difficulty/compensating_invariant/hold_then_release_conserves_sector_sold_plus_held_bandwidth
        """
        scenario = setup_qualified_request()
        sector_id = scenario["sector"]["id"]

        opening = get_sector(sector_id)
        assert_sector_ledger_invariants(opening)
        assert (opening["sold_mbps"], opening["held_mbps"], opening["committed_mbps"]) == (0, 0, 0), (
            "the sector must open empty, got sold/held/committed "
            f"{opening['sold_mbps']}/{opening['held_mbps']}/{opening['committed_mbps']}"
        )
        assert opening["remaining_allowance_mbps"] == SECTOR_CEILING_MBPS, (
            "floor(25 * 8.0) less nothing committed is 200 Mbps, got "
            f"{opening['remaining_allowance_mbps']}"
        )

        held = validate_success(
            api.create_capacity_hold(
                _hold_payload(scenario["request"]["id"], opening["version"]), sales_agent
            ),
            201,
        )
        assert_capacity_hold(held)
        assert held["held_mbps"] == RESERVATION_MBPS, (
            f"the reservation is plan-sized at 50 Mbps, got {held['held_mbps']}"
        )

        during = get_sector(sector_id)
        assert_sector_ledger_invariants(during)
        assert during["sold_mbps"] == 0, (
            f"a reservation sells nothing, got sold_mbps {during['sold_mbps']}"
        )
        assert during["held_mbps"] == RESERVATION_MBPS, (
            f"held_mbps rises by the reserved 50 Mbps, got {during['held_mbps']}"
        )
        assert during["committed_mbps"] == RESERVATION_MBPS, (
            f"committed_mbps is 0 sold plus 50 held, got {during['committed_mbps']}"
        )
        assert during["oversubscription_ratio"] == pytest.approx(2.000, abs=0.0005), (
            f"50 committed over 25 capacity is 2.000, got {during['oversubscription_ratio']}"
        )
        assert during["remaining_allowance_mbps"] == SECTOR_CEILING_MBPS - RESERVATION_MBPS, (
            f"200 less 50 committed is 150 Mbps, got {during['remaining_allowance_mbps']}"
        )

        released = validate_success(
            api.release_capacity_hold(held["id"], {"note": "Household went elsewhere"}, capacity_planner),
            200,
        )
        assert released["status"] == "RELEASED"

        after = get_sector(sector_id)
        assert_sector_ledger_invariants(after)
        assert after["sold_mbps"] == opening["sold_mbps"], (
            f"sold_mbps must be back at {opening['sold_mbps']}, got {after['sold_mbps']}"
        )
        assert after["held_mbps"] == opening["held_mbps"], (
            "held_mbps falls by the reservation's 50 Mbps and must be back at "
            f"{opening['held_mbps']}, got {after['held_mbps']}"
        )
        assert after["committed_mbps"] == opening["committed_mbps"], (
            "sold plus held is conserved across the release, expected "
            f"{opening['committed_mbps']}, got {after['committed_mbps']}"
        )
        assert after["oversubscription_ratio"] == pytest.approx(0.000, abs=0.0005), (
            f"0 committed over 25 capacity is 0.000, got {after['oversubscription_ratio']}"
        )
        assert after["remaining_allowance_mbps"] == SECTOR_CEILING_MBPS, (
            "the full 200 Mbps of allowance is handed back, got "
            f"{after['remaining_allowance_mbps']}"
        )
        assert after["capacity_posture"] == opening["capacity_posture"] == "OPEN", (
            "an empty ledger sits below the watch line, so the posture returns to OPEN, "
            f"got {after['capacity_posture']!r}"
        )

    def test_released_reservation_keeps_its_amount_and_expires_its_enquiry(
        self, api, capacity_planner
    ):
        """PRD §3.6: "A manual release moves the reservation `HELD → RELEASED` with a
        `release_reason` of `MANUAL`."
        PRD §3.6: "The sector's `held_mbps` falls by the reservation's `held_mbps`,
        `committed_mbps`, `oversubscription_ratio`, `remaining_allowance_mbps` and
        `capacity_posture` are recomputed, the sector's `version` is incremented, and
        the enquiry the reservation was protecting, if still `QUALIFIED`, moves to
        `EXPIRED` with its `qualified_sector_id` cleared."

        Design: Difficulty/compensating_invariant/hold_then_release_conserves_sector_sold_plus_held_bandwidth
        """
        scenario = setup_held_reservation()

        response = api.release_capacity_hold(scenario["hold"]["id"], {}, capacity_planner)
        released = validate_success(response, 200)
        assert_capacity_hold(released)

        assert released["status"] == "RELEASED", (
            f"a manual release lands on RELEASED, got {released['status']!r}"
        )
        assert released["release_reason"] == "MANUAL", (
            f"a manual release records a release_reason of MANUAL, got {released['release_reason']!r}"
        )
        assert released["held_mbps"] == RESERVATION_MBPS, (
            "the reservation keeps the amount it was worth — the sector's held_mbps "
            f"falls *by* it rather than the record being zeroed, got {released['held_mbps']}"
        )

        request_after = get_serviceability_request(scenario["request"]["id"])
        assert request_after["status"] == "EXPIRED", (
            "the enquiry the reservation was protecting was still QUALIFIED, so it "
            f"moves to EXPIRED, got {request_after['status']!r}"
        )
        assert request_after.get("qualified_sector_id") is None, (
            "the expired enquiry has its qualified_sector_id cleared, got "
            f"{request_after.get('qualified_sector_id')!r}"
        )

        sector_after = get_sector(scenario["sector"]["id"])
        assert sector_after["held_mbps"] == 0, (
            f"the sector holds nothing once the only reservation is gone, got {sector_after['held_mbps']}"
        )

    def test_sector_version_advances_once_for_the_hold_and_once_for_the_release(
        self, api, sales_agent, capacity_planner
    ):
        """PRD §2.5: "A recomputation of a derived field counts as a mutation: when a
        capacity reservation raises a sector's `held_mbps`, the sector's `version`
        increments even though no client wrote to the sector directly."
        PRD §3.6: "Its side effects on the sector are immediate: `held_mbps` rises by
        the reserved amount, `committed_mbps`, `oversubscription_ratio`,
        `remaining_allowance_mbps` and `capacity_posture` are all recomputed, and the
        sector's `version` is incremented — which invalidates any other caller's
        `expected_sector_version` and forces them to re-read."

        Design: Difficulty/compensating_invariant/hold_then_release_conserves_sector_sold_plus_held_bandwidth
        """
        scenario = setup_qualified_request()
        sector_id = scenario["sector"]["id"]

        before_hold = get_sector(sector_id)
        held = validate_success(
            api.create_capacity_hold(
                _hold_payload(scenario["request"]["id"], before_hold["version"]), sales_agent
            ),
            201,
        )

        after_hold = get_sector(sector_id)
        assert_version_advanced_by(before_hold, after_hold, 1, entity="sector")

        validate_success(api.release_capacity_hold(held["id"], {}, capacity_planner), 200)

        after_release = get_sector(sector_id)
        assert_version_advanced_by(after_hold, after_release, 1, entity="sector")
        assert after_release["committed_mbps"] == before_hold["committed_mbps"], (
            "the ledger is conserved even though the version has moved twice, expected "
            f"{before_hold['committed_mbps']}, got {after_release['committed_mbps']}"
        )

    def test_releasing_one_of_two_reservations_subtracts_only_that_amount(
        self, api, capacity_planner
    ):
        """PRD §3.3: "`held_mbps` is the sum of `held_mbps` over every reservation on
        this sector whose `status` is `HELD`. Reservations in `CONSUMED`, `RELEASED` or
        `EXPIRED` status contribute nothing."
        PRD §3.6: "The sector's `held_mbps` falls by the reservation's `held_mbps`,
        `committed_mbps`, `oversubscription_ratio`, `remaining_allowance_mbps` and
        `capacity_posture` are recomputed, the sector's `version` is incremented, and
        the enquiry the reservation was protecting, if still `QUALIFIED`, moves to
        `EXPIRED` with its `qualified_sector_id` cleared."

        Design: Difficulty/compensating_invariant/hold_then_release_conserves_sector_sold_plus_held_bandwidth
        """
        scenario = setup_active_plant()
        first = reserve_bandwidth(scenario, RESERVATION_MBPS)
        second = reserve_bandwidth(scenario, RESERVATION_MBPS)

        loaded = get_sector(scenario["sector"]["id"])
        assert_sector_ledger_invariants(loaded)
        assert loaded["held_mbps"] == 2 * RESERVATION_MBPS, (
            f"two 50 Mbps reservations hold 100 Mbps between them, got {loaded['held_mbps']}"
        )
        assert loaded["oversubscription_ratio"] == pytest.approx(4.000, abs=0.0005), (
            f"100 committed over 25 capacity is 4.000, got {loaded['oversubscription_ratio']}"
        )
        assert loaded["capacity_posture"] == "WATCH", (
            "4.000 sits exactly on the watch line of half the 8.0 ceiling and the "
            f"comparison is inclusive, got {loaded['capacity_posture']!r}"
        )

        validate_success(
            api.release_capacity_hold(second["hold"]["id"], {}, capacity_planner), 200
        )

        after = get_sector(scenario["sector"]["id"])
        assert_sector_ledger_invariants(after)
        assert after["held_mbps"] == RESERVATION_MBPS, (
            "only the released reservation's 50 Mbps comes back — the surviving one is "
            f"still held, got {after['held_mbps']}"
        )
        assert after["committed_mbps"] == RESERVATION_MBPS, (
            f"committed_mbps is the one surviving reservation, got {after['committed_mbps']}"
        )
        assert after["oversubscription_ratio"] == pytest.approx(2.000, abs=0.0005), (
            f"50 committed over 25 capacity is 2.000, got {after['oversubscription_ratio']}"
        )
        assert after["remaining_allowance_mbps"] == SECTOR_CEILING_MBPS - RESERVATION_MBPS, (
            f"200 less 50 committed is 150 Mbps, got {after['remaining_allowance_mbps']}"
        )
        assert after["capacity_posture"] == "OPEN", (
            "2.000 is below the watch line of 4.0, so the posture recomputes to OPEN, "
            f"got {after['capacity_posture']!r}"
        )
        assert get_capacity_hold(first["hold"]["id"])["status"] == "HELD", (
            "releasing one reservation must not disturb the other"
        )


# --------------------------------------------------------------------------
# Money conservation across a credit's application and its reversal.
#
# The reference household is on the 6999-cent plan with an `sla_uptime_pct` of
# 99.5 and an `sla_credit_method` of SLA_SHORTFALL. Its cycle opens on
# 2026-08-01 and its tower carries one CLOSED, non-excluded outage of 1680
# minutes, so:
#   cycle_outage_minutes  1680
#   measured_uptime_pct   100 * (43200 - 1680) / 43200 = 96.111
#   shortfall_pct         99.5 - 96.111 = 3.389
#   gross                 6999 * 3.389 / 100 * 10 = 2371.9611 -> 2372 cents
#   monthly cap           floor(0.5 * 6999) = 3499, which does not bite
#   credit_cents          2372 - 0 prior = 2372
# --------------------------------------------------------------------------

CREDIT_CENTS = 2372
CREDIT_OUTAGE_MINUTES = 1680


def _setup_pending_credit():
    """An ACTIVE household, one 1680-minute chargeable outage, one PENDING credit."""
    return setup_prepared_credit(
        minutes=CREDIT_OUTAGE_MINUTES,
        cause="WEATHER_WIND",
        started_at="2026-08-05T00:00:00Z",
        peak_wind_mph=41.0,
    )


class TestCreditReversalConservesMoney:
    """Applying then reversing a credit returns both roll-ups to the cent."""

    def test_reversal_returns_both_roll_ups_to_their_pre_application_values(self, api):
        """PRD §3.9: "On success it moves `APPLIED → REVERSED`, which is terminal, and
        both roll-ups are decreased by `credit_cents`. Because `credit_cents` is fixed
        at preparation and is **never** recomputed afterwards — not by a later cycle
        close, not by a further outage, not by a plan change — a reversal returns
        `credit_balance_cents` and `total_credited_cents` to exactly the values they
        held before the application, to the cent."

        Design: Difficulty/compensating_invariant/credit_reversal_conserves_subscriber_balance_and_outage_credited_total
        """
        scenario = _setup_pending_credit()
        credit = scenario["credit"]

        before_subscriber = get_subscriber(scenario["subscriber"]["id"])
        before_outage = get_outage(scenario["outage"]["id"])
        assert before_subscriber["credit_balance_cents"] == 0, (
            "a merely PENDING credit is not money yet, got credit_balance_cents "
            f"{before_subscriber['credit_balance_cents']}"
        )
        assert before_outage["total_credited_cents"] == 0, (
            "a merely PENDING credit is not money yet, got total_credited_cents "
            f"{before_outage['total_credited_cents']}"
        )

        applied = validate_success(
            api.apply_outage_credit(credit["id"], {}, CREDIT_APPROVER_HEADERS), 200
        )
        assert applied["status"] == "APPLIED"

        reversed_credit = validate_success(
            api.reverse_outage_credit(
                credit["id"], {"reversal_reason": "Posted against the wrong cycle"},
                CREDIT_APPROVER_HEADERS,
            ),
            200,
        )
        assert_outage_credit(reversed_credit)
        assert reversed_credit["status"] == "REVERSED", (
            f"a reversal lands on REVERSED, got {reversed_credit['status']!r}"
        )
        assert reversed_credit["credit_cents"] == CREDIT_CENTS, (
            "credit_cents is fixed at preparation and is never recomputed, expected "
            f"{CREDIT_CENTS}, got {reversed_credit['credit_cents']}"
        )

        after_subscriber = get_subscriber(scenario["subscriber"]["id"])
        after_outage = get_outage(scenario["outage"]["id"])
        assert after_subscriber["credit_balance_cents"] == before_subscriber["credit_balance_cents"], (
            "the account's credit_balance_cents returns to exactly its pre-application "
            f"value of {before_subscriber['credit_balance_cents']}, got "
            f"{after_subscriber['credit_balance_cents']}"
        )
        assert after_outage["total_credited_cents"] == before_outage["total_credited_cents"], (
            "the outage's total_credited_cents returns to exactly its pre-application "
            f"value of {before_outage['total_credited_cents']}, got "
            f"{after_outage['total_credited_cents']}"
        )

    def test_application_raises_both_roll_ups_by_exactly_the_credit_amount(self, api):
        """PRD §3.9: "On success the credit moves `PENDING → APPLIED`,
        `approved_by_user_id` is stamped, the account's `credit_balance_cents` rises by
        `credit_cents`, and the outage's `total_credited_cents` rises by the same
        amount."

        Design: Difficulty/compensating_invariant/credit_reversal_conserves_subscriber_balance_and_outage_credited_total
        """
        scenario = _setup_pending_credit()

        response = api.apply_outage_credit(
            scenario["credit"]["id"], {"note": "Storm of 5 August"}, CREDIT_APPROVER_HEADERS
        )
        applied = validate_success(response, 200)
        assert_outage_credit(applied)

        assert applied["status"] == "APPLIED", (
            f"a released credit sits in APPLIED, got {applied['status']!r}"
        )
        assert applied["approved_by_user_id"] == CREDIT_APPROVER_USER_ID, (
            "approved_by_user_id is stamped with the releasing approver, expected "
            f"{CREDIT_APPROVER_USER_ID!r}, got {applied.get('approved_by_user_id')!r}"
        )
        assert applied["prepared_by_user_id"] == CREDIT_PREPARER_USER_ID, (
            "the preparer's identifier is untouched by the application, expected "
            f"{CREDIT_PREPARER_USER_ID!r}, got {applied['prepared_by_user_id']!r}"
        )

        subscriber_after = get_subscriber(scenario["subscriber"]["id"])
        outage_after = get_outage(scenario["outage"]["id"])
        assert subscriber_after["credit_balance_cents"] == CREDIT_CENTS, (
            f"credit_balance_cents rises by the credit's {CREDIT_CENTS} cents, got "
            f"{subscriber_after['credit_balance_cents']}"
        )
        assert outage_after["total_credited_cents"] == CREDIT_CENTS, (
            f"total_credited_cents rises by the same {CREDIT_CENTS} cents, got "
            f"{outage_after['total_credited_cents']}"
        )

    def test_both_roll_ups_exclude_the_reversed_row(self, api, billing_admin):
        """PRD §3.9: "`credit_balance_cents` is at all times the sum of `credit_cents`
        over the account's credits in `APPLIED` status, and an outage's
        `total_credited_cents` is the sum over its own `APPLIED` credits; both therefore
        exclude `PENDING`, `DENIED` and `REVERSED` rows."

        Design: Difficulty/compensating_invariant/credit_reversal_conserves_subscriber_balance_and_outage_credited_total
        """
        scenario = setup_applied_credit(
            minutes=CREDIT_OUTAGE_MINUTES,
            cause="WEATHER_WIND",
            started_at="2026-08-05T00:00:00Z",
            peak_wind_mph=41.0,
        )
        assert scenario["subscriber"]["credit_balance_cents"] == CREDIT_CENTS
        assert scenario["outage"]["total_credited_cents"] == CREDIT_CENTS

        response = api.reverse_outage_credit(
            scenario["credit"]["id"],
            {"reversal_reason": "Duplicate of an earlier goodwill credit"},
            CREDIT_APPROVER_HEADERS,
        )
        reversed_credit = validate_success(response, 200)

        assert reversed_credit["reversal_reason"] == "Duplicate of an earlier goodwill credit", (
            "the mandatory reversal_reason is recorded on the credit, got "
            f"{reversed_credit.get('reversal_reason')!r}"
        )

        subscriber_after = get_subscriber(scenario["subscriber"]["id"])
        outage_after = get_outage(scenario["outage"]["id"])
        assert subscriber_after["credit_balance_cents"] == 0, (
            "the only credit on the account is now REVERSED, which the roll-up "
            f"excludes, so credit_balance_cents is zero, got {subscriber_after['credit_balance_cents']}"
        )
        assert outage_after["total_credited_cents"] == 0, (
            "the only credit against the outage is now REVERSED, which the roll-up "
            f"excludes, so total_credited_cents is zero, got {outage_after['total_credited_cents']}"
        )
        stored = validate_success(
            api.get_outage_credit(scenario["credit"]["id"], billing_admin), 200
        )
        assert stored["credit_cents"] == CREDIT_CENTS, (
            "the excluded row still carries the amount it was prepared for, expected "
            f"{CREDIT_CENTS}, got {stored['credit_cents']}"
        )

    def test_credit_amount_and_its_derivation_survive_application_and_reversal(self, api):
        """PRD §3.9: "Because `credit_cents` is fixed at preparation and is **never**
        recomputed afterwards — not by a later cycle close, not by a further outage,
        not by a plan change — a reversal returns `credit_balance_cents` and
        `total_credited_cents` to exactly the values they held before the application,
        to the cent."
        PRD §3.9: "`measured_uptime_pct` is 100 multiplied by the shortfall-free share
        of the month — that is, the standard monthly allowance of 43200 minutes less
        `cycle_outage_minutes`, divided by 43200 — rounded half up to three decimal
        places."

        Design: Difficulty/compensating_invariant/credit_reversal_conserves_subscriber_balance_and_outage_credited_total
        """
        scenario = _setup_pending_credit()
        prepared = scenario["credit"]

        assert prepared["status"] == "PENDING", (
            f"a chargeable outage with a shortfall yields a PENDING credit, got {prepared['status']!r}"
        )
        assert prepared["method"] == "SLA_SHORTFALL", (
            f"method is copied from the plan's sla_credit_method, got {prepared['method']!r}"
        )
        assert prepared["cycle_outage_minutes"] == CREDIT_OUTAGE_MINUTES, (
            f"the cycle's creditable minutes are the outage's 1680, got {prepared['cycle_outage_minutes']}"
        )
        assert prepared["measured_uptime_pct"] == pytest.approx(96.111, abs=0.0005), (
            "100 * (43200 - 1680) / 43200 rounds half up to 96.111, got "
            f"{prepared['measured_uptime_pct']}"
        )
        assert prepared["shortfall_pct"] == pytest.approx(3.389, abs=0.0005), (
            f"99.5 less 96.111 is 3.389, got {prepared['shortfall_pct']}"
        )
        assert prepared["prior_cycle_credited_cents"] == 0, (
            "no other credit exists for this cycle, got "
            f"{prepared['prior_cycle_credited_cents']}"
        )
        assert prepared["credit_cents"] == CREDIT_CENTS, (
            f"6999 * 3.389 / 100 * 10 rounds half up to {CREDIT_CENTS} cents, got {prepared['credit_cents']}"
        )

        applied = validate_success(
            api.apply_outage_credit(prepared["id"], {}, CREDIT_APPROVER_HEADERS), 200
        )
        reversed_credit = validate_success(
            api.reverse_outage_credit(
                prepared["id"], {"reversal_reason": "Reissued on the correct account"},
                CREDIT_APPROVER_HEADERS,
            ),
            200,
        )

        for stage_name, stage in (("APPLIED", applied), ("REVERSED", reversed_credit)):
            assert stage["credit_cents"] == prepared["credit_cents"], (
                f"credit_cents must not be recomputed at the {stage_name} stage, "
                f"expected {prepared['credit_cents']}, got {stage['credit_cents']}"
            )
            assert stage["cycle_outage_minutes"] == prepared["cycle_outage_minutes"], (
                f"cycle_outage_minutes must not be recomputed at the {stage_name} stage"
            )
            assert stage["measured_uptime_pct"] == pytest.approx(
                prepared["measured_uptime_pct"], abs=0.0005
            ), f"measured_uptime_pct must not be recomputed at the {stage_name} stage"
            assert stage["shortfall_pct"] == pytest.approx(
                prepared["shortfall_pct"], abs=0.0005
            ), f"shortfall_pct must not be recomputed at the {stage_name} stage"
            assert stage["prior_cycle_credited_cents"] == prepared["prior_cycle_credited_cents"], (
                f"prior_cycle_credited_cents must not be recomputed at the {stage_name} stage"
            )
