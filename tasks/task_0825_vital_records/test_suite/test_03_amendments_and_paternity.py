"""Amendment revision loop and the paternity-acknowledgment branch machine,
including the father-field cascade onto the birth record and the timing windows."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_paternity,
    acknowledge_paternity,
    create_amendment,
    submit_amendment,
    setup_registered_birth_event,
    setup_registered_death_event,
)

REGISTRAR = TEST_USERS["registrar_headers"]
APPLICANT = TEST_USERS["applicant_headers"]


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / amendment_reject_then_resubmit_cycle
# ---------------------------------------------------------------------------
def test_amendment_reject_moves_to_rejected(api):
    """PRD §3.4: "A registrar may reject a submitted amendment, moving it from
    `SUBMITTED` to `REJECTED`."

    Design: Difficulty/non_linear_state_machine/amendment_reject_then_resubmit_cycle
    """
    fac, ev = setup_registered_birth_event(jurisdiction_code="CTY-04")
    am = create_amendment(ev["id"], field_name="subject_last_name", new_value="Ohno")
    submit_amendment(am["id"])
    rejected = validate_success(api.reject_amendment(am["id"], REGISTRAR))
    assert rejected["status"] == "REJECTED"


def test_rejected_amendment_resubmits_to_submitted(api):
    """PRD §3.4: "Submission moves an amendment from `DRAFT` to `SUBMITTED`, and a
    rejected amendment may be resubmitted, moving from `REJECTED` back to
    `SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/amendment_reject_then_resubmit_cycle
    """
    fac, ev = setup_registered_birth_event(jurisdiction_code="CTY-04")
    am = create_amendment(ev["id"], field_name="subject_last_name", new_value="Ohno")
    submit_amendment(am["id"])
    validate_success(api.reject_amendment(am["id"], REGISTRAR))
    resubmitted = validate_success(api.submit_amendment(am["id"], REGISTRAR))
    assert resubmitted["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / paternity_acknowledge_then_rescind_branch
# ---------------------------------------------------------------------------
def test_paternity_rescind_sets_status_rescinded(api):
    """PRD §3.5: "A `StateRegistrar` or an `Applicant` may rescind it, moving it
    from `ACKNOWLEDGED` to the terminal `RESCINDED` state, but only while the
    current clock instant is at or before `rescission_deadline`; a later attempt
    is rejected with `ERR_RESCISSION_WINDOW_CLOSED`."

    Design: Difficulty/non_linear_state_machine/paternity_acknowledge_then_rescind_branch
    """
    fac, ev = setup_registered_birth_event(jurisdiction_code="CTY-05")
    pa = create_paternity(ev["id"], father_last_name="Vale", father_first_name="Max")
    acknowledge_paternity(pa["id"])
    rescinded = validate_success(api.rescind_paternity(pa["id"], REGISTRAR))
    assert rescinded["status"] == "RESCINDED"


def test_paternity_rescind_clears_father_fields_on_event(api):
    """PRD §3.5: "Rescission cascades onto the record, clearing `father_last_name`
    and `father_first_name` back to null, setting `paternity_established` to
    false, and incrementing the record's `version` by one."

    Design: Difficulty/non_linear_state_machine/paternity_acknowledge_then_rescind_branch
    """
    fac, ev = setup_registered_birth_event(jurisdiction_code="CTY-05")
    pa = create_paternity(ev["id"], father_last_name="Vale", father_first_name="Max")
    acknowledge_paternity(pa["id"])
    validate_success(api.rescind_paternity(pa["id"], REGISTRAR))
    ev_after = validate_success(api.get_vital_event(ev["id"], REGISTRAR))
    assert ev_after["paternity_established"] is False
    assert ev_after["father_first_name"] is None


# ---------------------------------------------------------------------------
# Corner: state_machines / paternity_finalize_before_window_returns_open
# ---------------------------------------------------------------------------
def test_paternity_finalize_before_window_returns_open(api):
    """PRD §3.5: "a `StateRegistrar` may finalize an acknowledgment, moving it
    from `ACKNOWLEDGED` to the terminal `FINALIZED` state, but only once the
    window has closed — that is, only when the current clock instant is strictly
    after `rescission_deadline`; an attempt while the window is still open is
    rejected with `ERR_RESCISSION_WINDOW_OPEN`."

    Design: Corner/state_machines/paternity_finalize_before_window_returns_open
    """
    fac, ev = setup_registered_birth_event(jurisdiction_code="CTY-39")
    pa = create_paternity(ev["id"], father_last_name="Fin", father_first_name="Pa")
    acknowledge_paternity(pa["id"])  # clock still at default 2026-03-01, window open
    resp = api.finalize_paternity(pa["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_RESCISSION_WINDOW_OPEN)


# ---------------------------------------------------------------------------
# Corner: state_machines / paternity_rescind_after_deadline_returns_closed
# ---------------------------------------------------------------------------
def test_paternity_rescind_after_deadline_returns_closed(api):
    """PRD §3.5: "A `StateRegistrar` or an `Applicant` may rescind it, moving it
    from `ACKNOWLEDGED` to the terminal `RESCINDED` state, but only while the
    current clock instant is at or before `rescission_deadline`; a later attempt
    is rejected with `ERR_RESCISSION_WINDOW_CLOSED`."
    PRD §3.5: "It stamps `acknowledged_at` with the current clock instant, sets
    `rescission_deadline` to that instant plus 60 days".

    Design: Corner/state_machines/paternity_rescind_after_deadline_returns_closed
    """
    fac, ev = setup_registered_birth_event(jurisdiction_code="CTY-40")
    pa = create_paternity(ev["id"], father_last_name="Late", father_first_name="Pa")
    acknowledge_paternity(pa["id"])  # acknowledged at default clock 2026-03-01
    set_clock("2026-04-30T00:00:01Z")  # one second past the 60-day deadline
    resp = api.rescind_paternity(pa["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_RESCISSION_WINDOW_CLOSED)


# ---------------------------------------------------------------------------
# Corner: validations / paternity_acknowledge_on_death_returns_not_birth_event
# ---------------------------------------------------------------------------
def test_paternity_acknowledge_on_death_returns_not_birth_event(api):
    """PRD §3.5: "Acknowledgment requires that the referenced event's
    `event_type` be `BIRTH` (else `ERR_NOT_BIRTH_EVENT`), that the event be
    `REGISTERED` or `AMENDED` (else `ERR_EVENT_NOT_REGISTERED`), and that
    `mother_consent` be true."

    Design: Corner/validations/paternity_acknowledge_on_death_returns_not_birth_event
    """
    fac, cer, ev, cert = setup_registered_death_event(jurisdiction_code="CTY-47")
    pa = create_paternity(ev["id"], father_last_name="Nb", father_first_name="Pa")
    resp = api.acknowledge_paternity(pa["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_NOT_BIRTH_EVENT)
