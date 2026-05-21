from flask import request
from .clock import iso
from .ids import new_uuid
from .errors import err


def now_iso():
    from .app import logical_clock
    return iso(logical_clock.now())


def base_versioned():
    now = now_iso()
    return {"id": new_uuid(), "created_at": now, "updated_at": now, "version": 1}


def base_internal():
    return {"id": new_uuid(), "created_at": now_iso()}


def touch(resource: dict) -> None:
    resource["updated_at"] = now_iso()
    resource["version"] = resource.get("version", 1) + 1


def check_version(resource: dict, body) -> None:
    if not isinstance(body, dict):
        return
    if "version" in body:
        v = body["version"]
        if not isinstance(v, int) or v != resource.get("version"):
            raise err("ERR_VERSION_CONFLICT", "version mismatch")


def body_or_empty():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object")
    return body
