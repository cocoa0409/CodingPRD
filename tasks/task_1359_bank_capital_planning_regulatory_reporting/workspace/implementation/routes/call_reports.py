"""CallReport and EditException endpoints (PRD 3.3, 3.4)."""

from __future__ import annotations

from flask import Blueprint

import db
from db import (
    call_reports, edit_exceptions, reporting_periods, stamp_new, touch,
)
from errors import (
    raise_err, ERR_INVALID_STATE_TRANSITION, ERR_NO_EXPOSURES, ERR_UNRESOLVED_EDITS,
    ERR_SEGREGATION_OF_DUTIES_VIOLATION, ERR_EDIT_NOTE_REQUIRED, ERR_AMENDMENT_LOCKED,
)
from middleware import require_roles
from response import success_object, success_list
from services.core import (
    ser_report, ser_edit, get_bank, get_period, get_report, get_edit,
    exposures_for_period, compute_rwa_variants, select_rwa, compute_capital_stack,
    ratio_bps, run_acceptance_cascade, bump_bank, clock_now,
)
from util import get_body, apply_filters, sorted_page

bp = Blueprint("call_reports", __name__)


def _newest_report_for_period(period_id: str):
    reps = [r for r in call_reports.values() if r["reporting_period_id"] == period_id]
    if not reps:
        return None
    reps.sort(key=lambda r: (r["amendment_sequence"], r.get("_seq", 0)))
    return reps[-1]


def _create_report_row(bank: dict, period: dict) -> dict:
    prior = _newest_report_for_period(period["id"])
    if prior is None:
        seq = 0
        supersedes = None
    else:
        seq = prior["amendment_sequence"] + 1
        supersedes = prior["id"]
    report = {
        "reporting_period_id": period["id"],
        "bank_id": bank["id"],
        "amendment_sequence": seq,
        "supersedes_call_report_id": supersedes,
        "cet1_cents": None,
        "tier1_cents": None,
        "total_capital_cents": None,
        "rwa_cents": None,
        "rwa_standardized_cents": None,
        "rwa_advanced_cents": None,
        "cet1_ratio_bps": None,
        "tier1_ratio_bps": None,
        "total_ratio_bps": None,
        "leverage_ratio_bps": None,
        "total_exposure_cents": None,
        "edit_failures_open_count": 0,
        "edit_failures_total_count": 0,
        "submitted_at": None,
        "accepted_at": None,
        "prepared_by_user_id": None,
        "status": "DRAFT",
    }
    stamp_new(report)
    call_reports[report["id"]] = report
    return report


@bp.route("/banks/<bankId>/reporting-periods/<periodId>/call-reports", methods=["POST"])
@require_roles("CapitalAnalyst")
def create_call_report(bankId: str, periodId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    period = get_period(bank, periodId)
    get_body()  # tolerate/absent body; still validate JSON when present
    report = _create_report_row(bank, period)
    return success_object(ser_report(report), 201)


@bp.route("/banks/<bankId>/reporting-periods/<periodId>/call-reports/<reportId>", methods=["GET"])
@require_roles("Any")
def get_one_report(bankId: str, periodId: str, reportId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    period = get_period(bank, periodId)
    return success_object(ser_report(get_report(period, reportId)))


@bp.route("/banks/<bankId>/reporting-periods/<periodId>/call-reports", methods=["GET"])
@require_roles("Any")
def list_reports(bankId: str, periodId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    period = get_period(bank, periodId)
    items = [r for r in call_reports.values() if r["reporting_period_id"] == period["id"]]
    items = apply_filters(items, {"status": "status"})
    page, limit, offset, total = sorted_page(items)
    return success_list([ser_report(r) for r in page], limit, offset, total)


@bp.route("/banks/<bankId>/call-reports", methods=["GET"])
@require_roles("Any")
def list_bank_reports(bankId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    items = [r for r in call_reports.values() if r["bank_id"] == bank["id"]]
    items = apply_filters(items, {
        "reporting_period_id": "reporting_period_id",
        "status": "status",
    })
    page, limit, offset, total = sorted_page(items)
    return success_list([ser_report(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------

@bp.route("/banks/<bankId>/reporting-periods/<periodId>/call-reports/<reportId>/prepare", methods=["POST"])
@require_roles("CapitalAnalyst")
def prepare_report(bankId: str, periodId: str, reportId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    period = get_period(bank, periodId)
    report = get_report(period, reportId)
    if report["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a DRAFT CallReport can be prepared")
    exposures = exposures_for_period(period["id"])
    if not exposures:
        raise_err(ERR_NO_EXPOSURES, "No RiskExposure rows exist for the period")

    period_end = period["_period_end"]
    rwa_std, rwa_adv, total_ead = compute_rwa_variants(period["id"])
    rwa = select_rwa(bank, rwa_std, rwa_adv)
    cet1, tier1, total_cap = compute_capital_stack(bank, rwa, period_end)

    report["rwa_standardized_cents"] = rwa_std
    report["rwa_advanced_cents"] = rwa_adv
    report["rwa_cents"] = rwa
    report["total_exposure_cents"] = total_ead
    report["cet1_cents"] = cet1
    report["tier1_cents"] = tier1
    report["total_capital_cents"] = total_cap
    report["cet1_ratio_bps"] = ratio_bps(cet1, rwa)
    report["tier1_ratio_bps"] = ratio_bps(tier1, rwa)
    report["total_ratio_bps"] = ratio_bps(total_cap, rwa)
    report["leverage_ratio_bps"] = ratio_bps(tier1, total_ead)
    report["prepared_by_user_id"] = _user_id

    # Edit checks (edit_check_rwa_mismatch family). The from-scratch
    # recomputation is the computation above, so RWA/ratio mismatch checks
    # cannot diverge; the Collins-floor check can genuinely fire.
    if bank["rwa_methodology"] == "ADVANCED" and rwa_adv < rwa_std:
        edit = {
            "call_report_id": report["id"],
            "edit_code": "EDIT_FLOOR_VIOLATION",
            "severity": "FATAL",
            "description": (
                "Advanced-approaches RWA (%d) fell below standardized RWA (%d); "
                "the Collins floor requires rwa_cents >= rwa_standardized_cents."
                % (rwa_adv, rwa_std)
            ),
            "resolution_note": None,
            "status": "OPEN",
        }
        stamp_new(edit)
        edit_exceptions[edit["id"]] = edit

    open_count = sum(
        1 for e in edit_exceptions.values()
        if e["call_report_id"] == report["id"] and e["status"] == "OPEN"
    )
    total_count = sum(
        1 for e in edit_exceptions.values() if e["call_report_id"] == report["id"]
    )
    report["edit_failures_open_count"] = open_count
    report["edit_failures_total_count"] = total_count
    report["status"] = "EDITS_OUTSTANDING" if open_count > 0 else "VALIDATED"
    touch(report)
    return success_object(ser_report(report))


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------

@bp.route("/banks/<bankId>/reporting-periods/<periodId>/call-reports/<reportId>/submit", methods=["POST"])
@require_roles("CapitalAnalyst")
def submit_report(bankId: str, periodId: str, reportId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    period = get_period(bank, periodId)
    report = get_report(period, reportId)
    # State (priority 5)
    if report["status"] != "VALIDATED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a VALIDATED CallReport can be submitted")
    if period["status"] not in ("OPEN", "FILING_DUE", "AMENDMENT_OPEN"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "ReportingPeriod does not permit submission in its current state")
    # Segregation of duties (priority 7)
    if report.get("prepared_by_user_id") is not None and report["prepared_by_user_id"] == _user_id:
        raise_err(ERR_SEGREGATION_OF_DUTIES_VIOLATION,
                  "Submitter must differ from the analyst who prepared the report")
    # Edit gate (priority 11)
    if report["edit_failures_open_count"] > 0:
        raise_err(ERR_UNRESOLVED_EDITS, "CallReport has open edit exceptions")

    now_iso = db.get_current_utc()
    now_dt = clock_now()
    report["submitted_at"] = now_iso
    report["status"] = "SUBMITTED"
    touch(report)

    late = now_dt > period["_filing_due_dt"]
    if late:
        period["late_filing"] = True
        if bank["supervisory_status"] == "NORMAL":
            bank["supervisory_status"] = "UNDER_LETTER"
            touch(bank, bump=False)

    if period["status"] == "AMENDMENT_OPEN":
        period["status"] = "RE_SUBMITTED"
        touch(period)
    else:
        period["status"] = "SUBMITTED"
        touch(period)

    bump_bank(bank)
    return success_object(ser_report(report))


# ---------------------------------------------------------------------------
# Accept
# ---------------------------------------------------------------------------

@bp.route("/banks/<bankId>/reporting-periods/<periodId>/call-reports/<reportId>/accept", methods=["POST"])
@require_roles("RegulatorReviewer")
def accept_report(bankId: str, periodId: str, reportId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    period = get_period(bank, periodId)
    report = get_report(period, reportId)
    if report["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a SUBMITTED CallReport can be accepted")
    non_terminal = any(
        e["call_report_id"] == report["id"] and e["status"] == "OPEN"
        for e in edit_exceptions.values()
    )
    if non_terminal:
        raise_err(ERR_UNRESOLVED_EDITS, "CallReport has non-terminal edit exceptions")

    amendment = period["status"] == "RE_SUBMITTED"
    report["accepted_at"] = db.get_current_utc()
    report["status"] = "ACCEPTED"
    touch(report)
    period["status"] = "RE_ACCEPTED" if amendment else "ACCEPTED"
    touch(period)

    run_acceptance_cascade(bank, period, report, amendment=amendment)
    bump_bank(bank)
    return success_object(ser_report(report))


# ---------------------------------------------------------------------------
# Open amendment
# ---------------------------------------------------------------------------

@bp.route("/banks/<bankId>/reporting-periods/<periodId>/call-reports/<reportId>/open_amendment", methods=["POST"])
@require_roles("CapitalAnalyst")
def open_amendment(bankId: str, periodId: str, reportId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    period = get_period(bank, periodId)
    report = get_report(period, reportId)
    if period["status"] != "ACCEPTED" or report["status"] != "ACCEPTED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Amendments may only be opened on an ACCEPTED period and report")
    # Amendment lock (priority 13): no later-dated period already CLOSED.
    for other in reporting_periods.values():
        if (other["bank_id"] == bank["id"] and other["id"] != period["id"]
                and other["status"] == "CLOSED"
                and other["_period_end"] > period["_period_end"]):
            raise_err(ERR_AMENDMENT_LOCKED,
                      "A later ReportingPeriod for this bank is already CLOSED")

    report["status"] = "AMENDED_SUPERSEDED"
    touch(report)
    period["status"] = "AMENDMENT_OPEN"
    touch(period)
    new_report = _create_report_row(bank, period)
    return success_object(ser_report(new_report), 200)


# ---------------------------------------------------------------------------
# Edit exceptions
# ---------------------------------------------------------------------------

@bp.route("/banks/<bankId>/reporting-periods/<periodId>/call-reports/<reportId>/edit-exceptions", methods=["GET"])
@require_roles("Any")
def list_edits(bankId: str, periodId: str, reportId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    period = get_period(bank, periodId)
    report = get_report(period, reportId)
    items = [e for e in edit_exceptions.values() if e["call_report_id"] == report["id"]]
    items = apply_filters(items, {"status": "status", "severity": "severity"})
    page, limit, offset, total = sorted_page(items)
    return success_list([ser_edit(e) for e in page], limit, offset, total)


@bp.route("/banks/<bankId>/reporting-periods/<periodId>/call-reports/<reportId>/edit-exceptions/<editId>", methods=["GET"])
@require_roles("Any")
def get_one_edit(bankId: str, periodId: str, reportId: str, editId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    period = get_period(bank, periodId)
    report = get_report(period, reportId)
    return success_object(ser_edit(get_edit(report, editId)))


def _resolve_or_explain(bankId, periodId, reportId, editId, target, _user_id):
    bank = get_bank(bankId)
    period = get_period(bank, periodId)
    report = get_report(period, reportId)
    edit = get_edit(report, editId)
    # State (priority 5): edit must be OPEN; report must be PREPARED/EDITS_OUTSTANDING.
    if edit["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE_TRANSITION, "EditException is not OPEN")
    if report["status"] not in ("PREPARED", "EDITS_OUTSTANDING"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "CallReport must be PREPARED or EDITS_OUTSTANDING to clear edits")
    if target == "EXPLAINED" and edit["severity"] == "FATAL":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "FATAL edits cannot be EXPLAINED; they must be RESOLVED")
    # Note requirement (priority 12).
    body = get_body()
    note = body.get("resolution_note")
    note_missing = note is None or not isinstance(note, str) or note.strip() == ""
    if target == "EXPLAINED":
        if note_missing:
            raise_err(ERR_EDIT_NOTE_REQUIRED, "resolution_note is required for an explanation")
    else:
        if edit["severity"] != "INFORMATIONAL" and note_missing:
            raise_err(ERR_EDIT_NOTE_REQUIRED,
                      "resolution_note is required for FATAL/QUALITY edits")
    if not note_missing:
        edit["resolution_note"] = note
    edit["status"] = target
    touch(edit)
    report["edit_failures_open_count"] = sum(
        1 for e in edit_exceptions.values()
        if e["call_report_id"] == report["id"] and e["status"] == "OPEN"
    )
    if report["edit_failures_open_count"] == 0 and report["status"] == "EDITS_OUTSTANDING":
        report["status"] = "VALIDATED"
    touch(report)
    return success_object(ser_edit(edit))


@bp.route("/banks/<bankId>/reporting-periods/<periodId>/call-reports/<reportId>/edit-exceptions/<editId>/resolve", methods=["POST"])
@require_roles("CapitalAnalyst")
def resolve_edit(bankId: str, periodId: str, reportId: str, editId: str, _user_id: str, _role: str):
    return _resolve_or_explain(bankId, periodId, reportId, editId, "RESOLVED", _user_id)


@bp.route("/banks/<bankId>/reporting-periods/<periodId>/call-reports/<reportId>/edit-exceptions/<editId>/explain", methods=["POST"])
@require_roles("CapitalAnalyst")
def explain_edit(bankId: str, periodId: str, reportId: str, editId: str, _user_id: str, _role: str):
    return _resolve_or_explain(bankId, periodId, reportId, editId, "EXPLAINED", _user_id)
