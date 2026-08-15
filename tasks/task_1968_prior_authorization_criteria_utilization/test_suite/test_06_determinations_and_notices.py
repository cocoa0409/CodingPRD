"""Determinations: notice rendering, voids, counter restoration (PRD §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    approved_determination,
    basic_um_environment,
    denied_determination,
    file_appeal,
    get_determination,
    get_provider,
    list_request_determinations,
    list_request_events,
    reviewer_decide,
    pended_request,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["um_admin_headers"]


class TestNoticeText:
    def test_notice_text_exact_segments(self, api):
        """PRD §3.4: "The `notice_text` is rendered at issuance from an exact-string template. Segments are joined by pipe characters in this fixed order: the literal `OUTCOME:` followed by the outcome; `|SERVICE:` followed by the request's `service_code`; `|REASON:` followed by the reason code; `|CRITERIA:` followed by the criteria set's `name`, an at-sign, and the pinned version's `version_label`; `|ISSUED:` followed by `issued_at` in ISO 8601 UTC with three fractional digits; `|APPEAL_BY:` followed by the appeal deadline — `issued_at` plus 4,320 hours (the 180-day appeal window) — in the same format; and `|DECIDED_BY:` followed by the deciding role. Segment order and separators are contractual."

        Design: Corner/calculations/notice_text_exact_segments
        """
        provider, cs, _gv = basic_um_environment()
        _req, det = denied_determination(
            provider["id"], cs["id"],
            deny_reason_code="EXPERIMENTAL_INVESTIGATIONAL",
        )
        expected = (
            "OUTCOME:DENIED"
            "|SERVICE:72148"
            "|REASON:EXPERIMENTAL_INVESTIGATIONAL"
            "|CRITERIA:Spine Imaging Criteria@1.0"
            "|ISSUED:2026-08-01T00:00:00.000Z"
            "|APPEAL_BY:2027-01-28T00:00:00.000Z"
            "|DECIDED_BY:CLINICAL_REVIEWER"
        )
        assert det["notice_text"] == expected


class TestDeterminationVoid:
    def test_void_restores_provider_counters_and_request_state(self, api):
        """PRD §3.4: "In every void, `determined_at` is cleared to null, provider statistics recompute excluding the voided row (void rows never count toward any rate), and a `DETERMINATION_VOIDED` event is recorded with the request and provider ids."
        PRD §3.4: "Voiding sets the determination `VOID` and reverts the request: a determination decided by `SYSTEM_RULE` or `CLINICAL_REVIEWER` sends the request back to `PENDED_REVIEW` (from `AUTO_APPROVED` or `APPROVED` for the reviewer case, and from `DENIED` for a reviewer denial), while a `MEDICAL_DIRECTOR` determination sends it back to `ESCALATED_MD` (from `APPROVED` or `DENIED`), with `escalated_by_user_id` retaining its prior value in the medical-director cases."
        PRD §2.10: "All approval and overturn rates in the system are computed to 4 decimal places using round-half-up. A rate whose denominator count is zero is represented as null rather than zero."

        Design: Difficulty/compensating_invariant/determination_void_restores_provider_counters
        """
        provider, cs, _gv = basic_um_environment()
        req = pended_request(provider["id"], cs["id"])
        approved = reviewer_decide(
            req["id"], "APPROVE", reason_code="MEDICAL_NECESSITY_MET",
        )
        assert approved["status"] == "APPROVED"
        mid = get_provider(provider["id"])
        assert mid["rolling_determination_count"] == 1
        assert mid["rolling_approval_count"] == 1
        assert mid["rolling_approval_rate"] == pytest.approx(1.0)
        det = list_request_determinations(req["id"])[0]
        validate_success(api.void_determination(det["id"], ADMIN))
        after = get_provider(provider["id"])
        assert after["rolling_determination_count"] == 0
        assert after["rolling_approval_count"] == 0
        assert after["rolling_approval_rate"] is None
        assert after["lifetime_determination_count"] == 0, (
            "the void restores every counter to its pre-issuance value"
        )
        reverted = validate_success(api.get_prior_auth_request(req["id"], ADMIN))
        assert reverted["status"] == "PENDED_REVIEW"
        assert reverted["determined_at"] is None

    def test_void_marks_determination_and_emits_event(self, api):
        """PRD §3.4: "In every void, `determined_at` is cleared to null, provider statistics recompute excluding the voided row (void rows never count toward any rate), and a `DETERMINATION_VOIDED` event is recorded with the request and provider ids."

        Design: Difficulty/compensating_invariant/determination_void_restores_provider_counters
        """
        provider, cs, _gv = basic_um_environment()
        req, det = approved_determination(provider["id"], cs["id"])
        voided = validate_success(api.void_determination(det["id"], ADMIN))
        assert voided["status"] == "VOID"
        events = list_request_events(req["id"], event_type="DETERMINATION_VOIDED")
        assert len(events) == 1
        assert events[0]["provider_id"] == provider["id"]

    def test_void_blocked_by_open_appeal_rejected(self, api):
        """PRD §3.4: "A `UMAdmin` may void a determination, but only one in `FINAL` status with no appeal against it sitting in `RECEIVED` or `IN_REVIEW`; otherwise `ERR_DETERMINATION_NOT_VOIDABLE`."

        Design: Corner/validations/void_blocked_by_open_appeal_rejected
        """
        provider, cs, _gv = basic_um_environment()
        _req, det = denied_determination(
            provider["id"], cs["id"], deny_reason_code="INSUFFICIENT_INFO",
        )
        file_appeal(det["id"], appeal_reason="Contesting")
        resp = api.void_determination(det["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_DETERMINATION_NOT_VOIDABLE)
        assert get_determination(det["id"])["status"] == "FINAL"
