"""Transitive cascades (list activation, license revocation) and validation priority pairs (PRD §2.8, §3.3, §3.5)."""
from test_helpers import (
    ApiErrorId,
    audit_records_for,
    block_party_with_confirmed_match,
    create_approved_license,
    create_classified_product,
    create_entry,
    create_order,
    create_party,
    create_released_shipment,
    create_screened_shipment,
    create_shipment,
    get_license,
    get_order,
    get_party,
    get_shipment,
    get_success_data,
    setup_licensed_order,
    setup_released_not_required_order,
    validate_error,
    validate_paginated,
)


class TestListActivationCascade:
    def _setup_licensed_order_with_planned_shipment(self):
        """5A002 product; APPROVED license; party 'Vostok Trading LLC' (RUS); order
        LICENSE_REQUIRED -> LICENSED; one PLANNED shipment. No entries exist yet."""
        ctx = setup_licensed_order(
            product_pct=50, unit_value_cents=1000, classification_code="5A002",
            destination_country="KAZ", end_use="DUAL_USE", order_quantity=5,
            license_value=100000, license_quantity=100,
            party_name="Vostok Trading LLC", party_country="RUS", party_city="Moscow",
        )
        shipment = create_shipment(ctx["order"]["id"], quantity=5,
                                   planned_ship_date="2026-08-20")
        assert shipment["status"] == "PLANNED"
        return ctx, shipment

    def _activate_matching_entry(self, manager_headers):
        return create_entry(list_source="ENTITY_LIST", match_name="Vostok Trading LLC",
                            country_code="RUS", severity="RESTRICTED")

    def test_list_change_result_and_posture_link(self, api, manager_headers):
        """PRD §3.3: "When a list entry is born `ACTIVE` or is re-activated from `INACTIVE`, the server runs a re-screen sweep: for every party referenced by an export order currently `CLEARED` or `LICENSED` — processed in order of that party's earliest such order by `created_at` ascending, with ties broken by the party's own `created_at` ascending — the FUZZY match score is computed against the newly activated entry only. If the score reaches or exceeds the entry's threshold, a new result is created with `trigger_context` `LIST_CHANGE` in status `POTENTIAL_MATCH` and the party's posture is recomputed; below the threshold, no row is created at all."
        PRD §3.3: "otherwise `REVIEW_REQUIRED` when any result stands at `POTENTIAL_MATCH`"

        Design: Difficulty/transitive_cascade/list_activation_rescreen_cascade_depth3
        """
        ctx, _ = self._setup_licensed_order_with_planned_shipment()
        entry = self._activate_matching_entry(manager_headers)

        rows, meta = validate_paginated(
            api.list_screening_results(manager_headers,
                                       params={"party_id": ctx["party"]["id"],
                                               "trigger_context": "LIST_CHANGE"})
        )
        assert meta["total_count"] == 1, (
            f"the born-ACTIVE entry sweep must create one LIST_CHANGE result, "
            f"got {meta['total_count']}"
        )
        result = rows[0]
        assert result["status"] == "POTENTIAL_MATCH", (
            f"FUZZY exact-name score 1.00 >= 0.70 must produce POTENTIAL_MATCH, "
            f"got {result['status']}"
        )
        assert result["matched_entry_id"] == entry["id"]

        party_after = get_party(ctx["party"]["id"], headers=manager_headers)
        assert party_after["screening_posture"] == "REVIEW_REQUIRED", (
            f"posture must recompute to REVIEW_REQUIRED, got {party_after['screening_posture']}"
        )

    def test_licensed_order_and_planned_shipment_held(self, api, manager_headers):
        """PRD §3.3: "As the affected parties' postures deteriorate to `REVIEW_REQUIRED` or `BLOCKED`, their `CLEARED` or `LICENSED` orders cascade to `HELD` (with `pre_hold_status` recorded) and those orders' shipments in `PLANNED` or `SCREENED` cascade to `HELD` as well."

        Design: Difficulty/transitive_cascade/list_activation_rescreen_cascade_depth3
        """
        ctx, shipment = self._setup_licensed_order_with_planned_shipment()
        self._activate_matching_entry(manager_headers)

        order_after = get_order(ctx["order"]["id"])
        assert order_after["status"] == "HELD", (
            f"LICENSED order must cascade to HELD, got {order_after['status']}"
        )
        assert order_after["pre_hold_status"] == "LICENSED"

        shipment_after = get_shipment(shipment["id"])
        assert shipment_after["status"] == "HELD", (
            f"the held order's PLANNED shipment must cascade to HELD, "
            f"got {shipment_after['status']}"
        )


class TestLicenseRevocationCascade:
    def _setup(self):
        """5A002 product; APPROVED license; clean party; order LICENSED; PLANNED shipment."""
        ctx = setup_licensed_order(
            product_pct=50, unit_value_cents=1000, classification_code="5A002",
            destination_country="CHE", end_use="DUAL_USE", order_quantity=3,
            license_value=100000, license_quantity=100,
            party_name="Meridian Trading SA", party_country="CHE", party_city="Zurich",
        )
        shipment = create_shipment(ctx["order"]["id"], quantity=3,
                                   planned_ship_date="2026-08-20")
        return ctx, shipment

    def test_revoke_holds_licensed_order_and_shipment(self, api, director_headers):
        """PRD §3.5: "Revocation is a hard stop with a deliberate blast radius: the license becomes `REVOKED`; every order whose `license_id` names this license and whose status is `LICENSED` cascades to `HELD` with `pre_hold_status` recorded as `LICENSED` (the license reference itself is retained on the order); every shipment of those orders in `PLANNED` or `SCREENED` cascades to `HELD`; and an audit record of type `LICENSE_REVOKED` is written."

        Design: Difficulty/transitive_cascade/license_revocation_cascade_depth2
        """
        ctx, shipment = self._setup()

        revoked = get_success_data(api.revoke_license(ctx["license"]["id"], director_headers))
        assert revoked["status"] == "REVOKED"

        order_after = get_order(ctx["order"]["id"])
        assert order_after["status"] == "HELD", (
            f"attached LICENSED order must cascade to HELD, got {order_after['status']}"
        )
        assert order_after["pre_hold_status"] == "LICENSED"
        assert order_after["license_id"] == ctx["license"]["id"], (
            "the license reference is retained on the held order"
        )

        shipment_after = get_shipment(shipment["id"])
        assert shipment_after["status"] == "HELD", (
            f"the held order's PLANNED shipment must cascade to HELD, "
            f"got {shipment_after['status']}"
        )

    def test_revoke_writes_audit_record(self, api, director_headers):
        """PRD §3.5: "Revocation is a hard stop with a deliberate blast radius: the license becomes `REVOKED`; every order whose `license_id` names this license and whose status is `LICENSED` cascades to `HELD` with `pre_hold_status` recorded as `LICENSED` (the license reference itself is retained on the order); every shipment of those orders in `PLANNED` or `SCREENED` cascades to `HELD`; and an audit record of type `LICENSE_REVOKED` is written."

        Design: Difficulty/transitive_cascade/license_revocation_cascade_depth2
        """
        ctx, _ = self._setup()
        get_success_data(api.revoke_license(ctx["license"]["id"], director_headers))

        records = audit_records_for("License", ctx["license"]["id"],
                                    event_type="LICENSE_REVOKED", headers=director_headers)
        assert len(records) == 1, (
            f"exactly one LICENSE_REVOKED record expected, got {len(records)}"
        )
        assert records[0]["actor_role"] == "ComplianceDirector"


class TestStateBeatsBusinessSafety:
    def _setup_planned_shipment_blocked_party(self):
        """NOT_REQUIRED order RELEASED; shipment PLANNED (never screened); the party
        is then confirmed BLOCKED. The cascade skips the RELEASED order, so the
        shipment stays PLANNED."""
        ctx = setup_released_not_required_order(
            party_name="Omicron Ltd", party_country="GBR", party_city="Leeds",
            destination_country="GBR", quantity=1, unit_value_cents=300,
        )
        shipment = create_shipment(ctx["order"]["id"], quantity=1,
                                   planned_ship_date="2026-08-15")
        block_party_with_confirmed_match(ctx["party"])
        return ctx, shipment

    def test_planned_shipment_release_fails_invalid_state_despite_blocked_party(
            self, api, ops_headers):
        """PRD §2.8: "When multiple rules could reject the same request, the server evaluates them in a fixed priority order and surfaces the first failure."
        PRD §2.8: "6. **State preconditions** — the target entity is in a valid from-state for the requested transition, including the attached-license `APPROVED` checks on order release and shipment release (`ERR_INVALID_STATE`, 409). Applies to all state-transition endpoints."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_at_shipment_release
        """
        ctx, shipment = self._setup_planned_shipment_blocked_party()
        party_after = get_party(ctx["party"]["id"])
        assert party_after["screening_posture"] == "BLOCKED", (
            "the safety violation must genuinely exist for the priority claim to bite"
        )

        res = api.release_shipment(shipment["id"], ops_headers)
        # State (priority 6) is evaluated before sanctions safety (priority 7).
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_blocked_party_posture_persists_after_state_rejection(self, api, ops_headers):
        """PRD §2.8: "The practical consequence of this ordering is that a caller learns about authentication before authorization, about a missing resource before a malformed body, about a stale version before a state conflict, and about a sanctions-safety block before a fiscal shortfall."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_at_shipment_release
        """
        ctx, shipment = self._setup_planned_shipment_blocked_party()

        res = api.release_shipment(shipment["id"], ops_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        shipment_after = get_shipment(shipment["id"])
        assert shipment_after["status"] == "PLANNED", (
            f"rejected release must leave the shipment PLANNED, got {shipment_after['status']}"
        )
        party_after = get_party(ctx["party"]["id"])
        assert party_after["screening_posture"] == "BLOCKED"


class TestSafetyBeatsFiscal:
    def _setup_screened_shipment_blocked_and_underfunded(self, api, ops_headers):
        """Order1 (party A) LICENSED -> RELEASED with shipment S1 qty 5 SCREENED (would
        consume 5000). Order2 (party B) on the SAME license releases a shipment for
        2000, leaving remaining_value_cents 1000. Party A is confirmed BLOCKED only
        after S1's screening; the CONFIRMED_MATCH cascade skips the RELEASED order1,
        so S1 stays SCREENED."""
        product, _ = create_classified_product(
            sku="P-910", name="Transceiver", controlled_content_pct=50,
            unit_value_cents=1000, classification_code="5A002", determination_basis="CCATS",
        )
        lic = create_approved_license(product["id"], approved_value_cents=3000,
                                      approved_quantity=100)

        party_a = create_party(legal_name="Omicron Ltd", country_code="GBR", city="Leeds")
        order1 = create_order(product["id"], party_a["id"], destination_country="FRA",
                              end_use="DUAL_USE", quantity=5)
        submitted1 = get_success_data(api.submit_order(order1["id"], ops_headers))
        assert submitted1["determination"] == "LICENSE_REQUIRED"
        get_success_data(
            api.attach_license_to_order(order1["id"], {"license_id": lic["id"]}, ops_headers)
        )
        get_success_data(api.release_order(order1["id"], ops_headers))
        s1 = create_screened_shipment(order1["id"], quantity=5,
                                      planned_ship_date="2026-08-15")

        party_b = create_party(legal_name="Clean Partner Ltd", country_code="GBR",
                               city="Bristol")
        order2 = create_order(product["id"], party_b["id"], destination_country="FRA",
                              end_use="DUAL_USE", quantity=2)
        submitted2 = get_success_data(api.submit_order(order2["id"], ops_headers))
        assert submitted2["determination"] == "LICENSE_REQUIRED"
        get_success_data(
            api.attach_license_to_order(order2["id"], {"license_id": lic["id"]}, ops_headers)
        )
        get_success_data(api.release_order(order2["id"], ops_headers))
        create_released_shipment(order2["id"], quantity=2, planned_ship_date="2026-08-15")

        license_mid = get_license(lic["id"])
        assert license_mid["remaining_value_cents"] == 1000, (
            f"setup expects remaining 1000 after party B consumes 2000 of 3000, "
            f"got {license_mid['remaining_value_cents']}"
        )

        block_party_with_confirmed_match(party_a)
        assert get_shipment(s1["id"])["status"] == "SCREENED"
        return lic, s1

    def test_blocked_party_error_precedes_value_insufficiency(self, api, ops_headers):
        """PRD §2.8: "The practical consequence of this ordering is that a caller learns about authentication before authorization, about a missing resource before a malformed body, about a stale version before a state conflict, and about a sanctions-safety block before a fiscal shortfall."
        PRD §3.7: "the party's posture must be neither `BLOCKED` (`ERR_PARTY_BLOCKED`) nor `REVIEW_REQUIRED` (`ERR_SCREENING_REVIEW_PENDING`)"

        Design: Difficulty/priority_pair_validation_conflict/business_safety_beats_business_fiscal_at_shipment_release
        """
        lic, s1 = self._setup_screened_shipment_blocked_and_underfunded(api, ops_headers)

        res = api.release_shipment(s1["id"], ops_headers)
        # Safety (priority 7) precedes fiscal sufficiency (priority 10): consumed
        # 5000 > remaining 1000 would also fail, but ERR_PARTY_BLOCKED must surface.
        validate_error(res, ApiErrorId.ERR_PARTY_BLOCKED)

        license_after = get_license(lic["id"])
        assert license_after["remaining_value_cents"] == 1000

    def test_license_unchanged_after_safety_rejection(self, api, ops_headers):
        """PRD §3.5: "Once approved, a license behaves as a consumption ledger with two invariants that hold at all times after approval: `approved_value_cents` always equals `remaining_value_cents` plus `consumed_value_cents`, and `approved_quantity` always equals `remaining_quantity` plus `consumed_quantity`."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_beats_business_fiscal_at_shipment_release
        """
        lic, s1 = self._setup_screened_shipment_blocked_and_underfunded(api, ops_headers)

        res = api.release_shipment(s1["id"], ops_headers)
        validate_error(res, ApiErrorId.ERR_PARTY_BLOCKED)

        shipment_after = get_shipment(s1["id"])
        assert shipment_after["status"] == "SCREENED", (
            f"rejected release must leave the shipment SCREENED, got {shipment_after['status']}"
        )
        license_after = get_license(lic["id"])
        assert license_after["remaining_value_cents"] == 1000, (
            f"no consumption may happen on a rejected release, got "
            f"{license_after['remaining_value_cents']}"
        )
