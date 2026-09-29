"""Requests that violate two rules at once and must report only the higher one.

Each scenario is paired with a control request that isolates the outranked rule,
so a passing pair proves the lower-priority rule is live and was suppressed by the
ordering rather than absent from the implementation.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.factories import patient_record_payload
from test_helpers.fixtures import HieHarness
from test_helpers.test_users import make_clinician_headers, make_privacy_officer_headers

UNRESPONSIVE_JUSTIFICATION = (
    "Unresponsive patient with no identification; medication reconciliation "
    "required before intubation."
)


class TestSuspendedCallerOutranksClosedEmergencySession:
    """A SUSPENDED querier and a CLOSED cited session: the caller state wins."""

    RECORD = patient_record_payload(
        source_mrn="H-7001",
        given_name="Theodore",
        family_name="Baptiste",
        birth_date="1948-11-05",
        sex="M",
        ssn_last4="8802",
        postal_code="70112",
        phone_digits="5045550188",
    )
    DEMOGRAPHICS = {
        "family_name": "Baptiste",
        "given_name": "Theodore",
        "birth_date": "1948-11-05",
        "sex": "M",
        "ssn_last4": "8802",
        "postal_code": "70112",
        "phone_digits": "5045550188",
    }
    EMERGENCY_CLINICIAN = "clin-h-1"

    def _suspended_participant_with_closed_session(self, hie: HieHarness):
        """A hospital certified, given one clustered patient, then suspended."""
        hie.activate_consent_policy(
            policy_version="SP-2026.5", effective_from="2026-01-01T00:00:00Z"
        )
        hie.activate_threshold_config(
            headers=make_privacy_officer_headers("privacy-tuner-1"),
            config_label="REF-PROB-H",
            score_variant_mode="PROBABILISTIC_ONLY",
        )
        participant = hie.certified_participant(
            legal_name="Halcyon Bay Medical Center",
            org_type="HOSPITAL",
            declared_annual_patient_volume=144000,
            primary_contact_email="hie@halcyonbay.example",
        )
        record = hie.contribute_record(participant["id"], headers=hie.admin, **self.RECORD)
        session = hie.open_break_glass(
            record["cluster_id"],
            participant["id"],
            emergency_category="UNCONSCIOUS_PATIENT",
            justification_text=UNRESPONSIVE_JUSTIFICATION,
            clinician_user_id=self.EMERGENCY_CLINICIAN,
        )
        closed = validate_success(
            hie.client.close_break_glass_access(
                make_clinician_headers(self.EMERGENCY_CLINICIAN), session["id"]
            ),
            200,
        )
        assert closed["session_status"] == "CLOSED"
        suspended = hie.suspend_participant(
            participant["id"], reason="Unresolved privacy audit findings"
        )
        assert suspended["onboarding_status"] == "SUSPENDED"
        return participant, record, session

    def test_uncertified_querier_reports_only_the_participant_state_violation(
        self, hie: HieHarness
    ):
        """Three gates are violated at once and only the priority-12 one is reported.

        PRD 2.9: "When a single request violates more than one rule, the response
        reports the violation with the lowest precedence number in the ordering
        below."

        PRD 3.7: "The querying participant must be `CERTIFIED`, failing which the
        query is refused with `ERR_PARTICIPANT_NOT_CERTIFIED`."

        Design: Difficulty/priority_pair_validation_conflict/suspended_participant_citing_closed_session_returns_not_certified_not_session_error
        """
        participant, _record, session = self._suspended_participant_with_closed_session(hie)

        response = hie.client.submit_record_locator_query(
            make_clinician_headers(self.EMERGENCY_CLINICIAN),
            querying_participant_id=participant["id"],
            purpose_of_use="TREATMENT",
            break_glass_id=session["id"],
            **self.DEMOGRAPHICS,
        )
        validate_error(response, "ERR_PARTICIPANT_NOT_CERTIFIED", 409)

        body = response.json()
        serialized = str(body)
        assert "ERR_BREAK_GLASS_SESSION_NOT_OPEN" not in serialized
        assert "ERR_QUERY_FEED_NOT_OPERATIONAL" not in serialized

        assert (
            validate_success(
                hie.client.list_record_locator_queries(hie.privacy_officer, limit=100), 200
            )
            == []
        )
        assert (
            validate_success(
                hie.client.list_access_audit_entries(hie.privacy_officer, limit=100), 200
            )
            == []
        )

    def test_certified_querier_citing_the_same_closed_session_reports_the_session_violation(
        self, hie: HieHarness
    ):
        """The outranked rule fires on its own once the caller state is clean.

        PRD 3.7: "A cited session that fails any of these — not open, expired,
        covering a different cluster, or belonging to a different clinician —
        causes the query to be rejected with `ERR_BREAK_GLASS_SESSION_NOT_OPEN`
        rather than silently ignored."

        Design: Difficulty/priority_pair_validation_conflict/suspended_participant_citing_closed_session_returns_not_certified_not_session_error
        """
        _participant, _record, session = self._suspended_participant_with_closed_session(hie)

        control = hie.certified_participant(
            legal_name="Juniper Ridge Hospital",
            org_type="HOSPITAL",
            primary_contact_email="hie@juniperridge.example",
        )
        hie.operational_feed(control["id"], feed_type="CCDA")

        response = hie.client.submit_record_locator_query(
            make_clinician_headers(self.EMERGENCY_CLINICIAN),
            querying_participant_id=control["id"],
            purpose_of_use="TREATMENT",
            break_glass_id=session["id"],
            **self.DEMOGRAPHICS,
        )
        validate_error(response, "ERR_BREAK_GLASS_SESSION_NOT_OPEN", 409)


class TestConformanceGateOutranksDelinquentFee:
    """A waived publisher run and an unpaid invoice: the conformance gate wins."""

    WAIVER_REASON = (
        "Vendor patch scheduled for the next release train; publisher gap accepted "
        "by the governance committee."
    )

    def _certified_on_a_waived_publisher_run(self, hie: HieHarness):
        """Certification earned with ADT_PUBLISHER waived rather than passed."""
        participant = hie.participant_in_conformance_testing(
            legal_name="Kestrel Valley Clinic Network",
            org_type="CLINIC",
            declared_annual_patient_volume=120000,
            primary_contact_email="hie@kestrelvalley.example",
        )
        failed = hie.fail_profile(
            participant["id"],
            "ADT_PUBLISHER",
            assertions_total=200,
            assertions_passed=189,
            failure_categories=["VOCABULARY"],
        )
        assert failed["pass_rate"] == 0.9450
        assert failed["status"] == "FAILED"
        waived = validate_success(
            hie.client.waive_conformance_test(
                hie.admin, failed["id"], waiver_reason=self.WAIVER_REASON
            ),
            200,
        )
        assert waived["status"] == "WAIVED"

        hie.pass_profile(participant["id"], "DOCUMENT_SOURCE")
        hie.pass_profile(participant["id"], "QUERY_RESPONDER")
        certified = validate_success(
            hie.client.transition_onboarding(
                hie.certifier, participant["id"], action="CERTIFY"
            ),
            200,
        )
        assert certified["onboarding_status"] == "CERTIFIED"
        return certified

    def test_missing_passed_publisher_run_reports_the_conformance_gate_not_the_fee(
        self, hie: HieHarness
    ):
        """A delinquent invoice is present too, and its 402 must stay suppressed.

        PRD 3.9: "Driving `PENDING_ACTIVATION → ACTIVE` requires the subscriber
        participant to hold a conformance run whose `profile` is `ADT_PUBLISHER`
        and whose `status` is **strictly** `PASSED`; a `WAIVED` run satisfies
        certification but does not satisfy this gate, and its absence is refused
        with `ERR_SUBSCRIPTION_CONFORMANCE_MISSING`."

        PRD 2.9: "When a single request violates more than one rule, the response
        reports the violation with the lowest precedence number in the ordering
        below."

        Design: Difficulty/priority_pair_validation_conflict/delinquent_invoice_and_waived_adt_publisher_returns_conformance_error_not_fee_error
        """
        participant = self._certified_on_a_waived_publisher_run(hie)

        invoice = hie.issue_invoice(
            participant["id"],
            billing_period_start="2026-06-01T00:00:00Z",
            billing_period_end="2026-07-01T00:00:00Z",
            basis_variant="PROVISIONAL",
            due_date="2026-07-15T00:00:00Z",
        )
        assert invoice["total_cents"] == 267500
        delinquent = validate_success(
            hie.client.administer_participation_invoice(
                hie.admin,
                invoice["id"],
                action="DECLARE_DELINQUENT",
                reason="Unpaid 15 days past due",
            ),
            200,
        )
        assert delinquent["status"] == "DELINQUENT"

        subscription = hie.create_subscription(
            participant["id"],
            subscription_scope="PATIENT_PANEL",
            event_types=["ADMISSION", "DISCHARGE", "TRANSFER"],
            delivery_endpoint_url="https://kestrelvalley.example/adt/inbound",
        )
        assert subscription["status"] == "PENDING_ACTIVATION"

        response = hie.client.transition_subscription_lifecycle(
            hie.admin, subscription["id"], action="ACTIVATE"
        )
        validate_error(response, "ERR_SUBSCRIPTION_CONFORMANCE_MISSING", 409)
        assert response.status_code != 402
        assert "ERR_PARTICIPATION_FEE_DELINQUENT" not in str(response.json())

        unchanged = validate_success(
            hie.client.get_notification_subscription(hie.admin, subscription["id"]), 200
        )
        assert unchanged["status"] == "PENDING_ACTIVATION"
        assert hie.get_participant(participant["id"])["active_subscription_count"] == 0

    def test_delinquent_invoice_alone_blocks_activation_with_the_fee_error(
        self, hie: HieHarness
    ):
        """With a genuinely PASSED publisher run, the outranked fee rule fires.

        PRD 3.9: "Activation additionally requires that the subscriber hold no
        `DELINQUENT` invoice (`ERR_PARTICIPATION_FEE_DELINQUENT` otherwise) and
        that its `onboarding_status` be `CERTIFIED`
        (`ERR_PARTICIPANT_NOT_CERTIFIED` otherwise)."

        Design: Difficulty/priority_pair_validation_conflict/delinquent_invoice_and_waived_adt_publisher_returns_conformance_error_not_fee_error
        """
        participant = hie.certified_participant(
            legal_name="Kestrel Valley Clinic Network",
            org_type="CLINIC",
            declared_annual_patient_volume=120000,
            primary_contact_email="hie@kestrelvalley.example",
        )
        invoice = hie.issue_invoice(
            participant["id"],
            billing_period_start="2026-06-01T00:00:00Z",
            billing_period_end="2026-07-01T00:00:00Z",
            basis_variant="PROVISIONAL",
            due_date="2026-07-15T00:00:00Z",
        )
        validate_success(
            hie.client.administer_participation_invoice(
                hie.admin,
                invoice["id"],
                action="DECLARE_DELINQUENT",
                reason="Unpaid 15 days past due",
            ),
            200,
        )
        subscription = hie.create_subscription(
            participant["id"],
            subscription_scope="PATIENT_PANEL",
            delivery_endpoint_url="https://kestrelvalley.example/adt/inbound",
        )

        validate_error(
            hie.client.transition_subscription_lifecycle(
                hie.admin, subscription["id"], action="ACTIVATE"
            ),
            "ERR_PARTICIPATION_FEE_DELINQUENT",
            402,
        )
        assert hie.get_participant(participant["id"])["active_subscription_count"] == 0
