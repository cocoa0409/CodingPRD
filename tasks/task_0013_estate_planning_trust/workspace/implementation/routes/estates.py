"""Estate routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
from common import (
    get_body,
    pagination_params,
    require_field,
    require_int,
    require_string,
    stamp_common_fields,
    touch,
)
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_SHARE_NOT_FULLY_ALLOCATED,
    ERR_STALE_ESTATE_VERSION,
    forbidden,
    invalid_state,
    not_found,
    stale_version,
)
from middleware import require_roles
from response import created, list_response, success
from services.calculations import (
    compute_net_taxable,
    intestacy_shares,
    recompute_and_store_gross,
    recompute_and_store_net,
)
from services.cascades import cascade_contest
from views import view_estate


bp = Blueprint("estates", __name__)


@bp.post("/estates")
@require_roles("EstatePlanner")
def create_estate():
    body = get_body()
    decedent_id = require_string(body, "decedent_id")
    if decedent_id not in db.decedents:
        raise not_found("Decedent")

    now = db.now_utc()
    estate = {
        "decedent_id": decedent_id,
        "status": "DRAFT",
        "gross_estate_value_cents": 0,
        "net_taxable_estate_cents": 0,
        "inventory_snapshot_gross_cents": None,
        "executor_user_id": None,
        "probate_filed_at": None,
        "probate_opened_at": None,
        "closed_at": None,
        "_net_taxable_has_run": False,
    }
    stamp_common_fields(estate, now)
    db.estates[estate["id"]] = estate
    return created(view_estate(estate))


@bp.get("/estates/<estate_id>")
@require_roles("EstatePlanner", "Executor", "Judge", "Beneficiary")
def get_estate(estate_id: str):
    e = db.estates.get(estate_id)
    if e is None:
        raise not_found("Estate")
    return success(view_estate(e))


@bp.get("/estates")
@require_roles("EstatePlanner", "Judge")
def list_estates():
    limit, offset = pagination_params()
    decedent_id = request.args.get("decedent_id")
    status = request.args.get("status")
    executor_user_id = request.args.get("executor_user_id")

    items = list(db.estates.values())
    if decedent_id is not None:
        items = [e for e in items if e["decedent_id"] == decedent_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if executor_user_id is not None:
        items = [e for e in items if e.get("executor_user_id") == executor_user_id]

    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = [view_estate(e) for e in items[offset:offset + limit]]
    return list_response(page, limit=limit, offset=offset, total_count=total)


@bp.post("/estates/<estate_id>/finalize-plan")
@require_roles("EstatePlanner")
def finalize_plan(estate_id: str):
    e = db.estates.get(estate_id)
    if e is None:
        raise not_found("Estate")
    if e["status"] != "DRAFT":
        raise invalid_state("Estate must be in DRAFT to finalize.")

    decedent = db.decedents.get(e["decedent_id"])
    if decedent is None:
        raise not_found("Decedent")
    if decedent.get("date_of_death") is not None:
        raise invalid_state("Decedent already deceased; cannot finalize plan.")

    estate_assets = [a for a in db.assets.values() if a["estate_id"] == estate_id]
    eligible = [a for a in estate_assets if a["status"] in ("DRAFT", "INCLUDED")]
    if not eligible:
        raise invalid_state("Estate must have at least one Asset in DRAFT or INCLUDED.")

    designations = [b for b in db.beneficiary_designations.values() if b["estate_id"] == estate_id]
    # PRD §3.1: sum across "designations being promoted to ACTIVE" must equal 10000.
    # That means DRAFT designations being promoted + already-ACTIVE designations.
    promo = [b for b in designations if b["status"] in ("DRAFT", "ACTIVE")]
    share_sum = sum(b["share_basis_points"] for b in promo)
    if share_sum != 10000:
        raise APIError(
            ERR_SHARE_NOT_FULLY_ALLOCATED,
            f"Sum of share_basis_points across designations being promoted to ACTIVE must equal 10000 (got {share_sum}).",
            422,
        )

    now = db.now_utc()
    # Cascade: DRAFT Assets -> INCLUDED; DRAFT Designations -> ACTIVE
    for a in estate_assets:
        if a["status"] == "DRAFT":
            a["status"] = "INCLUDED"
            touch(a, now)
    for b in promo:
        if b["status"] == "DRAFT":
            b["status"] = "ACTIVE"
            touch(b, now)

    e["status"] = "ALIVE"
    recompute_and_store_gross(e)
    recompute_and_store_net(e)
    touch(e, now)
    return success(view_estate(e))


@bp.post("/estates/<estate_id>/file-for-probate")
@require_roles("Executor")
def file_for_probate(estate_id: str):
    e = db.estates.get(estate_id)
    if e is None:
        raise not_found("Estate")
    if e["status"] != "DECEASED":
        raise invalid_state("Estate must be DECEASED to file for probate.")

    # Precondition: Executor with role_type=EXECUTOR on this estate has status=ACCEPTED.
    accepted = None
    for x in db.executors.values():
        if (
            x["estate_id"] == estate_id
            and x["role_type"] == "EXECUTOR"
            and x["status"] == "ACCEPTED"
        ):
            accepted = x
            break
    if accepted is None or e.get("executor_user_id") is None:
        raise invalid_state("No ACCEPTED executor on this estate.")

    # Ownership: the calling Executor must be that executor (entity_backed identity).
    from flask import g
    if g.user_id != accepted["id"]:
        raise forbidden("Only the accepted executor of this estate may file for probate.")

    now = db.now_utc()
    e["status"] = "PROBATE_PENDING"
    e["probate_filed_at"] = now
    touch(e, now)
    return success(view_estate(e))


@bp.post("/estates/<estate_id>/contest")
@require_roles("Beneficiary")
def contest_estate(estate_id: str):
    e = db.estates.get(estate_id)
    if e is None:
        raise not_found("Estate")
    if e["status"] != "PROBATE_OPEN":
        raise invalid_state("Estate must be in PROBATE_OPEN to be contested.")

    # Beneficiary ownership: X-User-ID must be the id of a BeneficiaryDesignation
    # on this estate.
    from flask import g
    designation = db.beneficiary_designations.get(g.user_id)
    if designation is None or designation["estate_id"] != estate_id:
        raise forbidden("Calling Beneficiary is not on this estate.")

    body = get_body()
    expected_v = require_int(body, "expected_estate_version")
    require_string(body, "reason")  # required by endpoint table

    if expected_v != e["version"]:
        raise stale_version()

    now = db.now_utc()
    cascade_contest(e, now)
    return success(view_estate(e))


@bp.post("/estates/<estate_id>/resolve-contest")
@require_roles("Judge")
def resolve_contest(estate_id: str):
    e = db.estates.get(estate_id)
    if e is None:
        raise not_found("Estate")
    if e["status"] != "CONTESTED":
        raise invalid_state("Estate must be CONTESTED to resolve.")

    body = get_body()
    require_string(body, "resolution_note")

    now = db.now_utc()
    e["status"] = "PROBATE_OPEN"
    touch(e, now)
    return success(view_estate(e))


@bp.post("/estates/<estate_id>/compute-intestacy-shares")
@require_roles("Judge", "EstatePlanner")
def compute_intestacy(estate_id: str):
    e = db.estates.get(estate_id)
    if e is None:
        raise not_found("Estate")
    decedent = db.decedents.get(e["decedent_id"])
    if decedent is None:
        raise not_found("Decedent")
    result = intestacy_shares(e, decedent)
    return success(result)


@bp.get("/estates/<estate_id>/net-taxable-summary")
@require_roles("EstatePlanner", "Executor", "Judge")
def net_taxable_summary(estate_id: str):
    e = db.estates.get(estate_id)
    if e is None:
        raise not_found("Estate")
    summary = compute_net_taxable(e)
    # Store the result so the "has run" precondition for CLOSE_ESTATE is met.
    e["net_taxable_estate_cents"] = summary["net_taxable_estate_cents"]
    e["_net_taxable_has_run"] = True
    return success(summary)
