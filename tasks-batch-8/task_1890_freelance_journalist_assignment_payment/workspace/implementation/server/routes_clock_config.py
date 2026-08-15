"""Logical clock and DeskConfig endpoints."""

from .auth import ALL_ROLES, require
from .blueprint import bp
from .calc import DEFAULTS
from .envelope import ok_obj
from .errors import ApiError, bad_request
from .serialize import ser_config
from .store import STORE, new_entity, touch
from .util import body, fmt_dt, is_int, parse_dt

CONFIG_INT_FIELDS = (
    "kill_fee_post_delivery_pct_num",
    "receipt_required_cents",
    "net_terms_days",
    "late_fee_daily_bps",
    "reporting_threshold_cents",
    "backup_withholding_rate_bps",
    "foreign_statutory_rate_bps",
    "flag_threshold_bps",
    "ai_flag_threshold_bps",
    "reuse_royalty_pct_num",
    "all_rights_uplift_pct_num",
)

CONFIG_OBJECT_FIELDS = ("category_caps_cents", "treaty_rates_bps")


@bp.post("/freelance-desk/_clock/set_current_utc")
def set_current_utc():
    require(["DeskAdmin"])
    b = body()
    dt = parse_dt(b.get("to_iso8601"))
    if dt is None:
        bad_request("to_iso8601 must be a valid ISO8601 timestamp")
    STORE.clock = dt
    # Clock sweep: VERIFIED tax documents whose expiry is earlier than the new now -> EXPIRED
    for doc in list(STORE.tax_documents.values()):
        if doc["status"] == "VERIFIED" and doc["expires_at"] < dt:
            doc["status"] = "EXPIRED"
            touch(doc)
    return ok_obj({"now_utc": fmt_dt(dt)})


@bp.post("/freelance-desk/desk-config")
def create_desk_config():
    require(["DeskAdmin"])
    if STORE.desk_config is not None:
        raise ApiError("ERR_INVALID_STATE", 409, "DeskConfig has already been initialized")
    b = body()
    e = new_entity()
    for k, default in DEFAULTS.items():
        e[k] = dict(default) if isinstance(default, dict) else default
    for k in CONFIG_INT_FIELDS:
        if k in b and b[k] is not None:
            if not is_int(b[k]):
                bad_request(f"{k} must be an integer")
            e[k] = b[k]
    for k in CONFIG_OBJECT_FIELDS:
        if k in b and b[k] is not None:
            v = b[k]
            if not isinstance(v, dict):
                bad_request(f"{k} must be an object")
            for kk, vv in v.items():
                if not isinstance(kk, str) or not is_int(vv):
                    bad_request(f"{k} must map strings to integers")
            e[k] = dict(v)
    if not (1 <= e["kill_fee_post_delivery_pct_num"] <= 100):
        bad_request("kill_fee_post_delivery_pct_num must be between 1 and 100")
    STORE.desk_config = e
    return ok_obj(ser_config(e), 201)


@bp.get("/freelance-desk/desk-config")
def get_desk_config():
    require(ALL_ROLES)
    if STORE.desk_config is None:
        raise ApiError("ERR_NOT_FOUND", 404, "DeskConfig has not been initialized")
    return ok_obj(ser_config(STORE.desk_config))
