"""Prize-claim lifecycle: reject/void compensation, self-exclusion guard,
segregation of duties, and priority-conflict ordering on claim/disburse.

Covers difficulty transitive_cascade (reject returns ticket), cross_entity_state_dependency
(self-exclusion blocks adjudication), priority_pair_validation_conflict (state beats
segregation; existence beats id-verification), plus claim-related corner instances.
"""
from test_helpers import (
    api_client, validate_success, validate_error, officer_headers,
    setup_submitted_claim, setup_adjudicating_claim, setup_approved_claim,
    setup_game_retailer_terminal, sell_and_validate_winner, create_player,
    open_claim, ApiErrorId, TEST_USERS,
)

CLERK = TEST_USERS["claims_clerk_headers"]
OFF = TEST_USERS["lottery_officer_headers"]


class TestRejectReturnsTicket:
    def test_reject_cascades_ticket_back_to_winner(self, api):
        """PRD 3.5: "the officer may reject the claim, moving it
        `ADJUDICATING → REJECTED`; rejection cascades the ticket
        `CLAIM_PENDING → VALIDATED_WINNER` so the prize becomes claimable again."

        Design: Difficulty/transitive_cascade/reject_claim_returns_ticket_then_reclaim_allowed
        """
        ctx = setup_adjudicating_claim(
            adj_user_id="u-adj", game_type="INSTANT", payout_option="CASH",
            gross_prize_cents=1000000, clock="2026-01-05T00:00:00Z", threshold_cents=600000)
        rej = validate_success(api.reject_claim(ctx["claim"]["id"], ctx["adj_headers"]))
        assert rej["status"] == "REJECTED", rej["status"]
        tk = validate_success(api.get_ticket(ctx["ticket"]["id"], OFF))
        assert tk["validation_status"] == "VALIDATED_WINNER", tk["validation_status"]

    def test_new_claim_allowed_after_reject(self, api):
        """PRD 3.5: "A claim may only be opened against a ticket whose `validation_status`
        is `VALIDATED_WINNER`"
        PRD 3.5: "rejection cascades the ticket `CLAIM_PENDING → VALIDATED_WINNER` so the
        prize becomes claimable again."

        Design: Difficulty/transitive_cascade/reject_claim_returns_ticket_then_reclaim_allowed
        """
        ctx = setup_adjudicating_claim(
            adj_user_id="u-adj", game_type="INSTANT", payout_option="CASH",
            gross_prize_cents=1000000, clock="2026-01-05T00:00:00Z", threshold_cents=600000)
        validate_success(api.reject_claim(ctx["claim"]["id"], ctx["adj_headers"]))
        new_claim = validate_success(
            api.create_prize_claim(
                {"ticket_id": ctx["ticket"]["id"], "player_id": ctx["player"]["id"],
                 "payout_option": "CASH"}, CLERK), expected_status=201)
        assert new_claim["status"] == "SUBMITTED", new_claim["status"]
        tk = validate_success(api.get_ticket(ctx["ticket"]["id"], OFF))
        assert tk["validation_status"] == "CLAIM_PENDING", tk["validation_status"]


class TestSelfExclusionGuard:
    def test_adjudication_blocked_when_player_excluded(self, api):
        """PRD 3.5: "Adjudication cannot begin if the claimant is under an active
        self-exclusion (see Section 3.6); such a claim is rejected with
        `ERR_PLAYER_SELF_EXCLUDED`."

        Design: Difficulty/cross_entity_state_dependency/adjudication_blocked_when_player_self_excluded
        """
        ctx = setup_submitted_claim(
            game_type="INSTANT", payout_option="CASH", gross_prize_cents=1000000,
            clock="2026-01-05T00:00:00Z", threshold_cents=600000)
        validate_success(
            api.self_exclude_player(ctx["player"]["id"], {"exclusion_days": 90}, CLERK))
        resp = api.begin_adjudication(ctx["claim"]["id"], officer_headers("u-adj"))
        validate_error(resp, ApiErrorId.ERR_PLAYER_SELF_EXCLUDED.value)
        claim = validate_success(api.get_prize_claim(ctx["claim"]["id"], OFF))
        assert claim["status"] == "SUBMITTED", claim["status"]

    def test_adjudication_proceeds_when_not_excluded(self, api):
        """PRD 3.5: "A `LotteryOfficer` begins adjudication, moving the claim
        `SUBMITTED → ADJUDICATING` and recording that officer's `X-User-ID` as
        `adjudicated_by_user_id`."

        Design: Difficulty/cross_entity_state_dependency/adjudication_blocked_when_player_self_excluded
        """
        ctx = setup_submitted_claim(
            game_type="INSTANT", payout_option="CASH", gross_prize_cents=1000000,
            clock="2026-01-05T00:00:00Z", threshold_cents=600000)
        data = validate_success(
            api.begin_adjudication(ctx["claim"]["id"], officer_headers("u-adj")))
        assert data["status"] == "ADJUDICATING", data["status"]


class TestPriorityConflicts:
    def test_state_beats_segregation_on_disburse(self, api):
        """PRD 2.11: "then whether the target resource is in a state from which the
        requested transition is defined (`ERR_INVALID_STATE`). Only after those structural
        gates does the system evaluate the optimistic-concurrency version check
        (`ERR_STALE_VERSION`), followed by the business-safety rules — self-exclusion at
        adjudication (`ERR_PLAYER_SELF_EXCLUDED`) and the two segregation-of-duties checks
        (`ERR_SEGREGATION_OF_DUTIES`)"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_disburse
        """
        ctx = setup_adjudicating_claim(
            adj_user_id="u-adj", game_type="INSTANT", payout_option="CASH",
            gross_prize_cents=1000000, clock="2026-01-05T00:00:00Z", threshold_cents=600000)
        # disburse on a still-ADJUDICATING claim by the same adjudicating officer
        resp = api.disburse_claim(ctx["claim"]["id"], officer_headers("u-adj"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_disburse_on_adjudicating_leaves_claim_unchanged(self, api):
        """PRD 3.5: "A `LotteryOfficer` disburses an approved claim, moving it
        `APPROVED_CASH → PAID` or `APPROVED_ANNUITY → PAID`"
        PRD 3.5: "Any transition attempted from a state in which it is not defined is
        rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_disburse
        """
        ctx = setup_adjudicating_claim(
            adj_user_id="u-adj", game_type="INSTANT", payout_option="CASH",
            gross_prize_cents=1000000, clock="2026-01-05T00:00:00Z", threshold_cents=600000)
        api.disburse_claim(ctx["claim"]["id"], officer_headers("u-adj"))
        claim = validate_success(api.get_prize_claim(ctx["claim"]["id"], OFF))
        assert claim["status"] == "ADJUDICATING", claim["status"]

    def test_existence_beats_id_verification_on_claim_create(self, api):
        """PRD 2.9: "the first reference that cannot be resolved causes the request to be
        rejected with `ERR_NOT_FOUND` before any later reference or business rule is
        evaluated."

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_business_constraint_on_claim_create
        """
        game, ret, term = setup_game_retailer_terminal(
            game_type="INSTANT", threshold_cents=600000, clock="2026-01-05T00:00:00Z")
        ticket = sell_and_validate_winner(game["id"], term["id"], gross_prize_cents=1000000)
        resp = api.create_prize_claim(
            {"ticket_id": ticket["id"],
             "player_id": "00000000-0000-4000-8000-000000000000",
             "payout_option": "CASH"}, CLERK)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_existence_check_also_fires_on_bogus_ticket_id(self, api):
        """PRD 2.9: "References are resolved left to right in the order they appear, and
        the first reference that cannot be resolved causes the request to be rejected with
        `ERR_NOT_FOUND` before any later reference or business rule is evaluated."

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_business_constraint_on_claim_create
        """
        player = create_player()
        resp = api.create_prize_claim(
            {"ticket_id": "00000000-0000-4000-8000-000000000000",
             "player_id": player["id"], "payout_option": "CASH"}, CLERK)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


class TestClaimCorners:
    def test_void_submitted_claim_returns_ticket(self, api):
        """PRD 3.5: "A claim still in `SUBMITTED` ... may instead be voided, moving it
        `SUBMITTED → VOIDED` and cascading the ticket `CLAIM_PENDING → VALIDATED_WINNER`
        to return it to circulation."

        Design: Corner/state_machines/void_submitted_claim_compensation_returns_ticket
        """
        ctx = setup_submitted_claim(
            game_type="INSTANT", payout_option="CASH", gross_prize_cents=1000000,
            clock="2026-01-05T00:00:00Z", threshold_cents=600000)
        data = validate_success(api.void_claim(ctx["claim"]["id"], officer_headers("u-off")))
        assert data["status"] == "VOIDED", data["status"]
        tk = validate_success(api.get_ticket(ctx["ticket"]["id"], OFF))
        assert tk["validation_status"] == "VALIDATED_WINNER", tk["validation_status"]

    def test_disburse_same_adjudicator_segregation_rejected(self, api):
        """PRD 2.6: "When a claim is disbursed, the acting `X-User-ID` is compared against
        the `adjudicated_by_user_id` recorded at adjudication; if they are the same
        identifier, the disbursement is rejected with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 409)."

        Design: Corner/errors/error_segregation_on_disburse_same_adjudicator
        """
        ctx = setup_approved_claim(
            adj_user_id="u-adj", game_type="INSTANT", payout_option="CASH",
            gross_prize_cents=1000000, clock="2026-01-05T00:00:00Z", threshold_cents=600000)
        assert ctx["claim"]["status"] == "APPROVED_CASH"
        resp = api.disburse_claim(ctx["claim"]["id"], officer_headers("u-adj"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
        claim = validate_success(api.get_prize_claim(ctx["claim"]["id"], OFF))
        assert claim["status"] == "APPROVED_CASH", claim["status"]

    def test_disburse_distinct_officer_succeeds(self, api):
        """PRD 3.5: "A `LotteryOfficer` disburses an approved claim, moving it
        `APPROVED_CASH → PAID` or `APPROVED_ANNUITY → PAID` and recording that officer's
        `X-User-ID` as `disbursed_by_user_id`."

        Design: Corner/errors/error_segregation_on_disburse_same_adjudicator
        """
        ctx = setup_approved_claim(
            adj_user_id="u-adj", game_type="INSTANT", payout_option="CASH",
            gross_prize_cents=1000000, clock="2026-01-05T00:00:00Z", threshold_cents=600000)
        data = validate_success(api.disburse_claim(ctx["claim"]["id"], officer_headers("u-disb")))
        assert data["status"] == "PAID", data["status"]

    def test_annuity_on_nonjackpot_create_rejected(self, api):
        """PRD 3.5: "If the elected option is `ANNUITY`, the ticket's game must be of
        `game_type` `JACKPOT`; an annuity election on a non-jackpot game is rejected with
        `ERR_ANNUITY_NOT_ALLOWED`."

        Design: Corner/validations/annuity_on_nonjackpot_create_rejected
        """
        game, ret, term = setup_game_retailer_terminal(
            game_type="INSTANT", threshold_cents=600000, clock="2026-01-05T00:00:00Z")
        ticket = sell_and_validate_winner(game["id"], term["id"], gross_prize_cents=1000000)
        player = create_player()
        resp = api.create_prize_claim(
            {"ticket_id": ticket["id"], "player_id": player["id"],
             "payout_option": "ANNUITY"}, CLERK)
        validate_error(resp, ApiErrorId.ERR_ANNUITY_NOT_ALLOWED.value)

    def test_claim_on_unvalidated_ticket_rejected(self, api):
        """PRD 3.5: "A claim may only be opened against a ticket whose `validation_status`
        is `VALIDATED_WINNER`; a claim against a ticket in any other state is rejected with
        `ERR_TICKET_NOT_CLAIMABLE`."

        Design: Corner/validations/claim_on_unvalidated_ticket_rejected
        """
        game, ret, term = setup_game_retailer_terminal(
            game_type="INSTANT", threshold_cents=600000, clock="2026-01-05T00:00:00Z")
        from test_helpers import sell_ticket
        ticket = sell_ticket(game["id"], term["id"], declared_tier=1,
                             gross_prize_cents=1000000)  # UNVALIDATED
        player = create_player()
        resp = api.create_prize_claim(
            {"ticket_id": ticket["id"], "player_id": player["id"],
             "payout_option": "CASH"}, CLERK)
        validate_error(resp, ApiErrorId.ERR_TICKET_NOT_CLAIMABLE.value)
