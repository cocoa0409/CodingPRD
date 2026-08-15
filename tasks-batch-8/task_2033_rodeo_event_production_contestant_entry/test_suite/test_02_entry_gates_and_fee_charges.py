"""Entry creation gates and the per-entry fee split (PRD §2.6, §2.8, §3.2)."""
from test_helpers import (
    ApiErrorId,
    add_event,
    compute_payout,
    create_entry_payload,
    enter,
    register_contestant,
    set_clock,
    setup_entries_open,
    setup_rodeo_with_event_and_performance,
    TEST_USERS,
    transition_rodeo,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["committee_admin_headers"]
OFFICE = TEST_USERS["entry_office_headers"]


def test_entry_rejected_while_rodeo_draft_then_accepted_when_open(api):
    """PRD §3.2: "Four gates guard creation, evaluated in this order: the
    rodeo must be in `ENTRIES_OPEN` posture (`ERR_RODEO_NOT_OPEN`); the logical
    clock must read strictly earlier than the rodeo's `entries_close_at` — a
    clock at or past the deadline closes the window (`ERR_ENTRY_WINDOW_CLOSED`);
    the contestant must be in `GOOD_STANDING` (`ERR_CONTESTANT_SUSPENDED`); and
    the contestant must not already hold a non-terminal entry for the same
    event, where non-terminal means `ENTERED`, `WAITLISTED`, or `DRAWN`
    (`ERR_DUPLICATE_ENTRY`)."

    Design: Difficulty/cross_entity_state_dependency/entry_requires_rodeo_entries_open
    """
    sc = setup_rodeo_with_event_and_performance(
        event_overrides={"event_code": "BAREBACK", "entry_fee_cents": 2000}
    )
    contestant = register_contestant("PRCA-121", "Rider T")

    # Rodeo still DRAFT: the posture gate rejects the identical payload.
    blocked = api.create_entry(
        create_entry_payload(contestant["id"], sc["event"]["id"]), OFFICE
    )
    validate_error(blocked, ApiErrorId.ERR_RODEO_NOT_OPEN)

    transition_rodeo(sc["rodeo"]["id"], "OPEN_ENTRIES")
    accepted = api.create_entry(
        create_entry_payload(contestant["id"], sc["event"]["id"]), OFFICE
    )
    data = validate_success(accepted, 201)
    assert data["status"] == "ENTERED"
    assert data["entry_fee_cents"] == 2000


def test_entry_rejected_while_rodeo_draw_locked(api):
    """PRD §3.2: "Four gates guard creation, evaluated in this order: the
    rodeo must be in `ENTRIES_OPEN` posture (`ERR_RODEO_NOT_OPEN`)".
    PRD §2.8: "7. Rodeo posture gate — entries and re-entries require
    `ENTRIES_OPEN`; draws require `DRAW_LOCKED` or `IN_PROGRESS`; result
    recording requires `IN_PROGRESS`; payout finalization requires `COMPLETED`
    (`ERR_RODEO_NOT_OPEN`)."

    Design: Difficulty/cross_entity_state_dependency/entry_requires_rodeo_entries_open
    """
    sc = setup_entries_open(
        event_overrides={"event_code": "BAREBACK", "entry_fee_cents": 2000}
    )
    contestant = register_contestant("PRCA-122", "Rider T2")
    transition_rodeo(sc["rodeo"]["id"], "LOCK_DRAW")

    blocked = api.create_entry(
        create_entry_payload(contestant["id"], sc["event"]["id"]), OFFICE
    )
    validate_error(blocked, ApiErrorId.ERR_RODEO_NOT_OPEN)


def test_posture_gate_beats_window_close_when_draw_locked(api):
    """PRD §3.2: "Four gates guard creation, evaluated in this order: the
    rodeo must be in `ENTRIES_OPEN` posture (`ERR_RODEO_NOT_OPEN`); the logical
    clock must read strictly earlier than the rodeo's `entries_close_at` — a
    clock at or past the deadline closes the window (`ERR_ENTRY_WINDOW_CLOSED`)".
    PRD §2.8: "When several checks could reject the same request, the server
    evaluates them in a fixed order and surfaces the earliest failure."

    Design: Difficulty/priority_pair_validation_conflict/entry_create_posture_gate_beats_window_close
    """
    sc = setup_entries_open(
        event_overrides={"event_code": "BAREBACK", "entry_fee_cents": 2000},
        rodeo_overrides={"entries_close_at": "2026-08-10T00:00:00Z"},
    )
    transition_rodeo(sc["rodeo"]["id"], "LOCK_DRAW")
    # Advance the logical clock past the entry deadline.
    set_clock("2026-08-11T00:00:00Z")
    contestant = register_contestant("PRCA-901", "Rider P")

    resp = api.create_entry(
        create_entry_payload(contestant["id"], sc["event"]["id"]), OFFICE
    )
    # Both the posture gate and the window gate are violated; the posture
    # gate is evaluated first.
    validate_error(resp, ApiErrorId.ERR_RODEO_NOT_OPEN)


def test_posture_gate_beats_window_close_when_draft(api):
    """PRD §3.2: "Four gates guard creation, evaluated in this order: the
    rodeo must be in `ENTRIES_OPEN` posture (`ERR_RODEO_NOT_OPEN`); the logical
    clock must read strictly earlier than the rodeo's `entries_close_at` — a
    clock at or past the deadline closes the window (`ERR_ENTRY_WINDOW_CLOSED`)".
    PRD §2.8: "When several checks could reject the same request, the server
    evaluates them in a fixed order and surfaces the earliest failure."

    Design: Difficulty/priority_pair_validation_conflict/entry_create_posture_gate_beats_window_close
    """
    sc = setup_rodeo_with_event_and_performance(
        event_overrides={"event_code": "BAREBACK", "entry_fee_cents": 2000},
        rodeo_overrides={"entries_close_at": "2026-08-10T00:00:00Z"},
    )
    # Rodeo still DRAFT, and the clock is moved past the deadline.
    set_clock("2026-08-11T00:00:00Z")
    contestant = register_contestant("PRCA-902", "Rider Q")

    resp = api.create_entry(
        create_entry_payload(contestant["id"], sc["event"]["id"]), OFFICE
    )
    validate_error(resp, ApiErrorId.ERR_RODEO_NOT_OPEN)


def test_entry_window_closed_rejected(api):
    """PRD §3.2: "the logical clock must read strictly earlier than the
    rodeo's `entries_close_at` — a clock at or past the deadline closes the
    window (`ERR_ENTRY_WINDOW_CLOSED`)".

    Design: Corner/validations/entry_window_closed_rejected
    """
    sc = setup_entries_open(
        event_overrides={"event_code": "BAREBACK", "entry_fee_cents": 2000},
        rodeo_overrides={"entries_close_at": "2026-08-10T00:00:00Z"},
    )
    contestant = register_contestant("PRCA-420", "Rider Late")

    # Clock exactly at the deadline: the window is already closed.
    set_clock("2026-08-10T00:00:00Z")
    at_deadline = api.create_entry(
        create_entry_payload(contestant["id"], sc["event"]["id"]), OFFICE
    )
    validate_error(at_deadline, ApiErrorId.ERR_ENTRY_WINDOW_CLOSED)

    # Clock past the deadline: same rejection.
    set_clock("2026-08-11T00:00:00Z")
    past_deadline = api.create_entry(
        create_entry_payload(contestant["id"], sc["event"]["id"]), OFFICE
    )
    validate_error(past_deadline, ApiErrorId.ERR_ENTRY_WINDOW_CLOSED)


def test_entry_create_rejected_for_suspended_contestant(api):
    """PRD §3.2: "the contestant must be in `GOOD_STANDING`
    (`ERR_CONTESTANT_SUSPENDED`)".

    Design: Corner/validations/entry_create_rejected_for_suspended_contestant
    """
    sc = setup_entries_open(
        event_overrides={"event_code": "BAREBACK", "entry_fee_cents": 2000}
    )
    contestant = register_contestant("PRCA-430", "Rider Sus")
    suspended = validate_success(
        api.patch_contestant(contestant["id"], {"status": "SUSPENDED"}, ADMIN), 200
    )
    assert suspended["status"] == "SUSPENDED"

    resp = api.create_entry(
        create_entry_payload(contestant["id"], sc["event"]["id"]), OFFICE
    )
    validate_error(resp, ApiErrorId.ERR_CONTESTANT_SUSPENDED)

    data, meta = validate_paginated(
        api.list_entries(ADMIN, params={"contestant_id": contestant["id"]})
    )
    assert data == [], f"no entry may persist for a suspended contestant: {data}"


def test_duplicate_entry_rejected_until_prior_terminal(api):
    """PRD §3.2: "the contestant must not already hold a non-terminal entry
    for the same event, where non-terminal means `ENTERED`, `WAITLISTED`, or
    `DRAWN` (`ERR_DUPLICATE_ENTRY`)"."

    Design: Corner/validations/duplicate_entry_rejected_until_prior_terminal
    """
    sc = setup_entries_open(
        event_overrides={"event_code": "BAREBACK", "entry_fee_cents": 2000}
    )
    contestant = register_contestant("PRCA-410", "Rider Dup")
    first = enter(contestant["id"], sc["event"]["id"])
    assert first["status"] == "ENTERED"

    dup = api.create_entry(
        create_entry_payload(contestant["id"], sc["event"]["id"]), OFFICE
    )
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_ENTRY)

    # Cancelling the first entry makes it terminal; a fresh entry then succeeds.
    cancelled = validate_success(
        api.entry_transition(first["id"], {"action": "CANCEL_ENTRY"}, OFFICE), 200
    )
    assert cancelled["status"] == "CANCELLED"

    second = validate_success(
        api.create_entry(
            create_entry_payload(contestant["id"], sc["event"]["id"]), OFFICE
        ),
        201,
    )
    assert second["id"] != first["id"], "re-entry after cancel must be a new row"
    assert second["status"] == "ENTERED"


def test_immediate_visibility_of_computed_splits_on_create(api):
    """PRD §3.2: "On acceptance, the entry's `entry_fee_cents` is copied from
    the event's fee at that moment, and the fee split is computed immediately:
    a flat 600-cent `sanction_fee_cents`, a `committee_retention_cents` equal
    to twelve percent of the fee rounded half-up to whole cents, and a
    `purse_contribution_cents` equal to the fee minus the retention minus the
    sanction."

    Design: Corner/consistency_model/immediate_visibility_of_computed_splits_on_create
    """
    sc = setup_entries_open(
        event_overrides={"event_code": "BAREBACK", "entry_fee_cents": 2000}
    )
    contestant = register_contestant("PRCA-499", "Rider Imm")

    resp = api.create_entry(
        create_entry_payload(contestant["id"], sc["event"]["id"]), OFFICE
    )
    data = validate_success(resp, 201)
    assert data["status"] == "ENTERED"
    assert data["entry_fee_cents"] == 2000
    assert data["committee_retention_cents"] == 240
    assert data["sanction_fee_cents"] == 600
    assert data["purse_contribution_cents"] == 1160
    assert data["fee_charges_cents"] == 2000
    assert data["contribution_charges_cents"] == 1160


def test_entry_fee_split_rounded_per_entry(api):
    """PRD §2.6: "The difference is real money: two entries at 2,005 and 2,030
    cents produce retentions of 241 and 244 cents (summing to 485) and
    contributions of 1,164 and 1,186 cents (summing to 2,350), whereas
    rounding the combined 4,035-cent fee would yield a retention of 484 and a
    combined contribution of 2,351. Only the per-entry figures are correct."

    Design: Difficulty/combinatorial_formula/entry_fee_split_rounding_order_per_entry
    """
    sc = setup_entries_open(rodeo_overrides={"name": "Pendleton Round-Up"})
    # Two events with the boundary fees named by the PRD example. Event
    # creation carries no posture gate, so they can be added while open.
    ev1 = add_event(sc["rodeo"]["id"], event_code="BAREBACK", entry_fee_cents=2005,
                    added_money_cents=0)
    ev2 = add_event(sc["rodeo"]["id"], event_code="SADDLE_BRONC", entry_fee_cents=2030,
                    added_money_cents=0)
    c1 = register_contestant("PRCA-401", "Rider H")
    c2 = register_contestant("PRCA-402", "Rider I")
    entry1 = enter(c1["id"], ev1["id"])
    entry2 = enter(c2["id"], ev2["id"])

    assert entry1["sanction_fee_cents"] == 600
    assert entry1["committee_retention_cents"] == 241, (
        f"round_half_up(2005 x 0.12) = 241, got {entry1['committee_retention_cents']}"
    )
    assert entry1["purse_contribution_cents"] == 1164

    assert entry2["sanction_fee_cents"] == 600
    assert entry2["committee_retention_cents"] == 244, (
        f"round_half_up(2030 x 0.12) = 244, got {entry2['committee_retention_cents']}"
    )
    assert entry2["purse_contribution_cents"] == 1186


def test_purses_sum_per_entry_rounded_contributions(api):
    """PRD §2.6: "Aggregates such as the purse or total retention are always
    sums of those per-entry rounded values; the server never rounds an
    aggregate fee sum."
    PRD §3.7: "Its purse — `purse_cents` — is the event's `added_money_cents`
    plus, summed over all of the event's entries regardless of their status,
    each entry's `contribution_charges_cents` minus its
    `refunded_contribution_cents`."

    Design: Difficulty/combinatorial_formula/entry_fee_split_rounding_order_per_entry
    """
    sc = setup_entries_open(rodeo_overrides={"name": "Pendleton Round-Up"})
    ev1 = add_event(sc["rodeo"]["id"], event_code="BAREBACK", entry_fee_cents=2005,
                    added_money_cents=0)
    ev2 = add_event(sc["rodeo"]["id"], event_code="SADDLE_BRONC", entry_fee_cents=2030,
                    added_money_cents=0)
    c1 = register_contestant("PRCA-401", "Rider H")
    c2 = register_contestant("PRCA-402", "Rider I")
    enter(c1["id"], ev1["id"])
    enter(c2["id"], ev2["id"])

    payout1 = compute_payout(ev1["id"], "PROVISIONAL")
    payout2 = compute_payout(ev2["id"], "PROVISIONAL")
    assert payout1["purse_cents"] == 1164
    assert payout2["purse_cents"] == 1186
    assert payout1["purse_cents"] + payout2["purse_cents"] == 2350, (
        "per-entry rounding yields a combined contribution of 2350, not the "
        "2351 that aggregate-order rounding would produce"
    )


def _entry_cancel_scenario(api):
    """ENTRIES_OPEN rodeo, BULL_RIDING event (fee 2000, added 50000); one
    baseline entry already charged. Returns (event_id, baseline_entry)."""
    sc = setup_entries_open(
        event_overrides={"event_code": "BULL_RIDING", "entry_fee_cents": 2000,
                         "added_money_cents": 50000, "payout_places": 1},
        rodeo_overrides={"name": "St Paul Rodeo"},
    )
    baseline = register_contestant("PRCA-151", "Rider V")
    baseline_entry = enter(baseline["id"], sc["event"]["id"])
    return sc, baseline_entry


def test_entry_create_then_cancel_restores_purse(api):
    """PRD §3.7: "Its purse — `purse_cents` — is the event's
    `added_money_cents` plus, summed over all of the event's entries
    regardless of their status, each entry's `contribution_charges_cents`
    minus its `refunded_contribution_cents`."
    PRD §3.2: "Cancelling an entry (`CANCEL_ENTRY`, available to `EntryOffice`
    or the contestant themself from `ENTERED`) refunds the purse contribution
    and the committee retention but keeps the sanction fee".

    Design: Difficulty/compensating_invariant/entry_create_then_cancel_leaves_purse_unchanged
    """
    sc, _baseline_entry = _entry_cancel_scenario(api)
    event_id = sc["event"]["id"]

    purse_base = compute_payout(event_id, "PROVISIONAL")
    assert purse_base["purse_cents"] == 51160, (
        f"50000 added + 1160 baseline contribution, got {purse_base['purse_cents']}"
    )

    c2 = register_contestant("PRCA-152", "Rider W")
    e2 = enter(c2["id"], event_id)
    purse_mid = compute_payout(event_id, "PROVISIONAL")
    assert purse_mid["purse_cents"] == 52320, (
        f"the new entry's 1160 contribution lands: {purse_mid['purse_cents']}"
    )

    cancelled = validate_success(
        api.entry_transition(e2["id"], {"action": "CANCEL_ENTRY"}, OFFICE), 200
    )
    assert cancelled["status"] == "CANCELLED"

    purse_end = compute_payout(event_id, "PROVISIONAL")
    assert purse_end["purse_cents"] == 51160, (
        f"create + cancel must leave the purse at its 51160 baseline, got "
        f"{purse_end['purse_cents']}"
    )


def test_cancel_entry_refunds_contribution_plus_retention_keeps_sanction(api):
    """PRD §3.2: "Cancelling an entry (`CANCEL_ENTRY`, available to
    `EntryOffice` or the contestant themself from `ENTERED`) refunds the purse
    contribution and the committee retention but keeps the sanction fee:
    `refunded_cents` grows by the contribution plus the retention,
    `refunded_contribution_cents` grows by the contribution alone, and the
    event's purse is recomputed downward."

    Design: Difficulty/compensating_invariant/entry_create_then_cancel_leaves_purse_unchanged
    """
    sc, _baseline_entry = _entry_cancel_scenario(api)
    c2 = register_contestant("PRCA-153", "Rider W2")
    e2 = enter(c2["id"], sc["event"]["id"])

    cancelled = validate_success(
        api.entry_transition(e2["id"], {"action": "CANCEL_ENTRY"}, OFFICE), 200
    )
    assert cancelled["status"] == "CANCELLED"
    # contribution 1160 + retention 240 refunded; the 600 sanction is kept.
    assert cancelled["refunded_cents"] == 1400
    assert cancelled["refunded_contribution_cents"] == 1160
