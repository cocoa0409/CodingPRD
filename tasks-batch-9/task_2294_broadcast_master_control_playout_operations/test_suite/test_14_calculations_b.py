"""Calculated figures, part B.

Covers the multiplex-wide live-encoder sweep, the inclusive quality-control
score thresholds, the pinned per-item credit rounding order, the two settlement
bases, the two notification deadline epochs, the capped air-check fault penalty
and the exactness of the makegood round trip.

Every world is built from an empty database through PRD endpoints only, and the
logical clock is the sole source of "now", so all the pinned arithmetic below is
reproducible from the clock's default value.
"""
from test_helpers import (
    assert_feed_window,
    assert_multiplex,
    assert_playlist_item,
    assert_qc_report,
    assert_regulatory_notification,
    assert_spot_count_conservation,
    assert_spot_order,
    factories,
    item_by_sequence,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx

# ---------------------------------------------------------------------------
# The encoder bench: the canonical seven-element day on air on ch1 (12.1) plus
# a sibling subchannel ch2 (12.2) on the SAME multiplex, MUX-A, whose
# live_encoder_units_total is 2. ch2 carries its own two-element ARMED playlist
# so both channels have a NETWORK_JOIN anchor element and the encoder pool is
# the only thing under test.
# ---------------------------------------------------------------------------

_CH1_JOIN_UTC = "2026-08-01T12:20:00Z"
_CH1_BREAKAWAY_UTC = "2026-08-01T12:22:00Z"
_CH1_ANCHOR_SEQ = 4
_CH2_ANCHOR_SEQ = 2


def _setup_encoder_bench():
    """Canonical day on air on ch1, plus an armed anchor playlist on ch2."""
    scn = fx.setup_playlist_scenario()
    sd_asset = fx.setup_qc_passed_asset(
        scn, 100, asset_overrides={"required_resolution_class": "SD_480I"}
    )
    ch2_items = [
        {"sequence_number": 1, "element_kind": "PROGRAM",
         "asset_id": sd_asset["id"],
         "scheduled_start_utc": "2026-08-01T14:00:00Z",
         "scheduled_duration_seconds": 100},
        {"sequence_number": _CH2_ANCHOR_SEQ, "element_kind": "NETWORK_JOIN",
         "scheduled_start_utc": "2026-08-01T14:01:40Z",
         "scheduled_duration_seconds": 100},
    ]
    ch2_playlist = fx.ingest(scn, ch2_items, channel_id=scn["ch2"]["id"],
                            schedule_start_utc="2026-08-01T14:00:00Z",
                            window_duration_seconds=200)
    fx.drive_playlist(scn, ch2_playlist["id"], "VALIDATED")
    fx.drive_playlist(scn, ch2_playlist["id"], "ARMED")
    scn["ch2_playlist"] = ch2_playlist
    return fx.drive_playlist_to_on_air(scn)


def _plan_ch1_pool_window(api, scn, live_encoder_units=2):
    """Plan the ch1 window that claims the whole encoder pool of MUX-A."""
    return api.create_feed_window(
        factories.create_feed_window_payload(
            scn["ch1"]["id"], _CH1_ANCHOR_SEQ, _CH1_JOIN_UTC, _CH1_BREAKAWAY_UTC,
            live_encoder_units=live_encoder_units,
        ),
        scn["mco_headers"],
    )


def test_window_claiming_the_whole_encoder_pool_is_accepted_at_exact_equality(api):
    """Two units against a total of two is a peak exactly equal to the total, so it is admitted.

    PRD §3.7: "The proposed window is refused with `ERR_ENCODER_CAPACITY_EXCEEDED` when the resulting peak would **exceed** `live_encoder_units_total`; **a peak exactly equal to the total is accepted**, and a peak one unit above it is not."

    Design: Corner/calculations/encoder_pool_is_multiplex_wide_with_releases_before_claims
    """
    scn = _setup_encoder_bench()

    window = validate_success(_plan_ch1_pool_window(api, scn), 201)
    assert_feed_window(window)
    assert window["state"] == "PLANNED"
    assert window["live_encoder_units"] == 2

    mux = fx.read_multiplex(scn["multiplex"]["id"], scn["eng_headers"])
    assert_multiplex(mux)
    assert mux["live_encoder_units_total"] == 2
    assert mux["live_encoder_units_peak"] == 2, (
        "the sweep records the highest occupancy reached, which is the single "
        f"window's 2 units, got {mux['live_encoder_units_peak']}"
    )


def test_sibling_channel_window_exhausts_the_multiplex_wide_encoder_pool(api):
    """One more unit on the sibling subchannel would drive the peak to 3 against a total of 2.

    PRD §3.7: "The peak is found by taking every window on any channel of the same multiplex whose `state` is `PLANNED` or `JOINED` — **windows in `BROKEN_AWAY` or `ABANDONED` are excluded, and windows on sibling channels of the same multiplex are included**"

    Design: Corner/calculations/encoder_pool_is_multiplex_wide_with_releases_before_claims
    """
    scn = _setup_encoder_bench()
    validate_success(_plan_ch1_pool_window(api, scn), 201)

    resp = api.create_feed_window(
        factories.create_feed_window_payload(
            scn["ch2"]["id"], _CH2_ANCHOR_SEQ,
            "2026-08-01T12:21:00Z", "2026-08-01T12:23:00Z",
            feed_source="NETWORK_ALT", live_encoder_units=1,
        ),
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_ENCODER_CAPACITY_EXCEEDED")

    mux = fx.read_multiplex(scn["multiplex"]["id"], scn["eng_headers"])
    assert mux["live_encoder_units_peak"] == 2, (
        "the refused window never joins the sweep, so the peak stays at the "
        f"admitted 2 units, got {mux['live_encoder_units_peak']}"
    )
    _, meta = validate_paginated(
        api.list_channel_feed_windows(scn["ch2"]["id"], scn["mco_headers"])
    )
    assert meta["total_count"] == 0


def test_back_to_back_sibling_window_fits_because_releases_precede_claims(api):
    """A claim of two units at exactly the other window's breakaway instant still fits the pool.

    PRD §3.7: "Because releases precede claims at equal instants, back-to-back windows are feasible even at full capacity."

    Design: Corner/calculations/encoder_pool_is_multiplex_wide_with_releases_before_claims
    """
    scn = _setup_encoder_bench()
    validate_success(_plan_ch1_pool_window(api, scn), 201)

    resp = api.create_feed_window(
        factories.create_feed_window_payload(
            scn["ch2"]["id"], _CH2_ANCHOR_SEQ,
            _CH1_BREAKAWAY_UTC, "2026-08-01T12:24:00Z",
            feed_source="NETWORK_ALT", live_encoder_units=2,
        ),
        scn["mco_headers"],
    )
    window = validate_success(resp, 201)
    assert_feed_window(window)
    assert window["live_encoder_units"] == 2

    mux = fx.read_multiplex(scn["multiplex"]["id"], scn["eng_headers"])
    assert mux["live_encoder_units_peak"] == 2, (
        "the release of the first window's 2 units at 12:22:00 is applied "
        "before the second window's claim at the same instant, so occupancy "
        f"never reaches 4, got {mux['live_encoder_units_peak']}"
    )


def test_join_at_the_guarded_breakaway_instant_of_a_same_channel_window_is_rejected(api):
    """The guarded intervals are compared with closed semantics, so touching them collides.

    PRD §3.7: "Because the endpoints are included, **a new join placed exactly at another window's guarded breakaway instant is rejected, and one second later is accepted**; the refusal is `ERR_FEED_WINDOW_OVERLAP`."

    Design: Corner/calculations/encoder_pool_is_multiplex_wide_with_releases_before_claims
    """
    scn = _setup_encoder_bench()
    validate_success(_plan_ch1_pool_window(api, scn), 201)

    resp = api.create_feed_window(
        factories.create_feed_window_payload(
            scn["ch1"]["id"], _CH1_ANCHOR_SEQ,
            "2026-08-01T12:22:02Z", "2026-08-01T12:24:00Z",
            live_encoder_units=1,
        ),
        scn["mco_headers"],
    )
    validate_error(resp, "ERR_FEED_WINDOW_OVERLAP")

    _, meta = validate_paginated(
        api.list_channel_feed_windows(scn["ch1"]["id"], scn["mco_headers"])
    )
    assert meta["total_count"] == 1, (
        "the rejected plan is not persisted, so the channel still carries only "
        f"the admitted window, got total_count {meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# The quality-control bench: 1800-second captioned HD_1080I assets delivered
# perfectly in spec (H264, HD_1080I, 29.97, -24.0 LKFS, caption track present),
# so the only penalties in play are the duration discrepancy and the defect
# list, and the verdict boundaries are exercised from a clean 100.
# ---------------------------------------------------------------------------

def _delivered_captioned_asset(plant):
    """Register and deliver an in-spec captioned asset; return (id, version)."""
    asset = fx.create_asset(
        plant,
        expected_duration_seconds=1800,
        required_resolution_class="HD_1080I",
        captions_required=True,
    )
    delivered = fx.deliver_asset(
        plant, asset["id"],
        measured_duration_seconds=1800,
        delivered_resolution_class="HD_1080I",
        audio_loudness_lkfs=-24.0,
        caption_present=True,
        caption_language="en",
    )
    assert delivered["status"] == "RECEIVED"
    return asset["id"], delivered["version"]


def _ingest_report(api, plant, asset_id, version, measured, defect_codes):
    return validate_success(
        api.submit_qc_report(
            asset_id,
            factories.qc_report_payload(
                version, plant["qc"]["id"],
                basis="INGEST",
                defect_codes=defect_codes,
                measured_duration_seconds=measured,
            ),
            plant["qc_headers"],
        ),
        201,
    )


def test_a_score_of_exactly_eighty_five_passes_while_eighty_four_is_an_exception(api):
    """A 10-second discrepancy costs 15 and lands on 85; one point lower is an exception.

    PRD §3.4: "Otherwise the verdict is `PASS_WITH_EXCEPTION` if the score is below 85, and `PASS` if it is 85 or above. **A score of exactly 70 is `PASS_WITH_EXCEPTION` and a score of exactly 85 is `PASS`**"

    Design: Corner/calculations/qc_score_thresholds_are_inclusive_and_critical_defects_override_the_score
    """
    plant = fx.bootstrap_operators()

    on_boundary_id, on_boundary_version = _delivered_captioned_asset(plant)
    # discrepancy 10 -> ceil(10/2) * 3 == 15 points, no defects.
    on_boundary = _ingest_report(api, plant, on_boundary_id, on_boundary_version,
                                 1790, [])
    assert_qc_report(on_boundary)
    assert on_boundary["technical_score"] == 85
    assert on_boundary["verdict"] == "PASS"
    assert on_boundary["duration_penalty_points"] == 15
    assert on_boundary["defect_penalty_points"] == 0

    below_id, below_version = _delivered_captioned_asset(plant)
    # discrepancy 4 -> 6 points, plus VIDEO_ARTIFACT at 10 -> 84.
    below = _ingest_report(api, plant, below_id, below_version, 1796,
                           ["VIDEO_ARTIFACT"])
    assert below["technical_score"] == 84
    assert below["verdict"] == "PASS_WITH_EXCEPTION", (
        "84 is strictly below the 85 boundary, so the report passes only with "
        f"an exception, got {below['verdict']}"
    )

    assert fx.read_asset(on_boundary_id, plant["qc_headers"])["status"] == "QC_PASSED"
    assert fx.read_asset(below_id, plant["qc_headers"])["status"] == "QC_PASSED"


def test_a_score_of_exactly_seventy_is_an_exception_while_sixty_nine_fails(api):
    """The lower verdict boundary is inclusive, so 70 still clears and 69 does not.

    PRD §3.4: "The verdict is `FAIL` if the score is below 70"

    Design: Corner/calculations/qc_score_thresholds_are_inclusive_and_critical_defects_override_the_score
    """
    plant = fx.bootstrap_operators()

    on_boundary_id, on_boundary_version = _delivered_captioned_asset(plant)
    # discrepancy 8 -> 12 points, plus BLACK_FRAMES at 18 -> 70.
    on_boundary = _ingest_report(api, plant, on_boundary_id, on_boundary_version,
                                 1808, ["BLACK_FRAMES"])
    assert on_boundary["technical_score"] == 70
    assert on_boundary["verdict"] == "PASS_WITH_EXCEPTION", (
        "exactly 70 is not below 70, so the report is an exception rather than "
        f"a failure, got {on_boundary['verdict']}"
    )

    below_id, below_version = _delivered_captioned_asset(plant)
    # discrepancy 6 -> 9 points, plus LOUDNESS_OUT_OF_SPEC 12 and
    # VIDEO_ARTIFACT 10 -> 69.
    below = _ingest_report(api, plant, below_id, below_version, 1806,
                           ["LOUDNESS_OUT_OF_SPEC", "VIDEO_ARTIFACT"])
    assert below["technical_score"] == 69
    assert below["verdict"] == "FAIL"
    assert below["defect_penalty_points"] == 22

    assert fx.read_asset(on_boundary_id, plant["qc_headers"])["status"] == "QC_PASSED"
    assert fx.read_asset(below_id, plant["qc_headers"])["status"] == "QC_FAILED"


def test_a_non_negotiable_defect_fails_a_report_that_still_scores_eighty_five(api):
    """FORMAT_MISMATCH costs 15 points and disqualifies outright, so 85 is still a failure.

    PRD §3.4: "The verdict is `FAIL` if the score is below 70, **or** if any of the report's distinct defect codes is `AUDIO_LOSS` or `FORMAT_MISMATCH`, which are the non-negotiable defects"

    Design: Corner/calculations/qc_score_thresholds_are_inclusive_and_critical_defects_override_the_score
    """
    plant = fx.bootstrap_operators()
    asset_id, version = _delivered_captioned_asset(plant)

    report = _ingest_report(api, plant, asset_id, version, 1800,
                            ["FORMAT_MISMATCH"])
    assert report["duration_penalty_points"] == 0
    assert report["defect_penalty_points"] == 15
    assert report["technical_score"] == 85
    assert report["verdict"] == "FAIL", (
        "a score on the PASS boundary cannot rescue a non-negotiable defect, "
        f"got {report['verdict']}"
    )
    assert report["superseded"] is False

    asset = fx.read_asset(asset_id, plant["qc_headers"])
    assert asset["status"] == "QC_FAILED"
    assert asset["qc_verdict"] == "FAIL"
    assert asset["technical_score_ingest"] == 85, (
        "the ingest column keeps the computed score even though the verdict "
        f"failed, got {asset['technical_score_ingest']}"
    )
    assert asset["technical_score_aircheck"] is None


# ---------------------------------------------------------------------------
# The rounding bench: a 3-spot order on ch2 whose gross rate is deliberately
# indivisible by the spot count (3650 / 3 == 1216.666...), carried by a
# four-element day of 100-second elements inside a 400-second window. Two spots
# run 3 seconds short, so each earns exactly 36.5 cents of credit, and the third
# runs one second short of its unit, which is still a full air.
# ---------------------------------------------------------------------------

def _setup_short_air_settlement_day():
    """A 3-spot order on ch2 with all three spots aired: 100 / 97 / 97 / 99."""
    plant = fx.setup_base_plant()
    program = fx.setup_qc_passed_asset(plant, 100)
    spot = fx.setup_qc_passed_asset(plant, 100)
    order = fx.create_order(
        plant, channel_id=plant["ch2"]["id"],
        advertiser_name="Halvor Rational",
        order_reference="ORD-2026-0005",
        ordered_spots=3,
        unit_duration_seconds=100,
        rate_cents_total=3650,
        daypart="DAYTIME",
        priority_class="PREEMPTIBLE",
    )
    items = [
        {"sequence_number": 1, "element_kind": "PROGRAM",
         "asset_id": program["id"],
         "scheduled_start_utc": "2026-08-01T14:00:00Z",
         "scheduled_duration_seconds": 100},
        {"sequence_number": 2, "element_kind": "COMMERCIAL",
         "asset_id": spot["id"], "spot_order_id": order["id"],
         "scheduled_start_utc": "2026-08-01T14:01:40Z",
         "scheduled_duration_seconds": 100},
        {"sequence_number": 3, "element_kind": "COMMERCIAL",
         "asset_id": spot["id"], "spot_order_id": order["id"],
         "scheduled_start_utc": "2026-08-01T14:03:20Z",
         "scheduled_duration_seconds": 100},
        {"sequence_number": 4, "element_kind": "COMMERCIAL",
         "asset_id": spot["id"], "spot_order_id": order["id"],
         "scheduled_start_utc": "2026-08-01T14:05:00Z",
         "scheduled_duration_seconds": 100},
    ]
    playlist = fx.ingest(plant, items, channel_id=plant["ch2"]["id"],
                         schedule_start_utc="2026-08-01T14:00:00Z",
                         window_duration_seconds=400)
    fx.drive_playlist(plant, playlist["id"], "VALIDATED")
    fx.set_air_status(plant, plant["ch2"]["id"], "ON_AIR")
    fx.drive_playlist(plant, playlist["id"], "ARMED")
    fx.set_clock("2026-08-01T13:55:00Z")
    plant["playlist"] = fx.drive_playlist(plant, playlist["id"], "ON_AIR")
    plant["order"] = order
    plant["items"] = fx.list_items(playlist["id"], plant["traffic_headers"])
    return plant


def _air_one(plant, item, start_utc, end_utc, measured_duration_seconds):
    """Cue and start at the current clock, then advance to the end instant."""
    fx.cue_item(plant, item["id"], start_utc)
    fx.start_item(plant, item["id"], start_utc)
    fx.set_clock(end_utc)
    return fx.end_item(plant, item["id"], end_utc, measured_duration_seconds)


def _air_the_first_three(plant):
    """Air the programme in full and both 97-second short spots."""
    items = plant["items"]
    fx.set_clock("2026-08-01T14:00:00Z")
    _air_one(plant, item_by_sequence(items, 1),
             "2026-08-01T14:00:00Z", "2026-08-01T14:01:40Z", 100)
    _air_one(plant, item_by_sequence(items, 2),
             "2026-08-01T14:01:40Z", "2026-08-01T14:03:17Z", 97)
    fx.set_clock("2026-08-01T14:03:20Z")
    _air_one(plant, item_by_sequence(items, 3),
             "2026-08-01T14:03:20Z", "2026-08-01T14:04:57Z", 97)


def _air_the_last_spot(plant, measured_duration_seconds=99):
    fx.set_clock("2026-08-01T14:05:00Z")
    return _air_one(plant, item_by_sequence(plant["items"], 4),
                    "2026-08-01T14:05:00Z", "2026-08-01T14:06:39Z",
                    measured_duration_seconds)


def test_two_half_cent_credits_are_rounded_before_they_are_summed(api):
    """36.5 cents each rounds up to 37 first, so the order accrues 74 rather than 73.

    PRD §3.9: "Each per-element credit is rounded to whole cents on its own, half-cent values rounding upward, and only then are the rounded figures summed."

    Design: Corner/calculations/settlement_rounds_half_up_per_item_and_the_air_tolerance_boundary_is_inclusive
    """
    plant = _setup_short_air_settlement_day()
    _air_the_first_three(plant)
    _air_the_last_spot(plant)

    order = fx.read_order(plant["order"]["id"], plant["traffic_headers"])
    assert_spot_order(order)
    assert order["credit_accrued_cents"] == 74, (
        "the exact per-spot rate 3650/3 gives each 3-second shortfall a credit "
        "of exactly 36.5 cents, which rounds up to 37 on its own before the "
        f"sum, so the total is 37 + 37 + 0, got {order['credit_accrued_cents']}"
    )
    assert order["aired_spots"] == 1
    assert order["short_aired_spots"] == 2
    assert order["credited_spots"] == 0
    assert order["scheduled_spots"] == 0
    assert order["unplaced_spots"] == 0
    assert_spot_count_conservation(order)
    assert order["status"] == "PARTIALLY_CREDITED"


def test_a_spot_one_second_short_of_its_unit_still_counts_as_aired_in_full(api):
    """99 seconds against a 100-second unit is inside the one-second air tolerance.

    PRD §3.9: "It is **aired in full** when its `playout_status` is `PLAYED` and its `measured_duration_seconds` is at least the order's `unit_duration_seconds` less a one-second air tolerance — so **a thirty-second spot that ran twenty-nine seconds counts as aired in full**, while twenty-eight seconds does not."

    Design: Corner/calculations/settlement_rounds_half_up_per_item_and_the_air_tolerance_boundary_is_inclusive
    """
    plant = _setup_short_air_settlement_day()
    _air_the_first_three(plant)

    before = fx.read_order(plant["order"]["id"], plant["traffic_headers"])
    assert before["credit_accrued_cents"] == 74
    assert before["aired_spots"] == 0

    # The playout-event endpoint answers with the as-run entry it appended, not
    # with the element (PRD §4), so the element itself is read back separately.
    _air_the_last_spot(plant, 99)
    last = fx.read_item(item_by_sequence(plant["items"], 4)["id"],
                        plant["mco_headers"])
    assert last["playout_status"] == "PLAYED"
    assert last["measured_duration_seconds"] == 99
    assert_playlist_item(last)

    after = fx.read_order(plant["order"]["id"], plant["traffic_headers"])
    assert after["aired_spots"] == 1, (
        "measured 99 is exactly the unit less the one-second tolerance, so the "
        f"spot aired in full, got aired_spots {after['aired_spots']}"
    )
    assert after["short_aired_spots"] == 2
    assert after["credit_accrued_cents"] == 74, (
        "an element that aired in full earns no credit, so the total is "
        f"unchanged, got {after['credit_accrued_cents']}"
    )


def test_an_order_settled_purely_out_of_short_airs_stays_partially_credited(api):
    """With nothing credited and nothing unplaced, the close cannot reach either terminal status.

    PRD §3.9: "It moves from `PARTIALLY_CREDITED` to `CLOSED_WITH_CREDIT` at close settlement when the four settled counters plus `unplaced_spots` account for the whole `ordered_spots`, `scheduled_spots` is zero, and the sum of `credited_spots` and `unplaced_spots` is greater than zero, writing the final-basis credit into `credit_accrued_cents` and into the playlist's `reconciliation_credit_cents`."

    Design: Corner/calculations/settlement_rounds_half_up_per_item_and_the_air_tolerance_boundary_is_inclusive
    """
    plant = _setup_short_air_settlement_day()
    _air_the_first_three(plant)
    _air_the_last_spot(plant)

    before_read = fx.read_order(plant["order"]["id"], plant["traffic_headers"])
    validate_success(
        api.get_playlist_reconciliation(plant["playlist"]["id"],
                                        plant["traffic_headers"])
    )
    unchanged = fx.read_order(plant["order"]["id"], plant["traffic_headers"])
    assert unchanged["version"] == before_read["version"], (
        "the reconciliation view is a computed read and never mutates the "
        f"orders, got version {unchanged['version']}"
    )

    closed = fx.drive_playlist(plant, plant["playlist"]["id"], "CLOSED")
    assert closed["status"] == "CLOSED"
    assert closed["reconciliation_credit_cents"] == 74

    order = fx.read_order(plant["order"]["id"], plant["traffic_headers"])
    assert order["credit_accrued_cents"] == 74, (
        "every ordered spot is linked, so the final basis adds no unplaced "
        f"credit and the total stays 74, got {order['credit_accrued_cents']}"
    )
    assert order["unplaced_spots"] == 0
    assert order["credited_spots"] == 0
    assert order["status"] == "PARTIALLY_CREDITED", (
        "credited_spots plus unplaced_spots is zero so CLOSED_WITH_CREDIT is "
        "unreachable, and short_aired_spots is non-zero so FULLY_AIRED is too, "
        f"got {order['status']}"
    )


def test_the_master_control_operator_cannot_read_the_reconciliation_view(api):
    """The operator who wrote every as-run row is not on the money read's role list.

    PRD §4: "| GET | `/playlists/{id}/reconciliation` | Computed read reconciling the as-run log against the spot orders this playlist touched. | ProgramDirector, TrafficCoordinator, ComplianceOfficer, StationAdmin |"

    Design: Corner/calculations/settlement_rounds_half_up_per_item_and_the_air_tolerance_boundary_is_inclusive
    """
    scn = fx.setup_playlist_scenario()

    refused = api.get_playlist_reconciliation(scn["playlist"]["id"],
                                              scn["mco_headers"])
    validate_error(refused, "ERR_ROLE_NOT_PERMITTED", 403)

    validate_success(
        api.get_playlist_reconciliation(scn["playlist"]["id"],
                                        scn["traffic_headers"])
    )


# ---------------------------------------------------------------------------
# The two settlement bases: the canonical day on air carries a 4-spot order at
# 400000 cents, of which only two spots were ever placed on the timeline, so the
# preliminary and final answers for the very same graph differ by the two
# unplaced spots and again by the two the close sweep skips.
# ---------------------------------------------------------------------------

def test_the_preliminary_basis_credits_nothing_while_both_placed_spots_are_pending(api):
    """Two pending spots and two never-placed spots leave the order at zero credit.

    PRD §3.9: "On the **preliminary** basis, which is the default while a playlist is still on air, elements still `SCHEDULED`, `CUED` or `PLAYING` are excluded from the credit and are counted only in `scheduled_spots`, and ordered-but-never-scheduled spots contribute nothing; no unplaced credit is added."

    Design: Corner/calculations/preliminary_and_final_bases_diverge_and_the_read_never_persists
    """
    scn = fx.setup_on_air_playlist()

    order = fx.read_order(scn["order"]["id"], scn["traffic_headers"])
    assert_spot_order(order)
    assert order["ordered_spots"] == 4
    assert order["scheduled_spots"] == 2
    assert order["unplaced_spots"] == 2, (
        "only two of the four sold spots are linked to elements, and the slack "
        f"absorbs the rest, got {order['unplaced_spots']}"
    )
    assert order["credited_spots"] == 0
    assert order["aired_spots"] == 0
    assert order["short_aired_spots"] == 0
    assert order["credit_accrued_cents"] == 0
    assert order["status"] == "OPEN"
    assert_spot_count_conservation(order)


def test_the_reconciliation_read_leaves_the_order_and_the_playlist_untouched(api):
    """Consulting the settlement view mid-day computes figures without writing any.

    PRD §3.9: "It computes and returns the settlement figures without persisting anything — **it never mutates the orders** — which makes it safe to consult mid-day."

    Design: Corner/calculations/preliminary_and_final_bases_diverge_and_the_read_never_persists
    """
    scn = fx.setup_on_air_playlist()
    order_before = fx.read_order(scn["order"]["id"], scn["traffic_headers"])
    playlist_before = fx.read_playlist(scn["playlist"]["id"], scn["traffic_headers"])

    validate_success(
        api.get_playlist_reconciliation(scn["playlist"]["id"],
                                        scn["traffic_headers"])
    )
    validate_success(
        api.get_playlist_reconciliation(scn["playlist"]["id"],
                                        scn["pd_headers"])
    )

    order_after = fx.read_order(scn["order"]["id"], scn["traffic_headers"])
    assert order_after["version"] == order_before["version"], (
        "a computed read never increments the order's version, got "
        f"{order_after['version']} against {order_before['version']}"
    )
    assert order_after["credit_accrued_cents"] == 0
    assert order_after["credited_spots"] == 0
    assert order_after["scheduled_spots"] == 2
    assert order_after["status"] == "OPEN"

    playlist_after = fx.read_playlist(scn["playlist"]["id"], scn["traffic_headers"])
    assert playlist_after["version"] == playlist_before["version"]
    assert playlist_after["reconciliation_credit_cents"] == (
        playlist_before["reconciliation_credit_cents"]
    )


def test_the_final_basis_at_close_credits_the_unplaced_spots_in_full(api):
    """The close accounts for all four sold spots: two swept to skipped, two never placed.

    PRD §3.9: "On the **final** basis, every ordered spot must be accounted for: the unplaced count is the order's `ordered_spots` less the number of linked elements, floored at zero, and each unplaced spot is credited in full at the rounded per-spot rate, that total being added to the credit."

    Design: Corner/calculations/preliminary_and_final_bases_diverge_and_the_read_never_persists
    """
    scn = fx.setup_on_air_playlist()
    fx.air_item(scn, scn["items"][0], "2026-08-01T12:00:00Z",
                "2026-08-01T12:30:00Z", 1800)

    closed = fx.drive_playlist(scn, scn["playlist"]["id"], "CLOSED")
    assert closed["status"] == "CLOSED"
    assert closed["reconciliation_credit_cents"] == 400000, (
        "the closing playlist's share is the whole final-basis credit for the "
        f"single order it touches, got {closed['reconciliation_credit_cents']}"
    )

    order = fx.read_order(scn["order"]["id"], scn["traffic_headers"])
    assert order["credit_accrued_cents"] == 400000, (
        "the two swept spots earn the full per-spot rate of 100000 each and "
        "the two unplaced spots are credited in full on the final basis, got "
        f"{order['credit_accrued_cents']}"
    )
    assert order["credited_spots"] == 2
    assert order["unplaced_spots"] == 2
    assert order["scheduled_spots"] == 0
    assert order["aired_spots"] == 0
    assert order["short_aired_spots"] == 0
    assert order["status"] == "CLOSED_WITH_CREDIT"
    assert_spot_count_conservation(order)


# ---------------------------------------------------------------------------
# The filing bench: one transmitter on a clock at 2026-08-01T09:00:00Z, dropped
# to 60 percent of licence (a filing obligation) and later taken dark, so the
# same facility carries one POWER_REDUCTION row timed from the change itself and
# one OUTAGE row timed from the instant the checkpoint detected it.
# ---------------------------------------------------------------------------

_PR_DUE_UTC = "2026-08-02T09:00:00Z"
_OUTAGE_START_UTC = "2026-08-02T09:00:00Z"
_OUTAGE_DETECTED_UTC = "2026-08-02T09:30:00Z"
_OUTAGE_DUE_UTC = "2026-08-03T09:30:00Z"


def _reduced_power_plant():
    """A full-power transmitter dropped to 60 percent at 2026-08-01T09:00:00Z."""
    plant = fx.bootstrap_operators()
    plant["transmitter"] = fx.create_transmitter(plant["eng_headers"])
    fx.change_power_state(plant, "REDUCED_POWER", power_pct=60)
    return plant


def _only_notification(plant, kind):
    rows = fx.list_notifications(plant["transmitter"]["id"],
                                 plant["compliance_headers"],
                                 params={"kind": kind})
    assert len(rows) == 1, f"expected exactly one {kind} row, got {len(rows)}"
    return rows[0]


def _detected_outage_plant():
    """Reduce power, go dark at 09:00 the next day, then let the sweep detect it."""
    plant = _reduced_power_plant()
    fx.set_clock(_OUTAGE_START_UTC)
    fx.change_power_state(plant, "OFF_AIR", reason="Antenna feedline failure")
    fx.set_clock(_OUTAGE_DETECTED_UTC)
    return plant


def test_the_power_reduction_deadline_is_twenty_four_hours_after_the_change(api):
    """A drop to 60 percent raises a pending filing due one day after the change instant.

    PRD §3.1: "a reduction to below 80 percent of licensed power creates a `POWER_REDUCTION` notification in status `PENDING`, with `triggering_utc` set to the logical clock instant of the change, `due_utc` set to 24 hours after that instant, and `observed_power_pct` recording the percentage observed at the triggering event; the transmitter's `notification_pending_count` rises by one."

    Design: Corner/calculations/notification_deadlines_use_two_different_epochs_and_the_due_boundary_is_on_time
    """
    plant = _reduced_power_plant()

    row = _only_notification(plant, "POWER_REDUCTION")
    assert_regulatory_notification(row)
    assert row["status"] == "PENDING"
    assert row["triggering_utc"] == "2026-08-01T09:00:00Z"
    assert row["due_utc"] == _PR_DUE_UTC, (
        "the deadline is the triggering instant plus 86400 seconds, got "
        f"{row['due_utc']}"
    )
    assert row["observed_power_pct"] == 60
    assert row["outage_seconds"] is None
    assert row["filed_utc"] is None

    transmitter = fx.read_transmitter(plant["transmitter"]["id"], plant["eng_headers"])
    assert transmitter["notification_pending_count"] == 1


def test_a_clock_landing_exactly_on_the_deadline_leaves_the_row_pending(api):
    """The overdue sweep is strict, so equality with the deadline is not yet late.

    PRD §3.1: "every notification still `PENDING` whose `due_utc` now lies strictly before the new clock instant flips to `OVERDUE` and its `version` advances by one."

    Design: Corner/calculations/notification_deadlines_use_two_different_epochs_and_the_due_boundary_is_on_time
    """
    plant = _reduced_power_plant()
    row = _only_notification(plant, "POWER_REDUCTION")

    fx.set_clock(_PR_DUE_UTC)
    on_boundary = fx.read_notification(row["id"], plant["compliance_headers"])
    assert on_boundary["status"] == "PENDING", (
        "the clock is exactly at due_utc, which does not lie strictly before "
        f"the clock, got {on_boundary['status']}"
    )
    assert on_boundary["version"] == row["version"]

    fx.set_clock("2026-08-02T09:00:01Z")
    swept = fx.read_notification(row["id"], plant["compliance_headers"])
    assert swept["status"] == "OVERDUE"
    assert swept["version"] > row["version"]

    transmitter = fx.read_transmitter(plant["transmitter"]["id"], plant["eng_headers"])
    assert transmitter["notification_pending_count"] == 1, (
        "the pending counter spans PENDING and OVERDUE rows alike, got "
        f"{transmitter['notification_pending_count']}"
    )


def test_filing_exactly_at_the_deadline_is_on_time_and_cannot_be_repeated(api):
    """The boundary instant files as FILED, stamped from the clock rather than the payload.

    PRD §3.1: "A notification whose `status` is `PENDING` becomes `FILED` when the logical clock is at or before `due_utc` — the boundary instant counts as on time — and becomes `LATE_FILED` when the clock has passed `due_utc`."

    Design: Corner/calculations/notification_deadlines_use_two_different_epochs_and_the_due_boundary_is_on_time
    """
    plant = _reduced_power_plant()
    row = _only_notification(plant, "POWER_REDUCTION")
    fx.set_clock(_PR_DUE_UTC)

    filed = validate_success(
        api.file_notification(
            row["id"],
            factories.file_notification_payload(
                filed_reference="FCC-PR-0001",
                narrative="Power reduced to 60 pct for antenna work.",
                filed_utc="2026-08-01T09:00:00Z",
            ),
            plant["compliance_headers"],
        )
    )
    assert filed["status"] == "FILED"
    assert filed["filed_utc"] == _PR_DUE_UTC, (
        "the recorded filed_utc is the logical clock instant at which the "
        f"filing was accepted, not the supplied value, got {filed['filed_utc']}"
    )
    assert filed["filed_reference"] == "FCC-PR-0001"

    refused = api.file_notification(
        row["id"],
        factories.file_notification_payload(filed_reference="FCC-PR-0001-DUP",
                                            narrative="Duplicate filing."),
        plant["compliance_headers"],
    )
    validate_error(refused, "ERR_NOTIFICATION_INVALID_STATE", 409)

    transmitter = fx.read_transmitter(plant["transmitter"]["id"], plant["eng_headers"])
    assert transmitter["notification_pending_count"] == 0


def test_the_outage_deadline_runs_from_the_detection_instant_not_the_outage_start(api):
    """A 30-minute dark epoch detected by the sweep is due 24 hours after the detection.

    PRD §3.1: "the checkpoint creates one — status `PENDING`, `triggering_utc` equal to `outage_started_utc`, `due_utc` 24 hours after the new clock instant, and `outage_seconds` equal to the elapsed seconds observed at detection — raises `notification_pending_count`, and advances the transmitter's `version`."

    Design: Corner/calculations/notification_deadlines_use_two_different_epochs_and_the_due_boundary_is_on_time
    """
    plant = _detected_outage_plant()

    row = _only_notification(plant, "OUTAGE")
    assert_regulatory_notification(row)
    assert row["status"] == "PENDING"
    assert row["triggering_utc"] == _OUTAGE_START_UTC
    assert row["due_utc"] == _OUTAGE_DUE_UTC, (
        "the OUTAGE clock starts at the detection instant 09:30:00, so the "
        "deadline is 1800 seconds later than the outage start plus 86400, got "
        f"{row['due_utc']}"
    )
    assert row["outage_seconds"] == 1800
    assert row["observed_power_pct"] is None


def test_an_overdue_outage_row_files_late_and_refuses_a_future_filing_stamp(api):
    """One second past the deadline the row is overdue, and it can still be filed late.

    PRD §3.1: "A notification the checkpoint has already swept to `OVERDUE` becomes `LATE_FILED`."

    Design: Corner/calculations/notification_deadlines_use_two_different_epochs_and_the_due_boundary_is_on_time
    """
    plant = _detected_outage_plant()
    row = _only_notification(plant, "OUTAGE")

    fx.set_clock("2026-08-03T09:30:01Z")
    overdue = fx.read_notification(row["id"], plant["compliance_headers"])
    assert overdue["status"] == "OVERDUE"

    refused = api.file_notification(
        row["id"],
        factories.file_notification_payload(
            filed_reference="FCC-OUT-0001",
            narrative="Filed after the window.",
            filed_utc="2026-08-04T00:00:00Z",
        ),
        plant["compliance_headers"],
    )
    validate_error(refused, "ERR_EVENT_TIMESTAMP_IN_FUTURE")

    before = fx.read_transmitter(plant["transmitter"]["id"], plant["eng_headers"])
    late = validate_success(
        api.file_notification(
            row["id"],
            factories.file_notification_payload(
                filed_reference="FCC-OUT-0001",
                narrative="Filed after the window."),
            plant["compliance_headers"],
        )
    )
    assert late["status"] == "LATE_FILED"
    assert late["filed_utc"] == "2026-08-03T09:30:01Z"

    after = fx.read_transmitter(plant["transmitter"]["id"], plant["eng_headers"])
    assert after["notification_pending_count"] == (
        before["notification_pending_count"] - 1
    ), (
        "a terminal filing outcome decrements the pending counter, got "
        f"{after['notification_pending_count']} from "
        f"{before['notification_pending_count']}"
    )


# ---------------------------------------------------------------------------
# The air-check bench: a two-element day on ch1 in which BOTH elements reference
# the same 1800-second asset, element one aired in full and element two never
# aired. The asset's ingest report scored a clean 100, so every point the
# air-check report loses comes from the fault penalty alone.
# ---------------------------------------------------------------------------

_FAULT_UTC = "2026-08-01T12:30:00Z"


def _setup_repeated_asset_day():
    """One asset placed twice on ch1; element one is PLAYED, element two SCHEDULED."""
    plant = fx.setup_base_plant()
    asset = fx.setup_qc_passed_asset(plant, 1800)
    items = [
        {"sequence_number": 1, "element_kind": "PROGRAM", "asset_id": asset["id"],
         "scheduled_start_utc": "2026-08-01T12:00:00Z",
         "scheduled_duration_seconds": 1800},
        {"sequence_number": 2, "element_kind": "PROGRAM", "asset_id": asset["id"],
         "scheduled_start_utc": "2026-08-01T12:30:00Z",
         "scheduled_duration_seconds": 1800},
    ]
    playlist = fx.ingest(plant, items)
    fx.drive_playlist(plant, playlist["id"], "VALIDATED")
    fx.set_air_status(plant, plant["ch1"]["id"], "ON_AIR")
    fx.drive_playlist(plant, playlist["id"], "ARMED")
    fx.set_clock("2026-08-01T11:59:00Z")
    plant["playlist"] = fx.drive_playlist(plant, playlist["id"], "ON_AIR")
    plant["items"] = fx.list_items(playlist["id"], plant["traffic_headers"])
    plant["asset"] = asset
    fx.air_item(plant, plant["items"][0], "2026-08-01T12:00:00Z",
                "2026-08-01T12:30:00Z", 1800)
    return plant


def _mitigated_item_fault(plant, item_id, fault_code):
    """Report a fault against an element and stop it at MITIGATED."""
    fault = fx.report_fault(plant, fault_code, "MINOR", _FAULT_UTC,
                            channel_id=plant["ch1"]["id"],
                            playlist_item_id=item_id)
    fx.advance_fault(plant, fault["id"], "ACKNOWLEDGED")
    return fx.advance_fault(plant, fault["id"], "MITIGATED",
                            mitigation_code="SWITCH_TO_BACKUP")


def _submit_air_check(api, plant):
    asset = fx.read_asset(plant["asset"]["id"], plant["qc_headers"])
    return validate_success(
        api.submit_qc_report(
            asset["id"],
            factories.qc_report_payload(asset["version"], plant["qc"]["id"],
                                        basis="AIR_CHECK", defect_codes=[],
                                        measured_duration_seconds=1800),
            plant["qc_headers"],
        ),
        201,
    )


def test_the_air_check_fault_penalty_is_capped_at_forty_points(api):
    """A resolved 25-point and a resolved 20-point fault sum to 45 and clamp to 40.

    PRD §3.4: "For an air-check report it is the sum of per-fault-code point values over the technical faults whose `state` is `RESOLVED` and whose `playlist_item_id` names an item that references this asset and whose `playout_status` is `PLAYED` or `TRUNCATED`; the sum is then capped at 40 points."

    Design: Corner/calculations/air_check_variant_adds_a_capped_fault_penalty_and_never_moves_the_asset
    """
    plant = _setup_repeated_asset_day()
    aired = plant["items"][0]
    fx.setup_resolved_item_fault(plant, aired["id"], "AUDIO_LOSS", "MAJOR", _FAULT_UTC)
    fx.setup_resolved_item_fault(plant, aired["id"], "CAPTION_LOSS", "MINOR", _FAULT_UTC)

    report = _submit_air_check(api, plant)
    assert_qc_report(report)
    assert report["basis"] == "AIR_CHECK"
    assert report["fault_penalty_points"] == 40, (
        "25 for AUDIO_LOSS plus 20 for CAPTION_LOSS is 45, which the cap clamps "
        f"to 40, got {report['fault_penalty_points']}"
    )
    assert report["defect_penalty_points"] == 0
    assert report["duration_penalty_points"] == 0
    assert report["loudness_penalty_points"] == 0
    assert report["technical_score"] == 60, (
        "the score starts at 100 and loses only the capped fault penalty, got "
        f"{report['technical_score']}"
    )
    assert report["verdict"] == "FAIL"


def test_mitigated_faults_and_faults_on_unaired_elements_earn_no_penalty(api):
    """Only resolved faults on elements that actually aired feed the penalty.

    PRD §3.4: "Faults in any other state, faults attached to items that never aired, and faults with no `playlist_item_id` at all contribute nothing."

    Design: Corner/calculations/air_check_variant_adds_a_capped_fault_penalty_and_never_moves_the_asset
    """
    plant = _setup_repeated_asset_day()
    aired, never_aired = plant["items"][0], plant["items"][1]
    assert never_aired["playout_status"] == "SCHEDULED"

    fx.setup_resolved_item_fault(plant, aired["id"], "CAPTION_LOSS", "MINOR", _FAULT_UTC)
    _mitigated_item_fault(plant, aired["id"], "AUTOMATION_STALL")
    fx.setup_resolved_item_fault(plant, never_aired["id"], "BLACK_FRAME",
                                 "MAJOR", _FAULT_UTC)

    report = _submit_air_check(api, plant)
    assert report["fault_penalty_points"] == 20, (
        "only the resolved CAPTION_LOSS on the played element counts; the "
        "mitigated 8-point stall and the resolved 18-point fault on the "
        f"element that never aired are excluded, got "
        f"{report['fault_penalty_points']}"
    )
    assert report["technical_score"] == 80
    assert report["verdict"] == "PASS_WITH_EXCEPTION"


def test_a_failing_air_check_report_leaves_the_asset_in_qc_passed(api):
    """The air-check basis writes its own column and never touches the asset's status.

    PRD §3.4: "its score is written to `technical_score_aircheck` and it never changes the asset's `status`."

    Design: Corner/calculations/air_check_variant_adds_a_capped_fault_penalty_and_never_moves_the_asset
    """
    plant = _setup_repeated_asset_day()
    aired = plant["items"][0]
    fx.setup_resolved_item_fault(plant, aired["id"], "AUDIO_LOSS", "MAJOR", _FAULT_UTC)
    fx.setup_resolved_item_fault(plant, aired["id"], "CAPTION_LOSS", "MINOR", _FAULT_UTC)

    report = _submit_air_check(api, plant)
    assert report["verdict"] == "FAIL"

    asset = fx.read_asset(plant["asset"]["id"], plant["qc_headers"])
    assert asset["status"] == "QC_PASSED", (
        "a failing air-check report is a report on what went to air, not a "
        f"re-grading of the media, got {asset['status']}"
    )
    assert asset["technical_score_aircheck"] == 60
    assert asset["technical_score_ingest"] == 100, (
        "the ingest column keeps the clean 100 it was graded at, got "
        f"{asset['technical_score_ingest']}"
    )


def test_an_air_check_report_does_not_supersede_the_ingest_report(api):
    """Superseding is per basis, so the governing ingest report survives untouched.

    PRD §3.4: "Submitting a report supersedes any earlier report of the same `basis` on that asset by setting the earlier report's `superseded` to true."

    Design: Corner/calculations/air_check_variant_adds_a_capped_fault_penalty_and_never_moves_the_asset
    """
    plant = _setup_repeated_asset_day()
    fx.setup_resolved_item_fault(plant, plant["items"][0]["id"], "AUDIO_LOSS",
                                 "MAJOR", _FAULT_UTC)
    _submit_air_check(api, plant)

    ingest_reports, meta = validate_paginated(
        api.list_qc_reports(plant["qc_headers"],
                            params={"asset_id": plant["asset"]["id"],
                                    "basis": "INGEST"})
    )
    assert meta["total_count"] == 1
    assert ingest_reports[0]["superseded"] is False, (
        "the air-check report is of a different basis, so it never marks the "
        "ingest report superseded"
    )
    assert ingest_reports[0]["technical_score"] == 100


def test_an_air_check_report_is_refused_on_an_asset_that_has_not_passed_qc(api):
    """The air-check basis presupposes media already cleared for air.

    PRD §3.4: "An ingest-basis report requires the asset to be in `RECEIVED`; an air-check-basis report requires the asset to be in `QC_PASSED` or `QC_WAIVED`; either mismatch yields `ERR_ASSET_INVALID_STATE`."

    Design: Corner/calculations/air_check_variant_adds_a_capped_fault_penalty_and_never_moves_the_asset
    """
    plant = fx.bootstrap_operators()

    received = fx.create_asset(plant)
    delivered = fx.deliver_asset(plant, received["id"])
    assert delivered["status"] == "RECEIVED"
    refused = api.submit_qc_report(
        received["id"],
        factories.qc_report_payload(delivered["version"], plant["qc"]["id"],
                                    basis="AIR_CHECK"),
        plant["qc_headers"],
    )
    validate_error(refused, "ERR_ASSET_INVALID_STATE", 409)

    failed = fx.setup_qc_failed_asset(plant)
    assert failed["status"] == "QC_FAILED"
    refused_again = api.submit_qc_report(
        failed["id"],
        factories.qc_report_payload(failed["version"], plant["qc"]["id"],
                                    basis="AIR_CHECK"),
        plant["qc_headers"],
    )
    validate_error(refused_again, "ERR_ASSET_INVALID_STATE", 409)


# ---------------------------------------------------------------------------
# The makegood bench: a 2-spot order on ch2 for 2001 cents, so the per-spot rate
# is 1000.5 cents and every accrual rounds up to 1001. Only one of the two sold
# spots is placed, as the trailing element of a two-element day that is on air
# from its preroll boundary, and the makegood deadline is 14:10:00Z.
# ---------------------------------------------------------------------------

_MAKEGOOD_DEADLINE_UTC = "2026-08-01T14:10:00Z"
_SPOT_SLOT_UTC = "2026-08-01T14:01:40Z"


def _setup_makegood_day():
    """A 2-spot order with one placed spot on an on-air ch2 playlist."""
    plant = fx.setup_base_plant()
    program = fx.setup_qc_passed_asset(plant, 100)
    spot = fx.setup_qc_passed_asset(plant, 100)
    order = fx.create_order(
        plant, channel_id=plant["ch2"]["id"],
        advertiser_name="Nordkapp Rail",
        order_reference="ORD-2026-0006",
        ordered_spots=2,
        unit_duration_seconds=100,
        rate_cents_total=2001,
        daypart="DAYTIME",
        priority_class="PREEMPTIBLE",
        makegood_deadline_utc=_MAKEGOOD_DEADLINE_UTC,
    )
    items = [
        {"sequence_number": 1, "element_kind": "PROGRAM",
         "asset_id": program["id"],
         "scheduled_start_utc": "2026-08-01T14:00:00Z",
         "scheduled_duration_seconds": 100},
        {"sequence_number": 2, "element_kind": "COMMERCIAL",
         "asset_id": spot["id"], "spot_order_id": order["id"],
         "scheduled_start_utc": _SPOT_SLOT_UTC,
         "scheduled_duration_seconds": 100},
    ]
    playlist = fx.ingest(plant, items, channel_id=plant["ch2"]["id"],
                         schedule_start_utc="2026-08-01T14:00:00Z",
                         window_duration_seconds=200)
    fx.drive_playlist(plant, playlist["id"], "VALIDATED")
    fx.set_air_status(plant, plant["ch2"]["id"], "ON_AIR")
    fx.drive_playlist(plant, playlist["id"], "ARMED")
    fx.set_clock("2026-08-01T13:55:00Z")
    plant["playlist"] = fx.drive_playlist(plant, playlist["id"], "ON_AIR")
    plant["items"] = fx.list_items(playlist["id"], plant["traffic_headers"])
    plant["order"] = order
    return plant


def _read_order(plant):
    return fx.read_order(plant["order"]["id"], plant["traffic_headers"])


def _place_makegood(plant, sequence_number, scheduled_start_utc=_SPOT_SLOT_UTC):
    playlist = fx.read_playlist(plant["playlist"]["id"], plant["traffic_headers"])
    return fx.place_makegood(plant, plant["order"]["id"], playlist["id"],
                             playlist["version"], sequence_number,
                             scheduled_start_utc,
                             scheduled_duration_seconds=100)


def _makegood_response(api, plant, sequence_number, scheduled_start_utc=_SPOT_SLOT_UTC):
    playlist = fx.read_playlist(plant["playlist"]["id"], plant["traffic_headers"])
    return api.place_makegood(
        plant["order"]["id"],
        factories.makegood_payload(playlist["id"], playlist["version"],
                                   sequence_number, scheduled_start_utc,
                                   scheduled_duration_seconds=100),
        plant["traffic_headers"],
    )


def _first_cycle(plant):
    """Skip the placed spot at 13:55:00Z and place its makegood as element three."""
    fx.skip_item(plant, plant["items"][1]["id"], "2026-08-01T13:55:00Z")
    return _place_makegood(plant, 3)


def test_skipping_the_only_placed_spot_accrues_the_full_rounded_credit(api):
    """A per-spot rate of 1000.5 cents accrues as 1001 when the spot never airs.

    PRD §3.6: "It appends a skip entry, and when the element carries a `spot_order_id` it moves that spot from `scheduled_spots` to `credited_spots` and accrues the **full** per-spot credit, then recomputes both of the playlist's variance figures."

    Design: Corner/calculations/makegood_round_trip_reverses_the_rounded_credit_exactly_with_no_drift
    """
    plant = _setup_makegood_day()

    before = _read_order(plant)
    assert before["credit_accrued_cents"] == 0
    assert before["scheduled_spots"] == 1
    assert before["unplaced_spots"] == 1
    assert before["status"] == "OPEN"
    assert_spot_count_conservation(before)

    fx.skip_item(plant, plant["items"][1]["id"], "2026-08-01T13:55:00Z")

    after = _read_order(plant)
    assert after["credit_accrued_cents"] == 1001, (
        "2001 cents over 2 spots is 1000.5 per spot, and a half cent rounds "
        f"upward, got {after['credit_accrued_cents']}"
    )
    assert after["credited_spots"] == 1
    assert after["scheduled_spots"] == 0
    assert after["unplaced_spots"] == 1
    assert after["status"] == "PARTIALLY_CREDITED"
    assert_spot_count_conservation(after)


def test_the_makegood_element_points_back_at_the_credited_spot(api):
    """The compensating placement is a new commercial element flagged as a makegood.

    PRD §3.9: "A successful makegood creates a playlist element with `is_makegood` set to true, `element_kind` `COMMERCIAL`, and `replaces_item_id` pointing at the credited element, in `playout_status` `SCHEDULED`."

    Design: Corner/calculations/makegood_round_trip_reverses_the_rounded_credit_exactly_with_no_drift
    """
    plant = _setup_makegood_day()
    credited_item = plant["items"][1]

    makegood = _first_cycle(plant)
    assert_playlist_item(makegood)
    assert makegood["is_makegood"] is True
    assert makegood["element_kind"] == "COMMERCIAL"
    assert makegood["replaces_item_id"] == credited_item["id"], (
        "the replacement names the credited element it compensates, got "
        f"{makegood['replaces_item_id']}"
    )
    assert makegood["playout_status"] == "SCHEDULED"
    assert makegood["spot_order_id"] == plant["order"]["id"]
    assert makegood["sequence_number"] == 3


def test_the_makegood_subtracts_exactly_the_rounded_credit_it_reverses(api):
    """The reversal uses the same 1001 that was accrued, so the ledger returns to zero.

    PRD §3.9: "It moves one spot from `credited_spots` back to `scheduled_spots` and subtracts **exactly the credit that spot had accrued** from `credit_accrued_cents`."

    Design: Corner/calculations/makegood_round_trip_reverses_the_rounded_credit_exactly_with_no_drift
    """
    plant = _setup_makegood_day()
    _first_cycle(plant)

    order = _read_order(plant)
    assert order["credit_accrued_cents"] == 0, (
        "subtracting the exact rational 1000.5 rather than the rounded 1001 "
        f"would leave a cent behind, got {order['credit_accrued_cents']}"
    )
    assert order["credited_spots"] == 0
    assert order["scheduled_spots"] == 1
    assert order["unplaced_spots"] == 1
    assert_spot_count_conservation(order)
    assert order["status"] == "OPEN", (
        "an order returns to OPEN once every credited spot has a makegood "
        f"placed, got {order['status']}"
    )


def test_two_skip_and_makegood_cycles_leave_no_rounding_drift(api):
    """A second round trip, placed at the deadline instant itself, still lands on zero.

    PRD §3.9: "and `credit_accrued_cents` returns to exactly its pre-preemption value, so **no rounding drift accrues across any number of preempt-and-makegood cycles.**"

    Design: Corner/calculations/makegood_round_trip_reverses_the_rounded_credit_exactly_with_no_drift
    """
    plant = _setup_makegood_day()
    first_makegood = _first_cycle(plant)

    fx.set_clock(_MAKEGOOD_DEADLINE_UTC)
    fx.skip_item(plant, first_makegood["id"], _MAKEGOOD_DEADLINE_UTC)
    mid_cycle = _read_order(plant)
    assert mid_cycle["credit_accrued_cents"] == 1001
    assert mid_cycle["credited_spots"] == 1

    second_makegood = _place_makegood(plant, 4)
    assert second_makegood["is_makegood"] is True
    assert second_makegood["replaces_item_id"] == first_makegood["id"]

    order = _read_order(plant)
    assert order["credit_accrued_cents"] == 0, (
        "two full cycles of a half-cent per-spot rate accumulate exactly zero "
        f"drift, got {order['credit_accrued_cents']}"
    )
    assert order["credited_spots"] == 0
    assert order["scheduled_spots"] == 1
    assert order["unplaced_spots"] == 1
    assert_spot_count_conservation(order)


def test_a_makegood_with_no_credited_spot_left_to_reverse_is_refused(api):
    """Once every credited spot has been placed again there is nothing to compensate.

    PRD §3.9: "The order must have `credited_spots` of at least 1, because there must be a credited spot to reverse; **a `credited_spots` of 0 is refused with `ERR_NO_CREDITED_SPOT_TO_MAKEGOOD` even when the order is `PARTIALLY_CREDITED` for other reasons**"

    Design: Corner/calculations/makegood_round_trip_reverses_the_rounded_credit_exactly_with_no_drift
    """
    plant = _setup_makegood_day()
    _first_cycle(plant)
    assert _read_order(plant)["credited_spots"] == 0

    refused = _makegood_response(api, plant, 4, "2026-08-01T14:03:20Z")
    validate_error(refused, "ERR_NO_CREDITED_SPOT_TO_MAKEGOOD", 409)

    unchanged = _read_order(plant)
    assert unchanged["credit_accrued_cents"] == 0
    assert unchanged["scheduled_spots"] == 1


def test_a_makegood_one_second_past_the_deadline_is_refused(api):
    """The deadline is checked on the logical clock before any inventory rule.

    PRD §3.9: "a makegood placed exactly at the deadline instant is accepted and one second later is refused** with `ERR_MAKEGOOD_DEADLINE_PASSED`, and **the deadline is checked before the inventory and credit rules**"

    Design: Corner/calculations/makegood_round_trip_reverses_the_rounded_credit_exactly_with_no_drift
    """
    plant = _setup_makegood_day()
    first_makegood = _first_cycle(plant)

    fx.set_clock("2026-08-01T14:10:01Z")
    fx.skip_item(plant, first_makegood["id"], "2026-08-01T14:10:01Z")
    assert _read_order(plant)["credited_spots"] == 1

    refused = _makegood_response(api, plant, 4)
    validate_error(refused, "ERR_MAKEGOOD_DEADLINE_PASSED", 409)

    order = _read_order(plant)
    assert order["credit_accrued_cents"] == 1001, (
        "the refused placement reverses nothing, so the credit stands, got "
        f"{order['credit_accrued_cents']}"
    )
    assert order["credited_spots"] == 1
