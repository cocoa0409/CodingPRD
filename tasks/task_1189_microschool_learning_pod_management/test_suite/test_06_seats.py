"""Seat claims: enrollment OCC, enroll/withdraw count invariant, immediate
consistency, duplicate-seat uniqueness, term window, and proration input
isolation."""
from test_helpers import (
    ApiErrorId,
    create_seat_payload,
    get_success_data,
    make_family_headers,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)
from test_helpers.fixtures import (
    create_family,
    create_student,
    enroll_seat,
    get_pod,
    get_pod_version,
    set_clock,
    setup_active_pod_with_enrolled_seats,
    setup_enrolled_seat,
    setup_family_student_seat,
    setup_pod_active,
    withdraw_seat,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["pod_operator_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


class TestOccOnEnroll:
    def test_occ_stale_version_on_seat_enroll(self, api):
        """PRD 2.9: "Enrolling a reserved seat requires the request body to
        carry `expected_pod_version`, holding the pod `version` the client
        last observed. Because every enrollment advances the pod's `version`
        as it recomputes `enrolled_count`, a client whose view of remaining
        capacity predates another enrollment holds a stale version; if
        `expected_pod_version` does not equal the pod's current `version`,
        the enrollment is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/endpoints/occ_stale_version_on_seat_enroll
        """
        set_clock("2026-08-15T00:00:00Z")
        pod, *_ = setup_pod_active()
        fam1, stu1, seat1 = setup_family_student_seat(pod)
        fam2, stu2, seat2 = setup_family_student_seat(pod)
        pod_v0 = get_pod_version(pod["id"])

        first = validate_success(api.enroll_seat(
            pod["id"], seat1["id"], {"expected_pod_version": pod_v0},
            make_family_headers(fam1["id"]),
        ))
        assert first["seat_status"] == "ENROLLED"
        assert get_pod_version(pod["id"]) == pod_v0 + 1, (
            "every enrollment advances the pod's version by 1"
        )

        resp = api.enroll_seat(
            pod["id"], seat2["id"], {"expected_pod_version": pod_v0},
            make_family_headers(fam2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        seat2_now = get_success_data(api.get_seat(seat2["id"], REGISTRAR))
        assert seat2_now["seat_status"] == "RESERVED"


class TestOccOnDissolve:
    def test_occ_stale_version_on_pod_dissolve(self, api):
        """PRD 2.9: "Initiating pod dissolution carries the same guard: the
        request must carry `expected_pod_version` matching the pod's current
        `version`. A pod whose version has advanced since the client last
        read it — through a fresh enrollment or any other versioned
        mutation — no longer matches the dissolution-refund baseline the
        client computed against, and the dissolution request is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/endpoints/occ_stale_version_on_pod_dissolve
        """
        set_clock("2026-08-15T00:00:00Z")
        pod, *_ = setup_pod_active()
        family, student, seat = setup_family_student_seat(pod)
        pod_v0 = get_pod_version(pod["id"])
        # Another writer enrolls the seat, advancing the pod version.
        enroll_seat(pod["id"], seat, family["id"])
        assert get_pod_version(pod["id"]) == pod_v0 + 1

        resp = api.dissolve_pod(
            pod["id"],
            {"expected_pod_version": pod_v0, "dissolution_reason": "stale"},
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        assert get_pod(pod["id"])["status"] == "ACTIVE"


class TestEnrollWithdrawInvariant:
    def test_enroll_then_withdraw_conserves_enrolled_count(self, api):
        """PRD 3.6: "On success the pod's `enrolled_count` increments, the
        student becomes `ENROLLED`, the family becomes `ACTIVE`, the seat
        pins `tuition_basis_cents` as a snapshot of the pod's
        `tuition_full_year_cents` at that instant, the seat's
        `prorated_due_cents` is computed as below, and the pod's posture,
        compliance flag, and version are all recomputed alongside the seat's
        own `version`."
        PRD 3.6: "The transition stamps `withdrawn_on`, moves the student to
        `WITHDRAWN`, decrements the pod's `enrolled_count`, recomputes the
        compliance flag, creates a refund claim of kind `WITHDRAWAL` priced
        by the sliding-scale rule of §3.9, and reconciles the seat's open
        invoices: ..."

        Design: Difficulty/compensating_invariant/seat_enroll_withdraw_count_invariant
        """
        set_clock("2026-08-15T00:00:00Z")
        pod, *_ = setup_pod_active()
        family, student, seat = setup_family_student_seat(pod)
        before = get_pod(pod["id"])
        count_before = before["enrolled_count"]

        enrolled = enroll_seat(pod["id"], seat, family["id"])
        assert enrolled["seat_status"] == "ENROLLED"
        assert get_pod(pod["id"])["enrolled_count"] == count_before + 1

        withdrawn = withdraw_seat(pod["id"], seat["id"], family["id"],
                                  "2026-08-20")
        assert withdrawn["seat_status"] == "WITHDRAWN"
        after = get_pod(pod["id"])
        assert after["enrolled_count"] == count_before, (
            f"enroll+withdraw must conserve enrolled_count: before="
            f"{count_before}, after={after['enrolled_count']}"
        )

    def test_withdrawal_creates_withdrawal_refund_claim(self, api):
        """PRD 3.6: "The transition stamps `withdrawn_on`, moves the student
        to `WITHDRAWN`, decrements the pod's `enrolled_count`, recomputes
        the compliance flag, creates a refund claim of kind `WITHDRAWAL`
        priced by the sliding-scale rule of §3.9, and reconciles the seat's
        open invoices: ..."

        Design: Difficulty/compensating_invariant/seat_enroll_withdraw_count_invariant
        """
        set_clock("2026-08-15T00:00:00Z")
        pod, *_ = setup_pod_active()
        family, student, seat = setup_enrolled_seat(pod)
        withdrawn = withdraw_seat(pod["id"], seat["id"], family["id"],
                                  "2026-08-20")
        assert withdrawn["seat_status"] == "WITHDRAWN"
        assert withdrawn["withdrawn_on"] is not None
        student_now = get_success_data(api.get_student(student["id"], REGISTRAR))
        assert student_now["student_status"] == "WITHDRAWN"
        claims, meta = validate_paginated(api.list_refund_claims_for_pod(
            pod["id"], REGISTRAR,
            params={"claim_kind": "WITHDRAWAL", "seat_id": seat["id"]},
        ))
        assert len(claims) == 1, (
            f"withdrawal must create exactly one WITHDRAWAL claim, got {len(claims)}"
        )
        assert claims[0]["claim_status"] == "FILED"
        assert isinstance(claims[0]["claimed_amount_cents"], int)


class TestImmediateConsistency:
    def test_immediate_visibility_after_enroll(self, api):
        """PRD 2.10: "Consistency is immediate, not eventual; a response is
        returned only after every cascade and recomputation the transition
        triggers has been applied."

        Design: Corner/consistency_model/immediate_visibility_after_enroll
        """
        set_clock("2026-08-15T00:00:00Z")
        pod, *_ = setup_pod_active()
        family, student, seat = setup_family_student_seat(pod)
        before = get_pod(pod["id"])
        cnt_pre = before["enrolled_count"]
        v_pre = before["version"]

        validate_success(api.enroll_seat(
            pod["id"], seat["id"], {"expected_pod_version": v_pre},
            make_family_headers(family["id"]),
        ))
        after = get_pod(pod["id"])
        assert after["enrolled_count"] == cnt_pre + 1, (
            f"enrolled_count must be immediately visible: {cnt_pre} -> "
            f"{after['enrolled_count']}"
        )


class TestSeatReservationRules:
    def test_enrollment_out_of_term_rejected(self, api):
        """PRD 3.6: "Reservation enforces, after the posture gate, seat
        uniqueness — at most one seat in `RESERVED` or `ENROLLED` may exist
        per student per pod, violations rejected with `ERR_DUPLICATE_SEAT`
        (HTTP 422) — and the term window: `enrolled_on` must fall within the
        pod's `term_start_date` and `term_end_date`, inclusive of both, with
        out-of-term dates rejected as `ERR_ENROLLMENT_OUT_OF_TERM`
        (HTTP 422)."

        Design: Corner/validations/enrollment_out_of_term_rejected
        """
        set_clock("2026-08-15T00:00:00Z")
        pod, *_ = setup_pod_active()
        family = create_family()
        student = create_student(family["id"])
        resp = api.create_seat(
            pod["id"],
            create_seat_payload(student["id"], enrolled_on="2026-07-01"),
            REGISTRAR,
        )
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_OUT_OF_TERM,
                       expected_status=422)

    def test_err_duplicate_seat_triggerable(self, api):
        """PRD 3.6: "Reservation enforces, after the posture gate, seat
        uniqueness — at most one seat in `RESERVED` or `ENROLLED` may exist
        per student per pod, violations rejected with `ERR_DUPLICATE_SEAT`
        (HTTP 422) — and the term window: ..."

        Design: Corner/errors/err_duplicate_seat_triggerable
        """
        set_clock("2026-08-15T00:00:00Z")
        pod, *_ = setup_pod_active()
        family, student, seat = setup_family_student_seat(pod)
        resp = api.create_seat(
            pod["id"],
            create_seat_payload(student["id"], enrolled_on="2026-09-01"),
            REGISTRAR,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SEAT, expected_status=422)


class TestProrationInputIsolation:
    def test_prorated_tuition_input_set_filtering(self, api):
        """PRD 3.6: "Under the daily convention, the amount owed for a
        mid-year start is the pod's full-year tuition multiplied by the
        seat's enrolled days — the calendar-day count from `enrolled_on`
        through `term_end_date`, inclusive of both — divided by the academic
        year's total instructional days, counted from `term_start_date`
        through `term_end_date` and likewise inclusive of both, with the
        quotient rounded half up to a whole cent."

        Design: Corner/calculations/prorated_tuition_input_set_filtering
        """
        set_clock("2026-09-01T00:00:00Z")
        pod, *_ = setup_pod_active()
        # A first seat enrolls at the term start.
        fam1, stu1, seat1 = setup_enrolled_seat(pod, enrolled_on="2026-08-01")
        # Two further seats enroll mid-year on the SAME date: whatever the
        # pod's proration convention, identical inputs must produce
        # identical results, and neither may be perturbed by the first seat.
        fam2, stu2, seat2 = setup_enrolled_seat(pod, enrolled_on="2026-10-15")
        fam3, stu3, seat3 = setup_enrolled_seat(pod, enrolled_on="2026-10-15")

        seat2_now = get_success_data(api.get_seat(seat2["id"], REGISTRAR))
        seat3_now = get_success_data(api.get_seat(seat3["id"], REGISTRAR))
        assert seat2_now["prorated_due_cents"] == seat3_now["prorated_due_cents"], (
            "seats with identical enrolled_on on the same pod must prorate "
            f"identically: {seat2_now['prorated_due_cents']} vs "
            f"{seat3_now['prorated_due_cents']}"
        )
        assert seat2_now["tuition_basis_cents"] == pod["tuition_full_year_cents"]
