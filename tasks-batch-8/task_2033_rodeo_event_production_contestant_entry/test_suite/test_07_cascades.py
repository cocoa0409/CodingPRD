"""Cross-entity cascades: vet injury turn-out, contestant suspension, and
terminal lockdown (PRD §3.1, §3.2, §3.3)."""
from test_helpers import (
    ApiErrorId,
    add_animal,
    add_event,
    add_performance,
    assign_judge,
    assignment_for_entry,
    compute_payout,
    create_rodeo,
    execute_draw,
    file_vet_report,
    get_animal,
    get_assignment,
    get_entry,
    get_success_data,
    record_rough_result,
    register_contestant,
    register_judge,
    enter,
    setup_active_stock,
    setup_drawn,
    suspend_contestant,
    TEST_USERS,
    transition_rodeo,
    validate_error,
    validate_success,
    verify_result,
)

ADMIN = TEST_USERS["committee_admin_headers"]
OFFICE = TEST_USERS["entry_office_headers"]


def _vet_cascade_scenario():
    """Two riders DRAWN with animals; rodeo IN_PROGRESS; provisional payout
    already computed. Returns (scenario, entry2, animal_of_entry2)."""
    sc = setup_drawn(
        event_code="BULL_RIDING", num_contestants=2,
        animal_tags=("A100", "A200"),
        event_overrides={"added_money_cents": 50000, "payout_places": 2,
                         "per_performance_slots": 10},
        card_prefix="PRCA-70",
    )
    transition_rodeo(sc["rodeo"]["id"], "START_RODEO")
    e2 = sc["entries"][1]
    da2 = assignment_for_entry(e2["id"])
    return sc, e2, da2


def test_vet_injury_releases_assignment_and_turns_out_entry_medically(api):
    """PRD §3.3: "Filing it on a `DRAWN` animal runs a deeper cascade: every
    `PENDING` draw assignment naming the animal is released, the entries
    behind those assignments become `TURNED_OUT` with a `MEDICAL` reason —
    the purse contribution refunded and `vet_report_id` set to the new
    report — and the affected purses are recomputed, leaving any stored
    payout stale."

    Design: Difficulty/transitive_cascade/vet_injury_turnout_cascade_recomputes_purse
    """
    sc, e2, da2 = _vet_cascade_scenario()
    animal_id = da2["animal_id"]

    report = file_vet_report(
        subject_type="ANIMAL",
        animal_id=animal_id,
        performance_id=sc["performance"]["id"],
        findings="Left hind lameness, grade 3",
        disposition="INJURED_TURNOUT",
        veterinarian_name="Dr. Ellis",
    )

    assert get_animal(animal_id)["status"] == "INJURED"
    assert get_assignment(da2["id"])["status"] == "RELEASED"
    entry_after = get_entry(e2["id"])
    assert entry_after["status"] == "TURNED_OUT"
    assert entry_after["turn_out_reason"] == "MEDICAL"
    assert entry_after["vet_report_id"] == report["id"]
    assert entry_after["refunded_cents"] == 1160
    assert entry_after["refunded_contribution_cents"] == 1160


def test_vet_injury_recomputes_event_purse(api):
    """PRD §3.3: "Filing it on a `DRAWN` animal runs a deeper cascade ... and
    the affected purses are recomputed, leaving any stored payout stale."
    PRD §3.7: "Its purse — `purse_cents` — is the event's `added_money_cents`
    plus, summed over all of the event's entries regardless of their status,
    each entry's `contribution_charges_cents` minus its
    `refunded_contribution_cents`."

    Design: Difficulty/transitive_cascade/vet_injury_turnout_cascade_recomputes_purse
    """
    sc, e2, da2 = _vet_cascade_scenario()
    before = compute_payout(sc["event"]["id"], "PROVISIONAL")
    assert before["purse_cents"] == 52320, (
        f"50000 added + 2 x 1160 contributions, got {before['purse_cents']}"
    )

    file_vet_report(
        subject_type="ANIMAL",
        animal_id=da2["animal_id"],
        performance_id=sc["performance"]["id"],
        findings="Left hind lameness, grade 3",
        disposition="INJURED_TURNOUT",
        veterinarian_name="Dr. Ellis",
    )

    after = compute_payout(sc["event"]["id"], "PROVISIONAL")
    assert after["purse_cents"] == 51160, (
        f"one medical refund of 1160 nets out of the purse: {after['purse_cents']}"
    )
    survivor = get_entry(sc["entries"][0]["id"])
    assert survivor["status"] == "DRAWN"
    assert survivor["refunded_contribution_cents"] == 0


def test_suspension_draws_out_entry_frees_animal(api):
    """PRD §3.2: "A `CommitteeAdmin` patches a contestant's `status` to
    `SUSPENDED`, and the cascade runs immediately: the contestant's `ENTERED`
    entries are cancelled with a full refund including the sanction; their
    `WAITLISTED` entries are cancelled on the same terms; and their `DRAWN`
    entries become `DRAWN_OUT` with the same full refund, their pending
    assignments released and their drawn animals returned to `AVAILABLE`."

    Design: Difficulty/transitive_cascade/contestant_suspension_cascade_draws_out_and_frees_slot
    """
    sc = setup_drawn(
        event_code="BULL_RIDING", num_contestants=2,
        animal_tags=("A100", "A200"),
        event_overrides={"added_money_cents": 50000, "payout_places": 2,
                         "per_performance_slots": 10},
        card_prefix="PRCA-80",
    )
    c2 = sc["contestants"][1]
    e2 = sc["entries"][1]
    da2 = assignment_for_entry(e2["id"])
    animal_id = da2["animal_id"]

    suspended = suspend_contestant(c2["id"])
    assert suspended["status"] == "SUSPENDED"

    entry_after = get_entry(e2["id"])
    assert entry_after["status"] == "DRAWN_OUT"
    assert entry_after["refunded_cents"] == 2000, (
        "full refund including the sanction fee"
    )
    assert entry_after["refunded_contribution_cents"] == 1160
    assert get_assignment(da2["id"])["status"] == "RELEASED"
    assert get_animal(animal_id)["status"] == "AVAILABLE"


def test_suspension_recomputes_event_purse(api):
    """PRD §3.2: "Event purses are recomputed as `refunded_contribution_cents`
    rises, and any stored payout for those events is stale until recomputed."
    PRD §3.7: "Its purse — `purse_cents` — is the event's `added_money_cents`
    plus, summed over all of the event's entries regardless of their status,
    each entry's `contribution_charges_cents` minus its
    `refunded_contribution_cents`."

    Design: Difficulty/transitive_cascade/contestant_suspension_cascade_draws_out_and_frees_slot
    """
    sc = setup_drawn(
        event_code="BULL_RIDING", num_contestants=2,
        animal_tags=("A100", "A200"),
        event_overrides={"added_money_cents": 50000, "payout_places": 2,
                         "per_performance_slots": 10},
        card_prefix="PRCA-81",
    )
    suspend_contestant(sc["contestants"][1]["id"])

    payout = compute_payout(sc["event"]["id"], "PROVISIONAL")
    assert payout["purse_cents"] == 51160, (
        f"50000 added + 1160 surviving contribution, got {payout['purse_cents']}"
    )
    survivor = get_entry(sc["entries"][0]["id"])
    assert survivor["status"] == "DRAWN"
    assert survivor["refunded_cents"] == 0


def test_suspension_skips_competed_entries(api):
    """PRD §3.2: "the contestant's `ENTERED` entries are cancelled with a full
    refund including the sanction; their `WAITLISTED` entries are cancelled on
    the same terms; and their `DRAWN` entries become `DRAWN_OUT` with the same
    full refund, their pending assignments released and their drawn animals
    returned to `AVAILABLE`." — the cascade names only the non-terminal
    states, so a `COMPETED` entry is untouched.
    PRD §3.2: "when every go-round assignment of a `DRAWN` entry reaches
    `COMPLETED`, the entry bubbles up to `COMPETED`".

    Design: Corner/state_machines/suspension_skips_competed_entries
    """
    rodeo = create_rodeo(name="Abilene Rodeo", city="Abilene")
    e1v = add_event(rodeo["id"], event_code="BULL_RIDING", entry_fee_cents=2000)
    e2v = add_event(rodeo["id"], event_code="BAREBACK", entry_fee_cents=2000)
    performance = add_performance(rodeo["id"])
    transition_rodeo(rodeo["id"], "OPEN_ENTRIES")
    contestant = register_contestant("PRCA-240", "Rider Multi")
    en1 = enter(contestant["id"], e1v["id"])
    en2 = enter(contestant["id"], e2v["id"])
    contract, animals = setup_active_stock(
        rodeo["id"], "BULL_RIDING", ["A100"]
    )
    a2 = add_animal(contract["id"], "A200", "BAREBACK")
    transition_rodeo(rodeo["id"], "LOCK_DRAW")
    execute_draw(e1v["id"], go_round_number=1)
    execute_draw(e2v["id"], go_round_number=1)

    judge = register_judge("J-24", "Judge Multi", "PRCA_CARD")
    assign_judge(judge["id"], performance["id"], "ARENA_1")
    transition_rodeo(rodeo["id"], "START_RODEO")

    # Complete the contestant's E1 entry so it bubbles to COMPETED.
    result = record_rough_result(
        assignment_for_entry(en1["id"])["id"], judge["id"], 40, 40
    )
    verify_result(result["id"])
    assert get_entry(en1["id"])["status"] == "COMPETED"

    suspend_contestant(contestant["id"])

    en1_after = get_entry(en1["id"])
    assert en1_after["status"] == "COMPETED", "COMPETED is terminal; cascade skips it"
    assert en1_after["refunded_cents"] == 0

    en2_after = get_entry(en2["id"])
    assert en2_after["status"] == "DRAWN_OUT"
    assert en2_after["refunded_cents"] == 2000
    assert en2_after["refunded_contribution_cents"] == 1160

    # E2's animal is freed; E1's animal keeps its verified-out bookkeeping.
    assert get_animal(a2["id"])["status"] == "AVAILABLE"
    a1_after = get_animal(animals[0]["id"])
    assert a1_after["status"] == "AVAILABLE"
    assert a1_after["welfare_out_count"] == 1


def test_rodeo_terminal_cancelled_lockdown(api):
    """PRD §3.1: "`SETTLED` and `CANCELLED` are terminal, and any transition
    attempted from a terminal state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/rodeo_terminal_cancelled_lockdown
    """
    rodeo = create_rodeo(name="Rained Out Rodeo", city="Nowhere")
    cancelled = transition_rodeo(rodeo["id"], "CANCEL_RODEO")
    assert cancelled["posture"] == "CANCELLED"

    resp = api.rodeo_transition(rodeo["id"], {"action": "OPEN_ENTRIES"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = get_success_data(api.get_rodeo(rodeo["id"], ADMIN), 200)
    assert after["posture"] == "CANCELLED"
