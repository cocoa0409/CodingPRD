"""Employer registration and read (PRD 3.1)."""

from core import constants, payload, serializers, store
from core.errors import ApiError
from core.ladder import ObjectResult, Spec

from .common import scope_rule


def _validate_create(ctx):
    payload.require_string(ctx.body, "legal_name")
    code = payload.require_string(ctx.body, "employer_code", min_len=2, max_len=16)
    payload.require_int(ctx.body, "annual_total_cost_of_coverage_cents", minimum=0)
    payload.require_int(ctx.body, "wellness_budget_cents", minimum=0)
    payload.optional_bool(ctx.body, "tobacco_program_enabled", default=False)
    # "A second employer registered with an `employer_code` already in use is
    # refused with ERR_VALIDATION." (PRD 3.1)
    for row in store.all_rows("employer"):
        if row["employer_code"] == code:
            raise ApiError("ERR_VALIDATION", "employer_code is already in use.")


def _create(ctx):
    body = ctx.body
    budget = int(body["wellness_budget_cents"])
    row = store.insert(
        "employer",
        {
            "legal_name": body["legal_name"],
            "employer_code": body["employer_code"],
            "annual_total_cost_of_coverage_cents": int(
                body["annual_total_cost_of_coverage_cents"]
            ),
            "tobacco_program_enabled": bool(body.get("tobacco_program_enabled") or False),
            "wellness_budget_cents": budget,
            "wellness_budget_committed_cents": 0,
            "wellness_budget_remaining_cents": budget,
            "program_cost_to_date_cents": 0,
            "status": "ACTIVE",
        },
    )
    return ObjectResult(serializers.dump("employer", row), 201)


def _read(ctx):
    return ObjectResult(serializers.dump("employer", ctx.entity("employer_id")), 200)


SPECS = [
    Spec(
        method="POST",
        path="/employers",
        roles=[constants.ROLE_PROGRAM_ADMIN],
        handler=_create,
        status=201,
        payload=_validate_create,
        is_write=True,
    ),
    Spec(
        method="GET",
        path="/employers/{employer_id}",
        roles=[
            constants.ROLE_PROGRAM_ADMIN,
            constants.ROLE_EMPLOYER_BENEFITS_ADMIN,
            constants.ROLE_CLINIC_MANAGER,
        ],
        handler=_read,
        path_ids=[("employer_id", "employer")],
        scope=scope_rule(employer_of=lambda ctx: ctx.path_params.get("employer_id")),
    ),
]
