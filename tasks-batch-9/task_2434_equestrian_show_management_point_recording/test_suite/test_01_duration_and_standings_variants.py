"""Two readings of one stored population: duration estimate variants and the two point scales."""

from test_helpers import api_client, validate_success
from test_helpers.fixtures import (
    acknowledge,
    book_slot,
    build_approved_show,
    build_entry,
    build_point_submission,
    confirm_entry,
    create_horse,
    create_rider,
    get_class,
    get_class_entry,
    get_ring,
    get_success_data,
    settle_entry,
)
from test_helpers.test_users import SHOW_SECRETARY_USER_ID, TEST_USERS

SLOT_START = "2026-09-10T14:00:00Z"


def _class_with_four_rows_two_confirmed():
    """One JUMPER class carrying four class entries, exactly two of them CONFIRMED."""
    ctx = build_approved_show(ring_specs=[{}])
    rider = create_rider()
    rows = []
    for index in range(4):
        horse = create_horse()
        row = build_entry(ctx["show_id"], rider["id"], horse["id"], [ctx["class_id"]])
        if index < 2:
            settle_entry(row["entry_id"], rider["id"])
            confirm_entry(row["entry_id"])
        rows.append(row)
    ctx["rider"] = rider
    ctx["rows"] = rows
    return ctx


def test_booking_writes_the_projected_variant_of_the_duration_estimate():
    """Four class entries sit on a 120 cm jumper class with a jump-off enabled, but only two
    of them are CONFIRMED. Booking the class into a ring with a 10-minute turnover buffer
    estimates against the projected population of all four: six rounds (four scheduled plus
    two jump-off) at 75 base seconds scaled by a height factor of 1.1 is 495 seconds, which
    rounds up once to 9 ride minutes, plus a 10-minute course walk and the 10-minute buffer,
    for 29 minutes. The slot's window and warm-up lead are derived from that single figure.

    PRD §3.6: "Two variants of the entry count exist, and they differ only in which class entries they count."
    PRD §3.6: "The *projected* variant counts class entries whose `status` is `ENTERED` or `CONFIRMED`, so it includes horses whose parent entry has not yet been accepted or paid."
    PRD §3.6: "Booking a class into a ring writes the *projected* variant into `estimated_minutes`."
    PRD §3.6: "Its `duration_minutes` is copied from the class's freshly computed `estimated_minutes`; its `end_utc` is its `start_utc` advanced by `duration_minutes`, and that upper bound is half-open, so the ring is free again at `end_utc`; and its `warmup_start_utc` is its `start_utc` moved back by 30 minutes, marking the beginning of the supervised warm-up window."
    PRD §3.6: "The ring's `scheduled_minutes_total` becomes the sum, over those same occupancies, of the whole minutes from each one's `start_utc` to its `end_utc`, and `slot_count` becomes their count."

    Design: Difficulty/dual_variant_calc/class_duration_projected_all_entered_vs_confirmed_only
    """
    ctx = _class_with_four_rows_two_confirmed()

    before = get_class(ctx["class_id"])
    assert before["entry_count"] == 4
    assert before["confirmed_entry_count"] == 2

    ring_version = get_ring(ctx["ring_id"])["version"]
    response = api_client.create_ring_slot(
        {
            "ring_id": ctx["ring_id"],
            "class_id": ctx["class_id"],
            "start_utc": SLOT_START,
            "expected_ring_version": ring_version,
        },
        TEST_USERS["ring_master_headers"],
    )
    slot = validate_success(response, 201)

    assert slot["duration_minutes"] == 29
    assert slot["end_utc"] == "2026-09-10T14:29:00Z"
    assert slot["warmup_start_utc"] == "2026-09-10T13:30:00Z"
    assert slot["order_index"] == 1

    booked = get_class(ctx["class_id"])
    assert booked["estimated_minutes"] == 29
    assert booked["status"] == "SCHEDULED"

    ring = get_ring(ctx["ring_id"])
    assert ring["scheduled_minutes_total"] == 29
    assert ring["slot_count"] == 1


def test_schedule_projection_reports_confirmed_only_beside_projected_and_their_drift():
    """The same four rows read twice. The projection endpoint recomputes the estimate under
    both filters: the projected variant admits all four rows for 29 minutes, while the
    confirmed-only variant admits the two CONFIRMED rows for 25 minutes (three rounds at
    82.5 seconds is 247.5 seconds, one rounding up to 5 ride minutes, plus 10 plus 10). The
    drift the show office sees is exactly 4 minutes over identical stored data.

    PRD §3.6: "The *confirmed-only* variant counts class entries whose `status` is exactly `CONFIRMED`."
    PRD §3.6: "Because confirmation requires both entry dimensions, the confirmed-only population is always a subset of the projected one, and the two variants therefore report different minute counts over identical stored data."
    PRD §3.6: "For every class of the show that currently holds an occupancy whose `status` is `SCHEDULED` or `RUNNING`, it recomputes both variants against that occupancy's ring and returns `show_id`, the aggregate `projected_total_minutes` from the projected variant, the aggregate `confirmed_only_total_minutes` from the confirmed-only variant, `projected_drift_minutes` as `projected_total_minutes` minus `confirmed_only_total_minutes`, and a `class_projections` array carrying the per-class figures."
    PRD §3.6: "The read computes and stores nothing."

    Design: Difficulty/dual_variant_calc/class_duration_projected_all_entered_vs_confirmed_only
    """
    ctx = _class_with_four_rows_two_confirmed()
    book_slot(ctx["ring_id"], ctx["class_id"], SLOT_START)

    projection = validate_success(
        api_client.get_schedule_projection(ctx["show_id"], TEST_USERS["show_secretary_headers"])
    )

    assert projection["show_id"] == ctx["show_id"]
    assert projection["projected_total_minutes"] == 29
    assert projection["confirmed_only_total_minutes"] == 25
    assert projection["projected_drift_minutes"] == 4
    assert len(projection["class_projections"]) == 1

    unchanged = get_class(ctx["class_id"])
    assert unchanged["estimated_minutes"] == 29
    assert unchanged["confirmed_entry_count"] == 2


def test_national_leg_credits_the_ten_six_four_three_table_at_a_unit_multiplier():
    """A four-starter class is placed 1..4 and its submission acknowledged nationally. The
    national table pays 10, 6, 4 and 3, and a confirmed field of four sits in the 1.0
    multiplier tier, so the credited figures are 10.0, 6.0, 4.0 and 3.0 and the submission's
    national total is 23.0. The regional side of the same submission is untouched: no
    `points_regional` has been written and the submission is only NATIONAL_ACCEPTED.

    PRD §3.8: "The national scale awards through fifth place from a fixed table: 10 points for first, 6 for second, 4 for third, 3 for fourth and 2 for fifth."
    PRD §3.8: "That whole table is then scaled by a multiplier chosen from the class's `confirmed_entry_count`: when it is at least 25 the multiplier is 2.0; otherwise when it is at least 10 the multiplier is 1.5; otherwise when it is at least 3 the multiplier is 1.0; and below 3 the multiplier is 0.0."
    PRD §3.8: "An accepted **national** leg writes `points_national` on every class entry of the class whose `status` is `COMPLETED`, sets the submission's `national_points_total` to the sum of those values, stores the supplied `body_reference` as `national_body_reference`, and credits each placed class entry's rider by adding that class entry's `points_national` to the rider's `national_points_total`."
    PRD §3.8: "From `PREPARED`, a national acceptance moves the submission `PREPARED → NATIONAL_ACCEPTED` and a regional acceptance moves it `PREPARED → REGIONAL_ACCEPTED`."

    Design: Difficulty/dual_variant_calc/rider_standings_national_scale_vs_regional_scale
    """
    ctx = build_point_submission(entry_count=4, actual_minutes=26)
    assert ctx["submission"]["status"] == "PREPARED"
    assert ctx["submission"]["submitted_by_user_id"] == SHOW_SECRETARY_USER_ID

    submission = validate_success(
        api_client.acknowledge_point_submission(
            ctx["submission_id"],
            {"standings_body": "NATIONAL", "outcome": "ACCEPTED", "body_reference": "NAT-2026-00417"},
            TEST_USERS["federation_officer_headers"],
        )
    )

    assert submission["status"] == "NATIONAL_ACCEPTED"
    assert submission["national_points_total"] == 10.0 + 6.0 + 4.0 + 3.0
    assert submission["national_body_reference"] == "NAT-2026-00417"
    assert submission["regional_points_total"] == 0
    assert submission["regional_body_reference"] is None

    expected_national = [10.0, 6.0, 4.0, 3.0]
    for row, points in zip(ctx["field"], expected_national):
        class_entry = get_class_entry(row["class_entry_id"])
        assert class_entry["points_national"] == points
        assert class_entry["points_regional"] == 0
        rider = get_success_data(
            api_client.get_rider(row["rider_id"], TEST_USERS["show_secretary_headers"])
        )
        assert rider["national_points_total"] == points
        assert rider["regional_points_total"] == 0


def test_regional_leg_pays_only_three_places_and_joins_the_submission_at_recorded():
    """The second leg of the same submission runs the regional scale over the identical four
    placings: 8, 5, 3 and — because regional pays only through third — 0 for the fourth. The
    two scales genuinely disagree on the same rows (10.0 against 8 for the winner, 3.0 against
    0 for fourth), the submission's regional total is 16, and the leg that lands second joins
    the saga at RECORDED. The standings read recomputes both totals for the winner.

    PRD §3.8: "The regional scale is flatter and capped."
    PRD §3.8: "It awards only through third place — 8 points for first, 5 for second, 3 for third — and any placing beyond third scores zero."
    PRD §3.8: "A first place in a three-entry class scores 10.0 nationally and 8 regionally; a fourth place in the same class scores 3.0 nationally and 0 regionally."
    PRD §3.8: "From `NATIONAL_ACCEPTED`, a regional acceptance moves it `NATIONAL_ACCEPTED → RECORDED`; from `REGIONAL_ACCEPTED`, a national acceptance moves it `REGIONAL_ACCEPTED → RECORDED`."
    PRD §3.8: "A rider's standings read recomputes both totals from accepted submissions without storing anything, optionally scoped by `show_id`, and returns `rider_id`, `national_points_total`, `regional_points_total`, `national_class_count` — the number of classes contributing national points — and `regional_capped`, a boolean reporting whether the per-show regional ceiling bound."

    Design: Difficulty/dual_variant_calc/rider_standings_national_scale_vs_regional_scale
    """
    ctx = build_point_submission(entry_count=4, actual_minutes=26)
    acknowledge(ctx["submission_id"], "NATIONAL", "ACCEPTED", "NAT-2026-00417")

    submission = validate_success(
        api_client.acknowledge_point_submission(
            ctx["submission_id"],
            {"standings_body": "REGIONAL", "outcome": "ACCEPTED", "body_reference": "REG-SE-0091"},
            TEST_USERS["federation_officer_headers"],
        )
    )

    assert submission["status"] == "RECORDED"
    assert submission["regional_points_total"] == 8 + 5 + 3
    assert submission["national_points_total"] == 23.0
    assert submission["regional_body_reference"] == "REG-SE-0091"

    expected = [(10.0, 8), (6.0, 5), (4.0, 3), (3.0, 0)]
    for row, (national, regional) in zip(ctx["field"], expected):
        class_entry = get_class_entry(row["class_entry_id"])
        assert class_entry["points_national"] == national
        assert class_entry["points_regional"] == regional
        rider = get_success_data(
            api_client.get_rider(row["rider_id"], TEST_USERS["show_secretary_headers"])
        )
        assert rider["national_points_total"] == national
        assert rider["regional_points_total"] == regional

    winner = ctx["field"][0]
    standings = validate_success(
        api_client.get_rider_standings(
            winner["rider_id"],
            TEST_USERS["ring_master_headers"],
            params={"show_id": ctx["show_id"]},
        )
    )
    assert standings["rider_id"] == winner["rider_id"]
    assert standings["national_points_total"] == 10.0
    assert standings["regional_points_total"] == 8
    assert standings["national_class_count"] == 1
    assert standings["regional_capped"] is False
