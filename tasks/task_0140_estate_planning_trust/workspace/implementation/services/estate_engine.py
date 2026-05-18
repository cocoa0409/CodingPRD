"""Estate state machine (SCAFFOLD §1.2, PRD §3.3 / §3.4 / §3.8 / §3.10 / §3.11 / §3.12).

Transitions:
    DRAFT       → IN_PROBATE   (Executor)
    IN_PROBATE  → INVENTORIED  (Executor)
    INVENTORIED → DISTRIBUTING (Executor)
    DISTRIBUTING→ SETTLED      (Executor)
    IN_PROBATE  → CONTESTED    (CourtClerk)
    INVENTORIED → CONTESTED    (CourtClerk)
    CONTESTED   → IN_PROBATE   (CourtClerk)

Cascades / side effects per §1.2.
"""
from __future__ import annotations

from datetime import timedelta

from config import SETTLEMENT_WINDOW_DAYS
from db import store
from errors import ApiError
from services.calculations import (
    compute_gross_estate_value,
    compute_planned_distributions,
    compute_probate_posture,
    compute_required_bond,
    recompute_estate_gross,
)
from services.common import bump

# ── Allowed transition map per role ────────────────────────────────────────

ALLOWED_TRANSITIONS = {
    ("DRAFT", "IN_PROBATE"): "Executor",
    ("IN_PROBATE", "INVENTORIED"): "Executor",
    ("INVENTORIED", "DISTRIBUTING"): "Executor",
    ("DISTRIBUTING", "SETTLED"): "Executor",
    ("IN_PROBATE", "CONTESTED"): "CourtClerk",
    ("INVENTORIED", "CONTESTED"): "CourtClerk",
    ("CONTESTED", "IN_PROBATE"): "CourtClerk",
}


def transition_estate(estate: dict, to_status: str, role: str) -> dict:
    current = estate["admin_phase"]
    key = (current, to_status)

    if key not in ALLOWED_TRANSITIONS:
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Cannot transition estate from {current} to {to_status}.")

    # Per-edge role gate — actor must match the scaffold's actor for the edge.
    expected_role = ALLOWED_TRANSITIONS[key]
    if role != expected_role:
        # Forbidden is the right semantic here: the role itself is in the
        # endpoint's allowed list but not authorized for this specific edge.
        raise ApiError("ERR_FORBIDDEN", 403,
                       f"Role {role} cannot perform estate transition {current}→{to_status}.")

    # Dispatch to the per-edge handler.
    handler = _HANDLERS[key]
    handler(estate)
    estate["admin_phase"] = to_status
    bump(estate)
    return estate


# ── Per-edge handlers ──────────────────────────────────────────────────────

def _draft_to_in_probate(estate: dict):
    """Three preconditions, then cascade POAs to TERMINATED."""
    eid = estate["id"]

    # Precondition 1: at least one CONFIRMED EXECUTOR.
    confirmed_executor = None
    for f in store.fiduciaries.values():
        if (f["estate_id"] == eid
                and f["scope_type"] == "EXECUTOR"
                and f["status"] == "CONFIRMED"):
            confirmed_executor = f
            break
    if confirmed_executor is None:
        raise ApiError("ERR_NO_CONFIRMED_EXECUTOR", 409,
                       "A CONFIRMED EXECUTOR is required to enter probate.")

    # Precondition 2: ACCEPTED PETITION_TO_PROBATE filing.
    has_petition = any(
        f for f in store.filings.values()
        if f["estate_id"] == eid
        and f["filing_type"] == "PETITION_TO_PROBATE"
        and f["status"] == "ACCEPTED"
    )
    if not has_petition:
        raise ApiError("ERR_NO_ACCEPTED_PETITION", 409,
                       "An ACCEPTED PETITION_TO_PROBATE filing is required.")

    # Precondition 3: executor bond ≥ required_bond (forward_looking).
    gross = compute_gross_estate_value(eid, "forward_looking")
    required_bond = compute_required_bond(gross)
    if (confirmed_executor.get("bond_amount_cents") or 0) < required_bond:
        raise ApiError("ERR_BOND_INSUFFICIENT", 422,
                       "Executor bond is below the required bond amount.")

    # Side effects.
    now = store.now()
    estate["petition_filed_at"] = now
    estate["settlement_due_at"] = now + timedelta(days=SETTLEMENT_WINDOW_DAYS)
    estate["gross_estate_value_cents"] = gross

    # Cascade: TERMINATE all PENDING/ACTIVE POAs.
    for p in list(store.poas.values()):
        if p["estate_id"] != eid:
            continue
        if p["status"] in ("PENDING", "ACTIVE"):
            p["status"] = "TERMINATED"
            bump(p)


def _in_probate_to_inventoried(estate: dict):
    eid = estate["id"]
    # Pre 1: ACCEPTED INVENTORY_REPORT filing.
    has_inventory = any(
        f for f in store.filings.values()
        if f["estate_id"] == eid
        and f["filing_type"] == "INVENTORY_REPORT"
        and f["status"] == "ACCEPTED"
    )
    if not has_inventory:
        raise ApiError("ERR_NO_ACCEPTED_INVENTORY", 409,
                       "An ACCEPTED INVENTORY_REPORT filing is required.")

    # Pre 2: every asset is INVENTORIED, APPRAISED, or EXCLUDED.
    for a in store.assets.values():
        if a["estate_id"] != eid:
            continue
        if a["status"] not in ("INVENTORIED", "APPRAISED", "EXCLUDED"):
            raise ApiError("ERR_ASSETS_NOT_INVENTORIED", 409,
                           f"Asset {a['id']} is still in status {a['status']}.")

    # Side effect: recompute gross_estate_value (forward-looking).
    recompute_estate_gross(estate, "forward_looking")


def _inventoried_to_distributing(estate: dict):
    eid = estate["id"]
    # Pre 1: probate_posture == OPEN.
    posture = compute_probate_posture(estate)
    if posture != "OPEN":
        raise ApiError("ERR_POSTURE_BLOCKED", 403,
                       f"Estate posture is {posture}; advance requires OPEN.")

    # Pre 2: settlement_due_at not exceeded.
    now = store.logical_now()
    settle_due = estate.get("settlement_due_at")
    if settle_due is not None and now >= settle_due:
        raise ApiError("ERR_SETTLEMENT_DEADLINE_PASSED", 422,
                       "settlement_due_at has elapsed.")

    # Pre 3: every minor beneficiary has an EFFECTIVE guardianship.
    for b in store.beneficiaries.values():
        if b["estate_id"] != eid:
            continue
        if b["status"] != "ACTIVE":
            continue
        if not b.get("is_minor"):
            continue
        guardianship_id = b.get("guardianship_id")
        if not guardianship_id:
            raise ApiError("ERR_GUARDIANSHIP_MISSING", 422,
                           f"Minor beneficiary {b['id']} lacks a guardianship.")
        g = store.guardianships.get(guardianship_id)
        if not g or g["status"] != "EFFECTIVE":
            raise ApiError("ERR_GUARDIANSHIP_MISSING", 422,
                           f"Minor beneficiary {b['id']} guardianship not EFFECTIVE.")

    # Pre 4: PROPOSED designation sums per asset == 10000 for every asset that
    # has any PROPOSED designations. Assets with no designations at all are
    # implicit zero-share assets and don't require allocation. (We follow the
    # canonical reading: every asset that will receive distribution must sum
    # exactly to 10000 across its PROPOSED rows; an asset with zero PROPOSED
    # designations is treated as fully unallocated and not yet in the share
    # plan — but per PRD §3.11, "sum...per asset...equals exactly 10000 for
    # every asset". An asset with zero designations totals 0, not 10000; if
    # any APPRAISED asset has no designations, fail with
    # ERR_DESIGNATIONS_INCOMPLETE.)
    sums: dict[str, int] = {}
    for d in store.designations.values():
        if d["estate_id"] != eid:
            continue
        if d["status"] == "PROPOSED":
            sums[d["asset_id"]] = sums.get(d["asset_id"], 0) + d["share_basis_points"]

    for a in store.assets.values():
        if a["estate_id"] != eid:
            continue
        if a["status"] in ("APPRAISED", "INVENTORIED"):
            asset_sum = sums.get(a["id"], 0)
            if asset_sum != 10000:
                raise ApiError("ERR_DESIGNATIONS_INCOMPLETE", 422,
                               f"Asset {a['id']} PROPOSED share sum is {asset_sum}, "
                               f"not 10000.")

    # Pre 5: ACCEPTED DISTRIBUTION_PETITION filing.
    has_dp = any(
        f for f in store.filings.values()
        if f["estate_id"] == eid
        and f["filing_type"] == "DISTRIBUTION_PETITION"
        and f["status"] == "ACCEPTED"
    )
    if not has_dp:
        raise ApiError("ERR_NO_ACCEPTED_DISTRIBUTION_PETITION", 409,
                       "An ACCEPTED DISTRIBUTION_PETITION filing is required.")

    # Side effects.
    # 1. Lock all PROPOSED designations.
    for d in store.designations.values():
        if d["estate_id"] != eid:
            continue
        if d["status"] == "PROPOSED":
            d["status"] = "LOCKED"
            # Designations have no version/updated_at.

    # 2. Compute planned distribution per beneficiary, create Distribution rows.
    plan = compute_planned_distributions(eid)

    # Wipe any pre-existing Distribution rows on the estate (defensive — there
    # shouldn't be any before this transition).
    to_drop = [d["id"] for d in store.distributions.values()
               if d["estate_id"] == eid]
    for did in to_drop:
        del store.distributions[did]

    from utils import new_uuid
    now = store.now()
    for bid, cents in plan.items():
        new_id = new_uuid()
        store.distributions[new_id] = {
            "id": new_id,
            "estate_id": eid,
            "beneficiary_id": bid,
            "planned_amount_cents": int(cents),
            "actual_amount_cents": None,
            "status": "PLANNED",
            "executed_at": None,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }


def _distributing_to_settled(estate: dict):
    eid = estate["id"]
    # Pre 1: every asset with a LOCKED designation is DISTRIBUTED.
    locked_asset_ids = set()
    for d in store.designations.values():
        if d["estate_id"] != eid:
            continue
        if d["status"] == "LOCKED":
            locked_asset_ids.add(d["asset_id"])
    for aid in locked_asset_ids:
        asset = store.assets.get(aid)
        if not asset or asset["status"] != "DISTRIBUTED":
            raise ApiError("ERR_ASSETS_NOT_DISTRIBUTED", 409,
                           f"Asset {aid} with a LOCKED designation is not DISTRIBUTED.")

    # Pre 2: ACCEPTED FINAL_ACCOUNTING filing.
    has_final = any(
        f for f in store.filings.values()
        if f["estate_id"] == eid
        and f["filing_type"] == "FINAL_ACCOUNTING"
        and f["status"] == "ACCEPTED"
    )
    if not has_final:
        raise ApiError("ERR_NO_ACCEPTED_FINAL_ACCOUNTING", 409,
                       "An ACCEPTED FINAL_ACCOUNTING filing is required.")

    # Pre 3: Σ actual EXECUTED == Σ planned (PLANNED+EXECUTED).
    sum_actual = 0
    sum_planned = 0
    for d in store.distributions.values():
        if d["estate_id"] != eid:
            continue
        if d["status"] == "EXECUTED":
            sum_actual += d.get("actual_amount_cents", 0) or 0
        if d["status"] in ("PLANNED", "EXECUTED"):
            sum_planned += d.get("planned_amount_cents", 0) or 0
    if sum_actual != sum_planned:
        raise ApiError("ERR_DISTRIBUTION_DRIFT", 422,
                       "Sum of actual distributions does not match planned.")

    # Compute net_estate_value (chronological gross - fees(0)).
    chrono_gross = compute_gross_estate_value(eid, "chronological")
    estate["gross_estate_value_cents"] = chrono_gross
    estate["net_estate_value_cents"] = chrono_gross

    # Cascades.
    # 1. EXECUTOR fiduciaries with status=CONFIRMED → REMOVED.
    for f in store.fiduciaries.values():
        if f["estate_id"] != eid:
            continue
        if f["scope_type"] == "EXECUTOR" and f["status"] == "CONFIRMED":
            f["status"] = "REMOVED"
            bump(f)

    # 2. ACTIVE HIPAA authorizations → REVOKED.
    for h in store.hipaa_auths.values():
        if h["estate_id"] != eid:
            continue
        if h["status"] == "ACTIVE":
            h["status"] = "REVOKED"
            bump(h)


def _in_probate_to_contested(estate: dict):
    _enter_contested(estate)


def _inventoried_to_contested(estate: dict):
    _enter_contested(estate)


def _enter_contested(estate: dict):
    eid = estate["id"]
    estate["contested_at"] = store.now()
    # Cascade: every SUBMITTED filing → REVISION_REQUESTED with reason
    # 'estate_contested'.
    for f in store.filings.values():
        if f["estate_id"] != eid:
            continue
        if f["status"] == "SUBMITTED":
            f["status"] = "REVISION_REQUESTED"
            f["rejection_reason"] = "estate_contested"
            f["court_response_at"] = store.now()
            bump(f)


def _contested_to_in_probate(estate: dict):
    eid = estate["id"]
    # Pre: no REVISION_REQUESTED filings remain.
    for f in store.filings.values():
        if f["estate_id"] != eid:
            continue
        if f["status"] == "REVISION_REQUESTED":
            raise ApiError("ERR_FILINGS_PENDING", 409,
                           "Cannot resolve contest while filings remain in REVISION_REQUESTED.")
    estate["contested_at"] = None


_HANDLERS = {
    ("DRAFT", "IN_PROBATE"): _draft_to_in_probate,
    ("IN_PROBATE", "INVENTORIED"): _in_probate_to_inventoried,
    ("INVENTORIED", "DISTRIBUTING"): _inventoried_to_distributing,
    ("DISTRIBUTING", "SETTLED"): _distributing_to_settled,
    ("IN_PROBATE", "CONTESTED"): _in_probate_to_contested,
    ("INVENTORIED", "CONTESTED"): _inventoried_to_contested,
    ("CONTESTED", "IN_PROBATE"): _contested_to_in_probate,
}


# ── Force-revert (used by Beneficiary.DISCLAIMED cascade) ──────────────────

def maybe_revert_to_inventoried(estate: dict) -> bool:
    """If estate is DISTRIBUTING and some asset's LOCKED-sum < 10000, revert
    to INVENTORIED. Returns True when the revert fires.
    """
    if estate["admin_phase"] != "DISTRIBUTING":
        return False
    eid = estate["id"]
    sums: dict[str, int] = {}
    asset_ids = set()
    for d in store.designations.values():
        if d["estate_id"] != eid:
            continue
        if d["status"] == "LOCKED":
            asset_ids.add(d["asset_id"])
            sums[d["asset_id"]] = sums.get(d["asset_id"], 0) + d["share_basis_points"]

    short = False
    for aid in asset_ids:
        if sums.get(aid, 0) < 10000:
            short = True
            break
    if short:
        estate["admin_phase"] = "INVENTORIED"
        bump(estate)
        return True
    return False
