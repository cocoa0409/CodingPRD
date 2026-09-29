"""One-cent boundaries: the note obligation and the constrained posture."""

from test_helpers import (
    append_cost_estimates,
    assert_bill,
    certify_note,
    read_agency,
    read_bill,
    read_session,
    route_fiscal_note,
    setup_introduced_bill,
    setup_world,
    submit_note,
)


def test_one_cent_of_appropriation_decides_the_fiscal_note_obligation():
    """PRD: "The second, independent state dimension is decided here too:
    `fiscal_status` opens at `NOTE_PENDING` when `appropriation_requested_cents`
    is strictly greater than 0, and at `NOT_REQUIRED` when it is exactly 0."

    Design: Difficulty/boundary_precision_check/bill_introduction_zero_versus_one_cent_appropriation_decides_fiscal_note_obligation
    """
    world = setup_world()
    _request_z, bill_z = setup_introduced_bill(
        world,
        affected_sections_count=3,
        requested_sections_count=3,
        subject="Open meetings notice reform",
        summary="Standardize open meetings notice.",
        target_code_chapter="Title 24",
        appropriation_requested_cents=0,
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-04T00:00:00Z",
    )
    _request_o, bill_o = setup_introduced_bill(
        world,
        affected_sections_count=3,
        requested_sections_count=3,
        subject="Open records fee schedule",
        summary="Set a uniform records fee schedule.",
        target_code_chapter="Title 24",
        appropriation_requested_cents=1,
        engagement_start_utc="2026-09-05T00:00:00Z",
        engagement_end_utc="2026-09-07T00:00:00Z",
    )

    assert_bill(bill_z)
    assert bill_z["appropriation_requested_cents"] == 0
    assert bill_z["fiscal_status"] == "NOT_REQUIRED"
    assert_bill(bill_o)
    assert bill_o["appropriation_requested_cents"] == 1
    assert bill_o["fiscal_status"] == "NOTE_PENDING"
    assert bill_z["legislative_status"] == "INTRODUCED"
    assert bill_o["legislative_status"] == "INTRODUCED"


def test_the_appropriation_tier_bonus_separates_zero_from_one_cent_at_intake():
    """PRD: "Finally an appropriation tier bonus is added: nothing when
    `appropriation_requested_cents` is exactly 0; five points when it is at least
    1 cent and at most 5,000,000 cents (that is, fifty thousand dollars); and
    fifteen points when it exceeds 5,000,000 cents." and "A `HOUSE` bill takes
    the current value of `next_house_bill_number`, renders `bill_number` as the
    two characters `HB`, a single space, and that number in decimal with no zero
    padding, and then raises `next_house_bill_number` by one."

    Design: Difficulty/boundary_precision_check/bill_introduction_zero_versus_one_cent_appropriation_decides_fiscal_note_obligation
    """
    world = setup_world()
    request_z, bill_z = setup_introduced_bill(
        world,
        affected_sections_count=3,
        requested_sections_count=3,
        subject="Open meetings notice reform",
        summary="Standardize open meetings notice.",
        target_code_chapter="Title 24",
        appropriation_requested_cents=0,
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-04T00:00:00Z",
    )
    request_o, bill_o = setup_introduced_bill(
        world,
        affected_sections_count=3,
        requested_sections_count=3,
        subject="Open records fee schedule",
        summary="Set a uniform records fee schedule.",
        target_code_chapter="Title 24",
        appropriation_requested_cents=1,
        engagement_start_utc="2026-09-05T00:00:00Z",
        engagement_end_utc="2026-09-07T00:00:00Z",
    )

    # Twelve points for three declared sections, then nothing versus five.
    assert request_z["intake_complexity_estimate"] == 12
    assert request_o["intake_complexity_estimate"] == 17
    assert bill_z["bill_number"] == "HB 1"
    assert bill_o["bill_number"] == "HB 2"

    session = read_session(world)
    assert session["bills_introduced_count"] == 2
    assert session["next_house_bill_number"] == 3


NEAR_THRESHOLD_LINES = [
    {
        "fiscal_year": 2027,
        "scenario": "BASELINE",
        "personnel_cost_cents": 20_000_000,
        "operating_cost_cents": 3_148_147,
        "one_time_cost_cents": 0,
        "fte_count": 1.0,
        "revenue_impact_cents": 0,
        "assumption_note": "FY2027 crew.",
    },
    {
        "fiscal_year": 2028,
        "scenario": "BASELINE",
        "personnel_cost_cents": 20_000_000,
        "operating_cost_cents": 3_148_148,
        "one_time_cost_cents": 0,
        "fte_count": 1.0,
        "revenue_impact_cents": 0,
        "assumption_note": "FY2028 crew.",
    },
]

ONE_CENT_LINES = [
    {
        "fiscal_year": 2027,
        "scenario": "BASELINE",
        "personnel_cost_cents": 1,
        "operating_cost_cents": 0,
        "one_time_cost_cents": 0,
        "fte_count": 1.0,
        "revenue_impact_cents": 0,
        "assumption_note": "One cent of sign vinyl.",
    },
    {
        "fiscal_year": 2028,
        "scenario": "BASELINE",
        "personnel_cost_cents": 0,
        "operating_cost_cents": 0,
        "one_time_cost_cents": 0,
        "fte_count": 1.0,
        "revenue_impact_cents": 0,
        "assumption_note": "No out-year cost.",
    },
]


def _two_submitted_notes():
    """A large bridge note one cent short of the threshold plus a one-cent note."""
    world = setup_world(
        with_agency=True,
        agency_overrides={
            "name": "Dept of Transportation",
            "agency_code": "DOT",
            "status": "ACTIVE",
            "max_open_requests": 3,
        },
    )
    _request_p, bill_p = setup_introduced_bill(
        world,
        affected_sections_count=5,
        requested_sections_count=5,
        subject="Bridge rehabilitation program",
        summary="Create a bridge rehabilitation program.",
        target_code_chapter="Title 23",
        appropriation_requested_cents=46_000_000,
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-04T00:00:00Z",
    )
    _request_q, bill_q = setup_introduced_bill(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Rest area signage",
        summary="Update rest area signage standards.",
        target_code_chapter="Title 23",
        appropriation_requested_cents=200_000,
        engagement_start_utc="2026-09-05T00:00:00Z",
        engagement_end_utc="2026-09-07T00:00:00Z",
    )
    note_p = route_fiscal_note(world, bill_p, methodology="INCREMENTAL_COST")
    append_cost_estimates(world, note_p, NEAR_THRESHOLD_LINES)
    submitted_p = submit_note(world, note_p)
    note_q = route_fiscal_note(world, bill_q, methodology="INCREMENTAL_COST")
    append_cost_estimates(world, note_q, ONE_CENT_LINES)
    submitted_q = submit_note(world, note_q)
    return world, bill_p, submitted_p, bill_q, submitted_q


def test_ledger_one_cent_below_the_threshold_leaves_the_posture_normal():
    """PRD: "The ledger is maintained by exact addition when a note is certified
    and exact subtraction when a certified note is re-opened, and the
    incrementally maintained value must equal a full recomputation of that sum at
    every observable instant." and "Alongside the ledger the session maintains
    `fiscal_posture`, which is `CONSTRAINED` when `certified_fiscal_total_cents`
    is greater than or equal to `constrained_threshold_cents` and `NORMAL`
    otherwise."

    Design: Difficulty/boundary_precision_check/certification_ledger_at_threshold_minus_one_cent_stays_normal_then_flips_constrained_at_exact_threshold
    """
    world, bill_p, submitted_p, _bill_q, _submitted_q = _two_submitted_notes()

    assert submitted_p["direct_cost_cents"] == 46_296_295
    assert float(submitted_p["contingency_pct"]) == 0.08
    assert submitted_p["contingency_cents"] == 3_703_704
    assert submitted_p["certified_total_cents"] == 49_999_999

    certify_note(world, submitted_p)

    session = read_session(world)
    assert session["certified_fiscal_total_cents"] == 49_999_999
    assert session["fiscal_posture"] == "NORMAL"
    assert read_bill(world, bill_p["id"])["fiscal_status"] == "NOTE_COMPLETE"


def test_one_more_cent_on_the_ledger_flips_the_posture_to_constrained():
    """PRD: "The boundary is inclusive: a total exactly equal to the threshold is
    already `CONSTRAINED`." and "It equals the sum of `certified_total_cents`
    over every fiscal note request in status `CERTIFIED` whose bill belongs to
    that session; requests in `ROUTED`, `SUBMITTED`, `RETURNED_FOR_REVISION` or
    `LAPSED` contribute nothing, even when a re-opened request still retains a
    `certified_total_cents` value for later restoration."

    Design: Difficulty/boundary_precision_check/certification_ledger_at_threshold_minus_one_cent_stays_normal_then_flips_constrained_at_exact_threshold
    """
    world, bill_p, submitted_p, bill_q, submitted_q = _two_submitted_notes()
    certify_note(world, submitted_p)
    assert read_session(world)["fiscal_posture"] == "NORMAL"

    # A single cent of personnel cost draws the lowest tier and no contingency.
    assert submitted_q["direct_cost_cents"] == 1
    assert float(submitted_q["contingency_pct"]) == 0.05
    assert submitted_q["contingency_cents"] == 0
    assert submitted_q["certified_total_cents"] == 1

    certify_note(world, submitted_q)

    session = read_session(world)
    assert session["certified_fiscal_total_cents"] == 50_000_000
    assert session["fiscal_posture"] == "CONSTRAINED"
    assert read_bill(world, bill_p["id"])["fiscal_status"] == "NOTE_COMPLETE"
    assert read_bill(world, bill_q["id"])["fiscal_status"] == "NOTE_COMPLETE"
    assert read_agency(world)["open_request_count"] == 0
