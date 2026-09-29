"""
Boundary and precision behaviour of the Digital Estate Fiduciary Access API.

Every case here sits one unit either side of a threshold the contract states
exactly — the inclusive seven-day refund minimum, the exclusive upper bound of
the first administrative-deduction tier, and the floor-then-remainder split of
the distributable pool — and asserts both sides so an off-by-one, a `<=` for a
`<`, or a half-up rounding shortcut cannot pass.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_REFUND_WINDOW_TOO_SHORT,
    ERR_SHARE_TOTAL_INVALID,
    ERR_STALE_ESTATE_VERSION,
)
from test_helpers.constants import (
    ACCESS_CATALOG_DISCLOSED,
    BASIS_DATE_OF_DEATH,
    CATEGORY_FINANCIAL_ACCOUNT,
    CLAIM_FILED,
    METHOD_PRORATA_DAILY,
    RUN_COMPUTED,
    RUN_SUPERSEDED,
    SOURCE_TRUST,
    SOURCE_WILL,
    TRANSFERABLE,
)


def _confirmed_subscription(api, court_case_number, platform_reference):
    """A CONFIRMED cancellation order over a 2026-01-01..2026-12-31 annual term."""
    platform = fx.register_subscription_platform(api)
    ctx = fx.authorized_estate(api, court_case_number)
    built = fx.subscription_with_confirmed_order(
        api, ctx, platform, platform_reference=platform_reference
    )
    return ctx, built


def test_a_six_day_claimed_period_is_one_day_short_of_the_minimum(api):
    """
    2026-06-01..2026-06-06 counts both endpoints and is therefore 6 days, one
    short of the minimum claimable stretch, so nothing is written.

    "Only after those four checks does the length rule apply: `claimed_days` must be at least 7, so a claim covering exactly 7 days is accepted and one covering 6 is rejected with `ERR_REFUND_WINDOW_TOO_SHORT`."

    Design: Difficulty/boundary_precision_check/refund_minimum_claim_days_boundary_six_versus_seven_days
    """
    fx.set_clock(api)
    ctx, built = _confirmed_subscription(api, "PR-2737-O", "SO-CANCEL-B1")
    order, term = built["order"], built["term"]

    refused = api.create_refund_claim(
        order["id"],
        f.refund_claim_payload("2026-06-01", "2026-06-06"),
        ctx.fid_headers,
    )
    validate_error(refused, ERR_REFUND_WINDOW_TOO_SHORT)

    rows, meta = validate_paginated(
        api.list_refund_claims(ctx.fid_headers, cancellation_order_id=order["id"])
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert fx.read_term(api, ctx, term["id"])["claimed_days_total"] == 0


def test_a_seven_day_claimed_period_is_accepted_and_rounds_half_up_to_230(api):
    """
    2026-06-01..2026-06-07 is exactly 7 days and clears the minimum; over the
    365-day term 11999 * 7 / 365 is 230.06..., which rounds half up to 230 cents
    rather than up to 231.

    "The term is a **closed** interval: both endpoints are inside it, so `term_days` is the number of days from `term_start_date` to `term_end_date` plus one, and a term whose two dates are equal is one day long."

    "The claimed period is also a **closed** interval, so `claimed_days` is the day count from `claimed_period_start` to `claimed_period_end` plus one."

    "Under `PRORATA_DAILY` the entitlement is `period_fee_cents` multiplied by `claimed_days`, divided by `term_days`, with the quotient rounded half up to a whole cent: every claimed day earns its share."

    Design: Difficulty/boundary_precision_check/refund_minimum_claim_days_boundary_six_versus_seven_days
    """
    fx.set_clock(api)
    ctx, built = _confirmed_subscription(api, "PR-2737-O", "SO-CANCEL-B1")
    order, term = built["order"], built["term"]
    assert term["term_days"] == 365

    validate_error(
        api.create_refund_claim(
            order["id"],
            f.refund_claim_payload("2026-06-01", "2026-06-06"),
            ctx.fid_headers,
        ),
        ERR_REFUND_WINDOW_TOO_SHORT,
    )

    claim = validate_success(
        api.create_refund_claim(
            order["id"],
            f.refund_claim_payload("2026-06-01", "2026-06-07"),
            ctx.fid_headers,
        ),
        201,
    )
    assert claim["claimed_days"] == 7
    assert claim["claimed_cents"] == 230
    assert claim["method"] == METHOD_PRORATA_DAILY
    assert claim["status"] == CLAIM_FILED


def test_an_eight_day_claim_prices_263_and_the_term_tallies_fifteen_days(api):
    """
    An eight-day stretch earns 11999 * 8 / 365 = 262.99... -> 263 cents, which is
    not 230 scaled per day, and the term's claimed-day tally sums the seven-day
    and eight-day claims to 15.

    "Under `PRORATA_DAILY` the entitlement is `period_fee_cents` multiplied by `claimed_days`, divided by `term_days`, with the quotient rounded half up to a whole cent: every claimed day earns its share."

    "A new claim opens with `status` at `FILED` and `credited_cents` at 0, and the term's `claimed_days_total` — defined as the sum of `claimed_days` across the claims on that term in `FILED`, `PLATFORM_REVIEW`, `ESCALATED` or `CREDITED` — rises by this claim's `claimed_days`."

    Design: Difficulty/boundary_precision_check/refund_minimum_claim_days_boundary_six_versus_seven_days
    """
    fx.set_clock(api)
    ctx, built = _confirmed_subscription(api, "PR-2737-O", "SO-CANCEL-B1")
    order, term = built["order"], built["term"]

    seven = validate_success(
        api.create_refund_claim(
            order["id"],
            f.refund_claim_payload("2026-06-01", "2026-06-07"),
            ctx.fid_headers,
        ),
        201,
    )
    assert seven["claimed_days"] == 7
    assert seven["claimed_cents"] == 230

    eight = validate_success(
        api.create_refund_claim(
            order["id"],
            f.refund_claim_payload("2026-07-01", "2026-07-08"),
            ctx.fid_headers,
        ),
        201,
    )
    assert eight["claimed_days"] == 8
    assert eight["claimed_cents"] == 263
    assert eight["status"] == CLAIM_FILED
    assert fx.read_term(api, ctx, term["id"])["claimed_days_total"] == 15


def _bank_estate_ready_to_value(api, court_case_number):
    """
    One TRANSFERABLE financial account quoted 502500 on a provider charging a
    2500-cent transfer fee and a 30000-cent request fee, disclosed by an
    approved catalogue request, with a sole beneficiary holding the whole share.
    """
    platform = fx.register_financial_platform(api, requires_court_order_for_content=False)
    ctx = fx.authorized_estate(api, court_case_number)
    asset = fx.add_asset(
        api,
        ctx,
        platform["id"],
        category=CATEGORY_FINANCIAL_ACCOUNT,
        account_handle="bt-savings-8890",
        quoted_value_cents=502500,
    )
    beneficiary = fx.add_beneficiary(api, ctx, beneficiary_name="Ives Family Trust")
    fx.approved_request(api, ctx, platform["id"], platform["form_code"])
    return ctx, platform, asset, beneficiary


def test_gross_is_the_quote_less_the_transfer_fee_at_exactly_five_hundred_thousand(api):
    """
    Under the date-of-death basis the account's 502500-cent quote is reduced only
    by the provider's 2500-cent transfer fee, putting the roll-up gross exactly
    on the first deduction tier's upper bound.

    "Under `DATE_OF_DEATH` the gross is the account's `quoted_value_cents` exactly, with no adjustment."

    "From the gross the provider's `transfer_fee_cents` is then subtracted — the fee the provider charges to move the account to a beneficiary — and the result is floored at zero, so an account whose transfer fee exceeds its decayed gross appraises at 0 rather than a negative number."

    "`gross_value_cents` is the sum of the `appraised_value_cents` of the included accounts and `included_asset_count` is how many there were."

    Design: Difficulty/boundary_precision_check/deduction_cap_tier_switches_at_exactly_five_hundred_thousand_gross_cents
    """
    fx.set_clock(api)
    ctx, _platform, asset, _beneficiary = _bank_estate_ready_to_value(api, "PR-2737-P")

    disclosed = fx.read_asset(api, ctx, asset["id"])
    assert disclosed["transferability"] == TRANSFERABLE
    assert disclosed["access_status"] == ACCESS_CATALOG_DISCLOSED

    run = fx.computed_valuation_run(api, ctx, basis=BASIS_DATE_OF_DEATH)
    assert run["gross_value_cents"] == 500000
    assert run["included_asset_count"] == 1
    assert run["status"] == RUN_COMPUTED
    assert fx.read_asset(api, ctx, asset["id"])["appraised_value_cents"] == 500000


def test_gross_of_exactly_five_hundred_thousand_selects_the_second_deduction_tier(api):
    """
    A gross of 500000 is not below 500000, so the cap is 150000 and the estate's
    only administrative cost — the approved package's 30000-cent request fee —
    is deducted in full, leaving 470000 taxable.

    "The administrative-expense deduction is capped by a tier selected **from the gross**, never from the post-deduction figure: a gross below 500000 selects a `deduction_cap_cents` of 25000, a gross below 5000000 selects 150000, and any larger gross selects 400000."

    "The estate's actual administrative costs are the sum of the `request_fee_cents` of the providers behind every one of the estate's platform requests in `APPROVED` status, plus the sum of the `pursuit_cost_cents` of every refund claim of the estate regardless of that claim's status — the money was spent whether or not the claim succeeded."

    "`admin_deduction_cents` is the smaller of the cap and those actual costs, so a frugal estate deducts only what it spent while a costly one is held to its tier."

    "`taxable_value_cents` is the gross minus the deduction, floored at zero."

    Design: Difficulty/boundary_precision_check/deduction_cap_tier_switches_at_exactly_five_hundred_thousand_gross_cents
    """
    fx.set_clock(api)
    ctx, _platform, _asset, _beneficiary = _bank_estate_ready_to_value(api, "PR-2737-P")

    run = fx.computed_valuation_run(api, ctx, basis=BASIS_DATE_OF_DEATH)
    assert run["gross_value_cents"] == 500000
    assert run["deduction_cap_cents"] == 150000
    assert run["admin_deduction_cents"] == 30000
    assert run["taxable_value_cents"] == 470000


def test_gross_one_cent_lower_drops_to_the_first_tier_and_raises_the_taxable_value(api):
    """
    Raising the transfer fee by a single cent moves the gross to 499999, which is
    below 500000 and therefore caps the deduction at 25000 — so the poorer estate
    ends up with a higher taxable value of 474999.

    "From the gross the provider's `transfer_fee_cents` is then subtracted — the fee the provider charges to move the account to a beneficiary — and the result is floored at zero, so an account whose transfer fee exceeds its decayed gross appraises at 0 rather than a negative number."

    "The administrative-expense deduction is capped by a tier selected **from the gross**, never from the post-deduction figure: a gross below 500000 selects a `deduction_cap_cents` of 25000, a gross below 5000000 selects 150000, and any larger gross selects 400000."

    "Creating a run moves every one of the estate's existing `COMPUTED` runs to the terminal `SUPERSEDED` and opens the new run at `COMPUTED`."

    "The three figures are mirrored onto the estate as `gross_digital_estate_cents`, `admin_deduction_cents` and `taxable_digital_estate_cents`, the estate's `valuation_basis` mirrors the basis of its newest `COMPUTED` or `FINALIZED` run, and `undistributed_value_cents` is set to the gross minus the sum of `received_value_cents` across the estate's designations."

    Design: Difficulty/boundary_precision_check/deduction_cap_tier_switches_at_exactly_five_hundred_thousand_gross_cents
    """
    fx.set_clock(api)
    ctx, platform, asset, beneficiary = _bank_estate_ready_to_value(api, "PR-2737-P")

    first = fx.computed_valuation_run(api, ctx, basis=BASIS_DATE_OF_DEATH)
    assert first["gross_value_cents"] == 500000
    assert first["deduction_cap_cents"] == 150000

    fx.patch_platform(api, platform["id"], transfer_fee_cents=2501)
    second = fx.computed_valuation_run(api, ctx, basis=BASIS_DATE_OF_DEATH)

    assert second["gross_value_cents"] == 499999
    assert second["deduction_cap_cents"] == 25000
    assert second["admin_deduction_cents"] == 25000
    assert second["taxable_value_cents"] == 474999
    assert second["status"] == RUN_COMPUTED
    assert fx.read_run(api, ctx, first["id"])["status"] == RUN_SUPERSEDED

    assert fx.read_asset(api, ctx, asset["id"])["appraised_value_cents"] == 499999
    estate = fx.read_estate(api, ctx)
    assert estate["gross_digital_estate_cents"] == 499999
    assert estate["admin_deduction_cents"] == 25000
    assert estate["taxable_digital_estate_cents"] == 474999
    assert estate["undistributed_value_cents"] == 499999
    assert (
        fx.read_designation(api, ctx, beneficiary["id"])["planned_allocation_cents"] == 499999
    )


def test_a_second_run_built_on_the_pre_run_estate_version_is_refused_as_stale(api):
    """
    The first run rewrites the estate's mirrored valuation fields, so replaying
    the same expected_estate_version afterwards no longer matches.

    "If the supplied value does not equal the estate's current `version`, the create is rejected with `ERR_STALE_ESTATE_VERSION` (HTTP 412)."

    Design: Difficulty/boundary_precision_check/deduction_cap_tier_switches_at_exactly_five_hundred_thousand_gross_cents
    """
    fx.set_clock(api)
    ctx, _platform, _asset, _beneficiary = _bank_estate_ready_to_value(api, "PR-2737-P")

    before = fx.estate_version(api, ctx)
    first = validate_success(
        api.create_valuation_run(
            ctx.estate_id,
            f.valuation_run_payload(before, basis=BASIS_DATE_OF_DEATH),
            ctx.fid_headers,
        ),
        201,
    )
    assert first["gross_value_cents"] == 500000

    stale = api.create_valuation_run(
        ctx.estate_id,
        f.valuation_run_payload(before, basis=BASIS_DATE_OF_DEATH),
        ctx.fid_headers,
    )
    validate_error(stale, ERR_STALE_ESTATE_VERSION)


def _estate_with_three_uneven_shares(api, court_case_number):
    """
    One TRANSFERABLE cloud-storage account quoted 400033 with no transfer fee,
    disclosed by an approved catalogue request, and three beneficiaries recorded
    in the order 3334, 3333, 3333 basis points.
    """
    platform = fx.register_platform(api)
    ctx = fx.authorized_estate(api, court_case_number)
    asset = fx.add_asset(
        api, ctx, platform["id"], account_handle="vault-estate", quoted_value_cents=400033
    )
    first = fx.add_beneficiary(
        api, ctx, beneficiary_name="Ada Ives", share_bp=3334, source=SOURCE_WILL, relationship="daughter"
    )
    second = fx.add_beneficiary(
        api, ctx, beneficiary_name="Bo Ives", share_bp=3333, source=SOURCE_WILL, relationship="son"
    )
    third = fx.add_beneficiary(
        api, ctx, beneficiary_name="Cy Ives", share_bp=3333, source=SOURCE_TRUST, relationship="nephew"
    )
    fx.approved_request(api, ctx, platform["id"], platform["form_code"])
    return ctx, asset, (first, second, third)


def test_allocation_remainder_is_the_pool_less_the_floored_shares(api):
    """
    Over a pool of 400033 the three shares floor to 133371, 133330 and 133330,
    which leaves exactly 2 cents unallocated after the first pass.

    "Under `DATE_OF_DEATH` the gross is the account's `quoted_value_cents` exactly, with no adjustment."

    "The server assigns `allocation_rank` as one more than the number of designations the estate already has, so ranks are dense, 1-based and follow `created_at` ascending order, and it opens `planned_allocation_cents` and `received_value_cents` at 0."

    "In the first pass each designation's `planned_allocation_cents` is the pool multiplied by that designation's `share_bp`, divided by 10000, with the fractional part **discarded** — always floored, never rounded."

    "The leftover is the pool minus the sum of those floors, and it is recorded on the run as `allocation_remainder_cents`."

    Design: Difficulty/boundary_precision_check/allocation_floors_then_distributes_remainder_by_rank_not_round_half_up
    """
    fx.set_clock(api)
    ctx, _asset, beneficiaries = _estate_with_three_uneven_shares(api, "PR-2737-Q")
    first, second, third = beneficiaries
    assert [first["allocation_rank"], second["allocation_rank"], third["allocation_rank"]] == [1, 2, 3]

    run = fx.computed_valuation_run(api, ctx, basis=BASIS_DATE_OF_DEATH)
    assert run["gross_value_cents"] == 400033
    assert run["allocation_remainder_cents"] == 2


def test_the_two_leftover_cents_go_to_ranks_one_and_two_not_to_the_largest_shares(api):
    """
    The second pass hands one cent at a time down the rank order, so the plan is
    133372 / 133331 / 133330 and sums to the pool exactly. Rounding each share
    half up independently would have produced 133371 / 133331 / 133331.

    "The pool is the run's `gross_value_cents`."

    "In the first pass each designation's `planned_allocation_cents` is the pool multiplied by that designation's `share_bp`, divided by 10000, with the fractional part **discarded** — always floored, never rounded."

    "In the second pass exactly one cent is added to each designation in `allocation_rank` ascending order, one designation at a time, until the leftover is exhausted; a leftover of two cents therefore goes to ranks 1 and 2 and nowhere else."

    "The three figures are mirrored onto the estate as `gross_digital_estate_cents`, `admin_deduction_cents` and `taxable_digital_estate_cents`, the estate's `valuation_basis` mirrors the basis of its newest `COMPUTED` or `FINALIZED` run, and `undistributed_value_cents` is set to the gross minus the sum of `received_value_cents` across the estate's designations."

    Design: Difficulty/boundary_precision_check/allocation_floors_then_distributes_remainder_by_rank_not_round_half_up
    """
    fx.set_clock(api)
    ctx, _asset, beneficiaries = _estate_with_three_uneven_shares(api, "PR-2737-Q")
    first, second, third = beneficiaries

    run = fx.computed_valuation_run(api, ctx, basis=BASIS_DATE_OF_DEATH)
    assert run["gross_value_cents"] == 400033

    planned = [
        fx.read_designation(api, ctx, row["id"])["planned_allocation_cents"]
        for row in (first, second, third)
    ]
    assert planned == [133372, 133331, 133330]
    assert sum(planned) == 400033
    assert fx.read_estate(api, ctx)["undistributed_value_cents"] == 400033


def test_a_share_that_pushes_the_estate_total_past_ten_thousand_is_refused(api):
    """
    The three recorded shares already sum to exactly 10000 basis points, so one
    more basis point cannot be recorded against this estate.

    "The running total of `share_bp` across an estate's designations may never exceed 10000 — a designation that would push it past that is rejected with `ERR_SHARE_TOTAL_INVALID` — and it must equal exactly 10000 before a valuation run may be created, so an estate whose shares total 9999 cannot be valued and reports the same code."

    Design: Difficulty/boundary_precision_check/allocation_floors_then_distributes_remainder_by_rank_not_round_half_up
    """
    fx.set_clock(api)
    ctx, _asset, _beneficiaries = _estate_with_three_uneven_shares(api, "PR-2737-Q")
    fx.computed_valuation_run(api, ctx, basis=BASIS_DATE_OF_DEATH)

    refused = api.create_beneficiary_designation(
        ctx.estate_id,
        f.beneficiary_payload(beneficiary_name="Di Ives", share_bp=1, source=SOURCE_WILL),
        ctx.fid_headers,
    )
    validate_error(refused, ERR_SHARE_TOTAL_INVALID)

    _, meta = validate_paginated(
        api.list_beneficiary_designations(ctx.fid_headers, estate_id=ctx.estate_id)
    )
    assert meta["total_count"] == 3, "A refused designation must not be persisted"
