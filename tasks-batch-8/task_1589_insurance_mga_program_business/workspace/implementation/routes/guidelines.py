"""Underwriting guidelines: OCC-guarded create with atomic supersede
(PRD sections 2.9, 3.2)."""
from flask import Blueprint, request

import serialize
from db import STORE, new_entity, touch
from errors import raise_err, ERR_STALE_VERSION
from middleware import require_roles, ALL_ROLES
from response import success_object
from routes.common import get_or_404, render_list, filter_query
from routes.programs import require_program_not_terminal
from validation import get_body, req_str, req_int, req_int_pos, opt_int_nonneg

bp = Blueprint("guidelines", __name__)


def active_guideline(program_id, state_code, class_code):
    for g in STORE.guidelines.values():
        if (
            g["program_id"] == program_id
            and g["state_code"] == state_code
            and g["class_code"] == class_code
            and g["status"] == "ACTIVE"
        ):
            return g
    return None


@bp.post("/mga/programs/<programId>/guidelines")
def create_guideline(programId):
    require_roles("MGAUnderwriter")
    program = get_or_404(STORE.programs, programId, "Program")
    body = get_body()
    state_code = req_str(body, "state_code")
    class_code = req_str(body, "class_code")
    max_policy_premium_cents = req_int_pos(body, "max_policy_premium_cents")
    max_policy_limit_cents = req_int_pos(body, "max_policy_limit_cents")
    min_policy_premium_cents = opt_int_nonneg(body, "min_policy_premium_cents", 0)
    expected_program_version = req_int(body, "expected_program_version")
    # Stage 6 (OCC) is evaluated before stage 7 (state legality / terminal).
    if expected_program_version != program["version"]:
        raise_err(
            ERR_STALE_VERSION,
            "expected_program_version %s does not match current program version %s."
            % (expected_program_version, program["version"]),
        )
    require_program_not_terminal(program)
    # Creating a guideline for an occupied (state_code, class_code) scope
    # supersedes the prior ACTIVE one, atomically with the create.
    for g in STORE.guidelines.values():
        if (
            g["program_id"] == program["id"]
            and g["state_code"] == state_code
            and g["class_code"] == class_code
            and g["status"] == "ACTIVE"
        ):
            g["status"] = "SUPERSEDED"
            touch(g)
    g = new_entity()
    g.update({
        "program_id": program["id"],
        "state_code": state_code,
        "class_code": class_code,
        "max_policy_premium_cents": max_policy_premium_cents,
        "max_policy_limit_cents": max_policy_limit_cents,
        "min_policy_premium_cents": min_policy_premium_cents,
        "status": "ACTIVE",
    })
    STORE.guidelines[g["id"]] = g
    touch(program)
    return success_object(serialize.guideline(g), status=201)


@bp.get("/mga/programs/<programId>/guidelines")
def list_program_guidelines(programId):
    require_roles(*ALL_ROLES)
    get_or_404(STORE.programs, programId, "Program")
    items = filter_query(
        [g for g in STORE.guidelines.values() if g["program_id"] == programId],
        status=request.args.get("status"),
    )
    return render_list(items, serialize.guideline)


@bp.get("/mga/guidelines/<guidelineId>")
def get_guideline(guidelineId):
    require_roles(*ALL_ROLES)
    g = get_or_404(STORE.guidelines, guidelineId, "UnderwritingGuideline")
    return success_object(serialize.guideline(g))


@bp.get("/mga/guidelines")
def list_guidelines():
    require_roles(*ALL_ROLES)
    items = filter_query(
        list(STORE.guidelines.values()),
        program_id=request.args.get("program_id"),
        status=request.args.get("status"),
    )
    return render_list(items, serialize.guideline)
