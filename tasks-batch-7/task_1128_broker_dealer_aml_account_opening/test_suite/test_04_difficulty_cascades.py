"""Difficulty queue: transitive cascades (314(a) confirm depth-4, suspicious cert depth-3)."""
import pytest

from test_helpers import (
    TEST_USERS,
    advance_deposit,
    api_client,
    approve_account,
    create_account,
    create_customer,
    create_deposit,
    create_fincen_request,
    create_rep,
    get_account,
    get_deposit,
    list_alerts_for_account,
    list_matches_for_request,
    post_wire,
    run_daily_sweep,
    scan_fincen_request,
    set_clock,
    submit_and_verify_document,
    validate_success,
)


class TestMatch314AConfirmDepth4Cascade:
    def _setup_pending_match(self):
        """HIGH+PEP customer with [LPS, MARGIN] -> INITIAL score 65 MEDIUM; one POSTED
        wire of 1000.00; 314(a) request scanned -> one PENDING_REVIEW match."""
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep I", crd_number="CRD-TC1")
        customer = create_customer(
            rep,
            customer_type="INDIVIDUAL",
            full_name="I Risky",
            tax_id="TIN-CASC1",
            country_risk_tier="HIGH",
            is_pep=True,
        )
        submit_and_verify_document(customer["id"], rep, document_number="P-TC1")
        account = create_account(
            customer["id"], rep, product_set=["LOW_PRICED_SECURITIES", "MARGIN"]
        )
        approve_account(account["id"])
        wire = post_wire(account["id"], rep, 1000.00)
        request = create_fincen_request(
            request_reference="FIN-2026-TC1",
            subjects=[{"name": "I Risky", "tax_id": "TIN-CASC1",
                       "subject_type": "INDIVIDUAL"}],
        )
        scanned = scan_fincen_request(request["id"])
        matches = list_matches_for_request(request["id"])
        assert len(matches) == 1, f"Setup failed: {len(matches)} matches"
        return account, wire, request, scanned, matches[0]

    def test_confirm_restricts_account_severe_and_flags_transactions(self, api):
        """PRD §3.7: "A subject matches a customer account on `TAX_ID_EXACT` when the
        subject's `tax_id` equals the customer's `tax_id`".
        PRD §3.7: "Hop one restricts the account (moving it `OPEN` → `RESTRICTED` when
        it is `OPEN`) and drives `aml_posture` to `SEVERE`. Hop two, caused by the
        restriction, flags every `POSTED` transaction of the account."

        Design: Difficulty/transitive_cascade/match314a_confirm_depth4_cascade
        """
        account, wire, _request, scanned, match = self._setup_pending_match()
        assert scanned["match_count"] == 1
        assert match["match_basis"] == "TAX_ID_EXACT"

        resp = api_client.confirm_match(match["id"], TEST_USERS["officer_headers"])
        confirmed = validate_success(resp)
        assert confirmed["status"] == "CONFIRMED"

        after = get_account(account["id"])
        assert after["lifecycle_status"] == "RESTRICTED", (
            f"hop 1 must restrict the account, got {after['lifecycle_status']}"
        )
        assert after["aml_posture"] == "SEVERE", (
            f"hop 1 must drive posture to SEVERE, got {after['aml_posture']}"
        )
        resp = api_client.get_transaction(wire["id"], TEST_USERS["officer_headers"])
        wire_after = validate_success(resp)
        assert wire_after["status"] == "FLAGGED", (
            f"hop 2 must flag the POSTED wire, got {wire_after['status']}"
        )

    def test_confirm_creates_fincen_alert_and_reruns_ongoing_recalc(self, api):
        """PRD §3.7: "Hop three, caused by the flagging, creates a `NEW` alert with
        `rule_code` `FINCEN_314A_MATCH` for each newly flagged transaction that lacks
        an open alert. Hop four, caused by the alert creation, recalculates the
        account's risk with the `ONGOING` variant, reading the alert set hop three
        produced."
        PRD §3.3: "Activity contributes 5 points per monitoring alert of the account
        currently in `UNDER_REVIEW` or `ESCALATED_TO_CASE`" — the cascade-created alert
        is `NEW`, so it contributes no activity points: the ONGOING recalc of the
        unchanged static profile (65) with a negligible velocity band keeps the score
        at 65 and the tier MEDIUM.

        Design: Difficulty/transitive_cascade/match314a_confirm_depth4_cascade
        """
        account, _wire, _request, _scanned, match = self._setup_pending_match()
        assert account["risk_score"] == 65
        assert account["risk_tier"] == "MEDIUM"

        resp = api_client.confirm_match(match["id"], TEST_USERS["officer_headers"])
        validate_success(resp)

        alerts = list_alerts_for_account(account["id"])
        assert len(alerts) == 1, f"hop 3 must create exactly one alert, got {len(alerts)}"
        assert alerts[0]["rule_code"] == "FINCEN_314A_MATCH"
        assert alerts[0]["status"] == "NEW"

        after = get_account(account["id"])
        assert after["risk_score"] == 65, (
            "hop 4 reads only UNDER_REVIEW/ESCALATED_TO_CASE alerts; the NEW cascade "
            f"alert contributes 0 activity points, so the score must stay 65 — "
            f"got {after['risk_score']}"
        )
        assert after["risk_tier"] == "MEDIUM"
        assert after["risk_variant_used"] == "ONGOING"


class TestSuspiciousCertRejectDepth3Cascade:
    def _setup_ready_deposit(self):
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep J", crd_number="CRD-TC2")
        customer = create_customer(
            rep,
            customer_type="INDIVIDUAL",
            full_name="J Low",
            tax_id="TIN-CASC2",
            country_risk_tier="LOW",
            is_pep=False,
        )
        submit_and_verify_document(customer["id"], rep, document_number="P-TC2")
        account = create_account(customer["id"], rep, product_set=["CASH"])
        approve_account(account["id"])
        deposit = create_deposit(
            account["id"],
            certificate_number="CN-TC2",
            cusip="CUSIPTC2",
            security_name="TC2 Corp",
            quantity=100,
            unit_price=40.00,
        )
        deposit = advance_deposit(deposit["id"])
        deposit = advance_deposit(deposit["id"])
        deposit = advance_deposit(deposit["id"])
        set_clock("2026-05-06T00:00:00Z")
        run_daily_sweep()
        deposit = get_deposit(deposit["id"])
        assert deposit["status"] == "READY_TO_ACCEPT", (
            f"Setup failed: deposit {deposit['status']}"
        )
        return account, deposit

    def test_reject_suspicious_reverses_linked_transaction_and_exposure(self, api):
        """PRD §3.8: "**Reject-suspicious** moves to the terminal `REJECTED_SUSPICIOUS`
        and fires a three-hop cascade: hop one reverses the linked transaction".
        PRD §3.5: "The `exposure_30d_amount` sums `amount` over all of the account's
        transactions not in `REVERSED` within the trailing thirty calendar days
        inclusive" — the 100 @ 40.00 = 4000.00 deposit counts before the decision
        (booked FLAGGED, not REVERSED) and drops out after it.

        Design: Difficulty/transitive_cascade/suspicious_cert_reject_depth3_cascade
        """
        account, deposit = self._setup_ready_deposit()
        before = get_account(account["id"])
        assert before["exposure_30d_amount"] == pytest.approx(4000.00, abs=0.01)
        assert before["aml_posture"] == "STANDARD"

        resp = api_client.decide_deposit(
            deposit["id"],
            {
                "expected_deposit_version": deposit["version"],
                "outcome": "REJECT_SUSPICIOUS",
                "reason": "counterfeit certificate paper",
            },
            TEST_USERS["officer_headers"],
        )
        decided = validate_success(resp)
        assert decided["status"] == "REJECTED_SUSPICIOUS"

        resp = api_client.get_transaction(
            deposit["transaction_id"], TEST_USERS["ops_headers"]
        )
        txn_after = validate_success(resp)
        assert txn_after["status"] == "REVERSED", (
            f"hop 1 must reverse the linked transaction, got {txn_after['status']}"
        )
        after = get_account(account["id"])
        assert after["exposure_30d_amount"] == pytest.approx(0.00, abs=0.01), (
            f"reversal must remove the deposit from exposure, "
            f"got {after['exposure_30d_amount']}"
        )

    def test_reject_suspicious_sets_flag_elevates_posture_creates_alert(self, api):
        """PRD §3.8: "hop two, caused by the reversal, sets the account's
        `has_suspicion_flag` to true and recomputes posture — which lands at `ELEVATED`
        at minimum, and the flag never auto-clears; hop three, caused by the suspicion
        flag, creates a `NEW` alert with `rule_code` `CERT_SUSPICION` whose
        `transaction_id` is the reversed transaction."

        Design: Difficulty/transitive_cascade/suspicious_cert_reject_depth3_cascade
        """
        account, deposit = self._setup_ready_deposit()
        resp = api_client.decide_deposit(
            deposit["id"],
            {
                "expected_deposit_version": deposit["version"],
                "outcome": "REJECT_SUSPICIOUS",
                "reason": "counterfeit certificate paper",
            },
            TEST_USERS["officer_headers"],
        )
        validate_success(resp)

        after = get_account(account["id"])
        assert after["has_suspicion_flag"] is True, "hop 2 must set has_suspicion_flag"
        assert after["aml_posture"] == "ELEVATED", (
            f"hop 2 must lift posture to at least ELEVATED, got {after['aml_posture']}"
        )
        alerts = list_alerts_for_account(account["id"])
        assert len(alerts) == 1, f"hop 3 must create exactly one alert, got {len(alerts)}"
        assert alerts[0]["rule_code"] == "CERT_SUSPICION"
        assert alerts[0]["status"] == "NEW"
        assert alerts[0]["transaction_id"] == deposit["transaction_id"]
