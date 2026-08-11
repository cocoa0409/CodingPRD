"""Policies, the scheduling ledger and the coverage gap (PRD 3.5)."""

import calc
import derive
import serializers
import store
from constants import COVERAGE_GAP_BASES
from errors import ApiError
from registry import endpoint
from routes.common import field, list_response, one


def _policy(ctx):
    return ctx.row("policy_id")


def _policy_household(ctx):
    return _policy(ctx)["household_id"]


@endpoint(
    "POST",
    "/vault/policies",
    roles=["Homeowner", "InsuranceAgent"],
    code=201,
    mutating=True,
    body={
        "household_id": ("string", True),
        "carrier_name": ("string", True),
        "policy_number": ("string", True),
        "deductible_cents": ("integer", True),
        "scheduled_allowance_cents": ("integer", True),
        "effective_from": ("datetime", True),
    },
    fks=("household_id",),
    household=lambda ctx: ctx.body.get("household_id"),
)
def create_policy(ctx):
    row = store.new_row(
        store.policies,
        household_id=ctx.body["household_id"],
        carrier_name=ctx.body["carrier_name"],
        policy_number=ctx.body["policy_number"],
        deductible_cents=ctx.body["deductible_cents"],
        scheduled_allowance_cents=ctx.body["scheduled_allowance_cents"],
        scheduled_consumed_cents=0,
        scheduled_remaining_cents=ctx.body["scheduled_allowance_cents"],
        coverage_gap_cents=0,
        total_effective_value_cents=0,
    )
    derive.keep_raw(row, "effective_from", ctx.body["effective_from"])
    return one(serializers.policy(row), 201)


@endpoint(
    "GET",
    "/vault/policies/{policy_id}",
    roles=["Homeowner", "InsuranceAgent", "ClaimsAdjuster", "PlatformAdmin"],
    scope_household=_policy_household,
)
def read_policy(ctx):
    return one(serializers.policy(_policy(ctx)))


@endpoint(
    "GET",
    "/vault/policies",
    roles=["Homeowner", "InsuranceAgent", "ClaimsAdjuster", "PlatformAdmin"],
)
def list_policies(ctx):
    return list_response(
        store.all_of(store.policies),
        ctx.args,
        serializers.policy,
        {"household_id": field("household_id")},
    )


def _patch_rung37(ctx):
    allowance = ctx.body.get("scheduled_allowance_cents")
    if allowance is None:
        return
    if allowance < _policy(ctx)["scheduled_consumed_cents"]:
        raise ApiError("ERR_ALLOWANCE_BELOW_CONSUMED")


@endpoint(
    "PATCH",
    "/vault/policies/{policy_id}",
    roles=["InsuranceAgent"],
    mutating=True,
    body={
        "carrier_name": ("string", False),
        "deductible_cents": ("integer", False),
        "scheduled_allowance_cents": ("integer", False),
    },
    household=_policy_household,
    rungs={37: _patch_rung37},
)
def patch_policy(ctx):
    policy = _policy(ctx)
    for name in ("carrier_name", "deductible_cents", "scheduled_allowance_cents"):
        if name in ctx.body and ctx.body[name] is not None:
            policy[name] = ctx.body[name]
    derive.recompute_policy(policy, bump=False)
    store.touch(policy)
    return one(serializers.policy(policy))


@endpoint(
    "GET",
    "/vault/policies/{policy_id}/coverage-gap",
    roles=["Homeowner", "InsuranceAgent", "ClaimsAdjuster", "PlatformAdmin"],
    query_enums={"basis": COVERAGE_GAP_BASES},
    scope_household=_policy_household,
)
def coverage_gap(ctx):
    basis = ctx.args.get("basis") or "SCHEDULED_FIRST"
    return one(calc.coverage_gap_report(_policy(ctx), basis))
