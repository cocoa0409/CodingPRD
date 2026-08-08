"""Vendor contracts: fee model, minimum guarantee and employer quota (3.1)."""

from core import constants, payload, serializers, store
from core.ladder import ObjectResult, Spec, paginate

from .common import filter_rows, scope_rule


def _validate_create(ctx):
    payload.require_id(ctx.body, "site_id")
    payload.require_id(ctx.body, "employer_id")
    payload.require_string(ctx.body, "vendor_name")
    payload.require_present(ctx.body, "fee_model")
    payload.require_int(ctx.body, "per_visit_fee_cents", minimum=0)
    payload.require_int(ctx.body, "fte_hourly_rate_cents", minimum=0)
    payload.require_int(ctx.body, "minimum_guarantee_cents", minimum=0)
    payload.require_int(ctx.body, "quota_visits_total", minimum=0)


def _create(ctx):
    body = ctx.body
    quota = int(body["quota_visits_total"])
    row = store.insert(
        "contract",
        {
            "site_id": body["site_id"],
            "employer_id": body["employer_id"],
            "vendor_name": body["vendor_name"],
            "fee_model": body["fee_model"],
            "per_visit_fee_cents": int(body["per_visit_fee_cents"]),
            "fte_hourly_rate_cents": int(body["fte_hourly_rate_cents"]),
            "minimum_guarantee_cents": int(body["minimum_guarantee_cents"]),
            "quota_visits_total": quota,
            "quota_visits_consumed": 0,
            "quota_visits_released": 0,
            "quota_visits_requested_total": 0,
            "quota_visits_remaining": quota,
            "billable_visit_count": 0,
            "staffed_hours": 0.0,
            "gross_fee_cents": 0,
            "true_up_amount_cents": 0,
            "contract_cost_cents": 0,
            "status": "ACTIVE",
        },
    )
    return ObjectResult(serializers.dump("contract", row), 201)


def _list(ctx):
    rows = filter_rows(
        store.all_rows("contract"),
        {
            "site_id": ctx.args.get("site_id"),
            "employer_id": ctx.args.get("employer_id"),
            "status": ctx.args.get("status"),
        },
    )
    return paginate(ctx, "contract", rows)


def _read(ctx):
    return ObjectResult(serializers.dump("contract", ctx.entity("contract_id")), 200)


_READ_ROLES = [
    constants.ROLE_PROGRAM_ADMIN,
    constants.ROLE_CLINIC_MANAGER,
    constants.ROLE_EMPLOYER_BENEFITS_ADMIN,
]

SPECS = [
    Spec(
        method="POST",
        path="/vendor-contracts",
        roles=[constants.ROLE_PROGRAM_ADMIN],
        handler=_create,
        status=201,
        body_fks=[("site_id", "site", True), ("employer_id", "employer", True)],
        payload=_validate_create,
        enums=[("fee_model", "fee_model")],
        is_write=True,
    ),
    Spec(
        method="GET",
        path="/vendor-contracts",
        roles=_READ_ROLES,
        handler=_list,
    ),
    Spec(
        method="GET",
        path="/vendor-contracts/{contract_id}",
        roles=_READ_ROLES,
        handler=_read,
        path_ids=[("contract_id", "contract")],
        scope=scope_rule(
            employer_of=lambda ctx: ctx.entity("contract_id")["employer_id"]
        ),
    ),
]
