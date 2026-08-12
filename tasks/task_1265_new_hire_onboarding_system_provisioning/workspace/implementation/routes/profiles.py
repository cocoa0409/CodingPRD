"""RoleProfile endpoints (PRD §3.1)."""

from flask import Blueprint

from auth import require_roles, ALL_ROLES
from errors import ERR_ROLE_PROFILE_NOT_FOUND
from helpers import new_record, touch, get_or_404, ser_profile
from util import (success, get_body, req_present, as_str, as_int, as_bool,
                  as_list, as_enum, bad)

bp = Blueprint("profiles", __name__)

TASK_KINDS = ("DOCUMENT_UPLOAD", "FORM_ACK", "POLICY_READ")


def _val_tasks(v):
    out = []
    for i, e in enumerate(as_list(v, "preboarding_tasks")):
        if not isinstance(e, dict):
            bad(f"preboarding_tasks[{i}] must be an object")
        out.append({
            "task_kind": as_enum(req_present(e, "task_kind"),
                                 "task_kind", TASK_KINDS),
            "title": as_str(req_present(e, "title"), "title"),
            "is_required": as_bool(req_present(e, "is_required"),
                                   "is_required"),
        })
    return out


def _val_modules(v):
    out = []
    for i, e in enumerate(as_list(v, "training_modules")):
        if not isinstance(e, dict):
            bad(f"training_modules[{i}] must be an object")
        out.append({
            "module_code": as_str(req_present(e, "module_code"),
                                  "module_code"),
            "due_offset_days": as_int(req_present(e, "due_offset_days"),
                                      "due_offset_days"),
        })
    return out


def _val_equipment(v):
    out = []
    for i, e in enumerate(as_list(v, "equipment_items")):
        if not isinstance(e, dict):
            bad(f"equipment_items[{i}] must be an object")
        qty = as_int(req_present(e, "quantity"), "quantity")
        if qty < 1:
            bad("equipment_items quantity must be >= 1")
        out.append({
            "item_name": as_str(req_present(e, "item_name"), "item_name"),
            "quantity": qty,
        })
    return out


def _val_access(v):
    out = []
    for i, e in enumerate(as_list(v, "access_grants")):
        if not isinstance(e, dict):
            bad(f"access_grants[{i}] must be an object")
        out.append({
            "system_name": as_str(req_present(e, "system_name"),
                                  "system_name"),
            "permission_level": as_str(req_present(e, "permission_level"),
                                       "permission_level"),
        })
    return out


def _val_offsets(v):
    return [as_int(x, "manager_checkin_offsets_days")
            for x in as_list(v, "manager_checkin_offsets_days")]


_TEMPLATE_FIELDS = {
    "name": lambda v: as_str(v, "name"),
    "preboarding_tasks": _val_tasks,
    "training_modules": _val_modules,
    "equipment_items": _val_equipment,
    "access_grants": _val_access,
    "probation_days": lambda v: as_int(v, "probation_days"),
    "max_probation_extensions": lambda v: as_int(v, "max_probation_extensions"),
    "extension_days": lambda v: as_int(v, "extension_days"),
    "buddy_checkin_interval_days": lambda v: as_int(
        v, "buddy_checkin_interval_days"),
    "buddy_checkin_count": lambda v: as_int(v, "buddy_checkin_count"),
    "manager_checkin_offsets_days": _val_offsets,
    "provisioning_sla_hours": lambda v: as_int(v, "provisioning_sla_hours"),
}


@bp.post("/api/role-profiles")
def create_profile():
    require_roles("HRAdmin")
    body = get_body()
    fields = {}
    for name, validator in _TEMPLATE_FIELDS.items():
        fields[name] = validator(req_present(body, name))
    rec = new_record("role_profiles", {
        **fields,
        "status": "DRAFT",
        "published_version": 0,
    })
    return success(ser_profile(rec), 201)


@bp.get("/api/role-profiles/<pid>")
def get_profile(pid):
    require_roles(*ALL_ROLES)
    rec = get_or_404("role_profiles", pid, ERR_ROLE_PROFILE_NOT_FOUND,
                     "RoleProfile")
    return success(ser_profile(rec))


@bp.put("/api/role-profiles/<pid>")
def edit_profile(pid):
    require_roles("HRAdmin")
    rec = get_or_404("role_profiles", pid, ERR_ROLE_PROFILE_NOT_FOUND,
                     "RoleProfile")
    body = get_body()
    for name, validator in _TEMPLATE_FIELDS.items():
        if name in body and body[name] is not None:
            rec[name] = validator(body[name])
    touch(rec)
    return success(ser_profile(rec))


@bp.post("/api/role-profiles/<pid>/publish")
def publish_profile(pid):
    require_roles("HRAdmin")
    rec = get_or_404("role_profiles", pid, ERR_ROLE_PROFILE_NOT_FOUND,
                     "RoleProfile")
    rec["status"] = "PUBLISHED"
    rec["published_version"] = rec["published_version"] + 1
    touch(rec)
    return success(ser_profile(rec))
