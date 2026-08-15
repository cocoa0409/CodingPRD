"""Funding grants and the partner-report ledger: creation defaults, OCC on
report create, submit/review/suspend/close, and the conserved-cents invariant."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_institution_officer_headers,
    create_funding_grant_payload, create_partner_report_payload,
    create_grant, activate_grant, setup_active_grant, get_grant,
    setup_certified_institution, setup_report_ready,
    create_report, submit_report, suspend_institution,
    setup_referral_docs_complete, create_application, decide_application,
    assert_grant_ledger_invariant,
)

ADMIN = TEST_USERS["coalition_admin_headers"]


class TestGrantCreation:
    def test_grant_created_draft_with_zeroed_ledger(self, api):
        """PRD §3.9: "A new grant is `DRAFT` with `reserved_cents` and `disbursed_cents` zero."
        PRD §2.8: "`reserved_cents` is the sum of `claim_total_cents` over the grant's reports in `SUBMITTED` status, `disbursed_cents` is the sum of `claim_total_cents` over its reports in `APPROVED` status, and `available_cents` is `total_cents` minus the other two."

        Design: Corner/entities/grant_ledger_fields_zeroed_on_create
        """
        resp = api.create_funding_grant(
            create_funding_grant_payload(total_cents=500000), ADMIN
        )
        data = validate_success(resp, 201)
        assert data["status"] == "DRAFT"
        assert data["reserved_cents"] == 0
        assert data["disbursed_cents"] == 0
        assert data["available_cents"] == 500000
        assert_grant_ledger_invariant(data)


class TestOccReportCreate:
    def test_stale_grant_version_rejected_412(self, api):
        """PRD §2.6: "Creating a partner report requires the request to carry `expected_grant_version`, holding the `version` of the target `FundingGrant` as the client last observed it. Because report creation advances the grant's `version` as a ledger-anchor touch, a create that arrives carrying the previously observed version is acting on a stale view of the grant's ledger state; if the supplied value does not match the grant's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_report_create_412
        """
        ctx = setup_certified_institution()
        inst_id = ctx["institution"]["id"]
        officer = make_institution_officer_headers(inst_id)
        grant = setup_active_grant()
        stale_version = grant["version"]

        create_report(inst_id, grant, period_start="2026-01-01",
                      period_end="2026-03-31", expected_grant_version=stale_version)

        resp = api.create_partner_report(
            create_partner_report_payload(
                inst_id, grant["id"], stale_version,
                period_start="2026-04-01", period_end="2026-06-30",
            ),
            officer,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        grant_after = get_grant(grant["id"])
        assert grant_after["version"] == stale_version + 1, (
            "bumped exactly once by the successful first create"
        )
        _, meta = validate_paginated(
            api.list_partner_reports(ADMIN, params={"grant_id": grant["id"]})
        )
        assert meta["total_count"] == 1


class TestSubmitRequiresActiveGrant:
    def test_submit_with_suspended_grant_rejected(self, api):
        """PRD §3.9: "The grant must be `ACTIVE` (`ERR_GRANT_NOT_ACTIVE` otherwise)."
        PRD §3.9: "Suspending an `ACTIVE` grant (from any other status, `ERR_INVALID_STATE`) runs a cascade: every `PartnerReport` of the grant in `SUBMITTED` moves back to `DRAFT`"

        Design: Difficulty/cross_entity_state_dependency/report_submit_requires_active_grant
        """
        ctx = setup_report_ready(num_accounts=1)
        inst_id = ctx["institution"]["id"]
        report = create_report(inst_id, ctx["grant"])  # DRAFT; claim 4963
        api.suspend_funding_grant(ctx["grant"]["id"], ADMIN)  # DRAFT report untouched

        resp = api.submit_partner_report(
            report["id"], make_institution_officer_headers(inst_id)
        )
        validate_error(resp, ApiErrorId.ERR_GRANT_NOT_ACTIVE)

    def test_rejected_submit_leaves_report_draft_and_ledger_untouched(self, api):
        """PRD §3.9: "The grant must be `ACTIVE` (`ERR_GRANT_NOT_ACTIVE` otherwise)."
        PRD §2.8: "First, the funding-grant ledger conserves cents: for each `FundingGrant`, `available_cents` plus `reserved_cents` plus `disbursed_cents` always equals `total_cents`"

        Design: Difficulty/cross_entity_state_dependency/report_submit_requires_active_grant
        """
        ctx = setup_report_ready(num_accounts=1)
        inst_id = ctx["institution"]["id"]
        report = create_report(inst_id, ctx["grant"])
        api.suspend_funding_grant(ctx["grant"]["id"], ADMIN)
        api.submit_partner_report(report["id"], make_institution_officer_headers(inst_id))

        report_after = get_success_data(api.get_partner_report(report["id"], ADMIN))
        assert report_after["status"] == "DRAFT"
        grant_after = get_grant(ctx["grant"]["id"])
        assert grant_after["reserved_cents"] == 0
        assert_grant_ledger_invariant(grant_after)


class TestSubmitPriorityStateOverFiscal:
    def test_resubmit_submitted_report_returns_invalid_state(self, api):
        """PRD §2.10: "State-machine legality is fifth — a target resource not in a state from which the requested transition exists surfaces `ERR_INVALID_STATE`."
        PRD §2.10: "and capacity, quota, and fiscal limits tenth (event full, coach caseload, claim cap, grant funds, campaign budget, pending claims, negotiation rounds, certification lapsed)."
        PRD §3.9: "Submission moves a report from `DRAFT` or `REJECTED` to `SUBMITTED` (any other starting status yields `ERR_INVALID_STATE`)."

        Design: Difficulty/priority_pair_validation_conflict/report_submit_state_vs_fiscal
        """
        # Grant total 9000: after R1 submits (claim 4963), available 4037 < 4963,
        # so a second submit of R1 violates BOTH the state rule and the funds
        # rule; the state rule outranks.
        ctx = setup_report_ready(num_accounts=1, grant_total=9000)
        inst_id = ctx["institution"]["id"]
        report = create_report(inst_id, ctx["grant"])
        submit_report(report["id"], inst_id)

        resp = api.submit_partner_report(
            report["id"], make_institution_officer_headers(inst_id)
        )
        err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert err["error_id"] == "ERR_INVALID_STATE", (
            "not ERR_INSUFFICIENT_GRANT_FUNDS: state (fifth) beats fiscal (tenth)"
        )

    def test_failed_resubmit_leaves_no_drift(self, api):
        """PRD §2.8: "First, the funding-grant ledger conserves cents: for each `FundingGrant`, `available_cents` plus `reserved_cents` plus `disbursed_cents` always equals `total_cents`, including across the reservation release that compensates a rejected report and across the grant-suspend cascade."
        PRD §3.9: "On submission the grant's `reserved_cents` increases by the claim and its `available_cents` decreases by the same amount."

        Design: Difficulty/priority_pair_validation_conflict/report_submit_state_vs_fiscal
        """
        ctx = setup_report_ready(num_accounts=1, grant_total=9000)
        inst_id = ctx["institution"]["id"]
        report = create_report(inst_id, ctx["grant"])
        submit_report(report["id"], inst_id)
        api.submit_partner_report(report["id"], make_institution_officer_headers(inst_id))

        report_after = get_success_data(api.get_partner_report(report["id"], ADMIN))
        assert report_after["status"] == "SUBMITTED"
        grant_after = get_grant(ctx["grant"]["id"])
        assert grant_after["reserved_cents"] == 4963
        assert grant_after["available_cents"] == 4037
        assert_grant_ledger_invariant(grant_after)


class TestGrantSuspendCascade:
    def test_suspend_moves_grant_and_returns_reports_to_draft(self, api):
        """PRD §3.9: "Suspending an `ACTIVE` grant (from any other status, `ERR_INVALID_STATE`) runs a cascade: every `PartnerReport` of the grant in `SUBMITTED` moves back to `DRAFT`, and each such report's reservation is released — the grant's `reserved_cents` decreases by the report's `claim_total_cents` and its `available_cents` increases by the same amount."

        Design: Difficulty/transitive_cascade/grant_suspend_release_cascade
        """
        ctx = setup_report_ready(num_accounts=1, grant_total=50000)
        inst_id = ctx["institution"]["id"]
        report = create_report(inst_id, ctx["grant"])  # claim 4963
        submit_report(report["id"], inst_id)

        grant_mid = get_grant(ctx["grant"]["id"])
        assert grant_mid["reserved_cents"] == 4963
        assert grant_mid["available_cents"] == 45037

        data = validate_success(api.suspend_funding_grant(ctx["grant"]["id"], ADMIN), 200)
        assert data["status"] == "SUSPENDED"  # cascade link 1

    def test_suspend_releases_reservation_through_report_transition(self, api):
        """PRD §3.9: "Suspending an `ACTIVE` grant (from any other status, `ERR_INVALID_STATE`) runs a cascade: every `PartnerReport` of the grant in `SUBMITTED` moves back to `DRAFT`, and each such report's reservation is released — the grant's `reserved_cents` decreases by the report's `claim_total_cents` and its `available_cents` increases by the same amount."
        PRD §2.8: "First, the funding-grant ledger conserves cents: for each `FundingGrant`, `available_cents` plus `reserved_cents` plus `disbursed_cents` always equals `total_cents`, including across the reservation release that compensates a rejected report and across the grant-suspend cascade."

        Design: Difficulty/transitive_cascade/grant_suspend_release_cascade
        """
        ctx = setup_report_ready(num_accounts=1, grant_total=50000)
        inst_id = ctx["institution"]["id"]
        report = create_report(inst_id, ctx["grant"])
        submit_report(report["id"], inst_id)
        api.suspend_funding_grant(ctx["grant"]["id"], ADMIN)

        report_after = get_success_data(api.get_partner_report(report["id"], ADMIN))
        assert report_after["status"] == "DRAFT"  # cascade link 2
        grant_after = get_grant(ctx["grant"]["id"])
        assert grant_after["reserved_cents"] == 0  # cascade link 3
        assert grant_after["available_cents"] == 50000
        assert_grant_ledger_invariant(grant_after)


class TestLedgerConservation:
    def test_submit_reserves_claim(self, api):
        """PRD §3.9: "On submission the grant's `reserved_cents` increases by the claim and its `available_cents` decreases by the same amount."
        PRD §2.8: "First, the funding-grant ledger conserves cents: for each `FundingGrant`, `available_cents` plus `reserved_cents` plus `disbursed_cents` always equals `total_cents`"

        Design: Difficulty/compensating_invariant/grant_ledger_submit_reject_conserved
        """
        ctx = setup_report_ready(num_accounts=1, grant_total=500000)
        inst_id = ctx["institution"]["id"]
        report = create_report(inst_id, ctx["grant"])  # claim 4963
        submit_report(report["id"], inst_id)

        grant_mid = get_grant(ctx["grant"]["id"])
        assert grant_mid["reserved_cents"] == 4963
        assert grant_mid["available_cents"] == 495037
        assert grant_mid["disbursed_cents"] == 0
        assert_grant_ledger_invariant(grant_mid)

    def test_reject_releases_reservation_with_zero_drift(self, api):
        """PRD §3.9: "A rejecting review moves the report to `REJECTED` and releases the reservation as compensation: `reserved_cents` decreases by the claim and `available_cents` increases by the claim."
        PRD §2.8: "First, the funding-grant ledger conserves cents: for each `FundingGrant`, `available_cents` plus `reserved_cents` plus `disbursed_cents` always equals `total_cents`, including across the reservation release that compensates a rejected report and across the grant-suspend cascade."

        Design: Difficulty/compensating_invariant/grant_ledger_submit_reject_conserved
        """
        ctx = setup_report_ready(num_accounts=1, grant_total=500000)
        inst_id = ctx["institution"]["id"]
        report = create_report(inst_id, ctx["grant"])
        submit_report(report["id"], inst_id)
        data = validate_success(
            api.review_partner_report(report["id"], {"outcome": "REJECT"}, ADMIN), 200
        )
        assert data["status"] == "REJECTED"

        grant_end = get_grant(ctx["grant"]["id"])
        assert grant_end["available_cents"] == 500000, "compensation restores available exactly"
        assert grant_end["reserved_cents"] == 0
        assert grant_end["disbursed_cents"] == 0
        assert_grant_ledger_invariant(grant_end)


class TestGrantClose:
    def test_close_with_pending_claims_rejected(self, api):
        """PRD §3.9: "Closing a grant requires it to be `ACTIVE` (`ERR_INVALID_STATE` otherwise) and to carry no pending claims: no report of the grant may be `SUBMITTED` and `reserved_cents` must be zero, with any pending residue rejected as `ERR_GRANT_HAS_PENDING_CLAIMS`."

        Design: Corner/errors/grant_close_with_pending_claims_rejected
        """
        ctx = setup_report_ready(num_accounts=1)
        inst_id = ctx["institution"]["id"]
        report = create_report(inst_id, ctx["grant"])
        submit_report(report["id"], inst_id)

        resp = api.close_funding_grant(ctx["grant"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_GRANT_HAS_PENDING_CLAIMS)
        grant_after = get_grant(ctx["grant"]["id"])
        assert grant_after["status"] == "ACTIVE"
        assert grant_after["reserved_cents"] == 4963, "reservation untouched"


class TestRejectedResubmit:
    def test_resubmit_recomputes_claim_against_current_data(self, api):
        """PRD §3.9: "A resubmission from `REJECTED` recomputes every claim field against current data before applying the same reservation."
        PRD §3.9: "Submission moves a report from `DRAFT` or `REJECTED` to `SUBMITTED` (any other starting status yields `ERR_INVALID_STATE`)."

        Design: Corner/state_machines/report_rejected_resubmit_recomputes_claim
        """
        ctx = setup_report_ready(num_accounts=1, grant_total=500000)
        inst_id = ctx["institution"]["id"]
        report = create_report(inst_id, ctx["grant"])  # 1 account -> 4963
        submit_report(report["id"], inst_id)
        validate_success(
            api.review_partner_report(report["id"], {"outcome": "REJECT"}, ADMIN), 200
        )

        # A second account opens (same institution) between reject and resubmit.
        pr = setup_referral_docs_complete(full_name="Ben Okafor", date_of_birth="1985-11-02")
        app = create_application(inst_id, pr["participant"]["id"],
                                 referral_id=pr["referral"]["id"])
        decide_application(app["id"], inst_id, "APPROVE")

        data = validate_success(
            api.submit_partner_report(
                report["id"], make_institution_officer_headers(inst_id)
            ), 200
        )
        assert data["status"] == "SUBMITTED"
        assert data["claim_total_cents"] == 9926, (
            "recomputed: two OPENED accounts x 4963, not the stale 4963 snapshot"
        )
        grant_after = get_grant(ctx["grant"]["id"])
        assert grant_after["reserved_cents"] == 9926
