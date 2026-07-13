"""Medical certification lifecycle and the registration / medical-amendment
cascade chains that drive certifications and their certifier counters."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    make_medical_certifier_headers,
    set_clock,
    create_facility,
    create_certifier,
    create_vital_event,
    create_certification,
    certify,
    file_event,
    register_event,
    create_amendment,
    submit_amendment,
    approve_amendment,
    event_version,
    setup_registered_death_event,
    create_certification_payload,
)

REGISTRAR = TEST_USERS["registrar_headers"]


def _filed_death_with_certified_cert(jurisdiction="CTY-06"):
    """Facility + certifier + DEATH event with a CERTIFIED certification, FILED
    but NOT yet registered. Returns (facility, certifier, event, cert)."""
    fac = create_facility(facility_type="FUNERAL_HOME", jurisdiction_code=jurisdiction)
    cer = create_certifier(jurisdiction_code=jurisdiction)
    ev = create_vital_event(
        fac["id"], event_type="DEATH", event_date="2026-03-01T00:00:00Z",
        jurisdiction_code=jurisdiction, sex="MALE",
    )
    cert = create_certification(ev["id"], cer["id"], cause_of_death="MI")
    certify(cert["id"], cer["id"])
    file_event(ev["id"], fac["id"])
    return fac, cer, ev, cert


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / register_death_locks_cert_bumps_certifier_depth3
# ---------------------------------------------------------------------------
def test_register_death_locks_certification(api):
    """PRD §3.1: "When `certification_required` is true, registration also drives
    the linked certification from `CERTIFIED` to `LOCKED`, and that lock in turn
    increments the signing certifier's `locked_certification_count` by one — a
    three-link cascade from event registration to certification lock to certifier
    counter, all within the single request."

    Design: Difficulty/transitive_cascade/register_death_locks_cert_bumps_certifier_depth3
    """
    fac, cer, ev, cert = _filed_death_with_certified_cert()
    registered = validate_success(api.register_vital_event(ev["id"], REGISTRAR))
    assert registered["status"] == "REGISTERED"
    cert_after = validate_success(api.get_certification(cert["id"], REGISTRAR))
    assert cert_after["status"] == "LOCKED"


def test_register_death_bumps_certifier_locked_count(api):
    """PRD §3.1: "When `certification_required` is true, registration also drives
    the linked certification from `CERTIFIED` to `LOCKED`, and that lock in turn
    increments the signing certifier's `locked_certification_count` by one — a
    three-link cascade from event registration to certification lock to certifier
    counter, all within the single request."

    Design: Difficulty/transitive_cascade/register_death_locks_cert_bumps_certifier_depth3
    """
    fac, cer, ev, cert = _filed_death_with_certified_cert()
    validate_success(api.register_vital_event(ev["id"], REGISTRAR))
    certifier_after = validate_success(api.get_certifier(cer["id"], REGISTRAR))
    assert certifier_after["locked_certification_count"] == 1


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / medical_amendment_cascades_cert_then_event_depth2
# ---------------------------------------------------------------------------
def test_medical_amendment_updates_target_certification(api):
    """PRD §3.4: "A `MEDICAL` approval instead drives the target certification:
    the certification moves from `LOCKED` to `AMENDED` (or remains in `AMENDED`
    for a further medical correction), its `cause_of_death` takes on `new_value`,
    and its own `amendment_count` increases by one; that certification amendment
    in turn sets the parent record's `cause_of_death_amended` flag to true,
    increments the record's `amendment_count` by one, sets its `status` to
    `AMENDED`, and increments its `version` by one."

    Design: Difficulty/transitive_cascade/medical_amendment_cascades_cert_then_event_depth2
    """
    fac, cer, ev, cert = setup_registered_death_event(jurisdiction_code="CTY-08")
    am = create_amendment(
        ev["id"], amendment_type="MEDICAL", target_certification_id=cert["id"],
        field_name="cause_of_death", new_value="Sepsis", reason="autopsy",
    )
    submit_amendment(am["id"])
    approve_amendment(am["id"], event_version(ev["id"]))
    cert_after = validate_success(api.get_certification(cert["id"], REGISTRAR))
    assert cert_after["status"] == "AMENDED"
    assert cert_after["cause_of_death"] == "Sepsis"


def test_medical_amendment_flags_event_cause_amended(api):
    """PRD §3.4: "that certification amendment in turn sets the parent record's
    `cause_of_death_amended` flag to true, increments the record's
    `amendment_count` by one, sets its `status` to `AMENDED`, and increments its
    `version` by one."

    Design: Difficulty/transitive_cascade/medical_amendment_cascades_cert_then_event_depth2
    """
    fac, cer, ev, cert = setup_registered_death_event(jurisdiction_code="CTY-08")
    am = create_amendment(
        ev["id"], amendment_type="MEDICAL", target_certification_id=cert["id"],
        field_name="cause_of_death", new_value="Sepsis", reason="autopsy",
    )
    submit_amendment(am["id"])
    approve_amendment(am["id"], event_version(ev["id"]))
    ev_after = validate_success(api.get_vital_event(ev["id"], REGISTRAR))
    assert ev_after["cause_of_death_amended"] is True
    assert ev_after["amendment_count"] == 1


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / death_register_blocked_when_certification_not_certified
# ---------------------------------------------------------------------------
def test_register_death_with_pending_certification_blocked(api):
    """PRD §3.1: "If `certification_required` is true, the record's
    `MedicalCertification` must be in `CERTIFIED` status, otherwise the request is
    rejected with `ERR_CERTIFICATION_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/death_register_blocked_when_certification_not_certified
    """
    fac = create_facility(facility_type="FUNERAL_HOME", jurisdiction_code="CTY-17")
    cer = create_certifier(jurisdiction_code="CTY-17", certifier_type="CORONER")
    ev = create_vital_event(
        fac["id"], event_type="DEATH", event_date="2026-03-01T00:00:00Z",
        jurisdiction_code="CTY-17", sex="FEMALE",
    )
    # certification stays PENDING (never signed)
    create_certification(ev["id"], cer["id"], cause_of_death="TBD",
                         manner_of_death="PENDING_INVESTIGATION")
    file_event(ev["id"], fac["id"])
    resp = api.register_vital_event(ev["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_REQUIRED)


def test_register_death_succeeds_once_certification_certified(api):
    """PRD §3.1: "If `certification_required` is true, the record's
    `MedicalCertification` must be in `CERTIFIED` status, otherwise the request is
    rejected with `ERR_CERTIFICATION_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/death_register_blocked_when_certification_not_certified
    """
    fac = create_facility(facility_type="FUNERAL_HOME", jurisdiction_code="CTY-17")
    cer = create_certifier(jurisdiction_code="CTY-17", certifier_type="CORONER")
    ev = create_vital_event(
        fac["id"], event_type="DEATH", event_date="2026-03-01T00:00:00Z",
        jurisdiction_code="CTY-17", sex="FEMALE",
    )
    cert = create_certification(ev["id"], cer["id"], cause_of_death="MI")
    certify(cert["id"], cer["id"])
    file_event(ev["id"], fac["id"])
    registered = validate_success(api.register_vital_event(ev["id"], REGISTRAR))
    assert registered["status"] == "REGISTERED"


# ---------------------------------------------------------------------------
# Corner: state_machines / certify_twice_second_returns_invalid_state
# ---------------------------------------------------------------------------
def test_certify_twice_second_returns_invalid_state(api):
    """PRD §3.2: "Signing advances the certification from `PENDING` to `CERTIFIED`
    and stamps `certified_at` with the current clock instant."
    PRD §2.9: "State — the target is in a state from which the requested
    transition is defined, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/certify_twice_second_returns_invalid_state
    """
    fac = create_facility(facility_type="FUNERAL_HOME", jurisdiction_code="CTY-35")
    cer = create_certifier(jurisdiction_code="CTY-35")
    ev = create_vital_event(
        fac["id"], event_type="DEATH", event_date="2026-03-01T00:00:00Z",
        jurisdiction_code="CTY-35", sex="MALE",
    )
    cert = create_certification(ev["id"], cer["id"], cause_of_death="X")
    certify(cert["id"], cer["id"])
    resp = api.certify_certification(cert["id"], make_medical_certifier_headers(cer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Corner: validations / duplicate_certification_returns_conflict
# ---------------------------------------------------------------------------
def test_duplicate_certification_returns_conflict(api):
    """PRD §3.2: "At most one certification may exist per vital event; a second
    create for an event that already has one is rejected with
    `ERR_DUPLICATE_CERTIFICATION`."

    Design: Corner/validations/duplicate_certification_returns_conflict
    """
    fac = create_facility(facility_type="FUNERAL_HOME", jurisdiction_code="CTY-45")
    cer = create_certifier(jurisdiction_code="CTY-45")
    ev = create_vital_event(
        fac["id"], event_type="DEATH", event_date="2026-03-01T00:00:00Z",
        jurisdiction_code="CTY-45", sex="MALE",
    )
    create_certification(ev["id"], cer["id"], cause_of_death="X")
    resp = api.create_certification(
        create_certification_payload(ev["id"], cer["id"], cause_of_death="Y",
                                     manner_of_death="ACCIDENT"),
        make_medical_certifier_headers(cer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CERTIFICATION)


# ---------------------------------------------------------------------------
# Corner: validations / certification_on_birth_returns_not_death_event
# ---------------------------------------------------------------------------
def test_certification_on_birth_returns_not_death_event(api):
    """PRD §3.2: "A certification may be opened only for an event whose
    `event_type` is `DEATH` or `FETAL_DEATH`; opening one against a birth is
    rejected with `ERR_NOT_DEATH_EVENT`."

    Design: Corner/validations/certification_on_birth_returns_not_death_event
    """
    fac = create_facility(jurisdiction_code="CTY-46")
    cer = create_certifier(jurisdiction_code="CTY-46")
    ev = create_vital_event(fac["id"], event_type="BIRTH", jurisdiction_code="CTY-46")
    resp = api.create_certification(
        create_certification_payload(ev["id"], cer["id"], cause_of_death="n/a"),
        make_medical_certifier_headers(cer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_DEATH_EVENT)


# ---------------------------------------------------------------------------
# Corner: validations / medical_amendment_missing_target_returns_target_required
# ---------------------------------------------------------------------------
def test_medical_amendment_missing_target_returns_target_required(api):
    """PRD §3.4: "A `MEDICAL` amendment corrects the cause-of-death certification
    and must supply the `target_certification_id` of the certification to amend; a
    `DEMOGRAPHIC` amendment corrects a record field and must omit it. Supplying a
    target on a demographic amendment, or omitting it on a medical one, is
    rejected with `ERR_AMENDMENT_TARGET_REQUIRED`."

    Design: Corner/validations/medical_amendment_missing_target_returns_target_required
    """
    fac, cer, ev, cert = setup_registered_death_event(jurisdiction_code="CTY-48")
    resp = api.create_amendment(
        {
            "vital_event_id": ev["id"], "amendment_type": "MEDICAL",
            "field_name": "cause_of_death", "new_value": "Z", "reason": "fix",
        },
        REGISTRAR,
    )
    validate_error(resp, ApiErrorId.ERR_AMENDMENT_TARGET_REQUIRED)


# ---------------------------------------------------------------------------
# Corner: endpoints / list_certifications_filtered_by_certifier_reverse_fk
# ---------------------------------------------------------------------------
def test_list_certifications_returns_certifier_certification(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/list_certifications_filtered_by_certifier_reverse_fk
    """
    fac = create_facility(facility_type="FUNERAL_HOME", jurisdiction_code="CTY-52")
    cer = create_certifier(jurisdiction_code="CTY-52")
    ev = create_vital_event(
        fac["id"], event_type="DEATH", event_date="2026-03-01T00:00:00Z",
        jurisdiction_code="CTY-52", sex="MALE",
    )
    cert = create_certification(ev["id"], cer["id"], cause_of_death="X")
    resp = api.list_certifications(REGISTRAR, params={"certifier_id": cer["id"]})
    data, meta = validate_paginated(resp)
    assert any(c["id"] == cert["id"] for c in data), "listing must contain the created certification"
