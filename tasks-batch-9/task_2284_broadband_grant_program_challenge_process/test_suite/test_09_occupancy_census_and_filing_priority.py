"""Location occupancy as a conserved quantity, and window before duplicate."""

from test_helpers import (
    ApiErrorId,
    api_client,
    create_challenge_payload,
    file_challenge,
    obligate_award,
    read_application,
    read_award,
    read_challenge,
    read_location,
    read_program,
    select_application,
    set_clock,
    setup_challenge_open_program,
    setup_scored_application,
    terminate_award,
    validate_error,
    validate_paginated,
)
from test_helpers.fixtures import ADMIN, CHALLENGER

OCCUPANCY_KEYS = ("L2", "L3", "L5")


def _census(location_ids):
    """Count the three occupancy buckets across every location of the program."""
    counts = {"AFFIRMED": 0, "AWARD_BOUND": 0, "DEFERRED_HIGH_COST": 0}
    for location_id in location_ids:
        state = read_location(location_id)["eligibility_state"]
        counts[state] = counts.get(state, 0) + 1
    return counts


def test_obligation_moves_every_retained_location_out_of_the_unbound_pool():
    """Before obligation all three locations sit in the affirmed pool with no
    award; obligation moves exactly those three into the award's bucket, and the
    census still totals the program's whole location inventory.

    PRD 3.1: "The program row also publishes `location_count_total`, the number of
    eligible locations recorded against it across every `eligibility_state`
    value."
    PRD 3.7: "Every retained claim moves to `AWARD_BOUND` and its location moves
    on the eligibility axis to `AWARD_BOUND` with `awarded_award_id` stamped to
    the new award — `AFFIRMED → AWARD_BOUND` for a location the challenge process
    left alone, and `RECLASSIFIED → AWARD_BOUND` for one a sustained challenge
    reclassified, and in both cases only when a claim on that location for this
    application is `CLAIMED_ELIGIBLE` and either its `claimed_cost_cents` is at
    most the extremely-high-cost threshold or the program has disabled the
    waiver."

    Design: Difficulty/compensating_invariant/bound_location_occupancy_identity_across_obligation_and_termination
    """
    ctx = setup_scored_application()
    location_ids = [ctx["location_ids"][k] for k in OCCUPANCY_KEYS]
    select_application(ctx["application_id"])

    assert read_program(ctx["program_id"])["location_count_total"] == 3
    before = _census(location_ids)
    assert before == {"AFFIRMED": 3, "AWARD_BOUND": 0, "DEFERRED_HIGH_COST": 0}
    assert sum(before.values()) == 3

    award = obligate_award(ctx["application_id"])
    after = _census(location_ids)
    assert after == {"AFFIRMED": 0, "AWARD_BOUND": 3, "DEFERRED_HIGH_COST": 0}
    assert sum(after.values()) == read_program(ctx["program_id"])["location_count_total"]

    for location_id in location_ids:
        assert read_location(location_id)["awarded_award_id"] == award["id"]
    assert award["confirmed_location_count"] == 3


def test_termination_returns_exactly_those_locations_and_nothing_else():
    """Termination is the exact inverse of the obligation on the occupancy census:
    the same three locations return to the affirmed pool with their award link
    cleared, every bound claim is released, and the deobligation restores the
    appropriation in full.

    PRD 3.7: "Each released location moves on the eligibility axis
    `AWARD_BOUND → AFFIRMED` and has its `awarded_award_id` cleared to null,
    returning it to the eligible pool; the application moves
    `AWARDED → NOT_SELECTED`; and the program's `scoring_posture` is recomputed on
    the standard rule."
    PRD 3.7: "Every `AWARD_BOUND` claim of the award moves to `RELEASED`, and
    every milestone of the award not already `DISBURSED` — that is, every
    milestone in `PLANNED`, `EVIDENCE_SUBMITTED`, `APPROVED`, `REJECTED` or
    `HELD` — moves to `VOIDED`."

    Design: Difficulty/compensating_invariant/bound_location_occupancy_identity_across_obligation_and_termination
    """
    ctx = setup_scored_application()
    location_ids = [ctx["location_ids"][k] for k in OCCUPANCY_KEYS]
    select_application(ctx["application_id"])
    ctx["award_id"] = obligate_award(ctx["application_id"])["id"]
    bound = _census(location_ids)

    terminated = terminate_award(ctx["award_id"], "Subgrantee withdrew from the build.")
    assert terminated["award_state"] == "TERMINATED"

    released = _census(location_ids)
    assert bound == {"AFFIRMED": 0, "AWARD_BOUND": 3, "DEFERRED_HIGH_COST": 0}
    assert released == {"AFFIRMED": 3, "AWARD_BOUND": 0, "DEFERRED_HIGH_COST": 0}
    assert sum(released.values()) == read_program(ctx["program_id"])["location_count_total"]

    for location_id in location_ids:
        assert read_location(location_id)["awarded_award_id"] is None

    claims, _ = validate_paginated(
        api_client.list_application_location_claims(ctx["application_id"], ADMIN)
    )
    assert {c["claim_state"] for c in claims} == {"RELEASED"}
    assert read_application(ctx["application_id"])["application_state"] == "NOT_SELECTED"
    assert read_award(ctx["award_id"])["confirmed_location_count"] == 3

    entries, meta = validate_paginated(
        api_client.list_ledger_entries(ctx["award_id"], ADMIN)
    )
    assert meta["total_count"] == 2
    assert [(e["entry_type"], e["amount_cents"]) for e in entries] == [
        ("OBLIGATION", 2025003),
        ("DEOBLIGATION", 2025003),
    ]

    program = read_program(ctx["program_id"])
    assert program["obligated_balance_cents"] == 0
    assert program["disbursed_balance_cents"] == 0
    assert program["uncommitted_balance_cents"] == 100000000


def test_a_late_refiling_reports_the_closed_window_not_the_duplicate():
    """The program was never administratively closed, so the phase check passes,
    but the clock has left the half-open challenge window while a live challenge
    from the same filer already exists — and the temporal rule at the lower
    priority is the one reported.

    PRD 2.12: "When more than one rule could reject a request, the rule with the
    lowest priority number wins and its error is the one returned; evaluation
    stops at the first violation."
    PRD 2.12: "24. **Priority 65 — challenge window** →
    `ERR_CHALLENGE_WINDOW_CLOSED`."
    PRD 2.12: "30. **Priority 75 — duplicate challenge** →
    `ERR_DUPLICATE_CHALLENGE`."

    Design: Difficulty/priority_pair_validation_conflict/challenge_window_beats_duplicate_challenge
    """
    ctx = setup_challenge_open_program(("L1",))
    contested = ctx["location_ids"]["L1"]
    first = file_challenge(ctx["program_id"], contested, CHALLENGER)
    assert first["challenge_state"] == "SUBMITTED"

    set_clock("2026-09-06T00:00:00Z")
    late_duplicate = api_client.create_challenge(
        create_challenge_payload(ctx["program_id"], contested), CHALLENGER
    )
    validate_error(late_duplicate, ApiErrorId.ERR_CHALLENGE_WINDOW_CLOSED)

    assert read_program(ctx["program_id"])["program_state"] == "CHALLENGE_OPEN"
    assert read_challenge(first["id"])["challenge_state"] == "SUBMITTED"
    assert read_location(contested)["challenge_count"] == 1


def test_inside_the_window_the_same_refiling_reports_the_duplicate():
    """The duplicate rule is live all along and merely masked by the ordering: the
    identical second filing, made while the clock is still inside the window, is
    refused as a duplicate.

    PRD 3.2: "At most one non-terminal challenge may exist for a given pairing of
    contested location and filing identity, so a second live filing by the same
    party against the same location is refused with `ERR_DUPLICATE_CHALLENGE`."
    PRD 3.2: "Filing outside the window is refused with
    `ERR_CHALLENGE_WINDOW_CLOSED`; a challenged location belonging to a different
    program than the one named is refused with `ERR_PROGRAM_SCOPE_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/challenge_window_beats_duplicate_challenge
    """
    ctx = setup_challenge_open_program(("L1",))
    contested = ctx["location_ids"]["L1"]
    first = file_challenge(ctx["program_id"], contested, CHALLENGER)

    duplicate = api_client.create_challenge(
        create_challenge_payload(ctx["program_id"], contested), CHALLENGER
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_CHALLENGE)

    assert read_challenge(first["id"])["challenge_state"] == "SUBMITTED"
    assert read_location(contested)["challenge_count"] == 1
