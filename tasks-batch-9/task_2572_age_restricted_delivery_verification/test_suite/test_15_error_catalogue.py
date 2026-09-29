"""Each failure code in the catalogue, reached by the request the PRD says raises it."""

from test_helpers import (
    ADMIN_HEADERS,
    NON_EXISTENT_UUID,
    OFFICER_A_HEADERS,
    OFFICER_B_HEADERS,
    OFFICER_B_USER_ID,
    ApiErrorId,
    assert_attempt_state,
    assert_case_state,
    assert_cents,
    assert_courier_gates,
    assert_order_states,
    assert_page_meta,
    assert_partner_gate,
    assert_plan_state,
    factories as f,
    fixtures as fx,
    make_courier_headers,
    make_customer_headers,
    make_partner_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

EPOCH = "2026-08-01T00:00:00Z"
CLOCK = "2026-08-20T12:00:00Z"
YESTERDAY = "2026-08-19T12:00:00Z"
EVENING = "2026-08-20T18:00:00Z"
LATER_EVENING = "2026-08-20T19:00:00Z"
LATEST_EVENING = "2026-08-20T20:00:00Z"
TOMORROW_EVENING = "2026-08-21T18:00:00Z"
NEXT_WEEK = "2026-08-27T12:00:00Z"
LATE_AUGUST = "2026-08-25T18:00:00Z"
BLOCK_HORIZON = "2026-09-19T20:00:00"
PLAN_DUE = "2026-09-15T12:00:00Z"
SEPTEMBER_END = "2026-09-30"

HAMPER_SKU = "GROCERY-P"
HAMPER_PRICE_CENTS = 6800


def _instant(value):
    """The instant a timestamp names, without the fractional digits of PRD 2.4."""
    assert value is not None, "the timestamp must not be null"
    return value.replace("Z", "").split(".")[0]


def _hamper(api):
    """One unrestricted pantry hamper priced at 6800 cents."""
    return fx.create_product(
        api,
        f.grocery_product_payload(
            sku=HAMPER_SKU, name="Premium Pantry Hamper", list_price_cents=HAMPER_PRICE_CENTS
        ),
    )


def test_01_every_path_identifier_has_its_own_not_found_code(api):
    """PRD 2.6: "The catalogue of not-found codes is one per entity:
    `ERR_JURISDICTION_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`,
    `ERR_PARTNER_NOT_FOUND`, `ERR_COURIER_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`,
    `ERR_ATTEMPT_NOT_FOUND`, `ERR_SHOPPER_TEST_NOT_FOUND`, `ERR_CASE_NOT_FOUND` and
    `ERR_PLAN_NOT_FOUND`."

    Design: Corner/errors/corner_every_path_id_probe_returns_its_own_not_found_error
    """
    probes = [
        (api.get_jurisdiction(NON_EXISTENT_UUID, ADMIN_HEADERS), ApiErrorId.JURISDICTION_NOT_FOUND),
        (api.get_restriction_policy(NON_EXISTENT_UUID, ADMIN_HEADERS), ApiErrorId.POLICY_NOT_FOUND),
        (api.get_customer(NON_EXISTENT_UUID, ADMIN_HEADERS), ApiErrorId.CUSTOMER_NOT_FOUND),
        (api.get_order_line(NON_EXISTENT_UUID, ADMIN_HEADERS), ApiErrorId.ORDER_LINE_NOT_FOUND),
        (api.get_delivery_partner(NON_EXISTENT_UUID, ADMIN_HEADERS), ApiErrorId.PARTNER_NOT_FOUND),
        (
            api.get_courier_certification(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ApiErrorId.CERTIFICATION_NOT_FOUND,
        ),
        (api.get_delivery_attempt(NON_EXISTENT_UUID, ADMIN_HEADERS), ApiErrorId.ATTEMPT_NOT_FOUND),
        (
            api.get_secret_shopper_test(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ApiErrorId.SHOPPER_TEST_NOT_FOUND,
        ),
        (api.get_violation_case(NON_EXISTENT_UUID, ADMIN_HEADERS), ApiErrorId.CASE_NOT_FOUND),
        (
            api.get_corrective_action_plan(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ApiErrorId.PLAN_NOT_FOUND,
        ),
    ]

    reported = []
    for response, expected in probes:
        validate_error(response, expected.value)
        body = response.json()
        assert body["response_type"] == "error", (
            f"a not-found read answers in the error envelope; got {body['response_type']!r}"
        )
        reported.append(body["data"]["error_id"])

    assert len(set(reported)) == len(probes), (
        "each entity owns its own not-found identifier, so ten probes report ten distinct "
        f"codes; got {reported}"
    )


def test_02_the_clock_may_stand_still_but_never_walk_backwards(api):
    """PRD 2.5: "A `PlatformAdmin` moves it by supplying a `current_utc` instant; moving
    the clock backwards is refused with `ERR_CLOCK_REWIND`, so the clock is monotonic for
    the lifetime of a server process."

    PRD 2.5: "The response reports `current_utc` together with
    `expired_identity_check_count`, `expired_certification_count` and
    `repostured_partner_count`, the last counting partners whose `posture` value actually
    changed during step three."

    Design: Corner/errors/corner_clock_may_stand_still_but_never_rewind
    """
    fx.set_clock(api, CLOCK)

    rewind = api.set_clock(f.clock_payload(YESTERDAY), ADMIN_HEADERS)

    validate_error(rewind, ApiErrorId.CLOCK_REWIND.value)
    standing_still = validate_success(api.set_clock(f.clock_payload(CLOCK), ADMIN_HEADERS))
    assert _instant(standing_still["current_utc"]) == _instant(CLOCK), (
        "re-setting the clock to the instant it already reads is admissible; got "
        f"{standing_still['current_utc']!r}"
    )
    assert standing_still["expired_identity_check_count"] == 0
    assert standing_still["expired_certification_count"] == 0
    assert standing_still["repostured_partner_count"] == 0


def test_03_every_natural_key_collision_reports_the_same_duplicate_code(api):
    """PRD 3.1: "Reusing a `code` that already exists is rejected with
    `ERR_DUPLICATE_CODE`."

    PRD 3.2: "A `PlatformAdmin` registers each customer with a `full_name`, an `email`
    that must be unique across all customers (a duplicate reports `ERR_DUPLICATE_CODE`),
    and a `jurisdiction_id` naming the customer's home and billing jurisdiction."

    Design: Corner/errors/corner_every_natural_key_collision_is_a_duplicate_code_conflict
    """
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    fx.create_product(api, f.wine_product_payload())
    customer = fx.create_customer(api, jurisdiction["id"])

    same_code = api.create_jurisdiction(
        f.jurisdiction_payload(
            code="US-NY", name="New York (duplicate)", dry_status="DRY", utc_offset_minutes=-300
        ),
        ADMIN_HEADERS,
    )
    same_sku = api.create_product(
        f.wine_product_payload(
            name="Cabernet 1.5L", restricted_units_per_item=3.00, list_price_cents=12000
        ),
        ADMIN_HEADERS,
    )
    same_email = api.create_customer(
        f.customer_payload(jurisdiction["id"], full_name="Ada L", email=customer["email"]),
        ADMIN_HEADERS,
    )

    for response in (same_code, same_sku, same_email):
        validate_error(response, ApiErrorId.DUPLICATE_CODE.value)
    for rows, meta in (
        validate_paginated(api.list_jurisdictions(ADMIN_HEADERS)),
        validate_paginated(api.list_products(ADMIN_HEADERS)),
        validate_paginated(api.list_customers(ADMIN_HEADERS)),
    ):
        assert len(rows) == 1, f"the collision stored nothing new; got {len(rows)} rows"
        assert_page_meta(meta, total_count=1)
    survivor = validate_success(api.get_jurisdiction(jurisdiction["id"], ADMIN_HEADERS))
    assert survivor["dry_status"] == "WET", (
        "the refused duplicate must not have overwritten the incumbent; got "
        f"{survivor['dry_status']!r}"
    )
    assert survivor["utc_offset_minutes"] == -240


def test_04_contradictory_field_pairs_are_inconsistent_rather_than_malformed(api):
    """PRD 3.1: "Its `delivery_window_start_minute` (from 0 through 1439) and
    `delivery_window_end_minute` (from 0 through 1440) bound the permitted local delivery
    hours on the minute axis described in 2.10; a policy whose two window minutes are equal
    is contradictory and is rejected with `ERR_INCONSISTENT_FIELDS`, as is a policy whose
    `effective_to` falls before its `effective_from`."

    PRD 3.2: "Each element of `source_signals` is an object with a `source_type` drawn from
    `GOVERNMENT_ID_DB`, `CREDIT_BUREAU`, `MOBILE_CARRIER` and `WATCHLIST_NEGATIVE`, plus a
    boolean `matched`; a given `source_type` may appear at most once, and a repeat is
    rejected with `ERR_INCONSISTENT_FIELDS`."

    Design: Corner/errors/corner_field_pairs_that_contradict_each_other_are_inconsistent_not_invalid
    """
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    customer = fx.create_customer(api, jurisdiction["id"])
    fx.attest_customer(api, customer["id"], f.ADULT_DOB)
    version_before = fx.read_customer(api, customer["id"])["version"]

    backwards_period = api.create_restriction_policy(
        f.restriction_policy_payload(
            jurisdiction["id"], effective_from="2026-08-31", effective_to="2026-08-01"
        ),
        ADMIN_HEADERS,
    )
    empty_window = api.create_restriction_policy(
        f.restriction_policy_payload(
            jurisdiction["id"], delivery_window_start_minute=600, delivery_window_end_minute=600
        ),
        ADMIN_HEADERS,
    )
    repeated_signal = api.create_identity_check(
        customer["id"],
        f.identity_check_payload(
            version_before,
            source_signals=[
                {"source_type": "GOVERNMENT_ID_DB", "matched": True},
                {"source_type": "GOVERNMENT_ID_DB", "matched": False},
            ],
        ),
        ADMIN_HEADERS,
    )

    for response in (backwards_period, empty_window, repeated_signal):
        validate_error(response, ApiErrorId.INCONSISTENT_FIELDS.value)
    assert validate_success(api.get_jurisdiction(jurisdiction["id"], ADMIN_HEADERS))[
        "active_policy_count"
    ] == 0, "neither contradictory policy was published"
    checks, meta = validate_paginated(api.list_identity_checks(customer["id"], ADMIN_HEADERS))
    assert checks == [], f"the refused pre-verification stored nothing; got {len(checks)}"
    assert_page_meta(meta, total_count=0)
    after = fx.read_customer(api, customer["id"])
    assert after["version"] == version_before, (
        "a refused identity check must not consume the customer's version; expected "
        f"{version_before}, got {after['version']}"
    )
    assert after["latest_identity_check_result"] == "NONE"


def test_05_a_case_opened_against_no_subject_at_all_is_refused(api):
    """PRD 3.9: "A manual case names the accountable `delivery_partner_id`, an asserted
    `severity` of `MINOR`, `MAJOR` or `CRITICAL`, a `summary` narrating the alleged
    violation, and exactly one subject: either a `delivery_attempt_id` or a
    `secret_shopper_test_id`, never both and never neither."

    Design: Corner/errors/corner_violation_case_needs_exactly_one_subject
    """
    fx.set_clock(api, CLOCK)
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )

    response = api.create_violation_case(
        f.violation_case_payload(
            partner["id"], severity="MAJOR", summary="Opened with no subject at all."
        ),
        OFFICER_A_HEADERS,
    )

    validate_error(response, ApiErrorId.CASE_SUBJECT_INVALID.value)
    assert_partner_gate(
        fx.read_partner(api, partner["id"]),
        posture="OPEN",
        open_case_count=0,
        open_critical_case_count=0,
        license_risk_score=0.00,
    )
    cases, meta = validate_paginated(
        api.list_violation_cases(OFFICER_A_HEADERS, {"delivery_partner_id": partner["id"]})
    )
    assert cases == [], f"the refused opening stored no case; got {len(cases)}"
    assert_page_meta(meta, total_count=0)


def test_06_submitting_an_order_that_has_no_lines_is_refused_on_its_own_code(api):
    """PRD 3.3: "An order with no lines at all cannot be submitted and reports
    `ERR_ORDER_HAS_NO_LINES`; an order whose `fulfillment_state` is anything other than
    `CREATED` reports `ERR_INVALID_ORDER_STATE`."

    Design: Corner/errors/corner_submitting_an_empty_order_is_a_conflict
    """
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Ada Lin")
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )
    order = fx.create_order(
        api, customer["id"], jurisdiction["id"], partner["id"], EVENING, 600
    )

    response = api.submit_order(order["id"], make_customer_headers(customer["id"]))

    validate_error(response, ApiErrorId.ORDER_HAS_NO_LINES.value)
    stored = fx.read_order(api, order["id"])
    assert_order_states(stored, compliance_state="DRAFT_UNVERIFIED", fulfillment_state="CREATED")
    assert_cents(stored["item_subtotal_cents"], 0, "item_subtotal_cents")
    assert_cents(stored["charged_cents"], 0, "charged_cents")
    assert stored["submitted_at"] is None, (
        f"an unsubmitted order carries no stamp; got {stored['submitted_at']!r}"
    )


def _one_case_under_investigation(api):
    """A manual `MINOR` case against a staged shopper probe, with round one counted."""
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Ada Lin")
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )
    courier = fx.create_courier(api, partner["id"], full_name="Dana Reyes")
    decoy = fx.create_order(
        api, customer["id"], jurisdiction["id"], partner["id"], TOMORROW_EVENING, 600
    )
    probe = fx.schedule_shopper_test(
        api,
        courier["id"],
        decoy["id"],
        scenario_type="INTOXICATION_CUES",
        scheduled_at=TOMORROW_EVENING,
    )
    case = fx.open_manual_case(
        api,
        partner["id"],
        secret_shopper_test_id=probe["id"],
        severity="MINOR",
        summary="Manual review of shopper staging.",
    )
    fx.investigate_case(api, case["id"], OFFICER_A_HEADERS)
    return {"partner": partner, "courier": courier, "probe": probe, "case": case}


def test_07_a_partner_response_deadline_at_or_behind_the_clock_is_refused(api):
    """PRD 3.9: "From `UNDER_INVESTIGATION` an officer may put questions to the accountable
    partner, moving `UNDER_INVESTIGATION → PENDING_PARTNER_RESPONSE`, recording an optional
    `notes` narrative and a `response_due_at` deadline that must lie strictly later than the
    logical clock now — a deadline at or before now is refused with
    `ERR_RESPONSE_DUE_NOT_FUTURE`."

    Design: Corner/errors/corner_partner_response_deadline_must_lie_in_the_future
    """
    world = _one_case_under_investigation(api)

    stale = api.request_partner_response(
        world["case"]["id"],
        f.request_partner_response_payload(YESTERDAY, notes="Deadline already gone."),
        OFFICER_A_HEADERS,
    )

    validate_error(stale, ApiErrorId.RESPONSE_DUE_NOT_FUTURE.value)
    refused = fx.read_case(api, world["case"]["id"])
    assert_case_state(refused, "UNDER_INVESTIGATION")
    assert refused["response_due_at"] is None, (
        f"the refused request stamped no deadline; got {refused['response_due_at']!r}"
    )

    asked = validate_success(
        api.request_partner_response(
            world["case"]["id"],
            f.request_partner_response_payload(NEXT_WEEK, notes="Seven days to respond."),
            OFFICER_A_HEADERS,
        )
    )

    assert_case_state(asked, "PENDING_PARTNER_RESPONSE")
    assert _instant(asked["response_due_at"]) == _instant(NEXT_WEEK)
    assert asked["origin"] == "MANUAL"
    assert asked["investigation_rounds"] == 1, (
        f"the refused request counted no round; got {asked['investigation_rounds']}"
    )


def test_08_attestation_alone_never_substitutes_for_pre_verification(api):
    """PRD 3.3: "First, the purchaser must be eligible, and the eligibility checks are
    evaluated in a fixed sub-order: the customer's `attestation_state` must be exactly
    `ATTESTED` (both `NOT_ATTESTED` and `ATTESTATION_REJECTED` report
    `ERR_ATTESTATION_REQUIRED`); then, if the customer's `blocked_until` is set and lies
    later than the logical clock now, the submission reports
    `ERR_CUSTOMER_DELIVERY_BLOCKED`; then the customer must have at least one identity check
    whose `status` is `VALID`, else `ERR_IDENTITY_PREVERIFICATION_REQUIRED`; and finally the
    completed age of the newest `VALID` check's `verified_dob`, measured as at the local
    calendar date of `scheduled_delivery_at` in the delivery jurisdiction, must be at least
    the largest `min_age_years` among the policies selected for this order, else
    `ERR_PURCHASER_UNDERAGE`."

    Design: Corner/errors/corner_restricted_order_without_a_valid_identity_check_is_rejected
    """
    world = fx.build_restricted_world(api, clock=CLOCK, with_identity_check=False)
    built = fx.add_restricted_order(api, world, quantity=1, scheduled_delivery_at=EVENING)

    response = api.submit_order(built["order"]["id"], world["customer_headers"])

    validate_error(response, ApiErrorId.IDENTITY_PREVERIFICATION_REQUIRED.value)
    customer = fx.read_customer(api, world["customer"]["id"])
    assert customer["attestation_state"] == "ATTESTED", (
        "the purchaser cleared the attestation gate and failed the next one; got "
        f"{customer['attestation_state']!r}"
    )
    assert customer["latest_identity_check_result"] == "NONE"
    stored = fx.read_order(api, built["order"]["id"])
    assert_order_states(stored, compliance_state="DRAFT_UNVERIFIED", fulfillment_state="CREATED")
    evaluation = validate_success(
        api.get_compliance_evaluation(built["order"]["id"], OFFICER_A_HEADERS)
    )
    assert evaluation["first_blocking_error_id"] == "ERR_IDENTITY_PREVERIFICATION_REQUIRED", (
        "the replay names the same first objection the submission raised; got "
        f"{evaluation['first_blocking_error_id']!r}"
    )
    assert evaluation["restriction_types"] == ["ALCOHOL"]
    assert evaluation["min_age_required"] == 21


def _one_courier_at_the_door(api, quantity=2):
    """A restricted order dispatched, with the clock and the courier both at the doorstep."""
    world = fx.build_restricted_world(api, clock=CLOCK)
    built = fx.build_dispatched_restricted_order(
        api, world, quantity=quantity, scheduled_delivery_at=EVENING
    )
    fx.set_clock(api, EVENING)
    attempt = fx.open_attempt(api, built["order"], world["courier"], EVENING)
    world.update({"order": built["order"], "line": built["line"], "attempt": attempt})
    return world


def test_09_the_document_sub_order_fails_twice_then_a_repeat_check_is_refused(api):
    """PRD 3.6: "Third, `document_expires_on` must be at or after the local calendar date of
    `started_at`; a document whose printed expiry falls strictly before that date reports
    `ERR_DOCUMENT_EXPIRED`, so a document expiring on the delivery date itself is still
    acceptable."

    PRD 3.6: "Fourth, `scanned_dob` must equal the purchaser's `attested_dob` exactly; any
    disagreement reports `ERR_RECIPIENT_IDENTITY_MISMATCH`."

    PRD 3.6: "The door-side identification check is the fork at the heart of the system, and
    only the courier named by the attempt's `courier_id` may record it, from `state`
    `INITIATED` only — from any other state it reports `ERR_INVALID_ATTEMPT_STATE`."

    Design: Corner/errors/corner_door_document_and_dob_failures_then_a_second_id_check_is_a_conflict
    """
    world = _one_courier_at_the_door(api)
    attempt_id = world["attempt"]["id"]
    courier_headers = world["courier_headers"]

    expired = api.record_id_check(
        attempt_id,
        f.id_check_payload(document_expires_on="2026-08-01", recipient_name="Ada Lin"),
        courier_headers,
    )
    mismatched = api.record_id_check(
        attempt_id,
        f.id_check_payload(scanned_dob="1999-01-01", recipient_name="Ada Lin"),
        courier_headers,
    )

    validate_error(expired, ApiErrorId.DOCUMENT_EXPIRED.value)
    validate_error(mismatched, ApiErrorId.RECIPIENT_IDENTITY_MISMATCH.value)
    assert_attempt_state(fx.read_attempt(api, attempt_id), "INITIATED")

    verified = validate_success(
        api.record_id_check(
            attempt_id,
            f.id_check_payload(scanned_dob=f.ADULT_DOB, recipient_name="Ada Lin"),
            courier_headers,
        )
    )

    assert_attempt_state(verified, "ID_VERIFIED")
    assert verified["recipient_age_years"] == 26, (
        "the recipient's completed age at the local doorstep date; got "
        f"{verified['recipient_age_years']!r}"
    )
    assert verified["id_check_compliant"] is True

    repeated = api.record_id_check(
        attempt_id,
        f.id_check_payload(
            document_type="PASSPORT", document_expires_on="2031-01-01", recipient_name="Ada Lin"
        ),
        courier_headers,
    )

    validate_error(repeated, ApiErrorId.INVALID_ATTEMPT_STATE.value)
    settled = fx.read_attempt(api, attempt_id)
    assert settled["document_type"] == "DRIVERS_LICENSE", (
        "the refused repeat must not have overwritten the recorded document; got "
        f"{settled['document_type']!r}"
    )
    assert fx.read_order(api, world["order"]["id"])["fulfillment_state"] == "OUT_FOR_DELIVERY"


def test_10_handover_needs_its_artefacts_and_a_verified_door_bars_an_age_refusal(api):
    """PRD 3.6: "The ordinary path is `ID_VERIFIED → HANDED_OVER`, which requires a
    `SIGNATURE` capture and a `PHOTO_HANDOFF` capture to already exist for the attempt, plus
    a `PHOTO_ID` capture whenever any selected policy has `requires_scan` true; a missing
    artefact reports `ERR_CAPTURE_INCOMPLETE`."

    PRD 3.6: "At most one capture of a given `kind` may exist per attempt, and a second of
    the same kind reports `ERR_DUPLICATE_CAPTURE_KIND`."

    PRD 3.7: "From `ID_VERIFIED`, where age has already been confirmed, the permitted
    reasons are `INTOXICATED_RECIPIENT`, `RECIPIENT_ABSENT` and `COURIER_FAULT` — an
    age-verified recipient who is visibly impaired must still be refused."

    Design: Corner/errors/corner_handover_capture_gates_and_a_disallowed_refusal_reason
    """
    world = _one_courier_at_the_door(api)
    attempt_id = world["attempt"]["id"]
    courier_headers = world["courier_headers"]
    fx.record_id_check(
        api, world["attempt"], world["courier"]["id"], scanned_dob=world["attested_dob"]
    )

    empty_handed = api.record_handover(
        attempt_id, f.handover_payload(recipient_name="Ada Lin"), courier_headers
    )
    signature = api.create_capture(
        attempt_id,
        f.capture_payload(kind="SIGNATURE", content_hash=f.SIGNATURE_HASH),
        courier_headers,
    )
    second_signature = api.create_capture(
        attempt_id,
        f.capture_payload(
            kind="SIGNATURE", content_hash=f.SPARE_HASH, captured_at="2026-08-20T18:06:00Z"
        ),
        courier_headers,
    )
    disallowed = api.record_refusal(
        attempt_id,
        f.refusal_payload("UNDERAGE_RECIPIENT", observed_indicators=["Courier changed their mind"]),
        courier_headers,
    )

    validate_error(empty_handed, ApiErrorId.CAPTURE_INCOMPLETE.value)
    stored_signature = validate_success(signature, expected_status=201)
    validate_error(second_signature, ApiErrorId.DUPLICATE_CAPTURE_KIND.value)
    validate_error(disallowed, ApiErrorId.REFUSAL_REASON_NOT_ALLOWED.value)
    captures, meta = validate_paginated(api.list_captures(attempt_id, courier_headers))
    assert len(captures) == 1, f"only the first signature was retained; got {len(captures)}"
    assert_page_meta(meta, total_count=1)
    assert captures[0]["kind"] == "SIGNATURE"
    assert captures[0]["content_hash"] == f.SIGNATURE_HASH
    assert stored_signature["content_hash"] == f.SIGNATURE_HASH
    attempt = fx.read_attempt(api, attempt_id)
    assert_attempt_state(attempt, "ID_VERIFIED")
    assert attempt["refusal_reason"] is None, (
        f"the disallowed reason was not recorded; got {attempt['refusal_reason']!r}"
    )
    order = fx.read_order(api, world["order"]["id"])
    assert order["fulfillment_state"] == "OUT_FOR_DELIVERY"
    assert order["final_restricted_units"] is None, (
        "the final exposure is written at handover alone, so an order that never handed "
        f"over keeps the null it opened with; got {order['final_restricted_units']!r}"
    )


def test_11_renewal_of_a_live_row_and_a_second_revocation_are_both_refused(api):
    """PRD 3.5: "Renewal requested against a row that is already `ACTIVE`, or that has been
    `REVOKED`, reports `ERR_INVALID_CERTIFICATION_STATE`."

    PRD 3.5: "Revocation is the `ComplianceOfficer`'s permanent act and is admissible from
    `ACTIVE`, `EXPIRED` or `SUSPENDED`; only an already-`REVOKED` row refuses it, with
    `ERR_INVALID_CERTIFICATION_STATE`."

    Design: Corner/errors/corner_renewing_an_active_certification_and_revoking_twice_are_conflicts
    """
    fx.set_clock(api, EPOCH)
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )
    courier = fx.create_courier(api, partner["id"], full_name="Dana Reyes")
    certification = fx.issue_certification(api, courier, training_score=92, valid_days=365)

    premature_renewal = api.renew_courier_certification(
        certification["id"],
        f.certification_renewal_payload(
            training_score=95, training_completed_at="2026-07-20", valid_days=365
        ),
        make_partner_manager_headers(partner["id"]),
    )

    validate_error(premature_renewal, ApiErrorId.INVALID_CERTIFICATION_STATE.value)
    live = fx.read_certification(api, certification["id"])
    assert live["state"] == "ACTIVE"
    assert live["renewal_count"] == 0, (
        f"the refused renewal counted nothing; got {live['renewal_count']}"
    )
    assert live["training_score"] == 92, (
        f"the refused renewal rewrote no score; got {live['training_score']}"
    )

    revoked = validate_success(
        api.revoke_courier_certification(
            certification["id"],
            f.certification_revocation_payload(revocation_reason="FALSIFIED_TRAINING_RECORD"),
            OFFICER_A_HEADERS,
        )
    )
    second_revocation = api.revoke_courier_certification(
        certification["id"],
        f.certification_revocation_payload(revocation_reason="FALSIFIED_TRAINING_RECORD"),
        OFFICER_A_HEADERS,
    )

    assert revoked["state"] == "REVOKED"
    assert revoked["revocation_reason"] == "FALSIFIED_TRAINING_RECORD"
    assert_courier_gates(
        fx.read_courier(api, courier["id"]),
        certification_state="UNCERTIFIED",
        dispatch_eligible=False,
    )
    validate_error(second_revocation, ApiErrorId.INVALID_CERTIFICATION_STATE.value)


def test_12_a_plan_can_only_be_verified_once_the_review_has_accepted_it(api):
    """PRD 3.9: "Review is the officer's first pass, admissible only from `SUBMITTED` and
    only while the parent case is still `SUBSTANTIATED`, and always subject to the
    segregation-of-duties rule of 2.1."

    PRD 3.9: "Transitions attempted from any other plan state report
    `ERR_INVALID_PLAN_STATE`."

    Design: Corner/errors/corner_verifying_a_plan_before_acceptance_is_a_conflict
    """
    world = _one_case_under_investigation(api)
    decided = fx.decide_case(
        api,
        world["case"]["id"],
        decision="SUBSTANTIATED",
        assessed_severity="MINOR",
        headers=OFFICER_A_HEADERS,
    )
    plan = fx.file_plan(
        api,
        decided,
        remediation_items=[
            "Retrain the courier on document checks",
            "Add a supervisor spot audit",
        ],
        due_at=PLAN_DUE,
    )

    too_early = api.verify_corrective_action_plan(
        plan["id"], f.plan_verify_payload("PASSED", notes="Too early."), OFFICER_B_HEADERS
    )

    validate_error(too_early, ApiErrorId.INVALID_PLAN_STATE.value)
    untouched = fx.read_plan(api, plan["id"])
    assert_plan_state(untouched, "SUBMITTED")
    assert untouched["verification_outcome"] is None, (
        f"the refused verification recorded no outcome; got {untouched['verification_outcome']!r}"
    )
    assert untouched["verified_by_user_id"] is None

    accepted = validate_success(
        api.review_corrective_action_plan(
            plan["id"], f.plan_review_payload("ACCEPT", notes="Plan looks adequate."), OFFICER_B_HEADERS
        )
    )
    verified = validate_success(
        api.verify_corrective_action_plan(
            plan["id"],
            f.plan_verify_payload("PASSED", notes="Remediation observed."),
            OFFICER_B_HEADERS,
        )
    )

    assert_plan_state(accepted, "ACCEPTED")
    assert_plan_state(verified, "VERIFIED")
    assert verified["verified_by_user_id"] == OFFICER_B_USER_ID
    assert verified["revision_round"] == 0, (
        f"the plan was never revised; got {verified['revision_round']}"
    )
    assert_case_state(fx.read_case(api, world["case"]["id"]), "CLOSED_VERIFIED")


def test_13_a_prohibited_class_and_a_damp_jurisdiction_fail_the_same_tier_differently(api):
    """PRD 3.3: "Per restriction class, and in this sub-order: a selected policy whose
    `permissibility` is `PROHIBITED` reports `ERR_DELIVERY_PROHIBITED_IN_JURISDICTION`; then
    an `ALCOHOL` class delivered into a jurisdiction whose `dry_status` is `DRY` reports
    `ERR_DRY_JURISDICTION_PROHIBITED`; then a jurisdiction whose `dry_status` is `DAMP`
    combined with a selected policy whose `permissibility` is anything other than
    `PERMIT_REQUIRED` reports `ERR_PERMIT_REQUIRED`."

    Design: Corner/errors/corner_prohibited_and_damp_jurisdictions_each_block_submit_differently
    """
    fx.set_clock(api, CLOCK)
    kansas = fx.create_jurisdiction(
        api, code="US-KS", name="Kansas", dry_status="WET", utc_offset_minutes=-300
    )
    arkansas = fx.create_jurisdiction(
        api, code="US-AR", name="Arkansas", dry_status="DAMP", utc_offset_minutes=-300
    )
    fx.create_policy(
        api,
        kansas["id"],
        permissibility="PROHIBITED",
        acceptable_document_types=["DRIVERS_LICENSE"],
    )
    fx.create_policy(
        api,
        arkansas["id"],
        permissibility="PERMITTED",
        acceptable_document_types=["DRIVERS_LICENSE"],
    )
    wine = fx.create_product(api, f.wine_product_payload())
    customer = fx.create_customer(api, kansas["id"], full_name="Ada Lin")
    fx.attest_customer(api, customer["id"], f.ADULT_DOB)
    fx.add_identity_check(
        api, customer["id"], provided_dob=f.ADULT_DOB, source_dob=f.ADULT_DOB
    )
    partner = fx.create_partner(
        api, legal_name="Plains Delivery", license_reference="KS-DEL-0001"
    )
    customer_headers = make_customer_headers(customer["id"])
    prohibited_order = fx.create_order(
        api, customer["id"], kansas["id"], partner["id"], EVENING, 600
    )
    fx.add_line(api, prohibited_order, wine["id"], 1)
    damp_order = fx.create_order(
        api, customer["id"], arkansas["id"], partner["id"], LATER_EVENING, 600
    )
    fx.add_line(api, damp_order, wine["id"], 1)

    prohibited = api.submit_order(prohibited_order["id"], customer_headers)
    damp = api.submit_order(damp_order["id"], customer_headers)

    validate_error(prohibited, ApiErrorId.DELIVERY_PROHIBITED_IN_JURISDICTION.value)
    validate_error(damp, ApiErrorId.PERMIT_REQUIRED.value)
    for order_id, expected in (
        (prohibited_order["id"], "ERR_DELIVERY_PROHIBITED_IN_JURISDICTION"),
        (damp_order["id"], "ERR_PERMIT_REQUIRED"),
    ):
        stored = fx.read_order(api, order_id)
        assert_order_states(
            stored, compliance_state="DRAFT_UNVERIFIED", fulfillment_state="CREATED"
        )
        assert_cents(stored["charged_cents"], 0, "charged_cents")
        evaluation = validate_success(api.get_compliance_evaluation(order_id, OFFICER_A_HEADERS))
        assert evaluation["first_blocking_error_id"] == expected, (
            "the replay names the objection this jurisdiction shape raises; got "
            f"{evaluation['first_blocking_error_id']!r}"
        )


def _one_dispatched_hamper_order(api, quantity=1, certify=True):
    """An unrestricted order dispatched, with the clock moved to the doorstep instant."""
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    hamper = _hamper(api)
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Ada Lin")
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )
    courier = fx.create_courier(api, partner["id"], full_name="Dana Reyes")
    certification = (
        fx.issue_certification(api, courier, valid_days=365) if certify else None
    )
    order = fx.create_order(
        api, customer["id"], jurisdiction["id"], partner["id"], EVENING, 600
    )
    line = fx.add_line(api, order, hamper["id"], quantity)
    submitted = fx.submit_order(api, order)
    dispatched = fx.dispatch_order(api, submitted)
    fx.set_clock(api, EVENING)
    return {
        "jurisdiction": jurisdiction,
        "hamper": hamper,
        "customer": customer,
        "partner": partner,
        "courier": courier,
        "certification": certification,
        "order": dispatched,
        "line": line,
        "courier_headers": make_courier_headers(courier["id"]),
        "partner_headers": make_partner_manager_headers(partner["id"]),
    }


def test_14_an_uncertified_courier_is_barred_even_from_an_unrestricted_doorstep(api):
    """PRD 3.6: "The courier's employing `delivery_partner_id` must equal the order's
    `delivery_partner_id`, else `ERR_COURIER_PARTNER_MISMATCH`; the courier's derived
    `certification_state` must be `CERTIFIED`, else `ERR_COURIER_NOT_CERTIFIED`; and the
    partner's `posture` must not be `SUSPENDED`, else `ERR_PARTNER_SUSPENDED`."

    Design: Corner/errors/corner_uncertified_courier_cannot_open_an_attempt
    """
    world = _one_dispatched_hamper_order(api, quantity=1, certify=False)
    arrival = f.delivery_attempt_payload(
        world["order"]["id"], world["courier"]["id"], EVENING
    )

    barred = api.create_delivery_attempt(arrival, world["courier_headers"])

    validate_error(barred, ApiErrorId.COURIER_NOT_CERTIFIED.value)
    assert_courier_gates(
        fx.read_courier(api, world["courier"]["id"]),
        certification_state="UNCERTIFIED",
        dispatch_eligible=False,
        compliance_score=100.00,
    )
    assert fx.read_order(api, world["order"]["id"])["fulfillment_state"] == "DISPATCHED"

    validate_success(
        api.create_courier_certification(
            f.courier_certification_payload(world["courier"]["id"], valid_days=365),
            world["partner_headers"],
        ),
        expected_status=201,
    )
    assert_courier_gates(
        fx.read_courier(api, world["courier"]["id"]),
        certification_state="CERTIFIED",
        dispatch_eligible=True,
    )
    attempt = validate_success(
        api.create_delivery_attempt(arrival, world["courier_headers"]), expected_status=201
    )

    assert_attempt_state(attempt, "INITIATED")
    assert fx.read_order(api, world["order"]["id"])["fulfillment_state"] == "OUT_FOR_DELIVERY"


def test_15_a_settlement_without_an_affirmative_restock_leaves_the_money_alone(api):
    """PRD 3.7: "The request carries `restock_confirmed`, which must be true; a settlement
    requested with it false is refused with `ERR_RESTOCK_NOT_CONFIRMED`."

    PRD 3.7: "Fourth, the fee itself: a refusal for `COURIER_FAULT` waives the restocking fee
    entirely and sets `restocking_fee_cents` to 0, and for every other reason the fee is the
    gross figure multiplied by the tier's basis points, divided by ten thousand, and
    **floored** to whole cents."

    PRD 3.7: "Every line of the order moves `line_state` `INCLUDED → WITHDRAWN`, the order's
    `final_restricted_units` is reset to 0.00, and the order's `fulfillment_state` advances
    `RETURN_IN_TRANSIT → RETURN_COMPLETED`."

    Design: Corner/errors/corner_return_settlement_demands_an_affirmative_restock_confirmation
    """
    world = _one_dispatched_hamper_order(api, quantity=3)
    attempt = fx.open_attempt(api, world["order"], world["courier"], EVENING)
    fx.record_refusal(
        api,
        attempt,
        world["courier"]["id"],
        "COURIER_FAULT",
        observed_indicators=["Vehicle breakdown"],
    )

    unconfirmed = api.create_return_settlement(
        world["order"]["id"], f.return_settlement_payload(restock_confirmed=False), ADMIN_HEADERS
    )

    validate_error(unconfirmed, ApiErrorId.RESTOCK_NOT_CONFIRMED.value)
    waiting = fx.read_order(api, world["order"]["id"])
    assert waiting["fulfillment_state"] == "RETURN_IN_TRANSIT"
    assert_cents(waiting["refunded_cents"], 0, "refunded_cents")
    assert_cents(waiting["retained_cents"], 0, "retained_cents")
    assert_cents(waiting["restocking_fee_cents"], 0, "restocking_fee_cents")
    held_line = validate_success(api.get_order_line(world["line"]["id"], ADMIN_HEADERS))
    assert held_line["line_state"] == "INCLUDED", (
        f"the refused settlement withdrew nothing; got {held_line['line_state']!r}"
    )

    settled = validate_success(
        api.create_return_settlement(
            world["order"]["id"], f.return_settlement_payload(restock_confirmed=True), ADMIN_HEADERS
        )
    )

    assert settled["fulfillment_state"] == "RETURN_COMPLETED"
    assert_cents(settled["refunded_cents"], 21000, "refunded_cents")
    assert_cents(settled["retained_cents"], 0, "retained_cents")
    released_line = validate_success(api.get_order_line(world["line"]["id"], ADMIN_HEADERS))
    assert released_line["line_state"] == "WITHDRAWN"


def _three_refusals_for_no_acceptable_document(api):
    """One purchaser whose three unrestricted deliveries were all refused at the door."""
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    fx.create_policy(api, jurisdiction["id"], effective_to=SEPTEMBER_END)
    hamper = _hamper(api)
    wine = fx.create_product(api, f.wine_product_payload())
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Ada Lin")
    fx.attest_customer(api, customer["id"], f.ADULT_DOB)
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )
    courier = fx.create_courier(api, partner["id"], full_name="Dana Reyes")
    fx.issue_certification(api, courier, valid_days=365)

    dispatched = []
    for promised in (EVENING, LATER_EVENING, LATEST_EVENING):
        order = fx.create_order(
            api, customer["id"], jurisdiction["id"], partner["id"], promised, 600
        )
        fx.add_line(api, order, hamper["id"], 1)
        dispatched.append(fx.dispatch_order(api, fx.submit_order(api, order)))

    for order, arrival in zip(dispatched, (EVENING, LATER_EVENING, LATEST_EVENING)):
        fx.set_clock(api, arrival)
        attempt = fx.open_attempt(api, order, courier, arrival)
        fx.record_refusal(
            api,
            attempt,
            courier["id"],
            "NO_ACCEPTABLE_ID",
            observed_indicators=["Recipient produced no document"],
        )

    fresh = fx.create_order(
        api, customer["id"], jurisdiction["id"], partner["id"], LATE_AUGUST, 600
    )
    fx.add_line(api, fresh, wine["id"], 1)
    return {
        "customer": customer,
        "partner": partner,
        "courier": courier,
        "refused_orders": dispatched,
        "fresh_order": fresh,
    }


def test_16_the_third_strike_blocks_the_purchaser_for_thirty_days(api):
    """PRD 3.7: "When that count reaches 3, the customer's `blocked_until` is set to the
    strike-triggering attempt's `started_at` plus 30 days, which is what the
    purchaser-eligibility check of 3.3 later reads to raise `ERR_CUSTOMER_DELIVERY_BLOCKED`."

    PRD 3.7: "**Link two** fires only when link one recorded a *compliance* refusal — that
    is, when `refusal_reason` is one of `UNDERAGE_RECIPIENT`, `ID_MISMATCH`,
    `NO_ACCEPTABLE_ID` or `INTOXICATED_RECIPIENT` — and opens a violation case
    automatically: its `origin` is `AUTO_REFUSAL`, its `delivery_attempt_id` names this
    attempt, its `delivery_partner_id` copies the order's, its `state` opens at `OPEN`, and
    its `severity` is read off a fixed mapping from the refusal reason —
    `UNDERAGE_RECIPIENT` maps to `CRITICAL`, `ID_MISMATCH` to `MAJOR`,
    `INTOXICATED_RECIPIENT` to `MAJOR` and `NO_ACCEPTABLE_ID` to `MINOR`."

    Design: Corner/errors/corner_three_recipient_refusals_block_the_customer_for_thirty_days
    """
    world = _three_refusals_for_no_acceptable_document(api)

    response = api.submit_order(
        world["fresh_order"]["id"], make_customer_headers(world["customer"]["id"])
    )

    validate_error(response, ApiErrorId.CUSTOMER_DELIVERY_BLOCKED.value)
    customer = fx.read_customer(api, world["customer"]["id"])
    assert customer["refusal_strikes"] == 3, (
        f"three counting refusals stand against the purchaser; got {customer['refusal_strikes']}"
    )
    assert _instant(customer["blocked_until"]) == BLOCK_HORIZON, (
        "the block runs 30 days from the third attempt's `started_at`; got "
        f"{customer['blocked_until']!r}"
    )
    assert customer["attestation_state"] == "ATTESTED", (
        "the block is not an attestation failure; got "
        f"{customer['attestation_state']!r}"
    )
    blocked = fx.read_order(api, world["fresh_order"]["id"])
    assert_order_states(blocked, compliance_state="DRAFT_UNVERIFIED", fulfillment_state="CREATED")
    assert_cents(blocked["charged_cents"], 0, "charged_cents")
    for order in world["refused_orders"]:
        assert fx.read_order(api, order["id"])["fulfillment_state"] == "RETURN_IN_TRANSIT"
    cases, meta = validate_paginated(
        api.list_violation_cases(
            OFFICER_A_HEADERS, {"delivery_partner_id": world["partner"]["id"]}
        )
    )
    assert len(cases) == 3, f"one case per compliance refusal; got {len(cases)}"
    assert_page_meta(meta, total_count=3)
    for case in cases:
        assert case["origin"] == "AUTO_REFUSAL"
        assert case["severity"] == "MINOR", (
            f"a `NO_ACCEPTABLE_ID` refusal is a `MINOR` case; got {case['severity']!r}"
        )
    assert_partner_gate(
        fx.read_partner(api, world["partner"]["id"]),
        posture="RESTRICTED",
        open_case_count=3,
        open_critical_case_count=0,
        license_risk_score=0.00,
    )


def test_17_the_error_envelope_differs_from_the_success_one_in_two_places(api):
    """PRD 2.2: "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."

    PRD 2.2: "The `response_type` is either "object" for a single resource or "array" for a
    list of resources."

    PRD 2.7: "Required fields present, JSON types correct, enum members recognised, declared
    numeric ranges respected, date and timestamp strings parseable, and `limit`/`offset`
    inside their bounds — otherwise `ERR_VALIDATION` with HTTP 400."

    Design: Corner/errors/corner_error_envelope_carries_response_type_error_with_id_and_message
    """
    fx.set_clock(api, EPOCH)

    refused = api.create_jurisdiction(
        f.jurisdiction_payload(
            code="US-NY", name="New York", dry_status="SOGGY", utc_offset_minutes=-240
        ),
        ADMIN_HEADERS,
    )

    validate_error(refused, ApiErrorId.VALIDATION.value)
    failure = refused.json()
    assert failure["response_type"] == "error"
    assert isinstance(failure["data"]["message"], str) and failure["data"]["message"], (
        f"a refusal explains itself; got {failure['data'].get('message')!r}"
    )
    assert "id" not in failure["data"], (
        f"a refusal mints no row; got keys {sorted(failure['data'])}"
    )
    assert failure["meta"]["api_request_id"].startswith("req_")
    assert failure["meta"]["api_request_timestamp"]
    rows, meta = validate_paginated(api.list_jurisdictions(ADMIN_HEADERS))
    assert rows == [], f"the refused registration stored nothing; got {len(rows)}"
    assert_page_meta(meta, total_count=0)

    accepted = api.create_jurisdiction(
        f.jurisdiction_payload(
            code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
        ),
        ADMIN_HEADERS,
    )

    created = validate_success(accepted, expected_status=201)
    success = accepted.json()
    assert success["response_type"] == "object", (
        f"one resource comes back as an object; got {success['response_type']!r}"
    )
    assert "error_id" not in success["data"], (
        f"a success carries no failure identifier; got keys {sorted(success['data'])}"
    )
    assert created["dry_status"] == "WET"
