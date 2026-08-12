"""Claim/work-order hierarchy reconciliation helpers (PRD section 2.9)."""

from db import store, touch

NON_TERMINAL_WO = {"OFFERED", "ACCEPTED", "SCHEDULED", "NO_SHOW"}


def has_non_terminal_work_order(claim_id, exclude_id=None):
    for wo in store.work_orders.values():
        if wo["claim_id"] != claim_id or wo["id"] == exclude_id:
            continue
        if wo["status"] in NON_TERMINAL_WO:
            return True
    return False


def bubble_up_claim(claim_id, exclude_wo_id=None):
    """When the last non-terminal work order of a WORK_AUTHORIZED claim falls
    away, the claim reverts to COVERAGE_VERIFIED and forgets its shop."""
    claim = store.claims.get(claim_id)
    if claim is None or claim["status"] != "WORK_AUTHORIZED":
        return
    if has_non_terminal_work_order(claim_id, exclude_id=exclude_wo_id):
        return
    claim["status"] = "COVERAGE_VERIFIED"
    claim["assigned_shop_id"] = None
    touch(claim)


def claim_transition(claim, to_status):
    claim["status"] = to_status
    touch(claim)
