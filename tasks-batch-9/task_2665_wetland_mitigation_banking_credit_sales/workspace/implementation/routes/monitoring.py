"""Performance monitoring, attainment scoring and remedial action (PRD 3.7)."""
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
from util import days, dec, now
from validation import (bad_request, coerce_decimal, filter_enum, filter_string, json_body,
                        pagination, paginate, v_enum, v_int, v_string, v_window)

bp = Blueprint("monitoring", __name__)

REVIEW_STATUSES = ("DRAFT", "SUBMITTED", "ACCEPTED", "RETURNED")
COMPLIANCE_STATUSES = ("UNEVALUATED", "PASS", "PARTIAL", "FAIL")
REMEDIAL_STATUSES = ("OPEN", "WORK_SUBMITTED", "REINSPECTION", "CLEARED", "FAILED")
OCCUPYING = ("DRAFT", "SUBMITTED", "ACCEPTED")
DECISIONS = ("ACCEPT", "RETURN")
OUTCOMES = ("CLEARED", "NOT_CLEARED")
ZERO = Decimal("0.00")


def _report_state_invalid(message):
    return ApiError("ERR_REPORT_STATE_INVALID", message)


def _remedial_state_invalid(message):
    return ApiError("ERR_REMEDIAL_STATE_INVALID", message)


def _parse_measurements(body):
    raw = body.get("measurements")
    if not isinstance(raw, list) or not 1 <= len(raw) <= 6:
        raise bad_request("measurements must be an array of 1 through 6 objects.")
    seen = set()
    out = []
    for item in raw:
        if not isinstance(item, dict):
            raise bad_request("Every measurements entry must be an object.")
        code = v_enum(item, "standard_code", calc.STANDARD_CODES)
        if code in seen:
            raise bad_request("measurements may not repeat a standard code.")
        seen.add(code)
        value = item.get("measured_value")
        if value is None:
            raise bad_request("Required field 'measured_value' is missing.")
        out.append({"standard_code": code,
                    "measured_value": coerce_decimal(value, "measured_value", places=None,
                                                     minimum=0)})
    return out


def _measurement_map(row):
    return {m["standard_code"]: m["measured_value"] for m in row["measurements"]}


def _require_measurements(report, standards):
    supplied = _measurement_map(report)
    for standard in standards:
        if standard["standard_code"] not in supplied:
            raise ApiError("ERR_MEASUREMENT_MISSING",
                           "No measurement supplied for effective standard %s."
                           % standard["standard_code"])
    return supplied


# ------------------------------------------------------------ monitoring reports
@bp.post("/mitigation/monitoring-reports")
def create_report():
    actor = auth.authenticate("Sponsor")
    body = json_body()
    bank_id = v_string(body, "bank_id")
    year = v_int(body, "monitoring_year", minimum=1)
    window_start, window_end = v_window(body)
    measurements = _parse_measurements(body)

    bank = lookup.bank(bank_id)
    auth.require_bank_sponsor(actor, bank)
    if bank["status"] == "CLOSED":
        raise ApiError("ERR_BANK_STATE_INVALID",
                       "A closed mitigation bank accepts no further writes.")

    siblings = [r for r in ledger.bank_reports(bank["id"])
                if r["review_status"] in OCCUPYING]
    for other in siblings:
        if window_start < other["window_end"] and other["window_start"] < window_end:
            raise ApiError("ERR_MONITORING_WINDOW_OVERLAP",
                           "The monitoring window overlaps an existing window on this bank.")
    if any(r["monitoring_year"] == year for r in siblings):
        raise ApiError("ERR_DUPLICATE_MONITORING_YEAR",
                       "A monitoring report already occupies this monitoring year.")
    if not ledger.effective_standards(bank["id"], year):
        raise ApiError("ERR_NO_EFFECTIVE_STANDARDS",
                       "The bank has no performance standard effective in that monitoring year.")

    row = store.new_row({
        "bank_id": bank["id"],
        "monitoring_year": year,
        "window_start": window_start,
        "window_end": window_end,
        "measurements": measurements,
        "review_status": "DRAFT",
        "compliance_status": "UNEVALUATED",
        "attainment_score": None,
        "failed_standard_codes": [],
        "reviewed_by_member_id": None,
        "submitted_at": None,
        "reviewed_at": None,
        "return_count": 0,
    })
    store.monitoring_reports[row["id"]] = row
    return object_response(serialize.monitoring_report(row), 201)


@bp.post("/mitigation/monitoring-reports/<row_id>/submit")
def submit_report(row_id):
    actor = auth.authenticate("Sponsor")
    report = lookup.monitoring_report(row_id)
    bank = lookup.bank(report["bank_id"])
    auth.require_bank_sponsor(actor, bank)
    if report["review_status"] not in ("DRAFT", "RETURNED"):
        raise _report_state_invalid("Only a DRAFT or RETURNED report may be submitted.")
    if bank["status"] not in ("INSTRUMENT_EXECUTED", "MONITORING", "SUSPENDED"):
        raise ApiError("ERR_BANK_STATE_INVALID",
                       "Submission requires the bank to be executed, monitoring or suspended.")
    _require_measurements(report,
                          ledger.effective_standards(bank["id"], report["monitoring_year"]))
    report["review_status"] = "SUBMITTED"
    report["submitted_at"] = now()
    store.touch(report)
    return object_response(serialize.monitoring_report(report))


@bp.post("/mitigation/monitoring-reports/<row_id>/review")
def review_report(row_id):
    actor = auth.authenticate("IRTMember")
    body = json_body()
    decision = v_enum(body, "decision", DECISIONS)
    return_reason = v_string(body, "return_reason", required=decision == "RETURN", max_len=1000)
    report = lookup.monitoring_report(row_id)
    bank = lookup.bank(report["bank_id"])
    member = auth.acting_member(actor)
    auth.check_not_recused(member)
    if report["review_status"] != "SUBMITTED":
        raise _report_state_invalid("Only a SUBMITTED report may be reviewed.")

    if decision == "RETURN":
        report["review_status"] = "RETURNED"
        report["return_count"] += 1
        report["reviewed_by_member_id"] = member["id"]
        report["reviewed_at"] = now()
        report["return_reason"] = return_reason
        store.touch(report)
        return object_response(serialize.monitoring_report(report))

    standards = ledger.effective_standards(bank["id"], report["monitoring_year"])
    if not standards:
        raise ApiError("ERR_NO_EFFECTIVE_STANDARDS",
                       "No performance standard is effective in the report's monitoring year.")
    supplied = _require_measurements(report, standards)

    had_accepted = any(r["review_status"] == "ACCEPTED"
                       for r in ledger.bank_reports(bank["id"]))
    score, failed, compliance = calc.performance_attainment(standards, supplied)
    report["review_status"] = "ACCEPTED"
    report["reviewed_by_member_id"] = member["id"]
    report["reviewed_at"] = now()
    report["attainment_score"] = score
    report["failed_standard_codes"] = failed
    report["compliance_status"] = compliance
    store.touch(report)

    if not had_accepted and bank["status"] == "INSTRUMENT_EXECUTED":
        bank["status"] = "MONITORING"

    if compliance == "FAIL":
        _failure_cascade(bank, report, failed)

    store.touch(bank)
    return object_response(serialize.monitoring_report(report))


def _failure_cascade(bank, report, failed):
    """The pinned four-hop cascade of PRD 3.7."""
    clock = now()
    action = store.new_row({
        "monitoring_report_id": report["id"],
        "deferred_milestone_id": None,
        "verified_by_member_id": None,
        "status": "OPEN",
        "round_number": 1,
        "corrective_scope": "REMEDIATE: " + ",".join(failed),
        "held_credits": ZERO,
        "due_at": clock + days(calc.REMEDIAL_DUE_DAYS),
        "opened_at": clock,
        "work_submitted_at": None,
        "cleared_at": None,
    })
    store.remedial_actions[action["id"]] = action
    # hop 2: posture is derived and now finds a non-terminal remedial action.
    # hop 3: cancel every open sale, restoring reserved holds first.
    ledger.cancel_open_sales(bank, "BANK_POSTURE_RESTRICTED")
    # hop 4: defer the earliest non-terminal milestone and freeze the unsold credits.
    milestone = ledger.earliest_deferrable_milestone(bank["id"])
    held = ZERO
    if milestone is not None:
        was_claimed = milestone["claimed_at"] is not None
        milestone["status"] = "DEFERRED"
        milestone["deferred_at"] = clock
        store.touch(milestone)
        bank["deferral_count"] += 1
        action["deferred_milestone_id"] = milestone["id"]
        if was_claimed:
            aggregate = ledger.aggregates(bank["id"])
            held = aggregate["credits_released"] - aggregate["credits_sold"]
            if held < 0:
                held = ZERO
    action["held_credits"] = held
    if held > 0:
        ledger.append_entry(bank["id"], "HOLD_PLACED", -held, "REMEDIAL_ACTION", action["id"],
                            "HOLD PLACED remedial=%s credits=%s" % (action["id"], held))
    return action


@bp.get("/mitigation/monitoring-reports/<row_id>")
def read_report(row_id):
    auth.authenticate("ProgramAdmin", "Sponsor", "IRTChair", "IRTMember")
    return object_response(serialize.monitoring_report(lookup.monitoring_report(row_id)))


@bp.get("/mitigation/monitoring-reports")
def list_reports():
    auth.authenticate("ProgramAdmin", "Sponsor", "IRTChair", "IRTMember")
    limit, offset = pagination()
    bank_id = filter_string("bank_id")
    reviewer = filter_string("reviewed_by_member_id")
    review_status = filter_enum("review_status", REVIEW_STATUSES)
    compliance_status = filter_enum("compliance_status", COMPLIANCE_STATUSES)
    rows = store.ordered(list(store.monitoring_reports.values()))
    if bank_id is not None:
        rows = [r for r in rows if r["bank_id"] == bank_id]
    if reviewer is not None:
        rows = [r for r in rows if r["reviewed_by_member_id"] == reviewer]
    if review_status is not None:
        rows = [r for r in rows if r["review_status"] == review_status]
    if compliance_status is not None:
        rows = [r for r in rows if r["compliance_status"] == compliance_status]
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.monitoring_report(r) for r in page], limit, offset, total)


# -------------------------------------------------------------- remedial actions
@bp.post("/mitigation/remedial-actions/<row_id>/submit-work")
def submit_work(row_id):
    actor = auth.authenticate("Sponsor")
    action = lookup.remedial_action(row_id)
    bank = ledger.remedial_bank(action)
    if bank is not None:
        auth.require_bank_sponsor(actor, bank)
    if action["status"] != "OPEN":
        raise _remedial_state_invalid("Only an OPEN remedial action may report work complete.")
    if now() > action["due_at"]:
        raise ApiError("ERR_REMEDIAL_PAST_DUE",
                       "The remedial action's due date has already passed.")
    action["status"] = "WORK_SUBMITTED"
    action["work_submitted_at"] = now()
    store.touch(action)
    return object_response(serialize.remedial_action(action))


@bp.post("/mitigation/remedial-actions/<row_id>/inspect")
def inspect_work(row_id):
    actor = auth.authenticate("IRTMember")
    body = json_body()
    outcome = v_enum(body, "outcome", OUTCOMES)
    action = lookup.remedial_action(row_id)
    bank = ledger.remedial_bank(action)
    member = auth.acting_member(actor)
    auth.check_not_recused(member)
    if action["status"] != "WORK_SUBMITTED":
        raise _remedial_state_invalid(
            "Only a remedial action standing in WORK_SUBMITTED may be inspected.")
    clock = now()
    action["status"] = "REINSPECTION"

    if outcome == "CLEARED":
        action["status"] = "CLEARED"
        action["verified_by_member_id"] = member["id"]
        action["cleared_at"] = clock
        store.touch(action)
        if bank is not None:
            _restore_after_clearance(bank, action)
            store.touch(bank)
        return object_response(serialize.remedial_action(action))

    if action["round_number"] < calc.MAX_REMEDIAL_ROUNDS:
        action["status"] = "OPEN"
        action["round_number"] += 1
        action["work_submitted_at"] = None
        action["due_at"] = clock + days(calc.REMEDIAL_DUE_DAYS)
        store.touch(action)
        return object_response(serialize.remedial_action(action))

    action["status"] = "FAILED"
    store.touch(action)
    if bank is not None:
        if bank["status"] == "MONITORING":
            bank["status"] = "SUSPENDED"
        ledger.cancel_open_sales(bank, "BANK_POSTURE_RESTRICTED")
        store.touch(bank)
    return object_response(serialize.remedial_action(action))


def _restore_after_clearance(bank, action):
    remaining = [a for a in ledger.bank_remedial_actions(bank["id"])
                 if a["id"] != action["id"] and a["status"] in ledger.NON_TERMINAL_REMEDIAL]
    if remaining:
        return
    milestone = store.milestones.get(action["deferred_milestone_id"])
    if milestone is not None and milestone["status"] == "DEFERRED":
        milestone["status"] = "CLAIMED" if milestone["claimed_at"] is not None else "PENDING"
        store.touch(milestone)
    held = dec(action["held_credits"])
    if held > 0:
        ledger.append_entry(bank["id"], "HOLD_RELEASED", held, "REMEDIAL_ACTION", action["id"],
                            "HOLD RELEASED remedial=%s credits=%s" % (action["id"], held))
    if bank["status"] == "SUSPENDED":
        bank["status"] = "MONITORING"


@bp.get("/mitigation/remedial-actions/<row_id>")
def read_remedial(row_id):
    auth.authenticate("ProgramAdmin", "Sponsor", "IRTChair", "IRTMember")
    return object_response(serialize.remedial_action(lookup.remedial_action(row_id)))


@bp.get("/mitigation/remedial-actions")
def list_remedial():
    auth.authenticate("ProgramAdmin", "Sponsor", "IRTChair", "IRTMember")
    limit, offset = pagination()
    report_id = filter_string("monitoring_report_id")
    milestone_id = filter_string("deferred_milestone_id")
    verifier = filter_string("verified_by_member_id")
    status = filter_enum("status", REMEDIAL_STATUSES)
    rows = store.ordered(list(store.remedial_actions.values()))
    if report_id is not None:
        rows = [r for r in rows if r["monitoring_report_id"] == report_id]
    if milestone_id is not None:
        rows = [r for r in rows if r["deferred_milestone_id"] == milestone_id]
    if verifier is not None:
        rows = [r for r in rows if r["verified_by_member_id"] == verifier]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.remedial_action(r) for r in page], limit, offset, total)
