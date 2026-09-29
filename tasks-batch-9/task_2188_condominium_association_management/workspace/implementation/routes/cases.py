"""Rules enforcement: notices, cures, hearing dockets, fine tiers and appeals."""
from datetime import timedelta

from flask import g, request

import clock
import db
import response
import serialize
import validation as V
from auth import authenticate
from errors import ApiError
from services import assessment, certificate, ledger

CASE_STATUSES = ("OPEN", "NOTICE_SENT", "HEARING_SCHEDULED", "FINE_ASSESSED",
                 "APPEALED", "FINE_UPHELD", "FINE_VACATED", "DISMISSED", "CURED")
TERMINAL_STATUSES = ("CURED", "DISMISSED", "FINE_UPHELD", "FINE_VACATED")
CHAIN_STATUSES = ("FINE_ASSESSED", "FINE_UPHELD", "CURED")
OUTCOMES = ("FINE", "DISMISS", "UPHOLD", "VACATE")
SLOT = timedelta(minutes=30)


def resolve_prior_case(case, assoc):
    """The most recent qualifying earlier case of the same unit and rule_code."""
    window_start = clock.add_days(case["notice_sent_at"],
                                  -assoc["repeat_lookback_days"])
    candidates = []
    for other in db.store["violation_cases"].values():
        if other["id"] == case["id"]:
            continue
        if other["association_id"] != case["association_id"]:
            continue
        if other["unit_id"] != case["unit_id"]:
            continue
        if other["rule_code"] != case["rule_code"]:
            continue
        if other["status"] not in CHAIN_STATUSES:
            continue
        sent = other.get("notice_sent_at")
        if sent is None or sent < window_start or sent > case["notice_sent_at"]:
            continue
        candidates.append(other)
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c["notice_sent_at"], c["created_at"], c["_seq"]),
                    reverse=True)
    return candidates[0]


def fine_tier_selection(case, assoc):
    """The repeat chain walk stops at the FIRST non-qualifying link."""
    window_start = clock.add_days(case["notice_sent_at"],
                                  -assoc["repeat_lookback_days"])
    chain = 0
    cursor = case.get("prior_case_id")
    guard = 0
    while cursor is not None and guard < 1000:
        guard += 1
        prior = db.get("violation_cases", cursor)
        if prior is None:
            break
        sent = prior.get("notice_sent_at")
        if prior["status"] not in CHAIN_STATUSES or sent is None or sent < window_start:
            break
        chain += 1
        cursor = prior.get("prior_case_id")

    tier = 1 if chain == 0 else 2 if chain == 1 else 3
    if tier == 1:
        raw = assoc["fine_tier_1_cents"]
    elif tier == 2:
        raw = assoc["fine_tier_2_cents"]
    else:
        raw = assoc["fine_tier_3_daily_cents"] * case["continuing_days"]
    return tier, min(raw, assoc["fine_cap_cents"])


def vacatur_cascade(case, unit):
    """The four-hop compensation for a vacated fine (Invariant L)."""
    fine = db.get("ledger_entries", case.get("fine_entry_id"))
    if fine is not None and fine["status"] == "POSTED":
        ledger.reverse_entry(unit, fine, memo="Fine vacated on appeal")
    ledger.recompute_unit(unit)
    ledger.recompute_balloting_eligibility(unit["association_id"])
    for cert in db.sorted_rows(
            "resale_certificates",
            lambda c: c["unit_id"] == unit["id"] and c["status"] == "ISSUED"):
        current = certificate.special_assessment_disclosure(unit)
        if current != cert.get("special_assessment_disclosure_cents"):
            certificate.cascade_void(cert, unit)
    for sa in db.store["special_assessments"].values():
        if sa["association_id"] == unit["association_id"]:
            assessment.refresh_money(sa)
    assessment.refresh_restricted_cash(unit["association_id"])


def register(app):

    @app.post("/violation-cases")
    def open_case():
        authenticate(("CommunityManager", "BoardDirector"))
        body = V.body_of()
        association_id = body.get("association_id")
        assoc = db.get("associations", association_id) if association_id else None
        if association_id is not None and assoc is None:
            raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND")
        fk = V.resolve_body_fk(body, "unit_id", "reported_by_owner_id")
        unit = fk["unit_id"]
        reporter = fk["reported_by_owner_id"]
        if assoc is None:
            V.fail("Field 'association_id' is required.")
        if unit is None:
            V.fail("Field 'unit_id' is required.")
        if reporter is None:
            V.fail("Field 'reported_by_owner_id' is required.")
        rule_code = V.require_str(body, "rule_code", min_len=1)
        continuing_days = V.require_int(body, "continuing_days", minimum=1,
                                       required=False, default=1)
        V.scope_match(assoc["id"], unit, reporter)

        row = db.base_fields()
        row.update({
            "association_id": assoc["id"],
            "unit_id": unit["id"],
            "prior_case_id": None,
            "reported_by_owner_id": reporter["id"],
            "decision_owner_id": None,
            "hearing_meeting_id": None,
            "rule_code": rule_code,
            "continuing_days": continuing_days,
            "notice_sent_at": None,
            "cure_deadline_at": None,
            "hearing_slot_start": None,
            "hearing_round": 0,
            "fine_tier": 0,
            "fine_amount_cents": 0,
            "fine_entry_id": None,
            "appeal_deadline_at": None,
            "status": "OPEN",
        })
        db.insert("violation_cases", row)
        return response.created(serialize.view(row))

    @app.get("/violation-cases")
    def list_cases():
        authenticate(("CommunityManager", "BoardDirector", "BoardTreasurer",
                      "UnitOwner", "TitleAgent"))
        limit, offset = V.pagination()
        args = request.args
        status = args.get("status")
        if status is not None and status not in CASE_STATUSES:
            V.fail("Query parameter 'status' is not a recognized case status.")

        def keep(c):
            for name in ("association_id", "unit_id", "prior_case_id",
                         "reported_by_owner_id", "decision_owner_id",
                         "hearing_meeting_id", "fine_entry_id", "rule_code"):
                want = args.get(name)
                if want and c.get(name) != want:
                    return False
            if status and c["status"] != status:
                return False
            return True

        rows = db.sorted_rows("violation_cases", keep)
        page, total = V.paginate(rows, limit, offset)
        return response.listing(serialize.views(page), limit, offset, total)

    @app.post("/violation-cases/<violation_case_id>/send-notice")
    def send_case_notice(violation_case_id):
        authenticate(("CommunityManager",))
        found = V.resolve_path(violation_case_id=violation_case_id)
        case = found["violation_case_id"]
        assoc = db.get("associations", case["association_id"])
        V.body_of()
        # Rung 10.
        if case["status"] in TERMINAL_STATUSES:
            raise ApiError("ERR_CASE_ALREADY_TERMINAL")
        # Rung 12.
        if case["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        unit = db.get("units", case["unit_id"])
        if unit is None:
            raise ApiError("ERR_UNIT_NOT_FOUND")
        V.scope_match(case["association_id"], unit)

        now = clock.now()
        case["notice_sent_at"] = now
        case["cure_deadline_at"] = clock.add_days(now, assoc["cure_period_days"])
        prior = resolve_prior_case(case, assoc)
        case["prior_case_id"] = prior["id"] if prior else None
        case["status"] = "NOTICE_SENT"
        db.touch(case)
        return response.ok(serialize.view(case))

    @app.post("/violation-cases/<violation_case_id>/mark-cured")
    def mark_case_cured(violation_case_id):
        authenticate(("CommunityManager",))
        found = V.resolve_path(violation_case_id=violation_case_id)
        case = found["violation_case_id"]
        V.body_of()
        # Rung 10.
        if case["status"] in TERMINAL_STATUSES:
            raise ApiError("ERR_CASE_ALREADY_TERMINAL")
        # Rung 12.
        if case["status"] != "NOTICE_SENT":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        # Rung 26 -- the deadline instant itself still cures.
        if clock.now() > case["cure_deadline_at"]:
            raise ApiError("ERR_CURE_PERIOD_ACTIVE")
        case["status"] = "CURED"
        db.touch(case)
        return response.ok(serialize.view(case))

    @app.post("/violation-cases/<violation_case_id>/schedule-hearing")
    def schedule_hearing(violation_case_id):
        authenticate(("BoardDirector",))
        found = V.resolve_path(violation_case_id=violation_case_id)
        case = found["violation_case_id"]
        assoc = db.get("associations", case["association_id"])
        body = V.body_of()
        fk = V.resolve_body_fk(body, "meeting_id")
        meeting = None
        meeting_id = body.get("hearing_meeting_id")
        if meeting_id is not None:
            meeting = db.get("board_meetings", meeting_id)
            if meeting is None:
                raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND")
        elif fk["meeting_id"] is not None:
            meeting = fk["meeting_id"]
        slot_start = V.require_dt(body, "hearing_slot_start")
        if meeting is None:
            V.fail("Field 'hearing_meeting_id' is required.")
        V.scope_match(case["association_id"], meeting)
        # Rung 11 -- kept ahead of the generic terminal check so the specific code
        # for an already-cured case stays reachable.
        if case["status"] == "CURED":
            raise ApiError("ERR_CASE_ALREADY_CURED")
        # Rung 10.
        if case["status"] in TERMINAL_STATUSES:
            raise ApiError("ERR_CASE_ALREADY_TERMINAL")
        # Rung 12.
        if case["status"] not in ("NOTICE_SENT", "APPEALED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if meeting["status"] not in ("SCHEDULED", "NOTICED"):
            raise ApiError("ERR_INVALID_MEETING_STATE")
        round_one = case["status"] == "NOTICE_SENT"
        # Rung 26 -- the cure deadline instant still belongs to the owner.
        if round_one and case["cure_deadline_at"] is not None:
            if clock.now() <= case["cure_deadline_at"]:
                raise ApiError("ERR_CURE_PERIOD_ACTIVE")
        # Rung 30 -- half-open 30-minute slots; touching endpoints do NOT collide.
        slot_end = slot_start + SLOT
        for other in db.store["violation_cases"].values():
            if other["id"] == case["id"]:
                continue
            if other.get("hearing_meeting_id") != meeting["id"]:
                continue
            other_start = other.get("hearing_slot_start")
            if other_start is None:
                continue
            if other_start < slot_end and slot_start < other_start + SLOT:
                raise ApiError("ERR_HEARING_SLOT_TAKEN")
        # Rung 31.
        if meeting["hearing_slot_count"] >= assoc["hearing_docket_capacity"]:
            raise ApiError("ERR_HEARING_DOCKET_FULL")
        # Rung 32 -- at most one other case for the same unit on one docket.
        same_unit = sum(
            1 for other in db.store["violation_cases"].values()
            if other["id"] != case["id"]
            and other.get("hearing_meeting_id") == meeting["id"]
            and other["unit_id"] == case["unit_id"])
        if same_unit >= 2:
            raise ApiError("ERR_UNIT_DOCKET_LIMIT")
        # Rung 33.
        if "HEARING" not in (meeting["agenda_kinds"] or []):
            raise ApiError("ERR_AGENDA_KIND_MISSING")
        # Rung 34 -- no board may rehear an appeal in the session it first decided.
        if not round_one and case.get("hearing_meeting_id") == meeting["id"]:
            raise ApiError("ERR_SAME_MEETING_REHEARING")
        # Rung 54 -- a 30-minute boundary, wholly inside [start, end).
        if (slot_start.minute % 30 or slot_start.second or slot_start.microsecond
                or slot_start < meeting["scheduled_start"]
                or slot_end > meeting["scheduled_end"]):
            raise ApiError("ERR_SLOT_OUTSIDE_MEETING")

        case["hearing_meeting_id"] = meeting["id"]
        case["hearing_slot_start"] = slot_start
        if round_one:
            case["hearing_round"] = 1
        else:
            case["hearing_round"] += 1
        case["status"] = "HEARING_SCHEDULED"
        meeting["hearing_slot_count"] += 1
        db.touch(meeting)
        db.touch(case)
        return response.ok(serialize.view(case))

    @app.post("/violation-cases/<violation_case_id>/hearing-decision")
    def hearing_decision(violation_case_id):
        authenticate(("BoardDirector",))
        found = V.resolve_path(violation_case_id=violation_case_id)
        case = found["violation_case_id"]
        assoc = db.get("associations", case["association_id"])
        body = V.body_of()
        outcome = V.require_enum(body, "outcome", OUTCOMES)
        # Rung 10.
        if case["status"] in TERMINAL_STATUSES:
            raise ApiError("ERR_CASE_ALREADY_TERMINAL")
        # Rung 12.
        if case["status"] != "HEARING_SCHEDULED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        round_one = case["hearing_round"] == 1
        if outcome in ("FINE", "DISMISS") and not round_one:
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if outcome in ("UPHOLD", "VACATE") and case["hearing_round"] < 2:
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        meeting = db.get("board_meetings", case.get("hearing_meeting_id"))
        # Rung 13.
        if meeting is None or meeting["status"] != "IN_SESSION":
            raise ApiError("ERR_MEETING_NOT_IN_SESSION")
        # Rung 14.
        if not meeting["quorum_met"]:
            raise ApiError("ERR_BOARD_QUORUM_NOT_MET")
        # Rung 15.
        actor_id = g.get("user_id")
        if actor_id == case["reported_by_owner_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        if outcome in ("UPHOLD", "VACATE") and actor_id == case.get("decision_owner_id"):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

        unit = db.get("units", case["unit_id"])
        if outcome == "FINE":
            tier, amount = fine_tier_selection(case, assoc)
            case["fine_tier"] = tier
            case["fine_amount_cents"] = amount
            entry = ledger.post_entry(
                unit, "FINE", amount, _period(clock.now()),
                due_on=clock.add_days(clock.now(), 30), source_case_id=case["id"])
            case["fine_entry_id"] = entry["id"]
            ledger.recompute_unit(unit)
            case["decision_owner_id"] = actor_id
            case["appeal_deadline_at"] = clock.add_days(clock.now(),
                                                        assoc["appeal_window_days"])
            case["status"] = "FINE_ASSESSED"
        elif outcome == "DISMISS":
            case["decision_owner_id"] = actor_id
            case["status"] = "DISMISSED"
        elif outcome == "UPHOLD":
            case["status"] = "FINE_UPHELD"
        else:
            case["status"] = "FINE_VACATED"
            vacatur_cascade(case, unit)
        db.touch(case)
        return response.ok(serialize.view(case))

    @app.post("/violation-cases/<violation_case_id>/appeal")
    def appeal_case(violation_case_id):
        authenticate(("UnitOwner",))
        found = V.resolve_path(violation_case_id=violation_case_id)
        case = found["violation_case_id"]
        body = V.body_of()
        V.require_str(body, "grounds", required=False, default=None)
        unit = db.get("units", case["unit_id"])
        # Rung 7.
        if unit is not None:
            V.owner_scope(unit)
        # Rung 10.
        if case["status"] in TERMINAL_STATUSES:
            raise ApiError("ERR_CASE_ALREADY_TERMINAL")
        # Rung 12.
        if case["status"] != "FINE_ASSESSED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        # Rung 27 -- the deadline instant itself still admits the appeal.
        if case["appeal_deadline_at"] is not None:
            if clock.now() > case["appeal_deadline_at"]:
                raise ApiError("ERR_APPEAL_WINDOW_CLOSED")

        meeting = db.get("board_meetings", case.get("hearing_meeting_id"))
        if meeting is not None:
            meeting["hearing_slot_count"] = max(0, meeting["hearing_slot_count"] - 1)
            db.touch(meeting)
        case["hearing_meeting_id"] = None
        case["hearing_slot_start"] = None
        case["status"] = "APPEALED"
        db.touch(case)
        return response.ok(serialize.view(case))


def _period(dt):
    return "%04d-%02d" % (dt.year, dt.month)
