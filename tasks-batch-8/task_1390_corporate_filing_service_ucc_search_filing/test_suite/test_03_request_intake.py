"""Filing-request intake: structural validation, office determination, intake gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_attempt,
    approve_preparation,
    create_attempt_payload,
    create_draft_attempt,
    create_filing_request,
    create_filing_request_payload,
    create_in_review_request,
    create_ready_request,
    get_request,
    make_filing_specialist_headers,
    order_lien_search,
    setup_active_initial_filing,
    setup_client_world,
    submit_attempt,
    submit_intake,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]


def test_create_request_missing_required_field_rejected(api):
    """PRD §2.9: "Required fields are present, types are correct, and enum members are
    valid, including the conditionally required ones: a request whose `kind` is not
    `NEW_UCC1` must carry `target_filing_id` (its absence yields
    `ERR_TARGET_FILING_REQUIRED`) and `expected_target_filing_version`; an amendment
    attempt must carry `amendment_scope`; a collateral-scope amendment must carry both
    `collateral_change_op` and `collateral_text`; an initial-filing attempt must carry
    `collateral_text`. Other structural violations surface as `ERR_INVALID_REQUEST`
    (400)."
    PRD §3.2: "A `FilingSpecialist` intakes a filing request by providing `client_id`,
    `kind` (`NEW_UCC1`, `AMENDMENT`, `CONTINUATION`, or `TERMINATION`), `debtor_id`,
    `secured_party_id`, `jurisdiction_code`, `collateral_class`, and
    `fee_authorization_cents`".

    Design: Corner/entities/create_request_missing_required_field_rejected
    """
    world = setup_client_world()
    payload = create_filing_request_payload(
        debtor_id=world["debtor"]["id"],
        secured_party_id=world["secured_party"]["id"],
    )  # client_id deliberately omitted
    resp = api.create_filing_request(payload, SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_request_with_invalid_enum_rejected(api):
    """PRD §2.9: "Required fields are present, types are correct, and enum members are
    valid, including the conditionally required ones: a request whose `kind` is not
    `NEW_UCC1` must carry `target_filing_id` (its absence yields
    `ERR_TARGET_FILING_REQUIRED`) and `expected_target_filing_version`; an amendment
    attempt must carry `amendment_scope`; a collateral-scope amendment must carry both
    `collateral_change_op` and `collateral_text`; an initial-filing attempt must carry
    `collateral_text`. Other structural violations surface as `ERR_INVALID_REQUEST`
    (400)."

    Design: Corner/entities/create_request_with_invalid_enum_rejected
    """
    world = setup_client_world()
    payload = create_filing_request_payload(
        client_id=world["client"]["id"],
        debtor_id=world["debtor"]["id"],
        secured_party_id=world["secured_party"]["id"],
        collateral_class="LEASEHOLD",
    )
    resp = api.create_filing_request(payload, SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_ucc3_without_target_rejected(api):
    """PRD §2.9: "a request whose `kind` is not `NEW_UCC1` must carry
    `target_filing_id` (its absence yields `ERR_TARGET_FILING_REQUIRED`) and
    `expected_target_filing_version`".

    Design: Corner/validations/ucc3_without_target_rejected
    """
    world = setup_client_world()
    payload = create_filing_request_payload(
        client_id=world["client"]["id"],
        kind="CONTINUATION",
        debtor_id=world["debtor"]["id"],
        secured_party_id=world["secured_party"]["id"],
    )
    resp = api.create_filing_request(payload, SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_TARGET_FILING_REQUIRED)


def test_initial_states_assigned_on_create(api):
    """PRD §3.2: "A new request lands in `DRAFT_INTAKE`."
    PRD §3.7: "A new search starts in `ORDERED`, and its terminal outcomes are
    `COMPLETED`, `VERIFIED`, and `DISCREPANCY`."
    PRD §3.4: "The new attempt starts with `effectiveness_status` of `DRAFT` and
    `reflection_status` of `UNVERIFIED`, and a `CREATED` event is appended to its
    trail."

    Design: Corner/state_machines/initial_states_assigned_on_create
    """
    world = setup_client_world()
    request = create_filing_request(world["client"], world["debtor"], world["secured_party"])
    assert request["status"] == "DRAFT_INTAKE", (
        f"request must land in DRAFT_INTAKE, got {request['status']}"
    )
    assert request.get("filing_office") is None, (
        "the filing-office determination has not run before submit-intake"
    )
    search = order_lien_search(world["client"], world["debtor"])
    assert search["status"] == "ORDERED", (
        f"search must start ORDERED, got {search['status']}"
    )
    ready = create_ready_request(world["client"], world["debtor"], world["secured_party"])
    attempt = create_draft_attempt(ready["id"])
    assert attempt["effectiveness_status"] == "DRAFT"
    assert attempt["reflection_status"] == "UNVERIFIED"


def test_county_required_when_office_county(api):
    """PRD §3.2: "At this moment the system determines `filing_office`: it becomes
    `COUNTY` exactly when the request's `collateral_class` is a member of the resolved
    profile's `county_filing_collateral_classes`, and `STATE` otherwise. A `COUNTY`
    resolution demands that `county_name` be present (otherwise `ERR_COUNTY_REQUIRED`)
    and that it be a member of the profile's `county_names` (otherwise
    `ERR_COUNTY_NOT_IN_JURISDICTION`)."

    Design: Corner/validations/county_required_when_office_county
    """
    world = setup_client_world()
    request = create_filing_request(
        world["client"], world["debtor"], world["secured_party"],
        collateral_class="FIXTURE")
    resp = api.submit_intake(request["id"], make_filing_specialist_headers("spec-1"))
    validate_error(resp, ApiErrorId.ERR_COUNTY_REQUIRED)
    assert get_request(request["id"])["status"] == "DRAFT_INTAKE", (
        "a failed intake must leave the request in DRAFT_INTAKE"
    )


def test_county_not_in_jurisdiction(api):
    """PRD §3.2: "A `COUNTY` resolution demands that `county_name` be present
    (otherwise `ERR_COUNTY_REQUIRED`) and that it be a member of the profile's
    `county_names` (otherwise `ERR_COUNTY_NOT_IN_JURISDICTION`)."

    Design: Corner/validations/county_not_in_jurisdiction
    """
    world = setup_client_world()
    request = create_filing_request(
        world["client"], world["debtor"], world["secured_party"],
        collateral_class="FIXTURE", county_name="MARIN")
    resp = api.submit_intake(request["id"], make_filing_specialist_headers("spec-1"))
    validate_error(resp, ApiErrorId.ERR_COUNTY_NOT_IN_JURISDICTION)


def test_double_submit_intake_rejected(api):
    """PRD §3.2: "Submitting intake — a capability shared by `FilingSpecialist` and
    `FilingReviewer` — moves the request from `DRAFT_INTAKE` to `IN_REVIEW`."
    PRD §2.9: "the request is in a valid from-state for the requested transition
    (`ERR_REQUEST_INVALID_STATE`, or `ERR_REQUEST_IN_PROCESS` for cancellation during
    processing)".

    Design: Corner/state_machines/double_submit_intake_rejected
    """
    world = setup_client_world()
    request = create_in_review_request(world["client"], world["debtor"],
                                       world["secured_party"])
    resp = api.submit_intake(request["id"], make_filing_specialist_headers("spec-1"))
    validate_error(resp, ApiErrorId.ERR_REQUEST_INVALID_STATE)
    assert get_request(request["id"])["status"] == "IN_REVIEW"


def test_attempt_create_rejected_while_request_in_review(api):
    """PRD §3.4: "Once a request is `READY`, a `FilingSpecialist` creates a filing
    attempt under it — any other request status yields `ERR_REQUEST_NOT_READY`."

    Design: Difficulty/cross_entity_state_dependency/attempt_create_requires_request_ready
    """
    world = setup_client_world()
    request = create_in_review_request(world["client"], world["debtor"],
                                       world["secured_party"])
    resp = api.create_attempt(request["id"], create_attempt_payload(), SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_READY)
    assert get_request(request["id"])["status"] == "IN_REVIEW", (
        "the rejected attempt creation must not move the request"
    )


def test_attempt_create_rejected_while_request_draft_intake(api):
    """PRD §3.4: "Once a request is `READY`, a `FilingSpecialist` creates a filing
    attempt under it — any other request status yields `ERR_REQUEST_NOT_READY`."

    Design: Difficulty/cross_entity_state_dependency/attempt_create_requires_request_ready
    """
    world = setup_client_world()
    request = create_filing_request(world["client"], world["debtor"],
                                    world["secured_party"])
    resp = api.create_attempt(request["id"], create_attempt_payload(), SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_READY)
    assert get_request(request["id"])["status"] == "DRAFT_INTAKE"


def test_submit_intake_blocked_for_suspended_client(api):
    """PRD §3.2: "The client's `status` must be `ACTIVE`; submitting intake under a
    `SUSPENDED` client fails with `ERR_CLIENT_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/intake_requires_client_active
    """
    world = setup_client_world()
    request = create_filing_request(world["client"], world["debtor"],
                                    world["secured_party"])
    validate_success(api.suspend_client(world["client"]["id"], ADMIN), expected_status=200)
    resp = api.submit_intake(request["id"], make_filing_specialist_headers("spec-1"))
    validate_error(resp, ApiErrorId.ERR_CLIENT_SUSPENDED)
    assert get_request(request["id"])["status"] == "DRAFT_INTAKE", (
        "the suspended gate must leave the request untouched"
    )


def test_suspension_does_not_disturb_in_flight_work(api):
    """PRD §3.1: "Suspension is a narrow gate: it blocks only the intake submission of
    filing requests (§3.2), and it never touches in-flight requests or filings, which
    run to completion undisturbed."

    Design: Difficulty/cross_entity_state_dependency/intake_requires_client_active
    """
    world = setup_client_world()
    request = create_ready_request(world["client"], world["debtor"],
                                   world["secured_party"])
    attempt = create_draft_attempt(request["id"])
    submit_attempt(attempt["id"])
    validate_success(api.suspend_client(world["client"]["id"], ADMIN), expected_status=200)
    filing = accept_attempt(attempt["id"], filing_number="CA-2026-0001",
                            filed_at="2026-08-01T00:00:00Z")
    assert filing["effectiveness_status"] == "ACTIVE", (
        "an in-flight attempt must run to completion under a suspended client"
    )
    assert get_request(request["id"])["status"] == "FULFILLED"
