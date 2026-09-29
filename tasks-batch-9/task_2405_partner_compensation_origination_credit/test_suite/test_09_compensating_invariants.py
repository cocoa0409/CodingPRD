"""Compensating actions: a void that restores percentage-point capacity on a
matter, and a reopen that restores cash cents on an append-only draw ledger."""

from test_helpers import (
    advance_cycle,
    allocate_origination_credit,
    approx2,
    create_credit_arbiter,
    create_cycle,
    create_matter,
    create_partner,
    draw_ledger,
    effectuate_transition,
    find_allocation,
    get_success_data,
    make_cycle_admin_headers,
    matter_allocations,
    notice_of_departure_payload,
    pay_draw,
    post_financials,
    read_award,
    read_cycle,
    read_matter,
    read_partner,
    read_transition,
    setup_published_discretionary_award,
    void_transition,
)

VOID_REASON = "The departure was withdrawn for this client relationship."


def _two_staged_transitions_for_one_departing_partner(api):
    """Partner A originates two matters at 100.00 each and gives notice, so two
    transitions sit in PROPOSED; voiding the first stays legal because the second
    keeps A in NOTICE_GIVEN."""
    cycle = create_cycle(api)
    departing = create_partner(api, full_name="Ada Origin", compensation_model="FORMULA")
    successor = create_partner(
        api,
        full_name="Stan Staying",
        compensation_model="FORMULA",
        admission_year=2014,
    )
    arbiter = create_credit_arbiter(api, full_name="Rex Arbiter", practice_group="REGULATORY")
    first = create_matter(
        api,
        billing_attorney_id=departing["id"],
        responsible_attorney_id=departing["id"],
        client_key="CLI-V1",
        client_display_name="Void Ventures",
        opened_on="2026-01-15",
    )
    post_financials(
        api,
        first["id"],
        billed_delta_cents=400_000,
        collected_delta_cents=400_000,
        direct_cost_delta_cents=0,
    )
    second = create_matter(
        api,
        billing_attorney_id=departing["id"],
        responsible_attorney_id=departing["id"],
        client_key="CLI-V2",
        client_display_name="Second Ventures",
        opened_on="2026-02-01",
    )
    for matter in (first, second):
        allocate_origination_credit(
            api,
            cycle_id=cycle["id"],
            matter_id=matter["id"],
            claimant_id=departing["id"],
            arbiter_id=arbiter["id"],
            approved_pct=100.00,
        )
    admin = make_cycle_admin_headers()
    get_success_data(
        api.notice_of_departure(
            departing["id"], notice_of_departure_payload("2026-12-31"), admin
        )
    )
    transitions = get_success_data(
        api.list_credit_transitions(admin, {"departing_partner_id": departing["id"]})
    )
    assert len(transitions) == 2
    return {
        "cycle": cycle,
        "departing": departing,
        "successor": successor,
        "arbiter": arbiter,
        "first": first,
        "second": second,
        "first_transition": next(
            row for row in transitions if row["matter_id"] == first["id"]
        ),
        "second_transition": next(
            row for row in transitions if row["matter_id"] == second["id"]
        ),
    }


def test_the_void_returns_the_hundred_points_to_the_departing_partner(api):
    """PRD 3.4: "The matter's `origination_pct_assigned` reports the total
    `credit_pct` currently in force across originating allocations in `ACTIVE`, and
    it is the conserved figure that an effectuate-then-void pair must leave
    unchanged."

    Design: Difficulty/compensating_invariant/matter_origination_pct_conserved_across_effectuate_and_void
    """
    scenario = _two_staged_transitions_for_one_departing_partner(api)
    matter_id = scenario["first"]["id"]
    transition_id = scenario["first_transition"]["id"]
    departing_id = scenario["departing"]["id"]
    successor_id = scenario["successor"]["id"]
    assert scenario["first_transition"]["prior_credit_pct"] == approx2(100.00)
    assert read_matter(api, matter_id)["origination_pct_assigned"] == approx2(100.00)

    effectuate_transition(
        api,
        transition_id=transition_id,
        successor_partner_id=successor_id,
        effective_on="2026-09-01",
        matter_id=matter_id,
    )
    assert read_matter(api, matter_id)["origination_pct_assigned"] == approx2(100.00)

    voided = void_transition(
        api, transition_id=transition_id, void_reason=VOID_REASON, matter_id=matter_id
    )

    assert voided["state"] == "VOIDED"
    assert voided["void_reason"] == VOID_REASON
    assert read_transition(api, transition_id)["state"] == "VOIDED"
    assert read_matter(api, matter_id)["origination_pct_assigned"] == approx2(100.00)

    rows = matter_allocations(api, matter_id, credit_role="ORIGINATING")
    assert len(rows) == 2
    restored = find_allocation(rows, "ORIGINATING", departing_id)
    superseded = find_allocation(rows, "ORIGINATING", successor_id)
    assert restored["state"] == "ACTIVE"
    assert restored["credit_pct"] == approx2(100.00)
    assert restored["credit_from"] == "2026-01-15"
    assert restored["credit_through"] is None
    assert superseded["state"] == "SUPERSEDED"
    assert superseded["credit_through"] == "2026-09-01"
    assert read_partner(api, successor_id)["credited_collection_provisional_cents"] == 0


def test_the_void_hands_the_responsible_role_back_and_clears_its_snapshot(api):
    """PRD 3.1: "The matter's `responsible_attorney_id` is restored from
    `prior_responsible_attorney_id`, that snapshot is then cleared,
    `origination_pct_assigned` is recomputed back to exactly its pre-effectuation
    value, and the matter's `version` increments; the credited-collection chain
    then re-runs down through both partners' totals, their
    `formula_score_provisional` and `formula_score_final`, and the cycle's
    `total_formula_score`."

    Design: Difficulty/compensating_invariant/matter_origination_pct_conserved_across_effectuate_and_void
    """
    scenario = _two_staged_transitions_for_one_departing_partner(api)
    matter_id = scenario["first"]["id"]
    transition_id = scenario["first_transition"]["id"]
    departing_id = scenario["departing"]["id"]
    successor_id = scenario["successor"]["id"]

    before = read_matter(api, matter_id)
    assert before["responsible_attorney_id"] == departing_id
    assert before["prior_responsible_attorney_id"] is None
    collections_before = read_partner(api, departing_id)[
        "credited_collection_provisional_cents"
    ]
    total_before = read_cycle(api, scenario["cycle"]["id"])["total_formula_score"]

    effectuate_transition(
        api,
        transition_id=transition_id,
        successor_partner_id=successor_id,
        effective_on="2026-09-01",
        matter_id=matter_id,
    )
    mid = read_matter(api, matter_id)
    assert mid["responsible_attorney_id"] == successor_id
    assert mid["prior_responsible_attorney_id"] == departing_id

    void_transition(
        api, transition_id=transition_id, void_reason=VOID_REASON, matter_id=matter_id
    )

    after = read_matter(api, matter_id)
    assert after["responsible_attorney_id"] == departing_id
    assert after["prior_responsible_attorney_id"] is None
    assert (
        read_partner(api, departing_id)["credited_collection_provisional_cents"]
        == collections_before
    )
    assert read_cycle(api, scenario["cycle"]["id"])["total_formula_score"] == total_before
    assert read_partner(api, departing_id)["status"] == "NOTICE_GIVEN"
    assert read_transition(api, scenario["second_transition"]["id"])["state"] == "PROPOSED"


def test_the_reopen_puts_every_drawn_cent_back_in_the_cycle(api):
    """PRD 3.8: "Those appends drive each award's `draw_paid_cents` back to 0 and
    its payment state back to `PENDING`, which drives each partner's
    `ytd_draw_paid_cents` back to its pre-draw value and the cycle's
    `undistributed_cash_cents` back to the full `distributable_pool_cents` — the
    conserved quantity the whole reversal exists to protect."

    Design: Difficulty/compensating_invariant/cycle_undistributed_cash_conserved_across_draw_and_reopen
    """
    bundle = setup_published_discretionary_award(
        api, subject_overrides={"target_capital_cents": 30_000_000}
    )
    cycle_id = bundle["cycle"]["id"]
    award_id = bundle["award"]["id"]
    subject_id = bundle["subject"]["id"]
    assert bundle["award"]["target_award_cents"] == 20_000_000
    assert read_cycle(api, cycle_id)["undistributed_cash_cents"] == 100_000_000

    pay_draw(api, award_id, period_year=2026, period_month=1)
    pay_draw(api, award_id, period_year=2026, period_month=2)
    assert read_cycle(api, cycle_id)["undistributed_cash_cents"] == 97_333_334
    assert read_partner(api, subject_id)["ytd_draw_paid_cents"] == 2_666_666

    reopened = advance_cycle(api, cycle_id, "DELIBERATION")

    assert reopened["state"] == "DELIBERATION"
    assert reopened["undistributed_cash_cents"] == 100_000_000
    assert reopened["reopen_count"] == 1
    assert read_partner(api, subject_id)["ytd_draw_paid_cents"] == 0
    award = read_award(api, award_id)
    assert award["draw_paid_cents"] == 0
    assert award["award_state"] == "PROPOSED"
    assert award["payment_state"] == "PENDING"
    assert award["reconsideration_count"] == 1


def test_the_reversal_appends_rather_than_deletes_the_paid_draws(api):
    """PRD 3.8: "For every award of the cycle, one ledger row of kind
    `DRAW_REVERSAL` is appended for each un-reversed scheduled draw, copying that
    draw's `period_year` and `period_month` and carrying `amount_cents` equal to
    the negation of that draw's `amount_cents`, the draws being processed in order
    of `period_year` ascending, then `period_month` ascending, then `created_at`
    ascending; each reversed scheduled draw has its `reversed` flag set to true,
    and a reversed draw no longer occupies its period bucket."

    Design: Difficulty/compensating_invariant/cycle_undistributed_cash_conserved_across_draw_and_reopen
    """
    bundle = setup_published_discretionary_award(
        api, subject_overrides={"target_capital_cents": 30_000_000}
    )
    award_id = bundle["award"]["id"]
    pay_draw(api, award_id, period_year=2026, period_month=1)
    pay_draw(api, award_id, period_year=2026, period_month=2)
    assert len(draw_ledger(api, award_id)) == 2

    advance_cycle(api, bundle["cycle"]["id"], "DELIBERATION")

    rows = draw_ledger(api, award_id)
    assert len(rows) == 4
    scheduled = [row for row in rows if row["kind"] == "SCHEDULED_DRAW"]
    reversals = [row for row in rows if row["kind"] == "DRAW_REVERSAL"]
    assert len(scheduled) == 2
    assert len(reversals) == 2
    assert all(row["amount_cents"] == 1_333_333 for row in scheduled)
    assert all(row["reversed"] is True for row in scheduled)
    assert all(row["amount_cents"] == -1_333_333 for row in reversals)
    assert [row["period_month"] for row in reversals] == [1, 2]
    assert all(row["period_year"] == 2026 for row in rows)
    assert sum(row["amount_cents"] for row in rows) == 0
