"""Programme change notices, announcement and grandfathering (PRD 3.10)."""

from flask import Blueprint, request

from auth import caller_id, endpoint, require_sod
from core import (
    DB,
    add_days,
    clock_dt,
    clock_iso,
    find,
    fmt_dt,
    must_find,
    new_row,
    ok,
    parse_dt,
    store,
    touch,
)
from errors import ApiError, invalid
from rhelp import require_agreement_active, require_state
from shapes import body, opt_int, opt_string, req_dt, req_enum, req_int, req_string
from views import ADMIN, APPROVER, OPS_CARD, listing, plain

bp = Blueprint("notices", __name__)

CHANGE_TYPES = ("TRANSFER_RATIO_CHANGE", "EARN_MULTIPLIER_CUT", "BENEFIT_REMOVAL")
NOTICE_PERIOD_DAYS = 45


@bp.post("/change-notices")
@endpoint(ADMIN)
def create_notice():
    data = body()
    target_agreement_id = data.get("target_agreement_id")
    if isinstance(target_agreement_id, str) and target_agreement_id.strip() != "":
        must_find("agreements", target_agreement_id)
    else:
        target_agreement_id = None
    supersedes_notice_id = data.get("supersedes_notice_id")
    if isinstance(supersedes_notice_id, str) and supersedes_notice_id.strip() != "":
        must_find("notices", supersedes_notice_id)
    else:
        supersedes_notice_id = None

    notice_code = req_string(data, "notice_code")
    change_type = req_enum(data, "change_type", CHANGE_TYPES)
    new_ratio_points_out = opt_int(data, "new_ratio_points_out", minimum=1, multiple_of=1000)
    new_ratio_partner_units_in = opt_int(data, "new_ratio_partner_units_in", minimum=1)
    effective_at = req_dt(data, "effective_at")
    grandfather_window_days = req_int(data, "grandfather_window_days", minimum=0)
    cohort_enrolled_before = req_dt(data, "cohort_enrolled_before")

    for other in DB["notices"].values():
        if other["notice_code"] == notice_code:
            raise ApiError(
                "ERR_DUPLICATE_PROGRAM_CODE",
                "Notice code '%s' is already in use." % notice_code,
            )

    row = store(
        "notices",
        new_row(
            "notices",
            {
                "notice_code": notice_code,
                "change_type": change_type,
                "target_agreement_id": target_agreement_id,
                "new_ratio_points_out": new_ratio_points_out,
                "new_ratio_partner_units_in": new_ratio_partner_units_in,
                "supersedes_notice_id": supersedes_notice_id,
                "effective_at": fmt_dt(effective_at),
                "grandfather_window_days": grandfather_window_days,
                "cohort_enrolled_before": fmt_dt(cohort_enrolled_before),
                "status": "DRAFT",
                "announced_at": None,
                "drafted_by_user_id": caller_id(),
                "approved_by_user_id": None,
                "withdrawn_reason": None,
            },
        ),
    )
    return ok(plain(row), 201)


@bp.get("/change-notices/<notice_id>")
@endpoint(OPS_CARD)
def read_notice(notice_id):
    return ok(plain(must_find("notices", notice_id)))


@bp.get("/change-notices")
@endpoint(OPS_CARD)
def list_notices():
    args = request.args
    filters = {
        "status": args.get("status"),
        "change_type": args.get("change_type"),
        "target_agreement_id": args.get("target_agreement_id"),
        "supersedes_notice_id": args.get("supersedes_notice_id"),
    }
    return listing("notices", args, filters)


@bp.post("/change-notices/<notice_id>/submit")
@endpoint(ADMIN)
def submit_notice(notice_id):
    notice = must_find("notices", notice_id)
    require_state(notice, ("DRAFT",))
    if notice["change_type"] == "TRANSFER_RATIO_CHANGE":
        if notice["target_agreement_id"]:
            agreement = find("agreements", notice["target_agreement_id"])
            if agreement is not None:
                require_agreement_active(agreement)
        if (
            not notice["target_agreement_id"]
            or notice["new_ratio_points_out"] is None
            or notice["new_ratio_partner_units_in"] is None
        ):
            raise ApiError(
                "ERR_NOTICE_TARGET_REQUIRED",
                "A TRANSFER_RATIO_CHANGE notice requires its target and both ratio terms.",
            )
    notice["status"] = "PENDING_APPROVAL"
    touch(notice)
    return ok(plain(notice))


@bp.post("/change-notices/<notice_id>/revise")
@endpoint(APPROVER)
def revise_notice(notice_id):
    notice = must_find("notices", notice_id)
    require_state(notice, ("PENDING_APPROVAL",))
    notice["status"] = "DRAFT"
    touch(notice)
    return ok(plain(notice))


@bp.post("/change-notices/<notice_id>/announce")
@endpoint(APPROVER)
def announce_notice(notice_id):
    notice = must_find("notices", notice_id)
    require_sod(notice["drafted_by_user_id"])
    require_state(notice, ("PENDING_APPROVAL",))
    if parse_dt(notice["effective_at"]) < add_days(clock_dt(), NOTICE_PERIOD_DAYS):
        raise ApiError(
            "ERR_NOTICE_PERIOD_TOO_SHORT",
            "A notice must be announced at least %d days before it takes effect."
            % NOTICE_PERIOD_DAYS,
        )
    notice["status"] = "ANNOUNCED"
    notice["announced_at"] = clock_iso()
    notice["approved_by_user_id"] = caller_id()
    touch(notice)
    if notice["supersedes_notice_id"]:
        superseded = find("notices", notice["supersedes_notice_id"])
        if superseded is not None and superseded["status"] == "ANNOUNCED":
            superseded["status"] = "WITHDRAWN"
            superseded["withdrawn_reason"] = "SUPERSEDED"
            touch(superseded)
    return ok(plain(notice))


@bp.post("/change-notices/<notice_id>/withdraw")
@endpoint(ADMIN)
def withdraw_notice(notice_id):
    notice = must_find("notices", notice_id)
    reason = req_string(body(), "withdrawn_reason")
    require_state(notice, ("ANNOUNCED",))
    notice["status"] = "WITHDRAWN"
    notice["withdrawn_reason"] = reason
    touch(notice)
    return ok(plain(notice))
