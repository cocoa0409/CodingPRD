"""Catalog services: Department, Matter, MatterVersion, MaterialTemplate, CertificateTemplate."""

from __future__ import annotations

import re
from typing import Any

from flask import g

import db
from config import (
    AGGREGATION_RULES,
    APPLICATION_TERMINAL,
    CHANNELS,
    DEPARTMENT_STATUSES,
    DEPT_CODE_MAX_LEN,
    DEPT_CODE_MIN_LEN,
    MATERIAL_TYPES,
    MATTER_CODE_MAX_LEN,
    MATTER_CODE_MIN_LEN,
    ROUTING_MODES,
    TEMPLATE_CODE_MAX_LEN,
    TEMPLATE_CODE_MIN_LEN,
    THEMES,
    VERSION_LABEL_MAX_LEN,
    VERSION_LABEL_MIN_LEN,
)
from errors import (
    AppError,
    ERR_DEPENDENT_TEMPLATE_UNPUBLISHED,
    ERR_DUPLICATE_RESOURCE,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_ROUTING_INVALID,
    ERR_TIME_LIMIT_INVERSION,
    ERR_VALIDATION_FAILED,
)
from services import validators as V

DEPT_CODE_RE = re.compile(r"^[A-Z_]+$")


# =============================================================================
# Department
# =============================================================================

def create_department(body: dict) -> dict:
    body = V.must_be_dict(body)
    code = V.require_str(body, "code", min_len=DEPT_CODE_MIN_LEN,
                         max_len=DEPT_CODE_MAX_LEN)
    if not DEPT_CODE_RE.match(code):
        raise AppError(ERR_VALIDATION_FAILED,
                       "Department code must be uppercase letters and underscores",
                       422)
    name = V.require_str(body, "name")
    parent_id = V.opt_str(body, "parent_department_id", default=None)
    status = V.opt_str(body, "status", default="ACTIVE") or "ACTIVE"
    if status not in DEPARTMENT_STATUSES:
        raise AppError(ERR_VALIDATION_FAILED,
                       f"status must be one of {sorted(DEPARTMENT_STATUSES)}",
                       422)

    if db.find_one("departments", code=code):
        raise AppError(ERR_DUPLICATE_RESOURCE,
                       f"Department code already exists: {code}",
                       409)
    if parent_id is not None:
        parent = db.find_by_id("departments", parent_id)
        if not parent:
            raise AppError(ERR_NOT_FOUND,
                           f"Parent department not found: {parent_id}", 404)

    record = db.insert("departments", {
        "code": code,
        "name": name,
        "parent_department_id": parent_id,
        "status": status,
    })
    return record


def list_departments(filters: dict, limit: int, offset: int):
    use_filters = {k: v for k, v in filters.items() if v is not None}
    return db.query("departments", filters=use_filters, limit=limit, offset=offset)


# =============================================================================
# Matter & MatterVersion
# =============================================================================

def create_matter(body: dict) -> dict:
    body = V.must_be_dict(body)
    code = V.require_str(body, "code", min_len=MATTER_CODE_MIN_LEN,
                         max_len=MATTER_CODE_MAX_LEN)
    theme = V.require_str(body, "theme")
    if theme not in THEMES:
        raise AppError(ERR_VALIDATION_FAILED,
                       f"theme must be one of {sorted(THEMES)}", 422)
    owning_department_id = V.require_str(body, "owning_department_id")

    dept = db.find_by_id("departments", owning_department_id)
    if not dept:
        raise AppError(ERR_NOT_FOUND,
                       f"Owning department not found: {owning_department_id}", 404)
    # Ownership: a CatalogManager's X-User-ID must equal the owning department.
    if g.role == "CatalogManager" and g.user_id != owning_department_id:
        from errors import ERR_FORBIDDEN
        raise AppError(ERR_FORBIDDEN,
                       "CatalogManager may only create matters owned by their department",
                       403)
    if db.find_one("matters", code=code):
        raise AppError(ERR_DUPLICATE_RESOURCE,
                       f"Matter code already exists: {code}", 409)

    return db.insert("matters", {
        "code": code,
        "theme": theme,
        "owning_department_id": owning_department_id,
        "current_published_version_id": None,
        "status": "DRAFT_ONLY",
    })


def list_matters(filters: dict, limit: int, offset: int):
    use_filters = {k: v for k, v in filters.items() if v is not None}
    return db.query("matters", filters=use_filters, limit=limit, offset=offset)


def get_matter(matter_id: str) -> dict:
    matter = db.find_by_id("matters", matter_id)
    if not matter:
        raise AppError(ERR_NOT_FOUND, f"Matter not found: {matter_id}", 404)
    return matter


# ----- Routing validation -----

def _validate_routing(routing: Any) -> None:
    if not isinstance(routing, dict):
        raise AppError(ERR_ROUTING_INVALID, "review_routing must be an object", 422)
    mode = routing.get("mode")
    if mode not in ROUTING_MODES:
        raise AppError(ERR_ROUTING_INVALID,
                       f"routing.mode must be one of {sorted(ROUTING_MODES)}", 422)
    stages = routing.get("stages")
    if not isinstance(stages, list) or len(stages) < 1:
        raise AppError(ERR_ROUTING_INVALID,
                       "routing.stages must be a non-empty array", 422)
    for s in stages:
        if not isinstance(s, dict):
            raise AppError(ERR_ROUTING_INVALID, "stage must be object", 422)
        dep_id = s.get("department_id")
        sla_days = s.get("sla_days")
        if not isinstance(dep_id, str) or not dep_id:
            raise AppError(ERR_ROUTING_INVALID,
                           "stage.department_id must be a non-empty string", 422)
        if isinstance(sla_days, bool) or not isinstance(sla_days, int):
            raise AppError(ERR_ROUTING_INVALID,
                           "stage.sla_days must be an integer", 422)
        if sla_days < 1:
            raise AppError(ERR_ROUTING_INVALID,
                           "stage.sla_days must be >= 1", 422)
    lead = routing.get("lead_department_id")
    if not isinstance(lead, str) or not lead:
        raise AppError(ERR_ROUTING_INVALID,
                       "routing.lead_department_id must be present", 422)
    if not any(s["department_id"] == lead for s in stages):
        raise AppError(ERR_ROUTING_INVALID,
                       "routing.lead_department_id must appear in stages", 422)
    rule = routing.get("aggregation_rule")
    if mode == "PARALLEL":
        if rule not in AGGREGATION_RULES:
            raise AppError(ERR_ROUTING_INVALID,
                           f"PARALLEL routing requires aggregation_rule one of {sorted(AGGREGATION_RULES)}",
                           422)
    else:  # SERIAL
        if rule is not None:
            raise AppError(ERR_ROUTING_INVALID,
                           "SERIAL routing requires aggregation_rule == null", 422)


# ----- MatterVersion -----

def create_matter_version(matter_id: str, body: dict) -> dict:
    matter = get_matter(matter_id)
    body = V.must_be_dict(body)

    # Ownership: CatalogManager X-User-ID == owning_department_id
    if g.role == "CatalogManager" and g.user_id != matter["owning_department_id"]:
        from errors import ERR_FORBIDDEN
        raise AppError(ERR_FORBIDDEN,
                       "CatalogManager may only create versions on matters owned by their department",
                       403)

    version_label = V.require_str(body, "version_label",
                                  min_len=VERSION_LABEL_MIN_LEN,
                                  max_len=VERSION_LABEL_MAX_LEN)
    legal_basis = V.require_str(body, "legal_basis")
    conditions = V.require_str(body, "conditions")
    required_material_template_ids = V.require_list(
        body, "required_material_template_ids", non_empty=True)
    for tid in required_material_template_ids:
        if not isinstance(tid, str):
            raise AppError(ERR_VALIDATION_FAILED,
                           "required_material_template_ids entries must be strings", 422)
    statutory_days = V.require_int(body, "statutory_time_limit_days",
                                   min_value=1, max_value=365)
    committed_days = V.require_int(body, "committed_time_limit_days", min_value=1)
    if committed_days > statutory_days:
        raise AppError(ERR_TIME_LIMIT_INVERSION,
                       "committed_time_limit_days must be <= statutory_time_limit_days",
                       422)
    warning_threshold_pct = V.opt_int(body, "warning_threshold_pct", default=80,
                                      min_value=50, max_value=99)
    fee_amount_cents = V.opt_int(body, "fee_amount_cents", default=0, min_value=0)
    channels = V.require_list(body, "channels", non_empty=True)
    for c in channels:
        if c not in CHANNELS:
            raise AppError(ERR_VALIDATION_FAILED,
                           f"channels must be a subset of {sorted(CHANNELS)}",
                           422)
    routing = body.get("review_routing")
    _validate_routing(routing)

    max_correction_rounds = V.opt_int(body, "max_correction_rounds", default=2,
                                      min_value=1, max_value=5)
    correction_window_days = V.opt_int(body, "correction_window_days", default=7,
                                       min_value=1, max_value=30)
    certificate_template_id = V.require_str(body, "certificate_template_id")

    # Existence checks for foreign-keyed templates (existence priority).
    for tid in required_material_template_ids:
        if not db.find_by_id("material_templates", tid):
            raise AppError(ERR_NOT_FOUND,
                           f"MaterialTemplate not found: {tid}", 404)
    if not db.find_by_id("certificate_templates", certificate_template_id):
        raise AppError(ERR_NOT_FOUND,
                       f"CertificateTemplate not found: {certificate_template_id}",
                       404)

    # Departments referenced by routing must exist.
    for s in routing["stages"]:
        if not db.find_by_id("departments", s["department_id"]):
            raise AppError(ERR_NOT_FOUND,
                           f"Department not found: {s['department_id']}", 404)
    if not db.find_by_id("departments", routing["lead_department_id"]):
        raise AppError(ERR_NOT_FOUND,
                       f"Lead department not found: {routing['lead_department_id']}",
                       404)

    # Unique version_label within matter.
    existing = [v for v in db.find_many("matter_versions", matter_id=matter_id)
                if v.get("version_label") == version_label]
    if existing:
        raise AppError(ERR_DUPLICATE_RESOURCE,
                       f"version_label '{version_label}' already exists for this matter",
                       409)

    return db.insert("matter_versions", {
        "matter_id": matter_id,
        "version_label": version_label,
        "legal_basis": legal_basis,
        "conditions": conditions,
        "required_material_template_ids": list(required_material_template_ids),
        "statutory_time_limit_days": statutory_days,
        "committed_time_limit_days": committed_days,
        "warning_threshold_pct": warning_threshold_pct,
        "fee_amount_cents": fee_amount_cents,
        "channels": list(channels),
        "review_routing": routing,
        "max_correction_rounds": max_correction_rounds,
        "correction_window_days": correction_window_days,
        "certificate_template_id": certificate_template_id,
        "status": "DRAFT",
        "published_at": None,
    })


def get_matter_version(matter_id: str, version_id: str) -> dict:
    matter = get_matter(matter_id)
    version = db.find_by_id("matter_versions", version_id)
    if not version or version.get("matter_id") != matter_id:
        raise AppError(ERR_NOT_FOUND, f"MatterVersion not found: {version_id}", 404)
    return version


def publish_matter_version(matter_id: str, version_id: str, body: dict) -> dict:
    matter = get_matter(matter_id)
    version = db.find_by_id("matter_versions", version_id)
    if not version or version.get("matter_id") != matter_id:
        raise AppError(ERR_NOT_FOUND, f"MatterVersion not found: {version_id}", 404)

    if g.role == "CatalogManager" and g.user_id != matter["owning_department_id"]:
        from errors import ERR_FORBIDDEN
        raise AppError(ERR_FORBIDDEN,
                       "CatalogManager may only publish versions on matters owned by their department",
                       403)

    # State precondition.
    if version["status"] != "DRAFT":
        raise AppError(ERR_INVALID_STATE,
                       f"MatterVersion must be DRAFT to publish (current: {version['status']})",
                       409)

    # OCC.
    from services import occ
    occ.check(version, body)

    # Routing check (priority 15).
    _validate_routing(version["review_routing"])

    # Time-limit inversion check (priority 14).
    if version["committed_time_limit_days"] > version["statutory_time_limit_days"]:
        raise AppError(ERR_TIME_LIMIT_INVERSION,
                       "committed_time_limit_days must be <= statutory_time_limit_days",
                       422)

    # Dependent templates published (priority 13).
    for tid in version["required_material_template_ids"]:
        mt = db.find_by_id("material_templates", tid)
        if not mt or mt["status"] != "PUBLISHED":
            raise AppError(ERR_DEPENDENT_TEMPLATE_UNPUBLISHED,
                           f"MaterialTemplate {tid} is not PUBLISHED", 422)
    ct = db.find_by_id("certificate_templates", version["certificate_template_id"])
    if not ct or ct["status"] != "PUBLISHED":
        raise AppError(ERR_DEPENDENT_TEMPLATE_UNPUBLISHED,
                       "CertificateTemplate is not PUBLISHED", 422)

    # Auto-cascade: prior PUBLISHED sibling -> SUPERSEDED.
    prior_pub_id = matter.get("current_published_version_id")
    if prior_pub_id and prior_pub_id != version_id:
        prior = db.find_by_id("matter_versions", prior_pub_id)
        if prior and prior["status"] == "PUBLISHED":
            db.update("matter_versions", prior_pub_id, {"status": "SUPERSEDED"})

    now = db.now_iso()
    db.update("matter_versions", version_id, {
        "status": "PUBLISHED",
        "published_at": now,
    })
    db.update("matters", matter_id, {
        "current_published_version_id": version_id,
        "status": "PUBLISHED",
    })
    return db.find_by_id("matter_versions", version_id)


def retire_matter_version(matter_id: str, version_id: str, body: dict) -> dict:
    matter = get_matter(matter_id)
    version = db.find_by_id("matter_versions", version_id)
    if not version or version.get("matter_id") != matter_id:
        raise AppError(ERR_NOT_FOUND, f"MatterVersion not found: {version_id}", 404)

    if g.role == "CatalogManager" and g.user_id != matter["owning_department_id"]:
        from errors import ERR_FORBIDDEN
        raise AppError(ERR_FORBIDDEN,
                       "CatalogManager may only retire versions on owned matters",
                       403)

    if version["status"] not in {"PUBLISHED", "SUPERSEDED"}:
        raise AppError(ERR_INVALID_STATE,
                       f"Cannot retire MatterVersion in status {version['status']}",
                       409)

    from services import occ
    occ.check(version, body)

    # No in-flight Application referencing this version.
    in_flight = [a for a in db.find_many("applications", matter_version_id=version_id)
                 if a["review_status"] not in APPLICATION_TERMINAL]
    if in_flight:
        raise AppError(ERR_INVALID_STATE,
                       "Cannot retire: in-flight applications reference this version",
                       409)

    db.update("matter_versions", version_id, {"status": "RETIRED"})

    if matter.get("current_published_version_id") == version_id:
        db.update("matters", matter_id, {"current_published_version_id": None})
    other_published = [
        v for v in db.find_many("matter_versions", matter_id=matter_id)
        if v["id"] != version_id and v["status"] == "PUBLISHED"
    ]
    if not other_published:
        # No surviving PUBLISHED version -> Matter ARCHIVED.
        # (Per PRD §3.1: only when retiring a PUBLISHED version that was the current pointer.)
        m = db.find_by_id("matters", matter_id)
        if m and m["status"] == "PUBLISHED":
            db.update("matters", matter_id, {"status": "ARCHIVED"})

    return db.find_by_id("matter_versions", version_id)


# =============================================================================
# MaterialTemplate
# =============================================================================

def create_material_template(body: dict) -> dict:
    body = V.must_be_dict(body)
    code = V.require_str(body, "code", min_len=TEMPLATE_CODE_MIN_LEN,
                         max_len=TEMPLATE_CODE_MAX_LEN)
    title = V.require_str(body, "title")
    material_type = V.require_str(body, "material_type")
    if material_type not in MATERIAL_TYPES:
        raise AppError(ERR_VALIDATION_FAILED,
                       f"material_type must be one of {sorted(MATERIAL_TYPES)}",
                       422)
    form_url = V.opt_str(body, "form_url", default=None)
    example_url = V.opt_str(body, "example_url", default=None)
    e_form_schema = body.get("e_form_schema")
    if e_form_schema is not None and not isinstance(e_form_schema, dict):
        raise AppError(ERR_VALIDATION_FAILED,
                       "e_form_schema must be an object or null", 422)

    if db.find_one("material_templates", code=code):
        raise AppError(ERR_DUPLICATE_RESOURCE,
                       f"MaterialTemplate code already exists: {code}", 409)

    return db.insert("material_templates", {
        "code": code,
        "title": title,
        "material_type": material_type,
        "form_url": form_url,
        "example_url": example_url,
        "e_form_schema": e_form_schema,
        "status": "DRAFT",
    })


def publish_material_template(template_id: str, body: dict) -> dict:
    t = db.find_by_id("material_templates", template_id)
    if not t:
        raise AppError(ERR_NOT_FOUND,
                       f"MaterialTemplate not found: {template_id}", 404)
    if t["status"] != "DRAFT":
        raise AppError(ERR_INVALID_STATE,
                       f"MaterialTemplate must be DRAFT to publish (current: {t['status']})",
                       409)
    from services import occ
    occ.check(t, body)
    return db.update("material_templates", template_id, {"status": "PUBLISHED"})


def list_material_templates(filters: dict, limit: int, offset: int):
    use = {k: v for k, v in filters.items() if v is not None}
    return db.query("material_templates", filters=use, limit=limit, offset=offset)


# =============================================================================
# CertificateTemplate
# =============================================================================

def create_certificate_template(body: dict) -> dict:
    body = V.must_be_dict(body)
    code = V.require_str(body, "code", min_len=TEMPLATE_CODE_MIN_LEN,
                         max_len=TEMPLATE_CODE_MAX_LEN)
    body_template = V.require_str(body, "body_template")
    required_variables = V.require_list(body, "required_variables")
    for v in required_variables:
        if not isinstance(v, str):
            raise AppError(ERR_VALIDATION_FAILED,
                           "required_variables entries must be strings", 422)
        if f"{{{{{v}}}}}" not in body_template:
            raise AppError(ERR_VALIDATION_FAILED,
                           f"required_variables entry '{v}' missing from body_template",
                           422)
    validity_days = V.opt_int(body, "validity_days", default=0, min_value=0)
    official_seal_id = V.require_str(body, "official_seal_id")

    if db.find_one("certificate_templates", code=code):
        raise AppError(ERR_DUPLICATE_RESOURCE,
                       f"CertificateTemplate code already exists: {code}", 409)

    return db.insert("certificate_templates", {
        "code": code,
        "body_template": body_template,
        "required_variables": list(required_variables),
        "validity_days": validity_days,
        "official_seal_id": official_seal_id,
        "status": "DRAFT",
    })


def publish_certificate_template(template_id: str, body: dict) -> dict:
    t = db.find_by_id("certificate_templates", template_id)
    if not t:
        raise AppError(ERR_NOT_FOUND,
                       f"CertificateTemplate not found: {template_id}", 404)
    if t["status"] != "DRAFT":
        raise AppError(ERR_INVALID_STATE,
                       f"CertificateTemplate must be DRAFT to publish (current: {t['status']})",
                       409)
    from services import occ
    occ.check(t, body)
    return db.update("certificate_templates", template_id, {"status": "PUBLISHED"})


def list_certificate_templates(filters: dict, limit: int, offset: int):
    use = {k: v for k, v in filters.items() if v is not None}
    return db.query("certificate_templates", filters=use, limit=limit, offset=offset)
