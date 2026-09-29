"""
Dual-variant calculations of the Digital Estate Fiduciary Access API.

Two arithmetic rules in this contract each carry two mutually exclusive
variants that must diverge on byte-identical inputs:

  * the appraisal basis of a valuation run — ``DATE_OF_DEATH`` takes the
    account's quote unchanged while ``ALTERNATE`` decays it by the account
    category's monthly rate over six months; and
  * the refund entitlement formula selected by the cancellation order's
    snapshotted policy — ``PRORATA_DAILY`` prices every claimed day while
    ``UNUSED_PERIOD`` prices only whole 30-day blocks.

Every test builds its own estate from scratch against an empty database whose
logical clock sits at the fresh-server epoch.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    BASIS_ALTERNATE,
    BASIS_DATE_OF_DEATH,
    CATEGORY_CLOUD_STORAGE,
    CLAIM_FILED,
    METHOD_PRORATA_DAILY,
    METHOD_UNUSED_PERIOD,
    REFUND_POLICY_PRORATA_DAILY,
    REFUND_POLICY_UNUSED_PERIOD,
    RUN_COMPUTED,
    RUN_SUPERSEDED,
    TRANSFERABLE,
)

# The single cloud-storage account every appraisal test in this module values.
CLOUD_QUOTE_CENTS = 400033
CLOUD_DOD_APPRAISAL_CENTS = 400033
CLOUD_ALTERNATE_APPRAISAL_CENTS = 388032

# The identical annual term and claimed interval every refund test uses.
TERM_START = "2026-01-01"
TERM_END = "2026-12-31"
TERM_FEE_CENTS = 11999
TERM_DAYS = 365
CLAIM_START = "2026-03-16"
CLAIM_END = "2026-12-31"
CLAIMED_DAYS = 291
PRORATA_ENTITLEMENT_CENTS = 9566
UNUSED_ENTITLEMENT_CENTS = 8876


def _disclosed_cloud_estate(api, case_number):
    """An estate holding one disclosed, TRANSFERABLE cloud-storage account."""
    fx.set_clock(api)
    platform = fx.register_platform(
        api,
        name="CloudVault",
        transfer_fee_cents=0,
        request_fee_cents=0,
        license_terminates_at_death=False,
        supports_transfer=True,
    )
    ctx = fx.authorized_estate(api, case_number, date_of_death="2026-02-14")
    asset = fx.add_asset(
        api,
        ctx,
        platform["id"],
        category=CATEGORY_CLOUD_STORAGE,
        account_handle="vault-primary",
        quoted_value_cents=CLOUD_QUOTE_CENTS,
    )
    beneficiary = fx.add_beneficiary(
        api, ctx, beneficiary_name="Ives Family Trust", share_bp=10000
    )
    fx.approved_request(api, ctx, platform["id"], platform["form_code"])
    asset = fx.read_asset(api, ctx, asset["id"])
    assert asset["transferability"] == TRANSFERABLE, (
        f"Setup expected a TRANSFERABLE account, got {asset['transferability']!r}"
    )
    return ctx, platform, asset, beneficiary


def _create_run(api, ctx, basis):
    return validate_success(
        api.create_valuation_run(
            ctx.estate_id,
            f.valuation_run_payload(fx.estate_version(api, ctx), basis=basis),
            ctx.fiduciary_headers,
        ),
        201,
    )


def test_date_of_death_basis_appraises_the_quote_without_any_adjustment(api):
    """
    A DATE_OF_DEATH run over one disclosed, transferable cloud-storage account
    whose provider charges no transfer fee takes the 400033-cent quote through
    unchanged, so the account's appraisal, the run's included count and the
    run's gross are all that one number.

    "Under `DATE_OF_DEATH` the gross is the account's `quoted_value_cents` exactly, with no adjustment."

    "An account enters the roll-up only if its `transferability` is exactly `TRANSFERABLE` **and** its `access_status` is `CATALOG_DISCLOSED` or `CONTENT_DISCLOSED`."

    "`gross_value_cents` is the sum of the `appraised_value_cents` of the included accounts and `included_asset_count` is how many there were."

    Design: Difficulty/dual_variant_calc/alternate_basis_decay_diverges_from_date_of_death_appraisal
    """
    ctx, _platform, asset, _beneficiary = _disclosed_cloud_estate(api, "PR-2737-A1")

    run = _create_run(api, ctx, BASIS_DATE_OF_DEATH)

    assert run["basis"] == BASIS_DATE_OF_DEATH
    assert run["included_asset_count"] == 1
    assert run["gross_value_cents"] == CLOUD_DOD_APPRAISAL_CENTS

    priced = fx.read_asset(api, ctx, asset["id"])
    assert priced["appraised_value_cents"] == CLOUD_DOD_APPRAISAL_CENTS
    assert priced["appraised_basis"] == BASIS_DATE_OF_DEATH


def test_date_of_death_run_takes_the_lowest_tier_cap_and_deducts_only_actual_costs(api):
    """
    The same DATE_OF_DEATH run's gross of 400033 cents sits below 500000, so
    the deduction cap is 25000; the estate's only approved request is against a
    provider charging no request fee and no refund claim exists, so the actual
    costs are 0 and the smaller of the two is deducted, leaving the taxable
    figure equal to the gross and the sole whole-estate beneficiary planned for
    all of it.

    "The administrative-expense deduction is capped by a tier selected **from the gross**, never from the post-deduction figure: a gross below 500000 selects a `deduction_cap_cents` of 25000, a gross below 5000000 selects 150000, and any larger gross selects 400000."

    "`admin_deduction_cents` is the smaller of the cap and those actual costs, so a frugal estate deducts only what it spent while a costly one is held to its tier."

    "`taxable_value_cents` is the gross minus the deduction, floored at zero."

    "The three figures are mirrored onto the estate as `gross_digital_estate_cents`, `admin_deduction_cents` and `taxable_digital_estate_cents`, the estate's `valuation_basis` mirrors the basis of its newest `COMPUTED` or `FINALIZED` run, and `undistributed_value_cents` is set to the gross minus the sum of `received_value_cents` across the estate's designations."

    "In the first pass each designation's `planned_allocation_cents` is the pool multiplied by that designation's `share_bp`, divided by 10000, with the fractional part **discarded** — always floored, never rounded."

    Design: Difficulty/dual_variant_calc/alternate_basis_decay_diverges_from_date_of_death_appraisal
    """
    ctx, _platform, _asset, beneficiary = _disclosed_cloud_estate(api, "PR-2737-A2")

    run = _create_run(api, ctx, BASIS_DATE_OF_DEATH)

    assert run["gross_value_cents"] == CLOUD_DOD_APPRAISAL_CENTS
    assert run["deduction_cap_cents"] == 25000
    assert run["admin_deduction_cents"] == 0
    assert run["taxable_value_cents"] == CLOUD_DOD_APPRAISAL_CENTS

    estate = fx.read_estate(api, ctx)
    assert estate["gross_digital_estate_cents"] == CLOUD_DOD_APPRAISAL_CENTS
    assert estate["admin_deduction_cents"] == 0
    assert estate["taxable_digital_estate_cents"] == CLOUD_DOD_APPRAISAL_CENTS
    assert estate["undistributed_value_cents"] == CLOUD_DOD_APPRAISAL_CENTS
    assert estate["valuation_basis"] == BASIS_DATE_OF_DEATH

    planned = fx.read_designation(api, ctx, beneficiary["id"])
    assert planned["planned_allocation_cents"] == CLOUD_DOD_APPRAISAL_CENTS


def test_alternate_basis_decays_the_same_quote_and_supersedes_the_earlier_run(api):
    """
    Re-running the identical single-account inventory on the ALTERNATE basis
    decays the cloud-storage quote by 50 basis points a month over six months,
    turning 400033 cents into 388032 cents — a 12001-cent divergence from the
    DATE_OF_DEATH run, which the new run supersedes and whose mirrored estate
    figures and planned allocation it overwrites.

    "Under `ALTERNATE` the value is decayed for the six months between the date of death and the alternate valuation date: each account `category` carries a monthly decay rate in basis points — `FINANCIAL_ACCOUNT` 0, `EMAIL` 0, `SUBSCRIPTION` 0, `CLOUD_STORAGE` 50, `LOYALTY_PROGRAM` 150, `SOCIAL_PROFILE` 200 — and the total decay is that monthly rate multiplied by 6."

    "The gross is then `quoted_value_cents` multiplied by the quantity 10000 minus the total decay basis points, divided by 10000, rounded half up to a whole cent."

    "Creating a run moves every one of the estate's existing `COMPUTED` runs to the terminal `SUPERSEDED` and opens the new run at `COMPUTED`."

    "In the first pass each designation's `planned_allocation_cents` is the pool multiplied by that designation's `share_bp`, divided by 10000, with the fractional part **discarded** — always floored, never rounded."

    Design: Difficulty/dual_variant_calc/alternate_basis_decay_diverges_from_date_of_death_appraisal
    """
    ctx, _platform, asset, beneficiary = _disclosed_cloud_estate(api, "PR-2737-A3")

    dod_run = _create_run(api, ctx, BASIS_DATE_OF_DEATH)
    assert dod_run["gross_value_cents"] == CLOUD_DOD_APPRAISAL_CENTS

    # The estate's alternate valuation date is 2026-08-14; move the clock past it.
    fx.set_clock(api, "2026-08-20T00:00:00Z")
    alt_run = _create_run(api, ctx, BASIS_ALTERNATE)

    assert alt_run["basis"] == BASIS_ALTERNATE
    assert alt_run["included_asset_count"] == 1
    assert alt_run["gross_value_cents"] == CLOUD_ALTERNATE_APPRAISAL_CENTS
    assert alt_run["taxable_value_cents"] == CLOUD_ALTERNATE_APPRAISAL_CENTS
    assert dod_run["gross_value_cents"] - alt_run["gross_value_cents"] == 12001, (
        "The two bases must diverge by exactly 12001 cents on the identical inventory"
    )

    assert alt_run["status"] == RUN_COMPUTED
    assert fx.read_run(api, ctx, dod_run["id"])["status"] == RUN_SUPERSEDED

    priced = fx.read_asset(api, ctx, asset["id"])
    assert priced["appraised_value_cents"] == CLOUD_ALTERNATE_APPRAISAL_CENTS
    assert priced["appraised_basis"] == BASIS_ALTERNATE

    estate = fx.read_estate(api, ctx)
    assert estate["gross_digital_estate_cents"] == CLOUD_ALTERNATE_APPRAISAL_CENTS
    assert estate["valuation_basis"] == BASIS_ALTERNATE
    assert (
        fx.read_designation(api, ctx, beneficiary["id"])["planned_allocation_cents"]
        == CLOUD_ALTERNATE_APPRAISAL_CENTS
    )


def _subscription_runway(api, ctx, *, name, form_code, refund_policy, handle, reference):
    """
    Register one subscription provider, inventory one subscription account with
    the standard annual term, disclose it through an approved catalogue request
    and drive the auto-created cancellation order to CONFIRMED.
    """
    platform = fx.register_subscription_platform(
        api,
        name=name,
        form_code=form_code,
        refund_policy=refund_policy,
        review_window_days=7,
        transfer_fee_cents=0,
        request_fee_cents=0,
    )
    built = fx.subscription_with_confirmed_order(
        api,
        ctx,
        platform,
        account_handle=handle,
        term_overrides={
            "term_start_date": TERM_START,
            "term_end_date": TERM_END,
            "billing_interval": "ANNUAL",
            "period_fee_cents": TERM_FEE_CENTS,
            "auto_renew": True,
        },
        effective_date="2026-03-15",
        platform_reference=reference,
    )
    built["platform"] = platform
    return built


def test_prorata_daily_policy_prices_every_claimed_day_of_the_term(api):
    """
    A cancellation order that snapshotted PRORATA_DAILY hands its method to the
    refund claim, and the 291-day claimed interval inside a 365-day term paid
    11999 cents earns 11999 * 291 / 365 rounded half up — 9566 cents — while
    the term's claimed-day total rises by exactly those 291 days.

    "For every account the second hop has just disclosed whose `category` is `SUBSCRIPTION` and which does not already have a cancellation order, the system creates a **`CancellationOrder`** in `PENDING` status and copies the provider's `refund_policy` into the order's `refund_policy_snapshot` at that moment."

    "The term is a **closed** interval: both endpoints are inside it, so `term_days` is the number of days from `term_start_date` to `term_end_date` plus one, and a term whose two dates are equal is one day long."

    "The claimed period is also a **closed** interval, so `claimed_days` is the day count from `claimed_period_start` to `claimed_period_end` plus one."

    "The claim's `method` is copied from the order's `refund_policy_snapshot`, and it selects one of two entitlement formulas, both of which take the term's `period_fee_cents` as the refundable pool and the term's `term_days` as the divisor."

    "Under `PRORATA_DAILY` the entitlement is `period_fee_cents` multiplied by `claimed_days`, divided by `term_days`, with the quotient rounded half up to a whole cent: every claimed day earns its share."

    "A new claim opens with `status` at `FILED` and `credited_cents` at 0, and the term's `claimed_days_total` — defined as the sum of `claimed_days` across the claims on that term in `FILED`, `PLATFORM_REVIEW`, `ESCALATED` or `CREDITED` — rises by this claim's `claimed_days`."

    Design: Difficulty/dual_variant_calc/unused_period_refund_diverges_from_prorata_daily_on_identical_interval
    """
    fx.set_clock(api)
    ctx = fx.authorized_estate(api, "PR-2737-B1", date_of_death="2026-02-14")
    built = _subscription_runway(
        api,
        ctx,
        name="StreamOne",
        form_code="SO-FORM-9",
        refund_policy=REFUND_POLICY_PRORATA_DAILY,
        handle="streamone-annual",
        reference="SO-CANCEL-1",
    )

    assert fx.read_term(api, ctx, built["term"]["id"])["term_days"] == TERM_DAYS
    assert built["order"]["refund_policy_snapshot"] == REFUND_POLICY_PRORATA_DAILY

    claim = fx.file_refund_claim(
        api, ctx, built["order"]["id"], CLAIM_START, CLAIM_END, pursuit_cost_cents=0
    )

    assert claim["method"] == METHOD_PRORATA_DAILY
    assert claim["claimed_days"] == CLAIMED_DAYS
    assert claim["claimed_cents"] == PRORATA_ENTITLEMENT_CENTS
    assert claim["status"] == CLAIM_FILED
    assert claim["credited_cents"] == 0
    assert fx.read_term(api, ctx, built["term"]["id"])["claimed_days_total"] == CLAIMED_DAYS


def test_unused_period_policy_prices_only_whole_thirty_day_blocks(api):
    """
    A cancellation order that snapshotted UNUSED_PERIOD collapses the identical
    291-day claimed interval to floor(291 / 30) * 30 = 270 billable days, so the
    same 365-day term paid 11999 cents yields 11999 * 270 / 365 rounded half up
    — 8876 cents — even though the interval itself is still 291 days long.

    "For every account the second hop has just disclosed whose `category` is `SUBSCRIPTION` and which does not already have a cancellation order, the system creates a **`CancellationOrder`** in `PENDING` status and copies the provider's `refund_policy` into the order's `refund_policy_snapshot` at that moment."

    "The claim's `method` is copied from the order's `refund_policy_snapshot`, and it selects one of two entitlement formulas, both of which take the term's `period_fee_cents` as the refundable pool and the term's `term_days` as the divisor."

    "The billable day count is the number of complete 30-day blocks inside `claimed_days` — that is, `claimed_days` divided by 30 with the fractional part discarded — multiplied back by 30; the entitlement is then `period_fee_cents` multiplied by that billable day count, divided by `term_days`, rounded half up."

    "A new claim opens with `status` at `FILED` and `credited_cents` at 0, and the term's `claimed_days_total` — defined as the sum of `claimed_days` across the claims on that term in `FILED`, `PLATFORM_REVIEW`, `ESCALATED` or `CREDITED` — rises by this claim's `claimed_days`."

    Design: Difficulty/dual_variant_calc/unused_period_refund_diverges_from_prorata_daily_on_identical_interval
    """
    fx.set_clock(api)
    ctx = fx.authorized_estate(api, "PR-2737-B2", date_of_death="2026-02-14")
    built = _subscription_runway(
        api,
        ctx,
        name="ReadDeck",
        form_code="RD-FORM-4",
        refund_policy=REFUND_POLICY_UNUSED_PERIOD,
        handle="readdeck-annual",
        reference="RD-CANCEL-1",
    )

    assert fx.read_term(api, ctx, built["term"]["id"])["term_days"] == TERM_DAYS
    assert built["order"]["refund_policy_snapshot"] == REFUND_POLICY_UNUSED_PERIOD

    claim = fx.file_refund_claim(
        api, ctx, built["order"]["id"], CLAIM_START, CLAIM_END, pursuit_cost_cents=0
    )

    assert claim["method"] == METHOD_UNUSED_PERIOD
    assert claim["claimed_days"] == CLAIMED_DAYS
    assert claim["claimed_cents"] == UNUSED_ENTITLEMENT_CENTS
    assert claim["status"] == CLAIM_FILED
    assert claim["credited_cents"] == 0
    assert fx.read_term(api, ctx, built["term"]["id"])["claimed_days_total"] == CLAIMED_DAYS


def test_the_two_refund_policies_diverge_by_690_cents_on_byte_identical_terms(api):
    """
    Two subscription accounts of one estate carrying byte-identical terms —
    2026-01-01 to 2026-12-31, 11999 cents, 365 days — and the identical claimed
    interval 2026-03-16 to 2026-12-31 differ only in the policy their provider
    snapshotted onto the cancellation order, and that single difference moves
    the entitlement from 9566 to 8876 cents.

    "Under `PRORATA_DAILY` the entitlement is `period_fee_cents` multiplied by `claimed_days`, divided by `term_days`, with the quotient rounded half up to a whole cent: every claimed day earns its share."

    "The billable day count is the number of complete 30-day blocks inside `claimed_days` — that is, `claimed_days` divided by 30 with the fractional part discarded — multiplied back by 30; the entitlement is then `period_fee_cents` multiplied by that billable day count, divided by `term_days`, rounded half up."

    Design: Difficulty/dual_variant_calc/unused_period_refund_diverges_from_prorata_daily_on_identical_interval
    """
    fx.set_clock(api)
    ctx = fx.authorized_estate(api, "PR-2737-B3", date_of_death="2026-02-14")
    prorata = _subscription_runway(
        api,
        ctx,
        name="StreamOne",
        form_code="SO-FORM-9",
        refund_policy=REFUND_POLICY_PRORATA_DAILY,
        handle="streamone-annual",
        reference="SO-CANCEL-1",
    )
    unused = _subscription_runway(
        api,
        ctx,
        name="ReadDeck",
        form_code="RD-FORM-4",
        refund_policy=REFUND_POLICY_UNUSED_PERIOD,
        handle="readdeck-annual",
        reference="RD-CANCEL-1",
    )

    assert fx.read_term(api, ctx, prorata["term"]["id"])["term_days"] == TERM_DAYS
    assert fx.read_term(api, ctx, unused["term"]["id"])["term_days"] == TERM_DAYS

    prorata_claim = fx.file_refund_claim(
        api, ctx, prorata["order"]["id"], CLAIM_START, CLAIM_END, pursuit_cost_cents=0
    )
    unused_claim = fx.file_refund_claim(
        api, ctx, unused["order"]["id"], CLAIM_START, CLAIM_END, pursuit_cost_cents=0
    )

    assert prorata_claim["method"] == METHOD_PRORATA_DAILY
    assert unused_claim["method"] == METHOD_UNUSED_PERIOD
    assert prorata_claim["claimed_days"] == CLAIMED_DAYS
    assert unused_claim["claimed_days"] == CLAIMED_DAYS
    assert prorata_claim["claimed_cents"] == PRORATA_ENTITLEMENT_CENTS
    assert unused_claim["claimed_cents"] == UNUSED_ENTITLEMENT_CENTS
    assert prorata_claim["claimed_cents"] - unused_claim["claimed_cents"] == 690, (
        "The two policies must diverge by exactly 690 cents on the identical interval"
    )
