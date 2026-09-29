"""Host royalty settlement: the revenue waterfall, the two settlement variants,
the contractual floor, and the optimistic-concurrency guard on site writes."""

from test_helpers import (
    ApiErrorId,
    approx_2dp,
    approx_4dp,
    assert_royalty_statement,
    create_royalty_statement_payload,
    create_site_payload,
    fixtures,
    make_host_representative_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import SEPTEMBER_CLOCK_UTC


def _august_production_with_attributes(site_overrides=None):
    """One 340.14 MMBtu batch injected in August against a 5.25 USD/dth contract,
    with an RIN_D3 and an LCFS attribute batch generated from it, and the clock
    advanced past the end of the month."""
    context = fixtures.setup_injected_batch(site_overrides=site_overrides)
    context["rin_batch"] = fixtures.generate_attribute_batch(
        context["batch"]["id"], program="RIN_D3"
    )
    context["lcfs_batch"] = fixtures.generate_attribute_batch(
        context["batch"]["id"], program="LCFS"
    )
    set_clock(SEPTEMBER_CLOCK_UTC)
    return context


class TestSettlementVariants:
    def test_gross_revenue_share_settles_on_the_full_gross_revenue(self, api):
        """PRD §3.9: "`gas_revenue_usd` is built per batch and only then summed: each
        batch's `gross_mmbtu` is multiplied by the `price_usd_per_dth` of the offtake
        contract behind the nomination the batch was attached to, **that per-batch
        product is rounded half up to two decimal places**, the rounded per-batch figures
        are summed, and the sum is rounded half up to two decimal places again."
        PRD §3.9: "`attribute_revenue_usd` sums, over every attribute batch whose source
        injection batch is in that set and whose `status` is `GENERATED`, `QA_HOLD`,
        `SEPARATED` or `RETIRED`, that batch's `rin_count` multiplied by the RIN price of
        2.85 US dollars plus its `lcfs_credits` multiplied by the LCFS credit price of
        62.00 US dollars, with the total rounded half up to two decimal places; attribute
        batches that are `REVERSED` or still `PENDING` contribute nothing."
        PRD §3.9: "Under `GROSS_REVENUE_SHARE`, `calculated_amount_usd` is
        `gross_revenue_usd` multiplied by the site's `host_royalty_pct`, rounded half up
        to two decimal places, and `allowed_deductions_usd` is ignored entirely."

        Design: Difficulty/dual_variant_calc/royalty_gross_revenue_share_vs_netback_share
        """
        context = _august_production_with_attributes()
        assert context["rin_batch"]["rin_count"] == 3988
        assert context["lcfs_batch"]["lcfs_credits"] == approx_4dp(17.9190)

        statement = fixtures.create_royalty_statement(
            context["site"]["id"], period="2026-08"
        )
        assert_royalty_statement(statement)

        assert statement["variant_applied"] == "GROSS_REVENUE_SHARE"
        assert statement["billable_mmbtu"] == approx_2dp(340.14)
        assert statement["gas_revenue_usd"] == approx_2dp(1785.74)
        assert statement["attribute_revenue_usd"] == approx_2dp(12476.78)
        assert statement["gross_revenue_usd"] == approx_2dp(14262.52)
        assert statement["calculated_amount_usd"] == approx_2dp(1711.50)
        assert statement["floor_amount_usd"] == approx_2dp(85.04)
        assert statement["royalty_amount_usd"] == approx_2dp(1711.50)

    def test_netback_share_override_deducts_before_taking_the_host_share(self, api):
        """PRD §3.9: "Under `NETBACK_SHARE`, the deductions are subtracted from the gross
        revenue first, with the difference floored at zero so a month of heavy deductions
        can never produce a negative base, and that floored difference is multiplied by
        `host_royalty_pct` and rounded half up to two decimal places — which yields a
        strictly smaller calculated amount than the gross variant whenever the deductions
        are greater than zero."
        PRD §3.9: "The `variant_applied` recorded on the statement is the
        `variant_override` when one was supplied and the site's `royalty_variant`
        otherwise, and like every money field on the row it is frozen at creation."
        PRD §3.9: "The site's `HostRepresentative` — and only the representative whose
        `X-User-ID` equals the statement's `site_id` — may dispute an issued statement
        with a `dispute_reason`, taking it `ISSUED → DISPUTED`, which lowers the site's
        `royalty_payable_usd` by the same amount and releases the site-and-period
        uniqueness slot so a restated statement may be written for that month."

        Design: Difficulty/dual_variant_calc/royalty_gross_revenue_share_vs_netback_share
        """
        context = _august_production_with_attributes()
        site_id = context["site"]["id"]

        gross_statement = fixtures.setup_issued_statement(site_id, period="2026-08")
        assert gross_statement["variant_applied"] == "GROSS_REVENUE_SHARE"
        validate_success(
            api.set_royalty_statement_status(
                gross_statement["id"],
                {
                    "to_status": "DISPUTED",
                    "dispute_reason": "Host disputes the deduction methodology",
                },
                make_host_representative_headers(site_id),
            )
        )

        netback_statement = fixtures.create_royalty_statement(
            site_id,
            period="2026-08",
            allowed_deductions_usd=400.00,
            variant_override="NETBACK_SHARE",
        )
        assert netback_statement["variant_applied"] == "NETBACK_SHARE"
        assert netback_statement["gross_revenue_usd"] == approx_2dp(14262.52)
        # (14262.52 - 400.00) * 0.12 = 1663.50
        assert netback_statement["calculated_amount_usd"] == approx_2dp(1663.50)
        assert netback_statement["royalty_amount_usd"] == approx_2dp(1663.50)
        assert netback_statement["royalty_amount_usd"] != approx_2dp(
            gross_statement["royalty_amount_usd"]
        ), "identical production settles differently under the two variants"


class TestSettlementInputSet:
    def test_settlement_over_an_empty_injected_set_lands_at_zero(self, api):
        """PRD §3.9: "The batches that count are those whose `status` is `INJECTED`,
        whose `interval_start` falls inside the settlement window, and whose producing
        plant belongs to the statement's site, taken in order of `interval_start`
        ascending with `created_at` ascending as tie-break; batches that were diverted,
        voided or merely nominated are excluded outright."
        PRD §3.9: "A month with no qualifying batches is perfectly legal: billable
        energy, every revenue figure, the floor and the royalty all settle at 0.00 and
        the statement is still created in `DRAFT`."

        Design: Difficulty/boundary_precision_check/royalty_statement_over_empty_injected_batch_set
        """
        context = fixtures.setup_diverted_batch()
        site_id = context["site"]["id"]
        assert context["batch"]["status"] == "DIVERTED_TO_FLARE"
        set_clock(SEPTEMBER_CLOCK_UTC)

        response = api.create_royalty_statement(
            create_royalty_statement_payload(
                site_id, fixtures.site_version(site_id), period="2026-08"
            ),
            fixtures.ADMIN,
        )
        statement = validate_success(response, 201)

        assert statement["status"] == "DRAFT"
        assert statement["variant_applied"] == "GROSS_REVENUE_SHARE"
        assert statement["billable_mmbtu"] == approx_2dp(0.0)
        assert statement["gas_revenue_usd"] == approx_2dp(0.0)
        assert statement["attribute_revenue_usd"] == approx_2dp(0.0)
        assert statement["gross_revenue_usd"] == approx_2dp(0.0)
        assert statement["calculated_amount_usd"] == approx_2dp(0.0)
        assert statement["floor_amount_usd"] == approx_2dp(0.0)
        assert statement["royalty_amount_usd"] == approx_2dp(0.0)

    def test_a_month_whose_only_gas_was_flared_still_produces_a_draft_statement(
        self, api
    ):
        """PRD §3.9: "A month with no qualifying batches is perfectly legal: billable
        energy, every revenue figure, the floor and the royalty all settle at 0.00 and
        the statement is still created in `DRAFT`."
        PRD §3.7: "The site's `energy_produced_mmbtu` and `energy_flared_mmbtu` each rise
        by the batch's `gross_mmbtu`, and when the batch had been attached to a
        nomination, that nomination's `committed_dth` falls by the same figure and the
        nomination is curtailed from `CONFIRMED` or `SCHEDULED` to `CURTAILED`."

        Design: Difficulty/boundary_precision_check/royalty_statement_over_empty_injected_batch_set
        """
        context = fixtures.setup_diverted_batch()
        site_id = context["site"]["id"]
        site_before = fixtures.read_site(site_id)
        assert site_before["energy_flared_mmbtu"] == approx_2dp(340.14)

        set_clock(SEPTEMBER_CLOCK_UTC)
        statement = fixtures.create_royalty_statement(site_id, period="2026-08")

        assert statement["status"] == "DRAFT"
        assert statement["royalty_amount_usd"] == approx_2dp(0.0)
        assert fixtures.read_site(site_id)["energy_flared_mmbtu"] == approx_2dp(340.14)

    def test_the_contractual_floor_wins_when_the_percentage_share_falls_below_it(
        self, api
    ):
        """PRD §3.9: "Separately, `floor_amount_usd` is `billable_mmbtu` multiplied by
        the site's `royalty_floor_usd_per_mmbtu`, rounded half up to two decimal places,
        and the final `royalty_amount_usd` is whichever of the calculated amount and the
        floor amount is larger."

        Design: Corner/calculations/royalty_floor_wins_when_percentage_share_falls_below_it
        """
        context = fixtures.setup_injected_batch(
            site_overrides={
                "name": "Cedar Ridge Landfill",
                "state_code": "TX",
                "host_royalty_pct": 0.02,
                "permit_nmoc_limit_lb_per_hr": 4.0,
                "royalty_floor_usd_per_mmbtu": 0.25,
            }
        )
        set_clock(SEPTEMBER_CLOCK_UTC)

        statement = fixtures.create_royalty_statement(
            context["site"]["id"], period="2026-08"
        )
        assert statement["billable_mmbtu"] == approx_2dp(340.14)
        assert statement["gas_revenue_usd"] == approx_2dp(1785.74)
        assert statement["attribute_revenue_usd"] == approx_2dp(0.0)
        assert statement["gross_revenue_usd"] == approx_2dp(1785.74)
        assert statement["calculated_amount_usd"] == approx_2dp(35.71)
        assert statement["floor_amount_usd"] == approx_2dp(85.04)
        assert statement["royalty_amount_usd"] == approx_2dp(85.04), (
            "the larger of the two, never their sum"
        )

    def test_a_diverted_batch_never_enters_the_settlement(self, api):
        """PRD §3.9: "The batches that count are those whose `status` is `INJECTED`,
        whose `interval_start` falls inside the settlement window, and whose producing
        plant belongs to the statement's site, taken in order of `interval_start`
        ascending with `created_at` ascending as tie-break; batches that were diverted,
        voided or merely nominated are excluded outright."
        PRD §3.9: "`billable_mmbtu` is the sum of those batches' `gross_mmbtu`, rounded
        half up to two decimal places."

        Design: Corner/calculations/royalty_input_set_excludes_diverted_batches
        """
        context = fixtures.setup_injected_batch()
        site_id = context["site"]["id"]

        flared = fixtures.create_batch(
            context["plant"]["id"],
            interval_start="2026-08-10T06:00:00Z",
            interval_end="2026-08-10T09:00:00Z",
        )
        fixtures.analyse_batch(flared["id"])
        fixtures.divert_batch(flared["id"])
        set_clock(SEPTEMBER_CLOCK_UTC)

        statement = fixtures.create_royalty_statement(site_id, period="2026-08")
        assert statement["billable_mmbtu"] == approx_2dp(340.14), (
            "only the injected half is billable"
        )
        assert statement["gas_revenue_usd"] == approx_2dp(1785.74)
        assert statement["gross_revenue_usd"] == approx_2dp(1785.74)
        assert statement["calculated_amount_usd"] == approx_2dp(214.29)
        assert statement["royalty_amount_usd"] == approx_2dp(214.29)

        site = fixtures.read_site(site_id)
        assert site["energy_produced_mmbtu"] == approx_2dp(680.28)
        assert site["energy_flared_mmbtu"] == approx_2dp(340.14)


class TestSettlementGuards:
    def test_settling_a_month_that_has_not_elapsed_is_refused(self, api, admin_headers):
        """PRD §3.9: "The settlement window runs from the first instant of the named
        month inclusive to the first instant of the following month exclusive, and that
        month must have fully elapsed against `current_utc` — settling a month still in
        progress is refused with `ERR_ROYALTY_PERIOD_NOT_CLOSED`."

        Design: Corner/validations/royalty_statement_for_a_period_still_running_is_rejected
        """
        set_clock("2026-08-20T00:00:00Z")
        site = validate_success(
            api.create_site(create_site_payload(), admin_headers), 201
        )

        validate_error(
            api.create_royalty_statement(
                create_royalty_statement_payload(
                    site["id"], site["version"], period="2026-08"
                ),
                admin_headers,
            ),
            ApiErrorId.ERR_ROYALTY_PERIOD_NOT_CLOSED.value,
        )

        _, meta = validate_paginated(
            api.list_royalty_statements(
                admin_headers, params={"site_id": site["id"], "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 0
        assert fixtures.read_site(site["id"])["royalty_payable_usd"] == approx_2dp(0.0)

    def test_a_second_statement_for_the_same_live_period_is_refused(
        self, api, admin_headers
    ):
        """PRD §3.9: "Only one statement may exist for a given site and period in
        `DRAFT`, `ISSUED` or `PAID`; a second is refused with
        `ERR_ROYALTY_PERIOD_DUPLICATE`."

        Design: Corner/errors/second_royalty_statement_for_the_same_open_period_is_rejected
        """
        set_clock(SEPTEMBER_CLOCK_UTC)
        site = validate_success(
            api.create_site(create_site_payload(), admin_headers), 201
        )
        first = fixtures.create_royalty_statement(
            site["id"], period="2026-08", expected_site_version=site["version"]
        )
        assert first["status"] == "DRAFT"
        assert first["royalty_amount_usd"] == approx_2dp(0.0)

        validate_error(
            api.create_royalty_statement(
                create_royalty_statement_payload(
                    site["id"], fixtures.site_version(site["id"]), period="2026-08"
                ),
                admin_headers,
            ),
            ApiErrorId.ERR_ROYALTY_PERIOD_DUPLICATE.value,
        )

        _, meta = validate_paginated(
            api.list_royalty_statements(
                admin_headers, params={"site_id": site["id"], "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 1

    def test_stale_expected_site_version_is_refused_until_the_client_re_reads(
        self, api, admin_headers
    ):
        """PRD §2.7: "A `POST /royalty-statements` request must likewise carry
        `expected_site_version`, a non-optional field holding the `version` of the target
        `LandfillSite` that the client last observed. A mismatch against the site's
        current `version` is rejected with `ERR_STALE_SITE_VERSION` and HTTP 412."
        PRD §2.7: "A successful create increments the site's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_site_version_on_royalty_create_returns_precondition_failed
        """
        set_clock(SEPTEMBER_CLOCK_UTC)
        site = validate_success(
            api.create_site(create_site_payload(), admin_headers), 201
        )
        observed = site["version"]

        july = validate_success(
            api.create_royalty_statement(
                create_royalty_statement_payload(site["id"], observed, period="2026-07"),
                admin_headers,
            ),
            201,
        )
        assert july["period"] == "2026-07"

        validate_error(
            api.create_royalty_statement(
                create_royalty_statement_payload(site["id"], observed, period="2026-08"),
                admin_headers,
            ),
            ApiErrorId.ERR_STALE_SITE_VERSION.value,
        )

        fresh = fixtures.site_version(site["id"])
        assert fresh == observed + 1

        august = validate_success(
            api.create_royalty_statement(
                create_royalty_statement_payload(site["id"], fresh, period="2026-08"),
                admin_headers,
            ),
            201,
        )
        assert august["period"] == "2026-08"
        assert august["royalty_amount_usd"] == approx_2dp(0.0)

        _, meta = validate_paginated(
            api.list_royalty_statements(
                admin_headers, params={"site_id": site["id"], "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 2


class TestHostRepresentativeOwnership:
    def test_a_host_representative_may_read_only_its_own_sites_statement(
        self, api, admin_headers
    ):
        """PRD §2.1: "When `X-User-Role` is `HostRepresentative`, `X-User-ID` is the `id`
        of the acting `LandfillSite`; ownership checks on any resource that references a
        `LandfillSite` compare the resource's site reference to `X-User-ID`, so a host
        representative may read and dispute only royalty statements whose `site_id`
        equals its own identifier."
        PRD §2.1: "An entity-backed role that reaches for a resource it does not own is
        rejected with `ERR_NOT_RESOURCE_OWNER` and HTTP 403."

        Design: Corner/rbac/host_representative_cannot_read_another_sites_royalty_statement
        """
        set_clock(SEPTEMBER_CLOCK_UTC)
        site_a = validate_success(
            api.create_site(create_site_payload(), admin_headers), 201
        )
        site_b = fixtures.create_site(
            name="Cedar Ridge Landfill",
            state_code="TX",
            host_royalty_pct=0.10,
            royalty_variant="NETBACK_SHARE",
            permit_nmoc_limit_lb_per_hr=4.0,
        )
        statement = fixtures.create_royalty_statement(
            site_a["id"], period="2026-08", expected_site_version=site_a["version"]
        )

        validate_error(
            api.get_royalty_statement(
                statement["id"], make_host_representative_headers(site_b["id"])
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
        )

        own = validate_success(
            api.get_royalty_statement(
                statement["id"], make_host_representative_headers(site_a["id"])
            )
        )
        assert own["id"] == statement["id"]
        assert own["site_id"] == site_a["id"]
