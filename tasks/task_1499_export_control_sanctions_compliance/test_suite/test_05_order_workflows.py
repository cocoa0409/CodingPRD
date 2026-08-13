"""Order state machine: release guards, cancel, holds, license attachment, listings (PRD §3.3, §3.4, §3.6)."""
from test_helpers import (
    ApiErrorId,
    assert_export_order,
    create_approved_license,
    create_classified_product,
    create_entry,
    create_order,
    create_party,
    get_order,
    get_party,
    get_success_data,
    resolve_screening_result,
    setup_cleared_order,
    validate_error,
    validate_paginated,
)


class TestReleaseGuards:
    def test_order_release_from_draft_rejected(self, api, ops_headers):
        """PRD §3.6: "Release for fulfillment is a single action with two legal launch points. From `CLEARED`, the determination must be `NOT_REQUIRED`; a license-requiring order released without one fails with `ERR_LICENSE_REQUIRED`. From `LICENSED`, the attached license must still be `APPROVED` and still inside its validity window, failing with `ERR_INVALID_STATE` or `ERR_LICENSE_WINDOW_INVALID` respectively."

        Design: Corner/state_machines/order_release_from_draft_rejected
        """
        product, _ = create_classified_product(sku="P-012", name="Spring",
                                               controlled_content_pct=0, unit_value_cents=10,
                                               classification_code="EAR99")
        party = create_party(legal_name="Nord Nest AB", country_code="SWE", city="Lund")
        order = create_order(product["id"], party["id"], destination_country="SWE",
                             end_use="CIVILIAN", quantity=1)
        assert order["status"] == "DRAFT"

        res = api.release_order(order["id"], ops_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        after = get_order(order["id"])
        assert after["status"] == "DRAFT", f"order must stay DRAFT, got {after['status']}"

    def test_release_license_required_order_without_license_rejected(self, api, ops_headers):
        """PRD §3.6: "From `CLEARED`, the determination must be `NOT_REQUIRED`; a license-requiring order released without one fails with `ERR_LICENSE_REQUIRED`."

        Design: Corner/validations/release_license_required_order_without_license_rejected
        """
        ctx = setup_cleared_order(
            party_name="Brno Machining SRO", party_country="CZE", party_city="Brno",
            destination_country="CZE", end_use="DUAL_USE", quantity=1,
            controlled_content_pct=50, classification_code="5A002",
        )
        assert ctx["order"]["determination"] == "LICENSE_REQUIRED"

        res = api.release_order(ctx["order"]["id"], ops_headers)
        validate_error(res, ApiErrorId.ERR_LICENSE_REQUIRED)

        after = get_order(ctx["order"]["id"])
        assert after["status"] == "CLEARED", f"order must stay CLEARED, got {after['status']}"


class TestCancellation:
    def test_cancel_cancelled_order_terminal_lockdown(self, api, ops_headers):
        """PRD §3.6: "Cancellation by the specialist is available from `DRAFT`, `IN_REVIEW`, `CLEARED`, and `HELD`, landing the order in the terminal `CANCELLED` state."

        Design: Corner/state_machines/cancel_cancelled_order_terminal_lockdown
        """
        product, _ = create_classified_product(sku="P-013", name="Rivet",
                                               controlled_content_pct=0, unit_value_cents=10,
                                               classification_code="EAR99")
        party = create_party(legal_name="Delta Handel GmbH", country_code="AUT", city="Vienna")
        order = create_order(product["id"], party["id"], destination_country="AUT",
                             end_use="CIVILIAN", quantity=1)
        cancelled = get_success_data(api.cancel_order(order["id"], ops_headers))
        assert cancelled["status"] == "CANCELLED"

        res = api.cancel_order(order["id"], ops_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        after = get_order(order["id"])
        assert after["status"] == "CANCELLED", (
            f"CANCELLED is terminal; second cancel must not move it, got {after['status']}"
        )


class TestAttachLicense:
    def test_attach_license_outside_valid_window_rejected(self, api, ops_headers):
        """PRD §3.6: "Attachment requires the order to be `CLEARED` (else `ERR_INVALID_STATE`), the determination to be exactly `LICENSE_REQUIRED` (else `ERR_LICENSE_NOT_REQUIRED`), the referenced license to exist (else `ERR_NOT_FOUND`) and to stand `APPROVED` (else `ERR_INVALID_STATE`), the license's `product_id` to equal the order's `product_id` (else `ERR_LICENSE_PRODUCT_MISMATCH`), and the license window to cover the current date (else `ERR_LICENSE_WINDOW_INVALID`)."

        Design: Corner/validations/attach_license_outside_valid_window_rejected
        """
        ctx = setup_cleared_order(
            party_name="Osaka Devices KK", party_country="JPN", party_city="Osaka",
            destination_country="JPN", end_use="DUAL_USE", quantity=1,
            controlled_content_pct=50, classification_code="5A002",
        )
        # Window 2026-09-01..2026-12-31 does not cover the default clock date 2026-08-01.
        lic = create_approved_license(ctx["product"]["id"], valid_from="2026-09-01",
                                      valid_until="2026-12-31")

        res = api.attach_license_to_order(ctx["order"]["id"], {"license_id": lic["id"]},
                                          ops_headers)
        validate_error(res, ApiErrorId.ERR_LICENSE_WINDOW_INVALID)

        after = get_order(ctx["order"]["id"])
        assert after["status"] == "CLEARED"
        assert after["license_id"] is None

    def test_attach_license_product_mismatch_rejected(self, api, ops_headers):
        """PRD §3.6: "the license's `product_id` to equal the order's `product_id` (else `ERR_LICENSE_PRODUCT_MISMATCH`)"

        Design: Corner/validations/attach_license_product_mismatch_rejected
        """
        product_a, _ = create_classified_product(sku="P-035", name="Gyro A",
                                                 controlled_content_pct=50, unit_value_cents=1000,
                                                 classification_code="5A002",
                                                 determination_basis="CCATS")
        ctx_b = setup_cleared_order(
            party_name="Helsinki Optics OY", party_country="FIN", party_city="Helsinki",
            destination_country="FIN", end_use="DUAL_USE", quantity=1,
            controlled_content_pct=50, classification_code="5A002",
        )
        lic = create_approved_license(product_a["id"])  # license covers product A only

        res = api.attach_license_to_order(ctx_b["order"]["id"], {"license_id": lic["id"]},
                                          ops_headers)
        validate_error(res, ApiErrorId.ERR_LICENSE_PRODUCT_MISMATCH)

        after = get_order(ctx_b["order"]["id"])
        assert after["status"] == "CLEARED"

    def test_attach_license_when_not_required_rejected(self, api, ops_headers):
        """PRD §3.6: "Attachment requires the order to be `CLEARED` (else `ERR_INVALID_STATE`), the determination to be exactly `LICENSE_REQUIRED` (else `ERR_LICENSE_NOT_REQUIRED`), the referenced license to exist (else `ERR_NOT_FOUND`) and to stand `APPROVED` (else `ERR_INVALID_STATE`), the license's `product_id` to equal the order's `product_id` (else `ERR_LICENSE_PRODUCT_MISMATCH`), and the license window to cover the current date (else `ERR_LICENSE_WINDOW_INVALID`)."

        Design: Corner/validations/attach_license_when_not_required_rejected
        """
        ctx = setup_cleared_order(
            party_name="Lisbon Retail LDA", party_country="PRT", party_city="Lisbon",
            destination_country="PRT", end_use="CIVILIAN", quantity=1,
            controlled_content_pct=0, unit_value_cents=100, classification_code="EAR99",
        )
        assert ctx["order"]["determination"] == "NOT_REQUIRED"
        lic = create_approved_license(ctx["product"]["id"])

        res = api.attach_license_to_order(ctx["order"]["id"], {"license_id": lic["id"]},
                                          ops_headers)
        validate_error(res, ApiErrorId.ERR_LICENSE_NOT_REQUIRED)

        after = get_order(ctx["order"]["id"])
        assert after["status"] == "CLEARED"


class TestHolds:
    def _setup_held_order_via_list_change(self):
        """CLEARED order auto-held when a matching list entry is born ACTIVE."""
        ctx = setup_cleared_order(
            party_name="Baltic Imports OU", party_country="EST", party_city="Tallinn",
            destination_country="EST", end_use="CIVILIAN", quantity=5,
            controlled_content_pct=0, unit_value_cents=220, classification_code="EAR99",
        )
        entry = create_entry(list_source="DENIED_PERSONS", match_name="Baltic Imports OU",
                             country_code="EST", severity="RESTRICTED")
        return ctx, entry

    def test_release_hold_rejected_while_review_pending(self, api, manager_headers):
        """PRD §3.6: "The checks run in this order: the order must be `HELD` (else `ERR_INVALID_STATE`); the party's posture must be `CLEAR`, with `REVIEW_REQUIRED` rejected as `ERR_SCREENING_REVIEW_PENDING` and `BLOCKED` as `ERR_PARTY_BLOCKED`; the determination must not be `PROHIBITED` (else `ERR_ORDER_PROHIBITED`);"

        Design: Difficulty/cross_entity_state_dependency/release_hold_gated_on_party_posture
        """
        ctx, _ = self._setup_held_order_via_list_change()
        order = get_order(ctx["order"]["id"])
        assert order["status"] == "HELD", f"list-change sweep must hold the order, got {order['status']}"

        res = api.release_order_hold(order["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_SCREENING_REVIEW_PENDING)

    def test_order_and_party_unchanged_after_release_hold_rejection(self, api, manager_headers):
        """PRD §3.6: "the party's posture must be `CLEAR`, with `REVIEW_REQUIRED` rejected as `ERR_SCREENING_REVIEW_PENDING` and `BLOCKED` as `ERR_PARTY_BLOCKED`"
        PRD §3.3: "As the affected parties' postures deteriorate to `REVIEW_REQUIRED` or `BLOCKED`, their `CLEARED` or `LICENSED` orders cascade to `HELD` (with `pre_hold_status` recorded) and those orders' shipments in `PLANNED` or `SCREENED` cascade to `HELD` as well."

        Design: Difficulty/cross_entity_state_dependency/release_hold_gated_on_party_posture
        """
        ctx, _ = self._setup_held_order_via_list_change()

        res = api.release_order_hold(ctx["order"]["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_SCREENING_REVIEW_PENDING)

        order_after = get_order(ctx["order"]["id"])
        assert order_after["status"] == "HELD", (
            f"rejected release-hold must leave the order HELD, got {order_after['status']}"
        )
        party_after = get_party(ctx["party"]["id"], headers=manager_headers)
        assert party_after["screening_posture"] == "REVIEW_REQUIRED"

    def test_order_auto_held_by_list_activation(self, api, manager_headers):
        """PRD §3.3: "When a list entry is born `ACTIVE` or is re-activated from `INACTIVE`, the server runs a re-screen sweep: for every party referenced by an export order currently `CLEARED` or `LICENSED` — processed in order of that party's earliest such order by `created_at` ascending, with ties broken by the party's own `created_at` ascending — the FUZZY match score is computed against the newly activated entry only. If the score reaches or exceeds the entry's threshold, a new result is created with `trigger_context` `LIST_CHANGE` in status `POTENTIAL_MATCH` and the party's posture is recomputed; below the threshold, no row is created at all."
        PRD §3.3: "As the affected parties' postures deteriorate to `REVIEW_REQUIRED` or `BLOCKED`, their `CLEARED` or `LICENSED` orders cascade to `HELD` (with `pre_hold_status` recorded) and those orders' shipments in `PLANNED` or `SCREENED` cascade to `HELD` as well."

        Design: Difficulty/non_linear_state_machine/order_cleared_held_cleared_cycle_via_list_change
        """
        ctx, _ = self._setup_held_order_via_list_change()
        order = get_order(ctx["order"]["id"])
        assert order["status"] == "HELD"
        assert order["pre_hold_status"] == "CLEARED", (
            f"pre_hold_status must record CLEARED, got {order['pre_hold_status']}"
        )
        party = get_party(ctx["party"]["id"], headers=manager_headers)
        assert party["screening_posture"] == "REVIEW_REQUIRED"

    def test_release_hold_returns_to_cleared(self, api, manager_headers):
        """PRD §3.6: "On success the order returns to its `pre_hold_status` when one was recorded, and to `CLEARED` otherwise; `pre_hold_status` is then cleared back to null."
        PRD §3.3: "A `FALSE_POSITIVE` simply relaxes the posture if no other open matches remain."

        Design: Difficulty/non_linear_state_machine/order_cleared_held_cleared_cycle_via_list_change
        """
        ctx, _ = self._setup_held_order_via_list_change()
        # Resolve the LIST_CHANGE POTENTIAL_MATCH, then release the hold.
        rows, meta = validate_paginated(
            api.list_screening_results(manager_headers,
                                       params={"party_id": ctx["party"]["id"],
                                               "trigger_context": "LIST_CHANGE"})
        )
        assert meta["total_count"] == 1
        resolve_screening_result(rows[0]["id"], "FALSE_POSITIVE", headers=manager_headers)

        released = get_success_data(api.release_order_hold(ctx["order"]["id"], manager_headers))
        assert released["status"] == "CLEARED", (
            f"review hold must return to CLEARED, got {released['status']}"
        )
        assert released["pre_hold_status"] is None


class TestProhibitedOrders:
    def test_release_hold_on_prohibited_order_rejected(self, api, manager_headers, ops_headers):
        """PRD §3.6: "when the outcome is `POTENTIAL_MATCH` or `CONFIRMED_MATCH`, or the determination is `PROHIBITED`, it lands in `HELD` with `pre_hold_status` left null, marking it as a review hold that will return to `CLEARED`."
        PRD §3.6: "the determination must not be `PROHIBITED` (else `ERR_ORDER_PROHIBITED`)"

        Design: Corner/validations/release_hold_on_prohibited_order_rejected
        """
        product, _ = create_classified_product(sku="P-046", name="Tube",
                                               controlled_content_pct=0, unit_value_cents=10,
                                               classification_code="EAR99")
        party = create_party(legal_name="Innocent Buyer BV", country_code="NLD",
                             city="Rotterdam")
        # Created BEFORE the embargo entry exists, so creation passes the door guard.
        order = create_order(product["id"], party["id"], destination_country="PRK",
                             end_use="CIVILIAN", quantity=1)
        create_entry(list_source="EMBARGOED_COUNTRY", match_name="North Korea",
                     country_code="PRK", severity="PROHIBITED")
        submitted = get_success_data(api.submit_order(order["id"], ops_headers))
        assert submitted["determination"] == "PROHIBITED", (
            f"embargo entry activated before submit must yield PROHIBITED, "
            f"got {submitted['determination']}"
        )
        assert submitted["status"] == "HELD"
        # Party posture is CLEAR (EXACT name/country mismatch), so the posture
        # checks pass and the PROHIBITED determination check is the one that fires.
        assert get_party(party["id"], headers=manager_headers)["screening_posture"] == "CLEAR"

        res = api.release_order_hold(order["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_ORDER_PROHIBITED)

        after = get_order(order["id"])
        assert after["status"] == "HELD"


class TestOrderListings:
    def test_orders_list_filtered_by_status(self, api, manager_headers, ops_headers,
                                            director_headers):
        """PRD §3.4: "Order listings support filtering by `product_id`, `party_id`, `license_id`, and `status`."
        PRD §3.6: "when the outcome is `POTENTIAL_MATCH` or `CONFIRMED_MATCH`, or the determination is `PROHIBITED`, it lands in `HELD` with `pre_hold_status` left null, marking it as a review hold that will return to `CLEARED`."

        Design: Corner/endpoints/orders_list_filtered_by_status
        """
        # Entry born ACTIVE before any order exists: its creation sweep is a no-op.
        create_entry(list_source="DENIED_PERSONS", match_name="Baltic Imports OU",
                     country_code="EST", severity="RESTRICTED")
        product, _ = create_classified_product(sku="P-050", name="Sheet",
                                               controlled_content_pct=0, unit_value_cents=10,
                                               classification_code="EAR99")
        party_a = create_party(legal_name="Baltic Imports OU", country_code="EST",
                               city="Tallinn")
        order_held = create_order(product["id"], party_a["id"], destination_country="EST",
                                  end_use="CIVILIAN", quantity=1)
        submitted = get_success_data(api.submit_order(order_held["id"], ops_headers))
        # EXACT name match: score 1.00 >= 0.70 -> POTENTIAL_MATCH -> auto HELD
        assert submitted["status"] == "HELD", (
            f"exact-name hit at submit must auto-hold the order, got {submitted['status']}"
        )

        party_b = create_party(legal_name="Clean Corner Oy", country_code="FIN", city="Turku")
        create_order(product["id"], party_b["id"], destination_country="FIN",
                     end_use="CIVILIAN", quantity=1)  # stays DRAFT

        rows, meta = validate_paginated(
            api.list_orders(manager_headers, params={"status": "HELD"})
        )
        assert meta["total_count"] == 1, f"only the HELD order matches, got {meta['total_count']}"
        assert rows[0]["id"] == order_held["id"]

    def test_fk_reverse_lookup_lists(self, api, analyst_headers):
        """PRD §3.1: "Classifications may be browsed through a filtered listing by `product_id` and `status`."
        PRD §3.4: "Order listings support filtering by `product_id`, `party_id`, `license_id`, and `status`."

        Design: Corner/endpoints/fk_reverse_lookup_lists
        """
        product, classification = create_classified_product(
            sku="P-051", name="Foam", controlled_content_pct=0, unit_value_cents=10,
            classification_code="EAR99",
        )
        party = create_party(legal_name="Riga Freight SIA", country_code="LVA", city="Riga")
        order = create_order(product["id"], party["id"], destination_country="LVA",
                             end_use="CIVILIAN", quantity=1)

        rows_c, meta_c = validate_paginated(
            api.list_classifications(analyst_headers, params={"product_id": product["id"]})
        )
        assert meta_c["total_count"] == 1
        assert rows_c[0]["id"] == classification["id"]

        rows_o, meta_o = validate_paginated(
            api.list_orders(analyst_headers, params={"party_id": party["id"]})
        )
        assert meta_o["total_count"] == 1
        assert rows_o[0]["id"] == order["id"]
        assert_export_order(rows_o[0])
