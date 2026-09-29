"""Inclusive and exclusive statutory boundaries, tested one cent either side."""

from test_helpers import (
    SCREENING_ANALYST_USER_ID,
    api_client,
    assert_member_assessment,
    get_success_data,
    make_coverage_analyst_headers,
    read_claim,
    read_member_assessment,
    remit_recoupment,
    setup_member_assessment_with_surcharge,
    setup_two_policies_at_net_worth_boundary,
    validate_error,
)

SINGLE_MEMBER = [
    {
        "naic_code": "20001",
        "insurer_name": "Huron Standard Insurance",
        "direct_written_premium_cents": 10_000_000,
        "annual_cap_rate_bps": 200,
    }
]

NET_WORTH_THRESHOLD = 2_500_000_000
BOUNDARY_PROFILE = {"net_worth_exclusion_threshold_cents": NET_WORTH_THRESHOLD}
ANALYST_HEADERS = make_coverage_analyst_headers(SCREENING_ANALYST_USER_ID)


class TestRecoupmentAtTheLevyCeiling:
    """Reported surcharge proceeds may reach the levy exactly and no further."""

    def _almost_recouped(self) -> dict:
        env = setup_member_assessment_with_surcharge(
            surcharge_rate_bps=25,
            surcharge_base_cents=60_000_000,
            member_specs=SINGLE_MEMBER,
            needed_amount_cents=150_000,
        )
        partial = remit_recoupment(env, 149_999, "RC-1")
        assert partial["recoupment_status"] == "RECOUPING", partial["recoupment_status"]
        assert partial["recouped_amount_cents"] == 149_999
        return env

    def test_one_cent_past_the_levy_is_refused(self):
        """The boundary is exact: reaching precisely `levied_amount_cents` completes the dimension,
        while a sum even one cent above `levied_amount_cents` is refused with `ERR_OVER_RECOUPMENT`.

        Design: Difficulty/boundary_precision_check/recoupment_remittance_at_levy_boundary_versus_one_cent_over
        """
        env = self._almost_recouped()
        invoice_id = env["member_assessment"]["id"]

        response = api_client.create_recoupment_remittance(
            invoice_id, {"proceeds_cents": 2, "remittance_ref": "RC-2"}, env["agent"]
        )
        validate_error(response, "ERR_OVER_RECOUPMENT", 422)

        invoice = read_member_assessment(invoice_id)
        assert invoice["recouped_amount_cents"] == 149_999, (
            f"the refused remittance must bank nothing, got {invoice['recouped_amount_cents']}"
        )
        assert invoice["recoupment_status"] == "RECOUPING", invoice["recoupment_status"]

    def test_the_final_cent_completes_the_recoupment_dimension(self):
        """When that sum reaches `levied_amount_cents` exactly, the dimension completes —
        `SURCHARGE_FILED → RECOUPED` when the whole levy arrives in a single remittance, or
        `RECOUPING → RECOUPED` when it arrives after earlier partial proceeds — and
        `recouped_amount_cents` is set to `levied_amount_cents`.

        Design: Difficulty/boundary_precision_check/recoupment_remittance_at_levy_boundary_versus_one_cent_over
        """
        env = self._almost_recouped()
        final = remit_recoupment(env, 1, "RC-3")

        assert_member_assessment(final)
        assert final["levied_amount_cents"] == 150_000
        assert final["projected_recoupment_cents"] == 150_000
        assert final["recouped_amount_cents"] == 150_000, (
            f"the dimension closes at exactly the levy, got {final['recouped_amount_cents']}"
        )
        assert final["recoupment_status"] == "RECOUPED", final["recoupment_status"]
        assert final["billing_status"] == "INVOICED", (
            f"full recoupment does not collect the levy itself, got {final['billing_status']}"
        )


class TestNetWorthExclusionThreshold:
    """The high-net-worth exclusion bites at the threshold, not below it."""

    def _boundary_pair(self) -> dict:
        return setup_two_policies_at_net_worth_boundary(
            low_net_worth_cents=NET_WORTH_THRESHOLD - 1,
            high_net_worth_cents=NET_WORTH_THRESHOLD,
            gross_loss_cents=900_000,
            profile_overrides=dict(BOUNDARY_PROFILE),
        )

    def test_one_cent_below_the_threshold_screens_through(self):
        """Two substantive coverage gates guard the operation: the claim's parent policy must be in
        `CANCELLED_BY_ORDER`, else `ERR_POLICY_NOT_CANCELLED`; and the policy's
        `policyholder_net_worth_cents` must be strictly below the governing line's
        `net_worth_exclusion_threshold_cents`, else `ERR_NET_WORTH_EXCLUSION` — a net worth exactly
        equal to the threshold is excluded, since the statutory test is exclusion at or above the
        threshold.

        Design: Difficulty/boundary_precision_check/net_worth_exclusion_fires_exactly_at_the_threshold_not_one_cent_below
        """
        env = self._boundary_pair()
        screened = get_success_data(
            api_client.screen_claim(
                env["low_net_worth_claim"]["id"], {"decision": "COVERED"}, ANALYST_HEADERS
            )
        )

        assert screened["status"] == "SCREENED_ELIGIBLE", screened["status"]
        assert screened["net_payable_cents"] == 890_000, (
            "a 900000 loss less the 10000 statutory deductible is payable in full, got "
            f"{screened['net_payable_cents']}"
        )
        assert screened["screened_by_user_id"] == SCREENING_ANALYST_USER_ID

    def test_exactly_at_the_threshold_the_claim_is_excluded(self):
        """The policyholder's `policyholder_net_worth_cents` is strictly below the line's
        `net_worth_exclusion_threshold_cents` → `ERR_NET_WORTH_EXCLUSION` (HTTP 422), on
        `POST /claims/{id}/screen`.

        Design: Difficulty/boundary_precision_check/net_worth_exclusion_fires_exactly_at_the_threshold_not_one_cent_below
        """
        env = self._boundary_pair()
        response = api_client.screen_claim(
            env["high_net_worth_claim"]["id"], {"decision": "COVERED"}, ANALYST_HEADERS
        )
        validate_error(response, "ERR_NET_WORTH_EXCLUSION", 422)

        claim = read_claim(env["high_net_worth_claim"]["id"])
        assert claim["status"] == "RECEIVED", (
            f"the excluded claim never leaves intake, got {claim['status']}"
        )
        assert claim["net_payable_cents"] == 0, (
            f"no payable is computed for an excluded claim, got {claim['net_payable_cents']}"
        )

    def test_the_refused_screening_leaves_no_trace_on_the_excluded_claim(self):
        """The claim is created in `RECEIVED` with `filed_at_utc` stamped from the logical clock, with
        `source_transfer_id` null when filed directly, with `paid_amount_cents` and `remand_count` at
        0, with `cap_binding` at `NONE`, with `pre_referral_status`, `referred_to_state_code`,
        `denial_reason`, `screened_by_user_id`, `approved_by_user_id`, `recommended_amount_cents`,
        `recommended_by_vendor_name` and `recommended_at_utc` all null, and with the next monotone
        `sequence` value assigned by the server.

        Design: Difficulty/boundary_precision_check/net_worth_exclusion_fires_exactly_at_the_threshold_not_one_cent_below
        """
        env = self._boundary_pair()
        api_client.screen_claim(
            env["high_net_worth_claim"]["id"], {"decision": "COVERED"}, ANALYST_HEADERS
        )

        claim = read_claim(env["high_net_worth_claim"]["id"])
        assert claim["screened_by_user_id"] is None, (
            "a refused screening records no analyst, got "
            f"{claim['screened_by_user_id']}"
        )
        assert claim["denial_reason"] is None
        assert claim["cap_binding"] == "NONE", claim["cap_binding"]
        assert claim["version"] == 1, (
            f"the refused screening must not bump the claim version, got {claim['version']}"
        )
