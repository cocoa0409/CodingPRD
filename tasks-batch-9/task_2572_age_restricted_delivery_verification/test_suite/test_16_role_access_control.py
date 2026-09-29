"""Who may call what, and whose identity a call is measured against."""

from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    NON_EXISTENT_UUID,
    OFFICER_A_HEADERS,
    OFFICER_A_USER_ID,
    OFFICER_B_HEADERS,
    OFFICER_B_USER_ID,
    ApiErrorId,
    assert_attempt_state,
    assert_case_state,
    assert_confidence_equal,
    assert_courier_gates,
    assert_order_states,
    assert_page_meta,
    assert_plan_state,
    factories as f,
    fixtures as fx,
    ids_of,
    make_courier_headers,
    make_customer_headers,
    make_partner_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-20T12:00:00Z"
EVENING = "2026-08-20T18:00:00Z"
CAPTURE_MOMENT = "2026-08-20T18:05:00Z"
PROBE_MOMENT = "2026-08-20T19:00:00Z"
TOMORROW_EVENING = "2026-08-21T18:00:00Z"
PLAN_DUE = "2026-09-15T12:00:00Z"


def _instant(value):
    """The instant a timestamp names, without the fractional digits of PRD 2.4."""
    assert value is not None, "the timestamp must not be null"
    return value.replace("Z", "").split(".")[0]


def test_01_four_calls_by_the_wrong_role_are_all_turned_away_at_tier_two(api):
    """PRD 2.7: "**Role authorisation.** The caller's role must be listed for the endpoint,
    else `ERR_UNAUTHORIZED` with HTTP 403."

    PRD 2.7: "**Body foreign-key existence.** Every foreign key in the request body must
    resolve, in the endpoint's declared field order, else the corresponding not-found code
    with HTTP 404."

    Design: Corner/rbac/corner_cross_role_exclusive_operations_are_unauthorized
    """
    world = fx.build_unrestricted_world(api, quantity=1)
    fx.submit_order(api, world["order"])

    by_the_purchaser = api.create_jurisdiction(
        f.jurisdiction_payload(
            code="US-NJ", name="New Jersey", dry_status="WET", utc_offset_minutes=-240
        ),
        world["customer_headers"],
    )
    by_the_partner = api.create_violation_case(
        f.violation_case_payload(
            world["partner"]["id"],
            delivery_attempt_id=NON_EXISTENT_UUID,
            severity="MINOR",
            summary="Self-opened case.",
        ),
        world["partner_headers"],
    )
    by_the_courier = api.dispatch_order(world["order"]["id"], world["courier_headers"])
    by_the_auditor = api.create_order(
        f.order_payload(
            world["customer"]["id"],
            world["jurisdiction"]["id"],
            world["partner"]["id"],
            TOMORROW_EVENING,
            600,
        ),
        AUDITOR_HEADERS,
    )

    for response in (by_the_purchaser, by_the_partner, by_the_courier, by_the_auditor):
        validate_error(response, ApiErrorId.UNAUTHORIZED.value)
    assert by_the_partner.status_code == 403, (
        "the role objection outranks the unresolvable `delivery_attempt_id` in the body; "
        f"got HTTP {by_the_partner.status_code}"
    )
    _, jurisdictions_meta = validate_paginated(api.list_jurisdictions(ADMIN_HEADERS))
    assert_page_meta(jurisdictions_meta, total_count=1)
    _, cases_meta = validate_paginated(
        api.list_violation_cases(
            OFFICER_A_HEADERS, {"delivery_partner_id": world["partner"]["id"]}
        )
    )
    assert_page_meta(cases_meta, total_count=0)
    assert fx.read_order(api, world["order"]["id"])["fulfillment_state"] == "SUBMITTED", (
        "the courier's dispatch attempt moved nothing"
    )
    _, orders_meta = validate_paginated(
        api.list_orders(ADMIN_HEADERS, {"customer_id": world["customer"]["id"]})
    )
    assert_page_meta(orders_meta, total_count=1)


def test_02_every_role_gets_through_the_operations_that_are_its_own(api):
    """PRD 4: "| `POST` | `/customers/{id}/age-attestation` | Records the customer's
    self-attested date of birth and derives the resulting attestation state; an under-age
    attestation is recorded rather than refused. | Customer |"

    PRD 3.8: "The `verdict` is derived by comparison: `PASS` when `observed_outcome` equals
    `expected_outcome`, and `FAIL` when it does not, with `recorded_at` stamped from the
    logical clock."

    PRD 3.3: "The first branch is the unrestricted shortcut. When the order's
    `restriction_types` is empty — every line's product is classified `NONE` — the compliance
    dimension moves `DRAFT_UNVERIFIED → AUTO_CLEARED`, `provisional_restricted_units` is set
    to 0.00 and `applied_policy_ids` stays empty."

    Design: Corner/rbac/corner_each_role_can_perform_its_own_exclusive_operations
    """
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    hamper = fx.create_product(
        api,
        f.grocery_product_payload(
            sku="GROCERY-P", name="Premium Pantry Hamper", list_price_cents=6800
        ),
    )
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Ada Lin")
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )
    customer_headers = make_customer_headers(customer["id"])
    partner_headers = make_partner_manager_headers(partner["id"])

    attested = validate_success(
        api.record_age_attestation(
            customer["id"],
            f.attestation_payload(f.ADULT_DOB, attestation_channel="MOBILE_APP"),
            customer_headers,
        )
    )
    courier = validate_success(
        api.create_courier(f.courier_payload(partner["id"], full_name="Dana Reyes"), partner_headers),
        expected_status=201,
    )
    courier_headers = make_courier_headers(courier["id"])
    validate_success(
        api.create_courier_certification(
            f.courier_certification_payload(courier["id"], valid_days=365), partner_headers
        ),
        expected_status=201,
    )
    validate_success(
        api.create_identity_check(
            customer["id"],
            f.identity_check_payload(attested["version"]),
            OFFICER_A_HEADERS,
        ),
        expected_status=201,
    )
    order = validate_success(
        api.create_order(
            f.order_payload(
                customer["id"], jurisdiction["id"], partner["id"], EVENING, 600
            ),
            customer_headers,
        ),
        expected_status=201,
    )
    validate_success(
        api.create_order_line(
            order["id"], f.order_line_payload(hamper["id"], 1), customer_headers
        ),
        expected_status=201,
    )
    validate_success(api.submit_order(order["id"], customer_headers))
    validate_success(api.dispatch_order(order["id"], partner_headers))
    fx.set_clock(api, EVENING)
    attempt = validate_success(
        api.create_delivery_attempt(
            f.delivery_attempt_payload(order["id"], courier["id"], EVENING), courier_headers
        ),
        expected_status=201,
    )
    validate_success(
        api.create_capture(
            attempt["id"],
            f.capture_payload(captured_at=CAPTURE_MOMENT),
            courier_headers,
        ),
        expected_status=201,
    )
    probe = validate_success(
        api.create_secret_shopper_test(
            f.secret_shopper_test_payload(
                courier["id"],
                order["id"],
                scenario_type="NO_ID_PRESENTED",
                scheduled_at=PROBE_MOMENT,
                expected_outcome="REFUSAL",
            ),
            AUDITOR_HEADERS,
        ),
        expected_status=201,
    )
    recorded = validate_success(
        api.record_shopper_outcome(
            probe["id"],
            f.shopper_outcome_payload("REFUSAL", findings="Courier followed the script."),
            AUDITOR_HEADERS,
        )
    )
    case = validate_success(
        api.create_violation_case(
            f.violation_case_payload(
                partner["id"],
                secret_shopper_test_id=probe["id"],
                severity="MINOR",
                summary="Documentation follow-up.",
            ),
            OFFICER_A_HEADERS,
        ),
        expected_status=201,
    )
    investigated = validate_success(api.investigate_case(case["id"], OFFICER_A_HEADERS))

    assert fx.read_customer(api, customer["id"])["attestation_state"] == "ATTESTED"
    assert fx.read_customer(api, customer["id"])["latest_identity_check_result"] == "MATCH"
    assert_courier_gates(
        fx.read_courier(api, courier["id"]),
        certification_state="CERTIFIED",
        compliance_score=100.00,
    )
    assert_order_states(
        fx.read_order(api, order["id"]),
        compliance_state="AUTO_CLEARED",
        fulfillment_state="OUT_FOR_DELIVERY",
    )
    assert_attempt_state(fx.read_attempt(api, attempt["id"]), "INITIATED")
    assert recorded["verdict"] == "PASS", (
        f"the observed outcome matched what was expected; got {recorded['verdict']!r}"
    )
    assert _instant(recorded["recorded_at"]) == _instant(EVENING), (
        f"the outcome is stamped from the logical clock; got {recorded['recorded_at']!r}"
    )
    assert_case_state(investigated, "UNDER_INVESTIGATION")
    assert investigated["origin"] == "MANUAL"


def test_03_a_partner_manager_may_only_dispatch_the_orders_of_their_own_partner(api):
    """PRD 2.7: "A `PartnerManager` caller may only touch delivery-partner rows, couriers,
    courier certifications, orders and violation cases whose owning `delivery_partner_id`
    equals `X-User-ID`. A `Courier` caller may only touch delivery attempts whose
    `courier_id` equals `X-User-ID`. A violation yields `ERR_FORBIDDEN_RESOURCE_SCOPE` with
    HTTP 403."

    PRD 3.3: "On success the order's `fulfillment_state` becomes `DISPATCHED`,
    `dispatched_at` is stamped from the logical clock, and `hold_reason` is cleared."

    Design: Corner/rbac/corner_partner_manager_cannot_dispatch_another_partners_order
    """
    world = fx.build_unrestricted_world(api, quantity=1)
    other_partner = fx.create_partner(
        api, legal_name="Harbor Courier Co", license_reference="NY-DEL-0002"
    )
    fx.submit_order(api, world["order"])

    by_the_neighbour = api.dispatch_order(
        world["order"]["id"], make_partner_manager_headers(other_partner["id"])
    )

    validate_error(by_the_neighbour, ApiErrorId.FORBIDDEN_RESOURCE_SCOPE.value)
    waiting = fx.read_order(api, world["order"]["id"])
    assert waiting["fulfillment_state"] == "SUBMITTED"
    assert waiting["dispatched_at"] is None, (
        f"the refused dispatch stamped nothing; got {waiting['dispatched_at']!r}"
    )

    accepted = validate_success(
        api.dispatch_order(world["order"]["id"], world["partner_headers"])
    )

    assert accepted["fulfillment_state"] == "DISPATCHED"
    assert _instant(accepted["dispatched_at"]) == _instant(CLOCK), (
        f"`dispatched_at` comes from the logical clock; got {accepted['dispatched_at']!r}"
    )


def test_04_only_the_courier_named_by_the_attempt_may_record_its_id_check(api):
    """PRD 2.7: "A `Courier` caller may only touch delivery attempts whose `courier_id`
    equals `X-User-ID`. A violation yields `ERR_FORBIDDEN_RESOURCE_SCOPE` with HTTP 403."

    PRD 3.6: "The door-side identification check is the fork at the heart of the system, and
    only the courier named by the attempt's `courier_id` may record it, from `state`
    `INITIATED` only — from any other state it reports `ERR_INVALID_ATTEMPT_STATE`."

    Design: Corner/rbac/corner_courier_cannot_record_the_id_check_on_another_couriers_attempt
    """
    world = fx.build_restricted_world(api)
    courier_a = world["courier"]
    courier_b = fx.create_courier(api, world["partner"]["id"], full_name="Sam Okafor")
    fx.issue_certification(api, courier_b, training_score=90, valid_days=365)
    built = fx.build_dispatched_restricted_order(
        api, world, quantity=1, scheduled_delivery_at=EVENING
    )
    fx.set_clock(api, EVENING)
    attempt = fx.open_attempt(api, built["order"], courier_a, started_at=EVENING)
    document = f.id_check_payload(recipient_name="Ada Lin")

    by_the_colleague = api.record_id_check(
        attempt["id"], document, make_courier_headers(courier_b["id"])
    )

    validate_error(by_the_colleague, ApiErrorId.FORBIDDEN_RESOURCE_SCOPE.value)
    untouched = fx.read_attempt(api, attempt["id"])
    assert_attempt_state(untouched, "INITIATED")
    assert untouched["document_type"] is None, (
        f"the refused check wrote no document fields; got {untouched['document_type']!r}"
    )

    verified = validate_success(
        api.record_id_check(attempt["id"], document, make_courier_headers(courier_a["id"]))
    )

    assert_attempt_state(verified, "ID_VERIFIED")
    assert verified["courier_id"] == courier_a["id"]
    assert_courier_gates(
        fx.read_courier(api, courier_b["id"]), compliant_handover_count=0
    )


def test_05_the_officer_who_substantiated_the_case_may_neither_review_nor_verify(api):
    """PRD 2.7: "**Segregation of duties.** On corrective-action-plan review and on
    corrective-action-plan verification only, `X-User-ID` must not equal the parent violation
    case's `substantiated_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES` with HTTP 403."

    PRD 3.9: "Its `decision` field carries `ACCEPT`, moving the plan `SUBMITTED → ACCEPTED`,
    or `REQUEST_REVISION`, moving it `SUBMITTED → REVISION_REQUESTED`; an optional `notes`
    narrative is recorded, and in both branches the acting `X-User-ID` is stored in
    `reviewed_by_user_id`."

    PRD 3.9: "A `PASSED` outcome moves the plan `ACCEPTED → VERIFIED` and drives the parent
    case `SUBSTANTIATED → CLOSED_VERIFIED`, which halves that case's contribution through the
    verified-remediation credit factor of 0.50, recomputes both of the partner's risk-score
    variants, and re-derives the partner's `posture` — the mechanism by which a partner
    earns its way back from `SUSPENDED` to `RESTRICTED` or from `RESTRICTED` to `OPEN`."

    Design: Corner/rbac/corner_the_substantiating_officer_cannot_review_or_verify_the_plan
    """
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
        scenario_type="EXPIRED_DOCUMENT",
        scheduled_at=TOMORROW_EVENING,
        expected_outcome="REFUSAL",
    )
    case = fx.build_substantiated_case(
        api,
        partner["id"],
        secret_shopper_test_id=probe["id"],
        severity="MAJOR",
        officer_headers=OFFICER_A_HEADERS,
    )
    plan = fx.file_plan(api, case, due_at=PLAN_DUE)
    assert case["substantiated_by_user_id"] == OFFICER_A_USER_ID, (
        f"officer_a owns the substantiation; got {case['substantiated_by_user_id']!r}"
    )

    self_review = api.review_corrective_action_plan(
        plan["id"], f.plan_review_payload("ACCEPT", notes="Self review attempt."), OFFICER_A_HEADERS
    )

    validate_error(self_review, ApiErrorId.SEGREGATION_OF_DUTIES.value)
    unreviewed = fx.read_plan(api, plan["id"])
    assert_plan_state(unreviewed, "SUBMITTED")
    assert unreviewed["reviewed_by_user_id"] is None, (
        f"the refused review recorded no reviewer; got {unreviewed['reviewed_by_user_id']!r}"
    )

    accepted = validate_success(
        api.review_corrective_action_plan(
            plan["id"],
            f.plan_review_payload("ACCEPT", notes="Independent review."),
            OFFICER_B_HEADERS,
        )
    )

    assert_plan_state(accepted, "ACCEPTED")
    assert accepted["reviewed_by_user_id"] == OFFICER_B_USER_ID

    self_verify = api.verify_corrective_action_plan(
        plan["id"],
        f.plan_verify_payload("PASSED", notes="Self verification attempt."),
        OFFICER_A_HEADERS,
    )

    validate_error(self_verify, ApiErrorId.SEGREGATION_OF_DUTIES.value)
    unverified = fx.read_plan(api, plan["id"])
    assert_plan_state(unverified, "ACCEPTED")
    assert unverified["verified_by_user_id"] is None, (
        "the refused verification recorded no verifier; got "
        f"{unverified['verified_by_user_id']!r}"
    )

    verified = validate_success(
        api.verify_corrective_action_plan(
            plan["id"],
            f.plan_verify_payload("PASSED", notes="Independent verification."),
            OFFICER_B_HEADERS,
        )
    )

    assert_plan_state(verified, "VERIFIED")
    assert verified["verified_by_user_id"] == OFFICER_B_USER_ID
    assert_case_state(fx.read_case(api, case["id"]), "CLOSED_VERIFIED")


def test_06_the_admin_and_the_officer_share_one_pre_verification_endpoint(api):
    """PRD 3.2: "Pre-verification is somebody else's act: a `PlatformAdmin` or a
    `ComplianceOfficer` runs an identity check on the customer's behalf against an external
    data source."

    PRD 3.2: "Each new check is stored with `status` of `VALID` and an `expires_at` of its own
    `created_at` plus `validity_days` days, and it demotes every earlier check of that
    customer whose `status` was `VALID` to `SUPERSEDED`."

    PRD 3.2: "The customer's `latest_identity_check_result` is then re-derived as the `result`
    of whichever of that customer's checks has `status` of `VALID` and the greatest
    `created_at`, falling back to `NONE` when no such row exists, and the customer's `version`
    advances by one."

    Design: Corner/rbac/corner_identity_check_creation_is_shared_by_admin_and_officer
    """
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Ada Lin")
    attested = fx.attest_customer(api, customer["id"], f.ADULT_DOB)
    first_version = attested["version"]

    by_the_admin = api.create_identity_check(
        customer["id"],
        f.identity_check_payload(
            first_version,
            provider="TELCO_VERIFY",
            source_signals=f.source_signals(
                government_id_db=True,
                credit_bureau=False,
                mobile_carrier=False,
                watchlist_negative=False,
            ),
        ),
        ADMIN_HEADERS,
    )
    thin = validate_success(by_the_admin, expected_status=201)

    assert fx.read_customer(api, customer["id"])["version"] == first_version + 1, (
        "storing a check advances the purchaser's `version`, which is why the officer's call "
        "must quote the newer number"
    )

    by_the_officer = api.create_identity_check(
        customer["id"],
        f.identity_check_payload(first_version + 1, provider="STATE_DMV_GATEWAY"),
        OFFICER_A_HEADERS,
    )
    full = validate_success(by_the_officer, expected_status=201)

    assert_confidence_equal(thin["confidence"], 0.5000)
    assert thin["result"] == "NO_MATCH", (
        f"a lone government-database match bands below 0.6000; got {thin['result']!r}"
    )
    assert_confidence_equal(full["confidence"], 0.8500)
    assert full["result"] == "MATCH"
    assert full["status"] == "VALID"
    rows, meta = validate_paginated(api.list_identity_checks(customer["id"], OFFICER_A_HEADERS))
    assert_page_meta(meta, total_count=2)
    superseded = next(row for row in rows if row["id"] == thin["id"])
    assert superseded["status"] == "SUPERSEDED", (
        f"the newer check demoted the older one; got {superseded['status']!r}"
    )
    assert fx.read_customer(api, customer["id"])["latest_identity_check_result"] == "MATCH"
    valid_rows, valid_meta = validate_paginated(
        api.list_identity_checks(customer["id"], ADMIN_HEADERS, {"status": "VALID"})
    )
    assert_page_meta(valid_meta, total_count=1)
    assert ids_of(valid_rows) == [full["id"]]
