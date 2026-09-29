"""Jury panels, seats and recusals; protests, hearings, decisions and reopenings."""
from datetime import timedelta

from flask import Blueprint

import calc
import services
import store
from errors import fail
from pipeline import Ctx, F, list_read, must, no_body, ok_row, soft, validate
from util import fmt_dt, parse_dt

bp = Blueprint("jury", __name__)

READ_ROLES = ["ClubAdmin", "RegattaChair", "Measurer", "RaceOfficer", "JuryChair", "Competitor"]
PANEL_READ_ROLES = ["ClubAdmin", "RegattaChair", "RaceOfficer", "JuryChair", "Competitor"]

QUALIFIED_LEVELS = ("REGIONAL", "NATIONAL", "INTERNATIONAL")
EVIDENCE_KINDS = ("WRITTEN_STATEMENT", "WITNESS", "GPS_TRACK", "PHOTO")
DECISIONS = ("PENALTY_DSQ", "PENALTY_SCORING_20", "DISMISSED", "REDRESS_GRANTED")


def _non_recused(panel):
    return len([s for s in panel.get("seats") or [] if not s.get("recused")])


# --------------------------------------------------------------------------
# JuryPanel
# --------------------------------------------------------------------------


@bp.post("/regatta-ops/jury-panels")
def panel_create():
    ctx = Ctx(["RegattaChair"])
    data = validate(ctx, [F("regatta_id", "string"), F("chair_member_id", "string")])
    regatta = must("regattas", data["regatta_id"])
    chair = must("club_members", data["chair_member_id"])
    # step 21
    if services.member_racing_conflict(regatta["id"], chair["id"]):
        fail("ERR_JURY_CONFLICT_OF_INTEREST", "the nominated chair takes part in the racing")
    # step 39
    if chair.get("judge_certification_level") not in QUALIFIED_LEVELS:
        fail("ERR_JURY_QUORUM_NOT_MET", "the nominated chair is not sufficiently certified")
    row = store.insert(
        "jury_panels",
        {
            "regatta_id": regatta["id"],
            "chair_member_id": chair["id"],
            "seats": [
                {
                    "member_id": chair["id"],
                    "seat_role": "CHAIR",
                    "recused": False,
                    "seated_utc": fmt_dt(store.now()),
                }
            ],
            "seated_member_count": 1,
            "status": "FORMING",
        },
    )
    return ok_row(row, 201)


@bp.post("/regatta-ops/jury-panels/<rid>/seats")
def panel_seat(rid):
    ctx = Ctx(["RegattaChair"])
    data = validate(ctx, [F("member_id", "string")])
    panel = must("jury_panels", rid)
    member = must("club_members", data["member_id"])
    regatta = store.get("regattas", panel["regatta_id"])
    # step 21
    if services.member_racing_conflict(panel["regatta_id"], member["id"]):
        fail("ERR_JURY_CONFLICT_OF_INTEREST", "the nominated judge takes part in the racing")
    # step 32: one non-recused seat per member per panel
    for seat in panel.get("seats") or []:
        if seat.get("member_id") == member["id"] and not seat.get("recused"):
            fail("ERR_DUPLICATE_RECORD", "the member already holds a seat on this panel")
    panel["seats"].append(
        {
            "member_id": member["id"],
            "seat_role": "MEMBER",
            "recused": False,
            "seated_utc": fmt_dt(store.now()),
        }
    )
    count = _non_recused(panel)
    panel["seated_member_count"] = count
    # bubble-up: quorum reached
    if count >= int(regatta["jury_quorum_required"]):
        panel["status"] = "SEATED"
    store.touch(panel)
    return ok_row(panel)


@bp.post("/regatta-ops/jury-panels/<rid>/recuse")
def panel_recuse(rid):
    ctx = Ctx(["JuryChair"])
    # step 5: only the chair of this very panel may recuse a judge
    probe = soft("jury_panels", rid)
    if probe is not None and probe.get("chair_member_id") != ctx.user_id:
        fail("ERR_NOT_ACTING_PARTY", "only the chair of this panel may recuse a judge")
    data = validate(ctx, [F("member_id", "string")])
    panel = must("jury_panels", rid)
    member = must("club_members", data["member_id"])
    regatta = store.get("regattas", panel["regatta_id"])
    # step 11
    if panel["status"] != "SEATED":
        fail("ERR_INVALID_STATE", "a judge is recused only from a SEATED panel")
    seat = None
    for element in panel.get("seats") or []:
        if element.get("member_id") == member["id"]:
            seat = element
            break
    if seat is None:
        fail("ERR_RESOURCE_NOT_FOUND", "the member holds no seat on this panel")
    if seat.get("recused"):
        fail("ERR_INVALID_STATE", "the seat is already recused")
    # hop 1
    seat["recused"] = True
    count = _non_recused(panel)
    panel["seated_member_count"] = count
    # hop 2
    lost_quorum = count < int(regatta["jury_quorum_required"])
    if lost_quorum:
        panel["status"] = "FORMING"
    store.touch(panel)
    # hop 3: only a panel that fell under quorum releases its scheduled hearings
    if lost_quorum:
        for protest in store.find("protests", jury_panel_id=panel["id"]):
            if protest.get("status") != "HEARING_SCHEDULED":
                continue
            store.apply_changes(
                protest, {"status": "FILED", "jury_panel_id": None, "hearing_utc": None}
            )
    return ok_row(panel)


@bp.get("/regatta-ops/jury-panels/<rid>")
def panel_read(rid):
    Ctx(PANEL_READ_ROLES)
    return ok_row(must("jury_panels", rid))


@bp.get("/regatta-ops/jury-panels")
def panel_list():
    Ctx(PANEL_READ_ROLES)
    return list_read("jury_panels", ["regatta_id", "chair_member_id", "status"])


# --------------------------------------------------------------------------
# Protest
# --------------------------------------------------------------------------


def _require_bound_chair(ctx, rid):
    """Step 5 for every jury-chair protest action: identity vs the bound panel."""
    protest = soft("protests", rid)
    if protest is None:
        return
    panel = store.get("jury_panels", protest.get("jury_panel_id"))
    if panel is not None and panel.get("chair_member_id") != ctx.user_id:
        fail("ERR_NOT_ACTING_PARTY", "only the chair of the bound panel may act on this protest")


@bp.post("/regatta-ops/protests")
def protest_create():
    ctx = Ctx(["Competitor", "RaceOfficer"])
    # step 5: a competitor files only for the entry it helms
    if ctx.role == "Competitor":
        probe = soft("entries", ctx.raw_value("protestor_entry_id"))
        if probe is not None and probe.get("helm_member_id") != ctx.user_id:
            fail("ERR_NOT_ACTING_PARTY", "a competitor files only for the entry it helms")
    data = validate(
        ctx,
        [
            F("race_id", "string"),
            F("protestor_entry_id", "string"),
            F("protestee_entry_id", "string"),
            F("rule_cited", "string", nonblank=True),
            F("incident_utc", "datetime"),
        ],
    )
    race = must("races", data["race_id"])
    protestor = must("entries", data["protestor_entry_id"])
    protestee = must("entries", data["protestee_entry_id"])
    # step 17: outranks the window deadline
    for party in (protestor, protestee):
        if party.get("registration_status") == "WITHDRAWN":
            fail("ERR_ENTRY_WITHDRAWN", "a party to the protest has withdrawn")
    # step 23
    for party in (protestor, protestee):
        if party["regatta_id"] != race["regatta_id"]:
            fail("ERR_CROSS_REGATTA_REFERENCE", "a party does not sail this regatta")
    regatta = store.get("regattas", race["regatta_id"])
    # step 36
    closed = store.D(race, "results_closed_utc")
    if closed is None:
        fail("ERR_PROTEST_WINDOW_NOT_OPEN", "the protested race has no recorded result yet")
    # step 37: the exact limit instant still counts as inside
    limit = closed + timedelta(minutes=int(regatta["protest_time_limit_minutes"]))
    if store.now() > limit:
        fail("ERR_PROTEST_WINDOW_CLOSED", "the protest time limit has expired")
    # step 38
    if protestor["id"] == protestee["id"]:
        fail("ERR_PROTEST_PARTIES_INVALID", "the two parties must differ")
    started = store.D(race, "actual_start_utc")
    incident = parse_dt(data["incident_utc"])
    if started is None or incident < started or incident > closed:
        fail("ERR_PROTEST_PARTIES_INVALID", "incident_utc is outside the sailing interval")
    row = store.insert(
        "protests",
        {
            "regatta_id": race["regatta_id"],
            "race_id": race["id"],
            "protestor_entry_id": protestor["id"],
            "protestee_entry_id": protestee["id"],
            "rule_cited": data["rule_cited"],
            "incident_utc": data["incident_utc"],
            "filed_utc": fmt_dt(store.now()),
            "status": "FILED",
            "jury_panel_id": None,
            "hearing_utc": None,
            "decision": "NONE",
            "penalty_target_entry_id": None,
            "redress_race_number": None,
            "evidence_log": [],
            "evidence_count": 0,
            "invalid_reason_code": None,
            "reopen_count": 0,
        },
    )
    return ok_row(row, 201)


@bp.post("/regatta-ops/protests/<rid>/evidence")
def protest_evidence(rid):
    ctx = Ctx(["Competitor", "JuryChair"])
    # step 5
    if ctx.role == "Competitor":
        probe = soft("entries", ctx.raw_value("submitted_by_entry_id"))
        if probe is not None and probe.get("helm_member_id") != ctx.user_id:
            fail("ERR_NOT_ACTING_PARTY", "a competitor files evidence only for the entry it helms")
    else:
        _require_bound_chair(ctx, rid)
    data = validate(
        ctx,
        [
            F("kind", "enum", enum=EVIDENCE_KINDS),
            F("summary", "string", nonblank=True),
            F("submitted_by_entry_id", "string"),
        ],
    )
    protest = must("protests", rid)
    entry = must("entries", data["submitted_by_entry_id"])
    # step 17
    if entry.get("registration_status") == "WITHDRAWN":
        fail("ERR_ENTRY_WITHDRAWN", "the submitting entry has withdrawn")
    protest["evidence_log"].append(
        {
            "kind": data["kind"],
            "summary": data["summary"],
            "submitted_by_entry_id": entry["id"],
            "recorded_utc": fmt_dt(store.now()),
        }
    )
    protest["evidence_count"] = len(protest["evidence_log"])
    store.touch(protest)
    return ok_row(protest)


@bp.post("/regatta-ops/protests/<rid>/schedule-hearing")
def protest_schedule(rid):
    ctx = Ctx(["JuryChair"])
    # step 5: identity is compared to the panel named in the payload
    probe = soft("jury_panels", ctx.raw_value("jury_panel_id"))
    if probe is not None and probe.get("chair_member_id") != ctx.user_id:
        fail("ERR_NOT_ACTING_PARTY", "only the chair of the named panel may schedule the hearing")
    data = validate(ctx, [F("jury_panel_id", "string"), F("hearing_utc", "datetime")])
    protest = must("protests", rid)
    panel = must("jury_panels", data["jury_panel_id"])
    regatta = store.get("regattas", protest["regatta_id"])
    # step 11
    if protest["status"] not in ("FILED", "REOPENED"):
        fail("ERR_INVALID_STATE", "a hearing is scheduled only from FILED or REOPENED")
    # step 21
    if services.hearing_conflict(panel, protest):
        fail("ERR_JURY_CONFLICT_OF_INTEREST", "a member of the panel is connected to the parties")
    # step 23
    if panel["regatta_id"] != protest["regatta_id"]:
        fail("ERR_CROSS_REGATTA_REFERENCE", "the panel serves another regatta")
    # step 39
    if panel["status"] != "SEATED" or int(panel["seated_member_count"]) < int(
        regatta["jury_quorum_required"]
    ):
        fail("ERR_JURY_QUORUM_NOT_MET", "the panel is not seated to quorum")
    # step 51
    if not parse_dt(data["hearing_utc"]) > store.now():
        fail("ERR_HEARING_TIME_INVALID", "hearing_utc must be later than the clock")
    store.apply_changes(
        protest,
        {
            "status": "HEARING_SCHEDULED",
            "jury_panel_id": panel["id"],
            "hearing_utc": data["hearing_utc"],
        },
    )
    return ok_row(protest)


@bp.post("/regatta-ops/protests/<rid>/hear")
def protest_hear(rid):
    ctx = Ctx(["JuryChair"])
    _require_bound_chair(ctx, rid)
    no_body(ctx)
    protest = must("protests", rid)
    # step 11
    if protest["status"] != "HEARING_SCHEDULED":
        fail("ERR_INVALID_STATE", "the hearing is held only from HEARING_SCHEDULED")
    # step 16
    if store.now() < store.D(protest, "hearing_utc"):
        fail("ERR_HEARING_NOT_DUE", "the hearing time has not arrived")
    # step 40
    if int(protest["evidence_count"]) < 1:
        fail("ERR_EVIDENCE_REQUIRED", "the protest carries no evidence")
    store.apply_changes(protest, {"status": "HEARD"})
    return ok_row(protest)


def _result_of(race, entry_id):
    for result in store.find("race_results", race_id=race["id"], entry_id=entry_id):
        return result
    return None


def _rescore(race, entry):
    """Hops 3 and 4 of a decision or a reopening, in that fixed order."""
    calc.race_points_and_places(race)
    store.apply_changes(race, {"rescore_count": int(race["rescore_count"]) + 1})
    regatta = store.get("regattas", race["regatta_id"])
    division = store.get("divisions", entry.get("division_id")) if entry is not None else None
    services.refresh_series(regatta, division)


@bp.post("/regatta-ops/protests/<rid>/decide")
def protest_decide(rid):
    ctx = Ctx(["JuryChair"])
    _require_bound_chair(ctx, rid)
    data = validate(
        ctx,
        [
            F("decision", "enum", enum=DECISIONS),
            F("penalty_target_entry_id", "string", required=False),
            F("redress_race_number", "integer", required=False),
        ],
    )
    protest = must("protests", rid)
    target = None
    if data["penalty_target_entry_id"] is not None:
        target = must("entries", data["penalty_target_entry_id"])
    # step 11
    if protest["status"] != "HEARD":
        fail("ERR_INVALID_STATE", "a decision is recorded only from HEARD")
    protested_race = store.get("races", protest["race_id"])
    if protested_race.get("scoring_status") != "FINAL":
        fail("ERR_INVALID_STATE", "the protested race has not been scored FINAL")
    regatta = store.get("regattas", protest["regatta_id"])
    decision = data["decision"]
    # step 42
    if decision != "DISMISSED":
        if target is None:
            fail("ERR_DECISION_PAYLOAD_INVALID", "penalty_target_entry_id is required")
        if target["id"] not in (protest["protestor_entry_id"], protest["protestee_entry_id"]):
            fail("ERR_DECISION_PAYLOAD_INVALID", "the target is not a party to this protest")
    redress_race = None
    if decision == "REDRESS_GRANTED":
        if data["redress_race_number"] is None:
            fail("ERR_DECISION_PAYLOAD_INVALID", "redress_race_number is required for redress")
        for race in store.find("races", regatta_id=regatta["id"]):
            if int(race["race_number"]) == int(data["redress_race_number"]):
                redress_race = race
                break
        if (
            redress_race is None
            or redress_race.get("scoring_status") != "FINAL"
            or redress_race.get("start_status") == "ABANDONED"
        ):
            fail("ERR_DECISION_PAYLOAD_INVALID", "redress_race_number names no FINAL race")
    elif data["redress_race_number"] is not None:
        fail("ERR_DECISION_PAYLOAD_INVALID", "redress_race_number is forbidden for this decision")
    # step 43: the average is fixed here and never recomputed after the re-score
    redress_points = None
    if decision == "REDRESS_GRANTED":
        redress_points = calc.redress_points_average(regatta, target, redress_race)
        if redress_points is None:
            fail("ERR_REDRESS_NOT_COMPUTABLE", "the target entry has no source result to average")
    # hop 1
    changes = {
        "status": "DECIDED",
        "decision": decision,
        "penalty_target_entry_id": None if target is None else target["id"],
    }
    if decision == "REDRESS_GRANTED":
        changes["redress_race_number"] = data["redress_race_number"]
    store.apply_changes(protest, changes)
    # hop 2
    affected_race = redress_race if decision == "REDRESS_GRANTED" else protested_race
    result = None if target is None else _result_of(affected_race, target["id"])
    if decision != "DISMISSED" and result is not None:
        protest["_pre_decision"] = {
            "result_id": result["id"],
            "race_id": affected_race["id"],
            "finish_status": result["finish_status"],
            "elapsed_seconds": result["elapsed_seconds"],
            "penalty_percent": result["penalty_percent"],
            "discardable": result["discardable"],
        }
        if decision == "PENALTY_DSQ":
            store.apply_changes(
                result,
                {
                    "finish_status": "DSQ",
                    "elapsed_seconds": None,
                    "corrected_seconds": None,
                    "discardable": False,
                },
            )
        elif decision == "PENALTY_SCORING_20":
            store.apply_changes(result, {"penalty_percent": 20})
        else:
            store.apply_changes(
                result,
                {
                    "finish_status": "RDG",
                    "points": redress_points,
                    "place": None,
                    "corrected_seconds": None,
                    "discardable": True,
                },
            )
        # hops 3 and 4
        _rescore(affected_race, target)
    services.maybe_score_regatta(regatta)
    return ok_row(protest)


@bp.post("/regatta-ops/protests/<rid>/reopen")
def protest_reopen(rid):
    ctx = Ctx(["JuryChair"])
    _require_bound_chair(ctx, rid)
    no_body(ctx)
    protest = must("protests", rid)
    # step 11
    if protest["status"] != "DECIDED":
        fail("ERR_INVALID_STATE", "only a DECIDED protest may be reopened")
    # step 41
    if int(protest["reopen_count"]) != 0:
        fail("ERR_REOPEN_LIMIT_REACHED", "this protest has already been reopened once")
    snapshot = protest.get("_pre_decision")
    # hop 1
    store.apply_changes(
        protest,
        {"status": "REOPENED", "reopen_count": 1, "decision": "NONE", "hearing_utc": None},
    )
    if snapshot is not None:
        result = store.get("race_results", snapshot["result_id"])
        race = store.get("races", snapshot["race_id"])
        if result is not None:
            # hop 2: back to the finish_status the result carried before the decision
            store.apply_changes(
                result,
                {
                    "finish_status": snapshot["finish_status"],
                    "elapsed_seconds": snapshot["elapsed_seconds"],
                    "penalty_percent": 0,
                    "discardable": True,
                },
            )
            # hop 3: no drift, every series_points_gross returns to its pre-decision value
            _rescore(race, store.get("entries", result["entry_id"]))
        protest["_pre_decision"] = None
    return ok_row(protest)


@bp.post("/regatta-ops/protests/<rid>/invalidate")
def protest_invalidate(rid):
    ctx = Ctx(["JuryChair"])
    _require_bound_chair(ctx, rid)
    data = validate(ctx, [F("reason_code", "string", nonblank=True)])
    protest = must("protests", rid)
    # step 11
    if protest["status"] not in ("FILED", "REOPENED"):
        fail("ERR_INVALID_STATE", "a protest is invalidated only from FILED or REOPENED")
    store.apply_changes(
        protest, {"status": "INVALID", "invalid_reason_code": data["reason_code"]}
    )
    services.maybe_score_regatta(store.get("regattas", protest["regatta_id"]))
    return ok_row(protest)


@bp.get("/regatta-ops/protests/<rid>")
def protest_read(rid):
    Ctx(READ_ROLES)
    return ok_row(must("protests", rid))


@bp.get("/regatta-ops/protests")
def protest_list():
    Ctx(READ_ROLES)
    return list_read(
        "protests",
        [
            "regatta_id",
            "race_id",
            "protestor_entry_id",
            "protestee_entry_id",
            "jury_panel_id",
            "penalty_target_entry_id",
            "status",
        ],
    )
