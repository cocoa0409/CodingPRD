"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database and the logical clock at its default). Setup calls use
get_success_data so failures surface as clear "Setup failed" errors.

The standard competitive pipeline encoded here:
  create tournament -> advance to REGISTRATION_OPEN -> players ->
  registrations -> roster slots -> submit -> review APPROVE -> fund ->
  set clock to the registration close -> advance to REGISTRATION_LOCKED ->
  generate-bracket -> schedule matches -> advance to IN_PROGRESS ->
  officiate/report/confirm -> advance to COMPLETED -> payout compute.

Team specs are dicts with keys: handle, dob, region, team_name, email,
rank, prior, qwins, plus optional submit (default True) and review
(default "APPROVE"; None leaves the registration unreviewed).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_dispute_payload,
    create_integrity_case_payload,
    create_player_payload,
    create_registration_payload,
    create_roster_slot_payload,
    create_server_payload,
    create_sponsor_deal_payload,
    create_talent_booking_payload,
    create_talent_payload,
    create_tournament_payload,
    schedule_match_payload,
)
from .test_users import (
    TEST_USERS,
    make_anti_cheat_investigator_headers,
    make_player_headers,
    make_payout_officer_headers,
    make_referee_headers,
    make_sponsor_manager_headers,
    make_team_manager_headers,
)

ADMIN = TEST_USERS["organizer_admin_headers"]
TD = TEST_USERS["tournament_director_headers"]
PRODUCER = TEST_USERS["broadcast_producer_headers"]
PAYOUT = TEST_USERS["payout_officer_headers"]
AC = TEST_USERS["anti_cheat_investigator_headers"]

DEFAULT_OPEN = "2026-08-01T00:00:00Z"
DEFAULT_CLOSE = "2026-08-10T00:00:00Z"
LOCK_TIME = "2026-08-10T00:00:00Z"
MATCH_DAY = "2026-08-11"


def _ok(step, resp):
    if not (200 <= resp.status_code < 300):
        raise AssertionError(
            f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}")
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Primitive steps
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return _ok("set_clock", resp)


def create_tournament(name="Test Cup", **overrides):
    resp = api_client.create_tournament(
        create_tournament_payload(name=name, **overrides), ADMIN)
    return _ok("create_tournament", resp)


def get_tournament(tournament_id):
    resp = api_client.get_tournament(tournament_id, TD)
    return _ok("get_tournament", resp)


def advance_tournament(tournament_id, target_status):
    resp = api_client.advance_tournament(
        tournament_id, {"target_status": target_status}, TD)
    return _ok(f"advance_tournament({target_status})", resp)


def fund_tournament(tournament_id, amount_cents):
    resp = api_client.fund_tournament(
        tournament_id, {"amount_cents": amount_cents}, ADMIN)
    return _ok("fund_tournament", resp)


def get_tournament_version(tournament_id):
    return get_tournament(tournament_id)["version"]


def generate_bracket(tournament_id, expected_version=None):
    if expected_version is None:
        expected_version = get_tournament_version(tournament_id)
    resp = api_client.generate_bracket(
        tournament_id, {"expected_tournament_version": expected_version}, TD)
    return _ok("generate_bracket", resp)


def create_player(handle, dob="2000-01-01", region="NA"):
    resp = api_client.create_player(
        create_player_payload(handle=handle, date_of_birth=dob,
                              region=region), ADMIN)
    return _ok("create_player", resp)


def get_player(player_id):
    resp = api_client.get_player(player_id, ADMIN)
    return _ok("get_player", resp)


def set_eligibility(player_id, action):
    resp = api_client.set_player_eligibility(player_id, {"action": action},
                                             ADMIN)
    return _ok("set_eligibility", resp)


def create_registration(tournament_id, team_name, captain_player_id,
                        rank=100, prior=0, qwins=0, email=None):
    resp = api_client.create_registration(
        create_registration_payload(
            tournament_id, captain_player_id, team_name=team_name,
            manager_contact_email=email or f"{team_name.lower()}@x.gg",
            region_rank_points=rank, prior_event_points=prior,
            qualifier_wins=qwins),
        ADMIN)
    return _ok("create_registration", resp)


def get_registration(registration_id):
    resp = api_client.get_registration(registration_id, TD)
    return _ok("get_registration", resp)


def add_roster_slot(registration_id, player_id, slot_role="STARTER"):
    resp = api_client.create_roster_slot(
        create_roster_slot_payload(registration_id, player_id, slot_role),
        make_team_manager_headers(registration_id))
    return _ok("add_roster_slot", resp)


def get_roster_slot(slot_id):
    resp = api_client.get_roster_slot(slot_id, TD)
    return _ok("get_roster_slot", resp)


def submit_registration(registration_id):
    resp = api_client.submit_registration(
        registration_id, make_team_manager_headers(registration_id))
    return _ok("submit_registration", resp)


def review_registration(registration_id, action, reason=None):
    payload = {"action": action}
    if reason is not None:
        payload["reason"] = reason
    resp = api_client.review_registration(registration_id, payload, TD)
    return _ok("review_registration", resp)


def appeal_registration(registration_id):
    resp = api_client.appeal_registration(
        registration_id, make_team_manager_headers(registration_id))
    return _ok("appeal_registration", resp)


def create_server(tournament_id, label="S1", region="NA"):
    resp = api_client.create_server(
        create_server_payload(tournament_id, label=label, region=region),
        ADMIN)
    return _ok("create_server", resp)


def get_server(server_id):
    resp = api_client.get_server(server_id, TD)
    return _ok("get_server", resp)


def set_server_maintenance(server_id, action):
    resp = api_client.server_maintenance(server_id, {"action": action}, ADMIN)
    return _ok("set_server_maintenance", resp)


def get_matches(tournament_id):
    """List matches in the PRD's deterministic order: bracket_round ASC,
    then bracket_slot ASC."""
    resp = api_client.list_matches(TD, params={"tournament_id": tournament_id})
    return _ok("get_matches", resp)


def get_match(match_id):
    resp = api_client.get_match(match_id, TD)
    return _ok("get_match", resp)


def schedule_match(match_id, server_id, scheduled_start_at,
                   duration_minutes=60, referee_id="ref-1"):
    resp = api_client.schedule_match(
        match_id,
        schedule_match_payload(server_id, scheduled_start_at,
                               duration_minutes, referee_id),
        TD)
    return _ok("schedule_match", resp)


def officiate_match(match_id, payload, referee_id="ref-1"):
    resp = api_client.officiate_match(
        match_id, payload, make_referee_headers(referee_id))
    return _ok("officiate_match", resp)


def report_result(match_id, home_score, away_score, reporter_id="ref-1"):
    resp = api_client.report_result(
        match_id, {"home_score": home_score, "away_score": away_score},
        make_referee_headers(reporter_id))
    return _ok("report_result", resp)


def confirm_result(match_id, confirmer_id="ref-2"):
    resp = api_client.confirm_result(
        match_id, make_referee_headers(confirmer_id))
    return _ok("confirm_result", resp)


def play_match_to_completed(match_id, home_score=13, away_score=7,
                            referee_id="ref-1"):
    """OPEN_LOBBY -> START -> report-result. Returns the COMPLETED match."""
    officiate_match(match_id, {"action": "OPEN_LOBBY"}, referee_id)
    officiate_match(match_id, {"action": "START"}, referee_id)
    return report_result(match_id, home_score, away_score, referee_id)


def play_match_to_confirmed(match_id, home_score=13, away_score=7,
                            reporter_id="ref-1", confirmer_id="ref-2"):
    play_match_to_completed(match_id, home_score, away_score, reporter_id)
    return confirm_result(match_id, confirmer_id)


def create_dispute(match_id, registration_id, reason="RULE_VIOLATION",
                   details="evidence package attached"):
    resp = api_client.create_dispute(
        create_dispute_payload(match_id, registration_id, reason=reason,
                               details=details),
        make_team_manager_headers(registration_id))
    return _ok("create_dispute", resp)


def get_dispute(dispute_id):
    resp = api_client.get_dispute(dispute_id, TD)
    return _ok("get_dispute", resp)


def adjudicate_dispute(dispute_id, payload):
    resp = api_client.adjudicate_dispute(dispute_id, payload, TD)
    return _ok("adjudicate_dispute", resp)


def create_integrity_case(player_id, evidence_summary="sig", match_id=None,
                          investigator_id="ac-1"):
    payload = create_integrity_case_payload(
        player_id, evidence_summary=evidence_summary)
    if match_id is not None:
        payload["match_id"] = match_id
    resp = api_client.create_integrity_case(
        payload, make_anti_cheat_investigator_headers(investigator_id))
    return _ok("create_integrity_case", resp)


def get_integrity_case(case_id):
    resp = api_client.get_integrity_case(case_id, AC)
    return _ok("get_integrity_case", resp)


def resolve_case(case_id, payload, investigator_id="ac-1"):
    resp = api_client.resolve_integrity_case(
        case_id, payload,
        make_anti_cheat_investigator_headers(investigator_id))
    return _ok("resolve_case", resp)


def issue_violation_strike(player_id, evidence_summary="sig",
                           investigator_id="ac-1"):
    """Open a case -> BEGIN_INVESTIGATION -> RESOLVE VIOLATION.

    Appends one strike to the player. Returns the resolved case.
    """
    case = create_integrity_case(player_id, evidence_summary,
                                 investigator_id=investigator_id)
    resolve_case(case["id"], {"action": "BEGIN_INVESTIGATION"},
                 investigator_id)
    return resolve_case(case["id"],
                        {"action": "RESOLVE", "outcome": "VIOLATION"},
                        investigator_id)


def issue_cleared_case(player_id, evidence_summary="sig", match_id=None,
                       investigator_id="ac-1"):
    """Open a case -> BEGIN_INVESTIGATION -> RESOLVE CLEARED."""
    case = create_integrity_case(player_id, evidence_summary,
                                 match_id=match_id,
                                 investigator_id=investigator_id)
    resolve_case(case["id"], {"action": "BEGIN_INVESTIGATION"},
                 investigator_id)
    return resolve_case(case["id"], {"action": "RESOLVE", "outcome": "CLEARED"},
                        investigator_id)


def ban_player_with_strikes(player_id, count=3, investigator_id="ac-1"):
    """Append `count` violation strikes; the strike that reaches the limit
    bans the player and fires the DQ cascade."""
    for i in range(count):
        case = issue_violation_strike(
            player_id, f"sig {i + 1}", investigator_id=investigator_id)
    return case


def create_talent(stage_name="CasterOne", home_region="NA",
                  day_rate_cents=80000, cross_region=None):
    overrides = {}
    if cross_region is not None:
        overrides["cross_region"] = cross_region
    resp = api_client.create_talent(
        create_talent_payload(stage_name=stage_name, home_region=home_region,
                              day_rate_cents=day_rate_cents, **overrides),
        PRODUCER)
    return _ok("create_talent", resp)


def create_talent_booking(tournament_id, talent_id, stage_label="MAIN",
                          shift_start_at="2026-08-12T10:00:00Z",
                          shift_end_at="2026-08-12T12:00:00Z"):
    resp = api_client.create_talent_booking(
        create_talent_booking_payload(
            tournament_id, talent_id, stage_label=stage_label,
            shift_start_at=shift_start_at, shift_end_at=shift_end_at),
        PRODUCER)
    return _ok("create_talent_booking", resp)


def get_talent_booking(booking_id):
    resp = api_client.get_talent_booking(booking_id, PRODUCER)
    return _ok("get_talent_booking", resp)


def transition_talent_booking(booking_id, action):
    resp = api_client.transition_talent_booking(booking_id,
                                                {"action": action}, PRODUCER)
    return _ok("transition_talent_booking", resp)


def create_sponsor_deal(tournament_id, sponsor_name="Acme",
                        contact_user_id="sm-1", rights_tier="TITLE",
                        bonus_cents=200000, content_rights=None):
    resp = api_client.create_sponsor_deal(
        create_sponsor_deal_payload(
            tournament_id, sponsor_name=sponsor_name,
            contact_user_id=contact_user_id, rights_tier=rights_tier,
            bonus_cents=bonus_cents,
            content_rights=content_rights or ["VOD"]),
        ADMIN)
    return _ok("create_sponsor_deal", resp)


def transition_sponsor_deal(deal_id, action, headers=None):
    resp = api_client.transition_sponsor_deal(deal_id, {"action": action},
                                              headers or ADMIN)
    return _ok("transition_sponsor_deal", resp)


def activate_sponsor_deal(deal_id, contact_user_id):
    resp = api_client.transition_sponsor_deal(
        deal_id, {"action": "ACTIVATE"},
        make_sponsor_manager_headers(contact_user_id))
    return _ok("activate_sponsor_deal", resp)


# ---------------------------------------------------------------------------
# Payout records
# ---------------------------------------------------------------------------

def compute_payout_records(tournament_id, mode, expected_version=None):
    if expected_version is None:
        expected_version = get_tournament_version(tournament_id)
    resp = api_client.compute_payout_records(
        tournament_id,
        {"mode": mode, "expected_tournament_version": expected_version},
        PAYOUT)
    return _ok("compute_payout_records", resp)


def list_payout_records(tournament_id, **filters):
    params = {"tournament_id": tournament_id}
    params.update(filters)
    resp = api_client.list_payout_records(PAYOUT, params=params)
    return _ok("list_payout_records", resp)


def get_payout_record(record_id):
    resp = api_client.get_payout_record(record_id, PAYOUT)
    return _ok("get_payout_record", resp)


def record_for_registration(records, registration_id):
    matches = [r for r in records if r["registration_id"] == registration_id]
    assert len(matches) == 1, (
        f"expected exactly one payout record for registration "
        f"{registration_id}, got {len(matches)}")
    return matches[0]


def submit_payout_docs(record_id, payee_player_id, doc_type,
                       guardian_name=None, guardian_email=None):
    payload = {"doc_type": doc_type}
    if guardian_name is not None:
        payload["guardian_name"] = guardian_name
    if guardian_email is not None:
        payload["guardian_email"] = guardian_email
    resp = api_client.submit_payout_docs(
        record_id, payload, make_player_headers(payee_player_id))
    return _ok("submit_payout_docs", resp)


def verify_payout_docs(record_id, action, officer_id="po-1"):
    resp = api_client.verify_payout_docs(
        record_id, {"action": action}, make_payout_officer_headers(officer_id))
    return _ok("verify_payout_docs", resp)


def approve_payout(record_id, officer_id="po-2"):
    resp = api_client.approve_payout(
        record_id, make_payout_officer_headers(officer_id))
    return _ok("approve_payout", resp)


def pay_payout(record_id, officer_id="po-1"):
    resp = api_client.pay_payout(record_id,
                                 make_payout_officer_headers(officer_id))
    return _ok("pay_payout", resp)


# ---------------------------------------------------------------------------
# Tier 2/3 — competitive pipeline scenarios
# ---------------------------------------------------------------------------

def _default_team_specs(count=2):
    base = [
        {"handle": "p1", "dob": "2000-01-01", "team_name": "Alpha",
         "rank": 100},
        {"handle": "p2", "dob": "2000-02-02", "team_name": "Beta",
         "rank": 80},
        {"handle": "p3", "dob": "2000-03-03", "team_name": "Gamma",
         "rank": 60},
        {"handle": "p4", "dob": "2000-04-04", "team_name": "Delta",
         "rank": 40},
    ]
    specs = []
    for i in range(count):
        spec = dict(base[i])
        spec.setdefault("region", "NA")
        spec.setdefault("prior", 0)
        spec.setdefault("qwins", 0)
        specs.append(spec)
    return specs


def setup_registration_open_tournament(name="Cup", team_count=2,
                                       team_specs=None, region="NA",
                                       prize_pool_target_cents=100000,
                                       roster_size=1, max_roster_size=2,
                                       curfew="22:00",
                                       opens=DEFAULT_OPEN,
                                       closes=DEFAULT_CLOSE):
    """Tournament REGISTRATION_OPEN with rostered (and optionally
    submitted/reviewed) registrations.

    Per-team spec keys submit (default True) and review (default "APPROVE";
    None leaves the registration unreviewed) control the pipeline depth.
    Returns dict(tournament, players, registrations, slots).
    """
    specs = team_specs if team_specs is not None else _default_team_specs(
        team_count)
    tournament = create_tournament(
        name, region=region, prize_pool_target_cents=prize_pool_target_cents,
        roster_size=roster_size, max_roster_size=max_roster_size,
        registration_opens_at=opens, registration_closes_at=closes,
        minor_curfew_local=curfew)
    advance_tournament(tournament["id"], "REGISTRATION_OPEN")
    players, registrations, slots = [], [], []
    for spec in specs:
        player = create_player(spec["handle"], spec["dob"],
                               spec.get("region", "NA"))
        registration = create_registration(
            tournament["id"], spec["team_name"], player["id"],
            rank=spec.get("rank", 100), prior=spec.get("prior", 0),
            qwins=spec.get("qwins", 0), email=spec.get("email"))
        slot = add_roster_slot(registration["id"], player["id"], "STARTER")
        if spec.get("submit", True):
            submit_registration(registration["id"])
            action = spec.get("review", "APPROVE")
            if action is not None:
                review_registration(registration["id"], action,
                                    reason=spec.get("reason"))
        players.append(player)
        registrations.append(get_registration(registration["id"]))
        slots.append(slot)
    return {
        "tournament": get_tournament(tournament["id"]),
        "players": players,
        "registrations": registrations,
        "slots": slots,
    }


def setup_locked_tournament(name="Cup", team_count=2, team_specs=None,
                            fund_amounts=(100000,), lock_time=LOCK_TIME,
                            **kwargs):
    """Registration-open scenario + funding + clock to the registration
    close + advance to REGISTRATION_LOCKED."""
    ctx = setup_registration_open_tournament(
        name, team_count=team_count, team_specs=team_specs, **kwargs)
    tournament_id = ctx["tournament"]["id"]
    for amount in fund_amounts:
        fund_tournament(tournament_id, amount)
    set_clock(lock_time)
    advance_tournament(tournament_id, "REGISTRATION_LOCKED")
    ctx["tournament"] = get_tournament(tournament_id)
    ctx["registrations"] = [
        get_registration(r["id"]) for r in ctx["registrations"]]
    return ctx


def setup_seeded_tournament(name="Cup", team_count=2, team_specs=None,
                            fund_amounts=(100000,), lock_time=LOCK_TIME,
                            **kwargs):
    """Locked scenario + generate-bracket. Adds matches to the context."""
    ctx = setup_locked_tournament(
        name, team_count=team_count, team_specs=team_specs,
        fund_amounts=fund_amounts, lock_time=lock_time, **kwargs)
    tournament_id = ctx["tournament"]["id"]
    generate_bracket(tournament_id)
    ctx["tournament"] = get_tournament(tournament_id)
    ctx["matches"] = get_matches(tournament_id)
    return ctx


def setup_in_progress_2team(name="Cup", prize_pool_target_cents=100000,
                            fund_amounts=(100000,), region="NA",
                            team_specs=None, curfew="22:00",
                            server_region=None,
                            match_start=f"{MATCH_DAY}T10:00:00Z",
                            duration_minutes=60, referee_id="ref-1"):
    """Seeded 2-team scenario + one server + the single round-1 (final)
    match scheduled + advance to IN_PROGRESS. Adds server and match."""
    ctx = setup_seeded_tournament(
        name, team_count=2, team_specs=team_specs, region=region,
        prize_pool_target_cents=prize_pool_target_cents,
        fund_amounts=fund_amounts, curfew=curfew)
    tournament_id = ctx["tournament"]["id"]
    server = create_server(
        tournament_id, "S1", server_region or region or "NA")
    match = ctx["matches"][0]
    schedule_match(match["id"], server["id"], match_start,
                   duration_minutes, referee_id)
    advance_tournament(tournament_id, "IN_PROGRESS")
    ctx["server"] = server
    ctx["match"] = match
    ctx["tournament"] = get_tournament(tournament_id)
    return ctx


def setup_completed_2team(name="Cup", prize_pool_target_cents=100000,
                          fund_amounts=None, region="NA", team_specs=None,
                          home_score=13, away_score=7, reporter_id="ref-1",
                          confirmer_id="ref-2", curfew="22:00"):
    """Full 2-team pipeline through COMPLETED: the single match is played
    (home wins by default), confirmed, and placements are assigned."""
    amounts = fund_amounts
    if amounts is None:
        amounts = (prize_pool_target_cents,)
    ctx = setup_in_progress_2team(
        name, prize_pool_target_cents=prize_pool_target_cents,
        fund_amounts=amounts, region=region, team_specs=team_specs,
        curfew=curfew, referee_id=reporter_id)
    play_match_to_confirmed(ctx["match"]["id"], home_score, away_score,
                            reporter_id, confirmer_id)
    advance_tournament(ctx["tournament"]["id"], "COMPLETED")
    ctx["match"] = get_match(ctx["match"]["id"])
    ctx["tournament"] = get_tournament(ctx["tournament"]["id"])
    ctx["registrations"] = [
        get_registration(r["id"]) for r in ctx["registrations"]]
    return ctx


def setup_in_progress_4team(name="Cup", prize_pool_target_cents=100000,
                            fund_amounts=None, reporter_id="ref-1",
                            team_specs=None):
    """Seeded 4-team scenario + one server + both round-1 matches scheduled
    (10:00 and 12:00 on match day) + advance to IN_PROGRESS.

    Match layout (bracket_round ASC, bracket_slot ASC):
      matches[0] = round 1 slot 1: seed 1 (home) vs seed 4 (away)
      matches[1] = round 1 slot 2: seed 2 (home) vs seed 3 (away)
      matches[2] = round 2 slot 1 (final): both participants TBD.
    """
    amounts = fund_amounts
    if amounts is None:
        amounts = (prize_pool_target_cents,)
    ctx = setup_seeded_tournament(
        name, team_count=4, team_specs=team_specs,
        prize_pool_target_cents=prize_pool_target_cents, fund_amounts=amounts)
    tournament_id = ctx["tournament"]["id"]
    server = create_server(tournament_id, "S1", "NA")
    m1, m2, mf = ctx["matches"]
    schedule_match(m1["id"], server["id"], f"{MATCH_DAY}T10:00:00Z", 60,
                   reporter_id)
    schedule_match(m2["id"], server["id"], f"{MATCH_DAY}T12:00:00Z", 60,
                   reporter_id)
    advance_tournament(tournament_id, "IN_PROGRESS")
    ctx["server"] = server
    ctx["tournament"] = get_tournament(tournament_id)
    return ctx


def setup_dispute_under_review(match_id, filer_registration_id,
                               reason="RULE_VIOLATION",
                               details="evidence package attached"):
    """File a dispute on a COMPLETED match and move it FILED -> UNDER_REVIEW.
    Returns the dispute."""
    dispute = create_dispute(match_id, filer_registration_id, reason,
                             details)
    adjudicate_dispute(dispute["id"], {"action": "START_REVIEW"})
    return get_dispute(dispute["id"])


def setup_completed_4team(name="Cup", prize_pool_target_cents=100000,
                          fund_amounts=None, reporter_id="ref-1",
                          confirmer_id="ref-2"):
    """Full 4-team pipeline through COMPLETED.

    Round 1: m1 = seed1 (home) vs seed4, home wins 13-5;
             m2 = seed2 (home) vs seed3, home wins 13-9.
    Final:   mf = seed1 (home) vs seed2, home wins 13-11.
    Placements: seed1 -> 1, seed2 -> 2, seed3 and seed4 -> 3.
    """
    amounts = fund_amounts
    if amounts is None:
        amounts = (prize_pool_target_cents,)
    ctx = setup_seeded_tournament(
        name, team_count=4, prize_pool_target_cents=prize_pool_target_cents,
        fund_amounts=amounts)
    tournament_id = ctx["tournament"]["id"]
    server = create_server(tournament_id, "S1", "NA")
    m1, m2, mf = ctx["matches"]
    schedule_match(m1["id"], server["id"], f"{MATCH_DAY}T10:00:00Z", 60,
                   reporter_id)
    schedule_match(m2["id"], server["id"], f"{MATCH_DAY}T12:00:00Z", 60,
                   reporter_id)
    advance_tournament(tournament_id, "IN_PROGRESS")
    play_match_to_confirmed(m1["id"], 13, 5, reporter_id, confirmer_id)
    play_match_to_confirmed(m2["id"], 13, 9, reporter_id, confirmer_id)
    schedule_match(mf["id"], server["id"], f"{MATCH_DAY}T14:00:00Z", 60,
                   reporter_id)
    play_match_to_confirmed(mf["id"], 13, 11, reporter_id, confirmer_id)
    advance_tournament(tournament_id, "COMPLETED")
    ctx["server"] = server
    ctx["tournament"] = get_tournament(tournament_id)
    ctx["registrations"] = [
        get_registration(r["id"]) for r in ctx["registrations"]]
    ctx["matches"] = get_matches(tournament_id)
    return ctx
