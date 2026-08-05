"""Clinic sites: calendar, closure overrides and slot capacity (PRD 3.1)."""

from core import constants, payload, serializers, store
from core.ladder import ObjectResult, Spec, paginate

from .common import filter_rows


def _validate_create(ctx):
    payload.require_string(ctx.body, "site_name")
    payload.require_present(ctx.body, "site_type")
    payload.require_hhmm(ctx.body, "open_time_utc")
    payload.require_hhmm(ctx.body, "close_time_utc")
    payload.require_weekday_array(ctx.body, "operating_weekdays")
    payload.require_int(ctx.body, "daily_slot_capacity", minimum=1)
    payload.optional_id(ctx.body, "host_employer_id")
    payload.optional_date_array(ctx.body, "closure_dates", default=[])


def _create(ctx):
    body = ctx.body
    row = store.insert(
        "site",
        {
            "host_employer_id": body.get("host_employer_id"),
            "site_name": body["site_name"],
            "site_type": body["site_type"],
            "open_time_utc": body["open_time_utc"],
            "close_time_utc": body["close_time_utc"],
            "operating_weekdays": list(body["operating_weekdays"]),
            "closure_dates": list(body.get("closure_dates") or []),
            "daily_slot_capacity": int(body["daily_slot_capacity"]),
            "slots_held_count": 0,
            "slots_consumed_count": 0,
            "slots_no_show_count": 0,
            "slots_released_count": 0,
            "slots_requested_total": 0,
        },
    )
    return ObjectResult(serializers.dump("site", row), 201)


def _list(ctx):
    rows = filter_rows(
        store.all_rows("site"),
        {
            "host_employer_id": ctx.args.get("host_employer_id"),
            "site_type": ctx.args.get("site_type"),
        },
    )
    return paginate(ctx, "site", rows)


def _read(ctx):
    return ObjectResult(serializers.dump("site", ctx.entity("site_id")), 200)


def _validate_patch(ctx):
    payload.optional_hhmm(ctx.body, "open_time_utc")
    payload.optional_hhmm(ctx.body, "close_time_utc")
    payload.optional_weekday_array(ctx.body, "operating_weekdays")
    payload.optional_date_array(ctx.body, "closure_dates")
    payload.optional_int(ctx.body, "daily_slot_capacity", minimum=1)


def _patch(ctx):
    site = ctx.entity("site_id")
    body = ctx.body
    for field in ("open_time_utc", "close_time_utc"):
        if payload.present(body, field):
            site[field] = body[field]
    if payload.present(body, "operating_weekdays"):
        site["operating_weekdays"] = list(body["operating_weekdays"])
    if payload.present(body, "closure_dates"):
        site["closure_dates"] = list(body["closure_dates"])
    if payload.present(body, "daily_slot_capacity"):
        site["daily_slot_capacity"] = int(body["daily_slot_capacity"])
    # PRD 3.1: "Any such revision increments the site's `version` by one."
    store.force_version_bump("site", site)
    return ObjectResult(serializers.dump("site", site), 200)


_READ_ROLES = [
    constants.ROLE_PROGRAM_ADMIN,
    constants.ROLE_CLINIC_MANAGER,
    constants.ROLE_CLINICIAN,
    constants.ROLE_CARE_NAVIGATOR,
    constants.ROLE_PARTICIPANT,
    constants.ROLE_EMPLOYER_BENEFITS_ADMIN,
]

SPECS = [
    Spec(
        method="POST",
        path="/sites",
        roles=[constants.ROLE_PROGRAM_ADMIN],
        handler=_create,
        status=201,
        body_fks=[("host_employer_id", "employer", False)],
        payload=_validate_create,
        enums=[("site_type", "site_type")],
        is_write=True,
    ),
    Spec(
        method="GET",
        path="/sites",
        roles=_READ_ROLES,
        handler=_list,
    ),
    Spec(
        method="GET",
        path="/sites/{site_id}",
        roles=_READ_ROLES,
        handler=_read,
        path_ids=[("site_id", "site")],
    ),
    Spec(
        method="PATCH",
        path="/sites/{site_id}",
        roles=[constants.ROLE_PROGRAM_ADMIN, constants.ROLE_CLINIC_MANAGER],
        handler=_patch,
        path_ids=[("site_id", "site")],
        payload=_validate_patch,
        is_write=True,
    ),
]
