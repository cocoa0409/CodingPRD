"""Incentive awards: amounts, the regulatory cap and payroll settlement (3.8)."""

from core import calc, constants, payload, recompute, serializers, store
from core.errors import ApiError
from core.ladder import ObjectResult, Spec, paginate

from .common import filter_rows, scope_rule


def _award(ctx):
    return ctx.entity("award_id")


def _refresh_money(award):
    period = store.get("period", award["reporting_period_id"])
    if period is not None:
        recompute.recompute_period_buckets(period)
    employer = store.get("employer", award["employer_id"])
    if employer is not None:
        recompute.recompute_employer_budget(employer)
    participant = store.get("participant", award["participant_id"])
    if participant is not None:
        recompute.recompute_participant_derived(participant)


# ------------------------------------------------------------------ create --

def _freeze_create(ctx):
    """Rung 6 -- governed by the reporting period the request names directly."""
    period = ctx.entity("reporting_period_id")
    if period is not None and period["status"] in ("FINALIZED", "CLOSED"):
        raise ApiError("ERR_PERIOD_FINALIZED")


def _validate_create(ctx):
    payload.require_id(ctx.body, "participant_id")
    payload.require_id(ctx.body, "reporting_period_id")
    award_type = payload.require_present(ctx.body, "award_type")
    if not isinstance(award_type, str):
        raise ApiError("ERR_VALIDATION", "Field 'award_type' must be a string.")
    payload.require_int(ctx.body, "expected_participant_version")
    payload.optional_id(ctx.body, "health_assessment_id")
    if award_type == "OUTCOME_BASED":
        payload.require_present(ctx.body, "health_assessment_id")
    else:
        payload.require_absent(
            ctx.body, "health_assessment_id", "for a participation-based award"
        )


def _state_create(ctx):
    if ctx.body["award_type"] != "OUTCOME_BASED":
        return
    assessment = ctx.entity("health_assessment_id")
    # A direct creation is accepted only when the named assessment reads
    # MET_DIRECT; PENDING_ALTERNATIVE has earned nothing and CREDITED_VIA_RAS
    # already had its award created by the cascade.
    if assessment is None or assessment["outcome_credit_status"] != "MET_DIRECT":
        raise ApiError("ERR_INVALID_STATE")
    for existing in store.all_rows("award"):
        if existing["award_type"] != "OUTCOME_BASED":
            continue
        if existing["participant_id"] != ctx.body["participant_id"]:
            continue
        if existing["reporting_period_id"] != ctx.body["reporting_period_id"]:
            continue
        raise ApiError("ERR_INVALID_STATE")


def _cap_check(ctx):
    participant = ctx.entity("participant_id")
    employer = store.get("employer", participant["employer_id"])
    amount = calc.incentive_award_amount(ctx.body["award_type"])
    committed = recompute.participant_committed_cents(
        participant["id"], ctx.body["reporting_period_id"]
    )
    if employer is None:
        return
    if committed + amount > calc.incentive_cap_cents(employer):
        raise ApiError("ERR_INCENTIVE_CAP_EXCEEDED")


def _budget_check(ctx):
    participant = ctx.entity("participant_id")
    employer = store.get("employer", participant["employer_id"])
    if employer is None:
        return
    amount = calc.incentive_award_amount(ctx.body["award_type"])
    if int(employer["wellness_budget_committed_cents"]) + amount > int(
        employer["wellness_budget_cents"]
    ):
        raise ApiError("ERR_WELLNESS_BUDGET_EXCEEDED")


def _create(ctx):
    participant = ctx.entity("participant_id")
    body = ctx.body
    row = store.insert(
        "award",
        {
            "participant_id": participant["id"],
            "employer_id": participant["employer_id"],
            "reporting_period_id": body["reporting_period_id"],
            "health_assessment_id": body.get("health_assessment_id"),
            "award_type": body["award_type"],
            "award_amount_cents": calc.incentive_award_amount(body["award_type"]),
            "retroactive": False,
            "status": "PENDING",
            "approved_by_user_id": None,
            "exported_by_user_id": None,
            "payroll_reference": None,
        },
    )
    _refresh_money(row)
    return ObjectResult(serializers.dump("award", row), 201)


# -------------------------------------------------------------------- reads --

def _list(ctx):
    rows = filter_rows(
        store.all_rows("award"),
        {
            "participant_id": ctx.args.get("participant_id"),
            "employer_id": ctx.args.get("employer_id"),
            "reporting_period_id": ctx.args.get("reporting_period_id"),
            "health_assessment_id": ctx.args.get("health_assessment_id"),
            "status": ctx.args.get("status"),
        },
    )
    return paginate(ctx, "award", rows)


def _read(ctx):
    return ObjectResult(serializers.dump("award", _award(ctx)), 200)


# ---------------------------------------------------------------- approve ---

def _state_approve(ctx):
    award = _award(ctx)
    if award["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE")
    period = store.get("period", award["reporting_period_id"])
    if period is None or period["status"] not in ("OPEN", "RESTATING"):
        raise ApiError("ERR_INVALID_STATE")


def _approve(ctx):
    award = _award(ctx)
    award["status"] = "APPROVED"
    award["approved_by_user_id"] = ctx.user_id
    _refresh_money(award)
    return ObjectResult(serializers.dump("award", award), 200)


# ----------------------------------------------------------------- export ---

def _validate_export(ctx):
    payload.require_string(ctx.body, "payroll_reference")


def _state_export(ctx):
    if _award(ctx)["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE")


def _export(ctx):
    award = _award(ctx)
    award["status"] = "EXPORTED"
    award["payroll_reference"] = ctx.body["payroll_reference"]
    award["exported_by_user_id"] = ctx.user_id
    _refresh_money(award)
    return ObjectResult(serializers.dump("award", award), 200)


# -------------------------------------------------------------- mark paid ---

def _state_mark_paid(ctx):
    if _award(ctx)["status"] != "EXPORTED":
        raise ApiError("ERR_INVALID_STATE")


def _mark_paid(ctx):
    award = _award(ctx)
    award["status"] = "PAID"
    _refresh_money(award)
    return ObjectResult(serializers.dump("award", award), 200)


# ---------------------------------------------------------------- reverse ---

def _state_reverse(ctx):
    if _award(ctx)["status"] not in ("APPROVED", "PAID"):
        raise ApiError("ERR_INVALID_STATE")


def _reverse(ctx):
    award = _award(ctx)
    award["status"] = "REVERSED"
    _refresh_money(award)
    return ObjectResult(serializers.dump("award", award), 200)


_READ_ROLES = [
    constants.ROLE_PROGRAM_ADMIN,
    constants.ROLE_EMPLOYER_BENEFITS_ADMIN,
    constants.ROLE_PAYROLL_PROCESSOR,
    constants.ROLE_PARTICIPANT,
]

_award_scope = scope_rule(
    participant_of=lambda ctx: ctx.entity("award_id")["participant_id"],
    employer_of=lambda ctx: ctx.entity("award_id")["employer_id"],
)

SPECS = [
    Spec(
        method="POST",
        path="/incentive-awards",
        roles=[constants.ROLE_EMPLOYER_BENEFITS_ADMIN],
        handler=_create,
        status=201,
        body_fks=[
            ("participant_id", "participant", True),
            ("reporting_period_id", "period", True),
            ("health_assessment_id", "assessment", False),
        ],
        scope=scope_rule(
            employer_of=lambda ctx: ctx.entity("participant_id")["employer_id"]
        ),
        freeze=_freeze_create,
        payload=_validate_create,
        enums=[("award_type", "award_type")],
        occ=("expected_participant_version", lambda ctx: ctx.entity("participant_id")),
        checks={10: _state_create, 24: _cap_check, 25: _budget_check},
        is_write=True,
    ),
    Spec(
        method="GET",
        path="/incentive-awards",
        roles=_READ_ROLES,
        handler=_list,
    ),
    Spec(
        method="GET",
        path="/incentive-awards/{award_id}",
        roles=_READ_ROLES,
        handler=_read,
        path_ids=[("award_id", "award")],
        scope=_award_scope,
    ),
    Spec(
        method="POST",
        path="/incentive-awards/{award_id}/approve",
        roles=[constants.ROLE_EMPLOYER_BENEFITS_ADMIN],
        handler=_approve,
        path_ids=[("award_id", "award")],
        scope=_award_scope,
        checks={10: _state_approve},
        is_write=True,
    ),
    Spec(
        method="POST",
        path="/incentive-awards/{award_id}/export",
        roles=[constants.ROLE_PAYROLL_PROCESSOR],
        handler=_export,
        path_ids=[("award_id", "award")],
        payload=_validate_export,
        checks={10: _state_export},
        is_write=True,
    ),
    Spec(
        method="POST",
        path="/incentive-awards/{award_id}/mark-paid",
        roles=[constants.ROLE_PAYROLL_PROCESSOR],
        handler=_mark_paid,
        path_ids=[("award_id", "award")],
        checks={10: _state_mark_paid},
        is_write=True,
    ),
    Spec(
        method="POST",
        path="/incentive-awards/{award_id}/reverse",
        roles=[constants.ROLE_EMPLOYER_BENEFITS_ADMIN],
        handler=_reverse,
        path_ids=[("award_id", "award")],
        scope=_award_scope,
        checks={10: _state_reverse},
        is_write=True,
    ),
]
