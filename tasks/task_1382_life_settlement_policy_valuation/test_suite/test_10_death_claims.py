"""Death verification and the settle/maturity cascade (PRD §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_finance_headers, make_compliance_headers,
    setup_case_acquired, setup_case_with_reported_claim, setup_case_with_filed_claim,
    add_verified_death_event, create_schedule, set_clock,
)

CM = TEST_USERS["case_manager_headers"]
PM = TEST_USERS["portfolio_manager_headers"]
UW = TEST_USERS["underwriter_headers"]
CO_1 = make_compliance_headers("co_1")
FO_1 = make_finance_headers("fo_1")


class TestClaimVerificationSources:
    def test_claim_verify_rejected_with_single_source(self, api):
        """PRD §3.8: "Verifying a claim requires `certificate_received` to be true
        in the payload (otherwise `ERR_INVALID_REQUEST`) and at least two
        `VERIFIED` tracking events on the case with outcome `DEATH_INDICATED` whose
        `source_channel` values are pairwise distinct — the count of distinct
        channels among such events is exactly what `verification_source_count`
        tracks — with a shortfall rejected as
        `ERR_VERIFICATION_SOURCES_INSUFFICIENT`."

        Design: Difficulty/cross_entity_state_dependency/claim_verify_rejected_with_single_source
        """
        ctx = setup_case_with_reported_claim()  # one VERIFIED OBIT source
        resp = api.verify_death_claim(ctx["claim"]["id"], {"certificate_received": True}, CO_1)
        validate_error(resp, ApiErrorId.ERR_VERIFICATION_SOURCES_INSUFFICIENT)

        add_verified_death_event(ctx["case"]["id"], "DMF", "DMF_MATCH")
        verified = validate_success(api.verify_death_claim(
            ctx["claim"]["id"], {"certificate_received": True}, CO_1))
        assert verified["status"] == "VERIFIED"
        assert verified["verification_source_count"] == 2

    def test_claim_create_requires_one_verified_death_event(self, api):
        """PRD §3.8: "A death claim is opened on an `ACQUIRED` case by a compliance
        officer supplying the ISO `date_of_death`; opening requires at least one
        `VERIFIED` tracking event on the case with outcome `DEATH_INDICATED`, and
        is otherwise rejected with `ERR_VERIFICATION_SOURCES_INSUFFICIENT`
        (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/claim_verify_rejected_with_single_source
        """
        ctx = setup_case_acquired(
            insured_overrides={"smoker_status": "UNKNOWN"})
        set_clock("2026-08-20T00:00:00Z")
        # No tracking events at all: claim create is rejected.
        resp = api.create_death_claim(ctx["case"]["id"], {"date_of_death": "2026-08-20"}, CO_1)
        validate_error(resp, ApiErrorId.ERR_VERIFICATION_SOURCES_INSUFFICIENT)

        # A RECORDED (not yet verified) event does not count.
        ev = validate_success(api.create_tracking_event(
            ctx["case"]["id"],
            {"event_type": "OBIT_SEARCH", "outcome": "DEATH_INDICATED",
             "source_channel": "OBIT", "event_date": "2026-08-20"},
            CM), expected_status=201)
        assert ev["status"] == "RECORDED"
        resp2 = api.create_death_claim(ctx["case"]["id"], {"date_of_death": "2026-08-20"}, CO_1)
        validate_error(resp2, ApiErrorId.ERR_VERIFICATION_SOURCES_INSUFFICIENT)

        validate_success(api.verify_tracking_event(ev["id"], CO_1))
        claim = validate_success(api.create_death_claim(
            ctx["case"]["id"], {"date_of_death": "2026-08-20"}, CO_1), expected_status=201)
        assert claim["status"] == "REPORTED"
        assert claim["verification_source_count"] == 0
        assert claim["certificate_received"] is False


class TestContestabilityFork:
    def test_contested_claim_requires_acknowledgement(self, api):
        """PRD §3.8: "Settling with `PAID` requires `gross_proceeds_cents` present
        and greater than zero (otherwise `ERR_INVALID_REQUEST`), and branches on
        contestability: when the claim's `in_contestability` is true and the
        payload's `contest_review_acknowledged` is not true, the claim moves from
        `FILED` to `CONTESTED` instead of paying — this is a branch, not an error;
        a contested claim pays out on a later settle that supplies
        `contest_review_acknowledged` true."
        PRD §3.8: "its computed `in_contestability` is true exactly when the
        `date_of_death` falls earlier than twenty-four months after the case's
        `acquired_at` — the carrier's contest window on the ownership transfer."
        PRD §3.8: "the claim's `net_proceeds_cents` is computed: the carrier's
        gross proceeds minus the policy's outstanding `policy_loan_cents` minus
        unpaid scheduled premiums, floored at zero."

        Design: Corner/state_machines/contested_claim_requires_acknowledgement
        """
        ctx = setup_case_with_filed_claim()  # acquired 2026-08-16, death 2026-08-20
        claim = ctx["claim"]
        assert claim["in_contestability"] is True

        contested = validate_success(api.settle_death_claim(
            claim["id"], {"outcome": "PAID", "gross_proceeds_cents": 10000000}, CO_1))
        assert contested["status"] == "CONTESTED"

        paid = validate_success(api.settle_death_claim(
            claim["id"], {"outcome": "PAID", "gross_proceeds_cents": 10000000,
                          "contest_review_acknowledged": True}, CO_1))
        assert paid["status"] == "PAID"
        assert paid["net_proceeds_cents"] == 10000000, "no loan, no schedule -> no deductions"
        case_after = validate_success(api.get_case(ctx["case"]["id"], CM))
        assert case_after["status"] == "MATURED"


class TestMaturityCascade:
    def test_death_settlement_maturity_chain(self, api):
        """PRD §3.8: "A paid settlement fires the maturity cascade: the claim moves
        to `PAID`; the case moves from `ACQUIRED` to `MATURED` and stamps
        `matured_at`; the insured's `status` becomes `DECEASED`; the policy's
        `status` becomes `MATURED`; the case's `ACTIVE` premium schedule moves to
        `TERMINATED`; the portfolio's `nav_stale` becomes true and its `version`
        increments, with `invested_capital_cents` unchanged by the settlement
        itself; and every `DRAFT` valuation snapshot on the portfolio moves to
        `SUPERSEDED`."
        PRD §3.8: "Unpaid scheduled premiums are the `amount_cents` of payments on
        the case's `ACTIVE` schedule in `SCHEDULED` or `MISSED` status whose
        `due_date` falls at or before the end of the `date_of_death` day in UTC."

        Design: Difficulty/transitive_cascade/death_settlement_maturity_chain
        """
        ctx = setup_case_acquired(
            start_clock="2026-07-20T00:00:00Z",
            fund_clock="2026-08-15T00:00:00Z",
            release_clock="2026-09-05T00:00:00Z",
        )
        case, pf = ctx["case"], ctx["portfolio"]
        sched = create_schedule(case["id"])  # first payment due 2026-10-05

        set_clock("2026-10-01T00:00:00Z")
        snap = validate_success(api.create_valuation_snapshot(
            pf["id"], {"period_start": "2026-09-05", "period_end": "2026-10-01",
                       "expected_portfolio_version":
                           validate_success(api.get_portfolio(pf["id"], PM))["version"]},
            PM), expected_status=201)
        assert snap["status"] == "DRAFT"

        set_clock("2026-10-10T00:00:00Z")
        add_verified_death_event(case["id"], "OBIT", "OBIT_SEARCH", event_date="2026-10-10")
        add_verified_death_event(case["id"], "DMF", "DMF_MATCH", event_date="2026-10-10")
        claim = validate_success(api.create_death_claim(
            case["id"], {"date_of_death": "2026-10-10"}, CO_1), expected_status=201)
        validate_success(api.verify_death_claim(claim["id"], {"certificate_received": True}, CO_1))
        validate_success(api.file_death_claim(claim["id"], CM))

        set_clock("2026-10-15T00:00:00Z")
        settled = validate_success(api.settle_death_claim(
            claim["id"], {"outcome": "PAID", "gross_proceeds_cents": 10000000,
                          "contest_review_acknowledged": True}, CO_1))
        assert settled["status"] == "PAID"
        # unpaid = the SCHEDULED payment due 2026-10-05 (at/before end of death day)
        assert settled["net_proceeds_cents"] == 9950000

        case_after = validate_success(api.get_case(case["id"], CM))
        assert case_after["status"] == "MATURED"
        assert case_after["matured_at"] == "2026-10-15T00:00:00Z"
        insured_after = validate_success(api.get_insured(ctx["insured"]["id"], CM))
        assert insured_after["status"] == "DECEASED"
        policy_after = validate_success(api.get_policy(ctx["policy"]["id"], CM))
        assert policy_after["status"] == "MATURED"
        sched_after = validate_success(api.get_premium_schedule(sched["id"], PM))
        assert sched_after["status"] == "TERMINATED"
        pf_after = validate_success(api.get_portfolio(pf["id"], PM))
        assert pf_after["nav_stale"] is True
        snap_after = validate_success(api.get_valuation_snapshot(snap["id"], PM))
        assert snap_after["status"] == "SUPERSEDED"

    def test_death_settlement_denied_fires_no_cascade(self, api):
        """PRD §3.8: "Settling with `DENIED` moves a `FILED` or `CONTESTED` claim
        to `DENIED` with no further effects."
        PRD §3.8: "A paid settlement fires the maturity cascade: the claim moves to
        `PAID`; the case moves from `ACQUIRED` to `MATURED` and stamps
        `matured_at`; the insured's `status` becomes `DECEASED`; the policy's
        `status` becomes `MATURED`; the case's `ACTIVE` premium schedule moves to
        `TERMINATED`"

        Design: Difficulty/transitive_cascade/death_settlement_maturity_chain
        """
        ctx = setup_case_with_filed_claim(date_of_death="2026-08-20",
                                          insured_overrides={"smoker_status": "UNKNOWN"})
        claim = ctx["claim"]
        settled = validate_success(api.settle_death_claim(claim["id"], {"outcome": "DENIED"}, CO_1))
        assert settled["status"] == "DENIED"
        assert settled["net_proceeds_cents"] is None

        case_after = validate_success(api.get_case(ctx["case"]["id"], CM))
        assert case_after["status"] == "ACQUIRED", "DENIED fires no maturity cascade"
        assert case_after["matured_at"] is None
        insured_after = validate_success(api.get_insured(ctx["insured"]["id"], CM))
        assert insured_after["status"] == "LIVING"
        policy_after = validate_success(api.get_policy(ctx["policy"]["id"], CM))
        assert policy_after["status"] == "IN_FORCE"
