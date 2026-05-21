"""Validation priority and ordering — PRD §2.10.

Tests pairwise priority ordering where PRD explicitly states a winner.
Skips ordering pairs PRD does not commit to.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    apply_extension_payload,
    audit_weekly_certification_payload,
    create_appeal_payload,
    create_claimant,
    decide_appeal_payload,
    make_appeal_officer_headers,
    make_claimant_headers,
    setup_appeal_segregation_collision,
    validate_error,
)


class TestPriorityOrdering:

    def test_auth_beats_not_found(self, api):
        """PRD §2.10: "The order is: authentication
        (ERR_UNAUTHENTICATED) first, then role permission
        (ERR_FORBIDDEN), then path-existence of every referenced
        resource (ERR_NOT_FOUND)."

        With empty headers, even a 404-able path returns
        ERR_UNAUTHENTICATED (not ERR_NOT_FOUND).
        """
        resp = api.get_claim(NON_EXISTENT_UUID, {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_forbidden_beats_not_found(self, api):
        """PRD §2.10: "authentication first, then role permission
        (ERR_FORBIDDEN), then path-existence of every referenced
        resource (ERR_NOT_FOUND)."

        EmployerAgent attempts to GET /claims/{nonexistent} — forbidden
        by RBAC; PRD §4 lists Claimant/Adjudicator/AppealOfficer/SystemAdmin
        for that endpoint.
        """
        resp = api.get_claim(
            NON_EXISTENT_UUID,
            TEST_USERS["employer_agent_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_not_found_beats_not_owner(self, api):
        """PRD §2.7: "URL paths are validated left to right. ... a
        non-existent parent produces ERR_NOT_FOUND before any further
        check. Only after every path segment resolves does the server
        proceed to ownership, state, and body validation."

        Test: a Claimant requests a non-existent claim. Path-existence
        fails (priority 3 ERR_NOT_FOUND) before ownership (priority 4
        ERR_NOT_OWNER) is even considered.
        """
        cm = create_claimant()
        resp = api.get_claim(
            NON_EXISTENT_UUID, make_claimant_headers(cm["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_invalid_state_beats_segregation_of_duties(self, api):
        """PRD §2.10: "state legality of the requested transition
        (ERR_INVALID_STATE), then segregation of duties on appeal
        hearing-start and decide
        (ERR_SEGREGATION_OF_DUTIES_VIOLATION)."

        Setup: WITHDRAWN appeal where assigned_appeal_officer_id ==
        assigned_adjudicator_id. start-hearing is illegal from
        WITHDRAWN (state-check fires first); SoD would also fire if
        state were FILED.

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_segregation
        """
        shared = "user-collide-0001"
        bundle = setup_appeal_segregation_collision(shared_user_id=shared)
        resp = api.start_hearing(
            bundle["appeal"]["id"],
            make_appeal_officer_headers(shared),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
