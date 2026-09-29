"""The four-hop cascade set off by approving a field action.

PRD §3.5: "the approval advances the action to `APPROVED`, which is terminal on the
approval dimension, and sets off a four-hop cascade that must be evaluated in
order."
"""

from test_helpers import (
    RESERVE_CONTROLLER_USER_ID,
    create_accrual,
    create_failure_mode,
    create_family,
    create_field_action,
    create_observation,
    create_period,
    create_remedy_option,
    create_vintage,
    decide_field_action,
    propose_accrual,
    read_accrual,
    read_family,
    read_period,
    select_remedy,
    submit_field_action,
)


def _build_world(api):
    """FAM-C with a PROPOSED accrual and a SUBMITTED 150156000-cent campaign."""
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")

    analog_family = create_family(
        api,
        family_code="FAM-A",
        name="Legacy Compressor Platform",
        launch_date="2022-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=20000,
        reserve_cap_cents=100000000,
    )
    analog_vintage = create_vintage(
        api,
        analog_family["id"],
        vintage_code="A-MY2022",
        units_shipped=10000,
        ship_period_code="2022-Q1",
        warranty_expiry_date="2025-12-31",
    )
    analog_mode = create_failure_mode(
        api,
        analog_family["id"],
        mode_code="FM-A-CORE",
        description="Legacy compressor core wear",
        severity="FUNCTIONAL",
        cost_per_claim_cents=20000,
    )
    create_observation(
        api,
        analog_vintage["id"],
        analog_mode["id"],
        observation_period_code="2026-Q3",
        months_in_service_from=0,
        months_in_service_to=24,
        claim_count=300,
        paid_cost_cents=6000000,
    )

    family = create_family(
        api,
        family_code="FAM-C",
        name="Combi Oven Platform",
        launch_date="2024-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=30000,
        reserve_cap_cents=150000000,
        engineering_estimate_rate_ppm=4000,
        analog_family_id=analog_family["id"],
    )
    vintage = create_vintage(
        api,
        family["id"],
        vintage_code="C-MY2024",
        units_shipped=3000,
        ship_period_code="2024-Q1",
        warranty_expiry_date="2028-12-31",
    )
    create_failure_mode(
        api,
        family["id"],
        mode_code="FM-C-DOOR",
        description="Door hinge fatigue",
        severity="FUNCTIONAL",
        cost_per_claim_cents=12000,
    )
    accrual = create_accrual(
        api,
        period["id"],
        vintage["id"],
        method="ANALOG_BLEND",
        elapsed_exposure_bps=2000,
        expected_period_version=1,
    )
    proposed = propose_accrual(api, accrual["id"])
    assert proposed["accrued_amount_cents"] == 2910000

    action = create_field_action(
        api,
        family["id"],
        action_code="FA-C-01",
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date="2025-01-01",
        affected_build_end_date="2025-03-31",
        affected_unit_count=12000,
        regulatory_notice_filed=False,
    )
    option = create_remedy_option(
        api,
        action["id"],
        option_code="OPT-C-PERM",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=4200,
        labor_hours_centi=150,
        admin_cost_cents=800,
        expected_take_rate_bps=6500,
        is_engineering_approved=True,
    )
    select_remedy(
        api, action["id"], remedy_option_id=option["id"], expected_field_action_version=1
    )
    submit_field_action(api, action["id"])

    return {
        "period": period,
        "family": family,
        "vintage": vintage,
        "accrual": proposed,
        "action": action,
        "option": option,
    }


def test_hop_one_records_the_decider_and_the_booking_period(api):
    """Approval writes the decider, the booking period and the campaign accrual.

    PRD §3.5: "**Hop one** records the controller's identifier as
    `decided_by_user_id`, writes the period chosen by the booking-period selector
    into `approved_period_id`, and recomputes `specific_accrual_cents` from the
    currently selected remedy option." PRD §3.1: "Its candidate set is every accrual
    period whose status is `OPEN` or `ANALYSIS_LOCKED`", and 2026-Q3 is the only
    candidate.

    Design: Difficulty/transitive_cascade/field_action_approval_cascades_four_hops_into_proposed_accrual_reversion
    """
    world = _build_world(api)

    approved = decide_field_action(api, world["action"]["id"], "APPROVED")

    assert approved["approval_state"] == "APPROVED"
    assert approved["specific_accrual_cents"] == 150156000
    assert approved["approved_period_id"] == world["period"]["id"]
    assert approved["decided_by_user_id"] == RESERVE_CONTROLLER_USER_ID
    assert approved["execution_state"] == "NOT_STARTED"
    assert approved["executed_cost_cents"] == 0


def test_hops_two_and_three_drive_the_family_balance_past_its_cap(api):
    """The recomputed balance re-derives a CONSTRAINED posture.

    PRD §3.5: "**Hop two**, because that accrual has now entered the
    approved-campaign filter, recomputes the family's
    `warranty_reserve_balance_cents` in full. **Hop three**, because the balance
    changed, re-derives the family's `reserve_posture`." PRD §2.10: "multiply by
    10000; divide by the family's `reserve_cap_cents`; and round the result to the
    nearest integer number of basis points ... If that ratio is at least 10000 basis
    points, `reserve_posture` becomes `CONSTRAINED`" — 150156000 against a
    150000000-cent cap rounds to 10010 basis points.

    Design: Difficulty/transitive_cascade/field_action_approval_cascades_four_hops_into_proposed_accrual_reversion
    """
    world = _build_world(api)

    decide_field_action(api, world["action"]["id"], "APPROVED")

    family = read_family(api, world["family"]["id"])
    assert family["warranty_reserve_balance_cents"] == 150156000
    assert family["reserve_posture"] == "CONSTRAINED"


def test_hop_four_reverts_the_families_proposed_accrual_to_draft(api):
    """A CONSTRAINED posture pushes proposed estimates back to their authors.

    PRD §3.5: "**Hop four** fires only when hop three left `reserve_posture` at
    `CONSTRAINED`: every warranty accrual sitting in `PROPOSED` whose cohort belongs
    to this family is pushed back to `DRAFT`, with 1 added to its `revision_index`
    and its `proposed_by_user_id` cleared to null, forcing the analysts to
    re-estimate in light of a reserve that has hit its ceiling." The reversion is a
    state change only — the 2910000-cent estimate is not re-priced.

    Design: Difficulty/transitive_cascade/field_action_approval_cascades_four_hops_into_proposed_accrual_reversion
    """
    world = _build_world(api)

    decide_field_action(api, world["action"]["id"], "APPROVED")

    accrual = read_accrual(api, world["accrual"]["id"])
    assert accrual["status"] == "DRAFT"
    assert accrual["revision_index"] == 1
    assert accrual["proposed_by_user_id"] is None
    assert accrual["accrued_amount_cents"] == 2910000


def test_approval_re_derives_the_periods_significant_exposure_disclosure(api):
    """A campaign above the half-million-dollar threshold becomes disclosable.

    PRD §3.5: "Independently of those hops, the approval re-derives
    `significant_exposure_count` and `requires_significant_exposure_disclosure` on
    the period named by `approved_period_id`." PRD §3.1:
    "`requires_significant_exposure_disclosure` is true exactly when
    `significant_exposure_count` is 1 or greater", and this 150156000-cent campaign
    clears the 50,000,000-cent threshold.

    Design: Difficulty/transitive_cascade/field_action_approval_cascades_four_hops_into_proposed_accrual_reversion
    """
    world = _build_world(api)
    before = read_period(api, world["period"]["id"])
    assert before["significant_exposure_count"] == 0

    decide_field_action(api, world["action"]["id"], "APPROVED")

    period = read_period(api, world["period"]["id"])
    assert period["significant_exposure_count"] == 1
    assert period["requires_significant_exposure_disclosure"] is True
