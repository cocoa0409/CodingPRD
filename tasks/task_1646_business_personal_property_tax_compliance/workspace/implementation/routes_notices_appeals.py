"""Routes: assessment notices and appeals (PRD §3.5)."""

from flask import Blueprint, request

import errors as E
from middleware import get_caller, require_role, parse_pagination
from response import ok, created, ok_list
from util import (
    get_body, req_str, req_int, req_enum, lookup, stamp_new, touch,
    parse_date_field, append_audit,
)
from services import finalize_notice
from serializers import notice_view, appeal_view

bp = Blueprint("notices_appeals", __name__)

ALL_ROLES = ("FirmAdmin", "TaxAnalyst", "SeniorManager", "AssessorClerk", "Client")


def register(app, store):

    # ------------------------------------------------------------------
    # POST /bpp/renditions/<rendition_id>/assessment-notices
    # ------------------------------------------------------------------
    @app.post("/bpp/renditions/<rendition_id>/assessment-notices")
    def create_notice(rendition_id):
        caller = get_caller(store)
        require_role(caller, "AssessorClerk")
        r = lookup(store.renditions, rendition_id, "Rendition")
        body = get_body()
        value = req_int(body, "notice_value_cents", min_v=1)
        received = parse_date_field(body, "received_date")
        protest_deadline = parse_date_field(body, "protest_deadline_date")
        # state gate (priority 5): rendition must be FILED or ACCEPTED
        if r["rendition_status"] not in ("FILED", "ACCEPTED"):
            E.raise_err(E.ERR_INVALID_STATE_TRANSITION,
                        "Notices may only be recorded on a FILED or ACCEPTED rendition")
        n = {
            "rendition_id": r["id"],
            "notice_value_cents": value,
            "received_date": received,
            "protest_deadline_date": protest_deadline,
            "notice_status": "RECEIVED",
            "final_value_cents": None,
            # remembers the status before a protest for appeal withdraw
            "_pre_appeal_status": None,
        }
        stamp_new(store, n)
        store.notices[n["id"]] = n
        return created(notice_view(n))

    # ------------------------------------------------------------------
    # GET /bpp/assessment-notices/<notice_id>
    # ------------------------------------------------------------------
    @app.get("/bpp/assessment-notices/<notice_id>")
    def get_notice(notice_id):
        caller = get_caller(store)
        require_role(caller, *ALL_ROLES)
        n = lookup(store.notices, notice_id, "AssessmentNotice")
        return ok(notice_view(n))

    # ------------------------------------------------------------------
    # GET /bpp/renditions/<rendition_id>/assessment-notices
    # ------------------------------------------------------------------
    @app.get("/bpp/renditions/<rendition_id>/assessment-notices")
    def list_notices(rendition_id):
        caller = get_caller(store)
        require_role(caller, *ALL_ROLES)
        lookup(store.renditions, rendition_id, "Rendition")
        limit, offset = parse_pagination()
        items = [n for n in store.notices.values() if n["rendition_id"] == rendition_id]
        ns = request.args.get("notice_status")
        if ns is not None:
            items = [n for n in items if n["notice_status"] == ns]
        items.sort(key=lambda n: n["created_at"])
        total = len(items)
        page = items[offset : offset + limit]
        return ok_list([notice_view(n) for n in page], total, limit, offset)

    # ------------------------------------------------------------------
    # POST /bpp/assessment-notices/<notice_id>/accept
    # ------------------------------------------------------------------
    @app.post("/bpp/assessment-notices/<notice_id>/accept")
    def accept_notice(notice_id):
        caller = get_caller(store)
        require_role(caller, "TaxAnalyst")
        n = lookup(store.notices, notice_id, "AssessmentNotice")
        get_body()
        if n["notice_status"] != "RECEIVED":
            E.raise_err(E.ERR_INVALID_STATE_TRANSITION, "Only a RECEIVED notice may be accepted")
        n["notice_status"] = "ACCEPTED"
        touch(n)
        return ok(notice_view(n))

    # ------------------------------------------------------------------
    # POST /bpp/assessment-notices/<notice_id>/appeals
    # ------------------------------------------------------------------
    @app.post("/bpp/assessment-notices/<notice_id>/appeals")
    def create_appeal(notice_id):
        caller = get_caller(store)
        require_role(caller, "TaxAnalyst")
        n = lookup(store.notices, notice_id, "AssessmentNotice")
        body = get_body()
        claimed = req_int(body, "claimed_value_cents", min_v=0)
        grounds = req_str(body, "grounds")
        # notice appealability (priority 8)
        if n["notice_status"] not in ("RECEIVED", "ACCEPTED"):
            E.raise_err(E.ERR_NOTICE_NOT_APPEALABLE,
                        "Appeals may only be filed on a RECEIVED or ACCEPTED notice")
        # protest window (priority 15)
        if store.clock_date() > n["protest_deadline_date"]:
            E.raise_err(E.ERR_PROTEST_WINDOW_CLOSED, "The protest deadline has passed")
        # claim sanity (priority 25)
        if claimed > n["notice_value_cents"]:
            E.raise_err(E.ERR_CLAIM_EXCEEDS_NOTICE,
                        "claimed_value_cents exceeds the noticed value")
        a = {
            "notice_id": n["id"],
            "claimed_value_cents": claimed,
            "grounds": grounds,
            "appeal_status": "FILED",
            "hearing_date": None,
            "decision": None,
            "decided_value_cents": None,
            "board_value_cents": None,
        }
        stamp_new(store, a)
        store.appeals[a["id"]] = a
        n["_pre_appeal_status"] = n["notice_status"]
        n["notice_status"] = "PROTESTED"
        touch(n)
        return created(appeal_view(a))

    # ------------------------------------------------------------------
    # GET /bpp/appeals/<appeal_id>
    # ------------------------------------------------------------------
    @app.get("/bpp/appeals/<appeal_id>")
    def get_appeal(appeal_id):
        caller = get_caller(store)
        require_role(caller, *ALL_ROLES)
        a = lookup(store.appeals, appeal_id, "Appeal")
        return ok(appeal_view(a))

    # ------------------------------------------------------------------
    # GET /bpp/assessment-notices/<notice_id>/appeals
    # ------------------------------------------------------------------
    @app.get("/bpp/assessment-notices/<notice_id>/appeals")
    def list_appeals(notice_id):
        caller = get_caller(store)
        require_role(caller, *ALL_ROLES)
        lookup(store.notices, notice_id, "AssessmentNotice")
        limit, offset = parse_pagination()
        items = [a for a in store.appeals.values() if a["notice_id"] == notice_id]
        st = request.args.get("appeal_status")
        if st is not None:
            items = [a for a in items if a["appeal_status"] == st]
        items.sort(key=lambda a: a["created_at"])
        total = len(items)
        page = items[offset : offset + limit]
        return ok_list([appeal_view(a) for a in page], total, limit, offset)

    # ------------------------------------------------------------------
    # POST /bpp/appeals/<appeal_id>/schedule-hearing
    # ------------------------------------------------------------------
    @app.post("/bpp/appeals/<appeal_id>/schedule-hearing")
    def schedule_hearing(appeal_id):
        caller = get_caller(store)
        require_role(caller, "AssessorClerk")
        a = lookup(store.appeals, appeal_id, "Appeal")
        body = get_body()
        hearing = parse_date_field(body, "hearing_date")
        if a["appeal_status"] != "FILED":
            E.raise_err(E.ERR_APPEAL_NOT_ACTIONABLE,
                        "schedule-hearing requires appeal status FILED")
        a["appeal_status"] = "HEARING_SCHEDULED"
        a["hearing_date"] = hearing
        touch(a)
        return ok(appeal_view(a))

    # ------------------------------------------------------------------
    # POST /bpp/appeals/<appeal_id>/record-decision
    # ------------------------------------------------------------------
    @app.post("/bpp/appeals/<appeal_id>/record-decision")
    def record_decision(appeal_id):
        caller = get_caller(store)
        require_role(caller, "AssessorClerk")
        a = lookup(store.appeals, appeal_id, "Appeal")
        body = get_body()
        decision = req_enum(body, "decision", {"GRANTED_REDUCTION", "DENIED"})
        decided_value = req_int(body, "decided_value_cents", min_v=0)
        if a["appeal_status"] != "HEARING_SCHEDULED":
            E.raise_err(E.ERR_APPEAL_NOT_ACTIONABLE,
                        "record-decision requires appeal status HEARING_SCHEDULED")
        notice = store.notices[a["notice_id"]]
        if decision == "GRANTED_REDUCTION" and not (decided_value < notice["notice_value_cents"]):
            E.raise_err(E.ERR_INVALID_REQUEST,
                        "GRANTED_REDUCTION requires decided_value_cents below the noticed value")
        if decision == "DENIED" and decided_value != notice["notice_value_cents"]:
            E.raise_err(E.ERR_INVALID_REQUEST,
                        "DENIED requires decided_value_cents equal to the noticed value")
        a["appeal_status"] = "DECIDED"
        a["decision"] = decision
        a["decided_value_cents"] = decided_value
        touch(a)
        return ok(appeal_view(a))

    # ------------------------------------------------------------------
    # POST /bpp/appeals/<appeal_id>/resolve
    # ------------------------------------------------------------------
    @app.post("/bpp/appeals/<appeal_id>/resolve")
    def resolve_appeal(appeal_id):
        caller = get_caller(store)
        require_role(caller, "Client")
        a = lookup(store.appeals, appeal_id, "Appeal")
        body = get_body()
        resolution = req_enum(body, "resolution", {"ACCEPT", "ESCALATE"})
        # Client ownership via FK chain (priority 2)
        notice = store.notices[a["notice_id"]]
        rendition = store.renditions[notice["rendition_id"]]
        if rendition["client_id"] != caller.user_id:
            E.raise_err(E.ERR_FORBIDDEN_ROLE, "Client does not own this appeal")
        if a["appeal_status"] != "DECIDED":
            E.raise_err(E.ERR_APPEAL_NOT_ACTIONABLE,
                        "resolve requires appeal status DECIDED")
        if resolution == "ACCEPT":
            a["appeal_status"] = "ACCEPTED"
            touch(a)
            # cascade: finalize the notice at the decided value
            finalize_notice(store, notice, a["decided_value_cents"], caller.user_id)
            append_audit(store, rendition["client_id"], "APPEAL_RESOLVED",
                         f"Appeal {a['id']} resolved (ACCEPT)", caller.user_id)
        else:  # ESCALATE — deliberately no notice or bill change
            a["appeal_status"] = "ESCALATED"
            touch(a)
        return ok(appeal_view(a))

    # ------------------------------------------------------------------
    # POST /bpp/appeals/<appeal_id>/withdraw
    # ------------------------------------------------------------------
    @app.post("/bpp/appeals/<appeal_id>/withdraw")
    def withdraw_appeal(appeal_id):
        caller = get_caller(store)
        require_role(caller, "TaxAnalyst")
        a = lookup(store.appeals, appeal_id, "Appeal")
        get_body()
        if a["appeal_status"] not in ("FILED", "HEARING_SCHEDULED"):
            E.raise_err(E.ERR_APPEAL_NOT_ACTIONABLE,
                        "withdraw requires appeal status FILED or HEARING_SCHEDULED")
        a["appeal_status"] = "WITHDRAWN"
        touch(a)
        notice = store.notices[a["notice_id"]]
        # return the notice to its pre-appeal standing
        notice["notice_status"] = notice.get("_pre_appeal_status") or "RECEIVED"
        notice["_pre_appeal_status"] = None
        touch(notice)
        return ok(appeal_view(a))

    # ------------------------------------------------------------------
    # POST /bpp/appeals/<appeal_id>/close
    # ------------------------------------------------------------------
    @app.post("/bpp/appeals/<appeal_id>/close")
    def close_appeal(appeal_id):
        caller = get_caller(store)
        require_role(caller, "Client", "AssessorClerk")
        a = lookup(store.appeals, appeal_id, "Appeal")
        body = get_body()
        notice = store.notices[a["notice_id"]]
        rendition = store.renditions[notice["rendition_id"]]

        if caller.role == "Client":
            # ownership via FK chain
            if rendition["client_id"] != caller.user_id:
                E.raise_err(E.ERR_FORBIDDEN_ROLE, "Client does not own this appeal")
            if a["appeal_status"] != "ACCEPTED":
                E.raise_err(E.ERR_APPEAL_NOT_ACTIONABLE,
                            "Client close requires appeal status ACCEPTED")
            a["appeal_status"] = "CLOSED"
            touch(a)
            return ok(appeal_view(a))

        # AssessorClerk: close an ESCALATED appeal with board_value_cents
        if a["appeal_status"] != "ESCALATED":
            E.raise_err(E.ERR_APPEAL_NOT_ACTIONABLE,
                        "AssessorClerk close requires appeal status ESCALATED")
        board_value = body.get("board_value_cents")
        if board_value is None or isinstance(board_value, bool) or not isinstance(board_value, int) or board_value <= 0:
            E.raise_err(E.ERR_INVALID_REQUEST,
                        "board_value_cents is required and must be > 0")
        a["board_value_cents"] = board_value
        a["appeal_status"] = "CLOSED"
        touch(a)
        finalize_notice(store, notice, board_value, caller.user_id)
        append_audit(store, rendition["client_id"], "APPEAL_RESOLVED",
                     f"Appeal {a['id']} resolved (board decision)", caller.user_id)
        return ok(appeal_view(a))
