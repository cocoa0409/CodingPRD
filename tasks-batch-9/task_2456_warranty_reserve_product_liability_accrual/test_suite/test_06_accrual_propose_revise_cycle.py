"""The warranty accrual's PROPOSED/DRAFT cycle and its revision counter.

PRD §3.3: "There is no limit on how many times an accrual may cycle between the
two states."
"""

from test_helpers import (
    ANALYST_ALT_HEADERS,
    ANALYST_HEADERS,
    WARRANTY_ANALYST_ALT_USER_ID,
    WARRANTY_ANALYST_USER_ID,
    create_accrual,
    create_failure_mode,
    create_family,
    create_observation,
    create_period,
    create_vintage,
    propose_accrual,
    success_data,
)


def _build_world(api):
    """FAM-R sits exactly on the maturity boundary with a DRAFT accrual of 1060000."""
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    family = create_family(
        api,
        family_code="FAM-R",
        name="Range Cooker Platform",
        launch_date="2024-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=20000,
        reserve_cap_cents=10000000,
    )
    vintage = create_vintage(
        api,
        family["id"],
        vintage_code="R-MY2024",
        units_shipped=5000,
        ship_period_code="2024-Q2",
        warranty_expiry_date="2028-12-31",
    )
    mode = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-R-IGN",
        description="Ignition module failure",
        severity="FUNCTIONAL",
        cost_per_claim_cents=20000,
    )
    create_observation(
        api,
        vintage["id"],
        mode["id"],
        observation_period_code="2026-Q3",
        months_in_service_from=0,
        months_in_service_to=12,
        claim_count=25,
        paid_cost_cents=200000,
    )
    accrual = create_accrual(
        api,
        period["id"],
        vintage["id"],
        method="HISTORICAL_RATE",
        elapsed_exposure_bps=3000,
        expected_period_version=1,
    )
    return {"period": period, "family": family, "vintage": vintage, "accrual": accrual}


def test_proposing_records_the_proposer_and_leaves_the_revision_index_at_zero(api):
    """The freshly created accrual starts unproposed and unrevised.

    PRD §3.3: "The row is born in `status` `DRAFT` with a `revision_index` of 0 and
    both `proposed_by_user_id` and `posted_by_user_id` null". PRD §3.3: "Proposing it
    advances `DRAFT` to `PROPOSED`, records the acting analyst's identifier as
    `proposed_by_user_id`, and re-runs the whole estimate against whatever claim data
    now exists".

    Design: Difficulty/non_linear_state_machine/warranty_accrual_propose_revise_cycle_reenters_draft_with_revision_index
    """
    world = _build_world(api)
    assert world["accrual"]["status"] == "DRAFT"
    assert world["accrual"]["revision_index"] == 0
    assert world["accrual"]["proposed_by_user_id"] is None

    proposed = propose_accrual(api, world["accrual"]["id"], headers=ANALYST_HEADERS)

    assert proposed["status"] == "PROPOSED"
    assert proposed["proposed_by_user_id"] == WARRANTY_ANALYST_USER_ID
    assert proposed["revision_index"] == 0
    assert proposed["accrued_amount_cents"] == 1060000
    assert proposed["posted_by_user_id"] is None


def test_revising_reenters_draft_clearing_the_proposer_and_counting_the_revision(api):
    """The cycle returns to an already visited state and bumps the loop counter.

    PRD §3.3: "Revising it loops `PROPOSED` back to `DRAFT`, adds 1 to
    `revision_index` and clears `proposed_by_user_id` to null". The estimate itself
    is unaffected: the cohort's single 25-claim observation on 5000 shipped units
    still develops to 1060000 cents.

    Design: Difficulty/non_linear_state_machine/warranty_accrual_propose_revise_cycle_reenters_draft_with_revision_index
    """
    world = _build_world(api)
    propose_accrual(api, world["accrual"]["id"], headers=ANALYST_HEADERS)

    revised = success_data(api.revise_accrual(ANALYST_HEADERS, world["accrual"]["id"]))

    assert revised["status"] == "DRAFT"
    assert revised["proposed_by_user_id"] is None
    assert revised["revision_index"] == 1
    assert revised["accrued_amount_cents"] == 1060000


def test_reproposing_records_a_new_proposer_without_moving_the_revision_index(api):
    """A second proposal is not a second revision.

    PRD §3.3: "Proposing it advances `DRAFT` to `PROPOSED`, records the acting
    analyst's identifier as `proposed_by_user_id`" — and only revision, per PRD §3.3,
    "adds 1 to `revision_index`". A different analyst therefore takes ownership of the
    estimate while the counter stays at the one revision that actually happened.

    Design: Difficulty/non_linear_state_machine/warranty_accrual_propose_revise_cycle_reenters_draft_with_revision_index
    """
    world = _build_world(api)
    propose_accrual(api, world["accrual"]["id"], headers=ANALYST_HEADERS)
    success_data(api.revise_accrual(ANALYST_HEADERS, world["accrual"]["id"]))

    reproposed = propose_accrual(api, world["accrual"]["id"], headers=ANALYST_ALT_HEADERS)

    assert reproposed["status"] == "PROPOSED"
    assert reproposed["proposed_by_user_id"] == WARRANTY_ANALYST_ALT_USER_ID
    assert reproposed["proposed_by_user_id"] != WARRANTY_ANALYST_USER_ID
    assert reproposed["revision_index"] == 1
    assert reproposed["accrued_amount_cents"] == 1060000
    assert reproposed["posted_by_user_id"] is None
