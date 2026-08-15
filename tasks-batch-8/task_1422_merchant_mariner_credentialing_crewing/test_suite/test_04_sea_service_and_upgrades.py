"""Sea-service documentation, the provisional/verified dual variants, the
dispute loop, segregation of duties, and upgrade eligibility."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_enrollment,
    create_activated_mariner,
    create_course,
    create_mariner,
    create_sea_record,
    create_verified_sea_record,
    create_vessel,
    enroll_enrollment,
    get_success_data,
    make_mariner_headers,
    make_officer_headers,
    request_enrollment,
    submit_sea_record,
    validate_error,
    validate_success,
    verify_sea_record,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
OFFICER = TEST_USERS["officer_headers"]
CREWING = TEST_USERS["crewing_headers"]


def _complete_course_for(mariner_id, course_id, approver_id="cm-300"):
    enrollment = request_enrollment(course_id, mariner_id)
    enrollment = approve_enrollment(enrollment["id"], approver_id=approver_id)
    enroll_enrollment(enrollment["id"])
    resp = api_client.record_enrollment_completion(
        enrollment["id"], {"outcome": "COMPLETED"}, ADMIN)
    return get_success_data(resp)


class TestSeaServiceDualVariant:

    def _setup_two_verified_records(self):
        """R1: OCEAN TWELVE_HOUR 2025-01-01..2025-01-30 (30 days);
        R2: INLAND EIGHT_HOUR 2025-02-01..2025-02-10 (10 days).
        Both SUBMITTED then VERIFIED by an officer (recorder is the mariner).
        """
        mariner = create_mariner()
        vessel = create_vessel()
        r1 = create_sea_record(
            mariner["id"], vessel["id"], position_code="AB",
            service_region="OCEAN", watch_schedule="TWELVE_HOUR",
            start_date="2025-01-01T00:00:00Z", end_date="2025-01-30T00:00:00Z")
        r2 = create_sea_record(
            mariner["id"], vessel["id"], position_code="AB",
            service_region="INLAND", watch_schedule="EIGHT_HOUR",
            start_date="2025-02-01T00:00:00Z", end_date="2025-02-10T00:00:00Z")
        self._r1_at_create = r1
        for record in (r1, r2):
            submit_sea_record(mariner["id"], record["id"])
        r1 = verify_sea_record(mariner["id"], r1["id"])
        r2 = verify_sea_record(mariner["id"], r2["id"])
        return mariner, r1, r2

    def test_provisional_vs_verified_day_credit_per_record(self):
        """PRD section 3.4: "its `provisional_days` is computed immediately as
        the inclusive calendar-day count — the whole-day difference between
        `end_date` and `start_date`, plus one — with no regional or watch
        factors applied."
        PRD section 3.4: "A 30-day ocean hitch on twelve-hour watches
        therefore verifies as 45.0 days, while the same 30 days inland on
        eight-hour watches verifies as 15.0."

        Design: Difficulty/dual_variant_calc/sea_service_provisional_vs_verified_day_credit
        """
        mariner, r1, r2 = self._setup_two_verified_records()
        assert self._r1_at_create["provisional_days"] == 30.0, \
            "provisional: raw inclusive calendar days, no factors"
        assert self._r1_at_create["verified_days"] is None, \
            "verified_days stays null until verification"
        assert r1["verified_days"] == 45.0, \
            f"verified: 30 x 1.0 OCEAN x 1.5 TWELVE_HOUR, got {r1['verified_days']}"
        assert r2["provisional_days"] == 10.0
        assert r2["verified_days"] == 5.0, \
            f"verified: 10 x 0.5 INLAND x 1.0 EIGHT_HOUR, got {r2['verified_days']}"

    def test_provisional_vs_verified_summary_totals_disagree(self, officer_headers):
        """PRD section 3.4: "The sea-service summary returns
        `provisional_days_total` — the sum of `provisional_days` over records
        in `SUBMITTED` or `VERIFIED` — `verified_days_total` — the sum of
        `verified_days` over `VERIFIED` records only"

        Design: Difficulty/dual_variant_calc/sea_service_provisional_vs_verified_day_credit
        """
        mariner, _, _ = self._setup_two_verified_records()
        summary = validate_success(
            api_client.get_sea_service_summary(mariner["id"], officer_headers))
        assert summary["provisional_days_total"] == 40.0, \
            f"30 + 10 over the provisional input set, got {summary['provisional_days_total']}"
        assert summary["verified_days_total"] == 50.0, \
            f"45.0 + 5.0 over the verified input set, got {summary['verified_days_total']}"
        assert summary["provisional_days_total"] != summary["verified_days_total"], \
            "the two variants must disagree on identical stored rows"


class TestSeaServiceLifecycle:

    def test_sea_service_initial_state_draft(self):
        """PRD section 3.4: "The record is created in `DRAFT` status, stamped
        with `entered_by_user_id` from `X-User-ID`, and its `provisional_days`
        is computed immediately as the inclusive calendar-day count"

        Design: Corner/state_machines/sea_service_initial_state_draft
        """
        mariner = create_mariner()
        vessel = create_vessel()
        record = create_sea_record(
            mariner["id"], vessel["id"], watch_schedule="TWELVE_HOUR",
            start_date="2025-03-01T00:00:00Z", end_date="2025-03-11T00:00:00Z")
        assert record["record_status"] == "DRAFT"
        assert record["provisional_days"] == 11.0, \
            f"Mar 1..Mar 11 inclusive is 11 days, got {record['provisional_days']}"
        assert record["verified_days"] is None

    def test_dispute_resubmit_cycle_records_reasons(self, officer_headers):
        """PRD section 3.4: "Dispute moves a `SUBMITTED` record to `DISPUTED`
        (else `ERR_RECORD_NOT_VERIFIABLE`), recording the supplied `reason`
        into `dispute_reason`. A disputed record may be resubmitted — the same
        submission action carries `DISPUTED` back to `SUBMITTED`"

        Design: Difficulty/non_linear_state_machine/sea_service_dispute_resubmit_cycle
        """
        mariner = create_mariner()
        vessel = create_vessel()
        record = create_sea_record(
            mariner["id"], vessel["id"],
            start_date="2025-01-01T00:00:00Z", end_date="2025-01-30T00:00:00Z")
        rid = record["id"]
        submit_sea_record(mariner["id"], rid)

        disputed = validate_success(
            api_client.dispute_sea_service_record(
                mariner["id"], rid, {"reason": "missing vessel logs"}, OFFICER))
        assert disputed["record_status"] == "DISPUTED"
        assert disputed["dispute_reason"] == "missing vessel logs"
        assert disputed["verified_days"] is None, \
            "verified_days stays null through the dispute loop"

        resubmitted = submit_sea_record(mariner["id"], rid)
        assert resubmitted["record_status"] == "SUBMITTED", \
            "DISPUTED -> SUBMITTED resubmission edge"

        disputed2 = validate_success(
            api_client.dispute_sea_service_record(
                mariner["id"], rid,
                {"reason": "dates inconsistent with discharge"}, OFFICER))
        assert disputed2["dispute_reason"] == "dates inconsistent with discharge", \
            "the second dispute overwrites the reason"

    def test_dispute_loop_ends_in_single_terminal_verify(self):
        """PRD section 3.4: "Verification computes `verified_days` — null
        until this point — as the inclusive calendar-day count multiplied by
        the region factor and the watch multiplier, floored to the half-day
        grid, and stamps `verified_by_user_id` with the verifier's
        `X-User-ID`."

        Design: Difficulty/non_linear_state_machine/sea_service_dispute_resubmit_cycle
        """
        mariner = create_mariner()
        vessel = create_vessel()
        record = create_sea_record(
            mariner["id"], vessel["id"],
            start_date="2025-01-01T00:00:00Z", end_date="2025-01-30T00:00:00Z")
        rid = record["id"]
        submit_sea_record(mariner["id"], rid)
        validate_success(api_client.dispute_sea_service_record(
            mariner["id"], rid, {"reason": "missing vessel logs"}, OFFICER))
        submit_sea_record(mariner["id"], rid)
        validate_success(api_client.dispute_sea_service_record(
            mariner["id"], rid, {"reason": "dates inconsistent"}, OFFICER))
        submit_sea_record(mariner["id"], rid)

        final = verify_sea_record(mariner["id"], rid)
        assert final["record_status"] == "VERIFIED"
        assert final["verified_days"] == 30.0, \
            f"30 x 1.0 x 1.0 computed once at the terminal verify, got {final['verified_days']}"
        assert final["verified_by_user_id"] == OFFICER["X-User-ID"]
        assert final["verified_by_user_id"] != mariner["id"], \
            "the recorder (mariner) must not be the verifier"

    def test_record_resubmit_from_verified_rejected(self):
        """PRD section 3.4: "Submission moves a record from `DRAFT` to
        `SUBMITTED`, re-checking that `end_date` is on or after `start_date`
        and not in the future (else `ERR_INVALID_REQUEST`); from any other
        state the submission is `ERR_RECORD_NOT_SUBMITTABLE`."

        Design: Corner/errors/record_resubmit_from_verified_rejected
        """
        mariner = create_mariner()
        vessel = create_vessel()
        record = create_verified_sea_record(
            mariner["id"], vessel["id"],
            start_date="2025-01-01T00:00:00Z", end_date="2025-01-10T00:00:00Z")
        resp = api_client.submit_sea_service_record(
            mariner["id"], record["id"], make_mariner_headers(mariner["id"]))
        validate_error(resp, ApiErrorId.ERR_RECORD_NOT_SUBMITTABLE)


class TestSeaServiceInputSetFiltering:

    def test_sea_service_input_set_filtering(self, officer_headers):
        """PRD section 3.4: "The sea-service summary returns
        `provisional_days_total` — the sum of `provisional_days` over records
        in `SUBMITTED` or `VERIFIED` — `verified_days_total` — the sum of
        `verified_days` over `VERIFIED` records only — and a `by_track`
        breakdown; `DRAFT`, `DISPUTED`, and `REJECTED` records are excluded
        from both totals."

        Design: Corner/calculations/sea_service_input_set_filtering
        """
        mariner = create_mariner()
        vessel = create_vessel()
        # R1: DRAFT 5 days; R2: SUBMITTED 10 days; R3: DISPUTED 15 days;
        # R4: VERIFIED 20 days (all OCEAN EIGHT_HOUR).
        create_sea_record(
            mariner["id"], vessel["id"],
            start_date="2025-01-01T00:00:00Z", end_date="2025-01-05T00:00:00Z")
        r2 = create_sea_record(
            mariner["id"], vessel["id"],
            start_date="2025-02-01T00:00:00Z", end_date="2025-02-10T00:00:00Z")
        submit_sea_record(mariner["id"], r2["id"])
        r3 = create_sea_record(
            mariner["id"], vessel["id"],
            start_date="2025-03-01T00:00:00Z", end_date="2025-03-15T00:00:00Z")
        submit_sea_record(mariner["id"], r3["id"])
        validate_success(api_client.dispute_sea_service_record(
            mariner["id"], r3["id"], {"reason": "date query"}, OFFICER))
        create_verified_sea_record(
            mariner["id"], vessel["id"],
            start_date="2025-04-01T00:00:00Z", end_date="2025-04-20T00:00:00Z")

        summary = validate_success(
            api_client.get_sea_service_summary(mariner["id"], officer_headers))
        assert summary["provisional_days_total"] == 30.0, \
            "SUBMITTED 10 + VERIFIED 20; DRAFT 5 and DISPUTED 15 excluded"
        assert summary["verified_days_total"] == 20.0, "only VERIFIED records"


class TestSeaServiceSegregationOfDuties:

    def test_sod_verify_same_recorder_enforced(self):
        """PRD section 3.4: "Verification moves `SUBMITTED` to `VERIFIED`
        (else `ERR_RECORD_NOT_VERIFIABLE`) under a segregation-of-duties rule:
        the verifying officer's `X-User-ID` must differ from the record's
        `entered_by_user_id`, else `ERR_SOD_VERIFY_SAME_RECORDER` (HTTP 403)."

        Design: Corner/rbac/sod_verify_same_recorder_enforced
        """
        mariner = create_mariner()
        vessel = create_vessel()
        recorder = make_officer_headers("co-100")
        record = create_sea_record(
            mariner["id"], vessel["id"], recorder_headers=recorder,
            start_date="2025-01-01T00:00:00Z", end_date="2025-01-10T00:00:00Z")
        assert record["entered_by_user_id"] == "co-100"
        submit_sea_record(mariner["id"], record["id"], headers=recorder)

        resp = api_client.verify_sea_service_record(
            mariner["id"], record["id"], recorder)
        validate_error(resp, ApiErrorId.ERR_SOD_VERIFY_SAME_RECORDER)

        verified = validate_success(
            api_client.verify_sea_service_record(
                mariner["id"], record["id"], make_officer_headers("co-200")))
        assert verified["record_status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == "co-200"


class TestUpgradeEligibility:

    def test_upgrade_window_and_grade_filters(self, officer_headers):
        """PRD section 3.4: "Qualifying days are the summed `verified_days` of
        `VERIFIED` records whose `rank_track` matches, whose `rank_grade` is
        at least the required serving grade, and whose `start_date` falls
        inside the lookback window (now minus the lookback in calendar
        months)."
        PRD section 3.4: "CHIEF_MATE demands 360 days within a 36-month
        lookback in the `DECK` track at serving grade 4 or higher"

        Design: Corner/calculations/upgrade_window_and_grade_filters
        """
        mariner = create_activated_mariner()
        vessel = create_vessel()
        # Qualifying: grade 5, in window (2024-06-01..2024-06-30, 30 days).
        create_verified_sea_record(
            mariner["id"], vessel["id"], position_code="OICNW", rank_grade=5,
            start_date="2024-06-01T00:00:00Z", end_date="2024-06-30T00:00:00Z")
        # Excluded by grade: grade 3 < 4.
        create_verified_sea_record(
            mariner["id"], vessel["id"], position_code="AB", rank_grade=3,
            start_date="2025-01-01T00:00:00Z", end_date="2025-01-30T00:00:00Z")
        # Excluded by window: start 2023-01-01 < window start 2023-08-01.
        create_verified_sea_record(
            mariner["id"], vessel["id"], position_code="OICNW", rank_grade=5,
            start_date="2023-01-01T00:00:00Z", end_date="2023-01-30T00:00:00Z")

        result = validate_success(
            api_client.get_upgrade_eligibility(
                mariner["id"], "CHIEF_MATE", officer_headers))
        assert result["verified_days_in_window"] == 30.0, \
            f"only the in-window grade-5 record counts, got {result['verified_days_in_window']}"
        assert result["eligible"] is False
        assert result["shortfall_days"] == 330.0
        assert result["course_requirement_met"] is False

    def _setup_boundary_mariners(self):
        """MA with 360 qualifying days (2024-01-01..2024-12-25, leap year),
        MB with 359 (2024-01-01..2024-12-24); both with a COMPLETED
        CHIEF_MATE-granting course."""
        ma = create_activated_mariner()
        mb = create_activated_mariner()
        vessel = create_vessel()
        create_verified_sea_record(
            ma["id"], vessel["id"], position_code="OICNW",
            start_date="2024-01-01T00:00:00Z", end_date="2024-12-25T00:00:00Z")
        create_verified_sea_record(
            mb["id"], vessel["id"], position_code="OICNW",
            start_date="2024-01-01T00:00:00Z", end_date="2024-12-24T00:00:00Z")
        course = create_course(course_code="CM-BOUNDARY",
                               grants_endorsement_code="CHIEF_MATE",
                               seat_capacity=10)
        _complete_course_for(ma["id"], course["id"])
        _complete_course_for(mb["id"], course["id"])
        return ma, mb

    def test_upgrade_eligibility_exactly_360_days_qualifies_read(
            self, officer_headers):
        """PRD section 3.4: "The day threshold is inclusive — exactly 360.0
        qualifies, 359.5 does not"
        PRD section 3.4: "The response reports `eligible` (both the day
        threshold and the course requirement met), `target_endorsement_code`,
        `verified_days_in_window`, `required_days`, `course_requirement_met`,
        `shortfall_days` (the gap between required and actual days, floored at
        zero), and `window_start`."

        Design: Difficulty/boundary_precision_check/upgrade_eligibility_exactly_360_days_qualifies
        """
        ma, mb = self._setup_boundary_mariners()
        result_a = validate_success(
            api_client.get_upgrade_eligibility(ma["id"], "CHIEF_MATE",
                                               officer_headers))
        assert result_a["eligible"] is True
        assert result_a["verified_days_in_window"] == 360.0
        assert result_a["shortfall_days"] == 0.0
        assert result_a["course_requirement_met"] is True

        result_b = validate_success(
            api_client.get_upgrade_eligibility(mb["id"], "CHIEF_MATE",
                                               officer_headers))
        assert result_b["eligible"] is False
        assert result_b["verified_days_in_window"] == 359.0
        assert result_b["shortfall_days"] == 1.0, \
            "course held equal; days are the sole discriminator"
        assert result_b["course_requirement_met"] is True

    def test_upgrade_eligibility_boundary_gates_credential_issuance(self):
        """PRD section 3.3: "A regulated upgrade — an `OFFICER_ENDORSEMENT`
        whose `endorsement_code` is one of the recognized upgrade targets
        CHIEF_MATE, MASTER, or SECOND_ENGINEER — additionally requires the
        mariner's upgrade eligibility (section 3.4) to hold for that target,
        else `ERR_UPGRADE_REQUIREMENTS_NOT_MET`."
        PRD section 3.4: "The day threshold is inclusive — exactly 360.0
        qualifies, 359.5 does not"

        Design: Difficulty/boundary_precision_check/upgrade_eligibility_exactly_360_days_qualifies
        """
        ma, mb = self._setup_boundary_mariners()
        payload = {
            "credential_type": "OFFICER_ENDORSEMENT",
            "endorsement_code": "CHIEF_MATE",
            "issue_date": "2026-08-02T00:00:00Z",
            "expiry_date": "2031-08-02T00:00:00Z",
        }
        issued = validate_success(
            api_client.create_credential(ma["id"], dict(payload), OFFICER),
            expected_status=201)
        assert issued["status"] == "VALID", \
            "OFFICER_ENDORSEMENT issued at exactly the 360-day threshold"

        resp = api_client.create_credential(mb["id"], dict(payload), OFFICER)
        validate_error(resp, ApiErrorId.ERR_UPGRADE_REQUIREMENTS_NOT_MET)
