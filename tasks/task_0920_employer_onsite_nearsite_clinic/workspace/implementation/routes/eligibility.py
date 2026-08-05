"""The eligibility file (PRD 3.3).  Coverage spans are CLOSED at both ends."""

from datetime import timedelta

from core import calc, constants, payload, serializers, store, timeutil
from core.errors import ApiError
from core.ladder import ObjectResult, Spec, paginate

from .common import filter_rows, scope_rule


def _validate_create(ctx):
    payload.require_id(ctx.body, "employer_id")
    payload.require_string(ctx.body, "subscriber_external_id")
    payload.require_string(ctx.body, "member_external_id")
    payload.require_present(ctx.body, "tier")
    payload.require_date(ctx.body, "effective_date")
    payload.optional_date(ctx.body, "termination_date")


def _uniqueness(ctx):
    """Rung 23 -- closed-interval overlap on employer_id + member_external_id."""
    new_start = timeutil.parse_date(ctx.body["effective_date"])
    new_end = timeutil.parse_date(ctx.body.get("termination_date")) if ctx.body.get(
        "termination_date"
    ) else None
    for row in store.all_rows("eligibility"):
        if row["employer_id"] != ctx.body["employer_id"]:
            continue
        if row["member_external_id"] != ctx.body["member_external_id"]:
            continue
        other_start = timeutil.parse_date(row["effective_date"])
        other_end = (
            timeutil.parse_date(row["termination_date"]) if row.get("termination_date") else None
        )
        if calc.spans_overlap(new_start, new_end, other_start, other_end):
            raise ApiError("ERR_DUPLICATE_ELIGIBILITY")


def _create(ctx):
    body = ctx.body
    row = store.insert(
        "eligibility",
        {
            "employer_id": body["employer_id"],
            "subscriber_external_id": body["subscriber_external_id"],
            "member_external_id": body["member_external_id"],
            "tier": body["tier"],
            "effective_date": body["effective_date"],
            "termination_date": body.get("termination_date"),
            "retro_terminated": False,
        },
    )
    return ObjectResult(serializers.dump("eligibility", row), 201)


def _list(ctx):
    rows = filter_rows(
        store.all_rows("eligibility"),
        {
            "employer_id": ctx.args.get("employer_id"),
            "member_external_id": ctx.args.get("member_external_id"),
        },
    )
    wanted = ctx.args.get("coverage_status")
    if wanted:
        clock_date = store.now_date()
        rows = [r for r in rows if calc.coverage_status_of(r, clock_date) == wanted]
    return paginate(ctx, "eligibility", rows)


def _read(ctx):
    return ObjectResult(serializers.dump("eligibility", ctx.entity("record_id")), 200)


def _validate_terminate(ctx):
    supplied = payload.require_date(ctx.body, "termination_date")
    # PRD 3.3 / rung 7: retroactivity is bounded at thirty days; a date exactly
    # thirty days before the clock date is accepted, the grace bound being
    # closed.
    floor = store.now_date() - timedelta(days=constants.RETRO_TERMINATION_GRACE_DAYS)
    if supplied < floor:
        raise ApiError(
            "ERR_VALIDATION",
            "termination_date falls outside the 30-day retroactive grace window.",
        )


def _terminate(ctx):
    row = ctx.entity("record_id")
    supplied = timeutil.parse_date(ctx.body["termination_date"])
    row["termination_date"] = ctx.body["termination_date"]
    row["retro_terminated"] = supplied < store.now_date()
    return ObjectResult(serializers.dump("eligibility", row), 200)


_READ_ROLES = [
    constants.ROLE_PROGRAM_ADMIN,
    constants.ROLE_EMPLOYER_BENEFITS_ADMIN,
    constants.ROLE_CLINIC_MANAGER,
]

SPECS = [
    Spec(
        method="POST",
        path="/eligibility-records",
        roles=[constants.ROLE_EMPLOYER_BENEFITS_ADMIN],
        handler=_create,
        status=201,
        body_fks=[("employer_id", "employer", True)],
        scope=scope_rule(employer_of=lambda ctx: ctx.body.get("employer_id")),
        payload=_validate_create,
        enums=[("tier", "tier")],
        checks={23: _uniqueness},
        is_write=True,
    ),
    Spec(
        method="GET",
        path="/eligibility-records",
        roles=_READ_ROLES,
        handler=_list,
    ),
    Spec(
        method="GET",
        path="/eligibility-records/{record_id}",
        roles=_READ_ROLES,
        handler=_read,
        path_ids=[("record_id", "eligibility")],
        scope=scope_rule(employer_of=lambda ctx: ctx.entity("record_id")["employer_id"]),
    ),
    Spec(
        method="POST",
        path="/eligibility-records/{record_id}/terminate",
        roles=[constants.ROLE_EMPLOYER_BENEFITS_ADMIN],
        handler=_terminate,
        path_ids=[("record_id", "eligibility")],
        scope=scope_rule(employer_of=lambda ctx: ctx.entity("record_id")["employer_id"]),
        payload=_validate_terminate,
        is_write=True,
    ),
]
