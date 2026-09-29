"""Stale writers, list windows, the clock-driven sweep, a configuration flag and a recomputed count."""

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_instant_equals,
    claim_payload,
    convert_poc_transfer,
    coverage_profile_payload,
    create_policy,
    deliver_poc_transfer,
    distribution_payload,
    estate_remittance_payload,
    get_success_data,
    move_clock,
    other_insurance_payload,
    poc_policy_record,
    premium_refund_payload,
    present_claim,
    read_assessment,
    read_claim,
    read_insolvency,
    read_member_assessment,
    read_policy,
    screen_claim,
    setup_approved_claim,
    setup_certified_assessment,
    setup_declared_insolvency,
    setup_presented_claim,
    setup_triggered_insolvency,
    trigger_insolvency,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["association_admin_headers"]
RECEIVER = TEST_USERS["receiver_liaison_headers"]
ANALYST = TEST_USERS["coverage_analyst_headers"]
OFFICER = TEST_USERS["claims_committee_officer_headers"]

LIVE_TERM = {
    "policy_number": "PA-1001",
    "policyholder_name": "Ada Renner",
    "effective_date": "2025-10-01",
    "expiration_date": "2026-10-01",
    "annual_premium_cents": 1_200_000,
}
SMALL_LOSS_CLAIM = {
    "claim_number": "C-1",
    "claimant_name": "Ben Ortiz",
    "gross_loss_cents": 900_000,
}
KESTREL_ADJUSTER = {
    "vendor_name": "Kestrel Claims Services",
    "settlement_authority_cents": 900_000,
    "hourly_rate_cents": 18_000,
    "engagement_start": "2026-08-01",
    "engagement_end": "2026-08-31",
}
NORTHERN_SHIELD = {
    "carrier_name": "Northern Shield Indemnity",
    "policy_number": "NS-77",
    "coverage_type": "PRIMARY",
    "stated_limit_cents": 1_500_000,
}
HURON_MEMBER = [
    {
        "naic_code": "20001",
        "insurer_name": "Huron Standard Insurance",
        "direct_written_premium_cents": 10_000_000,
    }
]
CGL_PROFILE = {
    "line_of_business": "COMMERCIAL_GENERAL_LIABILITY",
    "covers_punitive_damages": True,
}
CGL_TERM = {
    "policy_number": "CGL-1",
    "line_of_business": "COMMERCIAL_GENERAL_LIABILITY",
    "policyholder_name": "Redbud Fabrication LLC",
    "effective_date": "2025-10-01",
    "expiration_date": "2026-10-01",
    "annual_premium_cents": 4_800_000,
}


def _screen_covered(claim_id: str) -> dict:
    return get_success_data(
        api_client.screen_claim(claim_id, {"decision": "COVERED"}, ANALYST)
    )


class TestStaleWriters:
    """Three write paths carry the client's last observed version, and each refuses a stale one."""

    def test_a_layer_asserted_against_the_pre_screening_claim_is_refused(self):
        """`POST /claims/{id}/other-insurance` requires `expected_claim_version`, carrying the client's
        last observed `version` of the covered claim named in the path. A mismatch with the claim's
        current `version` is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412). Registering a new
        other-insurance layer legitimately supersedes the claim's previously computed payable, so a
        writer holding a stale view of the claim would be posting an offset against a payable that no
        longer exists.

        Design: Corner/cross_cutting_complexity_layers/a_stale_claim_version_blocks_an_other_insurance_layer
        """
        env = setup_presented_claim(
            claim_overrides=dict(SMALL_LOSS_CLAIM), policy_overrides=dict(LIVE_TERM)
        )
        at_intake = env["claim"]["version"]
        assert at_intake == 1, at_intake
        after_screening = screen_claim(env)["version"]
        assert after_screening == 2, (
            f"screening advanced the claim's version, got {after_screening}"
        )
        claim_id = env["claim"]["id"]

        validate_error(
            api_client.create_other_insurance(
                claim_id, other_insurance_payload(at_intake, **NORTHERN_SHIELD), ANALYST
            ),
            "ERR_STALE_CLAIM_VERSION",
            412,
        )
        layers, _ = validate_paginated(api_client.list_other_insurance(claim_id, ANALYST))
        assert layers == [], "a refused writer registers no layer"
        assert read_claim(claim_id)["version"] == after_screening

        accepted = get_success_data(
            api_client.create_other_insurance(
                claim_id, other_insurance_payload(after_screening, **NORTHERN_SHIELD), ANALYST
            ),
            201,
        )
        assert accepted["claim_id"] == claim_id, accepted["claim_id"]
        assert read_claim(claim_id)["version"] == 3, (
            "and the accepted write bumps the version again"
        )

    def test_a_refund_asserted_against_the_pre_cancellation_policy_is_refused(self):
        """`POST /policies/{id}/premium-refunds` requires `expected_policy_version`, carrying the
        client's last observed `version` of the transferred policy named in the path. A mismatch with
        the policy's current `version` is rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412). The
        refund is computed from the policy's cancellation data and written premium, so a writer holding
        a stale view of the policy would elect a refund variant against superseded cancellation facts.

        Design: Corner/cross_cutting_complexity_layers/a_stale_policy_version_blocks_a_premium_refund_filing
        """
        env = setup_declared_insolvency(policy_overrides=dict(LIVE_TERM))
        at_import = env["policy"]["version"]
        assert at_import == 1, at_import
        env["insolvency"] = trigger_insolvency(env["insolvency"]["id"])
        cancelled = read_policy(env["policy"]["id"])
        assert cancelled["status"] == "CANCELLED_BY_ORDER", cancelled["status"]
        assert cancelled["unexpired_days"] == 184, cancelled["unexpired_days"]
        assert cancelled["version"] == 2, (
            f"the order cascade rewrote the policy, got version {cancelled['version']}"
        )

        validate_error(
            api_client.create_premium_refund(
                cancelled["id"], premium_refund_payload("PRO_RATA", at_import), ANALYST
            ),
            "ERR_STALE_POLICY_VERSION",
            412,
        )
        assert read_policy(cancelled["id"])["up_refund_filed"] is False, (
            "the refused filing leaves the latch open"
        )

        refund = get_success_data(
            api_client.create_premium_refund(
                cancelled["id"], premium_refund_payload("PRO_RATA", cancelled["version"]), ANALYST
            ),
            201,
        )
        assert refund["computed_refund_cents"] == 604_932, refund["computed_refund_cents"]
        assert refund["status"] == "PENDING", refund["status"]
        assert read_insolvency(env["insolvency"]["id"])["pending_up_liability_cents"] == 604_932

    def test_a_run_asserted_against_the_pre_remittance_ledger_is_refused(self):
        """`POST /insolvencies/{id}/distributions` requires `expected_insolvency_version`, carrying the
        client's last observed `version` of the insolvency file named in the path. A mismatch with the
        insolvency file's current `version` is rejected with `ERR_STALE_INSOLVENCY_VERSION` (HTTP 412).
        A distribution run supersedes the estate ledger, so a writer holding a stale view of the
        undistributed balance would allocate cash that an earlier run has already committed.

        Design: Corner/cross_cutting_complexity_layers/a_stale_insolvency_version_blocks_a_distribution_run
        """
        env = setup_approved_claim(
            recommended_amount_cents=890_000,
            claim_overrides=dict(SMALL_LOSS_CLAIM),
            assignment_overrides=dict(KESTREL_ADJUSTER),
            policy_overrides=dict(LIVE_TERM),
        )
        insolvency_id = env["insolvency"]["id"]
        stale_version = read_insolvency(insolvency_id)["version"]
        funded = get_success_data(
            api_client.create_estate_remittance(
                insolvency_id, estate_remittance_payload(1_000_000, "EA-1"), RECEIVER
            ),
            200,
        )
        assert funded["version"] == stale_version + 1, funded["version"]

        validate_error(
            api_client.run_distribution(
                insolvency_id, distribution_payload(890_000, stale_version), ADMIN
            ),
            "ERR_STALE_INSOLVENCY_VERSION",
            412,
        )
        refused = read_insolvency(insolvency_id)
        assert refused["distribution_sequence"] == 0, (
            f"the refused run is never numbered, got {refused['distribution_sequence']}"
        )
        assert refused["estate_undistributed_cents"] == 1_000_000

        run = get_success_data(
            api_client.run_distribution(
                insolvency_id, distribution_payload(890_000, funded["version"]), ADMIN
            ),
            200,
        )
        assert run["distribution_sequence"] == 1, run["distribution_sequence"]
        assert run["class2_paid_cents"] == 890_000, run["class2_paid_cents"]
        assert run["estate_undistributed_cents"] == 110_000, run["estate_undistributed_cents"]
        assert read_claim(env["claim"]["id"])["status"] == "PAID"


class TestListWindows:
    """A status filter and a one-row window compose without losing or repeating rows."""

    def test_the_filter_narrows_the_total_and_the_window_splits_it(self):
        """The `meta` block of a list response carries `limit` and `offset` echoing the effective
        values used, `total_count` giving the number of rows matching the filter before the page window
        is applied, and `has_more` set to true exactly when rows remain beyond the current window.

        Claims can also be listed with optional filters on `insolvency_id`, `policy_id`,
        `source_transfer_id` and `status`, and read individually with both payable variants exposed.

        Design: Corner/cross_cutting_complexity_layers/claims_list_filters_and_paginates_together
        """
        env = setup_triggered_insolvency(policy_overrides=dict(LIVE_TERM))
        insolvency_id = env["insolvency"]["id"]
        first = present_claim(env, **SMALL_LOSS_CLAIM)
        second = present_claim(
            env,
            claim_number="C-2",
            claimant_name="Cora Diaz",
            loss_date="2026-01-20",
            gross_loss_cents=800_000,
        )
        unscreened = present_claim(
            env,
            claim_number="C-3",
            claimant_name="Dev Rao",
            loss_date="2026-01-25",
            gross_loss_cents=700_000,
        )
        _screen_covered(first["id"])
        _screen_covered(second["id"])

        page_one, meta_one = validate_paginated(
            api_client.list_claims(
                OFFICER,
                {
                    "insolvency_id": insolvency_id,
                    "status": "SCREENED_ELIGIBLE",
                    "limit": 1,
                    "offset": 0,
                },
            )
        )
        assert len(page_one) == 1, len(page_one)
        assert meta_one["total_count"] == 2, (
            f"the filter counts the two screened claims, got {meta_one['total_count']}"
        )
        assert meta_one["limit"] == 1, meta_one["limit"]
        assert meta_one["offset"] == 0, meta_one["offset"]
        assert meta_one["has_more"] is True, meta_one["has_more"]

        page_two, meta_two = validate_paginated(
            api_client.list_claims(
                OFFICER,
                {
                    "insolvency_id": insolvency_id,
                    "status": "SCREENED_ELIGIBLE",
                    "limit": 1,
                    "offset": 1,
                },
            )
        )
        assert len(page_two) == 1, len(page_two)
        assert meta_two["total_count"] == 2, meta_two["total_count"]
        assert meta_two["offset"] == 1, meta_two["offset"]
        assert meta_two["has_more"] is False, (
            f"the window has reached the end of the filtered set, got {meta_two['has_more']}"
        )

        seen = [page_one[0]["id"], page_two[0]["id"]]
        assert set(seen) == {first["id"], second["id"]}, (
            "the two pages together are the filtered set, with no repetition"
        )
        assert unscreened["id"] not in seen, "the unscreened claim appears in neither page"


class TestClockDrivenSweep:
    """Delinquency is a function of the clock, and its boundary is strict."""

    def test_the_levy_turns_delinquent_only_one_second_past_thirty_days(self):
        """Delinquency is driven by the clock rather than by a request: whenever the logical clock is
        advanced, every invoice still in `INVOICED` whose parent assessment's `certified_at_utc`
        advanced by 30 days falls strictly before the new instant is swept `INVOICED → DELINQUENT`,
        leaving its `recoupment_status` untouched, and the count of invoices swept is reported back as
        `delinquent_member_assessment_count`.

        Design: Corner/cross_cutting_complexity_layers/the_delinquency_sweep_fires_only_past_the_thirty_day_boundary
        """
        env = setup_certified_assessment(
            member_specs=HURON_MEMBER,
            needed_amount_cents=150_000,
            policy_overrides=dict(LIVE_TERM),
        )
        invoice_id = env["member_assessment"]["id"]
        assert_instant_equals(env["assessment"]["certified_at_utc"], "2026-08-01T00:00:00Z")
        assert env["member_assessment"]["billing_status"] == "INVOICED"

        at_boundary = move_clock("2026-08-31T00:00:00Z")
        assert at_boundary["delinquent_member_assessment_count"] == 0, (
            "thirty days on from certification is not strictly past it, got "
            f"{at_boundary['delinquent_member_assessment_count']}"
        )
        still_current = read_member_assessment(invoice_id)
        assert still_current["billing_status"] == "INVOICED", still_current["billing_status"]

        past_boundary = move_clock("2026-08-31T00:00:01Z")
        assert past_boundary["delinquent_member_assessment_count"] == 1, (
            "one second later the invoice is swept, got "
            f"{past_boundary['delinquent_member_assessment_count']}"
        )
        swept = read_member_assessment(invoice_id)
        assert swept["billing_status"] == "DELINQUENT", swept["billing_status"]
        assert swept["recoupment_status"] == "NOT_STARTED", (
            f"the sweep leaves the recoupment dimension alone, got {swept['recoupment_status']}"
        )
        assert swept["paid_amount_cents"] == 0, swept["paid_amount_cents"]
        assert read_assessment(env["assessment"]["id"])["status"] == "CERTIFIED"


class TestConfiguredCoverageBasis:
    """One configuration flag decides whether the punitive layer is covered at all."""

    def test_the_same_demand_prices_differently_by_line(self):
        """`covers_punitive_damages` is a boolean that defaults to false; when it is false, the
        punitive portion of a demand is left out of the covered loss basis in that line.

        First, `covered_basis_cents` is the claim's `gross_loss_cents` plus its
        `punitive_damages_cents` when the line's `covers_punitive_damages` is true, or
        `gross_loss_cents` alone when that flag is false.

        Design: Corner/cross_cutting_complexity_layers/the_punitive_damages_flag_toggles_the_covered_basis
        """
        env = setup_declared_insolvency(policy_overrides=dict(LIVE_TERM))
        get_success_data(
            api_client.create_coverage_profile(coverage_profile_payload(**CGL_PROFILE), ADMIN),
            201,
        )
        commercial_policy = create_policy(env["insolvency"]["id"], **CGL_TERM)
        env["insolvency"] = trigger_insolvency(env["insolvency"]["id"])

        auto_claim = get_success_data(
            api_client.create_claim(
                claim_payload(
                    env["insolvency"]["id"],
                    env["policy"]["id"],
                    claim_number="C-AUTO",
                    claimant_name="Ben Ortiz",
                    gross_loss_cents=1_000_000,
                    punitive_damages_cents=500_000,
                ),
                ANALYST,
            ),
            201,
        )
        commercial_claim = get_success_data(
            api_client.create_claim(
                claim_payload(
                    env["insolvency"]["id"],
                    commercial_policy["id"],
                    claim_number="C-CGL",
                    claimant_name="Ben Ortiz",
                    gross_loss_cents=1_000_000,
                    punitive_damages_cents=500_000,
                ),
                ANALYST,
            ),
            201,
        )

        priced_auto = _screen_covered(auto_claim["id"])
        priced_commercial = _screen_covered(commercial_claim["id"])

        assert priced_auto["covered_basis_cents"] == 1_000_000, (
            "the punitive layer is left out where the flag is false, got "
            f"{priced_auto['covered_basis_cents']}"
        )
        assert priced_auto["net_payable_cents"] == 990_000, priced_auto["net_payable_cents"]
        assert priced_auto["cap_binding"] == "NONE", priced_auto["cap_binding"]

        assert priced_commercial["covered_basis_cents"] == 1_500_000, (
            "and admitted where the line covers it, got "
            f"{priced_commercial['covered_basis_cents']}"
        )
        assert priced_commercial["net_payable_cents"] == 1_490_000, (
            priced_commercial["net_payable_cents"]
        )
        assert priced_commercial["cap_binding"] == "NONE", priced_commercial["cap_binding"]


class TestDerivedCountReconciliation:
    """The policy count is recomputed, and both import routes feed it."""

    def test_the_count_tracks_keyed_in_policies_and_converted_records_alike(self):
        """`policy_count` — the count of transferred policies whose `insolvency_id` equals this file's
        `id`, counting policies in every status.

        A directly keyed policy is created in `IMPORTED` with `source_transfer_id` null, with
        `cancellation_date` null, `unexpired_days` 0, `aggregate_paid_cents` 0 and `up_refund_filed`
        false, and the insolvency file's `policy_count` is recomputed.

        Design: Corner/cross_cutting_complexity_layers/policy_count_reconciles_after_every_import_path
        """
        env = setup_triggered_insolvency(with_policy=False, trigger=False)
        insolvency_id = env["insolvency"]["id"]
        assert env["insolvency"]["policy_count"] == 0, env["insolvency"]["policy_count"]

        create_policy(insolvency_id, **LIVE_TERM)
        assert read_insolvency(insolvency_id)["policy_count"] == 1, (
            "the first keyed-in policy is counted"
        )

        create_policy(
            insolvency_id,
            policy_number="PA-1002",
            policyholder_name="Boris Ilic",
            effective_date="2025-10-01",
            expiration_date="2026-10-01",
            annual_premium_cents=365_000,
        )
        assert read_insolvency(insolvency_id)["policy_count"] == 2

        deliver_poc_transfer(
            env,
            "RB-003",
            [
                poc_policy_record(
                    policy_number="PA-1003",
                    policyholder_name="Cora Diaz",
                    policyholder_net_worth_cents=50_000_000,
                    annual_premium_cents=900_000,
                )
            ],
        )
        converted = convert_poc_transfer(env)
        assert converted["status"] == "CONVERTED", converted["status"]
        assert converted["converted_count"] == 1, converted["converted_count"]

        assert read_insolvency(insolvency_id)["policy_count"] == 3, (
            "and the batch route feeds the same recomputed count"
        )
        rows, meta = validate_paginated(
            api_client.list_policies(ADMIN, {"insolvency_id": insolvency_id, "limit": 50})
        )
        assert meta["total_count"] == 3, meta["total_count"]
        assert {row["policy_number"] for row in rows} == {"PA-1001", "PA-1002", "PA-1003"}
