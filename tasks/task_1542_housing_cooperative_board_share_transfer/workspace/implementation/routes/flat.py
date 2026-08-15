"""Flat cross-cooperative read aliases (PRD §2.10).

Ids are globally unique, so each subordinate record can be located by id
alone. List aliases return records across all cooperatives, filterable by
foreign keys and status fields, and honor the §2.3 pagination contract.
"""
from flask import Blueprint, request

import domain as D
from db import STORE
from errors import ApiError, ERR_NOT_FOUND
from middleware import ctx, require_role, ALL_ROLES
from routes.core import list_response

bp = Blueprint("flat", __name__)

READ_ALL = list(ALL_ROLES)
READ_BOARD = ["PlatformAdmin", "BoardOfficer", "BoardMember", "ManagingAgent"]


def flat_get(kind, eid, label, roles):
    uid, role = ctx()
    require_role(role, roles)
    e = STORE[kind].get(eid)
    if e is None:
        raise ApiError(ERR_NOT_FOUND, "%s %s not found" % (label, eid), 404)
    return e


def flat_list(kind, roles, filters):
    uid, role = ctx()
    require_role(role, roles)
    return list_response(kind, None, filters)


# --- Units ---
@bp.get("/cooperatives/units")
def flat_units_list():
    return flat_list("units", READ_ALL, [
        ("cooperative_id", request.args.get("cooperative_id"), False),
        ("unit_label", request.args.get("unit_label"), False),
    ])


@bp.get("/cooperatives/units/<uid>")
def flat_units_get(uid):
    from response import ok
    return ok(D.ser(flat_get("units", uid, "Unit", READ_ALL)))


# --- Shareholders ---
@bp.get("/cooperatives/shareholders")
def flat_shareholders_list():
    return flat_list("shareholders", READ_BOARD, [
        ("cooperative_id", request.args.get("cooperative_id"), False),
        ("standing", request.args.get("standing"), False),
    ])


@bp.get("/cooperatives/shareholders/<sid>")
def flat_shareholders_get(sid):
    from response import ok
    return ok(D.ser(flat_get("shareholders", sid, "Shareholder", READ_ALL)))


# --- Share ledger entries ---
@bp.get("/cooperatives/share-ledger-entries")
def flat_ledger_list():
    return flat_list("share_ledger_entries", READ_ALL, [
        ("cooperative_id", request.args.get("cooperative_id"), False),
        ("unit_id", request.args.get("unit_id"), False),
        ("shareholder_id", request.args.get("shareholder_id"), False),
        ("entry_status", request.args.get("entry_status"), False),
    ])


@bp.get("/cooperatives/share-ledger-entries/<eid>")
def flat_ledger_get(eid):
    from response import ok
    return ok(D.ser(flat_get("share_ledger_entries", eid, "ShareLedgerEntry", READ_ALL)))


# --- Charge schedules ---
@bp.get("/cooperatives/charge-schedules")
def flat_schedules_list():
    return flat_list("charge_schedules", READ_BOARD, [
        ("cooperative_id", request.args.get("cooperative_id"), False),
        ("approving_resolution_id", request.args.get("approving_resolution_id"), False),
        ("fiscal_year", request.args.get("fiscal_year"), True),
        ("schedule_status", request.args.get("schedule_status"), False),
    ])


@bp.get("/cooperatives/charge-schedules/<csid>")
def flat_schedules_get(csid):
    from response import ok
    return ok(D.ser(flat_get("charge_schedules", csid, "ChargeSchedule", READ_ALL)))


# --- Maintenance charges ---
@bp.get("/cooperatives/maintenance-charges")
def flat_charges_list():
    return flat_list("maintenance_charges", READ_ALL, [
        ("cooperative_id", request.args.get("cooperative_id"), False),
        ("unit_id", request.args.get("unit_id"), False),
        ("schedule_id", request.args.get("schedule_id"), False),
        ("charge_status", request.args.get("charge_status"), False),
        ("billing_month", request.args.get("billing_month"), False),
    ])


@bp.get("/cooperatives/maintenance-charges/<mcid>")
def flat_charges_get(mcid):
    from response import ok
    return ok(D.ser(flat_get("maintenance_charges", mcid, "MaintenanceCharge", READ_ALL)))


# --- Payments ---
@bp.get("/cooperatives/payments")
def flat_payments_list():
    return flat_list("payments", READ_BOARD, [
        ("cooperative_id", request.args.get("cooperative_id"), False),
        ("shareholder_id", request.args.get("shareholder_id"), False),
        ("charge_id", request.args.get("charge_id"), False),
        ("payment_status", request.args.get("payment_status"), False),
    ])


@bp.get("/cooperatives/payments/<pid>")
def flat_payments_get(pid):
    from response import ok
    return ok(D.ser(flat_get("payments", pid, "Payment", READ_BOARD)))


# --- Arrears actions ---
@bp.get("/cooperatives/arrears-actions")
def flat_arrears_list():
    return flat_list("arrears_actions", READ_BOARD, [
        ("cooperative_id", request.args.get("cooperative_id"), False),
        ("shareholder_id", request.args.get("shareholder_id"), False),
        ("action_type", request.args.get("action_type"), False),
        ("action_status", request.args.get("action_status"), False),
    ])


@bp.get("/cooperatives/arrears-actions/<aid>")
def flat_arrears_get(aid):
    from response import ok
    return ok(D.ser(flat_get("arrears_actions", aid, "ArrearsAction", READ_BOARD)))


# --- Purchase applications ---
@bp.get("/cooperatives/purchase-applications")
def flat_apps_list():
    return flat_list("purchase_applications", READ_ALL, [
        ("cooperative_id", request.args.get("cooperative_id"), False),
        ("unit_id", request.args.get("unit_id"), False),
        ("seller_shareholder_id", request.args.get("seller_shareholder_id"), False),
        ("deciding_resolution_id", request.args.get("deciding_resolution_id"), False),
        ("application_status", request.args.get("application_status"), False),
    ])


@bp.get("/cooperatives/purchase-applications/<paid>")
def flat_apps_get(paid):
    from response import ok
    return ok(D.ser(flat_get("purchase_applications", paid, "PurchaseApplication", READ_ALL)))


# --- Interviews ---
@bp.get("/cooperatives/interviews")
def flat_interviews_list():
    return flat_list("interviews", READ_BOARD, [
        ("cooperative_id", request.args.get("cooperative_id"), False),
        ("application_id", request.args.get("application_id"), False),
        ("interview_status", request.args.get("interview_status"), False),
    ])


@bp.get("/cooperatives/interviews/<iid>")
def flat_interviews_get(iid):
    from response import ok
    return ok(D.ser(flat_get("interviews", iid, "Interview", READ_BOARD)))


# --- Resolutions ---
@bp.get("/cooperatives/resolutions")
def flat_resolutions_list():
    return flat_list("resolutions", READ_BOARD, [
        ("cooperative_id", request.args.get("cooperative_id"), False),
        ("supersedes_resolution_id", request.args.get("supersedes_resolution_id"), False),
        ("resolution_kind", request.args.get("resolution_kind"), False),
        ("resolution_status", request.args.get("resolution_status"), False),
        ("subject_entity_id", request.args.get("subject_entity_id"), False),
    ])


@bp.get("/cooperatives/resolutions/<rid>")
def flat_resolutions_get(rid):
    from response import ok
    return ok(D.ser(flat_get("resolutions", rid, "Resolution", READ_BOARD)))


# --- Resolution votes ---
@bp.get("/cooperatives/resolution-votes")
def flat_votes_list():
    return flat_list("resolution_votes", READ_BOARD, [
        ("cooperative_id", request.args.get("cooperative_id"), False),
        ("resolution_id", request.args.get("resolution_id"), False),
        ("vote_choice", request.args.get("vote_choice"), False),
    ])


@bp.get("/cooperatives/resolution-votes/<vid>")
def flat_votes_get(vid):
    from response import ok
    return ok(D.ser(flat_get("resolution_votes", vid, "ResolutionVote", READ_BOARD)))


# --- Sublet agreements ---
@bp.get("/cooperatives/sublet-agreements")
def flat_sublets_list():
    return flat_list("sublet_agreements", READ_ALL, [
        ("cooperative_id", request.args.get("cooperative_id"), False),
        ("unit_id", request.args.get("unit_id"), False),
        ("shareholder_id", request.args.get("shareholder_id"), False),
        ("sublet_status", request.args.get("sublet_status"), False),
    ])


@bp.get("/cooperatives/sublet-agreements/<sid>")
def flat_sublets_get(sid):
    from response import ok
    return ok(D.ser(flat_get("sublet_agreements", sid, "SubletAgreement", READ_ALL)))


# --- Alteration agreements ---
@bp.get("/cooperatives/alteration-agreements")
def flat_alterations_list():
    return flat_list("alteration_agreements", READ_ALL, [
        ("cooperative_id", request.args.get("cooperative_id"), False),
        ("unit_id", request.args.get("unit_id"), False),
        ("shareholder_id", request.args.get("shareholder_id"), False),
        ("alteration_status", request.args.get("alteration_status"), False),
    ])


@bp.get("/cooperatives/alteration-agreements/<aid>")
def flat_alterations_get(aid):
    from response import ok
    return ok(D.ser(flat_get("alteration_agreements", aid, "AlterationAgreement", READ_ALL)))


# --- Meetings ---
@bp.get("/cooperatives/meetings")
def flat_meetings_list():
    return flat_list("meetings", READ_ALL, [
        ("cooperative_id", request.args.get("cooperative_id"), False),
        ("meeting_kind", request.args.get("meeting_kind"), False),
        ("meeting_status", request.args.get("meeting_status"), False),
    ])


@bp.get("/cooperatives/meetings/<mid>")
def flat_meetings_get(mid):
    from response import ok
    return ok(D.ser(flat_get("meetings", mid, "Meeting", READ_ALL)))


# --- Ballots ---
@bp.get("/cooperatives/ballots")
def flat_ballots_list():
    return flat_list("ballots", READ_BOARD, [
        ("cooperative_id", request.args.get("cooperative_id"), False),
        ("meeting_id", request.args.get("meeting_id"), False),
        ("shareholder_id", request.args.get("shareholder_id"), False),
        ("ballot_status", request.args.get("ballot_status"), False),
    ])


@bp.get("/cooperatives/ballots/<bid>")
def flat_ballots_get(bid):
    from response import ok
    return ok(D.ser(flat_get("ballots", bid, "Ballot", READ_BOARD)))
