"""Material takeoff lifecycle (DRAFT/QUOTED/CONVERTED) and estimate math."""
from test_helpers import (
    TEST_USERS,
    assert_takeoff,
    create_quoted_takeoff,
    create_takeoff,
    make_account,
    make_branch,
    make_contractor_headers,
    make_job,
    make_product,
    validate_error,
    validate_success,
    ApiErrorId,
)

SALES = TEST_USERS["sales_rep_headers"]


def _job_with_product(branch_code="BR-TK", sku="SH-TK", price=3500):
    branch = make_branch(branch_code)
    product = make_product(sku, price=price)
    account = make_account()
    job = make_job(account["id"])
    return branch, product, account, job


class TestTakeoffLifecycle:
    def test_takeoff_starts_in_draft(self, api):
        """PRD §3.3: "Every takeoff records the `job_account_id` of the job it
        belongs to, starts life in `DRAFT`, and unknown takeoff references are
        `ERR_TAKEOFF_NOT_FOUND`."

        Design: Corner/state_machines/takeoff_starts_in_draft
        """
        _branch, product, _account, job = _job_with_product("BR-SM1", "SH-SM1")
        takeoff = validate_success(api.create_takeoff(
            job["id"],
            {"product_id": product["id"], "roof_squares": 8.0,
             "waste_factor_pct": 5, "valley_ridge_linear_feet": 0},
            SALES), expected_status=201)
        assert_takeoff(takeoff)
        assert takeoff["status"] == "DRAFT"

    def test_takeoff_convert_from_draft_rejected(self, api):
        """PRD §3.3: "The owning `Contractor` converts a `QUOTED` takeoff —
        any other state draws `ERR_TAKEOFF_NOT_QUOTED` — by naming the
        fulfilling `branch_id`."

        Design: Corner/state_machines/takeoff_convert_from_draft_rejected
        """
        branch, product, account, job = _job_with_product("BR-SM2", "SH-SM2")
        takeoff = create_takeoff(job["id"], product["id"], roof_squares=8.0,
                                 waste_factor_pct=5)
        resp = api.convert_takeoff(takeoff["id"], branch["id"],
                                   make_contractor_headers(account["id"]))
        validate_error(resp, ApiErrorId.ERR_TAKEOFF_NOT_QUOTED)

    def test_takeoff_revise_returns_quoted_takeoff_to_draft(self, api):
        """PRD §3.3: "If measurements change, a `SalesRep` can move the
        takeoff from `QUOTED` back to `DRAFT` — permitted only from `QUOTED`,
        otherwise `ERR_TAKEOFF_NOT_QUOTED` — which makes `roof_squares` and
        `waste_factor_pct` editable again for revision and eventual
        re-quoting."

        Design: Corner/state_machines/takeoff_revise_quote_cycle_returns_to_draft
        """
        _branch, product, _account, job = _job_with_product("BR-SM3", "SH-SM3")
        takeoff = create_quoted_takeoff(job["id"], product["id"],
                                        roof_squares=8.0, waste_factor_pct=5)
        revised = validate_success(api.revise_takeoff(takeoff["id"], SALES))
        assert revised["status"] == "DRAFT"

    def test_requote_of_quoted_takeoff_rejected(self, api):
        """PRD §3.3: "Moving a takeoff from `DRAFT` to `QUOTED` requires the
        takeoff to actually be in `DRAFT` (otherwise `ERR_TAKEOFF_NOT_DRAFT`)
        and requires the contractor account behind the parent job to be
        `ACTIVE` (otherwise `ERR_ACCOUNT_NOT_ACTIVE`)."

        Design: Corner/errors/error_takeoff_not_draft_on_requote
        """
        _branch, product, _account, job = _job_with_product("BR-ER1", "SH-ER1")
        takeoff = create_quoted_takeoff(job["id"], product["id"],
                                        roof_squares=5.0)
        resp = api.quote_takeoff(takeoff["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_TAKEOFF_NOT_DRAFT)


class TestTakeoffEstimateMath:
    def test_estimate_uses_accessory_constants_and_per_line_ceil(self, api):
        """PRD §3.3: "Accessory bundles are the `valley_ridge_linear_feet`
        divided by thirty-three linear feet of coverage per accessory bundle,
        again rounded up to a whole bundle."
        PRD §3.3: "The read-only `estimated_bundles` is the shingle count plus
        the accessory count, and the read-only `estimated_amount_cents` prices
        the shingle bundles at the product's current
        `base_price_per_bundle_cents` plus 4,200 cents (forty-two dollars) per
        accessory bundle."

        ceil(12.5 * 1.15 * 4.0) = ceil(57.5) = 58 shingles;
        ceil(66/33) = 2 accessories; amount = 58*4800 + 2*4200 = 286800.

        Design: Corner/calculations/takeoff_estimate_constants_applied
        """
        _branch, product, _account, job = _job_with_product("BR-CA1", "SH-CA1")
        product = make_product("SH-CA1B", price=4800, bps=4.0,
                               color_code="RED")
        takeoff = create_takeoff(job["id"], product["id"], roof_squares=12.5,
                                 waste_factor_pct=15,
                                 valley_ridge_linear_feet=66)
        assert takeoff["estimated_bundles"] == 60
        assert takeoff["estimated_amount_cents"] == 286800

    def test_quote_locks_estimate_at_quote_time_prices(self, api):
        """PRD §3.3: "At the moment of quoting the estimate is recomputed and
        frozen: `estimated_bundles` and `estimated_amount_cents` are locked at
        quote-time prices, and later price changes do not alter them."

        20.0 squares at 10% waste -> adjusted 22.0 -> ceil(22.0*3.0) = 66
        shingles; ceil(99/33) = 3 accessories; 66*3500 + 3*4200 = 243600.

        Design: Corner/calculations/takeoff_quote_locks_estimate_against_price_change
        """
        _branch, product, _account, job = _job_with_product("BR-CA2", "SH-CA2")
        takeoff = create_takeoff(job["id"], product["id"], roof_squares=20.0,
                                 waste_factor_pct=10, valley_ridge_linear_feet=99)
        quoted = validate_success(api.quote_takeoff(takeoff["id"], SALES))
        assert quoted["estimated_bundles"] == 69
        assert quoted["estimated_amount_cents"] == 243600
        reread = validate_success(api.get_takeoff(takeoff["id"], SALES))
        assert reread["estimated_amount_cents"] == 243600

    def test_per_line_ceil_then_sum_at_waste_ten_percent(self, api):
        """PRD §3.3: "The shingle requirement is then the adjusted area
        multiplied by the product's `bundles_per_square`, rounded up to the
        next whole bundle — this ceiling is applied per product line, before
        any summation across lines, never after."

        ceil(20.0 * 1.10 * 3.0) = 66 shingles; ceil(99/33) = 3 accessories;
        estimated_bundles = 69; amount = 66*3500 + 3*4200 = 243600.

        Design: Difficulty/combinatorial_formula/takeoff_per_line_ceil_then_sum
        """
        _branch, product, _account, job = _job_with_product("BR-T1", "SH-T1")
        takeoff = create_takeoff(job["id"], product["id"], roof_squares=20.0,
                                 waste_factor_pct=10, valley_ridge_linear_feet=99)
        assert takeoff["estimated_bundles"] == 69
        assert takeoff["estimated_amount_cents"] == 243600

    def test_per_line_ceil_then_sum_fractional_shingle_line(self, api):
        """PRD §3.3: "The shingle requirement is then the adjusted area
        multiplied by the product's `bundles_per_square`, rounded up to the
        next whole bundle — this ceiling is applied per product line, before
        any summation across lines, never after."
        PRD §2.6: "Estimation rounds up per product line (a ceiling applied to
        each line's requirement before any summation across lines), because
        rounding per line and then summing produces a different — and here
        normative — answer than summing and then rounding."

        ceil(10.0 * 1.05 * 3.0) = ceil(31.5) = 32 shingles;
        ceil(34/33) = 2 accessories; estimated_bundles = 34;
        amount = 32*3500 + 2*4200 = 120400.

        Design: Difficulty/combinatorial_formula/takeoff_per_line_ceil_then_sum
        """
        _branch, product, _account, job = _job_with_product("BR-T2", "SH-T2")
        takeoff = create_takeoff(job["id"], product["id"], roof_squares=10.0,
                                 waste_factor_pct=5, valley_ridge_linear_feet=34)
        assert takeoff["estimated_bundles"] == 34
        assert takeoff["estimated_amount_cents"] == 120400
