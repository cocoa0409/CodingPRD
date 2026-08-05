"""Holder report lifecycle: draft, attach, submit, review, accept/reject/revise."""
import re
from datetime import timedelta
from flask import request

from store import STORE, new_id, parse_iso, iso
from common import (
    ApiError, ok, ok_list, require_roles, get_json, require_str, require_int,
    stamp_new, touch, serialize, serialize_list, paginate,
)
import lookups
import calc
import ledger

_STATE_RE = re.compile(r"^[A-Z]{2}$")


def attached_properties(report_id):
    return [p for p in STORE.properties.values() if p.get("report_id") == report_id]


def compute_totals(report):
    props = attached_properties(report["id"])
    count = len(props)
    now = STORE.now()
    total = 0
    for p in props:
        if p["status"] in ("ESCHEATED", "CLAIMED") and p.get("remitted_amount_cents"):
            total += p["remitted_amount_cents"]
        else:
            ptype = STORE.property_types.get(p["property_type_id"])
            total += calc.escheat_remittance_amount(p, ptype, now)
    return count, total


def serialize_report(report):
    count, total = compute_totals(report)
    report["property_count"] = count
    report["total_remitted_cents"] = total
    return serialize(report)


def register(app):
    @app.post("/reports")
    @require_roles("Holder")
    def create_report():
        body = get_json()
        holder_id = require_str(body, "holder_id")
        report_state = require_str(body, "report_state")
        if not _STATE_RE.match(report_state):
            raise ApiError("ERR_INVALID_REQUEST", 400, "report_state must be two uppercase letters.")
        report_period_year = require_int(body, "report_period_year", min_val=2000)
        lookups.holder(holder_id)
        for r in STORE.reports.values():
            if (r["holder_id"] == holder_id and r["report_state"] == report_state
                    and r["report_period_year"] == report_period_year):
                raise ApiError("ERR_REPORT_PERIOD_OVERLAP", 409,
                               "A report already exists for this holder, state, and year.")
        ent = {
            "id": new_id(),
            "holder_id": holder_id,
            "report_state": report_state,
            "report_period_year": report_period_year,
            "property_count": 0,
            "total_remitted_cents": 0,
            "submitted_at": None,
            "status": "DRAFT",
        }
        stamp_new(ent)
        STORE.reports[ent["id"]] = ent
        return ok(serialize(ent), 201)

    @app.get("/reports/<rid>")
    @require_roles("StateAdmin", "Holder", "StateExaminer", "StateApprover")
    def get_report(rid):
        return ok(serialize_report(lookups.report(rid)))

    @app.get("/reports")
    @require_roles("StateAdmin", "Holder", "StateExaminer", "StateApprover")
    def list_reports():
        items = list(STORE.reports.values())
        for key in ("holder_id", "report_state", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [r for r in items if r.get(key) == val]
        items = serialize_list(items)
        page, limit, offset, total = paginate(items)
        return ok_list([serialize_report(r) for r in page], limit, offset, total)

    @app.post("/reports/<rid>/add-property")
    @require_roles("Holder")
    def add_property(rid):
        report = lookups.report(rid)
        body = get_json()
        property_id = require_str(body, "property_id")
        expected_report_version = require_int(body, "expected_report_version")
        prop = lookups.prop(property_id)
        # State checks (ERR_INVALID_STATE)
        if report["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", 409, "Report is not in DRAFT.")
        if prop["status"] not in ("DORMANT", "DUE_DILIGENCE"):
            raise ApiError("ERR_INVALID_STATE", 409, "Property is not attachable.")
        if prop["holder_id"] != report["holder_id"]:
            raise ApiError("ERR_INVALID_STATE", 409, "Property holder does not match report holder.")
        # Business referential
        if prop["escheat_state"] != report["report_state"]:
            raise ApiError("ERR_ESCHEAT_STATE_MISMATCH", 422,
                           "Property escheat_state does not match report_state.")
        # OCC
        if expected_report_version != report["version"]:
            raise ApiError("ERR_STALE_REPORT_VERSION", 412, "Stale report version.")
        prop["report_id"] = report["id"]
        prop["status"] = "REPORTED"
        touch(prop)
        count, total = compute_totals(report)
        report["property_count"] = count
        report["total_remitted_cents"] = total
        touch(report)
        return ok(serialize_report(report))

    @app.post("/reports/<rid>/submit")
    @require_roles("Holder")
    def submit_report(rid):
        report = lookups.report(rid)
        body = get_json()
        declared_total_cents = require_int(body, "declared_total_cents")
        if report["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", 409, "Report is not in DRAFT.")
        holder = STORE.holders.get(report["holder_id"])
        if holder and holder.get("audit_hold"):
            raise ApiError("ERR_HOLDER_UNDER_AUDIT", 409, "Holder is under audit.")
        now = STORE.now()
        for p in attached_properties(report["id"]):
            ptype = STORE.property_types.get(p["property_type_id"])
            if ptype and ptype["due_diligence_required"]:
                notices = [n for n in STORE.notices.values() if n["property_id"] == p["id"]]
                if not notices:
                    raise ApiError("ERR_DUE_DILIGENCE_INCOMPLETE", 422,
                                   "Due-diligence window not complete.")
                earliest = min(parse_iso(n["sent_at"]) for n in notices)
                elapsed_days = (now - earliest).days
                if elapsed_days < ptype["due_diligence_min_days"]:
                    raise ApiError("ERR_DUE_DILIGENCE_INCOMPLETE", 422,
                                   "Due-diligence window not complete.")
        _, total = compute_totals(report)
        if declared_total_cents != total:
            raise ApiError("ERR_REMITTANCE_MISMATCH", 422,
                           "declared_total_cents does not match computed total.")
        report["total_remitted_cents"] = total
        report["status"] = "SUBMITTED"
        report["submitted_at"] = iso(now)
        touch(report)
        return ok(serialize_report(report))

    @app.post("/reports/<rid>/begin-review")
    @require_roles("StateExaminer")
    def begin_review(rid):
        report = lookups.report(rid)
        if report["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", 409, "Report is not SUBMITTED.")
        report["status"] = "UNDER_AUDIT"
        touch(report)
        return ok(serialize_report(report))

    @app.post("/reports/<rid>/accept")
    @require_roles("StateExaminer")
    def accept_report(rid):
        report = lookups.report(rid)
        if report["status"] != "UNDER_AUDIT":
            raise ApiError("ERR_INVALID_STATE", 409, "Report is not UNDER_AUDIT.")
        now = STORE.now()
        for p in attached_properties(report["id"]):
            if p["status"] != "REPORTED":
                continue
            ptype = STORE.property_types.get(p["property_type_id"])
            remitted = calc.escheat_remittance_amount(p, ptype, now)
            p["remitted_amount_cents"] = remitted
            p["status"] = "ESCHEATED"
            touch(p)
            account = lookups.find_state_account_by_code(p["escheat_state"])
            if account is None:
                raise ApiError("ERR_STATE_ACCOUNT_NOT_FOUND", 404,
                               "No custody account for the escheat state.")
            ledger.write_entry(account, "REMIT_IN", remitted,
                               property_id=p["id"], ref_report_id=report["id"])
        report["status"] = "ACCEPTED"
        touch(report)
        return ok(serialize_report(report))

    @app.post("/reports/<rid>/reject")
    @require_roles("StateExaminer")
    def reject_report(rid):
        report = lookups.report(rid)
        if report["status"] != "UNDER_AUDIT":
            raise ApiError("ERR_INVALID_STATE", 409, "Report is not UNDER_AUDIT.")
        report["status"] = "REJECTED"
        touch(report)
        return ok(serialize_report(report))

    @app.post("/reports/<rid>/revise")
    @require_roles("Holder")
    def revise_report(rid):
        report = lookups.report(rid)
        if report["status"] != "REJECTED":
            raise ApiError("ERR_INVALID_STATE", 409, "Report is not REJECTED.")
        report["status"] = "DRAFT"
        touch(report)
        return ok(serialize_report(report))
