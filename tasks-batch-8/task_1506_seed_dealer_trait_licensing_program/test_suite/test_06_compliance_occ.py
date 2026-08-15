"""Trait stewardship: agreement lifecycle, the suspension cascade, stewardship
gates on selling, and optimistic concurrency on grower/field writes."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_line,
    assert_trait_agreement,
    confirm_order,
    create_draft_order,
    create_grower,
    create_pending_agreement,
    create_recommendation_payload,
    create_signed_agreement,
    create_trait_agreement_payload,
    create_trait_package,
    get_program_commission_statement,
    get_success_data,
    set_clock,
    setup_market,
    setup_traited_market,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
SALESREP = TEST_USERS["salesrep_headers"]
AGRONOMIST = TEST_USERS["agronomist_headers"]


class TestAgreementCycle:
    def test_agreement_sign_then_suspend(self, api):
        """PRD §3.3: "An administrator may suspend an active agreement, moving
        it `ACTIVE → SUSPENDED` and recording the request's `reason` — one of
        `STEWARDSHIP_VIOLATION` or `PAPERWORK` — into `suspension_reason`."

        Design: Difficulty/non_linear_state_machine/trait_agreement_active_suspended_cycle_twice
        """
        grower = create_grower()
        package = create_trait_package()
        agreement = create_pending_agreement(grower, package["id"])
        signed = validate_success(api.sign_trait_agreement(agreement["id"], ADMIN))
        assert_trait_agreement(signed)
        assert signed["status"] == "ACTIVE"

        suspended = validate_success(
            api.suspend_trait_agreement(agreement["id"], "STEWARDSHIP_VIOLATION", ADMIN)
        )
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "STEWARDSHIP_VIOLATION"

    def test_agreement_cycle_repeats_and_reason_refreshes(self, api):
        """PRD §3.3: "Reinstatement moves a suspended agreement `SUSPENDED →
        ACTIVE`, requires the logical clock to be no later than `effective_to`
        (otherwise `ERR_AGREEMENT_EXPIRED`), and clears `suspension_reason`."

        Design: Difficulty/non_linear_state_machine/trait_agreement_active_suspended_cycle_twice
        """
        grower = create_grower()
        package = create_trait_package()
        agreement = create_signed_agreement(grower, package["id"])

        get_success_data(
            api.suspend_trait_agreement(agreement["id"], "STEWARDSHIP_VIOLATION", ADMIN)
        )
        reinstated = validate_success(
            api.reinstate_trait_agreement(agreement["id"], ADMIN)
        )
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["suspension_reason"] is None

        suspended_again = validate_success(
            api.suspend_trait_agreement(agreement["id"], "PAPERWORK", ADMIN)
        )
        assert suspended_again["status"] == "SUSPENDED"
        assert suspended_again["suspension_reason"] == "PAPERWORK"


class TestSuspensionCascade:
    def _confirmed_traited_order(self, api):
        """Program + grower with signed agreement + 100-unit CONFIRMED order of
        the traited variety. Lot starts with 500 units; 100 are reserved."""
        ctx = setup_traited_market()
        set_clock("2027-01-10T00:00:00Z")
        order = create_draft_order(ctx["grower"], ctx["program"])
        line = add_line(order, ctx["variety"]["id"], 100)
        order = confirm_order(order["id"])
        return {**ctx, "order": order, "line": line}

    def test_suspend_holds_order_and_releases_reservations(self, api):
        """PRD §3.3: "First, every seed order whose `grower_id` matches the
        agreement's grower, whose status is `CONFIRMED`, and which contains at
        least one line whose variety carries the agreement's trait package moves
        to `COMPLIANCE_HOLD`. Second, each such order releases every line
        reservation: the line's `inventory_lot_id` is cleared, the lot's
        `reserved_units` is decremented by the line's `reserved_units`, and the
        line's `reserved_units` falls to zero."

        Design: Difficulty/transitive_cascade/agreement_suspend_cascades_order_hold_reservation_release_statement_drop
        """
        ctx = self._confirmed_traited_order(api)
        lot_before = validate_success(api.get_inventory_lot(ctx["lot"]["id"], ADMIN))
        assert lot_before["reserved_units"] == 100

        suspended = validate_success(
            api.suspend_trait_agreement(ctx["agreement"]["id"], "STEWARDSHIP_VIOLATION",
                                        ADMIN)
        )
        assert suspended["status"] == "SUSPENDED"

        order = validate_success(api.get_order(ctx["order"]["id"], SALESREP))
        assert order["status"] == "COMPLIANCE_HOLD"
        line = validate_success(api.get_order_line(ctx["line"]["id"], SALESREP))
        assert line["reserved_units"] == 0
        assert line["inventory_lot_id"] is None
        lot_after = validate_success(api.get_inventory_lot(ctx["lot"]["id"], ADMIN))
        assert lot_after["reserved_units"] == 0

    def test_suspend_drops_held_order_from_commission_accrual(self, api):
        """PRD §3.3: "Fourth, on the commission ledger, held orders leave the
        provisional inclusion set, so the next statement recompute drops their
        net amounts and units from the accrual."
        PRD §3.9: "the inclusion set is the program's orders in `CONFIRMED` or
        `CLOSED`".

        Design: Difficulty/transitive_cascade/agreement_suspend_cascades_order_hold_reservation_release_statement_drop
        """
        ctx = self._confirmed_traited_order(api)
        statement = get_program_commission_statement(ctx["program"]["id"])
        before = validate_success(
            api.recompute_commission_statement(statement["id"], ADMIN)
        )
        assert before["net_sales_cents"] == ctx["order"]["net_amount_cents"]

        get_success_data(
            api.suspend_trait_agreement(ctx["agreement"]["id"], "STEWARDSHIP_VIOLATION",
                                        ADMIN)
        )
        after = validate_success(
            api.recompute_commission_statement(statement["id"], ADMIN)
        )
        assert after["net_sales_cents"] == 0
        assert after["volume_units"] == 0


class TestStewardshipGates:
    def test_line_add_rejected_while_agreement_pending(self, api):
        """PRD §3.3: "whenever seed of a variety whose trait package has
        `requires_stewardship_agreement` set is sold or endorsed — adding the
        line to an order, confirming the order, releasing a held order, or
        accepting a recommendation for the variety — an `ACTIVE` agreement for
        the grower-and-package pair must exist with the logical clock inside its
        window, otherwise the operation is rejected with
        `ERR_TRAIT_AGREEMENT_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/line_add_gated_by_trait_agreement_state
        """
        ctx = setup_traited_market(sign_agreement=False)
        assert ctx["agreement"]["status"] == "PENDING_SIGNATURE"
        order = create_draft_order(ctx["grower"], ctx["program"])
        resp = api.add_order_line(
            order["id"], {"variety_id": ctx["variety"]["id"], "units": 10}, SALESREP
        )
        validate_error(resp, ApiErrorId.ERR_TRAIT_AGREEMENT_NOT_ACTIVE)

    def test_line_add_accepted_once_agreement_active(self, api):
        """PRD §3.3: "whenever seed of a variety whose trait package has
        `requires_stewardship_agreement` set is sold or endorsed — adding the
        line to an order, confirming the order, releasing a held order, or
        accepting a recommendation for the variety — an `ACTIVE` agreement for
        the grower-and-package pair must exist with the logical clock inside its
        window, otherwise the operation is rejected with
        `ERR_TRAIT_AGREEMENT_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/line_add_gated_by_trait_agreement_state
        """
        ctx = setup_traited_market(sign_agreement=False)
        order = create_draft_order(ctx["grower"], ctx["program"])
        get_success_data(api.sign_trait_agreement(ctx["agreement"]["id"], ADMIN))

        line = validate_success(
            api.add_order_line(
                order["id"], {"variety_id": ctx["variety"]["id"], "units": 10}, SALESREP
            ),
            expected_status=201,
        )
        assert line["units"] == 10
        lines, meta = validate_paginated(
            api.list_order_lines(SALESREP, params={"order_id": order["id"]})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in lines] == [line["id"]]


class TestGrowerStateGate:
    def test_confirm_rejected_while_grower_on_credit_hold(self, api):
        """PRD §3.5: "the grower must be `ACTIVE` (`ERR_GROWER_NOT_ACTIVE`)".

        Design: Difficulty/cross_entity_state_dependency/order_confirm_gated_by_grower_account_state
        """
        ctx = setup_market()
        set_clock("2027-01-10T00:00:00Z")
        order = create_draft_order(ctx["grower"], ctx["program"])
        add_line(order, ctx["variety"]["id"], 10)
        get_success_data(api.hold_grower(ctx["grower"]["id"], ADMIN))

        resp = api.confirm_order(order["id"], SALESREP)
        validate_error(resp, ApiErrorId.ERR_GROWER_NOT_ACTIVE)

    def test_confirm_succeeds_after_hold_released(self, api):
        """PRD §3.2: "Releasing the hold returns the account
        `CREDIT_HOLD → ACTIVE`."
        PRD §3.5: "the grower must be `ACTIVE` (`ERR_GROWER_NOT_ACTIVE`)".

        Design: Difficulty/cross_entity_state_dependency/order_confirm_gated_by_grower_account_state
        """
        ctx = setup_market()
        set_clock("2027-01-10T00:00:00Z")
        order = create_draft_order(ctx["grower"], ctx["program"])
        add_line(order, ctx["variety"]["id"], 10)
        get_success_data(api.hold_grower(ctx["grower"]["id"], ADMIN))
        get_success_data(api.release_grower_hold(ctx["grower"]["id"], ADMIN))

        confirmed = validate_success(api.confirm_order(order["id"], SALESREP))
        assert confirmed["status"] == "CONFIRMED"


class TestOptimisticConcurrency:
    def test_occ_stale_grower_version_rejected_on_agreement_create(self, api):
        """PRD §2.7: "If the grower's current `version` has advanced past the
        supplied value — for example because another writer has just created or
        signed an agreement for the same grower, legitimately superseding the
        prior active one — the create is rejected with
        `ERR_STALE_GROWER_VERSION` (HTTP 412), preventing the caller from
        writing on top of an agreement stack it has not observed. A successful
        create increments the grower's `version` by one."

        Design: Corner/cross_cutting_layers/occ_stale_grower_version_rejected_on_agreement_create
        """
        grower = create_grower()
        package_a = create_trait_package(code="VT2P")
        package_b = create_trait_package(
            code="SS-RR2", description="Roundup Ready 2", refuge_required_bps=0
        )
        observed_version = grower["version"]

        first = validate_success(
            api.create_trait_agreement(
                create_trait_agreement_payload(grower["id"], package_a["id"],
                                               observed_version),
                ADMIN,
            ),
            expected_status=201,
        )
        assert first["status"] == "PENDING_SIGNATURE"

        resp = api.create_trait_agreement(
            create_trait_agreement_payload(grower["id"], package_b["id"],
                                           observed_version),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_GROWER_VERSION, expected_status=412)

    def test_occ_stale_field_version_rejected_on_recommendation_create(self, api):
        """PRD §2.7: "If the field's current `version` no longer matches — for
        example because another agronomist has just created a recommendation for
        the same field, and publishing would legitimately supersede the prior
        published one — the create is rejected with `ERR_STALE_FIELD_VERSION`
        (HTTP 412). A successful create increments the field's `version` by
        one."

        Design: Corner/cross_cutting_layers/occ_stale_field_version_rejected_on_recommendation_create
        """
        ctx = setup_market(with_lot=False, with_field=True)
        observed_version = ctx["field"]["version"]

        first = validate_success(
            api.create_recommendation(
                create_recommendation_payload(
                    ctx["field"]["id"], ctx["variety"]["id"], ctx["program"]["id"],
                    observed_version,
                ),
                AGRONOMIST,
            ),
            expected_status=201,
        )
        assert first["status"] == "DRAFT"

        resp = api.create_recommendation(
            create_recommendation_payload(
                ctx["field"]["id"], ctx["variety"]["id"], ctx["program"]["id"],
                observed_version - 1, seeding_rate_seeds_per_acre=36000,
                expected_yield_index=110,
            ),
            AGRONOMIST,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_FIELD_VERSION, expected_status=412)


class TestAgreementWindowRules:
    def test_reinstate_agreement_past_window_rejected(self, api):
        """PRD §3.3: "Reinstatement moves a suspended agreement `SUSPENDED →
        ACTIVE`, requires the logical clock to be no later than `effective_to`
        (otherwise `ERR_AGREEMENT_EXPIRED`), and clears `suspension_reason`."

        Design: Corner/validations/reinstate_agreement_past_window_rejected
        """
        grower = create_grower()
        package = create_trait_package()
        agreement = create_signed_agreement(
            grower, package["id"], effective_to="2027-01-31T23:59:59Z"
        )
        get_success_data(api.suspend_trait_agreement(agreement["id"], "PAPERWORK", ADMIN))
        set_clock("2027-02-01T00:00:00Z")

        resp = api.reinstate_trait_agreement(agreement["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_EXPIRED)
        agreement_after = validate_success(api.get_trait_agreement(agreement["id"], ADMIN))
        assert agreement_after["status"] == "SUSPENDED"
