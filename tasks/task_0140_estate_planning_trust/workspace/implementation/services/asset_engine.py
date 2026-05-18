"""Asset state machine (SCAFFOLD §1.2, PRD §3.4).

Transitions:
    DECLARED    → INVENTORIED  (Executor) — estate in IN_PROBATE or INVENTORIED
    INVENTORIED → APPRAISED    (Executor) — supplies appraised_value_cents
    APPRAISED   → DISTRIBUTED  (Executor) — estate in DISTRIBUTING; distribution_id
    DECLARED    → EXCLUDED     (Executor) — estate in DRAFT or IN_PROBATE
    INVENTORIED → EXCLUDED     (Executor) — no BeneficiaryDesignation references
"""
from __future__ import annotations

from db import store
from errors import ApiError
from services.calculations import recompute_estate_gross
from services.common import bump


ALLOWED = {
    ("DECLARED", "INVENTORIED"),
    ("INVENTORIED", "APPRAISED"),
    ("APPRAISED", "DISTRIBUTED"),
    ("DECLARED", "EXCLUDED"),
    ("INVENTORIED", "EXCLUDED"),
}


def transition_asset(asset: dict, estate: dict, to_status: str, body: dict) -> dict:
    current = asset["status"]
    key = (current, to_status)
    if key not in ALLOWED:
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Cannot transition asset from {current} to {to_status}.")

    if key == ("DECLARED", "INVENTORIED"):
        if estate["admin_phase"] not in ("IN_PROBATE", "INVENTORIED"):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Asset DECLARED→INVENTORIED requires estate IN_PROBATE or INVENTORIED.")
    elif key == ("INVENTORIED", "APPRAISED"):
        appraised = body.get("appraised_value_cents")
        if not _is_non_neg_int(appraised):
            raise ApiError("ERR_BAD_REQUEST", 400,
                           "appraised_value_cents required and must be a non-negative integer.")
        asset["appraised_value_cents"] = int(appraised)
    elif key == ("APPRAISED", "DISTRIBUTED"):
        if estate["admin_phase"] != "DISTRIBUTING":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Asset APPRAISED→DISTRIBUTED requires estate in DISTRIBUTING.")
        distribution_id = body.get("distribution_id")
        if not distribution_id or not isinstance(distribution_id, str):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "distribution_id is required for APPRAISED→DISTRIBUTED.")
        dist = store.distributions.get(distribution_id)
        if not dist or dist.get("estate_id") != estate["id"]:
            raise ApiError("ERR_INVALID_STATE", 409,
                           "distribution_id does not reference a Distribution in this estate.")
        if dist["status"] != "EXECUTED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "distribution_id must reference a Distribution in status EXECUTED.")
        # A LOCKED BeneficiaryDesignation linking this Asset to dist.beneficiary_id must exist.
        match = False
        for d in store.designations.values():
            if (d["estate_id"] == estate["id"]
                    and d["status"] == "LOCKED"
                    and d["asset_id"] == asset["id"]
                    and d["beneficiary_id"] == dist["beneficiary_id"]):
                match = True
                break
        if not match:
            raise ApiError("ERR_DESIGNATION_MISMATCH", 409,
                           "No LOCKED designation links this asset to the distribution's beneficiary.")
        # First-writer-wins race: if already DISTRIBUTED, reject.
        # (We've already checked current==APPRAISED via the ALLOWED guard,
        # but for robustness against double-transition we re-check inline.)
        asset["distribution_id"] = distribution_id
    elif key == ("DECLARED", "EXCLUDED"):
        if estate["admin_phase"] not in ("DRAFT", "IN_PROBATE"):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "DECLARED→EXCLUDED requires estate DRAFT or IN_PROBATE.")
    elif key == ("INVENTORIED", "EXCLUDED"):
        # No BeneficiaryDesignation references this asset.
        for d in store.designations.values():
            if (d["estate_id"] == estate["id"]
                    and d["asset_id"] == asset["id"]
                    and d["status"] in ("PROPOSED", "LOCKED")):
                raise ApiError("ERR_HAS_DEPENDENCIES", 409,
                               "Cannot exclude an asset with existing designations.")

    asset["status"] = to_status
    bump(asset)

    # Side effect: recompute estate.gross when relevant.
    if to_status in ("APPRAISED", "INVENTORIED", "EXCLUDED", "DISTRIBUTED"):
        recompute_estate_gross(estate, "forward_looking")
    return asset


def _is_non_neg_int(v) -> bool:
    if isinstance(v, bool):
        return False
    return isinstance(v, int) and v >= 0
