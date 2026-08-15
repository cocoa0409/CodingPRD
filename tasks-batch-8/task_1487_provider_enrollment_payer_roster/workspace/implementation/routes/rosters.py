"""Roster files and lines: OCC-guarded submission with supersession, payer
adjudication (confirm/reject), discrepancy resolution, and segregation-of-duties
reconciliation."""
from datetime import timedelta

from flask import Blueprint, g, request

from db import base_fields, store, touch
from errors import (
    ApiError,
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_EMPTY_ROSTER,
    ERR_ENROLLMENT_OVERLAP,
    ERR_NO_ACTIVE_ENROLLMENT,
    ERR_PROVIDER_GROUP_MISMATCH,
    ERR_RETRO_WINDOW_EXCEEDED,
    ERR_ROSTER_LINE_NOT_PENDING,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_AGREEMENT_VERSION,
    invalid_request,
    invalid_state,
    not_found,
)
from middleware import ALL_ROLES, require_roles
from response import list_response, success_object
from serializers import pub
from services import (
    ACTIVE_RECORD_STATES,
    create_enrollment_record,
    enrollment_overlap_exists,
    recompute_roster_rollup,
    records_of,
    terminate_record,
)
from util import fmt_ts
from validate import body, req_bool, req_date, req_enum, req_int, req_str

bp = Blueprint("rosters", __name__)


def _get_file(fid):
    f = store.roster_files.get(fid)
    if f is None:
        raise not_found("RosterFile")
    return f


def _get_line(roster_file, line_id):
    """Nested resolution: the line must exist and belong to the file."""
    for l in store.roster_lines.values():
        if l["id"] == line_id and l["roster_file_id"] == roster_file["id"]:
            return l
    raise not_found("RosterLine")


def _apply_line_effects(roster_file, line, date_str):
    """Apply the enrollment effects of a confirmation at the given date.
    ADD: exclusivity check then record creation + claim-release cascade.
    TERM: an active enrollment must exist; it is terminated with full cascade."""
    ag = store.agreements[roster_file["agreement_id"]]
    pid = line["provider_id"]
    yid = ag["payer_id"]
    if line["action"] == "ADD":
        if enrollment_overlap_exists(pid, yid, date_str):
            raise ApiError(
                ERR_ENROLLMENT_OVERLAP,
                409,
                "The confirmed effective date overlaps an existing enrollment interval",
            )
        create_enrollment_record(
            pid,
            yid,
            line["enrollment_scope"],
            line["benefit_assignment"],
            date_str,
            store.payers[yid],
            source_roster_line_id=line["id"],
        )
    else:  # TERM
        rec = next(
            (
                r
                for r in records_of(pid, yid)
                if r["status"] in ACTIVE_RECORD_STATES
            ),
            None,
        )
        if rec is None:
            raise ApiError(
                ERR_NO_ACTIVE_ENROLLMENT,
                422,
                "No active enrollment exists for this provider and payer",
            )
        terminate_record(rec, date_str)


@bp.post("/api/roster-files")
@require_roles("EnrollmentSpecialist")
def submit_roster_file():
    b = body()
    # Existence (tier 3): agreement FK, then each line's provider FK.
    agid_raw = b.get("agreement_id")
    if isinstance(agid_raw, str) and agid_raw not in store.agreements:
        raise not_found("DelegatedCredentialingAgreement")
    lines_raw = b.get("lines")
    if isinstance(lines_raw, list):
        for ln in lines_raw:
            if isinstance(ln, dict):
                lp = ln.get("provider_id")
                if isinstance(lp, str) and lp not in store.providers:
                    raise not_found("Provider")
    # Schema (tier 4).
    agid = req_str(b, "agreement_id")
    expected_version = req_int(b, "expected_agreement_version")
    if not isinstance(lines_raw, list) or any(
        not isinstance(ln, dict) for ln in lines_raw
    ):
        raise invalid_request("Field 'lines' is required and must be an array of objects")
    parsed = []
    for ln in lines_raw:
        lp = req_str(ln, "provider_id")
        action = req_enum(ln, "action", ("ADD", "TERM"))
        eed = req_date(ln, "expected_effective_date")
        if action == "ADD":
            scope = req_enum(ln, "enrollment_scope", ("GROUP_LINK", "INDIVIDUAL"))
            benefit = req_enum(ln, "benefit_assignment", ("GROUP", "INDIVIDUAL"))
        else:
            scope = None
            benefit = None
        parsed.append((lp, action, eed, scope, benefit))
    ag = store.agreements[agid]
    # OCC (tier 6): expected agreement version must match.
    if expected_version != ag["version"]:
        raise ApiError(
            ERR_STALE_AGREEMENT_VERSION,
            412,
            "expected_agreement_version does not match the agreement's current version",
        )
    # Compliance gate (tier 8).
    if ag["status"] != "ACTIVE":
        raise ApiError(ERR_AGREEMENT_NOT_ACTIVE, 409, "The agreement is not ACTIVE")
    # Referential (tier 9): every line's provider belongs to the agreement's group.
    for lp, _action, _eed, _s, _ben in parsed:
        if store.providers[lp]["practice_group_id"] != ag["practice_group_id"]:
            raise ApiError(
                ERR_PROVIDER_GROUP_MISMATCH,
                422,
                "A roster line's provider does not belong to the agreement's practice group",
            )
    # Temporal (tier 10): each line's expected date within the 90-day retro window.
    floor = (store.clock.date() - timedelta(days=90)).isoformat()
    for _lp, _action, eed, _s, _ben in parsed:
        if eed < floor:
            raise ApiError(
                ERR_RETRO_WINDOW_EXCEEDED,
                422,
                "A line's expected_effective_date is earlier than current date - 90 days",
            )
    # Uniqueness (tier 11): the roster must carry at least one line.
    if len(parsed) == 0:
        raise ApiError(ERR_EMPTY_ROSTER, 422, "A roster file must contain at least one line")
    # Supersede the prior SUBMITTED file for this agreement, with its PENDING lines.
    for f in list(store.roster_files.values()):
        if f["agreement_id"] == agid and f["status"] == "SUBMITTED":
            f["status"] = "SUPERSEDED"
            for ln in store.roster_lines.values():
                if ln["roster_file_id"] == f["id"] and ln["status"] == "PENDING":
                    ln["status"] = "SUPERSEDED"
                    touch(ln)
            recompute_roster_rollup(f, bump=True)
    # Submission increments the agreement's version by one.
    touch(ag)
    roster_file = base_fields()
    roster_file.update(
        {
            "agreement_id": agid,
            "submitted_by_user_id": g.user_id,
            "submitted_at": fmt_ts(store.clock),
            "status": "SUBMITTED",
            "total_lines": 0,
            "pending_count": 0,
            "confirmed_count": 0,
            "rejected_count": 0,
            "discrepancy_count": 0,
            "superseded_count": 0,
        }
    )
    store.roster_files[roster_file["id"]] = roster_file
    for i, (lp, action, eed, scope, benefit) in enumerate(parsed):
        ln = base_fields()
        ln.update(
            {
                "roster_file_id": roster_file["id"],
                "provider_id": lp,
                "line_index": i,
                "action": action,
                "enrollment_scope": scope,
                "benefit_assignment": benefit,
                "expected_effective_date": eed,
                "confirmed_effective_date": None,
                "status": "PENDING",
                "rejection_reason": None,
            }
        )
        store.roster_lines[ln["id"]] = ln
    recompute_roster_rollup(roster_file, bump=False)
    return success_object(pub(roster_file), 201)


@bp.get("/api/roster-files/<fid>")
@require_roles(*ALL_ROLES)
def get_roster_file(fid):
    return success_object(pub(_get_file(fid)))


@bp.get("/api/roster-files")
@require_roles(*ALL_ROLES)
def list_roster_files():
    agreement_id = request.args.get("agreement_id")
    status = request.args.get("status")
    items = [
        f for f in store.roster_files.values()
        if (agreement_id is None or f["agreement_id"] == agreement_id)
        and (status is None or f["status"] == status)
    ]
    return list_response(items, pub)


@bp.get("/api/roster-files/<fid>/lines")
@require_roles(*ALL_ROLES)
def list_roster_lines(fid):
    roster_file = _get_file(fid)
    status = request.args.get("status")
    items = [
        l for l in store.roster_lines.values()
        if l["roster_file_id"] == roster_file["id"]
        and (status is None or l["status"] == status)
    ]
    # Roster lines are ordered by line_index ascending (submission order).
    return list_response(items, pub, sort_key=lambda l: l["line_index"])


@bp.post("/api/roster-files/<fid>/lines/<lid>/confirm")
@require_roles("PayerRepresentative")
def confirm_line(fid, lid):
    roster_file = _get_file(fid)
    line = _get_line(roster_file, lid)
    b = body()
    ced = req_date(b, "confirmed_effective_date")
    # State guards: the line-level error wins over the parent file's.
    if line["status"] != "PENDING":
        raise ApiError(
            ERR_ROSTER_LINE_NOT_PENDING, 409, "Only a PENDING line can be confirmed"
        )
    if roster_file["status"] != "SUBMITTED":
        raise invalid_state("The roster file is not SUBMITTED")
    if ced == line["expected_effective_date"]:
        _apply_line_effects(roster_file, line, ced)
        line["status"] = "CONFIRMED"
        line["confirmed_effective_date"] = ced
        touch(line)
    else:
        # Date mismatch: DISCREPANCY; enrollment effects deferred until resolve.
        line["status"] = "DISCREPANCY"
        line["confirmed_effective_date"] = ced
        touch(line)
    recompute_roster_rollup(roster_file, bump=True)
    return success_object(pub(line))


@bp.post("/api/roster-files/<fid>/lines/<lid>/reject")
@require_roles("PayerRepresentative")
def reject_line(fid, lid):
    roster_file = _get_file(fid)
    line = _get_line(roster_file, lid)
    b = body()
    reason = req_str(b, "reason")
    if line["status"] != "PENDING":
        raise ApiError(
            ERR_ROSTER_LINE_NOT_PENDING, 409, "Only a PENDING line can be rejected"
        )
    if roster_file["status"] != "SUBMITTED":
        raise invalid_state("The roster file is not SUBMITTED")
    line["status"] = "REJECTED"
    line["rejection_reason"] = reason
    touch(line)
    recompute_roster_rollup(roster_file, bump=True)
    return success_object(pub(line))


@bp.post("/api/roster-files/<fid>/lines/<lid>/resolve")
@require_roles("EnrollmentSpecialist")
def resolve_line(fid, lid):
    roster_file = _get_file(fid)
    line = _get_line(roster_file, lid)
    b = body()
    accept = req_bool(b, "accept_confirmed")
    if line["status"] != "DISCREPANCY":
        raise ApiError(
            ERR_ROSTER_LINE_NOT_PENDING, 409, "Only a DISCREPANCY line can be resolved"
        )
    if accept:
        # Apply the deferred confirmation effects at the confirmed date, under
        # the same guards as a clean confirm.
        _apply_line_effects(roster_file, line, line["confirmed_effective_date"])
        line["status"] = "CONFIRMED"
        touch(line)
    else:
        line["status"] = "REJECTED"
        line["rejection_reason"] = "DISCREPANCY_DECLINED"
        touch(line)
    recompute_roster_rollup(roster_file, bump=True)
    return success_object(pub(line))


@bp.post("/api/roster-files/<fid>/reconcile")
@require_roles("ComplianceOfficer")
def reconcile_roster_file(fid):
    roster_file = _get_file(fid)
    # Segregation of duties: the submitter never reconciles their own roster.
    if g.user_id == roster_file["submitted_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            403,
            "The roster's submitter may not reconcile it",
        )
    if roster_file["status"] not in ("CONFIRMED", "PARTIALLY_CONFIRMED"):
        raise invalid_state("Only a CONFIRMED or PARTIALLY_CONFIRMED roster can be reconciled")
    roster_file["status"] = "RECONCILED"
    touch(roster_file)
    return success_object(pub(roster_file))
