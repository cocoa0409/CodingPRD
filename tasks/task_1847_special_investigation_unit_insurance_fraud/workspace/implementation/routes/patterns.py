"""Provider pattern endpoints (PRD §3.8): organized-ring analysis."""

from __future__ import annotations

from flask import Blueprint

import db
from constants import CASE_TERMINAL, PATTERN_ESCALATION_THRESHOLD
from errors import (
    raise_err,
    ERR_INVALID_STATE,
    ERR_PATTERN_MERGE_INVALID,
)
from middleware import require_roles
from response import success_list, success_object
from serializers import pub_pattern
from services.scoring import recompute_pattern_score
from util import (
    apply_filters,
    fk_or_404,
    get_json_body,
    page_of,
    parse_pagination,
    path_or_404,
    require_string,
    sort_created,
)

bp = Blueprint("patterns", __name__)

READERS = ("SIUManager", "SIUInvestigator", "SIUComplianceOfficer")


@bp.post("/siu/provider-patterns")
@require_roles("SIUInvestigator", "SIUManager")
def create_pattern(_user_id: str, _role: str):
    body = get_json_body()
    provider_npi = require_string(body, "provider_npi")
    provider_name = require_string(body, "provider_name")
    ring_signature = require_string(body, "ring_signature")
    pattern = {
        "provider_npi": provider_npi,
        "provider_name": provider_name,
        "ring_signature": ring_signature,
        "linked_case_ids": [],
        "pattern_score": 0,
        "escalation_status": "MONITORING",
        "parent_pattern_id": None,
    }
    recompute_pattern_score(pattern)
    db.stamp_new(pattern)
    db.provider_patterns[pattern["id"]] = pattern
    return success_object(pub_pattern(pattern), 201)


@bp.get("/siu/provider-patterns/<patternId>")
@require_roles(*READERS)
def get_pattern(patternId: str, _user_id: str, _role: str):
    pattern = path_or_404(db.provider_patterns, patternId, "ProviderPattern")
    return success_object(pub_pattern(pattern))


@bp.get("/siu/provider-patterns")
@require_roles(*READERS)
def list_patterns(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = apply_filters(
        list(db.provider_patterns.values()),
        ["escalation_status", "ring_signature", "parent_pattern_id"],
    )
    items = sort_created(items)
    page, total = page_of(items, limit, offset)
    return success_list([pub_pattern(p) for p in page], limit, offset, total)


@bp.post("/siu/provider-patterns/<patternId>/escalate")
@require_roles("SIUManager")
def escalate_pattern(patternId: str, _user_id: str, _role: str):
    get_json_body()
    pattern = path_or_404(db.provider_patterns, patternId, "ProviderPattern")
    if pattern.get("escalation_status") != "MONITORING":
        raise_err(ERR_INVALID_STATE, "Pattern must be MONITORING to be escalated")
    if int(pattern.get("pattern_score", 0)) < PATTERN_ESCALATION_THRESHOLD:
        raise_err(ERR_INVALID_STATE, "pattern_score is below the escalation threshold")
    pattern["escalation_status"] = "ESCALATED_TO_NICB"
    db.touch(pattern)
    return success_object(pub_pattern(pattern))


@bp.post("/siu/provider-patterns/<patternId>/clear")
@require_roles("SIUManager")
def clear_pattern(patternId: str, _user_id: str, _role: str):
    get_json_body()
    pattern = path_or_404(db.provider_patterns, patternId, "ProviderPattern")
    if pattern.get("escalation_status") != "MONITORING":
        raise_err(ERR_INVALID_STATE, "Pattern must be MONITORING to be cleared")
    for case_id in pattern.get("linked_case_ids") or []:
        case = db.cases.get(case_id)
        if case is not None and case.get("status") not in CASE_TERMINAL:
            raise_err(ERR_INVALID_STATE, "All linked cases must be in terminal states")
    pattern["escalation_status"] = "CLEARED"
    db.touch(pattern)
    return success_object(pub_pattern(pattern))


@bp.post("/siu/provider-patterns/<patternId>/merge")
@require_roles("SIUManager")
def merge_pattern(patternId: str, _user_id: str, _role: str):
    body = get_json_body()
    parent_pattern_id = require_string(body, "parent_pattern_id")
    pattern = path_or_404(db.provider_patterns, patternId, "ProviderPattern")
    parent = fk_or_404(db.provider_patterns, parent_pattern_id, "ProviderPattern")
    if pattern.get("escalation_status") != "MONITORING":
        raise_err(ERR_INVALID_STATE, "Pattern must be MONITORING to be merged")
    if (
        parent["id"] == pattern["id"]
        or parent.get("escalation_status") != "MONITORING"
        or parent.get("ring_signature") != pattern.get("ring_signature")
    ):
        raise_err(
            ERR_PATTERN_MERGE_INVALID,
            "parent_pattern must be a different MONITORING pattern with the same ring_signature",
        )
    merged = parent.setdefault("linked_case_ids", [])
    for case_id in pattern.get("linked_case_ids") or []:
        if case_id not in merged:
            merged.append(case_id)
    recompute_pattern_score(parent)
    db.touch(parent)
    pattern["escalation_status"] = "MERGED_INTO_RING"
    pattern["parent_pattern_id"] = parent["id"]
    db.touch(pattern)
    return success_object(pub_pattern(pattern))
