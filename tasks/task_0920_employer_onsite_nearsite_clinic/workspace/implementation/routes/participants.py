"""Enrollment and the parallel authorization axis (PRD 3.3).

The two axes advance independently.  `enrollment_status` and
`authorization_status` are separate stored fields and neither is derived from
the other; the single place one reaches the other is the TERMINATED -> CLOSED
sweep, which is in routes/ops.py.
"""

from datetime import timedelta

from core import calc, constants, payload, recompute, serializers, store, timeutil
from core.errors import ApiError
from core.ladder import ObjectResult, Spec, paginate

from .common import filter_rows, scope_rule


# ------------------------------------------------------------------ create --

def _validate_create(ctx):
    payload.require_id(ctx.body, "employer_id")
    payload.require_id(ctx.body, "eligibility_record_id")
    payload.require_string(ctx.body, "display_name")


def _eligible_on_clock_date(ctx):
    record = ctx.entity("eligibility_record_id")
    if record is None or not calc.coverage_covers(record, store.now_date()):
        raise ApiError("ERR_NOT_ELIGIBLE_ON_DATE")


def _create(ctx):
    body = ctx.body
    record = ctx.entity("eligibility_record_id")
    row = store.insert(
        "participant",
        {
            "employer_id": body["employer_id"],
            "eligibility_record_id": body["eligibility_record_id"],
            "display_name": body["display_name"],
            "tier": record["tier"],
            "enrolled_on": timeutil.fmt_date(store.now_date()),
            "enrollment_status": "ACTIVE",
            "authorization_status": "NOT_REQUESTED",
            "termination_effective_date": None,
            "authorization_revoked_at": None,
            "completed_visit_count": 0,
            "incentive_awarded_cents": 0,
        },
    )
    return ObjectResult(serializers.dump("participant", row), 201)


# -------------------------------------------------------------------- reads --

def _list(ctx):
    rows = filter_rows(
        store.all_rows("participant"),
        {
            "employer_id": ctx.args.get("employer_id"),
            "eligibility_record_id": ctx.args.get("eligibility_record_id"),
            "enrollment_status": ctx.args.get("enrollment_status"),
        },
    )
    return paginate(ctx, "participant", rows)


def _read(ctx):
    return ObjectResult(serializers.dump("participant", ctx.entity("participant_id")), 200)


# --------------------------------------------------------------- terminate --

def _validate_terminate(ctx):
    supplied = payload.require_date(ctx.body, "termination_effective_date")
    floor = store.now_date() - timedelta(days=constants.RETRO_TERMINATION_GRACE_DAYS)
    if supplied < floor:
        raise ApiError(
            "ERR_VALIDATION",
            "termination_effective_date falls outside the 30-day retroactive grace window.",
        )


def _state_terminate(ctx):
    if ctx.entity("participant_id")["enrollment_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")


def _terminate(ctx):
    participant = ctx.entity("participant_id")
    participant["enrollment_status"] = "TERMINATED"
    participant["termination_effective_date"] = ctx.body["termination_effective_date"]

    # --- scheduling branch (cascade hops 2, 3, 4) --------------------------
    touched_sites = set()
    touched_contracts = set()
    for appt in store.sorted_rows("appointment"):
        if appt["participant_id"] != participant["id"]:
            continue
        if appt["status"] != "BOOKED":
            continue
        appt["status"] = "CANCELLED"
        appt["cancellation_reason"] = "ENROLLMENT_TERMINATED"
        touched_sites.add(appt["site_id"])
        if appt.get("quota_contract_id"):
            touched_contracts.add(appt["quota_contract_id"])
    for site_id in touched_sites:
        site = store.get("site", site_id)
        if site is not None:
            recompute.recompute_site_counters(site)
    for contract_id in touched_contracts:
        contract = store.get("contract", contract_id)
        if contract is not None:
            recompute.recompute_contract_quota(contract)

    # --- money branch (cascade hops 2b, 3b, 4b) ---------------------------
    # Only PENDING awards forfeit; APPROVED, EXPORTED and PAID are explicitly
    # left exactly as they were found (PRD 3.3).
    touched_periods = set()
    for award in store.sorted_rows("award"):
        if award["participant_id"] != participant["id"]:
            continue
        if award["status"] != "PENDING":
            continue
        award["status"] = "FORFEITED"
        touched_periods.add(award["reporting_period_id"])
    for period_id in touched_periods:
        period = store.get("period", period_id)
        if period is not None:
            recompute.recompute_period_buckets(period)
    employer = store.get("employer", participant["employer_id"])
    if employer is not None:
        recompute.recompute_employer_budget(employer)
    recompute.recompute_participant_derived(participant)

    return ObjectResult(serializers.dump("participant", participant), 200)


# --------------------------------------------------------------- reinstate --

def _state_reinstate(ctx):
    participant = ctx.entity("participant_id")
    if participant["enrollment_status"] != "TERMINATED":
        raise ApiError("ERR_INVALID_STATE")
    effective = timeutil.parse_date(participant.get("termination_effective_date"))
    if effective is None:
        raise ApiError("ERR_INVALID_STATE")
    limit = effective + timedelta(days=constants.RETRO_TERMINATION_GRACE_DAYS)
    if store.now_date() > limit:
        raise ApiError("ERR_INVALID_STATE")


def _eligible_reinstate(ctx):
    participant = ctx.entity("participant_id")
    record = store.get("eligibility", participant["eligibility_record_id"])
    if record is None or calc.coverage_status_of(record, store.now_date()) != "EFFECTIVE":
        raise ApiError("ERR_NOT_ELIGIBLE_ON_DATE")


def _reinstate(ctx):
    participant = ctx.entity("participant_id")
    participant["enrollment_status"] = "ACTIVE"
    participant["termination_effective_date"] = None
    return ObjectResult(serializers.dump("participant", participant), 200)


# ----------------------------------------------------------- authorization --

def _validate_authorization(ctx):
    payload.require_present(ctx.body, "decision")
    if not isinstance(ctx.body.get("decision"), str):
        raise ApiError("ERR_VALIDATION", "Field 'decision' must be a string.")


def _state_authorization(ctx):
    participant = ctx.entity("participant_id")
    decision = ctx.body["decision"]
    axis = participant["authorization_status"]
    if decision == "GRANT":
        if axis not in ("NOT_REQUESTED", "REVOKED"):
            raise ApiError("ERR_INVALID_STATE")
        if participant["enrollment_status"] == "CLOSED":
            raise ApiError("ERR_INVALID_STATE")
    else:  # REVOKE
        if axis != "GRANTED":
            raise ApiError("ERR_INVALID_STATE")


def _authorization(ctx):
    participant = ctx.entity("participant_id")
    decision = ctx.body["decision"]
    if decision == "GRANT":
        participant["authorization_status"] = "GRANTED"
        participant["authorization_revoked_at"] = None
    else:
        participant["authorization_status"] = "REVOKED"
        participant["authorization_revoked_at"] = store.now_iso()
        # Revocation is PROSPECTIVE ONLY.  WALLED and RELEASE_PENDING visits
        # are suppressed; visits already FITNESS_RELEASED or
        # PARTICIPATION_RELEASED are deliberately left untouched.
        for visit in store.sorted_rows("visit"):
            if visit["participant_id"] != participant["id"]:
                continue
            if visit["disclosure_status"] in ("WALLED", "RELEASE_PENDING"):
                visit["disclosure_status"] = "SUPPRESSED"
    return ObjectResult(serializers.dump("participant", participant), 200)


_READ_ROLES = [
    constants.ROLE_PROGRAM_ADMIN,
    constants.ROLE_EMPLOYER_BENEFITS_ADMIN,
    constants.ROLE_CLINIC_MANAGER,
    constants.ROLE_CLINICIAN,
    constants.ROLE_CARE_NAVIGATOR,
    constants.ROLE_PARTICIPANT,
]

_owner_scope = scope_rule(
    participant_of=lambda ctx: ctx.path_params.get("participant_id"),
    employer_of=lambda ctx: ctx.entity("participant_id")["employer_id"],
)

SPECS = [
    Spec(
        method="POST",
        path="/participants",
        roles=[constants.ROLE_EMPLOYER_BENEFITS_ADMIN],
        handler=_create,
        status=201,
        body_fks=[
            ("employer_id", "employer", True),
            ("eligibility_record_id", "eligibility", True),
        ],
        scope=scope_rule(employer_of=lambda ctx: ctx.body.get("employer_id")),
        payload=_validate_create,
        checks={12: _eligible_on_clock_date},
        is_write=True,
    ),
    Spec(
        method="GET",
        path="/participants",
        roles=_READ_ROLES,
        handler=_list,
    ),
    Spec(
        method="GET",
        path="/participants/{participant_id}",
        roles=_READ_ROLES,
        handler=_read,
        path_ids=[("participant_id", "participant")],
        scope=_owner_scope,
    ),
    Spec(
        method="POST",
        path="/participants/{participant_id}/terminate",
        roles=[constants.ROLE_EMPLOYER_BENEFITS_ADMIN],
        handler=_terminate,
        path_ids=[("participant_id", "participant")],
        scope=_owner_scope,
        payload=_validate_terminate,
        checks={10: _state_terminate},
        is_write=True,
    ),
    Spec(
        method="POST",
        path="/participants/{participant_id}/reinstate",
        roles=[constants.ROLE_EMPLOYER_BENEFITS_ADMIN],
        handler=_reinstate,
        path_ids=[("participant_id", "participant")],
        scope=_owner_scope,
        checks={10: _state_reinstate, 12: _eligible_reinstate},
        is_write=True,
    ),
    Spec(
        method="POST",
        path="/participants/{participant_id}/authorization",
        roles=[constants.ROLE_PARTICIPANT],
        handler=_authorization,
        path_ids=[("participant_id", "participant")],
        scope=_owner_scope,
        payload=_validate_authorization,
        enums=[("decision", "decision")],
        checks={10: _state_authorization},
        is_write=True,
    ),
]
