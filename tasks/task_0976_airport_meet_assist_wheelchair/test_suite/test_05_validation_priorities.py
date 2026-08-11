"""Difficulty queue A — priority_pair_validation_conflict instances."""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error, ApiErrorId,
    create_airport, create_terminal, create_segment, create_passenger,
    create_assist_request, create_leg, create_agent,
    submit_request, set_clock,
    api_client, TEST_USERS,
)


ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["ops_manager_headers"]
REQ = TEST_USERS["requester_headers"]
DISP = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_dispatch_in_lockdown_with_no_tsa_agent
# ---------------------------------------------------------------------------

class TestStateVsBusinessSafetyDispatch:
    def _setup_lockdown_with_expired_tsa(self):
        set_clock("2026-06-15T10:00:00Z")
        airport = create_airport(iata_code="IAH", meet_buffer_minutes=15)
        terminal = create_terminal(airport["id"], code="E", requires_secure_escort=True)
        segment = create_segment(
            airport["id"], terminal["id"], flight_no="UA9",
            direction="DEPARTURE", scheduled_utc="2026-06-16T10:00:00Z",
        )
        passenger = create_passenger(
            full_name="P IAH", dob="1980-01-01", mobility_code="WCHR",
            airline_pnr="IAH1",
        )
        request = create_assist_request(
            passenger["id"], bill_to="AIRLINE", service_tier="STANDARD",
            companion_count=0,
        )
        leg = create_leg(request["id"], segment["id"],
                         leg_kind="DEPARTURE_ESCORT", pickup_zone="Z")
        set_clock("2026-06-16T09:00:00Z")
        request = submit_request(request["id"])
        # Agent whose TSA clearance is in the past
        agent = create_agent(
            airport["id"], display_name="IAH Ag expired",
            tsa_cleared_until="2026-01-01T00:00:00Z",
            shift_start_utc="2026-06-16T08:00:00Z",
            shift_end_utc="2026-06-16T20:00:00Z",
        )
        # Move DEGRADED then LOCKDOWN
        get_success_data(api_client.set_airport_posture(
            airport["id"], {"posture": "DEGRADED"}, OPS,
        ))
        get_success_data(api_client.set_airport_posture(
            airport["id"], {"posture": "LOCKDOWN"}, OPS,
        ))
        return airport, request, leg, agent

    def test_dispatch_during_lockdown_returns_posture_restricted_not_tsa(self, api):
        """PRD §2.9: "5. **State-machine precondition** — the target resource is
        in the from-state the transition requires (`ERR_INVALID_STATE`).
        6. **TSA / regulatory safety** — TSA clearance and UMNR dual-signer
        requirements (`ERR_TSA_CLEARANCE_REQUIRED`)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_dispatch_in_lockdown_with_no_tsa_agent
        """
        airport, request, leg, agent = self._setup_lockdown_with_expired_tsa()
        cur = get_success_data(api_client.get_assist_request(request["id"], DISP))
        resp = api_client.dispatch_leg(
            leg["id"],
            {"expected_assist_request_version": cur["version"]},
            DISP,
        )
        # The dispatch under LOCKDOWN: lockdown already cancelled the leg, so the
        # leg is in CANCELLED — but the posture check rejects first. We accept
        # either ERR_POSTURE_RESTRICTED (posture gate) or ERR_INVALID_STATE
        # (leg already cancelled) — both are state-priority (5) errors outranking
        # business_safety (6).
        actual = resp.json()["data"]["error_id"]
        assert actual in ("ERR_POSTURE_RESTRICTED", "ERR_INVALID_STATE"), (
            f"Expected state-priority error, got {actual}"
        )
        assert actual != "ERR_TSA_CLEARANCE_REQUIRED", (
            "Business-safety (priority 6) must not outrank state (priority 5)"
        )

    def test_dispatch_during_lockdown_never_returns_tsa_clearance(self, api):
        """PRD §2.9: "a dispatch attempted during `LOCKDOWN` with a stale expected
        version surfaces `ERR_STALE_VERSION` (priority 4) rather than
        `ERR_INVALID_STATE` (priority 5) or `ERR_POSTURE_RESTRICTED`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_dispatch_in_lockdown_with_no_tsa_agent
        """
        airport, request, leg, agent = self._setup_lockdown_with_expired_tsa()
        # Posture check (or invalid-state check after cascade) wins over TSA
        cur = get_success_data(api_client.get_assist_request(request["id"], DISP))
        resp = api_client.dispatch_leg(
            leg["id"],
            {"expected_assist_request_version": cur["version"]},
            DISP,
        )
        actual = resp.json()["data"]["error_id"]
        # State-priority (4/5) error must outrank business_safety (6)
        assert actual != "ERR_TSA_CLEARANCE_REQUIRED"
        assert resp.status_code in (409, 412)


# ---------------------------------------------------------------------------
# Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_submit_with_bogus_onward_leg_and_missing_payment
# ---------------------------------------------------------------------------

class TestReferentialVsFiscal:
    def _setup_two_requests(self):
        set_clock("2026-06-15T10:00:00Z")
        airport = create_airport(iata_code="SEA", meet_buffer_minutes=15)
        terminal = create_terminal(airport["id"], code="N", requires_secure_escort=False)
        seg1 = create_segment(
            airport["id"], terminal["id"], flight_no="AS1",
            direction="ARRIVAL", scheduled_utc="2026-06-16T10:00:00Z",
        )
        seg2 = create_segment(
            airport["id"], terminal["id"], flight_no="AS2",
            direction="DEPARTURE", scheduled_utc="2026-06-16T14:00:00Z",
        )
        pax1 = create_passenger(
            full_name="No Card", dob="1990-01-01", mobility_code="WCHR",
        )
        pax2 = create_passenger(
            full_name="Other P", dob="1985-01-01", mobility_code="WCHR",
            airline_pnr="OP1",
        )
        req2 = create_assist_request(
            pax2["id"], bill_to="AIRLINE", service_tier="STANDARD", companion_count=0,
        )
        leg_r2 = create_leg(req2["id"], seg2["id"],
                            leg_kind="DEPARTURE_ESCORT", pickup_zone="Z2")
        req1 = create_assist_request(
            pax1["id"], bill_to="PRIVATE", service_tier="STANDARD", companion_count=0,
        )
        return airport, seg1, req1, req2, leg_r2

    def test_leg_create_with_cross_request_onward_leg_returns_referential(self, api):
        """PRD §3.2: "the field is meaningful only for `CONNECTION_TRANSFER` legs
        and must reference a leg belonging to the same assist request; cross-request
        or cross-airport references are rejected with `ERR_REFERENTIAL_INTEGRITY`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_submit_with_bogus_onward_leg_and_missing_payment
        """
        airport, seg1, req1, req2, leg_r2 = self._setup_two_requests()
        # Attempt to add a CONNECTION_TRANSFER leg on req1 pointing at req2's leg
        resp = api_client.create_leg(
            req1["id"],
            {"segment_id": seg1["id"], "leg_kind": "CONNECTION_TRANSFER",
             "pickup_zone": "Z1", "onward_leg_id": leg_r2["id"]},
            REQ,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_INTEGRITY)
        # No new leg was created on req1
        legs = get_success_data(api_client.list_legs(req1["id"], REQ))
        assert len(legs) == 0

    def test_referential_error_fires_on_leg_create_before_any_submit_check(self, api):
        """PRD §2.9: "8. **Referential integrity** — foreign keys resolve and
        respect airport boundaries (`ERR_REFERENTIAL_INTEGRITY`)."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_submit_with_bogus_onward_leg_and_missing_payment
        """
        airport, seg1, req1, req2, leg_r2 = self._setup_two_requests()
        # req1 has bill_to=PRIVATE and passenger has no card — a subsequent SUBMIT
        # would hit fiscal. But leg-create fails referential first.
        resp = api_client.create_leg(
            req1["id"],
            {"segment_id": seg1["id"], "leg_kind": "CONNECTION_TRANSFER",
             "pickup_zone": "Z1", "onward_leg_id": leg_r2["id"]},
            REQ,
        )
        assert resp.status_code == 422
        assert resp.json()["data"]["error_id"] == "ERR_REFERENTIAL_INTEGRITY"
