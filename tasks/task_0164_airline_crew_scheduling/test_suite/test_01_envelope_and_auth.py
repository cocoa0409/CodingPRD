"""Envelope shape, auth headers, RBAC, ownership, and 404 cascade.

Every test cites PRD §2.1 / §2.2 / §2.6 / §2.8 verbatim.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_crew_member,
    create_pairing_payload,
    make_pilot_headers,
    validate_error,
    validate_success,
)


class TestSuccessEnvelope:

    def test_create_crew_member_success_envelope(self, api, scheduler_headers):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body" — meta, response_type, data.
        """
        cm = create_crew_member()
        body = api.get_crew_member(cm["id"], scheduler_headers).json()
        assert "meta" in body
        assert "response_type" in body
        assert body["response_type"] == "object"
        assert "data" in body
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "PRD §2.2: The api_request_id is a server-generated unique "
            "identifier for the request that starts with req_."
        )


class TestAuthHeaders:

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "Every request must carry two headers: X-User-ID
        and X-User-Role. If either is missing or empty, the request is
        rejected with ERR_AUTH_REQUIRED."
        """
        bad = {"X-User-Role": "CrewScheduler",
               "Content-Type": "application/json"}
        resp = api._request("GET", "/pairings", headers=bad)
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "Every request must carry two headers: X-User-ID
        and X-User-Role. If either is missing or empty, the request is
        rejected with ERR_AUTH_REQUIRED."
        """
        bad = {"X-User-ID": "some-id", "Content-Type": "application/json"}
        resp = api._request("GET", "/pairings", headers=bad)
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_empty_user_id_header_rejected(self, api):
        """PRD §2.1: "If either is missing or empty, the request is
        rejected with ERR_AUTH_REQUIRED."
        """
        bad = {"X-User-ID": "", "X-User-Role": "CrewScheduler",
               "Content-Type": "application/json"}
        resp = api._request("GET", "/pairings", headers=bad)
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_unknown_role_rejected(self, api):
        """PRD §2.1: "If X-User-Role is present but is not one of the
        four supported values — CrewScheduler, Pilot, FlightAttendant,
        or UnionSteward — the request is rejected with
        ERR_AUTH_INVALID_ROLE."
        """
        bad = build_user_headers("u-1", "UnknownRole")
        resp = api._request("GET", "/pairings", headers=bad)
        validate_error(resp, ApiErrorId.ERR_AUTH_INVALID_ROLE.value)


class TestRoleForbidden:

    def test_pilot_cannot_create_crew_member(self, api):
        """PRD §4 table: POST /crew-members is CrewScheduler-only.
        PRD §2.1: "When a role is recognized but is not permitted to
        invoke the requested endpoint per the RBAC matrix described in
        §4, the request is rejected with ERR_FORBIDDEN."
        """
        # We can't create the CrewMember via this path (Pilot can't);
        # instead, build a synthetic pilot id (no entity behind it) and
        # confirm the role check fires first (PRD §2.8 priority).
        bad = build_user_headers("fake-pilot", "Pilot")
        resp = api.create_crew_member(
            {"employee_no": "E000001", "rank": "CAPTAIN",
             "base_airport": "DFW", "union_seniority_number": 1,
             "union_local_id": "L-100"},
            bad,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_pilot_cannot_award_bid_window(self, api):
        """PRD §4 table: POST /bid-windows/{id}/award is
        CrewScheduler-only. PRD §2.1 + §3.3: "When the bid window
        closes, a CrewScheduler runs the awarding sweep."
        """
        bad = build_user_headers("fake-pilot", "Pilot")
        resp = api.award_bid_window("BW-X", bad)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_crew_scheduler_cannot_union_bless(self, api,
                                                 scheduler_headers):
        """PRD §3.8: "A CrewScheduler is barred from blessing — this is
        the segregation of duties."
        PRD §4 table: POST /trade-requests/{id}/union-bless is
        UnionSteward-only.
        """
        resp = api.union_bless_trade(NON_EXISTENT_UUID, scheduler_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestOwnershipChecks:

    def test_pilot_cannot_withdraw_other_pilots_bid(self, api):
        """PRD §3.2: "Withdrawal by anyone other than the bid's owner is
        rejected by the ownership rule embedded in X-User-ID
        enforcement."
        PRD §2.1: "A Pilot may only bid, withdraw, sick-out, propose,
        counter, accept, reject, or cancel on resources where the
        relevant foreign key equals their own X-User-ID."
        """
        from test_helpers import (
            build_pairing_with_one_duty_period,
            publish_and_open_bidding,
            submit_bid,
        )
        owner = create_crew_member(rank="CAPTAIN")
        other = create_crew_member(rank="CAPTAIN")
        pairing, _, _ = build_pairing_with_one_duty_period(
            base_airport="DFW",
            required_rank_composition={"CAPTAIN": 1},
        )
        pairing, bw = publish_and_open_bidding(pairing["id"])
        bid = submit_bid(owner, pairing["id"], bw, preference_rank=1)

        # Attempt withdrawal as the other pilot.
        resp = api.delete_bid(bid["id"], make_pilot_headers(other["id"]))
        # PRD §2.1 names the ownership rule but does not commit to a
        # specific error_id beyond §2.8's priority list. The closest
        # named outcome PRD describes is ERR_FORBIDDEN (role check) —
        # but role IS allowed, so use is_one_of for the ownership
        # error_id space PRD permits.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_FORBIDDEN.value,
            ApiErrorId.ERR_RESOURCE_NOT_FOUND.value,
        ])


class TestExistenceCascade:

    def test_missing_pairing_yields_resource_not_found(self, api,
                                                        scheduler_headers):
        """PRD §2.6: "Path-referenced resources are validated left to
        right. For an endpoint such as the one that appends a flight
        leg to a duty period under a draft pairing, the parent duty
        period is checked first; if its id does not resolve,
        ERR_RESOURCE_NOT_FOUND is returned and no further checks run."
        """
        resp = api.get_pairing(NON_EXISTENT_UUID, scheduler_headers)
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)

    def test_missing_assignment_yields_resource_not_found(self, api,
                                                            scheduler_headers):
        """PRD §2.6: path-referenced resource id not found."""
        resp = api.get_assignment(NON_EXISTENT_UUID, scheduler_headers)
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)

    def test_unresolved_foreign_key_in_body_yields_reference_not_found(
        self, api,
    ):
        """PRD §2.6: "Foreign keys carried in the request body —
        crew_member_id, pairing_id, assignment_id,
        counterparty_assignment_id, initiator_assignment_id, and so on
        — are validated after path checks succeed, and an unresolved
        one yields ERR_REFERENCE_NOT_FOUND."
        """
        cm = create_crew_member(rank="CAPTAIN")
        from test_helpers import build_pairing_with_one_duty_period
        pairing, _, _ = build_pairing_with_one_duty_period()
        from test_helpers import publish_pairing
        publish_pairing(pairing["id"])
        # admin-assign with a non-existent crew_member_id.
        from test_helpers import scheduler_headers as _sch
        resp = api.create_assignment(
            {"pairing_id": pairing["id"],
             "crew_member_id": NON_EXISTENT_UUID,
             "assigned_rank_slot": "CAPTAIN"},
            _sch(),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)
