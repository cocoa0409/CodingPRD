"""Composite setup helpers.

Every fixture builds its preconditions from scratch against an empty database,
using only PRD-declared endpoints. Setup calls use get_success_data() so a setup
failure surfaces as a clear "Setup failed" message instead of a confusing
assertion error.

Timeline conventions (logical clock starts at 2026-08-01T00:00:00Z):
- canonical event window: 2026-10-08 .. 2026-10-12
- canonical hotel block: 20 rooms/night x 4 nights = 80 contracted room-nights,
  rate 15000 cents, cutoff 2026-10-01, attrition allowance 0.20
- canonical final-match start: 2026-10-10T14:00:00Z on a 90-minute slot field
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_event_payload, create_bid_payload, create_requirement_payload,
    create_venue_payload, create_field_payload, create_hotel_block_payload,
    create_booking_payload, create_division_payload, create_team_payload,
    create_official_payload, create_assignment_payload, create_volunteer_payload,
    create_shift_payload, create_weather_alert_payload,
    create_impact_report_payload, create_settlement_payload,
)
from .test_users import (
    TEST_USERS, make_teamrep_headers, make_official_headers,
    make_volunteer_headers, make_venue_manager_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ADMIN2 = TEST_USERS["admin2_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
CVB = TEST_USERS["cvb_headers"]
ANY = TEST_USERS["any_headers"]


def _ctx(label: str, resp):
    if resp.status_code >= 400:
        raise AssertionError(
            f"Setup failed during {label}: HTTP {resp.status_code} body={resp.text[:400]}"
        )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Primitive steps
# ---------------------------------------------------------------------------

def create_event(**overrides):
    return _ctx("create event", api_client.create_event(create_event_payload(**overrides), ADMIN))


def get_event(event_id):
    return _ctx("get event", api_client.get_event(event_id, ANY))


def set_clock(to_iso8601):
    return _ctx("set clock", api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_bid(event_id, **overrides):
    ev = get_event(event_id)
    return _ctx("create bid", api_client.create_bid(
        event_id, create_bid_payload(ev["version"], **overrides), ADMIN))


def create_verified_bid(event_id, requirement_overrides=None, evidence_user="ops-admin-1"):
    """Bid with one mandatory requirement (default weight 100) VERIFIED.

    Returns the bid dict (still DRAFT)."""
    bid = create_bid(event_id)
    req = _ctx("create requirement", api_client.create_requirement(
        bid["id"], create_requirement_payload(**(requirement_overrides or {})), ADMIN))
    _ctx("submit evidence", api_client.submit_evidence(
        req["id"], {"evidence_uri": "s3://ev/ins.pdf"},
        dict(ADMIN, **{"X-User-ID": evidence_user})))
    _ctx("verify requirement", api_client.verify_requirement(
        req["id"], {"decision": "VERIFIED"}, REVIEWER))
    return bid


def award_event_bid(event_id, **kwargs):
    """Create + verify + submit + review + award the event's bid.

    Returns the AWARDED bid. Leaves the event in AWARDED posture."""
    bid = create_verified_bid(event_id, **kwargs)
    _ctx("submit bid", api_client.submit_bid(bid["id"], ADMIN))
    _ctx("review bid", api_client.review_bid(bid["id"], REVIEWER))
    return _ctx("award bid", api_client.decide_bid(bid["id"], {"decision": "AWARDED"}, REVIEWER))


def create_contracted_venue(event_id, venue_overrides=None, field_overrides=None):
    """Contracted venue plus (by default) one lit 90-minute field.

    Returns (venue, field) when a field is created, else (venue, None)."""
    venue = _ctx("create venue", api_client.create_venue(
        event_id, create_venue_payload(**(venue_overrides or {})), ADMIN))
    venue = _ctx("contract venue", api_client.contract_venue(
        venue["id"], {"contract_uri": "s3://contracts/v1.pdf"}, ADMIN))
    field = None
    if field_overrides is not False:
        field = _ctx("create field", api_client.create_field(
            venue["id"], create_field_payload(**(field_overrides or {})), ADMIN))
    return venue, field


def create_hotel_block(event_id, contracted=True, **overrides):
    block = _ctx("create hotel block", api_client.create_hotel_block(
        event_id, create_hotel_block_payload(**overrides), ADMIN))
    if contracted:
        block = _ctx("contract hotel block", api_client.contract_hotel_block(block["id"], ADMIN))
    return block


def create_booking(block_id, confirm=False, check_in_out=False, **overrides):
    """Booking on a contracted block. confirm drives it to CONFIRMED;
    check_in_out additionally advances the clock and walks to CHECKED_OUT."""
    booking = _ctx("create booking", api_client.create_booking(
        block_id, create_booking_payload(**overrides), ADMIN))
    if confirm or check_in_out:
        booking = _ctx("confirm booking", api_client.transition_booking(
            booking["id"], {"action": "CONFIRM"}, ADMIN))
    if check_in_out:
        set_clock("2026-10-09T00:00:00Z")
        booking = _ctx("check in booking", api_client.transition_booking(
            booking["id"], {"action": "CHECK_IN"}, ADMIN))
        set_clock("2026-10-13T00:00:00Z")
        booking = _ctx("check out booking", api_client.transition_booking(
            booking["id"], {"action": "CHECK_OUT"}, ADMIN))
    return booking


def reconcile_block(block_id, clock_iso="2026-10-13T00:00:00Z"):
    """Advance the clock past the cutoff, close the window, reconcile."""
    set_clock(clock_iso)
    _ctx("close cutoff", api_client.close_cutoff(block_id, ADMIN))
    return _ctx("reconcile block", api_client.reconcile_hotel_block(block_id, ADMIN))


def advance_posture(event_id, to_posture):
    ev = get_event(event_id)
    return _ctx(f"posture -> {to_posture}", api_client.advance_posture(
        event_id, {"to_posture": to_posture, "expected_event_version": ev["version"]}, ADMIN))


def create_division(event_id, **overrides):
    return _ctx("create division", api_client.create_division(
        event_id, create_division_payload(**overrides), ADMIN))


def create_team(division_id, **overrides):
    return _ctx("create team", api_client.create_team(
        division_id, create_team_payload(**overrides), ADMIN))


def make_team_eligible(division_id, **team_overrides):
    """Create a team and walk it ENTERED -> ROSTER_SUBMITTED -> ELIGIBLE."""
    team = create_team(division_id, **team_overrides)
    _ctx("submit roster", api_client.submit_roster(
        team["id"], {"roster_player_count": 12}, make_teamrep_headers(team["id"])))
    return _ctx("verify eligibility", api_client.verify_eligibility(team["id"], ADMIN))


def create_active_official(event_id, vet=True, **overrides):
    official = _ctx("create official", api_client.create_official(
        event_id, create_official_payload(**overrides), ADMIN))
    _ctx("vet official", api_client.transition_official(official["id"], {"action": "VET"}, ADMIN))
    return _ctx("activate official", api_client.transition_official(
        official["id"], {"action": "ACTIVATE"}, ADMIN))


def create_active_volunteer(event_id, **overrides):
    vol = _ctx("create volunteer", api_client.create_volunteer(
        event_id, create_volunteer_payload(**overrides), ADMIN))
    _ctx("clear background check", api_client.patch_volunteer(
        vol["id"], {"background_check_cleared": True}, ADMIN))
    _ctx("approve volunteer", api_client.transition_volunteer(vol["id"], {"action": "APPROVE"}, ADMIN))
    return _ctx("activate volunteer", api_client.transition_volunteer(
        vol["id"], {"action": "ACTIVATE"}, ADMIN))


def create_shift(event_id, **overrides):
    return _ctx("create shift", api_client.create_shift(
        event_id, create_shift_payload(**overrides), ADMIN))


def list_division_matches(division_id):
    """All matches of a division ordered round ASC, slot ASC (its list sort)."""
    matches = []
    offset = 0
    while True:
        resp = api_client.list_division_matches(division_id, ANY, params={"limit": 100, "offset": offset})
        if resp.status_code >= 400:
            raise AssertionError(f"Setup failed listing division matches: {resp.text[:300]}")
        body = resp.json()
        matches.extend(body["data"])
        if not body["meta"]["has_more"]:
            return matches
        offset += len(body["data"])


# ---------------------------------------------------------------------------
# Composite: event lifecycle states
# ---------------------------------------------------------------------------

def setup_event_in_registration_open(division_overrides=None, with_venue=True, with_block=True):
    """Awarded event with venue/block contracted, posture REGISTRATION_OPEN.

    Returns dict with event, bid, venue, field, block, division."""
    ev = create_event()
    bid = award_event_bid(ev["id"])
    venue = field = block = None
    if with_venue:
        venue, field = create_contracted_venue(ev["id"])
    if with_block:
        block = create_hotel_block(ev["id"], contracted=True)
    advance_posture(ev["id"], "PLANNING")
    div = create_division(ev["id"], **(division_overrides or {}))
    advance_posture(ev["id"], "REGISTRATION_OPEN")
    return {"event": get_event(ev["id"]), "bid": bid, "venue": venue,
            "field": field, "block": block, "division": div}


def _lock_and_publish(ctx, team_ratings, lock_before_competition_setup=True):
    """Fill the division with ELIGIBLE teams, lock seeding, advance posture,
    publish the bracket. Returns (division, [team ids in creation order])."""
    ev_id = ctx["event"]["id"]
    div = ctx["division"]
    team_ids = []
    for i, rating in enumerate(team_ratings):
        t = make_team_eligible(
            div["id"],
            name=f"Team{i + 1}",
            contact_email=f"team{i + 1}@x.com",
            strength_rating=rating,
        )
        team_ids.append(t["id"])
    _ctx("lock seeding", api_client.lock_seeding(div["id"], ADMIN))
    advance_posture(ev_id, "COMPETITION_SETUP")
    _ctx("publish bracket", api_client.publish_bracket(div["id"], ADMIN))
    return get_division(div["id"]), team_ids


def get_division(division_id):
    return _ctx("get division", api_client.get_division(division_id, ANY))


def setup_published_bracket(team_ratings=(90, 70), division_overrides=None,
                            advance_to_live=False):
    """Event through bracket publication.

    Returns dict(event, bid, venue, field, block, division, team_ids, matches).
    `matches` are ordered round ASC, bracket_slot ASC."""
    ctx = setup_event_in_registration_open(division_overrides=division_overrides)
    div, team_ids = _lock_and_publish(ctx, list(team_ratings))
    ctx["division"] = div
    ctx["team_ids"] = team_ids
    if advance_to_live:
        advance_posture(ctx["event"]["id"], "LIVE")
        ctx["event"] = get_event(ctx["event"]["id"])
    ctx["matches"] = list_division_matches(div["id"])
    return ctx


def setup_completed_event(team_ratings=(90, 70), division_overrides=None,
                          sponsor_contributions_cents=0, with_settlement=False):
    """Full happy path: played final (home wins 3-1), posture COMPLETED,
    hotel block reconciled.

    Returns dict(event, bid, venue, field, block, division, team_ids, matches,
    final_match) and optionally `settlement` when with_settlement=True."""
    ctx = setup_published_bracket(team_ratings=team_ratings,
                                  division_overrides=division_overrides,
                                  advance_to_live=True)
    final = ctx["matches"][-1]  # highest round = the final (single match here)
    _ctx("schedule final", api_client.schedule_match(
        final["id"], {"field_id": ctx["field"]["id"],
                      "scheduled_start": "2026-10-10T14:00:00Z"}, ADMIN))
    _ctx("start final", api_client.start_match(final["id"], ADMIN))
    final = _ctx("finalize final", api_client.finalize_match(
        final["id"], {"home_score": 3, "away_score": 1}, ADMIN))
    ctx["final_match"] = final
    advance_posture(ctx["event"]["id"], "COMPLETED")
    ctx["event"] = get_event(ctx["event"]["id"])
    ctx["block"] = reconcile_block(ctx["block"]["id"])
    if with_settlement:
        settlement = _ctx("create settlement", api_client.create_settlement(
            ctx["event"]["id"],
            create_settlement_payload(sponsor_contributions_cents=sponsor_contributions_cents),
            ADMIN))
        ctx["settlement"] = settlement
    return ctx


def setup_accepted_impact_report(ctx, projected_attendance=400, actual_attendance=350,
                                 creator_user_id="ops-admin-1", auditor_user_id="cvb-7"):
    """On a COMPLETED event: create + submit + audit + ACCEPT an impact report.

    Returns the ACCEPTED report."""
    ev_id = ctx["event"]["id"]
    report = _ctx("create impact report", api_client.create_impact_report(
        ev_id, create_impact_report_payload(projected_attendance=projected_attendance),
        dict(ADMIN, **{"X-User-ID": creator_user_id})))
    _ctx("submit impact report", api_client.submit_impact_report(report["id"], ADMIN))
    _ctx("audit impact report", api_client.audit_impact_report(
        report["id"], {"actual_attendance": actual_attendance},
        dict(CVB, **{"X-User-ID": auditor_user_id})))
    return _ctx("accept impact report", api_client.audit_decision(
        report["id"], {"decision": "ACCEPTED"}, dict(CVB, **{"X-User-ID": auditor_user_id})))


def setup_approved_settlement(certifier_user_id="ops-admin-1",
                              approver_user_id="ops-admin-2",
                              sponsor_contributions_cents=0):
    """COMPLETED event, reconciled block, ACCEPTED impact report, and a
    settlement certified by one admin and approved by another (SoD-clean).

    Returns dict(...) with `settlement` and `report`."""
    ctx = setup_completed_event(with_settlement=True,
                                sponsor_contributions_cents=sponsor_contributions_cents)
    report = setup_accepted_impact_report(ctx)
    settlement = _ctx("certify settlement", api_client.certify_settlement(
        ctx["settlement"]["id"], dict(ADMIN, **{"X-User-ID": certifier_user_id})))
    settlement = _ctx("approve settlement", api_client.approve_settlement(
        settlement["id"], dict(ADMIN2, **{"X-User-ID": approver_user_id})))
    ctx["settlement"] = settlement
    ctx["report"] = report
    return ctx


def propose_and_accept_assignment(match_id, official_id, slot_role="CREW_CHIEF"):
    """PROPOSED assignment accepted by the official themselves. Returns it."""
    assignment = _ctx("create assignment", api_client.create_assignment(
        match_id, create_assignment_payload(official_id, slot_role=slot_role), ADMIN))
    return _ctx("accept assignment", api_client.respond_assignment(
        assignment["id"], {"response": "ACCEPTED"}, make_official_headers(official_id)))


def setup_match_in_reschedule_queue(advance_to_live=True):
    """LIVE event; the final SCHEDULED 2026-10-10T14:00; a venue-scoped weather
    alert activated and resolved so the match sits in RESCHEDULE_QUEUE.

    Returns dict with ctx fields plus `alert` and `match` (queued)."""
    ctx = setup_published_bracket(team_ratings=(90, 70), advance_to_live=advance_to_live)
    match = ctx["matches"][-1]
    match = _ctx("schedule match", api_client.schedule_match(
        match["id"], {"field_id": ctx["field"]["id"],
                      "scheduled_start": "2026-10-10T14:00:00Z"}, ADMIN))
    alert = _ctx("create weather alert", api_client.create_weather_alert(
        ctx["event"]["id"],
        create_weather_alert_payload(venue_id=ctx["venue"]["id"]), ADMIN))
    _ctx("activate alert", api_client.activate_alert(alert["id"], ADMIN))
    _ctx("resolve alert", api_client.resolve_alert(alert["id"], ADMIN))
    match = _ctx("get queued match", api_client.get_match(match["id"], ANY))
    ctx["alert"] = alert
    ctx["match"] = match
    return ctx
