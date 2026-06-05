"""TherapyLog endpoints: log, list, summary (PRD §3.5)."""
from decimal import Decimal

from flask import request

import db
import errors
import response
import serialize
import validation as V
from clock import parse_iso, current_utc, to_utc_date
from gate import gate
from services import calc, lookups


DISCIPLINES = {"PT", "OT", "SLP"}
MODES = {"INDIVIDUAL", "CONCURRENT", "GROUP"}


def _in_bed_hold_window(session_date_iso, admission_id, statuses):
    """True if session_date falls inside a bed-hold window with one of the given
    statuses (PRD §3.5). Window is [leave_start_at, expected/actual_return_at)."""
    sd = to_utc_date(parse_iso(session_date_iso))
    for bh in lookups.bed_holds_for_admission(admission_id):
        if bh["status"] not in statuses:
            continue
        start = to_utc_date(parse_iso(bh["leave_start_at"]))
        end_iso = bh.get("actual_return_at") or bh["expected_return_at"]
        end = to_utc_date(parse_iso(end_iso))
        if start <= sd < end:
            return True
    return False


def register(app):
    @app.route("/snf/admissions/<aid>/therapy-logs", methods=["POST"])
    def create_therapy_log(aid):
        gate(["Therapist"])
        adm = lookups.get_admission(aid)
        body = V.get_body()
        discipline = V.as_enum(V.require(body, "discipline"), "discipline", DISCIPLINES)
        mode = V.as_enum(V.require(body, "mode"), "mode", MODES)
        minutes = V.as_int(V.require(body, "minutes"), "minutes", minimum=1)
        session_date = V.require(body, "session_date")
        sd_dt = V.as_datetime(session_date, "session_date")
        # session_date within [admit_at, now] and admission therapy-eligible (priority 12).
        admit_dt = parse_iso(adm["admit_at"])
        if adm["status"] not in ("ACTIVE", "NON_COVERED", "DISCHARGE_PLANNED"):
            raise errors.err(errors.ERR_THERAPY_OUT_OF_STAY,
                             "admission is not in a therapy-eligible state")
        if sd_dt < admit_dt or sd_dt > current_utc():
            raise errors.err(errors.ERR_THERAPY_OUT_OF_STAY,
                             "session_date is outside the admission stay window")
        iem = calc.individual_equivalent_minutes(mode, minutes)
        obj = {
            "admission_id": aid,
            "discipline": discipline,
            "mode": mode,
            "minutes": minutes,
            "session_date": session_date,
            "individual_equivalent_minutes": iem,
        }
        db.stamp_create(obj)
        db.therapy_logs[obj["id"]] = obj
        return response.success(serialize.public(obj), 201)

    @app.route("/snf/admissions/<aid>/therapy-logs", methods=["GET"])
    def list_therapy_logs(aid):
        gate(["Therapist", "MdsCoordinator", "BillingAnalyst"])
        lookups.get_admission(aid)
        limit, offset = V.pagination(request.args)
        rows = lookups.therapy_logs_for_admission(aid)
        discipline = request.args.get("discipline")
        if discipline is not None:
            rows = [r for r in rows if r["discipline"] == discipline]
        page, total = V.paginate(rows, limit, offset)
        return response.success_list(serialize.public_list(page), limit, offset, total, 200)

    @app.route("/snf/admissions/<aid>/therapy-summary", methods=["GET"])
    def therapy_summary(aid):
        gate(["Therapist", "MdsCoordinator"])
        lookups.get_admission(aid)
        discipline = request.args.get("discipline")
        if discipline is None or discipline not in DISCIPLINES:
            raise errors.err(errors.ERR_INVALID_REQUEST,
                             "discipline query param is required and must be PT/OT/SLP")
        rows = [
            t for t in lookups.therapy_logs_for_admission(aid)
            if t["discipline"] == discipline
        ]
        # Exclude rows on bed-hold days (OPEN or CLOSED) (PRD §3.5).
        rows = [
            t for t in rows
            if not _in_bed_hold_window(t["session_date"], aid, ("OPEN", "CLOSED"))
        ]
        total_raw = sum(t["minutes"] for t in rows)
        total_individual_equiv = sum(t["individual_equivalent_minutes"] for t in rows)
        group_concurrent_raw = sum(
            t["minutes"] for t in rows if t["mode"] in ("GROUP", "CONCURRENT"))
        if total_raw > 0:
            pct = Decimal(group_concurrent_raw) / Decimal(total_raw)
        else:
            pct = Decimal("0")
        exceeds = pct > calc.GROUP_CONCURRENT_CAP_PCT
        data = {
            "discipline": discipline,
            "total_raw": total_raw,
            "total_individual_equiv": total_individual_equiv,
            "group_concurrent_pct": float(pct),
            "exceeds_group_cap": exceeds,
        }
        return response.success(data, 200)
