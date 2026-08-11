"""Difficulty queue: non-linear state machines (account cycle, case cycle, deposit cycle)."""
from test_helpers import (
    TEST_USERS,
    advance_deposit,
    api_client,
    approve_account,
    begin_investigation,
    create_account,
    create_customer,
    create_deposit,
    create_rep,
    create_rule,
    escalate_alert,
    get_account,
    get_deposit,
    list_alerts_for_account,
    post_structuring_buys,
    recommend_sar,
    run_daily_sweep,
    run_scan,
    set_clock,
    submit_and_verify_document,
    validate_success,
)


def _setup_open_account_with_expiring_doc(doc_expiry: str = "2026-05-10"):
    set_clock("2026-05-01T00:00:00Z")
    rep = create_rep(full_name="Rep F", crd_number="CRD-SM1")
    customer = create_customer(
        rep,
        customer_type="INDIVIDUAL",
        full_name="F Low",
        tax_id="TIN-SM1",
        country_risk_tier="LOW",
        is_pep=False,
    )
    submit_and_verify_document(customer["id"], rep, document_number="P-SM1",
                               expiry_date=doc_expiry)
    account = create_account(customer["id"], rep, product_set=["CASH"])
    approve_account(account["id"])
    return rep, customer, account


class TestAccountLifecycleCycleWithIndependentPostureDimension:
    def _elevated_account(self):
        rep, customer, account = _setup_open_account_with_expiring_doc()
        set_clock("2026-05-11T00:00:00Z")
        sweep = run_daily_sweep()
        assert sweep["documents_expired"] == 1, (
            f"Setup failed: sweep expired {sweep['documents_expired']} documents"
        )
        return rep, account

    def test_lifecycle_cycles_open_restricted_open_restricted(self, api):
        """PRD §3.3: "An `OPEN` account can be restricted by a `ComplianceOfficer`
        (who may supply a `reason`), moving `OPEN` → `RESTRICTED`" and "Reinstatement
        returns a `RESTRICTED` account to `OPEN`".
        The lifecycle machine is cyclic: OPEN -> RESTRICTED -> OPEN -> RESTRICTED.

        Design: Difficulty/non_linear_state_machine/account_lifecycle_cycle_with_independent_posture_dimension
        """
        _rep, account = self._elevated_account()
        resp = api_client.restrict_account(
            account["id"], {"reason": "manual review"}, TEST_USERS["officer_headers"]
        )
        assert validate_success(resp)["lifecycle_status"] == "RESTRICTED"
        resp = api_client.reinstate_account(account["id"], TEST_USERS["officer_headers"])
        assert validate_success(resp)["lifecycle_status"] == "OPEN"
        resp = api_client.restrict_account(
            account["id"], {"reason": "second cycle"}, TEST_USERS["officer_headers"]
        )
        assert validate_success(resp)["lifecycle_status"] == "RESTRICTED"

    def test_posture_dimension_unchanged_by_lifecycle_cycling(self, api):
        """PRD §2.5: "any identification document in `VERIFIED` whose `expiry_date` is
        earlier than the clock date becomes `EXPIRED`, and the AML posture of every
        account belonging to that customer is recomputed."
        PRD §3.4: "Elevation from `STANDARD` to `ELEVATED` occurs when any of four
        triggers is present: a `VERIFIED` identification document on the customer has
        expired and not yet been superseded; an EDD review of the account sits in
        `REFRESH_DUE`; the account's `has_suspicion_flag` is set; or the account's
        `risk_score` is at least 70."
        The expired document keeps the account ELEVATED throughout the lifecycle cycle.

        Design: Difficulty/non_linear_state_machine/account_lifecycle_cycle_with_independent_posture_dimension
        """
        _rep, account = self._elevated_account()
        before = get_account(account["id"])
        assert before["aml_posture"] == "ELEVATED", (
            f"expired document must elevate posture, got {before['aml_posture']}"
        )
        api_client.restrict_account(
            account["id"], {"reason": "manual review"}, TEST_USERS["officer_headers"]
        )
        api_client.reinstate_account(account["id"], TEST_USERS["officer_headers"])
        api_client.restrict_account(
            account["id"], {"reason": "second cycle"}, TEST_USERS["officer_headers"]
        )
        after = get_account(account["id"])
        assert after["aml_posture"] == "ELEVATED", (
            "posture is a parallel dimension and must survive lifecycle cycling; "
            f"got {after['aml_posture']}"
        )


class TestAmlCaseCloseReopenInvestigateCycle:
    def _setup_investigating_case(self):
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep G", crd_number="CRD-SM2")
        customer = create_customer(
            rep,
            customer_type="INDIVIDUAL",
            full_name="G Low",
            tax_id="TIN-SM2",
            country_risk_tier="LOW",
            is_pep=False,
        )
        submit_and_verify_document(customer["id"], rep, document_number="P-SM2")
        account = create_account(customer["id"], rep, product_set=["CASH"])
        approve_account(account["id"])
        create_rule(rule_code="STRUCTURING", threshold_amount=10000.00, window_days=2,
                    min_transaction_count=3)
        post_structuring_buys(account["id"], rep)
        run_scan()
        alert = list_alerts_for_account(account["id"])[0]
        resp = api_client.begin_alert_review(alert["id"], TEST_USERS["analyst_headers"])
        validate_success(resp)
        case_id = escalate_alert(alert["id"])["case_id"]
        investigating = begin_investigation(case_id)
        return account, case_id, investigating

    def test_case_machine_loops_through_close_and_reopen(self, api):
        """PRD §3.6: "A `SAROfficer` may instead decide not to file, from either
        `INVESTIGATING` or `SAR_RECOMMENDED`, moving the case to `DECIDED_NO_FILE` with
        a `rationale`."
        PRD §3.6: "Closing a case is allowed from `DECIDED_NO_FILE` or `DECIDED_FILED`"
        and "an `AMLAnalyst` may reopen a `CLOSED` case with a `reason`, recorded in
        `reopen_reason`, moving `CLOSED` → `REOPENED`".
        PRD §3.6: "Investigation begins when an `AMLAnalyst` moves the case from `OPEN`
        (or, after a reopen, from `REOPENED`) to `INVESTIGATING`".

        Design: Difficulty/non_linear_state_machine/aml_case_close_reopen_investigate_cycle
        """
        _account, case_id, _investigating = self._setup_investigating_case()
        resp = api_client.decide_no_file(
            case_id, {"rationale": "no suspicion"}, TEST_USERS["sar_officer_headers"]
        )
        assert validate_success(resp)["status"] == "DECIDED_NO_FILE"
        resp = api_client.close_case(case_id, TEST_USERS["sar_officer_headers"])
        assert validate_success(resp)["status"] == "CLOSED"
        resp = api_client.reopen_case(
            case_id, {"reason": "new evidence"}, TEST_USERS["analyst_headers"]
        )
        assert validate_success(resp)["status"] == "REOPENED"
        assert begin_investigation(case_id)["status"] == "INVESTIGATING"
        recommended = recommend_sar(
            case_id,
            analyst_id="analyst-sm2",
            initial_detection_date="2026-05-02",
            recommendation_note="second round",
        )
        assert recommended["status"] == "SAR_RECOMMENDED"

    def test_each_case_transition_increments_version_and_restamps_recommender(self, api):
        """PRD §2.4: "`version` (integer): starts at its initial value on creation and
        increments by one on every mutation of the resource, including system-driven
        transitions and cascade-driven updates."
        PRD §3.6: "the system stamps `recommending_analyst_id` from `X-User-ID`".
        Five transitions after INVESTIGATING (decide-no-file, close, reopen,
        begin-investigation, recommend-sar) each add exactly one.

        Design: Difficulty/non_linear_state_machine/aml_case_close_reopen_investigate_cycle
        """
        _account, case_id, investigating = self._setup_investigating_case()
        v1 = investigating["version"]
        resp = api_client.decide_no_file(
            case_id, {"rationale": "no suspicion"}, TEST_USERS["sar_officer_headers"]
        )
        validate_success(resp)
        resp = api_client.close_case(case_id, TEST_USERS["sar_officer_headers"])
        validate_success(resp)
        resp = api_client.reopen_case(
            case_id, {"reason": "new evidence"}, TEST_USERS["analyst_headers"]
        )
        validate_success(resp)
        begin_investigation(case_id)
        recommended = recommend_sar(
            case_id,
            analyst_id="analyst-sm2",
            initial_detection_date="2026-05-02",
            recommendation_note="second round",
        )
        assert recommended["version"] == v1 + 5, (
            f"five transitions must add exactly 5 to version {v1}, "
            f"got {recommended['version']}"
        )
        assert recommended["recommending_analyst_id"] == "analyst-sm2"


class TestCertificateDepositRejectResubmitCycle:
    def _setup_rejected_deposit(self):
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep H", crd_number="CRD-SM3")
        customer = create_customer(
            rep,
            customer_type="INDIVIDUAL",
            full_name="H Low",
            tax_id="TIN-SM3",
            country_risk_tier="LOW",
            is_pep=False,
        )
        submit_and_verify_document(customer["id"], rep, document_number="P-SM3")
        account = create_account(customer["id"], rep, product_set=["CASH"])
        approve_account(account["id"])
        deposit = create_deposit(
            account["id"],
            certificate_number="CN-SM3",
            cusip="CUSIPSM3",
            security_name="SM3 Corp",
            quantity=10,
            unit_price=40.00,
        )
        deposit = advance_deposit(deposit["id"])
        deposit = advance_deposit(deposit["id"])
        deposit = advance_deposit(deposit["id"])
        hold_release = deposit["hold_release_date"]
        set_clock("2026-05-06T00:00:00Z")
        run_daily_sweep()
        deposit = get_deposit(deposit["id"])
        assert deposit["status"] == "READY_TO_ACCEPT", (
            f"Setup failed: deposit {deposit['status']} after sweep"
        )
        resp = api_client.decide_deposit(
            deposit["id"],
            {
                "expected_deposit_version": deposit["version"],
                "outcome": "REJECT",
                "reason": "blurry medallion",
            },
            TEST_USERS["officer_headers"],
        )
        rejected = validate_success(resp)
        return account, rejected, hold_release

    def test_resubmitted_deposit_skips_eligibility_review(self, api):
        """PRD §3.8: "A rejected deposit may cycle back: an `OperationsAnalyst`
        resubmits it with a `note`, moving `REJECTED` → `RESUBMITTED`
        (`ERR_DEPOSIT_NOT_RESUBMITTABLE` from any other state), and a subsequent advance
        from `RESUBMITTED` skips eligibility and enters `AUTHENTICITY_REVIEW` directly".
        PRD §3.8: "Entering `CLEARANCE_HOLD` stamps `hold_release_date`: the hold lasts
        ten calendar days for a low-priced certificate and five otherwise" — first entry
        2026-05-01 with a regular 40.00 cert releases 2026-05-06.

        Design: Difficulty/non_linear_state_machine/certificate_deposit_reject_resubmit_cycle
        """
        _account, rejected, hold_release = self._setup_rejected_deposit()
        assert hold_release == "2026-05-06", (
            f"regular cert hold is 5 days from 2026-05-01 entry, got {hold_release}"
        )
        assert rejected["status"] == "REJECTED"

        resp = api_client.resubmit_deposit(
            rejected["id"], {"note": "new medallion stamp"}, TEST_USERS["ops_headers"]
        )
        resubmitted = validate_success(resp)
        assert resubmitted["status"] == "RESUBMITTED"
        advanced = advance_deposit(resubmitted["id"])
        assert advanced["status"] == "AUTHENTICITY_REVIEW", (
            f"advance from RESUBMITTED must skip ELIGIBILITY_REVIEW, "
            f"got {advanced['status']}"
        )

    def test_cycle_closes_at_accepted_after_second_hold(self, api):
        """PRD §2.5: "any deposit in `CLEARANCE_HOLD` whose `hold_release_date` is on
        or before the clock date becomes `READY_TO_ACCEPT` — release is inclusive, so
        a clock date equal to the release date releases the hold."
        PRD §3.8: "**Accept** moves `READY_TO_ACCEPT` → `ACCEPTED`".
        Re-entering CLEARANCE_HOLD at 2026-05-06 stamps a new hold release of
        2026-05-11; the sweep on 2026-05-11 releases it and the decision lands ACCEPTED.

        Design: Difficulty/non_linear_state_machine/certificate_deposit_reject_resubmit_cycle
        """
        _account, rejected, _hold_release = self._setup_rejected_deposit()
        resp = api_client.resubmit_deposit(
            rejected["id"], {"note": "new medallion stamp"}, TEST_USERS["ops_headers"]
        )
        validate_success(resp)
        advance_deposit(rejected["id"])
        second_hold = advance_deposit(rejected["id"])
        assert second_hold["status"] == "CLEARANCE_HOLD"
        assert second_hold["hold_release_date"] == "2026-05-11", (
            f"re-entry at 2026-05-06 with a 5-day hold must release 2026-05-11, "
            f"got {second_hold['hold_release_date']}"
        )
        set_clock("2026-05-11T00:00:00Z")
        run_daily_sweep()
        ready = get_deposit(rejected["id"])
        assert ready["status"] == "READY_TO_ACCEPT"
        resp = api_client.decide_deposit(
            ready["id"],
            {"expected_deposit_version": ready["version"], "outcome": "ACCEPT"},
            TEST_USERS["officer_headers"],
        )
        accepted = validate_success(resp)
        assert accepted["status"] == "ACCEPTED"
