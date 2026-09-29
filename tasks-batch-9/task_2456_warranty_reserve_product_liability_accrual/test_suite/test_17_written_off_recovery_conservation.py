"""Writing a supplier claim off moves value between buckets without destroying it.

PRD §3.7: "Note what is conserved: the amount does not vanish from
`gross_asserted_recovery_cents`, it simply moves out of `open_recovery_asset_cents` and
into `written_off_recovery_cents`."
"""

from test_helpers import (
    assert_recovery,
    close_recovery,
    create_failure_mode,
    create_family,
    create_field_action,
    create_period,
    create_recovery,
    create_remedy_option,
    create_supplier,
    decide_field_action,
    read_supplier,
    select_remedy,
    submit_field_action,
)


def _build_world(api):
    """SUP-4 with a single 5000000-cent DRAFT claim behind an APPROVED campaign."""
    create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    supplier = create_supplier(
        api,
        supplier_code="SUP-4",
        name="Vindal Pumpe GmbH",
        credit_rating="AAA",
        annual_purchase_volume_cents=1000000000,
        contractual_recovery_cap_bps=2000,
    )
    family = create_family(
        api,
        family_code="FAM-W",
        name="Washer Platform W",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=18000,
        reserve_cap_cents=70000000,
    )
    mode = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-W-PMP",
        description="Supplied drain pump impeller failure",
        severity="FUNCTIONAL",
        cost_per_claim_cents=18000,
        supplier_id=supplier["id"],
    )
    action = create_field_action(
        api,
        family["id"],
        action_code="FA-W-01",
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date="2025-03-01",
        affected_build_end_date="2025-05-31",
        affected_unit_count=1000,
        regulatory_notice_filed=False,
    )
    option = create_remedy_option(
        api,
        action["id"],
        option_code="OPT-W-PERM",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=2500,
        labor_hours_centi=100,
        admin_cost_cents=400,
        expected_take_rate_bps=5000,
        is_engineering_approved=True,
    )
    select_remedy(
        api, action["id"], remedy_option_id=option["id"], expected_field_action_version=1
    )
    submit_field_action(api, action["id"])
    decide_field_action(api, action["id"], "APPROVED")

    recovery = create_recovery(
        api,
        supplier["id"],
        mode["id"],
        asserted_amount_cents=5000000,
        field_action_id=action["id"],
    )
    return {"supplier": supplier, "family": family, "action": action, "recovery": recovery}


def test_asserting_the_claim_establishes_the_open_receivable(api):
    """Before the write-off the whole exposure sits in the live receivable.

    PRD §3.7: "`gross_asserted_recovery_cents` is the sum of `asserted_amount_cents`
    over that supplier's recovery claims whose status is `ASSERTED`, `NEGOTIATION`,
    `SETTLED` or `WRITTEN_OFF`. `open_recovery_asset_cents` is the sum of
    `recognized_recovery_cents` over claims still in `ASSERTED` or `NEGOTIATION` — the
    live receivable." PRD §3.7 also fixes the rating with no closed history: "when that
    denominator is 0, `realization_bps` is 10000 ... when `closed_recovery_count` is 0 the
    base rating stands".

    Design: Difficulty/compensating_invariant/gross_asserted_recovery_is_conserved_when_a_claim_is_written_off
    """
    world = _build_world(api)

    asserted = assert_recovery(api, world["recovery"]["id"])
    assert asserted["status"] == "ASSERTED"
    assert asserted["recognized_recovery_cents"] == 4500000
    assert asserted["valuation_variant"] == "EXPECTED_VALUE"

    supplier = read_supplier(api, world["supplier"]["id"])
    assert supplier["gross_asserted_recovery_cents"] == 5000000
    assert supplier["open_recovery_asset_cents"] == 4500000
    assert supplier["realized_recovery_cents"] == 0
    assert supplier["written_off_recovery_cents"] == 0
    assert supplier["closed_recovery_count"] == 0
    assert supplier["realization_bps"] == 10000
    assert supplier["collectability_rating"] == "HIGH"


def test_the_write_off_moves_the_exposure_without_changing_the_gross(api):
    """The removed asset is exactly compensated by the write-off entry.

    PRD §3.7: "It sets `settled_amount_cents` to 0, `recognized_recovery_cents` to 0 and
    `valuation_variant` to `CONTRACTUAL_FLOOR`; recomputes the supplier's
    `open_recovery_asset_cents`, `written_off_recovery_cents` and
    `closed_recovery_count`." PRD §3.7 defines the destination bucket as the *asserted*
    figure: "`written_off_recovery_cents` is the sum of `asserted_amount_cents` over
    claims in `WRITTEN_OFF`", so 4500000 leaves the receivable while 5000000 arrives.

    Design: Difficulty/compensating_invariant/gross_asserted_recovery_is_conserved_when_a_claim_is_written_off
    """
    world = _build_world(api)
    assert_recovery(api, world["recovery"]["id"])

    written_off = close_recovery(api, world["recovery"]["id"], outcome="WRITTEN_OFF")
    assert written_off["status"] == "WRITTEN_OFF"
    assert written_off["recognized_recovery_cents"] == 0
    assert written_off["settled_amount_cents"] == 0
    assert written_off["valuation_variant"] == "CONTRACTUAL_FLOOR"

    supplier = read_supplier(api, world["supplier"]["id"])
    assert supplier["gross_asserted_recovery_cents"] == 5000000
    assert supplier["open_recovery_asset_cents"] == 0
    assert supplier["written_off_recovery_cents"] == 5000000


def test_the_closure_identity_holds_and_costs_the_supplier_two_notches(api):
    """Once every claim is closed, gross equals realized plus written off.

    PRD §3.7: "let the denominator be `realized_recovery_cents` plus
    `written_off_recovery_cents`; when that denominator is 0, `realization_bps` is 10000,
    and otherwise `realization_bps` is `realized_recovery_cents` multiplied by 10000,
    divided by that denominator, rounded to the nearest integer ... and in every remaining
    case the base rating is downgraded by two notches. The downgrade ladder runs `HIGH` to
    `MEDIUM` to `LOW` to `IMPAIRED`." A supplier that realized nothing on its one closed
    claim sits at 0 basis points and therefore two notches below `HIGH`.

    Design: Difficulty/compensating_invariant/gross_asserted_recovery_is_conserved_when_a_claim_is_written_off
    """
    world = _build_world(api)
    assert_recovery(api, world["recovery"]["id"])
    close_recovery(api, world["recovery"]["id"], outcome="WRITTEN_OFF")

    supplier = read_supplier(api, world["supplier"]["id"])
    assert supplier["realized_recovery_cents"] == 0
    assert supplier["closed_recovery_count"] == 1
    assert supplier["realization_bps"] == 0
    assert supplier["collectability_rating"] == "LOW"
    assert supplier["gross_asserted_recovery_cents"] == (
        supplier["realized_recovery_cents"] + supplier["written_off_recovery_cents"]
    )
