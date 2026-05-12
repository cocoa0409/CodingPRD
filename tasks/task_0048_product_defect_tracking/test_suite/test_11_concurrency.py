"""Concurrency: race conditions on first-writer-wins serialisation points.

PRD §3 prose pins specific error IDs for losers in each race; this file
exercises only the races whose losing error_id is explicitly named in PRD
prose. Where PRD names the loser explicitly we assert that error_id;
otherwise we use validate_error_is_one_of so the test does not
over-constrain the implementation.
"""
from __future__ import annotations

import pytest

from prd_bench_local_runner.testing import (
    assert_exactly_one_succeeds,
    run_race,
    validate_error_is_one_of,
)

from test_helpers import (
    ApiErrorId,
    api_client,
    assign_defect,
    create_defect,
    create_defect_payload,
    create_team_member,
    duplicate_link_payload,
    latest_fix_record,
    make_qa_engineer_headers,
    make_triage_manager_headers,
    request_severity_override,
    setup_basic_module,
    setup_defect_in_state,
    setup_module_at_quota_boundary,
    start_progress,
    submit_fix,
    verify_payload,
)


class TestVerifyRace:
    def test_two_qa_engineers_one_passed_one_failed(self):
        """PRD §3.7: "Two QAEngineer operators racing to verify the same
        FIXED defect with opposing outcomes serialise on Defect.status:
        exactly one verification commits, and the loser, observing the
        defect now in either VERIFIED or REOPENED, receives
        ERR_DEFECT_NOT_FIXED."
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "FIXED")
        fix_id = latest_fix_record(team, defect)["id"]
        # Create a second QAEngineer so both verifiers are independent of
        # the developer (PRD §3.7 requires verifier independence).
        qa2 = create_team_member(
            team.project, "QA_ENGINEER",
            triage_headers=team.triage_headers,
        )
        results = run_race(
            lambda: api_client.verify_defect(
                defect["id"],
                verify_payload(outcome="PASSED", fix_record_id=fix_id),
                team.qa_headers,
            ),
            lambda: api_client.verify_defect(
                defect["id"],
                verify_payload(outcome="FAILED", fix_record_id=fix_id),
                make_qa_engineer_headers(qa2["id"]),
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser_resp = outcome["failures"][0]
        validate_error_is_one_of(
            loser_resp,
            [ApiErrorId.ERR_DEFECT_NOT_FIXED.value],
        )


class TestModuleQuotaRace:
    def test_two_reporters_filing_last_defect_serialise(self):
        """PRD §3.2: "When two reporters race to file the last defect
        against a module whose quota_remaining is 1, the system
        serialises them on the module's active_defect_count increment:
        exactly one report commits, and the loser receives
        ERR_MODULE_QUOTA_EXCEEDED."
        """
        # initial_defect_quota=2, pre-fill ONE so quota_remaining=1.
        team, module = setup_basic_module(initial_defect_quota=2)
        create_defect(team, module)  # quota_remaining now == 1
        # Two simultaneous create_defect attempts.
        results = run_race(
            lambda: api_client.create_defect(
                create_defect_payload(
                    project_id=team.project["id"],
                    module_id=module["id"],
                    reporter_id=team.developer["id"],
                    title="race-A",
                ),
                team.developer_headers,
            ),
            lambda: api_client.create_defect(
                create_defect_payload(
                    project_id=team.project["id"],
                    module_id=module["id"],
                    reporter_id=team.developer["id"],
                    title="race-B",
                ),
                team.developer_headers,
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser_resp = outcome["failures"][0]
        validate_error_is_one_of(
            loser_resp,
            [ApiErrorId.ERR_MODULE_QUOTA_EXCEEDED.value],
        )


class TestOverrideApproveRejectRace:
    def test_approve_and_reject_race_on_same_override(self):
        """PRD §3.3: "Two TriageManager operators racing to approve and
        reject the same pending override serialise on
        SeverityOverride.status: exactly one transition commits, and the
        loser sees the override in its new terminal state and receives
        ERR_OVERRIDE_NOT_PENDING."
        """
        team, module = setup_basic_module()
        defect = create_defect(team, module, severity="MAJOR")
        # Create two TriageManagers; the override is requested by a
        # third actor (team.developer) so neither racer violates
        # independence.
        triage_a = create_team_member(
            team.project, "TRIAGE_MANAGER",
            triage_headers=team.triage_headers,
        )
        triage_b = create_team_member(
            team.project, "TRIAGE_MANAGER",
            triage_headers=team.triage_headers,
        )
        override = request_severity_override(
            team, defect, requested_severity="BLOCKER",
            requester=team.developer,
        )
        results = run_race(
            lambda: api_client.approve_severity_override(
                override["id"],
                make_triage_manager_headers(triage_a["id"]),
            ),
            lambda: api_client.reject_severity_override(
                override["id"],
                make_triage_manager_headers(triage_b["id"]),
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser_resp = outcome["failures"][0]
        validate_error_is_one_of(
            loser_resp,
            [ApiErrorId.ERR_OVERRIDE_NOT_PENDING.value],
        )


class TestDuplicateLinkRace:
    def test_two_links_against_same_duplicate_serialise(self):
        """PRD §3.11: "Two duplicate-link requests targeting the same
        duplicate_defect_id against different canonicals race and
        serialise on Defect.canonical_defect_id: exactly one link commits,
        and the loser sees the duplicate defect already linked and
        receives ERR_DEFECT_ALREADY_LINKED."
        """
        team, module = setup_basic_module(initial_defect_quota=5)
        dup = create_defect(team, module, title="dup")
        canon_a = create_defect(team, module, title="canon-A")
        canon_b = create_defect(team, module, title="canon-B")
        results = run_race(
            lambda: api_client.create_duplicate_link(
                duplicate_link_payload(
                    duplicate_defect_id=dup["id"],
                    canonical_defect_id=canon_a["id"],
                    similarity_score=0.9,
                ),
                team.triage_headers,
            ),
            lambda: api_client.create_duplicate_link(
                duplicate_link_payload(
                    duplicate_defect_id=dup["id"],
                    canonical_defect_id=canon_b["id"],
                    similarity_score=0.9,
                ),
                team.triage_headers,
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser_resp = outcome["failures"][0]
        validate_error_is_one_of(
            loser_resp,
            [
                ApiErrorId.ERR_DEFECT_ALREADY_LINKED.value,
                ApiErrorId.ERR_INVALID_DUPLICATE_LINK.value,
            ],
        )
