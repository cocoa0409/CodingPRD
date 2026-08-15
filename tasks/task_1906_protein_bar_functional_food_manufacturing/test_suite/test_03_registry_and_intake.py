"""Supplier/ingredient registry, formula revision creation, and ingredient-lot
intake rules (PRD §2.6, §3.1, §3.2, §3.4)."""
from test_helpers import (
    ApiErrorId,
    assert_2dp,
    assert_lot_mass_invariant,
    assert_revision,
    assert_supplier,
    create_ingredient_lot_payload,
    create_revision_payload,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers import api_client as client
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["plant_admin_headers"]
SCI = TEST_USERS["formulation_scientist_headers"]
QM = TEST_USERS["quality_manager_headers"]


class TestSupplierDefaults:
    def test_creation_applies_defaults(self, api):
        """PRD §3.1: "A `PlantAdmin` registers each supplier with a legal
        `name` and the allergens handled at the supplier's site in
        `allergens_handled`, which defaults to an empty list when omitted."
        PRD §3.1: "Every supplier begins life with `qualification_status`
        `PROVISIONAL`."

        Design: Corner/entities/c_supplier_creation_defaults
        """
        data = validate_success(client.create_supplier({"name": "S-DEF"}, ADMIN), 201)
        assert_supplier(data)
        assert data["qualification_status"] == "PROVISIONAL"
        assert data["allergens_handled"] == []


class TestIngredientShapeValidation:
    def test_missing_name_returns_invalid_request(self, api):
        """PRD §2.6: "6. **Request shape** — required fields present, types
        correct, numeric ranges honored, and required arrays non-empty, else
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/c_ingredient_missing_name_returns_invalid_request
        """
        resp = client.create_ingredient(
            {"category": "PROTEIN", "nominal_protein_pct": 0.8}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_undeclared_category_returns_invalid_enum(self, api):
        """PRD §2.6: "7. **Enum membership** — enum-typed fields must carry a
        declared member, else `ERR_INVALID_ENUM_VALUE` (400)."
        PRD §3.1: "Ingredients are registered by a `PlantAdmin` with a `name`,
        a functional `category` drawn from `PROTEIN`, `SWEETENER`, `BINDER`,
        `FAT`, `FLAVOR`, and `ADDITIVE`"

        Design: Corner/entities/c_ingredient_invalid_enum_returns_invalid_enum
        """
        resp = client.create_ingredient({"name": "BAD", "category": "MEAT"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM_VALUE, 400)


class TestRevisionComputedFields:
    def test_revision_no_sequence_and_allergen_profile(self, api):
        """PRD §3.4: "At creation the revision records its parent in
        `formula_id`, receives a `revision_no`, a 1-based sequence number
        within its formula assigned in creation order, and a computed
        `allergen_profile`: the union of the `allergen_tags` of every
        ingredient referenced by its lines, sorted alphabetically."
        PRD §3.4: "A new revision starts in `DRAFT`"

        Design: Corner/entities/c_revision_computed_fields
        """
        whey = fixtures.create_ingredient(
            "WHEY", "PROTEIN", ["MILK"], nominal_protein_pct=0.8
        )
        oats = fixtures.create_ingredient("OATS", "BINDER", ["WHEAT"])
        cust = fixtures.create_customer("C1")
        formula = fixtures.create_formula(cust["id"], "F", bar_weight_g=60)

        first = validate_success(
            client.create_revision(
                formula["id"],
                create_revision_payload(
                    ingredient_lines=[
                        fixtures.line(whey["id"], 40, True),
                        fixtures.line(oats["id"], 40, False),
                    ],
                    target_protein_g_per_serving=15,
                ),
                SCI,
            ),
            201,
        )
        assert_revision(first)
        assert first["revision_no"] == 1
        assert first["status"] == "DRAFT"
        assert first["allergen_profile"] == ["MILK", "WHEAT"]

        second = validate_success(
            client.create_revision(
                formula["id"],
                create_revision_payload(
                    ingredient_lines=[fixtures.line(whey["id"], 45, True)],
                    target_protein_g_per_serving=17,
                ),
                SCI,
            ),
            201,
        )
        assert second["revision_no"] == 2
        assert second["allergen_profile"] == ["MILK"]


class TestLotIntake:
    def test_new_lot_starts_in_quarantine_with_full_availability(self, api):
        """PRD §3.2: "Every lot arrives in `QUARANTINE`, unavailable for
        reservation."
        PRD §2.8: "Every ingredient lot is a small ledger governed by a
        conservation invariant: its `available_qty_kg` always equals its
        `received_qty_kg` minus its `reserved_qty_kg` minus its
        `consumed_qty_kg`."

        Design: Corner/state_machines/c_lot_initial_quarantine
        """
        sup = fixtures.create_supplier("S1", "APPROVED")
        whey = fixtures.create_ingredient(
            "WHEY", "PROTEIN", ["MILK"], nominal_protein_pct=0.8
        )
        lot = validate_success(
            client.create_ingredient_lot(
                create_ingredient_lot_payload(
                    ingredient_id=whey["id"], supplier_id=sup["id"], lot_code="WL-1",
                    received_qty_kg=50, coa_protein_pct=0.8,
                ),
                ADMIN,
            ),
            201,
        )
        assert lot["status"] == "QUARANTINE"
        assert_2dp(lot["available_qty_kg"], 50.0, "available_qty_kg")
        assert_2dp(lot["reserved_qty_kg"], 0.0, "reserved_qty_kg")
        assert_2dp(lot["consumed_qty_kg"], 0.0, "consumed_qty_kg")
        assert_lot_mass_invariant(lot)

    def test_body_fk_must_reference_existing_ingredient(self, api):
        """PRD §2.6: "5. **Body foreign keys** — every identifier carried in
        the request body (`ingredient_id`, `supplier_id`, `customer_id`,
        `revision_id`, `agreement_id`, `line_id`, `run_id`, and each
        `ingredient_id` inside `ingredient_lines`) must reference an existing
        resource, producing the corresponding 404."

        Design: Corner/entities/c_lot_body_fk_existence
        """
        sup = fixtures.create_supplier("S1", "APPROVED")
        resp = client.create_ingredient_lot(
            create_ingredient_lot_payload(
                ingredient_id="22222222-2222-2222-2222-222222222222",
                supplier_id=sup["id"], lot_code="X-1", received_qty_kg=10,
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INGREDIENT_NOT_FOUND, 404)

    def test_release_moves_quarantine_to_released_and_bumps_version(self, api):
        """PRD §3.2: "Releasing a quarantined lot moves its `status` from
        `QUARANTINE` to `RELEASED`, making it eligible for the reservation
        ledger of §2.8."
        PRD §2.4: "As a rule, every state transition, field update, and
        system-driven reconciliation described in this document is a mutation:
        it increments the owning resource's `version` by one and refreshes its
        `updated_at`"

        Design: Corner/state_machines/c_lot_release_transition
        """
        sup = fixtures.create_supplier("S1", "APPROVED")
        whey = fixtures.create_ingredient(
            "WHEY", "PROTEIN", ["MILK"], nominal_protein_pct=0.8
        )
        lot = fixtures.receive_lot(whey["id"], sup["id"], "WL-1", 50,
                                   coa_protein_pct=0.8)
        released = validate_success(client.release_lot(lot["id"], QM), 200)
        assert released["status"] == "RELEASED"
        assert released["version"] == lot["version"] + 1

    def test_rejected_lot_is_terminal(self, api):
        """PRD §3.2: "Rejection from `QUARANTINE` simply moves the lot to
        `REJECTED`, a terminal state."
        PRD §2.6: "8. **Terminal-state lock** — the addressed resource must not
        sit in a terminal state: a `TERMINATED` agreement, a `SUPERSEDED`
        revision, a `REJECTED` or `DEPLETED` lot, a `CANCELLED` run or
        changeover, a lot release whose decision is `RELEASED` or `SCRAPPED`,
        or a `COMPLETED`, `FAILED`, or `TERMINATED` study all reject further
        action with `ERR_TERMINAL_STATE_LOCKED` (409)."

        Design: Corner/state_machines/c_terminal_lot_release_rejected
        """
        sup = fixtures.create_supplier("S1", "APPROVED")
        whey = fixtures.create_ingredient(
            "WHEY", "PROTEIN", ["MILK"], nominal_protein_pct=0.8
        )
        lot = fixtures.receive_lot(whey["id"], sup["id"], "WL-1", 50,
                                   coa_protein_pct=0.8)
        validate_success(client.reject_lot(lot["id"], QM), 200)
        resp = client.release_lot(lot["id"], QM)
        validate_error(resp, ApiErrorId.ERR_TERMINAL_STATE_LOCKED, 409)
        stayed = validate_success(client.get_ingredient_lot(lot["id"], QM), 200)
        assert stayed["status"] == "REJECTED"

    def test_duplicate_lot_code_within_ingredient_rejected(self, api):
        """PRD §3.2: "then the `lot_code` must be unique within its ingredient
        across all lots that are not `REJECTED`, otherwise the receipt is
        rejected with `ERR_DUPLICATE_LOT_CODE` (HTTP 409)."

        Design: Corner/validations/c_duplicate_lot_code
        """
        sup = fixtures.create_supplier("S1", "APPROVED")
        whey = fixtures.create_ingredient(
            "WHEY", "PROTEIN", ["MILK"], nominal_protein_pct=0.8
        )
        fixtures.receive_lot(whey["id"], sup["id"], "WL-1", 50, coa_protein_pct=0.8)
        resp = client.create_ingredient_lot(
            create_ingredient_lot_payload(
                ingredient_id=whey["id"], supplier_id=sup["id"], lot_code="WL-1",
                received_qty_kg=25, received_at="2026-08-02T00:00:00Z",
                coa_protein_pct=0.8,
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_LOT_CODE, 409)


class TestReferentialCreationGates:
    def test_four_referential_gates_each_fire_their_own_error(self, api):
        """PRD §3.2: "first the referenced supplier's `qualification_status`
        must be `APPROVED`, otherwise the receipt is rejected with
        `ERR_SUPPLIER_NOT_QUALIFIED` (HTTP 422)"
        PRD §3.4: "first, every ingredient referenced by the revision's lines
        must still be `ACTIVE`, else the submission is rejected with
        `ERR_INGREDIENT_DISCONTINUED` (HTTP 422)"
        PRD §3.3: "A customer whose `status` is `SUSPENDED` cannot be the
        subject of a new formula or a new agreement, and no production run may
        be created under its agreements — each attempt is rejected with
        `ERR_CUSTOMER_SUSPENDED` (HTTP 422)."
        PRD §3.4: "once `ARCHIVED`, it cannot receive new revisions, new
        shelf-life studies, or — transitively, through its revisions — new
        production runs, and attempts to create a revision or study against it
        are rejected with `ERR_FORMULA_ARCHIVED` (HTTP 422)."

        Design: Corner/validations/c_creation_referential_violations
        """
        prov = fixtures.create_supplier("S-PROV", "PROVISIONAL")
        disc = fixtures.create_ingredient("DISC", "BINDER", [], status="DISCONTINUED")
        c1 = fixtures.create_customer("C1", "c1@x.com")
        c2 = fixtures.create_customer("C2", "c2@x.com", status="SUSPENDED")
        fd = fixtures.create_formula(c1["id"], "FD", bar_weight_g=60)
        rd = fixtures.create_revision(
            fd["id"], [fixtures.line(disc["id"], 20, False)], target_protein=0,
            claim_tags=[],
        )
        fa = fixtures.create_formula(c1["id"], "FA", bar_weight_g=60,
                                     status="ARCHIVED")

        resp_lot = client.create_ingredient_lot(
            create_ingredient_lot_payload(
                ingredient_id=disc["id"], supplier_id=prov["id"], lot_code="D-1",
                received_qty_kg=10,
            ),
            ADMIN,
        )
        validate_error(resp_lot, ApiErrorId.ERR_SUPPLIER_NOT_QUALIFIED, 422)

        validate_error(
            client.submit_revision(rd["id"], SCI),
            ApiErrorId.ERR_INGREDIENT_DISCONTINUED, 422,
        )

        resp_formula = client.create_formula(
            {"customer_id": c2["id"], "name": "FX", "bar_weight_g": 50}, SCI
        )
        validate_error(resp_formula, ApiErrorId.ERR_CUSTOMER_SUSPENDED, 422)

        resp_revision = client.create_revision(
            fa["id"],
            create_revision_payload(
                ingredient_lines=[fixtures.line(disc["id"], 10, False)],
                batch_size_kg=50, target_protein_g_per_serving=0, claim_tags=[],
            ),
            SCI,
        )
        validate_error(resp_revision, ApiErrorId.ERR_FORMULA_ARCHIVED, 422)
