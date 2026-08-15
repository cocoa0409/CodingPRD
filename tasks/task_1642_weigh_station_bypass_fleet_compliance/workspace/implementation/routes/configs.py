"""State program config routes (PRD 3.3)."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import body_json, ctx, need_str, opt_bool, opt_int, require_role
from response import ok

bp = Blueprint("configs", __name__)

CREDENTIAL_SETS = ("IFTA", "IRP", "UCR", "HOS_LOG")
PARTICIPATION = ("PILOT", "PARTICIPATING", "SUSPENDED")

# Legal participation transitions; return to PILOT is forbidden and same-state
# no-ops are rejected (rung 5).
_LEGAL_PARTICIPATION = {
    ("PILOT", "PARTICIPATING"),
    ("PILOT", "SUSPENDED"),
    ("PARTICIPATING", "SUSPENDED"),
    ("SUSPENDED", "PARTICIPATING"),
}


def _validate_rule_fields(body):
    """Rung 12 for config rule fields; returns the normalized updates dict."""
    updates = {}
    if "iss_refusal_threshold" in body:
        v = opt_int(body, "iss_refusal_threshold")
        if v is None or not (50 <= v <= 100):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "iss_refusal_threshold must be in 50..100"
            )
        updates["iss_refusal_threshold"] = v
    if "random_pull_in_rate_bps" in body:
        v = opt_int(body, "random_pull_in_rate_bps")
        if v is None or not (0 <= v <= 10000):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "random_pull_in_rate_bps must be in 0..10000"
            )
        updates["random_pull_in_rate_bps"] = v
    if "bypass_rate_cap_bps" in body:
        v = opt_int(body, "bypass_rate_cap_bps")
        if v is None or not (1 <= v <= 10000):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "bypass_rate_cap_bps must be in 1..10000"
            )
        updates["bypass_rate_cap_bps"] = v
    if "hazmat_bypass_allowed" in body:
        updates["hazmat_bypass_allowed"] = opt_bool(body, "hazmat_bypass_allowed", None)
        if updates["hazmat_bypass_allowed"] is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, "hazmat_bypass_allowed must be a boolean")
    if "requires_weight_clearance" in body:
        updates["requires_weight_clearance"] = opt_bool(body, "requires_weight_clearance", None)
        if updates["requires_weight_clearance"] is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "requires_weight_clearance must be a boolean"
            )
    if "credential_sets_required" in body:
        v = body.get("credential_sets_required")
        if (
            not isinstance(v, list)
            or any(not isinstance(x, str) or x not in CREDENTIAL_SETS for x in v)
        ):
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "credential_sets_required must be a list drawn from IFTA, IRP, UCR, HOS_LOG",
            )
        updates["credential_sets_required"] = list(v)
    return updates


@bp.post("/api/state-program-configs")
def create_config():
    _uid, role = ctx()
    require_role(role, ("StateProgramManager",))
    body = body_json()
    state_code = need_str(body, "state_code")
    updates = _validate_rule_fields(body)
    for c in store.configs.values():
        if c["state_code"] == state_code:
            raise ApiError(
                "ERR_DUPLICATE_STATE_CONFIG", 409, "state_code already has a config"
            )
    rec = {
        "id": db.new_id(),
        "_seq": store.next_seq(),
        "state_code": state_code,
        "participation_status": "PILOT",
        "iss_refusal_threshold": updates.get("iss_refusal_threshold", 75),
        "random_pull_in_rate_bps": updates.get("random_pull_in_rate_bps", 0),
        "bypass_rate_cap_bps": updates.get("bypass_rate_cap_bps", 10000),
        "hazmat_bypass_allowed": updates.get("hazmat_bypass_allowed", False),
        "requires_weight_clearance": updates.get("requires_weight_clearance", True),
        "credential_sets_required": updates.get(
            "credential_sets_required", ["IFTA", "IRP", "UCR"]
        ),
        "version": 1,
    }
    db.stamp(rec)
    store.configs[rec["id"]] = rec
    return ok(db.public(rec), 201)


@bp.get("/api/state-program-configs/<configId>")
def get_config(configId):
    ctx()
    config = store.configs.get(configId)
    if config is None:
        raise ApiError(
            "ERR_STATE_PROGRAM_CONFIG_NOT_FOUND", 404, "state config id does not exist"
        )
    return ok(db.public(config), 200)


@bp.patch("/api/state-program-configs/<configId>")
def patch_config(configId):
    _uid, role = ctx()
    require_role(role, ("StateProgramManager",))
    config = store.configs.get(configId)
    if config is None:
        raise ApiError(
            "ERR_STATE_PROGRAM_CONFIG_NOT_FOUND", 404, "state config id does not exist"
        )
    body = body_json()
    # Rung 5: participation transition legality (valid enum members only)
    ps = body.get("participation_status")
    if isinstance(ps, str) and ps in PARTICIPATION:
        if (config["participation_status"], ps) not in _LEGAL_PARTICIPATION:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                409,
                f"participation_status cannot move from {config['participation_status']} to {ps}",
            )
    # Rung 6: OCC token (non-optional per PRD 2.9)
    expected = body.get("expected_state_program_config_version")
    if (
        expected is None
        or isinstance(expected, bool)
        or not isinstance(expected, int)
        or expected != config["version"]
    ):
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_state_program_config_version does not match the config's current version",
        )
    # Rung 12: validate provided fields (incl. participation enum validity)
    if ps is not None and ps not in PARTICIPATION:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "participation_status must be one of PARTICIPATING, PILOT, SUSPENDED",
        )
    updates = _validate_rule_fields(body)
    for k, v in updates.items():
        config[k] = v
    if ps is not None:
        config["participation_status"] = ps
    db.bump(config)
    return ok(db.public(config), 200)
