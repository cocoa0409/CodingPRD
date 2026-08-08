"""Staffing shifts (PRD 3.2)."""

from core import calc, constants, payload, serializers, store, timeutil
from core.errors import ApiError
from core.ladder import ObjectResult, Spec, paginate

from .common import filter_rows


def _validate_create(ctx):
    payload.require_id(ctx.body, "site_id")
    payload.require_id(ctx.body, "provider_id")
    start = payload.require_instant(ctx.body, "shift_start")
    end = payload.require_instant(ctx.body, "shift_end")
    payload.require_present(ctx.body, "coverage_role")
    # PRD 3.2 / rung 7: "a shift that ends at or before it starts is refused
    # with ERR_VALIDATION."
    if end <= start:
        raise ApiError("ERR_VALIDATION", "shift_end must be strictly after shift_start.")


def _credentialed(ctx):
    provider = ctx.entity("provider_id")
    if provider is not None and provider["credential_status"] != "CREDENTIALED":
        raise ApiError("ERR_PROVIDER_CREDENTIAL_LAPSED")


def _create(ctx):
    body = ctx.body
    start = timeutil.parse_instant(body["shift_start"])
    end = timeutil.parse_instant(body["shift_end"])
    hours = calc.round_half_up((end - start).total_seconds() / 3600.0, 2)
    row = store.insert(
        "shift",
        {
            "site_id": body["site_id"],
            "provider_id": body["provider_id"],
            "shift_start": timeutil.fmt_instant(start),
            "shift_end": timeutil.fmt_instant(end),
            "staffed_hours": float(hours),
            "coverage_role": body["coverage_role"],
        },
    )
    return ObjectResult(serializers.dump("shift", row), 201)


def _list(ctx):
    rows = filter_rows(
        store.all_rows("shift"),
        {
            "site_id": ctx.args.get("site_id"),
            "provider_id": ctx.args.get("provider_id"),
        },
    )
    return paginate(ctx, "shift", rows)


def _read(ctx):
    return ObjectResult(serializers.dump("shift", ctx.entity("shift_id")), 200)


_READ_ROLES = [
    constants.ROLE_PROGRAM_ADMIN,
    constants.ROLE_CLINIC_MANAGER,
    constants.ROLE_CLINICIAN,
    constants.ROLE_CARE_NAVIGATOR,
]

SPECS = [
    Spec(
        method="POST",
        path="/staffing-shifts",
        roles=[constants.ROLE_CLINIC_MANAGER],
        handler=_create,
        status=201,
        body_fks=[("site_id", "site", True), ("provider_id", "provider", True)],
        payload=_validate_create,
        enums=[("coverage_role", "coverage_role")],
        checks={15: _credentialed},
        is_write=True,
    ),
    Spec(
        method="GET",
        path="/staffing-shifts",
        roles=_READ_ROLES,
        handler=_list,
    ),
    Spec(
        method="GET",
        path="/staffing-shifts/{shift_id}",
        roles=_READ_ROLES,
        handler=_read,
        path_ids=[("shift_id", "shift")],
    ),
]
