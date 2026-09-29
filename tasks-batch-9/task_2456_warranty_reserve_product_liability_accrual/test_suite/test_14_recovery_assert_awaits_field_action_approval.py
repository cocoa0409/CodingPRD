"""Asserting a recovery depends on the approval state of the campaign it recovers.

PRD §3.7: "when the claim carries a non-null `field_action_id`, that field action's
`approval_state` must be `APPROVED`, or the assertion answers
`ERR_FIELD_ACTION_NOT_APPROVED`."
"""

from test_helpers import (
    ANALYST_HEADERS,
    ERR_FIELD_ACTION_NOT_APPROVED,
    create_family,
    create_failure_mode,
    create_field_action,
    create_period,
    create_recovery,
    create_remedy_option,
    create_supplier,
    decide_field_action,
    read_field_action,
    read_recovery,
    read_supplier,
    select_remedy,
    submit_field_action,
    validate_error,
    assert_recovery,
)


def _build_world(api):
    """A DRAFT recovery of 2000000 cents pointed at a DRAFT service campaign."""
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    supplier = create_supplier(
        api,
        supplier_code="SUP-3",
        name="Halden Electronics AS",
        credit_rating="AAA",
        annual_purchase_volume_cents=1000000000,
        contractual_recovery_cap_bps=2000,
    )
    family = create_family(
        api,
        family_code="FAM-M",
        name="Microwave Combi Platform",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=15000,
        reserve_cap_cents=80000000,
    )
    mode = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-M-BRD",
        description="Supplied inverter board failure",
        severity="FUNCTIONAL",
        cost_per_claim_cents=15000,
        supplier_id=supplier["id"],
    )
    action = create_field_action(
        api,
        family["id"],
        action_code="FA-M-01",
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date="2025-02-01",
        affected_build_end_date="2025-04-30",
        affected_unit_count=4000,
        regulatory_notice_filed=False,
    )
    option = create_remedy_option(
        api,
        action["id"],
        option_code="OPT-M-PERM",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=3000,
        labor_hours_centi=100,
        admin_cost_cents=500,
        expected_take_rate_bps=5000,
        is_engineering_approved=True,
    )
    select_remedy(
        api, action["id"], remedy_option_id=option["id"], expected_field_action_version=1
    )
    recovery = create_recovery(
        api,
        supplier["id"],
        mode["id"],
        asserted_amount_cents=2000000,
        field_action_id=action["id"],
    )
    return {
        "period": period,
        "supplier": supplier,
        "family": family,
        "action": action,
        "recovery": recovery,
    }


def test_assertion_is_refused_while_the_linked_campaign_is_still_a_draft(api):
    """The claim's own from-state is legal and the supplier is not impaired.

    PRD §2.9 rung 23: "When a supplier recovery carries a non-null `field_action_id`,
    that field action's `approval_state` is `APPROVED` — guarding
    `POST /warranty/supplier-recoveries/{recoveryId}/assert` — otherwise
    `ERR_FIELD_ACTION_NOT_APPROVED` (HTTP 422)." Nothing else bars the move: PRD §3.7
    says the claim "is legal from two starting points" including `DRAFT`, and the only
    other guard, "the supplier's `collectability_rating` must not be `IMPAIRED`", is
    satisfied by an AAA counterparty.

    Design: Difficulty/cross_entity_state_dependency/recovery_assert_blocked_until_linked_field_action_is_approved
    """
    world = _build_world(api)
    assert read_field_action(api, world["action"]["id"])["approval_state"] == "DRAFT"

    response = api.assert_recovery(ANALYST_HEADERS, world["recovery"]["id"])
    validate_error(response, ERR_FIELD_ACTION_NOT_APPROVED, expected_status=422)


def test_submitting_the_campaign_is_not_enough_to_unlock_the_assertion(api):
    """SUBMITTED is not APPROVED, and the refused claim keeps its creation valuation.

    PRD §3.5: "Submitting advances the approval dimension from `DRAFT` to `SUBMITTED`",
    which PRD §3.7's guard still rejects because it demands `APPROVED`. PRD §3.7 pins
    what the untouched row holds: "The row is born in `status` `DRAFT` with an
    `assert_count` of 0 ... and it is valued immediately on creation under the
    `EXPECTED_VALUE` variant", and PRD §3.7's weighting — "a rating of `HIGH` weights at
    9000 basis points" — puts 1800000 cents on a 2000000-cent assertion.

    Design: Difficulty/cross_entity_state_dependency/recovery_assert_blocked_until_linked_field_action_is_approved
    """
    world = _build_world(api)
    submit_field_action(api, world["action"]["id"])
    assert read_field_action(api, world["action"]["id"])["approval_state"] == "SUBMITTED"

    response = api.assert_recovery(ANALYST_HEADERS, world["recovery"]["id"])
    validate_error(response, ERR_FIELD_ACTION_NOT_APPROVED, expected_status=422)

    recovery = read_recovery(api, world["recovery"]["id"])
    assert recovery["status"] == "DRAFT"
    assert recovery["assert_count"] == 0
    assert recovery["recognized_recovery_cents"] == 1800000


def test_approving_the_campaign_unlocks_the_identical_assertion(api):
    """Once the campaign is APPROVED the unchanged request succeeds.

    PRD §3.7: "1 is added to `assert_count`, the `valuation_variant` is set to (or
    remains) `EXPECTED_VALUE`, `recognized_recovery_cents` and
    `collectability_rating_at_valuation` are recomputed under that variant, and the
    supplier's `gross_asserted_recovery_cents` and `open_recovery_asset_cents` are
    recomputed." The 200000000-cent contractual ceiling of PRD §3.7 does not bind, and
    PRD §3.5's hop one leaves the campaign priced at 6500 cents over 4000 units.

    Design: Difficulty/cross_entity_state_dependency/recovery_assert_blocked_until_linked_field_action_is_approved
    """
    world = _build_world(api)
    submit_field_action(api, world["action"]["id"])
    approved = decide_field_action(api, world["action"]["id"], "APPROVED")
    assert approved["approval_state"] == "APPROVED"
    assert approved["specific_accrual_cents"] == 26000000

    asserted = assert_recovery(api, world["recovery"]["id"])
    assert asserted["status"] == "ASSERTED"
    assert asserted["assert_count"] == 1
    assert asserted["recognized_recovery_cents"] == 1800000
    assert asserted["valuation_variant"] == "EXPECTED_VALUE"
    assert asserted["collectability_rating_at_valuation"] == "HIGH"

    supplier = read_supplier(api, world["supplier"]["id"])
    assert supplier["gross_asserted_recovery_cents"] == 2000000
    assert supplier["open_recovery_asset_cents"] == 1800000
