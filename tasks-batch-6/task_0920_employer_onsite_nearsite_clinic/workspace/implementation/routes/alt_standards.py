"""The reasonable alternative standard and its depth-5 cascade (PRD 3.6)."""

from datetime import timedelta

from core import calc, constants, ladder, payload, recompute, serializers, store, timeutil
from core.errors import ApiError
from core.ladder import ObjectResult, Spec, paginate

from .common import filter_rows, scope_rule


def _standard(ctx):
    return ctx.entity("standard_id")


def _backing_assessment(ctx):
    return store.get("assessment", _standard(ctx)["health_assessment_id"])


def _participant_of(ctx):
    return store.get("participant", _standard(ctx)["participant_id"])


def _period_for_measurement(employer_id, measurement_date):
    """The reporting period whose CLOSED span contains the measurement date."""
    if measurement_date is None:
        return None
    candidates = []
    for period in store.all_rows("period"):
        if period["employer_id"] != employer_id:
            continue
        start = timeutil.parse_date(period["period_start"])
        end = timeutil.parse_date(period["period_end"])
        if start is None or end is None:
            continue
        if start <= measurement_date <= end:
            candidates.append(period)
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return candidates[0]


# ------------------------------------------------------------------ create --

def _validate_create(ctx):
    payload.require_id(ctx.body, "participant_id")
    payload.require_id(ctx.body, "health_assessment_id")
    payload.require_string(ctx.body, "requested_reason")


def _create(ctx):
    body = ctx.body
    row = store.insert(
        "alt_standard",
        {
            "participant_id": body["participant_id"],
            "health_assessment_id": body["health_assessment_id"],
            "requested_reason": body["requested_reason"],
            "alternative_type": None,
            "assigned_at": None,
            "due_date": None,
            "reassignment_count": 0,
            "status": "REQUESTED",
            "credit_granted": False,
        },
    )
    return ObjectResult(serializers.dump("alt_standard", row), 201)


def _list(ctx):
    rows = filter_rows(
        store.all_rows("alt_standard"),
        {
            "participant_id": ctx.args.get("participant_id"),
            "health_assessment_id": ctx.args.get("health_assessment_id"),
            "status": ctx.args.get("status"),
        },
    )
    return paginate(ctx, "alt_standard", rows)


def _read(ctx):
    return ObjectResult(serializers.dump("alt_standard", _standard(ctx)), 200)


# ------------------------------------------------------------------ assign --

def _validate_assign(ctx):
    value = payload.require_present(ctx.body, "alternative_type")
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", "Field 'alternative_type' must be a string.")


def _state_assign(ctx):
    standard = _standard(ctx)
    if standard["status"] == "REQUESTED":
        return
    if standard["status"] == "ASSIGNED":
        if int(standard["reassignment_count"]) < constants.MAX_RAS_REASSIGNMENTS:
            return
    raise ApiError("ERR_INVALID_STATE")


def _assign(ctx):
    standard = _standard(ctx)
    reassignment = standard["status"] == "ASSIGNED"
    standard["status"] = "ASSIGNED"
    standard["alternative_type"] = ctx.body["alternative_type"]
    standard["assigned_at"] = store.now_iso()
    standard["due_date"] = timeutil.fmt_date(
        store.now_date() + timedelta(days=constants.RAS_COMPLETION_WINDOW_DAYS)
    )
    if reassignment:
        standard["reassignment_count"] = int(standard["reassignment_count"]) + 1
    return ObjectResult(serializers.dump("alt_standard", standard), 200)


# -------------------------------------------------------------------- deny --

def _state_deny(ctx):
    if _standard(ctx)["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE")


def _deny(ctx):
    standard = _standard(ctx)
    standard["status"] = "DENIED"
    # The backing assessment keeps outcome_credit_status PENDING_ALTERNATIVE;
    # no credit, no award, no period or employer money moves.
    return ObjectResult(serializers.dump("alt_standard", standard), 200)


# ---------------------------------------------------------------- complete --

def _freeze_complete(ctx):
    assessment = _backing_assessment(ctx)
    participant = _participant_of(ctx)
    employer_id = participant["employer_id"] if participant else None
    measurement_date = (
        timeutil.parse_date(assessment["measurement_date"]) if assessment else None
    )
    ladder.freeze_if_covered(employer_id, measurement_date)


def _state_complete(ctx):
    standard = _standard(ctx)
    if standard["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE")
    due = timeutil.parse_date(standard.get("due_date"))
    # Completion ON the due date is accepted (closed bound).
    if due is not None and store.now_date() > due:
        raise ApiError("ERR_INVALID_STATE")


def _award_context(ctx):
    assessment = _backing_assessment(ctx)
    participant = _participant_of(ctx)
    if assessment is None or participant is None:
        return None, None, None
    employer = store.get("employer", participant["employer_id"])
    period = _period_for_measurement(
        participant["employer_id"], timeutil.parse_date(assessment["measurement_date"])
    )
    return participant, employer, period


def _cap_check(ctx):
    participant, employer, period = _award_context(ctx)
    if period is None or employer is None:
        return  # no period contains the measurement date, so no award is created
    committed = recompute.participant_committed_cents(participant["id"], period["id"])
    if committed + constants.OUTCOME_AWARD_CENTS > calc.incentive_cap_cents(employer):
        raise ApiError("ERR_INCENTIVE_CAP_EXCEEDED")


def _budget_check(ctx):
    _participant, employer, period = _award_context(ctx)
    if period is None or employer is None:
        return
    committed = int(employer["wellness_budget_committed_cents"])
    if committed + constants.OUTCOME_AWARD_CENTS > int(employer["wellness_budget_cents"]):
        raise ApiError("ERR_WELLNESS_BUDGET_EXCEEDED")


def _complete(ctx):
    standard = _standard(ctx)
    assessment = _backing_assessment(ctx)
    participant, employer, period = _award_context(ctx)

    # hop 1
    standard["status"] = "COMPLETED"
    standard["credit_granted"] = True
    # hop 2 -- outcome_standard_met keeps its original false value
    if assessment is not None:
        assessment["outcome_credit_status"] = "CREDITED_VIA_RAS"
    # hop 3 -- retroactive award in the ORIGINAL measurement period
    if period is not None and participant is not None:
        store.insert(
            "award",
            {
                "participant_id": participant["id"],
                "employer_id": participant["employer_id"],
                "reporting_period_id": period["id"],
                "health_assessment_id": assessment["id"] if assessment else None,
                "award_type": "OUTCOME_BASED",
                "award_amount_cents": constants.OUTCOME_AWARD_CENTS,
                "retroactive": True,
                "status": "PENDING",
                "approved_by_user_id": None,
                "exported_by_user_id": None,
                "payroll_reference": None,
            },
        )
        # hop 4
        recompute.recompute_period_buckets(period)
        # hop 5
        if employer is not None:
            recompute.recompute_employer_budget(employer)
        recompute.recompute_participant_derived(participant)
    return ObjectResult(serializers.dump("alt_standard", standard), 200)


_READ_ROLES = [
    constants.ROLE_PROGRAM_ADMIN,
    constants.ROLE_CLINICIAN,
    constants.ROLE_CARE_NAVIGATOR,
    constants.ROLE_PARTICIPANT,
    constants.ROLE_EMPLOYER_BENEFITS_ADMIN,
]

SPECS = [
    Spec(
        method="POST",
        path="/alternative-standards",
        roles=[constants.ROLE_PARTICIPANT],
        handler=_create,
        status=201,
        body_fks=[
            ("participant_id", "participant", True),
            ("health_assessment_id", "assessment", True),
        ],
        scope=scope_rule(participant_of=lambda ctx: ctx.body.get("participant_id")),
        payload=_validate_create,
        is_write=True,
    ),
    Spec(
        method="GET",
        path="/alternative-standards",
        roles=_READ_ROLES,
        handler=_list,
        walled=True,
    ),
    Spec(
        method="GET",
        path="/alternative-standards/{standard_id}",
        roles=_READ_ROLES,
        handler=_read,
        walled=True,
        path_ids=[("standard_id", "alt_standard")],
        scope=scope_rule(
            participant_of=lambda ctx: ctx.entity("standard_id")["participant_id"]
        ),
    ),
    Spec(
        method="POST",
        path="/alternative-standards/{standard_id}/assign",
        roles=[constants.ROLE_CARE_NAVIGATOR],
        handler=_assign,
        path_ids=[("standard_id", "alt_standard")],
        payload=_validate_assign,
        enums=[("alternative_type", "alternative_type")],
        checks={10: _state_assign},
        is_write=True,
    ),
    Spec(
        method="POST",
        path="/alternative-standards/{standard_id}/complete",
        roles=[constants.ROLE_CARE_NAVIGATOR],
        handler=_complete,
        path_ids=[("standard_id", "alt_standard")],
        freeze=_freeze_complete,
        checks={10: _state_complete, 24: _cap_check, 25: _budget_check},
        is_write=True,
    ),
    Spec(
        method="POST",
        path="/alternative-standards/{standard_id}/deny",
        roles=[constants.ROLE_CARE_NAVIGATOR],
        handler=_deny,
        path_ids=[("standard_id", "alt_standard")],
        checks={10: _state_deny},
        is_write=True,
    ),
]
