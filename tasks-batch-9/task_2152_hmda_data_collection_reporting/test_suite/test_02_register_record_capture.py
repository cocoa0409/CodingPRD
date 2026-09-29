"""Opening a register record: required inputs, defaults, the completeness
calculation, uniqueness of the loan identifier and the institution counters."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_application,
    assert_register_accounting_identity,
    create_application,
    create_application_payload,
    create_institution,
    create_second_institution,
    make_loan_officer_headers,
    next_uli,
    patch_application,
    read_application,
    read_institution,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_reading_an_unknown_register_record_is_a_not_found(api):
    """PRD §2.6: "A request naming an institution that does not exist yields
    `ERR_INSTITUTION_NOT_FOUND`; an unknown register record yields
    `ERR_APPLICATION_NOT_FOUND`; and the same pattern holds for
    `ERR_DEMOGRAPHIC_ENTRY_NOT_FOUND`, `ERR_GEOCODE_ASSIGNMENT_NOT_FOUND`,
    `ERR_CENSUS_TRACT_NOT_FOUND`, `ERR_EDIT_RUN_NOT_FOUND`,
    `ERR_EDIT_EXCEPTION_NOT_FOUND`, `ERR_SUBMISSION_NOT_FOUND`, and
    `ERR_AUDIT_SAMPLE_NOT_FOUND`. All of these carry HTTP 404."

    Design: Corner/entities/application_get_with_unknown_id_returns_not_found
    """
    validate_error(
        api.get_application(UNKNOWN_ID, TEST_USERS["compliance_analyst_headers"]),
        ApiErrorId.ERR_APPLICATION_NOT_FOUND.value,
    )


def test_opening_a_record_without_a_lien_status_is_malformed(api):
    """PRD §3.2: "A register record is opened by a `LoanOfficer`, who names the
    owning bank with an `institution_id` and supplies the record's `uli` (its
    Universal Loan Identifier), the `application_date` on which the application
    was received, the `application_channel` through which it arrived — one of
    `FACE_TO_FACE`, `MAIL`, `INTERNET`, or `TELEPHONE` — and the four
    classification fields `loan_type` (`CONVENTIONAL`, `FHA`, `VA`, or `RHS_FSA`),
    `loan_purpose` (`HOME_PURCHASE`, `HOME_IMPROVEMENT`, `REFINANCING`,
    `CASH_OUT_REFINANCING`, or `OTHER_PURPOSE`), `occupancy_type` (`PRINCIPAL`,
    `SECOND`, or `INVESTMENT`), and `lien_status` (`FIRST_LIEN` or
    `SUBORDINATE_LIEN`), plus `loan_amount_cents`, which must be at least 1."
    PRD §2.9: "Body shape: every required input named in §4 is present, every enum
    value is a member of its declared set, integers and numbers are of the declared
    type and within any stated range, arrays are arrays, ISO 8601 datetimes parse,
    and `limit` and `offset` lie inside the pagination bounds —
    `ERR_INVALID_REQUEST`, 400."

    Design: Corner/entities/application_create_missing_required_field_returns_invalid_request
    """
    institution = create_institution()
    payload = create_application_payload(institution["id"])
    payload.pop("lien_status")
    payload.pop("income_thousands")

    validate_error(
        api.create_application(payload, make_loan_officer_headers()),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )
    assert read_institution(institution["id"])["total_application_count"] == 0


def test_optional_flags_default_when_omitted(api):
    """PRD §3.2: "Optionally the officer may already know `income_thousands`, may
    mark `business_or_commercial_purpose` or `open_end_line_of_credit` (both
    default false), and may declare `supersedes_application_id` when this row is a
    corrected replacement for an earlier register record."
    PRD §3.5: "`denial_reason_codes` is an array whose members are drawn from
    `DEBT_TO_INCOME`, `EMPLOYMENT_HISTORY`, `CREDIT_HISTORY`, `COLLATERAL`,
    `INSUFFICIENT_CASH`, `UNVERIFIABLE_INFO`, `INCOMPLETE_APPLICATION`,
    `MORTGAGE_INSURANCE_DENIED`, and `OTHER`, and it defaults to an empty array on
    a newly opened record."

    Design: Corner/entities/application_defaults_applied_when_optional_flags_omitted
    """
    institution = create_institution()
    payload = create_application_payload(institution["id"])
    payload.pop("income_thousands")

    data = validate_success(api.create_application(payload, make_loan_officer_headers()), 201)
    assert_application(data)
    assert data["business_or_commercial_purpose"] is False
    assert data["open_end_line_of_credit"] is False
    assert data["denial_reason_codes"] == []
    assert data["lar_status"] == "PENDING_FIELDS"
    assert data["exclusion_reason"] == "NOT_EXCLUDED"
    assert data["stage"] == "INTAKE"


def test_field_counts_reflect_the_applicable_set_before_any_action(api):
    """PRD §3.2: "Ten fields are always applicable: `uli`, `application_date`,
    `application_channel`, `loan_type`, `loan_purpose`, `occupancy_type`,
    `lien_status`, `loan_amount_cents`, `action_taken`, and `action_taken_date`.
    If the owning institution is **not** partially exempt, `income_thousands`
    joins the applicable set, and three further conditional additions apply on top
    of it: when `action_taken` reads `ORIGINATED`, both `rate_spread` and
    `purchaser_type` become applicable; when `action_taken` reads `PURCHASED_LOAN`,
    `purchaser_type` becomes applicable; and when `action_taken` reads `DENIED`,
    `denial_reason_codes` becomes applicable."
    PRD §3.2: "`applicable_field_count` is the size of that set and
    `captured_field_count` is the number of its members whose value is currently
    present — non-null, and for array-typed fields non-empty."

    Design: Corner/entities/application_computed_field_counts_reflect_applicable_set
    """
    institution = create_institution()

    data = validate_success(
        api.create_application(
            create_application_payload(institution["id"], income_thousands=120),
            make_loan_officer_headers(),
        ),
        201,
    )
    assert data["applicable_field_count"] == 11
    assert data["captured_field_count"] == 9
    assert data["lar_status"] == "PENDING_FIELDS"


def test_opening_a_record_against_an_unknown_bank_is_a_not_found(api):
    """PRD §2.6: "Foreign keys supplied inside a request body are resolved with
    the same vocabulary but at a later point in the validation ladder (§2.9): an
    unresolvable `institution_id`, `application_id`, `census_tract_id`,
    `edit_run_id`, or `audit_sample_id` in a body yields the corresponding
    not-found error and HTTP 404."

    Design: Corner/entities/application_with_unknown_institution_id_returns_not_found
    """
    validate_error(
        api.create_application(
            create_application_payload(UNKNOWN_ID), make_loan_officer_headers()
        ),
        ApiErrorId.ERR_INSTITUTION_NOT_FOUND.value,
    )


def test_a_new_record_starts_at_intake_and_pending_fields(api):
    """PRD §3.2: "Opening a record sets `stage` to `INTAKE` and runs the
    completeness calculation described below to set the register-quality
    dimension."
    PRD §3.2: "The capture stages are `INTAKE`, `UNDERWRITING`, `DECISIONED`,
    `REGISTER_LOCKED`, and `ARCHIVED`, with `ARCHIVED` terminal. The
    register-quality values are `PENDING_FIELDS` (the initial value), `COMPLETE`,
    `EXCEPTION_FLAGGED`, `CLEARED`, and `EXCLUDED`; none of them is terminal."

    Design: Corner/state_machines/application_starts_at_intake_and_pending_fields
    """
    institution = create_institution()
    payload = create_application_payload(institution["id"])
    payload.pop("income_thousands")

    data = validate_success(api.create_application(payload, make_loan_officer_headers()), 201)
    assert data["stage"] == "INTAKE"
    assert data["lar_status"] == "PENDING_FIELDS"

    updated = read_institution(institution["id"])
    assert updated["pending_record_count"] == 1
    assert updated["total_application_count"] == 1
    assert updated["open_register_count"] == 1
    assert_register_accounting_identity(updated)


def test_a_business_purpose_record_falls_out_of_the_register(api):
    """PRD §3.2: "If `business_or_commercial_purpose` is true and `loan_purpose` is
    none of `HOME_PURCHASE`, `HOME_IMPROVEMENT`, `REFINANCING`, or
    `CASH_OUT_REFINANCING`, the record becomes `EXCLUDED` with `exclusion_reason`
    set to `BUSINESS_PURPOSE`; the institution's `excluded_record_count` rises by
    one and its `pending_record_count` falls by one."

    Design: Corner/calculations/business_purpose_record_is_excluded_from_the_register
    """
    institution = create_institution()
    payload = create_application_payload(
        institution["id"],
        loan_purpose="OTHER_PURPOSE",
        occupancy_type="INVESTMENT",
        loan_amount_cents=90000000,
        business_or_commercial_purpose=True,
    )
    payload.pop("income_thousands")

    data = validate_success(api.create_application(payload, make_loan_officer_headers()), 201)
    assert data["lar_status"] == "EXCLUDED"
    assert data["exclusion_reason"] == "BUSINESS_PURPOSE"

    updated = read_institution(institution["id"])
    assert updated["excluded_record_count"] == 1
    assert updated["pending_record_count"] == 0
    assert updated["reportable_record_count"] == 0
    assert updated["total_application_count"] == 1
    assert_register_accounting_identity(updated)


def test_a_loan_identifier_is_unique_within_one_bank_only(api):
    """PRD §3.2: "A `uli` must be unique among the non-superseded records of the
    same institution; a collision is rejected with `ERR_DUPLICATE_ULI`."

    Design: Corner/validations/duplicate_uli_within_institution_rejected
    """
    first = create_institution()
    second = create_second_institution()
    shared_uli = next_uli()

    create_application(first["id"], uli=shared_uli)

    collision = create_application_payload(
        first["id"], uli=shared_uli, application_date="2026-02-11T00:00:00Z",
        loan_type="FHA", loan_purpose="REFINANCING", loan_amount_cents=20000000,
    )
    collision.pop("income_thousands")
    validate_error(
        api.create_application(collision, make_loan_officer_headers()),
        ApiErrorId.ERR_DUPLICATE_ULI.value,
    )

    elsewhere = create_application_payload(
        second["id"], uli=shared_uli, application_date="2026-02-11T00:00:00Z",
        loan_type="FHA", loan_purpose="REFINANCING", loan_amount_cents=20000000,
    )
    elsewhere.pop("income_thousands")
    validate_success(
        api.create_application(elsewhere, make_loan_officer_headers()), 201
    )

    assert read_institution(first["id"])["total_application_count"] == 1
    assert read_institution(second["id"])["total_application_count"] == 1


def test_a_correction_record_appears_in_the_originals_corrections_listing(api):
    """PRD §3.2: "When `supersedes_application_id` is supplied, the earlier
    record's `is_superseded` flag is set true and that record's `version`
    increments by 1 — a superseded original stays in the database and stays
    visible through the corrections listing, but it drops out of the final filing
    count and out of every analytical population."

    Design: Corner/endpoints/corrections_sub_resource_lists_the_superseding_record
    """
    institution = create_institution()
    original = create_application(institution["id"])

    correction = validate_success(
        api.create_application(
            create_application_payload(
                institution["id"], loan_amount_cents=36000000,
                supersedes_application_id=original["id"],
            ),
            make_loan_officer_headers(),
        ),
        201,
    )
    assert correction["supersedes_application_id"] == original["id"]
    assert correction["is_superseded"] is False
    assert read_application(original["id"])["is_superseded"] is True

    rows, meta = validate_paginated(
        api.list_application_corrections(original["id"], TEST_USERS["examiner_headers"])
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [correction["id"]]

    empty, empty_meta = validate_paginated(
        api.list_application_corrections(correction["id"], TEST_USERS["examiner_headers"])
    )
    assert empty == []
    assert empty_meta["total_count"] == 0


def test_register_listing_filters_by_register_quality(api):
    """PRD §4: "GET | `/hmda/institutions/{id}/applications` | List the
    institution's register records; filterable by `stage` and by `lar_status` |
    SystemAdmin, InstitutionAdmin, ComplianceAnalyst, ComplianceOfficer,
    LoanOfficer, Examiner"
    PRD §2.3: "Filter query parameters, where an endpoint offers them, narrow the
    set before `total_count` is computed."

    Design: Corner/endpoints/applications_list_filter_by_lar_status
    """
    institution = create_institution()
    create_application(institution["id"])
    excluded = create_application(
        institution["id"],
        application_date="2026-02-11T00:00:00Z",
        loan_purpose="OTHER_PURPOSE",
        occupancy_type="INVESTMENT",
        loan_amount_cents=90000000,
        business_or_commercial_purpose=True,
    )

    rows, meta = validate_paginated(
        api.list_institution_applications(
            institution["id"], TEST_USERS["compliance_analyst_headers"],
            params={"lar_status": "EXCLUDED", "limit": 10, "offset": 0},
        )
    )
    assert len(rows) == 1
    assert rows[0]["id"] == excluded["id"]
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_amending_the_loan_purpose_excludes_the_record_and_reconciles_counters(api):
    """PRD §3.2: "Every amendment re-runs the completeness calculation, recomputes
    the institution's record counters, and increments both the record's `version`
    and the institution's `version` by 1. The most consequential amendment is the
    one that turns a business-purpose row's `loan_purpose` to `OTHER_PURPOSE`,
    which drops the record out of the register entirely as `EXCLUDED`."

    Design: Corner/cross_cutting_layers/institution_counters_reconcile_after_patch_makes_record_excluded
    """
    institution = create_institution()
    record = create_application(
        institution["id"], occupancy_type="INVESTMENT", loan_amount_cents=90000000,
        business_or_commercial_purpose=True,
    )
    before = read_institution(institution["id"])
    assert before["pending_record_count"] == 1
    assert before["excluded_record_count"] == 0

    updated = patch_application(record["id"], {"loan_purpose": "OTHER_PURPOSE"})
    assert updated["lar_status"] == "EXCLUDED"
    assert updated["exclusion_reason"] == "BUSINESS_PURPOSE"

    after = read_institution(institution["id"])
    assert after["pending_record_count"] == 0
    assert after["excluded_record_count"] == 1
    assert after["reportable_record_count"] == 0
    assert after["total_application_count"] == 1
    assert_register_accounting_identity(after)
