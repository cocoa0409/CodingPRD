"""Deal memo negotiation: DRAFT lifecycle, propose gate, counters, OCC, expiry."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_artist,
    create_draft_memo,
    create_label,
    get_success_data,
    make_artist_portal_headers,
    sign_artist_via_memo,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import ADMIN, ANR, FIN, MKT, set_clock, sweep_label


# ===========================================================================
# Queue A — Difficulty/non_linear_state_machine/deal_memo_negotiation_cycle
# ===========================================================================


class TestDealMemoNegotiationCycle:
    def test_counter_round_trip_proposed_countered_proposed(self):
        """PRD §3.2: "Countering is the negotiation loop: from `PROPOSED` a counter
        moves the memo to `COUNTERED`, and from `COUNTERED` a counter returns it to
        `PROPOSED`."

        Design: Difficulty/non_linear_state_machine/deal_memo_negotiation_cycle
        """
        label = create_label("Label N1")
        artist = create_artist(label["id"], "Artist N1")
        memo = create_draft_memo(artist["id"], advance_cents=100_000,
                                 base_royalty_rate_bps=2_000)
        memo_v2 = get_success_data(api_client.propose_deal_memo(memo["id"], ANR))["version"]

        # Artist counters: PROPOSED -> COUNTERED
        r1 = api_client.counter_deal_memo(
            memo["id"],
            {"expected_deal_memo_version": memo_v2, "advance_cents": 80_000},
            make_artist_portal_headers(artist["id"]),
        )
        d1 = validate_success(r1)
        assert d1["status"] == "COUNTERED"
        assert d1["round_count"] == 1
        assert d1["advance_cents"] == 80_000
        assert d1["version"] == memo_v2 + 1

        # A&R counters back: COUNTERED -> PROPOSED
        r2 = api_client.counter_deal_memo(
            memo["id"],
            {"expected_deal_memo_version": d1["version"], "advance_cents": 90_000},
            ANR,
        )
        d2 = validate_success(r2)
        assert d2["status"] == "PROPOSED"
        assert d2["round_count"] == 2
        assert d2["advance_cents"] == 90_000

    def test_counter_cycle_ends_in_approval(self):
        """PRD §3.2: "A `LabelAdmin` approves a memo from either `PROPOSED` or
        `COUNTERED`, moving it to `APPROVED`; the only guard beyond state is the
        expiry guard."

        Design: Difficulty/non_linear_state_machine/deal_memo_negotiation_cycle
        """
        label = create_label("Label N1b")
        artist = create_artist(label["id"], "Artist N1b")
        memo = create_draft_memo(artist["id"], advance_cents=100_000,
                                 base_royalty_rate_bps=2_000)
        v2 = get_success_data(api_client.propose_deal_memo(memo["id"], ANR))["version"]
        d1 = get_success_data(api_client.counter_deal_memo(
            memo["id"], {"expected_deal_memo_version": v2, "advance_cents": 80_000},
            make_artist_portal_headers(artist["id"])))
        d2 = get_success_data(api_client.counter_deal_memo(
            memo["id"], {"expected_deal_memo_version": d1["version"], "advance_cents": 90_000},
            ANR))
        # Approve after a counter round-trip
        approved = get_success_data(api_client.approve_deal_memo(memo["id"], ADMIN))
        assert approved["status"] == "APPROVED"
        # version: 1 (create) + 1 (propose) + 1 (counter) + 1 (counter) + 1 (approve) = 5
        assert approved["version"] == 5
        assert approved["round_count"] == 2


# ===========================================================================
# Queue A — Difficulty/priority_pair_validation_conflict/execute_minor_without_guardian_beats_advance_cap
# ===========================================================================


class TestExecuteGuardianBeatsAdvanceCap:
    def test_minor_no_guardian_rejected_before_advance_cap(self):
        """PRD §3.2: "Three guards apply, in this order: first, if the artist is under
        18 years old as of today, the memo must carry both `guardian_name` and
        `guardian_email`, otherwise `ERR_GUARDIAN_CONSENT_REQUIRED`; second, the expiry
        guard; third, the memo's `advance_cents` must not exceed the label's
        `advance_cap_cents`, otherwise `ERR_ADVANCE_CAP_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/execute_minor_without_guardian_beats_advance_cap
        """
        label = create_label("Label V1")
        # Artist born 2012-06-01; default clock 2026-08-01 -> 14 years old.
        artist = create_artist(label["id"], "Artist V1", birth_date="2012-06-01")
        memo = create_draft_memo(artist["id"], advance_cents=6_000_000,
                                 base_royalty_rate_bps=2_000)
        get_success_data(api_client.propose_deal_memo(memo["id"], ANR))
        get_success_data(api_client.approve_deal_memo(memo["id"], ADMIN))
        # Both guards violated: minor without guardian AND advance 6_000_000 > 5_000_000 cap.
        r = api_client.execute_deal_memo(memo["id"], ADMIN)
        validate_error(r, ApiErrorId.ERR_GUARDIAN_CONSENT_REQUIRED)
        # Memo unchanged
        after = get_success_data(api_client.get_deal_memo(memo["id"], ADMIN))
        assert after["status"] == "APPROVED"

    def test_minor_with_guardian_executes_when_advance_in_cap(self):
        """PRD §3.2: "A `LabelAdmin` executes an `APPROVED` memo, and the operation
        returns the newly created contract (HTTP 201)."
        PRD §3.2: "first, if the artist is under 18 years old as of today, the memo
        must carry both `guardian_name` and `guardian_email`, otherwise
        `ERR_GUARDIAN_CONSENT_REQUIRED`".

        Design: Difficulty/priority_pair_validation_conflict/execute_minor_without_guardian_beats_advance_cap
        """
        label = create_label("Label V1b")
        artist = create_artist(label["id"], "Artist V1b", birth_date="2012-06-01")
        memo = create_draft_memo(
            artist["id"], advance_cents=1_000_000, base_royalty_rate_bps=2_000,
            guardian_name="Guardian", guardian_email="g@example.com",
        )
        get_success_data(api_client.propose_deal_memo(memo["id"], ANR))
        get_success_data(api_client.approve_deal_memo(memo["id"], ADMIN))
        contract = validate_success(api_client.execute_deal_memo(memo["id"], ADMIN),
                                    expected_status=201)
        assert contract["status"] == "ACTIVE"
        memo_after = get_success_data(api_client.get_deal_memo(memo["id"], ADMIN))
        assert memo_after["status"] == "EXECUTED"


# ===========================================================================
# Queue B — state_machines basics on DealMemo
# ===========================================================================


class TestMemoDraftThenPropose:
    def test_memo_draft_then_propose(self):
        """PRD §3.1: "A new artist starts in `SCOUTED` status. When the first deal
        memo for a scouted artist is proposed, the artist moves from `SCOUTED` to
        `IN_NEGOTIATION`".
        PRD §3.2: "Proposing moves a memo from `DRAFT` to `PROPOSED`."

        Design: Corner/state_machines/memo_initial_state_draft_then_propose_valid
        """
        label = create_label("Label S1")
        artist = create_artist(label["id"], "Artist S1")
        memo = create_draft_memo(artist["id"], advance_cents=50_000)
        assert memo["status"] == "DRAFT"
        proposed = get_success_data(api_client.propose_deal_memo(memo["id"], ANR))
        assert proposed["status"] == "PROPOSED"
        artist_after = get_success_data(api_client.get_artist(artist["id"], ADMIN))
        assert artist_after["status"] == "IN_NEGOTIATION"


class TestMemoProposeTwice:
    def test_propose_twice_rejected(self):
        """PRD §2.9: "Seventh, the attempted state transition must be declared from
        the resource's current status — attempts from terminal states included
        (`ERR_INVALID_STATE`)."
        PRD §3.2: "Proposing moves a memo from `DRAFT` to `PROPOSED`."

        Design: Corner/state_machines/memo_propose_twice_returns_invalid_state
        """
        label = create_label("Label S2")
        artist = create_artist(label["id"], "Artist S2")
        memo = create_draft_memo(artist["id"], advance_cents=50_000)
        get_success_data(api_client.propose_deal_memo(memo["id"], ANR))
        r = api_client.propose_deal_memo(memo["id"], ANR)
        validate_error(r, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api_client.get_deal_memo(memo["id"], ADMIN))
        assert after["status"] == "PROPOSED"
        assert after["round_count"] == 0


class TestMemoAlreadyOpen:
    def test_second_memo_rejected(self):
        """PRD §3.2: "An artist may have at most one open memo — one in `DRAFT`,
        `PROPOSED`, `COUNTERED`, or `APPROVED` — so drafting while another memo is
        open is rejected with `ERR_DEAL_MEMO_ALREADY_OPEN`."

        Design: Corner/validations/memo_already_open_rejected
        """
        label = create_label("Label Vb3")
        artist = create_artist(label["id"], "Artist Vb3")
        create_draft_memo(artist["id"], advance_cents=50_000)
        r = api_client.create_deal_memo(artist["id"], {
            "advance_cents": 60_000,
            "base_royalty_rate_bps": 2_000,
            "recoupment_scope": "MASTER_ONLY",
            "promo_costs_recoupable": False,
            "options_total": 0,
            "option_term_months": 12,
            "option_escalation_bps": 0,
            "term_months": 12,
            "valid_until_date": "2028-01-01",
        }, ANR)
        validate_error(r, ApiErrorId.ERR_DEAL_MEMO_ALREADY_OPEN)
        data, meta = validate_paginated(api_client.list_artist_deal_memos(artist["id"], ADMIN))
        assert meta["total_count"] == 1


class TestMemoExpirySweep:
    def test_sweep_expires_memo_and_reverts_artist(self):
        """PRD §3.2: "Memos also expire: from any of `DRAFT`, `PROPOSED`, `COUNTERED`,
        or `APPROVED`, a memo whose `valid_until_date` has passed moves to `EXPIRED`,
        either during the housekeeping sweep or lazily when a guarded transition —
        propose, counter, approve, or execute — is attempted against it".
        PRD §3.1: "If that negotiation later collapses — the memo is rejected, or it
        expires — and the artist has no other memo in `DRAFT`, `PROPOSED`, `COUNTERED`,
        or `APPROVED` and no contract at all, the artist reverts from `IN_NEGOTIATION`
        back to `SCOUTED`."

        Design: Corner/state_machines/sweep_expires_memo_and_reverts_artist
        """
        label = create_label("Label S6")
        artist = create_artist(label["id"], "Artist S6")
        memo = create_draft_memo(artist["id"], advance_cents=50_000,
                                 valid_until_date="2026-08-10")
        get_success_data(api_client.propose_deal_memo(memo["id"], ANR))
        set_clock("2026-08-11T00:00:00Z")
        sweep = get_success_data(api_client.sweep_label(label["id"], ADMIN))
        assert memo["id"] in sweep["expired_deal_memo_ids"]
        memo_after = get_success_data(api_client.get_deal_memo(memo["id"], ADMIN))
        assert memo_after["status"] == "EXPIRED"
        artist_after = get_success_data(api_client.get_artist(artist["id"], ADMIN))
        assert artist_after["status"] == "SCOUTED"


class TestMemoLazyExpiry:
    def test_propose_after_valid_until_expires_lazily(self):
        """PRD §3.2: "Memos also expire: ... or lazily when a guarded transition —
        propose, counter, approve, or execute — is attempted against it, in which
        case the attempt is rejected with `ERR_DEAL_MEMO_EXPIRED` as the memo expires."

        Design: Corner/validations/memo_expired_lazy_transition
        """
        label = create_label("Label Vb4")
        artist = create_artist(label["id"], "Artist Vb4")
        memo = create_draft_memo(artist["id"], advance_cents=50_000,
                                 valid_until_date="2026-08-10")
        set_clock("2026-08-11T00:00:00Z")
        r = api_client.propose_deal_memo(memo["id"], ANR)
        validate_error(r, ApiErrorId.ERR_DEAL_MEMO_EXPIRED)
        after = get_success_data(api_client.get_deal_memo(memo["id"], ADMIN))
        assert after["status"] == "EXPIRED"


class TestMemoTerminalLockdown:
    def test_reject_on_executed_memo_rejected(self):
        """PRD §3.2: "And the memo's `contract_id` is set to the new contract while
        the memo itself becomes `EXECUTED`, which is terminal."
        PRD §2.9: "Seventh, the attempted state transition must be declared from the
        resource's current status — attempts from terminal states included
        (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/memo_terminal_lockdown
        """
        label = create_label("Label S8")
        artist = create_artist(label["id"], "Artist S8")
        memo, _contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        r = api_client.reject_deal_memo(memo["id"], ANR)
        validate_error(r, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api_client.get_deal_memo(memo["id"], ADMIN))
        assert after["status"] == "EXECUTED"


class TestMemoScoreGate:
    def test_score_exactly_at_threshold_passes(self):
        """PRD §3.2: "the artist's `scouting_score` must be at least the label's
        `sign_threshold_score`, otherwise `ERR_SCOUTING_SCORE_TOO_LOW`".
        PRD §3.1: "`sign_threshold_score` (default 40.0) is the minimum scouting
        score required to propose a deal memo."

        Design: Corner/validations/score_gate_exactly_at_threshold_passes
        """
        label = create_label("Label Vb1")
        # ROCK: raw = 100*(0 + 0 + 0.25*0.6 + 0.25*1.0) = 40.0; * 1.00 = 40.0
        artist = create_artist(label["id"], "Edge Act", genre="ROCK",
                               monthly_streams=0, social_followers=0,
                               engagement_rate=0.6, live_draw_avg=2_000)
        assert artist["scouting_score"] == pytest.approx(40.0, abs=1e-9)
        memo = create_draft_memo(artist["id"], advance_cents=50_000)
        proposed = get_success_data(api_client.propose_deal_memo(memo["id"], ANR))
        assert proposed["status"] == "PROPOSED"

    def test_score_below_gate_rejected(self):
        """PRD §3.2: "the artist's `scouting_score` must be at least the label's
        `sign_threshold_score`, otherwise `ERR_SCOUTING_SCORE_TOO_LOW`".

        Design: Corner/validations/score_below_gate_rejected
        """
        label = create_label("Label Vb2")
        # OTHER multiplier 0.90; raw = 100*(0.30*0.01 + 0.20*0.01 + 0.25*0.1 + 0.25*0.025) = 3.625; * 0.9 = 3.2625 -> 3.3
        artist = create_artist(label["id"], "Low Act", genre="OTHER",
                               monthly_streams=10_000, social_followers=20_000,
                               engagement_rate=0.1, live_draw_avg=50)
        assert artist["scouting_score"] < 40.0
        memo = create_draft_memo(artist["id"], advance_cents=50_000)
        r = api_client.propose_deal_memo(memo["id"], ANR)
        validate_error(r, ApiErrorId.ERR_SCOUTING_SCORE_TOO_LOW)
        memo_after = get_success_data(api_client.get_deal_memo(memo["id"], ADMIN))
        assert memo_after["status"] == "DRAFT"
        artist_after = get_success_data(api_client.get_artist(artist["id"], ADMIN))
        assert artist_after["status"] == "SCOUTED"


class TestMemoRbac:
    def test_marketing_cannot_execute_memo(self):
        """PRD §2.1: "A request whose role is not in the target endpoint's authorized
        role list is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4 table: `POST /api/deal-memos/{id}/execute` — LabelAdmin.

        Design: Corner/rbac/marketing_manager_cannot_execute_memo
        """
        label = create_label("Label R1")
        artist = create_artist(label["id"], "Artist R1")
        memo = create_draft_memo(artist["id"], advance_cents=50_000)
        get_success_data(api_client.propose_deal_memo(memo["id"], ANR))
        get_success_data(api_client.approve_deal_memo(memo["id"], ADMIN))
        r = api_client.execute_deal_memo(memo["id"], MKT)
        validate_error(r, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        after = get_success_data(api_client.get_deal_memo(memo["id"], ADMIN))
        assert after["status"] == "APPROVED"


class TestMemoCreateValidation:
    def test_missing_required_field_returns_invalid_request(self):
        """PRD §2.9: "Fifth, the request body itself is validated — required fields
        present, types correct, enum membership, and numeric ranges ...
        (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/memo_create_missing_required_field_returns_invalid_request
        """
        label = create_label("Label E4")
        artist = create_artist(label["id"], "Artist E4")
        payload = {
            # advance_cents intentionally omitted
            "base_royalty_rate_bps": 2_000,
            "recoupment_scope": "MASTER_ONLY",
            "promo_costs_recoupable": False,
            "options_total": 0,
            "option_term_months": 12,
            "option_escalation_bps": 0,
            "term_months": 12,
            "valid_until_date": "2028-01-01",
        }
        r = api_client.create_deal_memo(artist["id"], payload, ANR)
        validate_error(r, ApiErrorId.ERR_INVALID_REQUEST)
        _data, meta = validate_paginated(api_client.list_artist_deal_memos(artist["id"], ADMIN))
        assert meta["total_count"] == 0


class TestMemoOccCounter:
    def test_stale_counter_rejected(self):
        """PRD §2.8: "Countering a deal memo requires `expected_deal_memo_version`
        to match the deal memo's current `version`. ... a mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_memo_counter_stale_version
        """
        label = create_label("Label L1")
        artist = create_artist(label["id"], "Artist L1")
        memo = create_draft_memo(artist["id"], advance_cents=50_000)
        v2 = get_success_data(api_client.propose_deal_memo(memo["id"], ANR))["version"]
        # First counter at v2 succeeds -> v3
        d = get_success_data(api_client.counter_deal_memo(
            memo["id"], {"expected_deal_memo_version": v2, "advance_cents": 45_000}, ANR))
        assert d["version"] == v2 + 1
        assert d["status"] == "COUNTERED"
        assert d["round_count"] == 1
        # Stale counter carrying the pre-counter v2 rejected
        r = api_client.counter_deal_memo(
            memo["id"], {"expected_deal_memo_version": v2, "advance_cents": 40_000},
            make_artist_portal_headers(artist["id"]))
        validate_error(r, ApiErrorId.ERR_STALE_VERSION)
        after = get_success_data(api_client.get_deal_memo(memo["id"], ADMIN))
        assert after["version"] == v2 + 1
        assert after["advance_cents"] == 45_000
