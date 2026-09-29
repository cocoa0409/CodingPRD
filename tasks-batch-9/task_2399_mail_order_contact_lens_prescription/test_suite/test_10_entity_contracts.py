"""Entity-level contracts: creation echoes, snapshots, defaults, system fields,
type and enum domains, foreign-key resolution, append-only audit rows, derived
ledger projections and list pagination.
"""

from test_helpers import (
    ADMIN_HEADERS,
    CO_ALPHA_HEADERS,
    DEFAULT_CLOCK_UTC,
    UNKNOWN_CUSTOMER_UUID,
    UNKNOWN_ORDER_UUID,
    UNKNOWN_PLAN_UUID,
    WORKING_TUESDAY_10AM,
    ApiErrorId,
    assert_common_fields,
    assert_compliance_event,
    assert_customer_ledger,
    assert_insurance_plan,
    assert_ledger_values,
    assert_order,
    assert_pagination_meta,
    assert_prescription,
    assert_timestamp_equals,
    assert_verification_request,
    create_order_payload,
    create_prescription_payload,
    create_reimbursement_claim_payload,
    create_return_request_payload,
    get_ledger,
    is_valid_uuid,
    make_customer_headers,
    new_customer,
    new_insurance_plan,
    new_prescription,
    new_product,
    set_clock,
    setup_delivered_order,
    setup_order_on_verified_prescription,
    setup_pending_verification_prescription,
    setup_reference_data,
    setup_verified_prescription,
    validate_error,
    validate_paginated,
    validate_success,
)

# The full set of plan input fields, used where the contract is that every
# declared field is echoed back unchanged.
FULL_PLAN_PAYLOAD = {
    "name": "VisionOne",
    "network_status": "OUT_OF_NETWORK",
    "annual_allowance_cents": 15000,
    "coinsurance_rate": 0.20,
    "requires_itemized_receipt": False,
    "covers_shipping": False,
    "claim_window_days": 90,
    "plan_year_start_month_day": "01-01",
    "status": "ACTIVE",
}

# A plan carrying only the four fields the PRD makes mandatory, so every
# optional field must fall back to its declared default.
MINIMAL_PLAN_PAYLOAD = {
    "name": "BareBones",
    "network_status": "OUT_OF_NETWORK",
    "annual_allowance_cents": 10000,
    "coinsurance_rate": 0.10,
}


def _three_draft_prescriptions(customer_id: str, product_id: str) -> None:
    """Three DRAFT prescriptions for one patient over disjoint validity
    intervals, so the overlap rule never enters the picture."""
    new_prescription(
        customer_id,
        product_id,
        document_reference="scan-1",
        issue_date="2026-07-01",
        expiry_date="2027-07-01",
    )
    new_prescription(
        customer_id,
        product_id,
        document_reference="scan-2",
        issue_date="2027-07-01",
        expiry_date="2028-07-01",
    )
    new_prescription(
        customer_id,
        product_id,
        document_reference="scan-3",
        issue_date="2028-07-01",
        expiry_date="2029-07-01",
    )


class TestInsurancePlanContract:
    def test_plan_creation_echoes_every_declared_field_with_system_properties(self, api):
        """PRD §3.1: "A **vision plan** is registered with a `name` for display and a
        `network_status` of either `IN_NETWORK` or `OUT_OF_NETWORK`."

        PRD §3.1: "The plan's money rules are `annual_allowance_cents`, the maximum
        eligible spend reimbursed per plan year, which must be zero or greater, and
        `coinsurance_rate`, the member's share applied to whatever eligible spend
        sits above the allowance."

        PRD §2.4: "`id` — a server-minted UUID with no type prefix."

        PRD §2.4: "`created_at` — an ISO 8601 UTC timestamp with three fractional
        digits, fixed at creation."

        PRD §2.4: "`version` — an integer that starts at 1 on creation and
        increments by one on every mutation of the row."

        PRD §4: "Operations that create a new stand-alone resource, or that add a
        new distinct resource to a collection, return `201 Created`."

        Design: Corner/entities/insurance_plan_creation_returns_all_declared_input_fields
        """
        set_clock(DEFAULT_CLOCK_UTC)

        created = validate_success(
            api.create_insurance_plan(dict(FULL_PLAN_PAYLOAD), ADMIN_HEADERS), 201
        )

        assert_insurance_plan(created)
        assert created["name"] == "VisionOne"
        assert created["network_status"] == "OUT_OF_NETWORK"
        assert created["annual_allowance_cents"] == 15000
        assert float(created["coinsurance_rate"]) == 0.20
        assert created["claim_window_days"] == 90
        assert created["plan_year_start_month_day"] == "01-01"

        assert is_valid_uuid(created["id"])
        assert created["version"] == 1
        assert_timestamp_equals(created["created_at"], "2026-08-01T00:00:00.000Z")
        assert_timestamp_equals(created["updated_at"], "2026-08-01T00:00:00.000Z")

        reread = validate_success(api.get_insurance_plan(created["id"], ADMIN_HEADERS))
        for field in (
            "id",
            "name",
            "network_status",
            "annual_allowance_cents",
            "claim_window_days",
            "plan_year_start_month_day",
            "version",
            "created_at",
            "updated_at",
        ):
            assert reread[field] == created[field], (
                f"GET must return the stored {field}, got {reread[field]!r}"
            )
        assert float(reread["coinsurance_rate"]) == 0.20

    def test_plan_optional_fields_fall_back_to_declared_defaults(self, api):
        """PRD §3.1: "Four optional fields shape the paperwork:
        `requires_itemized_receipt`, which defaults to true and, when true, forces
        claim generation to find a receipt identifier on the order;
        `covers_shipping`, which defaults to false and, when false, excludes the
        order's shipping charge from the base eligible spend; `claim_window_days`,
        the number of days after delivery within which a claim may be generated,
        defaulting to 90; and `plan_year_start_month_day`, the `MM-DD` anchor of
        the plan year, defaulting to `01-01`."

        PRD §3.1: "A plan's `status` is `ACTIVE` or `RETIRED` and defaults to
        `ACTIVE`; retiring a plan flips it to `RETIRED`, after which claim creation
        and claim generation against it are both refused with `ERR_PLAN_RETIRED`."

        Design: Corner/entities/insurance_plan_defaults_applied_when_optional_fields_omitted
        """
        set_clock(DEFAULT_CLOCK_UTC)

        created = validate_success(
            api.create_insurance_plan(dict(MINIMAL_PLAN_PAYLOAD), ADMIN_HEADERS), 201
        )

        assert created["requires_itemized_receipt"] is True
        assert created["covers_shipping"] is False
        assert created["claim_window_days"] == 90
        assert created["plan_year_start_month_day"] == "01-01"
        assert created["status"] == "ACTIVE"


class TestOrderSnapshotContract:
    def test_order_read_returns_the_price_snapshot_taken_at_creation(self, api):
        """PRD §3.5: "The ordered product's `unit_price_cents` and `lenses_per_box`
        are copied onto the order as `unit_price_cents` and
        `lenses_per_box_at_capture`, and `fulfilled_product_id` is initialised to
        the same value as `ordered_product_id`."

        PRD §3.5: "`subtotal_cents` is the snapshotted `unit_price_cents`
        multiplied by total boxes."

        PRD §3.5: "`shipping_cents` is zero when `subtotal_cents` has reached the
        free-shipping threshold of 5,000 cents — fifty dollars, and the comparison
        is inclusive, so a subtotal of exactly 5,000 cents ships free — and is
        otherwise the flat standard charge of 695 cents."

        PRD §3.5: "`total_cents` is `subtotal_cents` plus `shipping_cents`."

        PRD §3.5: "Its `verification_state` is seeded from the prescription:
        `RX_CLEARED` when the prescription is already `VERIFIED_ACTIVE`, and
        `RX_PENDING` otherwise."

        PRD §3.5: "An order also carries fields it does not yet use at creation:
        `substitution_type` starts at `NONE`, `parameter_deviation_index` starts at
        0.00, `fulfilled_od_sphere` and `fulfilled_os_sphere` start null,
        `recall_flagged` starts false, and `cancellation_reason`, `shipped_at` and
        `delivered_at` start null."

        Design: Corner/entities/order_retrieval_returns_stored_price_snapshot
        """
        scenario = setup_order_on_verified_prescription(
            boxes_od=1, boxes_os=1, clock=DEFAULT_CLOCK_UTC
        )
        customer_headers = make_customer_headers(scenario["customer"]["id"])

        order = validate_success(
            api.get_order(scenario["order"]["id"], customer_headers)
        )

        assert_order(order)
        assert order["id"] == scenario["order"]["id"]
        assert order["unit_price_cents"] == 3200
        assert order["lenses_per_box_at_capture"] == 30
        assert order["subtotal_cents"] == 6400
        assert order["shipping_cents"] == 0
        assert order["total_cents"] == 6400
        assert order["verification_state"] == "RX_CLEARED"
        assert order["fulfillment_state"] == "PENDING"
        assert order["substitution_type"] == "NONE"
        assert float(order["parameter_deviation_index"]) == 0.0
        assert order["fulfilled_product_id"] == scenario["product"]["id"]
        assert order["recall_flagged"] is False

    def test_order_money_is_server_computed_and_client_amounts_are_not_stored(self, api):
        """PRD §3.5: "The payload names the `customer_id`, the authorising
        `prescription_id`, the `ordered_product_id` the customer asked for, and the
        split of quantity across eyes: `boxes_od` for the right eye and `boxes_os`
        for the left, each of which must be zero or greater, with the sum of the
        two being at least 1."

        PRD §3.5: "`subtotal_cents` is the snapshotted `unit_price_cents`
        multiplied by total boxes."

        PRD §3.5: "`shipping_cents` is zero when `subtotal_cents` has reached the
        free-shipping threshold of 5,000 cents — fifty dollars, and the comparison
        is inclusive, so a subtotal of exactly 5,000 cents ships free — and is
        otherwise the flat standard charge of 695 cents."

        PRD §3.5: "`total_cents` is `subtotal_cents` plus `shipping_cents`."

        PRD §2.7: "`lifetime_charged_cents` is the sum of `total_cents` over every
        order of that customer whose `fulfillment_state` is anything other than
        `CANCELLED`."

        PRD §2.7: "`net_cash_position_cents` is `lifetime_charged_cents` less
        `lifetime_refunded_cents`."

        Design: Corner/entities/order_total_cents_is_computed_and_client_supplied_value_input_ignored
        """
        scenario = setup_verified_prescription(clock=DEFAULT_CLOCK_UTC)
        customer_id = scenario["customer"]["id"]

        payload = create_order_payload(
            customer_id,
            scenario["prescription"]["id"],
            scenario["product"]["id"],
            boxes_od=1,
            boxes_os=1,
            total_cents=1,
            subtotal_cents=1,
            shipping_cents=9999,
        )
        order = validate_success(
            api.create_order(payload, make_customer_headers(customer_id)), 201
        )

        assert order["subtotal_cents"] == 6400
        assert order["shipping_cents"] == 0
        assert order["total_cents"] == 6400

        ledger = get_ledger(customer_id)
        assert_customer_ledger(ledger)
        assert_ledger_values(
            ledger, lifetime_charged_cents=6400, net_cash_position_cents=6400
        )


class TestPrescriptionFieldSourceContract:
    def test_prescription_status_and_counters_are_system_owned(self, api):
        """PRD §3.2: "A newly captured prescription is in `DRAFT`."

        PRD §3.2: "It also carries two derived counters: `boxes_consumed`, the
        running box ledger described in §2.7, and `verification_rounds`, the number
        of verification contacts sent on its behalf, both starting at zero."

        PRD §2.4: "`id` — a server-minted UUID with no type prefix."

        PRD §2.4: "`version` — an integer that starts at 1 on creation and
        increments by one on every mutation of the row."

        Design: Corner/entities/prescription_status_is_a_system_field_and_client_status_input_ignored
        """
        scenario = setup_reference_data(clock=DEFAULT_CLOCK_UTC)
        customer_id = scenario["customer"]["id"]

        payload = create_prescription_payload(
            customer_id,
            scenario["product"]["id"],
            status="VERIFIED_ACTIVE",
            boxes_consumed=9,
            verification_rounds=7,
        )
        created = validate_success(
            api.create_prescription(payload, make_customer_headers(customer_id)), 201
        )

        assert created["status"] == "DRAFT"
        assert created["boxes_consumed"] == 0
        assert created["verification_rounds"] == 0

        assert_common_fields(created, "Prescription")
        assert is_valid_uuid(created["id"])
        assert created["version"] == 1
        assert_timestamp_equals(created["created_at"], "2026-08-01T00:00:00.000Z")

        reread = validate_success(
            api.get_prescription(created["id"], CO_ALPHA_HEADERS)
        )
        assert reread["status"] == "DRAFT"

    def test_prescription_without_boxes_authorized_total_is_malformed(self, api):
        """PRD §3.2: "The commercial content is `boxes_authorized_total`, the total
        number of boxes the prescription authorises across its whole life, which
        must be at least 1."

        PRD §2.10: "**Request well-formed.** On any endpoint with a request body or
        query parameters: a required field absent, a field of the wrong type, an
        enum value outside its declared domain, a numeric field outside its
        declared range, or an `expiry_date` that is not a valid calendar date →
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/prescription_creation_missing_required_boxes_authorized_total_returns_invalid_request
        """
        scenario = setup_reference_data(clock=DEFAULT_CLOCK_UTC)
        customer_id = scenario["customer"]["id"]

        payload = create_prescription_payload(customer_id, scenario["product"]["id"])
        del payload["boxes_authorized_total"]

        validate_error(
            api.create_prescription(payload, make_customer_headers(customer_id)),
            ApiErrorId.ERR_INVALID_REQUEST,
        )

        _, meta = validate_paginated(
            api.list_prescriptions(CO_ALPHA_HEADERS, params={"customer_id": customer_id})
        )
        assert meta["total_count"] == 0, "a rejected capture must persist nothing"

    def test_prescription_with_capture_mode_outside_the_enum_is_malformed(self, api):
        """PRD §3.2: "The capture names the owning `customer_id`, the prescribed SKU
        as `product_id`, and a `capture_mode` of `UPLOAD`, `DOCTOR_LOOKUP` or
        `SELF_REPORT`."

        PRD §2.10: "**Request well-formed.** On any endpoint with a request body or
        query parameters: a required field absent, a field of the wrong type, an
        enum value outside its declared domain, a numeric field outside its
        declared range, or an `expiry_date` that is not a valid calendar date →
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/prescription_creation_with_invalid_enum_capture_mode_returns_invalid_request
        """
        scenario = setup_reference_data(clock=DEFAULT_CLOCK_UTC)
        customer_id = scenario["customer"]["id"]

        payload = create_prescription_payload(
            customer_id, scenario["product"]["id"], capture_mode="PHONE_CALL"
        )

        validate_error(
            api.create_prescription(payload, make_customer_headers(customer_id)),
            ApiErrorId.ERR_INVALID_REQUEST,
        )

        _, meta = validate_paginated(
            api.list_prescriptions(CO_ALPHA_HEADERS, params={"customer_id": customer_id})
        )
        assert meta["total_count"] == 0, "a rejected capture must persist nothing"


class TestPrescriptionListingContract:
    def test_prescription_list_reports_total_count_and_has_more_across_pages(self, api):
        """PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10,
        may be no smaller than 1, and may be no larger than 100."

        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object, where `total_count` counts every row
        matching the filters before pagination is applied and `has_more` is true
        when rows remain beyond the returned page."

        PRD §3.2: "A newly captured prescription is in `DRAFT`."

        PRD §3.2: "It also carries two derived counters: `boxes_consumed`, the
        running box ledger described in §2.7, and `verification_rounds`, the number
        of verification contacts sent on its behalf, both starting at zero."

        Design: Corner/entities/prescription_listing_paginates_with_total_count_and_has_more
        """
        scenario = setup_reference_data(clock=DEFAULT_CLOCK_UTC)
        customer_id = scenario["customer"]["id"]
        _three_draft_prescriptions(customer_id, scenario["product"]["id"])

        first_page, first_meta = validate_paginated(
            api.list_prescriptions(
                CO_ALPHA_HEADERS,
                params={"customer_id": customer_id, "limit": 2, "offset": 0},
            )
        )
        assert len(first_page) == 2
        assert_pagination_meta(
            first_meta, limit=2, offset=0, total_count=3, has_more=True
        )

        second_page, second_meta = validate_paginated(
            api.list_prescriptions(
                CO_ALPHA_HEADERS,
                params={"customer_id": customer_id, "limit": 2, "offset": 2},
            )
        )
        assert len(second_page) == 1
        assert_pagination_meta(
            second_meta, limit=2, offset=2, total_count=3, has_more=False
        )

        for row in first_page + second_page:
            assert_prescription(row)
            assert row["status"] == "DRAFT"
            assert row["boxes_consumed"] == 0
            assert row["verification_rounds"] == 0


class TestReferentialResolutionContract:
    def test_unknown_order_id_in_the_path_is_a_not_found(self, api):
        """PRD §2.10: "**Path row exists.** On any endpoint whose path contains an
        identifier, the `id` in the path does not name a stored row → the not-found
        code of the addressed entity, at HTTP 404: `ERR_INSURANCE_PLAN_NOT_FOUND`,
        `ERR_PRODUCT_NOT_FOUND`, `ERR_PRESCRIBER_NOT_FOUND`,
        `ERR_CUSTOMER_NOT_FOUND`, `ERR_PRESCRIPTION_NOT_FOUND`,
        `ERR_VERIFICATION_REQUEST_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
        `ERR_REORDER_HOLD_NOT_FOUND`, `ERR_SCHEDULE_NOT_FOUND`,
        `ERR_RETURN_REQUEST_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` or
        `ERR_DISPUTE_NOT_FOUND` as appropriate."

        PRD §2.2: "The `message` provides a human-readable explanation of what went
        wrong."

        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
        the request that starts with `req_`."

        Design: Corner/entities/order_not_found_returns_err_order_not_found
        """
        set_clock(DEFAULT_CLOCK_UTC)

        response = api.get_order(UNKNOWN_ORDER_UUID, CO_ALPHA_HEADERS)
        error = validate_error(response, ApiErrorId.ERR_ORDER_NOT_FOUND)

        assert response.json()["response_type"] == "error"
        assert isinstance(error["message"], str) and error["message"]
        api_request_id = response.json()["meta"]["api_request_id"]
        assert api_request_id.startswith("req_")

        _, meta = validate_paginated(api.list_orders(CO_ALPHA_HEADERS))
        assert meta["total_count"] == 0

    def test_unknown_customer_reference_outranks_the_expiry_ordering_check(self, api):
        """PRD §2.10: "**Body references exist.** A foreign key in the request body
        that does not name a stored row → the not-found code of the *referenced*
        entity, at HTTP 404, drawn from the same list."

        PRD §2.10: "Expiry after issue, on prescription capture →
        `ERR_EXPIRY_BEFORE_ISSUE` (400)."

        PRD §2.10: "The first check that fails determines the response, and no
        later check is evaluated."

        Design: Corner/entities/prescription_with_unknown_customer_id_returns_customer_not_found
        """
        set_clock(DEFAULT_CLOCK_UTC)
        product = new_product()

        payload = create_prescription_payload(
            UNKNOWN_CUSTOMER_UUID,
            product["id"],
            issue_date="2027-07-01",
            expiry_date="2026-07-01",
        )

        validate_error(
            api.create_prescription(payload, ADMIN_HEADERS),
            ApiErrorId.ERR_CUSTOMER_NOT_FOUND,
        )

        _, meta = validate_paginated(api.list_prescriptions(CO_ALPHA_HEADERS))
        assert meta["total_count"] == 0

    def test_claim_resolves_each_of_its_three_body_foreign_keys(self, api):
        """PRD §3.9: "Out-of-network reimbursement begins with the patient opening a
        claim naming the `order_id`, their `customer_id`, and the
        `insurance_plan_id` the claim will be priced against."

        PRD §2.10: "**Body references exist.** A foreign key in the request body
        that does not name a stored row → the not-found code of the *referenced*
        entity, at HTTP 404, drawn from the same list."

        PRD §3.9: "The claim is created in `DRAFT` with every money field null
        except `refund_offset_cents`, which is seeded from the settled returns
        already recorded against the order."

        Design: Corner/entities/reimbursement_claim_validates_all_three_foreign_keys
        """
        scenario = setup_delivered_order(clock=DEFAULT_CLOCK_UTC, with_plan=True)
        customer_id = scenario["customer"]["id"]
        order_id = scenario["order"]["id"]
        customer_headers = make_customer_headers(customer_id)

        unknown_plan_payload = create_reimbursement_claim_payload(
            order_id, customer_id, UNKNOWN_PLAN_UUID
        )
        validate_error(
            api.create_reimbursement_claim(unknown_plan_payload, customer_headers),
            ApiErrorId.ERR_INSURANCE_PLAN_NOT_FOUND,
        )

        _, meta = validate_paginated(
            api.list_reimbursement_claims(
                CO_ALPHA_HEADERS, params={"order_id": order_id}
            )
        )
        assert meta["total_count"] == 0

        stored_plan_payload = create_reimbursement_claim_payload(
            order_id, customer_id, scenario["plan"]["id"]
        )
        claim = validate_success(
            api.create_reimbursement_claim(stored_plan_payload, customer_headers), 201
        )
        assert claim["status"] == "DRAFT"
        assert claim["order_id"] == order_id
        assert claim["insurance_plan_id"] == scenario["plan"]["id"]


class TestReturnRequestTypeContract:
    def test_scalar_used_counts_is_a_type_violation_not_a_quantity_violation(self, api):
        """PRD §3.8: "The physical content of the return is described by
        `unopened_boxes`, the count of fully unopened boxes coming back, defaulting
        to zero; `opened_box_used_counts`, an array with one element per opened box
        giving the lenses already used out of that box, defaulting to an empty
        array; and `torn_lens_count`, the number of lenses reported torn, which is
        required when `reason` is `TORN_LENS`."

        PRD §2.10: "**Request well-formed.** On any endpoint with a request body or
        query parameters: a required field absent, a field of the wrong type, an
        enum value outside its declared domain, a numeric field outside its
        declared range, or an `expiry_date` that is not a valid calendar date →
        `ERR_INVALID_REQUEST` (400)."

        PRD §2.10: "Returned quantities within what the order shipped, on return
        creation → `ERR_RETURN_QUANTITY_EXCEEDS_ORDER` (422)."

        PRD §2.10: "The first check that fails determines the response, and no
        later check is evaluated."

        Design: Corner/entities/return_request_with_non_array_used_counts_rejects_the_wrong_type
        """
        scenario = setup_delivered_order(clock=DEFAULT_CLOCK_UTC)
        customer_id = scenario["customer"]["id"]
        order_id = scenario["order"]["id"]

        payload = create_return_request_payload(
            order_id,
            customer_id,
            reason="PRESCRIPTION_CHANGE",
            unopened_boxes=1,
            opened_box_used_counts="three",
        )

        validate_error(
            api.create_return_request(payload, make_customer_headers(customer_id)),
            ApiErrorId.ERR_INVALID_REQUEST,
        )

        _, meta = validate_paginated(
            api.list_return_requests(CO_ALPHA_HEADERS, params={"order_id": order_id})
        )
        assert meta["total_count"] == 0


class TestComplianceEventContract:
    def test_compliance_event_is_append_only_with_no_version_or_updated_at(self, api):
        """PRD §2.4: "Compliance events are the single exception."

        PRD §2.4: "A compliance event is an append-only audit record and carries
        only `id` and `created_at`; it has no `updated_at` and no `version`,
        because it is never modified after it is written."

        PRD §2.11: "A compliance event names the `prescription_id` it belongs to,
        an `event_type`, the `subject_type` (the entity name the event concerns,
        such as `Order`) and the `subject_id` of the subject row, together with the
        `actor_role` and `actor_user_id` responsible and an optional
        human-readable `detail`."

        PRD §2.11: "`occurred_at` is the logical clock value at the moment the
        event was recorded."

        PRD §3.3: "A successful upload submit appends a compliance event of type
        `RX_SUBMITTED` with the detail `upload accepted`."

        Design: Corner/entities/compliance_event_is_append_only_with_no_version_field
        """
        scenario = setup_verified_prescription(clock=DEFAULT_CLOCK_UTC)
        prescription_id = scenario["prescription"]["id"]
        customer_id = scenario["customer"]["id"]

        events, _ = validate_paginated(
            api.list_compliance_events_for_prescription(
                prescription_id, CO_ALPHA_HEADERS
            )
        )

        assert len(events) == 1, "the upload submit appends exactly one event"
        event = events[0]
        assert_compliance_event(event)
        assert event["event_type"] == "RX_SUBMITTED"
        assert event["prescription_id"] == prescription_id
        assert event["subject_type"] == "Prescription"
        assert event["subject_id"] == prescription_id
        assert event["actor_role"] == "Customer"
        assert event["actor_user_id"] == customer_id
        assert_timestamp_equals(event["occurred_at"], "2026-08-01T00:00:00.000Z")
        assert "version" not in event, "an append-only row carries no version"
        assert "updated_at" not in event, "an append-only row carries no updated_at"


class TestCustomerLedgerContract:
    def test_new_patient_ledger_reads_every_counter_at_zero(self, api):
        """PRD §2.7: "A newly registered patient has every counter at zero and
        `auto_reorder_enabled` false."

        PRD §2.7: "It returns `customer_id`, `lifetime_charged_cents`,
        `lifetime_refunded_cents`, `net_cash_position_cents`, `store_credit_cents`,
        `allowance_used_cents`, `allowance_remaining_cents`, `open_hold_count`,
        `active_schedule_count` and `auto_reorder_enabled`, each recomputed from
        live rows at read time so that any drift between the stored counters and
        reality is directly observable."

        PRD §2.7: "`allowance_remaining_cents` is the plan's
        `annual_allowance_cents` less `allowance_used_cents`, floored at zero; for
        a self-pay customer who carries no `insurance_plan_id` it is zero."

        Design: Corner/entities/customer_ledger_fields_start_at_zero_for_a_new_customer
        """
        set_clock(DEFAULT_CLOCK_UTC)
        plan = new_insurance_plan()
        customer = new_customer(insurance_plan_id=plan["id"])

        ledger = validate_success(
            api.get_customer_ledger(
                customer["id"], make_customer_headers(customer["id"])
            )
        )

        assert_customer_ledger(ledger)
        assert ledger["customer_id"] == customer["id"]
        assert_ledger_values(
            ledger,
            lifetime_charged_cents=0,
            lifetime_refunded_cents=0,
            net_cash_position_cents=0,
            store_credit_cents=0,
            allowance_used_cents=0,
            open_hold_count=0,
            active_schedule_count=0,
        )
        assert ledger["allowance_remaining_cents"] == 15000
        assert ledger["auto_reorder_enabled"] is False


class TestVerificationRequestContract:
    def test_new_round_snapshots_channel_and_starts_at_sent(self, api):
        """PRD §3.3: "A successful round creates a **verification request**."

        PRD §3.3: "It records the `prescription_id` being verified and the
        `prescriber_id` receiving the contact, snapshots the provider's
        `contact_channel` into its own `channel`, and stamps `sent_at` from the
        logical clock."

        PRD §3.3: "Its `round_number` is a one-based index within the prescription,
        set to the prescription's `verification_rounds` plus one, and the
        prescription's `verification_rounds` is then incremented."

        PRD §3.3: "The request's `status` begins at `SENT` and ends in one of four
        terminal values — `CONFIRMED`, `CORRECTED`, `DENIED` or `PASSIVE_TIMEOUT` —
        and its `response_type` stays null until a provider actually answers, at
        which point it takes the value `CONFIRMED`, `CORRECTED` or `DENIED`."

        PRD §3.3: "Each request's `passive_deadline_at` is computed by advancing a
        business-hour budget from `sent_at`: **eight** business hours when the
        receiving provider's `directory_verified` flag is true, and **twelve**
        business hours when it is false, because a prescriber the patient merely
        named deserves longer to object than one the directory confirmed."

        PRD §2.5: "A business day runs from 08:00 UTC to 17:00 UTC, which is nine
        business hours per day, and business days are Monday, Tuesday, Wednesday,
        Thursday and Friday."

        Design: Corner/entities/verification_request_defaults_channel_from_prescriber_and_status_to_sent
        """
        scenario = setup_pending_verification_prescription(
            clock=WORKING_TUESDAY_10AM,
            directory_verified=True,
            contact_channel="PORTAL",
        )
        prescription_id = scenario["prescription"]["id"]

        request = validate_success(
            api.send_verification_request(
                prescription_id,
                {"prescriber_id": scenario["prescriber"]["id"]},
                CO_ALPHA_HEADERS,
            ),
            201,
        )

        assert_verification_request(request)
        assert request["status"] == "SENT"
        assert request["round_number"] == 1
        assert request["channel"] == "PORTAL"
        assert_timestamp_equals(request["sent_at"], "2026-09-08T10:00:00.000Z")
        assert_timestamp_equals(
            request["passive_deadline_at"], "2026-09-09T09:00:00.000Z"
        )
        assert request["response_type"] is None

        prescription = validate_success(
            api.get_prescription(prescription_id, CO_ALPHA_HEADERS)
        )
        assert prescription["status"] == "PENDING_VERIFICATION"
        assert prescription["verification_rounds"] == 1
