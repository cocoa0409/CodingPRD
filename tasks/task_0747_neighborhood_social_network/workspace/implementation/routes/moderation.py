"""ModerationDecision endpoints."""
from __future__ import annotations

from flask import Blueprint, g, request

from db import DB, stamp_new, bump
from errors import (
    InvalidRequest,
    NotFound,
    ReferenceNotFound,
    Forbidden,
    InvalidState,
    StaleTargetVersion,
)
from middleware import require_roles
from paging import apply_pagination
from response import success
from services import (
    MOD_UPHOLD_PENALTY,
    refresh_resident_trust,
    recompute_post_flag_count,
    recompute_post_score,
)
from validators import as_str, as_int, as_enum


bp = Blueprint("moderation", __name__)

DECISIONS = {"UPHOLD", "DISMISS", "REVERSE"}


def _prior_upheld_on_post_exists(post_id: str, exclude_decision_id: str | None = None) -> bool:
    for d in DB.moderation_decisions.values():
        if exclude_decision_id and d["id"] == exclude_decision_id:
            continue
        if d["decision"] != "UPHOLD":
            continue
        fr = DB.flag_reports.get(d["flag_report_id"])
        if fr and fr["target_type"] == "POST" and fr["target_id"] == post_id:
            return True
    return False


@bp.post("/neighborhood/moderation-decisions")
@require_roles("Moderator")
def create_decision():
    payload = request.get_json(silent=True) or {}
    moderator_resident_id = as_str(payload, "moderator_resident_id")
    flag_report_id = as_str(payload, "flag_report_id")
    decision = as_enum(payload, "decision", DECISIONS)
    rationale = as_str(payload, "rationale")
    expected_target_version = as_int(payload, "expected_target_version")

    mod = DB.residents.get(moderator_resident_id)
    if mod is None:
        raise ReferenceNotFound(f"Resident {moderator_resident_id} not found")
    if not mod.get("is_moderator", False):
        raise Forbidden("moderator_resident_id does not name a moderator")

    fr = DB.flag_reports.get(flag_report_id)
    if fr is None:
        raise ReferenceNotFound(f"FlagReport {flag_report_id} not found")

    target_type = fr["target_type"]
    target_id = fr["target_id"]

    # We only support cascading state transitions for POST and MARKETPLACE_LISTING per spec.
    if target_type == "POST":
        target = DB.posts.get(target_id)
    elif target_type == "MARKETPLACE_LISTING":
        target = DB.marketplace_listings.get(target_id)
    else:
        # Other target types have no state cascades; still allow OCC + status update
        target = None

    # Determine state-precondition (priority 70)
    if decision == "UPHOLD":
        if fr["status"] != "OPEN":
            raise InvalidState(f"FlagReport.status is {fr['status']}, expected OPEN")
        if target_type == "POST":
            if target is None or target["state"] != "FLAGGED":
                raise InvalidState(
                    f"Post.state is {target['state'] if target else 'MISSING'}, expected FLAGGED"
                )
        elif target_type == "MARKETPLACE_LISTING":
            if target is None or target["state"] != "ACTIVE":
                raise InvalidState(
                    f"MarketplaceListing.state is {target['state'] if target else 'MISSING'}, "
                    f"expected ACTIVE"
                )
    elif decision == "DISMISS":
        if fr["status"] != "OPEN":
            raise InvalidState(f"FlagReport.status is {fr['status']}, expected OPEN")
        if target_type == "POST":
            if target is None or target["state"] != "FLAGGED":
                raise InvalidState(
                    f"Post.state is {target['state'] if target else 'MISSING'}, expected FLAGGED"
                )
    elif decision == "REVERSE":
        if target_type == "POST":
            if target is None or target["state"] != "HIDDEN":
                raise InvalidState(
                    f"Post.state is {target['state'] if target else 'MISSING'}, expected HIDDEN"
                )
            if not _prior_upheld_on_post_exists(target_id):
                raise InvalidState("No prior UPHELD moderation decision on this Post")
        elif target_type == "MARKETPLACE_LISTING":
            if target is None or target["state"] != "SUSPENDED":
                raise InvalidState(
                    f"MarketplaceListing.state is {target['state'] if target else 'MISSING'}, "
                    f"expected SUSPENDED"
                )

    # OCC check (priority 80): expected_target_version against target's current version
    if target is not None:
        if expected_target_version != target.get("version"):
            raise StaleTargetVersion(
                f"expected_target_version {expected_target_version} != "
                f"current version {target.get('version')}"
            )

    # Create the decision row (trust_delta_applied filled below)
    d = {
        "moderator_resident_id": moderator_resident_id,
        "flag_report_id": flag_report_id,
        "decision": decision,
        "rationale": rationale,
        "expected_target_version": expected_target_version,
        "trust_delta_applied": 0,
    }
    stamp_new(d)
    DB.moderation_decisions[d["id"]] = d

    # Determine the affected author/seller resident whose trust we'll recompute
    if target_type == "POST":
        author_id = target["author_resident_id"] if target else None
    elif target_type == "MARKETPLACE_LISTING":
        author_id = target["seller_resident_id"] if target else None
    else:
        author_id = None

    trust_before = None
    if author_id is not None:
        r = DB.residents.get(author_id)
        if r is not None:
            trust_before = r.get("trust_score", 100)

    # Apply cascade side effects per §1.2
    if target_type == "POST" and target is not None:
        if decision == "UPHOLD":
            target["state"] = "HIDDEN"
            bump(target)
            fr["status"] = "UPHELD"
            fr["linked_decision_id"] = d["id"]
            bump(fr)
            # All OPEN flag reports against this post -> UPHELD
            for other in DB.flag_reports.values():
                if (
                    other["id"] != fr["id"]
                    and other["target_type"] == "POST"
                    and other["target_id"] == target_id
                    and other["status"] == "OPEN"
                ):
                    other["status"] = "UPHELD"
                    bump(other)
            # trust dock via recompute
            if author_id:
                refresh_resident_trust(author_id)
            # recompute flag_count (all should now be UPHELD, still counted in OPEN|UPHELD)
            new_fc = recompute_post_flag_count(target_id)
            if target.get("flag_count") != new_fc:
                target["flag_count"] = new_fc
                bump(target)
            recompute_post_score(target, bump_row=True)

        elif decision == "DISMISS":
            fr["status"] = "DISMISSED"
            fr["linked_decision_id"] = d["id"]
            bump(fr)
            target["state"] = "PUBLISHED"
            bump(target)
            # Reset flag_count to number of remaining OPEN flag reports
            new_fc = recompute_post_flag_count(target_id)
            if target.get("flag_count") != new_fc:
                target["flag_count"] = new_fc
                bump(target)
            recompute_post_score(target, bump_row=True)

        elif decision == "REVERSE":
            target["state"] = "PUBLISHED"
            bump(target)
            # All UPHELD flag reports against this post -> REVERSED
            for other in DB.flag_reports.values():
                if (
                    other["target_type"] == "POST"
                    and other["target_id"] == target_id
                    and other["status"] == "UPHELD"
                ):
                    other["status"] = "REVERSED"
                    bump(other)
            fr["linked_decision_id"] = d["id"]
            bump(fr)
            if author_id:
                refresh_resident_trust(author_id)
            new_fc = recompute_post_flag_count(target_id)
            if target.get("flag_count") != new_fc:
                target["flag_count"] = new_fc
                bump(target)
            recompute_post_score(target, bump_row=True)

    elif target_type == "MARKETPLACE_LISTING" and target is not None:
        if decision == "UPHOLD":
            target["state"] = "SUSPENDED"
            bump(target)
            fr["status"] = "UPHELD"
            fr["linked_decision_id"] = d["id"]
            bump(fr)
            if author_id:
                refresh_resident_trust(author_id)
        elif decision == "DISMISS":
            fr["status"] = "DISMISSED"
            fr["linked_decision_id"] = d["id"]
            bump(fr)
        elif decision == "REVERSE":
            target["state"] = "ACTIVE"
            bump(target)
            fr["status"] = "REVERSED"
            fr["linked_decision_id"] = d["id"]
            bump(fr)
            if author_id:
                refresh_resident_trust(author_id)

    else:
        # No cascading target — just update flag report status
        if decision == "UPHOLD":
            fr["status"] = "UPHELD"
        elif decision == "DISMISS":
            fr["status"] = "DISMISSED"
        elif decision == "REVERSE":
            fr["status"] = "REVERSED"
        fr["linked_decision_id"] = d["id"]
        bump(fr)

    # Compute trust_delta_applied (post-cascade)
    trust_after = None
    if author_id is not None:
        r = DB.residents.get(author_id)
        if r is not None:
            trust_after = r.get("trust_score", 100)
    if trust_before is not None and trust_after is not None:
        d["trust_delta_applied"] = trust_after - trust_before

    return success(d, status=201)


@bp.get("/neighborhood/moderation-decisions/<did>")
@require_roles("Moderator", "PlatformAdmin")
def get_decision(did: str):
    d = DB.moderation_decisions.get(did)
    if d is None:
        raise NotFound(f"ModerationDecision {did} not found")
    return success(d)


@bp.get("/neighborhood/moderation-decisions")
@require_roles("Moderator", "PlatformAdmin")
def list_decisions():
    mid = request.args.get("moderator_resident_id")
    fid = request.args.get("flag_report_id")
    rows = list(DB.moderation_decisions.values())
    if mid is not None:
        rows = [r for r in rows if r["moderator_resident_id"] == mid]
    if fid is not None:
        rows = [r for r in rows if r["flag_report_id"] == fid]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, meta = apply_pagination(rows)
    return success(page, response_type="array", pagination=meta)
