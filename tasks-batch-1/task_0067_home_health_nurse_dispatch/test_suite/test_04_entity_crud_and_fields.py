"""Corner: entity creation, retrieval, defaults, computed fields, listing,
not-found, required fields (PRD §2-§3). Queue B 'entities' section.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import clinician_payload, patient_payload
from test_helpers.fixtures import (
    INTAKE,
    SCHEDULER,
    setup_active_episode,
    setup_draft_episode,
)

WOUND_RATE = {
    "clinical_group": "WOUND", "base_30day_rate": 2000.00,
    "functional_weight_low": 0.95, "functional_weight_medium": 1.00,
    "functional_weight_high": 1.05, "lupa_threshold": 5,
}
WOUND_OASIS = {"clinical_group": "WOUND", "functional_level": "HIGH", "comorbidity_count": 2}


def test_create_patient_returns_201_active(api):
    """PRD §3.1: "A newly created patient begins life with status of ACTIVE."

    Design: Corner/entities/create_patient_returns_201_with_fields
    """
    resp = api.create_patient(patient_payload(full_name="Jane Doe"), INTAKE)
    patient = validate_success(resp, 201)
    assert patient["status"] == "ACTIVE"
    assert patient["full_name"] == "Jane Doe"


def test_get_patient_returns_stored_data(api):
    """PRD §3.1: "An IntakeCoordinator registers a patient by supplying the
    patient's full_name, a medicare_id, a residential home_zip, and the residence
    coordinates home_lat and home_lon."

    Design: Corner/entities/get_patient_returns_stored_data
    """
    created = validate_success(api.create_patient(patient_payload(medicare_id="MED-STORED-2"), INTAKE), 201)
    fetched = validate_success(api.get_patient(created["id"], INTAKE))
    assert fetched["medicare_id"] == "MED-STORED-2"


def test_get_patient_not_found(api):
    """PRD §2.5: "the first segment whose referenced resource does not exist
    causes the request to fail immediately with ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_patient_not_found
    """
    resp = api.get_patient(NON_EXISTENT_UUID, INTAKE)
    validate_error(resp, "ERR_NOT_FOUND", 404)


def test_create_patient_missing_medicare_id_rejected(api):
    """PRD §3.1: "The medicare_id must be non-empty and unique across all
    patients, and home_zip must consist of exactly five digits; violations of
    body shape, type, or these constraints are rejected with ERR_VALIDATION
    (HTTP 400)."

    Design: Corner/entities/create_patient_missing_required_field
    """
    body = patient_payload()
    body.pop("medicare_id")
    resp = api.create_patient(body, INTAKE)
    validate_error(resp, "ERR_VALIDATION", 400)


def test_clinician_license_active_defaults_true(api):
    """PRD §3.1: "a license_active flag that defaults to true".

    Design: Corner/entities/clinician_license_active_default_true
    """
    body = clinician_payload()
    body.pop("license_active")
    clinician = validate_success(api.create_clinician(body, SCHEDULER), 201)
    assert clinician["license_active"] is True


def test_episode_id_is_uuid_status_draft_version_1(api):
    """PRD §2.4: "Every resource is assigned an id that is a server-minted UUID
    carrying no type prefix." PRD §3.2: "leaves the episode in DRAFT status."
    PRD §2.4: "The version starts at 1 on creation".

    Design: Corner/entities/episode_id_is_uuid_with_no_prefix
    """
    base = setup_draft_episode(api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS)
    ep = base["episode"]
    assert is_valid_uuid(ep["id"])
    assert ep["status"] == "DRAFT"
    assert ep["version"] == 1


def test_oasis_invalid_enum_assessment_type(api):
    """PRD §3.1: "an assessment_type of either START_OF_CARE or RECERTIFICATION".
    PRD §3.1: "violations of body shape, type, or these constraints are rejected
    with ERR_VALIDATION (HTTP 400)."

    Design: Corner/entities/oasis_invalid_enum_assessment_type
    """
    patient = validate_success(api.create_patient(patient_payload(), INTAKE), 201)
    clinician = validate_success(api.create_clinician(clinician_payload(), SCHEDULER), 201)
    resp = api.create_oasis({
        "patient_id": patient["id"], "clinician_id": clinician["id"],
        "assessment_type": "RESUMPTION", "assessment_date": "2026-02-01T08:00:00Z",
        "clinical_group": "WOUND", "functional_level": "HIGH", "comorbidity_count": 2,
    }, INTAKE)
    validate_error(resp, "ERR_VALIDATION", 400)


def test_episode_computed_payments_initialize_zero(api):
    """PRD §3.3: "The provisional payment, stored on the episode as
    provisional_payment, is a forward-looking estimate, recomputed on episode
    activation". PRD §3.8: "final_payment (which is zero until finalize)."
    (A DRAFT episode, pre-activation, carries both at 0.)

    Design: Corner/entities/episode_computed_payments_initialize_zero
    """
    base = setup_draft_episode(api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS)
    ep = validate_success(api.get_episode(base["episode"]["id"], INTAKE))
    assert ep["provisional_payment"] == 0
    assert ep["final_payment"] == 0


def test_episode_event_log_records_activated(api):
    """PRD §3.2: "On success, activation appends an ACTIVATED audit event".
    PRD §3.9: "Every materially significant change appends an EpisodeEvent to the
    episode's immutable log."

    Design: Corner/entities/episode_event_log_immutable_no_version
    """
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 6},
    )
    events, _ = validate_paginated(api.list_episode_events(base["episode"]["id"], INTAKE))
    assert any(e["event_type"] == "ACTIVATED" for e in events)


def test_episode_requires_existing_patient(api):
    """PRD §2.5: "The same existence rule covers any resource referenced in the
    request body." PRD §2.5: "the first segment whose referenced resource does
    not exist causes the request to fail immediately with ERR_NOT_FOUND (HTTP
    404)."

    Design: Corner/entities/episode_requires_existing_patient_parent
    """
    patient = validate_success(api.create_patient(patient_payload(), INTAKE), 201)
    clinician = validate_success(api.create_clinician(clinician_payload(), SCHEDULER), 201)
    oasis = validate_success(api.create_oasis({
        "patient_id": patient["id"], "clinician_id": clinician["id"],
        "assessment_type": "START_OF_CARE", "assessment_date": "2026-02-01T08:00:00Z",
        "clinical_group": "WOUND", "functional_level": "HIGH", "comorbidity_count": 2,
    }, INTAKE), 201)
    resp = api.create_episode({"patient_id": NON_EXISTENT_UUID, "soc_oasis_id": oasis["id"]}, INTAKE)
    validate_error(resp, "ERR_NOT_FOUND", 404)


def test_list_patient_episodes_pagination_envelope(api):
    """PRD §2.3: "Each paginated response surfaces its pagination state inside the
    meta object through four fields: limit, offset, total_count (the total number
    of records matching the query before pagination), and has_more (a boolean
    indicating whether records remain beyond the current page)."

    Design: Corner/entities/list_episodes_pagination_envelope
    """
    base = setup_draft_episode(api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS)
    rows, meta = validate_paginated(
        api.list_patient_episodes(base["patient"]["id"], INTAKE, params={"limit": 10, "offset": 0}))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
