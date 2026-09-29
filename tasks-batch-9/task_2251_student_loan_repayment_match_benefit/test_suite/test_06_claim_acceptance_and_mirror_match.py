"""Adjudicating the claim: the return cycle, the pay-period mirror match and its cascade."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_allocation_shape,
    assert_batch_net_identity,
    assert_cents,
    assert_ratio_4dp,
)
from test_helpers.test_users import ADMIN_HEADERS


# ---------------------------------------------------------------------------
# The return / resubmit cycle
# ---------------------------------------------------------------------------


def test_certification_return_then_resubmit_records_the_cycle(client):
    """
    A returned claim can be resubmitted and the return count records the round trip.

    PRD: "`SUBMITTED` → `RETURNED` sends the claim back to the participant for
    rework. It increments `return_count` by one, stamps `decided_at` with the current
    logical clock".

    PRD: "The `SUBMITTED` → `RETURNED` → `SUBMITTED` cycle may repeat, and
    `return_count` records how many times it has."

    Design: Difficulty/non_linear_state_machine/certification_return_resubmit_cycle_then_accept
    """
    scenario = fx.setup_submitted_claim(client, create_batches=True)

    returned = fx.return_certification(
        client, scenario["certification_id"], "servicer statement illegible"
    )
    assert returned["status"] == "RETURNED"
    assert returned["return_count"] == 1

    resubmitted = fx.submit_certification(
        client, scenario["certification_id"], scenario["employee"]
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["return_count"] == 1


def test_certification_accepted_after_a_return_cycle_pays_once(client):
    """
    Money is created once at the end of a return cycle, not once per submission.

    PRD: "`SUBMITTED` → `ACCEPTED` is where money is created, and it is guarded by
    two rules beyond the state check."

    PRD: "`matched_total_cents` is the sum of `amount_cents` over the allocations
    bearing this `certification_id` whose `funding_status` is `SCHEDULED` or
    `FUNDED`."

    Design: Difficulty/non_linear_state_machine/certification_return_resubmit_cycle_then_accept
    """
    scenario = fx.setup_submitted_claim(client, create_batches=True)

    fx.return_certification(client, scenario["certification_id"], "servicer statement illegible")
    fx.submit_certification(client, scenario["certification_id"], scenario["employee"])

    accepted = fx.accept_certification(client, scenario["certification_id"])
    assert accepted["status"] == "ACCEPTED"
    assert accepted["return_count"] == 1
    assert_cents(accepted["matched_total_cents"], 20_000, "matched_total_cents")

    allocations = fx.allocations_of_certification(client, scenario["certification_id"])
    assert len(allocations) == 1
    assert_allocation_shape(allocations[0])

    plan_year = fx.refresh_plan_year(client, scenario["plan_year_id"])
    assert_cents(plan_year["total_qslp_match_funded_cents"], 20_000, "plan year qslp total")


# ---------------------------------------------------------------------------
# The acceptance cascade
# ---------------------------------------------------------------------------


def test_accept_certification_cascades_into_batch_and_plan_year_totals(client):
    """
    Acceptance writes the allocation, attaches it to the pending batch and moves both totals.

    PRD: "Accepting a claim writes allocations, attaches them to a pending batch,
    moves the batch's totals, moves the plan year's totals, and stales the plan
    year's completed nondiscrimination tests — all before the response is produced."

    PRD: "And if a `PENDING` funding batch exists for the allocation's plan year and
    target payroll period, the allocation's `funding_status` moves `UNFUNDED` →
    `SCHEDULED`, its `funding_batch_id` is set to that batch, and the batch's
    `total_allocated_cents`, `allocation_count`, and `net_funding_cents` are
    recomputed, as is the plan year's `total_qslp_match_funded_cents`."

    Design: Difficulty/transitive_cascade/accept_certification_cascade_depth4
    """
    scenario = fx.setup_submitted_claim(client, create_batches=True)

    batch_before = fx.refresh_funding_batch(client, scenario["funding_batch_id"])
    assert_cents(batch_before["total_allocated_cents"], 0, "batch total before")
    plan_year_before = fx.refresh_plan_year(client, scenario["plan_year_id"])
    assert_cents(plan_year_before["total_qslp_match_funded_cents"], 0, "plan year total before")

    fx.accept_certification(client, scenario["certification_id"])

    allocations = fx.allocations_of_certification(client, scenario["certification_id"])
    assert len(allocations) == 1
    allocation = allocations[0]
    assert_cents(allocation["amount_cents"], 20_000, "allocation amount")
    assert allocation["funding_status"] == "SCHEDULED"
    assert allocation["funding_batch_id"] == scenario["funding_batch_id"]

    batch_after = fx.refresh_funding_batch(client, scenario["funding_batch_id"])
    assert_cents(batch_after["total_allocated_cents"], 20_000, "batch total after")
    assert batch_after["allocation_count"] == 1
    assert_cents(batch_after["net_funding_cents"], 20_000, "batch net after")
    assert_batch_net_identity(batch_after)

    plan_year_after = fx.refresh_plan_year(client, scenario["plan_year_id"])
    assert_cents(plan_year_after["total_qslp_match_funded_cents"], 20_000, "plan year total after")
    assert plan_year_after["accepted_certification_count"] == 1


def test_accept_certification_stales_the_completed_nondiscrimination_test(client):
    """
    The fourth hop of the acceptance cascade stales an already-completed ACP test.

    PRD: "Every nondiscrimination test of that plan year standing in `PASSED` or
    `FAILED` moves to `STALE`, because the plan year's funded totals just changed and
    the stored ratios are no longer authoritative."

    Design: Difficulty/transitive_cascade/accept_certification_cascade_depth4
    """
    scenario = fx.setup_submitted_claim(client, create_batches=True)

    test = fx.open_nondiscrimination_test(client, scenario["plan_year_id"])
    computed = fx.compute_nondiscrimination_test(client, test["id"])
    assert computed["status"] == "PASSED"
    assert_ratio_4dp(computed["nhce_acp"], 0.0200, "nhce_acp")
    assert_ratio_4dp(computed["limit_acp"], 0.0400, "limit_acp")

    fx.accept_certification(client, scenario["certification_id"])

    staled = validate_success(client.get_nondiscrimination_test(test["id"], ADMIN_HEADERS))
    assert staled["status"] == "STALE"
    assert_ratio_4dp(staled["nhce_acp"], 0.0200, "retained nhce_acp")


# ---------------------------------------------------------------------------
# Acceptance guard precedence and the amendment dependency
# ---------------------------------------------------------------------------


def test_amendment_not_effective_outranks_loan_not_verified(client):
    """
    An acceptance blocked by both the amendment and the loan reports the amendment.

    PRD: "An effective plan amendment must exist — `ERR_AMENDMENT_NOT_EFFECTIVE`, on
    `POST /loan-certifications/{certification_id}/decision`."

    PRD: "Referenced loans must be verified — `ERR_LOAN_NOT_VERIFIED`, on both
    `POST /loan-certifications/{certification_id}/lines` and
    `POST /loan-certifications/{certification_id}/decision`."

    Design: Difficulty/priority_pair_validation_conflict/amendment_not_effective_beats_loan_not_verified
    """
    scenario = fx.setup_submitted_claim(
        client, amendment_status="ADOPTED", create_batches=True
    )
    assert scenario["amendment"]["status"] == "ADOPTED"

    disqualified = fx.verify_loan_account(
        client, scenario["loan_account_id"], "DISQUALIFIED"
    )
    assert disqualified["status"] == "DISQUALIFIED"

    response = client.decide_certification(
        scenario["certification_id"], f.decision_payload("ACCEPT"), ADMIN_HEADERS
    )
    validate_error(response, ApiErrorId.AMENDMENT_NOT_EFFECTIVE.value, 422)

    claim = fx.refresh_certification(client, scenario["certification_id"])
    assert claim["status"] == "SUBMITTED"
    assert_cents(claim["eligible_total_cents"], 0, "eligible_total_cents")

    allocations = fx.allocations_of_certification(client, scenario["certification_id"])
    assert len(allocations) == 0


def test_loan_not_verified_surfaces_once_the_amendment_is_effective(client):
    """
    With the amendment effective the same acceptance reports the disqualified loan.

    PRD: "And every certification line of the claim must reference a loan account
    whose status is `VERIFIED`, re-checked here even though it was checked when the
    line was added, with `ERR_LOAN_NOT_VERIFIED` on failure."

    Design: Difficulty/priority_pair_validation_conflict/amendment_not_effective_beats_loan_not_verified
    """
    scenario = fx.setup_submitted_claim(
        client, amendment_status="ADOPTED", create_batches=True
    )
    fx.verify_loan_account(client, scenario["loan_account_id"], "DISQUALIFIED")

    masked = client.decide_certification(
        scenario["certification_id"], f.decision_payload("ACCEPT"), ADMIN_HEADERS
    )
    validate_error(masked, ApiErrorId.AMENDMENT_NOT_EFFECTIVE.value, 422)

    fx.advance_amendment_to(client, scenario["amendment"]["id"], "EFFECTIVE")

    revealed = client.decide_certification(
        scenario["certification_id"], f.decision_payload("ACCEPT"), ADMIN_HEADERS
    )
    validate_error(revealed, ApiErrorId.LOAN_NOT_VERIFIED.value, 422)

    claim = fx.refresh_certification(client, scenario["certification_id"])
    assert claim["status"] == "SUBMITTED"
    assert_cents(claim["matched_total_cents"], 0, "matched_total_cents")


def test_accept_requires_an_effective_amendment(client):
    """
    A claim cannot be accepted while the authorizing amendment is only noticed.

    PRD: "At least one plan amendment of the claim's plan year must stand in
    `EFFECTIVE` — the plan document must be amended and participants notified before
    any claim may be accepted — and otherwise the acceptance is rejected with
    `ERR_AMENDMENT_NOT_EFFECTIVE`."

    Design: Difficulty/cross_entity_state_dependency/accept_requires_amendment_effective
    """
    scenario = fx.setup_submitted_claim(
        client, amendment_status="NOTICE_SENT", create_batches=True
    )
    assert scenario["amendment"]["status"] == "NOTICE_SENT"

    response = client.decide_certification(
        scenario["certification_id"], f.decision_payload("ACCEPT"), ADMIN_HEADERS
    )
    validate_error(response, ApiErrorId.AMENDMENT_NOT_EFFECTIVE.value, 422)

    claim = fx.refresh_certification(client, scenario["certification_id"])
    assert claim["status"] == "SUBMITTED"

    plan_year = fx.refresh_plan_year(client, scenario["plan_year_id"])
    assert_cents(plan_year["total_qslp_match_funded_cents"], 0, "plan year qslp total")


def test_effective_amendment_unblocks_acceptance(client):
    """
    Declaring the amendment effective is the event that unblocks claim acceptance.

    PRD: "It stamps `effective_at`, which is null before it, and it is the event that
    unblocks claim acceptance for that plan year."

    PRD: "`total_qslp_match_funded_cents` is the sum of `amount_cents` over the plan
    year's match allocations whose `funding_status` is `SCHEDULED` or `FUNDED`, plus
    the sum of `amount_cents` over the plan year's correction adjustments whose
    `reason_code` is `TRUE_UP_RECOUPMENT`."

    Design: Difficulty/cross_entity_state_dependency/accept_requires_amendment_effective
    """
    scenario = fx.setup_submitted_claim(
        client, amendment_status="NOTICE_SENT", create_batches=True
    )

    blocked = client.decide_certification(
        scenario["certification_id"], f.decision_payload("ACCEPT"), ADMIN_HEADERS
    )
    validate_error(blocked, ApiErrorId.AMENDMENT_NOT_EFFECTIVE.value, 422)

    effective = fx.advance_amendment_to(client, scenario["amendment"]["id"], "EFFECTIVE")
    assert effective["status"] == "EFFECTIVE"

    accepted = fx.accept_certification(client, scenario["certification_id"])
    assert accepted["status"] == "ACCEPTED"
    assert_cents(accepted["matched_total_cents"], 20_000, "matched_total_cents")

    plan_year = fx.refresh_plan_year(client, scenario["plan_year_id"])
    assert_cents(plan_year["total_qslp_match_funded_cents"], 20_000, "plan year qslp total")


# ---------------------------------------------------------------------------
# Conserved statutory space across the return branch
# ---------------------------------------------------------------------------


def test_return_after_submit_restores_remaining_statutory_space(client):
    """
    Returning a submitted claim restores the participant's space to its exact prior value.

    PRD: "An employee's `remaining_qslp_space_cents` must return to its exact
    pre-submission value once a submitted claim is returned, voided, or superseded,
    because the statuses `DRAFT`, `RETURNED`, `VOIDED`, and `SUPERSEDED` all sit
    outside the set of statuses that reserve space."

    Design: Difficulty/compensating_invariant/return_after_submit_restores_remaining_qslp_space
    """
    scenario = fx.build_claim_scenario(client)

    before = fx.refresh_employee(client, scenario["employee_id"])
    assert_cents(before["remaining_qslp_space_cents"], 2_280_000, "space before submit")

    fx.submit_certification(client, scenario["certification_id"], scenario["employee"])
    submitted = fx.refresh_employee(client, scenario["employee_id"])
    assert_cents(submitted["remaining_qslp_space_cents"], 2_250_000, "space after submit")

    returned = fx.return_certification(client, scenario["certification_id"])
    assert returned["status"] == "RETURNED"
    assert returned["return_count"] == 1

    after = fx.refresh_employee(client, scenario["employee_id"])
    assert_cents(after["remaining_qslp_space_cents"], 2_280_000, "space after return")
    assert after["remaining_qslp_space_cents"] == before["remaining_qslp_space_cents"]


def test_return_branch_creates_no_money_across_repeated_cycles(client):
    """
    Repeated submit-and-return cycles leave the funded ledger and the claim's money at zero.

    PRD: "and — because `RETURNED` sits outside the reserved status set — restores
    the employee's `remaining_qslp_space_cents` to exactly its pre-submission value."

    Design: Difficulty/compensating_invariant/return_after_submit_restores_remaining_qslp_space
    """
    scenario = fx.build_claim_scenario(client)

    for expected_returns in (1, 2):
        fx.submit_certification(client, scenario["certification_id"], scenario["employee"])
        assert_cents(
            fx.refresh_employee(client, scenario["employee_id"])[
                "remaining_qslp_space_cents"
            ],
            2_250_000,
            "space while submitted",
        )
        returned = fx.return_certification(client, scenario["certification_id"])
        assert returned["return_count"] == expected_returns
        assert_cents(
            fx.refresh_employee(client, scenario["employee_id"])[
                "remaining_qslp_space_cents"
            ],
            2_280_000,
            "space after return",
        )

    claim = fx.refresh_certification(client, scenario["certification_id"])
    assert_cents(claim["matched_total_cents"], 0, "matched_total_cents")
    assert_cents(claim["eligible_total_cents"], 0, "eligible_total_cents")

    allocations = fx.allocations_of_certification(client, scenario["certification_id"])
    assert len(allocations) == 0

    plan_year = fx.refresh_plan_year(client, scenario["plan_year_id"])
    assert_cents(plan_year["total_qslp_match_funded_cents"], 0, "plan year qslp total")


# ---------------------------------------------------------------------------
# Mirror waterfall and immediate visibility
# ---------------------------------------------------------------------------


def test_mirror_waterfall_spills_into_second_period(client):
    """
    Certified dollars beyond one period's leftover space spill into the next period.

    PRD: "The system then takes the lesser of the remaining pool and the free
    first-tier space, reduces the pool by that amount, takes the lesser of the
    now-reduced pool and the free second-tier space, and reduces the pool again."

    PRD: "Rounding happens once per period allocation and the already-rounded
    allocations are then summed into every derived total".

    Design: Corner/calculations/corner_mirror_waterfall_spills_into_second_period
    """
    scenario = fx.setup_accepted_claim(
        client,
        period_numbers=(1, 2),
        line_specs=[{"amount_cents": 40_000}],
    )
    claim = scenario["certification"]

    assert_cents(claim["eligible_total_cents"], 40_000, "eligible_total_cents")
    assert claim["capped_by_statutory_room"] is False
    assert_cents(claim["matched_total_cents"], 30_000, "matched_total_cents")
    assert_cents(claim["unmatched_eligible_cents"], 0, "unmatched_eligible_cents")

    allocations = sorted(
        fx.allocations_of_certification(client, scenario["certification_id"]),
        key=lambda row: row["created_at"],
    )
    assert len(allocations) == 2
    first, second = allocations

    assert_cents(first["amount_cents"], 20_000, "first allocation amount")
    assert_cents(first["tier1_applied_cents"], 10_000, "first tier1 applied")
    assert_cents(first["tier2_applied_cents"], 20_000, "first tier2 applied")
    assert first["funding_status"] == "SCHEDULED"

    assert_cents(second["amount_cents"], 10_000, "second allocation amount")
    assert_cents(second["tier1_applied_cents"], 10_000, "second tier1 applied")
    assert_cents(second["tier2_applied_cents"], 0, "second tier2 applied")
    assert second["funding_status"] == "SCHEDULED"

    first_batch, second_batch = scenario["batches"]
    assert_cents(
        fx.refresh_funding_batch(client, first_batch["id"])["total_allocated_cents"],
        20_000,
        "first batch total",
    )
    assert_cents(
        fx.refresh_funding_batch(client, second_batch["id"])["total_allocated_cents"],
        10_000,
        "second batch total",
    )

    plan_year = fx.refresh_plan_year(client, scenario["plan_year_id"])
    assert_cents(plan_year["total_qslp_match_funded_cents"], 30_000, "plan year qslp total")


def test_immediate_visibility_of_derived_totals_in_same_response(client):
    """
    Every derived total moved by an acceptance is readable immediately afterwards.

    PRD: "Cascades run to completion within the request that triggers them."

    PRD: "`accepted_certification_count` is the number of loan certifications of the
    plan year whose `status` is `ACCEPTED` or `AUDIT_HOLD`."

    Design: Corner/consistency model/corner_immediate_visibility_of_derived_totals_in_same_response
    """
    scenario = fx.setup_accepted_claim(client)
    claim = scenario["certification"]

    assert claim["status"] == "ACCEPTED"
    assert_cents(claim["eligible_total_cents"], 30_000, "eligible_total_cents")
    assert_cents(claim["matched_total_cents"], 20_000, "matched_total_cents")

    plan_year = fx.refresh_plan_year(client, scenario["plan_year_id"])
    assert_cents(plan_year["total_qslp_match_funded_cents"], 20_000, "plan year qslp total")
    assert plan_year["accepted_certification_count"] == 1

    batch = fx.refresh_funding_batch(client, scenario["funding_batch_id"])
    assert_cents(batch["total_allocated_cents"], 20_000, "batch total")
    assert_cents(batch["net_funding_cents"], 20_000, "batch net")
    assert batch["allocation_count"] == 1
    assert batch["status"] == "PENDING"

    employee = fx.refresh_employee(client, scenario["employee_id"])
    assert_cents(employee["remaining_qslp_space_cents"], 2_250_000, "remaining space")

    listing = client.list_match_allocations(
        ADMIN_HEADERS, {"certification_id": scenario["certification_id"]}
    )
    allocations, meta = validate_paginated(listing)
    assert len(allocations) == 1
    assert meta["total_count"] == 1
