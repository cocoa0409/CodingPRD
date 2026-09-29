"""Composed money formulas of the Money Transmitter Licensing API.

Three computations are exercised here, each of which produces an integer that no
single input can explain: the four-step surety bond requirement of PRD 3.4, the
per-line whole-dollar rounding of the annual assessment invoice of PRD 3.5, and
the renewal fee whose tier rate is selected from the pre-assessment subtotal.

Every expected figure below is a literal computed by hand from the PRD prose
quoted in the test's own docstring; the arithmetic is shown in a comment beside
the assertion.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import MoneyTransmitterApiClient
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_RENEWAL_FEE_MISMATCH
from test_helpers.test_users import MANAGER_HEADERS

# ---------------------------------------------------------------------------
# The surety bond requirement: tier, statutory floor, class multiplier, cap
# ---------------------------------------------------------------------------


def test_submitted_application_composes_tier_floor_and_class_multiplier(
    api: MoneyTransmitterApiClient,
) -> None:
    """A Texas PAYMENT_INSTRUMENTS submission pins a bond of 36,000,000 cents.

    PRD 3.4: "Step one selects a tier bond from the relevant volume figure: the application's `projected_annual_volume_cents` in an application context, or the licence's `annual_volume_cents` in a licence context."
    PRD 3.4: "A volume of at most one billion cents — that is, ten million dollars — is tier one at a tier bond of two and a half million cents; a volume above one billion cents but at most ten billion cents is tier two at ten million cents; a volume above ten billion cents is tier three at twenty-five million cents."
    PRD 3.4: "Step two takes the greater of the jurisdiction's `base_bond_cents` and the sum of the tier bond plus the delegate count multiplied by the jurisdiction's `per_delegate_bond_cents`; the delegate count is zero in an application context and the licence's `active_delegate_count` otherwise."
    PRD 3.4: "Step three multiplies that figure by the class multiplier for the `license_class` and divides by 10000, rounding down: `MONEY_TRANSMISSION` carries a multiplier of 10000 basis points and therefore leaves the figure unchanged, `PAYMENT_INSTRUMENTS` carries 12000 basis points, and `VIRTUAL_CURRENCY` carries 15000 basis points."
    PRD 3.4: "Step four takes the lesser of that result and the jurisdiction's `bond_cap_cents`."
    PRD 3.4: "Applying the statutory floor after the multiplier, or the cap before it, produces a different figure and is wrong."
    PRD 3.3: "On success the application moves `DRAFT → SUBMITTED`, `submitted_at` is stamped from the logical clock, `required_net_worth_cents` is pinned as a copy of the jurisdiction's `min_net_worth_cents`, and `required_bond_cents` is pinned to the surety bond figure computed as described in §3.4, using the jurisdiction configuration, the submitted `projected_annual_volume_cents`, the declared `license_class`, and a delegate count of zero — an applicant has no active delegates yet by definition."

    Design: Difficulty/combinatorial_formula/bond_requirement_composes_tier_floor_multiplier_and_cap
    """
    jurisdiction = fx.create_jurisdiction(api, C.TX_CONFIG)
    licensee = fx.create_licensee(api)
    application = fx.create_application(
        api,
        licensee["id"],
        jurisdiction["id"],
        license_class="PAYMENT_INSTRUMENTS",
        projected_annual_volume_cents=250_000_000,
    )

    submitted = fx.submit_application(api, application["id"])

    assert submitted["status"] == "SUBMITTED"
    # Tier: 250,000,000 <= 1,000,000,000 -> 2,500,000.
    # Floor: max(base 30,000,000, 2,500,000 + 0 * 250,000) = 30,000,000.
    # Class: floor(30,000,000 * 12000 / 10000) = 36,000,000.
    # Cap: min(36,000,000, 60,000,000) = 36,000,000.
    assert submitted["required_bond_cents"] == 36_000_000
    # required_net_worth_cents is a plain copy of the Texas min_net_worth_cents.
    assert submitted["required_net_worth_cents"] == 100_000_000


def test_bond_cap_is_applied_after_the_class_multiplier_and_is_copied_to_the_licence(
    api: MoneyTransmitterApiClient,
) -> None:
    """A 33,000,000 cent cap trims the post-multiplier 36,000,000 and the licence inherits it.

    PRD 3.4: "Step two takes the greater of the jurisdiction's `base_bond_cents` and the sum of the tier bond plus the delegate count multiplied by the jurisdiction's `per_delegate_bond_cents`; the delegate count is zero in an application context and the licence's `active_delegate_count` otherwise."
    PRD 3.4: "Step three multiplies that figure by the class multiplier for the `license_class` and divides by 10000, rounding down: `MONEY_TRANSMISSION` carries a multiplier of 10000 basis points and therefore leaves the figure unchanged, `PAYMENT_INSTRUMENTS` carries 12000 basis points, and `VIRTUAL_CURRENCY` carries 15000 basis points."
    PRD 3.4: "Step four takes the lesser of that result and the jurisdiction's `bond_cap_cents`."
    PRD 3.4: "Applying the statutory floor after the multiplier, or the cap before it, produces a different figure and is wrong."
    PRD 3.3: "It starts with `license_status` `PENDING_BOND`, `reporting_status` `CURRENT`, `expansion_gate` `BLOCKED`, `bond_status` `NONE`, `outstanding_obligations_cents` zero, and `bond_requirement_cents` copied from the application's `required_bond_cents`."

    Design: Difficulty/combinatorial_formula/bond_requirement_composes_tier_floor_multiplier_and_cap
    """
    capped_texas = dict(C.TX_CONFIG, bond_cap_cents=33_000_000)
    scenario = fx.setup_pending_bond_license(
        api,
        jurisdiction_config=capped_texas,
        application_overrides={
            "license_class": "PAYMENT_INSTRUMENTS",
            "projected_annual_volume_cents": 250_000_000,
        },
    )

    application = validate_success(api.get_application(scenario.application_id, MANAGER_HEADERS))
    license_row = fx.get_license(api, scenario.license_id)

    # Tier 2,500,000; floor max(30,000,000, 2,500,000) = 30,000,000;
    # class floor(30,000,000 * 12000 / 10000) = 36,000,000; cap min(36,000,000, 33,000,000).
    # Capping before the multiplier would instead read
    # floor(min(30,000,000, 33,000,000) * 12000 / 10000) = 36,000,000.
    assert application["required_bond_cents"] == 33_000_000
    assert license_row["bond_requirement_cents"] == 33_000_000
    assert license_row["license_status"] == "PENDING_BOND"


def test_licence_bond_requirement_recomposes_from_filed_volume_and_active_delegate(
    api: MoneyTransmitterApiClient,
) -> None:
    """A filed volume tier plus one activated delegate recompute the bond to 15,049,999 cents.

    PRD 3.4: "Step one selects a tier bond from the relevant volume figure: the application's `projected_annual_volume_cents` in an application context, or the licence's `annual_volume_cents` in a licence context."
    PRD 3.4: "A volume of at most one billion cents — that is, ten million dollars — is tier one at a tier bond of two and a half million cents; a volume above one billion cents but at most ten billion cents is tier two at ten million cents; a volume above ten billion cents is tier three at twenty-five million cents."
    PRD 3.4: "Step two takes the greater of the jurisdiction's `base_bond_cents` and the sum of the tier bond plus the delegate count multiplied by the jurisdiction's `per_delegate_bond_cents`; the delegate count is zero in an application context and the licence's `active_delegate_count` otherwise."
    PRD 3.4: "Step three multiplies that figure by the class multiplier for the `license_class` and divides by 10000, rounding down: `MONEY_TRANSMISSION` carries a multiplier of 10000 basis points and therefore leaves the figure unchanged, `PAYMENT_INSTRUMENTS` carries 12000 basis points, and `VIRTUAL_CURRENCY` carries 15000 basis points."
    PRD 3.4: "Step four takes the lesser of that result and the jurisdiction's `bond_cap_cents`."
    PRD 3.4: "The requirement is recomputed on application submission, on application resubmission, on every delegate authorization activation, termination or suspension, and on every call report that changes the licence's annual volume."
    PRD 3.5: "Regardless of status, every filing adds its `transmission_volume_cents` to the licence's `annual_volume_cents` and recomputes `bond_requirement_cents`, since the volume tier may have moved."
    PRD 3.6: "The licence's `active_delegate_count` increases by one and its `bond_requirement_cents` is recomputed with the new delegate count — which is how onboarding an agent can raise a bond requirement above the posted bond."

    Design: Difficulty/combinatorial_formula/bond_requirement_composes_tier_floor_multiplier_and_cap
    """
    config = dict(
        C.CA_CONFIG,
        base_bond_cents=1_000_000,
        per_delegate_bond_cents=33_333,
        bond_cap_cents=40_000_000,
    )
    scenario = fx.setup_active_license(
        api,
        jurisdiction_config=config,
        application_overrides={
            "license_class": "VIRTUAL_CURRENCY",
            "projected_annual_volume_cents": 2_000_000_000,
        },
    )

    # Tier 2 (2,000,000,000 > 1,000,000,000); max(1,000,000, 10,000,000) = 10,000,000;
    # floor(10,000,000 * 15000 / 10000) = 15,000,000; min(15,000,000, 40,000,000).
    assert fx.get_license(api, scenario.license_id)["bond_requirement_cents"] == 15_000_000

    fx.file_call_report(api, scenario.license_id, "2026Q2", 2_000_000_000, 500)
    after_report = fx.get_license(api, scenario.license_id)
    assert after_report["annual_volume_cents"] == 2_000_000_000
    assert after_report["reporting_status"] == "CURRENT"
    # Same tier 2 out of the licence's own volume, still with no active delegate.
    assert after_report["bond_requirement_cents"] == 15_000_000

    fx.setup_active_authorization(api, scenario)

    after_activation = fx.get_license(api, scenario.license_id)
    assert after_activation["active_delegate_count"] == 1
    # Tier 10,000,000 + 1 * 33,333 = 10,033,333; the floor 1,000,000 does not bind;
    # 10,033,333 * 15000 / 10000 = 15,049,999.5 -> floor 15,049,999; cap 40,000,000 does not bind.
    assert after_activation["bond_requirement_cents"] == 15_049_999


# ---------------------------------------------------------------------------
# The annual assessment invoice: round every line, then add
# ---------------------------------------------------------------------------


def test_assessment_invoice_rounds_each_line_to_a_whole_dollar_before_summing(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """Two active licences invoice 25,200 cents while their exact raw amounts sum to 25,120.

    PRD 3.5: "Each line's raw amount is that licence's `outstanding_obligations_cents` multiplied by its jurisdiction's `assessment_rate_bps` divided by 10000, kept exact in cents; `unrounded_sum_cents` reports the sum of those exact raw amounts."
    PRD 3.5: "Each line is then rounded to a whole dollar — divide the raw cents by one hundred, round half up, and multiply by one hundred again — and `annual_assessment_total_cents` is the sum of the rounded lines."
    PRD 3.5: "The rounding order is pinned: round every line first, then add."
    PRD 3.5: "Adding first and rounding once produces a different number and is wrong."
    PRD 3.5: "Lines are taken in `created_at` ascending order, which affects no value but is pinned for reproducibility, and `line_item_count` reports how many there were."

    Design: Difficulty/combinatorial_formula/assessment_invoice_rounds_each_line_before_summing
    """
    texas = fx.add_license_in_jurisdiction(api, active_license.licensee_id, C.TX_CONFIG)
    fx.adjust_obligations(api, active_license.license_id, 6_024_000)
    fx.adjust_obligations(api, texas["license"]["id"], 2_515_000)

    summary = fx.get_assessment_summary(api, active_license.licensee_id)

    assert summary["line_item_count"] == 2
    # CA line: 6,024,000 * 25 / 10000 = 15,060 exact.
    # TX line: 2,515,000 * 40 / 10000 = 10,060 exact.
    assert summary["unrounded_sum_cents"] == 25_120
    # Rounded per line: 150.60 -> 151 dollars -> 15,100 and 100.60 -> 101 dollars -> 10,100.
    # Adding the exact amounts first would instead read 251.20 -> 251 dollars -> 25,100.
    assert summary["annual_assessment_total_cents"] == 25_200


def test_assessment_invoice_lines_only_active_licences_but_the_aggregate_keeps_the_rest(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A suspended licence's obligations stay in the aggregate yet produce no invoice line.

    PRD 3.5: "Only licences whose `license_status` is `ACTIVE` produce a line; `PENDING_BOND`, `SUSPENDED`, `SURRENDER_REQUESTED`, `SURRENDERED` and `REVOKED` licences contribute nothing at all."
    PRD 3.5: "Each line's raw amount is that licence's `outstanding_obligations_cents` multiplied by its jurisdiction's `assessment_rate_bps` divided by 10000, kept exact in cents; `unrounded_sum_cents` reports the sum of those exact raw amounts."
    PRD 3.5: "Each line is then rounded to a whole dollar — divide the raw cents by one hundred, round half up, and multiply by one hundred again — and `annual_assessment_total_cents` is the sum of the rounded lines."
    PRD 3.4: "The aggregate itself is the exact sum, in integer cents with no rounding, of `outstanding_obligations_cents` over the licensee's licences whose `license_status` is `PENDING_BOND`, `ACTIVE`, `SUSPENDED` or `SURRENDER_REQUESTED`."
    PRD 3.4: "On acceptance, `bond_status` becomes `CANCELLATION_NOTICED`, the effective date is stored, and the licence moves `ACTIVE → SUSPENDED`, triggering the licence-suspension cascade of §2.9 in full."

    Design: Difficulty/combinatorial_formula/assessment_invoice_rounds_each_line_before_summing
    """
    texas = fx.add_license_in_jurisdiction(api, active_license.licensee_id, C.TX_CONFIG)
    fx.adjust_obligations(api, active_license.license_id, 6_024_000)
    fx.adjust_obligations(api, texas["license"]["id"], 2_515_000)
    get_success_data(
        api.file_bond_cancellation_notice(
            texas["license"]["id"],
            F.bond_cancellation_payload("2026-10-01T00:00:00Z"),
            MANAGER_HEADERS,
        )
    )
    assert fx.get_license(api, texas["license"]["id"])["license_status"] == "SUSPENDED"

    summary = fx.get_assessment_summary(api, active_license.licensee_id)
    licensee = fx.get_licensee(api, active_license.licensee_id)

    assert summary["line_item_count"] == 1
    # Only the ACTIVE California licence lines: 6,024,000 * 25 / 10000 = 15,060 exact.
    assert summary["unrounded_sum_cents"] == 15_060
    # 150.60 dollars rounded half up is 151 dollars -> 15,100 cents.
    assert summary["annual_assessment_total_cents"] == 15_100
    # The suspended Texas licence is still inside the obligation aggregate: 6,024,000 + 2,515,000.
    assert licensee["aggregate_outstanding_obligations_cents"] == 8_539_000


def test_assessment_invoice_rounds_an_exact_half_dollar_line_upward(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """Two lines landing exactly on a half dollar both round up, giving 25,200 over 25,100.

    PRD 3.5: "Each line's raw amount is that licence's `outstanding_obligations_cents` multiplied by its jurisdiction's `assessment_rate_bps` divided by 10000, kept exact in cents; `unrounded_sum_cents` reports the sum of those exact raw amounts."
    PRD 3.5: "Each line is then rounded to a whole dollar — divide the raw cents by one hundred, round half up, and multiply by one hundred again — and `annual_assessment_total_cents` is the sum of the rounded lines."
    PRD 3.5: "The rounding order is pinned: round every line first, then add."
    PRD 3.5: "Adding first and rounding once produces a different number and is wrong."
    PRD 2.5: "**Round half up** governs the assessment step of the renewal fee, the per-report call-report assessment fee, and the per-line whole-dollar rounding of the annual assessment invoice."

    Design: Difficulty/combinatorial_formula/assessment_invoice_rounds_each_line_before_summing
    """
    texas = fx.add_license_in_jurisdiction(api, active_license.licensee_id, C.TX_CONFIG)
    fx.adjust_obligations(api, active_license.license_id, 6_020_000)
    fx.adjust_obligations(api, texas["license"]["id"], 2_512_500)

    summary = fx.get_assessment_summary(api, active_license.licensee_id)

    assert summary["line_item_count"] == 2
    # CA line: 6,020,000 * 25 / 10000 = 15,050 exact. TX line: 2,512,500 * 40 / 10000 = 10,050 exact.
    assert summary["unrounded_sum_cents"] == 25_100
    # 150.50 -> 151 dollars -> 15,100 and 100.50 -> 101 dollars -> 10,100, half up on both.
    # Adding first would read exactly 251.00 dollars -> 25,100 cents.
    assert summary["annual_assessment_total_cents"] == 25_200


# ---------------------------------------------------------------------------
# The renewal fee: the tier rate keys off the pre-assessment subtotal
# ---------------------------------------------------------------------------


def test_renewal_tier_rate_is_selected_from_the_pre_assessment_subtotal(
    api: MoneyTransmitterApiClient,
) -> None:
    """A 245,000 cent subtotal renews at 253,575 cents on the 350 basis point tier.

    PRD 3.5: "First the subtotal: the jurisdiction's `renewal_fee_cents` plus the licence's current `active_delegate_count` multiplied by twenty-five thousand cents — two hundred and fifty dollars per active delegate."
    PRD 3.5: "Second, a tier rate is selected **from that pre-assessment subtotal and never from the final total**: 500 basis points when the subtotal is at most one hundred thousand cents, 350 basis points when the subtotal is above one hundred thousand cents but at most two hundred and fifty thousand cents, and 200 basis points when the subtotal exceeds two hundred and fifty thousand cents."
    PRD 3.5: "Third, the assessment is the subtotal multiplied by the tier rate divided by 10000, rounded half up to whole cents."
    PRD 3.5: "Fourth, the total is the subtotal plus that assessment."
    PRD 3.5: "On a match, `renewal_status` moves from `NOT_RENEWED` to `RENEWED`, `renewal_year` records the year renewed, `renewal_total_fee_cents` records the computed total, and the licence's `version` is bumped."

    Design: Difficulty/combinatorial_formula/renewal_fee_tier_keys_off_pre_assessment_subtotal
    """
    scenario = fx.setup_active_license(api, jurisdiction_config=C.NV_CONFIG)

    # Subtotal 245,000 + 0 * 25,000 = 245,000; tier 350 bps (100,000 < 245,000 <= 250,000);
    # assessment 245,000 * 350 / 10000 = 8,575 exact; total 245,000 + 8,575 = 253,575.
    renewed = validate_success(
        api.renew_license(scenario.license_id, F.renewal_payload(2027, 253_575), MANAGER_HEADERS)
    )

    assert renewed["renewal_total_fee_cents"] == 253_575
    assert renewed["renewal_status"] == "RENEWED"
    assert renewed["renewal_year"] == 2027
    # Renewal moves the reporting-calendar side of the licence only.
    assert renewed["license_status"] == "ACTIVE"


def test_renewal_rejects_the_payment_derived_from_the_post_assessment_tier(
    api: MoneyTransmitterApiClient,
) -> None:
    """Paying 249,900 — the 200 bps answer read off the total — is a fee mismatch.

    PRD 3.5: "Second, a tier rate is selected **from that pre-assessment subtotal and never from the final total**: 500 basis points when the subtotal is at most one hundred thousand cents, 350 basis points when the subtotal is above one hundred thousand cents but at most two hundred and fifty thousand cents, and 200 basis points when the subtotal exceeds two hundred and fifty thousand cents."
    PRD 3.5: "Third, the assessment is the subtotal multiplied by the tier rate divided by 10000, rounded half up to whole cents."
    PRD 3.5: "Fourth, the total is the subtotal plus that assessment."
    PRD 3.5: "The supplied `payment_amount_cents` must equal that total exactly; any other figure is rejected with `ERR_RENEWAL_FEE_MISMATCH` (HTTP 422)."

    Design: Difficulty/combinatorial_formula/renewal_fee_tier_keys_off_pre_assessment_subtotal
    """
    scenario = fx.setup_active_license(api, jurisdiction_config=C.NV_CONFIG)

    # Reading the tier off the resulting total (253,575 > 250,000 -> 200 bps) would charge
    # 245,000 + 245,000 * 200 / 10000 = 245,000 + 4,900 = 249,900, which is not the total.
    validate_error(
        api.renew_license(scenario.license_id, F.renewal_payload(2027, 249_900), MANAGER_HEADERS),
        ERR_RENEWAL_FEE_MISMATCH,
    )

    unrenewed = fx.get_license(api, scenario.license_id)
    assert unrenewed["renewal_status"] == "NOT_RENEWED"

    renewed = validate_success(
        api.renew_license(scenario.license_id, F.renewal_payload(2027, 253_575), MANAGER_HEADERS)
    )
    assert renewed["renewal_total_fee_cents"] == 253_575


def test_active_delegate_pushes_the_renewal_subtotal_into_the_lowest_tier(
    api: MoneyTransmitterApiClient,
) -> None:
    """One active delegate lifts the subtotal to 270,000 and drops the rate to 200 bps.

    PRD 3.5: "First the subtotal: the jurisdiction's `renewal_fee_cents` plus the licence's current `active_delegate_count` multiplied by twenty-five thousand cents — two hundred and fifty dollars per active delegate."
    PRD 3.5: "Second, a tier rate is selected **from that pre-assessment subtotal and never from the final total**: 500 basis points when the subtotal is at most one hundred thousand cents, 350 basis points when the subtotal is above one hundred thousand cents but at most two hundred and fifty thousand cents, and 200 basis points when the subtotal exceeds two hundred and fifty thousand cents."
    PRD 3.5: "Third, the assessment is the subtotal multiplied by the tier rate divided by 10000, rounded half up to whole cents."
    PRD 3.5: "Fourth, the total is the subtotal plus that assessment."
    PRD 3.6: "The licence's `active_delegate_count` increases by one and its `bond_requirement_cents` is recomputed with the new delegate count — which is how onboarding an agent can raise a bond requirement above the posted bond."

    Design: Difficulty/combinatorial_formula/renewal_fee_tier_keys_off_pre_assessment_subtotal
    """
    scenario = fx.setup_active_license(api, jurisdiction_config=C.NV_CONFIG)
    fx.setup_active_authorization(api, scenario)
    assert fx.get_license(api, scenario.license_id)["active_delegate_count"] == 1

    # Subtotal 245,000 + 1 * 25,000 = 270,000; 270,000 > 250,000 so the tier is 200 bps;
    # assessment 270,000 * 200 / 10000 = 5,400 exact; total 270,000 + 5,400 = 275,400.
    renewed = validate_success(
        api.renew_license(scenario.license_id, F.renewal_payload(2027, 275_400), MANAGER_HEADERS)
    )

    assert renewed["renewal_total_fee_cents"] == 275_400
    assert renewed["renewal_status"] == "RENEWED"


def test_renewal_assessment_rounds_half_up_on_the_top_tier_subtotal(
    api: MoneyTransmitterApiClient,
) -> None:
    """A 99,990 cent subtotal takes 500 bps and rounds 4,999.5 up to a 104,990 total.

    PRD 3.5: "First the subtotal: the jurisdiction's `renewal_fee_cents` plus the licence's current `active_delegate_count` multiplied by twenty-five thousand cents — two hundred and fifty dollars per active delegate."
    PRD 3.5: "Second, a tier rate is selected **from that pre-assessment subtotal and never from the final total**: 500 basis points when the subtotal is at most one hundred thousand cents, 350 basis points when the subtotal is above one hundred thousand cents but at most two hundred and fifty thousand cents, and 200 basis points when the subtotal exceeds two hundred and fifty thousand cents."
    PRD 3.5: "Third, the assessment is the subtotal multiplied by the tier rate divided by 10000, rounded half up to whole cents."
    PRD 3.5: "Fourth, the total is the subtotal plus that assessment."
    PRD 2.5: "**Round half up** governs the assessment step of the renewal fee, the per-report call-report assessment fee, and the per-line whole-dollar rounding of the annual assessment invoice."

    Design: Difficulty/combinatorial_formula/renewal_fee_tier_keys_off_pre_assessment_subtotal
    """
    scenario = fx.setup_active_license(
        api, jurisdiction_config=dict(C.NV_CONFIG, renewal_fee_cents=99_990)
    )

    # Subtotal 99,990 + 0 = 99,990, at most 100,000, so the tier is 500 bps;
    # assessment 99,990 * 500 / 10000 = 4,999.5 -> 5,000 half up; total 99,990 + 5,000 = 104,990.
    # The 104,990 total sits in the 350 bps band, so reading the tier off it would charge less.
    renewed = validate_success(
        api.renew_license(scenario.license_id, F.renewal_payload(2027, 104_990), MANAGER_HEADERS)
    )

    assert renewed["renewal_total_fee_cents"] == 104_990
    assert renewed["renewal_status"] == "RENEWED"
