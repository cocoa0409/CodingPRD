"""External events, dedup window, and clock advance (PRD §3.9, §2.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_external_event_payload,
)


# ---------------------------------------------------------------------------
# Difficulty-design: resource_temporal_overlap/external_event_dedup_closed_window
# ---------------------------------------------------------------------------

class TestExternalEventDedupClosedWindow:
    """# difficulty: resource_temporal_overlap/external_event_dedup_closed_window"""

    def test_first_event_accepted(self, api, admin_headers):
        """PRD §3.9: "The server stamps `received_at` from its logical clock and starts the event in `processing_status` `RECEIVED`."

        Claim: baseline first arrival → 201.
        # difficulty: resource_temporal_overlap/external_event_dedup_closed_window
        """
        payload = create_external_event_payload(
            source_system="HR", external_event_id="evt-baseline-A",
            event_type="EMPLOYEE_TRANSFERRED", payload={},
        )
        resp = api.create_external_event(payload, admin_headers)
        validate_success(resp, expected_status=201)

    def test_dedup_at_exactly_60_minutes_is_duplicate(self, api, admin_headers):
        """PRD §3.9: "The boundary is inclusive: a re-arrival exactly 60 minutes after the prior receipt is still a duplicate, while a re-arrival 60 minutes plus one second after the prior receipt is treated as a fresh event."
        PRD §3.9: "the `error_id` reported when the duplicate is surfaced is `ERR_DUPLICATE_EVENT`."

        Claim: send event at t0; advance clock 60 min; send same (source, external_event_id) →
        duplicate (ERR_DUPLICATE_EVENT at the inclusive 60-min boundary).
        # difficulty: resource_temporal_overlap/external_event_dedup_closed_window
        """
        payload = create_external_event_payload(
            source_system="HR", external_event_id="evt-bound-60",
            event_type="EMPLOYEE_TRANSFERRED", payload={},
        )
        validate_success(api.create_external_event(payload, admin_headers), expected_status=201)
        # Advance exactly 60 minutes
        validate_success(api.advance_clock(3600, admin_headers))
        # Resend same (source, external_event_id)
        resp = api.create_external_event(payload, admin_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EVENT.value)

    def test_dedup_at_61_minutes_is_fresh(self, api, admin_headers):
        """PRD §3.9: "a re-arrival 60 minutes plus one second after the prior receipt is treated as a fresh event."

        Claim: t0 send; +60 min advance; +1 second advance; resend → fresh (201).
        # difficulty: resource_temporal_overlap/external_event_dedup_closed_window
        """
        payload = create_external_event_payload(
            source_system="HR", external_event_id="evt-bound-61",
            event_type="EMPLOYEE_TRANSFERRED", payload={},
        )
        validate_success(api.create_external_event(payload, admin_headers), expected_status=201)
        # Advance 3601 seconds total
        validate_success(api.advance_clock(3601, admin_headers))
        resp = api.create_external_event(payload, admin_headers)
        # Just past the closed boundary → fresh
        validate_success(resp, expected_status=201)


# ---------------------------------------------------------------------------
# RBAC on external events and clock
# ---------------------------------------------------------------------------

class TestExternalEventRBAC:
    def test_employee_cannot_post_external_event(self, api, employee_headers_unowned):
        """PRD §4 endpoint table: POST /external-events is PlatformAdmin only.
        PRD §2.1: "When a role is presented but is not permitted for the requested endpoint, the response is `ERR_FORBIDDEN` (HTTP 403)."

        Note: this test uses the shared Employee header because it asserts only the role gate,
        not ownership. The user-existence priority (priority 3) runs before role-permission
        (priority 11), so an Employee header that doesn't resolve would surface ERR_USER_NOT_FOUND
        first. We therefore use a real Employee user via setup_org.
        """
        from test_helpers import setup_org
        org = setup_org()
        payload = create_external_event_payload()
        resp = api.create_external_event(payload, org["employee_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_employee_cannot_advance_clock(self, api):
        """PRD §2.8 + PRD §4 endpoint table: POST /_clock/advance is PlatformAdmin only."""
        from test_helpers import setup_org
        org = setup_org()
        resp = api.advance_clock(60, org["employee_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
