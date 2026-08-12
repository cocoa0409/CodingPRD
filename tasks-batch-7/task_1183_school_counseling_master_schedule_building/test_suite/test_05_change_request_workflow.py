"""Schedule change window: revision loop, posture/ownership precedence, OCC."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_student_headers, make_counselor_headers,
    make_admin_headers, setup_counselor,
    setup_change_window_scenario, entry_for, make_change_request,
    claim_change_request, approve_change_request, get_term_version,
)

ADMIN = TEST_USERS["admin_headers"]


def _two_course_window(api, term_code, counselor_name):
    """CHANGE_WINDOW term: course A at period 1, course B at period 2;
    s1 enrolled in A's section, s2 enrolled in B's section."""
    return setup_change_window_scenario(
        courses=[{"course_code": f"{term_code}-A", "subject_area": "ELECTIVE"},
                 {"course_code": f"{term_code}-B", "subject_area": "ELECTIVE"}],
        students=[{"ref": "S001", "requests": [(0, 1)]},
                  {"ref": "S002", "requests": [(1, 1)]}],
        section_specs={0: [{"period": 1, "capacity": 32}],
                       1: [{"period": 2, "capacity": 32}]},
        term_code=term_code, counselor_name=counselor_name)


class TestChangeRequestRevisionCycle:
    def test_revision_loop_resets_reviewed_by(self, api):
        """PRD §3.5: "the student may then resubmit while the window remains
        open, returning the request `REVISED` → `SUBMITTED` with
        `reviewed_by_counselor_id` reset to null."

        Design: Difficulty/non_linear_state_machine/change_request_revision_cycle
        """
        sc = _two_course_window(api, "2029-FALL", "C Five")
        counselor = sc["counselor"]
        s_cyc = sc["students"][0]
        sec_b = sc["sections"][1][0]
        entry_a = entry_for(api, s_cyc["id"], sc["sections"][0][0]["id"])
        req = make_change_request(s_cyc["id"], sc["term"]["id"], "SWAP",
                                  drop_entry_id=entry_a["id"], add_section_id=sec_b["id"],
                                  reason="Need different period for job")
        claim_change_request(req["id"], counselor["id"])
        revised = validate_success(api.return_change_request_for_revision(
            req["id"], {"revision_note": "Please justify the swap more fully"},
            make_counselor_headers(counselor["id"])), 200)
        assert revised["state"] == "REVISED"
        resub = validate_success(api.resubmit_change_request(
            req["id"], make_student_headers(s_cyc["id"])), 200)
        assert resub["state"] == "SUBMITTED", "the loop must close back to SUBMITTED"
        assert resub["reviewed_by_counselor_id"] is None, "loop state must not be sticky"

    def test_revision_loop_is_reentrant(self, api):
        """PRD §3.5: "The counselor who owns the student's caseload — and only
        that counselor — claims a `SUBMITTED` request while `change_window_open`
        is true, moving it `SUBMITTED` → `COUNSELOR_REVIEW`" — after a
        resubmission the request is `SUBMITTED` again, so a fresh claim succeeds.

        Design: Difficulty/non_linear_state_machine/change_request_revision_cycle
        """
        sc = _two_course_window(api, "2029-FALL", "C Five")
        counselor = sc["counselor"]
        s_cyc = sc["students"][0]
        sec_b = sc["sections"][1][0]
        entry_a = entry_for(api, s_cyc["id"], sc["sections"][0][0]["id"])
        req = make_change_request(s_cyc["id"], sc["term"]["id"], "SWAP",
                                  drop_entry_id=entry_a["id"], add_section_id=sec_b["id"],
                                  reason="Need different period for job")
        claim_change_request(req["id"], counselor["id"])
        get_success_data(api.return_change_request_for_revision(
            req["id"], {"revision_note": "Please justify the swap more fully"},
            make_counselor_headers(counselor["id"])))
        get_success_data(api.resubmit_change_request(req["id"], make_student_headers(s_cyc["id"])))
        reclaimed = validate_success(api.claim_change_request(
            req["id"], make_counselor_headers(counselor["id"])), 200)
        assert reclaimed["state"] == "COUNSELOR_REVIEW", "the cycle must be re-entrant"
        assert reclaimed["reviewed_by_counselor_id"] == counselor["id"]


class TestPostureVsCapacityConflict:
    def _setup(self, api):
        sc = setup_change_window_scenario(
            courses=[{"course_code": "PP-F", "subject_area": "ELECTIVE"},
                     {"course_code": "PP-B", "subject_area": "ELECTIVE"}],
            students=[{"ref": "F001", "requests": [(0, 1)]},
                      {"ref": "F002", "requests": [(0, 1)]},
                      {"ref": "PP01", "requests": [(1, 1)]}],
            section_specs={0: [{"period": 1, "capacity": 1}],
                           1: [{"period": 2, "capacity": 32}]},
            term_code="2032-FALL", counselor_name="C Nine", open_window=False)
        return sc

    def test_posture_beats_capacity_on_change_create(self, api):
        """PRD §3.5: "Filing outside the change window is rejected with
        `ERR_INVALID_TERM_POSTURE`"
        PRD §2.8: "Once everything exists, the term-posture gate fires
        (`ERR_INVALID_TERM_POSTURE`)"

        Design: Difficulty/priority_pair_validation_conflict/posture_vs_capacity_conflict
        """
        sc = self._setup(api)
        s_pp = sc["students"][2]
        sec_full = sc["sections"][0][0]
        assert sec_full["enrolled_count"] == sec_full["capacity"] == 1
        resp = api.create_change_request({
            "student_id": s_pp["id"], "term_id": sc["term"]["id"], "kind": "ADD",
            "add_section_id": sec_full["id"], "reason": "Attempt while window closed",
        }, make_student_headers(s_pp["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_TERM_POSTURE, 409)

    def test_posture_error_not_section_full(self, api):
        """PRD §2.8: "a request failing several checks reports the earliest one.
        ... Once everything exists, the term-posture gate fires
        (`ERR_INVALID_TERM_POSTURE`)" — the full target section never surfaces
        `ERR_SECTION_FULL` while the posture gate blocks the filing.

        Design: Difficulty/priority_pair_validation_conflict/posture_vs_capacity_conflict
        """
        sc = self._setup(api)
        s_pp = sc["students"][2]
        sec_full = sc["sections"][0][0]
        resp = api.create_change_request({
            "student_id": s_pp["id"], "term_id": sc["term"]["id"], "kind": "ADD",
            "add_section_id": sec_full["id"], "reason": "Attempt while window closed",
        }, make_student_headers(s_pp["id"]))
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_INVALID_TERM_POSTURE"
        assert body["data"]["error_id"] != "ERR_SECTION_FULL", (
            "state gate (priority 5) must beat the business_fiscal capacity check"
        )


class TestOwnershipVsRequestShapeConflict:
    def _setup(self, api):
        return setup_change_window_scenario(
            courses=[{"course_code": "OWN-O", "subject_area": "ELECTIVE"},
                     {"course_code": "OWN-P", "subject_area": "ELECTIVE"}],
            students=[{"ref": "OW01", "requests": [(0, 1)]},
                      {"ref": "OT01", "requests": [(1, 1)]}],
            section_specs={0: [{"period": 1, "capacity": 32}],
                           1: [{"period": 2, "capacity": 32}]},
            term_code="2033-FALL", counselor_name="C Ten")

    def test_ownership_beats_payload_shape(self, api):
        """PRD §2.8: "then ownership (`ERR_FORBIDDEN_OWNERSHIP`, HTTP 403) ...
        Payload-shape validation (`ERR_INVALID_REQUEST`, HTTP 400) follows those
        guards."

        Design: Difficulty/priority_pair_validation_conflict/ownership_vs_request_shape_conflict
        """
        sc = self._setup(api)
        s_own, s_other = sc["students"][0], sc["students"][1]
        entry_other = entry_for(api, s_other["id"], sc["sections"][1][0]["id"])
        resp = api.create_change_request({
            "student_id": s_other["id"], "term_id": sc["term"]["id"], "kind": "DROP",
            "drop_entry_id": entry_other["id"], "reason": "short",
        }, make_student_headers(s_own["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, 403)

    def test_invalid_request_not_returned_for_foreign_owner(self, api):
        """PRD §2.8: "then ownership (`ERR_FORBIDDEN_OWNERSHIP`, HTTP 403) ...
        Payload-shape validation (`ERR_INVALID_REQUEST`, HTTP 400) follows those
        guards." A missing `reason` is a payload-shape failure, yet the foreign
        caller still sees the ownership error.

        Design: Difficulty/priority_pair_validation_conflict/ownership_vs_request_shape_conflict
        """
        sc = self._setup(api)
        s_own, s_other = sc["students"][0], sc["students"][1]
        entry_other = entry_for(api, s_other["id"], sc["sections"][1][0]["id"])
        resp = api.create_change_request({
            "student_id": s_other["id"], "term_id": sc["term"]["id"], "kind": "DROP",
            "drop_entry_id": entry_other["id"],
        }, make_student_headers(s_own["id"]))
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_FORBIDDEN_OWNERSHIP"
        assert body["data"]["error_id"] != "ERR_INVALID_REQUEST"


class TestCloseWindowGuard:
    def test_close_window_blocked_by_inflight_requests(self, api):
        """PRD §3.5: "it is refused with `ERR_CLOSE_WINDOW_BLOCKED` (HTTP 409)
        while any change request of the term remains in `SUBMITTED`,
        `COUNSELOR_REVIEW`, `REVISED`, or `APPROVED`."

        Design: Corner/state_machines/close_window_blocked_by_inflight_requests
        """
        sc = setup_change_window_scenario(
            courses=[{"course_code": "CW-1", "subject_area": "ELECTIVE"}],
            students=[{"ref": "CW01", "requests": [(0, 1)]}],
            section_specs={0: [{"period": 1, "capacity": 32}]},
            term_code="2047-FALL", counselor_name="C CW")
        s_cw = sc["students"][0]
        entry = entry_for(api, s_cw["id"], sc["sections"][0][0]["id"])
        make_change_request(s_cw["id"], sc["term"]["id"], "DROP",
                            drop_entry_id=entry["id"], reason="Blocking close for test")
        resp = api.close_change_window(sc["term"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CLOSE_WINDOW_BLOCKED, 409)


class TestSegregationOfDuties:
    def test_segregation_of_duties_same_actor_decide(self, api):
        """PRD §3.5: "Segregation of duties is enforced: the acting
        administrator's `X-User-ID` must differ from the request's
        `reviewed_by_counselor_id`, or the decision is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/segregation_of_duties_same_actor_decide
        """
        sc = setup_change_window_scenario(
            courses=[{"course_code": "SOD-1", "subject_area": "ELECTIVE"}],
            students=[{"ref": "SD01", "requests": [(0, 1)]}],
            section_specs={0: [{"period": 1, "capacity": 32}]},
            term_code="2056-FALL", counselor_name="C Sod")
        counselor = sc["counselor"]
        s_sod = sc["students"][0]
        entry = entry_for(api, s_sod["id"], sc["sections"][0][0]["id"])
        req = make_change_request(s_sod["id"], sc["term"]["id"], "DROP",
                                  drop_entry_id=entry["id"], reason="Dropping this course now")
        claim_change_request(req["id"], counselor["id"])
        resp = api.decide_change_request(req["id"], {
            "decision": "APPROVE", "expected_term_version": get_term_version(sc["term"]["id"]),
        }, make_admin_headers(counselor["id"]))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)


class TestOccOnDecide:
    def test_occ_stale_version_on_decide(self, api):
        """PRD §2.7: "On each, if `expected_term_version` does not match the
        term's current `version` — because the term's version has advanced since
        the client last read it, invalidating the client's view of window caps,
        seat tallies, conflict maps, or rebalance epoch — the request is rejected
        with `ERR_STALE_TERM_VERSION` (HTTP 412)."

        Design: Corner/endpoints/occ_stale_version_on_decide
        """
        sc = setup_change_window_scenario(
            courses=[{"course_code": "OCC-1", "subject_area": "ELECTIVE"}],
            students=[{"ref": "OC01", "requests": [(0, 1)]}],
            section_specs={0: [{"period": 1, "capacity": 32}]},
            term_code="2062-FALL", counselor_name="C Occ")
        counselor = sc["counselor"]
        s_occ = sc["students"][0]
        entry = entry_for(api, s_occ["id"], sc["sections"][0][0]["id"])
        req = make_change_request(s_occ["id"], sc["term"]["id"], "DROP",
                                  drop_entry_id=entry["id"], reason="Dropping for OCC test")
        claim_change_request(req["id"], counselor["id"])
        stale_version = get_term_version(sc["term"]["id"]) - 1
        resp = api.decide_change_request(req["id"], {
            "decision": "APPROVE", "expected_term_version": stale_version,
        }, ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_TERM_VERSION, 412)


class TestCounselorClaimOwnership:
    def test_counselor_cannot_claim_outside_caseload(self, api):
        """PRD §3.5: "The counselor who owns the student's caseload — and only
        that counselor — claims a `SUBMITTED` request while `change_window_open`
        is true... anyone else is turned away with `ERR_FORBIDDEN_OWNERSHIP`."

        Design: Corner/rbac/counselor_cannot_claim_outside_caseload
        """
        c_a = setup_counselor(max_caseload=50, full_name="C A")
        c_b = setup_counselor(max_caseload=50, full_name="C B")
        sc = setup_change_window_scenario(
            courses=[{"course_code": "OWN-C", "subject_area": "ELECTIVE"}],
            students=[{"ref": "OC01", "requests": [(0, 1)]}],
            section_specs={0: [{"period": 1, "capacity": 32}]},
            term_code="2069-FALL", counselor_name="C A2")
        # Reassign: the scenario built its own counselor; use c_a as the owner instead.
        # Simpler: the scenario counselor IS the owner; c_b is the outsider.
        owner = sc["counselor"]
        s_own = sc["students"][0]
        entry = entry_for(api, s_own["id"], sc["sections"][0][0]["id"])
        req = make_change_request(s_own["id"], sc["term"]["id"], "DROP",
                                  drop_entry_id=entry["id"], reason="Claim ownership check")
        assert req["state"] == "SUBMITTED"
        resp = api.claim_change_request(req["id"], make_counselor_headers(c_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, 403)
        ok = validate_success(api.claim_change_request(
            req["id"], make_counselor_headers(owner["id"])), 200)
        assert ok["state"] == "COUNSELOR_REVIEW"
