"""Error catalogue: every refusal reports its own identifier at its own status.

Each test drives one refusal to the surface, cross-checks the HTTP status the
error catalogue pins to that identifier, and then shows that the refused
operation left no trace — no row minted, no ledger moved, no audit event
appended — and that the legitimate variant of the same call still succeeds.
"""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    CO_ALPHA,
    CO_ALPHA_HEADERS,
    CO_BRAVO,
    CO_BRAVO_HEADERS,
    DEFAULT_CLOCK_UTC,
    FO_HEADERS,
    ApiErrorId,
    approve_return_request,
    assert_ledger_values,
    build_user_headers,
    create_customer_payload,
    deliver_order,
    get_ledger,
    invalidate_prescription,
    make_customer_headers,
    new_customer,
    new_order,
    new_reimbursement_claim,
    new_return_request,
    set_clock,
    setup_correction_pending_prescription,
    setup_delivered_order,
    setup_delivered_order_with_draft_claim,
    setup_reference_data,
    setup_substitution_candidates,
    ship_order,
    settle_return_request,
    validate_error,
    validate_paginated,
    validate_success,
)

# A syntactically valid uuid that names no stored row in any aggregate.
UNKNOWN_ROW_UUID = "00000000-0000-0000-0000-0000000000aa"

# A Customer identity that owns no row — safe only where the addressed resource
# carries no ownership dimension.
ANY_CUSTOMER_READER_HEADERS = make_customer_headers("any-customer-reader")


def _place_delivered_order_with_receipt(scenario, receipt_reference):
    """Add a second delivered order that does carry an itemised receipt
    identifier, reusing the scenario's customer, prescription and product."""
    order = new_order(
        scenario["customer"]["id"],
        scenario["prescription"]["id"],
        scenario["product"]["id"],
        1,
        1,
        itemized_receipt_reference=receipt_reference,
    )
    ship_order(order["id"])
    return deliver_order(order["id"])


class TestIdentityAndRoleRefusals:
    """Priorities 1, 3 and 6: who is calling, in what capacity, about whose row."""

    def test_product_listing_without_identity_headers_is_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the capacity in
        which they act."

        PRD §2.1: "If either header is absent or empty, the request is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is examined."

        Design: Corner/errors/request_with_missing_auth_headers_returns_401_unauthenticated
        """
        setup_reference_data(clock=DEFAULT_CLOCK_UTC)

        response = api.get("/products", headers={})

        error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)
        assert response.json()["response_type"] == "error"
        assert error["message"].strip(), "the error envelope must carry a message"

        # An empty X-User-ID is "absent or empty" too, even with a valid role.
        empty_id_response = api.list_products(build_user_headers("", "PlatformAdmin"))
        validate_error(empty_id_response, ApiErrorId.ERR_UNAUTHENTICATED)

        # With both headers present the same listing succeeds and sees the row.
        products, meta = validate_paginated(
            api.list_products(ANY_CUSTOMER_READER_HEADERS)
        )
        assert meta["total_count"] == 1
        assert len(products) == 1

    def test_fulfillment_operator_cannot_generate_a_claim_packet(self, api):
        """PRD §2.1: "If the header pair is present but the declared role is not
        one of the roles authorised for the addressed endpoint in §4, the request
        is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        PRD §2.1: "`FulfillmentOperator` is warehouse staff: it substitutes,
        ships, delivers and drives the auto-reorder run, and never touches holds,
        claims or disputes."

        Design: Corner/errors/fulfillment_operator_generating_a_claim_returns_403_unauthorized
        """
        scenario = setup_delivered_order_with_draft_claim(clock=DEFAULT_CLOCK_UTC)
        claim_id = scenario["claim"]["id"]

        response = api.generate_reimbursement_claim(claim_id, FO_HEADERS)

        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)

        # No money was computed: the claim is untouched in DRAFT.
        claim = validate_success(
            api.get_reimbursement_claim(claim_id, CO_ALPHA_HEADERS)
        )
        assert claim["status"] == "DRAFT"
        assert claim["reimbursable_cents"] is None

        # The compliance desk is authorised, so the same call now prices it.
        generated = validate_success(
            api.generate_reimbursement_claim(claim_id, CO_ALPHA_HEADERS)
        )
        assert generated["status"] == "GENERATED"
        assert generated["reimbursable_cents"] == 6150

    def test_customer_cannot_read_another_patients_ledger(self, api):
        """PRD §2.1: "Ownership checks on any resource that references a Customer
        compare that resource's customer foreign key to `X-User-ID`: a patient
        may address only their own prescriptions, orders, auto-reorder schedules,
        return requests, reimbursement claims, reorder holds and ledger."

        PRD §2.1: "A failed ownership check yields `ERR_IDENTITY_MISMATCH` (HTTP
        403)."

        PRD §2.1: "The remaining three roles are **opaque**: when `X-User-Role`
        is `ComplianceOfficer`, `FulfillmentOperator`, or `PlatformAdmin`,
        `X-User-ID` is an operator identifier that is not tied to any persisted
        entity."

        Design: Corner/errors/customer_reading_another_customers_ledger_returns_403_identity_mismatch
        """
        set_clock(DEFAULT_CLOCK_UTC)
        customer_a = new_customer(full_name="Ada Lin", email="ada.lin@example.com")
        customer_b = new_customer(full_name="Ben Ortiz", email="ben.ortiz@example.com")

        response = api.get_customer_ledger(
            customer_a["id"], make_customer_headers(customer_b["id"])
        )

        validate_error(response, ApiErrorId.ERR_IDENTITY_MISMATCH)

        # The owning patient reads their own ledger.
        own_ledger = validate_success(
            api.get_customer_ledger(
                customer_a["id"], make_customer_headers(customer_a["id"])
            )
        )
        assert own_ledger["net_cash_position_cents"] == 0

        # An opaque operator identity is never compared to a row id.
        officer_view = validate_success(
            api.get_customer_ledger(customer_a["id"], CO_ALPHA_HEADERS)
        )
        assert officer_view["customer_id"] == customer_a["id"]


class TestUniquenessAndReferentialRefusals:
    """Priorities 4 and 11: unknown rows, and rows that already exist."""

    def test_duplicate_patient_email_is_refused_across_state_codes(self, api):
        """PRD §3.2: "A patient is registered by an administrator with a
        `full_name`, a contact `email` that must be unique across all patients,
        and a two-letter `state_code` of residence."

        PRD §3.2: "A duplicate email is rejected with `ERR_DUPLICATE_EMAIL`, and
        a plan identifier that names no stored plan is rejected with
        `ERR_INSURANCE_PLAN_NOT_FOUND`."

        Design: Corner/errors/duplicate_customer_email_returns_409_duplicate_email
        """
        set_clock(DEFAULT_CLOCK_UTC)
        first = new_customer(full_name="Ada Lin", email="ada.lin@example.com")

        response = api.create_customer(
            create_customer_payload(
                full_name="Ada Lin Duplicate",
                email="ada.lin@example.com",
                state_code="NV",
            ),
            ADMIN_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_EMAIL)

        # Uniqueness is global, so no second row was minted.
        customers, meta = validate_paginated(api.list_customers(ADMIN_HEADERS))
        assert meta["total_count"] == 1
        assert customers[0]["id"] == first["id"]

        # A distinct address registers normally.
        accepted = api.create_customer(
            create_customer_payload(
                full_name="Ada Lin Duplicate",
                email="ada.lin+2@example.com",
                state_code="NV",
            ),
            ADMIN_HEADERS,
        )
        validate_success(accepted, 201)

    @pytest.mark.parametrize(
        "read_addressed_row, expected_error",
        [
            (
                lambda api: api.get_prescription(UNKNOWN_ROW_UUID, CO_ALPHA_HEADERS),
                ApiErrorId.ERR_PRESCRIPTION_NOT_FOUND,
            ),
            (
                lambda api: api.get_product(UNKNOWN_ROW_UUID, CO_ALPHA_HEADERS),
                ApiErrorId.ERR_PRODUCT_NOT_FOUND,
            ),
            (
                lambda api: api.get_prescriber(UNKNOWN_ROW_UUID, CO_ALPHA_HEADERS),
                ApiErrorId.ERR_PRESCRIBER_NOT_FOUND,
            ),
            (
                lambda api: api.get_verification_request(
                    UNKNOWN_ROW_UUID, CO_ALPHA_HEADERS
                ),
                ApiErrorId.ERR_VERIFICATION_REQUEST_NOT_FOUND,
            ),
            (
                lambda api: api.get_reorder_hold(UNKNOWN_ROW_UUID, CO_ALPHA_HEADERS),
                ApiErrorId.ERR_REORDER_HOLD_NOT_FOUND,
            ),
            (
                lambda api: api.get_auto_reorder_schedule(
                    UNKNOWN_ROW_UUID, CO_ALPHA_HEADERS
                ),
                ApiErrorId.ERR_SCHEDULE_NOT_FOUND,
            ),
            (
                lambda api: api.get_return_request(UNKNOWN_ROW_UUID, CO_ALPHA_HEADERS),
                ApiErrorId.ERR_RETURN_REQUEST_NOT_FOUND,
            ),
            (
                lambda api: api.get_reimbursement_claim(
                    UNKNOWN_ROW_UUID, CO_ALPHA_HEADERS
                ),
                ApiErrorId.ERR_CLAIM_NOT_FOUND,
            ),
            (
                lambda api: api.get_prescriber_dispute(
                    UNKNOWN_ROW_UUID, CO_ALPHA_HEADERS
                ),
                ApiErrorId.ERR_DISPUTE_NOT_FOUND,
            ),
        ],
        ids=[
            "prescription",
            "product",
            "prescriber",
            "verification_request",
            "reorder_hold",
            "auto_reorder_schedule",
            "return_request",
            "reimbursement_claim",
            "prescriber_dispute",
        ],
    )
    def test_unknown_path_id_reports_the_addressed_entitys_own_not_found_code(
        self, api, read_addressed_row, expected_error
    ):
        """PRD §2.10: "On any endpoint whose path contains an identifier, the
        `id` in the path does not name a stored row → the not-found code of the
        addressed entity, at HTTP 404: `ERR_INSURANCE_PLAN_NOT_FOUND`,
        `ERR_PRODUCT_NOT_FOUND`, `ERR_PRESCRIBER_NOT_FOUND`,
        `ERR_CUSTOMER_NOT_FOUND`, `ERR_PRESCRIPTION_NOT_FOUND`,
        `ERR_VERIFICATION_REQUEST_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
        `ERR_REORDER_HOLD_NOT_FOUND`, `ERR_SCHEDULE_NOT_FOUND`,
        `ERR_RETURN_REQUEST_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` or
        `ERR_DISPUTE_NOT_FOUND` as appropriate."

        Design: Corner/errors/each_addressed_path_id_returns_its_own_not_found_code
        """
        set_clock(DEFAULT_CLOCK_UTC)

        response = read_addressed_row(api)

        error = validate_error(response, expected_error)
        assert response.json()["response_type"] == "error"
        assert error["message"].strip(), "the error envelope must carry a message"


class TestLifecycleAndClinicalRefusals:
    """Priorities 20 and 25: a dead prescription, and an unmapped substitution."""

    def test_invalidated_prescription_cannot_be_ordered_against(self, api):
        """PRD §3.4: "When a correction round stalls and nobody will confirm, a
        compliance officer may invalidate the prescription manually, supplying a
        `reason`."

        PRD §3.4: "It appends an `RX_INVALIDATED` compliance event, opens a
        reorder hold with `reason` `MANUAL` in `OPEN` status, and recomputes the
        customer's `open_hold_count` and `auto_reorder_enabled`."

        PRD §3.5: "The prescription must not be `INVALIDATED`, or the order is
        refused with `ERR_PRESCRIPTION_INVALIDATED`."

        Design: Corner/errors/invalidated_prescription_blocks_a_new_order_with_409
        """
        scenario = setup_correction_pending_prescription(clock=DEFAULT_CLOCK_UTC)
        customer_id = scenario["customer"]["id"]
        prescription_id = scenario["prescription"]["id"]
        invalidate_prescription(
            prescription_id, reason="prescriber directory mismatch", actor=CO_ALPHA
        )

        response = api.create_order(
            {
                "customer_id": customer_id,
                "prescription_id": prescription_id,
                "ordered_product_id": scenario["product"]["id"],
                "boxes_od": 1,
                "boxes_os": 1,
            },
            make_customer_headers(customer_id),
        )

        validate_error(response, ApiErrorId.ERR_PRESCRIPTION_INVALIDATED)

        # The refusal is about the terminal status, not about the expiry date,
        # which is still a year out; the box ledger never moved.
        prescription = validate_success(
            api.get_prescription(prescription_id, CO_ALPHA_HEADERS)
        )
        assert prescription["status"] == "INVALIDATED"
        assert prescription["boxes_consumed"] == 0
        assert prescription["expiry_date"] == "2027-07-01"

        _, order_meta = validate_paginated(
            api.list_orders(CO_ALPHA_HEADERS, params={"customer_id": customer_id})
        )
        assert order_meta["total_count"] == 0

        holds, hold_meta = validate_paginated(
            api.list_reorder_holds(
                CO_ALPHA_HEADERS, params={"customer_id": customer_id, "status": "OPEN"}
            )
        )
        assert hold_meta["total_count"] == 1
        assert holds[0]["reason"] == "MANUAL"

        assert_ledger_values(
            get_ledger(customer_id), open_hold_count=1, auto_reorder_enabled=False
        )

    def test_substitution_without_an_active_mapping_is_refused(self, api):
        """PRD §3.6: "Where the index and consent both pass, the mapping
        requirement bites: an `ACTIVE` mapping whose `from_product_id` is the
        order's ordered product and whose `to_product_id` is the requested
        substitute must exist, or the request is refused with
        `ERR_NO_EQUIVALENCE_MAPPING` at HTTP 422."

        PRD §3.6: "`RETIRED` mappings do not count."

        Design: Corner/errors/substitution_without_an_active_mapping_returns_422_no_equivalence_mapping
        """
        scenario = setup_substitution_candidates(
            [{"brand": "OptiSoft"}],
            clock=DEFAULT_CLOCK_UTC,
            equivalence_overrides={"status": "RETIRED"},
        )
        ordered_product_id = scenario["product"]["id"]
        substitute_id = scenario["substitutes"][0]["id"]
        order = scenario["order"]

        response = api.apply_substitution(
            order["id"],
            {
                "substitute_product_id": substitute_id,
                "expected_order_version": order["version"],
            },
            FO_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_NO_EQUIVALENCE_MAPPING)

        # Nothing on the order moved, so no version was burned either.
        after = validate_success(api.get_order(order["id"], FO_HEADERS))
        assert after["fulfilled_product_id"] == ordered_product_id
        assert after["substitution_type"] == "NONE"
        assert after["version"] == order["version"]

        # The only mapping from the ordered product is RETIRED.
        _, equivalence_meta = validate_paginated(
            api.list_lens_equivalences_for_product(
                ordered_product_id,
                ADMIN_HEADERS,
                params={"direction": "FROM", "status": "ACTIVE"},
            )
        )
        assert equivalence_meta["total_count"] == 0

        events, _ = validate_paginated(
            api.list_compliance_events_for_prescription(
                scenario["prescription"]["id"], CO_ALPHA_HEADERS
            )
        )
        assert not [
            event for event in events if event["event_type"] == "SUBSTITUTION_APPLIED"
        ]


class TestReimbursementRefusals:
    """Priorities 33 and 34: which plans qualify, and what paperwork they need."""

    def test_in_network_plan_cannot_open_a_reimbursement_claim(self, api):
        """PRD §3.1: "A **vision plan** is registered with a `name` for display
        and a `network_status` of either `IN_NETWORK` or `OUT_OF_NETWORK`."

        PRD §3.9: "The plan must not be `RETIRED`, or the claim is refused with
        `ERR_PLAN_RETIRED`, and its `network_status` must be `OUT_OF_NETWORK`
        rather than `IN_NETWORK`, or the claim is refused with
        `ERR_PLAN_NOT_OUT_OF_NETWORK` at HTTP 422 — in-network care is billed by
        the provider, not reimbursed to the member."

        Design: Corner/errors/claim_on_an_in_network_plan_returns_422_plan_not_out_of_network
        """
        scenario = setup_delivered_order(
            clock=DEFAULT_CLOCK_UTC,
            with_plan=True,
            plan_overrides={"name": "InNetOne", "network_status": "IN_NETWORK"},
        )
        customer_id = scenario["customer"]["id"]

        response = api.create_reimbursement_claim(
            {
                "order_id": scenario["order"]["id"],
                "customer_id": customer_id,
                "insurance_plan_id": scenario["plan"]["id"],
            },
            make_customer_headers(customer_id),
        )

        validate_error(response, ApiErrorId.ERR_PLAN_NOT_OUT_OF_NETWORK)

        # No claim row appeared and no allowance was consumed.
        _, claim_meta = validate_paginated(
            api.list_reimbursement_claims(
                CO_ALPHA_HEADERS, params={"customer_id": customer_id}
            )
        )
        assert claim_meta["total_count"] == 0

        assert_ledger_values(
            get_ledger(customer_id),
            allowance_used_cents=0,
            allowance_remaining_cents=15000,
        )

    def test_claim_generation_demands_the_itemised_receipt_the_plan_requires(
        self, api
    ):
        """PRD §3.1: "Four optional fields shape the paperwork:
        `requires_itemized_receipt`, which defaults to true and, when true,
        forces claim generation to find a receipt identifier on the order;
        `covers_shipping`, which defaults to false and, when false, excludes the
        order's shipping charge from the base eligible spend; `claim_window_days`,
        the number of days after delivery within which a claim may be generated,
        defaulting to 90; and `plan_year_start_month_day`, the `MM-DD` anchor of
        the plan year, defaulting to `01-01`."

        PRD §3.9: "When the plan's `requires_itemized_receipt` is true, the order
        must carry an `itemized_receipt_reference`, or generation is refused with
        `ERR_ITEMIZED_RECEIPT_REQUIRED` at HTTP 422."

        Design: Corner/errors/claim_generation_without_the_itemized_receipt_returns_422
        """
        scenario = setup_delivered_order_with_draft_claim(
            clock=DEFAULT_CLOCK_UTC,
            plan_overrides={
                "name": "ReceiptPlan",
                "requires_itemized_receipt": True,
            },
        )
        customer_id = scenario["customer"]["id"]
        claim_id = scenario["claim"]["id"]

        # Creation is unaffected by the receipt requirement.
        assert scenario["claim"]["status"] == "DRAFT"

        response = api.generate_reimbursement_claim(claim_id, CO_ALPHA_HEADERS)

        validate_error(response, ApiErrorId.ERR_ITEMIZED_RECEIPT_REQUIRED)

        claim = validate_success(
            api.get_reimbursement_claim(claim_id, CO_ALPHA_HEADERS)
        )
        assert claim["status"] == "DRAFT"
        assert claim["applied_allowance_cents"] is None

        assert_ledger_values(get_ledger(customer_id), allowance_used_cents=0)

        # An order that does carry a receipt identifier generates normally.
        second_order = _place_delivered_order_with_receipt(scenario, "rcpt-1")
        second_claim = new_reimbursement_claim(
            second_order["id"], customer_id, scenario["plan"]["id"]
        )
        generated = validate_success(
            api.generate_reimbursement_claim(second_claim["id"], CO_ALPHA_HEADERS)
        )
        assert generated["status"] == "GENERATED"
        assert generated["reimbursable_cents"] == 6150


class TestSettlementMoneyRefusals:
    """Priority 39: the platform never refunds more than it captured."""

    def test_second_settlement_beyond_the_captured_total_is_refused(self, api):
        """PRD §3.8: "The frozen `settlement_cents` added to the sum of prior
        settled settlements on the same order must not exceed the order's
        `total_cents`, or the settlement is refused with
        `ERR_REFUND_EXCEEDS_CAPTURE` — the platform never refunds more than it
        captured."

        PRD §3.8: "Under `NO_PRORATION`, no box residue is considered at all: the
        candidate figure is `torn_lens_count` multiplied by the per-box value,
        divided by the lenses per box and rounded half up to a whole cent, and
        `settlement_cents` is whichever is smaller — that candidate figure, or a
        cap equal to twenty percent of the order's `total_cents` with any
        fraction of a cent discarded downward."

        Design: Corner/errors/settlement_beyond_the_captured_total_returns_409_refund_exceeds_capture
        """
        scenario = setup_delivered_order(clock=DEFAULT_CLOCK_UTC)
        customer_id = scenario["customer"]["id"]
        order_id = scenario["order"]["id"]

        first_return = new_return_request(
            order_id,
            customer_id,
            reason="PRESCRIPTION_CHANGE",
            unopened_boxes=2,
            opened_box_used_counts=[],
        )
        approve_return_request(first_return["id"], actor=CO_ALPHA)
        settled_first = settle_return_request(first_return["id"], actor=CO_BRAVO)
        assert settled_first["settlement_cents"] == 6400
        assert settled_first["settlement_channel"] == "CASH_REFUND"
        assert_ledger_values(
            get_ledger(customer_id),
            lifetime_refunded_cents=6400,
            net_cash_position_cents=0,
        )

        # Torn lenses are counted against lenses, not boxes, so the quantity
        # rule lets this second return through to the money rule.
        second_return = new_return_request(
            order_id,
            customer_id,
            reason="TORN_LENS",
            torn_lens_count=13,
            unopened_boxes=0,
            opened_box_used_counts=[],
        )
        approve_return_request(second_return["id"], actor=CO_ALPHA)

        response = api.settle_return_request(second_return["id"], CO_BRAVO_HEADERS)

        validate_error(response, ApiErrorId.ERR_REFUND_EXCEEDS_CAPTURE)

        unsettled = validate_success(
            api.get_return_request(second_return["id"], CO_ALPHA_HEADERS)
        )
        assert unsettled["status"] == "APPROVED"
        assert unsettled["settlement_cents"] == 1280
        assert unsettled["settled_by_user_id"] is None

        assert_ledger_values(
            get_ledger(customer_id),
            lifetime_refunded_cents=6400,
            store_credit_cents=0,
            net_cash_position_cents=0,
        )
