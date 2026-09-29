"""Interval semantics: half-open session windows and closed coverage intervals.

The API compares two different kinds of interval with two deliberately
different conventions. A neutral's session calendar is half-open and the
requested window is padded by a turnaround allowance before the comparison,
while a policy's coverage terms are closed on both ends with no padding at all.
Each pair of tests below probes the boundary instant on both sides of one of
those conventions, so a boundary treated the other way round cannot pass.
"""

from test_helpers import (
    ApiErrorId,
    CANONICAL_STRUCTURAL_TERM_END_DATE,
    INSURER_PERIOD_INSTANT,
    adjudicate_claim,
    assert_coverage_term,
    assert_escalation_case,
    assert_same_instant,
    create_coverage_term_payload,
    create_escalation_payload,
    file_claim,
    file_structural_assessment,
    find_term,
    investigate_claim,
    make_homeowner_headers,
    read_claim,
    read_coverage_terms,
    read_neutral,
    read_policy,
    route_claim,
    set_clock,
    setup_active_policy,
    setup_mediation_case,
    validate_error,
    validate_paginated,
    validate_success,
)

# The first session is booked from 14:00 to 16:00 UTC on 2028-09-10.
BOOKED_WINDOW_START = "2028-09-10T14:00:00Z"
BOOKED_WINDOW_END = "2028-09-10T16:00:00Z"


def _panel_world_with_one_booked_session():
    """One neutral carrying a single mediation session from 14:00 to 16:00, and
    a second denied claim on the same home whose owner is about to ask for a
    second session with the same neutral."""
    scenario = setup_mediation_case(
        neutral_overrides={"full_name": "Rosalind Okafor", "credential": "BOTH"},
        window_start=BOOKED_WINDOW_START,
        window_end=BOOKED_WINDOW_END,
    )
    set_clock(INSURER_PERIOD_INSTANT)
    second = file_claim(
        scenario["policy"]["id"], scenario["homeowner"]["id"],
        coverage_type="STRUCTURAL", defect_category="STRUCTURAL_CRACKING",
        claimed_amount_cents=700_000,
        damage_description="Diagonal cracking above the garage header",
    )
    investigate_claim(second["id"], 1.00)
    # PRD 3.6: a STRUCTURAL_CRACKING allegation cannot be adjudicated at all
    # until at least one engineering assessment is on file, so the denial that
    # puts the claim in reach of the escalation ladder needs one first.
    file_structural_assessment(second["id"], affected_elements=["FOUNDATION_WALL"],
                               deflection_ratio=0.0100,
                               load_bearing_affected=True)
    route_claim(second["id"])
    adjudicate_claim(second["id"], "DENY",
                     adjudication_note="damage predates the coverage term")
    scenario["second_claim"] = read_claim(second["id"])
    scenario["neutral"] = read_neutral(scenario["neutral"]["id"])
    return scenario


def _second_booking_response(api, scenario, window_start, window_end):
    return api.create_escalation(
        scenario["second_claim"]["id"],
        create_escalation_payload(scenario["neutral"]["id"], "MEDIATION",
                                  window_start, window_end),
        make_homeowner_headers(scenario["homeowner"]["id"]),
    )


# --------------------------------------------------------------------------
# Session windows: half-open, but widened by 120 minutes on both sides
# --------------------------------------------------------------------------
def test_session_starting_when_another_ends_still_conflicts_through_the_turnaround(
        api, underwriting_officer_headers):
    """PRD §3.9: "The requested session window is treated as **half-open** — it
    includes its start instant and excludes its end instant, so a window that
    begins at the exact instant another ends does not by itself overlap it."
    PRD §3.9: "Before comparing, the requested window is **widened by a
    turnaround allowance of 120 minutes on both sides**, giving the neutral two
    hours of travel and preparation either side of a session."
    PRD §3.9: "If that widened window overlaps any other escalation-case window
    already booked on the same neutral, the request is refused with
    `ERR_NEUTRAL_WINDOW_CONFLICT`."

    A request for 16:00 to 18:00 begins exactly when the booked 14:00-to-16:00
    session ends, so the bare interval would not overlap; widened by the
    turnaround it runs 14:00 to 20:00 and does.

    Design: Difficulty/resource_temporal_overlap/neutral_session_windows_are_half_open_but_widened_by_a_two_hour_turnaround
    """
    scenario = _panel_world_with_one_booked_session()
    neutral_before = scenario["neutral"]
    assert neutral_before["booked_session_count"] == 1, (
        f"one session must already be booked, got {neutral_before['booked_session_count']}"
    )
    assert scenario["second_claim"]["status"] == "DENIED", (
        "the second claim must be denied so the booking reaches the calendar check, "
        f"got {scenario['second_claim']['status']}"
    )

    response = _second_booking_response(
        api, scenario, "2028-09-10T16:00:00Z", "2028-09-10T18:00:00Z")
    validate_error(response, ApiErrorId.ERR_NEUTRAL_WINDOW_CONFLICT.value)

    neutral_after = read_neutral(neutral_before["id"])
    assert neutral_after["booked_session_count"] == 1, (
        "a refused booking must not increment the counter, got "
        f"{neutral_after['booked_session_count']}"
    )
    assert neutral_after["version"] == neutral_before["version"], (
        "a refused booking must not advance the neutral's version"
    )
    cases, meta = validate_paginated(
        api.list_escalation_cases(underwriting_officer_headers,
                                  {"neutral_id": neutral_before["id"], "limit": 100})
    )
    assert meta["total_count"] == 1, (
        f"the refused booking must not create a case, got {meta['total_count']}"
    )
    assert read_claim(scenario["second_claim"]["id"])["status"] == "DENIED", (
        "a refused booking must leave the claim in DENIED"
    )


def test_session_two_hours_clear_of_the_turnaround_is_booked(
        api, underwriting_officer_headers):
    """PRD §3.9: "The requested session window is treated as **half-open** — it
    includes its start instant and excludes its end instant, so a window that
    begins at the exact instant another ends does not by itself overlap it."
    PRD §3.9: "Before comparing, the requested window is **widened by a
    turnaround allowance of 120 minutes on both sides**, giving the neutral two
    hours of travel and preparation either side of a session."
    PRD §3.9: "The booked neutral's `booked_session_count` is incremented by 1
    and its `version` advances by 1; that counter is the number of escalation
    cases naming this neutral whose `status` is `SCHEDULED`, `SETTLED`,
    `IMPASSE` or `AWARD_ISSUED`."

    The exclusive edge: a request for 18:00 to 20:00 widens to 16:00 to 22:00,
    which begins at the exact instant the booked session ends and therefore
    does not overlap it.

    Design: Difficulty/resource_temporal_overlap/neutral_session_windows_are_half_open_but_widened_by_a_two_hour_turnaround
    """
    scenario = _panel_world_with_one_booked_session()
    neutral_before = scenario["neutral"]

    response = _second_booking_response(
        api, scenario, "2028-09-10T18:00:00Z", "2028-09-10T20:00:00Z")
    case = validate_success(response, 201)
    assert_escalation_case(case)
    assert case["claim_id"] == scenario["second_claim"]["id"]
    assert case["neutral_id"] == neutral_before["id"]
    assert case["stage"] == "MEDIATION"
    assert case["status"] == "SCHEDULED", f"expected SCHEDULED, got {case['status']}"
    assert case["binding"] is False, "a mediation case is not binding"
    assert_same_instant(case["window_start"], "2028-09-10T18:00:00Z")
    assert_same_instant(case["window_end"], "2028-09-10T20:00:00Z")

    neutral_after = read_neutral(neutral_before["id"])
    assert neutral_after["booked_session_count"] == 2, (
        f"the accepted booking must be counted, got {neutral_after['booked_session_count']}"
    )
    assert neutral_after["version"] == neutral_before["version"] + 1
    cases, meta = validate_paginated(
        api.list_escalation_cases(underwriting_officer_headers,
                                  {"neutral_id": neutral_before["id"], "limit": 100})
    )
    assert meta["total_count"] == 2, (
        f"both sessions must be on the neutral's calendar, got {meta['total_count']}"
    )
    assert read_claim(scenario["second_claim"]["id"])["status"] == "MEDIATION", (
        "the first rung advances the claim DENIED -> MEDIATION"
    )


# --------------------------------------------------------------------------
# Coverage terms: closed on both ends, with no buffer, scoped per coverage type
# --------------------------------------------------------------------------
def test_endorsement_starting_on_the_last_day_of_an_existing_term_is_refused(
        api, underwriting_officer_headers):
    """PRD §3.3: "And an endorsement may not overlap any existing term of the
    same `coverage_type` on that policy: both intervals are treated as closed on
    both ends with no buffer whatsoever, so an endorsement that merely touches
    an existing term of the same type — beginning on the very day the existing
    term ends — is a conflict, and the request is refused with
    `ERR_COVERAGE_TERM_OVERLAP`."

    The inclusive edge: the base structural term ends on 2036-08-14 and an
    endorsement of the same type beginning that very day shares exactly one day
    with it.

    Design: Difficulty/resource_temporal_overlap/endorsement_coverage_terms_are_closed_intervals_so_a_touching_start_date_overlaps
    """
    scenario = setup_active_policy()
    policy = scenario["policy"]
    structural_base = scenario["structural_term"]
    assert structural_base["end_date"] == CANONICAL_STRUCTURAL_TERM_END_DATE
    assert policy["coverage_status"] == "ACTIVE"

    response = api.create_coverage_term(
        policy["id"],
        create_coverage_term_payload(
            coverage_type="STRUCTURAL",
            start_date=CANONICAL_STRUCTURAL_TERM_END_DATE,
            end_date="2038-08-13",
            limit_cents=10_000_000,
            deductible_cents=250_000,
        ),
        underwriting_officer_headers,
    )
    validate_error(response, ApiErrorId.ERR_COVERAGE_TERM_OVERLAP.value)

    terms = read_coverage_terms(policy["id"])
    assert len(terms) == 3, (
        f"the refused endorsement must not be attached, got {len(terms)} terms"
    )
    assert read_policy(policy["id"])["version"] == policy["version"], (
        "a refused endorsement must not advance the policy's version"
    )


def test_endorsement_starting_the_day_after_an_existing_term_ends_is_attached(
        api, underwriting_officer_headers):
    """PRD §3.3: "And an endorsement may not overlap any existing term of the
    same `coverage_type` on that policy: both intervals are treated as closed on
    both ends with no buffer whatsoever, so an endorsement that merely touches
    an existing term of the same type — beginning on the very day the existing
    term ends — is a conflict, and the request is refused with
    `ERR_COVERAGE_TERM_OVERLAP`."
    PRD §3.3: "The new term is born with `term_kind` `ENDORSEMENT`, `status`
    `OPEN`, `consumed_limit_cents` of 0 and `remaining_limit_cents` equal to its
    `limit_cents`, and the policy's `version` advances by 1."

    The exclusive edge: one day later there is no shared day, and because the
    convention carries no buffer whatsoever a single day of separation is
    enough.

    Design: Difficulty/resource_temporal_overlap/endorsement_coverage_terms_are_closed_intervals_so_a_touching_start_date_overlaps
    """
    scenario = setup_active_policy()
    policy = scenario["policy"]
    assert scenario["structural_term"]["end_date"] == CANONICAL_STRUCTURAL_TERM_END_DATE

    response = api.create_coverage_term(
        policy["id"],
        create_coverage_term_payload(
            coverage_type="STRUCTURAL",
            start_date="2036-08-15",
            end_date="2038-08-13",
            limit_cents=10_000_000,
            deductible_cents=250_000,
        ),
        underwriting_officer_headers,
    )
    term = validate_success(response, 201)
    assert_coverage_term(term)
    assert term["policy_id"] == policy["id"]
    assert term["coverage_type"] == "STRUCTURAL"
    assert term["term_kind"] == "ENDORSEMENT", (
        f"an attached term is an endorsement, got {term['term_kind']}"
    )
    assert term["status"] == "OPEN", f"expected OPEN, got {term['status']}"
    assert term["start_date"] == "2036-08-15"
    assert term["end_date"] == "2038-08-13"
    assert term["limit_cents"] == 10_000_000
    assert term["deductible_cents"] == 250_000
    assert term["consumed_limit_cents"] == 0
    assert term["remaining_limit_cents"] == 10_000_000

    assert len(read_coverage_terms(policy["id"])) == 4
    assert read_policy(policy["id"])["version"] == policy["version"] + 1, (
        "attaching an endorsement advances the policy's version by 1"
    )


def test_endorsement_of_another_coverage_type_may_share_the_same_days(
        api, underwriting_officer_headers):
    """PRD §3.3: "And an endorsement may not overlap any existing term of the
    same `coverage_type` on that policy: both intervals are treated as closed on
    both ends with no buffer whatsoever, so an endorsement that merely touches
    an existing term of the same type — beginning on the very day the existing
    term ends — is a conflict, and the request is refused with
    `ERR_COVERAGE_TERM_OVERLAP`."
    PRD §3.3: "Terms of a *different* coverage type may overlap freely."

    The same start date that conflicts for a structural endorsement is accepted
    for a workmanship one, because the closed-interval comparison is scoped to
    terms of the same coverage type.

    Design: Difficulty/resource_temporal_overlap/endorsement_coverage_terms_are_closed_intervals_so_a_touching_start_date_overlaps
    """
    scenario = setup_active_policy()
    policy = scenario["policy"]
    workmanship_base = find_term(read_coverage_terms(policy["id"]),
                                 "WORKMANSHIP", "BASE")
    assert workmanship_base["end_date"] < CANONICAL_STRUCTURAL_TERM_END_DATE, (
        "the workmanship base term must end before the structural one, so the "
        "endorsement below can only collide with a term of a different type"
    )

    response = api.create_coverage_term(
        policy["id"],
        create_coverage_term_payload(
            coverage_type="WORKMANSHIP",
            start_date=CANONICAL_STRUCTURAL_TERM_END_DATE,
            end_date="2038-08-13",
            limit_cents=4_000_000,
            deductible_cents=100_000,
        ),
        underwriting_officer_headers,
    )
    term = validate_success(response, 201)
    assert_coverage_term(term)
    assert term["coverage_type"] == "WORKMANSHIP"
    assert term["term_kind"] == "ENDORSEMENT"
    assert term["status"] == "OPEN"
    assert term["start_date"] == CANONICAL_STRUCTURAL_TERM_END_DATE
    assert term["remaining_limit_cents"] == 4_000_000
    assert len(read_coverage_terms(policy["id"])) == 4
