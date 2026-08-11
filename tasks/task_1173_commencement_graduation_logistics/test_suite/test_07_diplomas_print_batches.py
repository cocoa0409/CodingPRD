"""Diploma printing, print-batch release controls, honor snapshot pinning,
and the post-ceremony correction cycle."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, api_client,
    setup_ceremony, setup_diploma_queued, setup_diploma_printed,
    setup_diploma_issued, create_open_batch, release_batch,
    mark_batch_printed, get_print_batch, get_diploma, set_clock,
    make_graduate_headers, make_registrar_headers, TEST_USERS,
)

CHAIR = TEST_USERS["committee_chair_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
COORDINATOR = TEST_USERS["venue_coordinator_headers"]
REG_A = "reg-a-1"
REG_B = "reg-b-1"


class TestDiplomaCorrectionReprintCycle:
    def _setup_correction_approved(self):
        """ISSUED diploma on a COMMENCED ceremony; correction requested; a
        second OPEN batch exists; correction approved into it."""
        ctx = setup_diploma_issued(grad_tier="SUMMA", full_name="Jonathan Public",
                                   phonetic="JON-uh-thun PUB-lik",
                                   printed_name="Jonathan Public")
        diploma = ctx["diploma"]
        requested = validate_success(
            api_request_correction(diploma["id"], "Johnathan Public",
                                   ctx["graduate"]["id"]), 200)
        assert requested["status"] == "CORRECTION_REQUESTED"
        batch2 = create_open_batch(ctx["ceremony"]["id"])
        decided = validate_success(
            api_decide_correction(diploma["id"], "APPROVED"), 200)
        return ctx, batch2, decided

    def test_correction_approval_effects(self, api):
        """PRD §3.7: "it reassigns the diploma's `print_batch_id` to that open
        batch, copies `corrected_name` into `printed_name`, clears
        `corrected_name` to null, adds one to `correction_count`, re-pins
        `honors_text` and `pinned_honor_tier` from the graduate's **current**
        `honor_tier`, and moves the diploma to `REPRINT_QUEUED`".

        Design: Difficulty/non_linear_state_machine/diploma_correction_reprint_cycle
        """
        ctx, batch2, decided = self._setup_correction_approved()
        assert decided["status"] == "REPRINT_QUEUED"
        assert decided["print_batch_id"] == batch2["id"]
        assert decided["printed_name"] == "Johnathan Public"
        assert decided["corrected_name"] is None
        assert decided["correction_count"] == 1
        assert decided["pinned_honor_tier"] == "SUMMA_CUM_LAUDE"

    def test_full_correction_cycle_returns_to_issued(self, api):
        """PRD §3.7: "moves the diploma to `REPRINT_QUEUED` — from which the
        next batch printing returns it to `PRINTED`, ready to be issued again."
        PRD §3.7: "Marking the batch printed moves `RELEASED` to the terminal
        `PRINTED` and cascades every attached diploma in `QUEUED` or
        `REPRINT_QUEUED` to `PRINTED`."

        Design: Difficulty/non_linear_state_machine/diploma_correction_reprint_cycle
        """
        ctx, batch2, decided = self._setup_correction_approved()
        release_batch(batch2["id"])  # releaser REG_B differs from creator REG_A
        printed_batch = mark_batch_printed(batch2["id"])
        assert printed_batch["status"] == "PRINTED"

        diploma = get_diploma(ctx["diploma"]["id"])
        assert diploma["status"] == "PRINTED"
        assert diploma["pinned_honor_tier"] == "SUMMA_CUM_LAUDE"

        issued = validate_success(api.issue_diploma(diploma["id"], CHAIR), 200)
        assert issued["status"] == "ISSUED"  # full cycle traversed


def api_request_correction(diploma_id, corrected_name, graduate_id):
    return api_client.request_correction(
        diploma_id, {"corrected_name": corrected_name},
        make_graduate_headers(graduate_id))


def api_decide_correction(diploma_id, decision):
    return api_client.decide_correction(diploma_id, {"decision": decision}, REGISTRAR)


class TestBatchReleasePosture:
    def _setup_reopened_with_queued_diploma(self):
        """AUDIT_LOCKED batch + QUEUED diploma (pinned SUMMA), then the audit
        is legitimately reopened (batch is only OPEN, so the revert is legal)."""
        ctx = setup_diploma_queued(grad_tier="SUMMA", full_name="Sam Summa",
                                   phonetic="SAM SUM-muh")
        ceremony = validate_success(api_client.reopen_audit(ctx["ceremony"]["id"], CHAIR), 200)
        assert ceremony["readiness_posture"] == "AUDIT_OPEN"
        return ctx

    def test_batch_release_requires_audit_locked(self, api):
        """PRD §2.5: "Releasing a print batch requires `AUDIT_LOCKED`,
        `READY`, `COMMENCED`, or `COMPLETED`, so that post-ceremony correction
        reprints remain releasable."
        PRD §2.5: "The posture gates nearly every operation in the system, and
        a violation is always rejected with `ERR_CEREMONY_POSTURE_FORBIDS`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/batch_release_requires_audit_locked
        """
        ctx = self._setup_reopened_with_queued_diploma()
        res = api.release_batch(ctx["batch"]["id"], make_registrar_headers(REG_B))
        validate_error(res, ApiErrorId.ERR_CEREMONY_POSTURE_FORBIDS)
        assert res.status_code == 409

    def test_rejected_release_leaves_batch_and_diploma_untouched(self, api):
        """PRD §3.7: "A clean release moves the batch to `RELEASED` and stamps
        `released_by_user_id` with the releaser."
        PRD §3.1: "Reopening the audit returns `AUDIT_LOCKED` to `AUDIT_OPEN`,
        but only while no print batch for the ceremony stands in `RELEASED` or
        `PRINTED` status".

        Design: Difficulty/cross_entity_state_dependency/batch_release_requires_audit_locked
        """
        ctx = self._setup_reopened_with_queued_diploma()
        res = api.release_batch(ctx["batch"]["id"], make_registrar_headers(REG_B))
        validate_error(res, ApiErrorId.ERR_CEREMONY_POSTURE_FORBIDS)

        batch = get_print_batch(ctx["batch"]["id"])
        assert batch["status"] == "OPEN"
        assert batch["released_by_user_id"] is None
        diploma = get_diploma(ctx["diploma"]["id"])
        assert diploma["status"] == "QUEUED"


class TestDiplomaIssuePosture:
    def test_diploma_issue_requires_commenced_posture(self, api):
        """PRD §3.7: "a `CommitteeChair` issues a `PRINTED` diploma — only
        while the ceremony's posture is `COMMENCED`, else
        `ERR_CEREMONY_POSTURE_FORBIDS` — moving it to `ISSUED`."

        Design: Corner/state_machines/diploma_issue_requires_commenced_posture
        """
        ctx = setup_diploma_printed(grad_tier="SUMMA", full_name="Dee Ploma",
                                    phonetic="DEE PLOH-muh")
        assert ctx["ceremony"]["readiness_posture"] == "READY"
        assert ctx["diploma"]["status"] == "PRINTED"
        res = api.issue_diploma(ctx["diploma"]["id"], CHAIR)
        validate_error(res, ApiErrorId.ERR_CEREMONY_POSTURE_FORBIDS)
        assert res.status_code == 409
        assert get_diploma(ctx["diploma"]["id"])["status"] == "PRINTED"


class TestHonorSnapshotFreshness:
    def test_honor_snapshot_stale_blocks_batch_release(self, api):
        """PRD §3.7: "every attached diploma in `QUEUED` or `REPRINT_QUEUED`
        must carry a `pinned_honor_tier` equal to its graduate's **current**
        `honor_tier` — a mismatch, typically created by an audit reopening or a
        grade revision after queueing, is rejected with
        `ERR_HONOR_SNAPSHOT_STALE`".
        PRD §3.2: "Within a locked audit, a `RegistrarOfficer` may also post a
        grade revision for a single graduate — any of
        `institutional_gpa_credits`, `institutional_quality_points`,
        `transfer_gpa_credits`, or `transfer_quality_points` — which recomputes
        that graduate's FINAL INSTITUTIONAL honor".

        Design: Corner/validations/honor_snapshot_stale_blocks_batch_release
        """
        ctx = setup_diploma_queued(grad_tier="SUMMA", full_name="Snap Sue",
                                   phonetic="SNAP SOO")
        diploma = ctx["diploma"]
        assert diploma["pinned_honor_tier"] == "SUMMA_CUM_LAUDE"

        # 170.0 / 45 = 3.778 -> MAGNA; strands the QUEUED snapshot
        revised = validate_success(
            api.post_grade_revision(ctx["graduate"]["id"],
                                    {"institutional_quality_points": 170.0},
                                    REGISTRAR), 200)
        assert revised["honor_tier"] == "MAGNA_CUM_LAUDE"

        res = api.release_batch(ctx["batch"]["id"], make_registrar_headers(REG_B))
        validate_error(res, ApiErrorId.ERR_HONOR_SNAPSHOT_STALE)
        assert res.status_code == 409
        assert get_print_batch(ctx["batch"]["id"])["status"] == "OPEN"


class TestReprintBatchRequirement:
    def test_reprint_decision_requires_open_batch(self, api):
        """PRD §3.7: "Approval requires an `OPEN` print batch to exist for the
        ceremony (else `ERR_NO_OPEN_REPRINT_BATCH`)".

        Design: Corner/validations/reprint_decision_requires_open_batch
        """
        ctx = setup_diploma_issued(full_name="Reprint Ron", phonetic="REE-print RON")
        diploma = ctx["diploma"]
        requested = validate_success(
            api_request_correction(diploma["id"], "Ron Reprinted",
                                   ctx["graduate"]["id"]), 200)
        assert requested["status"] == "CORRECTION_REQUESTED"
        # the sole batch is already PRINTED, so no OPEN batch exists
        res = api_decide_correction(diploma["id"], "APPROVED")
        validate_error(res, ApiErrorId.ERR_NO_OPEN_REPRINT_BATCH)
        assert res.status_code == 409
        assert get_diploma(diploma["id"])["status"] == "CORRECTION_REQUESTED"


class TestEmptyBatchRelease:
    def test_empty_batch_release_returns_batch_not_releasable(self, api):
        """PRD §3.7: "the batch must hold at least one diploma (an empty batch
        is `ERR_BATCH_NOT_RELEASABLE`)".

        Design: Corner/validations/empty_batch_release_returns_batch_not_releasable
        """
        ctx = setup_ceremony(lock_audit=True)
        batch = create_open_batch(ctx["ceremony"]["id"])
        assert batch["diploma_count"] == 0
        res = api.release_batch(batch["id"], make_registrar_headers(REG_B))
        validate_error(res, ApiErrorId.ERR_BATCH_NOT_RELEASABLE)
        assert res.status_code == 409
        assert get_print_batch(batch["id"])["status"] == "OPEN"


class TestCorrectionWindow:
    def test_correction_window_closed_returns_error(self, api):
        """PRD §2.10: "a diploma correction requested strictly after thirty
        days from the ceremony's `ceremony_date` is rejected with
        `ERR_CORRECTION_WINDOW_CLOSED`".

        Design: Corner/validations/correction_window_closed_returns_error
        """
        ctx = setup_diploma_issued(full_name="Corr Connie",
                                   phonetic="KOR-ek-shun KAH-nee")
        diploma = ctx["diploma"]
        assert diploma["status"] == "ISSUED"
        # ceremony_date 2026-06-01T15:00:00Z + 30 days ended 2026-07-01T15:00:00Z
        set_clock("2026-07-02T00:00:00Z")
        res = api_request_correction(diploma["id"], "Connie Corrected",
                                     ctx["graduate"]["id"])
        validate_error(res, ApiErrorId.ERR_CORRECTION_WINDOW_CLOSED)
        assert res.status_code == 422
        assert get_diploma(diploma["id"])["status"] == "ISSUED"


class TestBatchSegregationOfDuties:
    def test_sod_batch_release_by_creator_returns_segregation_error(self, api):
        """PRD §2.7: "A print batch may be released only by a
        `RegistrarOfficer` whose identifier differs from the batch's
        `created_by_user_id`."
        PRD §2.7: "In each pair, the second step is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) when the same `X-User-ID`
        performs both".

        Design: Corner/validations/sod_batch_release_by_creator_returns_segregation_error
        """
        ctx = setup_ceremony()  # PLANNING is fine: SoD precedes the posture gate
        batch = create_open_batch(ctx["ceremony"]["id"], creator=REG_A)
        res = api.release_batch(batch["id"], make_registrar_headers(REG_A))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert res.status_code == 403
        after = get_print_batch(batch["id"])
        assert after["status"] == "OPEN"
        assert after["released_by_user_id"] is None
