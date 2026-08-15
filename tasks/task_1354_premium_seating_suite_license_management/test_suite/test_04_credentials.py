"""Access credentials: capacity boundary, event-state guards, uniqueness, windows."""
from test_helpers import (
    ADMIN, ESM, REP,
    ApiClient, ApiErrorId, EVENT_E1,
    issue_credential, set_clock, setup_active_agreement,
    validate_error, validate_paginated, validate_success,
)

SILVER_CAP2 = dict(suite_code="S-009", tier="SILVER", capacity_seats=2,
                   base_annual_fee_cents=6000000, f_b_minimum_cents=2000000)
GOLD_SUITE = dict(suite_code="G-101", tier="GOLD", capacity_seats=20,
                  base_annual_fee_cents=12000000, f_b_minimum_cents=4000000)


def _credential_payload(s, name, email):
    return {"event_id": s["events"][0]["id"], "suite_id": s["suite"]["id"],
            "agreement_id": s["agreement"]["id"], "guest_name": name,
            "guest_email": email, "credential_type": "GUEST"}


class TestCredentialCapacityBoundary:
    def test_credential_reaching_exact_capacity_succeeds(self, api: ApiClient):
        """PRD §3.7: "the count of credentials in `ISSUED` or `ACTIVATED` for the same
        event and suite must remain within the suite's `capacity_seats`: issuing the
        credential that exactly reaches capacity succeeds, and the next attempt fails
        with `ERR_CREDENTIAL_CAPACITY_EXCEEDED`."
        Design: Difficulty/boundary_precision_check/credential_capacity_nth_succeeds_nplus1_fails
        """
        s = setup_active_agreement(num_seasons=1, events_spec=[EVENT_E1],
                                   suite_over=SILVER_CAP2,
                                   agreement_over=dict(base_annual_fee_cents=6000000,
                                                       escalator_bp=0,
                                                       f_b_minimum_cents=2000000))
        c1 = validate_success(api.create_credential(
            _credential_payload(s, "Guest One", "g1@x.example"), ESM), expected_status=201)
        c2 = validate_success(api.create_credential(
            _credential_payload(s, "Guest Two", "g2@x.example"), ESM), expected_status=201)
        assert c1["status"] == "ISSUED" and c2["status"] == "ISSUED", (
            "count reaches exactly capacity_seats == 2")

    def test_credential_beyond_capacity_fails(self, api: ApiClient):
        """PRD §3.7: "the count of credentials in `ISSUED` or `ACTIVATED` for the same
        event and suite must remain within the suite's `capacity_seats`: issuing the
        credential that exactly reaches capacity succeeds, and the next attempt fails
        with `ERR_CREDENTIAL_CAPACITY_EXCEEDED`."
        Design: Difficulty/boundary_precision_check/credential_capacity_nth_succeeds_nplus1_fails
        """
        s = setup_active_agreement(num_seasons=1, events_spec=[EVENT_E1],
                                   suite_over=SILVER_CAP2,
                                   agreement_over=dict(base_annual_fee_cents=6000000,
                                                       escalator_bp=0,
                                                       f_b_minimum_cents=2000000))
        validate_success(api.create_credential(
            _credential_payload(s, "Guest One", "g1@x.example"), ESM), expected_status=201)
        validate_success(api.create_credential(
            _credential_payload(s, "Guest Two", "g2@x.example"), ESM), expected_status=201)
        resp = api.create_credential(_credential_payload(s, "Guest Three", "g3@x.example"), ESM)
        validate_error(resp, ApiErrorId.ERR_CREDENTIAL_CAPACITY_EXCEEDED)


class TestEventStateGuard:
    def test_credential_issue_blocked_when_event_cancelled(self, api: ApiClient):
        """PRD §3.7: "the event must be `SCHEDULED` (`ERR_EVENT_NOT_SCHEDULED`)".
        Design: Difficulty/cross_entity_state_dependency/credential_issue_blocked_when_event_cancelled
        """
        s = setup_active_agreement(num_seasons=1, events_spec=[EVENT_E1],
                                   suite_over=GOLD_SUITE)
        set_clock("2026-08-20T00:00:00Z")  # before the event start: cancellable
        validate_success(api.set_event_status(
            s["events"][0]["id"], {"target_status": "CANCELLED"}, ADMIN))
        resp = api.create_credential(_credential_payload(s, "Guest One", "g1@x.example"), ESM)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_SCHEDULED)

    def test_cancelled_event_also_blocks_issue_after_prior_issue(self, api: ApiClient):
        """PRD §2.8: "(ii) the event must be `SCHEDULED` for catering placement or
        confirmation and for credential issue or activation, else
        `ERR_EVENT_NOT_SCHEDULED`". PRD §3.1: "every access credential of the event in
        `ISSUED` or `ACTIVATED` moves to `EXPIRED`".
        Design: Difficulty/cross_entity_state_dependency/credential_issue_blocked_when_event_cancelled
        """
        s = setup_active_agreement(num_seasons=1, events_spec=[EVENT_E1],
                                   suite_over=GOLD_SUITE)
        set_clock("2026-08-20T00:00:00Z")
        issued = validate_success(api.create_credential(
            _credential_payload(s, "Guest One", "g1@x.example"), ESM), expected_status=201)
        validate_success(api.set_event_status(
            s["events"][0]["id"], {"target_status": "CANCELLED"}, ADMIN))
        # The pre-existing credential expired in the cancellation cascade ...
        after = validate_success(api.get_credential(issued["id"], ESM))
        assert after["status"] == "EXPIRED"
        # ... and new issuance against the cancelled event is refused.
        resp = api.create_credential(_credential_payload(s, "Guest Two", "g2@x.example"), ESM)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_SCHEDULED)


class TestGuestUniqueness:
    def test_duplicate_guest_email_and_revoke_reissue(self, api: ApiClient):
        """PRD §3.7: "a `guest_email` may appear on only one credential per event and
        suite among those not `REVOKED` or `EXPIRED`; a repeat is
        `ERR_DUPLICATE_GUEST`."
        Design: Corner/validations/duplicate_guest_email_and_revoke_reissue
        """
        s = setup_active_agreement(num_seasons=1, events_spec=[EVENT_E1],
                                   suite_over=GOLD_SUITE)
        first = validate_success(api.create_credential(
            _credential_payload(s, "Guest One", "g1@x.example"), ESM), expected_status=201)
        dup = api.create_credential(_credential_payload(s, "Guest One Again", "g1@x.example"), ESM)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_GUEST)
        validate_success(api.set_credential_status(
            first["id"], {"target_status": "REVOKED"}, ESM))
        reissued = validate_success(api.create_credential(
            _credential_payload(s, "Guest One Reissued", "g1@x.example"), ESM),
            expected_status=201)
        assert reissued["status"] == "ISSUED"
        assert reissued["barcode"] != first["barcode"], "a new barcode is minted"
        rows, meta = validate_paginated(api.list_credentials(
            ESM, params={"event_id": s["events"][0]["id"], "suite_id": s["suite"]["id"]}))
        assert meta["total_count"] == 2
        statuses = sorted(r["status"] for r in rows)
        assert statuses == ["ISSUED", "REVOKED"]


class TestRevocationAndActivationWindow:
    def test_credential_revoke_after_activate_rejected(self, api: ApiClient):
        """PRD §3.7: "Revocation — `ISSUED` to `REVOKED` — is open to event-services
        staff and to the `AccountHolder` who owns the credential's agreement or rental
        account". PRD §2.8: "The target resource must be in a valid from-state for the
        requested transition, else `ERR_INVALID_STATE_TRANSITION` (HTTP 409); terminal
        states are locked down."
        Design: Corner/state_machines/credential_revoke_after_activate_rejected
        """
        s = setup_active_agreement(num_seasons=1, events_spec=[EVENT_E1],
                                   suite_over=GOLD_SUITE)
        cred = validate_success(api.create_credential(
            _credential_payload(s, "Guest One", "g1@x.example"), ESM), expected_status=201)
        set_clock("2026-09-10T18:00:00Z")  # inside the admission window [13:00, 21:00]
        validate_success(api.set_credential_status(
            cred["id"], {"target_status": "ACTIVATED"}, ESM))
        resp = api.set_credential_status(cred["id"], {"target_status": "REVOKED"}, ESM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert validate_success(api.get_credential(cred["id"], ESM))["status"] == "ACTIVATED"

    def test_credential_activation_window_boundary(self, api: ApiClient):
        """PRD §3.7: "moving `ISSUED` to `ACTIVATED` requires the event still
        `SCHEDULED` (else `ERR_EVENT_NOT_SCHEDULED`) and the clock inside the admission
        window, which runs from four hours before the event's `starts_at` through
        `starts_at` plus `duration_hours`, both ends inclusive; outside that window the
        attempt is `ERR_CREDENTIAL_WINDOW`."
        Design: Corner/validations/credential_activation_window_boundary
        """
        s = setup_active_agreement(num_seasons=1, events_spec=[EVENT_E1],
                                   suite_over=GOLD_SUITE)
        c1 = validate_success(api.create_credential(
            _credential_payload(s, "Early Bird", "early@x.example"), ESM), expected_status=201)
        c2 = validate_success(api.create_credential(
            _credential_payload(s, "On Time", "ontime@x.example"), ESM), expected_status=201)
        set_clock("2026-09-10T12:59:59Z")  # one second before the window opens (13:00)
        resp = api.set_credential_status(c1["id"], {"target_status": "ACTIVATED"}, ESM)
        validate_error(resp, ApiErrorId.ERR_CREDENTIAL_WINDOW)
        set_clock("2026-09-10T13:00:00Z")  # exactly at the inclusive window open
        activated = validate_success(api.set_credential_status(
            c2["id"], {"target_status": "ACTIVATED"}, ESM))
        assert activated["status"] == "ACTIVATED"
