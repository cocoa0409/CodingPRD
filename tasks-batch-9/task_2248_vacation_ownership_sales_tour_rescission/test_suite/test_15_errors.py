"""Declared refusals: the 404 catalog, clock monotonicity and conflict scoping."""

from test_helpers import (
    TEST_USERS,
    UNKNOWN_UUID,
    ApiErrorId,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers import factories as fac
from test_helpers import fixtures as fx

CLOCK_START = "2026-08-01T00:00:00Z"
CHECK_IN_UTC = "2026-08-14T07:00:00Z"
SECOND_TOUR_UTC = "2026-08-15T07:00:00Z"
EXECUTION_UTC = "2026-08-14T09:00:00Z"
SECOND_EXECUTION_UTC = "2026-08-15T09:00:00Z"
POS_DELIVERED_AT = "2026-08-10T10:00:00Z"
FUNDING_UTC = "2026-08-25T00:00:00Z"

GALLERY = TEST_USERS["gallery_manager_headers"]
MARKETING = TEST_USERS["marketing_manager_headers"]
OFFICER_ALPHA = TEST_USERS["compliance_officer_headers"]
INTAKE = TEST_USERS["contract_administrator_headers"]
FUNDER = TEST_USERS["contract_admin_funder_headers"]
PLATFORM = TEST_USERS["platform_admin_headers"]
ANY_REP = TEST_USERS["sales_representative_headers"]


def test_each_collection_answers_an_unknown_identifier_with_its_own_code():
    """Twelve reads of the same unknown id return twelve distinct 404 identifiers.

    The PRD states: "Existence of path-parameter resources, validated strictly left to
    right, yielding HTTP 404 with the code for the *first* identifier in the path that
    does not resolve: `ERR_CHANNEL_NOT_FOUND`, `ERR_GALLERY_NOT_FOUND`,
    `ERR_REPRESENTATIVE_NOT_FOUND`, `ERR_PROSPECT_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`,
    `ERR_PRESENTATION_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
    `ERR_FINANCING_APPLICATION_NOT_FOUND`, `ERR_RESCISSION_REQUEST_NOT_FOUND`,
    `ERR_REFUND_DISBURSEMENT_NOT_FOUND`, `ERR_CLOSING_PACKAGE_NOT_FOUND` or
    `ERR_RETRAINING_ASSIGNMENT_NOT_FOUND`."

    The PRD states: "Existence of foreign keys supplied in a request body, validated in
    this declaration order and yielding HTTP 404 for the first one that does not
    resolve: `channel_id` yields `ERR_CHANNEL_NOT_FOUND`, `prospect_id` yields
    `ERR_PROSPECT_NOT_FOUND`, `gallery_id` yields `ERR_GALLERY_NOT_FOUND`, `booking_id`
    yields `ERR_BOOKING_NOT_FOUND`, `presentation_id` yields `ERR_PRESENTATION_NOT_FOUND`,
    `agreement_id` yields `ERR_AGREEMENT_NOT_FOUND`, `traded_in_agreement_id` also
    yields `ERR_AGREEMENT_NOT_FOUND`, `rescission_request_id` yields
    `ERR_RESCISSION_REQUEST_NOT_FOUND`, and `rep_id` yields
    `ERR_REPRESENTATIVE_NOT_FOUND`."

    The PRD states: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."

    The PRD states: "The `message` provides a human-readable explanation of what went
    wrong."

    The PRD states: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/errors/every_collection_has_its_own_not_found_error
    """
    fx.pin_clock(CLOCK_START)

    channel_response = api.get_tour_channel(UNKNOWN_UUID, MARKETING)
    validate_error(channel_response, ApiErrorId.ERR_CHANNEL_NOT_FOUND.value, 404)

    body = channel_response.json()
    assert set(body.keys()) == {"meta", "response_type", "data"}
    assert body["response_type"] == "error"
    assert set(body["data"].keys()) == {"error_id", "message"}
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
    assert isinstance(body["data"]["message"], str)

    validate_error(
        api.get_sales_gallery(UNKNOWN_UUID, GALLERY),
        ApiErrorId.ERR_GALLERY_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_sales_representative(UNKNOWN_UUID, GALLERY),
        ApiErrorId.ERR_REPRESENTATIVE_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_prospect(UNKNOWN_UUID, MARKETING),
        ApiErrorId.ERR_PROSPECT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_tour_booking(UNKNOWN_UUID, MARKETING),
        ApiErrorId.ERR_BOOKING_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_sales_presentation(UNKNOWN_UUID, OFFICER_ALPHA),
        ApiErrorId.ERR_PRESENTATION_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_purchase_agreement(UNKNOWN_UUID, INTAKE),
        ApiErrorId.ERR_AGREEMENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_financing_application(UNKNOWN_UUID, INTAKE),
        ApiErrorId.ERR_FINANCING_APPLICATION_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_rescission_request(UNKNOWN_UUID, INTAKE),
        ApiErrorId.ERR_RESCISSION_REQUEST_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_refund_disbursement(UNKNOWN_UUID, INTAKE),
        ApiErrorId.ERR_REFUND_DISBURSEMENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_closing_package(UNKNOWN_UUID, INTAKE),
        ApiErrorId.ERR_CLOSING_PACKAGE_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_retraining_assignment(UNKNOWN_UUID, OFFICER_ALPHA),
        ApiErrorId.ERR_RETRAINING_ASSIGNMENT_NOT_FOUND.value,
        404,
    )

    body_foreign_key = api.create_sales_representative(
        fac.create_sales_representative_payload(UNKNOWN_UUID), GALLERY
    )
    validate_error(body_foreign_key, ApiErrorId.ERR_GALLERY_NOT_FOUND.value, 404)


def test_the_clock_refuses_a_step_backwards_but_accepts_the_same_instant_again():
    """One second early is refused without moving the clock; the equal value succeeds.

    The PRD states: "The clock may only advance: a requested value earlier than the
    current value is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422)."

    The PRD states: "Setting the clock to a value equal to the current value is
    permitted."

    The PRD states: "The response reports `current_utc` (the clock after the call) and
    `previous_utc` (the clock before it), and no entity state changes as a result."

    The PRD states: "`created_at` (string): an ISO 8601 UTC timestamp with three
    fractional digits, fixed when the record is first written."

    Design: Corner/errors/logical_clock_rejects_backward_time_but_accepts_a_replay
    """
    fx.pin_clock(CLOCK_START)
    fx.pin_clock("2026-08-10T00:00:00Z")

    backwards = api.set_clock(
        fac.set_clock_payload("2026-08-09T23:59:59Z"), PLATFORM
    )
    validate_error(backwards, ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value, 422)

    prospect = fx.create_prospect()
    assert prospect["created_at"] == "2026-08-10T00:00:00.000Z"

    replay = validate_success(
        api.set_clock(fac.set_clock_payload("2026-08-10T00:00:00Z"), PLATFORM)
    )
    assert replay["current_utc"] == "2026-08-10T00:00:00.000Z"
    assert replay["previous_utc"] == "2026-08-10T00:00:00.000Z"


def test_a_presentation_holds_one_agreement_and_a_funded_one_refuses_intake():
    """The second execution and the post-funding notice are both refused as conflicts.

    The PRD states: "At most one agreement may exist per presentation, and a second
    attempt is rejected with `ERR_AGREEMENT_ALREADY_EXISTS`."

    The PRD states: "Intake requires the agreement's `fulfillment_status` to still be
    `AWAITING_FUNDING`; once the contract has been funded, intake is refused with
    `ERR_AGREEMENT_ALREADY_FUNDED`."

    The PRD states: "Funding advances `fulfillment_status` `AWAITING_FUNDING →
    FUNDED`, stamps `funded_at` from the logical clock, records the
    `funding_reference`, and sets `total_collected_cents` to `escrow_collected_cents`
    plus `collected_amount_cents`."

    Design: Corner/errors/duplicate_execution_and_post_funding_intake_conflicts
    """
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_executed_agreement(
        rep_count=1,
        issue_incentive_gift=False,
        check_in_at=CHECK_IN_UTC,
        execute_at=EXECUTION_UTC,
        booking_overrides={"scheduled_start_utc": CHECK_IN_UTC},
        agreement_overrides={
            "state_code": "FL",
            "purchase_price_cents": 3_200_000,
            "down_payment_cents": 320_000,
            "pos_delivered_at": POS_DELIVERED_AT,
        },
    )
    agreement = scene["agreement"]
    presentation_id = scene["presentation"]["id"]
    rep_id = scene["assigned_rep_id"]
    rep_headers = fx.make_sales_representative_headers(rep_id)

    application = fx.submit_financing(
        agreement["id"],
        rep_id,
        fx.read_agreement(agreement["id"])["version"],
        requested_amount_cents=3_019_980,
        applicant_fico=760,
        term_months=120,
    )
    fx.decide_financing(application["id"], "APPROVE")

    duplicate = api.create_purchase_agreement(
        fac.create_purchase_agreement_payload(
            presentation_id,
            product_type="RIGHT_TO_USE",
            state_code="NV",
            purchase_price_cents=2_400_000,
            down_payment_cents=240_000,
            pos_delivered_at="2026-08-12T10:00:00Z",
        ),
        rep_headers,
    )
    validate_error(duplicate, ApiErrorId.ERR_AGREEMENT_ALREADY_EXISTS.value, 409)

    rows, meta = validate_paginated(
        api.list_purchase_agreements(INTAKE, params={"presentation_id": presentation_id})
    )
    assert meta["total_count"] == 1
    assert rows[0]["product_type"] == "DEEDED_INTEREST"

    fx.pin_clock(FUNDING_UTC)
    fx.sweep_rescissions()
    funded = fx.fund_agreement(agreement["id"], 3_019_980)
    assert funded["fulfillment_status"] == "FUNDED"

    late_notice = api.create_rescission_request(
        fac.create_rescission_request_payload(agreement["id"], "HAND_DELIVERED"),
        INTAKE,
    )
    validate_error(late_notice, ApiErrorId.ERR_AGREEMENT_ALREADY_FUNDED.value, 409)

    intake_rows, intake_meta = validate_paginated(
        api.list_rescission_requests(INTAKE, params={"agreement_id": agreement["id"]})
    )
    assert intake_meta["total_count"] == 0
    assert intake_rows == []
    assert fx.read_agreement(agreement["id"])["rescission_status"] == "EXPIRED"


def test_the_active_retraining_conflict_is_keyed_by_representative_and_reason():
    """A second disclosure-gap assignment is refused while a claim-points one is created.

    The PRD states: "At most one assignment per representative per reason may sit in
    `ASSIGNED` or `IN_PROGRESS` at a time, and a duplicate is rejected with
    `ERR_RETRAINING_ALREADY_ACTIVE` — assignments with *different* reasons coexist
    freely."

    The PRD states: "A new assignment opens in `status` `ASSIGNED` with `cycle_index`
    1, `modules_completed` 0, `assigned_at` stamped from the logical clock,
    `started_at` and `closed_at` null, `strike_count_at_assignment` snapshotting the
    representative's current `compliance_strike_count`, and
    `cancellation_rate_at_assignment` snapshotting their current `cancellation_rate`
    when the reason is `CANCELLATION_RATE_BREACH` and null for the other two reasons."

    The PRD states: "Because cascade-created assignments are never returned to the
    triggering client, the assignment list — filterable by `rep_id`, `trigger_reason`
    and `status` — is the only channel through which they are discovered."

    Design: Corner/errors/retraining_already_active_is_scoped_to_the_trigger_reason
    """
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    representative = fx.create_representative(gallery["id"])

    first = fx.assign_retraining(
        representative["id"],
        fx.read_representative(representative["id"])["version"],
        "DISCLOSURE_GAP",
        required_module_count=4,
    )
    assert first["status"] == "ASSIGNED"
    assert first["cycle_index"] == 1
    assert first["cancellation_rate_at_assignment"] is None

    version_before = fx.read_representative(representative["id"])["version"]
    duplicate = api.create_retraining_assignment(
        fac.create_retraining_assignment_payload(
            representative["id"],
            version_before,
            "DISCLOSURE_GAP",
            required_module_count=6,
        ),
        OFFICER_ALPHA,
    )
    validate_error(duplicate, ApiErrorId.ERR_RETRAINING_ALREADY_ACTIVE.value, 409)
    assert fx.read_representative(representative["id"])["version"] == version_before
    assert fx.read_retraining_assignment(first["id"])["required_module_count"] == 4

    other_reason = fx.assign_retraining(
        representative["id"],
        version_before,
        "PROHIBITED_CLAIM_POINTS",
        required_module_count=4,
    )
    assert other_reason["trigger_reason"] == "PROHIBITED_CLAIM_POINTS"
    assert other_reason["status"] == "ASSIGNED"
    assert other_reason["cycle_index"] == 1

    rows, meta = validate_paginated(
        api.list_retraining_assignments(
            OFFICER_ALPHA, params={"rep_id": representative["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert {row["trigger_reason"] for row in rows} == {
        "DISCLOSURE_GAP",
        "PROHIBITED_CLAIM_POINTS",
    }


def test_a_surrender_of_an_unfunded_contract_is_refused_after_ownership_passes():
    """The same household is not enough: the surrendered contract must be delivered.

    The PRD states: "When a prior agreement is surrendered, two referential gates
    apply in order. The surrendered agreement's `prospect_id` must equal the new
    agreement's `prospect_id`, otherwise `ERR_TRADE_IN_OWNER_MISMATCH`; and the
    surrendered agreement must sit in `fulfillment_status` `DOCS_DELIVERED` with
    `rescission_status` `EXPIRED`, otherwise `ERR_TRADE_IN_NOT_ELIGIBLE`."

    The PRD states: "Trade-in eligibility of the surrendered agreement —
    `ERR_TRADE_IN_NOT_ELIGIBLE` (409), on `POST /purchase-agreements`. Note that
    ownership is checked before eligibility."

    The PRD states: "The household also carries a computed `is_existing_owner` flag,
    which starts false and becomes true as soon as at least one purchase agreement
    naming that household has a `fulfillment_status` of `FUNDED`, `RECORDED`,
    `DOCS_DELIVERED` or `TRADED_IN`."

    Design: Corner/errors/trade_in_surrender_requires_a_delivered_and_expired_agreement
    """
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    representative = fx.create_representative(gallery["id"])
    channel = fx.create_channel()
    prospect = fx.create_prospect()
    first_booking = fx.create_booking(
        channel["id"], prospect["id"], gallery["id"], scheduled_start_utc=CHECK_IN_UTC
    )
    second_booking = fx.create_booking(
        channel["id"], prospect["id"], gallery["id"], scheduled_start_utc=SECOND_TOUR_UTC
    )

    fx.pin_clock(CHECK_IN_UTC)
    fx.check_in(first_booking["id"], issue_incentive_gift=False)
    first_presentation = fx.open_presentation(first_booking["id"], representative["id"])
    fx.acknowledge_required_disclosures(first_presentation["id"], representative["id"])
    fx.review_presentation(first_presentation["id"], "CLEAR", OFFICER_ALPHA)
    fx.complete_presentation(first_presentation["id"], representative["id"])

    fx.pin_clock(EXECUTION_UTC)
    surrendered = fx.execute_agreement(
        first_presentation["id"],
        representative["id"],
        state_code="FL",
        purchase_price_cents=3_200_000,
        down_payment_cents=320_000,
        pos_delivered_at=POS_DELIVERED_AT,
    )

    fx.pin_clock(SECOND_TOUR_UTC)
    fx.check_in(second_booking["id"], issue_incentive_gift=False)
    second_presentation = fx.open_presentation(
        second_booking["id"], representative["id"], recorded_ack_reference="REC-0002"
    )
    fx.acknowledge_required_disclosures(second_presentation["id"], representative["id"])
    fx.review_presentation(second_presentation["id"], "CLEAR", OFFICER_ALPHA)
    fx.complete_presentation(second_presentation["id"], representative["id"])

    fx.pin_clock(SECOND_EXECUTION_UTC)
    refused = api.create_purchase_agreement(
        fac.create_purchase_agreement_payload(
            second_presentation["id"],
            state_code="FL",
            purchase_price_cents=4_200_000,
            down_payment_cents=420_000,
            pos_delivered_at="2026-08-13T10:00:00Z",
            traded_in_agreement_id=surrendered["id"],
        ),
        fx.make_sales_representative_headers(representative["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_TRADE_IN_NOT_ELIGIBLE.value, 409)

    rows, meta = validate_paginated(
        api.list_purchase_agreements(
            INTAKE, params={"presentation_id": second_presentation["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []

    unchanged = fx.read_agreement(surrendered["id"])
    assert unchanged["fulfillment_status"] == "AWAITING_FUNDING"
    assert unchanged["rescission_status"] == "OPEN"
    assert fx.read_prospect(prospect["id"])["is_existing_owner"] is False
