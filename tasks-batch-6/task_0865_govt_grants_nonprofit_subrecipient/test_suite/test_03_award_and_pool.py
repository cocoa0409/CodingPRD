"""Award decision gates, subaward creation, and NOFO pool conservation."""
from test_helpers import (
    validate_success,
    validate_error,
    create_nonprofit,
    create_nofo,
    create_scored_application,
    award_and_get_subaward,
    get_nofo,
    make_program_officer_headers,
)


def test_award_over_max_award_rejected(api):
    """PRD §3.4: "Next, the `requested_amount_cents` must not exceed the opportunity's
    `max_award_cents`, or the award is rejected with `ERR_MAX_AWARD_EXCEEDED`."

    Design: Corner/validations/award_over_max_award_rejected
    """
    np = create_nonprofit()
    nofo = create_nofo(total_pool_cents=100_000_000, max_award_cents=50_000_000)
    app = create_scored_application(nofo["id"], np["id"], requested_amount_cents=60_000_000)
    res = api.award_application(app["id"], make_program_officer_headers())
    validate_error(res, "ERR_MAX_AWARD_EXCEEDED")


def test_award_with_near_period_overlap_rejected(api):
    """PRD §3.4: "the applicant nonprofit must not already hold another non-terminal subaward
    under the same opportunity whose performance period overlaps the proposed period; overlap
    is measured as a closed interval widened by a thirty-day gap on each side, so two periods
    that come within thirty days of touching are treated as overlapping and the award is
    rejected with ERR_PERIOD_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/subaward_period_gap_buffer_overlap
    """
    np = create_nonprofit()
    nofo = create_nofo()
    app1 = create_scored_application(
        nofo["id"], np["id"],
        proposed_period_start="2026-06-01T00:00:00Z", proposed_period_end="2026-12-31T00:00:00Z",
    )
    validate_success(api.award_application(app1["id"], make_program_officer_headers()), 200)

    app2 = create_scored_application(
        nofo["id"], np["id"], scores=(70, 75, 88),
        proposed_period_start="2027-01-15T00:00:00Z", proposed_period_end="2027-06-30T00:00:00Z",
    )
    res = api.award_application(app2["id"], make_program_officer_headers())
    validate_error(res, "ERR_PERIOD_OVERLAP")


def test_award_with_period_beyond_gap_buffer_allowed(api):
    """PRD §3.4: "overlap is measured as a closed interval widened by a thirty-day gap on each
    side, so two periods that come within thirty days of touching are treated as overlapping
    and the award is rejected with ERR_PERIOD_OVERLAP."

    A second period starting well beyond the thirty-day buffer does not overlap and is awarded.

    Design: Difficulty/resource_temporal_overlap/subaward_period_gap_buffer_overlap
    """
    np = create_nonprofit()
    nofo = create_nofo()
    app1 = create_scored_application(
        nofo["id"], np["id"],
        proposed_period_start="2026-06-01T00:00:00Z", proposed_period_end="2026-12-31T00:00:00Z",
    )
    validate_success(api.award_application(app1["id"], make_program_officer_headers()), 200)

    app2 = create_scored_application(
        nofo["id"], np["id"], scores=(70, 75, 88),
        proposed_period_start="2027-03-01T00:00:00Z", proposed_period_end="2027-08-31T00:00:00Z",
    )
    awarded = validate_success(api.award_application(app2["id"], make_program_officer_headers()), 200)
    assert awarded["status"] == "AWARDED"


def test_award_debits_remaining_pool(api):
    """PRD §3.4: "On a successful award the system sets the application's awarded_amount_cents
    equal to its requested_amount_cents, debits the opportunity's remaining_pool_cents by that
    same amount, and creates a Subaward in DRAFT."

    Design: Difficulty/compensating_invariant/pool_conserved_across_award_then_terminate_draft
    """
    np = create_nonprofit()
    nofo = create_nofo(total_pool_cents=100_000_000)
    app = create_scored_application(nofo["id"], np["id"], requested_amount_cents=11_000_000)
    validate_success(api.award_application(app["id"], make_program_officer_headers()), 200)

    refreshed = get_nofo(nofo["id"])
    assert refreshed["remaining_pool_cents"] == 100_000_000 - 11_000_000


def test_terminate_draft_subaward_restores_pool(api):
    """PRD §3.9: "Terminating a DRAFT subaward — one that was awarded but never activated —
    moves it to TERMINATED and credits the opportunity's remaining_pool_cents back by the
    application's awarded_amount_cents, reversing the award debit under the pool-conservation
    invariant."

    Design: Difficulty/compensating_invariant/pool_conserved_across_award_then_terminate_draft
    """
    np = create_nonprofit()
    nofo = create_nofo(total_pool_cents=100_000_000)
    app = create_scored_application(nofo["id"], np["id"], requested_amount_cents=11_000_000)
    sub = award_and_get_subaward(app["id"])

    terminated = validate_success(
        api.terminate_subaward(sub["id"], {"reason": "withdrawn"}, make_program_officer_headers()),
        200,
    )
    assert terminated["status"] == "TERMINATED"
    refreshed = get_nofo(nofo["id"])
    assert refreshed["remaining_pool_cents"] == 100_000_000
