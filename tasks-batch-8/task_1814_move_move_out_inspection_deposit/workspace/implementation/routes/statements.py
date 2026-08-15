"""DepositStatement endpoints (PRD §3.5): OCC-guarded create-with-supersede,
issuance with the statutory deadline, and compensating reopen."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_STATE_TRANSITION,
    ERR_STATEMENT_ALREADY_ACTIVE,
    ERR_STALE_VERSION,
    ERR_TENANCY_NOT_VACATED,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.calculations import deadline_and_lateness
from services.core import (
    active_dispute_for, jurisdiction_for_tenancy, new_record, public,
    recompute_tenancy_money, refresh_draft_statement_projection, touch,
)
from util import CLOCK
from validate import get_body, req_int, req_str, require_body_ref, require_path_resource

bp = Blueprint("statements", __name__)


def _revert_billed_lines(statement):
    """Compensating action: this statement's BILLED lines revert to DRAFT
    with statement_id cleared."""
    for d in db["deductions"].values():
        if d["statement_id"] == statement["id"] and d["status"] == "BILLED":
            d["status"] = "DRAFT"
            d["statement_id"] = None
            touch(d)


@bp.post("/pm/statements")
def create_statement():
    authorized(["PropertyManager"])
    body = get_body()
    tenancy_id = req_str(body, "tenancy_id")
    expected_version = req_int(body, "expected_tenancy_version", non_negative=True)
    tenancy = require_body_ref("tenancies", tenancy_id, "tenancy_id")
    # OCC guard (PRD §2.8): creating against a tenancy whose version advanced
    # since the client last observed it is rejected with 412.
    if expected_version != tenancy["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_tenancy_version does not match the tenancy's "
                    "current version")
    if tenancy["status"] not in ("NOTICE_GIVEN", "VACATED"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    "statements may be created only while NOTICE_GIVEN or VACATED")
    existing = [s for s in db["statements"].values() if s["tenancy_id"] == tenancy["id"]]
    # One active statement per tenancy: DRAFT or ISSUED blocks creation.
    if any(s["status"] in ("DRAFT", "ISSUED") for s in existing):
        raise_error(ERR_STATEMENT_ALREADY_ACTIVE,
                    "a DRAFT or ISSUED statement already exists for the tenancy")
    # Create-with-supersede: a DISPUTED predecessor flips to SUPERSEDED, its
    # billed lines compensate back to DRAFT, and its active dispute withdraws.
    for s in existing:
        if s["status"] == "DISPUTED":
            s["status"] = "SUPERSEDED"
            touch(s)
            _revert_billed_lines(s)
            dispute = active_dispute_for(s["id"])
            if dispute is not None:
                dispute["status"] = "WITHDRAWN"
                touch(dispute)
    seq = max((s["statement_seq"] for s in existing), default=0) + 1
    rec = new_record("statements", {
        "tenancy_id": tenancy["id"],
        "statement_seq": seq,
        "issued_at": None,
        "deadline_on": None,
        "late": None,
        "interest_cents": 0,
        "deduction_total_cents": 0,
        "released_cents": 0,
        "refund_due_cents": 0,
        "projected_deductions_cents": 0,
        "projected_refund_cents": 0,
        "status": "DRAFT",
    })
    recompute_tenancy_money(tenancy["id"])
    # While DRAFT, projections shadow the tenancy's live pending figures.
    rec["projected_deductions_cents"] = tenancy["pending_deductions_cents"]
    rec["projected_refund_cents"] = (
        tenancy["deposit_cents"]
        + tenancy["interest_accrued_cents"]
        - tenancy["pending_deductions_cents"]
    )
    touch(tenancy)
    return success_object(public(rec), status=201)


@bp.get("/pm/statements/<rid>")
def get_statement(rid):
    return get_one("statements", rid)


@bp.get("/pm/statements")
def list_statements():
    return list_response("statements", {
        "tenancy_id": request.args.get("tenancy_id"),
        "status": request.args.get("status"),
    })


@bp.post("/pm/statements/<rid>/issue")
def issue_statement(rid):
    authorized(["PropertyManager"])
    get_body()
    statement = require_path_resource("statements", rid)
    if statement["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"issue requires a DRAFT statement, got {statement['status']}")
    tenancy = db["tenancies"].get(statement["tenancy_id"])
    if tenancy["status"] != "VACATED":
        raise_error(ERR_TENANCY_NOT_VACATED,
                    "statement issuance requires the tenancy VACATED")
    jur = jurisdiction_for_tenancy(tenancy)
    issued_dt = CLOCK.now()
    deadline_on, late = deadline_and_lateness(tenancy["move_out_on"], issued_dt, jur)
    # Sweep every DRAFT deduction of the tenancy to BILLED — billed even when
    # late; lateness is exposed via the late flag and the multiplier.
    swept = [d for d in db["deductions"].values()
             if d["tenancy_id"] == tenancy["id"] and d["status"] == "DRAFT"]
    swept.sort(key=lambda d: d["_seq"])
    for d in swept:
        d["status"] = "BILLED"
        d["statement_id"] = statement["id"]
        touch(d)
    statement["issued_at"] = CLOCK.now_iso()
    statement["deadline_on"] = deadline_on
    statement["late"] = late
    statement["interest_cents"] = tenancy["interest_accrued_cents"]
    # Per-line rounding happened at line creation; the total is the plain sum.
    statement["deduction_total_cents"] = sum(d["amount_cents"] for d in swept)
    statement["refund_due_cents"] = (
        tenancy["deposit_cents"]
        + statement["interest_cents"]
        - statement["deduction_total_cents"]
    )
    statement["status"] = "ISSUED"
    touch(statement)
    recompute_tenancy_money(tenancy["id"])
    touch(tenancy)
    return success_object(public(statement))


@bp.post("/pm/statements/<rid>/reopen")
def reopen_statement(rid):
    authorized(["PropertyManager"])
    get_body()
    statement = require_path_resource("statements", rid)
    if statement["status"] != "DISPUTED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"reopen requires a DISPUTED statement, got {statement['status']}")
    # Precondition: an active dispute (OPEN, MANAGER_COUNTERED, or
    # ESCALATED_SMALL_CLAIMS) rides on this statement; it is withdrawn.
    dispute = active_dispute_for(statement["id"])
    if dispute is not None:
        dispute["status"] = "WITHDRAWN"
        touch(dispute)
    _revert_billed_lines(statement)
    statement["status"] = "DRAFT"
    statement["released_cents"] = 0
    statement["refund_due_cents"] = 0
    statement["issued_at"] = None
    statement["deadline_on"] = None
    statement["late"] = None
    tenancy = db["tenancies"].get(statement["tenancy_id"])
    recompute_tenancy_money(tenancy["id"])
    # Projections shadow the live pending figures again while DRAFT.
    statement["projected_deductions_cents"] = tenancy["pending_deductions_cents"]
    statement["projected_refund_cents"] = (
        tenancy["deposit_cents"]
        + tenancy["interest_accrued_cents"]
        - tenancy["pending_deductions_cents"]
    )
    touch(statement)
    touch(tenancy)
    return success_object(public(statement))
