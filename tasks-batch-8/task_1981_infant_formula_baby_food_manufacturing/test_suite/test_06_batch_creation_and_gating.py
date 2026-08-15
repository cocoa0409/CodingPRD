"""Production batch creation and production-start gating: immediate
consistency, formula-state gates, validation currency windows, and optimistic
concurrency on the parent formula (PRD §2.4, §2.6, §3.3, §3.4)."""
import re

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, assert_production_batch,
    create_approved_nutrient_profile, create_ingredient, create_draft_formula,
    create_passed_validation, create_active_formula, create_qualified_supplier,
    create_qc_passed_lot, create_planned_batch, get_formula_version,
    create_production_batch_payload, set_clock,
)


class TestBatchCreateResponse:
    def test_batch_create_returns_fully_populated_batch(self, api, users):
        """PRD §3.4: "The server assigns a unique `batch_number` in the format
        `B-{YYYYMMDD}-{seq}`." and "New batches start in `PLANNED`, with
        `ingredient_consumptions` empty". PRD §4: "Operations that create a new
        resource — whether a top-level resource or a child resource added to a
        parent's collection — return `201 Created`." PRD §2.4: every primary
        entity carries a server-minted UUID `id` and an integer `version`.

        Design: Corner/consistency_model/immediate_consistency_batch_create_response
        """
        scenario = create_active_formula(users, formula_code="CEREAL-IMM",
                                         profile_code="CEREAL-6M")
        version = get_formula_version(users, scenario["formula"]["id"])
        res = api.create_production_batch(
            create_production_batch_payload(
                formula_id=scenario["formula"]["id"], batch_size_kg=75.000,
                expected_formula_version=version),
            users["ps"]["headers"])
        data = validate_success(res, 201)
        assert data["status"] == "PLANNED"
        assert data["formula_id"] == scenario["formula"]["id"]
        assert re.match(r"^B-\d{8}-.+$", data["batch_number"]), (
            f"batch_number must follow B-{{YYYYMMDD}}-{{seq}}, "
            f"got {data['batch_number']!r}")
        assert data.get("ingredient_consumptions", []) == []
        assert_production_batch(data)


class TestFormulaStateGate:
    def _approved_but_not_active_formula(self, api, users):
        """Formula driven to APPROVED (validation passed) but never activated —
        no approved label exists."""
        profile = create_approved_nutrient_profile(
            users, profile_code="INF-0-6M")
        ing_a = create_ingredient(users, "WPC-CROSS", "WPC Cross Test",
                                  "DAIRY_BASE", "HIGH_RISK", "REFRIGERATED")
        ing_b = create_ingredient(users, "LAC-CROSS", "Lactose Cross Test",
                                  "CARBOHYDRATE", "LOW_RISK", "AMBIENT")
        formula = create_draft_formula(
            users, "IF-CROSS-1", "Cross Entity Test", profile["id"],
            ing_a["id"], ing_b["id"])
        validate_success(api.submit_formula_for_review(
            formula["id"], users["ra1"]["headers"]))
        create_passed_validation(users, formula["id"])
        return validate_success(api.approve_formula(
            formula["id"], users["qm"]["headers"]))

    def test_batch_create_rejected_when_formula_approved_not_active(self, api, users):
        """PRD §3.4: "If the referenced formula is not in `ACTIVE` status,
        creation is refused with `ERR_FORMULA_NOT_ACTIVE` (HTTP 422)." An
        APPROVED formula is not ACTIVE.

        Design: Difficulty/cross_entity_state_dependency/batch_production_requires_formula_active_and_validation_passed
        """
        set_clock(users)
        formula = self._approved_but_not_active_formula(api, users)
        assert formula["status"] == "APPROVED"
        res = api.create_production_batch(
            create_production_batch_payload(
                formula_id=formula["id"], batch_size_kg=50.000,
                expected_formula_version=formula["version"]),
            users["ps"]["headers"])
        validate_error(res, ApiErrorId.ERR_FORMULA_NOT_ACTIVE)

    def test_batch_create_rejected_when_formula_draft(self, api, users):
        """PRD §3.4: "If the referenced formula is not in `ACTIVE` status,
        creation is refused with `ERR_FORMULA_NOT_ACTIVE` (HTTP 422)." A DRAFT
        formula is not ACTIVE.

        Design: Difficulty/cross_entity_state_dependency/batch_production_requires_formula_active_and_validation_passed
        """
        set_clock(users)
        profile = create_approved_nutrient_profile(
            users, profile_code="INF-6-12M")
        ing_a = create_ingredient(users, "WPC-DRAFT", "WPC Draft Test",
                                  "DAIRY_BASE", "HIGH_RISK", "REFRIGERATED")
        ing_b = create_ingredient(users, "LAC-DRAFT", "Lactose Draft Test",
                                  "CARBOHYDRATE", "LOW_RISK", "AMBIENT")
        formula = create_draft_formula(
            users, "IF-DRAFT-1", "Draft Formula Test", profile["id"],
            ing_a["id"], ing_b["id"])
        assert formula["status"] == "DRAFT"
        res = api.create_production_batch(
            create_production_batch_payload(
                formula_id=formula["id"], batch_size_kg=50.000,
                expected_formula_version=formula["version"]),
            users["ps"]["headers"])
        validate_error(res, ApiErrorId.ERR_FORMULA_NOT_ACTIVE)


class TestValidationCurrencyWindow:
    def _scenario_with_short_validation(self, users):
        """ACTIVE formula whose DRY_BLEND_HOMOGENEITY validation passes with a
        30-day validity window; lots QC-passed; batch created while the
        validation is still current."""
        set_clock(users, "2026-08-01T00:00:00Z")
        scenario = create_active_formula(
            users, formula_code="IF-EXP-1", profile_code="INF-6-12M",
            validity_days=30)
        supplier = create_qualified_supplier(
            users, "SUP-EXP", ["DAIRY_BASE", "CARBOHYDRATE"], score=85.00)
        create_qc_passed_lot(users, scenario["ing_a"]["id"], supplier["id"],
                             "LOT-EXP-A", quantity_kg=200.000)
        create_qc_passed_lot(users, scenario["ing_b"]["id"], supplier["id"],
                             "LOT-EXP-B", quantity_kg=200.000)
        batch = create_planned_batch(
            users, scenario["formula"]["id"], batch_size_kg=50.000,
            production_date="2026-09-15T00:00:00Z")
        return scenario, batch

    def test_expired_validation_blocks_production_start(self, api, users):
        """PRD §3.4: starting production requires "that for a `DRY_BLEND` or
        `COMBINATION` formula at least one `ProcessValidation` of type
        `DRY_BLEND_HOMOGENEITY` exists in `PASSED` state with `valid_until`
        strictly after the current logical timestamp ... (else
        `ERR_VALIDATION_REQUIRED`)". The validation passed on 2026-08-01 with a
        30-day validity; at 2026-09-15 its window has closed.

        Design: Difficulty/resource_temporal_overlap/process_validation_expiry_blocks_production_start
        """
        scenario, batch = self._scenario_with_short_validation(users)
        set_clock(users, "2026-09-15T00:00:00Z")
        res = api.start_production(batch["id"], users["ps"]["headers"])
        validate_error(res, ApiErrorId.ERR_VALIDATION_REQUIRED)

    def test_passed_validation_auto_expires_after_valid_until(self, api, users):
        """PRD §3.3: "A `PASSED` validation whose `valid_until` passes is
        automatically transitioned by the system to the terminal `EXPIRED`
        state". Computed per PRD §3.3: "`valid_until` is computed as
        `completed_at + validation_validity_days` (calendar days)" — here
        2026-08-01 + 30 days = 2026-08-31, passed by 2026-09-15.

        Design: Difficulty/resource_temporal_overlap/process_validation_expiry_blocks_production_start
        """
        scenario, _batch = self._scenario_with_short_validation(users)
        set_clock(users, "2026-09-15T00:00:00Z")
        pv = validate_success(api.get_process_validation(
            scenario["validation"]["id"], users["qa"]["headers"]))
        assert pv["status"] == "EXPIRED", (
            f"Validation past valid_until must be EXPIRED, got {pv['status']}")


class TestFormulaOptimisticConcurrency:
    def test_stale_formula_version_rejected_on_batch_create(self, api, users):
        """PRD §2.6: "Creating a new production batch requires the request body
        to include `expected_formula_version`, matching the current `version`
        of the `Formula` referenced by `formula_id`." and "The server compares
        the submitted value against the parent's current `version` and rejects
        the request with `ERR_STALE_VERSION` (HTTP 412) on mismatch". The first
        batch creation advances the formula version (PRD §3.4: "Successful
        creation increments the parent formula's `version` by one."), so a
        second create carrying the previously read version is stale.

        Design: Difficulty/concurrency_occ_stale_version/stale_formula_version_on_batch_create
        """
        scenario = create_active_formula(users, formula_code="IF-OCC-1")
        version = get_formula_version(users, scenario["formula"]["id"])
        first = api.create_production_batch(
            create_production_batch_payload(
                formula_id=scenario["formula"]["id"], batch_size_kg=50.000,
                expected_formula_version=version),
            users["ps"]["headers"])
        validate_success(first, 201)
        res = api.create_production_batch(
            create_production_batch_payload(
                formula_id=scenario["formula"]["id"], batch_size_kg=75.000,
                production_date="2026-08-02T00:00:00Z",
                expected_formula_version=version),
            users["ps"]["headers"])
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    def test_batch_create_increments_formula_version(self, api, users):
        """PRD §3.4: "Successful creation increments the parent formula's
        `version` by one."

        Design: Difficulty/concurrency_occ_stale_version/stale_formula_version_on_batch_create
        """
        scenario = create_active_formula(users, formula_code="IF-OCC-2")
        before = get_formula_version(users, scenario["formula"]["id"])
        batch = create_planned_batch(users, scenario["formula"]["id"])
        assert batch["status"] == "PLANNED"
        after = get_formula_version(users, scenario["formula"]["id"])
        assert after == before + 1, (
            f"Formula version must increment by one on batch creation: "
            f"{before} -> {after}")
