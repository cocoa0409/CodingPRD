from datetime import datetime

from flask import request

from db import db
from errors import (
    ERR_FUNDER_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_OWNERSHIP_VIOLATION,
    ERR_REPORTING_PERIOD_INVALID,
    raise_error,
)
from middleware import get_auth, require_roles
from response import paginate, success
from services import (
    REFERRAL_TERMINAL,
    _stamp_new,
    _touch,
    make_funder,
    raw_cost_float,
    serialise_funder,
    serialise_funder_report,
)
from util import fmt_ts, half_up_int, parse_ts
from validate import (
    CURRENCY_ENUM,
    ROUNDING_VARIANT_ENUM,
    parse_pagination,
    require_body,
    require_enum,
    require_int,
    require_str,
)


def _funder_or_404(fid: str):
    f = db.funders.get(fid)
    if not f:
        raise_error(ERR_FUNDER_NOT_FOUND, f"funder {fid} not found")
    return f


def _check_funder_ownership(f: dict) -> None:
    uid, role = get_auth()
    if role == "FunderReporter" and uid != f["id"]:
        raise_error(ERR_OWNERSHIP_VIOLATION, "FunderReporter does not own this funder")


def register(app):

    @app.post("/funders")
    @require_roles("PlatformAdmin")
    def create_funder():
        body = require_body(request.get_json(silent=True))
        name = require_str(body, "name")
        month = require_int(body, "fiscal_year_start_month")
        if month < 1 or month > 12:
            raise_error(ERR_INVALID_REQUEST, "fiscal_year_start_month must be in [1,12]")
        total = require_int(body, "grant_cents_total")
        if total < 0:
            raise_error(ERR_INVALID_REQUEST, "grant_cents_total must be >= 0")
        currency = require_enum(body, "reporting_currency", CURRENCY_ENUM)
        entity = make_funder(name, month, total, currency)
        return success(serialise_funder(entity), 201)

    @app.get("/funders/<fid>")
    @require_roles("PlatformAdmin", "FunderReporter")
    def get_funder(fid):
        f = _funder_or_404(fid)
        _check_funder_ownership(f)
        return success(serialise_funder(f), 200)

    @app.get("/funders/<fid>/reports")
    @require_roles("PlatformAdmin", "FunderReporter")
    def list_reports(fid):
        f = _funder_or_404(fid)
        _check_funder_ownership(f)
        limit, offset = parse_pagination(request.args)
        items = [r for r in db.funder_reports.values() if r["funder_id"] == fid]
        items.sort(key=lambda x: x["created_at"])
        window, pg = paginate(items, limit, offset)
        return success([serialise_funder_report(r) for r in window], 200, "array", pg)

    @app.post("/funders/<fid>/reports")
    @require_roles("PlatformAdmin")
    def create_report(fid):
        f = _funder_or_404(fid)
        body = require_body(request.get_json(silent=True))
        start_s = require_str(body, "reporting_period_start")
        end_s = require_str(body, "reporting_period_end")
        variant = require_enum(body, "rounding_variant", ROUNDING_VARIANT_ENUM)

        start_dt = parse_ts(start_s)
        end_dt = parse_ts(end_s)
        if not (start_dt < end_dt):
            raise_error(ERR_REPORTING_PERIOD_INVALID, "start must be strictly less than end")

        # Select outcomes: ACTIVE + referral.program.funder_id == fid + created_at in [start, end)
        selected = []
        for o in db.outcome_reports.values():
            if o["status"] != "ACTIVE":
                continue
            ref = db.referrals.get(o["referral_id"])
            if not ref:
                continue
            prog = db.programs.get(ref["program_id"])
            if not prog or prog["funder_id"] != fid:
                continue
            o_created = parse_ts(o["created_at"])
            if o_created >= start_dt and o_created < end_dt:
                selected.append(o)
        # Sort by created_at ascending (tie-breaker specified in scaffold)
        selected.sort(key=lambda o: o["created_at"])

        if variant == "PER_REFERRAL_ROUND_THEN_SUM":
            total_disb = sum(o["service_cost_final_cents"] for o in selected)
        else:  # SUM_THEN_ROUND
            raw_total = 0.0
            for o in selected:
                ref = db.referrals[o["referral_id"]]
                prog = db.programs[ref["program_id"]]
                raw_total += raw_cost_float(o["outcome"], o["service_hours"],
                                            prog["unit_cost_cents"])
            total_disb = half_up_int(raw_total)

        # Referrals in the window whose program.funder_id == fid
        window_refs = []
        for ref in db.referrals.values():
            prog = db.programs.get(ref["program_id"])
            if not prog or prog["funder_id"] != fid:
                continue
            rc = parse_ts(ref["created_at"])
            if rc >= start_dt and rc < end_dt:
                window_refs.append(ref)

        total_referrals = len(window_refs)
        total_completions = sum(
            1 for r in window_refs if r["status"] in ("COMPLETED_SUCCESS", "COMPLETED_UNSUCCESSFUL")
        )
        # language_breakdown
        lang_counts = {"EN": 0, "ES": 0, "FR": 0, "ZH": 0, "VI": 0, "AR": 0}
        for r in window_refs:
            intake = db.intakes.get(r["intake_id"])
            if not intake:
                continue
            client = db.clients.get(intake["client_id"])
            if not client:
                continue
            lang = client["preferred_language"]
            if lang in lang_counts:
                lang_counts[lang] += 1

        report = {
            "funder_id": fid,
            "reporting_period_start": start_s,
            "reporting_period_end": end_s,
            "rounding_variant": variant,
            "total_referrals": total_referrals,
            "total_completions": total_completions,
            "total_disbursement_cents": total_disb,
            "language_breakdown": lang_counts,
        }
        # FunderReport has only id and created_at (no updated_at / version).
        from util import new_id
        report["id"] = new_id()
        report["created_at"] = fmt_ts(db.clock)
        db.funder_reports[report["id"]] = report

        # Advance funder_reporting_posture on every contributing program: OPEN -> LOCKED
        contributing_prog_ids = set()
        for o in selected:
            ref = db.referrals[o["referral_id"]]
            contributing_prog_ids.add(ref["program_id"])
        for pid in contributing_prog_ids:
            prog = db.programs.get(pid)
            if prog and prog["funder_reporting_posture"] == "OPEN":
                prog["funder_reporting_posture"] = "LOCKED"
                _touch(prog)

        return success(serialise_funder_report(report), 201)
