"""Concurrency: race conditions and OCC version conflicts (PRD §2.4, §2.6)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    validate_error_is_one_of,
    ApiErrorId,
    run_race, assert_exactly_one_succeeds, assert_race_outcome,
    self_submit_payload, manager_submit_payload,
    setup_active_individual_objective,
    setup_review_at_pending_manager,
    setup_alignment_pair,
    create_user, make_employee_headers, make_manager_headers,
    create_value_change_payload,
)


# ---------------------------------------------------------------------------
# OCC: version-conflict on PATCH
# ---------------------------------------------------------------------------

class TestOCCVersionConflict:
    def test_patch_objective_with_stale_version_returns_err_version_conflict(self, api):
        """PRD §2.4: "When `version` is supplied, the server compares it to the resource's current `version`; if they do not match, the request is rejected with `ERR_VERSION_CONFLICT` (HTTP 409) and no mutation is applied."

        Claim: PATCH with stale version → ERR_VERSION_CONFLICT.
        """
        s = setup_active_individual_objective()
        # Read current version
        obj = validate_success(api.get_objective(s["objective"]["id"], s["org"]["admin_headers"]))
        current_version = obj["version"]
        # PATCH with version=current+1 (wrong) — must fail
        bad_payload = {"title": "new title", "version": current_version + 1}
        resp = api.patch_objective(
            s["objective"]["id"], bad_payload, s["org"]["employee_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_patch_objective_increments_version_by_one(self, api):
        """PRD §2.4: "On every successful mutation, `version` is incremented by 1 and `updated_at` is refreshed".

        Claim: PATCH with correct version → version + 1.
        """
        s = setup_active_individual_objective()
        obj = validate_success(api.get_objective(s["objective"]["id"], s["org"]["admin_headers"]))
        v_before = obj["version"]
        payload = {"title": "renamed", "version": v_before}
        resp = api.patch_objective(
            s["objective"]["id"], payload, s["org"]["employee_headers"]
        )
        data = validate_success(resp)
        assert data["version"] == v_before + 1


# ---------------------------------------------------------------------------
# Race: two concurrent manager-submits → exactly one succeeds
# ---------------------------------------------------------------------------

class TestRaceManagerSubmit:
    def test_two_concurrent_manager_submits_exactly_one_wins(self, api):
        """PRD §2.6: "When two clients race to advance the same review score from `PENDING_MANAGER` to `PENDING_CALIBRATION` (two simultaneous manager submits)... exactly one wins; the loser's request finds the review in a status that does not match the precondition for its action and is rejected with `ERR_INVALID_STATE`."

        Claim: two simultaneous manager-submits → one 200, one ERR_INVALID_STATE.
        """
        s = setup_review_at_pending_manager(self_score=0.6)
        review_id = s["review"]["id"]
        mgr_headers = s["org"]["manager_headers"]

        results = run_race(
            lambda: api.manager_submit_review(review_id, manager_submit_payload(0.5), mgr_headers),
            lambda: api.manager_submit_review(review_id, manager_submit_payload(0.6), mgr_headers),
        )
        outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
        # Loser must surface ERR_INVALID_STATE
        loser = outcome["failures"][0]
        body = loser.json()
        assert body["data"]["error_id"] == ApiErrorId.ERR_INVALID_STATE.value


# ---------------------------------------------------------------------------
# Race: two concurrent accepts of same alignment link
# ---------------------------------------------------------------------------

class TestRaceAcceptLink:
    def test_two_concurrent_accepts_exactly_one_wins(self, api):
        """PRD §2.6: "The same applies to two clients racing to accept the same alignment link: the second sees `ERR_INVALID_STATE` because the first has advanced the link out of `PENDING`."

        Claim: two simultaneous accept calls → exactly one succeeds, the other gets ERR_INVALID_STATE.
        """
        s = setup_alignment_pair(progress_a=0.5, progress_b=0.5)
        b_headers = make_employee_headers(s["employee_b"]["id"])
        link_id = s["link"]["id"]

        results = run_race(
            lambda: api.accept_alignment_link(link_id, b_headers),
            lambda: api.accept_alignment_link(link_id, b_headers),
        )
        outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
        loser = outcome["failures"][0]
        body = loser.json()
        assert body["data"]["error_id"] == ApiErrorId.ERR_INVALID_STATE.value


# ---------------------------------------------------------------------------
# Race: two stale-version PATCH on KR.current_value indirectly via progress
# ---------------------------------------------------------------------------

class TestKRPatchVersionRace:
    def test_two_concurrent_kr_patches_with_same_version_one_wins_with_version_conflict(self, api):
        """PRD §2.6: "When two updates to the same `KeyResult.current_value` race using the optimistic `version` field, the loser sees `ERR_VERSION_CONFLICT`."
        PRD §4 endpoint table: PATCH /key-results/{id} accepts version (OCC).

        Claim: two PATCHes against the same KR with the same version → exactly one wins,
        the other gets ERR_VERSION_CONFLICT.
        """
        s = setup_active_individual_objective(num_krs=1, kr_kind="NUMERIC")
        kr = s["krs"][0]
        owner_headers = s["org"]["employee_headers"]
        v = kr["version"]
        results = run_race(
            lambda: api.patch_key_result(kr["id"], {"title": "t1", "version": v}, owner_headers),
            lambda: api.patch_key_result(kr["id"], {"title": "t2", "version": v}, owner_headers),
        )
        outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
        loser = outcome["failures"][0]
        body = loser.json()
        assert body["data"]["error_id"] == ApiErrorId.ERR_VERSION_CONFLICT.value
