"""Case endpoints: open, get, list, close, payments (PRD §3.2, §3.10)."""

from flask import Blueprint, g, request

from clock import clock
from db import db, common_fields, touch
from errors import err
from middleware import require_roles
from response import success, list_success
from services import domain, serialize
from services.helpers import (
    get_body,
    lookup,
    pagination_params,
    paginate,
    require_int,
    resolve_ref,
    sort_by_created,
)

bp = Blueprint("cases", __name__)


@bp.post("/cases")
@require_roles("CodeOfficer")
def open_case():
    body = get_body()
    if "property_id" not in body or body["property_id"] is None:
        raise err("ERR_INVALID_REQUEST", "missing required field: property_id")
    prop = resolve_ref(db.properties, body["property_id"])

    # Single-active-case rule: a property with a non-CLOSED case rejects a new one
    # (PRD §3.2, ERR_PROPERTY_HAS_OPEN_CASE).
    for c in db.cases.values():
        if c["property_id"] == prop["id"]:
            domain.refresh_case_for_read(c)
            if c["posture"] != "CLOSED":
                raise err("ERR_PROPERTY_HAS_OPEN_CASE", "property already has an open case")

    record = common_fields()
    record.update({
        "property_id": prop["id"],
        "opened_by_user_id": g.user_id,
        "posture": "INTAKE",
        "outstanding_balance_cents": 0,
        "payments_applied_cents": 0,
        "closed_at": None,
    })
    db.cases[record["id"]] = record
    return success(serialize.case_out(record), status=201)


@bp.get("/cases/<cid>")
@require_roles("PlatformAdmin", "CodeOfficer", "FinanceClerk", "Registrant")
def get_case(cid):
    case = lookup(db.cases, cid)
    # Live recompute on read without bumping case version (PRD §2.5).
    domain.refresh_case_for_read(case)
    return success(serialize.case_out(case), status=200)


@bp.get("/cases")
@require_roles("PlatformAdmin", "CodeOfficer", "FinanceClerk")
def list_cases():
    limit, offset = pagination_params()
    items = list(db.cases.values())
    property_id = request.args.get("property_id")
    if property_id is not None:
        items = [c for c in items if c["property_id"] == property_id]
    items = sort_by_created(items)
    for c in items:
        domain.refresh_case_for_read(c)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([serialize.case_out(c) for c in page], limit, offset, total)


@bp.post("/cases/<cid>/close")
@require_roles("FinanceClerk")
def close_case(cid):
    case = lookup(db.cases, cid)
    domain.refresh_case_for_read(case)

    # A CLOSED case is terminal and cannot be re-closed (PRD §2.5).
    if case["posture"] == "CLOSED":
        raise err("ERR_INVALID_STATE", "case is already closed")

    # The binding close gate (PRD §3.2): every ViolationNotice on the case must be in
    # a benign terminal state {COMPLIED, DISMISSED, SETTLED}, and the outstanding
    # balance must be exactly zero. The PRD names a single close error —
    # "If the balance is still nonzero, the close is rejected with
    # ERR_BALANCE_OUTSTANDING" — and assigns NO error to the notice-status condition.
    # Whenever a notice is non-benign (ISSUED/OVERDUE/CONTESTED/UPHELD) it carries a
    # positive fine_total_cents that lands in outstanding_balance_cents (PRD §3.10),
    # so a non-benign notice always implies a nonzero balance. We therefore evaluate
    # the PRD-named balance condition first; it subsumes the notice-status failure and
    # surfaces the only error the PRD assigns to a blocked close.
    if case["outstanding_balance_cents"] != 0:
        raise err("ERR_BALANCE_OUTSTANDING", "outstanding balance must be zero to close")

    # Defensive guard for the (unreachable-with-nonzero-balance) case of a non-benign
    # notice whose fine_total is somehow zero; the PRD names no error here, so reuse
    # the state-legality error.
    for n in domain.notices_for_case(case["id"]):
        if n["status"] not in ("COMPLIED", "DISMISSED", "SETTLED"):
            raise err("ERR_INVALID_STATE", "not all notices are in a benign terminal state")

    case["closed_at"] = clock.now()
    domain.recompute_case(case)  # posture -> CLOSED, bumps version
    return success(serialize.case_out(case), status=200)


@bp.post("/cases/<cid>/payments")
@require_roles("FinanceClerk")
def post_payment(cid):
    case = lookup(db.cases, cid)
    body = get_body()
    amount = require_int(body, "amount_cents")
    if "expected_case_version" not in body or body["expected_case_version"] is None:
        raise err("ERR_INVALID_REQUEST", "missing required field: expected_case_version")
    expected = body["expected_case_version"]

    # Evaluate notices lazily so OVERDUE crossing is current before allocation.
    for n in domain.notices_for_case(case["id"]):
        domain.evaluate_notice(n)

    # OCC: expected_case_version must equal current version (PRD §2.7, §3.10).
    if expected != case["version"]:
        raise err("ERR_STALE_VERSION", "expected_case_version does not match current version")

    now = clock.now()
    case["payments_applied_cents"] += amount

    # Allocate to OPEN CITATION/ABATEMENT_COST fines, oldest-first by created_at.
    open_fines = [
        f for f in domain.fines_for_case(case["id"])
        if f["source_kind"] in ("CITATION", "ABATEMENT_COST") and f["settlement_status"] == "OPEN"
    ]
    open_fines = sort_by_created(open_fines)

    remaining = amount
    fully_covered_fine_ids = set()
    for f in open_fines:
        if remaining >= (f["assessed_cents"] or 0):
            remaining -= (f["assessed_cents"] or 0)
            fully_covered_fine_ids.add(f["id"])
        else:
            # Partial coverage stops here; remaining fines stay OPEN.
            break

    # A notice all of whose OPEN fines are fully covered settles (PRD §3.10).
    for n in domain.notices_for_case(case["id"]):
        notice_open_fines = [
            f for f in domain.fines_for_notice(n["id"])
            if f["source_kind"] == "CITATION" and f["settlement_status"] == "OPEN"
        ]
        if not notice_open_fines:
            continue
        if all(f["id"] in fully_covered_fine_ids for f in notice_open_fines):
            if n["status"] in ("UPHELD", "OVERDUE"):
                if n["status"] == "OVERDUE":
                    domain.freeze_fine(n, now)
                n["status"] = "SETTLED"
                touch(n)
                for f in notice_open_fines:
                    f["settlement_status"] = "SETTLED"
                    touch(f)

    domain.recompute_case(case)  # bumps version (+1)
    return success(serialize.case_out(case), status=201)
