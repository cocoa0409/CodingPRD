"""Epidemic config endpoints."""
from db import LOCK, get_db
from errors import APIError
from helpers import new_entity, require_body, require_enum, require_field, touch
from middleware import require_roles
from response import success


MODES = {"NORMAL", "RESTRICTED", "LOCKDOWN"}


def _get_or_create_config():
    db = get_db()
    if db.epidemic_config is None:
        cfg = new_entity({
            "mode": "NORMAL",
            "max_temperature_c": 37.3,
            "max_visitors_per_day": 2,
        })
        db.epidemic_config = cfg
    return db.epidemic_config


def register(app):

    @app.put("/epidemic-config")
    @require_roles("Admin")
    def put_config(user_id, role):
        body = require_body()
        mode = require_enum(body, "mode", MODES)
        max_temp = body.get("max_temperature_c")
        max_per_day = body.get("max_visitors_per_day")
        with LOCK:
            cfg = _get_or_create_config()
            cfg["mode"] = mode
            if max_temp is not None:
                if not isinstance(max_temp, (int, float)) or isinstance(max_temp, bool):
                    raise APIError("ERR_VALIDATION", "max_temperature_c must be a number", 422)
                cfg["max_temperature_c"] = float(max_temp)
            if max_per_day is not None:
                if not isinstance(max_per_day, int) or isinstance(max_per_day, bool):
                    raise APIError("ERR_VALIDATION", "max_visitors_per_day must be int", 422)
                if max_per_day < 0:
                    raise APIError("ERR_VALIDATION", "max_visitors_per_day must be >= 0", 422)
                cfg["max_visitors_per_day"] = max_per_day
            touch(cfg)
            return success(dict(cfg))

    @app.get("/epidemic-config")
    @require_roles("Admin", "Family", "Supervisor")
    def get_config(user_id, role):
        cfg = _get_or_create_config()
        return success(dict(cfg))
