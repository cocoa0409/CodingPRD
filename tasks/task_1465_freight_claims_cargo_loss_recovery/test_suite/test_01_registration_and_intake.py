"""Registration and intake: carrier/lane/shipment/claim creation rules,
uniqueness, defaults, not-found behavior, and filtered listing."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_carrier,
    assert_claim,
    create_assignment_payload,
    create_carrier_payload,
    create_lane_payload,
    setup_claim_draft,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]


class TestCarrierRegistration:
    def test_carrier_create_applies_carmack_defaults(self, api):
        """PRD §3.1: "Registration also fixes the carrier's `max_auto_settle_cents`, the largest settlement an adjuster may see flow through without higher-tier authority, and its two Carmack windows: `carmack_acknowledgment_days`, defaulting to 30 calendar days, and `carmack_filing_days`, defaulting to 270 calendar days — a statutory floor that a contract may lengthen but never shorten."
        PRD §3.1: "A freshly registered carrier is `ACTIVE` with `claims_filed_count`, `claims_paid_count`, and `claim_ratio_bp` all zero."

        Design: Corner/entities/carrier_create_success_with_defaults
        """
        payload = create_carrier_payload()
        # Omit the two Carmack window fields entirely: defaults must apply.
        payload.pop("carmack_acknowledgment_days")
        payload.pop("carmack_filing_days")
        resp = api.create_carrier(payload, MANAGER)
        carrier = validate_success(resp, 201)
        assert_carrier(carrier)
        assert carrier["carmack_acknowledgment_days"] == 30
        assert carrier["carmack_filing_days"] == 270
        assert carrier["claims_filed_count"] == 0
        assert carrier["claims_paid_count"] == 0
        assert carrier["claim_ratio_bp"] == 0
        assert carrier["status"] == "ACTIVE"

    def test_carrier_duplicate_scac_rejected(self, api):
        """PRD §3.1: "A `ClaimsManager` onboards a carrier by supplying its `scac_code` — the Standard Carrier Alpha Code, unique across carriers, with duplicates rejected by `ERR_DUPLICATE_KEY` — along with its `legal_name` and its `liability_model`, one of `FULL_VALUE`, `RELEASED_RATE`, `PER_PACKAGE`, or `PER_POUND`."

        Design: Corner/entities/carrier_create_duplicate_scac_rejected
        """
        first = create_carrier_payload(scac_code="DUP1", legal_name="First")
        validate_success(api.create_carrier(first, MANAGER), 201)
        second = create_carrier_payload(
            scac_code="DUP1",
            legal_name="Second",
            liability_model="PER_POUND",
            per_pound_cap_cents=100,
        )
        resp = api.create_carrier(second, MANAGER)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY)


class TestShipmentRegistration:
    def test_shipment_delivery_before_ship_date_rejected(self, api):
        """PRD §3.2: "A `ClaimsClerk` registers it with its `bol_number` — unique across shipments, duplicates drawing `ERR_DUPLICATE_KEY` — the `carrier_id` and `lane_id` it moved under, the `ship_date` and `delivery_date` (delivery must not precede shipment, else `ERR_INVALID_TEMPORAL_RANGE`), the shipper-declared `declared_value_cents`, the `total_weight_lbs` (greater than zero), the `package_count` (greater than zero), a `commodity_class` of `GENERAL`, `FRAGILE`, `PERISHABLE`, `HIGH_VALUE`, or `HAZMAT`, and an optional `is_concealed_damage` flag that defaults to false and marks damage discovered after delivery without notation on the receipt."

        Design: Corner/entities/shipment_create_delivery_before_ship_rejected
        """
        from test_helpers import set_clock
        from test_helpers import create_shipment_payload

        set_clock("2026-06-01T00:00:00Z")
        carrier = validate_success(
            api.create_carrier(create_carrier_payload(), MANAGER), 201
        )
        lane = validate_success(api.create_lane(create_lane_payload(), MANAGER), 201)
        validate_success(
            api.create_assignment(
                create_assignment_payload(carrier["id"], lane["id"]), MANAGER
            ),
            201,
        )
        payload = create_shipment_payload(
            carrier["id"],
            lane["id"],
            ship_date="2026-06-10T00:00:00Z",
            delivery_date="2026-06-05T00:00:00Z",
        )
        resp = api.create_shipment(payload, CLERK)
        validate_error(resp, ApiErrorId.ERR_INVALID_TEMPORAL_RANGE)


class TestClaimIntake:
    def test_claim_create_initializes_workflow_fields(self, api):
        """PRD §3.2: "A new claim opens in `DRAFT` with `payment_status` `UNPAID` — the payment dimension's declared values are `UNPAID`, `PARTIAL`, `PAID_IN_FULL`, and `WAIVED`, with the middle two reached only through settlement acceptance as §3.6 describes — an `appeal_round` of zero, null `acknowledged_at`, `settlement_amount_cents`, and `liability_assessment_id`, and zeroed `computed_liability_cents`, `salvage_credit_cents`, `net_exposure_cents`, and `reserve_amount_cents`."

        Design: Corner/entities/claim_create_computed_fields_initialized
        """
        ctx = setup_claim_draft()
        claim = ctx["claim"]
        assert_claim(claim)
        assert claim["filing_status"] == "DRAFT"
        assert claim["payment_status"] == "UNPAID"
        assert claim["appeal_round"] == 0
        assert claim["acknowledged_at"] is None
        assert claim["settlement_amount_cents"] is None
        assert claim["liability_assessment_id"] is None
        assert claim["computed_liability_cents"] == 0
        assert claim["salvage_credit_cents"] == 0
        assert claim["net_exposure_cents"] == 0
        assert claim["reserve_amount_cents"] == 0

    def test_get_claim_unknown_id_returns_not_found(self, api, clerk_headers):
        """PRD §2.8: "The resource-specific identifiers are: `ERR_CARRIER_NOT_FOUND`, `ERR_LANE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SALVAGE_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_SUBROGATION_NOT_FOUND`, and `ERR_RESERVE_NOT_FOUND` — each HTTP 404, each naming exactly the path segment that failed to resolve."

        Design: Corner/entities/claim_get_not_found
        """
        resp = api.get_claim(NON_EXISTENT_UUID, clerk_headers)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FOUND)

    def test_get_carrier_unknown_id_returns_not_found(self, api, clerk_headers):
        """PRD §2.8: "The resource-specific identifiers are: `ERR_CARRIER_NOT_FOUND`, `ERR_LANE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SALVAGE_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_SUBROGATION_NOT_FOUND`, and `ERR_RESERVE_NOT_FOUND` — each HTTP 404, each naming exactly the path segment that failed to resolve."

        Design: Corner/errors/error_carrier_not_found_triggerable
        """
        resp = api.get_carrier(NON_EXISTENT_UUID, clerk_headers)
        validate_error(resp, ApiErrorId.ERR_CARRIER_NOT_FOUND)


class TestClaimOpeningReferentialGates:
    def test_claim_open_with_suspended_carrier_rejected(self, api):
        """PRD §3.2: "Four referential gates must all hold at opening: the shipment is in `DELIVERED` status, the carrier is `ACTIVE`, the lane is `ACTIVE`, and a carrier–lane assignment whose effectiveness window covers the shipment's `ship_date` exists; failure of any of them is reported as `ERR_SHIPMENT_NOT_DELIVERED`."

        Design: Difficulty/cross_entity_state_dependency/claim_create_requires_shipment_delivered_and_carrier_active
        """
        ctx = setup_claim_draft()  # establishes carrier, lane, assignment
        # Suspend the carrier before any shipment exists for it: with no claims
        # there is no open exposure, so the suspension itself is permitted.
        validate_success(api.suspend_carrier(ctx["carrier"]["id"], MANAGER), 200)
        from test_helpers import create_shipment_payload, get_success_data

        shipment = get_success_data(
            api.create_shipment(
                create_shipment_payload(ctx["carrier"]["id"], ctx["lane"]["id"]),
                CLERK,
            )
        )
        assert shipment["status"] == "DELIVERED"
        resp = api.create_claim(
            {"shipment_id": shipment["id"], "claim_type": "LOSS",
             "claimed_amount_cents": 500},
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_DELIVERED)

    def test_claim_open_on_claimed_shipment_rejected(self, api):
        """PRD §3.2: "Four referential gates must all hold at opening: the shipment is in `DELIVERED` status, the carrier is `ACTIVE`, the lane is `ACTIVE`, and a carrier–lane assignment whose effectiveness window covers the shipment's `ship_date` exists; failure of any of them is reported as `ERR_SHIPMENT_NOT_DELIVERED`."
        PRD §3.3: "It then ripples outward: the carrier's `claims_filed_count` increases by one and its `claim_ratio_bp` is recomputed; the lane's `claims_count` increases by one and `lane_claim_ratio_bp` is recomputed; the shipment moves from `DELIVERED` to `CLAIMED`; a `FILED` event is appended to the claim's log; and the claim's `version` increments."

        Design: Difficulty/cross_entity_state_dependency/claim_create_requires_shipment_delivered_and_carrier_active
        """
        from test_helpers import setup_claim_submitted

        # After the first claim submits, the shipment is CLAIMED, not DELIVERED.
        ctx = setup_claim_submitted()
        resp = api.create_claim(
            {"shipment_id": ctx["shipment"]["id"], "claim_type": "LOSS",
             "claimed_amount_cents": 500},
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_DELIVERED)


class TestAssignmentListing:
    def test_assignments_filter_by_carrier(self, api, clerk_headers):
        """PRD §2.3: "Beyond pagination, list endpoints accept resource-specific filters: carriers filter by `status`; lanes filter by `status`; carrier–lane assignments filter by `carrier_id` and `lane_id`; shipments filter by `carrier_id`, `lane_id`, and `status`; claims filter by `carrier_id`, `lane_id`, `shipment_id`, `filing_status`, `payment_status`, and `liability_assessment_id`; documents filter by `verification_status` and `document_kind`; salvage dispositions, appeals, settlements, subrogation cases, and reserves each filter by `state`; the claim event log filters by `event_kind`; calendar rows filter by `day_kind`; the carrier claim-ratio analytic filters by `carrier_id` and a `window` selector; and the lane claim-ratio analytic filters by `lane_id`."

        Design: Corner/entities/carrier_lane_assignment_reverse_reachable_via_filtered_list
        """
        from test_helpers import set_clock

        set_clock("2026-06-01T00:00:00Z")
        carrier = validate_success(
            api.create_carrier(create_carrier_payload(), MANAGER), 201
        )
        lane1 = validate_success(api.create_lane(create_lane_payload(), MANAGER), 201)
        lane2 = validate_success(api.create_lane(create_lane_payload(), MANAGER), 201)
        validate_success(
            api.create_assignment(
                create_assignment_payload(carrier["id"], lane1["id"]), MANAGER
            ),
            201,
        )
        validate_success(
            api.create_assignment(
                create_assignment_payload(
                    carrier["id"], lane2["id"], contracted_discount_pct=5
                ),
                MANAGER,
            ),
            201,
        )
        resp = api.list_assignments(clerk_headers, params={"carrier_id": carrier["id"]})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2, (
            f"Expected 2 assignments for carrier, got {meta['total_count']}"
        )
        assert len(data) == 2
        assert all(row["carrier_id"] == carrier["id"] for row in data)
