"""Voter eligibility (citizenship/age/residency), precinct assignment,
cure-grace window, validation priority interplay.

PRD §3.3 (preconditions on PENDING → ACTIVE), §3.6 (cure-grace
window).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_voter,
    advance_clock_iso,
    advance_clock_to,
    advance_to_early_voting,
    api_client,
    create_election,
    create_precinct,
    create_voter,
    get_voter,
    iso_utc,
    open_registration,
    parse_iso,
    setup_active_voter,
    setup_election_with_precinct,
    setup_open_registration,
    state_transition_payload,
    validate_error,
    validate_success,
)


class TestCitizenshipPrecondition:

    def test_non_citizen_activation_rejected(self, api):
        """PRD §3.3: 'the voter must attest citizenship (is_citizen=true,
        otherwise ERR_NOT_CITIZEN).'
        """
        election, _ = setup_open_registration()
        voter = create_voter(election["id"], is_citizen=False)
        resp = api.transition_voter(
            voter["id"], state_transition_payload("ACTIVE"),
            TEST_USERS["registrar_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NOT_CITIZEN.value)


class TestAgePrecondition:

    def test_under_age_activation_rejected(self, api):
        """PRD §3.3: 'the voter must be at least 18 years of age on
        Election.election_date ... otherwise ERR_UNDER_AGE.'

        Use a date_of_birth that is 17 years before the election_date.
        """
        # Election anchored 1 year out by default; DOB only 17 years
        # before election_date → age 17 → fails.
        election, _ = setup_open_registration()
        ed = parse_iso(election["election_date"])
        # 17 years 0 days before election date → under age.
        dob = ed - timedelta(days=17 * 365)
        voter = create_voter(
            election["id"],
            date_of_birth=iso_utc(dob),
        )
        resp = api.transition_voter(
            voter["id"], state_transition_payload("ACTIVE"),
            TEST_USERS["registrar_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_UNDER_AGE.value)

    def test_exactly_18_activation_succeeds(self, api):
        """PRD §3.3: 'the voter must be at least 18 years of age on
        Election.election_date'. PRD §2.10: age = floor(days/365.25).

        Boundary: at exactly 18 years (~ 18 * 365.25 days), the
        activation succeeds.
        """
        election, _ = setup_open_registration()
        ed = parse_iso(election["election_date"])
        # 18 * 365.25 = 6574.5 → use 6575 days = > 18 by floor.
        dob = ed - timedelta(days=int(18 * 365.25) + 1)
        voter = create_voter(
            election["id"],
            date_of_birth=iso_utc(dob),
        )
        resp = api.transition_voter(
            voter["id"], state_transition_payload("ACTIVE"),
            TEST_USERS["registrar_clerk_headers"],
        )
        data = validate_success(resp)
        assert data["status"] == "ACTIVE"


class TestResidencyPrecondition:

    def test_short_residency_activation_rejected(self, api):
        """PRD §3.3: 'the residency duration (the day-count between
        residency_since and Election.election_date) must be at least
        30 days (otherwise ERR_RESIDENCY_INSUFFICIENT).'
        """
        election, _ = setup_open_registration()
        ed = parse_iso(election["election_date"])
        residency_since = iso_utc(ed - timedelta(days=10))  # 10 days
        voter = create_voter(
            election["id"], residency_since=residency_since,
        )
        resp = api.transition_voter(
            voter["id"], state_transition_payload("ACTIVE"),
            TEST_USERS["registrar_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RESIDENCY_INSUFFICIENT.value)

    def test_residency_exactly_30_days_succeeds(self, api):
        """PRD §3.3: 'at least 30 days' — boundary inclusive.

        Claim: residency_days == 30 passes; residency_days == 29 fails.
        """
        election, _ = setup_open_registration()
        ed = parse_iso(election["election_date"])
        residency_since_30 = iso_utc(ed - timedelta(days=30))
        voter = create_voter(
            election["id"], residency_since=residency_since_30,
        )
        resp = api.transition_voter(
            voter["id"], state_transition_payload("ACTIVE"),
            TEST_USERS["registrar_clerk_headers"],
        )
        data = validate_success(resp)
        assert data["status"] == "ACTIVE", (
            "residency_days=30 must pass the >=30 boundary"
        )

    def test_residency_29_days_rejected(self, api):
        """PRD §3.3: 'the residency duration ... must be at least 30
        days (otherwise ERR_RESIDENCY_INSUFFICIENT).'

        Boundary: residency_days == 29 fails.
        """
        election, _ = setup_open_registration()
        ed = parse_iso(election["election_date"])
        residency_since_29 = iso_utc(ed - timedelta(days=29))
        voter = create_voter(
            election["id"], residency_since=residency_since_29,
        )
        resp = api.transition_voter(
            voter["id"], state_transition_payload("ACTIVE"),
            TEST_USERS["registrar_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RESIDENCY_INSUFFICIENT.value)


class TestPrecinctAssignment:

    def test_no_matching_precinct_keeps_precinct_id_null(self, api):
        """PRD §3.3: 'If no precinct's street_pattern matches the
        supplied address, the creation still succeeds but the voter's
        precinct_id remains null.'
        """
        election = create_election()
        create_precinct(election["id"], code="P1",
                        street_pattern=".*Oak.*")
        open_registration(election["id"])
        voter = create_voter(
            election["id"],
            residency_address="123 Maple Avenue",  # does not match
        )
        assert voter["precinct_id"] is None, (
            "precinct_id must be null when no street_pattern matches"
        )

    def test_unmatched_precinct_blocks_activation(self, api):
        """PRD §3.3: 'the voter cannot later be activated.'
        PRD §3.3: 'the voter's precinct_id must be non-null
        (otherwise ERR_NO_PRECINCT_MATCH).'
        """
        election = create_election()
        create_precinct(election["id"], code="P1",
                        street_pattern=".*Oak.*")
        open_registration(election["id"])
        voter = create_voter(
            election["id"],
            residency_address="999 Maple Street",
        )
        resp = api.transition_voter(
            voter["id"], state_transition_payload("ACTIVE"),
            TEST_USERS["registrar_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NO_PRECINCT_MATCH.value)

    def test_longest_pattern_wins_then_code_ascending(self, api):
        """PRD §3.3: 'Among the matches, the routine ranks by the
        length of street_pattern in descending order; ties are broken
        by Precinct.code in ascending lexicographic order. The first
        precinct under that ranking is assigned.'
        """
        election = create_election()
        # Two precincts that both match '123 Main Street':
        p_short = create_precinct(
            election["id"], code="A1",
            street_pattern=".*Main.*",  # length 8
        )
        p_long = create_precinct(
            election["id"], code="Z9",
            street_pattern=".*Main.*Street.*",  # length 15 — wins
        )
        open_registration(election["id"])
        voter = create_voter(
            election["id"], residency_address="100 Main Street",
        )
        assert voter["precinct_id"] == p_long["id"], (
            "longest street_pattern must win regardless of code"
        )


class TestDeadlinePrecondition:

    def test_activation_after_registration_deadline_rejected(self, api):
        """PRD §3.3: 'the server clock must be no later than
        registration_deadline (otherwise ERR_DEADLINE_PASSED).'
        """
        election, _ = setup_open_registration()
        voter = create_voter(election["id"])
        # Advance past registration_deadline.
        advance_clock_to(
            parse_iso(election["registration_deadline"])
            + timedelta(seconds=1),
        )
        resp = api.transition_voter(
            voter["id"], state_transition_payload("ACTIVE"),
            TEST_USERS["registrar_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DEADLINE_PASSED.value)
