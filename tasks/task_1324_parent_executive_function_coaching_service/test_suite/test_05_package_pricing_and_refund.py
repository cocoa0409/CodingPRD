"""Package tiered pricing, expiry, and the two refund variants (PRD §3.5)."""
from datetime import timedelta

from test_helpers import (
    ApiErrorId,
    activate_family,
    add_client,
    assert_inv_credits,
    create_family,
    get_success_data,
    make_coach_headers,
    parse_instant,
    purchase_package,
    run_sweep,
    set_clock,
    schedule_session_ok,
    setup_active_plan_scenario,
    setup_dual_variant_package,
    validate_error,
    validate_success,
)


def test_package_refund_final_variant_values(api, admin_headers):
    """PRD §3.5: "The final refund is `price_paid_cents` minus the sum of
    `credits_consumed` and `credits_forfeited` multiplied by `unit_gross_cents`,
    floored at zero — used credits are re-priced at the gross unit rate,
    clawing back any sibling discount, and the materials fee is never
    refunded."
    PRD §3.5: "when the family has at least 2 clients whose status is `INTAKE`,
    `ACTIVE`, or `PAUSED` at purchase time, the subtotal is multiplied by 0.90
    and rounded half-up again — a 10 percent discount"

    Design: Difficulty/dual_variant_calc/package_refund_provisional_vs_final
    """
    ctx = setup_dual_variant_package()
    package = ctx["packages"][0]

    before = validate_success(api.get_package(package["id"], admin_headers))
    assert before["price_paid_cents"] == 196900  # 16 x 13500 x 0.9 + 2500
    assert before["unit_gross_cents"] == 13500
    assert before["per_credit_value_cents"] == 12306  # round_half_up(196900/16)
    assert before["credits_consumed"] == 4
    assert before["credits_remaining"] == 12

    refunded = validate_success(api.refund_package(package["id"], admin_headers))
    assert refunded["status"] == "REFUNDED"
    # FINAL: 196900 - (4 + 0) x 13500 = 142900.
    assert refunded["refund_cents"] == 142900


def test_package_refund_provisional_differs_from_final(api, admin_headers):
    """PRD §3.5: "A package read exposes a provisional refundable value — the
    PROVISIONAL variant of the refund calculation — equal to `credits_remaining`
    multiplied by the rounded `per_credit_value_cents`. This estimate ignores
    clawback and therefore differs from the final amount whenever the sibling
    discount applied or the per-credit division had a remainder."
    PRD §3.5: "The resulting `refund_cents` is stamped on the package, the
    package moves to the terminal `REFUNDED` state, and the family's
    `total_refunded_cents` increases by that amount."

    Design: Difficulty/dual_variant_calc/package_refund_provisional_vs_final
    """
    ctx = setup_dual_variant_package()
    package = ctx["packages"][0]

    before = validate_success(api.get_package(package["id"], admin_headers))
    provisional = before["credits_remaining"] * before["per_credit_value_cents"]
    assert provisional == 12 * 12306 == 147672

    refunded = validate_success(api.refund_package(package["id"], admin_headers))
    assert refunded["refund_cents"] != provisional, (
        "FINAL claws the sibling discount back; the provisional estimate must differ"
    )

    family = validate_success(api.get_family(ctx["family"]["id"], admin_headers))
    assert family["total_refunded_cents"] == 142900


def test_group_package_pricing_tier_and_multiplier(api, admin_headers):
    """PRD §3.5: "the tier rate is 15000 cents per credit when `credits_total`
    is 8 or fewer, 13500 cents per credit when `credits_total` is from 9 to 16
    inclusive, and 12000 cents per credit when `credits_total` is 17 or more;
    this rate is then multiplied by the track multiplier — 1.00 for
    `INDIVIDUAL`, 0.60 for `GROUP` — and the product is rounded half-up to an
    integer number of cents, yielding `unit_gross_cents`."
    PRD §3.5: "Step four adds a flat materials fee of 2500 cents, which is
    never discounted, producing `price_paid_cents`."

    Design: Difficulty/combinatorial_formula/package_pricing_tier_track_sibling_interplay
    """
    family = create_family("Fam X", "x@example.com")
    add_client(family["id"], track="GROUP", full_name="Kid X",
               date_of_birth="2015-01-01")
    activate_family(family["id"])
    package = purchase_package(family["id"], "GROUP", 20)
    # One client: no sibling discount. unit = round(12000 x 0.60) = 7200.
    assert package["unit_gross_cents"] == 7200
    assert package["price_paid_cents"] == 146500  # 7200 x 20 + 2500
    assert package["per_credit_value_cents"] == 7325  # round_half_up(146500/20)
    assert_inv_credits(package)


def test_individual_package_pricing_with_sibling_discount(api, admin_headers):
    """PRD §3.5: "when the family has at least 2 clients whose status is
    `INTAKE`, `ACTIVE`, or `PAUSED` at purchase time, the subtotal is
    multiplied by 0.90 and rounded half-up again — a 10 percent discount. Step
    four adds a flat materials fee of 2500 cents, which is never discounted,
    producing `price_paid_cents`. Step five derives the
    `per_credit_value_cents`, the provisional per-credit value, as
    `price_paid_cents` divided by `credits_total`, rounded half-up."

    Design: Difficulty/combinatorial_formula/package_pricing_tier_track_sibling_interplay
    """
    family = create_family("Fam Y", "y@example.com")
    add_client(family["id"], track="INDIVIDUAL", full_name="Kid Y1",
               date_of_birth="2014-01-01")
    add_client(family["id"], track="INDIVIDUAL", full_name="Kid Y2",
               date_of_birth="2016-01-01")
    activate_family(family["id"])
    package = purchase_package(family["id"], "INDIVIDUAL", 20)
    # Two clients: subtotal 240000 x 0.9 = 216000, fee added undiscounted.
    assert package["unit_gross_cents"] == 12000
    assert package["price_paid_cents"] == 218500  # 216000 + 2500
    assert package["per_credit_value_cents"] == 10925  # round_half_up(218500/20)
    assert_inv_credits(package)


def test_package_expiry_computed_as_purchase_plus_180_days(api, admin_headers):
    """PRD §3.5: "The package records `purchased_at` from the logical clock and
    computes `expires_at` as exactly 180 days after purchase."
    PRD §2.4: "At startup, before any administrative intervention, the logical
    clock holds exactly `2026-08-01T00:00:00Z`; it must not silently fall back
    to real time."

    Design: Corner/entities/package_expiry_computed_as_purchase_plus_180_days
    """
    family = create_family("Fam EX", "ex@example.com")
    add_client(family["id"], full_name="Kid EX")
    activate_family(family["id"])
    package = purchase_package(family["id"], "INDIVIDUAL", 2)

    purchased = parse_instant(package["purchased_at"])
    expires = parse_instant(package["expires_at"])
    assert purchased == parse_instant("2026-08-01T00:00:00Z")
    assert expires == purchased + timedelta(days=180)
    assert expires == parse_instant("2027-01-28T00:00:00Z")
    assert package["status"] == "ACTIVE"
    assert package["credits_remaining"] == 2


def test_package_refund_from_exhausted_rejected(api, admin_headers):
    """PRD §3.5: "The actual refund — the FINAL variant — runs when an
    administrator refunds a package in `ACTIVE` or `EXPIRED` status (refund
    from `EXHAUSTED` or `REFUNDED` is rejected with
    `ERR_PACKAGE_NOT_REFUNDABLE`; the family must not be `CLOSED`, else
    `ERR_FAMILY_NOT_ACTIVE`)."
    PRD §3.5: "When `credits_remaining` reaches zero after a consume or forfeit
    mutation, an `ACTIVE` package moves to `EXHAUSTED`"

    Design: Corner/state_machines/package_refund_from_exhausted_rejected
    """
    ctx = setup_active_plan_scenario(
        account_name="Fam PR",
        primary_email="pr@example.com",
        package={"track": "INDIVIDUAL", "credits_total": 1},
    )
    plan, coach, package = ctx["plans"][0], ctx["coach"], ctx["packages"][0]
    session = schedule_session_ok(plan["id"], coach["id"], package["id"],
                                  "2026-08-03T15:00:00Z", "2026-08-03T16:00:00Z")
    set_clock("2026-08-03T15:30:00Z")
    get_success_data(
        api.complete_session(session["id"], make_coach_headers(coach["id"]))
    )
    exhausted = validate_success(api.get_package(package["id"], admin_headers))
    assert exhausted["status"] == "EXHAUSTED"
    assert exhausted["credits_remaining"] == 0

    resp = api.refund_package(package["id"], admin_headers)
    validate_error(resp, ApiErrorId.ERR_PACKAGE_NOT_REFUNDABLE)


def test_package_expiry_boundary_via_sweep(api, admin_headers):
    """PRD §2.4: "first, every `ACTIVE` package whose expiry instant has been
    reached or passed is moved to `EXPIRED` if it still holds remaining
    credits, or to `EXHAUSTED` if none remain"
    PRD §2.4: "The sweep returns a summary with `packages_expired`,
    `packages_exhausted`, `checkins_missed`, `consents_expired`, and
    `coaches_recomputed` counts."

    Design: Corner/calculations/package_expiry_boundary_via_sweep
    """
    family = create_family("Fam PX", "px@example.com")
    add_client(family["id"], full_name="Kid PX", date_of_birth="2014-03-15")
    activate_family(family["id"])
    package = purchase_package(family["id"], "INDIVIDUAL", 2)

    # now == expires_at exactly: expiry is inclusive ("reached or passed").
    set_clock("2027-01-28T00:00:00Z")
    summary = run_sweep()
    assert summary["packages_expired"] == 1

    after = validate_success(api.get_package(package["id"], admin_headers))
    assert after["status"] == "EXPIRED", (
        "remaining 2 > 0 rules out the EXHAUSTED route"
    )
