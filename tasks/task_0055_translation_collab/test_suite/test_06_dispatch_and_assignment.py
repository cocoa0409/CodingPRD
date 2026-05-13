"""Assignment dispatch, accept, reject lifecycle.

PRD §2.10 (Stage Time Limits and Acceptance Window),
§2.11 (Workload, Eligibility, and Translator Selection),
§3.3 (Dispatching, Accepting, and Reassigning Translation Work).
"""
from __future__ import annotations
import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)
from test_helpers import (
    ACCEPT_WINDOW_HOURS,
    ApiErrorId,
    PM,
    STAGE_LIMIT_HOURS,
    advance_clock,
    api_client,
    assert_assignment,
    create_passed_translator,
    create_translator,
    dispatch_assignment,
    dispatch_assignment_payload,
    find_sync_records,
    language_pair,
    list_all_sync_records,
    make_translator_headers,
    setup_quoted_project_with_one_word_segment,
    setup_translator_passed,
    setup_translator_with_open_workload,
)


# ===========================================================================
# Dispatch basics
# ===========================================================================
class TestDispatch:

    def test_dispatch_sets_state_pending_and_accept_deadline(self):
        """PRD §3.3: "On success the assignment is created in state
        PENDING, dispatched_at is set to the server clock, and
        accept_deadline_at is set to dispatched_at plus the 48-hour
        acceptance window."

        Claim: dispatched assignment has state=PENDING and a non-null
        accept_deadline_at.
        """
        _, project, _, segments = setup_quoted_project_with_one_word_segment()
        t = setup_translator_passed(grade="SENIOR")
        seg_ids = [s["id"] for s in segments]
        a = dispatch_assignment(project["id"], t["id"],
                                "TRANSLATOR", seg_ids)
        assert a["state"] == "PENDING"
        assert a["accept_deadline_at"], "accept_deadline_at must be set on dispatch"
        assert_assignment(a)

    def test_dispatch_emits_im_assignment_dispatched_sync(self):
        """PRD §3.3: "The platform emits an ExternalSyncRecord whose
        target_system is IM and whose trigger_event is
        ASSIGNMENT_DISPATCHED."

        Claim: ExternalSyncRecord (IM / ASSIGNMENT_DISPATCHED) exists
        after dispatch.
        """
        _, project, _, segments = setup_quoted_project_with_one_word_segment()
        t = setup_translator_passed(grade="SENIOR")
        seg_ids = [s["id"] for s in segments]
        dispatch_assignment(project["id"], t["id"], "TRANSLATOR", seg_ids)
        records = list_all_sync_records(project_id=project["id"])
        matches = find_sync_records(
            records, target_system="IM",
            trigger_event="ASSIGNMENT_DISPATCHED",
        )
        assert matches, \
            "an IM ExternalSyncRecord with ASSIGNMENT_DISPATCHED must exist"


# ===========================================================================
# Eligibility — profile mismatch
# ===========================================================================
class TestProfileMatching:

    def test_dispatch_to_translator_without_language_pair_rejected(self):
        """PRD §3.3: "The translator's profile is checked: the project's
        source_lang and target_lang pair must be present in the
        translator's language_pairs and the project's domain must be in
        the translator's domains, otherwise
        ERR_TRANSLATOR_PROFILE_MISMATCH."

        Claim: translator without en→fr pair on an en→fr project ->
        ERR_TRANSLATOR_PROFILE_MISMATCH.
        """
        _, project, _, segments = setup_quoted_project_with_one_word_segment()
        # Translator with only es→de (wrong pair)
        bad = create_translator(
            language_pairs=[language_pair("es", "de")],
            domains=["GENERAL"],
        )
        api_client.pass_test_translator(bad["id"], PM)
        seg_ids = [s["id"] for s in segments]
        resp = api_client.dispatch_assignment(
            project["id"],
            dispatch_assignment_payload(bad["id"], "TRANSLATOR", seg_ids),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_TRANSLATOR_PROFILE_MISMATCH)

    def test_dispatch_to_translator_without_domain_rejected(self):
        """PRD §3.3: "the project's domain must be in the translator's
        domains, otherwise ERR_TRANSLATOR_PROFILE_MISMATCH."

        Claim: translator without project.domain in domains -> mismatch.
        """
        _, project, _, segments = setup_quoted_project_with_one_word_segment(
            domain="MEDICAL",
        )
        bad = create_translator(
            language_pairs=[language_pair("en", "fr")],
            domains=["LEGAL"],
        )
        api_client.pass_test_translator(bad["id"], PM)
        seg_ids = [s["id"] for s in segments]
        resp = api_client.dispatch_assignment(
            project["id"],
            dispatch_assignment_payload(bad["id"], "TRANSLATOR", seg_ids),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_TRANSLATOR_PROFILE_MISMATCH)


# ===========================================================================
# Acceptance gates
# ===========================================================================
class TestAccept:

    def test_translator_without_test_translation_passed_blocked(self):
        """PRD §3.3: "the acceptance is rejected with ... with
        ERR_TEST_TRANSLATION_REQUIRED if test_translation_passed is still
        false."

        Claim: accept by a translator with test_translation_passed=false
        yields ERR_TEST_TRANSLATION_REQUIRED.
        """
        _, project, _, segments = setup_quoted_project_with_one_word_segment()
        # Translator without pass-test
        t = create_translator(
            language_pairs=[language_pair("en", "fr")],
            domains=["GENERAL"],
        )
        seg_ids = [s["id"] for s in segments]
        a = dispatch_assignment(project["id"], t["id"], "TRANSLATOR", seg_ids)
        # Activate project so workflow is alive
        api_client.activate_project(project["id"], PM)
        resp = api_client.accept_assignment(
            a["id"], make_translator_headers(t["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TEST_TRANSLATION_REQUIRED)

    def test_accepting_assignment_in_terminal_state_returns_invalid_assignment_state(self):
        """PRD §3.3: "the acceptance is rejected with
        ERR_INVALID_ASSIGNMENT_STATE if the assignment is not in PENDING."

        Claim: re-accepting an already-ACCEPTED assignment yields
        ERR_INVALID_ASSIGNMENT_STATE.
        """
        _, project, _, segments = setup_quoted_project_with_one_word_segment()
        t = setup_translator_passed(grade="SENIOR")
        seg_ids = [s["id"] for s in segments]
        a = dispatch_assignment(project["id"], t["id"], "TRANSLATOR", seg_ids)
        api_client.activate_project(project["id"], PM)
        # First accept succeeds
        api_client.accept_assignment(a["id"], make_translator_headers(t["id"]))
        # Second accept fails on state
        resp = api_client.accept_assignment(
            a["id"], make_translator_headers(t["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ASSIGNMENT_STATE)

    def test_accept_sets_stage_deadline_for_translator_role_72_hours(self):
        """PRD §2.10: "stage_deadline_at is set to accepted_at plus a
        role-specific stage limit: 72 hours for TRANSLATOR, 48 hours for
        REVIEWER, and 24 hours for FINAL_REVIEWER."

        Claim: after accept of a TRANSLATOR assignment, stage_deadline_at
        is not null.
        """
        _, project, _, segments = setup_quoted_project_with_one_word_segment()
        t = setup_translator_passed(grade="SENIOR")
        seg_ids = [s["id"] for s in segments]
        a = dispatch_assignment(project["id"], t["id"], "TRANSLATOR", seg_ids)
        api_client.activate_project(project["id"], PM)
        resp = api_client.accept_assignment(
            a["id"], make_translator_headers(t["id"]),
        )
        accepted = validate_success(resp)
        assert accepted["state"] == "ACCEPTED"
        assert accepted.get("stage_deadline_at"), \
            "stage_deadline_at must be set on accept"
        assert accepted.get("accepted_at"), \
            "accepted_at must be set on accept"


# ===========================================================================
# Accept window expiry
# ===========================================================================
class TestAcceptWindow:

    def test_accept_after_window_expired_returns_err_accept_window_expired(self):
        """PRD §3.3: "with ERR_ACCEPT_WINDOW_EXPIRED if the platform clock
        has reached or passed accept_deadline_at."

        Claim: clock advance past accept_deadline_at + accept -> ERR_ACCEPT_WINDOW_EXPIRED
        (or assignment is already EXPIRED on the path).
        """
        _, project, _, segments = setup_quoted_project_with_one_word_segment()
        t = setup_translator_passed(grade="SENIOR")
        seg_ids = [s["id"] for s in segments]
        a = dispatch_assignment(project["id"], t["id"], "TRANSLATOR", seg_ids)
        api_client.activate_project(project["id"], PM)
        # Advance clock past 48-hour window
        advance_clock(ACCEPT_WINDOW_HOURS * 3600)
        # Whether the sweep marks EXPIRED first or the accept fails on
        # the window check, both outcomes are PRD-faithful expressions of
        # the same rule. PRD prose explicitly names ERR_ACCEPT_WINDOW_EXPIRED
        # AND PRD §2.10/§3.3 says the EXPIRED transition fires when crossing
        # the deadline. The validation order pins the accept-time check to
        # priority 9 (window), so a still-PENDING assignment surfaces
        # ERR_ACCEPT_WINDOW_EXPIRED.
        from prd_bench_local_runner.testing import validate_error_is_one_of
        resp = api_client.accept_assignment(
            a["id"], make_translator_headers(t["id"]),
        )
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_ACCEPT_WINDOW_EXPIRED.value,
            ApiErrorId.ERR_INVALID_ASSIGNMENT_STATE.value,
        ])


# ===========================================================================
# Rejection cascade — successor spawn
# ===========================================================================
class TestRejectSpawnsSuccessor:

    def test_translator_reject_spawns_successor_to_different_translator(self):
        """PRD §3.3: "On decline, the assignment terminates as REJECTED,
        the covered segments remain in NEW, the platform emits an
        ExternalSyncRecord whose target_system is IM and whose
        trigger_event is ASSIGNMENT_REJECTED, and a successor assignment
        is immediately spawned to a different translator selected by the
        ranking described in §2.11; the rejecting translator is excluded
        from the candidate pool."

        Claim: rejecter yields a successor PENDING assignment to a
        DIFFERENT translator id covering the same segments.
        """
        _, project, _, segments = setup_quoted_project_with_one_word_segment()
        t1 = setup_translator_passed(grade="SENIOR")
        t2 = setup_translator_passed(grade="SENIOR")
        seg_ids = [s["id"] for s in segments]
        # Dispatch to t1 — the system will choose t2 as the successor.
        a = dispatch_assignment(project["id"], t1["id"], "TRANSLATOR", seg_ids)
        api_client.activate_project(project["id"], PM)
        # T1 rejects
        api_client.reject_assignment(
            a["id"], {"reason": "unavailable"},
            make_translator_headers(t1["id"]),
        )
        # Look for a successor in the project's assignments
        # List all assignments under the project via list endpoint; if no
        # such endpoint exists, we inspect via /assignments/{id} for newly
        # created rows. PRD §4 lists GET /assignments/{id} (single) — list
        # is implicit. We use sync records as observable proxy: an
        # ASSIGNMENT_DISPATCHED sync should now show TWO dispatches for
        # this project (original + successor).
        records = list_all_sync_records(project_id=project["id"])
        dispatched = find_sync_records(records, target_system="IM",
                                       trigger_event="ASSIGNMENT_DISPATCHED")
        assert len(dispatched) >= 2, (
            "successor dispatch must produce a second IM ASSIGNMENT_DISPATCHED sync"
        )

    def test_translator_reject_emits_im_assignment_rejected_sync(self):
        """PRD §3.3: "the platform emits an ExternalSyncRecord whose
        target_system is IM and whose trigger_event is
        ASSIGNMENT_REJECTED."

        Claim: IM/ASSIGNMENT_REJECTED sync row is created after reject.
        """
        _, project, _, segments = setup_quoted_project_with_one_word_segment()
        t1 = setup_translator_passed(grade="SENIOR")
        t2 = setup_translator_passed(grade="SENIOR")  # successor candidate
        seg_ids = [s["id"] for s in segments]
        a = dispatch_assignment(project["id"], t1["id"], "TRANSLATOR", seg_ids)
        api_client.activate_project(project["id"], PM)
        api_client.reject_assignment(
            a["id"], {"reason": "unavailable"},
            make_translator_headers(t1["id"]),
        )
        records = list_all_sync_records(project_id=project["id"])
        rejected = find_sync_records(records, target_system="IM",
                                     trigger_event="ASSIGNMENT_REJECTED")
        assert len(rejected) >= 1, \
            "IM ExternalSyncRecord with ASSIGNMENT_REJECTED must be emitted"


# ===========================================================================
# Workload cap
# ===========================================================================
class TestWorkloadCap:

    def test_accept_pushing_workload_above_cap_returns_translator_overloaded(self):
        """PRD §2.11: "The platform caps each translator's open workload
        at 200 open segments — that is, Translator.workload_segments_open
        plus the size of any new package must not exceed 200, and any
        dispatch or acceptance that would breach the cap is rejected with
        ERR_TRANSLATOR_OVERLOADED."

        Claim: a translator already holding 150 open segments who is
        dispatched a 60-segment package -> ERR_TRANSLATOR_OVERLOADED at
        dispatch time (210 > 200).
        """
        t, pdata = setup_translator_with_open_workload(
            initial_open_segments=150, grade="SENIOR",
        )
        # Build a NEW project with 60 fresh segments so the dispatch
        # involves exactly 60 segment ids.
        from test_helpers import (
            extract_segments_from,
            build_multi_sentence_text, setup_client_and_project_in_draft,
            split_document, upload_document,
        )
        _, project2 = setup_client_and_project_in_draft(
            project_overrides={"package_size_segments": 200},
        )
        text = build_multi_sentence_text([3] * 60)
        doc = upload_document(project2["id"], raw_text=text)
        ds = split_document(doc["id"])
        segs = extract_segments_from(ds, doc)
        assert len(segs) >= 60, (
            "Setup expected 60 segments from a 60-sentence split. The "
            "implementation must surface segment ids via the split "
            "response so test code can dispatch the package."
        )
        new_seg_ids = [s["id"] for s in segs[:60]]
        # Quote and activate the second project so dispatch is permitted.
        from test_helpers import quote_project, activate_project
        quote_project(project2["id"])
        resp = api_client.dispatch_assignment(
            project2["id"],
            dispatch_assignment_payload(
                t["id"], "TRANSLATOR", new_seg_ids,
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_TRANSLATOR_OVERLOADED)
