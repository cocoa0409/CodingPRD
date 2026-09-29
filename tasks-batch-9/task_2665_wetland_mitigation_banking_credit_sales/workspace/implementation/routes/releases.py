"""The credit release schedule: scheduling, claiming and approving releases (PRD 3.6)."""
from decimal import Decimal

import auth
import calc
import ledger
import lookup
import serialize
import store
from errors import ApiError
from flask import Blueprint
from response import list_response, object_response
from util import days, now
from validation import (bad_request, filter_enum, filter_string, json_body, pagination,
                        paginate, v_decimal, v_enum, v_int, v_string, v_window)

bp = Blueprint("releases", __name__)

MILESTONE_STATUSES = ("PENDING", "CLAIMED", "APPROVED", "DEFERRED")
ZERO = Decimal("0.00")


def _state_invalid(message):
    return ApiError("ERR_MILESTONE_STATE_INVALID", message)


@bp.post("/mitigation/milestones")
def create_milestone():
    actor = auth.authenticate("Sponsor")
    body = json_body()
    bank_id = v_string(body, "bank_id")
    code = v_enum(body, "milestone_code", calc.MILESTONE_CODES)
    release_pct = v_decimal(body, "release_pct", places=3, min_exclusive=0, maximum=1)
    window_start, window_end = v_window(body)
    predecessor_id = v_string(body, "predecessor_milestone_id", required=False)

    bank = lookup.bank(bank_id)
    predecessor = None
    if predecessor_id is not None:
        predecessor = lookup.milestone(predecessor_id)
        if predecessor["bank_id"] != bank["id"]:
            raise ApiError("ERR_MILESTONE_NOT_FOUND",
                           "The predecessor milestone belongs to a different bank.")
    auth.require_bank_sponsor(actor, bank)
    if bank["status"] == "CLOSED":
        raise ApiError("ERR_BANK_STATE_INVALID",
                       "A closed mitigation bank accepts no further writes.")

    siblings = ledger.bank_milestones(bank["id"])
    if siblings:
        latest_end = max(m["window_end"] for m in siblings)
        if window_start < latest_end + days(calc.MILESTONE_WINDOW_BUFFER_DAYS):
            raise ApiError("ERR_MILESTONE_WINDOW_BUFFER",
                           "Consecutive milestone windows must be separated by 365 days.")
    if any(m["milestone_code"] == code for m in siblings):
        raise ApiError("ERR_DUPLICATE_MILESTONE_CODE",
                       "This milestone code is already scheduled on the bank.")
    total_pct = sum((m["release_pct"] for m in siblings), Decimal("0")) + release_pct
    if total_pct > Decimal("1.000"):
        raise ApiError("ERR_RELEASE_SCHEDULE_OVERSUBSCRIBED",
                       "The bank's release percentages may not exceed 1.000 in total.")

    row = store.new_row({
        "bank_id": bank["id"],
        "predecessor_milestone_id": predecessor["id"] if predecessor else None,
        "milestone_code": code,
        "release_pct": release_pct,
        "window_start": window_start,
        "window_end": window_end,
        "status": "PENDING",
        "provisional_release_credits": calc.provisional_release_credits(
            bank["total_authorized_credits"], release_pct),
        "final_release_credits": ZERO,
        "attainment_factor_applied": None,
        "claimed_at": None,
        "approved_at": None,
        "deferred_at": None,
    })
    store.milestones[row["id"]] = row
    return object_response(serialize.milestone(row), 201)


@bp.post("/mitigation/milestones/<row_id>/claim")
def claim_milestone(row_id):
    actor = auth.authenticate("Sponsor")
    milestone = lookup.milestone(row_id)
    bank = lookup.bank(milestone["bank_id"])
    auth.require_bank_sponsor(actor, bank)
    if milestone["status"] != "PENDING":
        raise _state_invalid("Only a PENDING milestone may be claimed.")
    if bank["status"] not in ("INSTRUMENT_EXECUTED", "MONITORING"):
        raise ApiError("ERR_BANK_STATE_INVALID",
                       "Claiming requires the bank to be in INSTRUMENT_EXECUTED or MONITORING.")
    if now() < milestone["window_start"]:
        raise ApiError("ERR_MILESTONE_WINDOW_NOT_OPEN",
                       "The milestone's performance window has not opened yet.")
    if milestone["predecessor_milestone_id"] is not None:
        predecessor = store.milestones.get(milestone["predecessor_milestone_id"])
        if predecessor is None or predecessor["status"] != "APPROVED":
            raise ApiError("ERR_PREDECESSOR_NOT_RELEASED",
                           "The predecessor milestone has not been released yet.")
    milestone["status"] = "CLAIMED"
    milestone["claimed_at"] = now()
    milestone["provisional_release_credits"] = calc.provisional_release_credits(
        bank["total_authorized_credits"], milestone["release_pct"])
    store.touch(milestone)
    return object_response(serialize.milestone(milestone))


@bp.post("/mitigation/milestones/<row_id>/approve-release")
def approve_release(row_id):
    actor = auth.authenticate("IRTMember")
    body = json_body()
    expected_version = v_int(body, "expected_bank_version", minimum=0)
    milestone = lookup.milestone(row_id)
    bank = lookup.bank(milestone["bank_id"])
    member = auth.acting_member(actor)
    auth.check_not_recused(member)
    if milestone["status"] != "CLAIMED":
        raise _state_invalid("Only a CLAIMED milestone may have its release approved.")
    if expected_version != bank["version"]:
        raise ApiError("ERR_STALE_BANK_VERSION",
                       "expected_bank_version does not match the bank's current version.")
    if not bank["easement_recorded"]:
        raise ApiError("ERR_EASEMENT_NOT_RECORDED",
                       "The conservation easement must be recorded before any release.")
    for action in store.remedial_actions.values():
        if (action["deferred_milestone_id"] == milestone["id"]
                and action["verified_by_member_id"] == member["id"]):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "The member who cleared the deferring remedial action may not "
                           "approve this release.")

    if milestone["milestone_code"] in calc.CONSTRUCTION_MILESTONE_CODES:
        factor = calc.FULL_RELEASE_FACTOR
    else:
        report = ledger.governing_report(bank["id"])
        if report is None:
            raise ApiError("ERR_NO_ACCEPTED_MONITORING_REPORT",
                           "A performance release requires an accepted monitoring report.")
        if report["compliance_status"] == "FAIL":
            raise ApiError("ERR_COMPLIANCE_FAILED",
                           "The governing monitoring report reports a compliance failure.")
        score = report["attainment_score"]
        if score is None or score < calc.ATTAINMENT_PARTIAL_RELEASE_MIN:
            raise ApiError("ERR_COMPLIANCE_FAILED",
                           "The governing attainment score is below the release threshold.")
        factor = (calc.FULL_RELEASE_FACTOR if score >= calc.ATTAINMENT_FULL_RELEASE_MIN
                  else calc.PARTIAL_RELEASE_FACTOR)

    gate = calc.stewardship_gate_for_milestone(milestone["milestone_code"],
                                               bank["stewardship_required_cents"])
    if bank["stewardship_funded_cents"] < gate:
        raise ApiError("ERR_STEWARDSHIP_UNDERFUNDED",
                       "The long-term stewardship endowment has not cleared its gate.")

    final = calc.final_release_credits(milestone["provisional_release_credits"], factor)
    milestone["status"] = "APPROVED"
    milestone["attainment_factor_applied"] = factor
    milestone["final_release_credits"] = final
    milestone["approved_at"] = now()
    store.touch(milestone)
    ledger.append_entry(bank["id"], "RELEASED", final, "RELEASE_MILESTONE", milestone["id"],
                        "RELEASE code=%s factor=%s credits=%s"
                        % (milestone["milestone_code"], factor, final))
    store.touch(bank)
    return object_response(serialize.milestone(milestone))


@bp.get("/mitigation/milestones/<row_id>")
def read_milestone(row_id):
    auth.authenticate("ProgramAdmin", "Sponsor", "IRTChair", "IRTMember")
    return object_response(serialize.milestone(lookup.milestone(row_id)))


@bp.get("/mitigation/milestones")
def list_milestones():
    auth.authenticate("ProgramAdmin", "Sponsor", "IRTChair", "IRTMember")
    limit, offset = pagination()
    bank_id = filter_string("bank_id")
    status = filter_enum("status", MILESTONE_STATUSES)
    predecessor_id = filter_string("predecessor_milestone_id")
    rows = store.ordered(list(store.milestones.values()))
    if bank_id is not None:
        rows = [r for r in rows if r["bank_id"] == bank_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if predecessor_id is not None:
        rows = [r for r in rows if r["predecessor_milestone_id"] == predecessor_id]
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.milestone(r) for r in page], limit, offset, total)
