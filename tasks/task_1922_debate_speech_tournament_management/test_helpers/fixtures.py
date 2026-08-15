"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. Setup calls use get_success_data (lenient) so a
setup failure surfaces as a clear "Setup failed" error.

Identity threading: SchoolCoach and Judge calls are entity-backed. Every
ownership-gated call threads the real entity id through make_coach_headers /
make_judge_headers; the shared TEST_USERS coach/judge constants are never used
for ownership-gated calls.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    LOCK_DAY,
    ROUND1_END,
    ROUND1_START,
    ROUND2_END,
    ROUND2_START,
    ROUND3_END,
    ROUND3_START,
    TIGHT_ROUND_END,
    TIGHT_ROUND_START,
    TOUCHING_ROUND_END,
    TOUCHING_ROUND_START,
)
from .factories import (
    create_contract_payload,
    create_debate_ballot_payload,
    create_division_payload,
    create_entry_payload,
    create_judge_payload,
    create_order_payload,
    create_room_payload,
    create_round_payload,
    create_school_payload,
    create_speech_ballot_payload,
    create_tournament_payload,
)
from .test_users import TEST_USERS, make_coach_headers, make_judge_headers

DIRECTOR = TEST_USERS["director_headers"]
TAB = TEST_USERS["tabstaff_headers"]


def _setup_failed(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text[:300]}")


# ---------------------------------------------------------------------------
# Tier 1: single-resource primitives
# ---------------------------------------------------------------------------

def create_tournament(name="Districts", registration_opens_at=None,
                      registration_locks_at=None, prelim_round_count=None,
                      entry_fee_cents=None, tournament_staff_count=None,
                      late_fee_starts_at=None, late_fee_surcharge_pct=None):
    """Create a tournament (born DRAFT / HIDDEN). Optional config only when given."""
    kwargs = {}
    if registration_opens_at is not None:
        kwargs["registration_opens_at"] = registration_opens_at
    if registration_locks_at is not None:
        kwargs["registration_locks_at"] = registration_locks_at
    payload = create_tournament_payload(
        name=name, prelim_round_count=prelim_round_count,
        entry_fee_cents=entry_fee_cents, tournament_staff_count=tournament_staff_count,
        late_fee_starts_at=late_fee_starts_at,
        late_fee_surcharge_pct=late_fee_surcharge_pct, **kwargs)
    return get_success_data(api_client.create_tournament(payload, DIRECTOR))


def add_division(tournament_id, event_type="DEBATE", event_code="CX",
                 division="VARSITY", per_school_entry_cap=None, global_entry_cap=None):
    payload = create_division_payload(
        tournament_id, event_type=event_type, event_code=event_code,
        division=division, per_school_entry_cap=per_school_entry_cap,
        global_entry_cap=global_entry_cap)
    return get_success_data(api_client.create_division(payload, DIRECTOR))


def add_school(tournament_id, name="Alpha", credit_limit_cents=None):
    payload = create_school_payload(tournament_id, name=name,
                                    credit_limit_cents=credit_limit_cents)
    return get_success_data(api_client.create_school(payload, DIRECTOR))


def open_registration(tournament_id):
    return get_success_data(api_client.open_registration(tournament_id, DIRECTOR))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, DIRECTOR))


def get_tournament(tournament_id):
    return get_success_data(api_client.get_tournament(tournament_id, DIRECTOR))


def get_division(division_id):
    return get_success_data(api_client.get_division(division_id, DIRECTOR))


def lock_tournament(tournament_id):
    """Lock with a fresh expected_tournament_version (OCC field per PRD §2.6)."""
    current = get_tournament(tournament_id)
    return get_success_data(api_client.lock_registration(
        tournament_id, current["version"], DIRECTOR))


def start_prelims(tournament_id):
    return get_success_data(api_client.start_prelims(tournament_id, DIRECTOR))


def start_elims(tournament_id):
    return get_success_data(api_client.start_elims(tournament_id, DIRECTOR))


def complete_tournament(tournament_id):
    return get_success_data(api_client.complete_tournament(tournament_id, DIRECTOR))


def publish_results(tournament_id):
    return get_success_data(api_client.publish_results(tournament_id, DIRECTOR))


def certify_qualifications(tournament_id):
    return get_success_data(api_client.certify_qualifications(tournament_id, DIRECTOR))


def add_entry(school_id, division_id, competitor_name):
    """Create an entry as the owning coach (born REGISTERED)."""
    payload = create_entry_payload(school_id, division_id, competitor_name)
    return get_success_data(
        api_client.create_entry(payload, make_coach_headers(school_id)))


def confirm_entry(entry_id, school_id):
    return get_success_data(
        api_client.confirm_entry(entry_id, make_coach_headers(school_id)))


def withdraw_entry(entry_id, school_id):
    return get_success_data(
        api_client.withdraw_entry(entry_id, make_coach_headers(school_id)))


def get_entry(entry_id):
    return get_success_data(api_client.get_entry(entry_id, DIRECTOR))


def add_judge(tournament_id, school_id, name):
    """Register a school-provided judge as the owning coach (born REGISTERED)."""
    payload = create_judge_payload(tournament_id, school_id, name)
    return get_success_data(
        api_client.create_judge(payload, make_coach_headers(school_id)))


def commit_judge(judge_id, school_id, commitment_rounds):
    return get_success_data(api_client.commit_judge(
        judge_id, commitment_rounds, make_coach_headers(school_id)))


def get_judge(judge_id):
    return get_success_data(api_client.get_judge(judge_id, TAB))


def confirm_school(school_id):
    return get_success_data(
        api_client.confirm_school(school_id, make_coach_headers(school_id)))


def get_school(school_id):
    return get_success_data(
        api_client.get_school(school_id, make_coach_headers(school_id)))


def add_room(tournament_id, name):
    return get_success_data(
        api_client.create_room(create_room_payload(tournament_id, name=name), DIRECTOR))


def add_round(division_id, round_number, kind="PRELIM",
              starts_at=ROUND1_START, ends_at=ROUND1_END):
    payload = create_round_payload(division_id, round_number=round_number, kind=kind,
                                   starts_at=starts_at, ends_at=ends_at)
    return get_success_data(api_client.create_round(payload, TAB))


def get_round(round_id):
    return get_success_data(api_client.get_round(round_id, TAB))


def generate_round(round_id):
    """Generate pairings with a fresh expected_round_version. Returns pairings."""
    current = get_round(round_id)
    get_success_data(api_client.generate_pairings(round_id, current["version"], TAB))
    pairings, _meta = validate_paginated(
        api_client.list_pairings(TAB, params={"round_id": round_id}))
    return pairings


def pairing_members(pairing_id):
    """Membership rows sorted by draw_position ascending (PRD §3.4)."""
    members, _meta = validate_paginated(
        api_client.list_pairing_entries(TAB, params={"pairing_id": pairing_id}))
    return members


def staff_pairing(pairing_id, room_id, judge_id):
    get_success_data(api_client.assign_room(pairing_id, room_id, TAB))
    get_success_data(api_client.assign_judge(pairing_id, judge_id, TAB))


def staff_round(pairings, room_ids, judge_ids):
    """Assign room_i / judge_i to the i-th non-bye pairing (listing order)."""
    i = 0
    for pairing in pairings:
        if pairing.get("is_bye"):
            continue
        staff_pairing(pairing["id"], room_ids[i], judge_ids[i])
        i += 1
    return i


def open_round(round_id):
    return get_success_data(api_client.open_ballots(round_id, TAB))


def tabulate(round_id):
    return get_success_data(api_client.tabulate_round(round_id, TAB))


def get_pairing(pairing_id):
    return get_success_data(api_client.get_pairing(pairing_id, TAB))


def create_debate_ballot(pairing_id, judge_id, winner_entry_id, speaker_points,
                         allow_low_point_win=None):
    payload = create_debate_ballot_payload(
        pairing_id, winner_entry_id, speaker_points,
        allow_low_point_win=allow_low_point_win)
    return get_success_data(
        api_client.create_ballot(payload, make_judge_headers(judge_id)))


def create_speech_ballot(pairing_id, judge_id, ranks):
    payload = create_speech_ballot_payload(pairing_id, ranks)
    return get_success_data(
        api_client.create_ballot(payload, make_judge_headers(judge_id)))


def submit_ballot(ballot_id, judge_id):
    return get_success_data(
        api_client.submit_ballot(ballot_id, make_judge_headers(judge_id)))


def recall_ballot(ballot_id, judge_id):
    return get_success_data(
        api_client.recall_ballot(ballot_id, make_judge_headers(judge_id)))


def verify_ballot(ballot_id):
    return get_success_data(api_client.verify_ballot(ballot_id, TAB))


def void_ballot(ballot_id):
    return get_success_data(api_client.void_ballot(ballot_id, TAB))


def get_ballot(ballot_id):
    return get_success_data(api_client.get_ballot(ballot_id, TAB))


def determine_breaks(division_id):
    return get_success_data(api_client.determine_breaks(division_id, TAB))


# ---------------------------------------------------------------------------
# Tier 1: hired-judge contracts and logistics
# ---------------------------------------------------------------------------

def create_contract_for_school(school_id, rounds_requested):
    """Create a hired-judge contract with a fresh expected_school_version (OCC)."""
    school = get_school(school_id)
    payload = create_contract_payload(school_id, rounds_requested, school["version"])
    return get_success_data(
        api_client.create_contract(payload, make_coach_headers(school_id)))


def fill_contract(contract_id, judge_name="Hired Judge"):
    return get_success_data(api_client.fill_contract(contract_id, judge_name, DIRECTOR))


def accept_contract(contract_id, school_id):
    return get_success_data(
        api_client.accept_contract(contract_id, make_coach_headers(school_id)))


def dispute_contract(contract_id, school_id):
    return get_success_data(
        api_client.dispute_contract(contract_id, make_coach_headers(school_id)))


def resolve_dispute(contract_id):
    return get_success_data(api_client.resolve_dispute(contract_id, DIRECTOR))


def pay_contract(contract_id, school_id):
    return get_success_data(
        api_client.pay_contract(contract_id, make_coach_headers(school_id)))


def cancel_contract(contract_id):
    return get_success_data(api_client.cancel_contract(contract_id, DIRECTOR))


def get_contract(contract_id):
    return get_success_data(api_client.get_contract(contract_id, DIRECTOR))


def create_order(tournament_id, kind="CATERING"):
    return get_success_data(
        api_client.create_order(create_order_payload(tournament_id, kind), DIRECTOR))


def submit_order(order_id):
    return get_success_data(api_client.submit_order(order_id, DIRECTOR))


def fulfill_order(order_id):
    return get_success_data(api_client.fulfill_order(order_id, DIRECTOR))


def get_order(order_id):
    return get_success_data(api_client.get_order(order_id, DIRECTOR))


# ---------------------------------------------------------------------------
# Tier 2: registration-graph scenario builder
# ---------------------------------------------------------------------------

def setup_registration_scenario(name="Districts", prelim_round_count=None,
                                entry_fee_cents=None, tournament_staff_count=None,
                                late_fee_starts_at=None, late_fee_surcharge_pct=None,
                                divisions=(("d", "DEBATE", "CX", "VARSITY", None, None),),
                                schools=(), confirm_schools=True, lock=True,
                                lock_clock=LOCK_DAY):
    """Tournament + divisions + schools; registration opened; every declared entry
    created and confirmed; every declared judge created and committed; optionally
    every school confirmed and the tournament locked.

    divisions: tuples (key, event_type, event_code, division, per_school_cap, global_cap)
    schools:   dicts {"key", "name", "entries": {div_key: count},
                      "judges": [commitment_rounds, ...], "credit_limit_cents": int?}
    Entries are created school-by-school in declaration order, so created_at order
    matches declaration order (drives the round-1 created_at ordering).
    """
    t = create_tournament(name=name, prelim_round_count=prelim_round_count,
                          entry_fee_cents=entry_fee_cents,
                          tournament_staff_count=tournament_staff_count,
                          late_fee_starts_at=late_fee_starts_at,
                          late_fee_surcharge_pct=late_fee_surcharge_pct)
    ws = {"t": t, "divisions": {}, "schools": {}, "entries": {}, "judges": {},
          "rounds": {}, "rooms": []}
    for (key, event_type, event_code, division, per_cap, glob_cap) in divisions:
        ws["divisions"][key] = add_division(
            t["id"], event_type=event_type, event_code=event_code, division=division,
            per_school_entry_cap=per_cap, global_entry_cap=glob_cap)
    for spec in schools:
        ws["schools"][spec["key"]] = add_school(
            t["id"], name=spec["name"],
            credit_limit_cents=spec.get("credit_limit_cents"))
    open_registration(t["id"])
    # Entries: create all (declaration order), then confirm all in the same order.
    for spec in schools:
        school_id = ws["schools"][spec["key"]]["id"]
        entries = []
        initial = spec["name"][0]
        for div_key, count in spec.get("entries", {}).items():
            for n in range(count):
                entries.append(add_entry(
                    school_id, ws["divisions"][div_key]["id"],
                    f"{initial}-{'One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve'.split()[n]}"))
        ws["entries"][spec["key"]] = entries
    for spec in schools:
        school_id = ws["schools"][spec["key"]]["id"]
        for entry in ws["entries"][spec["key"]]:
            confirm_entry(entry["id"], school_id)
    # Judges: create + commit per declared rounds.
    for spec in schools:
        school_id = ws["schools"][spec["key"]]["id"]
        judges = []
        for n, rounds in enumerate(spec.get("judges", [])):
            judge = add_judge(t["id"], school_id, f"J-{spec['name']}-{n + 1}")
            judges.append(commit_judge(judge["id"], school_id, rounds))
        ws["judges"][spec["key"]] = judges
    if confirm_schools:
        confirm_all_schools(ws)
    if lock:
        set_clock(lock_clock)
        ws["t"] = lock_tournament(t["id"])
    return ws


def confirm_all_schools(ws):
    for key in ws["schools"]:
        ws["schools"][key] = confirm_school(ws["schools"][key]["id"])


def schedule_rounds(ws, specs):
    """specs: {div_key: [(round_number, kind, starts_at, ends_at), ...]}.
    Rounds are scheduled before prelims start (start-prelims gate)."""
    for div_key, rounds_spec in specs.items():
        division = ws["divisions"][div_key]
        for (number, kind, start, end) in rounds_spec:
            round_ = add_round(division["id"], number, kind=kind,
                               starts_at=start, ends_at=end)
            ws["rounds"].setdefault(div_key, []).append(round_)
    return ws["rounds"]


def begin_prelims(ws):
    ws["t"] = start_prelims(ws["t"]["id"])
    return ws["t"]


def add_rooms(ws, count):
    for _ in range(count):
        ws["rooms"].append(add_room(ws["t"]["id"], f"Room {len(ws['rooms']) + 1}"))
    return ws["rooms"]


# ---------------------------------------------------------------------------
# Tier 3: round-flow drivers
# ---------------------------------------------------------------------------

def play_pairing_ballot(pairing_id, judge_id, winner_pos="first",
                        winner_points=27, loser_points=25, verify=True):
    """Create + submit (+ optionally verify) a debate ballot on a two-member pairing.
    winner_pos picks the winner by draw_position order: 'first' (AFF) or 'second'."""
    members = pairing_members(pairing_id)
    winner = members[0]["entry_id"] if winner_pos == "first" else members[1]["entry_id"]
    loser = members[1]["entry_id"] if winner_pos == "first" else members[0]["entry_id"]
    ballot = create_debate_ballot(
        pairing_id, judge_id, winner, {winner: winner_points, loser: loser_points})
    ballot = submit_ballot(ballot["id"], judge_id)
    if verify:
        ballot = verify_ballot(ballot["id"])
    return ballot


def play_debate_round(round_id, room_ids, judge_ids, plans, tabulate_round=True):
    """generate -> staff -> open -> ballot+verify each non-bye pairing -> tabulate.
    plans: per non-bye pairing (listing order) of (winner_pos, winner_pts, loser_pts).
    Returns (pairings, ballots)."""
    pairings = generate_round(round_id)
    staff_round(pairings, room_ids, judge_ids)
    open_round(round_id)
    ballots = []
    i = 0
    for pairing in pairings:
        if pairing.get("is_bye"):
            continue
        (pos, w_pts, l_pts) = plans[i]
        ballots.append(play_pairing_ballot(pairing["id"], judge_ids[i],
                                           pos, w_pts, l_pts))
        i += 1
    if tabulate_round:
        tabulate(round_id)
    return pairings, ballots


# ---------------------------------------------------------------------------
# Tier 4: composite ballot-stage scenarios
# ---------------------------------------------------------------------------

def setup_ballot_round(stage="open", name="Districts", prelim_round_count=2,
                       event=("DEBATE", "CX"), plan=("first", 27, 25)):
    """Alpha + Beta with 1 confirmed entry each; Epsilon with a committed judge;
    locked; round 1 scheduled 14:00-15:30; prelims active; one room; pairings
    generated. stage: paired | staffed | open | submitted | verified | tabulated.
    Returns ws with p1 (the single pairing) and, from 'submitted' on, ballot."""
    ws = setup_registration_scenario(
        name=name, prelim_round_count=prelim_round_count,
        divisions=(("d", event[0], event[1], "VARSITY", None, None),),
        schools=(
            {"key": "a", "name": "Alpha", "entries": {"d": 1},
             "judges": [prelim_round_count]},
            {"key": "b", "name": "Beta", "entries": {"d": 1},
             "judges": [prelim_round_count]},
            {"key": "e", "name": "Epsilon", "entries": {},
             "judges": [prelim_round_count]},
        ))
    schedule_rounds(ws, {"d": [(1, "PRELIM", ROUND1_START, ROUND1_END)]})
    begin_prelims(ws)
    add_rooms(ws, 1)
    ws["round"] = ws["rounds"]["d"][0]
    pairings = generate_round(ws["round"]["id"])
    ws["pairings"] = pairings
    ws["p1"] = pairings[0]
    ws["staff_judge"] = ws["judges"]["e"][0]
    if stage == "paired":
        return ws
    staff_round(pairings, [ws["rooms"][0]["id"]], [ws["staff_judge"]["id"]])
    if stage == "staffed":
        return ws
    open_round(ws["round"]["id"])
    if stage == "open":
        return ws
    (pos, w_pts, l_pts) = plan
    ws["ballot"] = play_pairing_ballot(ws["p1"]["id"], ws["staff_judge"]["id"],
                                       pos, w_pts, l_pts,
                                       verify=stage in ("verified", "tabulated"))
    if stage == "tabulated":
        tabulate(ws["round"]["id"])
    return ws


def setup_four_school_ballot_round(stage="open", name="Districts",
                                   prelim_round_count=2,
                                   plans=(("first", 27, 25), ("first", 27, 25))):
    """Alpha..Delta with 1 confirmed CX entry each; Epsilon with two committed
    judges; locked; round 1; prelims active; two rooms; pairings (A1,B1),(C1,D1).
    Same stage ladder as setup_ballot_round. Returns ws with p1, p2, judges f1/f2."""
    ws = setup_registration_scenario(
        name=name, prelim_round_count=prelim_round_count,
        schools=(
            {"key": "a", "name": "Alpha", "entries": {"d": 1},
             "judges": [prelim_round_count]},
            {"key": "b", "name": "Beta", "entries": {"d": 1},
             "judges": [prelim_round_count]},
            {"key": "c", "name": "Gamma", "entries": {"d": 1},
             "judges": [prelim_round_count]},
            {"key": "dd", "name": "Delta", "entries": {"d": 1},
             "judges": [prelim_round_count]},
            {"key": "e", "name": "Epsilon", "entries": {},
             "judges": [prelim_round_count, prelim_round_count]},
        ))
    schedule_rounds(ws, {"d": [(1, "PRELIM", ROUND1_START, ROUND1_END)]})
    begin_prelims(ws)
    add_rooms(ws, 2)
    ws["round"] = ws["rounds"]["d"][0]
    pairings = generate_round(ws["round"]["id"])
    ws["pairings"] = pairings
    ws["p1"], ws["p2"] = pairings[0], pairings[1]
    ws["staff_judges"] = ws["judges"]["e"]
    if stage == "paired":
        return ws
    staff_round(pairings, [r["id"] for r in ws["rooms"]],
                [j["id"] for j in ws["staff_judges"]])
    if stage == "staffed":
        return ws
    open_round(ws["round"]["id"])
    if stage == "open":
        return ws
    ballots = []
    for i, pairing in enumerate((ws["p1"], ws["p2"])):
        (pos, w_pts, l_pts) = plans[i]
        ballots.append(play_pairing_ballot(
            pairing["id"], ws["staff_judges"][i]["id"], pos, w_pts, l_pts,
            verify=stage in ("verified", "tabulated")))
    ws["ballots"] = ballots
    if stage == "tabulated":
        tabulate(ws["round"]["id"])
    return ws


def setup_bye_ballot_round(stage="open", name="Districts WN", prelim_round_count=2):
    """Alpha, Beta, Gamma with 1 confirmed CX entry each (3 entries -> one bye);
    Epsilon judge; locked; round 1; prelims active. Pairing list: the regular
    pairing first, then the bye pairing (emitted after all regular pairings)."""
    ws = setup_registration_scenario(
        name=name, prelim_round_count=prelim_round_count,
        schools=(
            {"key": "a", "name": "Alpha", "entries": {"d": 1},
             "judges": [prelim_round_count]},
            {"key": "b", "name": "Beta", "entries": {"d": 1},
             "judges": [prelim_round_count]},
            {"key": "c", "name": "Gamma", "entries": {"d": 1},
             "judges": [prelim_round_count]},
            {"key": "e", "name": "Epsilon", "entries": {},
             "judges": [prelim_round_count]},
        ))
    schedule_rounds(ws, {"d": [(1, "PRELIM", ROUND1_START, ROUND1_END)]})
    begin_prelims(ws)
    add_rooms(ws, 1)
    ws["round"] = ws["rounds"]["d"][0]
    pairings = generate_round(ws["round"]["id"])
    ws["pairings"] = pairings
    ws["p1"] = pairings[0]
    ws["bye_pairing"] = pairings[-1]
    ws["staff_judge"] = ws["judges"]["e"][0]
    if stage == "paired":
        return ws
    staff_pairing(ws["p1"]["id"], ws["rooms"][0]["id"], ws["staff_judge"]["id"])
    if stage == "staffed":
        return ws
    open_round(ws["round"]["id"])
    return ws


# ---------------------------------------------------------------------------
# Tier 4: multi-round competition scenarios
# ---------------------------------------------------------------------------

# Round-1 profile: first member wins each pairing 28/26, 28/24, 27/25.
# Round-2 profile: first member wins pairings 1-2 (30/23, 29/23); the second
# member wins pairing 3 (26/22).
TWO_ROUND_PLAN_R1 = [("first", 28, 26), ("first", 28, 24), ("first", 27, 25)]
TWO_ROUND_PLAN_R2 = [("first", 30, 23), ("first", 29, 23), ("second", 26, 22)]


def setup_break_boundary_scenario(name="Districts BK"):
    """Six CX entries (Alpha/Beta/Gamma, two each); Epsilon three committed judges;
    locked; prelim rounds 1 and 2 scheduled, played with the shared point profile
    and tabulated. determine-breaks is the caller's trigger."""
    ws = setup_registration_scenario(
        name=name, prelim_round_count=2,
        schools=(
            {"key": "a", "name": "Alpha", "entries": {"d": 2}, "judges": [2]},
            {"key": "b", "name": "Beta", "entries": {"d": 2}, "judges": [2]},
            {"key": "c", "name": "Gamma", "entries": {"d": 2}, "judges": [2]},
            {"key": "e", "name": "Epsilon", "entries": {}, "judges": [2, 2, 2]},
        ))
    schedule_rounds(ws, {"d": [(1, "PRELIM", ROUND1_START, ROUND1_END),
                               (2, "PRELIM", ROUND2_START, ROUND2_END)]})
    begin_prelims(ws)
    add_rooms(ws, 3)
    room_ids = [r["id"] for r in ws["rooms"]]
    judge_ids = [j["id"] for j in ws["judges"]["e"]]
    ws["r1_pairings"], ws["r1_ballots"] = play_debate_round(
        ws["rounds"]["d"][0]["id"], room_ids, judge_ids, TWO_ROUND_PLAN_R1)
    ws["r2_pairings"], ws["r2_ballots"] = play_debate_round(
        ws["rounds"]["d"][1]["id"], room_ids, judge_ids, TWO_ROUND_PLAN_R2)
    return ws


def setup_speaker_divergence_scenario(name="Districts SP"):
    """Five schools with 1 confirmed CX entry each; Zeta with two committed
    3-round judges; prelim_round_count 3; three prelim rounds scheduled
    (14:00, 16:00, 18:00). Rounds 1-2 played and tabulated:
      r1: (A1,B1) 30/26, (C1,D1) 28/25, bye to the lowest-ordered entry (E1);
      r2: (A1,C1) 28/26, (E1,B1) 26/24, bye to D1.
    Round 3 is generated, staffed, and opened; its ballots are the caller's
    trigger (plan: first member wins pairings 1-2 with 28/24 and 22/20)."""
    ws = setup_registration_scenario(
        name=name, prelim_round_count=3, entry_fee_cents=2500,
        tournament_staff_count=10,
        schools=(
            {"key": "a", "name": "Alpha", "entries": {"d": 1}, "judges": [3]},
            {"key": "b", "name": "Beta", "entries": {"d": 1}, "judges": [3]},
            {"key": "c", "name": "Gamma", "entries": {"d": 1}, "judges": [3]},
            {"key": "dd", "name": "Delta", "entries": {"d": 1}, "judges": [3]},
            {"key": "e", "name": "Epsilon", "entries": {"d": 1}, "judges": [3]},
            {"key": "f", "name": "Zeta", "entries": {}, "judges": [3, 3]},
        ))
    schedule_rounds(ws, {"d": [(1, "PRELIM", ROUND1_START, ROUND1_END),
                               (2, "PRELIM", ROUND2_START, ROUND2_END),
                               (3, "PRELIM", ROUND3_START, ROUND3_END)]})
    begin_prelims(ws)
    add_rooms(ws, 2)
    room_ids = [r["id"] for r in ws["rooms"]]
    judge_ids = [j["id"] for j in ws["judges"]["f"]]
    ws["r1_pairings"], _ = play_debate_round(
        ws["rounds"]["d"][0]["id"], room_ids, judge_ids,
        [("first", 30, 26), ("first", 28, 25)])
    ws["r2_pairings"], _ = play_debate_round(
        ws["rounds"]["d"][1]["id"], room_ids, judge_ids,
        [("first", 28, 26), ("first", 26, 24)])
    pairings_r3 = generate_round(ws["rounds"]["d"][2]["id"])
    staff_round(pairings_r3, room_ids, judge_ids)
    open_round(ws["rounds"]["d"][2]["id"])
    ws["r3_pairings"] = pairings_r3
    ws["staff_judges"] = ws["judges"]["f"]
    return ws


def setup_completed_tournament_for_publication(name="Districts QP"):
    """Full end-to-end: six competing CX entries (Alpha/Beta two each, Gamma two
    plus a third withdrawn pre-lock); Alpha covers its last shortfall round with
    a 1-round hired contract (filled, accepted, unpaid); both prelim rounds
    played with the shared profile; breaks determined (bracket 2); elim round
    played (seed 1 beats seed 2, 28/26); tournament COMPLETED; AWARDS order
    submitted. Publication/certification are the caller's triggers."""
    ws = setup_registration_scenario(
        name=name, prelim_round_count=2,
        schools=(
            {"key": "a", "name": "Alpha", "entries": {"d": 2}, "judges": [1]},
            {"key": "b", "name": "Beta", "entries": {"d": 2}, "judges": [2]},
            {"key": "c", "name": "Gamma", "entries": {"d": 3}, "judges": [2]},
            {"key": "e", "name": "Epsilon", "entries": {}, "judges": [2, 2, 2]},
        ),
        confirm_schools=False, lock=False)
    # Gamma's third entry leaves the competition before the lock.
    withdrawn = ws["entries"]["c"][2]
    ws["withdrawn_entry"] = withdraw_entry(withdrawn["id"], ws["schools"]["c"]["id"])
    # Alpha: obligation 2, one committed judge round, shortfall 1 -> 1-round contract.
    contract = create_contract_for_school(ws["schools"]["a"]["id"], 1)
    fill_contract(contract["id"], "Hired Alpha")
    ws["contract"] = accept_contract(contract["id"], ws["schools"]["a"]["id"])
    confirm_all_schools(ws)
    set_clock(LOCK_DAY)
    ws["t"] = lock_tournament(ws["t"]["id"])
    schedule_rounds(ws, {"d": [(1, "PRELIM", ROUND1_START, ROUND1_END),
                               (2, "PRELIM", ROUND2_START, ROUND2_END)]})
    begin_prelims(ws)
    add_rooms(ws, 3)
    room_ids = [r["id"] for r in ws["rooms"]]
    judge_ids = [j["id"] for j in ws["judges"]["e"]]
    play_debate_round(ws["rounds"]["d"][0]["id"], room_ids, judge_ids,
                      TWO_ROUND_PLAN_R1)
    play_debate_round(ws["rounds"]["d"][1]["id"], room_ids, judge_ids,
                      TWO_ROUND_PLAN_R2)
    determine_breaks(ws["divisions"]["d"]["id"])
    start_elims(ws["t"]["id"])
    elim = add_round(ws["divisions"]["d"]["id"], 3, kind="ELIM",
                     starts_at=ROUND3_START, ends_at=ROUND3_END)
    ws["elim_round"] = elim
    # Elim pairing: seed 1 vs seed 2; staffed by Beta's judge; first member wins.
    ws["elim_pairings"], _ = play_debate_round(
        elim["id"], [ws["rooms"][0]["id"]], [ws["judges"]["b"][0]["id"]],
        [("first", 28, 26)])
    ws["t"] = complete_tournament(ws["t"]["id"])
    ws["awards_order"] = submit_order(create_order(ws["t"]["id"], "AWARDS")["id"])
    return ws


# ---------------------------------------------------------------------------
# Tier 4: resource-contention scenarios (rooms / judges across divisions)
# ---------------------------------------------------------------------------

def setup_room_adjacency_scenario(name="Districts RM"):
    """CX division: Alpha..Delta 1 entry each; LD division: Epsilon, Zeta 1 each;
    every school a committed 2-round judge; locked; CX round 1 (14:00-15:30) and
    LD round 1 (15:30-17:00, touching endpoint) both paired; one room, already
    held by CX pairing p1. Returns ws with p1/p2 (CX), p3 (LD), room."""
    ws = setup_registration_scenario(
        name=name, prelim_round_count=2,
        divisions=(("cx", "DEBATE", "CX", "VARSITY", None, None),
                   ("ld", "DEBATE", "LD", "VARSITY", None, None)),
        schools=(
            {"key": "a", "name": "Alpha", "entries": {"cx": 1}, "judges": [2]},
            {"key": "b", "name": "Beta", "entries": {"cx": 1}, "judges": [2]},
            {"key": "c", "name": "Gamma", "entries": {"cx": 1}, "judges": [2]},
            {"key": "dd", "name": "Delta", "entries": {"cx": 1}, "judges": [2]},
            {"key": "e", "name": "Epsilon", "entries": {"ld": 1}, "judges": [2]},
            {"key": "f", "name": "Zeta", "entries": {"ld": 1}, "judges": [2]},
        ))
    schedule_rounds(ws, {"cx": [(1, "PRELIM", ROUND1_START, ROUND1_END)],
                         "ld": [(1, "PRELIM", TOUCHING_ROUND_START,
                                 TOUCHING_ROUND_END)]})
    begin_prelims(ws)
    add_rooms(ws, 1)
    ws["room"] = ws["rooms"][0]
    cx_pairings = generate_round(ws["rounds"]["cx"][0]["id"])
    ld_pairings = generate_round(ws["rounds"]["ld"][0]["id"])
    ws["p1"], ws["p2"] = cx_pairings[0], cx_pairings[1]
    ws["p3"] = ld_pairings[0]
    get_success_data(api_client.assign_room(ws["p1"]["id"], ws["room"]["id"], TAB))
    return ws


def setup_judge_turnover_scenario(name="Districts JT"):
    """CX (Alpha, Beta), LD (Gamma, Epsilon), PF (Zeta, Eta): 1 confirmed entry
    each with a committed 2-round judge; Delta has no entries and committed judge
    J-Delta (2 rounds); locked; CX 14:00-15:30, LD 15:45-17:15 (15-minute gap),
    PF 16:00-17:30 (exactly 30-minute gap) all paired; J-Delta already staffs the
    CX pairing. Returns ws with p_cx, p_ld, p_pf and j_d."""
    ws = setup_registration_scenario(
        name=name, prelim_round_count=2,
        divisions=(("cx", "DEBATE", "CX", "VARSITY", None, None),
                   ("ld", "DEBATE", "LD", "VARSITY", None, None),
                   ("pf", "DEBATE", "PF", "VARSITY", None, None)),
        schools=(
            {"key": "a", "name": "Alpha", "entries": {"cx": 1}, "judges": [2]},
            {"key": "b", "name": "Beta", "entries": {"cx": 1}, "judges": [2]},
            {"key": "c", "name": "Gamma", "entries": {"ld": 1}, "judges": [2]},
            {"key": "e", "name": "Epsilon", "entries": {"ld": 1}, "judges": [2]},
            {"key": "f", "name": "Zeta", "entries": {"pf": 1}, "judges": [2]},
            {"key": "g", "name": "Eta", "entries": {"pf": 1}, "judges": [2]},
            {"key": "dd", "name": "Delta", "entries": {}, "judges": [2]},
        ))
    schedule_rounds(ws, {"cx": [(1, "PRELIM", ROUND1_START, ROUND1_END)],
                         "ld": [(1, "PRELIM", TIGHT_ROUND_START, TIGHT_ROUND_END)],
                         "pf": [(1, "PRELIM", ROUND2_START, ROUND2_END)]})
    begin_prelims(ws)
    ws["p_cx"] = generate_round(ws["rounds"]["cx"][0]["id"])[0]
    ws["p_ld"] = generate_round(ws["rounds"]["ld"][0]["id"])[0]
    ws["p_pf"] = generate_round(ws["rounds"]["pf"][0]["id"])[0]
    ws["j_d"] = ws["judges"]["dd"][0]
    get_success_data(api_client.assign_judge(ws["p_cx"]["id"], ws["j_d"]["id"], TAB))
    return ws


def setup_conflict_priority_scenario(name="Districts CT"):
    """CX + LD divisions; Alpha (1 CX entry, judge J-Alpha committed 4); Beta
    (1 CX + 1 LD entry, two judges committed 4 each); Gamma (1 LD entry, judge
    committed 4); locked; CX round 1 (14:00-15:30) paired (A1, B1cx); LD round 1
    (15:45-17:15, a 15-minute gap) paired (B1ld, C1); J-Alpha already staffs the
    LD pairing (no conflict there). Assigning J-Alpha to the CX pairing violates
    both the conflict rule and the turnover buffer."""
    ws = setup_registration_scenario(
        name=name, prelim_round_count=4,
        divisions=(("cx", "DEBATE", "CX", "VARSITY", None, None),
                   ("ld", "DEBATE", "LD", "VARSITY", None, None)),
        schools=(
            {"key": "a", "name": "Alpha", "entries": {"cx": 1}, "judges": [4]},
            {"key": "b", "name": "Beta", "entries": {"cx": 1, "ld": 1},
             "judges": [4, 4]},
            {"key": "c", "name": "Gamma", "entries": {"ld": 1}, "judges": [4]},
        ))
    schedule_rounds(ws, {"cx": [(1, "PRELIM", ROUND1_START, ROUND1_END)],
                         "ld": [(1, "PRELIM", TIGHT_ROUND_START, TIGHT_ROUND_END)]})
    begin_prelims(ws)
    add_rooms(ws, 2)
    ws["p_cx"] = generate_round(ws["rounds"]["cx"][0]["id"])[0]
    ws["p_ld"] = generate_round(ws["rounds"]["ld"][0]["id"])[0]
    ws["j_a"] = ws["judges"]["a"][0]
    staff_pairing(ws["p_ld"]["id"], ws["rooms"][1]["id"], ws["j_a"]["id"])
    return ws


# ---------------------------------------------------------------------------
# Tier 4: hired-judge / fiscal scenarios
# ---------------------------------------------------------------------------

def setup_school_with_shortfall(name="Districts", entries=2, prelim_round_count=4,
                                entry_fee_cents=None, judge_rounds=(),
                                per_school_entry_cap=None, credit_limit_cents=None,
                                tournament_staff_count=None):
    """Tournament + one CX division + school Alpha with `entries` confirmed
    entries and the given committed judges. Registration left open (no lock)."""
    ws = setup_registration_scenario(
        name=name, prelim_round_count=prelim_round_count,
        entry_fee_cents=entry_fee_cents, tournament_staff_count=tournament_staff_count,
        divisions=(("d", "DEBATE", "CX", "VARSITY", per_school_entry_cap, None),),
        schools=(
            {"key": "a", "name": "Alpha", "entries": {"d": entries},
             "judges": list(judge_rounds), "credit_limit_cents": credit_limit_cents},
        ),
        confirm_schools=False, lock=False)
    return ws


def setup_fee_divergence_scenario(name="Districts HF"):
    """Tournament (prelim_round_count 4); Alpha with 2 confirmed CX entries
    (obligation 4, no judges); Beta with 3 confirmed CX entries (obligation 8,
    no judges). Alpha's 4-round contract is created first and left REQUESTED;
    Beta's 6-round contract is created second. Registration left open."""
    ws = setup_registration_scenario(
        name=name, prelim_round_count=4, entry_fee_cents=2500,
        schools=(
            {"key": "a", "name": "Alpha", "entries": {"d": 2}, "judges": []},
            {"key": "b", "name": "Beta", "entries": {"d": 3}, "judges": []},
        ),
        confirm_schools=False, lock=False)
    ws["c_a"] = create_contract_for_school(ws["schools"]["a"]["id"], 4)
    ws["c_b"] = create_contract_for_school(ws["schools"]["b"]["id"], 6)
    return ws


def setup_catering_freeze_scenario(name="Districts CF"):
    """Tournament (staff 10, prelim_round_count 4); CX division; school Alpha;
    registration open; a CATERING order created DRAFT (born at 0); two Alpha
    judges then committed — the commits are registration-graph mutations that
    recompute the DRAFT order's live demand to headcount 12 / meal 14."""
    ws = setup_registration_scenario(
        name=name, prelim_round_count=4, tournament_staff_count=10,
        schools=({"key": "a", "name": "Alpha", "entries": {}, "judges": []},),
        confirm_schools=False, lock=False)
    ws["order"] = create_order(ws["t"]["id"], "CATERING")
    judges = []
    for n in (1, 2):
        judge = add_judge(ws["t"]["id"], ws["schools"]["a"]["id"], f"J-Alpha-{n}")
        judges.append(commit_judge(judge["id"], ws["schools"]["a"]["id"], 4))
    ws["judges"]["a"] = judges
    return ws
