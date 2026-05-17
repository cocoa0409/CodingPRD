"""Arm endpoints — create/list under a Trial."""
from __future__ import annotations

from flask import Blueprint

from ..auth import ROLE_COORD, ROLE_IRB, ROLE_PI, require_roles
from ..clock import now
from ..errors import err_invalid_input, err_invalid_state
from ..helpers import (
    assert_integer,
    assert_string,
    new_uuid,
    paginate,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing
from ..services.lookups import arms_for_trial, get_trial
from ..services.serialize import serialize_arm
from ..store import store

bp = Blueprint("arms", __name__)

ARM_CODE_PATTERN = r"^[A-Z0-9]{1,8}$"


@bp.post("/trials/<trial_id>/arms")
@require_roles(ROLE_PI)
def create_arm(trial_id: str, **_caller):
    body = require_json_object()
    with store().lock:
        trial = get_trial(trial_id)
        if trial["status"] != "DRAFT":
            raise err_invalid_state("Arms may only be added while the Trial is in DRAFT")

        code = assert_string(
            body.get("code"),
            "code",
            required=True,
            min_len=1,
            max_len=8,
            pattern=ARM_CODE_PATTERN,
        )
        label = assert_string(body.get("label"), "label", required=True, min_len=1, max_len=200, trim=True)
        weight = assert_integer(body.get("weight"), "weight", required=True, minimum=1, maximum=10)

        # Per-trial code uniqueness.
        for existing in arms_for_trial(trial_id):
            if existing["code"] == code:
                raise err_invalid_input(f"Arm code '{code}' already exists in this trial")

        arm_id = new_uuid()
        ts = now()
        arm = {
            "id": arm_id,
            "trial_id": trial_id,
            "code": code,
            "label": label,
            "weight": weight,
            "assigned_count": 0,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        store().arms[arm_id] = arm
    return created(serialize_arm(arm))


@bp.get("/trials/<trial_id>/arms")
@require_roles(ROLE_PI, ROLE_IRB, ROLE_COORD)
def list_arms(trial_id: str, **_caller):
    limit, offset = parse_pagination()
    with store().lock:
        get_trial(trial_id)  # existence
        rows = arms_for_trial(trial_id)
        rows.sort(key=lambda a: a["created_at"])
        total = len(rows)
        page = paginate(rows, limit, offset)
        items = [serialize_arm(a) for a in page]
    return listing(items, total, limit, offset)
