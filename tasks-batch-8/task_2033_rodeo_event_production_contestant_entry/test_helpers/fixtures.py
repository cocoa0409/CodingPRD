"""Composite setup helpers for rodeo test scenarios.

Every helper builds its preconditions from scratch through the public API
(the harness restarts the server before each test, so no state carries over).
Setup calls use the lenient get_success_data() validator so failures surface
as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_contestant_payload,
    create_entry_payload,
    create_judge_assignment_payload,
    create_judge_payload,
    create_performance_payload,
    create_rodeo_event_payload,
    create_rodeo_payload,
    create_run_result_payload,
    create_stock_animal_payload,
    create_stock_contract_payload,
    create_ticket_order_payload,
    create_vet_report_payload,
)
from .test_users import TEST_USERS, make_judge_headers

ADMIN = TEST_USERS["committee_admin_headers"]
OFFICE = TEST_USERS["entry_office_headers"]
VET = TEST_USERS["veterinarian_headers"]
BOX = TEST_USERS["box_office_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creators / transitions
# ---------------------------------------------------------------------------

def create_rodeo(**overrides):
    resp = api_client.create_rodeo(create_rodeo_payload(**overrides), ADMIN)
    return get_success_data(resp, 201)


def add_event(rodeo_id, **overrides):
    resp = api_client.create_rodeo_event(
        create_rodeo_event_payload(rodeo_id, **overrides), ADMIN
    )
    return get_success_data(resp, 201)


def add_performance(rodeo_id, **overrides):
    resp = api_client.create_performance(
        create_performance_payload(rodeo_id, **overrides), ADMIN
    )
    return get_success_data(resp, 201)


def transition_rodeo(rodeo_id, action):
    resp = api_client.rodeo_transition(rodeo_id, {"action": action}, ADMIN)
    return get_success_data(resp, 200)


def register_contestant(card_number, full_name):
    resp = api_client.create_contestant(
        create_contestant_payload(card_number=card_number, full_name=full_name),
        OFFICE,
    )
    return get_success_data(resp, 201)


def enter(contestant_id, event_id, headers=None):
    """Enter a contestant into an event (EntryOffice by default)."""
    resp = api_client.create_entry(
        create_entry_payload(contestant_id, event_id), headers or OFFICE
    )
    return get_success_data(resp, 201)


def get_entry(entry_id):
    return get_success_data(api_client.get_entry(entry_id, ADMIN), 200)


def transition_entry(entry_id, payload, headers=None):
    resp = api_client.entry_transition(entry_id, payload, headers or OFFICE)
    return get_success_data(resp, 200)


def create_contract(rodeo_id, **overrides):
    resp = api_client.create_stock_contract(
        create_stock_contract_payload(rodeo_id, **overrides), ADMIN
    )
    return get_success_data(resp, 201)


def transition_contract(contract_id, action):
    resp = api_client.stock_contract_transition(contract_id, {"action": action}, ADMIN)
    return get_success_data(resp, 200)


def add_animal(contract_id, tag_number, event_code):
    resp = api_client.create_stock_animal(
        create_stock_animal_payload(
            contract_id, tag_number=tag_number, event_code=event_code
        ),
        ADMIN,
    )
    return get_success_data(resp, 201)


def get_animal(animal_id):
    return get_success_data(api_client.get_stock_animal(animal_id, ADMIN), 200)


def register_judge(card_number, full_name, certification="PRCA_CARD"):
    resp = api_client.create_judge(
        create_judge_payload(
            card_number=card_number, full_name=full_name, certification=certification
        ),
        ADMIN,
    )
    return get_success_data(resp, 201)


def assign_judge(judge_id, performance_id, position="ARENA_1"):
    resp = api_client.create_judge_assignment(
        create_judge_assignment_payload(
            judge_id, performance_id, position=position
        ),
        ADMIN,
    )
    return get_success_data(resp, 201)


def get_event(event_id):
    return get_success_data(api_client.get_rodeo_event(event_id, ADMIN), 200)


def get_event_version(event_id):
    return get_event(event_id)["version"]


def execute_draw(event_id, go_round_number=1, expected_version=None):
    """Execute the draw for one go-round, fetching the current event version
    when the caller does not pin one."""
    version = expected_version if expected_version is not None else get_event_version(event_id)
    resp = api_client.execute_draw(
        event_id,
        {"go_round_number": go_round_number, "expected_rodeo_event_version": version},
        ADMIN,
    )
    return get_success_data(resp, 200)


def assignments_for_entry(entry_id, status=None):
    params = {"entry_id": entry_id}
    if status:
        params["status"] = status
    resp = api_client.list_draw_assignments(ADMIN, params=params)
    return get_success_data(resp, 200)


def assignment_for_entry(entry_id, status=None):
    """The single draw assignment of an entry (optionally status-filtered)."""
    data = assignments_for_entry(entry_id, status=status)
    assert len(data) == 1, (
        f"Expected exactly one assignment for entry {entry_id} "
        f"(status={status}), got {len(data)}"
    )
    return data[0]


def get_assignment(assignment_id):
    return get_success_data(api_client.get_draw_assignment(assignment_id, ADMIN), 200)


def record_rough_result(da_id, judge_id, judge_1_score, judge_2_score,
                        qualified=True, disqualified=False):
    payload = create_run_result_payload(
        da_id,
        judge_1_score=judge_1_score,
        judge_2_score=judge_2_score,
        qualified_flag=qualified,
        disqualified_flag=disqualified,
    )
    resp = api_client.create_run_result(payload, make_judge_headers(judge_id))
    return get_success_data(resp, 201)


def record_timed_result(da_id, judge_id, raw_time_ms, penalty_ms=None,
                        qualified=True, disqualified=False):
    overrides = {"raw_time_ms": raw_time_ms, "qualified_flag": qualified,
                 "disqualified_flag": disqualified}
    if penalty_ms is not None:
        overrides["penalty_ms"] = penalty_ms
    payload = create_run_result_payload(da_id, **overrides)
    resp = api_client.create_run_result(payload, make_judge_headers(judge_id))
    return get_success_data(resp, 201)


def transition_result(result_id, payload, headers=None):
    resp = api_client.run_result_transition(result_id, payload, headers or ADMIN)
    return get_success_data(resp, 200)


def verify_result(result_id):
    return transition_result(result_id, {"action": "VERIFY"}, ADMIN)


def compute_payout(event_id, variant):
    resp = api_client.compute_payout(
        {"rodeo_event_id": event_id, "variant": variant}, ADMIN
    )
    return get_success_data(resp, 200)


def transition_payout(payout_id, action):
    resp = api_client.payout_transition(payout_id, {"action": action}, ADMIN)
    return get_success_data(resp, 200)


def file_vet_report(**overrides):
    resp = api_client.create_vet_report(create_vet_report_payload(**overrides), VET)
    return get_success_data(resp, 201)


def sell_tickets(performance_id, quantity, **overrides):
    resp = api_client.create_ticket_order(
        create_ticket_order_payload(performance_id, quantity=quantity, **overrides),
        BOX,
    )
    return get_success_data(resp, 201)


def get_performance(performance_id):
    return get_success_data(api_client.get_performance(performance_id, ADMIN), 200)


def set_clock(to_iso8601):
    resp = api_client.set_clock(to_iso8601, ADMIN)
    return get_success_data(resp, 200)


def suspend_contestant(contestant_id):
    resp = api_client.patch_contestant(contestant_id, {"status": "SUSPENDED"}, ADMIN)
    return get_success_data(resp, 200)


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — rodeo with event + performance
# ---------------------------------------------------------------------------

def setup_rodeo_with_event_and_performance(event_overrides=None,
                                           performance_overrides=None,
                                           rodeo_overrides=None):
    """Rodeo (DRAFT) + one event + one performance. Returns dict."""
    rodeo = create_rodeo(**(rodeo_overrides or {}))
    event = add_event(rodeo["id"], **(event_overrides or {}))
    performance = add_performance(rodeo["id"], **(performance_overrides or {}))
    return {"rodeo": rodeo, "event": event, "performance": performance}


def setup_entries_open(event_overrides=None, performance_overrides=None,
                       rodeo_overrides=None):
    """Rodeo + event + performance, posture driven DRAFT -> ENTRIES_OPEN."""
    sc = setup_rodeo_with_event_and_performance(
        event_overrides, performance_overrides, rodeo_overrides
    )
    transition_rodeo(sc["rodeo"]["id"], "OPEN_ENTRIES")
    sc["rodeo"] = get_success_data(api_client.get_rodeo(sc["rodeo"]["id"], ADMIN), 200)
    return sc


def register_and_enter(event_id, count, card_prefix="PRCA", name_prefix="Rider"):
    """Register `count` contestants and enter each into the event.
    Returns (contestants, entries) in creation order."""
    contestants, entries = [], []
    for i in range(count):
        c = register_contestant(f"{card_prefix}-{i + 1}", f"{name_prefix} {i + 1}")
        e = enter(c["id"], event_id)
        contestants.append(c)
        entries.append(e)
    return contestants, entries


def setup_active_stock(rodeo_id, event_code, tag_numbers,
                       day_rate_cents=TEST_DEFAULTS["DAY_RATE_CENTS"],
                       per_out_fee_cents=TEST_DEFAULTS["PER_OUT_FEE_CENTS"],
                       contractor_name="Bar None Ranch"):
    """ACTIVE contract + one animal per tag. Returns (contract, animals)."""
    contract = create_contract(
        rodeo_id,
        contractor_name=contractor_name,
        day_rate_cents=day_rate_cents,
        per_out_fee_cents=per_out_fee_cents,
    )
    transition_contract(contract["id"], "ACTIVATE")
    animals = [add_animal(contract["id"], tag, event_code) for tag in tag_numbers]
    contract = get_success_data(
        api_client.get_stock_contract(contract["id"], ADMIN), 200
    )
    return contract, animals


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts — drawn / in-progress scenarios
# ---------------------------------------------------------------------------

def setup_draw_locked(event_code="BULL_RIDING", num_contestants=2,
                      animal_tags=("A100", "A200"), event_overrides=None,
                      performance_overrides=None, rodeo_overrides=None,
                      card_prefix="PRCA", stock_kwargs=None):
    """Full chain through LOCK_DRAW (draw NOT executed).

    Rough-stock events get an ACTIVE contract with the given animals; timed
    events (animal_tags=None or empty) get no stock. Returns a scenario dict.
    """
    ev_ov = dict(event_overrides or {})
    ev_ov.setdefault("event_code", event_code)
    sc = setup_entries_open(ev_ov, performance_overrides, rodeo_overrides)
    contestants, entries = register_and_enter(
        sc["event"]["id"], num_contestants, card_prefix=card_prefix
    )
    contract, animals = None, []
    if animal_tags:
        contract, animals = setup_active_stock(
            sc["rodeo"]["id"], event_code, list(animal_tags),
            **(stock_kwargs or {})
        )
    transition_rodeo(sc["rodeo"]["id"], "LOCK_DRAW")
    sc.update({
        "contestants": contestants,
        "entries": entries,
        "contract": contract,
        "animals": animals,
    })
    return sc


def setup_drawn(event_code="BULL_RIDING", num_contestants=2,
                animal_tags=("A100", "A200"), go_round=1, **kwargs):
    """setup_draw_locked + go-round draw executed. Returns scenario dict."""
    sc = setup_draw_locked(event_code, num_contestants, animal_tags, **kwargs)
    sc["draw"] = execute_draw(sc["event"]["id"], go_round_number=go_round)
    sc["event"] = get_event(sc["event"]["id"])
    return sc


def start_rodeo_with_judge(scenario, card_number="J-100", certification="PRCA_CARD",
                           position="ARENA_1", full_name="Test Judge"):
    """Register a judge, assign them to the scenario's performance, and drive
    the rodeo DRAW_LOCKED -> IN_PROGRESS. Returns the judge."""
    judge = register_judge(card_number, full_name, certification)
    assignment = assign_judge(
        judge["id"], scenario["performance"]["id"], position=position
    )
    transition_rodeo(scenario["rodeo"]["id"], "START_RODEO")
    scenario["judge"] = judge
    scenario["judge_assignment"] = assignment
    return judge


def setup_in_progress(event_code="BULL_RIDING", num_contestants=2,
                      animal_tags=("A100", "A200"), judge_position="ARENA_1",
                      judge_certification="PRCA_CARD", judge_card="J-100",
                      **kwargs):
    """Full chain: drawn go-round 1 + judge assigned + START_RODEO.
    Returns scenario dict with 'judge'."""
    sc = setup_drawn(event_code, num_contestants, animal_tags, **kwargs)
    start_rodeo_with_judge(
        sc, card_number=judge_card, certification=judge_certification,
        position=judge_position,
    )
    return sc


def record_and_verify_rough(entry_id, judge_id, judge_1_score, judge_2_score,
                            qualified=True):
    """Record + verify a rough-stock result for an entry's pending assignment.
    Returns the verified result."""
    da = assignment_for_entry(entry_id, status="PENDING")
    result = record_rough_result(
        da["id"], judge_id, judge_1_score, judge_2_score, qualified=qualified
    )
    return verify_result(result["id"])


def record_and_verify_timed(entry_id, judge_id, raw_time_ms, qualified=True):
    """Record + verify a timed result for an entry's pending assignment."""
    da = assignment_for_entry(entry_id, status="PENDING")
    result = record_timed_result(da["id"], judge_id, raw_time_ms, qualified=qualified)
    return verify_result(result["id"])


# ---------------------------------------------------------------------------
# Tier 4/5: late-lifecycle scenarios — completed rodeo, finalized payout
# ---------------------------------------------------------------------------

def complete_performance(performance_id):
    resp = api_client.performance_transition(
        performance_id, {"action": "COMPLETE_PERFORMANCE"}, ADMIN
    )
    return get_success_data(resp, 200)


def setup_completed_rodeo(event_code="BULL_RIDING", num_contestants=2,
                          animal_tags=("A100", "A200"), scores=None,
                          times=None, **kwargs):
    """In-progress scenario + all entries scored and verified in every
    go-round of the event + performance completed + COMPLETE_RODEO.

    `scores`: list of (j1, j2, qualified) per contestant, applied in every
    go-round (rough stock). `times`: list of (raw_time_ms, qualified) per
    contestant per go-round (timed). Defaults produce qualified rides for all.
    Returns scenario dict.
    """
    sc = setup_in_progress(event_code, num_contestants, animal_tags, **kwargs)
    event = sc["event"]
    judge = sc["judge"]
    for g in range(1, event["go_rounds"] + 1):
        if g > 1:
            execute_draw(event["id"], go_round_number=g)
        for idx, entry in enumerate(sc["entries"]):
            if event_code in ("BAREBACK", "SADDLE_BRONC", "BULL_RIDING"):
                j1, j2, qual = (scores[idx] if scores else (40, 40, True))
                record_and_verify_rough(entry["id"], judge["id"], j1, j2, qual)
            else:
                raw, qual = (times[idx] if times else (14000 + idx * 100, True))
                record_and_verify_timed(entry["id"], judge["id"], raw, qual)
    complete_performance(sc["performance"]["id"])
    transition_rodeo(sc["rodeo"]["id"], "COMPLETE_RODEO")
    sc["rodeo"] = get_success_data(api_client.get_rodeo(sc["rodeo"]["id"], ADMIN), 200)
    return sc


def setup_finalized_payout(event_code="BULL_RIDING", num_contestants=2,
                           animal_tags=("A100", "A200"), **kwargs):
    """Completed rodeo + payout computed FINAL + FINALIZE. Returns scenario
    dict with 'payout'."""
    sc = setup_completed_rodeo(event_code, num_contestants, animal_tags, **kwargs)
    payout = compute_payout(sc["event"]["id"], "FINAL")
    sc["payout"] = transition_payout(payout["id"], "FINALIZE")
    return sc


def drive_go_round(scenario, go_round_number, rough_scores=None,
                   timed_results=None):
    """Draw one go-round (2 or later) and record + verify a result for every
    entry of the scenario. rough_scores: list of (j1, j2, qualified) aligned
    with scenario['entries']; timed_results: list of (raw_time_ms, qualified).
    Returns the verified results in entry order."""
    execute_draw(scenario["event"]["id"], go_round_number=go_round_number)
    results = []
    for idx, entry in enumerate(scenario["entries"]):
        if rough_scores is not None:
            j1, j2, qual = rough_scores[idx]
            results.append(record_and_verify_rough(
                entry["id"], scenario["judge"]["id"], j1, j2, qual))
        else:
            raw, qual = timed_results[idx]
            results.append(record_and_verify_timed(
                entry["id"], scenario["judge"]["id"], raw, qual))
    return results


def setup_riders_with_mixed_results(scores, verified_mask,
                                    added_money_cents=100000,
                                    payout_places=2, card_prefix="PRCA"):
    """BULL_RIDING one-go-round event with four entries drawn and scored;
    verified_mask selects which recorded results are also verified.
    Returns the scenario dict with 'results' aligned to 'entries'."""
    sc = setup_in_progress(
        "BULL_RIDING", num_contestants=len(scores),
        animal_tags=tuple(f"A{i + 1}00" for i in range(len(scores))),
        event_overrides={
            "added_money_cents": added_money_cents,
            "payout_places": payout_places,
            "per_performance_slots": 10,
        },
        judge_certification="PRCA_GOLD",
        card_prefix=card_prefix,
    )
    results = []
    for entry, (j1, j2), verified in zip(sc["entries"], scores, verified_mask):
        da = assignment_for_entry(entry["id"], status="PENDING")
        result = record_rough_result(da["id"], sc["judge"]["id"], j1, j2)
        if verified:
            result = verify_result(result["id"])
        results.append(result)
    sc["results"] = results
    return sc
