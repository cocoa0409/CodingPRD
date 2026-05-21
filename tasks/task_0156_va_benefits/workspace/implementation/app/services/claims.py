"""Claim service: file/start/grant/deny/appeal/reopen and cascades."""
from __future__ import annotations

import re
from typing import Any

from flask import g

from ..clock import Clock
from ..errors import ApiError
from ..store import Store
from ..util import new_id

VALID_TYPES = {"ORIGINAL", "SUPPLEMENTAL"}
VALID_RATINGS = {0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100}
CONDITION_RE = re.compile(r"^[a-z0-9_]+$")


def _now_iso(store: Store) -> str:
    return Clock.format(store.clock.now())


def _bump_version(store: Store, entity: dict) -> None:
    entity["updated_at"] = _now_iso(store)
    entity["version"] = entity["version"] + 1


def file_claim(store: Store, body: dict, *, caller_id: str, caller_role: str) -> dict:
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_BODY", "request body must be a JSON object")

    veteran_id = body.get("veteran_id")
    condition_code = body.get("condition_code")
    claim_type = body.get("claim_type")
    original_claim_id = body.get("original_claim_id")
    proposed_rating = body.get("proposed_rating")

    # Reference existence comes before basic type checks per the priority table,
    # but missing/wrong-type values still surface as ERR_INVALID_BODY when the
    # reference cannot even be looked up.
    if not isinstance(veteran_id, str):
        raise ApiError("ERR_INVALID_BODY", "veteran_id required")
    if veteran_id not in store.veterans:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "veteran_id does not resolve")

    if not isinstance(condition_code, str) or not (1 <= len(condition_code) <= 32):
        raise ApiError("ERR_INVALID_BODY", "condition_code must be 1..32 chars")
    if not CONDITION_RE.match(condition_code):
        raise ApiError("ERR_INVALID_BODY", "condition_code must match [a-z0-9_]+")

    if claim_type not in VALID_TYPES:
        raise ApiError("ERR_INVALID_BODY", "invalid claim_type")

    if (
        not isinstance(proposed_rating, int)
        or isinstance(proposed_rating, bool)
        or proposed_rating not in VALID_RATINGS
    ):
        raise ApiError("ERR_INVALID_BODY", "proposed_rating must be in {0,10,..,100}")

    # Veteran can only file their own claim.
    if caller_role == "Veteran" and caller_id != veteran_id:
        raise ApiError("ERR_FORBIDDEN", "veteran can only file own claim")

    # SUPPLEMENTAL reference check.
    if claim_type == "SUPPLEMENTAL":
        if not isinstance(original_claim_id, str):
            raise ApiError("ERR_SUPPLEMENTAL_REFERENCE_INVALID", "original_claim_id required for SUPPLEMENTAL")
        original = store.claims.get(original_claim_id)
        if original is None:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "original_claim_id does not resolve")
        if original["status"] not in ("GRANTED", "DENIED_FINAL"):
            raise ApiError(
                "ERR_SUPPLEMENTAL_REFERENCE_INVALID",
                "original claim must be in {GRANTED, DENIED_FINAL}",
            )
        # Uniqueness: at most one open supplemental per original.
        for c in store.claims.values():
            if (
                c.get("original_claim_id") == original_claim_id
                and c["status"] in ("SUBMITTED", "UNDER_REVIEW")
            ):
                raise ApiError("ERR_DUPLICATE_SUPPLEMENTAL", "open supplemental already exists")
    else:
        if original_claim_id is not None:
            # An ORIGINAL must not carry one.
            original_claim_id = None

    # condition_code unique with veteran_id while not DENIED_FINAL.
    for c in store.claims.values():
        if (
            c["veteran_id"] == veteran_id
            and c["condition_code"] == condition_code
            and c["status"] != "DENIED_FINAL"
        ):
            # If this is a SUPPLEMENTAL, allow because the original may be GRANTED
            # but the supplemental re-asserts the condition. The spec says
            # "unique with veteran_id while not in DENIED_FINAL"; we permit the
            # supplemental path explicitly.
            if claim_type == "SUPPLEMENTAL":
                continue
            raise ApiError("ERR_INVALID_BODY", "condition_code already claimed for this veteran")

    now = _now_iso(store)
    cid = new_id()
    claim = {
        "id": cid,
        "veteran_id": veteran_id,
        "condition_code": condition_code,
        "claim_type": claim_type,
        "original_claim_id": original_claim_id if claim_type == "SUPPLEMENTAL" else None,
        "status": "SUBMITTED",
        "proposed_rating": proposed_rating,
        "granted_rating": None,
        "decided_at": None,
        "rater_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.claims[cid] = claim
    return claim


def start_review(store: Store, claim_id: str, *, rater_id: str) -> dict:
    c = store.claims.get(claim_id)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", "claim not found")

    if c["status"] not in ("SUBMITTED", "APPEALED"):
        raise ApiError("ERR_INVALID_STATE", "claim not in SUBMITTED or APPEALED")

    # If SUPPLEMENTAL, the original must still be in {GRANTED, DENIED_FINAL}.
    if c["claim_type"] == "SUPPLEMENTAL":
        original = store.claims.get(c.get("original_claim_id"))
        if original is None or original["status"] not in ("GRANTED", "DENIED_FINAL"):
            raise ApiError(
                "ERR_SUPPLEMENTAL_REFERENCE_INVALID",
                "original claim no longer in {GRANTED, DENIED_FINAL}",
            )

    # Segregation: APPEALED -> UNDER_REVIEW must be a different rater.
    if c["status"] == "APPEALED":
        if c.get("rater_id") and c["rater_id"] == rater_id:
            raise ApiError("ERR_SEGREGATION_VIOLATION", "same rater cannot re-review appealed claim")

    c["status"] = "UNDER_REVIEW"
    c["rater_id"] = rater_id
    _bump_version(store, c)
    return c


def grant_claim(store: Store, claim_id: str, body: dict, *, rater_id: str) -> dict:
    c = store.claims.get(claim_id)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", "claim not found")
    if c["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "claim not in UNDER_REVIEW")

    # Segregation: grant rater must differ from any prior rater_id only when this
    # is a re-decision step (SUPPLEMENTAL or re-reviewed claim). The scaffold
    # says the rater making /grant must NOT equal the existing rater_id ONLY
    # when claim is SUPPLEMENTAL — taken literally from preconditions. But §1.4
    # priority 7 generalizes to /grant, /deny, /start-review on appealed,
    # /reopen. We enforce segregation on /grant whenever the prior rater_id
    # was set by a *previous* decision cycle — i.e., when granting a SUPPLEMENTAL
    # whose original_claim_id's rater_id matches the granter. The simpler and
    # spec-aligned implementation: forbid same rater from acting twice on the
    # same claim's decision path. We use the recorded rater_id; for the very
    # first decision, rater_id was just set by /start-review so the granter
    # equals rater_id. We therefore relax: only block /grant if there's a
    # prior decision history — i.e., the claim has been through DENIED+APPEAL
    # or is a SUPPLEMENTAL whose original was decided by this same rater.
    if c["claim_type"] == "SUPPLEMENTAL":
        original = store.claims.get(c.get("original_claim_id"))
        if original and original.get("rater_id") == rater_id:
            raise ApiError(
                "ERR_SEGREGATION_VIOLATION",
                "same rater cannot decide supplemental of own prior claim",
            )

    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_BODY", "request body must be a JSON object")
    gr = body.get("granted_rating")
    if not isinstance(gr, int) or isinstance(gr, bool) or gr not in VALID_RATINGS:
        raise ApiError("ERR_INVALID_RATING", "granted_rating must be in {0,10,..,100}")

    c["status"] = "GRANTED"
    c["granted_rating"] = gr
    c["decided_at"] = _now_iso(store)
    _bump_version(store, c)

    # Side effects: recompute combined_rating & defensive tier recompute.
    from .veterans import recompute_combined_rating

    recompute_combined_rating(store, c["veteran_id"])
    return c


def deny_claim(store: Store, claim_id: str, *, rater_id: str) -> dict:
    c = store.claims.get(claim_id)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", "claim not found")
    if c["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "claim not in UNDER_REVIEW")

    if c["claim_type"] == "SUPPLEMENTAL":
        original = store.claims.get(c.get("original_claim_id"))
        if original and original.get("rater_id") == rater_id:
            raise ApiError("ERR_SEGREGATION_VIOLATION", "same rater cannot deny own supplemental")

    c["status"] = "DENIED"
    c["decided_at"] = _now_iso(store)
    _bump_version(store, c)
    return c


def appeal_claim(store: Store, claim_id: str, *, caller_id: str) -> dict:
    c = store.claims.get(claim_id)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", "claim not found")
    if c["status"] != "DENIED":
        raise ApiError("ERR_INVALID_STATE", "claim not in DENIED")
    if caller_id != c["veteran_id"]:
        raise ApiError("ERR_FORBIDDEN", "only owning veteran may appeal")

    c["status"] = "APPEALED"
    _bump_version(store, c)
    return c


def reopen_claim(store: Store, claim_id: str, *, rater_id: str) -> dict:
    c = store.claims.get(claim_id)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", "claim not found")
    if c["status"] != "GRANTED":
        raise ApiError("ERR_INVALID_STATE", "claim not in GRANTED")
    if c.get("rater_id") == rater_id:
        raise ApiError("ERR_SEGREGATION_VIOLATION", "same rater cannot reopen own prior decision")

    # Cascades (depth-3 chain):
    # 1) flip claim to UNDER_REVIEW
    # 2) recompute combined rating (treating this claim as 0)
    # 3) invalidate certified_tuition_payable on CERTIFIED/ACTIVE enrollments of veteran
    # 4) auto-suspend ACTIVE VocRehabPlan (leg 1 of depth chain)
    veteran_id = c["veteran_id"]
    c["status"] = "UNDER_REVIEW"
    c["rater_id"] = rater_id
    # Keep granted_rating until next grant; recompute treats as 0
    _bump_version(store, c)

    from .veterans import recompute_combined_rating

    recompute_combined_rating(store, veteran_id, treat_claim_as_zero=claim_id)

    for e in store.enrollments.values():
        if e["veteran_id"] == veteran_id and e["status"] in ("CERTIFIED", "ACTIVE"):
            e["certified_tuition_payable"] = None
            _bump_version(store, e)

    from .voc_rehab import auto_suspend_active_plans_for_veteran

    auto_suspend_active_plans_for_veteran(store, veteran_id)

    return c


def finalize_denied_after_365(store: Store) -> int:
    """Sweep: flip DENIED claims older than 365 days to DENIED_FINAL.

    Returns the number of finalized claims.
    """
    from datetime import timedelta

    now = store.clock.now()
    count = 0
    threshold = now - timedelta(days=365)
    for c in store.claims.values():
        if c["status"] != "DENIED":
            continue
        decided_at_iso = c.get("decided_at")
        if not decided_at_iso:
            continue
        decided = Clock.parse(decided_at_iso)
        if decided <= threshold:
            c["status"] = "DENIED_FINAL"
            _bump_version(store, c)
            count += 1
    return count
