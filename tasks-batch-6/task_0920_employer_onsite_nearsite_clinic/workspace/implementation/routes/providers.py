"""Providers and the credentialing cycle (PRD 3.2)."""

from core import constants, payload, serializers, store
from core.errors import ApiError
from core.ladder import ObjectResult, Spec, paginate

from .common import filter_rows


def _validate_create(ctx):
    payload.require_id(ctx.body, "site_id")
    payload.require_string(ctx.body, "full_name")
    payload.require_present(ctx.body, "provider_function")
    payload.require_date(ctx.body, "license_expiry_date")


def _create(ctx):
    body = ctx.body
    row = store.insert(
        "provider",
        {
            "site_id": body["site_id"],
            "full_name": body["full_name"],
            "provider_function": body["provider_function"],
            "license_expiry_date": body["license_expiry_date"],
            "credential_status": "CREDENTIALED",
            "renewal_count": 0,
        },
    )
    return ObjectResult(serializers.dump("provider", row), 201)


def _list(ctx):
    rows = filter_rows(
        store.all_rows("provider"),
        {
            "site_id": ctx.args.get("site_id"),
            "credential_status": ctx.args.get("credential_status"),
            "provider_function": ctx.args.get("provider_function"),
        },
    )
    return paginate(ctx, "provider", rows)


def _read(ctx):
    return ObjectResult(serializers.dump("provider", ctx.entity("provider_id")), 200)


def _validate_renewal(ctx):
    supplied = payload.require_date(ctx.body, "license_expiry_date")
    # PRD 3.2 / rung 7: "The replacement date must not fall strictly earlier
    # than the current clock date; one that does is refused with
    # ERR_VALIDATION."
    if supplied < store.now_date():
        raise ApiError(
            "ERR_VALIDATION", "license_expiry_date falls strictly before the clock date."
        )


def _state_renewal(ctx):
    provider = ctx.entity("provider_id")
    if provider["credential_status"] != "LAPSED":
        raise ApiError("ERR_INVALID_STATE")


def _renew(ctx):
    provider = ctx.entity("provider_id")
    provider["license_expiry_date"] = ctx.body["license_expiry_date"]
    provider["renewal_count"] = int(provider["renewal_count"]) + 1
    provider["credential_status"] = "CREDENTIALED"
    return ObjectResult(serializers.dump("provider", provider), 200)


def _state_deactivate(ctx):
    provider = ctx.entity("provider_id")
    if provider["credential_status"] not in ("CREDENTIALED", "LAPSED"):
        raise ApiError("ERR_INVALID_STATE")


def _deactivate(ctx):
    provider = ctx.entity("provider_id")
    provider["credential_status"] = "DEACTIVATED"
    return ObjectResult(serializers.dump("provider", provider), 200)


_READ_ROLES = [
    constants.ROLE_PROGRAM_ADMIN,
    constants.ROLE_CLINIC_MANAGER,
    constants.ROLE_CLINICIAN,
    constants.ROLE_CARE_NAVIGATOR,
    constants.ROLE_PARTICIPANT,
]

SPECS = [
    Spec(
        method="POST",
        path="/providers",
        roles=[constants.ROLE_CLINIC_MANAGER],
        handler=_create,
        status=201,
        body_fks=[("site_id", "site", True)],
        payload=_validate_create,
        enums=[("provider_function", "provider_function")],
        is_write=True,
    ),
    Spec(
        method="GET",
        path="/providers",
        roles=_READ_ROLES,
        handler=_list,
    ),
    Spec(
        method="GET",
        path="/providers/{provider_id}",
        roles=_READ_ROLES,
        handler=_read,
        path_ids=[("provider_id", "provider")],
    ),
    Spec(
        method="POST",
        path="/providers/{provider_id}/credential-renewal",
        roles=[constants.ROLE_CLINIC_MANAGER],
        handler=_renew,
        path_ids=[("provider_id", "provider")],
        payload=_validate_renewal,
        checks={10: _state_renewal},
        is_write=True,
    ),
    Spec(
        method="POST",
        path="/providers/{provider_id}/deactivate",
        roles=[constants.ROLE_CLINIC_MANAGER],
        handler=_deactivate,
        path_ids=[("provider_id", "provider")],
        checks={10: _state_deactivate},
        is_write=True,
    ),
]
