"""The two backward- and forward-looking money figures of a residency, the two
reliability figures of an artist, and the chain a no-show sets off."""
from test_helpers import (
    TEST_USERS,
    cancel_session_as_coordinator,
    create_confirmed_session,
    deliver_session,
    read_artist,
    read_residency,
    read_session,
    set_clock_to_default,
    setup_active_residency,
    setup_two_delivered_evaluated_sessions,
)

RC = TEST_USERS["roster_coordinator_headers"]


# ==========================================================================
# Earned to date versus projected cost
# ==========================================================================
def test_earned_to_date_sums_the_payables_of_the_delivered_sessions_only(api):
    """PRD §3.4: "`earned_to_date_cents` is the chronological, backward-looking
    figure: the sum of `payable_cents` over this residency's `DELIVERED`
    sessions, at the actual fees and reimbursements recorded at delivery, with
    real prorated minutes and real mileage."
    PRD §3.7: "The session's `payable_cents` is the sum of `fee_cents`,
    `travel_reimbursement_cents`, and `materials_reimbursement_cents`."

    Design: Difficulty/dual_variant_calc/residency_cost_outlook_earned_versus_projected_completion
    """
    set_clock_to_default()
    scenario = setup_two_delivered_evaluated_sessions()
    one = read_session(scenario["session_one"]["id"])
    two = read_session(scenario["session_two"]["id"])
    assert one["payable_cents"] == 17178, (
        f"expected 13974 + 704 + 2500, got {one['payable_cents']}"
    )
    assert two["payable_cents"] == 14276, (
        f"expected 13974 + 302, got {two['payable_cents']}"
    )

    residency = read_residency(scenario["residency"]["id"])
    assert residency["earned_to_date_cents"] == 31454, (
        f"expected 17178 + 14276, got {residency['earned_to_date_cents']}"
    )
    assert residency["sessions_delivered_count"] == 2
    assert residency["encumbered_cents"] == 31454
    assert residency["available_cents"] == 168546
    assert residency["disbursed_cents"] == 0


def test_projected_cost_adds_a_lead_projection_for_each_remaining_slot(api):
    """PRD §3.4: "`projected_cost_cents` is the forward-looking figure the
    program director watches against `budget_cents`: it starts from
    `earned_to_date_cents`, adds a full-length fee projection for every session
    of the residency whose status is `PLANNED`, `CONFIRMED`, or `VACATED`, and
    then adds one lead projection for each remaining unscheduled allotment unit
    and each outstanding make-up credit — that is, `sessions_unscheduled_count`
    plus `makeup_credits_outstanding` lead projections."
    PRD §3.4: "Cancelled sessions of either kind are excluded from both figures."

    Design: Difficulty/dual_variant_calc/residency_cost_outlook_earned_versus_projected_completion
    """
    set_clock_to_default()
    scenario = setup_two_delivered_evaluated_sessions()
    residency = read_residency(scenario["residency"]["id"])

    assert residency["sessions_unscheduled_count"] == 8
    assert residency["makeup_credits_outstanding"] == 0
    assert residency["projected_cost_cents"] == 143246, (
        "expected the earned 31454 plus eight lead projections of 13974, got "
        f"{residency['projected_cost_cents']}"
    )
    assert (
        residency["projected_cost_cents"] - residency["earned_to_date_cents"] == 111792
    ), "the two figures must diverge by the eight unfilled allotment units"


# ==========================================================================
# The rolling window versus the program year
# ==========================================================================
def _five_terminal_sessions_for_one_artist() -> dict:
    """Two delivered, two artist-cancelled, then a fifth delivered — five
    terminal artist-attributable sessions inside one program year."""
    set_clock_to_default()
    scenario = setup_active_residency()
    dates = ["2026-09-15", "2026-09-22", "2026-09-29", "2026-10-06", "2026-10-13"]
    sessions = [
        create_confirmed_session(scenario, session_date=date) for date in dates
    ]
    artist_id = scenario["artist"]["id"]
    deliver_session(sessions[0]["id"], artist_id, students_present_count=22)
    deliver_session(sessions[1]["id"], artist_id, students_present_count=24)
    cancel_session_as_coordinator(
        sessions[2]["id"], "ARTIST_ILLNESS", note="artist ill, third week"
    )
    cancel_session_as_coordinator(
        sessions[3]["id"], "ARTIST_ILLNESS", note="artist ill, fourth week"
    )
    deliver_session(sessions[4]["id"], artist_id, students_present_count=25)
    scenario["sessions"] = sessions
    return scenario


def test_rolling_reliability_scores_only_the_four_most_recent_terminal_rows(api):
    """PRD §3.2: "The input set is the artist's *terminal, artist-attributable*
    sessions: rows where the artist is either the currently assigned artist or
    the recorded vacated artist, and whose status is `DELIVERED` or
    `CANCELLED_ARTIST`."
    PRD §3.2: "`reliability_bps_rolling` uses the **four most recent** rows of
    that ordered list, regardless of program year, and it is the only figure that
    can trigger probation."
    PRD §3.2: "Each session in the set is credited one if it was delivered and
    zero otherwise; the figure in basis points is 10000 multiplied by the number
    of credited sessions, divided by the number of sessions in the set, rounded
    half up to a whole number — and it is defined as zero when the set is empty."

    Design: Difficulty/dual_variant_calc/artist_reliability_rolling_window_versus_program_year
    """
    scenario = _five_terminal_sessions_for_one_artist()
    artist = read_artist(scenario["artist"]["id"])
    assert artist["reliability_bps_rolling"] == 5000, (
        "the four most recent rows are two deliveries and two artist "
        f"cancellations, got {artist['reliability_bps_rolling']}"
    )
    assert artist["lifetime_delivered_count"] == 3
    assert artist["no_show_count"] == 0, (
        f"an illness cancellation is not a no-show, got {artist['no_show_count']}"
    )
    assert artist["roster_status"] == "PROBATION", (
        f"a rolling figure below 8000 basis points forces probation, got "
        f"{artist['roster_status']}"
    )


def test_program_year_reliability_scores_every_terminal_row_in_the_year(api):
    """PRD §3.2: "`reliability_bps_program_year` uses **every** terminal session
    whose `session_date` falls in the current program year — the twelve months
    from the first of July of one year through the thirtieth of June of the next,
    whichever such span contains the logical clock date — with no cap on count;
    it feeds tier promotion and funder reporting."
    PRD §3.2: "Whenever more than four terminal sessions exist within the program
    year, the two figures diverge on identical data."
    PRD §3.7: "Link one terminates the session as an artist cancellation with
    `makeup_eligible` true, releases whatever it was holding, subtracts one from
    `sessions_open_count`, and adds one to `makeup_credits_outstanding`; the
    `PLANNED` branch is identical except that there is no held amount to
    release."

    Design: Difficulty/dual_variant_calc/artist_reliability_rolling_window_versus_program_year
    """
    scenario = _five_terminal_sessions_for_one_artist()
    artist = read_artist(scenario["artist"]["id"])
    assert artist["reliability_bps_program_year"] == 6000, (
        "all five terminal rows are in the 2026-07-01..2027-06-30 program year, "
        f"three of them delivered, got {artist['reliability_bps_program_year']}"
    )
    assert (
        artist["reliability_bps_program_year"] - artist["reliability_bps_rolling"]
        == 1000
    ), "the two variants must read the same data differently"

    residency = read_residency(scenario["residency"]["id"])
    assert residency["sessions_delivered_count"] == 3
    assert residency["makeup_credits_outstanding"] == 2, (
        f"both illness cancellations earn a credit, got "
        f"{residency['makeup_credits_outstanding']}"
    )


# ==========================================================================
# Cascade B, from the no-show through to the residency outlook
# ==========================================================================
def _master_artist_on_the_edge_of_probation() -> dict:
    """A MASTER-tier lead with three terminal sessions on record — two
    delivered, one cancelled for illness — and a fourth session still
    confirmed."""
    set_clock_to_default()
    scenario = setup_active_residency(
        artist_overrides={
            "roster_tier_assigned": "MASTER",
            "demo_rubric_score": 4.7,
            "portfolio_reviews": [
                ("panelist-1", 4.5, 4.5, 4.5),
                ("panelist-2", 4.0, 4.0, 4.0),
            ],
        }
    )
    dates = ["2026-09-15", "2026-09-22", "2026-09-29", "2026-10-06"]
    sessions = [
        create_confirmed_session(scenario, session_date=date) for date in dates
    ]
    artist_id = scenario["artist"]["id"]
    deliver_session(sessions[0]["id"], artist_id, students_present_count=22)
    deliver_session(sessions[1]["id"], artist_id, students_present_count=24)
    cancel_session_as_coordinator(
        sessions[2]["id"], "ARTIST_ILLNESS", note="artist ill"
    )
    scenario["sessions"] = sessions
    scenario["artist_before"] = read_artist(artist_id)
    return scenario


def test_no_show_cancellation_raises_the_count_and_recomputes_reliability(api):
    """PRD §3.7: "Link two, caused by the artist-cancellation outcome, adds one
    to the artist's `no_show_count` when and only when the reason was
    `ARTIST_NO_SHOW`, and recomputes both `reliability_bps_rolling` and
    `reliability_bps_program_year`."
    PRD §3.7: "`makeup_eligible` becomes true when the reason is
    `SCHOOL_CLOSURE`, `TESTING_CONFLICT`, `ARTIST_ILLNESS`, or `ARTIST_NO_SHOW`,
    and false when it is `LOW_ENROLLMENT` or `RESIDENCY_DESCOPED`."
    PRD §3.7: "Link three, caused by the rolling figure falling below 8000 basis
    points once the artist has at least four terminal sessions on record, moves
    the artist's `roster_status` from `ACTIVE` to `PROBATION`."

    Design: Difficulty/transitive_cascade/artist_no_show_cascade_reliability_probation_tier_projection
    """
    scenario = _master_artist_on_the_edge_of_probation()
    before = scenario["artist_before"]
    assert before["roster_tier_effective"] == "MASTER"
    assert before["roster_status"] == "ACTIVE", (
        "three terminal sessions is too few to trigger probation, got "
        f"{before['roster_status']}"
    )
    assert before["reliability_bps_rolling"] == 6667, (
        f"expected two of three credited, got {before['reliability_bps_rolling']}"
    )

    cancelled = cancel_session_as_coordinator(
        scenario["sessions"][3]["id"],
        "ARTIST_NO_SHOW",
        note="artist did not arrive",
    )
    assert cancelled["status"] == "CANCELLED_ARTIST"
    assert cancelled["makeup_eligible"] is True
    assert cancelled["encumbered_cents"] == 0, (
        f"the cancellation releases the hold, got {cancelled['encumbered_cents']}"
    )

    artist = read_artist(scenario["artist"]["id"])
    assert artist["no_show_count"] == 1
    assert artist["reliability_bps_rolling"] == 5000, (
        f"expected two of four credited, got {artist['reliability_bps_rolling']}"
    )


def test_probation_caps_the_effective_tier_and_reprices_the_outlook(api):
    """PRD §3.7: "Link four, caused by entering probation, caps
    `roster_tier_effective` at the lower of `roster_tier_assigned` and
    `TEACHING_ARTIST` and re-projects `projected_cost_cents` for every residency
    holding an open session of that artist."
    PRD §3.2: "If the artist is on `PROBATION`, `roster_tier_effective` is the
    lower of `roster_tier_assigned` and `TEACHING_ARTIST`, comparing tiers by
    their rank in the ascending order `APPRENTICE`, then `TEACHING_ARTIST`, then
    `MASTER` — never by alphabetical string order."
    PRD §3.4: "`projected_cost_cents` is the forward-looking figure the program
    director watches against `budget_cents`: it starts from
    `earned_to_date_cents`, adds a full-length fee projection for every session
    of the residency whose status is `PLANNED`, `CONFIRMED`, or `VACATED`, and
    then adds one lead projection for each remaining unscheduled allotment unit
    and each outstanding make-up credit — that is, `sessions_unscheduled_count`
    plus `makeup_credits_outstanding` lead projections."

    Design: Difficulty/transitive_cascade/artist_no_show_cascade_reliability_probation_tier_projection
    """
    scenario = _master_artist_on_the_edge_of_probation()
    cancel_session_as_coordinator(
        scenario["sessions"][3]["id"],
        "ARTIST_NO_SHOW",
        note="artist did not arrive",
    )

    artist = read_artist(scenario["artist"]["id"])
    assert artist["roster_status"] == "PROBATION"
    assert artist["roster_tier_effective"] == "TEACHING_ARTIST", (
        "probation caps a MASTER assignment at TEACHING_ARTIST, got "
        f"{artist['roster_tier_effective']}"
    )

    residency = read_residency(scenario["residency"]["id"])
    assert residency["earned_to_date_cents"] == 36264, (
        f"expected two MASTER-rate deliveries of 18132, got "
        f"{residency['earned_to_date_cents']}"
    )
    assert residency["sessions_unscheduled_count"] == 6
    assert residency["makeup_credits_outstanding"] == 2
    assert residency["sessions_open_count"] == 0
    assert residency["projected_cost_cents"] == 159144, (
        "expected the earned 36264 plus eight capped lead projections of 15360, "
        f"got {residency['projected_cost_cents']}"
    )
    assert residency["encumbered_cents"] == 36264
    assert residency["available_cents"] == 163736
