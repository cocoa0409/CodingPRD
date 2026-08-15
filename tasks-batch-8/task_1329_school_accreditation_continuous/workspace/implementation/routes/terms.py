"""AccreditationTerm endpoints and the term lifecycle state machine."""
from flask import Blueprint, request

from db import DB, clock_now, fmt_iso, new_id
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import get_or_404
from util import (
    add_years,
    as_enum,
    as_int,
    body,
    paginate,
    pagination,
    parse_dt,
    required,
    stamp_new,
    touch,
)

bp = Blueprint("terms", __name__)

ACTIVE_TERM_STATES = {
    "SELF_STUDY",
    "REVIEW",
    "DECISION",
    "TERM_ACTIVE",
    "INTERIM_MONITORING",
    "RENEWAL",
}

DECISION_OUTCOMES = {"ACCREDITED", "ACCREDITED_WITH_STIPULATIONS", "DENIED"}


def term_view(t):
    return {k: v for k, v in t.items() if not k.startswith("_")}


@bp.post("/accreditation/systems/<id>/terms")
def create_term(id):
    auth(["AccreditationOfficer"])
    system = get_or_404("systems", id, "InstitutionSystem")
    data = body()
    term_start_raw = required(data, "term_start")
    term_start_dt = parse_dt(term_start_raw, "term_start")
    term_length_years = as_int(required(data, "term_length_years"), "term_length_years")
    if term_length_years not in (5, 6):
        raise ApiError("ERR_VALIDATION", 400, "term_length_years must be 5 or 6")
    # Uniqueness: at most one term in flight per system.
    for t in DB["terms"].values():
        if t["system_id"] == id and t["status"] in ACTIVE_TERM_STATES:
            raise ApiError(
                "ERR_DUPLICATE_RESOURCE",
                409,
                "System already has a term in an active state",
            )
    term_end_dt = add_years(term_start_dt, term_length_years)
    record = {
        "id": new_id(),
        "system_id": id,
        "term_start": fmt_iso(term_start_dt),
        "term_length_years": term_length_years,
        "term_end": fmt_iso(term_end_dt),
        "status": "PREPARATION",
        "decision_outcome": "NONE",
        "_term_start_dt": term_start_dt,
        "_term_end_dt": term_end_dt,
    }
    stamp_new(record, with_version=True)
    DB["terms"][record["id"]] = record
    return ok(term_view(record), status=201)


@bp.get("/accreditation/systems/<id>/terms")
def list_terms(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader"])
    get_or_404("systems", id, "InstitutionSystem")
    limit, offset = pagination()
    rows = [t for t in DB["terms"].values() if t["system_id"] == id]
    rows.sort(key=lambda t: t["created_at"])
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([term_view(r) for r in page], total, limit, offset)


@bp.get("/accreditation/terms/<id>")
def get_term(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader", "Reviewer"])
    row = get_or_404("terms", id, "AccreditationTerm")
    return ok(term_view(row))


@bp.post("/accreditation/terms/<id>/advance")
def advance_term(id):
    auth(["AccreditationOfficer"])
    term = get_or_404("terms", id, "AccreditationTerm")
    system = DB["systems"].get(term["system_id"])
    current = term["status"]

    if current == "PREPARATION":
        # PREPARATION -> SELF_STUDY
        # Uniqueness: no other ACTIVE term for the same system.
        for t in DB["terms"].values():
            if (
                t["id"] != term["id"]
                and t["system_id"] == term["system_id"]
                and t["status"] in ACTIVE_TERM_STATES
            ):
                raise ApiError(
                    "ERR_DUPLICATE_RESOURCE",
                    409,
                    "System already has a term in an active state",
                )
        # Coverage: every IN_SCOPE campus has at least one rating row per Standard.
        standards = list(DB["standards"].values())
        campuses = [
            c for c in DB["campuses"].values()
            if c["system_id"] == term["system_id"] and c["campus_status"] == "IN_SCOPE"
        ]
        for c in campuses:
            for s in standards:
                found = any(
                    r for r in DB["ratings"].values()
                    if r["term_id"] == term["id"]
                    and r["campus_id"] == c["id"]
                    and r["standard_id"] == s["id"]
                )
                if not found:
                    raise ApiError(
                        "ERR_INVALID_STATE",
                        409,
                        f"Campus {c['id']} is missing a rating for standard {s['id']}",
                    )
        term["status"] = "SELF_STUDY"
        touch(term)
        if system is not None:
            system["current_term_id"] = term["id"]
            touch(system)
        return ok(term_view(term))

    if current == "SELF_STUDY":
        # SELF_STUDY -> REVIEW
        for r in DB["ratings"].values():
            if r["term_id"] == term["id"] and r["status"] != "FINALIZED":
                raise ApiError(
                    "ERR_INVALID_STATE",
                    409,
                    "All ratings under the term must be FINALIZED",
                )
        for w in DB["survey_windows"].values():
            if w["term_id"] == term["id"] and w["status"] not in ("CLOSED", "INVALIDATED"):
                raise ApiError(
                    "ERR_INVALID_STATE",
                    409,
                    "All survey windows under the term must be CLOSED or INVALIDATED",
                )
        term["status"] = "REVIEW"
        touch(term)
        return ok(term_view(term))

    if current == "REVIEW":
        # REVIEW -> DECISION
        visits = [v for v in DB["visits"].values() if v["term_id"] == term["id"]]
        if not any(v["status"] == "REPORT_ISSUED" for v in visits):
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "At least one visit must be REPORT_ISSUED",
            )
        blocking = {"REQUESTED", "CONFIRMED", "IN_FIELD", "REPORT_DRAFT"}
        if any(v["status"] in blocking for v in visits):
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Visits remain in an open state",
            )
        term["status"] = "DECISION"
        touch(term)
        return ok(term_view(term))

    if current == "TERM_ACTIVE":
        # TERM_ACTIVE -> INTERIM_MONITORING
        # Every RequiredActionItem arising from this term's visits VERIFIED or WAIVED.
        visit_ids = {
            v["id"] for v in DB["visits"].values() if v["term_id"] == term["id"]
        }
        finding_ids = {
            f["id"] for f in DB["findings"].values() if f["visit_id"] in visit_ids
        }
        for ai in DB["action_items"].values():
            if ai["finding_id"] in finding_ids and ai["status"] not in ("VERIFIED", "WAIVED"):
                raise ApiError(
                    "ERR_INVALID_STATE",
                    409,
                    "All required action items must be VERIFIED or WAIVED",
                )
        accepted = any(
            r for r in DB["interim_reports"].values()
            if r["term_id"] == term["id"] and r["status"] == "ACCEPTED"
        )
        if not accepted:
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "At least one interim report must be ACCEPTED",
            )
        term["status"] = "INTERIM_MONITORING"
        touch(term)
        return ok(term_view(term))

    # DECISION / INTERIM_MONITORING / RENEWAL / CLOSED have no officer-driven advance
    raise ApiError(
        "ERR_INVALID_STATE", 409, f"Term in {current} cannot be advanced via this endpoint"
    )


@bp.post("/accreditation/terms/<id>/decide")
def decide_term(id):
    auth(["AccreditationCommission"])
    term = get_or_404("terms", id, "AccreditationTerm")
    if term["status"] != "DECISION":
        raise ApiError("ERR_INVALID_STATE", 409, "Term is not in DECISION")
    data = body()
    outcome = as_enum(required(data, "outcome"), "outcome", DECISION_OUTCOMES)
    system = DB["systems"].get(term["system_id"])

    if outcome in ("ACCREDITED", "ACCREDITED_WITH_STIPULATIONS"):
        if outcome == "ACCREDITED_WITH_STIPULATIONS":
            visit_ids = {
                v["id"] for v in DB["visits"].values() if v["term_id"] == term["id"]
            }
            has_required = any(
                f for f in DB["findings"].values()
                if f["visit_id"] in visit_ids and f["severity"] == "REQUIRED_ACTION"
            )
            if not has_required:
                raise ApiError(
                    "ERR_INVALID_STATE",
                    409,
                    "ACCREDITED_WITH_STIPULATIONS requires at least one REQUIRED_ACTION finding",
                )
        term["decision_outcome"] = outcome
        term["status"] = "TERM_ACTIVE"
        touch(term)
        if system is not None:
            system["accreditation_status"] = (
                "ACCREDITED" if outcome == "ACCREDITED" else "ON_PROBATION"
            )
            touch(system)
        return ok(term_view(term))

    # outcome == DENIED
    term["decision_outcome"] = "DENIED"
    term["status"] = "CLOSED"
    touch(term)
    if system is not None:
        system["accreditation_status"] = "ACCREDITATION_WITHDRAWN"
        system["current_term_id"] = None
        touch(system)
    return ok(term_view(term))


@bp.post("/accreditation/terms/<id>/close")
def close_term(id):
    auth(["AccreditationOfficer"])
    term = get_or_404("terms", id, "AccreditationTerm")
    if term["status"] != "RENEWAL":
        raise ApiError("ERR_INVALID_STATE", 409, "Term is not in RENEWAL")
    system = DB["systems"].get(term["system_id"])
    # Locate the RENEWAL_FEE invoice issued on entering RENEWAL.
    renewal_invoices = [
        inv for inv in DB["invoices"].values()
        if inv["system_id"] == term["system_id"] and inv["invoice_type"] == "RENEWAL_FEE"
    ]
    renewal_invoices.sort(key=lambda i: i["created_at"])
    if not renewal_invoices or renewal_invoices[-1]["status"] != "PAID":
        raise ApiError(
            "ERR_FISCAL_VIOLATION",
            422,
            "The RENEWAL_FEE invoice issued on entering RENEWAL must be PAID",
        )
    term["status"] = "CLOSED"
    touch(term)
    if system is not None:
        system["current_term_id"] = None
        touch(system)
    return ok(term_view(term))
