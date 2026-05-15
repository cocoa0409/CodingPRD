"""ContraindicationRule routes."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..errors import ApiError
from ..pagination import parse_limit_offset
from ..response import paginate
from ..services.validation import require_keys, require_str
from ..store import LOCK, common_fields_create, get_store
from ._helpers import created, get_json_body, list_ok


_ALLOWED_SEVERITY = {"ABSOLUTE", "RELATIVE"}
_ALLOWED_OPS = {"EQ", "IN", "GT", "LT"}


def register(app: Flask) -> None:
    @app.route("/aesthetics/projects/<pid>/contraindication-rules", methods=["POST"])
    @require_auth("MedicalDirector")
    def create_rule(pid: str):
        with LOCK:
            proj = get_store().projects.get(pid)
            if not proj:
                raise ApiError("ERR_NOT_FOUND", "Project not found")
            body = get_json_body()
            require_keys(body, ["severity", "predicate", "reason"])
            sev = body["severity"]
            if sev not in _ALLOWED_SEVERITY:
                raise ApiError("ERR_INVALID_INPUT", "severity must be ABSOLUTE or RELATIVE")
            pred = body["predicate"]
            if not isinstance(pred, dict):
                raise ApiError("ERR_INVALID_INPUT", "predicate must be an object")
            for k in ("field", "op", "value"):
                if k not in pred:
                    raise ApiError("ERR_INVALID_INPUT", f"predicate.{k} required")
            if pred["op"] not in _ALLOWED_OPS:
                raise ApiError("ERR_INVALID_INPUT", f"predicate.op must be one of {_ALLOWED_OPS}")
            if not isinstance(pred["field"], str):
                raise ApiError("ERR_INVALID_INPUT", "predicate.field must be a string")
            reason = require_str(body["reason"], "reason", allow_empty=True)

            rule = common_fields_create()
            rule.update({
                "project_id": pid,
                "severity": sev,
                "predicate": pred,
                "reason": reason,
            })
            get_store().contraindication_rules[rule["id"]] = rule
        return created(rule)

    @app.route("/aesthetics/projects/<pid>/contraindication-rules", methods=["GET"])
    @require_auth("MedicalDirector", "Consultant", "AttendingPhysician", "SeniorPhysician")
    def list_rules(pid: str):
        proj = get_store().projects.get(pid)
        if not proj:
            raise ApiError("ERR_NOT_FOUND", "Project not found")
        limit, offset = parse_limit_offset()
        items = [r for r in get_store().contraindication_rules.values() if r["project_id"] == pid]
        items.sort(key=lambda x: x["created_at"])
        sliced, page = paginate(items, limit, offset)
        return list_ok(sliced, page)
