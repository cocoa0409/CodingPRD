"""Supervisee endpoints: open case, lifecycle, compliance, payoff (PRD §3.1, §3.7, §3.10)."""
from flask import Blueprint, g, request

import clock
import db
from calculations import compliance_rate, projected_outstanding
from errors import (
    ApiError,
    ERR_DUPLICATE_KEY,
    ERR_OFFICER_ROLE_MISMATCH,
    ERR_REFERENCE_NOT_FOUND,
)
from middleware import require_roles
from response import object_response, array_response
from serialize import public, public_list
from services import supervisee as svc
from services.common import (
    apply_page,
    check_enum,
    get_body,
    get_supervisee_or_404,
    paginate,
    recompute_balances,
    require_datetime,
    require_fields,
    require_int_min,
    require_str,
    sorted_by_created,
)
from timeutil import iso_now, parse_iso

bp = Blueprint("supervisees", __name__)

SUPERVISION_TYPES = {"PROBATION", "PAROLE"}


def _check_state_code(value, field):
    if (
        not isinstance(value, str)
        or len(value) != 2
        or not value.isalpha()
        or not value.isupper()
    ):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be two uppercase letters.")


@bp.post("/supervisees")
@require_roles("Officer")
def create_supervisee():
    body = get_body()
    require_fields(
        body,
        [
            "full_name",
            "docket_number",
            "supervision_type",
            "assigned_officer_id",
            "sentence_state_code",
            "ordered_term_months",
            "supervision_start_date",
        ],
    )
    require_str(body["full_name"], "full_name")
    require_str(body["docket_number"], "docket_number")
    check_enum(body["supervision_type"], SUPERVISION_TYPES, "supervision_type")
    require_str(body["assigned_officer_id"], "assigned_officer_id")
    _check_state_code(body["sentence_state_code"], "sentence_state_code")
    require_int_min(body["ordered_term_months"], 1, "ordered_term_months")
    require_datetime(body["supervision_start_date"], "supervision_start_date")

    # Body FK existence (ERR_REFERENCE_NOT_FOUND, 422) before business checks.
    officer = db.officers.get(body["assigned_officer_id"])
    if officer is None:
        raise ApiError(*ERR_REFERENCE_NOT_FOUND, "assigned_officer_id not found.")

    # Officer role/active fit (ERR_OFFICER_ROLE_MISMATCH, 422).
    if officer["role_type"] != body["supervision_type"] or not officer["active"]:
        raise ApiError(*ERR_OFFICER_ROLE_MISMATCH, "Assigned officer role/active mismatch.")

    # Docket uniqueness (ERR_DUPLICATE_KEY, 409).
    for s in db.supervisees.values():
        if s["docket_number"] == body["docket_number"]:
            raise ApiError(*ERR_DUPLICATE_KEY, "docket_number already exists.")

    rec = db.common_create_fields(versioned=True)
    rec.update(
        {
            "full_name": body["full_name"],
            "docket_number": body["docket_number"],
            "supervision_type": body["supervision_type"],
            "assigned_officer_id": body["assigned_officer_id"],
            "sentence_state_code": body["sentence_state_code"],
            "ordered_term_months": body["ordered_term_months"],
            "supervision_start_date": body["supervision_start_date"],
            "status": "INTAKE",
            "supervision_level": "MINIMUM",
            "cumulative_violation_points": 0,
            "restitution_balance_cents": 0,
            "fee_balance_cents": 0,
        }
    )
    db.supervisees[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/supervisees/<sid>")
@require_roles("Officer", "SupervisingJudge", "CompactAdministrator")
def get_supervisee(sid):
    s = get_supervisee_or_404(sid)
    recompute_balances(s)
    return object_response(public(s), 200)


@bp.get("/supervisees")
@require_roles("Officer", "SupervisingJudge", "CompactAdministrator")
def list_supervisees():
    limit, offset = paginate(request.args)
    records = list(db.supervisees.values())
    assigned = request.args.get("assigned_officer_id")
    if assigned is not None:
        records = [r for r in records if r["assigned_officer_id"] == assigned]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    for r in records:
        recompute_balances(r)
    records = sorted_by_created(records)
    page, total = apply_page(records, limit, offset)
    return array_response(public_list(page), limit, offset, total)


# ---- Lifecycle transitions ----------------------------------------------
@bp.post("/supervisees/<sid>/activate")
@require_roles("Officer")
def activate(sid):
    s = get_supervisee_or_404(sid)
    svc.activate(s)
    return object_response(public(s), 200)


@bp.post("/supervisees/<sid>/abscond")
@require_roles("Officer")
def abscond(sid):
    s = get_supervisee_or_404(sid)
    svc.abscond(s, g.user_id)
    return object_response(public(s), 200)


@bp.post("/supervisees/<sid>/return-to-supervision")
@require_roles("Officer")
def return_to_supervision(sid):
    s = get_supervisee_or_404(sid)
    svc.return_to_supervision(s)
    return object_response(public(s), 200)


@bp.post("/supervisees/<sid>/refer-revocation")
@require_roles("Officer")
def refer_revocation(sid):
    s = get_supervisee_or_404(sid)
    svc.refer_revocation(s)
    return object_response(public(s), 200)


@bp.post("/supervisees/<sid>/revoke")
@require_roles("SupervisingJudge")
def revoke(sid):
    s = get_supervisee_or_404(sid)
    svc.revoke(s)
    return object_response(public(s), 200)


@bp.post("/supervisees/<sid>/reinstate")
@require_roles("SupervisingJudge")
def reinstate(sid):
    s = get_supervisee_or_404(sid)
    svc.reinstate(s)
    return object_response(public(s), 200)


@bp.post("/supervisees/<sid>/complete")
@require_roles("SupervisingJudge")
def complete(sid):
    s = get_supervisee_or_404(sid)
    svc.complete(s)
    return object_response(public(s), 200)


# ---- Computed reads -----------------------------------------------------
@bp.get("/supervisees/<sid>/compliance")
@require_roles("Officer", "SupervisingJudge", "CompactAdministrator")
def compliance(sid):
    s = get_supervisee_or_404(sid)
    recompute_balances(s)
    cis = [c for c in db.check_ins.values() if c.get("supervisee_id") == sid]
    rate = compliance_rate(cis)
    data = {
        "compliance_rate": rate,
        "restitution_balance_cents": s["restitution_balance_cents"],
        "fee_balance_cents": s["fee_balance_cents"],
        "cumulative_violation_points": s["cumulative_violation_points"],
        "supervision_level": s["supervision_level"],
    }
    return object_response(data, 200)


@bp.get("/supervisees/<sid>/payoff-quote")
@require_roles("Officer", "SupervisingJudge", "CompactAdministrator")
def payoff_quote(sid):
    s = get_supervisee_or_404(sid)
    as_of_raw = request.args.get("as_of")
    if as_of_raw is not None:
        as_of_dt = parse_iso(as_of_raw)
        if as_of_dt is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, "as_of must be an ISO 8601 datetime.")
    else:
        as_of_dt = clock.now()
    rest = 0
    fee = 0
    for ob in db.obligations.values():
        if ob.get("supervisee_id") != sid:
            continue
        if ob["status"] not in ("OPEN", "PARTIALLY_PAID"):
            continue
        out = projected_outstanding(ob, as_of_dt)
        if ob["obligation_type"] == "RESTITUTION":
            rest += out
        else:
            fee += out
    data = {
        "projected_restitution_cents": rest,
        "projected_fee_cents": fee,
        "projected_total_cents": rest + fee,
        "as_of": iso_now(as_of_dt),
    }
    return object_response(data, 200)
