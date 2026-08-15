"""Attestation lifecycle, sweep-driven overdue flips, and eligibility gates."""
from test_helpers import (
    ApiErrorId,
    admin_headers,
    api_client,
    as_insider,
    as_officer,
    assert_same_instant,
    complete_attestation_for,
    create_attestation_payload,
    create_officer,
    create_person,
    create_preclearance_request_payload,
    get_person,
    get_success_data,
    run_sweep,
    set_logical_clock,
    validate_error,
    validate_success,
)


class TestLateCompletion:
    def test_overdue_attestation_completes_late_and_restores_currency(self, api):
        """PRD §2.10: "`ASSIGNED` attestations whose `due_date` has passed move to
        `OVERDUE`, and each affected person's training currency is recomputed."
        PRD §3.1: "Completion is accepted from `ASSIGNED` and also from `OVERDUE`:
        late completion is allowed and restores currency."

        Design: Corner/state_machines/attestation_late_completion_from_overdue
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        person = create_person("Late Learner", "late@x.com")
        officer = create_officer("officer_s4@x.com")
        att = get_success_data(
            api.create_attestation(
                create_attestation_payload(
                    covered_person_id=person["id"],
                    kind="ANNUAL_TRAINING",
                    period_year=2026,
                    due_date="2026-08-02T00:00:00Z",
                ),
                admin_headers(),
            ),
            expected_status=201,
        )
        set_logical_clock("2026-08-03T00:00:00Z")
        run_sweep(officer)
        overdue = get_success_data(api.get_attestation(att["id"], admin_headers()))
        assert overdue["status"] == "OVERDUE", "sweep past due_date must flip ASSIGNED to OVERDUE"

        completed = validate_success(
            api.complete_attestation(att["id"], as_insider(person))
        )
        assert completed["status"] == "COMPLETED"
        assert_same_instant(completed["completed_at"], "2026-08-03T00:00:00Z", "completed_at")
        assert get_person(person["id"])["training_current"] is True


class TestSweepOverdueFiltering:
    def test_sweep_flips_only_past_due_attestations(self, api):
        """PRD §2.10: "`ASSIGNED` attestations whose `due_date` has passed move to
        `OVERDUE`, and each affected person's training currency is recomputed."
        PRD §2.10: "The sweep response reports how much work it did, as counts:
        `windows_activated`, `windows_lifted`, `approvals_expired`, `approvals_voided`,
        `exceptions_expired`, `plans_activated`, `attestations_overdue`,
        `persons_reinstated`, and `confirmations_remanaged`."

        Design: Corner/calculations/sweep_overdue_filtering_by_due_date
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        p1 = create_person("P One", "p1@x.com", department="A")
        p2 = create_person("P Two", "p2@x.com", department="B")
        officer = create_officer("officer_c3@x.com")
        att1 = get_success_data(
            api.create_attestation(
                create_attestation_payload(
                    covered_person_id=p1["id"], kind="ANNUAL_TRAINING",
                    period_year=2026, due_date="2026-08-02T00:00:00Z",
                ),
                admin_headers(),
            ),
            expected_status=201,
        )
        att2 = get_success_data(
            api.create_attestation(
                create_attestation_payload(
                    covered_person_id=p2["id"], kind="ANNUAL_TRAINING",
                    period_year=2026, due_date="2026-12-31T00:00:00Z",
                ),
                admin_headers(),
            ),
            expected_status=201,
        )
        set_logical_clock("2026-08-03T00:00:00Z")
        counts = run_sweep(officer)
        assert counts["attestations_overdue"] == 1

        assert get_success_data(api.get_attestation(att1["id"], admin_headers()))["status"] == "OVERDUE"
        assert get_success_data(api.get_attestation(att2["id"], admin_headers()))["status"] == "ASSIGNED"
        assert get_person(p1["id"])["training_current"] is False


class TestEligibilityGates:
    def test_request_without_policy_ack_rejected(self, api):
        """PRD §3.1: "Submitting a preclearance request and creating a 10b5-1 plan
        both require the subject to be free of a compliance hold
        (`ERR_COMPLIANCE_HOLD`, 422), to hold a current policy acknowledgment
        (`ERR_POLICY_ACK_REQUIRED`, 422), and to hold current training
        (`ERR_TRAINING_OVERDUE`, 422) — evaluated in that order, so a person missing
        both currency flags always sees the policy-acknowledgment error first."

        Design: Corner/validations/create_request_without_policy_ack_returns_policy_error
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        person = create_person("No Ack", "noack@x.com")
        complete_attestation_for(person, "ANNUAL_TRAINING")

        resp = api.create_preclearance_request(
            create_preclearance_request_payload(
                covered_person_id=person["id"],
                security_ticker="ACME",
                trade_side="BUY",
                quantity=10,
                proposed_trade_date="2026-08-20T00:00:00Z",
            ),
            as_insider(person),
        )
        validate_error(resp, ApiErrorId.ERR_POLICY_ACK_REQUIRED)

    def test_request_with_training_overdue_rejected(self, api):
        """PRD §2.9: "policy acknowledgment is checked before training currency: a
        person whose `policy_ack_current` is false draws `ERR_POLICY_ACK_REQUIRED`
        (422); a person whose acknowledgment is current but whose `training_current`
        is false draws `ERR_TRAINING_OVERDUE` (422)."

        Design: Corner/validations/create_request_with_training_overdue_returns_training_error
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        person = create_person("Overdue T", "overdue@x.com")
        officer = create_officer("officer_v1@x.com")
        complete_attestation_for(person, "POLICY_ACK")
        get_success_data(
            api.create_attestation(
                create_attestation_payload(
                    covered_person_id=person["id"], kind="ANNUAL_TRAINING",
                    period_year=2026, due_date="2026-08-02T00:00:00Z",
                ),
                admin_headers(),
            ),
            expected_status=201,
        )
        set_logical_clock("2026-08-03T00:00:00Z")
        run_sweep(officer)
        assert get_person(person["id"])["policy_ack_current"] is True
        assert get_person(person["id"])["training_current"] is False

        resp = api.create_preclearance_request(
            create_preclearance_request_payload(
                covered_person_id=person["id"],
                security_ticker="ACME",
                trade_side="BUY",
                quantity=10,
                proposed_trade_date="2026-08-20T00:00:00Z",
            ),
            as_insider(person),
        )
        validate_error(resp, ApiErrorId.ERR_TRAINING_OVERDUE)
