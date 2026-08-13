"""License approval/ledger, shipment release fiscal rules, fees, delivery close-out (PRD §3.5, §3.6, §3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_license,
    assert_license_consumption_invariants,
    assert_shipment,
    audit_records_for,
    create_approved_license,
    create_classified_product,
    create_draft_license,
    create_released_shipment,
    create_screened_shipment,
    create_shipment,
    get_license,
    get_order,
    get_shipment,
    get_success_data,
    make_analyst_headers,
    make_manager_headers,
    release_shipment,
    setup_licensed_order,
    setup_released_licensed_order,
    setup_released_not_required_order,
    submit_license,
    validate_error,
    validate_success,
)


class TestLicenseApproval:
    def test_license_approval_side_effects(self, api, manager_headers):
        """PRD §3.5: "`APPROVE` requires the reviewer to differ from `applicant_user_id` (else `ERR_SEGREGATION_OF_DUTIES`) and performs a cluster of writes: the license becomes `APPROVED`, `reviewed_by_user_id` is anchored, a `license_number` is assigned from a system-wide monotone counter formatted as `LIC-` followed by six zero-padded digits beginning at `LIC-000001`, `remaining_value_cents` initializes to `approved_value_cents` and `remaining_quantity` to `approved_quantity`, and an audit record of type `LICENSE_APPROVED` is written."

        Design: Corner/state_machines/license_approval_side_effects
        """
        product, _ = create_classified_product(sku="P-016", name="Latch",
                                               controlled_content_pct=0, unit_value_cents=10,
                                               classification_code="EAR99")
        lic = create_approved_license(product["id"], approved_value_cents=42000,
                                      approved_quantity=7)
        assert_license(lic)
        assert lic["license_number"] == "LIC-000001", (
            f"first approval must mint LIC-000001, got {lic['license_number']}"
        )
        assert lic["remaining_value_cents"] == 42000
        assert lic["remaining_quantity"] == 7
        assert lic["reviewed_by_user_id"] == "manager-1"

        records = audit_records_for("License", lic["id"], event_type="LICENSE_APPROVED")
        assert len(records) == 1, (
            f"exactly one LICENSE_APPROVED record expected, got {len(records)}"
        )

    def test_denied_license_is_terminal(self, api, manager2_headers):
        """PRD §3.5: "`DENY` lands the application in the terminal `DENIED` state; `RETURN` sends it to `RETURNED_FOR_INFO`, from which an analyst may resubmit — the resubmission re-anchors `applicant_user_id`, so the segregation check on the next review binds to whoever resubmitted."

        Design: Corner/state_machines/denied_license_is_terminal
        """
        product, _ = create_classified_product(sku="P-015", name="Clamp",
                                               controlled_content_pct=0, unit_value_cents=10,
                                               classification_code="EAR99")
        lic = create_draft_license(product["id"], approved_value_cents=1000,
                                   approved_quantity=10)
        submit_license(lic["id"])
        denied = get_success_data(
            api.review_license(lic["id"], {"decision": "DENY"}, make_manager_headers("manager-1"))
        )
        assert denied["status"] == "DENIED"

        # A second review attempt on the terminal DENIED license must fail.
        res = api.review_license(lic["id"], {"decision": "APPROVE"}, manager2_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        after = get_license(lic["id"])
        assert after["status"] == "DENIED"

    def test_sod_license_self_approval_rejected(self, api):
        """PRD §2.10: "a license application's `applicant_user_id` cannot equal its reviewer's `X-User-ID`"
        PRD §2.10: "Any breach is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

        Design: Corner/validations/sod_license_self_approval_rejected
        """
        product, _ = create_classified_product(sku="P-033", name="Bar",
                                               controlled_content_pct=0, unit_value_cents=10,
                                               classification_code="EAR99")
        lic = create_draft_license(product["id"], approved_value_cents=1000,
                                   approved_quantity=10)
        submit_license(lic["id"], headers=make_analyst_headers("user-shared"))

        res = api.review_license(lic["id"], {"decision": "APPROVE"},
                                 make_manager_headers("user-shared"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        after = get_license(lic["id"])
        assert after["status"] == "SUBMITTED", (
            f"rejected review must leave the license SUBMITTED, got {after['status']}"
        )


class TestShipmentReleaseGuards:
    def test_screened_shipment_release_rejected_while_order_licensed(self, api, ops_headers):
        """PRD §3.7: "Release is the fiscally decisive step, guarded by a layered check set: the shipment must be `SCREENED` (else `ERR_INVALID_STATE`); the parent order must be `RELEASED` (else `ERR_INVALID_STATE`); the party's posture must be neither `BLOCKED` (`ERR_PARTY_BLOCKED`) nor `REVIEW_REQUIRED` (`ERR_SCREENING_REVIEW_PENDING`);"

        Design: Difficulty/cross_entity_state_dependency/shipment_release_gated_on_order_released
        """
        ctx = setup_licensed_order(
            order_quantity=4, party_name="Danube Logistics Kft", party_country="HUN",
            party_city="Budapest", destination_country="HUN",
        )
        shipment = create_screened_shipment(ctx["order"]["id"], quantity=4,
                                            planned_ship_date="2026-08-15")

        res = api.release_shipment(shipment["id"], ops_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_no_consumption_after_order_state_rejection(self, api, ops_headers, manager_headers):
        """PRD §3.7: "the parent order must be `RELEASED` (else `ERR_INVALID_STATE`)"
        PRD §3.5: "Shipment releases draw the remaining side down and push the consumed side up; returns restore them by exactly the same amounts."

        Design: Difficulty/cross_entity_state_dependency/shipment_release_gated_on_order_released
        """
        ctx = setup_licensed_order(
            order_quantity=4, party_name="Danube Logistics Kft", party_country="HUN",
            party_city="Budapest", destination_country="HUN",
        )
        shipment = create_screened_shipment(ctx["order"]["id"], quantity=4,
                                            planned_ship_date="2026-08-15")

        res = api.release_shipment(shipment["id"], ops_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        shipment_after = get_shipment(shipment["id"])
        assert shipment_after["status"] == "SCREENED", (
            f"rejected release must leave the shipment SCREENED, got {shipment_after['status']}"
        )
        license_after = get_license(ctx["license"]["id"], headers=manager_headers)
        assert license_after["remaining_quantity"] == 100, (
            f"no consumption may happen on a rejected release, got "
            f"{license_after['remaining_quantity']}"
        )
        assert_license_consumption_invariants(license_after)

    def test_shipment_release_over_remaining_quantity_rejected(self, api, ops_headers,
                                                               manager_headers):
        """PRD §3.7: "the shipment's `quantity` must not exceed the license's `remaining_quantity` (`ERR_LICENSE_QUANTITY_INSUFFICIENT`), and the shipment's consumed value must not exceed the license's `remaining_value_cents` (`ERR_LICENSE_VALUE_INSUFFICIENT`)"

        Design: Corner/validations/shipment_release_over_remaining_quantity_rejected
        """
        ctx = setup_released_licensed_order(
            order_quantity=2, license_quantity=1, license_value=100000,
            party_name="Turin Meccanica SPA", party_country="ITA", party_city="Turin",
            destination_country="ITA",
        )
        shipment = create_screened_shipment(ctx["order"]["id"], quantity=2)

        res = api.release_shipment(shipment["id"], ops_headers)
        validate_error(res, ApiErrorId.ERR_LICENSE_QUANTITY_INSUFFICIENT)

        license_after = get_license(ctx["license"]["id"], headers=manager_headers)
        assert license_after["remaining_quantity"] == 1, (
            f"rejected release must not consume quantity, got {license_after['remaining_quantity']}"
        )

    def test_shipment_release_over_remaining_value_rejected(self, api, ops_headers,
                                                            manager_headers):
        """PRD §3.7: "the shipment's `quantity` must not exceed the license's `remaining_quantity` (`ERR_LICENSE_QUANTITY_INSUFFICIENT`), and the shipment's consumed value must not exceed the license's `remaining_value_cents` (`ERR_LICENSE_VALUE_INSUFFICIENT`)"

        Design: Corner/validations/shipment_release_over_remaining_value_rejected
        """
        ctx = setup_released_licensed_order(
            order_quantity=1, license_value=500, license_quantity=100,
            party_name="Galway Marine Ltd", party_country="IRL", party_city="Galway",
            destination_country="IRL",
        )
        shipment = create_screened_shipment(ctx["order"]["id"], quantity=1)

        res = api.release_shipment(shipment["id"], ops_headers)
        # consumed would be 1000 > remaining_value 500
        validate_error(res, ApiErrorId.ERR_LICENSE_VALUE_INSUFFICIENT)

        license_after = get_license(ctx["license"]["id"], headers=manager_headers)
        assert license_after["remaining_value_cents"] == 500, (
            f"rejected release must not consume value, got {license_after['remaining_value_cents']}"
        )

    def test_military_condition_blocks_shipment_release(self, api, ops_headers):
        """PRD §3.7: "a license carrying the `NO_MILITARY_END_USE` condition forbids release of an order whose `end_use` is `MILITARY` (`ERR_LICENSE_CONDITION_VIOLATION`)"

        Design: Corner/validations/military_condition_blocks_shipment_release
        """
        ctx = setup_released_licensed_order(
            order_quantity=1, end_use="MILITARY", conditions=["NO_MILITARY_END_USE"],
            party_name="Warsaw Defense Works", party_country="POL", party_city="Gdansk",
            destination_country="POL",
        )
        shipment = create_screened_shipment(ctx["order"]["id"], quantity=1)

        res = api.release_shipment(shipment["id"], ops_headers)
        validate_error(res, ApiErrorId.ERR_LICENSE_CONDITION_VIOLATION)

        shipment_after = get_shipment(shipment["id"])
        assert shipment_after["status"] == "SCREENED", (
            f"rejected release must leave the shipment SCREENED, got {shipment_after['status']}"
        )


class TestShipmentCreationBudget:
    def test_shipment_create_exceeds_order_quantity_rejected(self, api, ops_headers):
        """PRD §3.7: "The parent order must be `LICENSED` or `RELEASED` (else `ERR_INVALID_STATE`), and the quantity budget is enforced at creation: the sum of `quantity` across the order's shipments in `PLANNED`, `SCREENED`, `HELD`, `RELEASED`, `IN_TRANSIT`, or `DELIVERED` status, plus the new shipment's quantity, must not exceed the order's `quantity` — a breach is `ERR_ORDER_QUANTITY_EXCEEDED`."

        Design: Corner/validations/shipment_create_exceeds_order_quantity_rejected
        """
        ctx = setup_released_not_required_order(
            party_name="Aarhus Supply APS", party_country="DNK", party_city="Aarhus",
            destination_country="DNK", quantity=2, unit_value_cents=10,
        )
        create_shipment(ctx["order"]["id"], quantity=2, planned_ship_date="2026-08-10")

        res = api.create_shipment(
            {"order_id": ctx["order"]["id"], "quantity": 1, "planned_ship_date": "2026-08-11"},
            ops_headers,
        )
        validate_error(res, ApiErrorId.ERR_ORDER_QUANTITY_EXCEEDED)


class TestExactEqualityBoundary:
    def _setup_equality_scenario(self):
        return setup_released_licensed_order(
            order_quantity=10, license_quantity=10, license_value=100000,
            party_name="Alpine Systems AG", party_country="CHE", party_city="Bern",
            destination_country="CHE",
        )

    def test_release_at_exact_remaining_quantity_succeeds(self, api, ops_headers):
        """PRD §3.7: "Both sufficiency comparisons are inclusive — a shipment exactly equal to the remaining quantity or value is allowed, and it is precisely that equality which exhausts the license."

        Design: Difficulty/boundary_precision_check/license_quantity_exact_equality_exhausts
        """
        ctx = self._setup_equality_scenario()
        shipment = create_screened_shipment(ctx["order"]["id"], quantity=10,
                                            planned_ship_date="2026-08-15")

        released = release_shipment(shipment["id"])
        assert released["status"] == "RELEASED", (
            f"quantity 10 == remaining 10 must be allowed, got {released['status']}"
        )
        assert released["consumed_value_cents"] == 10000
        assert_shipment(released)

        license_after = get_license(ctx["license"]["id"])
        assert license_after["remaining_quantity"] == 0
        assert license_after["remaining_value_cents"] == 90000
        assert_license_consumption_invariants(license_after)

    def test_license_exhausted_at_zero_remaining(self, api):
        """PRD §3.5: "After any decrement, if either `remaining_quantity` or `remaining_value_cents` reaches zero, the license moves `APPROVED → EXHAUSTED`."

        Design: Difficulty/boundary_precision_check/license_quantity_exact_equality_exhausts
        """
        ctx = self._setup_equality_scenario()
        shipment = create_screened_shipment(ctx["order"]["id"], quantity=10,
                                            planned_ship_date="2026-08-15")
        release_shipment(shipment["id"])

        license_after = get_license(ctx["license"]["id"])
        assert license_after["remaining_quantity"] == 0
        assert license_after["status"] == "EXHAUSTED", (
            f"equality exhausts the license, got {license_after['status']}"
        )


class TestFeeRoundingOrder:
    def _setup_two_shipment_fees(self):
        """EAR99 product unit 40; NOT_REQUIRED order qty 13 released; shipments of
        4 (value 160) and 9 (value 360) screened and released."""
        ctx = setup_released_not_required_order(
            party_name="Clean Buyer Ltd", party_country="GBR", party_city="London",
            destination_country="FRA", quantity=13, unit_value_cents=40,
        )
        s1 = create_released_shipment(ctx["order"]["id"], quantity=4,
                                      planned_ship_date="2026-08-10")
        s2 = create_released_shipment(ctx["order"]["id"], quantity=9,
                                      planned_ship_date="2026-08-11")
        return ctx, s1, s2

    def test_per_shipment_fees_rounded_individually(self, api):
        """PRD §3.7: "its `fee_cents` is computed as 1.5 percent of that consumed value — that is, the consumed value multiplied by 0.015 — rounded to a whole cent round half up"

        Design: Difficulty/combinatorial_formula/fee_round_per_shipment_then_sum
        """
        _, s1, s2 = self._setup_two_shipment_fees()
        # round(160 * 0.015) = round(2.40) = 2; round(360 * 0.015) = round(5.40) = 5
        assert s1["consumed_value_cents"] == 160
        assert s1["fee_cents"] == 2, f"round(160*0.015)=2 expected, got {s1['fee_cents']}"
        assert s2["consumed_value_cents"] == 360
        assert s2["fee_cents"] == 5, f"round(360*0.015)=5 expected, got {s2['fee_cents']}"

    def test_accumulated_fees_sum_of_rounded_fees(self, api):
        """PRD §3.7: "The rounding order is contractual: each shipment's fee is computed and rounded individually at its own release moment and then accumulated; summing shipment values first and rounding once is forbidden because it yields different cents. Returns do not refund the fee — `accumulated_fees_cents` only ever grows."

        Design: Difficulty/combinatorial_formula/fee_round_per_shipment_then_sum
        """
        ctx, _, _ = self._setup_two_shipment_fees()
        order = get_order(ctx["order"]["id"])
        # Per-shipment rounding pins 2 + 5 = 7; the forbidden sum-then-round would give 8.
        assert order["accumulated_fees_cents"] == 7, (
            f"accumulated fees must be 7 (2 + 5 per-shipment rounded), "
            f"got {order['accumulated_fees_cents']}"
        )
        assert order["shipped_quantity"] == 13


class TestValueConservationAcrossReturn:
    def _setup_release_and_return(self, api, ops_headers):
        """Licensed order qty 20; shipment qty 5 released, departed, returned."""
        ctx = setup_released_licensed_order(
            order_quantity=20, license_value=100000, license_quantity=100,
            party_name="Iberian Components SL", party_country="ESP", party_city="Madrid",
            destination_country="ESP",
        )
        shipment = create_released_shipment(ctx["order"]["id"], quantity=5,
                                            planned_ship_date="2026-08-15")
        get_success_data(api.advance_shipment(shipment["id"], {"event": "DEPART"}, ops_headers))
        returned = get_success_data(
            api.advance_shipment(shipment["id"], {"event": "RETURN"}, ops_headers)
        )
        return ctx, shipment, returned

    def test_value_invariant_restored_after_return(self, api, ops_headers, manager_headers):
        """PRD §3.5: "Once approved, a license behaves as a consumption ledger with two invariants that hold at all times after approval: `approved_value_cents` always equals `remaining_value_cents` plus `consumed_value_cents`, and `approved_quantity` always equals `remaining_quantity` plus `consumed_quantity`."
        PRD §3.7: "`RETURN` moves `IN_TRANSIT → RETURNED` and unwinds the ledger: when the order carries a license, its `remaining_quantity` and `remaining_value_cents` are restored by the shipment's quantity and consumed value, `consumed_quantity` and `consumed_value_cents` decrease by the same amounts, and the license's `version` increments by 1; the order's `shipped_quantity` decreases by the quantity and its `version` increments by 1; if the license was `EXHAUSTED` and the restoration leaves both remaining values above zero while the current date is still within `valid_until`, the license reactivates to `APPROVED`; and an audit record of type `SHIPMENT_RETURNED` is written."

        Design: Difficulty/compensating_invariant/license_value_conserved_across_release_and_return
        """
        ctx, _, _ = self._setup_release_and_return(api, ops_headers)

        license_after = get_license(ctx["license"]["id"], headers=manager_headers)
        assert license_after["remaining_value_cents"] == 100000, (
            f"return must restore the full value, got {license_after['remaining_value_cents']}"
        )
        assert license_after["consumed_value_cents"] == 0
        assert license_after["remaining_quantity"] == 100
        assert_license_consumption_invariants(license_after)

        order_after = get_order(ctx["order"]["id"])
        assert order_after["shipped_quantity"] == 0, (
            f"release +5 then return -5 nets to zero, got {order_after['shipped_quantity']}"
        )

    def test_fee_not_refunded_and_return_audited(self, api, ops_headers, director_headers):
        """PRD §3.7: "The rounding order is contractual: each shipment's fee is computed and rounded individually at its own release moment and then accumulated; summing shipment values first and rounding once is forbidden because it yields different cents. Returns do not refund the fee — `accumulated_fees_cents` only ever grows."
        PRD §2.11: "Eleven business events are deemed regulatorily significant and cause an `AuditRecord` to be written at the moment they occur, identified by `event_type`: `CLASSIFICATION_ACTIVATED`, `LICENSE_APPROVED`, `LICENSE_REVOKED`, `ORDER_RELEASED`, `SHIPMENT_RELEASED`, `SHIPMENT_RETURNED`, `GRANT_ACTIVATED`, `GRANT_REVOKED`, `SCREENING_CONFIRMED_MATCH`, `VSD_SUBMITTED`, and `VIOLATION_CLOSED`."

        Design: Difficulty/compensating_invariant/license_value_conserved_across_release_and_return
        """
        ctx, shipment, _ = self._setup_release_and_return(api, ops_headers)

        order_after = get_order(ctx["order"]["id"])
        # round(5000 * 0.015) = 75; the fee is not refunded on return.
        assert order_after["accumulated_fees_cents"] == 75, (
            f"fee must survive the return, got {order_after['accumulated_fees_cents']}"
        )

        records = audit_records_for("Shipment", shipment["id"], event_type="SHIPMENT_RETURNED",
                                    headers=director_headers)
        assert len(records) == 1, (
            f"exactly one SHIPMENT_RETURNED record expected, got {len(records)}"
        )


class TestDeliveryAndImmediateVisibility:
    def test_shipment_deliver_closes_order(self, api, ops_headers):
        """PRD §3.6: "Once `RELEASED`, an order no longer cancels: it closes automatically when every one of its shipments has reached a terminal state and the total quantity across `DELIVERED` shipments equals the order's `quantity`, transitioning `RELEASED → CLOSED`."

        Design: Corner/state_machines/shipment_deliver_closes_order
        """
        ctx = setup_released_not_required_order(
            party_name="Porto Comercio LDA", party_country="PRT", party_city="Porto",
            destination_country="PRT", quantity=2, unit_value_cents=10,
        )
        shipment = create_released_shipment(ctx["order"]["id"], quantity=2)
        get_success_data(api.advance_shipment(shipment["id"], {"event": "DEPART"}, ops_headers))
        delivered = get_success_data(
            api.advance_shipment(shipment["id"], {"event": "DELIVER"}, ops_headers)
        )
        assert delivered["status"] == "DELIVERED"

        order_after = get_order(ctx["order"]["id"])
        assert order_after["status"] == "CLOSED", (
            f"all shipments terminal and delivered qty == order qty must close the order, "
            f"got {order_after['status']}"
        )

    def test_release_effects_visible_immediately(self, api, ops_headers):
        """PRD §1: "Second, **immediate consistency**: when a screening match is confirmed, a license is revoked, or a list entry is activated, every downstream order, shipment, and grant that depends on the changed fact is reconciled in the same instant — there is no eventual-consistency window in which a held party's goods could keep moving."
        PRD §3.7: "On release the following happen together: the shipment's `consumed_value_cents` is set to its `quantity` multiplied by the product's `unit_value_cents` (an exact integer, no rounding); its `fee_cents` is computed as 1.5 percent of that consumed value — that is, the consumed value multiplied by 0.015 — rounded to a whole cent round half up; the license's `remaining_quantity` decreases by the quantity, `remaining_value_cents` decreases by the consumed value, `consumed_quantity` and `consumed_value_cents` increase by the same amounts, and the license's `version` increments by 1; the order's `accumulated_fees_cents` increases by this shipment's `fee_cents`, its `shipped_quantity` increases by the quantity, and its `version` increments by 1; if either remaining balance has hit zero the license flips to `EXHAUSTED`; and an audit record of type `SHIPMENT_RELEASED` is written."

        Design: Corner/consistency_model/release_effects_visible_immediately
        """
        ctx = setup_released_not_required_order(
            party_name="Vilnius Trade UAB", party_country="LTU", party_city="Vilnius",
            destination_country="LTU", quantity=2, unit_value_cents=1000,
        )
        shipment = create_screened_shipment(ctx["order"]["id"], quantity=2)

        released = validate_success(api.release_shipment(shipment["id"], ops_headers), 200)
        # The release RESPONSE itself carries the computed values.
        assert released["status"] == "RELEASED"
        assert released["consumed_value_cents"] == 2000
        assert released["fee_cents"] == 30, (
            f"round(2000*0.015)=30 expected, got {released['fee_cents']}"
        )

        order_after = get_order(ctx["order"]["id"])
        assert order_after["shipped_quantity"] == 2
        assert order_after["accumulated_fees_cents"] == 30, (
            f"the very next GET must reflect the accumulated fee (no lag), "
            f"got {order_after['accumulated_fees_cents']}"
        )
