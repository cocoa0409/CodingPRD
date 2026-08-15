"""Recycling take-back: provisional vs final credits and intake gates (PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    assert_recycling_intake,
    create_recycling_intake_payload,
    create_finalize_intake_payload,
    list_ledger,
    setup_recycling_retailer,
    setup_complete_order,
)

PM = TEST_USERS["plant_manager_headers"]
LOG1 = TEST_USERS["logistics_headers"]


def test_intake_posts_provisional_credit_immediately(api):
    """PRD §3.9: "The provisional credit is computed immediately:
    `declared_weight_kg` multiplied by a flat 20 cents per kilogram, rounded
    half up to integer cents, stored as `provisional_credit_cents`, and posted
    to the retailer's ledger as a `CreditAdjustment` with source
    `RECYCLING_PROVISIONAL` and `source_id` set to the intake."

    Design: Difficulty/dual_variant_calc/recycling_provisional_vs_final_divergence
    """
    retailer = setup_recycling_retailer()
    intake = validate_success(api.create_recycling_intake(
        create_recycling_intake_payload(
            retailer_id=retailer["id"], declared_weight_kg=100,
        ),
        LOG1,
    ), expected_status=201)
    assert_recycling_intake(intake)
    assert intake["status"] == "RECEIVED"
    assert intake["provisional_credit_cents"] == 2000

    ledger = list_ledger(retailer["id"])
    assert len(ledger) == 1
    assert ledger[0]["amount_cents"] == 2000
    assert ledger[0]["source"] == "RECYCLING_PROVISIONAL"
    assert ledger[0]["source_id"] == intake["id"]

    reloaded = get_success_data(api.get_retailer(retailer["id"], PM))
    assert reloaded["credit_balance_cents"] == 2000


def test_finalize_posts_signed_delta_adjustment(api):
    """PRD §3.9: "It accepts the four actual masses — `actual_steel_kg`,
    `actual_foam_kg`, `actual_fiber_kg`, and `actual_wood_kg` — and computes
    `final_credit_cents` as the sum of four per-material lines, each rounded
    half up to integer cents before summing: steel at 25 cents per kilogram,
    foam at 40, fiber at 15, and wood at 5. Because the final weighed credit
    almost always diverges from the flat provisional, the difference posts to
    the ledger as a signed `CreditAdjustment` equal to the final credit minus
    the provisional credit, with source `RECYCLING_FINAL_DELTA` — the delta
    may be negative."

    Design: Difficulty/dual_variant_calc/recycling_provisional_vs_final_divergence
    """
    retailer = setup_recycling_retailer()
    intake = get_success_data(api.create_recycling_intake(
        create_recycling_intake_payload(
            retailer_id=retailer["id"], declared_weight_kg=100,
        ),
        LOG1,
    ))

    finalized = validate_success(api.finalize_recycling_intake(
        intake["id"], create_finalize_intake_payload(
            actual_steel_kg=40, actual_foam_kg=30,
            actual_fiber_kg=20, actual_wood_kg=10,
        ),
        PM,
    ))
    assert finalized["status"] == "FINALIZED"
    # 40*25 + 30*40 + 20*15 + 10*5 = 1000 + 1200 + 300 + 50 = 2550
    assert finalized["final_credit_cents"] == 2550

    ledger = list_ledger(retailer["id"])
    assert len(ledger) == 2
    assert ledger[0]["amount_cents"] == 2000
    assert ledger[0]["source"] == "RECYCLING_PROVISIONAL"
    assert ledger[1]["amount_cents"] == 550
    assert ledger[1]["source"] == "RECYCLING_FINAL_DELTA"
    assert ledger[1]["source_id"] == intake["id"]

    reloaded = get_success_data(api.get_retailer(retailer["id"], PM))
    assert reloaded["credit_balance_cents"] == 2550


def test_intake_unit_check_masks_fiscal_cap(api):
    """PRD §2.8: "Every request is evaluated against a fixed pipeline of
    twelve validation tiers, and an earlier tier masks later ones — a failure
    surfaces the error of the earliest tier it violates, and only a request
    clean through a tier reaches the next:"
    PRD §2.8: "10. Cross-entity referential integrity (422):
    `ERR_UNIT_ORDER_MISMATCH`, `ERR_RETAILER_UNIT_MISMATCH`,
    `ERR_RETAILER_IDENTITY_MISMATCH`, `ERR_UNIT_NOT_SCRAPPED`,
    `ERR_SAG_BELOW_THRESHOLD`. 11. Fiscal caps (402):
    `ERR_CREDIT_LIMIT_EXCEEDED`, `ERR_INSUFFICIENT_FOAM_MASS`."
    PRD §3.9: "when `unit_id` is given it must reference a `SCRAPPED` unit
    owned by that same retailer — anything else is `ERR_UNIT_NOT_SCRAPPED`
    (422)."

    Design: Difficulty/priority_pair_validation_conflict/intake_referential_check_beats_fiscal_cap
    """
    # Retailer credit limit 0 means the provisional credit would also breach
    # the fiscal cap (tier 11); the MANUFACTURED unit fails tier 10 first.
    ctx = setup_complete_order(
        state_code="CA", quantity=1, foam_mass_required_kg=10,
        retailer_overrides={"credit_limit_cents": 0, "recycling_enrolled": True},
    )
    unit_id = ctx["units"][0]["id"]
    assert ctx["units"][0]["status"] == "MANUFACTURED"

    resp = api.create_recycling_intake(
        create_recycling_intake_payload(
            retailer_id=ctx["retailer"]["id"], declared_weight_kg=100,
            unit_id=unit_id,
        ),
        LOG1,
    )
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_SCRAPPED)


def test_intake_provisional_credit_capped_by_limit(api):
    """PRD §3.9: "That posting must respect the credit limit — a provisional
    credit that would push the balance above the cap is rejected with
    `ERR_CREDIT_LIMIT_EXCEEDED` (402) — and any successful posting recomputes
    the balance and increments the retailer's `version`."

    Design: Difficulty/priority_pair_validation_conflict/intake_referential_check_beats_fiscal_cap
    """
    retailer = setup_recycling_retailer(credit_limit_cents=0)
    resp = api.create_recycling_intake(
        create_recycling_intake_payload(
            retailer_id=retailer["id"], declared_weight_kg=100,
        ),
        LOG1,
    )
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)

    reloaded = get_success_data(api.get_retailer(retailer["id"], PM))
    assert reloaded["credit_balance_cents"] == 0
