"""Building the chart: patients, practitioners, intake sections and the gate read."""

from test_helpers import (
    UNKNOWN_UUID,
    ApiErrorId,
    assert_intake_section,
    assert_patient,
    assert_same_instant,
    create_intake_section_payload,
    create_patient_payload,
    create_practitioner_payload,
    make_director_headers,
    make_patient_headers,
    read_patient,
    register_director,
    register_nd,
    register_patient,
    set_clock,
    submit_and_attest,
    submit_section,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN


def read_section(api, patient_id, section_id):
    """Read one section back through its patient's section list."""
    rows, _ = validate_paginated(
        api.list_intake_sections(patient_id, make_patient_headers(patient_id))
    )
    return next(row for row in rows if row["id"] == section_id)


def test_patient_registration_initialises_both_axes_and_the_open_gate(api):
    """PRD §3.1: "Every other patient attribute is server-owned at creation:
    `clinical_status` starts at `INTAKE`, `scope_review_status` at `NONE` with
    `scope_review_reason` and `scope_review_opened_by_user_id` both null,
    `clinical_write_gate` at `OPEN`, `red_flag_referral_open` at false, both
    `intake_booking_score` and `intake_protocol_score` at 0, and both
    `cash_charged_total_cents` and `cash_refunded_total_cents` at 0."
    PRD §2.4: "Almost every resource additionally carries an `updated_at`
    timestamp and an integer `version` that starts at 1 on creation and
    increments by exactly 1 on every mutation of that row"

    Design: Corner/entities/patient_creation_initialises_both_axes_and_the_open_gate
    """
    nd = register_nd(api)
    payload = create_patient_payload(nd["id"], full_name="Ada Reyes")
    response = api.create_patient(payload, ADMIN)
    patient = validate_success(response, 201)

    assert_patient(patient)
    assert patient["clinical_status"] == "INTAKE"
    assert patient["scope_review_status"] == "NONE"
    assert patient["scope_review_reason"] is None
    assert patient["scope_review_opened_by_user_id"] is None
    assert patient["clinical_write_gate"] == "OPEN"
    assert patient["red_flag_referral_open"] is False
    assert patient["intake_booking_score"] == 0
    assert patient["intake_protocol_score"] == 0
    assert patient["cash_charged_total_cents"] == 0
    assert patient["cash_refunded_total_cents"] == 0
    assert patient["version"] == 1


def test_reading_an_unknown_patient_id_returns_patient_not_found(api):
    """PRD §2.6: "Every id embedded in the request path resolves to a live row,
    checked strictly left to right, on every endpoint carrying a path parameter.
    The code is the entity-specific one where the domain declares one:
    `ERR_PATIENT_NOT_FOUND`, `ERR_PRACTITIONER_NOT_FOUND`,
    `ERR_PROTOCOL_NOT_FOUND`, `ERR_LAB_ORDER_NOT_FOUND`,
    `ERR_ENCOUNTER_NOT_FOUND` or `ERR_MEMBERSHIP_NOT_FOUND`; an unresolvable
    intake-section, protocol-item, dispensary-product, product-lot, dispense,
    message-thread, superbill or referral id yields `ERR_RESOURCE_NOT_FOUND`.
    All of these carry HTTP 404."

    Design: Corner/entities/patient_get_with_unknown_id_returns_patient_not_found
    """
    register_nd(api)
    response = api.get_patient(UNKNOWN_UUID, ADMIN)
    validate_error(response, ApiErrorId.ERR_PATIENT_NOT_FOUND.value, 404)


def test_patient_registration_without_state_code_is_a_payload_failure(api):
    """PRD §3.1: "Registering a patient captures `full_name`, `email`, the
    two-letter `state_code` of residence that drives telehealth licensure
    matching, and the `primary_practitioner_id` of the treating naturopathic
    doctor of record."
    PRD §2.6: "Every required input field for the endpoint is present, non-null
    and of the declared type; integers such as `quantity`, `duration_minutes`
    and `current_symptom_score` are positive where the domain demands it; and
    `scheduled_end` is strictly after `scheduled_start`. Any failure yields
    `ERR_VALIDATION` (400)."

    Design: Corner/entities/patient_creation_missing_required_state_code_returns_validation
    """
    nd = register_nd(api)
    payload = {
        "full_name": "Ada Reyes",
        "email": "ada-no-state@example.com",
        "primary_practitioner_id": nd["id"],
    }
    response = api.create_patient(payload, ADMIN)
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

    rows, meta = validate_paginated(api.list_patients(ADMIN))
    assert meta["total_count"] == 0, "A refused registration must not persist a Patient"


def test_telehealth_consent_defaults_to_false_when_omitted(api):
    """PRD §3.1: "Two optional fields matter enormously later:
    `telehealth_consent` defaults to false and gates every remote modality, and
    `medication_classes` is the array of prescription medication classes the
    patient reports, which is matched against each dispensary product's
    interaction profile."

    Design: Corner/entities/patient_telehealth_consent_defaults_to_false
    """
    nd = register_nd(api)
    payload = create_patient_payload(nd["id"])
    payload.pop("telehealth_consent", None)
    patient = validate_success(api.create_patient(payload, ADMIN), 201)

    assert patient["telehealth_consent"] is False


def test_practitioner_with_an_undeclared_credential_is_an_enum_failure(api):
    """PRD §3.1: "A `PracticeAdmin` records each practitioner's `full_name` and
    their `credential`, which is one of `ND`, `HEALTH_COACH`, `DISPENSARY_TECH`
    or `CLINICAL_DIRECTOR`."
    PRD §2.6: "Every supplied enum-typed field carries a declared member —
    `credential`, `section_type`, `tier`, `panel_code`, `funding_source`,
    `modality`, `outcome`, `action`, `severity` and the pricing hints among
    them. A value outside the declared set yields `ERR_INVALID_ENUM` (422)."

    Design: Corner/entities/practitioner_creation_with_invalid_credential_returns_invalid_enum
    """
    payload = create_practitioner_payload(
        full_name="Dr Nobody", credential="CHIROPRACTOR"
    )
    response = api.create_practitioner(payload, ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_ENUM.value, 422)


def test_patient_roster_paginates_and_narrows_by_primary_practitioner(api):
    """PRD §3.1: "The patient roster can be listed and narrowed by
    `primary_practitioner_id` and by `clinical_status`."
    PRD §2.3: "Successful list responses carry `limit`, `offset`, `total_count`
    and `has_more` in the `meta` object, where `total_count` is the number of
    rows matching the filter before pagination is applied and `has_more` is true
    when rows remain beyond the current page."

    Design: Corner/entities/patient_list_returns_pagination_envelope_and_filters_by_practitioner
    """
    nd = register_nd(api)
    patient_a = register_patient(api, nd["id"], full_name="Ada Reyes")
    patient_b = register_patient(api, nd["id"], full_name="Ben Cash")

    response = api.list_patients(
        ADMIN, params={"primary_practitioner_id": nd["id"], "limit": 1, "offset": 0}
    )
    rows, meta = validate_paginated(response)

    assert meta["total_count"] == 2, "total_count counts matches before pagination"
    assert meta["has_more"] is True
    assert meta["limit"] == 1 and meta["offset"] == 0
    assert len(rows) == 1
    assert rows[0]["id"] in {patient_a["id"], patient_b["id"]}


def test_intake_submission_ignores_client_supplied_server_owned_fields(api):
    """PRD §3.1: "On submission the section's `status` is `SUBMITTED`, its
    `submitted_at` is stamped with the logical clock, its `attested_at` and
    `expires_at` are cleared to null, and its `weight` is copied from the fixed
    scoring table: `CHIEF_COMPLAINT_TIMELINE` is worth 25, `SYSTEMS_REVIEW` 25,
    `DIET_LIFESTYLE` 15, `MEDICATIONS_SUPPLEMENTS` 25 and `FAMILY_HISTORY` 10,
    which is a hundred points across the five."
    PRD §3.1: "In the **booking variant**, an `ATTESTED` section contributes its
    full weight, a merely `SUBMITTED` section contributes half its weight with
    the fraction discarded — 25 becomes 12, 15 becomes 7, 10 becomes 5 — and an
    `EXPIRED` or entirely absent section contributes nothing."

    Design: Corner/entities/intake_section_server_owned_fields_input_ignored
    """
    nd = register_nd(api)
    patient = register_patient(api, nd["id"])
    payload = create_intake_section_payload(
        "CHIEF_COMPLAINT_TIMELINE", status="ATTESTED", weight=99
    )
    section = validate_success(
        api.create_intake_section(
            patient["id"], payload, make_patient_headers(patient["id"])
        ),
        201,
    )

    assert_intake_section(section)
    assert section["status"] == "SUBMITTED"
    assert section["weight"] == 25
    assert section["attested_at"] is None

    refreshed = read_patient(api, patient["id"])
    assert refreshed["intake_booking_score"] == 12
    assert refreshed["intake_protocol_score"] == 0


def test_attesting_an_already_attested_section_is_refused(api):
    """PRD §3.1: "Attestation takes a section from `SUBMITTED` to `ATTESTED`,
    stamps `attested_at` with the logical clock, sets `expires_at` to 180 days
    after that instant, recomputes both intake scores, and increments the
    patient's `version` by 1."
    PRD §2.6: "The addressed resource is in a state from which the requested
    transition is declared, on the relevant axis, on every state-transition
    endpoint — otherwise `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/attesting_an_already_attested_section_returns_invalid_state
    """
    nd = register_nd(api)
    patient = register_patient(api, nd["id"])
    section = submit_and_attest(api, patient["id"], "CHIEF_COMPLAINT_TIMELINE")
    assert_same_instant(
        section["expires_at"], "2026-10-28T00:00:00Z", "IntakeSection.expires_at"
    )

    response = api.attest_intake_section(
        section["id"], make_patient_headers(patient["id"])
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    rows, _ = validate_paginated(
        api.list_intake_sections(patient["id"], make_patient_headers(patient["id"]))
    )
    still = next(row for row in rows if row["id"] == section["id"])
    assert still["status"] == "ATTESTED"
    assert_same_instant(
        still["expires_at"], "2026-10-28T00:00:00Z", "IntakeSection.expires_at"
    )


def test_resubmitting_a_section_type_overwrites_the_attested_row(api):
    """PRD §3.1: "Submitting a section type that already exists for that patient
    does not create a second row — it overwrites the existing one and drives it
    back to `SUBMITTED` from wherever it was, whether that was `ATTESTED` or
    `EXPIRED`, clearing the attestation timestamps in both cases."
    PRD §3.1: "In the **protocol variant** there is no partial credit
    whatsoever: only `ATTESTED` sections contribute, at full weight, and
    everything else including `SUBMITTED` contributes nothing."

    Design: Corner/state_machines/intake_resubmission_returns_attested_section_to_submitted
    """
    nd = register_nd(api)
    patient = register_patient(api, nd["id"])
    section = submit_and_attest(api, patient["id"], "CHIEF_COMPLAINT_TIMELINE")

    again = validate_success(
        api.create_intake_section(
            patient["id"],
            create_intake_section_payload(
                "CHIEF_COMPLAINT_TIMELINE", payload_summary="fatigue, revised timeline"
            ),
            make_patient_headers(patient["id"]),
        ),
        201,
    )

    assert again["id"] == section["id"], "Re-submission overwrites the same row"
    assert again["status"] == "SUBMITTED"
    assert again["attested_at"] is None
    assert again["expires_at"] is None

    refreshed = read_patient(api, patient["id"])
    assert refreshed["intake_booking_score"] == 12
    assert refreshed["intake_protocol_score"] == 0

    rows, meta = validate_paginated(
        api.list_intake_sections(patient["id"], make_patient_headers(patient["id"]))
    )
    assert meta["total_count"] == 1 and len(rows) == 1


def test_expired_sections_contribute_nothing_and_close_the_booking_gate(api):
    """PRD §3.1: "Attestation is a signature with an expiry date: once the
    logical clock reaches or passes `expires_at` the section moves
    `ATTESTED → EXPIRED` and both scores are recomputed with that section
    contributing nothing."
    PRD §3.1: "Booking an encounter requires `intake_booking_score` to be at
    least 60, and issuing a protocol requires `intake_protocol_score` to be at
    least 85; both boundaries are inclusive, so a chart sitting exactly on the
    number passes."

    Design: Corner/calculations/expired_intake_sections_contribute_zero_to_both_scores
    """
    nd = register_nd(api)
    patient = register_patient(api, nd["id"])
    sections = [
        submit_and_attest(api, patient["id"], section_type)
        for section_type in ("CHIEF_COMPLAINT_TIMELINE", "SYSTEMS_REVIEW", "DIET_LIFESTYLE")
    ]

    set_clock(api, "2026-10-28T00:00:00Z")

    gate = validate_success(api.get_patient_gate(patient["id"], ADMIN))
    assert gate["intake_booking_score"] == 0
    assert gate["intake_protocol_score"] == 0

    rows, _ = validate_paginated(
        api.list_intake_sections(patient["id"], make_patient_headers(patient["id"]))
    )
    by_id = {row["id"]: row for row in rows}
    for section in sections:
        assert by_id[section["id"]]["status"] == "EXPIRED"

    booking = api.create_encounter(
        {
            "patient_id": patient["id"],
            "practitioner_id": nd["id"],
            "modality": "IN_PERSON",
            "scheduled_start": "2026-11-02T09:00:00Z",
            "scheduled_end": "2026-11-02T10:00:00Z",
        },
        make_patient_headers(patient["id"]),
    )
    validate_error(booking, ApiErrorId.ERR_INTAKE_INCOMPLETE.value, 422)


def test_gate_read_reports_every_input_of_the_freeze(api):
    """PRD §3.1: "It answers with the current `clinical_write_gate`, the current
    `scope_review_status`, the `red_flag_referral_open` flag, the
    `open_red_flag_referral_id` naming the referral holding the freeze when
    there is one, and both intake scores — and it materialises intake-section
    expiry before answering, so the numbers it returns are never stale."
    PRD §3.1: "Opening a review records the supplied text as
    `scope_review_reason`, records the acting `X-User-ID` as
    `scope_review_opened_by_user_id`, sets `clinical_write_gate` to
    `FROZEN_SCOPE_REVIEW`, sets `advancement_blocked` to true on every `ACTIVE`
    protocol of that patient, sets `titration_locked` to true on every `ACTIVE`
    or `HELD` line beneath those protocols, and increments the patient's
    `version` by 1."

    Design: Corner/endpoints/gate_computed_read_reports_every_input_of_the_freeze
    """
    nd = register_nd(api)
    director = register_director(api)
    patient = register_patient(api, nd["id"])
    submit_and_attest(api, patient["id"], "CHIEF_COMPLAINT_TIMELINE")

    validate_success(
        api.open_scope_review(
            patient["id"],
            {"reason": "supervision query"},
            make_director_headers(director["id"]),
        )
    )

    gate = validate_success(api.get_patient_gate(patient["id"], ADMIN))
    assert gate["clinical_write_gate"] == "FROZEN_SCOPE_REVIEW"
    assert gate["scope_review_status"] == "UNDER_REVIEW"
    assert gate["red_flag_referral_open"] is False
    assert gate["open_red_flag_referral_id"] is None
    assert gate["intake_booking_score"] == 25
    assert gate["intake_protocol_score"] == 25


def test_a_patient_cannot_attest_another_patients_section(api):
    """PRD §3.1: "Only the `Patient` may attest, and only their own sections —
    the acting `X-User-ID` must equal the section's `patient_id`."
    PRD §2.1: "Whenever the acting role is `Patient`, the `X-User-ID` must equal
    the `patient_id` that owns the addressed resource — the intake section's
    patient, the message thread's patient, the encounter's patient, the
    superbill's patient, or, for an adverse-reaction report, the patient behind
    the protocol that owns the addressed protocol line. A mismatch is refused
    with `ERR_OWNERSHIP_VIOLATION` and HTTP 403."

    Design: Corner/validations/patient_cannot_attest_another_patients_intake_section
    """
    nd = register_nd(api)
    patient_a = register_patient(api, nd["id"], full_name="Ada Reyes")
    patient_b = register_patient(api, nd["id"], full_name="Ben Cash")
    section = submit_section(api, patient_a["id"], "CHIEF_COMPLAINT_TIMELINE")

    response = api.attest_intake_section(
        section["id"], make_patient_headers(patient_b["id"])
    )
    validate_error(response, ApiErrorId.ERR_OWNERSHIP_VIOLATION.value, 403)

    owner_view = read_section(api, patient_a["id"], section["id"])
    assert owner_view["status"] == "SUBMITTED"
    assert read_patient(api, patient_a["id"])["intake_booking_score"] == 12
