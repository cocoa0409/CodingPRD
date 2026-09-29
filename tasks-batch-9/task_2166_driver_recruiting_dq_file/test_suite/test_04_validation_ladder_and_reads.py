"""Pagination bounds, ladder ordering, and the computed / filtered read endpoints."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_completeness_payload,
    create_carrier,
    create_employment_verification_payload,
    fetch_dq_file,
    request_and_verify_segment,
    record_employment_segment,
    setup_hired_applicant,
    setup_submitted_application,
    validate_error,
    validate_paginated,
    validate_success,
)

RECRUITER = TEST_USERS["recruiter_headers"]
SAFETY_DIRECTOR = TEST_USERS["safety_director_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]
SCHOOL = TEST_USERS["school_coordinator_headers"]


def test_a_limit_above_one_hundred_is_rejected(api):
    """PRD §2.3: "The `limit` parameter defaults to 10 when omitted, may not be smaller than
    1, and may not be larger than 100."
    PRD §2.3: "A `limit` or `offset` that is not an integer, or that falls outside those
    bounds, is rejected with `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/validations/pagination_limit_above_max_returns_422
    """
    create_carrier(dot_number="DOT-CORNER-1")

    response = api.list_carriers(RECRUITER, params={"limit": 101, "offset": 0})

    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)


def test_pagination_defaults_are_applied_when_omitted(api):
    """PRD §2.3: "The `limit` parameter defaults to 10 when omitted, may not be smaller than
    1, and may not be larger than 100. The `offset` parameter defaults to 0 and may not be
    negative."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and `has_more`
    inside the `meta` object, where `total_count` is the number of rows matching the filters
    before the window is applied and `has_more` indicates whether any row remains beyond the
    returned window."

    Design: Corner/validations/pagination_defaults_applied_when_params_omitted
    """
    create_carrier(dot_number="DOT-CORNER-1")

    response = api.list_carriers(RECRUITER)
    rows, meta = validate_paginated(response)

    assert response.json()["response_type"] == "array"
    assert len(rows) == 1
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_an_unresolvable_path_id_is_reported_before_any_state_check(api):
    """PRD §2.9: "Second, existence: every identifier in the path is resolved left to right,
    then every foreign key in the body, each producing its own 404 code from the catalogue in
    §2.6."
    PRD §2.6: "a missing qualification file `ERR_DQ_FILE_NOT_FOUND`"
    PRD §3.7: "And the file's `review_state` must be `DUE` or `OVERDUE` — an early review is
    refused with `ERR_REVIEW_NOT_DUE`, never with `ERR_INVALID_STATE`, because the
    review-clock axis is owned by its own rung of the ladder in §2.9 and sits below the three
    checks just named."

    Design: Corner/validations/path_existence_checked_before_state_precondition
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})

    response = api.annual_review(
        NON_EXISTENT_UUID, {"certification_note": "n/a"}, AUDITOR
    )

    validate_error(response, ApiErrorId.ERR_DQ_FILE_NOT_FOUND.value, 404)
    dq_file = fetch_dq_file(ctx["dq_file_id"])
    assert dq_file["review_state"] == "NOT_DUE"
    assert dq_file["last_annual_review_at"] is None


def test_an_unauthorised_role_is_reported_before_the_path_is_resolved(api):
    """PRD §2.9: "First, authentication and authorisation: the two headers must be present
    and non-empty, then `X-User-Role` must name one of the six declared roles (both failures
    reporting `ERR_UNAUTHENTICATED` at HTTP 401), then the acting role must appear in the
    endpoint's authorised list (`ERR_FORBIDDEN_ROLE`, 403), then — on the Clearinghouse
    consent decision and on the screening dispute only — an acting `Applicant` must own the
    targeted resource (`ERR_NOT_RESOURCE_OWNER`, 403)."
    PRD §2.9: "Second, existence: every identifier in the path is resolved left to right,
    then every foreign key in the body, each producing its own 404 code from the catalogue in
    §2.6."
    PRD §2.1: "Where a role is not listed as authorised for the endpoint it calls, the
    request fails with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/validations/role_authorization_checked_before_existence
    """
    create_carrier(dot_number="DOT-CORNER-1")

    response = api.terminate_hire_record(
        NON_EXISTENT_UUID,
        {
            "terminated_on": "2026-08-20",
            "termination_type": "VOLUNTARY",
            "rehire_flag": "ELIGIBLE",
        },
        SCHOOL,
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_a_degenerate_employment_interval_is_rejected(api):
    """PRD §3.3: "A `Recruiter` records one segment per previous employer by supplying
    `application_id`, the `employer_name`, a boolean `is_dot_regulated` marking whether that
    employer was itself a DOT-regulated motor carrier — which is what triggers the
    safety-performance history duty — and the segment's boundaries as `employed_from`, an
    inclusive calendar date, and `employed_to`, an exclusive calendar date that must fall
    strictly after `employed_from`; an inverted or degenerate interval is refused with
    `ERR_VALIDATION` at HTTP 422."

    Design: Corner/validations/employment_segment_with_reversed_dates_returns_422
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})

    response = api.create_employment_verification(
        create_employment_verification_payload(
            ctx["application_id"],
            employer_name="Zero Length Co",
            is_dot_regulated=False,
            employed_from="2024-09-01",
            employed_to="2024-09-01",
        ),
        RECRUITER,
    )

    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)
    rows, _ = validate_paginated(
        api.list_employment_verifications(
            RECRUITER, params={"application_id": ctx["application_id"]}
        )
    )
    assert rows == [], "a rejected segment must not persist"


def test_the_completeness_read_defaults_to_the_provisional_accounting(api):
    """PRD §3.7: "The provisional accounting, named `pre_hire_provisional`, is the default
    and the only one persisted: it is what `completeness_pct` and `deficiency_count` hold on
    the file and what drives the file's status between `OPEN`, `COMPLETE` and `DEFICIENT`. It
    excludes `MVR_ANNUAL` and `ANNUAL_REVIEW_CERT` from scope, leaving a denominator of 28,
    and it treats both `PRESENT` and `WAIVED` as satisfying, so a waived artifact counts
    toward the score."
    PRD §3.7: "The on-demand completeness read takes an optional `variant` of
    `pre_hire_provisional` or `annual_review_final`, defaulting to the former, and answers
    with the `variant` it applied, the resulting `completeness_pct` and `deficiency_count`,
    the `satisfied_weight` and `denominator_weight` that produced them, and
    `missing_doc_types`, the list of in-scope artifact types that were not satisfied."

    Design: Corner/endpoints/dq_completeness_defaults_to_pre_hire_variant
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})

    payload = validate_success(
        api.get_dq_file_completeness(ctx["dq_file_id"], AUDITOR)
    )

    assert_completeness_payload(payload, "pre_hire_provisional")
    assert payload["denominator_weight"] == 28
    assert payload["satisfied_weight"] == 3
    assert float(payload["completeness_pct"]) == 10.71
    assert payload["deficiency_count"] == 9
    missing = set(payload["missing_doc_types"])
    assert missing == {
        "CDL_COPY",
        "MVR_INITIAL",
        "PSP_REPORT",
        "CRIMINAL_CHECK",
        "EMPLOYMENT_VERIFICATION",
        "CLEARINGHOUSE_QUERY",
        "DRUG_TEST_RESULT",
        "ROAD_TEST_CERT",
        "MEDICAL_CERT",
    }
    assert "MVR_ANNUAL" not in missing
    assert "ANNUAL_REVIEW_CERT" not in missing


def test_the_coverage_read_defaults_to_the_strict_accounting(api):
    """PRD §3.3: "The projected figure exists so a recruiter can demonstrate diligence to an
    auditor, and it is obtained by asking the coverage read for a `variant` of
    `good_faith_projected`; omitting the parameter yields `strict_verified`."
    PRD §3.3: "That read answers with the `variant` it applied, the resulting
    `verified_coverage_days` and `gap_days_unexplained`, and a `merged_segment_count` giving
    the number of runs left after merging."

    Design: Corner/endpoints/employment_coverage_defaults_to_strict_variant
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    segment = record_employment_segment(
        ctx["application_id"], "Northgate Haul", "2024-09-01", "2026-08-01"
    )
    request_and_verify_segment(segment["id"])

    payload = validate_success(
        api.get_employment_coverage(ctx["application_id"], RECRUITER)
    )

    assert payload["variant"] == "strict_verified"
    assert payload["verified_coverage_days"] == 699
    assert payload["gap_days_unexplained"] == 396
    assert payload["merged_segment_count"] == 1


def test_reapplying_links_the_predecessor_and_advances_its_version(api):
    """PRD §3.2: "A `Recruiter` names the predecessor in the path, supplies
    `expected_application_version` matching that predecessor's current `version` and a fresh
    `position_type`; the service increments the predecessor's `version` by one and mints a
    brand-new application for the same applicant at `DRAFT` and `NOT_STARTED`, with
    `prior_application_id` pointing back at the predecessor."
    PRD §3.2: "Applications may be listed and narrowed by `applicant_id`, by `carrier_id`, by
    `prior_application_id`, by `screening_status` or by `qualification_status`, and a single
    application read exposes both axes together with its strict verified coverage figures."

    Design: Corner/endpoints/reapply_links_prior_application_and_bumps_prior_version
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    validate_success(
        api.disqualify_application(
            ctx["application_id"], {"reason": "CANDIDATE_PAUSED"}, SAFETY_DIRECTOR
        )
    )
    prior = validate_success(api.get_driver_application(ctx["application_id"], RECRUITER))
    prior_version = prior["version"]

    response = api.reapply(
        ctx["application_id"],
        {"expected_application_version": prior_version, "position_type": "REGIONAL"},
        RECRUITER,
    )
    successor = validate_success(response, 201)

    assert successor["prior_application_id"] == ctx["application_id"]
    assert successor["screening_status"] == "DRAFT"
    assert successor["qualification_status"] == "NOT_STARTED"
    assert successor["applicant_id"] == ctx["applicant_id"]
    assert successor["position_type"] == "REGIONAL"

    refreshed = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert refreshed["version"] == prior_version + 1

    rows, meta = validate_paginated(
        api.list_driver_applications(
            RECRUITER, params={"prior_application_id": ctx["application_id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == successor["id"]


def test_hire_record_filters_expose_the_prior_hire_chain(api):
    """PRD §3.8: "It also resolves `prior_hire_id`, which points at the most recent
    `TERMINATED` hire record of the same applicant at the same carrier, chosen by ordering
    those records by `terminated_on` descending and, where those tie, by `created_at`
    descending; when the applicant has never been terminated there, the field stays null."
    PRD §3.8: "Hire records may be listed and narrowed by `application_id`, by
    `applicant_id`, by `carrier_id`, by `prior_hire_id` or by `status`."
    PRD §3.8: "On success the service mints the hire record in `ACTIVE`, copying
    `applicant_id` and `carrier_id` from the application and leaving `terminated_on` null,
    `termination_type` at `NONE`, `rehire_flag` at `ELIGIBLE` and `tenure_days` at zero."

    Design: Corner/endpoints/hire_records_filtered_list_exposes_prior_hire_chain
    """
    ctx = setup_hired_applicant(carrier_overrides={"dot_number": "DOT-CORNER-1"})

    rows, meta = validate_paginated(
        api.list_hire_records(SAFETY_DIRECTOR, params={"applicant_id": ctx["applicant_id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == ctx["hire_id"]
    assert rows[0]["prior_hire_id"] is None
    assert rows[0]["carrier_id"] == ctx["carrier_id"]
    assert rows[0]["applicant_id"] == ctx["applicant_id"]

    _, chained_meta = validate_paginated(
        api.list_hire_records(SAFETY_DIRECTOR, params={"prior_hire_id": ctx["hire_id"]})
    )
    assert chained_meta["total_count"] == 0, "no later hire points at this one yet"


def test_documents_can_be_narrowed_to_a_single_artifact_type(api):
    """PRD §3.7: "Documents may be listed and narrowed by `dq_file_id`, by `doc_type` or by
    `status`."
    PRD §3.7: "Each of the twelve rows the file holds carries `dq_file_id` back to its file, a
    `doc_type` naming the regulatory artifact it tracks, and a `weight` fixed per artifact type
    and never supplied by a client: `APPLICATION_FORM` weighs 3, `CDL_COPY` weighs 2,
    `MVR_INITIAL` weighs 3, `PSP_REPORT` weighs 2, `CRIMINAL_CHECK` weighs 1,
    `EMPLOYMENT_VERIFICATION` weighs 4, `CLEARINGHOUSE_QUERY` weighs 3, `DRUG_TEST_RESULT`
    weighs 3, `ROAD_TEST_CERT` weighs 3, `MEDICAL_CERT` weighs 4, `MVR_ANNUAL` weighs 3 and
    `ANNUAL_REVIEW_CERT` weighs 2 — thirty-three in total, and that sum must read identically
    before and after every operation, compensating operations included."
    PRD §3.7: "A document's presence is tracked by its `status`, one of `MISSING`, `PRESENT`,
    `EXPIRED` or `WAIVED`, together with the calendar dates `effective_on` — the date the
    artifact took effect, null while missing — and `expires_on` — the date it lapses, null for
    an artifact that never expires — and a free-text `source_ref` pointing at whatever
    originated it, such as a screening check identifier or a medical examiner registry number."

    Design: Corner/endpoints/dq_documents_filtered_by_doc_type_returns_single_row
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})

    rows, meta = validate_paginated(
        api.list_dq_documents(
            RECRUITER, params={"dq_file_id": ctx["dq_file_id"], "doc_type": "MEDICAL_CERT"}
        )
    )
    assert meta["total_count"] == 1
    medical = rows[0]
    assert medical["weight"] == 4
    assert medical["status"] == "MISSING"
    assert medical["dq_file_id"] == ctx["dq_file_id"]
    assert medical["effective_on"] is None
    assert medical["expires_on"] is None

    _, missing_meta = validate_paginated(
        api.list_dq_documents(
            RECRUITER,
            params={"dq_file_id": ctx["dq_file_id"], "status": "MISSING", "limit": 100},
        )
    )
    assert missing_meta["total_count"] == 11, (
        "eleven rows stay MISSING once submission files the application form"
    )
