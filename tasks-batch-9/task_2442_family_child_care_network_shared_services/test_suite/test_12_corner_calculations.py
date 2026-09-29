"""Deterministic selection, scoring and money arithmetic."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    COACH_B_HEADERS,
    FISCAL_OFFICER_HEADERS,
    NETWORK_ADMIN_HEADERS,
    accept_assignment,
    active_provider,
    claim_line,
    claim_walked_to,
    contract_version,
    create_claim,
    create_enrollment,
    create_substitute,
    post_remittance,
    provider_with_contract,
    request_coverage,
    schedule_visit,
    set_clock,
)

# Local setup builders


def _pool_home_with_three_members():
    """An ACTIVE home and three members: 2200, then another 2200, then 2500."""
    ctx = active_provider(
        apply_overrides={"county_tier": "STANDARD", "capacity_slots": 6},
        agreement_overrides={"shared_services": ["SUBSTITUTE_POOL"]},
    )
    ctx["s_b"] = create_substitute(
        full_name="Bea Ramirez",
        credential_level="NONE",
        clearance_expires_on="2026-12-31T00:00:00Z",
        hourly_rate_cents=2200,
        service_county_tiers=["STANDARD"],
    )["id"]
    ctx["s_c"] = create_substitute(
        full_name="Cleo Danner",
        credential_level="NONE",
        clearance_expires_on="2026-12-31T00:00:00Z",
        hourly_rate_cents=2200,
        service_county_tiers=["STANDARD"],
    )["id"]
    ctx["s_a"] = create_substitute(
        full_name="Ada Nkemelu",
        credential_level="NONE",
        clearance_expires_on="2026-12-31T00:00:00Z",
        hourly_rate_cents=2500,
        service_county_tiers=["STANDARD"],
    )["id"]
    return ctx


def _billing_home_with_one_subsidy_child(**contract_overrides):
    """An ACTIVE home with a subsidy contract and a single certified child."""
    overrides = {
        "daily_rate_cents": 4500,
        "contracted_slots": 4,
        "authorized_amount_cents": 5000000,
        "period_start_on": "2026-08-01T00:00:00Z",
        "absence_rate_pct": 50,
    }
    overrides.update(contract_overrides)
    ctx = provider_with_contract(
        apply_overrides={"capacity_slots": 6, "fixed_monthly_cost_cents": 237000},
        agreement_overrides={"shared_services": ["ENROLLMENT", "BILLING"]},
        contract_overrides=overrides,
    )
    ctx["e1"] = create_enrollment(
        ctx["provider_id"],
        child_ref="CH-1",
        family_name="Alvarez",
        days_per_week=5,
        private_monthly_tuition_cents=0,
        subsidy_certified=True,
        start_on=overrides["period_start_on"],
    )["id"]
    return ctx


# Selection and scoring


def test_the_selector_walks_rate_then_workload_then_tenure(api):
    """The cheaper of two tied members wins on tenure, then the other wins on workload.

    Both 2200-cent members outrank the 2500-cent member on the first key, and they tie on
    the second, so the earlier-created one takes the first offer. Once that member has one
    completed job the second key separates them, so the identical request goes to the other
    2200-cent member. The dearer member is never picked while a cheaper candidate survives.

    PRD: "Among the surviving candidates, the winner is chosen by cheapest first —
    `hourly_rate_cents` ascending — then by fewest completed jobs,
    `assignment_count_completed` ascending, then by longest tenure in the pool, `created_at`
    ascending."

    Design: Corner/Calculations/substitute_selection_applies_all_three_ranking_keys_in_order
    """
    ctx = _pool_home_with_three_members()

    first = request_coverage(
        ctx["provider_id"],
        "2026-08-05T08:00:00Z",
        "2026-08-05T12:00:00Z",
        reason="ILLNESS",
        min_credential_level="NONE",
    )
    assert first["substitute_id"] == ctx["s_b"]

    accept_assignment(first["id"], ctx["s_b"])
    set_clock("2026-08-05T12:00:00Z")
    validate_success(api.complete_assignment(first["id"], None, ctx["headers"]))

    worked = validate_success(api.get_substitute(ctx["s_b"], NETWORK_ADMIN_HEADERS))
    assert worked["assignment_count_completed"] == 1

    second = request_coverage(
        ctx["provider_id"],
        "2026-08-06T08:00:00Z",
        "2026-08-06T12:00:00Z",
        reason="ILLNESS",
        min_credential_level="NONE",
    )
    assert second["substitute_id"] == ctx["s_c"]
    assert second["staffing_status"] == "OFFERED"
    assert first["substitute_id"] != ctx["s_a"]
    assert second["substitute_id"] != ctx["s_a"]


def test_a_visit_still_on_the_calendar_never_enters_the_quality_score(api):
    """One observation of 60 and one unconducted booking give a score of exactly 60.00.

    A single completed visit renormalises its own weight, so the score is the observation
    itself and the band is TIER_3. The second visit is still SCHEDULED with a null
    observation, and were it counted at all no arithmetic could land on 60.00.

    PRD: "The provider's coaching visits in `COMPLETED` status — visits still `SCHEDULED`
    never count towards either variant — are ordered by `visit_conducted_on` descending and
    then by `created_at` descending, and at most the first three are taken."

    Design: Corner/Calculations/quality_score_input_set_excludes_scheduled_visits
    """
    ctx = active_provider(
        apply_overrides={"capacity_slots": 6},
        agreement_overrides={"shared_services": ["ENROLLMENT"]},
    )
    first = schedule_visit(
        ctx["provider_id"], "2026-08-01T00:00:00Z", focus_area="ENVIRONMENT"
    )
    second = schedule_visit(
        ctx["provider_id"], "2026-09-15T00:00:00Z", focus_area="CURRICULUM"
    )

    conducted = validate_success(
        api.conduct_visit(
            first["id"],
            {
                "visit_conducted_on": "2026-08-01T00:00:00Z",
                "observation_score": 60,
                "findings": ["QS-ROUTINES"],
                "critical_finding": False,
            },
            COACH_B_HEADERS,
        )
    )
    assert conducted["status"] == "COMPLETED"

    pending = validate_success(api.get_visit(second["id"], NETWORK_ADMIN_HEADERS))
    assert pending["status"] == "SCHEDULED"
    assert pending["observation_score"] is None

    provider = validate_success(api.get_provider(ctx["provider_id"], NETWORK_ADMIN_HEADERS))
    assert float(provider["quality_score"]) == 60.00
    assert provider["quality_tier"] == "TIER_3"
    assert provider["quality_variant_applied"] == "COACHING_WEIGHTED"


# Claim and remittance money


def test_the_advance_truncates_the_eighty_percent_share_rather_than_rounding_it(api):
    """A provisional of 4503 advances 3602, not 3603, so the delta lands on 901.

    One attended day at 4503 cents makes the provisional amount 4503. Four fifths of that
    is 3602.4 cents, and discarding the fraction gives 3602. Reconciliation values the same
    single attended day at 4503 again, so the settlement delta is 4503 - 3602 == 901; a
    half-up reading of the advance would have produced 900 instead.

    PRD: "The advance requires the claim to be `SUBMITTED` and the contract to be `ACTIVE`,
    moves the claim `SUBMITTED → ADVANCE_PAID`, and sets `advance_paid_cents` to eighty
    percent of `provisional_amount_cents` with any fraction of a cent discarded — the
    product of the provisional amount and 80, divided by 100, truncated downward."

    Design: Corner/Calculations/advance_payment_applies_the_eighty_percent_constant_with_floor_not_rounding
    """
    ctx = _billing_home_with_one_subsidy_child(daily_rate_cents=4503)
    claim = create_claim(
        ctx["contract_id"],
        ctx["provider_id"],
        "2026-08",
        [claim_line(ctx["e1"], 1, 0)],
        contract_version(ctx["contract_id"]),
    )

    submitted = validate_success(api.submit_claim(claim["id"], None, ctx["headers"]))
    assert submitted["provisional_amount_cents"] == 4503

    advanced = validate_success(
        api.advance_claim(claim["id"], None, FISCAL_OFFICER_HEADERS)
    )
    assert advanced["advance_paid_cents"] == 3602
    assert advanced["advance_paid_cents"] != 3603

    reconciled = validate_success(
        api.reconcile_claim(claim["id"], None, FISCAL_OFFICER_HEADERS)
    )
    assert reconciled["final_amount_cents"] == 4503
    assert reconciled["settlement_delta_cents"] == 901
    assert reconciled["settlement_delta_cents"] != 900

    contract = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert contract["claimed_amount_cents"] == 4503


def test_the_waterfall_fills_one_bucket_before_it_touches_the_next(api):
    """100000 cents fill July completely and leave August partly paid, with nothing over.

    July takes the lesser of the remaining balance and its own 90000 shortfall, reaching its
    final amount and settling. August then takes the 10000 that survive, which is short of
    its own 90000, so it keeps its reconciled status. The balance is exhausted, so nothing
    is credited and the contract's remitted total is the allocated 100000 exactly.

    PRD: "Beginning with the remittance's full `amount_cents` as the remaining balance, each
    candidate in turn takes the lesser of the remaining balance and its own outstanding
    shortfall (its `final_amount_cents` less its `paid_cents`)."

    Design: Corner/Calculations/remittance_waterfall_fills_first_claim_then_partially_fills_second
    """
    ctx = _billing_home_with_one_subsidy_child(period_start_on="2026-07-01T00:00:00Z")
    july = claim_walked_to(
        "RECONCILED", ctx["contract_id"], ctx["provider_id"], "2026-07",
        [claim_line(ctx["e1"], 20, 0)],
    )
    august = claim_walked_to(
        "RECONCILED", ctx["contract_id"], ctx["provider_id"], "2026-08",
        [claim_line(ctx["e1"], 20, 0)],
    )
    assert july["final_amount_cents"] == 90000
    assert august["final_amount_cents"] == 90000

    remittance = post_remittance(
        ctx["contract_id"], "AG-PARTIAL-1", 100000, received_on="2026-08-01T00:00:00Z"
    )
    assert remittance["allocations"] == [
        {"claim_id": july["id"], "allocated_cents": 90000},
        {"claim_id": august["id"], "allocated_cents": 10000},
    ]
    assert remittance["unallocated_cents"] == 0

    settled = validate_success(api.get_claim(july["id"], FISCAL_OFFICER_HEADERS))
    assert settled["status"] == "SETTLED"
    assert settled["paid_cents"] == 90000

    partial = validate_success(api.get_claim(august["id"], FISCAL_OFFICER_HEADERS))
    assert partial["status"] == "RECONCILED"
    assert partial["paid_cents"] == 10000

    contract = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert contract["remitted_cents"] == 100000
    assert contract["unallocated_credit_cents"] == 0


def test_the_waterfall_pays_the_earlier_service_month_even_though_it_was_filed_later(api):
    """A 45000-cent payment goes entirely to the July claim that was created second.

    August is drafted, advanced and reconciled at 90000 before July is even drafted, so a
    creation-ordered walk would have paid August first. Because candidates are ordered by
    service month instead, the whole 45000 lands on July, settling it in full and leaving
    August reconciled and unpaid.

    PRD: "Candidates are ordered by `period_month` ascending and then by `created_at`
    ascending, never by identifier; ties cannot occur, because service months are unique per
    contract among non-rejected claims."

    Design: Corner/Calculations/remittance_allocation_follows_period_month_order_not_creation_order
    """
    ctx = _billing_home_with_one_subsidy_child(period_start_on="2026-06-01T00:00:00Z")
    late = claim_walked_to(
        "RECONCILED", ctx["contract_id"], ctx["provider_id"], "2026-08",
        [claim_line(ctx["e1"], 20, 0)],
    )
    early = claim_walked_to(
        "RECONCILED", ctx["contract_id"], ctx["provider_id"], "2026-07",
        [claim_line(ctx["e1"], 10, 0)],
    )
    assert late["final_amount_cents"] == 90000
    assert early["final_amount_cents"] == 45000

    remittance = post_remittance(
        ctx["contract_id"], "AG-ORDER-1", 45000, received_on="2026-08-01T00:00:00Z"
    )
    assert remittance["allocations"] == [
        {"claim_id": early["id"], "allocated_cents": 45000}
    ]
    assert remittance["unallocated_cents"] == 0

    settled = validate_success(api.get_claim(early["id"], FISCAL_OFFICER_HEADERS))
    assert settled["status"] == "SETTLED"
    assert settled["paid_cents"] == 45000

    untouched = validate_success(api.get_claim(late["id"], FISCAL_OFFICER_HEADERS))
    assert untouched["status"] == "RECONCILED"
    assert untouched["paid_cents"] == 0
