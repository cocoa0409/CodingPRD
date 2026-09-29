"""Entity read/write contracts: roster rows, licence defaults, derived experience
fields, immutable activity line items, and the not-found and well-formedness
answers the board owes on every entity identifier."""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    BOARD_LICENSING_OFFICER_HEADERS,
    BOARD_SECRETARY_HEADERS,
    assert_fields,
    assert_has_common_fields,
    assert_money_cents,
    assert_no_version_field,
    assert_pdh_value,
    assert_uuid,
    assert_version_is,
    constants,
    factories,
    fixtures,
    make_applicant_headers,
    make_firm_admin_headers,
    make_licensee_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_engineer_creation_returns_201_and_echoes_inputs(api):
    """PRD §3.1: "A `BoardSecretary` registers an engineer by supplying `full_name` — a non-empty string of at most 120 characters — `email`, which must contain an `@` character and must be unique across the roster"

    Design: Corner/entities/engineer_created_with_all_required_fields_returns_201
    """
    payload = factories.engineer_payload(
        full_name="Ivo Karlsen",
        home_jurisdiction="OR",
        ncees_record_id="NCEES-770001",
    )

    response = api.create_engineer(payload, BOARD_SECRETARY_HEADERS)

    engineer = validate_success(response, 201)
    assert response.json()["response_type"] == "object"
    assert_fields(
        engineer,
        full_name="Ivo Karlsen",
        email=payload["email"],
        home_jurisdiction="OR",
        ncees_record_id="NCEES-770001",
    )
    assert_has_common_fields(engineer)
    assert_uuid(engineer["id"])
    assert_version_is(engineer, 1)


def test_new_engineer_holds_no_active_license_number_and_no_open_cases(api):
    """PRD §3.1: "`active_license_number` mirrors the `license_number` of whichever licence held by that engineer currently sits in `ACTIVE`, and is `null` when the engineer holds none"

    Design: Corner/entities/engineer_created_with_all_required_fields_returns_201
    """
    created = fixtures.create_engineer(api, full_name="Ivo Karlsen", home_jurisdiction="OR")

    engineer = validate_success(api.get_engineer(created["id"], BOARD_SECRETARY_HEADERS), 200)

    assert engineer["active_license_number"] is None
    assert engineer["open_case_count"] == 0


def test_engineer_read_returns_the_persisted_row(api):
    """PRD §3.1: "The roster is readable one row at a time by every role in the system, and as a paginated list — narrowable by `home_jurisdiction` or `email` — by the four board roles."

    Design: Corner/entities/engineer_retrieval_by_id_returns_stored_row
    """
    created = fixtures.create_engineer(api, full_name="Ivo Karlsen", home_jurisdiction="OR")

    response = api.get_engineer(created["id"], BOARD_SECRETARY_HEADERS)

    engineer = validate_success(response, 200)
    body = response.json()
    assert body["response_type"] == "object"
    assert_fields(
        engineer,
        id=created["id"],
        full_name="Ivo Karlsen",
        email=created["email"],
        home_jurisdiction="OR",
    )


def test_engineer_list_pages_with_total_count_and_has_more(api):
    """PRD §2.3: "The `meta` block of a list response carries `limit` and `offset` echoing the effective values used, `total_count` giving the number of rows that match the filter before the window is applied, and `has_more` set true when rows remain beyond the current window."

    Design: Corner/entities/engineers_listing_paginates_with_total_count_and_has_more
    """
    for name in ("Page One", "Page Two", "Page Three"):
        fixtures.create_engineer(api, full_name=name, home_jurisdiction="OR")

    first_page, first_meta = validate_paginated(
        api.list_engineers(
            BOARD_SECRETARY_HEADERS,
            params={"home_jurisdiction": "OR", "limit": 2, "offset": 0},
        )
    )
    second_page, second_meta = validate_paginated(
        api.list_engineers(
            BOARD_SECRETARY_HEADERS,
            params={"home_jurisdiction": "OR", "limit": 2, "offset": 2},
        )
    )

    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_meta["offset"] == 2


def test_unknown_license_id_reports_license_not_found(api):
    """PRD §3.1: "A licence identifier — whether it arrives as `license_id`, `sealing_license_id`, `responsible_charge_license_id` or `respondent_license_id` — that matches no register row yields `ERR_LICENSE_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/license_get_unknown_id_returns_license_not_found
    """
    response = api.get_license(NON_EXISTENT_UUID, BOARD_LICENSING_OFFICER_HEADERS)

    validate_error(response, "ERR_LICENSE_NOT_FOUND")
    assert response.json()["response_type"] == "error"


def test_application_without_pathway_is_rejected_as_malformed(api):
    """PRD §2.7: "Request well-formedness — `ERR_INVALID_REQUEST`, 400. Every required input present; every enum value a declared member; every number inside its declared range; every ISO 8601 datetime parseable"

    Design: Corner/entities/application_create_missing_pathway_rejected
    """
    engineer = fixtures.create_engineer(api, full_name="Mona Silt", home_jurisdiction="OR")
    headers = make_applicant_headers(engineer["id"])
    payload = factories.application_payload(engineer["id"])
    del payload["pathway"]

    response = api.create_application(payload, headers)

    validate_error(response, "ERR_INVALID_REQUEST")
    items, meta = validate_paginated(
        api.list_applications(headers, params={"engineer_id": engineer["id"]})
    )
    assert meta["total_count"] == 0
    assert items == []


def test_license_pdh_requirement_defaults_to_thirty(api):
    """PRD §3.1: "optionally `pdh_requirement` — the professional development hours the holder owes for the current period, a number at least 0 carried to at most one decimal place, defaulting to 30 when omitted"

    Design: Corner/entities/license_pdh_requirement_defaults_to_thirty
    """
    engineer = fixtures.create_engineer(api, full_name="Default Holder", home_jurisdiction="OR")
    payload = factories.license_payload(engineer["id"])
    assert "pdh_requirement" not in payload

    response = api.create_license(payload, BOARD_LICENSING_OFFICER_HEADERS)

    license_ = validate_success(response, 201)
    assert_pdh_value(license_["pdh_requirement"], constants.DEFAULT_PDH_REQUIREMENT)
    stored = validate_success(
        api.get_license(license_["id"], BOARD_LICENSING_OFFICER_HEADERS), 200
    )
    assert_pdh_value(stored["pdh_requirement"], 30)


def test_license_pdh_requirement_honours_the_supplied_value(api):
    """PRD §3.1: "optionally `pdh_requirement` — the professional development hours the holder owes for the current period, a number at least 0 carried to at most one decimal place, defaulting to 30 when omitted"

    Design: Corner/entities/license_pdh_requirement_defaults_to_thirty
    """
    engineer = fixtures.create_engineer(api, full_name="Explicit Holder", home_jurisdiction="OR")

    response = api.create_license(
        factories.license_payload(engineer["id"], pdh_requirement=45),
        BOARD_LICENSING_OFFICER_HEADERS,
    )

    license_ = validate_success(response, 201)
    assert_pdh_value(license_["pdh_requirement"], 45)
    stored = validate_success(
        api.get_license(license_["id"], BOARD_LICENSING_OFFICER_HEADERS), 200
    )
    assert_pdh_value(stored["pdh_requirement"], 45)


def test_experience_record_derives_span_multiplier_and_zero_credit(api):
    """PRD §3.3: "`raw_months` is the inclusive span of the claimed period: twelve times the difference in years between the end and start months, plus the difference in months, plus one — so January through June is six months, not five."

    Design: Corner/entities/experience_record_computed_credit_fields_client_input_ignored
    """
    engineer = fixtures.create_engineer(api, full_name="Cy Ranfield", home_jurisdiction="OR")
    application = fixtures.create_application(api, engineer["id"], pathway="STANDARD_EXAM")
    applicant = make_applicant_headers(engineer["id"])

    response = api.create_experience_record(
        application["id"],
        factories.experience_record_payload(
            employer_name="Ranfield Design",
            position_title="Junior Engineer",
            period_start_month="2019-01",
            period_end_month="2019-12",
            responsibility_level="SUBORDINATE",
            post_degree=True,
            raw_months=999,
            credit_multiplier=9.99,
            credited_months=999,
        ),
        applicant,
    )

    record = validate_success(response, 201)
    assert record["raw_months"] == 12
    assert record["credit_multiplier"] == pytest.approx(0.5, abs=1e-9)
    assert record["credited_months"] == 0
    assert record["verification_status"] == "UNVERIFIED"

    stored = validate_success(api.get_experience_record(record["id"], applicant), 200)
    assert stored["raw_months"] == 12
    assert stored["credited_months"] == 0

    # Twelve raw months at 0.50 truncate to six self-reported months, and the
    # single added block prices the verification charge at 2,500 cents on top of
    # the 25,000-cent examination base.
    refreshed = validate_success(api.get_application(application["id"], applicant), 200)
    assert refreshed["provisional_experience_months"] == 6
    assert_money_cents(refreshed["fee_assessment_cents"], 27500)


def test_engineer_identity_and_timestamps_are_server_generated(api):
    """PRD §2.4: "Every resource this API mints carries an `id` that is a server-generated UUID. Identifiers are never prefixed by type, never client-supplied, and never reused."

    Design: Corner/entities/engineer_id_and_timestamps_client_input_ignored
    """
    payload = factories.engineer_payload(full_name="Spoof Attempt", home_jurisdiction="WA")
    payload["id"] = "deadbeef"
    payload["version"] = 99
    payload["created_at"] = "1999-01-01T00:00:00Z"

    response = api.create_engineer(payload, BOARD_SECRETARY_HEADERS)

    engineer = validate_success(response, 201)
    assert engineer["id"] != "deadbeef"
    assert_uuid(engineer["id"])
    assert_version_is(engineer, 1)
    assert engineer["created_at"] == "2026-08-01T00:00:00.000Z"
    assert engineer["updated_at"] == "2026-08-01T00:00:00.000Z"


def test_application_with_undeclared_pathway_enum_is_rejected(api):
    """PRD §2.7: "Every required input present; every enum value a declared member"

    Design: Corner/entities/application_invalid_pathway_enum_rejected
    """
    engineer = fixtures.create_engineer(api, full_name="Enum Prober", home_jurisdiction="OR")
    headers = make_applicant_headers(engineer["id"])

    response = api.create_application(
        factories.application_payload(engineer["id"], pathway="RECIPROCITY"), headers
    )

    validate_error(response, "ERR_INVALID_REQUEST")
    items, meta = validate_paginated(
        api.list_applications(headers, params={"engineer_id": engineer["id"]})
    )
    assert meta["total_count"] == 0
    assert items == []


def test_pdh_record_read_omits_version_and_updated_at(api):
    """PRD §2.4: "A professional-development-hour line item is immutable once filed: it carries `id` and `created_at` only. Both `updated_at` and `version` are absent from a `PDHRecord` representation, and there is no endpoint that edits one."

    Design: Corner/entities/pdh_record_immutable_exposes_no_version_field
    """
    setup = fixtures.setup_cpc_report(
        api, report_overrides={"self_certified_pdh": 12}, engineer_overrides={"full_name": "Nell Auber"}
    )
    engineer_id = setup["engineer"]["id"]
    filed = fixtures.add_pdh_record(
        api,
        setup["report"]["id"],
        engineer_id,
        activity_type="COURSE",
        pdh_hours=12,
        completed_on="2027-02-02",
    )

    response = api.get_pdh_record(filed["id"], make_licensee_headers(engineer_id))

    record = validate_success(response, 200)
    assert record["id"] == filed["id"]
    assert record["created_at"] == "2026-08-01T00:00:00.000Z"
    assert_no_version_field(record)
    assert record["documentation_status"] == "NONE"
    assert_pdh_value(record["pdh_hours"], 12)


def test_experience_record_under_unknown_application_reports_application_not_found(api):
    """PRD §3.2: "An `application_id` matching no file yields `ERR_APPLICATION_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/experience_record_requires_existing_parent_application
    """
    engineer = fixtures.create_engineer(api, full_name="Orphan Filer", home_jurisdiction="OR")

    response = api.create_experience_record(
        NON_EXISTENT_UUID,
        factories.experience_record_payload(
            employer_name="Nowhere Civil",
            position_title="Engineer",
            period_start_month="2019-01",
            period_end_month="2019-12",
            responsibility_level="RESPONSIBLE_CHARGE",
            post_degree=True,
        ),
        make_applicant_headers(engineer["id"]),
    )

    error = validate_error(response, "ERR_APPLICATION_NOT_FOUND")
    assert error["error_id"] != "ERR_EXPERIENCE_RECORD_NOT_FOUND"


def test_plan_submission_with_unknown_firm_reports_firm_registration_not_found(api):
    """PRD §2.7: "Body foreign-key existence — the matching per-entity not-found code at HTTP 404, resolved in the field order the endpoint declares its inputs."

    Design: Corner/entities/plan_submission_body_fk_unknown_firm_not_found
    """
    response = api.create_plan_submission(
        factories.plan_submission_payload(
            NON_EXISTENT_UUID, project_name="Ghost Tower", sheet_count=2
        ),
        make_firm_admin_headers(NON_EXISTENT_UUID),
    )

    validate_error(response, "ERR_FIRM_REGISTRATION_NOT_FOUND")
    items, meta = validate_paginated(api.list_plan_submissions(BOARD_LICENSING_OFFICER_HEADERS))
    assert meta["total_count"] == 0
    assert items == []
