"""Agency claims: the pinned recourse waterfall and the two fiscal equalities."""

from test_helpers import (
    ApiErrorId,
    add_line,
    assert_claim_status,
    assert_money_equal,
    assert_remittance_status,
    assert_statement_status,
    assert_total_count,
    create_claim,
    create_claim_payload,
    create_policy_file,
    create_statement,
    factories,
    issue_policy,
    reconcile_statement,
    submit_statement,
    transition_claim,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import COUNSEL, OFFICER


class TestRecourseTierPinning:
    """The tier is fixed from the gross loss and never revisited."""

    def test_the_tier_and_the_indemnity_come_from_the_gross_ratio(self, api, env):
        """80,000,000 against a 200,000,000 limit is 0.40, which pins `TIER_2`.

        PRD: "The gross ratio is `loss_amount_cents` divided by the agency's
        `eo_policy_limit_cents`, evaluated as an exact rational; `recourse_tier` is
        `TIER_1` when that ratio is at most 0.25, `TIER_2` when it is above 0.25 but at
        most 0.60, and `TIER_3` otherwise."

        Design: Difficulty/combinatorial_formula/claim_tier_pinned_from_gross_loss_not_from_net_exposure
        """
        policy_file = create_policy_file(
            api,
            env,
            closing_date="2026-07-20",
            liability_amount_cents=40_000_000,
            gross_premium_cents=500_000,
        )
        issued = issue_policy(api, env, policy_file["id"])
        assert issued["referral_decided_by_user_id"] is None, (
            "the file never went to referral, so no segregation-of-duties bar applies, "
            f"got {issued['referral_decided_by_user_id']!r}"
        )
        claim = create_claim(
            api,
            env,
            policy_file["id"],
            cause_code="AGENCY_ERROR",
            loss_amount_cents=80_000_000,
        )
        assert_claim_status(claim, "INVESTIGATING")

        demanded = transition_claim(
            api,
            claim["id"],
            "RECOURSE_DEMANDED",
            headers=COUNSEL,
            note="Agency error on search",
        )

        assert demanded["recourse_tier"] == "TIER_2", (
            f"a gross ratio of 0.40 pins TIER_2, got {demanded['recourse_tier']}"
        )
        assert_money_equal(
            demanded["indemnity_offset_cents"],
            60_000_000,
            "indemnity_offset_cents (three quarters of the gross loss)",
        )
        assert_money_equal(
            demanded["recourse_amount_cents"],
            36_000_000,
            "recourse_amount_cents (six tenths of the indemnity)",
        )

    def test_the_net_exposure_never_re_derives_the_tier(self, api, env):
        """A 20,000,000 exposure would imply `TIER_1`, and the stored figures refuse it.

        PRD: "The pinning in step 1 is deliberate and must not be revisited once the later
        steps have run."

        Design: Difficulty/combinatorial_formula/claim_tier_pinned_from_gross_loss_not_from_net_exposure
        """
        policy_file = create_policy_file(
            api,
            env,
            closing_date="2026-07-20",
            liability_amount_cents=40_000_000,
            gross_premium_cents=500_000,
        )
        issue_policy(api, env, policy_file["id"])
        claim = create_claim(
            api,
            env,
            policy_file["id"],
            cause_code="AGENCY_ERROR",
            loss_amount_cents=80_000_000,
        )

        demanded = transition_claim(
            api,
            claim["id"],
            "RECOURSE_DEMANDED",
            headers=COUNSEL,
            note="Agency error on search",
        )

        assert_claim_status(demanded, "RECOURSE_DEMANDED")
        assert_money_equal(
            demanded["net_underwriter_exposure_cents"],
            20_000_000,
            "net_underwriter_exposure_cents (gross loss less the indemnity)",
        )
        assert demanded["recourse_amount_cents"] != 24_000_000, (
            "24,000,000 is the figure a re-derived TIER_1 would produce, but the demand "
            f"reads {demanded['recourse_amount_cents']}"
        )
        assert demanded["recourse_tier"] != "TIER_1", (
            "the 0.10 ratio of the net exposure must not re-tier the claim, got "
            f"{demanded['recourse_tier']}"
        )
        assert demanded["decided_by_user_id"] == "counsel-1", (
            "the adjudicating counsel is recorded, got "
            f"{demanded['decided_by_user_id']!r}"
        )


class TestFiscalEqualities:
    """Settlement must match to the cent, and recovery may not exceed the demand."""

    def test_settlement_and_recovery_must_match_the_computed_figures(self, api, env):
        """One cent short of the share is refused; one cent over the demand is refused.

        PRD: "Recovery — `RECOURSE_DEMANDED` to `RECOVERED` — requires
        `recovered_amount_cents` in the body, else `ERR_INVALID_REQUEST`, and that figure
        may not exceed the claim's `recourse_amount_cents`, else
        `ERR_RECOVERY_EXCEEDS_RECOURSE` (HTTP 422); a recovery equal to the full demand is
        accepted."

        Design: Corner/errors/settlement_and_recovery_amounts_must_match_computed_figures_returns_422
        """
        policy_file = create_policy_file(
            api,
            env,
            closing_date="2026-07-10",
            liability_amount_cents=40_000_000,
            gross_premium_cents=33_333,
        )
        issue_policy(api, env, policy_file["id"])
        statement = create_statement(api, env, "2026-07-01", "2026-07-31")
        add_line(api, env, statement["id"], policy_file["id"], 33_333)
        submit_statement(api, env, statement["id"])
        reconciled = reconcile_statement(api, statement["id"])
        assert_money_equal(
            reconciled["underwriter_share_cents"], 6_667, "underwriter_share_cents"
        )
        assert_money_equal(reconciled["late_fee_cents"], 0, "late_fee_cents")
        assert_money_equal(reconciled["variance_cents"], 0, "variance_cents")

        one_cent_short = api.transition_statement(
            statement["id"],
            factories.statement_state_payload("SETTLED", settled_amount_cents=6_666),
            OFFICER,
        )
        validate_error(
            one_cent_short, ApiErrorId.ERR_SETTLEMENT_AMOUNT_MISMATCH.value, 422
        )

        settled = validate_success(
            api.transition_statement(
                statement["id"],
                factories.statement_state_payload("SETTLED", settled_amount_cents=6_667),
                OFFICER,
            )
        )
        assert_statement_status(settled, "SETTLED")
        assert_remittance_status(
            validate_success(api.get_policy_file(policy_file["id"], OFFICER)), "REMITTED"
        )

        claim = create_claim(
            api,
            env,
            policy_file["id"],
            cause_code="AGENCY_ERROR",
            loss_amount_cents=40_000_000,
        )
        demanded = transition_claim(
            api, claim["id"], "RECOURSE_DEMANDED", headers=COUNSEL, note="Search defect"
        )
        assert demanded["recourse_tier"] == "TIER_1", (
            f"a gross ratio of 0.20 pins TIER_1, got {demanded['recourse_tier']}"
        )
        assert_money_equal(
            demanded["indemnity_offset_cents"], 20_000_000, "indemnity_offset_cents"
        )
        assert_money_equal(
            demanded["recourse_amount_cents"], 12_000_000, "recourse_amount_cents"
        )

        over_recovery = api.transition_claim(
            claim["id"],
            factories.claim_state_payload("RECOVERED", recovered_amount_cents=12_000_001),
            OFFICER,
        )
        validate_error(
            over_recovery, ApiErrorId.ERR_RECOVERY_EXCEEDS_RECOURSE.value, 422
        )

        recovered = transition_claim(
            api,
            claim["id"],
            "RECOVERED",
            headers=OFFICER,
            recovered_amount_cents=12_000_000,
        )

        assert_claim_status(recovered, "RECOVERED")
        assert_money_equal(
            recovered["net_underwriter_exposure_cents"],
            8_000_000,
            "net_underwriter_exposure_cents (loss less indemnity less recovery)",
        )


class TestClaimPolicyCoherence:
    """A claim may only be written against a policy that is actually in force."""

    def test_a_claim_on_a_pending_policy_is_refused_then_accepted_once_issued(
        self, api, env
    ):
        """The identical POST fails on the `PENDING` file and succeeds after issuance.

        PRD: "One referential rule ties the three together: the referenced policy's
        `agency_id` must equal the claim's `agency_id`, that policy's `issuance_status`
        must be `ISSUED` or `LATE_ISSUED`, and when a `cpl_id` is supplied it must equal
        that policy's own `cpl_id`."

        Design: Corner/errors/claim_against_an_unissued_policy_is_rejected_returns_422
        """
        policy_file = create_policy_file(
            api, env, closing_date="2026-07-10", gross_premium_cents=500_000
        )
        payload = create_claim_payload(
            env.agency_id,
            policy_file["id"],
            cause_code="SEARCH_DEFECT",
            loss_amount_cents=25_000_000,
            notice_date="2026-07-28",
        )

        refused = api.create_claim(payload, COUNSEL)

        validate_error(refused, ApiErrorId.ERR_CLAIM_POLICY_MISMATCH.value, 422)
        _rows, empty_meta = validate_paginated(
            api.list_claims(OFFICER, params={"agency_id": env.agency_id})
        )
        assert_total_count(empty_meta, 0)

        issue_policy(api, env, policy_file["id"], policy_number="POL-971")

        accepted = validate_success(api.create_claim(payload, COUNSEL), 201)

        assert_claim_status(accepted, "INVESTIGATING")
        assert accepted["recourse_tier"] is None, (
            f"recourse_tier stays null until the demand, got {accepted['recourse_tier']!r}"
        )
        assert_money_equal(
            accepted["recourse_amount_cents"], 0, "recourse_amount_cents on a new claim"
        )
        assert_money_equal(
            accepted["indemnity_offset_cents"], 0, "indemnity_offset_cents on a new claim"
        )
        _rows, meta = validate_paginated(
            api.list_claims(OFFICER, params={"agency_id": env.agency_id})
        )
        assert_total_count(meta, 1)
