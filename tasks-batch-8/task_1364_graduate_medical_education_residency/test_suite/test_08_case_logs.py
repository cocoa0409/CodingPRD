"""Procedure case logs and graduation minimums: the assist cap and primary
floor, the reject/resubmit cycle, the verify/void compensating pair, and the
empty-roster computed read (PRD §3.7)."""
from test_helpers import (
    PD, ApiClient, ApiErrorId, make_case_log, make_case_requirement,
    make_faculty_headers, make_rotation, make_verified_case_log,
    resident_headers, setup_graduation_ready,
    setup_program_with_active_resident, validate_error, validate_success,
    verify_case_log,
)


def _all_met(api, resident_id):
    data = validate_success(api.get_case_progress(resident_id, PD))
    return data["all_met"], data


class TestAssistCapAndPrimaryFloor:
    def _setup(self, api):
        """Resident ACTIVE; CaseRequirement MAJOR_SURGERY (4 effective, 2
        primary); a FINALIZED CCC review so the case gate is the only failing
        graduation precondition; 1 VERIFIED SURGEON + 10 VERIFIED ASSIST."""
        s = setup_graduation_ready(required_count=4, required_primary_count=2,
                                   surgeon_logs=1)
        resident, rotation = s["resident"], s["rotation"]
        for i in range(10):
            make_verified_case_log(resident, rotation,
                                   performed_date=f"2026-08-{10 + i:02d}",
                                   role="ASSIST")
        return s

    def test_cap_binds_and_primary_floor_blocks_graduation(self, api: ApiClient):
        """PRD §3.7: "The effective case total is the verified primary count
        plus the assist credit, and the requirement is met exactly when the
        effective total is at least `required_count` and the verified primary
        count is at least `required_primary_count`. The cap makes progress
        non-linear: past one quarter of the requirement, additional `ASSIST`
        logs add nothing."
        PRD §3.3: "every case requirement of the program evaluates to met for
        this resident (`ERR_CASE_REQUIREMENTS_UNMET`, HTTP 409; the requirement
        math lives in §3.7)".

        Design: Difficulty/combinatorial_formula/case_progress_assist_cap_and_primary_floor
        """
        s = self._setup(api)
        resident = s["resident"]
        # 1 SURGEON + 10 ASSIST: assist credit min(5.00, 0.25 x 4 = 1.00) =
        # 1.00, effective 2.00 < 4 and primary 1 < 2.
        all_met, data = _all_met(api, resident["id"])
        assert all_met is False
        assert isinstance(data["requirements"], list)

        resp = api.graduate_resident(resident["id"], PD)
        validate_error(resp, ApiErrorId.ERR_CASE_REQUIREMENTS_UNMET)
        assert validate_success(api.get_resident(resident["id"], PD))[
            "lifecycle_status"] == "ACTIVE"

    def test_meeting_both_floors_unlocks_graduation(self, api: ApiClient):
        """PRD §3.3: "Graduation is the `ProgramDirector`'s certification that
        training is complete, and it is gated on four conditions: the resident
        is `ACTIVE` (`ERR_RESIDENT_NOT_ACTIVE`); their `standing_status` is
        `GOOD_STANDING` (`ERR_STANDING_NOT_CLEAR`, HTTP 409); every case
        requirement of the program evaluates to met for this resident
        (`ERR_CASE_REQUIREMENTS_UNMET`, HTTP 409; the requirement math lives in
        §3.7); and at least one CCC review for the resident has reached
        `FINALIZED` (`ERR_NO_FINALIZED_CCC_REVIEW`, HTTP 409). Graduation moves
        the resident to `GRADUATED`".

        Design: Difficulty/combinatorial_formula/case_progress_assist_cap_and_primary_floor
        """
        s = self._setup(api)
        resident, rotation = s["resident"], s["rotation"]
        # Add 3 more VERIFIED SURGEON logs: 4 primary + 1.00 assist credit =
        # 5.00 >= 4 and primary 4 >= 2.
        for i in range(3):
            make_verified_case_log(resident, rotation,
                                   performed_date=f"2026-08-{20 + i:02d}",
                                   role="SURGEON")
        all_met, _ = _all_met(api, resident["id"])
        assert all_met is True
        graduated = validate_success(api.graduate_resident(resident["id"], PD))
        assert graduated["lifecycle_status"] == "GRADUATED"


class TestRejectResubmitCycle:
    def _setup(self, api):
        s = setup_program_with_active_resident()
        rotation = make_rotation(s["program"]["id"], name="Trauma Surgery",
                                 max_residents_per_block=3)
        log = make_case_log(s["resident"], rotation)
        return s, log

    def test_reject_returns_log_to_logged_via_resubmit(self, api: ApiClient):
        """PRD §3.7: "rejecting likewise requires `LOGGED` (same error) and
        moves it to `REJECTED` with the supplied `rejection_reason` recorded as
        `decision_reason`. The resident may resubmit a `REJECTED` log — their
        own, `ERR_OWNERSHIP_VIOLATION` otherwise — returning it to `LOGGED` for
        another look; resubmission from any other status fails with
        `ERR_CASE_LOG_NOT_LOGGED`."

        Design: Difficulty/non_linear_state_machine/case_log_reject_resubmit_cycle
        """
        s, log = self._setup(api)
        rejected = validate_success(api.reject_case_log(
            log["id"], {"rejection_reason": "Wrong category"},
            make_faculty_headers("ev-9")))
        assert rejected["status"] == "REJECTED"
        assert rejected["decision_reason"] == "Wrong category"

        resubmitted = validate_success(api.resubmit_case_log(
            log["id"], resident_headers(s["resident"])))
        assert resubmitted["status"] == "LOGGED"

    def test_cycle_then_verify_with_exact_versions(self, api: ApiClient):
        """PRD §3.7: "verifying requires `LOGGED` (otherwise
        `ERR_CASE_LOG_NOT_LOGGED`, HTTP 409) and moves the log to `VERIFIED`".
        PRD §2.5: "`version` (integer): starts at 1 at creation and increments
        by exactly 1 on every mutation of the resource".

        Design: Difficulty/non_linear_state_machine/case_log_reject_resubmit_cycle
        """
        s, log = self._setup(api)
        assert log["version"] == 1
        validate_success(api.reject_case_log(
            log["id"], {"rejection_reason": "Wrong category"},
            make_faculty_headers("ev-9")))
        validate_success(api.resubmit_case_log(
            log["id"], resident_headers(s["resident"])))
        verified = verify_case_log(log["id"], "ev-9")
        assert verified["status"] == "VERIFIED"
        # create 1, reject 2, resubmit 3, verify 4.
        assert verified["version"] == 4


class TestVerifyVoidConservation:
    def test_verify_then_void_restores_counts(self, api: ApiClient):
        """PRD §3.7: "a `ProgramDirector` may void a `VERIFIED` log (otherwise
        `ERR_CASE_LOG_NOT_VERIFIED`, HTTP 409), recording the `void_reason` as
        `decision_reason` and recomputing progress; voiding is the compensating
        action of verification, so a verify-then-void sequence leaves the
        verified counts unchanged."

        Design: Difficulty/compensating_invariant/verify_void_conserves_verified_case_count
        """
        s = setup_program_with_active_resident()
        resident = s["resident"]
        rotation = make_rotation(s["program"]["id"], name="General Surgery",
                                 max_residents_per_block=5)
        make_case_requirement(s["program"]["id"], required_count=2,
                              required_primary_count=1)
        log = make_case_log(resident, rotation)
        all_met0, _ = _all_met(api, resident["id"])
        assert all_met0 is False

        verified = verify_case_log(log["id"], "ev-1")
        assert verified["status"] == "VERIFIED"

        voided = validate_success(api.void_case_log(
            log["id"], {"void_reason": "duplicate log entry"}, PD))
        assert voided["status"] == "VOIDED"
        # One verified SURGEON (1.00 < 2) would still miss; after the void the
        # count is back at exactly zero — all_met never flips.
        all_met1, _ = _all_met(api, resident["id"])
        assert all_met1 is False

    def test_voided_log_never_reenters_progress(self, api: ApiClient):
        """PRD §3.7: "Progress against a requirement is computed only from
        `VERIFIED` logs — `LOGGED`, `REJECTED`, and `VOIDED` never count."

        Design: Difficulty/compensating_invariant/verify_void_conserves_verified_case_count
        """
        s = setup_program_with_active_resident()
        resident = s["resident"]
        rotation = make_rotation(s["program"]["id"], name="General Surgery",
                                 max_residents_per_block=5)
        make_case_requirement(s["program"]["id"], required_count=2,
                              required_primary_count=1)
        log1 = make_case_log(resident, rotation, performed_date="2026-08-03")
        verify_case_log(log1["id"], "ev-1")
        validate_success(api.void_case_log(
            log1["id"], {"void_reason": "duplicate log entry"}, PD))

        # A fresh VERIFIED SURGEON log: if the VOIDED log still counted, the
        # pair would read 2 primary >= required_count 2 and all_met would flip.
        log2 = make_case_log(resident, rotation, performed_date="2026-08-04")
        verify_case_log(log2["id"], "ev-1")
        all_met, _ = _all_met(api, resident["id"])
        assert all_met is False, "the VOIDED log must not count (1.00 < 2)"


class TestVerifyFromVerifiedRejected:
    def test_second_verify_rejected(self, api: ApiClient):
        """PRD §3.7: "verifying requires `LOGGED` (otherwise
        `ERR_CASE_LOG_NOT_LOGGED`, HTTP 409) and moves the log to `VERIFIED`".
        PRD §3.7: "`VERIFIED` and `VOIDED` are terminal."

        Design: Corner/state_machines/case_log_verify_from_verified_rejected
        """
        s = setup_program_with_active_resident()
        rotation = make_rotation(s["program"]["id"], name="General Surgery",
                                 max_residents_per_block=5)
        log = make_case_log(s["resident"], rotation)
        verify_case_log(log["id"], "ev-1")

        resp = api.verify_case_log(log["id"], make_faculty_headers("ev-1"))
        validate_error(resp, ApiErrorId.ERR_CASE_LOG_NOT_LOGGED)
        assert validate_success(api.get_case_log(log["id"], PD))[
            "status"] == "VERIFIED"


class TestCaseProgressEmptyRoster:
    def test_empty_progress_is_a_valid_read(self, api: ApiClient):
        """PRD §3.3: "The case-progress read returns `resident_id`, a
        `requirements` array with the per-requirement progress of §3.7, and an
        `all_met` flag that is exactly the graduation case-requirement gate."
        PRD §3.7: "The effective case total is the verified primary count plus
        the assist credit, and the requirement is met exactly when the
        effective total is at least `required_count` and the verified primary
        count is at least `required_primary_count`."

        Design: Corner/endpoints/case_progress_empty_roster_shape
        """
        s = setup_program_with_active_resident()
        make_case_requirement(s["program"]["id"],
                              procedure_category="ENDOSCOPY",
                              required_count=2, required_primary_count=1)
        resp = api.get_case_progress(s["resident"]["id"], PD)
        assert resp.status_code == 200
        data = validate_success(resp)
        assert data["resident_id"] == s["resident"]["id"]
        assert isinstance(data["requirements"], list)
        # One requirement defined -> exactly one progress entry.
        assert len(data["requirements"]) == 1
        assert data["all_met"] is False
