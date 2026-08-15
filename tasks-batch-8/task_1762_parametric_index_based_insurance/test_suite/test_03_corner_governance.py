"""Queue B (corner design) — validations, endpoints, errors, RBAC,
cross-cutting layers, and the consistency model.

One or more tests per non-stub corner instance; each docstring carries a
verbatim PRD citation plus its `Design: Corner/<section>/<instance.name>` tag.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    create_and_bind_treaty,
    create_bound_policy,
    create_policyholder,
    create_program,
    create_quoted_policy,
    create_verified_event_with_claim,
    find_event_for_window,
    get_success_data,
    ingest_observation,
    list_claims_for_policy,
    make_claims_adjuster_headers,
    make_treasury_officer_headers,
    pay_invoice_in_full,
    setup_active_program,
    setup_approved_claim,
    setup_paid_claim,
    setup_program_with_bound_policy,
    validate_error,
    validate_paginated,
    validate_success,
    verify_event,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["program_manager_headers"]
ACT = TEST_USERS["actuary_headers"]
UW = TEST_USERS["underwriter_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]
TRE = TEST_USERS["treasury_officer_headers"]
FRA = TEST_USERS["fraud_analyst_headers"]
DOPS = TEST_USERS["data_operations_headers"]
SVC = TEST_USERS["servicing_agent_headers"]

MISSING = "00000000-0000-0000-0000-000000000000"

TIERS_2 = [
    {"tier": 1, "threshold_value": 50, "payout_fraction": 0.25},
    {"tier": 2, "threshold_value": 30, "payout_fraction": 0.5},
]
TIERS_3 = [
    {"tier": 1, "threshold_value": 50, "payout_fraction": 0.25},
    {"tier": 2, "threshold_value": 30, "payout_fraction": 0.5},
    {"tier": 3, "threshold_value": 20, "payout_fraction": 1.0},
]
TIERS_1 = [{"tier": 1, "threshold_value": 50, "payout_fraction": 0.25}]


# ===========================================================================
# Section validations
# ===========================================================================

class TestMissingAuthHeaders:
    def test_request_without_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role the
        system does not recognize, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_rejected
        """
        program = create_program(program_code="PRG-V1")
        resp = api.get_program(program["id"], headers={})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            expected_status=400,
        )


class TestSupersessionChain:
    def test_superseding_already_superseded_row_rejected(self, api):
        """PRD §3.3: "A `supersedes_observation_id` that references no existing
        observation draws `ERR_OBSERVATION_NOT_FOUND`, and one that references a
        row other than the currently-effective observation for that
        station-window pair — a broken correction chain — draws
        `ERR_SUPERSESSION_CHAIN_BROKEN` (HTTP 409)."

        Design: Corner/validations/supersession_chain_broken_error
        """
        program, station, index = setup_active_program(program_code="PRG-V2")
        prog_id, idx_id = program["id"], index["id"]
        obs1 = ingest_observation(prog_id, idx_id, station["id"], "2026-06-30", 40)
        ingest_observation(prog_id, idx_id, station["id"], "2026-06-30", 45,
                           supersedes_observation_id=obs1["id"])
        # obs1 is no longer the effective row; a new revision naming it breaks the chain.
        resp = api.create_observation(
            prog_id, idx_id,
            {"station_id": station["id"], "window_end_date": "2026-06-30",
             "measured_value": 47, "supersedes_observation_id": obs1["id"]},
            DOPS,
        )
        validate_error(resp, ApiErrorId.ERR_SUPERSESSION_CHAIN_BROKEN, expected_status=409)


class TestTreatyCreationCapacity:
    def test_zero_ceded_percentage_rejected(self, api):
        """PRD §3.9: "A `ProgramManager` creates a treaty proposal by supplying
        the `treaty_name`, the `ceded_percentage` ceded to the reinsurer — which
        must be greater than 0 and at most 100, with violations rejected as
        `ERR_TREATY_CAPACITY_INVALID` (HTTP 422)"

        Design: Corner/validations/treaty_creation_invalid_percentage
        """
        program, station, index = setup_active_program(program_code="PRG-V3")
        resp = api.create_treaty(
            program["id"],
            {"treaty_name": "T-BAD", "ceded_percentage": 0,
             "attachment_point_cents": 0, "treaty_limit_cents": 1_000_000},
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_TREATY_CAPACITY_INVALID, expected_status=422)

    def test_percentage_above_100_rejected(self, api):
        """PRD §3.9: "the `ceded_percentage` ceded to the reinsurer — which must
        be greater than 0 and at most 100, with violations rejected as
        `ERR_TREATY_CAPACITY_INVALID` (HTTP 422)"

        Design: Corner/validations/treaty_creation_invalid_percentage
        """
        program, station, index = setup_active_program(program_code="PRG-V3B")
        resp = api.create_treaty(
            program["id"],
            {"treaty_name": "T-BAD2", "ceded_percentage": 101,
             "attachment_point_cents": 0, "treaty_limit_cents": 1_000_000},
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_TREATY_CAPACITY_INVALID, expected_status=422)


class TestAdjustTierAboveBreach:
    def test_adjust_above_max_tier_rejected(self, api):
        """PRD §3.7: "The adjustment submits a `new_tier`, which must be at
        least 1, must not exceed the event's `max_tier_breached`, and must
        differ from the claim's current `tier_applied`; any of the three
        violations is rejected with `ERR_TIER_EXCEEDS_BREACH` (HTTP 422)."

        Design: Corner/validations/adjust_tier_above_breach_rejected
        """
        stack = setup_program_with_bound_policy(
            program_code="PRG-V4", trigger_thresholds=TIERS_3
        )
        prog_id = stack["program"]["id"]
        # 40mm breaches tier 1 only (t2 needs <= 30).
        _, claims = create_verified_event_with_claim(stack, measured_value=40)
        claim = claims[0]
        assert claim["tier_applied"] == 1
        resp = api.adjust_claim(prog_id, claim["id"], {"new_tier": 3}, ADJ)
        validate_error(resp, ApiErrorId.ERR_TIER_EXCEEDS_BREACH, expected_status=422)
        after = validate_success(api.get_claim(prog_id, claim["id"], ADJ))
        assert after["status"] == "GENERATED"
        assert after["tier_applied"] == 1


class TestClaimGenerationCoverageWindow:
    def test_out_of_coverage_policy_receives_no_claim(self, api):
        """PRD §3.6: "For every policy `BOUND` on this index whose coverage
        window — `policy_start_date` through `policy_end_date`, both inclusive —
        contains the event's `window_end_date`, the system generates exactly one
        claim, producing them in the order the policies were created; a policy
        whose window does not contain the window end date contributes no claim
        (this is the claim-generation side of `ERR_WINDOW_OUT_OF_COVERAGE`)."

        Design: Corner/validations/claim_generation_skips_out_of_coverage_policy
        """
        program, station, index = setup_active_program(program_code="PRG-V5")
        prog_id, idx_id = program["id"], index["id"]
        holder = create_policyholder(prog_id)
        pol_a, _ = create_bound_policy(prog_id, holder["id"], idx_id,
                                       sum_insured_cents=2_000_000)
        pol_b, _ = create_bound_policy(
            prog_id, holder["id"], idx_id, sum_insured_cents=1_000_000,
            policy_start_date="2026-07-01", policy_end_date="2026-12-31",
        )
        ingest_observation(prog_id, idx_id, station["id"], "2026-06-30", 40)
        event = find_event_for_window(prog_id, idx_id, "2026-06-30")
        verify_event(prog_id, idx_id, event["id"])
        claims_a = list_claims_for_policy(prog_id, pol_a["id"])
        claims_b = list_claims_for_policy(prog_id, pol_b["id"])
        assert len(claims_a) == 1, "policy A covers 2026-06-30 and claims"
        assert claims_b == [], (
            "policy B's coverage starts 2026-07-01; the 2026-06-30 window is outside"
        )
        all_event_claims = get_success_data(api.list_claims(
            prog_id, ADJ, params={"trigger_event_id": event["id"]}
        ))
        assert len(all_event_claims) == 1


class TestFutureObservationWindow:
    def test_future_window_rejected_past_accepted(self, api):
        """PRD §2.4: "Temporal validation also reads this clock: an observation
        whose `window_end_date` lies in the future relative to the logical clock
        is rejected."
        PRD §3.3: "the `window_end_date` must not lie in the future relative to
        the logical clock (`ERR_WINDOW_OUT_OF_COVERAGE`, HTTP 422)."

        Design: Corner/validations/future_observation_window_rejected
        """
        program, station, index = setup_active_program(program_code="PRG-V6")
        validate_success(api.set_clock({"to_iso8601": "2026-06-15T00:00:00Z"}, PM))
        resp = api.create_observation(
            program["id"], index["id"],
            {"station_id": station["id"], "window_end_date": "2026-06-30",
             "measured_value": 40},
            DOPS,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_OUT_OF_COVERAGE, expected_status=422)
        ok = validate_success(api.create_observation(
            program["id"], index["id"],
            {"station_id": station["id"], "window_end_date": "2026-06-14",
             "measured_value": 40},
            DOPS,
        ), expected_status=201)
        assert ok["id"]


class TestDisputeOnUnsettledClaim:
    def test_dispute_on_generated_claim_rejected(self, api):
        """PRD §3.8: "A `ServicingAgent` may open a dispute on behalf of a
        policyholder against a claim that has reached a settled outcome —
        `PAID`, `RECOVERY_CEDED`, or `DECLINED`; an attempt against a claim in
        any other state is rejected with `ERR_CLAIM_NOT_SETTLED`."

        Design: Corner/validations/dispute_on_unsettled_claim_rejected
        """
        stack = setup_program_with_bound_policy(
            program_code="PRG-V7", trigger_thresholds=TIERS_2
        )
        prog_id = stack["program"]["id"]
        _, claims = create_verified_event_with_claim(stack)
        resp = api.create_dispute(
            prog_id, claims[0]["id"],
            {"dispute_reason": "BASIS_RISK_MISMATCH", "claimed_tier": 2}, SVC,
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_SETTLED, expected_status=409)


class TestDeniedDataSourceDisputeFraudScore:
    def test_denied_data_source_error_adds_10_other_reasons_add_0(self, api):
        """PRD §3.8: "One resolution path feeds the fraud model. When a dispute
        is resolved `DENIED` and its `dispute_reason` was `DATA_SOURCE_ERROR`,
        the policyholder's `fraud_score` is increased by 10, clamped within the
        0-to-100 band of §3.4 — frivolous challenges to the data feed are
        treated as a contagion signal that nudges the holder toward the
        automatic hold threshold."
        PRD §3.8: "On `DENIED`, the delta is zero."

        Design: Corner/validations/denied_data_source_dispute_raises_fraud_score
        """
        # measured_value=30 breaches both tiers (max_tier=2). The claim is
        # approved at tier 2, so claiming tier 1 is a valid downward assertion.
        stack, _, claim = setup_paid_claim(
            program_code="PRG-V8", trigger_thresholds=TIERS_2, measured_value=30,
        )
        prog_id = stack["program"]["id"]
        holder_id = stack["holder"]["id"]
        d1 = validate_success(api.create_dispute(
            prog_id, claim["id"],
            {"dispute_reason": "DATA_SOURCE_ERROR", "claimed_tier": 1}, SVC,
        ), expected_status=201)
        validate_success(api.resolve_dispute(
            prog_id, claim["id"], d1["id"], {"resolution": "DENIED"}, ADJ
        ))
        holder = validate_success(api.get_policyholder(prog_id, holder_id, FRA))
        assert holder["fraud_score"] == 10
        d2 = validate_success(api.create_dispute(
            prog_id, claim["id"],
            {"dispute_reason": "BASIS_RISK_MISMATCH", "claimed_tier": 1}, SVC,
        ), expected_status=201)
        validate_success(api.resolve_dispute(
            prog_id, claim["id"], d2["id"], {"resolution": "DENIED"}, ADJ
        ))
        holder = validate_success(api.get_policyholder(prog_id, holder_id, FRA))
        assert holder["fraud_score"] == 10, (
            "a DENIED non-data-source dispute adds nothing"
        )
        claim_after = validate_success(api.get_claim(prog_id, claim["id"], ADJ))
        assert claim_after["final_payout_cents"] == 1_000_000, (
            "denials carry a zero delta; the final payout does not move"
        )


# ===========================================================================
# Section endpoints
# ===========================================================================

class TestListPagination:
    def test_pagination_envelope_defaults(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return. If not provided, it defaults to 10, with a minimum of 1
        and maximum of 100. The `offset` parameter specifies the number of items
        to skip and defaults to 0."
        PRD §2.3: "Paginated and non-paginated list-based responses include the
        following fields in the `meta` object of the response envelope:
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_pagination_envelope_defaults
        """
        program = create_program(program_code="PRG-EP1")
        for i in range(3):
            create_policyholder(
                program["id"], acknowledged=False,
                legal_name=f"H{i + 1}", tax_id=f"T{i + 1}",
            )
        page1, meta1 = validate_paginated(api.list_policyholders(
            program["id"], SVC, params={"limit": 2, "offset": 0}
        ))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(api.list_policyholders(
            program["id"], SVC, params={"limit": 2, "offset": 2}
        ))
        assert len(page2) == 1
        assert meta2["has_more"] is False


class TestFinancialSummary:
    def test_financial_summary_reflects_ledger(self, api):
        """PRD §3.1: "At any point, a computed financial-summary read returns
        the program's profit-and-loss snapshot as of the current epoch:
        `gross_written_premium_cents`, `incurred_claims_cents`,
        `ceded_recovery_cents`, `net_retained_exposure_cents`,
        `fraud_alert_count`, and `reporting_epoch` together describe the
        program's standing for reporting and reinsurance-interplay purposes."
        PRD §3.5: "the program's `gross_written_premium_cents` grows by the
        policy's `premium_cents`"

        Design: Corner/endpoints/financial_summary_computed_read
        """
        stack, _, claim = setup_paid_claim(
            program_code="PRG-EP2", trigger_thresholds=TIERS_1
        )
        summary = validate_success(api.get_financial_summary(stack["program"]["id"], PM))
        assert summary["gross_written_premium_cents"] == 300_000, (
            "GWP counts premium_cents only, tax excluded"
        )
        assert summary["incurred_claims_cents"] == 500_000
        assert summary["ceded_recovery_cents"] == 0


class TestReportingEpoch:
    def test_advance_reporting_epoch_increments(self, api):
        """PRD §3.1: "An operations run by a `ProgramManager` advances the
        reporting epoch, incrementing `reporting_epoch` by one and — because it
        is a program mutation — the program's `version` by one as well."

        Design: Corner/endpoints/reporting_epoch_advances
        """
        program = create_program(
            program_code="PRG-EP3", peril_type="WINDSPEED"
        )
        first = validate_success(api.advance_reporting_epoch(program["id"], PM))
        assert first["reporting_epoch"] == 1
        assert first["version"] == 2
        second = validate_success(api.advance_reporting_epoch(program["id"], PM))
        assert second["reporting_epoch"] == 2
        assert second["version"] == 3


# ===========================================================================
# Section errors
# ===========================================================================

class TestErrorCoverageProgramNotActive:
    def test_bind_while_program_suspended(self, api):
        """PRD §3.5: "the parent program must be `ACTIVE`
        (`ERR_PROGRAM_NOT_ACTIVE`)"
        PRD §2.6: "4. Whether the parent program's status permits the operation
        (`ERR_PROGRAM_NOT_ACTIVE`) — policy binding, observation ingestion, and
        treaty binding all require an `ACTIVE` program."

        Design: Corner/errors/error_coverage_program_not_active_on_bind
        """
        program, station, index = setup_active_program(program_code="PRG-ER1")
        holder = create_policyholder(program["id"])
        policy, invoice = create_quoted_policy(
            program["id"], holder["id"], index["id"], sum_insured_cents=2_000_000
        )
        pay_invoice_in_full(program["id"], invoice["id"])
        validate_success(api.suspend_program(program["id"], PM))
        resp = api.bind_policy(program["id"], holder["id"], policy["id"], UW)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE, expected_status=409)


class TestErrorCoverageHolderNotActiveForBind:
    def test_bind_for_prospect_holder(self, api):
        """PRD §3.5: "the policyholder must be `ACTIVE`
        (`ERR_HOLDER_NOT_ACTIVE_FOR_BIND`)"

        Design: Corner/errors/error_coverage_holder_not_active_for_bind
        """
        program, station, index = setup_active_program(program_code="PRG-ER2")
        holder = create_policyholder(program["id"], acknowledged=False,
                                     legal_name="H-ER2", tax_id="T-ER2")
        assert holder["status"] == "PROSPECT"
        policy, invoice = create_quoted_policy(
            program["id"], holder["id"], index["id"], sum_insured_cents=2_000_000
        )
        pay_invoice_in_full(program["id"], invoice["id"])
        resp = api.bind_policy(program["id"], holder["id"], policy["id"], UW)
        validate_error(resp, ApiErrorId.ERR_HOLDER_NOT_ACTIVE_FOR_BIND, expected_status=409)


class TestErrorCoverageClearFraudHold:
    def test_clear_fraud_hold_on_approved_claim(self, api):
        """PRD §3.7: "a `FraudAnalyst` clears the hold on a claim standing in
        `FRAUD_HOLD` (otherwise `ERR_CLAIM_NOT_IN_FRAUD_HOLD`)"

        Design: Corner/errors/error_coverage_clear_fraud_hold_requires_hold
        """
        stack, _, claim = setup_approved_claim(
            program_code="PRG-ER3", trigger_thresholds=TIERS_1
        )
        resp = api.clear_fraud_hold(stack["program"]["id"], claim["id"], FRA)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_IN_FRAUD_HOLD, expected_status=409)


class TestErrorCoverageReleaseRequiresApproved:
    def test_release_on_generated_claim(self, api):
        """PRD §3.7: "Payment release belongs to the `TreasuryOfficer` alone and
        requires the claim to be `APPROVED` (`ERR_CLAIM_NOT_APPROVED`)."

        Design: Corner/errors/error_coverage_release_requires_approved
        """
        stack = setup_program_with_bound_policy(
            program_code="PRG-ER4", trigger_thresholds=TIERS_1
        )
        prog_id = stack["program"]["id"]
        _, claims = create_verified_event_with_claim(stack)
        resp = api.release_payment(
            prog_id, claims[0]["id"], make_treasury_officer_headers("treasury-1")
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_APPROVED, expected_status=409)


class TestErrorCoverageTreatyAndInvoiceState:
    def test_rebind_active_treaty_and_pay_paid_invoice(self, api):
        """PRD §3.9: "The treaty must still be `PROPOSED`
        (`ERR_TREATY_NOT_PROPOSED`)"
        PRD §3.5: "the invoice must be `ISSUED` or `PARTIALLY_PAID` (otherwise
        `ERR_INVOICE_NOT_PAYABLE`)"

        Design: Corner/errors/error_coverage_treaty_not_proposed_and_invoice_not_payable
        """
        program, station, index = setup_active_program(program_code="PRG-ER5")
        prog_id = program["id"]
        treaty = create_and_bind_treaty(
            prog_id, treaty_name="T-ER5", ceded_percentage=25,
            attachment_point_cents=0, treaty_limit_cents=1_000_000,
        )
        holder = create_policyholder(prog_id)
        policy, invoice = create_quoted_policy(
            prog_id, holder["id"], index["id"], sum_insured_cents=2_000_000
        )
        pay_invoice_in_full(prog_id, invoice["id"])

        prog = validate_success(api.get_program(prog_id, PM))
        resp = api.bind_treaty(
            prog_id, treaty["id"], {"expected_program_version": prog["version"]}, PM
        )
        validate_error(resp, ApiErrorId.ERR_TREATY_NOT_PROPOSED, expected_status=409)

        resp = api.pay_invoice(prog_id, invoice["id"], {"amount_cents": 100}, SVC)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_PAYABLE, expected_status=409)


class TestErrorCoverageInvalidRequestAndObservationNotFound:
    def test_missing_required_field_and_missing_supersede_target(self, api):
        """PRD §2.6: "Independent of this ordering, any request with a malformed
        body, a missing required field, or an invalid enum value is rejected
        with `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.3: "A `supersedes_observation_id` that references no existing
        observation draws `ERR_OBSERVATION_NOT_FOUND`"

        Design: Corner/errors/error_coverage_invalid_request_and_observation_not_found
        """
        program, station, index = setup_active_program(program_code="PRG-ER6")
        resp = api.create_station(
            program["id"],
            {"station_kind": "PHYSICAL_STATION", "reliability_weight": 1.0},
            DOPS,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
        resp = api.create_observation(
            program["id"], index["id"],
            {"station_id": station["id"], "window_end_date": "2026-06-30",
             "measured_value": 40, "supersedes_observation_id": MISSING},
            DOPS,
        )
        validate_error(resp, ApiErrorId.ERR_OBSERVATION_NOT_FOUND, expected_status=404)


class TestErrorCoverageResumeGuards:
    def test_resume_active_program_and_active_index(self, api):
        """PRD §3.1: "Resuming reverses the cycle: it requires the program to be
        `SUSPENDED` (otherwise `ERR_PROGRAM_NOT_SUSPENDED`)"
        PRD §3.2: "Once active, an index can be suspended and resumed by a
        `ProgramManager` — suspension requires `ACTIVE` status
        (`ERR_INDEX_NOT_ACTIVE`), resumption requires `SUSPENDED` status
        (`ERR_INDEX_NOT_SUSPENDED`)"

        Design: Corner/errors/error_coverage_program_not_suspended_and_index_not_suspended
        """
        program, station, index = setup_active_program(program_code="PRG-ER7")
        resp = api.resume_program(program["id"], PM)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_SUSPENDED, expected_status=409)
        resp = api.resume_index(program["id"], index["id"], PM)
        validate_error(resp, ApiErrorId.ERR_INDEX_NOT_SUSPENDED, expected_status=409)


# ===========================================================================
# Section rbac
# ===========================================================================

class TestRbacUnderwriterCannotVerify:
    def test_underwriter_verify_denied(self, api):
        """PRD §2.1: "Beyond authentication, every write operation is restricted
        to designated roles; an authenticated operator who attempts an action
        outside their role is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §2.1: "`ClaimsAdjuster` — verifies trigger events, adjusts,
        approves, and declines claims, and adjudicates disputes."

        Design: Corner/rbac/rbac_underwriter_cannot_verify_event
        """
        program, station, index = setup_active_program(program_code="PRG-R1")
        prog_id, idx_id = program["id"], index["id"]
        ingest_observation(prog_id, idx_id, station["id"], "2026-06-30", 40)
        event = find_event_for_window(prog_id, idx_id, "2026-06-30")
        get_success_data(api.open_event_review(prog_id, idx_id, event["id"], ADJ))
        resp = api.verify_event(prog_id, idx_id, event["id"], UW)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)
        after = validate_success(api.get_trigger_event(prog_id, idx_id, event["id"], ADJ))
        assert after["status"] == "UNDER_REVIEW"


class TestRbacAdjusterAndAgentDenials:
    def test_adjuster_cannot_release_and_agent_cannot_create_index(self, api):
        """PRD §2.1: "`TreasuryOfficer` — releases claim payments, deliberately
        segregated from claim approval."
        PRD §2.1: "`Actuary` — defines indexes, pricing parameters, and
        regulatory classification inputs; activates and decommissions indexes."
        PRD §2.1: "an authenticated operator who attempts an action outside
        their role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/rbac_adjuster_cannot_release_payment_and_agent_cannot_create_index
        """
        stack, _, claim = setup_approved_claim(
            program_code="PRG-R2", approver_user_id="adjuster-1",
            trigger_thresholds=TIERS_1,
        )
        prog_id = stack["program"]["id"]
        resp = api.release_payment(
            prog_id, claim["id"], make_claims_adjuster_headers("adjuster-2")
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)
        after = validate_success(api.get_claim(prog_id, claim["id"], ADJ))
        assert after["status"] == "APPROVED"
        resp = api.create_index_definition(
            prog_id,
            {"index_code": "IDX-R2B", "measurement_unit": "mm",
             "aggregation_window_days": 30, "data_source_agreement_ref": "DSA-R2B",
             "source_priority_mode": "STATION_PRIMARY",
             "trigger_thresholds": [{"tier": 1, "threshold_value": 50, "payout_fraction": 0.25}],
             "strike_direction": "BELOW",
             "historical_breach_frequency": 0.2, "expected_loss_ratio": 0.6},
            SVC,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)


class TestRbacDataOpsAndFraudDenials:
    def test_dataops_cannot_blacklist_and_fraud_cannot_ingest(self, api):
        """PRD §2.1: "`FraudAnalyst` — manages fraud signals, blacklists
        policyholders, and clears fraud holds."
        PRD §2.1: "`DataOperations` — operates measurement stations and ingests
        index observations."
        PRD §2.1: "an authenticated operator who attempts an action outside
        their role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/rbac_dataops_cannot_blacklist_and_fraud_cannot_ingest
        """
        program, station, index = setup_active_program(program_code="PRG-R3")
        holder = create_policyholder(program["id"], acknowledged=False,
                                     legal_name="H-R3", tax_id="T-R3")
        resp = api.blacklist_policyholder(program["id"], holder["id"], DOPS)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)
        resp = api.create_observation(
            program["id"], index["id"],
            {"station_id": station["id"], "window_end_date": "2026-06-30",
             "measured_value": 40},
            FRA,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)


# ===========================================================================
# Section cross_cutting_layers
# ===========================================================================

class TestOccTreatyBind:
    def test_stale_version_rejected_then_fresh_succeeds(self, api):
        """PRD §2.8: "Each requires the client to supply
        `expected_program_version`, carrying the program `version` the client
        last observed; the field is non-optional on these two calls. If the
        supplied value does not match the program's current `version` — because
        a bind, a payment release, a treaty binding, or an epoch advance has
        advanced it since the client last read the program — the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/cross_cutting_layers/occ_treaty_bind_stale_version_rejected
        """
        program, station, index = setup_active_program(program_code="PRG-CC1")
        prog_id = program["id"]
        stale_version = program["version"]
        treaty = validate_success(api.create_treaty(
            prog_id,
            {"treaty_name": "T-CC1", "ceded_percentage": 25,
             "attachment_point_cents": 0, "treaty_limit_cents": 1_000_000},
            PM,
        ), expected_status=201)
        # Intervening program mutation advances the version.
        validate_success(api.advance_reporting_epoch(prog_id, PM))
        resp = api.bind_treaty(
            prog_id, treaty["id"], {"expected_program_version": stale_version}, PM
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        fresh = validate_success(api.get_program(prog_id, PM))
        bound = validate_success(api.bind_treaty(
            prog_id, treaty["id"], {"expected_program_version": fresh["version"]}, PM
        ))
        assert bound["status"] == "ACTIVE"


class TestOccProgramClose:
    def test_close_with_stale_version_rejected_then_commutes_treaty(self, api):
        """PRD §2.8: "**Closing a program** — any mutation that advanced the
        program's `version` since the client's last read invalidates the basis
        on which the close preconditions were checked."
        PRD §3.1: "A successful close moves the program to `CLOSED`, expires
        every policy still `BOUND` (each such policy's settlement posture is
        left unchanged by the cascade), commutes every `ACTIVE` reinsurance
        treaty, and increments the program's `version` by one."

        Design: Corner/cross_cutting_layers/occ_program_close_stale_version_rejected
        """
        program, station, index = setup_active_program(program_code="PRG-CC2")
        prog_id = program["id"]
        stale_version = program["version"]
        treaty = validate_success(api.create_treaty(
            prog_id,
            {"treaty_name": "T-CC2", "ceded_percentage": 25,
             "attachment_point_cents": 0, "treaty_limit_cents": 1_000_000},
            PM,
        ), expected_status=201)
        # The treaty bind itself advances the program version.
        bound = validate_success(api.bind_treaty(
            prog_id, treaty["id"], {"expected_program_version": stale_version}, PM
        ))
        assert bound["status"] == "ACTIVE"
        resp = api.close_program(
            prog_id, {"expected_program_version": stale_version}, PM
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        fresh = validate_success(api.get_program(prog_id, PM))
        closed = validate_success(api.close_program(
            prog_id, {"expected_program_version": fresh["version"]}, PM
        ))
        assert closed["status"] == "CLOSED"
        treaty_after = validate_success(api.get_treaty(prog_id, treaty["id"], PM))
        assert treaty_after["status"] == "COMMUTED", (
            "close commutes every ACTIVE treaty"
        )


class TestIdempotentVerify:
    def test_second_verify_rejected_without_duplicate_claims(self, api):
        """PRD §3.6: "The adjuster's verify action requires the event to be
        `UNDER_REVIEW` (otherwise `ERR_EVENT_NOT_UNDER_REVIEW`)"
        PRD §3.6: "For every policy `BOUND` on this index whose coverage window
        — `policy_start_date` through `policy_end_date`, both inclusive —
        contains the event's `window_end_date`, the system generates exactly one
        claim"

        Design: Corner/cross_cutting_layers/idempotent_retrigger_second_verify_rejected
        """
        stack = setup_program_with_bound_policy(
            program_code="PRG-CC3", trigger_thresholds=TIERS_1
        )
        prog_id = stack["program"]["id"]
        idx_id = stack["index"]["id"]
        event, claims = create_verified_event_with_claim(stack)
        assert len(claims) == 1
        resp = api.verify_event(prog_id, idx_id, event["id"], ADJ)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_UNDER_REVIEW, expected_status=409)
        claims_after = get_success_data(api.list_claims(
            prog_id, ADJ, params={"trigger_event_id": event["id"]}
        ))
        assert len(claims_after) == 1, (
            "a retried verify must not duplicate claim generation"
        )


# ===========================================================================
# Section consistency_model
# ===========================================================================

class TestImmediateConsistency:
    def test_release_effects_visible_in_same_read(self, api):
        """PRD §2.10: "Every such mutation, whether client-initiated or
        automatic, refreshes `updated_at` and increments `version` on the
        mutated resource, and all computed program aggregates are reconciled
        within the same atomic request so that reads never observe a partially
        applied cascade."
        PRD §3.7: "In the same atomic step the program's
        `incurred_claims_cents` grows by the claim's `final_payout_cents`, the
        program's `ceded_recovery_cents` grows by the claim's ceded total, and
        if every claim of the policy has now reached a terminal state the
        policy's posture settles to `SETTLED_QUIET`."

        Design: Corner/consistency_model/immediate_consistency_cascade_visible_same_read
        """
        stack, _, claim = setup_approved_claim(
            program_code="PRG-CM1", trigger_thresholds=TIERS_1
        )
        prog_id = stack["program"]["id"]
        released = validate_success(api.release_payment(
            prog_id, claim["id"], make_treasury_officer_headers("treasury-1")
        ))
        assert released["status"] == "PAID", "no treaties -> no cession -> PAID"
        program = validate_success(api.get_program(prog_id, PM))
        assert program["incurred_claims_cents"] == 500_000, (
            "the aggregate is reconciled within the release request"
        )
        policy = validate_success(api.get_policy(
            prog_id, stack["holder"]["id"], stack["policy"]["id"], UW
        ))
        assert policy["settlement_posture"] == "SETTLED_QUIET", (
            "the posture bubble-up is visible immediately"
        )
