"""Edit library endpoints: EditRule + EditVersion lifecycle."""

from flask import Blueprint, request

import db
from errors import raise_err
from middleware import (
    get_body,
    pagination_params,
    require_auth,
    require_role,
    validate_body,
)
from response import success_list, success_object
from serializers import serialize
from services import core
from services.calc import FP_SUSPEND_THRESHOLD
from decimal import Decimal

bp = Blueprint("edits", __name__)
PREFIX = "/payment-integrity"

CLAIM_TYPES = {"PROFESSIONAL", "INSTITUTIONAL_INPATIENT", "INSTITUTIONAL_OUTPATIENT"}


# ---------------------------------------------------------------------------
# Edit rules
# ---------------------------------------------------------------------------

@bp.route(PREFIX + "/edit-rules", methods=["POST"])
def create_edit_rule():
    user_id, role = require_auth()
    require_role(role, ["EditLibrarian"])
    body = get_body()
    vals = validate_body(
        body,
        {
            "edit_code": (True, "string", None),
            "category": (True, "string", {"CLINICAL", "CODING", "POLICY"}),
            "source": (True, "string", {"INTERNAL", "VENDOR"}),
            "description": (False, "string", None),
        },
    )
    rule = db.create_resource(
        "edit_rules",
        {
            "edit_code": vals["edit_code"],
            "category": vals["category"],
            "source": vals["source"],
            "description": vals.get("description", ""),
            "active_version_count": 0,
        },
    )
    return success_object(serialize(rule), status=201)


@bp.route(PREFIX + "/edit-rules", methods=["GET"])
def list_edit_rules():
    require_auth()
    limit, offset = pagination_params()
    category = request.args.get("category")
    source = request.args.get("source")
    rows = db.all_records("edit_rules")
    if category is not None:
        if category not in ("CLINICAL", "CODING", "POLICY"):
            raise_err("ERR_INVALID_ENUM", "category filter carries undeclared member")
        rows = [r for r in rows if r["category"] == category]
    if source is not None:
        if source not in ("INTERNAL", "VENDOR"):
            raise_err("ERR_INVALID_ENUM", "source filter carries undeclared member")
        rows = [r for r in rows if r["source"] == source]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    return success_list([serialize(r) for r in rows[offset : offset + limit]], limit, offset, total)


@bp.route(PREFIX + "/edit-rules/<rid>", methods=["GET"])
def get_edit_rule(rid):
    require_auth()
    rule = db.get("edit_rules", rid)
    if rule is None:
        raise_err("ERR_EDIT_RULE_NOT_FOUND", "Edit rule not found")
    return success_object(serialize(rule))


# ---------------------------------------------------------------------------
# Edit versions
# ---------------------------------------------------------------------------

@bp.route(PREFIX + "/edit-rules/<rid>/versions", methods=["POST"])
def create_edit_version(rid):
    user_id, role = require_auth()
    require_role(role, ["EditLibrarian"])
    body = get_body()
    vals = validate_body(
        body,
        {
            "severity": (True, "string", {"DENY", "SUSPEND", "MONITOR"}),
            "applies_to_claim_types": (True, "array", CLAIM_TYPES),
            "logic_expression": (True, "string", None),
            "effective_from": (True, "datetime", None),
            "effective_to": (False, "datetime", None),
        },
    )
    if len(vals["applies_to_claim_types"]) < 1:
        raise_err("ERR_INVALID_REQUEST", "applies_to_claim_types must be non-empty")
    rule = db.get("edit_rules", rid)
    if rule is None:
        raise_err("ERR_EDIT_RULE_NOT_FOUND", "Edit rule not found")
    # Sequential version_number per rule, starts at 1, in creation order
    existing = [v for v in db.all_records("edit_versions") if v["edit_rule_id"] == rid]
    version_number = len(existing) + 1
    version = db.create_resource(
        "edit_versions",
        {
            "edit_rule_id": rid,
            "version_number": version_number,
            "severity": vals["severity"],
            "applies_to_claim_types": vals["applies_to_claim_types"],
            "logic_expression": vals["logic_expression"],
            "effective_from": vals["effective_from"],
            "effective_to": vals.get("effective_to"),
            "status": "DRAFT",
            "created_by_user_id": user_id,
            "approved_by_user_id": None,
            "resolved_hits_count": 0,
            "fp_hits_count": 0,
            "fp_rate": 0,
        },
    )
    return success_object(serialize(version), status=201)


@bp.route(PREFIX + "/edit-rules/<rid>/versions", methods=["GET"])
def list_rule_versions(rid):
    require_auth()
    rule = db.get("edit_rules", rid)
    if rule is None:
        raise_err("ERR_EDIT_RULE_NOT_FOUND", "Edit rule not found")
    limit, offset = pagination_params()
    rows = [v for v in db.all_records("edit_versions") if v["edit_rule_id"] == rid]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    return success_list([serialize(r) for r in rows[offset : offset + limit]], limit, offset, total)


@bp.route(PREFIX + "/edit-versions", methods=["GET"])
def list_edit_versions():
    require_auth()
    limit, offset = pagination_params()
    rule_filter = request.args.get("edit_rule_id")
    status_filter = request.args.get("status")
    rows = db.all_records("edit_versions")
    if rule_filter is not None:
        rows = [r for r in rows if r["edit_rule_id"] == rule_filter]
    if status_filter is not None:
        if status_filter not in ("DRAFT", "PENDING_APPROVAL", "ACTIVE", "SUSPENDED", "RETIRED"):
            raise_err("ERR_INVALID_ENUM", "status filter carries undeclared member")
        rows = [r for r in rows if r["status"] == status_filter]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    return success_list([serialize(r) for r in rows[offset : offset + limit]], limit, offset, total)


@bp.route(PREFIX + "/edit-versions/<vid>", methods=["GET"])
def get_edit_version(vid):
    require_auth()
    version = db.get("edit_versions", vid)
    if version is None:
        raise_err("ERR_EDIT_VERSION_NOT_FOUND", "Edit version not found")
    return success_object(serialize(version))


def _get_version_or_404(vid):
    version = db.get("edit_versions", vid)
    if version is None:
        raise_err("ERR_EDIT_VERSION_NOT_FOUND", "Edit version not found")
    return version


@bp.route(PREFIX + "/edit-versions/<vid>/submit", methods=["POST"])
def submit_version(vid):
    user_id, role = require_auth()
    require_role(role, ["EditLibrarian"])
    body = get_body()
    validate_body(body, {})
    version = _get_version_or_404(vid)
    if version["status"] != "DRAFT":
        raise_err("ERR_EDIT_VERSION_NOT_APPROVABLE", "submit requires DRAFT")
    version["status"] = "PENDING_APPROVAL"
    db.touch(version)
    return success_object(serialize(version))


@bp.route(PREFIX + "/edit-versions/<vid>/approve", methods=["POST"])
def approve_version(vid):
    user_id, role = require_auth()
    require_role(role, ["EditApprover"])
    body = get_body()
    vals = validate_body(
        body,
        {
            "expected_edit_rule_version": (True, "integer", None),
            "clinical_review_attestation": (False, "boolean", None),
        },
    )
    version = _get_version_or_404(vid)
    rule = db.get("edit_rules", version["edit_rule_id"])
    if rule is None:
        raise_err("ERR_EDIT_RULE_NOT_FOUND", "Edit rule not found")
    # Band 6: OCC on EditRule.version
    if vals["expected_edit_rule_version"] != rule["version"]:
        raise_err("ERR_STALE_VERSION", "Stale edit-rule version; re-read before approving")
    # Band 7: state
    if version["status"] != "PENDING_APPROVAL":
        raise_err("ERR_EDIT_VERSION_NOT_APPROVABLE", "approve requires PENDING_APPROVAL")
    # Band 8: SoD then clinical attestation (PRD 3.2 fixed surfacing order)
    if user_id == version["created_by_user_id"]:
        raise_err("ERR_SOD_AUTHOR_APPROVAL", "Approver must differ from author")
    if (
        version["severity"] == "DENY"
        and "INSTITUTIONAL_INPATIENT" in version["applies_to_claim_types"]
        and vals.get("clinical_review_attestation") is not True
    ):
        raise_err(
            "ERR_CLINICAL_ATTESTATION_REQUIRED",
            "DENY edit applicable to INSTITUTIONAL_INPATIENT requires clinical_review_attestation",
        )
    # Band 9: half-open window overlap against other ACTIVE versions of the rule
    for other in db.all_records("edit_versions"):
        if other["id"] == version["id"]:
            continue
        if other["edit_rule_id"] != rule["id"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        if core.windows_overlap(
            version["effective_from"], version["effective_to"],
            other["effective_from"], other["effective_to"],
        ):
            raise_err("ERR_EDIT_WINDOW_OVERLAP", "Window overlaps another ACTIVE version")
    version["status"] = "ACTIVE"
    version["approved_by_user_id"] = user_id
    db.touch(version)
    core.recompute_rule_active_count(rule)
    return success_object(serialize(version))


@bp.route(PREFIX + "/edit-versions/<vid>/reject", methods=["POST"])
def reject_version(vid):
    user_id, role = require_auth()
    require_role(role, ["EditApprover"])
    body = get_body()
    validate_body(body, {"rejection_reason": (False, "string", None)})
    version = _get_version_or_404(vid)
    if version["status"] != "PENDING_APPROVAL":
        raise_err("ERR_EDIT_VERSION_NOT_APPROVABLE", "reject requires PENDING_APPROVAL")
    version["status"] = "DRAFT"
    db.touch(version)
    return success_object(serialize(version))


@bp.route(PREFIX + "/edit-versions/<vid>/suspend", methods=["POST"])
def suspend_version_endpoint(vid):
    user_id, role = require_auth()
    require_role(role, ["EditApprover"])
    body = get_body()
    validate_body(body, {"note": (False, "string", None)})
    version = _get_version_or_404(vid)
    if version["status"] != "ACTIVE":
        raise_err("ERR_EDIT_VERSION_NOT_APPROVABLE", "suspend requires ACTIVE")
    core.suspend_version(version)
    return success_object(serialize(version))


@bp.route(PREFIX + "/edit-versions/<vid>/reactivate", methods=["POST"])
def reactivate_version(vid):
    user_id, role = require_auth()
    require_role(role, ["EditApprover"])
    body = get_body()
    validate_body(body, {})
    version = _get_version_or_404(vid)
    if version["status"] != "SUSPENDED":
        raise_err("ERR_EDIT_VERSION_NOT_APPROVABLE", "reactivate requires SUSPENDED")
    if Decimal(str(version["fp_rate"])) >= FP_SUSPEND_THRESHOLD:
        raise_err("ERR_EDIT_VERSION_NOT_APPROVABLE", "fp_rate at/above suspension threshold")
    version["status"] = "ACTIVE"
    db.touch(version)
    rule = db.get("edit_rules", version["edit_rule_id"])
    if rule is not None:
        core.recompute_rule_active_count(rule)
    return success_object(serialize(version))


@bp.route(PREFIX + "/edit-versions/<vid>/retire", methods=["POST"])
def retire_version(vid):
    user_id, role = require_auth()
    require_role(role, ["EditApprover"])
    body = get_body()
    validate_body(body, {})
    version = _get_version_or_404(vid)
    if version["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_err("ERR_EDIT_VERSION_NOT_APPROVABLE", "retire requires ACTIVE or SUSPENDED")
    # Band 11: no FIRED hits pinned to this version
    for hit in db.all_records("edit_hits"):
        if hit["edit_version_id"] == version["id"] and hit["status"] == "FIRED":
            raise_err("ERR_EDIT_VERSION_IN_USE", "FIRED hits are pinned to this version")
    version["status"] = "RETIRED"
    db.touch(version)
    rule = db.get("edit_rules", version["edit_rule_id"])
    if rule is not None:
        core.recompute_rule_active_count(rule)
    return success_object(serialize(version))
