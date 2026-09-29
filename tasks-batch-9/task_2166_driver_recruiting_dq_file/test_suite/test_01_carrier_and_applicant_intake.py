"""Registering a recruiting office and opening applicant / application records."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_carrier,
    assert_driver_applicant,
    assert_driver_application,
    create_applicant,
    create_application,
    create_carrier,
    create_carrier_payload,
    create_driver_applicant_payload,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS


RECRUITER = TEST_USERS["recruiter_headers"]
SAFETY_DIRECTOR = TEST_USERS["safety_director_headers"]


def test_carrier_registration_returns_201_with_open_posture(api):
    """PRD §4: "Endpoints that mint a brand-new resource answer with HTTP 201; every
    other successful call — reads, state transitions, action endpoints and updates
    alike — answers with HTTP 200."
    PRD §3.1: "At registration time, with no hires in existence, the ratio is 0.0 and
    the posture therefore resolves to `OPEN` unless the office was registered with an
    `UNSATISFACTORY` rating."
    PRD §3.1: "The `filled_requisitions` count is the number of hire records at that
    carrier whose status is `ACTIVE`; terminated and rescinded hires do not count."
    PRD §2.4: "Every persisted resource carries a server-minted `id`, which is a UUID
    with no type prefix of any kind."
    PRD §2.4: "Each resource also carries `created_at` and `updated_at`, both ISO 8601
    UTC timestamps rendered with exactly three fractional-second digits, and an integer
    `version` that starts at 1 when the row is minted."

    Design: Corner/entities/carrier_creation_returns_201_with_computed_posture
    """
    payload = create_carrier_payload(
        legal_name="Redline Freight LLC", dot_number="DOT-CORNER-1", open_requisitions=5
    )
    response = api.create_carrier(payload, SAFETY_DIRECTOR)
    carrier = validate_success(response, 201)

    assert_carrier(carrier)
    assert carrier["legal_name"] == "Redline Freight LLC"
    assert carrier["dot_number"] == "DOT-CORNER-1"
    assert carrier["version"] == 1, f"version must start at 1, got {carrier['version']}"
    assert carrier["filled_requisitions"] == 0
    assert float(carrier["deficiency_ratio"]) == 0.0
    assert carrier["posture"] == "OPEN"
    assert is_valid_uuid(carrier["id"]), "the id must be a bare UUID with no type prefix"


def test_carrier_policy_knob_defaults_applied_when_omitted(api):
    """PRD §3.1: "The registration payload also carries the office's policy knobs, all
    optional and all defaulted: `safety_rating`, which is one of `SATISFACTORY`,
    `CONDITIONAL` or `UNSATISFACTORY` and defaults to `SATISFACTORY`; `mvr_validity_days`,
    the number of days a motor vehicle record stays current after the date it was issued,
    defaulting to 365 and never less than 1; `annual_review_interval_days`, the spacing
    between qualification-file annual reviews, defaulting to 365 and never less than 1;
    `annual_review_grace_days`, the number of days of slack allowed after a review comes
    due before the file is treated as overdue, defaulting to 30 and never negative;
    `mvr_point_threshold`, the adjudication score at or above which a motor vehicle record
    is disqualifying, defaulting to 7 and never less than 1; `rehire_cooldown_days`, the
    number of days a voluntarily separated driver must wait before being considered again,
    defaulting to 180 and never negative; and `medical_cert_grace_days`, the number of days
    a driver may run past a medical certificate's expiry before the CDL is treated as
    downgraded, defaulting to 15 and never negative."

    Design: Corner/entities/carrier_defaults_applied_when_optional_knobs_omitted
    """
    response = api.create_carrier(
        {"legal_name": "Sparse Carrier", "dot_number": "DOT-CORNER-1", "open_requisitions": 3},
        SAFETY_DIRECTOR,
    )
    carrier = validate_success(response, 201)

    assert carrier["safety_rating"] == "SATISFACTORY"
    assert carrier["mvr_validity_days"] == 365
    assert carrier["annual_review_interval_days"] == 365
    assert carrier["annual_review_grace_days"] == 30
    assert carrier["mvr_point_threshold"] == 7
    assert carrier["rehire_cooldown_days"] == 180
    assert carrier["medical_cert_grace_days"] == 15
    assert carrier["posture"] == "OPEN"


def test_applicant_read_returns_stored_and_derived_fields(api):
    """PRD §3.2: "A new applicant opens with `cdl_downgrade_risk` at `NO_CERTIFICATE`,
    `governing_medical_cert_expires_on` at null, `rehire_eligibility` at `ELIGIBLE` and
    `outstanding_clawback_cents` at 0; all four are derived and are described in §3.7 and
    §3.8."
    PRD §3.2: "Reading a single applicant is not a passive operation: the downgrade risk
    band, the governing certificate expiry, the re-hire eligibility and the outstanding
    clawback total are all recomputed before the record is returned."

    Design: Corner/entities/driver_applicant_retrieval_returns_stored_and_derived_fields
    """
    carrier = create_carrier(dot_number="DOT-CORNER-1")
    applicant = create_applicant(carrier["id"])

    fetched = validate_success(api.get_driver_applicant(applicant["id"], RECRUITER))

    assert_driver_applicant(fetched)
    assert fetched["full_name"] == "Dana Ruiz"
    assert fetched["cdl_state"] == "TX"
    assert fetched["cdl_class"] == "CLASS_A"
    assert fetched["experience_months"] == 24
    assert fetched["cdl_downgrade_risk"] == "NO_CERTIFICATE"
    assert fetched["governing_medical_cert_expires_on"] is None
    assert fetched["rehire_eligibility"] == "ELIGIBLE"
    assert fetched["outstanding_clawback_cents"] == 0


def test_application_listing_windows_and_reports_total_count(api):
    """PRD §2.3: "The `offset` parameter defaults to 0 and may not be negative."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and `has_more`
    inside the `meta` object, where `total_count` is the number of rows matching the
    filters before the window is applied and `has_more` indicates whether any row remains
    beyond the returned window."
    PRD §3.2: "Applications may be listed and narrowed by `applicant_id`, by `carrier_id`,
    by `prior_application_id`, by `screening_status` or by `qualification_status`, and a
    single application read exposes both axes together with its strict verified coverage
    figures."

    Design: Corner/entities/driver_applications_listing_paginates_with_total_count
    """
    carrier = create_carrier(dot_number="DOT-CORNER-1")
    for index, position_type in enumerate(("OTR", "LOCAL", "REGIONAL"), start=1):
        applicant = create_applicant(
            carrier["id"],
            full_name=f"Driver {index}",
            email=f"driver.{index}@example.com",
            cdl_number=f"CDL-{index}",
        )
        create_application(applicant["id"], position_type=position_type)

    response = api.list_driver_applications(
        RECRUITER, params={"carrier_id": carrier["id"], "limit": 2, "offset": 1}
    )
    rows, meta = validate_paginated(response)

    assert len(rows) == 2, f"a limit of 2 must return 2 rows, got {len(rows)}"
    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 1
    assert meta["has_more"] is False
    assert response.json()["response_type"] == "array"


def test_reading_an_unknown_application_reports_application_not_found(api):
    """PRD §2.6: "Nested and parameterised paths are resolved strictly left to right.
    Each identifier in the path is looked up in turn, and the first one that fails to
    resolve determines the error: a missing carrier yields `ERR_CARRIER_NOT_FOUND`, a
    missing applicant `ERR_APPLICANT_NOT_FOUND`, a missing application
    `ERR_APPLICATION_NOT_FOUND`, a missing employment verification
    `ERR_VERIFICATION_NOT_FOUND`, a missing screening check
    `ERR_SCREENING_CHECK_NOT_FOUND`, a missing Clearinghouse query
    `ERR_CLEARINGHOUSE_QUERY_NOT_FOUND`, a missing drug test order
    `ERR_DRUG_TEST_NOT_FOUND`, a missing road test `ERR_ROAD_TEST_NOT_FOUND`, a missing
    orientation session `ERR_SESSION_NOT_FOUND`, a missing enrollment
    `ERR_ENROLLMENT_NOT_FOUND`, a missing qualification file `ERR_DQ_FILE_NOT_FOUND`, a
    missing qualification document `ERR_DQ_DOCUMENT_NOT_FOUND`, a missing tuition
    agreement `ERR_TUITION_AGREEMENT_NOT_FOUND`, and a missing hire record
    `ERR_HIRE_RECORD_NOT_FOUND`. All of these carry HTTP 404."

    Design: Corner/entities/driver_application_get_unknown_id_not_found_returns_404
    """
    create_carrier(dot_number="DOT-CORNER-1")

    response = api.get_driver_application(NON_EXISTENT_UUID, RECRUITER)

    validate_error(response, ApiErrorId.ERR_APPLICATION_NOT_FOUND.value, 404)
    assert response.json()["response_type"] == "error"


def test_applicant_create_without_cdl_number_is_rejected(api):
    """PRD §2.9: "Third, shape: every required body field must be present, every enum
    value must be a declared member of its enumeration, every integer must fall inside its
    declared range, and every date must parse as a `YYYY-MM-DD` calendar date or an ISO
    8601 instant as appropriate — all failures reporting `ERR_VALIDATION` at HTTP 422."
    PRD §3.2: "A `Recruiter` opens a driver applicant record under a carrier, supplying
    `carrier_id`, the driver's `full_name`, their `date_of_birth` as a calendar date, a
    contact `email`, the `cdl_number` as printed, the two-uppercase-letter issuing
    jurisdiction `cdl_state`, the licence `cdl_class` — one of `CLASS_A`, `CLASS_B` or
    `CLASS_C` — and `experience_months`, the count of verified Class-A or Class-B driving
    months, which may be zero but never negative."

    Design: Corner/entities/driver_applicant_create_missing_required_cdl_number_returns_422
    """
    carrier = create_carrier(dot_number="DOT-CORNER-1")
    payload = create_driver_applicant_payload(
        carrier["id"], full_name="No CDL", email="no.cdl@example.com"
    )
    payload.pop("cdl_number")

    response = api.create_driver_applicant(payload, RECRUITER)

    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)
    rows, _ = validate_paginated(
        api.list_driver_applicants(RECRUITER, params={"carrier_id": carrier["id"]})
    )
    assert rows == [], "a rejected create must not persist an applicant"


def test_carrier_create_with_undeclared_safety_rating_is_rejected(api):
    """PRD §2.9: "Third, shape: every required body field must be present, every enum
    value must be a declared member of its enumeration, every integer must fall inside its
    declared range, and every date must parse as a `YYYY-MM-DD` calendar date or an ISO
    8601 instant as appropriate — all failures reporting `ERR_VALIDATION` at HTTP 422."
    PRD §3.1: "`safety_rating`, which is one of `SATISFACTORY`, `CONDITIONAL` or
    `UNSATISFACTORY` and defaults to `SATISFACTORY`"

    Design: Corner/entities/carrier_create_invalid_enum_safety_rating_returns_422
    """
    response = api.create_carrier(
        {
            "legal_name": "Bad Enum Co",
            "dot_number": "DOT-CORNER-1",
            "open_requisitions": 2,
            "safety_rating": "MARGINAL",
        },
        SAFETY_DIRECTOR,
    )

    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)
    rows, _ = validate_paginated(api.list_carriers(RECRUITER))
    assert rows == [], "a rejected registration must not persist a carrier"


def test_duplicate_dot_number_is_refused(api):
    """PRD §3.1: "The `dot_number` is the USDOT number as printed, between 1 and 12
    characters long, and it must be unique across every carrier the service holds; a second
    registration reusing an existing number is refused with `ERR_DUPLICATE_DOT_NUMBER`."

    Design: Corner/entities/carrier_duplicate_dot_number_rejected
    """
    create_carrier(dot_number="DOT-CORNER-1")

    response = api.create_carrier(
        {"legal_name": "Copycat Lines", "dot_number": "DOT-CORNER-1", "open_requisitions": 1},
        SAFETY_DIRECTOR,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_DOT_NUMBER.value, 409)
    rows, meta = validate_paginated(api.list_carriers(RECRUITER))
    assert meta["total_count"] == 1, "the duplicate registration must not have persisted"


def test_duplicate_applicant_email_within_carrier_is_refused(api):
    """PRD §3.2: "The `email` must be unique within its carrier; a collision reports
    `ERR_DUPLICATE_DOT_NUMBER`, the same code the carrier-level uniqueness rule uses."

    Design: Corner/entities/driver_applicant_duplicate_email_within_carrier_rejected
    """
    carrier = create_carrier(dot_number="DOT-CORNER-1")
    create_applicant(carrier["id"], email="dana.ruiz@example.com")

    response = api.create_driver_applicant(
        create_driver_applicant_payload(
            carrier["id"],
            full_name="Dana Twin",
            email="dana.ruiz@example.com",
            cdl_number="CDL-9999",
            experience_months=10,
        ),
        RECRUITER,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_DOT_NUMBER.value, 409)
    _, meta = validate_paginated(
        api.list_driver_applicants(RECRUITER, params={"carrier_id": carrier["id"]})
    )
    assert meta["total_count"] == 1


def test_new_application_opens_on_both_axes_with_derived_coverage(api):
    """PRD §3.2: "The service copies `carrier_id` from the applicant onto the application;
    a client never supplies it."
    PRD §3.2: "A fresh application opens at `DRAFT` on the first axis and `NOT_STARTED` on
    the second."
    PRD §3.2: "Against an applicant, a `Recruiter` opens an application by supplying
    `applicant_id`, a `position_type` of `OTR`, `REGIONAL` or `LOCAL`, and optionally a
    `prior_application_id` naming the superseded application this one re-applies against —
    null for a first application."
    PRD §3.3: "The `verified_coverage_days` figure is the total number of days spanned by
    the merged runs, and `gap_days_unexplained` is 1,095 minus that figure."
    PRD §2.4: "Each resource also carries `created_at` and `updated_at`, both ISO 8601 UTC
    timestamps rendered with exactly three fractional-second digits, and an integer
    `version` that starts at 1 when the row is minted."

    Design: Corner/entities/driver_application_computed_fields_initialised_on_create
    """
    carrier = create_carrier(dot_number="DOT-CORNER-1")
    applicant = create_applicant(carrier["id"])

    response = api.create_driver_application(
        {"applicant_id": applicant["id"], "position_type": "OTR"}, RECRUITER
    )
    application = validate_success(response, 201)

    assert_driver_application(application)
    assert application["screening_status"] == "DRAFT"
    assert application["qualification_status"] == "NOT_STARTED"
    assert application["version"] == 1
    assert application["verified_coverage_days"] == 0
    assert application["gap_days_unexplained"] == 1095
    assert application["carrier_id"] == carrier["id"]
    assert application["submitted_at"] is None
    assert application["prior_application_id"] is None


def test_application_create_with_unknown_applicant_reports_applicant_not_found(api):
    """PRD §2.6: "Foreign keys arriving in a request body are resolved with the same
    catalogue of not-found codes and the same 404 status, and this check runs immediately
    after path resolution. It covers `applicant_id`, `carrier_id`, `application_id`,
    `session_id`, `prior_application_id`, and every member of an `attended_enrollment_ids`
    list."
    PRD §2.6: "a missing applicant `ERR_APPLICANT_NOT_FOUND`"

    Design: Corner/entities/driver_application_create_unknown_applicant_not_found_returns_404
    """
    create_carrier(dot_number="DOT-CORNER-1")

    response = api.create_driver_application(
        {"applicant_id": NON_EXISTENT_UUID, "position_type": "OTR"}, RECRUITER
    )

    validate_error(response, ApiErrorId.ERR_APPLICANT_NOT_FOUND.value, 404)
    rows, _ = validate_paginated(api.list_driver_applications(RECRUITER))
    assert rows == [], "a rejected create must not persist an application"


def test_client_supplied_identifier_is_ignored_on_create(api):
    """PRD §2.4: "Every persisted resource carries a server-minted `id`, which is a UUID
    with no type prefix of any kind. Clients never supply an `id`; a client-supplied
    identifier in a create payload is ignored."
    PRD §2.4: "Each resource also carries `created_at` and `updated_at`, both ISO 8601 UTC
    timestamps rendered with exactly three fractional-second digits, and an integer
    `version` that starts at 1 when the row is minted."

    Design: Corner/entities/carrier_create_system_fields_input_ignored
    """
    spoofed_id = "11111111-1111-4111-8111-111111111111"
    response = api.create_carrier(
        {
            "legal_name": "Spoofed Co",
            "dot_number": "DOT-CORNER-1",
            "open_requisitions": 2,
            "id": spoofed_id,
            "version": 77,
        },
        SAFETY_DIRECTOR,
    )
    carrier = validate_success(response, 201)

    assert carrier["id"] != spoofed_id, "a client-supplied id must be ignored"
    assert is_valid_uuid(carrier["id"])
    assert carrier["version"] == 1, "version must start at 1 regardless of the payload"
