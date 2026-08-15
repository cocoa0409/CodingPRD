"""Tournament lifecycle, section gates, entry fees, refunds, and cancel cascade
(PRD §2.10, §3.5, §3.7)."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    club_balance,
    create_entry,
    create_membership,
    create_player,
    create_section,
    create_tournament,
    fund_club,
    get_club,
    get_player,
    make_club_coach_headers,
    open_tournament,
    setup_one_club,
    setup_open_tournament_with_section,
    start_tournament_with_proctor,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["federation_admin_headers"]

def _entry_fee_ledger_rows(api, club_id, entry_type="ENTRY_FEE"):
    rows, _ = validate_paginated(
        api.list_ledger_entries(ADMIN, params={"club_id": club_id, "entry_type": entry_type})
    )
    return rows

# ─── Registration cycle (queue A) ──

def test_tournament_registration_reopen_cycle(api, federation_admin_headers):
    """PRD §3.7: "A tournament begins in `DRAFT`, opens for registration
    (`REGISTRATION_OPEN`), closes (`REGISTRATION_CLOSED`), may reopen to
    `REGISTRATION_OPEN` again, starts (`RUNNING`), and completes (`COMPLETED`) — each
    step guarded by `ERR_TOURNAMENT_INVALID_STATE` from the wrong state."

    Design: Difficulty/non_linear_state_machine/tournament_registration_reopen_cycle
    """
    ctx = setup_one_club(fund=5000, num_players=1)
    tournament, section = setup_open_tournament_with_section(
        ctx["season"]["id"],
        tournament_overrides={"entry_fee_cents": 1035,
                              "early_bird_deadline": "2026-09-15T00:00:00Z",
                              "early_bird_discount_pct": 0.10},
    )
    closed = validate_success(api.close_registration(tournament["id"], federation_admin_headers))
    assert closed["status"] == "REGISTRATION_CLOSED"
    reopened = validate_success(api.reopen_registration(tournament["id"], federation_admin_headers))
    assert reopened["status"] == "REGISTRATION_OPEN", "the close -> reopen lap is legal"

def test_entry_accepted_after_reopen(api, federation_admin_headers):
    """PRD §3.7: "may reopen to `REGISTRATION_OPEN` again" — entries created after the
    reopen are accepted and charged. PRD §3.7: "When the tournament has an early-bird
    deadline and the logical clock reads at or before it — the boundary is inclusive —
    the fee is the round-half-up of `entry_fee_cents` multiplied by one minus
    `early_bird_discount_pct`".

    Design: Difficulty/non_linear_state_machine/tournament_registration_reopen_cycle
    """
    ctx = setup_one_club(fund=5000, num_players=1)
    tournament, section = setup_open_tournament_with_section(
        ctx["season"]["id"],
        tournament_overrides={"entry_fee_cents": 1035,
                              "early_bird_deadline": "2026-09-15T00:00:00Z",
                              "early_bird_discount_pct": 0.10},
    )
    validate_success(api.close_registration(tournament["id"], federation_admin_headers))
    validate_success(api.reopen_registration(tournament["id"], federation_admin_headers))

    entry = create_entry(section["id"], ctx["players"][0]["id"], ctx["coach"]["id"])
    assert entry["status"] == "REGISTERED"
    assert entry["fee_cents"] == 932, "round_half_up(1035 * 0.9) = round_half_up(931.5) = 932"

# ─── Cross-entity state gates (queue A) ──

def test_entry_requires_tournament_registration_open(api, federation_admin_headers):
    """PRD §3.7: "Its checks run in the ladder order of §2.10, and within the state
    rung the order is pinned: the tournament must be `REGISTRATION_OPEN` first
    (`ERR_TOURNAMENT_INVALID_STATE`), and only then is the section checked to be `OPEN`
    (`ERR_SECTION_INVALID_STATE`)."

    Design: Difficulty/cross_entity_state_dependency/entry_requires_tournament_registration_open
    """
    ctx = setup_one_club(num_players=1)
    tournament = create_tournament(ctx["season"]["id"], entry_fee_cents=0)  # stays DRAFT
    section = create_section(tournament["id"])

    res = api.create_entry(section["id"], {"player_id": ctx["players"][0]["id"]},
                           make_club_coach_headers(ctx["coach"]["id"]))
    validate_error(res, ApiErrorId.ERR_TOURNAMENT_INVALID_STATE)

def test_entry_in_draft_tournament_has_no_side_effects(api, federation_admin_headers):
    """PRD §3.7: "the tournament must be `REGISTRATION_OPEN` first
    (`ERR_TOURNAMENT_INVALID_STATE`)". A rejected entry mutates nothing.

    Design: Difficulty/cross_entity_state_dependency/entry_requires_tournament_registration_open
    """
    ctx = setup_one_club(num_players=1)
    tournament = create_tournament(ctx["season"]["id"], entry_fee_cents=0)
    section = create_section(tournament["id"])

    validate_error(
        api.create_entry(section["id"], {"player_id": ctx["players"][0]["id"]},
                         make_club_coach_headers(ctx["coach"]["id"])),
        ApiErrorId.ERR_TOURNAMENT_INVALID_STATE,
    )
    after = validate_success(api.get_section(section["id"], federation_admin_headers))
    assert after["current_entries"] == 0

# ─── Validation ladder pairs (queue A) ──

def _running_tournament_ctx(entry_fee_cents=1035, fund=None):
    """Club + player (WAIVED) + RUNNING tournament with one (now CLOSED) section."""
    ctx = setup_one_club(fund=fund, num_players=1)
    tournament, section = setup_open_tournament_with_section(
        ctx["season"]["id"], tournament_overrides={"entry_fee_cents": entry_fee_cents}
    )
    start_tournament_with_proctor(tournament["id"], ctx["coach"]["id"])
    return ctx, tournament, section

def test_entry_state_beats_fiscal(api):
    """PRD §2.10: "Every request is evaluated against a fixed ladder of checks, and the
    first failing rung determines the error returned." Rung 8 is "State checks" and
    rung 13 is "Fiscal guard — a charge that would drive a club's balance below zero
    yields `ERR_INSUFFICIENT_FUNDS` (HTTP 402)" — so entering a RUNNING tournament with
    an unfunded club reports the state error, not the fiscal one.

    Design: Difficulty/priority_pair_validation_conflict/entry_state_beats_fiscal
    """
    ctx, tournament, section = _running_tournament_ctx(entry_fee_cents=1035, fund=None)
    assert club_balance(ctx["club"]["id"]) == 0, "club is unfunded (0 < 1035)"

    res = api.create_entry(section["id"], {"player_id": ctx["players"][0]["id"]},
                           make_club_coach_headers(ctx["coach"]["id"]))
    validate_error(res, ApiErrorId.ERR_TOURNAMENT_INVALID_STATE)
    assert res.status_code == 409, "state (409) outranks fiscal (402)"

def test_entry_state_beats_fiscal_no_side_effects(api, federation_admin_headers):
    """PRD §2.10: rung 8 "State checks" precede rung 13 "Fiscal guard — a charge that
    would drive a club's balance below zero yields `ERR_INSUFFICIENT_FUNDS` (HTTP
    402)". The rejected entry posts no fee and bumps no counter.

    Design: Difficulty/priority_pair_validation_conflict/entry_state_beats_fiscal
    """
    ctx, tournament, section = _running_tournament_ctx(entry_fee_cents=1035, fund=None)
    validate_error(
        api.create_entry(section["id"], {"player_id": ctx["players"][0]["id"]},
                         make_club_coach_headers(ctx["coach"]["id"])),
        ApiErrorId.ERR_TOURNAMENT_INVALID_STATE,
    )
    after = validate_success(api.get_section(section["id"], federation_admin_headers))
    assert after["current_entries"] == 0
    assert club_balance(ctx["club"]["id"]) == 0
    assert _entry_fee_ledger_rows(api, ctx["club"]["id"]) == []

def test_entry_referential_beats_constraint(api):
    """PRD §2.10: "Every request is evaluated against a fixed ladder of checks, and the
    first failing rung determines the error returned." Rung 10 is "Business referential
    rules — a pairing or entry for a player lacking a paid-or-waived membership yields
    `ERR_MEMBERSHIP_REQUIRED` (HTTP 409)"; rung 11 is "Business constraints — a rating
    outside a section's band (`ERR_RATING_OUT_OF_BAND`)". An unpaid player whose rating
    is also out of band reports the referential error.

    Design: Difficulty/priority_pair_validation_conflict/entry_referential_beats_constraint
    """
    ctx = setup_one_club(fund=5000, num_players=0)
    player = create_player(ctx["club"]["id"], full_name="P1",
                           initial_rating=500, initial_rated_games=25)
    create_membership(player["id"], ctx["season"]["id"])  # left INVOICED
    tournament, section = setup_open_tournament_with_section(
        ctx["season"]["id"],
        tournament_overrides={"entry_fee_cents": 1035},
        section_overrides={"name": "U1200", "min_rating": 1000, "max_rating": 1200,
                           "allow_provisional": True},
    )
    res = api.create_entry(section["id"], {"player_id": player["id"]},
                           make_club_coach_headers(ctx["coach"]["id"]))
    validate_error(res, ApiErrorId.ERR_MEMBERSHIP_REQUIRED)

def test_entry_referential_beats_constraint_no_side_effects(api, federation_admin_headers):
    """PRD §2.10: rung 10 "Business referential rules — a pairing or entry for a player
    lacking a paid-or-waived membership yields `ERR_MEMBERSHIP_REQUIRED` (HTTP 409)"
    precedes rung 11's "a rating outside a section's band (`ERR_RATING_OUT_OF_BAND`)".

    Design: Difficulty/priority_pair_validation_conflict/entry_referential_beats_constraint
    """
    ctx = setup_one_club(fund=5000, num_players=0)
    player = create_player(ctx["club"]["id"], full_name="P1",
                           initial_rating=500, initial_rated_games=25)
    create_membership(player["id"], ctx["season"]["id"])  # INVOICED
    tournament, section = setup_open_tournament_with_section(
        ctx["season"]["id"],
        tournament_overrides={"entry_fee_cents": 1035},
        section_overrides={"name": "U1200", "min_rating": 1000, "max_rating": 1200,
                           "allow_provisional": True},
    )
    validate_error(
        api.create_entry(section["id"], {"player_id": player["id"]},
                         make_club_coach_headers(ctx["coach"]["id"])),
        ApiErrorId.ERR_MEMBERSHIP_REQUIRED,
    )
    after = validate_success(api.get_section(section["id"], federation_admin_headers))
    assert after["current_entries"] == 0
    assert _entry_fee_ledger_rows(api, ctx["club"]["id"]) == []

# ─── Boundary precision (queue A) ──

def _band_section_ctx():
    """Club funded 5000; players at 1200/25 and 1201/25; section [1000, 1200]."""
    ctx = setup_one_club(
        fund=5000,
        player_overrides=[{"initial_rating": 1200, "initial_rated_games": 25},
                          {"initial_rating": 1201, "initial_rated_games": 25}],
    )
    tournament, section = setup_open_tournament_with_section(
        ctx["season"]["id"],
        tournament_overrides={"entry_fee_cents": 1035},
        section_overrides={"name": "U1200", "min_rating": 1000, "max_rating": 1200,
                           "allow_provisional": False},
    )
    return ctx, section

def test_section_rating_band_inclusive_max_accepts(api):
    """PRD §3.7: "Each section is created with a `name`, an inclusive lower rating bound
    `min_rating` and an inclusive upper bound `max_rating` that must be at least the
    minimum" and "the player's current `rating` must fall within the section's
    inclusive band (`ERR_RATING_OUT_OF_BAND`)". Rating exactly equal to the inclusive
    upper bound is inside the band.

    Design: Difficulty/boundary_precision_check/section_rating_band_inclusive_max
    """
    ctx, section = _band_section_ctx()
    entry = create_entry(section["id"], ctx["players"][0]["id"], ctx["coach"]["id"])
    assert entry["status"] == "REGISTERED"
    assert entry["fee_cents"] == 1035, "no early-bird configured -> full fee"

def test_section_rating_band_one_over_max_rejected(api):
    """PRD §3.7: "the player's current `rating` must fall within the section's
    inclusive band (`ERR_RATING_OUT_OF_BAND`)". One point above the inclusive maximum
    is outside the band.

    Design: Difficulty/boundary_precision_check/section_rating_band_inclusive_max
    """
    ctx, section = _band_section_ctx()
    res = api.create_entry(section["id"], {"player_id": ctx["players"][1]["id"]},
                           make_club_coach_headers(ctx["coach"]["id"]))
    validate_error(res, ApiErrorId.ERR_RATING_OUT_OF_BAND)

def _capacity_section_ctx(max_entries=2):
    ctx = setup_one_club(num_players=3)
    tournament, section = setup_open_tournament_with_section(
        ctx["season"]["id"],
        tournament_overrides={"entry_fee_cents": 0},
        section_overrides={"max_entries": max_entries},
    )
    return ctx, section

def test_section_capacity_last_seat_accepted(api, federation_admin_headers):
    """PRD §3.7: "the section must have room — `current_entries` equal to `max_entries`
    means full (`ERR_SECTION_FULL`)". With current_entries 1 < max_entries 2 the seat
    is still free.

    Design: Difficulty/boundary_precision_check/section_capacity_last_seat
    """
    ctx, section = _capacity_section_ctx(max_entries=2)
    create_entry(section["id"], ctx["players"][0]["id"], ctx["coach"]["id"])
    second = create_entry(section["id"], ctx["players"][1]["id"], ctx["coach"]["id"])
    assert second["status"] == "REGISTERED"
    after = validate_success(api.get_section(section["id"], federation_admin_headers))
    assert after["current_entries"] == 2

def test_section_capacity_at_max_rejected(api, federation_admin_headers):
    """PRD §3.7: "the section must have room — `current_entries` equal to `max_entries`
    means full (`ERR_SECTION_FULL`)". At current_entries == max_entries the next entry
    is rejected.

    Design: Difficulty/boundary_precision_check/section_capacity_last_seat
    """
    ctx, section = _capacity_section_ctx(max_entries=2)
    create_entry(section["id"], ctx["players"][0]["id"], ctx["coach"]["id"])
    create_entry(section["id"], ctx["players"][1]["id"], ctx["coach"]["id"])
    res = api.create_entry(section["id"], {"player_id": ctx["players"][2]["id"]},
                           make_club_coach_headers(ctx["coach"]["id"]))
    validate_error(res, ApiErrorId.ERR_SECTION_FULL)
    after = validate_success(api.get_section(section["id"], federation_admin_headers))
    assert after["current_entries"] == 2

# ─── Per-entry rounding (queue A) ──

def _rounding_ctx():
    """Club funded 5000; tournament fee 1035 with 10% early-bird (deadline after the
    default clock); three players with WAIVED memberships."""
    ctx = setup_one_club(fund=5000, num_players=3)
    tournament, section = setup_open_tournament_with_section(
        ctx["season"]["id"],
        tournament_overrides={"entry_fee_cents": 1035,
                              "early_bird_deadline": "2026-09-15T00:00:00Z",
                              "early_bird_discount_pct": 0.10},
    )
    return ctx, section

def test_entry_fee_rounded_per_entry(api):
    """PRD §3.7: "Rounding order is pinned: each entry's fee is rounded to whole cents
    at creation, and a club's total charge is the sum of the per-entry rounded fees,
    never a rounding of the unrounded sum."
    PRD §3.7: "otherwise an `ENTRY_FEE` ledger entry posts for exactly `fee_cents` with
    `entry_id` set".

    Design: Difficulty/combinatorial_formula/entry_fee_per_entry_rounding
    """
    ctx, section = _rounding_ctx()
    fees = []
    for player in ctx["players"]:
        entry = create_entry(section["id"], player["id"], ctx["coach"]["id"])
        fees.append(entry["fee_cents"])
    assert fees == [932, 932, 932], "round_half_up(1035 * 0.9 = 931.5) = 932 per entry"

    rows = _entry_fee_ledger_rows(api, ctx["club"]["id"], entry_type="ENTRY_FEE")
    assert len(rows) == 3
    assert all(row["amount_cents"] == -932 for row in rows), "each row debits exactly 932"
    assert all(row.get("entry_id") for row in rows)

def test_entry_fee_sum_of_rounded_not_round_of_sum(api):
    """PRD §3.7: "Rounding order is pinned: each entry's fee is rounded to whole cents
    at creation, and a club's total charge is the sum of the per-entry rounded fees,
    never a rounding of the unrounded sum." 3 x 932 = 2796; the sum-then-round
    alternative (round(3 x 931.5) = 2795) is wrong.

    Design: Difficulty/combinatorial_formula/entry_fee_per_entry_rounding
    """
    ctx, section = _rounding_ctx()
    for player in ctx["players"]:
        create_entry(section["id"], player["id"], ctx["coach"]["id"])
    balance = club_balance(ctx["club"]["id"])
    assert balance == 2204, f"5000 - 2796 = 2204 (not 2205); got {balance}"

# ─── Cancel cascade (queue A) ──

def _cancel_cascade_ctx():
    """Club funded 5000, two entries at 932 (balance 3136), then a -3500 adjustment
    (balance -364, DELINQUENT); tournament still REGISTRATION_OPEN."""
    ctx = setup_one_club(fund=5000, num_players=2)
    tournament, section = setup_open_tournament_with_section(
        ctx["season"]["id"],
        tournament_overrides={"entry_fee_cents": 1035,
                              "early_bird_deadline": "2026-09-15T00:00:00Z",
                              "early_bird_discount_pct": 0.10},
    )
    e1 = create_entry(section["id"], ctx["players"][0]["id"], ctx["coach"]["id"])
    e2 = create_entry(section["id"], ctx["players"][1]["id"], ctx["coach"]["id"])
    fund_club(ctx["club"]["id"], -3500, memo="sanction fine")
    return ctx, tournament, [e1, e2]

def test_tournament_cancel_withdraws_and_refunds(api, federation_admin_headers):
    """PRD §3.7: "the cancel unwinds money in a four-link cascade: first, every entry
    in `REGISTERED` or `CHECKED_IN` becomes `WITHDRAWN` with `refund_cents` set to the
    full `fee_cents` regardless of tournament state; second, for each withdrawn entry
    an `ENTRY_REFUND` ledger entry crediting exactly that entry's fee posts with
    `entry_id` set; third, each affected club's `account_balance_cents` is recomputed;
    fourth, each club's standing auto-transition is applied."

    Design: Difficulty/transitive_cascade/tournament_cancel_refund_cascade
    """
    ctx, tournament, entries = _cancel_cascade_ctx()
    before = get_club(ctx["club"]["id"])
    assert before["account_balance_cents"] == -364 and before["status"] == "DELINQUENT"

    validate_success(api.cancel_tournament(tournament["id"], federation_admin_headers))

    for entry in entries:
        after = validate_success(api.get_entry(entry["id"], federation_admin_headers))
        assert after["status"] == "WITHDRAWN"
        assert after["refund_cents"] == 932, "cancel cascade refunds 100% of the fee"
    refunds = _entry_fee_ledger_rows(api, ctx["club"]["id"], entry_type="ENTRY_REFUND")
    assert len(refunds) == 2
    assert all(row["amount_cents"] == 932 for row in refunds)

def test_tournament_cancel_restores_standing(api, federation_admin_headers):
    """PRD §3.7: "third, each affected club's `account_balance_cents` is recomputed;
    fourth, each club's standing auto-transition is applied."
    PRD §3.2: "a club in `DELINQUENT` whose balance has returned to zero or above flips
    back to `GOOD_STANDING`."

    Design: Difficulty/transitive_cascade/tournament_cancel_refund_cascade
    """
    ctx, tournament, _entries = _cancel_cascade_ctx()
    validate_success(api.cancel_tournament(tournament["id"], federation_admin_headers))

    after = get_club(ctx["club"]["id"])
    assert after["account_balance_cents"] == 1500, "-364 + 2 x 932 = 1500"
    assert after["status"] == "GOOD_STANDING", "the refund lifts the club out of DELINQUENT"

# ─── Queue B: tournament/entry violations and cascades ──

def test_tournament_capacity_exceeded(api):
    """PRD §3.7: "the tournament's total non-withdrawn entries across all sections must
    remain within `capacity` (`ERR_TOURNAMENT_CAPACITY_EXCEEDED`)". Capacity spans
    sections.

    Design: Corner/errors/tournament_capacity_exceeded
    """
    ctx = setup_one_club(num_players=2)
    tournament = create_tournament(ctx["season"]["id"], entry_fee_cents=0, capacity=1)
    s1 = create_section(tournament["id"], name="S1")
    s2 = create_section(tournament["id"], name="S2")
    open_tournament(tournament["id"])
    create_entry(s1["id"], ctx["players"][0]["id"], ctx["coach"]["id"])

    res = api.create_entry(s2["id"], {"player_id": ctx["players"][1]["id"]},
                           make_club_coach_headers(ctx["coach"]["id"]))
    validate_error(res, ApiErrorId.ERR_TOURNAMENT_CAPACITY_EXCEEDED)

def test_entry_into_locked_section_rejected(api):
    """PRD §3.7: "the tournament must be `REGISTRATION_OPEN` first
    (`ERR_TOURNAMENT_INVALID_STATE`), and only then is the section checked to be `OPEN`
    (`ERR_SECTION_INVALID_STATE`)."

    Design: Corner/errors/entry_into_locked_section_rejected
    """
    ctx = setup_one_club(num_players=1)
    tournament, section = setup_open_tournament_with_section(
        ctx["season"]["id"], tournament_overrides={"entry_fee_cents": 0}
    )
    validate_success(api.lock_section(section["id"], ADMIN))
    res = api.create_entry(section["id"], {"player_id": ctx["players"][0]["id"]},
                           make_club_coach_headers(ctx["coach"]["id"]))
    validate_error(res, ApiErrorId.ERR_SECTION_INVALID_STATE)

def test_validation_duplicate_entry(api):
    """PRD §3.7: "the player may hold only one non-`WITHDRAWN` entry per section
    (`ERR_DUPLICATE_ENTRY`)."

    Design: Corner/validations/validation_duplicate_entry
    """
    ctx = setup_one_club(num_players=1)
    tournament, section = setup_open_tournament_with_section(
        ctx["season"]["id"], tournament_overrides={"entry_fee_cents": 0}
    )
    create_entry(section["id"], ctx["players"][0]["id"], ctx["coach"]["id"])
    res = api.create_entry(section["id"], {"player_id": ctx["players"][0]["id"]},
                           make_club_coach_headers(ctx["coach"]["id"]))
    validate_error(res, ApiErrorId.ERR_DUPLICATE_ENTRY)

def test_validation_provisional_not_allowed(api):
    """PRD §3.7: "a provisional player may enter only if the section allows it
    (`ERR_PROVISIONAL_NOT_ALLOWED`)". The rating-band and provisional gates are
    independent: an in-band provisional player is still rejected.

    Design: Corner/validations/validation_provisional_not_allowed
    """
    ctx = setup_one_club(season_overrides={"provisional_game_threshold": 4,
                                           "base_rating": 800},
                         num_players=1)
    assert get_player(ctx["players"][0]["id"])["is_provisional"] is True
    tournament, section = setup_open_tournament_with_section(
        ctx["season"]["id"],
        tournament_overrides={"entry_fee_cents": 0},
        section_overrides={"allow_provisional": False},
    )
    res = api.create_entry(section["id"], {"player_id": ctx["players"][0]["id"]},
                           make_club_coach_headers(ctx["coach"]["id"]))
    validate_error(res, ApiErrorId.ERR_PROVISIONAL_NOT_ALLOWED)

def test_early_bird_deadline_boundary(api, federation_admin_headers):
    """PRD §3.7: "When the tournament has an early-bird deadline and the logical clock
    reads at or before it — the boundary is inclusive — the fee is the round-half-up of
    `entry_fee_cents` multiplied by one minus `early_bird_discount_pct`; otherwise the
    full `entry_fee_cents` is charged."

    Design: Corner/calculations/early_bird_deadline_boundary
    """
    ctx = setup_one_club(fund=5000, num_players=2)
    tournament, section = setup_open_tournament_with_section(
        ctx["season"]["id"],
        tournament_overrides={"entry_fee_cents": 1035,
                              "early_bird_deadline": "2026-09-15T00:00:00Z",
                              "early_bird_discount_pct": 0.10},
    )
    validate_success(
        api.set_clock({"to_iso8601": "2026-09-15T00:00:00Z"}, federation_admin_headers)
    )
    e1 = create_entry(section["id"], ctx["players"][0]["id"], ctx["coach"]["id"])
    assert e1["fee_cents"] == 932, "at exactly the deadline the discount applies"

    validate_success(
        api.set_clock({"to_iso8601": "2026-09-15T00:00:01Z"}, federation_admin_headers)
    )
    e2 = create_entry(section["id"], ctx["players"][1]["id"], ctx["coach"]["id"])
    assert e2["fee_cents"] == 1035, "one second later the full fee is charged"

def test_withdrawal_refund_tiers(api, federation_admin_headers):
    """PRD §3.7: "A manual withdrawal while the tournament is `REGISTRATION_OPEN`
    refunds the full fee; while `REGISTRATION_CLOSED`, half the fee rounded half up;
    while `RUNNING` or `COMPLETED`, nothing. Two overrides sit on top of that table: a
    manual withdrawal from `CHECKED_IN` always refunds zero regardless of tournament
    state, and the tournament-cancel cascade always refunds the full fee regardless of
    state."

    Design: Corner/calculations/withdrawal_refund_tiers
    """
    ctx = setup_one_club(fund=5000, num_players=3)
    tournament, section = setup_open_tournament_with_section(
        ctx["season"]["id"],
        tournament_overrides={"entry_fee_cents": 1035,
                              "early_bird_deadline": "2026-09-15T00:00:00Z",
                              "early_bird_discount_pct": 0.10},
    )
    entries = [
        create_entry(section["id"], player["id"], ctx["coach"]["id"])
        for player in ctx["players"]
    ]

    # Tier 1: withdrawn while REGISTRATION_OPEN -> 100% (932)
    w1 = validate_success(api.withdraw_entry(
        entries[0]["id"], make_club_coach_headers(ctx["coach"]["id"])))
    assert w1["refund_cents"] == 932

    # Tier 2: withdrawn while REGISTRATION_CLOSED -> round_half_up(932 * 0.5) = 466
    validate_success(api.close_registration(tournament["id"], federation_admin_headers))
    w2 = validate_success(api.withdraw_entry(
        entries[1]["id"], make_club_coach_headers(ctx["coach"]["id"])))
    assert w2["refund_cents"] == 466

    # Override: withdrawn from CHECKED_IN while RUNNING -> 0
    start_tournament_with_proctor(tournament["id"], ctx["coach"]["id"])
    validate_success(api.check_in_entry(entries[2]["id"], ADMIN))
    w3 = validate_success(api.withdraw_entry(
        entries[2]["id"], make_club_coach_headers(ctx["coach"]["id"])))
    assert w3["refund_cents"] == 0

    # Ledger reconciliation: 5000 - 3*932 + 932 + 466 = 3602
    assert club_balance(ctx["club"]["id"]) == 3602

def test_tournament_complete_cascades_entries_and_proctors(api, federation_admin_headers):
    """PRD §3.7: "Completion requires `RUNNING` and moves every entry still
    `REGISTERED` or `CHECKED_IN` to `FINISHED` while promoting the tournament's
    `CONFIRMED` proctor assignments to `COMPLETED`."
    PRD §3.5: "and two points for each of the player's tournament entries that has
    reached `CHECKED_IN` or `FINISHED`."

    Design: Corner/state_machines/tournament_complete_cascades_entries_and_proctors
    """
    ctx = setup_one_club(num_players=2)
    tournament, section = setup_open_tournament_with_section(
        ctx["season"]["id"], tournament_overrides={"entry_fee_cents": 0}
    )
    e1 = create_entry(section["id"], ctx["players"][0]["id"], ctx["coach"]["id"])
    e2 = create_entry(section["id"], ctx["players"][1]["id"], ctx["coach"]["id"])
    start_tournament_with_proctor(tournament["id"], ctx["coach"]["id"])
    validate_success(api.check_in_entry(e1["id"], ADMIN))

    validate_success(api.complete_tournament(tournament["id"], federation_admin_headers))

    assert validate_success(api.get_entry(e1["id"], federation_admin_headers))["status"] == "FINISHED"
    assert validate_success(api.get_entry(e2["id"], federation_admin_headers))["status"] == "FINISHED"
    assignments, _ = validate_paginated(
        api.list_proctor_assignments(federation_admin_headers,
                                     params={"tournament_id": tournament["id"]})
    )
    assert assignments[0]["status"] == "COMPLETED"
    assert get_player(ctx["players"][0]["id"])["performance_points"] == 2

def test_section_auto_close_on_tournament_start(api, federation_admin_headers):
    """PRD §3.7: "Starting requires `REGISTRATION_CLOSED` (state checked first) and at
    least one `CONFIRMED` proctor assignment for the tournament, otherwise
    `ERR_NO_CONFIRMED_PROCTOR`; the start also closes every section still `OPEN` or
    `LOCKED`."

    Design: Corner/state_machines/section_auto_close_on_tournament_start
    """
    ctx = setup_one_club()
    tournament = create_tournament(ctx["season"]["id"], entry_fee_cents=0)
    s1 = create_section(tournament["id"], name="S1", max_rating=1000)
    s2 = create_section(tournament["id"], name="S2", min_rating=1001)
    validate_success(api.lock_section(s1["id"], federation_admin_headers))
    open_tournament(tournament["id"])
    start_tournament_with_proctor(tournament["id"], ctx["coach"]["id"])

    running = validate_success(api.get_tournament(tournament["id"], federation_admin_headers))
    assert running["status"] == "RUNNING"
    assert validate_success(api.get_section(s1["id"], federation_admin_headers))["status"] == "CLOSED"
    assert validate_success(api.get_section(s2["id"], federation_admin_headers))["status"] == "CLOSED"

def test_withdraw_already_withdrawn_rejected(api):
    """PRD §3.7: "Withdrawal is a coach action from `REGISTERED` or `CHECKED_IN` —
    anything else fails with `ERR_ENTRY_INVALID_STATE`".

    Design: Corner/errors/withdraw_already_withdrawn_rejected
    """
    ctx = setup_one_club(num_players=1)
    tournament, section = setup_open_tournament_with_section(
        ctx["season"]["id"], tournament_overrides={"entry_fee_cents": 0}
    )
    entry = create_entry(section["id"], ctx["players"][0]["id"], ctx["coach"]["id"])
    validate_success(
        api.withdraw_entry(entry["id"], make_club_coach_headers(ctx["coach"]["id"])))
    res = api.withdraw_entry(entry["id"], make_club_coach_headers(ctx["coach"]["id"]))
    validate_error(res, ApiErrorId.ERR_ENTRY_INVALID_STATE)

def test_immediate_visibility_entry_charge(api, federation_admin_headers):
    """PRD §3.7: "otherwise an `ENTRY_FEE` ledger entry posts for exactly `fee_cents`
    with `entry_id` set, the club's balance and standing are recomputed, and the
    section's `current_entries` grows by one. The new entry is `REGISTERED` with
    `refund_cents` at zero." The create response and the very next reads already
    reflect all of it.

    Design: Corner/consistency_model/immediate_visibility_entry_charge
    """
    ctx = setup_one_club(fund=5000, num_players=1)
    tournament, section = setup_open_tournament_with_section(
        ctx["season"]["id"],
        tournament_overrides={"entry_fee_cents": 1035,
                              "early_bird_deadline": "2026-09-15T00:00:00Z",
                              "early_bird_discount_pct": 0.10},
    )
    entry = create_entry(section["id"], ctx["players"][0]["id"], ctx["coach"]["id"])
    assert entry["fee_cents"] == 932
    assert entry["status"] == "REGISTERED"
    assert entry["refund_cents"] == 0

    assert club_balance(ctx["club"]["id"]) == 4068, "5000 - 932 visible immediately"
    after = validate_success(api.get_section(section["id"], federation_admin_headers))
    assert after["current_entries"] == 1
