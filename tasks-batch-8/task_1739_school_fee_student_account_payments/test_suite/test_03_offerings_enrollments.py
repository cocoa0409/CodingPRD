"""Offerings and the enrollment lifecycle: lazy transitions, completion cascade,
enrollment business-rule ladder, schedule-conflict interval semantics."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId,
    create_fee_catalog_item_payload, create_offering_payload,
    create_student_payload,
    setup_open_year, setup_year_with_fee, add_student_with_account,
    setup_account_enrolled, set_clock, NON_EXISTENT_UUID,
)


class TestOfferingLazyTransitions:
    def test_offering_lazy_in_session_transition(self, bookkeeper_headers):
        """PRD §3.3: "When the logical clock's date reaches an offering's
        start_date while it is still `SCHEDULED`, the offering lazily moves
        `SCHEDULED` → `IN_SESSION` — observed on any read of the offering or on
        an operations run — and its version increments by 1."

        Design: Corner/state_machines/offering_lazy_in_session_transition
        """
        env = setup_year_with_fee(
            fee_amount=1000, with_offering=True,
            offering_overrides={"start_date": "2026-08-01", "end_date": "2026-12-15"})
        resp = api_client.get_offering(env["year"]["id"], env["offering"]["id"],
                                       bookkeeper_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "IN_SESSION", (
            f"Clock default 2026-08-01 == start_date must flip to IN_SESSION, got {data['status']}")

    def test_offering_not_started_stays_scheduled(self, bookkeeper_headers):
        """PRD §3.3: "Offerings are born `SCHEDULED`. When the logical clock's date
        reaches an offering's start_date while it is still `SCHEDULED`, the
        offering lazily moves `SCHEDULED` → `IN_SESSION`"

        With the clock at the default 2026-08-01 and a 2026-09-01 start date the
        boundary is not yet reached, so the offering stays SCHEDULED.

        Design: Corner/state_machines/offering_lazy_in_session_transition
        """
        env = setup_year_with_fee(
            fee_amount=1000, with_offering=True,
            offering_overrides={"start_date": "2026-09-01", "end_date": "2026-12-15"})
        data = get_success_data(api_client.get_offering(
            env["year"]["id"], env["offering"]["id"], bookkeeper_headers))
        assert data["status"] == "SCHEDULED"


class TestOfferingCompleteCancel:
    def test_offering_complete_cascades_enrollment_completed(self, bookkeeper_headers):
        """PRD §3.3: "Completing an offering moves it `IN_SESSION` → `COMPLETED`,
        cascades every `ACTIVE` enrollment on it to `COMPLETED`, and increments
        the offering's version by 1"

        Design: Corner/state_machines/offering_complete_cascades_enrollment_completed
        """
        env = setup_account_enrolled(fee_amount=1000)
        set_clock("2026-09-02T00:00:00Z")
        # Read to fire the lazy IN_SESSION transition
        get_success_data(api_client.get_offering(env["year"]["id"], env["offering"]["id"],
                                                 bookkeeper_headers))
        resp = api_client.complete_offering(env["year"]["id"], env["offering"]["id"],
                                            bookkeeper_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "COMPLETED"
        enrollment = get_success_data(api_client.get_enrollment(
            env["account"]["id"], env["enrollment"]["id"], bookkeeper_headers))
        assert enrollment["status"] == "COMPLETED", (
            f"Completion must cascade to the ACTIVE enrollment; got {enrollment['status']}")

    def test_offering_cancel_from_completed_rejected(self, bookkeeper_headers):
        """PRD §3.3: "A `COMPLETED` or already-`CANCELLED` offering accepts neither
        action."
        PRD §2.10: "The target resource must be in the from-state its state machine
        requires — otherwise `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/offering_cancel_from_completed_rejected
        """
        env = setup_year_with_fee(fee_amount=1000, with_offering=True)
        set_clock("2026-09-02T00:00:00Z")
        get_success_data(api_client.get_offering(env["year"]["id"], env["offering"]["id"],
                                                 bookkeeper_headers))
        get_success_data(api_client.complete_offering(env["year"]["id"],
                                                      env["offering"]["id"], bookkeeper_headers))
        resp = api_client.cancel_offering(env["year"]["id"], env["offering"]["id"],
                                          bookkeeper_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_offering_complete_requires_in_session(self, bookkeeper_headers):
        """PRD §3.3: "completing requires the offering to actually be `IN_SESSION`,
        else `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/offering_cancel_from_completed_rejected
        """
        env = setup_year_with_fee(fee_amount=1000, with_offering=True)
        # Clock default 2026-08-01 < start 2026-09-01: still SCHEDULED
        resp = api_client.complete_offering(env["year"]["id"], env["offering"]["id"],
                                            bookkeeper_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestEnrollmentRules:
    def test_duplicate_enrollment_rejected(self, bookkeeper_headers):
        """PRD §2.10: "No second ACTIVE enrollment may exist for the same account
        and offering — otherwise `ERR_DUPLICATE_ENROLLMENT` (HTTP 409)."

        Design: Corner/validations/duplicate_enrollment_rejected
        """
        env = setup_account_enrolled(fee_amount=1000)
        resp = api_client.create_enrollment(
            env["account"]["id"], {"offering_id": env["offering"]["id"]}, bookkeeper_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENROLLMENT)

    def test_enrollment_referenced_offering_not_found(self, bookkeeper_headers):
        """PRD §2.8: "Separately, identifiers referenced in a request body —
        offering_id, fee_item_id, department_id, waiver_program_id, item_id,
        student_id — must exist and belong to the same school-year scope as the
        resource being written; a body reference that fails this check is rejected
        with `ERR_REFERENCED_NOT_FOUND` (HTTP 404)."

        Design: Corner/validations/referenced_body_id_not_found
        """
        env = setup_open_year()
        student, account = add_student_with_account(env["year"]["id"])
        resp = api_client.create_enrollment(
            account["id"], {"offering_id": NON_EXISTENT_UUID}, bookkeeper_headers)
        validate_error(resp, ApiErrorId.ERR_REFERENCED_NOT_FOUND)

    def test_enrollment_gated_by_offering_state(self, bookkeeper_headers):
        """PRD §2.10: "The offering must be SCHEDULED — otherwise
        `ERR_ENROLLMENT_WINDOW_CLOSED` (HTTP 409)."
        PRD §3.3: "the offering still `SCHEDULED` since students cannot join an
        `IN_SESSION`, `COMPLETED`, or `CANCELLED` offering"

        Design: Difficulty/cross_entity_state_dependency/enrollment_gated_by_offering_state
        """
        env = setup_year_with_fee(fee_amount=1000, with_offering=True,
                                  offering_overrides={"capacity": 30})
        student, account = add_student_with_account(env["year"]["id"])
        set_clock("2026-09-01T00:00:00Z")
        offering = get_success_data(api_client.get_offering(
            env["year"]["id"], env["offering"]["id"], bookkeeper_headers))
        assert offering["status"] == "IN_SESSION"
        resp = api_client.create_enrollment(
            account["id"], {"offering_id": env["offering"]["id"]}, bookkeeper_headers)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_WINDOW_CLOSED)

    def test_enrollment_into_completed_offering_rejected(self, bookkeeper_headers):
        """PRD §3.3: "the offering still `SCHEDULED` since students cannot join an
        `IN_SESSION`, `COMPLETED`, or `CANCELLED` offering
        (`ERR_ENROLLMENT_WINDOW_CLOSED`, HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/enrollment_gated_by_offering_state
        """
        env = setup_year_with_fee(fee_amount=1000, with_offering=True,
                                  offering_overrides={"capacity": 30})
        student, account = add_student_with_account(env["year"]["id"])
        set_clock("2026-09-02T00:00:00Z")
        get_success_data(api_client.get_offering(env["year"]["id"], env["offering"]["id"],
                                                 bookkeeper_headers))
        get_success_data(api_client.complete_offering(env["year"]["id"],
                                                      env["offering"]["id"], bookkeeper_headers))
        resp = api_client.create_enrollment(
            account["id"], {"offering_id": env["offering"]["id"]}, bookkeeper_headers)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_WINDOW_CLOSED)

    def test_enrollment_full_offering_referential_beats_temporal(self, bookkeeper_headers):
        """PRD §2.10: "Checks run in ascending priority order, and the first failing
        check determines the error returned — an earlier failure masks later ones."
        and "enrollment creation evaluates its four business checks in the order
        uniqueness, then capacity, then window, then schedule conflict".

        Design: Difficulty/priority_pair_validation_conflict/enrollment_full_offering_referential_beats_temporal
        """
        env = setup_year_with_fee(fee_amount=1000, with_offering=True,
                                  offering_overrides={"capacity": 1})
        # Student 1 fills the single slot
        s1, a1 = add_student_with_account(env["year"]["id"], external_ref="S-1",
                                          family_id="fam-a", full_name="Ada")
        get_success_data(api_client.create_enrollment(a1["id"],
                                                      {"offering_id": env["offering"]["id"]},
                                                      bookkeeper_headers))
        s2, a2 = add_student_with_account(env["year"]["id"], external_ref="S-2",
                                          family_id="fam-b", full_name="Ben")
        # Move the clock so the offering lazily transitions to IN_SESSION
        set_clock("2026-09-02T00:00:00Z")
        offering = get_success_data(api_client.get_offering(
            env["year"]["id"], env["offering"]["id"], bookkeeper_headers))
        assert offering["status"] == "IN_SESSION"
        # Capacity (rung 9) is evaluated before the window check (rung 10)
        resp = api_client.create_enrollment(a2["id"], {"offering_id": env["offering"]["id"]},
                                            bookkeeper_headers)
        validate_error(resp, ApiErrorId.ERR_OFFERING_FULL)

    def test_enrollment_full_alone_rejected(self, bookkeeper_headers):
        """PRD §2.10: "The count of ACTIVE enrollments on the offering must be below
        its capacity — otherwise `ERR_OFFERING_FULL` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/enrollment_full_offering_referential_beats_temporal
        """
        env = setup_year_with_fee(fee_amount=1000, with_offering=True,
                                  offering_overrides={"capacity": 1})
        s1, a1 = add_student_with_account(env["year"]["id"], external_ref="S-1",
                                          family_id="fam-a", full_name="Ada")
        get_success_data(api_client.create_enrollment(a1["id"],
                                                      {"offering_id": env["offering"]["id"]},
                                                      bookkeeper_headers))
        s2, a2 = add_student_with_account(env["year"]["id"], external_ref="S-2",
                                          family_id="fam-b", full_name="Ben")
        resp = api_client.create_enrollment(a2["id"], {"offering_id": env["offering"]["id"]},
                                            bookkeeper_headers)
        validate_error(resp, ApiErrorId.ERR_OFFERING_FULL)


class TestScheduleConflictSemantics:
    def test_enrollment_half_open_interval_adjacency_allowed(self, bookkeeper_headers):
        """PRD §2.7: "Offering schedules use **half-open intervals**. An offering
        occupies the window from its `start_date` up to but not including its
        `end_date`. Two offerings whose windows merely touch — one offering's
        `start_date` equal to another's `end_date` — do not conflict, and a
        student may be actively enrolled in both."

        Design: Difficulty/resource_temporal_overlap/enrollment_half_open_interval_adjacency_allowed
        """
        env = setup_year_with_fee(fee_amount=1000)
        year_id, dept_id, fee_id = env["year"]["id"], env["department"]["id"], env["fee_item"]["id"]
        oa = get_success_data(api_client.create_offering(year_id, create_offering_payload(
            title="A", department_id=dept_id, fee_item_id=fee_id,
            start_date="2026-09-01", end_date="2026-12-15"), bookkeeper_headers))
        ob = get_success_data(api_client.create_offering(year_id, create_offering_payload(
            title="B", department_id=dept_id, fee_item_id=fee_id,
            start_date="2026-12-15", end_date="2027-03-01"), bookkeeper_headers))
        student, account = add_student_with_account(year_id)
        get_success_data(api_client.create_enrollment(account["id"], {"offering_id": oa["id"]},
                                                      bookkeeper_headers))
        resp = api_client.create_enrollment(account["id"], {"offering_id": ob["id"]},
                                            bookkeeper_headers)
        data = validate_success(resp, 201)
        assert data["status"] == "ACTIVE", (
            "Half-open adjacency (B.start == A.end) must not collide")
        assert data["offering_id"] == ob["id"]

    def test_enrollment_one_day_overlap_rejected(self, bookkeeper_headers):
        """PRD §2.10: "The target offering's half-open window must not intersect
        the half-open window of any other offering with an ACTIVE enrollment on
        the same account; a shared boundary date does not collide — otherwise
        `ERR_SCHEDULE_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/enrollment_half_open_interval_adjacency_allowed
        """
        env = setup_year_with_fee(fee_amount=1000)
        year_id, dept_id, fee_id = env["year"]["id"], env["department"]["id"], env["fee_item"]["id"]
        oa = get_success_data(api_client.create_offering(year_id, create_offering_payload(
            title="A", department_id=dept_id, fee_item_id=fee_id,
            start_date="2026-09-01", end_date="2026-12-15"), bookkeeper_headers))
        oc = get_success_data(api_client.create_offering(year_id, create_offering_payload(
            title="C", department_id=dept_id, fee_item_id=fee_id,
            start_date="2026-12-14", end_date="2027-02-01"), bookkeeper_headers))
        student, account = add_student_with_account(year_id)
        get_success_data(api_client.create_enrollment(account["id"], {"offering_id": oa["id"]},
                                                      bookkeeper_headers))
        resp = api_client.create_enrollment(account["id"], {"offering_id": oc["id"]},
                                            bookkeeper_headers)
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT)
