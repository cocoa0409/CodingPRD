"""Lien endpoints: record, get, list, release, foreclose (PRD §3.12)."""

from datetime import timedelta

from flask import Blueprint, request

from clock import clock
from db import db, common_fields, touch
from errors import err
from middleware import require_roles
from response import success, list_success
from services import calc, domain, serialize
from services.constants import FORECLOSURE_WAIT_DAYS
from services.helpers import (
    get_body,
    lookup,
    pagination_params,
    paginate,
    resolve_ref,
    sort_by_created,
)

bp = Blueprint("liens", __name__)


@bp.post("/liens")
@require_roles("FinanceClerk")
def record_lien():
    body = get_body()
    if "case_id" not in body or body["case_id"] is None:
        raise err("ERR_INVALID_REQUEST", "missing required field: case_id")
    if "expected_case_version" not in body or body["expected_case_version"] is None:
        raise err("ERR_INVALID_REQUEST", "missing required field: expected_case_version")
    case = resolve_ref(db.cases, body["case_id"])
    expected = body["expected_case_version"]

    # Evaluate notices so OVERDUE crossing/balance are current before guards.
    for n in domain.notices_for_case(case["id"]):
        domain.evaluate_notice(n)
    case["outstanding_balance_cents"] = domain.compute_balance(case)

    now = clock.now()

    # Business-rule ordering per PRD §2.9: after state legality come the operation's
    # own constraints. For lien recording the explicit checks (§3.12) are: duplicate
    # lien, nothing-to-lien, then OCC stale-version. The validations table also lists
    # ERR_LIEN_ALREADY_EXISTS (14), ERR_NOTHING_TO_LIEN (15), ERR_STALE_VERSION (16)
    # in that priority order.
    if any(l["status"] in ("PENDING", "RECORDED") for l in domain.liens_for_case(case["id"])):
        raise err("ERR_LIEN_ALREADY_EXISTS", "case already has a pending/recorded lien")

    if case["outstanding_balance_cents"] <= 0:
        raise err("ERR_NOTHING_TO_LIEN", "no outstanding balance to lien")

    if expected != case["version"]:
        raise err("ERR_STALE_VERSION", "expected_case_version does not match current version")

    # Freeze every OPEN CITATION Fine on an OVERDUE/UPHELD notice: assessed_cents :=
    # that notice's settlement fine_total_cents as-of the recording instant (PRD §3.12).
    for n in domain.notices_for_case(case["id"]):
        if n["status"] in ("OVERDUE", "UPHELD"):
            total = domain.freeze_fine(n, now)
            for f in domain.fines_for_notice(n["id"]):
                if f["source_kind"] == "CITATION" and f["settlement_status"] == "OPEN":
                    f["assessed_cents"] = total
                    touch(f)

    # Compute lien amount over the now-frozen OPEN Fine ledger lines.
    open_citation = sum(
        f["assessed_cents"] or 0
        for f in domain.fines_for_case(case["id"])
        if f["source_kind"] == "CITATION" and f["settlement_status"] == "OPEN"
    )
    open_abatement = sum(
        f["assessed_cents"] or 0
        for f in domain.fines_for_case(case["id"])
        if f["source_kind"] == "ABATEMENT_COST" and f["settlement_status"] == "OPEN"
    )
    principal, admin_fee, total = calc.lien_amount(open_citation, open_abatement)

    record = common_fields()
    record.update({
        "case_id": case["id"],
        "property_id": case["property_id"],
        "principal_cents": principal,
        "admin_fee_cents": admin_fee,
        "total_cents": total,
        "status": "RECORDED",
    })
    db.liens[record["id"]] = record

    # Recompute case (-> LIENED), bump version.
    domain.recompute_case(case)
    return success(serialize.lien_out(record), status=201)


@bp.get("/liens/<lid>")
@require_roles("PlatformAdmin", "CodeOfficer", "FinanceClerk", "Registrant")
def get_lien(lid):
    record = lookup(db.liens, lid)
    return success(serialize.lien_out(record), status=200)


@bp.get("/liens")
@require_roles("PlatformAdmin", "CodeOfficer", "FinanceClerk", "Registrant")
def list_liens():
    limit, offset = pagination_params()
    items = list(db.liens.values())
    case_id = request.args.get("case_id")
    property_id = request.args.get("property_id")
    if case_id is not None:
        items = [l for l in items if l["case_id"] == case_id]
    if property_id is not None:
        items = [l for l in items if l["property_id"] == property_id]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([serialize.lien_out(l) for l in page], limit, offset, total)


@bp.post("/liens/<lid>/release")
@require_roles("FinanceClerk")
def release_lien(lid):
    lien = lookup(db.liens, lid)
    if lien["status"] != "RECORDED":
        raise err("ERR_INVALID_STATE", "lien is not RECORDED")
    case = db.cases.get(lien["case_id"])
    # Paid in full: payments_applied_cents >= lien.total_cents (PRD §3.12).
    if case is None or case["payments_applied_cents"] < lien["total_cents"]:
        raise err("ERR_BALANCE_OUTSTANDING", "lien is not paid in full")

    lien["status"] = "RELEASED"
    touch(lien)

    # Settle all remaining OPEN citation/abatement-cost fines on the case.
    for f in domain.fines_for_case(case["id"]):
        if f["source_kind"] in ("CITATION", "ABATEMENT_COST") and f["settlement_status"] == "OPEN":
            f["settlement_status"] = "SETTLED"
            touch(f)
    # Move any non-terminal notices on the case to SETTLED so balance -> 0.
    for n in domain.notices_for_case(case["id"]):
        if n["status"] in ("OVERDUE", "UPHELD"):
            n["status"] = "SETTLED"
            touch(n)

    domain.recompute_case(case)
    return success(serialize.lien_out(lien), status=200)


@bp.post("/liens/<lid>/foreclose")
@require_roles("FinanceClerk")
def foreclose_lien(lid):
    lien = lookup(db.liens, lid)
    if lien["status"] != "RECORDED":
        raise err("ERR_INVALID_STATE", "lien is not RECORDED")
    now = clock.now()
    ripe_at = lien["created_at"] + timedelta(days=FORECLOSURE_WAIT_DAYS)
    if now < ripe_at:
        raise err("ERR_FORECLOSURE_NOT_RIPE", "foreclosure waiting period not elapsed")
    lien["status"] = "FORECLOSED"
    touch(lien)
    case = db.cases.get(lien["case_id"])
    if case is not None:
        domain.recompute_case(case)
    return success(serialize.lien_out(lien), status=200)
