"""Cancellation cascades: depth-3 agreement cascade, conditional terminal
cohort skip, parallel billing dimension."""
from test_helpers import (
    validate_success,
    get_success_data,
    ApiErrorId,
    create_employer,
    create_approved_assessment,
    create_signed_agreement,
    create_venue_for_mode,
    create_cohort_under,
    create_session_on,
    create_instructor,
    propose_and_confirm,
    enroll_participants,
    setup_credentialed_cohort,
    api_client,
    TEST_USERS,
    validate_error,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["admin_headers"]
CRED = TEST_USERS["credential_officer_headers"]


class TestAgreementCancelCascadeDepth3:
    def _fixture(self, api):
        emp = create_employer(legal_name="Iota Inc", industry_code="811310",
                              contact_email="hr@iota.example")
        na = create_approved_assessment(emp["id"])
        agr = create_signed_agreement(emp["id"], na["id"], pricing_model="FLAT_COHORT",
                                      est_participant_count=3, est_delivery_hours=4)
        ven = create_venue_for_mode("ON_SITE", name="Iota Shop", capacity=8)
        coh = create_cohort_under(agr["id"], min_enrollment=1,
                                  start_date="2026-06-15T00:00:00Z",
                                  end_date="2026-06-16T00:00:00Z", venue_id=ven["id"])
        s1 = create_session_on(coh["id"], ven["id"],
                               "2026-06-15T09:00:00Z", "2026-06-15T11:00:00Z")
        s2 = create_session_on(coh["id"], ven["id"],
                               "2026-06-16T09:00:00Z", "2026-06-16T11:00:00Z")
        ins = create_instructor(full_name="Dee Instructor")
        asg1 = propose_and_confirm(s1["id"], ins["id"])
        asg2 = propose_and_confirm(s2["id"], ins["id"])
        enroll_participants(coh["id"], ["I01"])  # launchable but left SCHEDULED
        return agr, coh, (s1, s2), (asg1, asg2), ins

    def test_cascade_reaches_sessions_assignments_and_hours(self, api):
        """PRD §3.9: "Cancelling from `SIGNED` fires the full cascade: every
        child cohort in `SCHEDULED`, `LAUNCHED`, or `IN_PROGRESS` moves to
        `CANCELLED` (link 1); each such cohort cancellation moves its
        `PLANNED` sessions to `CANCELLED` (link 2); each such session
        cancellation moves its assignments in `PROPOSED` or `CONFIRMED` to
        `RELEASED`, decrementing the instructor's `committed_hours` by the
        session's `hours` for the `CONFIRMED` ones (link 3)".

        Design: Difficulty/transitive_cascade/agreement_cancel_cascade_depth3
        """
        agr, coh, (s1, s2), (asg1, asg2), ins = self._fixture(api)
        before = get_success_data(api_client.get_instructor(ins["id"], COORD))
        assert before["committed_hours"] == 4

        cancelled = validate_success(api_client.cancel_training_agreement(agr["id"], COORD))
        assert cancelled["contract_status"] == "CANCELLED"

        coh_after = get_success_data(api_client.get_cohort(coh["id"], COORD))
        assert coh_after["delivery_status"] == "CANCELLED"
        for sid in (s1["id"], s2["id"]):
            s = get_success_data(api_client.get_session(sid, COORD))
            assert s["status"] == "CANCELLED"
        for aid in (asg1["id"], asg2["id"]):
            a = get_success_data(api_client.get_instructor_assignment(aid, COORD))
            assert a["status"] == "RELEASED"
        ins_after = get_success_data(api_client.get_instructor(ins["id"], COORD))
        assert ins_after["committed_hours"] == 0

    def test_each_cascade_link_observed_independently(self, api):
        """PRD §3.9: "Cancelling from `SIGNED` fires the full cascade: every
        child cohort in `SCHEDULED`, `LAUNCHED`, or `IN_PROGRESS` moves to
        `CANCELLED` (link 1); each such cohort cancellation moves its
        `PLANNED` sessions to `CANCELLED` (link 2)" — the cascade is
        transitive: agreement to cohort to session to assignment.

        Design: Difficulty/transitive_cascade/agreement_cancel_cascade_depth3
        """
        agr, coh, (s1, s2), (asg1, asg2), ins = self._fixture(api)
        validate_success(api_client.cancel_training_agreement(agr["id"], COORD))
        # link 1: cohort
        assert get_success_data(api_client.get_cohort(coh["id"], COORD))["delivery_status"] == "CANCELLED"
        # link 2: sessions
        assert get_success_data(api_client.get_session(s1["id"], COORD))["status"] == "CANCELLED"
        # link 3: assignments + hours decrement
        assert get_success_data(api_client.get_instructor_assignment(asg2["id"], COORD))["status"] == "RELEASED"
        assert get_success_data(api_client.get_instructor(ins["id"], COORD))["committed_hours"] == 0


class TestCancelCascadeSkipsTerminalCohort:
    def test_credentialed_cohort_untouched_by_agreement_cancel(self, api):
        """PRD §3.9: "Cancelling from `IN_DELIVERY` fires the same chain with
        two carve-outs: `CREDENTIALED` cohorts are terminal and untouched, and
        `HELD` sessions are likewise left in place."

        Design: Corner/state_machines/cancel_cascade_skips_terminal_cohort
        """
        # C1: fully CREDENTIALED via the composite fixture
        ctx1 = setup_credentialed_cohort(num_participants=1, min_enrollment=1,
                                         agreement_overrides={
                                             "pricing_model": "FLAT_COHORT",
                                             "est_participant_count": 2,
                                             "est_delivery_hours": 4,
                                             "max_cohorts": 3},
                                         participant_prefix="CC1_")
        agr = ctx1["agreement"]
        emp = ctx1["employer"]
        ven = ctx1["venue"]
        ins = ctx1["instructor"]

        # C2: SCHEDULED with session + confirmed assignment + participant
        c2 = create_cohort_under(agr["id"], min_enrollment=1,
                                 start_date="2026-06-22T00:00:00Z",
                                 end_date="2026-06-22T00:00:00Z", venue_id=ven["id"])
        s2 = create_session_on(c2["id"], ven["id"],
                               "2026-06-22T09:00:00Z", "2026-06-22T11:00:00Z")
        propose_and_confirm(s2["id"], ins["id"])
        enroll_participants(c2["id"], ["CC2"])

        cancelled = validate_success(api_client.cancel_training_agreement(agr["id"], ADMIN))
        assert cancelled["contract_status"] == "CANCELLED"
        c1_after = get_success_data(api_client.get_cohort(ctx1["cohort"]["id"], ADMIN))
        c2_after = get_success_data(api_client.get_cohort(c2["id"], ADMIN))
        assert c1_after["delivery_status"] == "CREDENTIALED"
        assert c2_after["delivery_status"] == "CANCELLED"


class TestParallelDeliveryAndBillingDimensions:
    def test_delivery_and_billing_evolve_independently(self, api):
        """PRD §2.11: "A cohort's `delivery_status` walks `SCHEDULED`,
        `LAUNCHED`, `IN_PROGRESS`, `DELIVERED`, and the terminal
        `CREDENTIALED` or `CANCELLED`, while its `billing_status` walks
        `UNBILLED`, `INVOICED`, and `PAID`, again independently."

        Design: Difficulty/non_linear_state_machine/cohort_parallel_delivery_and_billing_dimensions
        """
        from test_helpers import setup_launched_cohort, close_session_attendance
        ctx = setup_launched_cohort(
            num_participants=1, min_enrollment=1,
            sessions=[("2026-06-15T09:00:00Z", "2026-06-15T11:00:00Z"),
                      ("2026-06-16T09:00:00Z", "2026-06-16T11:00:00Z")],
            agreement_overrides={"pricing_model": "FLAT_COHORT",
                                 "est_participant_count": 4,
                                 "est_delivery_hours": 4},
            participant_prefix="T",
        )
        ins = ctx["instructor"]["id"]
        coh_id = ctx["cohort"]["id"]
        close_session_attendance(ctx["session_ids"][0], ins,
                                 [{"external_employee_ref": "T01", "attended_hours": 2}])
        mid = get_success_data(api_client.get_cohort(coh_id, COORD))
        assert mid["delivery_status"] == "IN_PROGRESS"
        assert mid["billing_status"] == "UNBILLED"

        close_session_attendance(ctx["session_ids"][1], ins,
                                 [{"external_employee_ref": "T01", "attended_hours": 2}])
        end = get_success_data(api_client.get_cohort(coh_id, COORD))
        assert end["delivery_status"] == "DELIVERED"
        assert end["billing_status"] == "UNBILLED"

        inv = validate_success(api_client.create_invoice(coh_id, {"variant": "FINAL"},
                                                         TEST_USERS["billing_clerk_headers"]), 201)
        validate_success(api_client.issue_invoice(inv["id"], TEST_USERS["billing_clerk_headers"]))
        after = get_success_data(api_client.get_cohort(coh_id, COORD))
        assert after["billing_status"] == "INVOICED"
        assert after["delivery_status"] == "DELIVERED"

    def test_billing_advances_to_paid_without_touching_delivery(self, api):
        """PRD §2.11: "A cohort's `delivery_status` walks `SCHEDULED`,
        `LAUNCHED`, `IN_PROGRESS`, `DELIVERED`, and the terminal
        `CREDENTIALED` or `CANCELLED`, while its `billing_status` walks
        `UNBILLED`, `INVOICED`, and `PAID`, again independently."
        PRD §3.7: marking paid "moves the invoice to `PAID`, the cohort's
        `billing_status` to `PAID`".

        Design: Difficulty/non_linear_state_machine/cohort_parallel_delivery_and_billing_dimensions
        """
        from test_helpers import setup_delivered_cohort
        ctx = setup_delivered_cohort(num_participants=1, min_enrollment=1)
        coh_id = ctx["cohort"]["id"]
        bill = TEST_USERS["billing_clerk_headers"]
        inv = validate_success(api_client.create_invoice(coh_id, {"variant": "FINAL"}, bill), 201)
        validate_success(api_client.issue_invoice(inv["id"], bill))
        validate_success(api_client.mark_paid_invoice(inv["id"], bill))
        after = get_success_data(api_client.get_cohort(coh_id, COORD))
        assert after["billing_status"] == "PAID"
        assert after["delivery_status"] == "DELIVERED"
