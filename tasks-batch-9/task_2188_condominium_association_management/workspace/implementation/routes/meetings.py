"""Board meetings: notice, convene, adjourn, and the cancel compensation."""
from flask import request

import clock
import db
import response
import serialize
import validation as V
from auth import authenticate
from errors import ApiError

AGENDA_KINDS = ("REGULAR", "BUDGET_RATIFICATION", "HEARING", "CONTRACT_AWARD",
                "SPECIAL_ASSESSMENT")
MEETING_STATUSES = ("SCHEDULED", "NOTICED", "IN_SESSION", "ADJOURNED", "CANCELLED")


def register(app):

    @app.post("/associations/<association_id>/board-meetings")
    def create_board_meeting(association_id):
        authenticate(("CommunityManager",))
        found = V.resolve_path(association_id=association_id)
        body = V.body_of()
        scheduled_start = V.require_dt(body, "scheduled_start")
        scheduled_end = V.require_dt(body, "scheduled_end")
        agenda_kinds = V.require_str_list(body, "agenda_kinds", allowed=AGENDA_KINDS,
                                         non_empty=True)
        if scheduled_end <= scheduled_start:
            V.fail("Field 'scheduled_end' must be after 'scheduled_start'.")

        row = db.base_fields()
        row.update({
            "association_id": association_id,
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "agenda_kinds": list(agenda_kinds),
            "notice_sent_at": None,
            "status": "SCHEDULED",
            "seated_director_count": 0,
            "quorum_met": False,
            "hearing_slot_count": 0,
        })
        db.insert("board_meetings", row)
        return response.created(serialize.view(row))

    @app.get("/board-meetings")
    def list_board_meetings():
        authenticate(("CommunityManager", "BoardDirector", "BoardTreasurer",
                      "UnitOwner"))
        limit, offset = V.pagination()
        args = request.args
        status = args.get("status")
        if status is not None and status not in MEETING_STATUSES:
            V.fail("Query parameter 'status' is not a recognized meeting status.")

        def keep(m):
            want = args.get("association_id")
            if want and m["association_id"] != want:
                return False
            if status and m["status"] != status:
                return False
            return True

        rows = db.sorted_rows("board_meetings", keep)
        page, total = V.paginate(rows, limit, offset)
        return response.listing(serialize.views(page), limit, offset, total)

    @app.post("/board-meetings/<board_meeting_id>/send-notice")
    def send_meeting_notice(board_meeting_id):
        authenticate(("CommunityManager",))
        found = V.resolve_path(board_meeting_id=board_meeting_id)
        meeting = found["board_meeting_id"]
        V.body_of()
        # Rung 12.
        if meeting["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_MEETING_STATE")
        # Rung 25 -- the meeting must still lie strictly in the future.
        if not meeting["scheduled_start"] > clock.now():
            raise ApiError("ERR_NOTICE_PERIOD_NOT_SATISFIED")
        meeting["status"] = "NOTICED"
        meeting["notice_sent_at"] = clock.now()
        db.touch(meeting)
        return response.ok(serialize.view(meeting))

    @app.post("/board-meetings/<board_meeting_id>/convene")
    def convene_board_meeting(board_meeting_id):
        authenticate(("CommunityManager",))
        found = V.resolve_path(board_meeting_id=board_meeting_id)
        meeting = found["board_meeting_id"]
        assoc = db.get("associations", meeting["association_id"])
        body = V.body_of()
        attending = V.require_str_list(body, "attending_owner_ids", required=False,
                                       default=[])
        owners = []
        for owner_id in attending or []:
            owner = db.get("owners", owner_id)
            if owner is None:
                raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND")
            owners.append(owner)
        V.scope_match(meeting["association_id"], *owners)
        # Rung 12.
        if meeting["status"] != "NOTICED":
            raise ApiError("ERR_INVALID_MEETING_STATE")
        if clock.now() < meeting["scheduled_start"]:
            raise ApiError("ERR_INVALID_MEETING_STATE",
                           "The meeting cannot be convened before its scheduled start.")
        seated = sum(1 for o in owners if o["is_seated"] and o["board_role"] != "NONE")
        # Rung 14.
        if seated < assoc["board_quorum_seats"]:
            raise ApiError("ERR_BOARD_QUORUM_NOT_MET")

        meeting["seated_director_count"] = seated
        meeting["quorum_met"] = True
        meeting["status"] = "IN_SESSION"
        db.touch(meeting)
        return response.ok(serialize.view(meeting))

    @app.post("/board-meetings/<board_meeting_id>/adjourn")
    def adjourn_board_meeting(board_meeting_id):
        authenticate(("CommunityManager",))
        found = V.resolve_path(board_meeting_id=board_meeting_id)
        meeting = found["board_meeting_id"]
        V.body_of()
        # Rung 12.
        if meeting["status"] != "IN_SESSION":
            raise ApiError("ERR_INVALID_MEETING_STATE")
        # Rung 50.
        for case in db.store["violation_cases"].values():
            if (case.get("hearing_meeting_id") == meeting["id"]
                    and case["status"] == "HEARING_SCHEDULED"):
                raise ApiError("ERR_HEARINGS_PENDING")
        # Rung 51.
        for budget in db.store["budgets"].values():
            if (budget.get("ratification_meeting_id") == meeting["id"]
                    and budget["status"] == "NOTICED"):
                raise ApiError("ERR_BUDGET_NOTICE_PENDING")

        meeting["status"] = "ADJOURNED"
        db.touch(meeting)
        return response.ok(serialize.view(meeting))

    @app.post("/board-meetings/<board_meeting_id>/cancel")
    def cancel_board_meeting(board_meeting_id):
        authenticate(("CommunityManager",))
        found = V.resolve_path(board_meeting_id=board_meeting_id)
        meeting = found["board_meeting_id"]
        body = V.body_of()
        V.require_str(body, "reason", required=False, default=None)
        # Rung 12.
        if meeting["status"] not in ("SCHEDULED", "NOTICED"):
            raise ApiError("ERR_INVALID_MEETING_STATE")

        # De-docket every hearing.  A round-1 case returns to NOTICE_SENT with its
        # cure_deadline_at deliberately NOT extended; a round-2+ case returns to
        # APPEALED with hearing_round left where it is.
        for case in db.sorted_rows(
                "violation_cases",
                lambda c: c.get("hearing_meeting_id") == meeting["id"]):
            if case["hearing_round"] >= 2:
                case["status"] = "APPEALED"
                case["hearing_meeting_id"] = None
                case["hearing_slot_start"] = None
            elif case["hearing_round"] == 1:
                case["status"] = "NOTICE_SENT"
                case["hearing_meeting_id"] = None
                case["hearing_slot_start"] = None
                case["hearing_round"] = 0
            else:
                continue
            db.touch(case)
        meeting["hearing_slot_count"] = 0

        for budget in db.sorted_rows(
                "budgets",
                lambda b: b.get("ratification_meeting_id") == meeting["id"]
                and b["status"] == "NOTICED"):
            budget["status"] = "PROPOSED"
            budget["notice_sent_at"] = None
            db.touch(budget)

        meeting["status"] = "CANCELLED"
        db.touch(meeting)
        return response.ok(serialize.view(meeting))
