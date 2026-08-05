"""Registering a premises and walking the plan-review cycle."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_establishment,
    assert_plan_review,
    create_establishment_payload,
    create_plan_review_payload,
    decide_plan_review,
    is_valid_uuid,
    make_operator_headers,
    plan_review_decision_payload,
    register_establishment,
    resubmit_plan_review_payload,
    submit_plan_review,
    validate_error,
    validate_paginated,
    validate_success,
)

HO = TEST_USERS["health_officer_headers"]
REVIEWER = TEST_USERS["plan_reviewer_headers"]
CLERK = TEST_USERS["records_clerk_headers"]


def test_register_establishment_returns_declared_defaults(api):
    """PRD §3.1: "The record is born in `permit_status` `PENDING_PLAN_REVIEW` with
    `permit_issued_on` and `permit_expires_on` both null, `active_artist_count`,
    `open_violation_count`, `open_critical_violation_count`, `fees_paid_cents` and
    `fees_refunded_cents` all zero, and `plan_review_cycles_used` at 1."
    PRD §3.1: "The provisional risk figure then runs and, with no violations, no
    complaints and no infection reports on file, consists solely of the
    non-compliance penalty, so a brand-new establishment opens its life with a
    `risk_score` of 25."
    PRD §3.1: "Its `operating_posture` is `CLOSED`, because the permit is not yet
    `ACTIVE`."
    PRD §2.4: "The `version` of a fresh record is 1, and every mutation that touches
    the record increments it by exactly one and refreshes `updated_at` to the current
    logical-clock instant."

    Design: Corner/entities/create_establishment_returns_defaults_and_initial_state
    """
    payload = create_establishment_payload(
        name="Fresh Ink", street_address="1 First St", county_code="ADA",
        establishment_type="TATTOO",
    )
    data = validate_success(api.create_establishment(payload, HO), 201)
    assert_establishment(data)

    assert data["permit_status"] == "PENDING_PLAN_REVIEW"
    assert data["operating_posture"] == "CLOSED"
    assert data["sterilization_compliance_status"] == "NONCOMPLIANT"
    assert data["risk_score"] == 25, f"Expected risk_score 25, got {data['risk_score']}"
    assert data["version"] == 1
    assert data["permit_issued_on"] is None
    assert data["permit_expires_on"] is None
    assert is_valid_uuid(data["id"]), "The id must be a dashed UUID with no type prefix"
    assert data["plan_review_cycles_used"] == 1
    assert data["fees_paid_cents"] == 0
    assert data["fees_refunded_cents"] == 0
    assert data["active_artist_count"] == 0
    assert data["open_violation_count"] == 0
    assert data["open_critical_violation_count"] == 0


def test_read_establishment_echoes_every_stored_input_field(api):
    """PRD §3.1: "The registration payload carries the legal business `name` of the
    shop, which must be between 1 and 120 characters and non-empty once surrounding
    whitespace is trimmed; the `street_address` of the permitted premises, between 1
    and 200 characters; the `county_code` asserting jurisdiction, which must be
    exactly three uppercase letters A through Z; and the `establishment_type`, which
    is one of `TATTOO`, `PIERCING`, `PERMANENT_COSMETICS` or `COMBINED`."
    PRD §3.1: "Departmental staff can read any establishment individually, and
    `HealthOfficer`, `Inspector`, `PlanReviewer` and `RecordsClerk` users can browse
    the whole roster with optional filters on `county_code`, `permit_status` and
    `operating_posture` alongside the usual `limit` and `offset`."

    Design: Corner/entities/get_establishment_by_id_returns_stored_entity
    """
    created = register_establishment(
        name="Echo Ink", street_address="2 Second St", county_code="CAN",
        establishment_type="PERMANENT_COSMETICS",
    )

    data = validate_success(api.get_establishment(created["id"], CLERK), 200)
    assert data["name"] == "Echo Ink"
    assert data["street_address"] == "2 Second St"
    assert data["county_code"] == "CAN"
    assert data["establishment_type"] == "PERMANENT_COSMETICS"
    assert data["id"] == created["id"]


def test_list_establishments_filters_by_county_and_paginates(api):
    """PRD §3.1: "Departmental staff can read any establishment individually, and
    `HealthOfficer`, `Inspector`, `PlanReviewer` and `RecordsClerk` users can browse
    the whole roster with optional filters on `county_code`, `permit_status` and
    `operating_posture` alongside the usual `limit` and `offset`."
    PRD §2.3: "For list responses the `meta` object carries `limit` and `offset`
    echoing the effective values, `total_count` giving the number of rows matching the
    filters before pagination is applied, and `has_more` indicating whether any
    further rows remain beyond the current page."

    Design: Corner/entities/list_establishments_paginated_with_county_filter
    """
    register_establishment(name="ADA One", street_address="1 A St", county_code="ADA")
    register_establishment(
        name="ADA Two", street_address="2 A St", county_code="ADA",
        establishment_type="PIERCING",
    )
    register_establishment(
        name="ADA Three", street_address="3 A St", county_code="ADA",
        establishment_type="COMBINED",
    )
    register_establishment(name="CAN One", street_address="1 C St", county_code="CAN")

    response = api.list_establishments(HO, params={"county_code": "ADA", "limit": 2, "offset": 0})
    rows, meta = validate_paginated(response)

    assert response.json()["response_type"] == "array"
    assert len(rows) == 2, f"Expected 2 rows on the page, got {len(rows)}"
    assert all(row["county_code"] == "ADA" for row in rows)
    assert meta["total_count"] == 3, f"Expected total_count 3, got {meta['total_count']}"
    assert meta["has_more"] is True


def test_read_unknown_establishment_returns_not_found(api):
    """PRD §2.6: "An unresolved establishment segment yields
    `ERR_ESTABLISHMENT_NOT_FOUND`, an artist segment yields `ERR_ARTIST_NOT_FOUND`, a
    plan-review segment yields `ERR_PLAN_REVIEW_NOT_FOUND`, an inspection segment
    yields `ERR_INSPECTION_NOT_FOUND`, a violation segment yields
    `ERR_VIOLATION_NOT_FOUND`, a sterilization-record segment yields
    `ERR_STERILIZATION_RECORD_NOT_FOUND`, a minor-consent segment yields
    `ERR_MINOR_CONSENT_NOT_FOUND`, a procedure-log segment yields
    `ERR_PROCEDURE_LOG_NOT_FOUND`, a complaint segment yields
    `ERR_COMPLAINT_NOT_FOUND`, an infection-report segment yields
    `ERR_INFECTION_REPORT_NOT_FOUND`, an enforcement-action segment yields
    `ERR_ENFORCEMENT_ACTION_NOT_FOUND` and a renewal-application segment yields
    `ERR_RENEWAL_APPLICATION_NOT_FOUND`. All of these carry HTTP 404."

    Design: Corner/entities/get_establishment_unknown_id_returns_not_found
    """
    response = api.get_establishment("11111111-2222-4333-8444-555555555555", HO)
    validate_error(response, ApiErrorId.ERR_ESTABLISHMENT_NOT_FOUND.value)
    assert response.status_code == 404


def test_register_establishment_without_county_code_is_a_validation_failure(api):
    """PRD §2.7: "Request-body shape: every required input field present, every enum
    field holding a declared member, every numeric field inside its declared range,
    every datetime field a well-formed ISO 8601 UTC instant, `scheduled_end_at`
    strictly after `scheduled_start_at`, `ended_at` strictly after `started_at`, and
    pagination parameters within their declared bounds — all failures yield
    `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_establishment_missing_required_field_returns_validation
    """
    response = api.create_establishment(
        {"name": "No County", "street_address": "9 Ninth St", "establishment_type": "TATTOO"},
        HO,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value)
    assert response.status_code == 400

    rows, meta = validate_paginated(api.list_establishments(HO))
    assert meta["total_count"] == 0, "A rejected registration must store nothing"


def test_register_establishment_with_undeclared_type_is_a_validation_failure(api):
    """PRD §3.1: "the `county_code` asserting jurisdiction, which must be exactly
    three uppercase letters A through Z; and the `establishment_type`, which is one of
    `TATTOO`, `PIERCING`, `PERMANENT_COSMETICS` or `COMBINED`."
    PRD §2.7: "Request-body shape: every required input field present, every enum
    field holding a declared member, every numeric field inside its declared range,
    every datetime field a well-formed ISO 8601 UTC instant, `scheduled_end_at`
    strictly after `scheduled_start_at`, `ended_at` strictly after `started_at`, and
    pagination parameters within their declared bounds — all failures yield
    `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_establishment_invalid_enum_returns_validation
    """
    response = api.create_establishment(
        create_establishment_payload(
            name="Bad Enum", street_address="8 Eighth St", establishment_type="BRANDING"
        ),
        HO,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value)
    assert response.status_code == 400


def test_plan_review_is_born_submitted_with_declared_defaults(api):
    """PRD §3.1: "The new review is born `SUBMITTED` with `cycle_count` at 1 and
    `decision_notes` and `decided_by_user_id` both null."

    Design: Corner/entities/plan_review_defaults_applied_on_create
    """
    establishment = register_establishment(
        name="Default Ink", street_address="4 Fourth St"
    )
    payload = create_plan_review_payload(
        establishment["id"], floor_plan_reference="FP-D1", sterilization_area_sqft=50
    )
    data = validate_success(
        api.create_plan_review(payload, make_operator_headers(establishment["id"])), 201
    )
    assert_plan_review(data)

    assert data["status"] == "SUBMITTED"
    assert data["cycle_count"] == 1
    assert data["decision_notes"] is None
    assert data["decided_by_user_id"] is None


def test_register_artist_against_unknown_establishment_returns_not_found(api):
    """PRD §2.6: "On creation routes that accept a referenced identifier — artist
    registration, plan-review submission, inspection scheduling, sterilization-record
    filing, minor-consent filing, procedure-log filing, complaint filing,
    infection-report filing and renewal-application creation — each of
    `establishment_id`, `artist_id`, `minor_consent_id` and `supersedes_record_id`
    must resolve to a stored row, and a failure yields the corresponding not-found
    code with HTTP 404."

    Design: Corner/entities/create_artist_with_unknown_establishment_returns_not_found
    """
    response = api.create_artist(
        {
            "establishment_id": "99999999-8888-4777-8666-555555555555",
            "legal_name": "Ghost Artist",
        },
        HO,
    )
    validate_error(response, ApiErrorId.ERR_ESTABLISHMENT_NOT_FOUND.value)
    assert response.status_code == 404

    rows, meta = validate_paginated(api.list_artists(HO))
    assert meta["total_count"] == 0, "No orphan Artist row may be written"


def test_denied_plan_review_cannot_be_resubmitted(api):
    """PRD §3.1: "A denial is admissible from either `SUBMITTED` or
    `CORRECTIONS_REQUIRED`, and both `APPROVED` and `DENIED` are terminal."
    PRD §2.9: "Every action route that drives a state machine first checks that its
    target sits in a state the requested transition declares as its origin."
    PRD §2.9: "When it does not, the error identifier is chosen by the entity that
    owns the state machine, not by the action: establishments yield
    `ERR_ESTABLISHMENT_STATE_INVALID`, artists `ERR_ARTIST_STATE_INVALID`, plan
    reviews `ERR_PLAN_REVIEW_STATE_INVALID`, inspections
    `ERR_INSPECTION_STATE_INVALID`, violations `ERR_VIOLATION_STATE_INVALID`, minor
    consents `ERR_CONSENT_STATE_INVALID`, procedure logs
    `ERR_PROCEDURE_LOG_STATE_INVALID`, complaints `ERR_COMPLAINT_STATE_INVALID`,
    infection reports `ERR_INFECTION_STATE_INVALID`, enforcement actions
    `ERR_ENFORCEMENT_STATE_INVALID` and renewal applications
    `ERR_RENEWAL_STATE_INVALID`. All eleven carry HTTP 409."

    Design: Corner/state_machines/denied_plan_review_is_terminal_and_resubmit_is_rejected
    """
    establishment = register_establishment(
        name="Denied Ink", street_address="12 Twelfth St"
    )
    review = submit_plan_review(establishment["id"], floor_plan_reference="FP-DN")
    decide_plan_review(review["id"], "DENY", decision_notes="Sited over a floor drain.")

    response = api.resubmit_plan_review(
        review["id"],
        resubmit_plan_review_payload(
            floor_plan_reference="FP-DN2", sterilization_area_sqft=70
        ),
        make_operator_headers(establishment["id"]),
    )
    validate_error(response, ApiErrorId.ERR_PLAN_REVIEW_STATE_INVALID.value)
    assert response.status_code == 409

    stored = validate_success(api.get_plan_review(review["id"], HO))
    assert stored["status"] == "DENIED"
    assert stored["cycle_count"] == 1

    parent = validate_success(api.get_establishment(establishment["id"], HO))
    assert parent["permit_status"] == "PENDING_PLAN_REVIEW"


def test_corrections_cycle_increments_count_then_approval_advances_the_premises(api):
    """PRD §3.1: "A resubmission carries fresh values for `floor_plan_reference`,
    `sterilization_area_sqft`, `procedure_station_count` and `has_handwash_sink`,
    which overwrite the stored values outright; it increments `cycle_count` by one and
    copies that new count onto the establishment's `plan_review_cycles_used`; and it
    clears `decision_notes` back to null."
    PRD §3.1: "It cascades: the parent establishment advances `PENDING_PLAN_REVIEW →
    PENDING_INSPECTION`, its `version` increments by one, its `updated_at` refreshes,
    and its posture is recomputed — which leaves it `CLOSED`, since the permit is
    still not `ACTIVE`."

    Design: Corner/state_machines/plan_review_corrections_cycle_increments_then_approves
    """
    establishment = register_establishment(
        name="Cycle Ink", street_address="13 Thirteenth St"
    )
    review = submit_plan_review(
        establishment["id"], floor_plan_reference="FP-C1", has_handwash_sink=False
    )
    decide_plan_review(
        review["id"], "REQUEST_CORRECTIONS", decision_notes="Add a dedicated handwash sink."
    )

    resubmitted = validate_success(
        api.resubmit_plan_review(
            review["id"],
            resubmit_plan_review_payload(
                floor_plan_reference="FP-C2", sterilization_area_sqft=60,
                procedure_station_count=2, has_handwash_sink=True,
            ),
            make_operator_headers(establishment["id"]),
        )
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["cycle_count"] == 2
    assert resubmitted["decision_notes"] is None
    assert resubmitted["has_handwash_sink"] is True

    approved = validate_success(
        api.decide_plan_review(
            review["id"], plan_review_decision_payload("APPROVE", decision_notes="Sink added."),
            REVIEWER,
        )
    )
    assert approved["status"] == "APPROVED"

    parent = validate_success(api.get_establishment(establishment["id"], HO))
    assert parent["plan_review_cycles_used"] == 2
    assert parent["permit_status"] == "PENDING_INSPECTION"
    assert parent["operating_posture"] == "CLOSED"


def test_plan_review_duplicate_requirements_and_cycle_limit_rejections(api):
    """PRD §3.1: "A premises may hold only one review in flight at a time: if any
    prior plan review for the same establishment is still `SUBMITTED` or
    `CORRECTIONS_REQUIRED`, a further submission is rejected with
    `ERR_DUPLICATE_OPEN_PLAN_REVIEW` (HTTP 409)."
    PRD §3.1: "A plan that fails either requirement is rejected with
    `ERR_PLAN_REVIEW_REQUIREMENTS_NOT_MET` (HTTP 422) rather than being approved."
    PRD §3.1: "This revision loop may repeat, but not indefinitely — a resubmission is
    admissible only while `cycle_count` remains strictly below 3, so the third
    submission of a plan is the last one the department will look at."
    PRD §3.1: "An attempt beyond that ceiling is rejected with
    `ERR_PLAN_REVIEW_CYCLE_LIMIT` (HTTP 409)."

    Design: Corner/validations/plan_review_duplicate_requirements_and_cycle_limit_rejections
    """
    establishment = register_establishment(
        name="Plan Gate Ink", street_address="33 Thirtythird St"
    )
    operator = make_operator_headers(establishment["id"])
    review = submit_plan_review(
        establishment["id"], floor_plan_reference="FP-PG1",
        sterilization_area_sqft=30, has_handwash_sink=False,
    )

    duplicate = api.create_plan_review(
        create_plan_review_payload(
            establishment["id"], floor_plan_reference="FP-PG2", sterilization_area_sqft=80
        ),
        operator,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_OPEN_PLAN_REVIEW.value)
    assert duplicate.status_code == 409

    bad_approve = api.decide_plan_review(
        review["id"], plan_review_decision_payload("APPROVE", decision_notes="Trying to approve."),
        REVIEWER,
    )
    validate_error(bad_approve, ApiErrorId.ERR_PLAN_REVIEW_REQUIREMENTS_NOT_MET.value)
    assert bad_approve.status_code == 422

    decide_plan_review(review["id"], "REQUEST_CORRECTIONS", decision_notes="Round 1.")
    validate_success(
        api.resubmit_plan_review(
            review["id"],
            resubmit_plan_review_payload(
                floor_plan_reference="FP-PG1b", sterilization_area_sqft=32,
                has_handwash_sink=False,
            ),
            operator,
        )
    )
    decide_plan_review(review["id"], "REQUEST_CORRECTIONS", decision_notes="Round 2.")
    third = validate_success(
        api.resubmit_plan_review(
            review["id"],
            resubmit_plan_review_payload(
                floor_plan_reference="FP-PG1c", sterilization_area_sqft=34,
                has_handwash_sink=False,
            ),
            operator,
        )
    )
    assert third["cycle_count"] == 3

    decide_plan_review(review["id"], "REQUEST_CORRECTIONS", decision_notes="Round 3.")
    over_limit = api.resubmit_plan_review(
        review["id"],
        resubmit_plan_review_payload(
            floor_plan_reference="FP-PG1d", sterilization_area_sqft=36,
            has_handwash_sink=True,
        ),
        operator,
    )
    validate_error(over_limit, ApiErrorId.ERR_PLAN_REVIEW_CYCLE_LIMIT.value)
    assert over_limit.status_code == 409

    stored = validate_success(api.get_plan_review(review["id"], HO))
    assert stored["status"] == "CORRECTIONS_REQUIRED"
    assert stored["has_handwash_sink"] is False

    parent = validate_success(api.get_establishment(establishment["id"], HO))
    assert parent["plan_review_cycles_used"] == 3

    rows, meta = validate_paginated(
        api.list_plan_reviews(HO, params={"establishment_id": establishment["id"]})
    )
    assert meta["total_count"] == 1
