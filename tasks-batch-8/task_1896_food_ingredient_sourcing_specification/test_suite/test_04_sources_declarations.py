"""Approved-source lifecycle, regulatory declarations, and substitution requests."""

from test_helpers import (
    PM_1,
    QM_1,
    SQE_1,
    ApiErrorId,
    add_parameter,
    approve_spec,
    assert_approved_source,
    assert_assessment,
    assert_declaration,
    assert_qty,
    assert_substitution_request,
    collect_declarations,
    create_allergen_declaration_payload,
    create_approved_source_payload,
    create_coa_payload,
    create_draft_spec,
    create_ingredient_entity,
    create_ingredient_with_effective_spec,
    create_provisional_source,
    create_qualified_supplier,
    create_substitution_request,
    create_supplier_entity,
    fresh_ingredient,
    fresh_ingredient_version,
    fresh_source,
    make_procurement_manager_headers,
    make_quality_manager_headers,
    make_sqe_headers,
    set_clock,
    setup_dual_sourced_ingredient,
    setup_source_with_contract,
    setup_two_active_sources_same_spec,
    setup_two_spec_sources,
    submit_spec,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSourceActivationCrossEntityGates:
    def test_source_activation_blocked_while_supplier_in_qualification(self, api):
        """PRD §3.4: "The activation is rejected with `ERR_INVALID_STATE` if the
        source is not `PROVISIONAL`, with `ERR_SUPPLIER_NOT_QUALIFIED` if the
        referenced supplier is not `QUALIFIED`, with `ERR_SPEC_NOT_EFFECTIVE` if the
        pinned spec is not currently `EFFECTIVE`, and with `ERR_DECLARATION_MISSING`
        if either of the two required regulatory declarations is absent."

        Design: Difficulty/cross_entity_state_dependency/source_activation_depends_on_supplier_state_and_declaration_state
        """
        ingredient, spec = create_ingredient_with_effective_spec(
            "SWT-1",
            parameters=[{
                "parameter_name": "brix", "criticality": "MINOR", "uom": "deg",
                "target_value": 65, "min_value": 60, "max_value": 70,
            }],
        )
        # Supplier stuck IN_QUALIFICATION (open qualification, never decided).
        supplier = create_supplier_entity("SUP-X", risk_tier="TIER_B", country_of_operation="BR")
        validate_success(api.create_qualification(
            supplier["id"], {"questionnaire_score": 80, "document_pack_complete": True},
            make_sqe_headers(SQE_1),
        ), expected_status=201)
        source = create_provisional_source(ingredient["id"], supplier["id"], spec["id"])
        # Both declarations in place, so the ONLY gate that can fire is the
        # supplier-qualification gate.
        collect_declarations(source["id"], primary_country="BR")

        resp = api.activate_approved_source(
            ingredient["id"], source["id"], make_procurement_manager_headers(PM_1)
        )
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_NOT_QUALIFIED)

    def test_source_activation_blocked_when_declarations_missing(self, api):
        """PRD §3.4: "Both declarations must exist in `CURRENT` status with the
        logical clock inside the `[valid_from, valid_until)` window: one of
        `declaration_type` `ALLERGEN` and one of `declaration_type`
        `COUNTRY_OF_ORIGIN`." — with a QUALIFIED supplier and EFFECTIVE pinned
        spec but no declarations, activation draws `ERR_DECLARATION_MISSING`.

        Design: Difficulty/cross_entity_state_dependency/source_activation_depends_on_supplier_state_and_declaration_state
        """
        ingredient, spec = create_ingredient_with_effective_spec(
            "SWT-2",
            parameters=[{
                "parameter_name": "brix", "criticality": "MINOR", "uom": "deg",
                "target_value": 65, "min_value": 60, "max_value": 70,
            }],
        )
        supplier = create_qualified_supplier("SUP-Y", country_of_operation="BR")
        source = create_provisional_source(ingredient["id"], supplier["id"], spec["id"])
        # No declarations collected: the declaration gate is the only one failing.

        resp = api.activate_approved_source(
            ingredient["id"], source["id"], make_procurement_manager_headers(PM_1)
        )
        validate_error(resp, ApiErrorId.ERR_DECLARATION_MISSING)


class TestDualSourceBreachRoundtrip:
    def test_dual_source_breach_roundtrip_suspend_reinstate(self, api, procurement_manager_headers):
        """PRD §3.10: "For an ingredient, count the approved sources that are in
        `ACTIVE` status and pinned to the ingredient's `active_spec_id`. When
        `requires_dual_source` is true and that count is less than two,
        `current_dual_source_breach` is set to true; when the count is exactly two
        or more, the breach is cleared."

        Design: Difficulty/compensating_invariant/dual_source_breach_recompute_roundtrip_conserved
        """
        ctx = setup_dual_sourced_ingredient("DUAL-2")
        ingredient = ctx["ingredient"]
        src_a = ctx["sources"][0]
        assert ctx["ingredient"]["current_dual_source_breach"] is False

        validate_success(
            api.suspend_approved_source(ingredient["id"], src_a["id"], procurement_manager_headers)
        )
        mid = fresh_ingredient(ingredient["id"])
        assert mid["current_dual_source_breach"] is True, (
            "one ACTIVE source left on the EFFECTIVE spec: 1 < 2 must raise the breach"
        )

        validate_success(
            api.reinstate_approved_source(ingredient["id"], src_a["id"], procurement_manager_headers)
        )
        after = fresh_ingredient(ingredient["id"])
        assert after["current_dual_source_breach"] is False, (
            "suspend+reinstate is a compensating pair: the breach returns to false"
        )

    def test_dual_source_breach_reinstate_clears_suspension_reason(self, api, procurement_manager_headers):
        """PRD §3.4: "Reinstatement moves a `SUSPENDED` source back to `ACTIVE` and
        clears `suspension_reason` to `NONE`" and PRD §3.10: "when the count is
        exactly two or more, the breach is cleared."

        Design: Difficulty/compensating_invariant/dual_source_breach_recompute_roundtrip_conserved
        """
        ctx = setup_dual_sourced_ingredient("DUAL-3")
        ingredient = ctx["ingredient"]
        src_a, src_b = ctx["sources"]
        # Boundary: exactly two ACTIVE sources on the EFFECTIVE spec -> no breach.
        assert ctx["ingredient"]["current_dual_source_breach"] is False

        api.suspend_approved_source(ingredient["id"], src_a["id"], procurement_manager_headers)
        reinstated = validate_success(
            api.reinstate_approved_source(ingredient["id"], src_a["id"], procurement_manager_headers)
        )
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["suspension_reason"] == "NONE"
        assert fresh_ingredient(ingredient["id"])["current_dual_source_breach"] is False
        assert fresh_source(src_b["id"])["status"] == "ACTIVE", "the untouched source is undisturbed"


class TestSourceLifecycleGuards:
    def test_revoked_source_terminal_lockdown(self, api, procurement_manager_headers):
        """PRD §3.4: activation "is rejected with `ERR_INVALID_STATE` if the source
        is not `PROVISIONAL`", reinstatement moves only "a `SUSPENDED` source back
        to `ACTIVE`", and revocation "is rejected with `ERR_INVALID_STATE` if the
        source is not in one of those three statuses" — REVOKED is terminal.

        Design: Corner/state_machines/revoked_source_terminal_lockdown
        """
        ingredient, spec = create_ingredient_with_effective_spec("ENZ-RVK")
        supplier = create_supplier_entity("SUP-RVK")  # PROSPECT: activation never reached
        source = create_provisional_source(ingredient["id"], supplier["id"], spec["id"])
        revoked = validate_success(
            api.revoke_approved_source(ingredient["id"], source["id"], procurement_manager_headers)
        )
        assert revoked["status"] == "REVOKED"

        resp_activate = api.activate_approved_source(ingredient["id"], source["id"], procurement_manager_headers)
        validate_error(resp_activate, ApiErrorId.ERR_INVALID_STATE)
        resp_reinstate = api.reinstate_approved_source(ingredient["id"], source["id"], procurement_manager_headers)
        validate_error(resp_reinstate, ApiErrorId.ERR_INVALID_STATE)
        resp_revoke = api.revoke_approved_source(ingredient["id"], source["id"], procurement_manager_headers)
        validate_error(resp_revoke, ApiErrorId.ERR_INVALID_STATE)

    def test_source_revoke_blocked_by_active_contract(self, api, procurement_manager_headers):
        """PRD §3.4: "The manual path is rejected with `ERR_INVALID_STATE` if the
        source is not in one of those three statuses, and with
        `ERR_ACTIVE_CONTRACT_EXISTS` if any contract of the source is `ACTIVE`."

        Design: Corner/validations/source_revoke_blocked_by_active_contract
        """
        ctx = setup_source_with_contract("ENZ-ACE", supplier_code="SUP-ACE")
        ingredient, source, contract = ctx["ingredient"], ctx["source"], ctx["contract"]

        resp = api.revoke_approved_source(ingredient["id"], source["id"], procurement_manager_headers)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_CONTRACT_EXISTS)

        validate_success(api.terminate_contract(source["id"], contract["id"], procurement_manager_headers))
        revoked = validate_success(
            api.revoke_approved_source(ingredient["id"], source["id"], procurement_manager_headers)
        )
        assert revoked["status"] == "REVOKED"

    def test_source_activation_blocked_when_pinned_spec_not_effective(self, api):
        """PRD §3.4: "The activation is rejected with `ERR_INVALID_STATE` if the
        source is not `PROVISIONAL`, with `ERR_SUPPLIER_NOT_QUALIFIED` if the
        referenced supplier is not `QUALIFIED`, with `ERR_SPEC_NOT_EFFECTIVE` if the
        pinned spec is not currently `EFFECTIVE`, and with `ERR_DECLARATION_MISSING`
        if either of the two required regulatory declarations is absent."

        Design: Corner/errors/source_activation_blocked_when_pinned_spec_not_effective
        """
        ingredient = create_ingredient_entity("ENZ-SNE2")
        spec = create_draft_spec(ingredient["id"])
        add_parameter(ingredient["id"], spec["id"])
        submit_spec(ingredient["id"], spec["id"])
        approve_spec(ingredient["id"], spec["id"])  # APPROVED, never EFFECTIVE
        supplier = create_qualified_supplier("SUP-SNE2")
        source = create_provisional_source(ingredient["id"], supplier["id"], spec["id"])
        collect_declarations(source["id"])

        resp = api.activate_approved_source(
            ingredient["id"], source["id"], make_procurement_manager_headers(PM_1)
        )
        validate_error(resp, ApiErrorId.ERR_SPEC_NOT_EFFECTIVE)


class TestDeclarations:
    def test_declaration_supersede_on_recollect(self, api, regulatory_affairs_headers):
        """PRD §3.4: "Collecting a declaration supersedes any prior `CURRENT`
        declaration of the same `declaration_type` for the same approved source —
        only one `CURRENT` declaration per (source, type) pair exists at any time —
        and `collected_by_user_id` records the acting operator." PRD §2.3: "Rows are
        returned ordered by `created_at` ascending (earliest created first)".

        Design: Corner/state_machines/declaration_supersede_on_recollect
        """
        ingredient, spec = create_ingredient_with_effective_spec("ENZ-DCL")
        supplier = create_supplier_entity("SUP-DCL")
        source = create_provisional_source(ingredient["id"], supplier["id"], spec["id"])

        validate_success(api.create_declaration(
            source["id"],
            create_allergen_declaration_payload(payload={"allergen_tags": ["NONE"]}),
            regulatory_affairs_headers,
        ), expected_status=201)
        validate_success(api.create_declaration(
            source["id"],
            create_allergen_declaration_payload(
                payload={"allergen_tags": ["SOY"]},
                valid_from="2026-08-01T00:00:00Z", valid_until="2027-08-01T00:00:00Z",
            ),
            regulatory_affairs_headers,
        ), expected_status=201)

        data, meta = validate_paginated(api.list_declarations(source["id"], regulatory_affairs_headers))
        allergen_rows = [d for d in data if d["declaration_type"] == "ALLERGEN"]
        assert meta["total_count"] == 2
        assert len(allergen_rows) == 2
        first, second = allergen_rows[0], allergen_rows[1]  # created_at ASC
        assert first["status"] == "SUPERSEDED", "the earlier declaration is superseded"
        assert second["status"] == "CURRENT", "the recollected declaration is the CURRENT one"
        current_rows = [d for d in allergen_rows if d["status"] == "CURRENT"]
        assert len(current_rows) == 1, "exactly one CURRENT declaration per (source, type)"

    def test_declaration_expiry_suspends_source_via_sweep(self, api, procurement_manager_headers, regulatory_affairs_headers):
        """PRD §2.6: "**Declaration expiry sweep** — every `CURRENT` regulatory
        declaration whose `valid_until` is at or before the new clock transitions to
        `EXPIRED`; its parent approved source, if it was `ACTIVE`, transitions to
        `SUSPENDED` with `suspension_reason` set to `MANUAL`; and the supplier's
        composite risk score is recomputed (the declaration-lapse component becomes
        100)."

        Design: Corner/cross_cutting_layers/declaration_expiry_suspends_source_via_sweep
        """
        ingredient, spec = create_ingredient_with_effective_spec("ENZ-DXP")
        supplier = create_qualified_supplier("SUP-DXP")
        source = create_provisional_source(ingredient["id"], supplier["id"], spec["id"])
        collect_declarations(
            source["id"], valid_from="2026-01-01T00:00:00Z", valid_until="2026-08-10T00:00:00Z",
        )
        validate_success(
            api.activate_approved_source(ingredient["id"], source["id"], procurement_manager_headers)
        )

        # At clock == valid_until exactly, the declaration is end-exclusive expired.
        set_clock("2026-08-10T00:00:00Z")

        src_after = fresh_source(source["id"])
        assert src_after["status"] == "SUSPENDED", "declaration lapse suspends the ACTIVE source"
        assert src_after["suspension_reason"] == "MANUAL"

        declarations, _meta = validate_paginated(
            api.list_declarations(source["id"], regulatory_affairs_headers)
        )
        for row in declarations:
            assert_declaration(row)
            assert row["status"] == "EXPIRED", "valid_until <= clock: declaration must be EXPIRED"

    def test_rbac_procurement_cannot_collect_declaration(self, api, procurement_manager_headers):
        """PRD §2.1: "a role that is not permitted for the endpoint is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD §4 restricts
        POST /sourcing/approved-sources/{id}/declarations to RegulatoryAffairs.

        Design: Corner/roles/rbac_procurement_cannot_collect_declaration
        """
        ingredient, spec = create_ingredient_with_effective_spec("RBAC-3")
        supplier = create_supplier_entity("RBAC-S3")
        source = create_provisional_source(ingredient["id"], supplier["id"], spec["id"])

        resp = api.create_declaration(
            source["id"], create_allergen_declaration_payload(), procurement_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_cross_reference_mismatch_on_source_create(self, api, procurement_manager_headers):
        """PRD §2.9: "The `pinned_spec_id` on an approved-source create must
        reference a spec that belongs to the path ingredient. ... Any violation is
        rejected with `ERR_CROSS_REFERENCE_MISMATCH` (HTTP 422)."

        Design: Corner/validations/cross_reference_mismatch_on_source_create
        """
        ing_a = create_ingredient_entity("XR-A")
        ing_b = create_ingredient_entity("XR-B")
        spec_b = create_draft_spec(ing_b["id"])  # belongs to ingredient B
        supplier = create_supplier_entity("SUP-XR")

        resp = api.create_approved_source(
            ing_a["id"],
            create_approved_source_payload(
                supplier["id"], spec_b["id"], fresh_ingredient_version(ing_a["id"]),
            ),
            procurement_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CROSS_REFERENCE_MISMATCH)


class TestCoARegistrationGate:
    def test_coa_registration_blocked_when_source_suspended(self, api, procurement_manager_headers):
        """PRD §3.4: "While a source is `SUSPENDED`, its contracts remain `ACTIVE`
        (they are not terminated) but new CoA registration against the source is
        blocked." and PRD §3.6: "Registration is rejected with
        `ERR_MEASURED_VALUES_INCOMPLETE` if the coverage is wrong, with
        `ERR_SOURCE_NOT_ACTIVE` if the source is not `ACTIVE`, and with
        `ERR_INVALID_REQUEST` if `shipped_qty_kg` is not positive."

        Design: Corner/endpoints/coa_registration_blocked_when_source_suspended
        """
        ctx = setup_source_with_contract("ENZ-SUS", supplier_code="SUP-SUS")
        ingredient, source, contract = ctx["ingredient"], ctx["source"], ctx["contract"]
        validate_success(
            api.suspend_approved_source(ingredient["id"], source["id"], procurement_manager_headers)
        )

        resp = api.register_coa(
            source["id"],
            create_coa_payload(
                contract["id"],
                [{"parameter_name": "moisture", "observed_value": 5}],
                lot_number="SUS-1",
            ),
            make_sqe_headers(SQE_1),
        )
        validate_error(resp, ApiErrorId.ERR_SOURCE_NOT_ACTIVE)


class TestSubstitutionRequests:
    def test_formula_impact_delta_computed_values(self, api, sqe_headers):
        """PRD §3.8: "`total_delta_per_unit` is the sum of all `cost_delta` values
        rounded half-up to four decimal places." and "The request's
        `requires_regulatory_signoff` is set to true when `allergen_delta_tags` is
        non-empty or `coo_changed` is true, and `impact_delta_per_unit` is set to
        `total_delta_per_unit`."

        Design: Corner/calculations/formula_impact_delta_computed_values
        """
        ctx = setup_two_spec_sources(
            "IMP-1",
            v1_parameters=[
                {"parameter_name": "moisture", "criticality": "MINOR", "uom": "percent",
                 "target_value": 5, "min_value": 0, "max_value": 10},
                {"parameter_name": "density", "criticality": "MINOR", "uom": "g_ml",
                 "target_value": 1.04, "min_value": 0, "max_value": 2},
            ],
            v2_parameters=[
                {"parameter_name": "moisture", "criticality": "MINOR", "uom": "percent",
                 "target_value": 4, "min_value": 0, "max_value": 10},
                {"parameter_name": "density", "criticality": "MINOR", "uom": "g_ml",
                 "target_value": 1.06, "min_value": 0, "max_value": 2},
            ],
        )
        ingredient = ctx["ingredient"]
        request = create_substitution_request(
            ingredient["id"], ctx["src_a"]["id"], ctx["src_b"]["id"],
            sensitivities=[
                {"parameter_name": "moisture", "cost_per_unit_delta": 0.10},
                {"parameter_name": "density", "cost_per_unit_delta": 0.50},
            ],
        )
        assessed = validate_success(
            api.assess_substitution(ingredient["id"], request["id"], sqe_headers)
        )
        assert_substitution_request(assessed)
        assert assessed["status"] == "IMPACT_ASSESSED"
        # moisture: (4 - 5) x 0.10 = -0.1000; density: (1.06 - 1.04) x 0.50 = 0.0100.
        assert_qty(assessed["impact_delta_per_unit"], -0.09, places=4)
        assert assessed["requires_regulatory_signoff"] is False

        rows, _meta = validate_paginated(
            api.get_assessment(ingredient["id"], request["id"], sqe_headers)
        )
        assert len(rows) == 1
        assessment = rows[0]
        assert_assessment(assessment)
        assert_qty(assessment["total_delta_per_unit"], -0.09, places=4)
        assert assessment["coo_changed"] is False
        assert assessment["allergen_delta_tags"] == []

    def test_substitution_approve_blocked_by_delta_threshold(self, api):
        """PRD §3.8: "Independently, a fiscal gate caps the auto-approvable size:
        the absolute value of `impact_delta_per_unit` must be at most 0.5000
        (exactly 0.5000 passes); larger absolute deltas are rejected with
        `ERR_IMPACT_DELTA_EXCEEDS_THRESHOLD` and require the `PENDING_REGULATORY`
        path regardless of the sign-off flag."

        Design: Corner/validations/substitution_approve_blocked_by_delta_threshold_and_signoff
        """
        ctx = setup_two_spec_sources(
            "THR-1",
            v1_parameters=[{
                "parameter_name": "moisture", "criticality": "MINOR", "uom": "percent",
                "target_value": 5, "min_value": 0, "max_value": 20,
            }],
            v2_parameters=[{
                "parameter_name": "moisture", "criticality": "MINOR", "uom": "percent",
                "target_value": 11, "min_value": 0, "max_value": 20,
            }],
        )
        ingredient = ctx["ingredient"]
        request = create_substitution_request(
            ingredient["id"], ctx["src_a"]["id"], ctx["src_b"]["id"],
            sensitivities=[{"parameter_name": "moisture", "cost_per_unit_delta": 0.10}],
        )
        assessed = validate_success(
            api.assess_substitution(ingredient["id"], request["id"], make_sqe_headers(SQE_1))
        )
        # moisture: (11 - 5) x 0.10 = +0.6000, above the 0.5000 auto-approve cap.
        assert_qty(assessed["impact_delta_per_unit"], 0.6, places=4)

        resp = api.approve_substitution(
            ingredient["id"], request["id"], make_quality_manager_headers(QM_1)
        )
        validate_error(resp, ApiErrorId.ERR_IMPACT_DELTA_EXCEEDS_THRESHOLD)

    def test_route_regulatory_when_not_required_rejected(self, api, sqe_headers):
        """PRD §3.8: "Routing to regulatory moves an `IMPACT_ASSESSED` request to
        `PENDING_REGULATORY`; it is rejected with
        `ERR_REGULATORY_SIGNOFF_NOT_REQUIRED` when `requires_regulatory_signoff` is
        false."

        Design: Corner/validations/route_regulatory_when_not_required_rejected
        """
        ctx = setup_two_active_sources_same_spec("IMP-2")
        ingredient = ctx["ingredient"]
        request = create_substitution_request(
            ingredient["id"], ctx["src_a"]["id"], ctx["src_b"]["id"],
            reason_code="DUAL_SOURCE_BREACH",
        )
        assessed = validate_success(
            api.assess_substitution(ingredient["id"], request["id"], sqe_headers)
        )
        assert assessed["requires_regulatory_signoff"] is False, (
            "same-spec substitution: no allergen or country-of-origin change"
        )

        resp = api.route_regulatory(ingredient["id"], request["id"], sqe_headers)
        validate_error(resp, ApiErrorId.ERR_REGULATORY_SIGNOFF_NOT_REQUIRED)

    def test_substitution_execute_suspends_replaced_source(self, api, procurement_manager_headers):
        """PRD §3.8: "On execution the from-source transitions from `ACTIVE` to
        `SUSPENDED` with `suspension_reason` of `MANUAL` — the replaced source is
        parked — and the ingredient's `current_dual_source_breach` is recomputed."

        Design: Corner/endpoints/substitution_execute_suspends_replaced_source
        """
        ctx = setup_two_active_sources_same_spec("EXE-1")
        ingredient = ctx["ingredient"]
        src_a, src_b = ctx["src_a"], ctx["src_b"]
        request = create_substitution_request(
            ingredient["id"], src_a["id"], src_b["id"], reason_code="SUPPLY_SHORTAGE",
        )
        validate_success(api.assess_substitution(ingredient["id"], request["id"], make_sqe_headers(SQE_1)))
        # Approved by a QualityManager who is not the requester.
        validate_success(
            api.approve_substitution(ingredient["id"], request["id"], make_quality_manager_headers(QM_1))
        )

        executed = validate_success(
            api.execute_substitution(ingredient["id"], request["id"], procurement_manager_headers)
        )
        assert_substitution_request(executed)
        assert executed["status"] == "EXECUTED"

        from_after = fresh_source(src_a["id"])
        assert_approved_source(from_after)
        assert from_after["status"] == "SUSPENDED"
        assert from_after["suspension_reason"] == "MANUAL"
        assert fresh_source(src_b["id"])["status"] == "ACTIVE", "the replacement source stays ACTIVE"
