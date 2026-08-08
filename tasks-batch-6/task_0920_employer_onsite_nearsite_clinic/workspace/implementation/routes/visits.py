"""The encounter and its two independent axes (PRD 3.5).

`encounter_status` (clinical) and `disclosure_status` (confidentiality) are
separate stored fields.  Neither is a function of the other and neither is
collapsed into a compound status.
"""

from core import calc, constants, ladder, payload, recompute, serializers, store, timeutil
from core.errors import ApiError
from core.ladder import ObjectResult, Spec, paginate

from .common import employer_of_visit, filter_rows, scope_rule


def _visit(ctx):
    return ctx.entity("visit_id")


def _freeze_on_service_date(ctx):
    visit = _visit(ctx)
    ladder.freeze_if_covered(
        employer_of_visit(visit), timeutil.parse_date(visit["service_date"])
    )


# -------------------------------------------------------------------- reads --

def _list(ctx):
    rows = filter_rows(
        store.all_rows("visit"),
        {
            "participant_id": ctx.args.get("participant_id"),
            "provider_id": ctx.args.get("provider_id"),
            "site_id": ctx.args.get("site_id"),
            "appointment_id": ctx.args.get("appointment_id"),
            "visit_type": ctx.args.get("visit_type"),
            "encounter_status": ctx.args.get("encounter_status"),
        },
    )
    return paginate(ctx, "visit", rows)


def _read(ctx):
    return ObjectResult(serializers.dump("visit", _visit(ctx)), 200)


# -------------------------------------------------------------------- start --

def _state_start(ctx):
    if _visit(ctx)["encounter_status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE")


def _start(ctx):
    visit = _visit(ctx)
    visit["encounter_status"] = "IN_PROGRESS"
    return ObjectResult(serializers.dump("visit", visit), 200)


# ----------------------------------------------------------------- complete --

def _validate_complete(ctx):
    visit = _visit(ctx)
    payload.optional_string(ctx.body, "clinical_note")
    if visit["visit_type"] == "OCC_HEALTH":
        payload.require_present(ctx.body, "fitness_conclusion")
    if payload.present(ctx.body, "fitness_conclusion") and not isinstance(
        ctx.body["fitness_conclusion"], str
    ):
        raise ApiError("ERR_VALIDATION", "Field 'fitness_conclusion' must be a string.")


def _state_complete(ctx):
    if _visit(ctx)["encounter_status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE")


def _complete(ctx):
    visit = _visit(ctx)
    if payload.present(ctx.body, "fitness_conclusion"):
        visit["fitness_conclusion"] = ctx.body["fitness_conclusion"]
    if payload.present(ctx.body, "clinical_note"):
        visit["clinical_note"] = ctx.body["clinical_note"]

    visit["encounter_status"] = "COMPLETED"
    visit_type = visit["visit_type"]
    visit["chargeable_party"] = constants.CHARGEABLE_PARTY_BY_VISIT_TYPE[visit_type]
    visit["consumes_benefit_entitlement"] = visit_type == "PRIMARY_CARE"

    participant = store.get("participant", visit["participant_id"])

    # The confidentiality axis fires as part of the same completion and forks
    # on visit_type AND the participant's current authorization_status.
    if visit_type == "PRIMARY_CARE":
        visit["disclosure_status"] = "NOT_DISCLOSABLE"
    elif participant is not None and participant["authorization_status"] == "GRANTED":
        visit["disclosure_status"] = "RELEASE_PENDING"
    else:
        visit["disclosure_status"] = "SUPPRESSED"

    if participant is not None:
        recompute.recompute_participant_derived(participant)
    return ObjectResult(serializers.dump("visit", visit), 200)


# -------------------------------------------------------------------- amend --

def _validate_amend(ctx):
    payload.require_int(ctx.body, "expected_visit_version")
    payload.optional_string(ctx.body, "clinical_note")
    if payload.present(ctx.body, "fitness_conclusion") and not isinstance(
        ctx.body["fitness_conclusion"], str
    ):
        raise ApiError("ERR_VALIDATION", "Field 'fitness_conclusion' must be a string.")


def _state_amend(ctx):
    visit = _visit(ctx)
    if visit["encounter_status"] not in ("COMPLETED", "AMENDED"):
        raise ApiError("ERR_INVALID_STATE")
    if not int(visit["amendment_count"]) < constants.MAX_VISIT_AMENDMENTS:
        raise ApiError("ERR_INVALID_STATE")


def _amend(ctx):
    visit = _visit(ctx)
    if payload.present(ctx.body, "clinical_note"):
        visit["clinical_note"] = ctx.body["clinical_note"]
    if payload.present(ctx.body, "fitness_conclusion"):
        visit["fitness_conclusion"] = ctx.body["fitness_conclusion"]
    visit["encounter_status"] = "AMENDED"
    visit["amendment_count"] = int(visit["amendment_count"]) + 1
    # Amending does not touch the disclosure axis.
    return ObjectResult(serializers.dump("visit", visit), 200)


# ------------------------------------------------------- disclosure release --

def _authorization_in_force(ctx):
    visit = _visit(ctx)
    participant = store.get("participant", visit["participant_id"])
    if participant is None or participant["authorization_status"] != "GRANTED":
        raise ApiError("ERR_AUTHORIZATION_REVOKED")


def _release_permitted(ctx):
    if _visit(ctx)["disclosure_status"] != "RELEASE_PENDING":
        raise ApiError("ERR_DISCLOSURE_NOT_PERMITTED")


def _release(ctx):
    visit = _visit(ctx)
    if visit["visit_type"] == "OCC_HEALTH":
        visit["disclosure_status"] = "FITNESS_RELEASED"
    else:
        visit["disclosure_status"] = "PARTICIPATION_RELEASED"
    return ObjectResult(serializers.dump("visit", visit), 200)


# ------------------------------------------------------- employer disclosure --

def _disclosure_readable(ctx):
    if _visit(ctx)["disclosure_status"] not in ("FITNESS_RELEASED", "PARTICIPATION_RELEASED"):
        raise ApiError("ERR_DISCLOSURE_NOT_PERMITTED")


def _employer_disclosure(ctx):
    return ObjectResult(calc.visit_disclosure_payload(_visit(ctx)), 200)


_READ_ROLES = [
    constants.ROLE_PROGRAM_ADMIN,
    constants.ROLE_CLINIC_MANAGER,
    constants.ROLE_CLINICIAN,
    constants.ROLE_CARE_NAVIGATOR,
    constants.ROLE_PARTICIPANT,
    constants.ROLE_EMPLOYER_BENEFITS_ADMIN,
]

_owner_scope = scope_rule(
    participant_of=lambda ctx: ctx.entity("visit_id")["participant_id"],
)

# Only the visit's own provider may ADVANCE the encounter (PRD 3.5).
_advance_scope = scope_rule(
    visit_provider_of=lambda ctx: ctx.entity("visit_id")["provider_id"],
)

SPECS = [
    Spec(
        method="GET",
        path="/visits",
        roles=_READ_ROLES,
        handler=_list,
        walled=True,
    ),
    Spec(
        method="GET",
        path="/visits/{visit_id}",
        roles=_READ_ROLES,
        handler=_read,
        walled=True,
        path_ids=[("visit_id", "visit")],
        scope=_owner_scope,
    ),
    Spec(
        method="POST",
        path="/visits/{visit_id}/start",
        roles=[constants.ROLE_CLINICIAN],
        handler=_start,
        path_ids=[("visit_id", "visit")],
        scope=_advance_scope,
        checks={10: _state_start},
        is_write=True,
    ),
    Spec(
        method="POST",
        path="/visits/{visit_id}/complete",
        roles=[constants.ROLE_CLINICIAN],
        handler=_complete,
        path_ids=[("visit_id", "visit")],
        scope=_advance_scope,
        payload=_validate_complete,
        enums=[("fitness_conclusion", "fitness_conclusion")],
        checks={10: _state_complete},
        is_write=True,
    ),
    Spec(
        method="POST",
        path="/visits/{visit_id}/amend",
        roles=[constants.ROLE_CLINICIAN],
        handler=_amend,
        path_ids=[("visit_id", "visit")],
        scope=_advance_scope,
        freeze=_freeze_on_service_date,
        payload=_validate_amend,
        enums=[("fitness_conclusion", "fitness_conclusion")],
        occ=("expected_visit_version", lambda ctx: ctx.entity("visit_id")),
        checks={10: _state_amend},
        is_write=True,
    ),
    Spec(
        method="POST",
        path="/visits/{visit_id}/disclosure-release",
        roles=[constants.ROLE_CLINICIAN],
        handler=_release,
        path_ids=[("visit_id", "visit")],
        scope=_advance_scope,
        freeze=_freeze_on_service_date,
        checks={13: _authorization_in_force, 14: _release_permitted},
        is_write=True,
    ),
    Spec(
        method="GET",
        path="/visits/{visit_id}/employer-disclosure",
        roles=[constants.ROLE_EMPLOYER_BENEFITS_ADMIN, constants.ROLE_PROGRAM_ADMIN],
        handler=_employer_disclosure,
        path_ids=[("visit_id", "visit")],
        scope=scope_rule(employer_of=lambda ctx: employer_of_visit(ctx.entity("visit_id"))),
        checks={14: _disclosure_readable},
    ),
]
