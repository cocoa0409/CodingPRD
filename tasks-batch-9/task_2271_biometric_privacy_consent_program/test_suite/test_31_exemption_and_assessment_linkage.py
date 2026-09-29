"""An action gated on a computed field, and an optional association that is real.

Exemption offered to one incident and refused to its twin, and an assessment that
carries — and can be filtered by — the incident that prompted it.
"""

from test_helpers import (
    COMPLIANCE_APPROVER,
    NON_EXISTENT_UUID,
    PRIVACY_OFFICER,
    ApiErrorId,
    assert_is_null,
    assert_pagination,
    assessed_incident,
    create_asset,
    create_incident,
    create_jurisdiction,
    create_program,
    current_jurisdiction_version,
    read_incident,
    validate_error,
    validate_paginated,
    validate_success,
)

EXEMPTION_BASIS = "templates were encrypted at rest"


def test_exemption_is_offered_to_the_fingerprint_case_and_refused_to_the_face_case(api):
    """The same exposure size is exemptible on one modality and not the other.

    PRD §3.8: "The tier is `TIER_1` when either of two conditions holds: at least one
    affected collection point has a `modality` of `FACE_GEOMETRY` or `IRIS`, or
    `exposed_subject_count` is at least 500."

    PRD §3.8: "Exemption is available only at `TIER_2`; claiming it on a `TIER_1` case is
    rejected with `ERR_EXEMPTION_NOT_AVAILABLE`."

    PRD §3.8: "A written `exemption_basis` must be present in the request body, else
    `ERR_INVALID_REQUEST`, and it is stored on the case."

    Ten exposed individuals is far below the mass-exposure threshold, so the tier turns
    purely on the modality, and the exemption turns purely on the tier. The same request
    body — identical basis, identical approver — is refused on one case and honoured on
    the other, and neither call touches the containment dimension.

    Design: Corner/endpoints/notification_exemption_is_available_only_to_tier_2_incidents
    """
    program = create_program(api)
    jurisdiction = create_jurisdiction(api, program["id"])
    camera = create_asset(
        api,
        program["id"],
        jurisdiction["id"],
        system_category="SECURITY_CAMERA",
        modality="FACE_GEOMETRY",
        template_storage_location="cam-vault-01",
    )
    reader = create_asset(api, program["id"], jurisdiction["id"])

    face_case = assessed_incident(
        api,
        program["id"],
        [camera["id"]],
        exposure_vector="INSIDER_MISUSE",
        description="ten face templates viewed by an unauthorised operator",
        exposed_subject_count=10,
        translation_locale_count=0,
    )
    fingerprint_case = assessed_incident(
        api,
        program["id"],
        [reader["id"]],
        exposure_vector="INSIDER_MISUSE",
        description="ten fingerprint templates viewed by an unauthorised operator",
        exposed_subject_count=10,
        translation_locale_count=0,
    )
    assert face_case["heightened_tier"] == "TIER_1"
    assert fingerprint_case["heightened_tier"] == "TIER_2"

    refused = api.transition_incident_notification(
        face_case["id"],
        {"to_status": "EXEMPT", "exemption_basis": EXEMPTION_BASIS},
        COMPLIANCE_APPROVER,
    )

    validate_error(refused, ApiErrorId.EXEMPTION_NOT_AVAILABLE)
    unchanged = read_incident(api, face_case["id"])
    assert unchanged["notification_status"] == "ASSESSED"
    assert_is_null(unchanged["exemption_basis"], "exemption_basis after a refused exemption")
    assert unchanged["containment_status"] == "DETECTED"

    exempted = validate_success(
        api.transition_incident_notification(
            fingerprint_case["id"],
            {"to_status": "EXEMPT", "exemption_basis": EXEMPTION_BASIS},
            COMPLIANCE_APPROVER,
        )
    )
    assert exempted["notification_status"] == "EXEMPT"
    assert exempted["exemption_basis"] == EXEMPTION_BASIS
    assert exempted["containment_status"] == "DETECTED"


def test_an_estimate_carries_its_source_incident_and_the_list_filters_on_it(api):
    """An unknown incident is refused, a known one is echoed, and the filter isolates it.

    PRD §3.9: "A `PrivacyOfficer` drafts an **exposure assessment** for one `program_id`
    and one `jurisdiction_id`, optionally linking it to the `incident_id` that prompted
    it (null for a routine posture assessment), choosing a `variant` of
    `PER_VIOLATION_STACKED` or `PER_SUBJECT_CAPPED`, and pinning
    `expected_jurisdiction_version` per §2.8."

    PRD §2.11: "The response reports the first reference that fails to resolve, and
    nothing further is evaluated."

    PRD §2.3: "Exposure assessments accept `program_id`, `jurisdiction_id`, `incident_id`
    and `status`."

    The refused draft resolves no reference and therefore performs no write, so the
    version pin it was rejected with is still current for the very next call — which is
    what lets the linked draft reuse it. The routine draft that follows carries no
    incident at all, and the filtered list returns the linked assessment alone.

    Design: Corner/endpoints/exposure_assessment_links_to_its_source_incident_and_is_filterable_by_it
    """
    program = create_program(api)
    jurisdiction = create_jurisdiction(api, program["id"])
    point = create_asset(api, program["id"], jurisdiction["id"])
    incident = create_incident(
        api,
        program["id"],
        [point["id"]],
        exposure_vector="LOST_DEVICE",
        description="handheld reader lost in transit",
        exposed_subject_count=4,
        translation_locale_count=0,
    )
    pinned_version = current_jurisdiction_version(api, jurisdiction["id"])

    unknown_link = api.create_exposure_assessment(
        {
            "program_id": program["id"],
            "jurisdiction_id": jurisdiction["id"],
            "variant": "PER_VIOLATION_STACKED",
            "expected_jurisdiction_version": pinned_version,
            "incident_id": NON_EXISTENT_UUID,
        },
        PRIVACY_OFFICER,
    )
    validate_error(unknown_link, ApiErrorId.INCIDENT_NOT_FOUND)
    assert current_jurisdiction_version(api, jurisdiction["id"]) == pinned_version

    linked = validate_success(
        api.create_exposure_assessment(
            {
                "program_id": program["id"],
                "jurisdiction_id": jurisdiction["id"],
                "variant": "PER_VIOLATION_STACKED",
                "expected_jurisdiction_version": pinned_version,
                "incident_id": incident["id"],
            },
            PRIVACY_OFFICER,
        ),
        expected_status=201,
    )
    assert linked["incident_id"] == incident["id"]

    routine = validate_success(
        api.create_exposure_assessment(
            {
                "program_id": program["id"],
                "jurisdiction_id": jurisdiction["id"],
                "variant": "PER_SUBJECT_CAPPED",
                "expected_jurisdiction_version": current_jurisdiction_version(
                    api, jurisdiction["id"]
                ),
            },
            PRIVACY_OFFICER,
        ),
        expected_status=201,
    )
    assert_is_null(routine["incident_id"], "incident_id on a routine assessment")

    rows, meta = validate_paginated(
        api.list_exposure_assessments(
            COMPLIANCE_APPROVER, {"program_id": program["id"], "incident_id": incident["id"]}
        )
    )
    assert_pagination(meta, total_count=1, has_more=False, limit=10, offset=0)
    assert [row["id"] for row in rows] == [linked["id"]]
    assert routine["id"] not in {row["id"] for row in rows}
