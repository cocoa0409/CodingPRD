"""State-machine claims: initial states, terminal lockdowns, invalid
transitions, and preconditions (PRD 3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_invoice_payload,
    create_payment_payload,
    create_pod_payload,
    create_progress_conference_payload,
    make_family_headers,
    validate_error,
    validate_success,
    TEST_USERS,
)
from test_helpers.fixtures import (
    create_family,
    create_issued_invoice,
    create_site,
    create_student,
    decide_all_claims,
    enroll_seat,
    get_pod,
    list_dissolution_claims,
    post_and_clear_payment,
    set_clock,
    setup_active_pod_with_enrolled_seats,
    setup_dissolved_pod,
    setup_dissolving_pod,
    setup_enrolled_seat,
    setup_family_student_seat,
    setup_pod_active,
    setup_pod_licensing_review,
    setup_pod_with_approved_policy_and_plan,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["pod_operator_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


class TestPodLifecycle:
    def test_pod_initial_state_is_draft(self, api):
        """PRD 3.1: "A new pod's `status` is `DRAFT`, its `enrolled_count`
        is a derived count of seats currently `ENROLLED`, and its
        `dissolved_at` remains null until dissolution finalizes."

        Design: Corner/state_machines/pod_initial_state_is_draft
        """
        site = create_site(site_name="IS")
        data = validate_success(
            api.create_pod(create_pod_payload(site["id"], name="IS Pod"), OPERATOR),
            expected_status=201,
        )
        assert data["status"] == "DRAFT"

    def test_pod_terminal_dissolved_lockdown(self, api):
        """PRD 3.9: "Finalization stamps `dissolved_at` with the current UTC
        instant, keeps the pod's `posture` at `CLOSED`, moves every
        `WITHDRAWN` seat to `RELEASED`, moves every family left with zero
        enrolled students to `INACTIVE`, increments the pod's `version`, and
        lands the pod in the terminal `DISSOLVED` state."

        Design: Corner/state_machines/pod_terminal_dissolved_lockdown
        """
        ctx = setup_dissolved_pod(num_seats=1)
        pod = ctx["pod"]
        assert pod["status"] == "DISSOLVED"
        resp = api.open_enrollment(pod["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestSeatLifecycle:
    def test_seat_invalid_from_transition_rejected(self, api):
        """PRD 3.6: "Withdrawal — a family moving a seat from `ENROLLED` to
        `WITHDRAWN` — is permitted while the pod is `ACTIVE` or `SUSPENDED`,
        and the payload's `withdrawn_on` date must not precede the current
        logical-clock date."

        Design: Corner/state_machines/seat_invalid_from_transition_rejected
        """
        set_clock("2026-08-15T00:00:00Z")
        pod, *_ = setup_pod_active()
        family, student, seat = setup_family_student_seat(pod)
        assert seat["seat_status"] == "RESERVED"
        resp = api.withdraw_seat(
            pod["id"], seat["id"], {"withdrawn_on": "2026-08-20"},
            make_family_headers(family["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestLicensingLifecycle:
    def test_licensing_determination_begin_review_precondition(self, api):
        """PRD 3.3: "A `ComplianceOfficer` begins review, moving the
        determination from `SUBMITTED` — or, on a resubmitted case, from
        `RESUBMITTED` — to `UNDER_REVIEW`."

        Design: Corner/state_machines/licensing_determination_begin_review_precondition
        """
        set_clock("2026-06-01T00:00:00Z")
        pod, site, policy, plan, det, guide, assignment = setup_pod_licensing_review()
        validate_success(
            api.begin_review_licensing_determination(pod["id"], det["id"], OFFICER)
        )
        resp = api.begin_review_licensing_determination(pod["id"], det["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_licensing_resubmit_cycle_closes(self, api):
        """PRD 3.3: "A `PodOperator` may resubmit a `DENIED` determination by
        supplying a `revision_number` exactly one greater than the current
        one, moving it to `RESUBMITTED` with the counter incremented. A
        `LICENSE_REQUIRED` determination resubmits the same way but must
        additionally switch `submission_kind` to `FULL_LICENSE`, abandoning
        the exemption path. A resubmitted determination re-enters review
        through the same begin-review step."

        Design: Difficulty/non_linear_state_machine/licensing_determination_resubmit_cycle
        """
        set_clock("2026-06-01T00:00:00Z")
        pod, site, policy, plan = setup_pod_with_approved_policy_and_plan(
            pod_overrides={"seat_capacity": 8},
        )
        # COMMERCIAL zoning is not exemptible -> DENIED path is reliable.
        pod = validate_success(api.open_enrollment(pod["id"], OPERATOR))
        det = validate_success(
            api.create_licensing_determination(
                pod["id"],
                {"jurisdiction_code": "AZ-MARICOPA",
                 "submission_kind": "EXEMPTION_CLAIM"},
                OPERATOR,
            ),
            expected_status=201,
        )
        validate_success(
            api.begin_review_licensing_determination(pod["id"], det["id"], OFFICER)
        )
        decided = validate_success(api.decide_licensing_determination(
            pod["id"], det["id"],
            {"decision": "DENIED", "denial_reason": "zoning not exemptible"},
            OFFICER,
        ))
        assert decided["determination_status"] == "DENIED"
        pod = get_pod(pod["id"])
        assert pod["status"] == "FORMING", (
            f"DENIED must cascade pod to FORMING, got {pod['status']}"
        )

        resubmitted = validate_success(api.resubmit_licensing_determination(
            pod["id"], det["id"],
            {"revision_number": 1, "submission_kind": "FULL_LICENSE"},
            OPERATOR,
        ))
        assert resubmitted["determination_status"] == "RESUBMITTED"
        assert resubmitted["revision_number"] == 1, (
            f"revision_number must increment to 1, got {resubmitted['revision_number']}"
        )

        under_review = validate_success(
            api.begin_review_licensing_determination(pod["id"], det["id"], OFFICER)
        )
        assert under_review["determination_status"] == "UNDER_REVIEW"

    def test_licensing_resubmit_cycle_is_repeatable(self, api):
        """PRD 3.3: "Neither adverse outcome is terminal. A `PodOperator`
        may resubmit a `DENIED` determination by supplying a
        `revision_number` exactly one greater than the current one, moving
        it to `RESUBMITTED` with the counter incremented."

        Design: Difficulty/non_linear_state_machine/licensing_determination_resubmit_cycle
        """
        set_clock("2026-06-01T00:00:00Z")
        pod, site, policy, plan = setup_pod_with_approved_policy_and_plan(
            pod_overrides={"seat_capacity": 8},
        )
        pod = validate_success(api.open_enrollment(pod["id"], OPERATOR))
        det = validate_success(
            api.create_licensing_determination(
                pod["id"],
                {"jurisdiction_code": "AZ-MARICOPA",
                 "submission_kind": "EXEMPTION_CLAIM"},
                OPERATOR,
            ),
            expected_status=201,
        )
        for expected_revision in (1, 2):
            validate_success(
                api.begin_review_licensing_determination(pod["id"], det["id"], OFFICER)
            )
            decided = validate_success(api.decide_licensing_determination(
                pod["id"], det["id"],
                {"decision": "DENIED", "denial_reason": f"denial {expected_revision}"},
                OFFICER,
            ))
            assert decided["determination_status"] == "DENIED"
            resubmitted = validate_success(api.resubmit_licensing_determination(
                pod["id"], det["id"],
                {"revision_number": expected_revision,
                 "submission_kind": "FULL_LICENSE"},
                OPERATOR,
            ))
            assert resubmitted["determination_status"] == "RESUBMITTED"
            assert resubmitted["revision_number"] == expected_revision, (
                f"cycle {expected_revision}: revision_number must be "
                f"{expected_revision}, got {resubmitted['revision_number']}"
            )


class TestInvoiceLifecycle:
    def test_invoice_paid_is_terminal(self, api):
        """PRD 3.7: "An invoice in `ISSUED` or `OVERDUE` may be written off
        to `WRITTEN_OFF` by a `PodOperator` only when its seat is `WITHDRAWN`
        and its `paid_cents` is exactly zero — an invoice carrying any
        cleared payment must be refunded rather than written off, and the
        attempt is rejected with `ERR_INVOICE_HAS_PAYMENTS` (HTTP 422)."

        Design: Corner/state_machines/invoice_paid_is_terminal
        """
        set_clock("2026-08-15T00:00:00Z")
        pod, *_ = setup_pod_active()
        family, student, seat = setup_enrolled_seat(pod)
        inv = create_issued_invoice(pod["id"], seat["id"])
        post_and_clear_payment(pod["id"], seat["id"], inv["id"],
                               amount_cents=inv["total_cents"])
        inv_now = validate_success(api.get_invoice(inv["id"], OPERATOR))
        assert inv_now["invoice_status"] == "PAID"
        # A PAID invoice's seat is still ENROLLED, so the write-off attempt
        # also violates the paid_cents == 0 / seat-WITHDRAWN preconditions;
        # the state-vs-business ordering between them is not pinned for this
        # combination, so either outcome is accepted (PRD 2.11).
        from test_helpers import validate_error_is_one_of
        resp = api.write_off_invoice(pod["id"], seat["id"], inv["id"], OPERATOR)
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_INVOICE_HAS_PAYMENTS]
        )


class TestConferenceLifecycle:
    def test_progress_conference_cycle_count_cap(self, api):
        """PRD 3.8: "A no-show is recoverable by the family: rescheduling
        moves the conference from `NO_SHOW` to `RESCHEDULED` and increments
        `cycle_count`, but only while fewer than three reschedule cycles
        have been consumed — a third rescheduling attempt is rejected with
        `ERR_CONFERENCE_CYCLE_LIMIT` (HTTP 422)."

        Design: Corner/state_machines/progress_conference_cycle_count_cap
        """
        set_clock("2026-08-15T00:00:00Z")
        pod, site, policy, plan, det, guide, assignment = setup_pod_active()
        family, student, seat = setup_enrolled_seat(pod)
        fam_headers = make_family_headers(family["id"])
        guide_headers = {"X-User-ID": guide["id"], "X-User-Role": "Guide",
                         "Content-Type": "application/json"}

        # Create + schedule a first conference window; then drive
        # NO_SHOW -> RESCHEDULED -> SCHEDULED -> NO_SHOW cycles by advancing
        # the logical clock past each window's scheduled_end.
        conf = validate_success(
            api.create_progress_conference(
                pod["id"],
                create_progress_conference_payload(
                    seat["id"], plan["id"],
                    scheduled_start="2026-09-01T15:00:00Z",
                    scheduled_end="2026-09-01T15:30:00Z",
                ),
                fam_headers,
            ),
            expected_status=201,
        )
        validate_success(
            api.schedule_progress_conference(pod["id"], conf["id"], guide_headers)
        )

        def drive_to_no_show(day_iso):
            set_clock(day_iso)
            no_show = validate_success(
                api.mark_no_show_progress_conference(pod["id"], conf["id"],
                                                     guide_headers)
            )
            assert no_show["conference_status"] == "NO_SHOW"

        # PRD's two cap clauses diverge at the third attempt: "fewer than
        # three reschedule cycles have been consumed" admits attempts 1-3,
        # while "a third rescheduling attempt is rejected" admits only 1-2.
        # Both clauses agree that attempts 1 and 2 succeed, so assert those
        # outright ...
        for i, day in enumerate(("2026-09-01T16:00:00Z",
                                 "2026-09-02T16:00:00Z")):
            drive_to_no_show(day)
            rescheduled = validate_success(
                api.reschedule_progress_conference(pod["id"], conf["id"],
                                                   fam_headers)
            )
            assert rescheduled["conference_status"] == "RESCHEDULED"
            assert rescheduled["cycle_count"] == i + 1
            validate_success(
                api.schedule_progress_conference(pod["id"], conf["id"],
                                                 guide_headers)
            )

        # ... and that the cap rejects with exactly ERR_CONFERENCE_CYCLE_LIMIT
        # (422) no later than the fourth attempt.
        drive_to_no_show("2026-09-03T16:00:00Z")
        resp3 = api.reschedule_progress_conference(pod["id"], conf["id"],
                                                   fam_headers)
        if resp3.status_code == 200:
            validate_success(resp3)
            validate_success(
                api.schedule_progress_conference(pod["id"], conf["id"],
                                                 guide_headers)
            )
            drive_to_no_show("2026-09-04T16:00:00Z")
            resp4 = api.reschedule_progress_conference(pod["id"], conf["id"],
                                                       fam_headers)
            validate_error(resp4, ApiErrorId.ERR_CONFERENCE_CYCLE_LIMIT,
                           expected_status=422)
        else:
            validate_error(resp3, ApiErrorId.ERR_CONFERENCE_CYCLE_LIMIT,
                           expected_status=422)
