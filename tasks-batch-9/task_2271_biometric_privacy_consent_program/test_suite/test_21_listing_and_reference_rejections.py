"""Paginated reads, malformed bodies and unresolvable references.

The list contract, the 400 for a missing required input, the 404 for an unknown row
and the 404 for an unknown parent.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    PRIVACY_OFFICER,
    SYSTEM_OPERATOR,
    ApiErrorId,
    assert_pagination,
    assert_program_state,
    create_asset,
    create_jurisdiction,
    create_program,
    jurisdiction_payload,
    read_program,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_asset_list_filters_by_status_and_paginates_in_creation_order(api):
    """`total_count` follows the filter, and `has_more` follows the offset.

    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and
    `has_more` inside the `meta` object of the envelope."

    PRD §2.3: "Unless a specific endpoint says otherwise, list results are ordered by
    `created_at` ascending."

    Three surfaces are inventoried and the first two are classified, so a
    `CLASSIFIED` filter with a page size of one yields two rows across two pages, in
    the order they were inventoried, and never the third.

    Design: Corner/entities/biometric_asset_listing_paginates_and_filters_by_status
    """
    program = create_program(api)
    jurisdiction = create_jurisdiction(api, program["id"])
    first = create_asset(
        api, program["id"], jurisdiction["id"], target_status="CLASSIFIED"
    )
    second = create_asset(
        api,
        program["id"],
        jurisdiction["id"],
        target_status="CLASSIFIED",
        system_category="ACCESS_CONTROL",
        modality="HAND_GEOMETRY",
        template_storage_location="door-vault-01",
    )
    third = create_asset(
        api,
        program["id"],
        jurisdiction["id"],
        system_category="SECURITY_CAMERA",
        modality="FACE_GEOMETRY",
        template_storage_location="cam-vault-01",
    )

    page_one_rows, page_one_meta = validate_paginated(
        api.list_assets(
            PRIVACY_OFFICER,
            {"program_id": program["id"], "status": "CLASSIFIED", "limit": 1, "offset": 0},
        )
    )
    assert_pagination(page_one_meta, total_count=2, has_more=True, limit=1, offset=0)
    assert [row["id"] for row in page_one_rows] == [first["id"]]

    page_two_rows, page_two_meta = validate_paginated(
        api.list_assets(
            PRIVACY_OFFICER,
            {"program_id": program["id"], "status": "CLASSIFIED", "limit": 1, "offset": 1},
        )
    )
    assert_pagination(page_two_meta, total_count=2, has_more=False, limit=1, offset=1)
    assert [row["id"] for row in page_two_rows] == [second["id"]]

    listed = {row["id"] for row in page_one_rows + page_two_rows}
    assert third["id"] not in listed, "the DISCOVERED surface is excluded by the status filter"


def test_reading_a_program_that_does_not_exist_reports_its_own_404(api):
    """An unknown but well-formed id is a not-found, never an empty success.

    PRD §2.11: "Each maps to its own 404: `ERR_PROGRAM_NOT_FOUND`,
    `ERR_JURISDICTION_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
    `ERR_POLICY_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`,
    `ERR_SUBJECT_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`, `ERR_ACCOMMODATION_NOT_FOUND`,
    `ERR_INCIDENT_NOT_FOUND` and `ERR_ASSESSMENT_NOT_FOUND`."

    Design: Corner/entities/get_program_with_unknown_id_not_found
    """
    program = create_program(api)

    response = api.get_program(NON_EXISTENT_UUID, SYSTEM_OPERATOR)

    validate_error(response, ApiErrorId.PROGRAM_NOT_FOUND)
    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]

    assert read_program(api, program["id"])["id"] == program["id"], "the real row is unaffected"


def test_a_state_profile_missing_a_required_input_is_a_malformed_request(api):
    """An omitted required field is rejected before anything else runs.

    PRD §2.5: "**Body well-formedness.** Required fields present; enum values members
    of their declared sets; integers non-negative where constrained; datetimes
    parseable as ISO 8601; arrays non-empty where required; `to_status` a member of
    the target entity's status enum; pagination within range."

    Registering a profile would normally bump the owning program's version, so the
    parent staying at version 1 shows the rejected create wrote nothing at all.

    Design: Corner/entities/jurisdiction_missing_required_field_returns_400
    """
    program = create_program(api)
    payload = jurisdiction_payload(program["id"])
    del payload["damages_model"]

    refused = api.create_jurisdiction(payload, SYSTEM_OPERATOR)

    validate_error(refused, ApiErrorId.INVALID_REQUEST)

    _rows, meta = validate_paginated(
        api.list_jurisdictions(SYSTEM_OPERATOR, {"program_id": program["id"]})
    )
    assert_pagination(meta, total_count=0, has_more=False, limit=10, offset=0)
    assert read_program(api, program["id"])["version"] == 1


def test_an_org_type_outside_its_enum_and_a_negative_ceiling_are_both_refused(api):
    """Both type constraints on a program registration are enforced.

    PRD §3.1: "Registration supplies the entity's legal name as `org_name`, an
    `org_type` of `EMPLOYER`, `RETAILER` or `HYBRID` describing whether biometrics
    are collected from workers, shoppers or both, and an `exposure_ceiling_cents`
    value: the board-approved maximum aggregate private-right-of-action exposure the
    program may carry across all of its final assessments. The ceiling must not be
    negative."

    Design: Corner/entities/program_invalid_enum_org_type_rejected
    """
    bad_enum = api.create_program(
        {"org_name": "Northline Retail Group", "org_type": "NONPROFIT", "exposure_ceiling_cents": 1093750},
        SYSTEM_OPERATOR,
    )
    validate_error(bad_enum, ApiErrorId.INVALID_REQUEST)

    negative_ceiling = api.create_program(
        {"org_name": "Northline Retail Group", "org_type": "HYBRID", "exposure_ceiling_cents": -1},
        SYSTEM_OPERATOR,
    )
    validate_error(negative_ceiling, ApiErrorId.INVALID_REQUEST)

    # Nothing was written by either attempt, so a fresh program is the first row.
    survivor = create_program(api)
    assert_program_state(survivor, posture="OPEN")
    assert survivor["version"] == 1


def test_a_state_profile_naming_an_unknown_program_reports_the_parents_404(api):
    """The unresolvable parent reference decides the error.

    PRD §2.11: "Requests are checked for referential existence before any business
    rule runs, and the checks proceed strictly left to right: first the identifier
    embedded in the URL path, then the foreign keys carried in the body, in the order
    they appear in the endpoint's input list — `program_id`, then `jurisdiction_id`,
    then `policy_id`, then `vendor_id`, then `asset_id`, then `data_subject_id`, then
    `incident_id`, and finally the members of `affected_asset_ids` in index order."

    Design: Corner/entities/jurisdiction_with_unknown_program_id_returns_404
    """
    program = create_program(api)

    refused = api.create_jurisdiction(jurisdiction_payload(NON_EXISTENT_UUID), SYSTEM_OPERATOR)

    validate_error(refused, ApiErrorId.PROGRAM_NOT_FOUND)

    _rows, meta = validate_paginated(
        api.list_jurisdictions(SYSTEM_OPERATOR, {"program_id": program["id"]})
    )
    assert_pagination(meta, total_count=0, has_more=False, limit=10, offset=0)
    assert validate_success(api.get_program(program["id"], SYSTEM_OPERATOR))["version"] == 1
