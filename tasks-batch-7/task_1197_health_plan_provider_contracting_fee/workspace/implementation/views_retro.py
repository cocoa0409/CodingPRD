"""Retro adjustment runs and adjustments: compute, finalize, void,
adjudication (approve / reject / settle), and the settlement bubble-up."""

from flask import Blueprint, request

import store
from bodycheck import validate_body
from envelope import ok, ok_list
from errors import ApiError
from helpers import get_adjustment, get_paid_claim, get_run, sorted_by_created
from pricing import recompute_run_totals, retro_sweep
from security import INTERNAL_ROLES, ROLE_PAYMENT_INTEGRITY, auth, require_roles

bp = Blueprint("retro", __name__)

NON_TERMINAL_ADJUSTMENT_STATES = ("PROPOSED", "APPROVED")


def _run_invalid_state(action):
    return ApiError(
        "ERR_RUN_INVALID_STATE", 409,
        f"RetroAdjustmentRun state does not permit {action}.",
    )


def _adjustment_invalid_state(action):
    return ApiError(
        "ERR_ADJUSTMENT_INVALID_STATE", 409,
        f"RetroAdjustment state or parent run state does not permit {action}.",
    )


def _parent_contract_id(run):
    version = store.versions.get(run["contract_version_id"])
    return version["contract_id"] if version else None


def _bubble_up_settled(run, role):
    """A FINALIZED run advances itself to SETTLED the moment no adjustment
    remains in a non-terminal (PROPOSED | APPROVED) state."""
    if run["run_status"] != "FINALIZED":
        return
    open_count = sum(
        1 for a in store.adjustments.values()
        if a["retro_run_id"] == run["id"]
        and a["adjustment_status"] in NON_TERMINAL_ADJUSTMENT_STATES
    )
    if open_count == 0:
        run["run_status"] = "SETTLED"
        store.touch(run)
        store.add_audit(_parent_contract_id(run), "RETRO_RUN_SETTLED", role, "system",
                        "Retro adjustment run settled automatically.")


# ---------------------------------------------------------------------------
# Run read / compute / finalize / void
# ---------------------------------------------------------------------------
@bp.get("/retro-adjustment-runs/<rid>")
def get_one_run(rid):
    _, role = auth()
    require_roles(role, INTERNAL_ROLES)
    return ok(dict(get_run(rid)))


@bp.post("/retro-adjustment-runs/<rid>/compute")
def compute_run(rid):
    validate_body({})
    _, role = auth()
    require_roles(role, [ROLE_PAYMENT_INTEGRITY])
    run = get_run(rid)
    if run["run_status"] != "CREATED":
        raise _run_invalid_state("compute (requires CREATED)")
    version = store.versions.get(run["contract_version_id"])
    contract = store.contracts.get(version["contract_id"]) if version else None
    retro_sweep(run, version, contract)
    recompute_run_totals(run)
    run["run_status"] = "COMPUTED"
    store.touch(run)
    return ok(dict(run))


@bp.post("/retro-adjustment-runs/<rid>/finalize")
def finalize_run(rid):
    validate_body({})
    user_id, role = auth()
    require_roles(role, [ROLE_PAYMENT_INTEGRITY])
    run = get_run(rid)
    if run["run_status"] != "COMPUTED":
        raise _run_invalid_state("finalize (requires COMPUTED)")
    # Commit the sweep to the ledger: referenced snapshots become ADJUSTED.
    referenced = {
        a["paid_claim_id"] for a in store.adjustments.values()
        if a["retro_run_id"] == rid and a["adjustment_status"] == "PROPOSED"
    }
    for snapshot_id in referenced:
        snapshot = store.paid_claims.get(snapshot_id)
        if snapshot is not None and snapshot["snapshot_status"] == "OPEN":
            snapshot["snapshot_status"] = "ADJUSTED"
            store.touch(snapshot)
    run["run_status"] = "FINALIZED"
    store.touch(run)
    store.add_audit(_parent_contract_id(run), "RETRO_RUN_FINALIZED", role, user_id,
                    "Retro adjustment run finalized.")
    return ok(dict(run))


@bp.post("/retro-adjustment-runs/<rid>/void")
def void_run(rid):
    validate_body({})
    user_id, role = auth()
    require_roles(role, [ROLE_PAYMENT_INTEGRITY])
    run = get_run(rid)
    if run["run_status"] != "COMPUTED":
        raise _run_invalid_state("void (requires COMPUTED)")
    # Compensation: proposed adjustments are voided; snapshots were never
    # mutated by compute, so the paid ledger emerges unchanged.
    for adjustment in store.adjustments.values():
        if (adjustment["retro_run_id"] == rid
                and adjustment["adjustment_status"] == "PROPOSED"):
            adjustment["adjustment_status"] = "VOIDED"
            store.touch(adjustment)
    run["run_status"] = "VOID"
    run["adjustment_count"] = 0
    run["total_underpaid_cents"] = 0
    run["total_overpaid_cents"] = 0
    run["net_delta_cents"] = 0
    store.touch(run)
    store.add_audit(_parent_contract_id(run), "RETRO_RUN_VOIDED", role, user_id,
                    "Retro adjustment run voided.")
    return ok(dict(run))


@bp.get("/retro-adjustment-runs/<rid>/adjustments")
def list_run_adjustments(rid):
    _, role = auth()
    require_roles(role, INTERNAL_ROLES)
    get_run(rid)
    items = [a for a in store.adjustments.values() if a["retro_run_id"] == rid]
    return ok_list([dict(a) for a in sorted_by_created(items)])


# ---------------------------------------------------------------------------
# Adjustment read / adjudication
# ---------------------------------------------------------------------------
@bp.get("/retro-adjustments")
def list_adjustments_filtered():
    _, role = auth()
    require_roles(role, INTERNAL_ROLES)
    paid_claim_id = request.args.get("paid_claim_id")
    items = store.adjustments.values()
    if paid_claim_id is not None:
        items = [a for a in items if a["paid_claim_id"] == paid_claim_id]
    return ok_list([dict(a) for a in sorted_by_created(items)])


@bp.get("/retro-adjustments/<aid>")
def get_one_adjustment(aid):
    _, role = auth()
    require_roles(role, INTERNAL_ROLES)
    return ok(dict(get_adjustment(aid)))


@bp.post("/retro-adjustments/<aid>/approve")
def approve_adjustment(aid):
    validate_body({})
    _, role = auth()
    require_roles(role, [ROLE_PAYMENT_INTEGRITY])
    adjustment = get_adjustment(aid)
    run = get_run(adjustment["retro_run_id"])
    if (adjustment["adjustment_status"] != "PROPOSED"
            or run["run_status"] not in ("COMPUTED", "FINALIZED")):
        raise _adjustment_invalid_state("approve")
    adjustment["adjustment_status"] = "APPROVED"
    store.touch(adjustment)
    return ok(dict(adjustment))


@bp.post("/retro-adjustments/<aid>/reject")
def reject_adjustment(aid):
    validate_body({})
    _, role = auth()
    require_roles(role, [ROLE_PAYMENT_INTEGRITY])
    adjustment = get_adjustment(aid)
    run = get_run(adjustment["retro_run_id"])
    if (adjustment["adjustment_status"] != "PROPOSED"
            or run["run_status"] not in ("COMPUTED", "FINALIZED")):
        raise _adjustment_invalid_state("reject")
    adjustment["adjustment_status"] = "REJECTED"
    store.touch(adjustment)
    _bubble_up_settled(run, role)
    return ok(dict(adjustment))


@bp.post("/retro-adjustments/<aid>/settle")
def settle_adjustment(aid):
    validate_body({})
    _, role = auth()
    require_roles(role, [ROLE_PAYMENT_INTEGRITY])
    adjustment = get_adjustment(aid)
    run = get_run(adjustment["retro_run_id"])
    if adjustment["adjustment_status"] != "APPROVED":
        raise _adjustment_invalid_state("settle (requires APPROVED)")
    if adjustment["direction"] == "UNDERPAID":
        adjustment["adjustment_status"] = "PAID"
    elif adjustment["direction"] == "OVERPAID":
        adjustment["adjustment_status"] = "RECOVERED"
    else:
        raise _adjustment_invalid_state("settle (unknown direction)")
    store.touch(adjustment)
    _bubble_up_settled(run, role)
    return ok(dict(adjustment))


# ---------------------------------------------------------------------------
# Paid claim snapshot single-read
# ---------------------------------------------------------------------------
@bp.get("/paid-claims/<pid>")
def get_one_paid_claim(pid):
    _, role = auth()
    require_roles(role, INTERNAL_ROLES)
    return ok(dict(get_paid_claim(pid)))
