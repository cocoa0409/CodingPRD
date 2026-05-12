"""Template / TemplateVersion business logic per PRD §3.1."""

from db import DB, LOCK, new_id
from clock import now
from errors import (
    APIError, ERR_VALIDATION_FAILED, ERR_VERSION_CONFLICT, ERR_INVALID_STATE,
    ERR_NOT_FOUND, validation_failed, version_conflict, invalid_state, not_found,
)
from services.audit import append_audit


VALID_CATEGORIES = {"HR", "SALES", "PROCUREMENT", "LEGAL", "FINANCE", "OTHER"}
VALID_SCOPES = {"ORG_ONLY", "CROSS_ORG", "PUBLIC"}


def _validate_template_payload(payload: dict, required: bool = True):
    if not isinstance(payload, dict):
        raise validation_failed("Body must be a JSON object")
    if "name" in payload:
        n = payload["name"]
        if not isinstance(n, str) or not (1 <= len(n) <= 120):
            raise validation_failed("name must be a string of length 1..120")
    elif required:
        raise validation_failed("name is required")
    if "category" in payload:
        if payload["category"] not in VALID_CATEGORIES:
            raise validation_failed("category invalid")
    elif required:
        raise validation_failed("category is required")
    if "owner_org_id" in payload:
        if not isinstance(payload["owner_org_id"], str) or not payload["owner_org_id"]:
            raise validation_failed("owner_org_id must be a non-empty string")
    elif required:
        raise validation_failed("owner_org_id is required")
    if "permission_scope" in payload and payload["permission_scope"] is not None:
        if payload["permission_scope"] not in VALID_SCOPES:
            raise validation_failed("permission_scope invalid")


def create_template(payload: dict) -> dict:
    _validate_template_payload(payload, required=True)
    name = payload["name"]
    owner_org_id = payload["owner_org_id"]
    # uniqueness of (owner_org_id, name)
    for t in DB.templates.values():
        if t["owner_org_id"] == owner_org_id and t["name"] == name:
            raise validation_failed("Template name already exists for this owner_org_id")
    permission_scope = payload.get("permission_scope") or "ORG_ONLY"
    n = now()
    tid = new_id()
    t = {
        "id": tid,
        "name": name,
        "category": payload["category"],
        "owner_org_id": owner_org_id,
        "permission_scope": permission_scope,
        "latest_version_number": 0,
        "published_version_number": None,
        "status": "ACTIVE",
        "version": 1,
        "created_at": n,
        "updated_at": n,
    }
    DB.templates[tid] = t
    return t


def get_template(template_id: str) -> dict:
    t = DB.templates.get(template_id)
    if not t:
        raise not_found("Template not found")
    return t


def list_templates(category=None, owner_org_id=None, limit=10, offset=0):
    rows = list(DB.templates.values())
    if category:
        rows = [r for r in rows if r["category"] == category]
    if owner_org_id:
        rows = [r for r in rows if r["owner_org_id"] == owner_org_id]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    return rows[offset:offset + limit], total


def patch_template(template_id: str, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise validation_failed("Body must be a JSON object")
    t = get_template(template_id)
    # OCC
    if "version" in payload and payload["version"] is not None:
        if payload["version"] != t["version"]:
            raise version_conflict("Version mismatch")
    # validate present fields
    if "name" in payload:
        n = payload["name"]
        if not isinstance(n, str) or not (1 <= len(n) <= 120):
            raise validation_failed("name must be a string of length 1..120")
        # uniqueness within owner_org_id
        for other in DB.templates.values():
            if other["id"] == template_id:
                continue
            if other["owner_org_id"] == t["owner_org_id"] and other["name"] == n:
                raise validation_failed("Template name already exists for this owner_org_id")
        t["name"] = n
    if "category" in payload:
        if payload["category"] not in VALID_CATEGORIES:
            raise validation_failed("category invalid")
        t["category"] = payload["category"]
    if "permission_scope" in payload:
        if payload["permission_scope"] not in VALID_SCOPES:
            raise validation_failed("permission_scope invalid")
        t["permission_scope"] = payload["permission_scope"]
    t["version"] += 1
    t["updated_at"] = now()
    return t


# --- TemplateVersion --------------------------------------------------------

def _validate_version_payload(payload: dict, *, partial: bool = False):
    if not isinstance(payload, dict):
        raise validation_failed("Body must be a JSON object")
    if "document_blob_sha256" in payload:
        v = payload["document_blob_sha256"]
        if not isinstance(v, str) or len(v) != 64:
            raise validation_failed("document_blob_sha256 must be 64-char lowercase hex")
        try:
            int(v, 16)
        except Exception:
            raise validation_failed("document_blob_sha256 must be hex")
        if v.lower() != v:
            raise validation_failed("document_blob_sha256 must be lowercase hex")
    elif not partial:
        raise validation_failed("document_blob_sha256 is required")
    if "page_count" in payload:
        pc = payload["page_count"]
        if not isinstance(pc, int) or isinstance(pc, bool) or pc < 1:
            raise validation_failed("page_count must be an integer >= 1")
    elif not partial:
        raise validation_failed("page_count is required")
    if "variable_fields" in payload:
        vf = payload["variable_fields"]
        if not isinstance(vf, list):
            raise validation_failed("variable_fields must be an array")
    elif not partial:
        raise validation_failed("variable_fields is required")
    if "signature_positions" in payload:
        sp = payload["signature_positions"]
        if not isinstance(sp, list):
            raise validation_failed("signature_positions must be an array")
        for s in sp:
            if not isinstance(s, dict):
                raise validation_failed("signature_positions entries must be objects")
            if s.get("kind") not in ("NORMAL", "SEAM"):
                raise validation_failed("signature_positions.kind must be NORMAL or SEAM")
    elif not partial:
        raise validation_failed("signature_positions is required")


def create_template_version(template_id: str, payload: dict) -> dict:
    t = get_template(template_id)
    _validate_version_payload(payload, partial=False)
    new_vn = t["latest_version_number"] + 1
    n = now()
    vid = new_id()
    v = {
        "id": vid,
        "template_id": template_id,
        "version_number": new_vn,
        "document_blob_sha256": payload["document_blob_sha256"],
        "page_count": payload["page_count"],
        "variable_fields": payload["variable_fields"],
        "signature_positions": payload["signature_positions"],
        "status": "DRAFT",
        "version": 1,
        "created_at": n,
        "updated_at": n,
    }
    DB.template_versions[vid] = v
    t["latest_version_number"] = new_vn
    t["version"] += 1
    t["updated_at"] = n
    return v


def get_template_version(template_id: str, vid: str) -> dict:
    # path validated left to right
    t = DB.templates.get(template_id)
    if not t:
        raise not_found("Template not found")
    v = DB.template_versions.get(vid)
    if not v or v["template_id"] != template_id:
        raise not_found("TemplateVersion not found")
    return v


def list_template_versions(template_id: str, status=None, limit=10, offset=0):
    if template_id not in DB.templates:
        raise not_found("Template not found")
    rows = [v for v in DB.template_versions.values() if v["template_id"] == template_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    return rows[offset:offset + limit], total


def patch_template_version(template_id: str, vid: str, payload: dict) -> dict:
    v = get_template_version(template_id, vid)
    if v["status"] != "DRAFT":
        raise invalid_state("TemplateVersion is not in DRAFT")
    if not isinstance(payload, dict):
        raise validation_failed("Body must be a JSON object")
    if "version" in payload and payload["version"] is not None:
        if payload["version"] != v["version"]:
            raise version_conflict("Version mismatch")
    _validate_version_payload(payload, partial=True)
    if "document_blob_sha256" in payload:
        v["document_blob_sha256"] = payload["document_blob_sha256"]
    if "page_count" in payload:
        v["page_count"] = payload["page_count"]
    if "variable_fields" in payload:
        v["variable_fields"] = payload["variable_fields"]
    if "signature_positions" in payload:
        v["signature_positions"] = payload["signature_positions"]
    v["version"] += 1
    v["updated_at"] = now()
    return v


def publish_template_version(template_id: str, vid: str, *, actor_user_id: str, actor_role: str) -> dict:
    v = get_template_version(template_id, vid)
    if v["status"] != "DRAFT":
        raise invalid_state("TemplateVersion must be DRAFT to publish")
    if not v["signature_positions"] or len(v["signature_positions"]) < 1:
        raise invalid_state("TemplateVersion must have at least one signature_position")
    n = now()
    v["status"] = "PUBLISHED"
    v["version"] += 1
    v["updated_at"] = n
    t = DB.templates[template_id]
    t["published_version_number"] = v["version_number"]
    t["version"] += 1
    t["updated_at"] = n
    DB.template_version_publisher[vid] = actor_user_id
    append_audit(
        template_id=template_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action="TEMPLATE_PUBLISHED",
        payload={"template_version_id": vid, "version_number": v["version_number"]},
    )
    return v


def deprecate_template_version(template_id: str, vid: str, *, actor_user_id: str, actor_role: str) -> dict:
    v = get_template_version(template_id, vid)
    if v["status"] != "PUBLISHED":
        raise invalid_state("TemplateVersion must be PUBLISHED to deprecate")
    # No Contract referencing this in {DRAFT, PENDING_SIGN, PARTIALLY_SIGNED}
    blocking = {"DRAFT", "PENDING_SIGN", "PARTIALLY_SIGNED"}
    for c in DB.contracts.values():
        if c["template_version_id"] == vid and c["status"] in blocking:
            raise invalid_state("Contracts depending on this version are still active")
    n = now()
    v["status"] = "DEPRECATED"
    v["version"] += 1
    v["updated_at"] = n
    t = DB.templates[template_id]
    if t.get("published_version_number") == v["version_number"]:
        t["published_version_number"] = None
        t["version"] += 1
        t["updated_at"] = n
    append_audit(
        template_id=template_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action="TEMPLATE_DEPRECATED",
        payload={"template_version_id": vid, "version_number": v["version_number"]},
    )
    return v
