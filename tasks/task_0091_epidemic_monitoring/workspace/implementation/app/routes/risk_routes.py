"""RiskTierDecision endpoints."""
from __future__ import annotations

from flask import Flask

from ..audit import append_audit
from ..auth import current_actor, require_auth
from ..clock import now_iso_ms
from ..constants import RISK_TIERS, TIER_WEIGHT, CATEGORY_WEIGHT
from ..errors import ApiError
from ..services.calculations import compute_case_density_score, compute_priority_score
from ..store import bump_version, common_fields_append_only, get_store
from ._helpers import check_version, get_json_body, ok, with_lock


def register(app: Flask) -> None:
    app.add_url_rule(
        "/epi/risk-decisions",
        view_func=require_auth("CDCSupervisor")(with_lock(create_decision)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/risk-decisions/<did>",
        view_func=require_auth("CDCSupervisor", "RiskExpert", "PressOfficer")(
            with_lock(get_decision)
        ),
        methods=["GET"],
    )
    app.add_url_rule(
        "/epi/risk-decisions/<did>/submit-review",
        view_func=require_auth("CDCSupervisor")(with_lock(submit_review)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/risk-decisions/<did>/approve",
        view_func=require_auth("RiskExpert")(with_lock(approve_decision)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/risk-decisions/<did>/reject",
        view_func=require_auth("RiskExpert")(with_lock(reject_decision)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/risk-decisions/<did>/publish",
        view_func=require_auth("PressOfficer")(with_lock(publish_decision)),
        methods=["POST"],
    )


def create_decision():
    body = get_json_body()
    store = get_store()
    region_id = body.get("region_id")
    if not region_id:
        raise ApiError("ERR_INVALID_INPUT", "Missing region_id.")
    region = store.regions.get(region_id)
    if not region:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"region_id {region_id} not found.")
    score, computed_tier = compute_case_density_score(region)

    # The decision snapshots provisional_tier; if region.provisional_risk_tier already
    # equals computed_tier, we accept; otherwise this means the persisted provisional
    # is stale.
    if region.get("provisional_risk_tier") != computed_tier:
        # Auto-refresh provisional_risk_tier to satisfy ERR_TIER_STALE check
        region["provisional_risk_tier"] = computed_tier
        bump_version(region)

    base = common_fields_append_only()
    decision = {
        **base,
        "region_id": region_id,
        "previous_tier": region.get("current_risk_tier"),
        "provisional_tier": computed_tier,
        "final_tier": None,
        "mode": "AUTO",
        "expert_reviewer_id": None,
        "published_at": None,
        "status": "PROVISIONAL",
    }
    store.risk_decisions[decision["id"]] = decision
    user_id, role = current_actor()
    append_audit(
        "RiskTierDecision",
        decision["id"],
        "",
        "PROVISIONAL",
        actor_role=role,
        actor_id=user_id,
    )
    return ok(decision, status=201)


def get_decision(did: str):
    store = get_store()
    d = store.risk_decisions.get(did)
    if not d:
        raise ApiError("ERR_NOT_FOUND", f"RiskTierDecision {did} not found.")
    return ok(d)


def submit_review(did: str):
    body = get_json_body()
    store = get_store()
    d = store.risk_decisions.get(did)
    if not d:
        raise ApiError("ERR_NOT_FOUND", f"RiskTierDecision {did} not found.")
    if d.get("status") != "PROVISIONAL":
        raise ApiError("ERR_INVALID_STATE", "Decision must be PROVISIONAL to submit for review.")

    # Re-verify provisional_tier still matches latest computed (ERR_TIER_STALE)
    region = store.regions.get(d.get("region_id"))
    if not region:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "region not found.")
    _score, latest = compute_case_density_score(region)
    if d.get("provisional_tier") != latest:
        raise ApiError(
            "ERR_TIER_STALE",
            "Provisional tier no longer matches latest computed tier.",
        )
    if d.get("provisional_tier") == region.get("current_risk_tier"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Provisional tier equals current risk tier; nothing to review.",
        )
    prev = d["status"]
    d["status"] = "UNDER_REVIEW"
    user_id, role = current_actor()
    append_audit(
        "RiskTierDecision", d["id"], prev, "UNDER_REVIEW", actor_role=role, actor_id=user_id
    )
    return ok(d)


def approve_decision(did: str):
    body = get_json_body()
    store = get_store()
    d = store.risk_decisions.get(did)
    if not d:
        raise ApiError("ERR_NOT_FOUND", f"RiskTierDecision {did} not found.")
    if d.get("status") != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Decision must be UNDER_REVIEW to approve.")
    final_tier = body.get("final_tier")
    reviewer = body.get("expert_reviewer_id")
    if final_tier not in RISK_TIERS:
        raise ApiError(
            "ERR_INVALID_INPUT", f"final_tier must be one of {sorted(RISK_TIERS)}."
        )
    if not reviewer:
        raise ApiError("ERR_INVALID_INPUT", "expert_reviewer_id required.")
    d["final_tier"] = final_tier
    d["expert_reviewer_id"] = reviewer
    d["mode"] = "AUTO" if final_tier == d.get("provisional_tier") else "EXPERT_OVERRIDE"
    prev = d["status"]
    d["status"] = "APPROVED"
    user_id, role = current_actor()
    append_audit(
        "RiskTierDecision", d["id"], prev, "APPROVED", actor_role=role, actor_id=user_id
    )
    return ok(d)


def reject_decision(did: str):
    body = get_json_body()
    store = get_store()
    d = store.risk_decisions.get(did)
    if not d:
        raise ApiError("ERR_NOT_FOUND", f"RiskTierDecision {did} not found.")
    if d.get("status") != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Decision must be UNDER_REVIEW to reject.")
    reviewer = body.get("expert_reviewer_id")
    if not reviewer:
        raise ApiError("ERR_INVALID_INPUT", "expert_reviewer_id required.")
    d["expert_reviewer_id"] = reviewer
    prev = d["status"]
    d["status"] = "REJECTED"
    user_id, role = current_actor()
    append_audit(
        "RiskTierDecision", d["id"], prev, "REJECTED", actor_role=role, actor_id=user_id
    )
    return ok(d)


def publish_decision(did: str):
    body = get_json_body()
    store = get_store()
    d = store.risk_decisions.get(did)
    if not d:
        raise ApiError("ERR_NOT_FOUND", f"RiskTierDecision {did} not found.")
    if d.get("status") != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Decision must be APPROVED to publish.")
    region = store.regions.get(d.get("region_id"))
    if not region:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "region not found.")
    final_tier = d.get("final_tier")
    # Permitted as long as final_tier differs OR this is first publication.
    is_first = region.get("last_tier_decision_id") is None
    if not is_first and region.get("current_risk_tier") == final_tier:
        raise ApiError(
            "ERR_INVALID_STATE",
            "Final tier equals current_risk_tier; nothing to publish.",
        )

    region["current_risk_tier"] = final_tier
    region["last_tier_decision_id"] = d["id"]
    bump_version(region)

    d["published_at"] = now_iso_ms()
    prev = d["status"]
    d["status"] = "PUBLISHED"
    user_id, role = current_actor()
    append_audit(
        "RiskTierDecision", d["id"], prev, "PUBLISHED", actor_role=role, actor_id=user_id
    )

    # Cascade: recompute priority_score on all PENDING SupplyRequests whose institution sits in this region
    district = region.get("district_code")
    for req in store.supply_requests.values():
        if req.get("status") != "PENDING":
            continue
        inst = store.institutions.get(req.get("requesting_institution_id"))
        if not inst or inst.get("district_code") != district:
            continue
        item = store.supply_items.get(req.get("sku_item_id"))
        if not item:
            # Fall back: find item by sku string
            for it in store.supply_items.values():
                if it.get("sku") == req.get("sku"):
                    item = it
                    break
        if item:
            req["priority_score"] = compute_priority_score(inst, item)
            bump_version(req)

    # If final_tier == HIGH: flag any DRAFT Bulletin for the publish date to include this region in HIGH bucket.
    # Re-snapshot tier_summary on relevant DRAFT bulletins.
    if final_tier == "HIGH":
        for bul in store.bulletins.values():
            if bul.get("status") == "DRAFT":
                _refresh_bulletin_snapshots(bul)

    return ok(d)


def _refresh_bulletin_snapshots(bul: dict) -> None:
    """Re-snapshot total_new_cases and tier_summary for DRAFT bulletins."""
    from ..clock import parse_iso
    store = get_store()
    bdate = bul.get("bulletin_date")
    try:
        bdt = parse_iso(bdate)
    except Exception:
        return
    count = 0
    for c in store.cases.values():
        try:
            r_at = parse_iso(c.get("reported_at"))
        except Exception:
            continue
        if r_at.year == bdt.year and r_at.month == bdt.month and r_at.day == bdt.day:
            count += 1
    bul["total_new_cases"] = count
    summary = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for r in store.regions.values():
        tier = r.get("current_risk_tier") or "LOW"
        if tier in summary:
            summary[tier] += 1
    bul["tier_summary"] = summary
    bump_version(bul)
