"""The documentation axis of a home visit: attestation, its 72-hour window, the
30-day amendment window measured from the original attestation, and the void
cascade onto linked encounters."""

from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import SUPERVISOR


def test_the_documentation_axis_keeps_moving_after_scheduling_completes(api):
    """PRD §3.5: "A home visit carries **two independent state axes** that
    evolve separately and never constrain each other's transitions."
    PRD §3.5: "`AMEND` applies from `ATTESTED`, moving documentation to
    `AMENDED`, overwriting `visit_note` and incrementing `amendment_count` by 1;
    it also applies from `AMENDED` back to `AMENDED` as a self-loop, again
    overwriting the note and again incrementing the count, so a visit can be
    amended any number of times."

    Design: Difficulty/non_linear_state_machine/home_visit_parallel_scheduling_and_documentation_axes
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-02T08:00:00Z", employee_code="W-006",
        mrn="MRN-060", full_name="Omar Haddad", household_size=5,
        monthly_income_cents=90_000,
    )
    visit = fx.attested_visit(
        chw_headers, patient["id"], worker["id"],
        attested_at="2026-06-02T11:00:00Z", visit_note="Initial documentation",
    )

    fx.set_clock("2026-06-05T11:00:00Z")
    first_amendment = fx.revise_documentation(
        chw_headers, visit["id"], "AMEND", "Added food-insecurity detail"
    )
    assert first_amendment["documentation_status"] == "AMENDED"
    assert first_amendment["amendment_count"] == 1

    fx.set_clock("2026-06-20T11:00:00Z")
    second_amendment = validate_success(
        api.revise_documentation(
            visit["id"],
            {"action": "AMEND", "visit_note": "Corrected household size"},
            chw_headers,
        )
    )

    assert second_amendment["scheduling_status"] == "COMPLETED", (
        "the scheduling axis stays at its terminal COMPLETED throughout"
    )
    assert second_amendment["documentation_status"] == "AMENDED", (
        "the AMENDED self-loop leaves documentation in AMENDED"
    )
    assert second_amendment["amendment_count"] == 2, (
        f"each amendment increments the count, got {second_amendment['amendment_count']}"
    )
    assert second_amendment["visit_note"] == "Corrected household size"


def test_amendments_never_move_the_original_attestation_instant(api):
    """PRD §3.5: "Every amendment must fall within 30 days measured from the
    **original** `attested_at`, never from the most recent amendment; past that,
    the request is rejected at rung 14 with `ERR_AMENDMENT_WINDOW_CLOSED` (HTTP
    422)."
    PRD §3.5: "Along the scheduling axis, the assigned worker departs — moving
    `SCHEDULED` to `EN_ROUTE` — and later completes the visit, moving `EN_ROUTE`
    to `COMPLETED` and stamping `completed_at` with the current logical clock,
    which is the instant that starts the 72-hour attestation clock."

    Design: Difficulty/non_linear_state_machine/home_visit_parallel_scheduling_and_documentation_axes
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-02T08:00:00Z", employee_code="W-006B",
        mrn="MRN-060B", full_name="Omar Haddad", household_size=5,
    )
    visit = fx.attested_visit(
        chw_headers, patient["id"], worker["id"],
        attested_at="2026-06-02T11:00:00Z", visit_note="Initial documentation",
    )
    assert_same_instant(
        visit["completed_at"], "2026-06-02T10:00:00Z", "visit.completed_at"
    )
    assert_same_instant(
        visit["attested_at"], "2026-06-02T11:00:00Z", "visit.attested_at"
    )

    fx.set_clock("2026-06-05T11:00:00Z")
    fx.revise_documentation(
        chw_headers, visit["id"], "AMEND", "Added food-insecurity detail"
    )
    fx.set_clock("2026-06-20T11:00:00Z")
    fx.revise_documentation(
        chw_headers, visit["id"], "AMEND", "Corrected household size"
    )

    reread = fx.read_home_visit(visit["id"])
    assert_same_instant(
        reread["attested_at"], "2026-06-02T11:00:00Z",
        "visit.attested_at after two amendments",
    )
    assert_same_instant(
        reread["completed_at"], "2026-06-02T10:00:00Z",
        "visit.completed_at after two amendments",
    )
    assert reread["two_person_required"] is False, (
        "two_person_required is copied from a false address_safety_flag"
    )


def test_ownership_is_checked_before_the_attestation_window(api):
    """PRD §2.5: "The server evaluates checks in a single global order and stops
    at the first failure; no later check may mask an earlier one, and no earlier
    check may be skipped because a later one is cheaper to evaluate."
    PRD §2.5: "**Actor identity and segregation of duties** — the caller owns
    the resource, or is distinct from the party they must be distinct from
    (`ERR_NOT_RESOURCE_OWNER` or `ERR_SEGREGATION_OF_DUTIES`, each 403)."
    PRD §3.5: "Attestation requires `documentation_status` to be `DRAFT`,
    requires `scheduling_status` to be `COMPLETED`, requires the acting
    `X-User-ID` to equal `assigned_chw_id`, and requires the elapsed time from
    `completed_at` to the current logical clock to be no more than 72 hours —
    exactly 72 hours still attests, and anything beyond is rejected at rung 14
    with `ERR_ATTESTATION_WINDOW_CLOSED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/ownership_rung10_preempts_attestation_window_rung14
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-02T08:00:00Z", employee_code="W-011",
        mrn="MRN-110", full_name="Tomas Vela",
    )
    other, other_headers = fx.second_worker(employee_code="W-012")
    visit = fx.completed_visit(chw_headers, patient["id"], worker["id"])

    fx.set_clock("2026-06-05T11:00:00Z")
    response = api.attest_home_visit(
        visit["id"], {"visit_note": "Attempted by the wrong worker"}, other_headers
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    assert response.status_code == 403


def test_the_out_of_window_owner_gets_the_window_error_instead(api):
    """PRD §3.5: "Attestation requires `documentation_status` to be `DRAFT`,
    requires `scheduling_status` to be `COMPLETED`, requires the acting
    `X-User-ID` to equal `assigned_chw_id`, and requires the elapsed time from
    `completed_at` to the current logical clock to be no more than 72 hours —
    exactly 72 hours still attests, and anything beyond is rejected at rung 14
    with `ERR_ATTESTATION_WINDOW_CLOSED` (HTTP 422)."
    PRD §2.5: "**Window and count limits** — attestation, amendment, re-route
    and appeal limits (`ERR_ATTESTATION_WINDOW_CLOSED`,
    `ERR_AMENDMENT_WINDOW_CLOSED`, `ERR_REROUTE_LIMIT_EXCEEDED`,
    `ERR_APPEAL_WINDOW_CLOSED`, each 422)."

    Design: Difficulty/priority_pair_validation_conflict/ownership_rung10_preempts_attestation_window_rung14
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-02T08:00:00Z", employee_code="W-011B",
        mrn="MRN-110B", full_name="Tomas Vela",
    )
    other, other_headers = fx.second_worker(employee_code="W-012B")
    visit = fx.completed_visit(chw_headers, patient["id"], worker["id"])

    fx.set_clock("2026-06-05T11:00:00Z")
    stranger = api.attest_home_visit(
        visit["id"], {"visit_note": "Attempted by the wrong worker"}, other_headers
    )
    validate_error(stranger, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    owner = api.attest_home_visit(
        visit["id"], {"visit_note": "Late but by the right worker"}, chw_headers
    )
    validate_error(owner, ApiErrorId.ERR_ATTESTATION_WINDOW_CLOSED.value, 422)

    reread = fx.read_home_visit(visit["id"])
    assert reread["documentation_status"] == "DRAFT", (
        "neither refused attestation moved the documentation axis"
    )
    assert reread["attested_at"] is None


def test_attestation_at_exactly_seventy_two_hours_is_accepted(api):
    """PRD §3.5: "Attestation requires `documentation_status` to be `DRAFT`,
    requires `scheduling_status` to be `COMPLETED`, requires the acting
    `X-User-ID` to equal `assigned_chw_id`, and requires the elapsed time from
    `completed_at` to the current logical clock to be no more than 72 hours —
    exactly 72 hours still attests, and anything beyond is rejected at rung 14
    with `ERR_ATTESTATION_WINDOW_CLOSED` (HTTP 422)."
    PRD §3.5: "A successful attestation sets `documentation_status` to
    `ATTESTED` and stamps `attested_at`."

    Design: Corner/validations/attestation_window_exactly_72_hours_accepted
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-01T00:00:00Z", employee_code="C-039",
        mrn="MRN-C39", full_name="Attest Edge",
    )
    visit = fx.completed_visit(chw_headers, patient["id"], worker["id"])

    fx.set_clock("2026-06-05T10:00:00Z")
    response = api.attest_home_visit(
        visit["id"], {"visit_note": "Attested on the last legal second"}, chw_headers
    )
    data = validate_success(response, 200)

    assert data["documentation_status"] == "ATTESTED"
    assert_same_instant(
        data["attested_at"], "2026-06-05T10:00:00Z", "visit.attested_at"
    )
    assert_same_instant(
        data["completed_at"], "2026-06-02T10:00:00Z", "visit.completed_at"
    )
    assert data["amendment_count"] == 0


def test_the_amendment_window_closes_thirty_days_after_attestation(api):
    """PRD §3.5: "Every amendment must fall within 30 days measured from the
    **original** `attested_at`, never from the most recent amendment; past that,
    the request is rejected at rung 14 with `ERR_AMENDMENT_WINDOW_CLOSED` (HTTP
    422)."
    PRD §3.5: "`AMEND` applies from `ATTESTED`, moving documentation to
    `AMENDED`, overwriting `visit_note` and incrementing `amendment_count` by 1;
    it also applies from `AMENDED` back to `AMENDED` as a self-loop, again
    overwriting the note and again incrementing the count, so a visit can be
    amended any number of times."

    Design: Corner/validations/amendment_window_closes_after_thirty_days
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-01T00:00:00Z", employee_code="C-038",
        mrn="MRN-C38", full_name="Amend Window Case",
    )
    visit = fx.attested_visit(
        chw_headers, patient["id"], worker["id"],
        attested_at="2026-06-02T11:00:00Z", visit_note="Original documentation",
    )

    fx.set_clock("2026-07-02T11:00:01Z")
    too_late = api.revise_documentation(
        visit["id"], {"action": "AMEND", "visit_note": "Too late"}, chw_headers
    )
    validate_error(too_late, ApiErrorId.ERR_AMENDMENT_WINDOW_CLOSED.value, 422)

    fx.set_clock("2026-07-02T11:00:00Z")
    on_boundary = validate_success(
        api.revise_documentation(
            visit["id"],
            {"action": "AMEND", "visit_note": "Exactly on the boundary"},
            chw_headers,
        )
    )

    assert_same_instant(
        on_boundary["attested_at"], "2026-06-02T11:00:00Z", "visit.attested_at"
    )
    assert on_boundary["documentation_status"] == "AMENDED"
    assert on_boundary["amendment_count"] == 1
    assert on_boundary["visit_note"] == "Exactly on the boundary"


def test_a_no_show_visit_can_never_be_attested(api):
    """PRD §3.5: "A visit in `NO_SHOW` keeps `documentation_status` at `DRAFT`
    forever and can never be attested, since attestation requires `COMPLETED`."
    PRD §2.5: "**Target-entity state precondition** — the target row is in a
    state that permits the requested transition (`ERR_INVALID_STATE`, 409)."

    Design: Corner/state_machines/home_visit_no_show_can_never_be_attested
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-01T00:00:00Z", employee_code="C-014",
        mrn="MRN-C14", full_name="NoShow Case",
    )
    visit = fx.schedule_visit(
        chw_headers, patient["id"], worker["id"],
        "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z",
    )

    fx.set_clock("2026-06-02T09:30:00Z")
    no_show = validate_success(api.no_show_home_visit(visit["id"], chw_headers))
    assert no_show["scheduling_status"] == "NO_SHOW"

    response = api.attest_home_visit(
        visit["id"],
        {"visit_note": "Attempted attestation of a no-show"},
        chw_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    reread = fx.read_home_visit(visit["id"])
    assert reread["scheduling_status"] == "NO_SHOW"
    assert reread["documentation_status"] == "DRAFT", (
        "the documentation axis stays DRAFT forever on a no-show"
    )
    assert reread["completed_at"] is None


def test_voiding_documentation_only_voids_the_draft_encounters(api):
    """PRD §3.5: "`VOID` applies from either `ATTESTED` or `AMENDED`, sets
    `documentation_status` to `VOIDED`, and cascades: every encounter whose
    `home_visit_id` names this visit and whose `status` is `DRAFT` is itself
    voided."
    PRD §3.5: "The two actions have different owners, and the mismatch is caught
    at rung 10: `AMEND` requires the caller to be a `CHW` whose `X-User-ID`
    equals `assigned_chw_id`, while `VOID` requires the caller to be a
    `Supervisor`; a caller who fails the applicable test gets
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/state_machines/documentation_void_cascade_only_touches_draft_encounters
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-01T00:00:00Z", employee_code="C-016",
        mrn="MRN-C16", full_name="Void Case",
    )
    visit = fx.attested_visit(
        chw_headers, patient["id"], worker["id"],
        attested_at="2026-06-02T11:00:00Z", visit_note="Visit documented",
    )

    draft_encounter = fx.create_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-02",
        direct_minutes=30, indirect_minutes=0, travel_minutes=0,
        documentation_minutes=0, home_visit_id=visit["id"],
    )
    submitted_encounter = fx.submitted_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-02",
        direct_minutes=60, indirect_minutes=0, travel_minutes=0,
        documentation_minutes=0, home_visit_id=visit["id"],
    )

    voided = validate_success(
        api.revise_documentation(visit["id"], {"action": "VOID"}, SUPERVISOR)
    )
    assert voided["documentation_status"] == "VOIDED"
    assert voided["scheduling_status"] == "COMPLETED", (
        "the scheduling axis is untouched by a documentation void"
    )

    assert fx.read_encounter(draft_encounter["id"])["status"] == "VOIDED", (
        "a linked DRAFT encounter is voided by the cascade"
    )
    survivor = fx.read_encounter(submitted_encounter["id"])
    assert survivor["status"] == "SUBMITTED", (
        "an already SUBMITTED encounter on the same visit is left alone"
    )
    assert survivor["billable_minutes"] == 60
