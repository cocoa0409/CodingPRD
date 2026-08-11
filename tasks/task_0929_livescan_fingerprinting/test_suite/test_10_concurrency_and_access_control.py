"""Optimistic concurrency on the three parent rows, plus authentication and role gates."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    code_position_exception,
    create_agency_payload,
    create_invoice_payload,
    create_ori_payload,
    finalize_card,
    headers_without_auth,
    make_applicant_headers,
    mark_no_show,
    new_agency,
    new_applicant,
    new_appointment,
    pass_positions,
    post_result,
    set_clock,
    setup_open_card,
    setup_registry,
    setup_finalized_card,
    state_response_of,
    transmit_card,
    validate_error,
    validate_paginated,
    validate_success,
)

VA = TEST_USERS["vendor_admin_headers"]
TECH = TEST_USERS["technician_headers"]
ADJ = TEST_USERS["adjudicator_headers"]


def _card_whose_version_moved_during_capture():
    world = setup_open_card(clock_start="2026-06-01T09:00:00Z")
    world["version_at_creation"] = world["card"]["version"]
    pass_positions(world["card"]["id"], 80)
    world["card"] = finalize_card(world["card"]["id"])
    return world


def test_transmitting_on_a_pre_capture_card_version_is_rejected(api):
    """PRD 2.7: "- `POST /livescan/submissions` requires `expected_card_version`, carrying the
    client's last observed `version` of the `FingerprintCard` named by `card_id`. If that number does
    not equal the card's current `version`, the transmission is rejected with `ERR_STALE_VERSION` and
    HTTP 412."
    PRD 2.5: "**Recording a scored attempt** — the position row bumps once and the card bumps once,
    on every attempt, including an attempt that does not change any aggregate. This is why a client
    holding a card version from before a capture round cannot transmit that card."

    Design: Corner/cross_cutting_complexity_layers/transmit_with_pre_finalize_card_version_returns_412
    """
    world = _card_whose_version_moved_during_capture()
    assert world["version_at_creation"] < world["card"]["version"]

    response = api.create_submission(
        {
            "card_id": world["card"]["id"],
            "retention_requested": False,
            "expected_card_version": world["version_at_creation"],
        },
        TECH,
    )

    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)

    _rows, meta = validate_paginated(api.list_submissions(TECH, {"card_id": world["card"]["id"]}))
    assert meta["total_count"] == 0


def test_transmitting_on_the_current_card_version_succeeds(api):
    """PRD 2.7: "A card legitimately accepts more than one transmission over its life, and its
    `version` advances on every scored attempt, every exception coding, every override and every
    finalize, so a create built on a stale view of the card would otherwise mint a duplicate
    transaction control number for the same print."
    PRD 3.5: "Acceptance moves the card `READY_FOR_SUBMISSION → SUBMITTED`, moves its appointment
    `IN_CAPTURE → COMPLETED`, adds one to the capture site's `billable_print_count`, creates the
    submission row, and creates exactly one fee assessment for it."

    Design: Corner/cross_cutting_complexity_layers/transmit_with_pre_finalize_card_version_returns_412
    """
    world = _card_whose_version_moved_during_capture()
    api.create_submission(
        {
            "card_id": world["card"]["id"],
            "retention_requested": False,
            "expected_card_version": world["version_at_creation"],
        },
        TECH,
    )

    submission = validate_success(
        api.create_submission(
            {
                "card_id": world["card"]["id"],
                "retention_requested": False,
                "expected_card_version": world["card"]["version"],
            },
            TECH,
        ),
        201,
    )

    assert submission["state_status"] == "PENDING"

    card = validate_success(api.get_card(world["card"]["id"], TECH), 200)
    assert card["status"] == "SUBMITTED"

    _rows, meta = validate_paginated(api.list_submissions(TECH, {"card_id": world["card"]["id"]}))
    assert meta["total_count"] == 1


def _submission_whose_version_moved_on_the_state_result():
    world = setup_finalized_card(clock_start="2026-06-01T09:00:00Z", score=80)
    world["submission"] = transmit_card(world["card"]["id"], world["card"]["version"])
    world["version_at_transmission"] = world["submission"]["version"]
    world["submission"] = post_result(
        world["submission"]["id"], "STATE", "ACCEPTED", record_count=0, disqualifying_offense_count=0
    )
    return world


def test_issuing_a_determination_on_a_pre_result_submission_version_is_rejected(api):
    """PRD 2.7: "- `POST /livescan/fitness-determinations` requires `expected_submission_version`,
    carrying the client's last observed `version` of the `Submission` named by `submission_id`. A
    mismatch with the submission's current `version` is rejected with `ERR_STALE_VERSION` and HTTP
    412."

    Design: Corner/cross_cutting_complexity_layers/determination_with_pre_result_submission_version_returns_412
    """
    world = _submission_whose_version_moved_on_the_state_result()
    assert world["version_at_transmission"] < world["submission"]["version"]

    response = api.create_fitness_determination(
        {
            "submission_id": world["submission"]["id"],
            "outcome": "FIT",
            "expected_submission_version": world["version_at_transmission"],
        },
        ADJ,
    )

    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)


def test_the_retried_determination_pins_the_routed_state_response(api):
    """PRD 3.6: "Issuance pins `basis_response_id` to the submission's `STATE` criminal-history
    response whose `routing_status` is `ROUTED`, copies `ori_id` from the submission, stamps
    `issued_by_user_id` with the acting `X-User-ID` and `issued_at` with the logical clock, and
    starts the determination at `status` `ISSUED` with `challenge_count` 0, `challenge_filed_at` null
    and `resolved_by_user_id` null."

    Design: Corner/cross_cutting_complexity_layers/determination_with_pre_result_submission_version_returns_412
    """
    world = _submission_whose_version_moved_on_the_state_result()
    api.create_fitness_determination(
        {
            "submission_id": world["submission"]["id"],
            "outcome": "FIT",
            "expected_submission_version": world["version_at_transmission"],
        },
        ADJ,
    )

    determination = validate_success(
        api.create_fitness_determination(
            {
                "submission_id": world["submission"]["id"],
                "outcome": "FIT",
                "expected_submission_version": world["submission"]["version"],
            },
            ADJ,
        ),
        201,
    )

    assert determination["status"] == "ISSUED"
    assert determination["outcome"] == "FIT"
    assert determination["issued_by_user_id"] == "adj-01"
    assert determination["challenge_count"] == 0
    assert determination["basis_response_id"] == state_response_of(world["submission"]["id"])["id"]


def test_a_second_invoice_on_the_pre_create_agency_version_is_rejected(api):
    """PRD 2.7: "- `POST /livescan/invoices` requires `expected_agency_version`, carrying the
    client's last observed `version` of the `Agency` named by `agency_id`. A mismatch with the
    agency's current `version` is rejected with `ERR_STALE_VERSION` and HTTP 412."
    PRD 2.5: "**Opening an invoice** — one new invoice at `version` 1. The agency bumps once."

    Design: Corner/cross_cutting_complexity_layers/second_invoice_with_pre_create_agency_version_returns_412
    """
    world = setup_registry(
        clock_start="2026-06-01T09:00:00Z",
        agency_overrides={"payer_regime_default": "AGENCY_BILLED"},
        with_device=False,
    )
    applicant = new_applicant(full_name="Ula Wren")
    appointment = new_appointment(
        applicant["id"], world["site"]["id"], world["service_type"]["id"], "2026-06-01T10:00:00Z"
    )
    mark_no_show(appointment["id"], "2026-06-01T10:20:00Z")

    agency_before = validate_success(api.get_agency(world["agency"]["id"], VA), 200)

    first = validate_success(
        api.create_invoice(
            create_invoice_payload(world["agency"]["id"], agency_before["version"], "2026-06"), VA
        ),
        201,
    )
    assert first["status"] == "DRAFT"

    second = api.create_invoice(
        create_invoice_payload(world["agency"]["id"], agency_before["version"], "2026-07"), VA
    )
    validate_error(second, ApiErrorId.ERR_STALE_VERSION.value)

    _rows, meta = validate_paginated(api.list_invoices(VA, {"agency_id": world["agency"]["id"]}))
    assert meta["total_count"] == 1

    agency_after = validate_success(api.get_agency(world["agency"]["id"], VA), 200)
    assert agency_after["version"] == agency_before["version"] + 1


def test_a_technician_is_not_authorized_to_grant_the_override(api):
    """PRD 2.1: "If `X-User-Role` carries a string that is not one of those six, or carries one of
    the six but that role is not listed for the endpoint being called in the endpoint table of §4,
    the request is rejected with `ERR_UNAUTHORIZED` and HTTP 403. Role membership is checked
    immediately after authentication and before any resource in the path is looked up, so a caller
    with the wrong role receives 403 rather than 404 even when the resource named in the path does
    not exist."

    Design: Corner/rbac/technician_cannot_grant_the_exception_override
    """
    world = setup_open_card(clock_start="2026-06-01T09:00:00Z")
    code_position_exception(world["card"]["id"], "R_THUMB", "AMPUTATED")

    response = api.grant_exception_override(world["card"]["id"], "self service", TECH)

    error = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)
    assert error["error_id"] != ApiErrorId.ERR_CARD_STATE_INVALID.value
    assert error["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value

    card = validate_success(api.get_card(world["card"]["id"], TECH), 200)
    assert card["exception_override_by_user_id"] is None


def test_an_applicant_may_not_register_an_ori(api):
    """PRD 2.1: "- `VendorAdmin` — vendor operations. Registers agencies, ORIs, service types,
    capture sites and devices; records calibrations and runs calibration audits; opens, issues and
    settles invoices; decides purge requests; drives the nightly batch and the logical clock."
    PRD 2.1: "If `X-User-Role` carries a string that is not one of those six, or carries one of the
    six but that role is not listed for the endpoint being called in the endpoint table of §4, the
    request is rejected with `ERR_UNAUTHORIZED` and HTTP 403."

    Design: Corner/rbac/applicant_cannot_create_an_ori
    """
    set_clock("2026-06-01T09:00:00Z")
    agency = new_agency()
    applicant = new_applicant(full_name="Rex Alder")

    response = api.create_ori(
        create_ori_payload(agency["id"]), make_applicant_headers(applicant["id"])
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

    _rows, meta = validate_paginated(api.list_oris(VA, {"agency_id": agency["id"]}))
    assert meta["total_count"] == 0


def test_a_request_without_the_two_headers_is_unauthenticated(api):
    """PRD 2.1: "Every request to every endpoint — reads included — must carry two headers:
    `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role that principal
    is acting in. If either header is absent, or is present but empty, the request is rejected with
    `ERR_UNAUTHENTICATED` and HTTP 401. This check runs before anything else, including before the
    server looks at the URL's resource identifiers."

    Design: Corner/rbac/request_with_missing_header_returns_unauthenticated
    """
    set_clock("2026-06-01T09:00:00Z")

    response = api.create_agency(
        create_agency_payload(name="Headerless", account_code="ACC-NH"), headers_without_auth()
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
