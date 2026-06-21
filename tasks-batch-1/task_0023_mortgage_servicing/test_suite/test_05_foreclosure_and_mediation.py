"""Foreclosure filing, OCC, mediation, sale-scheduling, withdraw, mediation
notice boundary, modification outcome."""
from test_helpers import (
    ApiErrorId,
    validate_success,
    validate_error,
    set_clock,
    create_mediation_session_payload,
    record_outcome_payload,
    fetch_loan,
    fetch_foreclosure_case,
    fetch_mediation_session,
    make_loan_servicer_headers,
    setup_borrower_loan_escrow,
    setup_foreclosure_filed,
    setup_case_in_mediation,
)


class TestForeclosureOCC:

    def test_foreclosure_filing_with_stale_version_rejected(self, api):
        """PRD §2.8: "A request to file foreclosure must carry the field
        expected_loan_version, an integer equal to the client's last
        observed version of the target loan. If another writer has advanced
        the loan's version since the client last read it — for example, by
        posting a payment that legitimately cured the delinquency — the
        create is rejected with ERR_STALE_VERSION and HTTP 412."

        Design: Corner/errors/err_stale_version_on_foreclosure_filing
        """
        set_clock("2025-06-01T00:00:00Z")
        ctx = setup_borrower_loan_escrow(
            clock_iso="2025-06-01T00:00:00Z",
            origination_date="2025-06-01T00:00:00Z",
            original_principal_cents=30000000,
            original_property_value_cents=35000000,
            interest_rate_bps=600,
            term_months=360,
            pmi_monthly_cents=12500,
        )
        set_clock("2025-11-01T00:00:00Z")
        loan_before = fetch_loan(ctx["loan"]["id"])
        observed_version = loan_before["version"]
        # Post a payment to advance the loan's version.
        validate_success(api.post_payment(
            ctx["loan"]["id"],
            {"amount_cents": 50000, "received_at": "2025-11-01T00:00:00Z"},
            make_loan_servicer_headers(),
        ), expected_status=201)
        # Now file foreclosure with the stale version.
        resp = api.file_foreclosure(
            ctx["loan"]["id"], observed_version,
            make_loan_servicer_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestForeclosureWithdraw:

    def test_withdraw_after_filing_preserves_principal_balance(self, api):
        """PRD §3.5: "A case may be withdrawn at any non-terminal stage of
        the mediation/sale pipeline — specifically while the case is in any
        of MEDIATION_REQUIRED, IN_MEDIATION, MEDIATION_FAILED, or
        SALE_SCHEDULED — moving the case to WITHDRAWN and the loan back to
        REINSTATED."

        Design: Difficulty/compensating_invariant/invariant_payment_then_reversal_preserves_principal_balance
        """
        ctx = setup_foreclosure_filed(
            clock_iso="2025-06-01T00:00:00Z",
            after_120_days_iso="2025-11-01T00:00:00Z",
            origination_date="2025-06-01T00:00:00Z",
            original_principal_cents=30000000,
            original_property_value_cents=35000000,
            interest_rate_bps=600,
            term_months=360,
            pmi_monthly_cents=12500,
        )
        balance_before = fetch_loan(ctx["loan"]["id"])["principal_balance_cents"]
        validate_success(api.withdraw_foreclosure(
            ctx["foreclosure_case"]["id"], make_loan_servicer_headers(),
        ))
        loan_after = fetch_loan(ctx["loan"]["id"])
        # Withdraw is a status change only — principal is unchanged because
        # no payment posted between file and withdraw.
        assert loan_after["principal_balance_cents"] == balance_before
        assert loan_after["principal_balance_cents"] == 30000000
        assert loan_after["status"] == "REINSTATED"


class TestMediationNotice:

    def test_mediation_scheduled_for_exactly_14_days_accepted(self, api):
        """PRD §3.5: "Mediation must be noticed at least fourteen days
        ahead: the scheduled_for must be at or after the simulated current
        UTC time plus fourteen days, and a violation is rejected with
        ERR_NOTICE_PERIOD_VIOLATED. Scheduling moves the case into
        IN_MEDIATION and creates a MediationSession row whose outcome is
        initialized to PENDING and whose foreclosure_case_id ties it to
        the case."

        Design: Difficulty/boundary_precision_check/boundary_mediation_notice_exactly_14_days_allowed
        """
        ctx = setup_foreclosure_filed(
            clock_iso="2025-06-01T00:00:00Z",
            after_120_days_iso="2025-11-01T00:00:00Z",
            origination_date="2025-06-01T00:00:00Z",
            original_principal_cents=30000000,
            original_property_value_cents=35000000,
            interest_rate_bps=600,
            term_months=360,
            pmi_monthly_cents=12500,
        )
        set_clock("2025-11-01T00:00:00Z")
        # Exactly +14 days.
        resp = api.schedule_mediation_session(
            ctx["foreclosure_case"]["id"],
            create_mediation_session_payload(
                scheduled_for="2025-11-15T00:00:00Z",
            ),
            make_loan_servicer_headers(),
        )
        session = validate_success(resp, expected_status=201)
        assert session["outcome"] == "PENDING"
        # PRD §2.4 mandates 3-fractional-digit ISO timestamps server-side.
        # The input "...:00Z" may be canonicalized to "...:00.000Z" on read.
        from datetime import datetime, timezone
        def _parse_iso(s: str) -> datetime:
            s = s.replace("Z", "+00:00")
            return datetime.fromisoformat(s).astimezone(timezone.utc)
        assert _parse_iso(session["scheduled_for"]) == _parse_iso(
            "2025-11-15T00:00:00Z"
        )
        case_after = fetch_foreclosure_case(ctx["foreclosure_case"]["id"])
        assert case_after["status"] == "IN_MEDIATION"

    def test_mediation_scheduled_for_13_days_rejected(self, api):
        """PRD §3.5: "Mediation must be noticed at least fourteen days
        ahead: the scheduled_for must be at or after the simulated current
        UTC time plus fourteen days, and a violation is rejected with
        ERR_NOTICE_PERIOD_VIOLATED."

        Design: Corner/validations/validation_mediation_notice_too_short
        """
        ctx = setup_foreclosure_filed(
            clock_iso="2025-06-01T00:00:00Z",
            after_120_days_iso="2025-11-01T00:00:00Z",
            origination_date="2025-06-01T00:00:00Z",
            original_principal_cents=30000000,
            original_property_value_cents=35000000,
            interest_rate_bps=600,
            term_months=360,
            pmi_monthly_cents=12500,
        )
        set_clock("2025-11-01T00:00:00Z")
        resp = api.schedule_mediation_session(
            ctx["foreclosure_case"]["id"],
            create_mediation_session_payload(
                scheduled_for="2025-11-14T00:00:00Z",
            ),
            make_loan_servicer_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_NOTICE_PERIOD_VIOLATED)


class TestMediationOutcome:

    def test_modification_agreed_completes_case_and_reinstates_loan(self, api):
        """PRD §3.5: "When the outcome is MODIFICATION_AGREED, the case
        transitions to COMPLETED, the loan's scheduled_monthly_pi_cents is
        replaced by the supplied modification_pi_cents (which is required
        in this branch), and the loan transitions to REINSTATED."

        Design: Difficulty/non_linear_state_machine/non_linear_foreclosure_branching_mediation_outcome
        """
        ctx = setup_case_in_mediation(
            clock_iso="2025-06-01T00:00:00Z",
            after_120_days_iso="2025-11-01T00:00:00Z",
            mediation_clock_iso="2025-11-01T00:00:00Z",
            mediation_scheduled_for="2025-11-15T00:00:00Z",
            origination_date="2025-06-01T00:00:00Z",
            original_principal_cents=30000000,
            original_property_value_cents=35000000,
            interest_rate_bps=600,
            term_months=360,
            pmi_monthly_cents=12500,
        )
        resp = api.record_mediation_outcome(
            ctx["mediation_session"]["id"],
            record_outcome_payload(
                outcome="MODIFICATION_AGREED",
                modification_pi_cents=150000,
            ),
            make_loan_servicer_headers(),
        )
        session_after = validate_success(resp)
        assert session_after["outcome"] == "MODIFICATION_AGREED"
        case_after = fetch_foreclosure_case(ctx["foreclosure_case"]["id"])
        assert case_after["status"] == "COMPLETED"
        loan_after = fetch_loan(ctx["loan"]["id"])
        assert loan_after["status"] == "REINSTATED"
        assert loan_after["scheduled_monthly_pi_cents"] == 150000
