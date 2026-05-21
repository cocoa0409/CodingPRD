"""CalibrationSession lifecycle and the calibration commit cascade.

This file covers:
* CalibrationSession creation + facilitator-conflict guard.
* Proposals update + bell_curve_distribution recomputation.
* Commit-time bell-curve compliance + coverage gates.
* The three-hop cascade: LOCKED -> FINALIZED, auto PIPCase, Employee
  status flip to ON_PIP.
"""
from __future__ import annotations

from test_helpers import (
    TEST_USERS,
    create_calibration_session_payload,
    create_employee_with_role,
    create_open_cycle,
    proposals_payload,
    setup_department_with_locked_cases,
    attach_calibration_session,
    validate_error,
    validate_success,
)


# ===========================================================================
# Facilitator conflict (PRD §2.11, §3.5)
# ===========================================================================
class TestFacilitatorConflict:

    def test_facilitator_cannot_be_a_case_manager_in_department(self, api):
        """PRD §2.11: "the calibration facilitator: a
        `CalibrationSession`'s `facilitator_employee_id` must not equal
        the `manager_employee_id` of any `ReviewCase` whose subject
        belongs to that session's `department`. Violations at session
        creation, start, or commit all surface as
        `ERR_FACILITATOR_CONFLICT` with HTTP 422."."""
        dept_bundle = setup_department_with_locked_cases(
            ratings=("MEETS", "MEETS"),
            bell_curve_target={
                "OUTSTANDING": 0, "EXCEEDS": 0, "MEETS": 100,
                "NEEDS_IMPROVEMENT": 0, "UNSATISFACTORY": 0,
            },
        )
        # Try creating a CalibrationSession whose facilitator is one of
        # the case managers (clearly violates segregation).
        offending_mgr = dept_bundle.managers[0]
        # Mint HRBP headers for the offending manager id so the role is
        # authorised but identity collides.
        from test_helpers.test_users import make_hrbp_headers
        rogue_facilitator_headers = make_hrbp_headers(offending_mgr.id)
        res = api.create_calibration_session(
            dept_bundle.cycle["id"],
            create_calibration_session_payload(
                department=dept_bundle.department,
                facilitator_employee_id=offending_mgr.id,
            ),
            rogue_facilitator_headers,
        )
        validate_error(res, "ERR_FACILITATOR_CONFLICT")


# ===========================================================================
# Proposals + bell_curve_distribution
# ===========================================================================
class TestProposalsAndDistribution:

    def test_distribution_recomputed_on_proposals_patch(self, api):
        """PRD §3.5: "Each call replaces `proposed_ratings` in its
        entirety with an ordered list of `{review_case_id,
        proposed_rating}` pairs and immediately recomputes
        `bell_curve_distribution`: for each of the five buckets, the
        bucket count is the number of pairs whose `proposed_rating`
        equals that bucket."."""
        dept_bundle = setup_department_with_locked_cases(
            ratings=("MEETS", "MEETS", "EXCEEDS"),
            bell_curve_target={
                "OUTSTANDING": 0, "EXCEEDS": 33, "MEETS": 67,
                "NEEDS_IMPROVEMENT": 0, "UNSATISFACTORY": 0,
            },
        )
        cs = validate_success(api.create_calibration_session(
            dept_bundle.cycle["id"],
            create_calibration_session_payload(
                department=dept_bundle.department,
                facilitator_employee_id=dept_bundle.facilitator.id,
            ),
            dept_bundle.facilitator.headers,
        ), 201)
        pairs = [
            {"review_case_id": rc["id"], "proposed_rating": r}
            for rc, r in zip(dept_bundle.review_cases,
                             ("MEETS", "MEETS", "EXCEEDS"))
        ]
        res = api.update_calibration_proposals(
            dept_bundle.cycle["id"], cs["id"],
            proposals_payload(pairs),
            dept_bundle.facilitator.headers,
        )
        upd = validate_success(res, 200)
        assert upd["bell_curve_distribution"]["MEETS"] == 2
        assert upd["bell_curve_distribution"]["EXCEEDS"] == 1
        assert upd["bell_curve_distribution"]["OUTSTANDING"] == 0


# ===========================================================================
# Commit-time gates
# ===========================================================================
class TestCommitGates:

    def test_commit_fails_when_coverage_incomplete(self, api):
        """PRD §3.5: "every locked `ReviewCase` whose subject's
        `department` matches the session's `department` appears in
        `proposed_ratings` exactly once (otherwise
        `ERR_CALIBRATION_COVERAGE`)"."""
        dept_bundle = setup_department_with_locked_cases(
            ratings=("MEETS", "MEETS"),
            bell_curve_target={
                "OUTSTANDING": 0, "EXCEEDS": 0, "MEETS": 100,
                "NEEDS_IMPROVEMENT": 0, "UNSATISFACTORY": 0,
            },
        )
        cs = validate_success(api.create_calibration_session(
            dept_bundle.cycle["id"],
            create_calibration_session_payload(
                department=dept_bundle.department,
                facilitator_employee_id=dept_bundle.facilitator.id,
            ),
            dept_bundle.facilitator.headers,
        ), 201)
        # Only one of two cases included in proposed_ratings.
        validate_success(api.update_calibration_proposals(
            dept_bundle.cycle["id"], cs["id"],
            proposals_payload([
                {"review_case_id": dept_bundle.review_cases[0]["id"],
                 "proposed_rating": "MEETS"},
            ]),
            dept_bundle.facilitator.headers,
        ), 200)
        validate_success(api.start_calibration_session(
            dept_bundle.cycle["id"], cs["id"],
            dept_bundle.facilitator.headers,
        ), 200)
        res = api.commit_calibration_session(
            dept_bundle.cycle["id"], cs["id"],
            dept_bundle.facilitator.headers,
        )
        validate_error(res, "ERR_CALIBRATION_COVERAGE")

    def test_commit_fails_when_bell_curve_violated(self, api):
        """PRD §3.5: "the bell-curve compliance check passes (otherwise
        `ERR_BELL_CURVE_VIOLATED`)...Every bucket's absolute difference
        between observed and target percentage points must be at most
        5; any bucket exceeding the 5-percentage-point tolerance fails
        compliance."."""
        dept_bundle = setup_department_with_locked_cases(
            ratings=("MEETS", "MEETS", "MEETS"),
            # Target says 100% OUTSTANDING — proposing all MEETS will be
            # off by >5pp in OUTSTANDING and MEETS buckets simultaneously.
            bell_curve_target={
                "OUTSTANDING": 100, "EXCEEDS": 0, "MEETS": 0,
                "NEEDS_IMPROVEMENT": 0, "UNSATISFACTORY": 0,
            },
        )
        attach_calibration_session(
            dept_bundle, proposed_ratings=["MEETS", "MEETS", "MEETS"],
        )
        res = api.commit_calibration_session(
            dept_bundle.cycle["id"],
            dept_bundle.calibration_session["id"],
            dept_bundle.facilitator.headers,
        )
        validate_error(res, "ERR_BELL_CURVE_VIOLATED")

    def test_commit_succeeds_and_finalizes_each_case(self, api):
        """PRD §3.5: "A successful commit drives a three-hop cascade.
        First, each `ReviewCase` named in `proposed_ratings` transitions
        `LOCKED → FINALIZED` with its `final_rating` set to the proposed
        value...".
        """
        dept_bundle = setup_department_with_locked_cases(
            ratings=("MEETS", "MEETS"),
            bell_curve_target={
                "OUTSTANDING": 0, "EXCEEDS": 0, "MEETS": 100,
                "NEEDS_IMPROVEMENT": 0, "UNSATISFACTORY": 0,
            },
        )
        attach_calibration_session(
            dept_bundle, proposed_ratings=["MEETS", "MEETS"],
        )
        validate_success(api.commit_calibration_session(
            dept_bundle.cycle["id"],
            dept_bundle.calibration_session["id"],
            dept_bundle.facilitator.headers,
        ), 200)
        for rc in dept_bundle.review_cases:
            updated = validate_success(api.get_review_case(
                dept_bundle.cycle["id"], rc["id"],
                dept_bundle.hrbp.headers,
            ), 200)
            assert updated["status"] == "FINALIZED"
            assert updated["final_rating"] == "MEETS"


# ===========================================================================
# Three-hop cascade — calibration commit -> PIPCase -> Employee.status
# ===========================================================================
class TestCalibrationCommitCascade:

    def test_finalizing_with_needs_improvement_creates_pip(self, api):
        """PRD §3.5: "Second, any newly `FINALIZED` case whose
        `final_rating` is `NEEDS_IMPROVEMENT` or `UNSATISFACTORY`
        triggers automatic creation of a `PIPCase` in `ACTIVE` status
        for that subject. Third, the subject's `Employee.status` flips
        from `ACTIVE` to `ON_PIP`."

        Depth-3 cascade.

        # difficulty: transitive_cascade/calibration_commit_to_pip_to_employee_status
        """
        dept_bundle = setup_department_with_locked_cases(
            ratings=("MEETS", "MEETS", "NEEDS_IMPROVEMENT"),
            # Distribution: 2/3=66, 0, 33 split — choose target tolerant
            # for the proposed mix (we will propose 2 MEETS + 1 NI).
            bell_curve_target={
                "OUTSTANDING": 0, "EXCEEDS": 0, "MEETS": 67,
                "NEEDS_IMPROVEMENT": 33, "UNSATISFACTORY": 0,
            },
        )
        attach_calibration_session(
            dept_bundle,
            proposed_ratings=["MEETS", "MEETS", "NEEDS_IMPROVEMENT"],
        )
        validate_success(api.commit_calibration_session(
            dept_bundle.cycle["id"],
            dept_bundle.calibration_session["id"],
            dept_bundle.facilitator.headers,
        ), 200)
        # Subject 0 and 1 (MEETS) remain ACTIVE; subject 2 (NI) is ON_PIP.
        for i, subj in enumerate(dept_bundle.subjects):
            emp = validate_success(api.get_employee(
                subj["id"], TEST_USERS["admin_headers"],
            ), 200)
            if i == 2:
                assert emp["status"] == "ON_PIP", (
                    "PRD §3.5: NEEDS_IMPROVEMENT must flip subject to ON_PIP"
                )
            else:
                assert emp["status"] == "ACTIVE"
        # One PIPCase for subj[2] with status ACTIVE.
        pip_resp = api.list_pip_cases(
            dept_bundle.cycle["id"], dept_bundle.hrbp.headers,
            params={"subject_employee_id": dept_bundle.subjects[2]["id"]},
        )
        pips = validate_success(pip_resp, 200)
        # Some implementations return list as data directly; normalise.
        if isinstance(pips, dict):
            pips = pips.get("data", [])
        assert len(pips) == 1
        assert pips[0]["status"] == "ACTIVE"
        assert pips[0]["duration_days"] == 60  # PRD §3.6 NI -> 60 days

    def test_unsatisfactory_creates_30_day_pip(self, api):
        """PRD §3.6: "The PIP's duration is server-pinned by the
        triggering rating — 60 days when the triggering rating is
        `NEEDS_IMPROVEMENT`, and 30 days when it is `UNSATISFACTORY`".

        Second variant of the calibration -> PIP -> Employee.status
        depth-3 cascade with the alternate rating.

        # difficulty: transitive_cascade/calibration_commit_to_pip_to_employee_status
        """
        dept_bundle = setup_department_with_locked_cases(
            ratings=("MEETS", "UNSATISFACTORY"),
            bell_curve_target={
                "OUTSTANDING": 0, "EXCEEDS": 0, "MEETS": 50,
                "NEEDS_IMPROVEMENT": 0, "UNSATISFACTORY": 50,
            },
        )
        attach_calibration_session(
            dept_bundle, proposed_ratings=["MEETS", "UNSATISFACTORY"],
        )
        validate_success(api.commit_calibration_session(
            dept_bundle.cycle["id"],
            dept_bundle.calibration_session["id"],
            dept_bundle.facilitator.headers,
        ), 200)
        pips = validate_success(api.list_pip_cases(
            dept_bundle.cycle["id"], dept_bundle.hrbp.headers,
            params={"subject_employee_id": dept_bundle.subjects[1]["id"]},
        ), 200)
        if isinstance(pips, dict):
            pips = pips.get("data", [])
        assert len(pips) == 1
        assert pips[0]["duration_days"] == 30
