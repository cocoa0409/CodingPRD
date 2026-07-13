"""Vital-event registration lifecycle: drafting, filing, delay-fee classification,
state-file numbering, the RETURNED revision loop, and the registered_count invariant."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_facility_filer_headers,
    set_clock,
    create_facility,
    create_vital_event,
    file_event,
    register_event,
    return_event,
    void_event,
    create_facility_payload,
    create_vital_event_payload,
    api_client,
)

REGISTRAR = TEST_USERS["registrar_headers"]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / registration_fee_timely_vs_delayed_same_event_type
# ---------------------------------------------------------------------------
def test_death_filed_at_window_is_timely_with_zero_fee(api):
    """PRD §3.1: "Otherwise, if `days_late` is greater than the statutory window
    for the event type, the type is `DELAYED`; if `days_late` is less than or
    equal to the window, the type is `TIMELY`."
    PRD §3.1: "a `TIMELY` record carries 0, while a `DELAYED` or `FOREIGN` record
    carries a base surcharge of 2000 cents plus 100 cents for every full day of
    overage, where overage is `days_late` minus the statutory window but never
    less than zero, and the per-day portion is capped so that the total never
    exceeds the base plus 5000 cents."

    Design: Difficulty/dual_variant_calc/registration_fee_timely_vs_delayed_same_event_type
    """
    fac = create_facility(facility_type="FUNERAL_HOME", jurisdiction_code="CTY-02")
    ev = create_vital_event(
        fac["id"], event_type="DEATH", event_date="2026-03-01T00:00:00Z",
        jurisdiction_code="CTY-02", sex="MALE", subject_last_name="Doe",
    )
    set_clock("2026-03-06T00:00:00Z")  # 5 days after event_date (== window)
    filed = validate_success(
        api.file_vital_event(ev["id"], make_facility_filer_headers(fac["id"]))
    )
    assert filed["days_late"] == 5
    assert filed["registration_type"] == "TIMELY"
    assert filed["delayed_fee_cents"] == 0


def test_death_filed_over_window_is_delayed_with_surcharge(api):
    """PRD §3.1: "Otherwise, if `days_late` is greater than the statutory window
    for the event type, the type is `DELAYED`; if `days_late` is less than or
    equal to the window, the type is `TIMELY`."
    PRD §3.1: "a `TIMELY` record carries 0, while a `DELAYED` or `FOREIGN` record
    carries a base surcharge of 2000 cents plus 100 cents for every full day of
    overage, where overage is `days_late` minus the statutory window but never
    less than zero, and the per-day portion is capped so that the total never
    exceeds the base plus 5000 cents."

    Design: Difficulty/dual_variant_calc/registration_fee_timely_vs_delayed_same_event_type
    """
    fac = create_facility(facility_type="FUNERAL_HOME", jurisdiction_code="CTY-02")
    ev = create_vital_event(
        fac["id"], event_type="DEATH", event_date="2026-03-01T00:00:00Z",
        jurisdiction_code="CTY-02", sex="FEMALE", subject_last_name="Doe",
    )
    set_clock("2026-03-07T00:00:00Z")  # 6 days after event_date (window+1)
    filed = validate_success(
        api.file_vital_event(ev["id"], make_facility_filer_headers(fac["id"]))
    )
    assert filed["days_late"] == 6
    assert filed["registration_type"] == "DELAYED"
    assert filed["delayed_fee_cents"] == 2100


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / delay_fee_boundary_five_vs_six_days_on_file
# ---------------------------------------------------------------------------
def test_delay_fee_days_late_five_is_boundary_timely(api):
    """PRD §3.1: "First, `days_late` is the number of whole days between
    `event_date` and `filed_at`: the difference of the two instants in seconds,
    divided by 86,400, rounded down to a whole number."
    PRD §3.1: "if `days_late` is less than or equal to the window, the type is
    `TIMELY`."

    Design: Difficulty/boundary_precision_check/delay_fee_boundary_five_vs_six_days_on_file
    """
    fac = create_facility(facility_type="FUNERAL_HOME", jurisdiction_code="CTY-15")
    ev = create_vital_event(
        fac["id"], event_type="DEATH", event_date="2026-03-01T00:00:00Z",
        jurisdiction_code="CTY-15", sex="MALE",
    )
    set_clock("2026-03-06T00:00:00Z")
    filed = validate_success(
        api.file_vital_event(ev["id"], make_facility_filer_headers(fac["id"]))
    )
    assert filed["days_late"] == 5
    assert filed["delayed_fee_cents"] == 0


def test_delay_fee_days_late_six_crosses_to_delayed(api):
    """PRD §3.1: "Otherwise, if `days_late` is greater than the statutory window
    for the event type, the type is `DELAYED`".
    PRD §3.1: "a `DELAYED` or `FOREIGN` record carries a base surcharge of 2000
    cents plus 100 cents for every full day of overage".

    Design: Difficulty/boundary_precision_check/delay_fee_boundary_five_vs_six_days_on_file
    """
    fac = create_facility(facility_type="FUNERAL_HOME", jurisdiction_code="CTY-15")
    ev = create_vital_event(
        fac["id"], event_type="DEATH", event_date="2026-03-01T00:00:00Z",
        jurisdiction_code="CTY-15", sex="MALE",
    )
    set_clock("2026-03-07T00:00:00Z")
    filed = validate_success(
        api.file_vital_event(ev["id"], make_facility_filer_headers(fac["id"]))
    )
    assert filed["days_late"] == 6
    assert filed["delayed_fee_cents"] == 2100


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / void_conserves_facility_registered_count
# ---------------------------------------------------------------------------
def test_register_increments_facility_registered_count(api):
    """PRD §2.5: "A `Facility` tracks `registered_count`, the number of vital
    events with that `facility_id` whose `status` is `REGISTERED` or `AMENDED`.
    It increases by one when a record is registered and decreases by one when a
    record is voided."

    Design: Difficulty/compensating_invariant/void_conserves_facility_registered_count
    """
    fac = create_facility(jurisdiction_code="CTY-21")
    ev = create_vital_event(fac["id"], jurisdiction_code="CTY-21", subject_last_name="Uma")
    file_event(ev["id"], fac["id"])
    register_event(ev["id"])
    after_reg = validate_success(api.get_facility(fac["id"], REGISTRAR))
    assert after_reg["registered_count"] == 1


def test_void_decrements_facility_registered_count_back(api):
    """PRD §2.5: "A `Facility` tracks `registered_count`, the number of vital
    events with that `facility_id` whose `status` is `REGISTERED` or `AMENDED`.
    It increases by one when a record is registered and decreases by one when a
    record is voided."

    Design: Difficulty/compensating_invariant/void_conserves_facility_registered_count
    """
    fac = create_facility(jurisdiction_code="CTY-21")
    ev = create_vital_event(fac["id"], jurisdiction_code="CTY-21", subject_last_name="Uma")
    file_event(ev["id"], fac["id"])
    register_event(ev["id"])
    void_event(ev["id"])
    after_void = validate_success(api.get_facility(fac["id"], REGISTRAR))
    assert after_void["registered_count"] == 0


# ---------------------------------------------------------------------------
# Corner: entities / birth_event_creation_returns_201_with_system_fields
# ---------------------------------------------------------------------------
def test_birth_event_creation_returns_draft_and_system_fields(api):
    """PRD §3.1: "A newly drafted record begins in `DRAFT` status. At creation the
    system pins `certification_required` to true exactly when `event_type` is
    `DEATH` or `FETAL_DEATH`, and false for a `BIRTH`; a death or fetal-death
    record cannot be registered until a certified cause of death exists."
    PRD §2.4: "`version`: an integer that starts at its initial value and
    increments by one on every mutation."

    Design: Corner/entities/birth_event_creation_returns_201_with_system_fields
    """
    fac = create_facility(jurisdiction_code="CTY-30")
    resp = api.create_vital_event(
        create_vital_event_payload(
            fac["id"], event_type="BIRTH", jurisdiction_code="CTY-30",
            subject_last_name="New", subject_first_name="Born", sex="MALE",
        ),
        make_facility_filer_headers(fac["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT"
    assert data["certification_required"] is False
    assert data["version"] == 1


# ---------------------------------------------------------------------------
# Corner: entities / vital_event_foreign_born_defaults_false
# ---------------------------------------------------------------------------
def test_vital_event_foreign_born_defaults_false(api):
    """PRD §3.1: "The filer may also set `foreign_born` to indicate the event
    occurred outside the state's territory; it defaults to false."

    Design: Corner/entities/vital_event_foreign_born_defaults_false
    """
    fac = create_facility(jurisdiction_code="CTY-32")
    payload = create_vital_event_payload(
        fac["id"], event_type="BIRTH", jurisdiction_code="CTY-32",
        subject_last_name="Def", subject_first_name="Ault", sex="MALE",
    )
    payload.pop("foreign_born", None)
    data = validate_success(
        api.create_vital_event(payload, make_facility_filer_headers(fac["id"])),
        expected_status=201,
    )
    assert data["foreign_born"] is False


# ---------------------------------------------------------------------------
# Corner: entities / new_facility_registered_count_defaults_zero
# ---------------------------------------------------------------------------
def test_new_facility_registered_count_defaults_zero(api):
    """PRD §2.5: "A `Facility` tracks `registered_count`, the number of vital
    events with that `facility_id` whose `status` is `REGISTERED` or `AMENDED`.
    It increases by one when a record is registered and decreases by one when a
    record is voided."

    Design: Corner/entities/new_facility_registered_count_defaults_zero
    """
    data = validate_success(
        api.create_facility(
            create_facility_payload(
                facility_type="BIRTHING_CENTER", jurisdiction_code="CTY-33",
                npi="NPI-033",
            ),
            REGISTRAR,
        ),
        expected_status=201,
    )
    assert data["registered_count"] == 0


# ---------------------------------------------------------------------------
# Corner: state_machines / register_from_draft_returns_invalid_state
# ---------------------------------------------------------------------------
def test_register_from_draft_returns_invalid_state(api):
    """PRD §3.1: "Registration is refused unless the record is in `FILED`."
    PRD §2.9: "State — the target is in a state from which the requested
    transition is defined, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/register_from_draft_returns_invalid_state
    """
    fac = create_facility(jurisdiction_code="CTY-34")
    ev = create_vital_event(fac["id"], jurisdiction_code="CTY-34")
    resp = api.register_vital_event(ev["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Corner: state_machines / void_already_voided_returns_invalid_state
# ---------------------------------------------------------------------------
def test_void_already_voided_returns_invalid_state(api):
    """PRD §3.1: "Finally, a `StateRegistrar` may void a record that is
    `REGISTERED` or `AMENDED`, driving it to the terminal `VOIDED` state and
    reversing everything the registration and copy activity accumulated."
    PRD §2.9: "State — the target is in a state from which the requested
    transition is defined, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/void_already_voided_returns_invalid_state
    """
    fac = create_facility(jurisdiction_code="CTY-36")
    ev = create_vital_event(fac["id"], jurisdiction_code="CTY-36")
    file_event(ev["id"], fac["id"])
    register_event(ev["id"])
    void_event(ev["id"])
    resp = api.void_vital_event(ev["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Corner: state_machines / returned_event_reopens_to_draft_and_refiles
# ---------------------------------------------------------------------------
def test_returned_event_reopens_to_draft_and_refiles(api):
    """PRD §3.1: "A returned record is reopened for refiling: when the owning
    facility refiles a `RETURNED` record, the record first transitions from
    `RETURNED` back to `DRAFT` and is then filed again, recomputing `filed_at`,
    `days_late`, `registration_type`, and `delayed_fee_cents` exactly as on an
    initial filing."

    Design: Corner/state_machines/returned_event_reopens_to_draft_and_refiles
    """
    fac = create_facility(jurisdiction_code="CTY-38")
    ev = create_vital_event(fac["id"], jurisdiction_code="CTY-38")
    file_event(ev["id"], fac["id"])
    return_event(ev["id"])
    refiled = validate_success(
        api.file_vital_event(ev["id"], make_facility_filer_headers(fac["id"]))
    )
    assert refiled["status"] == "FILED"


# ---------------------------------------------------------------------------
# Corner: calculations / registration_delay_fee_surcharge_capped
# ---------------------------------------------------------------------------
def test_registration_delay_fee_surcharge_capped(api):
    """PRD §3.1: "a `DELAYED` or `FOREIGN` record carries a base surcharge of 2000
    cents plus 100 cents for every full day of overage, where overage is
    `days_late` minus the statutory window but never less than zero, and the
    per-day portion is capped so that the total never exceeds the base plus 5000
    cents. In other words the fee equals 2000 plus the smaller of 5000 and 100
    times the overage."

    Design: Corner/calculations/registration_delay_fee_surcharge_capped
    """
    fac = create_facility(facility_type="FUNERAL_HOME", jurisdiction_code="CTY-43")
    ev = create_vital_event(
        fac["id"], event_type="DEATH", event_date="2026-03-01T00:00:00Z",
        jurisdiction_code="CTY-43", sex="MALE",
    )
    set_clock("2026-05-01T00:00:00Z")  # 61 days late
    filed = validate_success(
        api.file_vital_event(ev["id"], make_facility_filer_headers(fac["id"]))
    )
    assert filed["days_late"] == 61
    assert filed["registration_type"] == "DELAYED"
    assert filed["delayed_fee_cents"] == 7000


# ---------------------------------------------------------------------------
# Corner: consistency_model / register_response_reflects_state_file_number_immediately
# ---------------------------------------------------------------------------
def test_register_response_reflects_state_file_number_immediately(api):
    """PRD §3.1: "On success, registration stamps `registered_at` with the current
    clock instant and mints the `state_file_number`."
    PRD §2.5: "All cascades complete within the triggering request — there is no
    deferred reconciliation."

    Design: Corner/consistency_model/register_response_reflects_state_file_number_immediately
    """
    fac = create_facility(jurisdiction_code="CTY-59")
    ev = create_vital_event(fac["id"], jurisdiction_code="CTY-59")
    file_event(ev["id"], fac["id"])
    registered = validate_success(api.register_vital_event(ev["id"], REGISTRAR))
    assert registered["status"] == "REGISTERED"
    assert registered["state_file_number"], "state_file_number must be present in the register response"
