"""Board Governance API — Flask entry point.

Wires auth middleware, error handlers, and every endpoint from the PRD
section 4 table onto the services modules. The store starts empty on every
boot; the logical clock starts at 2026-05-01T00:00:00Z.
"""

import os

from flask import Flask, request

import middleware
import services_core as core
import services_meetings as meetings_svc
import services_voting as voting
from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION
from middleware import (
    ROLE_BOARD_CHAIR,
    ROLE_CORPORATE_SECRETARY,
    ROLE_DIRECTOR,
    ROLE_EXTERNAL_AUDITOR,
    require_roles,
)
from response import error_response
from util import body_dict

app = Flask(__name__, static_folder=None)

ALL = (
    ROLE_CORPORATE_SECRETARY,
    ROLE_DIRECTOR,
    ROLE_BOARD_CHAIR,
    ROLE_EXTERNAL_AUDITOR,
)
CS = (ROLE_CORPORATE_SECRETARY,)
DIR = (ROLE_DIRECTOR,)
CHAIR = (ROLE_BOARD_CHAIR,)


@app.before_request
def _auth_context():
    middleware.extract_context()


@app.errorhandler(ApiError)
def _api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def _not_found(err):
    return error_response(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Resource not found")


@app.errorhandler(405)
def _method_not_allowed(err):
    return error_response(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Resource not found")


@app.errorhandler(Exception)
def _unexpected(err):
    return error_response("ERR_INTERNAL", 500, "Internal server error: %s" % err)


def _body():
    raw = request.get_data(cache=True)
    if raw:
        parsed = request.get_json(force=True, silent=True)
        if parsed is None:
            from errors import raise_err

            raise_err(ERR_VALIDATION, "Request body must be valid JSON")
        return body_dict(parsed)
    return {}


# --- Test-driving clock ------------------------------------------------------


@app.post("/_clock/set_current_utc")
def clock_set():
    require_roles(*CS)
    return core.set_current_utc(_body())


# --- Corporations -------------------------------------------------------------


@app.post("/corporations")
def corporations_create():
    require_roles(*CS)
    return core.create_corporation(_body())


@app.get("/corporations")
def corporations_list():
    require_roles(*ALL)
    return core.list_corporations(request.args)


@app.get("/corporations/<id>")
def corporations_get(id):
    require_roles(*ALL)
    return core.get_corporation(id)


@app.post("/corporations/<id>/run_checkpoint")
def corporations_checkpoint(id):
    require_roles(*CS)
    return voting.run_checkpoint(id)


# --- Bylaws -------------------------------------------------------------------


@app.post("/bylaws")
def bylaws_create():
    require_roles(*CS)
    return core.create_bylaws(_body())


@app.get("/bylaws")
def bylaws_list():
    require_roles(*ALL)
    return core.list_bylaws(request.args)


@app.get("/bylaws/<id>")
def bylaws_get(id):
    require_roles(*ALL)
    return core.get_bylaws(id)


@app.post("/bylaws/<id>/adopt")
def bylaws_adopt(id):
    require_roles(*CS)
    return core.adopt_bylaws(id, _body())


# --- Directors ----------------------------------------------------------------


@app.post("/directors")
def directors_create():
    require_roles(*CS)
    return core.create_director(_body())


@app.get("/directors")
def directors_list():
    require_roles(*ALL)
    return core.list_directors(request.args)


@app.get("/directors/<id>")
def directors_get(id):
    require_roles(*ALL)
    return core.get_director(id)


@app.post("/directors/<id>/resign")
def directors_resign(id):
    require_roles(ROLE_CORPORATE_SECRETARY, ROLE_DIRECTOR)
    return core.resign_director(id, middleware.current_role(), middleware.current_user_id())


@app.post("/directors/<id>/review_independence")
def directors_review(id):
    require_roles(*CS)
    return core.review_independence(id, _body())


# --- Committees ---------------------------------------------------------------


@app.post("/committees")
def committees_create():
    require_roles(*CS)
    return core.create_committee(_body())


@app.get("/committees")
def committees_list():
    require_roles(*ALL)
    return core.list_committees(request.args)


@app.get("/committees/<id>")
def committees_get(id):
    require_roles(*ALL)
    return core.get_committee(id)


@app.post("/committees/<id>/activate")
def committees_activate(id):
    require_roles(*CS)
    return core.activate_committee(id)


@app.post("/committees/<id>/dissolve")
def committees_dissolve(id):
    require_roles(*CS)
    return core.dissolve_committee(id)


# --- Committee memberships -----------------------------------------------------


@app.post("/committee_memberships")
def memberships_create():
    require_roles(*CS)
    return core.create_membership(_body())


@app.get("/committee_memberships")
def memberships_list():
    require_roles(*ALL)
    return core.list_memberships(request.args)


@app.get("/committee_memberships/<id>")
def memberships_get(id):
    require_roles(*ALL)
    return core.get_membership(id)


@app.post("/committee_memberships/<id>/end")
def memberships_end(id):
    require_roles(*CS)
    return core.end_membership_endpoint(id)


# --- Meetings -----------------------------------------------------------------


@app.post("/meetings")
def meetings_create():
    require_roles(*CS)
    return meetings_svc.create_meeting(_body())


@app.get("/meetings")
def meetings_list():
    require_roles(*ALL)
    return meetings_svc.list_meetings(request.args)


@app.get("/meetings/<id>")
def meetings_get(id):
    require_roles(*ALL)
    return meetings_svc.get_meeting(id)


@app.post("/meetings/<id>/send_notices")
def meetings_send_notices(id):
    require_roles(*CS)
    return meetings_svc.send_notices(id)


@app.post("/meetings/<id>/reschedule")
def meetings_reschedule(id):
    require_roles(*CS)
    return meetings_svc.reschedule_meeting(id, _body())


@app.post("/meetings/<id>/cancel")
def meetings_cancel(id):
    require_roles(ROLE_CORPORATE_SECRETARY, ROLE_BOARD_CHAIR)
    return meetings_svc.cancel_meeting(id)


@app.post("/meetings/<id>/convene")
def meetings_convene(id):
    require_roles(*CHAIR)
    return meetings_svc.convene_meeting(id, middleware.current_user_id())


@app.post("/meetings/<id>/adjourn")
def meetings_adjourn(id):
    require_roles(*CHAIR)
    return meetings_svc.adjourn_meeting(id, middleware.current_user_id())


# --- Meeting notices -----------------------------------------------------------


@app.get("/meeting_notices")
def notices_list():
    require_roles(*ALL)
    return meetings_svc.list_notices(request.args)


@app.get("/meeting_notices/<id>")
def notices_get(id):
    require_roles(*ALL)
    return meetings_svc.get_notice(id)


@app.post("/meeting_notices/<id>/waive")
def notices_waive(id):
    require_roles(*DIR)
    return meetings_svc.waive_notice(id, middleware.current_user_id())


# --- Attendance ----------------------------------------------------------------


@app.post("/attendance_records")
def attendance_create():
    require_roles(*CS)
    return meetings_svc.create_attendance(_body())


@app.get("/attendance_records")
def attendance_list():
    require_roles(*ALL)
    return meetings_svc.list_attendance(request.args)


@app.get("/attendance_records/<id>")
def attendance_get(id):
    require_roles(*ALL)
    return meetings_svc.get_attendance(id)


# --- Agenda items --------------------------------------------------------------


@app.post("/agenda_items")
def agenda_create():
    require_roles(ROLE_CORPORATE_SECRETARY, ROLE_DIRECTOR)
    return meetings_svc.create_agenda_item(_body())


@app.get("/agenda_items")
def agenda_list():
    require_roles(*ALL)
    return meetings_svc.list_agenda_items(request.args)


@app.get("/agenda_items/<id>")
def agenda_get(id):
    require_roles(*ALL)
    return meetings_svc.get_agenda_item(id)


@app.post("/agenda_items/<id>/include")
def agenda_include(id):
    require_roles(*CS)
    return meetings_svc.include_agenda_item(id)


@app.post("/agenda_items/<id>/drop")
def agenda_drop(id):
    require_roles(*CS)
    return meetings_svc.drop_agenda_item(id)


# --- Board packages ------------------------------------------------------------


@app.post("/board_packages")
def packages_create():
    require_roles(*CS)
    return meetings_svc.create_board_package(_body())


@app.get("/board_packages")
def packages_list():
    require_roles(*ALL)
    return meetings_svc.list_board_packages(request.args)


@app.get("/board_packages/<id>")
def packages_get(id):
    require_roles(*ALL)
    return meetings_svc.get_board_package(id)


@app.post("/board_packages/<id>/seal")
def packages_seal(id):
    require_roles(*CS)
    return meetings_svc.seal_package(id)


@app.post("/board_packages/<id>/unseal")
def packages_unseal(id):
    require_roles(*CS)
    return meetings_svc.unseal_package(id)


@app.post("/board_packages/<id>/distribute")
def packages_distribute(id):
    require_roles(*CS)
    return meetings_svc.distribute_package(id)


# --- Package documents ---------------------------------------------------------


@app.post("/package_documents")
def documents_create():
    require_roles(*CS)
    return meetings_svc.create_package_document(_body())


@app.get("/package_documents")
def documents_list():
    require_roles(*ALL)
    return meetings_svc.list_package_documents(
        request.args, middleware.current_role(), middleware.current_user_id()
    )


@app.get("/package_documents/<id>")
def documents_get(id):
    require_roles(*ALL)
    return meetings_svc.get_package_document(
        id, middleware.current_role(), middleware.current_user_id()
    )


# --- Resolutions ---------------------------------------------------------------


@app.post("/resolutions")
def resolutions_create():
    require_roles(ROLE_CORPORATE_SECRETARY, ROLE_DIRECTOR)
    return voting.create_resolution(_body())


@app.get("/resolutions")
def resolutions_list():
    require_roles(*ALL)
    return voting.list_resolutions(request.args)


@app.get("/resolutions/<id>")
def resolutions_get(id):
    require_roles(*ALL)
    return voting.get_resolution(id)


@app.post("/resolutions/<id>/table")
def resolutions_table(id):
    require_roles(ROLE_CORPORATE_SECRETARY, ROLE_BOARD_CHAIR)
    return voting.table_resolution(id, middleware.current_role())


@app.post("/resolutions/<id>/open_vote")
def resolutions_open_vote(id):
    require_roles(*CHAIR)
    return voting.open_vote(id)


@app.post("/resolutions/<id>/close_vote")
def resolutions_close_vote(id):
    require_roles(*CHAIR)
    return voting.close_vote(id)


@app.post("/resolutions/<id>/redraft")
def resolutions_redraft(id):
    require_roles(*CS)
    return voting.redraft_resolution(id)


@app.post("/resolutions/<id>/circulate_consent")
def resolutions_circulate(id):
    require_roles(*CS)
    return voting.circulate_consent(id)


@app.post("/resolutions/<id>/finalize_consent")
def resolutions_finalize(id):
    require_roles(*CS)
    return voting.finalize_consent(id)


# --- Vote records --------------------------------------------------------------


@app.post("/vote_records")
def votes_create():
    require_roles(*DIR)
    return voting.cast_vote(_body(), middleware.current_user_id())


@app.get("/vote_records")
def votes_list():
    require_roles(*ALL)
    return voting.list_vote_records(request.args)


@app.get("/vote_records/<id>")
def votes_get(id):
    require_roles(*ALL)
    return voting.get_vote_record(id)


@app.post("/vote_records/<id>/recast")
def votes_recast(id):
    require_roles(*DIR)
    return voting.recast_vote(id, _body(), middleware.current_user_id())


# --- Conflict disclosures ------------------------------------------------------


@app.post("/conflict_disclosures")
def disclosures_create():
    require_roles(ROLE_CORPORATE_SECRETARY, ROLE_DIRECTOR)
    return voting.create_disclosure(
        _body(), middleware.current_role(), middleware.current_user_id()
    )


@app.get("/conflict_disclosures")
def disclosures_list():
    require_roles(*ALL)
    return voting.list_disclosures(request.args)


@app.get("/conflict_disclosures/<id>")
def disclosures_get(id):
    require_roles(*ALL)
    return voting.get_disclosure(id)


@app.post("/conflict_disclosures/<id>/clear")
def disclosures_clear(id):
    require_roles(*CS)
    return voting.clear_disclosure(id)


# --- Minutes -------------------------------------------------------------------


@app.get("/minutes")
def minutes_list():
    require_roles(*ALL)
    return voting.list_minutes(request.args)


@app.get("/minutes/<id>")
def minutes_get(id):
    require_roles(*ALL)
    return voting.get_minutes(id)


@app.post("/minutes/<id>/circulate")
def minutes_circulate(id):
    require_roles(*CS)
    return voting.circulate_minutes(id, _body())


@app.post("/minutes/<id>/approve")
def minutes_approve(id):
    require_roles(*CHAIR)
    return voting.approve_minutes(id, middleware.current_user_id())


@app.post("/minutes/<id>/reject")
def minutes_reject(id):
    require_roles(*CHAIR)
    return voting.reject_minutes(id, _body(), middleware.current_user_id())


@app.post("/minutes/<id>/redraft")
def minutes_redraft(id):
    require_roles(*CS)
    return voting.redraft_minutes(id, _body())


@app.post("/minutes/<id>/enter_book")
def minutes_enter_book(id):
    require_roles(*CS)
    return voting.enter_book(id)


# --- Audit requests ------------------------------------------------------------


@app.post("/audit_requests")
def audit_create():
    require_roles(ROLE_EXTERNAL_AUDITOR, ROLE_CORPORATE_SECRETARY)
    return voting.create_audit_request(_body())


@app.get("/audit_requests")
def audit_list():
    require_roles(*ALL)
    return voting.list_audit_requests(request.args)


@app.get("/audit_requests/<id>")
def audit_get(id):
    require_roles(*ALL)
    return voting.get_audit_request(id)


@app.post("/audit_requests/<id>/reconstruct")
def audit_reconstruct(id):
    require_roles(ROLE_EXTERNAL_AUDITOR, ROLE_CORPORATE_SECRETARY)
    return voting.run_reconstruction(id)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
