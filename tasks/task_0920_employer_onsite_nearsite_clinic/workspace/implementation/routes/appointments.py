"""Appointment booking, reschedule, cancellation and check-in (PRD 3.4).

Every boundary convention is read at its own site: the operating window and
staffing containment are CLOSED, provider occupation is HALF-OPEN with zero
buffer, and site day capacity is a strict-less-than test taken before the
write.  No single `overlaps()` helper is reused across them.
"""

from core import calc, constants, ladder, payload, recompute, serializers, store, timeutil
from core.errors import ApiError
from core.ladder import ObjectResult, Spec, paginate

from .common import filter_rows, scope_rule


# ------------------------------------------------------- geometry gathering --

def _booking_geometry(ctx):
    site = ctx.entity("site_id")
    provider = ctx.entity("provider_id")
    participant = ctx.entity("participant_id")
    start = timeutil.parse_instant(ctx.body.get("scheduled_start"))
    return site, provider, participant, start, None


def _reschedule_geometry(ctx):
    appt = ctx.entity("appointment_id")
    site = store.get("site", appt["site_id"])
    provider = store.get("provider", appt["provider_id"])
    participant = store.get("participant", appt["participant_id"])
    start = timeutil.parse_instant(ctx.body.get("scheduled_start"))
    return site, provider, participant, start, appt["id"]


def _make_scheduling_checks(geometry):
    """Build the rung 12 and rung 15-21 callables shared by booking and
    rescheduling.  Each rung is a separate callable so the engine runs them in
    ascending rung order."""

    def rung12(ctx):
        _site, _provider, participant, start, _exclude = geometry(ctx)
        if participant is None or participant["enrollment_status"] != "ACTIVE":
            raise ApiError("ERR_NOT_ELIGIBLE_ON_DATE")
        record = store.get("eligibility", participant["eligibility_record_id"])
        if record is None or not calc.coverage_covers(record, start.date()):
            raise ApiError("ERR_NOT_ELIGIBLE_ON_DATE")

    def rung15(ctx):
        _site, provider, _participant, _start, _exclude = geometry(ctx)
        if provider is None or provider["credential_status"] != "CREDENTIALED":
            raise ApiError("ERR_PROVIDER_CREDENTIAL_LAPSED")

    def rung16(ctx):
        site, _provider, _participant, start, _exclude = geometry(ctx)
        service_date = timeutil.fmt_date(start.date())
        if service_date in (site.get("closure_dates") or []):
            raise ApiError("ERR_SITE_CLOSED")

    def rung17(ctx):
        site, _provider, _participant, start, _exclude = geometry(ctx)
        end = calc.slot_end(start)
        if not calc.inside_operating_window(site, start, end):
            raise ApiError("ERR_OUTSIDE_OPERATING_HOURS")

    def rung18(ctx):
        site, provider, _participant, start, _exclude = geometry(ctx)
        end = calc.slot_end(start)
        for shift in store.all_rows("shift"):
            if shift["site_id"] != site["id"] or shift["provider_id"] != provider["id"]:
                continue
            shift_start = timeutil.parse_instant(shift["shift_start"])
            shift_end = timeutil.parse_instant(shift["shift_end"])
            if calc.shift_closed_contains(shift_start, shift_end, start, end):
                return
        raise ApiError("ERR_STAFFING_COVERAGE_REQUIRED")

    def rung19(ctx):
        _site, provider, _participant, start, exclude = geometry(ctx)
        end = calc.slot_end(start)
        for appt in store.all_rows("appointment"):
            if appt["id"] == exclude:
                continue
            if appt["provider_id"] != provider["id"]:
                continue
            if appt["status"] not in constants.OCCUPYING_APPOINTMENT_STATUSES:
                continue
            other_start = timeutil.parse_instant(appt["scheduled_start"])
            other_end = timeutil.parse_instant(appt["scheduled_end"])
            if calc.half_open_overlap(start, end, other_start, other_end):
                raise ApiError("ERR_PROVIDER_SLOT_CONFLICT")

    def rung20(ctx):
        site, _provider, _participant, start, exclude = geometry(ctx)
        service_date = timeutil.fmt_date(start.date())
        count = 0
        for appt in store.all_rows("appointment"):
            if appt["id"] == exclude:
                continue
            if appt["site_id"] != site["id"]:
                continue
            if appt["service_date"] != service_date:
                continue
            if appt["status"] in constants.OCCUPYING_APPOINTMENT_STATUSES:
                count += 1
        if not count < int(site["daily_slot_capacity"]):
            raise ApiError("ERR_SLOT_CAPACITY_EXHAUSTED")

    def rung21(ctx):
        site, _provider, participant, _start, _exclude = geometry(ctx)
        contract = calc.select_quota_contract(
            store.all_rows("contract"), site["id"], participant["employer_id"]
        )
        if contract is None:
            raise ApiError("ERR_EMPLOYER_QUOTA_EXHAUSTED")
        ctx.scratch["contract"] = contract

    return {
        12: rung12,
        15: rung15,
        16: rung16,
        17: rung17,
        18: rung18,
        19: rung19,
        20: rung20,
        21: rung21,
    }


# ------------------------------------------------------------------ booking --

def _validate_book(ctx):
    payload.require_id(ctx.body, "participant_id")
    payload.require_id(ctx.body, "site_id")
    payload.require_id(ctx.body, "provider_id")
    payload.require_present(ctx.body, "visit_type")
    payload.require_instant(ctx.body, "scheduled_start")
    payload.require_int(ctx.body, "expected_site_version")


def _book(ctx):
    site = ctx.entity("site_id")
    contract = ctx.scratch["contract"]
    start = timeutil.parse_instant(ctx.body["scheduled_start"])
    end = calc.slot_end(start)
    row = store.insert(
        "appointment",
        {
            "participant_id": ctx.body["participant_id"],
            "site_id": ctx.body["site_id"],
            "provider_id": ctx.body["provider_id"],
            "quota_contract_id": contract["id"],
            "visit_type": ctx.body["visit_type"],
            "scheduled_start": timeutil.fmt_instant(start),
            "scheduled_end": timeutil.fmt_instant(end),
            "service_date": timeutil.fmt_date(start.date()),
            "status": "BOOKED",
            "reschedule_count": 0,
            "cancellation_reason": None,
        },
    )
    recompute.recompute_site_counters(site)
    recompute.recompute_contract_quota(contract)
    return ObjectResult(serializers.dump("appointment", row), 201)


# --------------------------------------------------------------- reschedule --

def _validate_reschedule(ctx):
    payload.require_instant(ctx.body, "scheduled_start")


def _state_reschedule(ctx):
    if ctx.entity("appointment_id")["status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE")


def _reschedule_cap(ctx):
    appt = ctx.entity("appointment_id")
    if not int(appt["reschedule_count"]) < constants.MAX_RESCHEDULES_PER_APPOINTMENT:
        raise ApiError("ERR_RESCHEDULE_LIMIT_REACHED")


def _reschedule(ctx):
    appt = ctx.entity("appointment_id")
    site = store.get("site", appt["site_id"])
    start = timeutil.parse_instant(ctx.body["scheduled_start"])
    end = calc.slot_end(start)
    previous_contract_id = appt.get("quota_contract_id")
    winner = ctx.scratch["contract"]

    appt["scheduled_start"] = timeutil.fmt_instant(start)
    appt["scheduled_end"] = timeutil.fmt_instant(end)
    appt["service_date"] = timeutil.fmt_date(start.date())
    appt["reschedule_count"] = int(appt["reschedule_count"]) + 1
    appt["quota_contract_id"] = winner["id"]

    # PRD 3.4: the site's version rises because day-level occupancy changed,
    # even though its slot counters do not move.
    recompute.recompute_site_counters(site)
    store.force_version_bump("site", site)

    if previous_contract_id != winner["id"]:
        previous = store.get("contract", previous_contract_id)
        if previous is not None:
            recompute.recompute_contract_quota(previous)
    recompute.recompute_contract_quota(winner)
    return ObjectResult(serializers.dump("appointment", appt), 200)


# ------------------------------------------------------------------- cancel --

def _role_extra_cancel(ctx):
    """Rung 2: only a Clinician may supply a NO_SHOW cancellation reason."""
    if ctx.body.get("cancellation_reason") == "NO_SHOW" and ctx.role != constants.ROLE_CLINICIAN:
        raise ApiError("ERR_FORBIDDEN_ROLE")


def _freeze_cancel(ctx):
    appt = ctx.entity("appointment_id")
    participant = store.get("participant", appt["participant_id"])
    employer_id = participant["employer_id"] if participant else None
    ladder.freeze_if_covered(employer_id, timeutil.parse_date(appt["service_date"]))


def _validate_cancel(ctx):
    payload.require_present(ctx.body, "cancellation_reason")
    reason = ctx.body.get("cancellation_reason")
    if not isinstance(reason, str):
        raise ApiError("ERR_VALIDATION", "Field 'cancellation_reason' must be a string.")
    # PRD 3.4: ENROLLMENT_TERMINATED is written only by the termination
    # cascade; a caller supplying it directly is refused with ERR_VALIDATION.
    if reason == "ENROLLMENT_TERMINATED":
        raise ApiError(
            "ERR_VALIDATION",
            "cancellation_reason ENROLLMENT_TERMINATED is written only by the termination cascade.",
        )


def _state_cancel(ctx):
    if ctx.entity("appointment_id")["status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE")


def _cancel(ctx):
    appt = ctx.entity("appointment_id")
    site = store.get("site", appt["site_id"])
    reason = ctx.body["cancellation_reason"]
    appt["cancellation_reason"] = reason
    if reason == "NO_SHOW":
        appt["status"] = "NO_SHOW"
    else:
        appt["status"] = "CANCELLED"
    if site is not None:
        recompute.recompute_site_counters(site)
    # A no-show keeps consuming the employer's quota, so the contract counters
    # are recomputed either way and simply do not move on the NO_SHOW path.
    contract = store.get("contract", appt.get("quota_contract_id"))
    if contract is not None:
        recompute.recompute_contract_quota(contract)
    return ObjectResult(serializers.dump("appointment", appt), 200)


# ----------------------------------------------------------------- check-in --

def _freeze_checkin(ctx):
    _freeze_cancel(ctx)


def _state_checkin(ctx):
    if ctx.entity("appointment_id")["status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE")


def _eligible_checkin(ctx):
    appt = ctx.entity("appointment_id")
    participant = store.get("participant", appt["participant_id"])
    if participant is None or participant["enrollment_status"] != "ACTIVE":
        raise ApiError("ERR_NOT_ELIGIBLE_ON_DATE")
    record = store.get("eligibility", participant["eligibility_record_id"])
    service_date = timeutil.parse_date(appt["service_date"])
    if record is None or not calc.coverage_covers(record, service_date):
        raise ApiError("ERR_NOT_ELIGIBLE_ON_DATE")


def _credentialed_checkin(ctx):
    appt = ctx.entity("appointment_id")
    provider = store.get("provider", appt["provider_id"])
    if provider is None or provider["credential_status"] != "CREDENTIALED":
        raise ApiError("ERR_PROVIDER_CREDENTIAL_LAPSED")


def _check_in(ctx):
    appt = ctx.entity("appointment_id")
    site = store.get("site", appt["site_id"])
    visit = store.insert(
        "visit",
        {
            "appointment_id": appt["id"],
            "participant_id": appt["participant_id"],
            "provider_id": appt["provider_id"],
            "site_id": appt["site_id"],
            "visit_type": appt["visit_type"],
            "service_date": appt["service_date"],
            "encounter_status": "CHECKED_IN",
            "disclosure_status": "WALLED",
            "fitness_conclusion": None,
            "chargeable_party": None,
            "consumes_benefit_entitlement": None,
            "amendment_count": 0,
            "clinical_note": None,
        },
    )
    appt["status"] = "CONSUMED"
    if site is not None:
        recompute.recompute_site_counters(site)
    return ObjectResult(serializers.dump("visit", visit), 201)


# -------------------------------------------------------------------- reads --

def _list(ctx):
    rows = filter_rows(
        store.all_rows("appointment"),
        {
            "participant_id": ctx.args.get("participant_id"),
            "site_id": ctx.args.get("site_id"),
            "provider_id": ctx.args.get("provider_id"),
            "quota_contract_id": ctx.args.get("quota_contract_id"),
            "status": ctx.args.get("status"),
            "service_date": ctx.args.get("service_date"),
        },
    )
    return paginate(ctx, "appointment", rows)


def _read(ctx):
    return ObjectResult(serializers.dump("appointment", ctx.entity("appointment_id")), 200)


_READ_ROLES = [
    constants.ROLE_PROGRAM_ADMIN,
    constants.ROLE_CLINIC_MANAGER,
    constants.ROLE_CLINICIAN,
    constants.ROLE_CARE_NAVIGATOR,
    constants.ROLE_PARTICIPANT,
]

_appt_owner_scope = scope_rule(
    participant_of=lambda ctx: ctx.entity("appointment_id")["participant_id"]
)

_book_checks = _make_scheduling_checks(_booking_geometry)
_resched_checks = _make_scheduling_checks(_reschedule_geometry)
_resched_checks[10] = _state_reschedule
_resched_checks[11] = _reschedule_cap

SPECS = [
    Spec(
        method="POST",
        path="/appointments",
        roles=[constants.ROLE_PARTICIPANT, constants.ROLE_CARE_NAVIGATOR],
        handler=_book,
        status=201,
        body_fks=[
            ("participant_id", "participant", True),
            ("site_id", "site", True),
            ("provider_id", "provider", True),
        ],
        scope=scope_rule(participant_of=lambda ctx: ctx.body.get("participant_id")),
        payload=_validate_book,
        enums=[("visit_type", "visit_type")],
        occ=("expected_site_version", lambda ctx: ctx.entity("site_id")),
        checks=_book_checks,
        is_write=True,
    ),
    Spec(
        method="GET",
        path="/appointments",
        roles=_READ_ROLES,
        handler=_list,
    ),
    Spec(
        method="GET",
        path="/appointments/{appointment_id}",
        roles=_READ_ROLES,
        handler=_read,
        path_ids=[("appointment_id", "appointment")],
        scope=_appt_owner_scope,
    ),
    Spec(
        method="POST",
        path="/appointments/{appointment_id}/reschedule",
        roles=[constants.ROLE_PARTICIPANT, constants.ROLE_CARE_NAVIGATOR],
        handler=_reschedule,
        path_ids=[("appointment_id", "appointment")],
        scope=_appt_owner_scope,
        payload=_validate_reschedule,
        checks=_resched_checks,
        is_write=True,
    ),
    Spec(
        method="POST",
        path="/appointments/{appointment_id}/cancel",
        roles=[
            constants.ROLE_PARTICIPANT,
            constants.ROLE_CARE_NAVIGATOR,
            constants.ROLE_CLINICIAN,
        ],
        handler=_cancel,
        path_ids=[("appointment_id", "appointment")],
        role_extra=_role_extra_cancel,
        scope=_appt_owner_scope,
        freeze=_freeze_cancel,
        payload=_validate_cancel,
        enums=[("cancellation_reason", "cancellation_reason")],
        checks={10: _state_cancel},
        is_write=True,
    ),
    Spec(
        method="POST",
        path="/appointments/{appointment_id}/check-in",
        roles=[constants.ROLE_CLINICIAN],
        handler=_check_in,
        status=201,
        path_ids=[("appointment_id", "appointment")],
        freeze=_freeze_checkin,
        checks={
            10: _state_checkin,
            12: _eligible_checkin,
            15: _credentialed_checkin,
        },
        is_write=True,
    ),
]
