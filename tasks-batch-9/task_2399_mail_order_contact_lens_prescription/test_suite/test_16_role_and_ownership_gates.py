"""Role gates, ownership gates and the two-person split on compliance work.

Every caller declares a role, and the declared role decides which endpoints it
may address at all; on top of that, the two entity-backed roles are additionally
scoped to the rows they own, and the return workflow is split across two
compliance operators.
"""

from test_helpers import (
    ADMIN_HEADERS,
    CO_ALPHA,
    CO_ALPHA_HEADERS,
    CO_BRAVO,
    CO_BRAVO_HEADERS,
    DEFAULT_CLOCK_UTC,
    FO_HEADERS,
    WORKING_TUESDAY_10AM,
    ApiErrorId,
    create_order_payload,
    create_prescription_payload,
    create_reorder_hold_payload,
    make_customer_headers,
    make_prescriber_headers,
    new_customer,
    new_order,
    new_prescriber,
    new_product,
    respond_to_verification_request,
    set_clock,
    setup_approved_return,
    setup_order_on_verified_prescription,
    setup_pending_verification_prescription,
    setup_verification_round,
    setup_verified_prescription,
    validate_error,
    validate_paginated,
    validate_success,
)

SECOND_CUSTOMER = {"full_name": "Ben Ortiz", "email": "ben.ortiz@example.com"}
SECOND_PRESCRIBER = {
    "full_name": "Dr. Ivo Renner",
    "license_number": "UT-50117",
    "contact_channel": "FAX",
    "directory_verified": False,
}


class TestComplianceDeskExclusiveOperations:
    def test_one_officer_drives_round_sweep_hold_and_invalidation(self, api):
        """PRD §2.1: "`ComplianceOfficer` is the compliance desk: it opens
        verification rounds, runs sweeps, manages holds, and performs both halves
        of the return workflow (with the halves necessarily performed by two
        different `X-User-ID` values)."

        PRD §3.3: "It records the `prescription_id` being verified and the
        `prescriber_id` receiving the contact, snapshots the provider's
        `contact_channel` into its own `channel`, and stamps `sent_at` from the
        logical clock."

        PRD §3.3: "Each request's `passive_deadline_at` is computed by advancing
        a business-hour budget from `sent_at`: **eight** business hours when the
        receiving provider's `directory_verified` flag is true, and **twelve**
        business hours when it is false, because a prescriber the patient merely
        named deserves longer to object than one the directory confirmed."

        PRD §3.4: "When a correction round stalls and nobody will confirm, a
        compliance officer may invalidate the prescription manually, supplying a
        `reason`."

        PRD §3.4: "It appends an `RX_INVALIDATED` compliance event, opens a
        reorder hold with `reason` `MANUAL` in `OPEN` status, and recomputes the
        customer's `open_hold_count` and `auto_reorder_enabled`."

        Design: Corner/rbac/compliance_officer_performs_all_of_its_exclusive_operations
        """
        scenario = setup_pending_verification_prescription(
            clock=WORKING_TUESDAY_10AM,
            directory_verified=True,
            contact_channel="PORTAL",
        )
        customer_id = scenario["customer"]["id"]
        prescription_id = scenario["prescription"]["id"]
        prescriber_id = scenario["prescriber"]["id"]

        # 1 — opening a passive verification round.
        round_one = validate_success(
            api.send_verification_request(
                prescription_id, {"prescriber_id": prescriber_id}, CO_ALPHA_HEADERS
            ),
            201,
        )
        assert round_one["status"] == "SENT"
        assert round_one["round_number"] == 1
        assert round_one["channel"] == "PORTAL"
        assert round_one["passive_deadline_at"] == "2026-09-09T09:00:00.000Z"

        # 2 — running the verification sweep; nothing is due yet.
        sweep = validate_success(api.run_verification_sweep(CO_ALPHA_HEADERS))
        assert sweep["promoted_prescription_ids"] == []
        assert sweep["timed_out_request_ids"] == []
        assert sweep["expired_prescription_ids"] == []
        assert sweep["holds_opened_count"] == 0
        assert sweep["schedules_paused_count"] == 0

        # 3 — opening a reorder hold manually.
        hold = validate_success(
            api.create_reorder_hold(
                create_reorder_hold_payload(customer_id, prescription_id),
                CO_ALPHA_HEADERS,
            ),
            201,
        )
        assert hold["status"] == "OPEN"
        assert hold["opened_by_user_id"] == CO_ALPHA

        # A manual invalidation is declared for a prescription in
        # CORRECTION_PENDING, so the outstanding round is answered with a
        # correction before the fourth compliance-only call is made.
        respond_to_verification_request(
            round_one["id"],
            prescriber_id,
            "CORRECTED",
            corrected_od_sphere=-2.50,
            corrected_os_sphere=-4.00,
        )

        # 4 — manually invalidating the stalled correction.
        invalidated = validate_success(
            api.invalidate_prescription(
                prescription_id, {"reason": "prescriber unreachable"}, CO_ALPHA_HEADERS
            )
        )
        assert invalidated["status"] == "INVALIDATED"

        _, meta = validate_paginated(
            api.list_reorder_holds(
                CO_ALPHA_HEADERS,
                params={"customer_id": customer_id, "status": "OPEN"},
            )
        )
        assert meta["total_count"] == 2, (
            "the manual hold plus the one the invalidation cascade opened"
        )


class TestHoldOpeningIsComplianceExclusive:
    def test_warehouse_operator_cannot_open_a_reorder_hold(self, api):
        """PRD §2.1: "If the header pair is present but the declared role is not
        one of the roles authorised for the addressed endpoint in §4, the request
        is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        PRD §2.1: "`FulfillmentOperator` is warehouse staff: it substitutes,
        ships, delivers and drives the auto-reorder run, and never touches holds,
        claims or disputes."

        PRD §3.7: "Opening a hold manually records the acting `X-User-ID` in
        `opened_by_user_id`, increments the customer's `open_hold_count`,
        recomputes `auto_reorder_enabled`, and appends a `HOLD_OPENED` compliance
        event."

        Design: Corner/rbac/fulfillment_operator_cannot_open_a_reorder_hold
        """
        scenario = setup_verified_prescription(clock=DEFAULT_CLOCK_UTC)
        customer_id = scenario["customer"]["id"]
        payload = create_reorder_hold_payload(
            customer_id, scenario["prescription"]["id"]
        )

        validate_error(
            api.create_reorder_hold(payload, FO_HEADERS),
            ApiErrorId.ERR_UNAUTHORIZED,
        )

        _, meta = validate_paginated(
            api.list_reorder_holds(
                CO_ALPHA_HEADERS, params={"customer_id": customer_id}
            )
        )
        assert meta["total_count"] == 0, "the refused call must create no hold row"

        ledger = validate_success(
            api.get_customer_ledger(customer_id, make_customer_headers(customer_id))
        )
        assert ledger["open_hold_count"] == 0

        # The identical body is accepted from the compliance desk.
        hold = validate_success(
            api.create_reorder_hold(payload, CO_ALPHA_HEADERS), 201
        )
        assert hold["status"] == "OPEN"
        assert hold["opened_by_user_id"] == CO_ALPHA


class TestOrderReadSharing:
    def test_four_roles_read_the_order_but_a_stranger_patient_cannot(self, api):
        """PRD §2.1: "Ownership checks on any resource that references a Customer
        compare that resource's customer foreign key to `X-User-ID`: a patient
        may address only their own prescriptions, orders, auto-reorder schedules,
        return requests, reimbursement claims, reorder holds and ledger."

        PRD §2.1: "A failed ownership check yields `ERR_IDENTITY_MISMATCH` (HTTP
        403)."

        PRD §3.5: "Its `verification_state` is seeded from the prescription:
        `RX_CLEARED` when the prescription is already `VERIFIED_ACTIVE`, and
        `RX_PENDING` otherwise."

        Design: Corner/rbac/order_read_is_shared_by_four_roles_but_still_ownership_scoped
        """
        scenario = setup_verified_prescription(clock=DEFAULT_CLOCK_UTC)
        owner_id = scenario["customer"]["id"]
        stranger_id = new_customer(**SECOND_CUSTOMER)["id"]
        order = new_order(
            owner_id,
            scenario["prescription"]["id"],
            scenario["product"]["id"],
            1,
            1,
        )

        as_compliance = validate_success(
            api.get_order(order["id"], CO_ALPHA_HEADERS)
        )
        assert as_compliance["id"] == order["id"]
        assert as_compliance["verification_state"] == "RX_CLEARED"
        assert as_compliance["fulfillment_state"] == "PENDING"

        for headers in (make_customer_headers(owner_id), FO_HEADERS, ADMIN_HEADERS):
            shared = validate_success(api.get_order(order["id"], headers))
            assert shared["id"] == order["id"]
            assert shared["total_cents"] == 6400

        validate_error(
            api.get_order(order["id"], make_customer_headers(stranger_id)),
            ApiErrorId.ERR_IDENTITY_MISMATCH,
        )

        _, meta = validate_paginated(
            api.list_orders(CO_ALPHA_HEADERS, params={"customer_id": stranger_id})
        )
        assert meta["total_count"] == 0


class TestReturnSettlementSegregation:
    def test_approver_cannot_settle_but_a_second_officer_can(self, api):
        """PRD §2.8: "Settling a return request requires an `X-User-ID` different
        from the request's `approved_by_user_id`."

        PRD §2.8: "A violation of either rule is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

        PRD §3.8: "Under `NO_PRORATION`, no box residue is considered at all: the
        candidate figure is `torn_lens_count` multiplied by the per-box value,
        divided by the lenses per box and rounded half up to a whole cent, and
        `settlement_cents` is whichever is smaller — that candidate figure, or a
        cap equal to twenty percent of the order's `total_cents` with any
        fraction of a cent discarded downward."

        PRD §3.8: "Settlement records `settled_by_user_id`, and this is where
        money actually moves: a `STORE_CREDIT` settlement credits the customer's
        `store_credit_cents`, while a `CASH_REFUND` settlement increases
        `lifetime_refunded_cents`, and either way `net_cash_position_cents` is
        then reconciled."

        Design: Corner/rbac/return_settlement_requires_a_different_officer_than_the_approver
        """
        scenario = setup_approved_return(
            reason="TORN_LENS",
            return_overrides={"torn_lens_count": 30, "unopened_boxes": 0},
            approver=CO_ALPHA,
            clock=DEFAULT_CLOCK_UTC,
        )
        customer_id = scenario["customer"]["id"]
        return_id = scenario["return_request"]["id"]
        assert scenario["return_request"]["settlement_cents"] == 1280
        assert scenario["return_request"]["settlement_channel"] == "STORE_CREDIT"

        validate_error(
            api.settle_return_request(return_id, CO_ALPHA_HEADERS),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )

        unsettled = validate_success(
            api.get_return_request(return_id, CO_ALPHA_HEADERS)
        )
        assert unsettled["approved_by_user_id"] == CO_ALPHA
        assert unsettled["settled_by_user_id"] is None
        assert unsettled["settlement_cents"] == 1280

        blocked_ledger = validate_success(
            api.get_customer_ledger(customer_id, make_customer_headers(customer_id))
        )
        assert blocked_ledger["store_credit_cents"] == 0
        assert blocked_ledger["net_cash_position_cents"] == 6400

        settled = validate_success(
            api.settle_return_request(return_id, CO_BRAVO_HEADERS)
        )
        assert settled["status"] == "SETTLED"
        assert settled["settled_by_user_id"] == CO_BRAVO

        settled_ledger = validate_success(
            api.get_customer_ledger(customer_id, make_customer_headers(customer_id))
        )
        assert settled_ledger["store_credit_cents"] == 1280
        assert settled_ledger["net_cash_position_cents"] == 6400


class TestPrescriberResponseOwnership:
    def test_uninvolved_prescriber_is_an_identity_mismatch_not_a_role_refusal(
        self, api
    ):
        """PRD §2.1: "Ownership checks compare the addressed resource's
        prescriber foreign key to `X-User-ID`: a provider may respond only to
        verification requests addressed to them, and may file disputes only
        against prescriptions that name them."

        PRD §3.4: "The responding provider's identity must equal the request's
        `prescriber_id`, or the attempt is refused with `ERR_IDENTITY_MISMATCH`."

        PRD §3.4: "A `CONFIRMED` response sets the request's `status` and
        `response_type` both to `CONFIRMED` and promotes the prescription from
        `PENDING_VERIFICATION` to `VERIFIED_ACTIVE`."

        Design: Corner/rbac/prescriber_may_only_respond_to_a_request_addressed_to_itself
        """
        scenario = setup_verification_round(
            clock=WORKING_TUESDAY_10AM,
            directory_verified=True,
            contact_channel="PORTAL",
        )
        addressed_id = scenario["prescriber"]["id"]
        prescription_id = scenario["prescription"]["id"]
        request_id = scenario["verification_request"]["id"]
        uninvolved_id = new_prescriber(**SECOND_PRESCRIBER)["id"]

        validate_error(
            api.respond_to_verification_request(
                request_id,
                {"response_type": "CONFIRMED"},
                make_prescriber_headers(uninvolved_id),
            ),
            ApiErrorId.ERR_IDENTITY_MISMATCH,
        )

        untouched = validate_success(
            api.get_verification_request(request_id, CO_ALPHA_HEADERS)
        )
        assert untouched["status"] == "SENT"
        assert untouched["response_type"] is None

        still_pending = validate_success(
            api.get_prescription(prescription_id, CO_ALPHA_HEADERS)
        )
        assert still_pending["status"] == "PENDING_VERIFICATION"

        confirmed = validate_success(
            api.respond_to_verification_request(
                request_id,
                {"response_type": "CONFIRMED"},
                make_prescriber_headers(addressed_id),
            )
        )
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["response_type"] == "CONFIRMED"

        promoted = validate_success(
            api.get_prescription(prescription_id, CO_ALPHA_HEADERS)
        )
        assert promoted["status"] == "VERIFIED_ACTIVE"


class TestFulfillmentIsNotConferredByOwnership:
    def test_owning_patient_cannot_ship_but_can_cancel(self, api):
        """PRD §2.1: "If the header pair is present but the declared role is not
        one of the roles authorised for the addressed endpoint in §4, the request
        is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        PRD §3.7: "Shipping stamps `shipped_at` from the logical clock and leaves
        `verification_state` untouched."

        PRD §3.7: "Cancellation is available while an order is still `PENDING`
        and is a full **compensating** operation, reversing every forward effect
        of placement."

        Design: Corner/rbac/customer_cannot_ship_its_own_order
        """
        scenario = setup_order_on_verified_prescription(clock=DEFAULT_CLOCK_UTC)
        customer_id = scenario["customer"]["id"]
        owner_headers = make_customer_headers(customer_id)
        order_id = scenario["order"]["id"]

        validate_error(
            api.ship_order(order_id, owner_headers),
            ApiErrorId.ERR_UNAUTHORIZED,
        )

        unshipped = validate_success(api.get_order(order_id, owner_headers))
        assert unshipped["fulfillment_state"] == "PENDING"
        assert unshipped["shipped_at"] is None

        shipped = validate_success(api.ship_order(order_id, FO_HEADERS))
        assert shipped["fulfillment_state"] == "SHIPPED"

        # Cancellation is the patient-side action on a still-pending order, so
        # the role split is a split rather than a blanket read-only rule.
        second_order = new_order(
            customer_id,
            scenario["prescription"]["id"],
            scenario["product"]["id"],
            1,
            1,
        )
        cancelled = validate_success(
            api.cancel_order(
                second_order["id"],
                {"cancellation_reason": "CUSTOMER_REQUEST"},
                owner_headers,
            )
        )
        assert cancelled["fulfillment_state"] == "CANCELLED"
        assert cancelled["cancellation_reason"] == "CUSTOMER_REQUEST"


class TestPlatformAdminSharesEveryOperation:
    def test_admin_drives_capture_submit_order_and_ship_end_to_end(self, api):
        """PRD §2.1: "The remaining three roles are **opaque**: when
        `X-User-Role` is `ComplianceOfficer`, `FulfillmentOperator`, or
        `PlatformAdmin`, `X-User-ID` is an operator identifier that is not tied
        to any persisted entity."

        PRD §2.1: "`PlatformAdmin` owns reference-data setup and the logical
        clock and may additionally perform any other operation in this
        specification, but is still bound by the segregation-of-duties rules in
        §2.8."

        PRD §3.5: "Placing an order also moves the ledgers forward: the
        prescription's `boxes_consumed` grows by the ordered boxes, and the
        customer's `lifetime_charged_cents` and `net_cash_position_cents` are
        reconciled."

        Design: Corner/rbac/platform_admin_shares_every_workflow_operation
        """
        set_clock(DEFAULT_CLOCK_UTC)
        product = new_product()
        customer = new_customer()

        captured = validate_success(
            api.create_prescription(
                create_prescription_payload(customer["id"], product["id"]),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert captured["status"] == "DRAFT"

        submitted = validate_success(
            api.submit_prescription(captured["id"], ADMIN_HEADERS)
        )
        assert submitted["status"] == "VERIFIED_ACTIVE"

        order = validate_success(
            api.create_order(
                create_order_payload(
                    customer["id"], captured["id"], product["id"], 1, 1
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert order["customer_id"] == customer["id"]
        assert order["verification_state"] == "RX_CLEARED"
        assert order["total_cents"] == 6400

        shipped = validate_success(api.ship_order(order["id"], ADMIN_HEADERS))
        assert shipped["fulfillment_state"] == "SHIPPED"

        ledger = validate_success(
            api.get_customer_ledger(customer["id"], ADMIN_HEADERS)
        )
        assert ledger["lifetime_charged_cents"] == 6400
