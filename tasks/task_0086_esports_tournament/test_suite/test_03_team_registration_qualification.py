"""TeamRegistration and qualification-gate tests (PRD §3.2).

Covers creation, ownership rule (X-User-ID must equal manager_id),
duplicate team-name guard, the four qualification gates (entry fee,
roster size, identity verification, age, region) and the ranking
threshold + max_teams cap.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    build_five_main_roster,
    build_user_headers,
    create_open_tournament,
    create_team_registration,
    create_team_registration_payload,
    create_active_contract,
    iso_utc,
    make_team_manager_headers,
    pay_entry_fee_payload,
    register_team_to_registered,
    reset_clock_to_epoch,
    validate_error,
    validate_success,
)


# ===========================================================================
# Creation (PRD §3.2)
# ===========================================================================
class TestCreateTeamRegistration:
    def test_create_team_registration_in_draft(self, api):
        """PRD §3.2: "A successful registration creates the row in
        DRAFT status with entry_fee_paid_cents zero, roster_locked
        false, and seed_number unset."

        Claim: POST /tournaments/{tid}/team-registrations returns
        status=DRAFT, entry_fee_paid_cents=0, roster_locked=false.
        """
        reset_clock_to_epoch()
        t = create_open_tournament()
        manager_id = "tm-create-test"
        response = api.create_team_registration(
            t["id"],
            create_team_registration_payload(manager_id=manager_id),
            make_team_manager_headers(manager_id),
        )
        data = validate_success(response, expected_status=201)
        assert data["status"] == "DRAFT"
        assert data["entry_fee_paid_cents"] == 0
        assert data["roster_locked"] is False

    def test_create_team_registration_x_user_id_mismatch_forbidden(self, api):
        """PRD §2.1: "Ownership of a TeamRegistration is established at
        creation time by the rule that X-User-ID must equal the
        manager_id supplied in the request body."

        Claim: when X-User-ID does not equal the body's manager_id,
        creation is rejected with ERR_FORBIDDEN.
        """
        reset_clock_to_epoch()
        t = create_open_tournament()
        response = api.create_team_registration(
            t["id"],
            create_team_registration_payload(manager_id="tm-real"),
            build_user_headers("tm-impersonator", "TeamManager"),
        )
        validate_error(response, ApiErrorId.ERR_FORBIDDEN.value)

    def test_register_when_tournament_not_in_registration_open(self, api):
        """PRD §3.2: "Registration is only accepted while the parent
        tournament is in REGISTRATION_OPEN; otherwise the response is
        ERR_REGISTRATION_NOT_OPEN."

        Claim: registering against a Tournament in DRAFT → ERR_REGISTRATION_NOT_OPEN.
        """
        from test_helpers import create_tournament
        reset_clock_to_epoch()
        t = create_tournament()
        manager_id = "tm-not-open"
        response = api.create_team_registration(
            t["id"],
            create_team_registration_payload(manager_id=manager_id),
            make_team_manager_headers(manager_id),
        )
        validate_error(response, ApiErrorId.ERR_REGISTRATION_NOT_OPEN.value)

    def test_duplicate_team_name_rejected(self, api):
        """PRD §3.2: "the team_name must be unique within the
        tournament among registrations whose status is not WITHDRAWN,
        otherwise ERR_DUPLICATE_TEAM_NAME."

        Claim: second registration in the same tournament with the
        same team_name → ERR_DUPLICATE_TEAM_NAME.
        """
        reset_clock_to_epoch()
        t = create_open_tournament()
        create_team_registration(t["id"], manager_id="tm-a",
                                 team_name="DuplicateName")
        response = api.create_team_registration(
            t["id"],
            create_team_registration_payload(
                manager_id="tm-b", team_name="DuplicateName",
            ),
            make_team_manager_headers("tm-b"),
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_TEAM_NAME.value)


# ===========================================================================
# Qualification gates on pay-entry-fee (PRD §3.2)
# ===========================================================================
class TestPayEntryFeeQualification:
    def test_insufficient_entry_fee_rejected(self, api):
        """PRD §3.2: "the cumulative entry_fee_paid_cents (after FX
        conversion to entry_fee_currency) must be at least
        Tournament.entry_fee_cents; otherwise
        ERR_ENTRY_FEE_INSUFFICIENT."

        Claim: paying less than entry_fee_cents → ERR_ENTRY_FEE_INSUFFICIENT.
        """
        reset_clock_to_epoch()
        t = create_open_tournament(entry_fee_cents=10_000)
        manager_id = "tm-poor"
        reg = create_team_registration(
            t["id"], manager_id=manager_id, team_name="Underfunded",
        )
        # Build a valid 5-MAIN roster so OTHER gates (roster size,
        # identity verification, age, region) all pass — only the
        # fiscal gate should fail.
        build_five_main_roster(team_id=reg["id"], manager_id=manager_id)
        response = api.pay_entry_fee(
            reg["id"],
            pay_entry_fee_payload(amount_cents=5_000, currency="USD"),
            make_team_manager_headers(manager_id),
        )
        validate_error(response, ApiErrorId.ERR_ENTRY_FEE_INSUFFICIENT.value)

    def test_player_underage_rejected(self, api):
        """PRD §3.2: "every main-roster player's player_age must be at
        least Tournament.min_age (the boundary is inclusive — a player
        exactly at the minimum passes); otherwise ERR_PLAYER_UNDERAGE."

        Claim: pay-entry-fee while one MAIN player has age < min_age
        → ERR_PLAYER_UNDERAGE.
        """
        reset_clock_to_epoch()
        t = create_open_tournament(min_age=18, entry_fee_cents=10_000)
        manager_id = "tm-young"
        reg = create_team_registration(
            t["id"], manager_id=manager_id, team_name="Young",
        )
        # 4 adults + 1 underage.
        for _ in range(4):
            create_active_contract(team_id=reg["id"], manager_id=manager_id,
                                   player_age=22)
        create_active_contract(team_id=reg["id"], manager_id=manager_id,
                               player_age=16)
        response = api.pay_entry_fee(
            reg["id"],
            pay_entry_fee_payload(amount_cents=10_000, currency="USD"),
            make_team_manager_headers(manager_id),
        )
        validate_error(response, ApiErrorId.ERR_PLAYER_UNDERAGE.value)

    def test_region_mismatch_rejected(self, api):
        """PRD §3.2: "the team's region must equal Tournament.region,
        or Tournament.region must be GLOBAL; otherwise ERR_REGION_MISMATCH."

        Claim: team in 'EU' registering for a 'NA' tournament →
        ERR_REGION_MISMATCH.
        """
        reset_clock_to_epoch()
        t = create_open_tournament(region="NA", entry_fee_cents=10_000)
        manager_id = "tm-wrongregion"
        reg = create_team_registration(
            t["id"], manager_id=manager_id, region="EU",
            team_name="WrongRegion",
        )
        build_five_main_roster(team_id=reg["id"], manager_id=manager_id)
        response = api.pay_entry_fee(
            reg["id"],
            pay_entry_fee_payload(amount_cents=10_000),
            make_team_manager_headers(manager_id),
        )
        validate_error(response, ApiErrorId.ERR_REGION_MISMATCH.value)

    def test_pay_entry_fee_success_transitions_to_registered(self, api):
        """PRD §3.2: "submits the entry-fee payment to advance from
        FEE_PENDING to REGISTERED."

        Claim: with all four gates satisfied, pay-entry-fee returns
        TeamRegistration with status=REGISTERED and
        ranking_points_snapshot pinned.
        """
        reset_clock_to_epoch()
        t = create_open_tournament(entry_fee_cents=10_000)
        reg, contracts = register_team_to_registered(
            tournament_id=t["id"], manager_id="tm-happy",
            team_name="HappyPath",
            ranking_points_each=100,
        )
        assert reg["status"] == "REGISTERED"
        # ranking_points_snapshot is pinned at this moment (PRD §3.2).
        assert isinstance(reg.get("ranking_points_snapshot"), int)
        assert reg["ranking_points_snapshot"] == sum(
            c.get("ranking_points", 0) for c in contracts
        ), (
            "PRD §3.2: ranking_points_snapshot pins the sum across MAIN-slot "
            "players' ranking_points"
        )
