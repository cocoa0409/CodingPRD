"""Production-run creation gates: MOQ boundary, cascade ordering, gluten-free
segregation, referential state, and agreement OCC (PRD §2.5, §2.6, §2.7, §3.6)."""
from test_helpers import (
    ApiErrorId,
    create_run_payload,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers import api_client as client
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["plant_admin_headers"]
SCI = TEST_USERS["formulation_scientist_headers"]
QM = TEST_USERS["quality_manager_headers"]
PP = TEST_USERS["production_planner_headers"]


class TestMoqInclusiveBoundary:
    def test_planned_cases_equal_to_moq_is_accepted(self, api):
        """PRD §3.3: "a `moq_cases_per_run` floor on every run's planned
        output, greater than zero and inclusive at the boundary so a run
        planning exactly the minimum passes"
        PRD §3.6: "then `planned_cases` must meet the agreement's
        `moq_cases_per_run`, the boundary inclusive (`ERR_MOQ_SHORTFALL`,
        HTTP 422)"

        Design: Difficulty/boundary_precision_check/moq_inclusive_boundary
        """
        plant = fixtures.setup_basic_plant(moq=100)
        run = fixtures.create_run(plant.r1["id"], plant.ag["id"],
                                  plant.ln1["id"], 100)
        assert run["status"] == "PLANNED"

    def test_planned_cases_one_below_moq_is_rejected(self, api):
        """PRD §3.6: "then `planned_cases` must meet the agreement's
        `moq_cases_per_run`, the boundary inclusive (`ERR_MOQ_SHORTFALL`,
        HTTP 422)"

        Design: Difficulty/boundary_precision_check/moq_inclusive_boundary
        """
        plant = fixtures.setup_basic_plant(moq=100)
        payload = create_run_payload(
            revision_id=plant.r1["id"], agreement_id=plant.ag["id"],
            line_id=plant.ln1["id"], planned_cases=99,
            expected_agreement_version=fixtures.get_agreement_version(plant.ag["id"]),
        )
        resp = client.create_production_run(payload, PP)
        validate_error(resp, ApiErrorId.ERR_MOQ_SHORTFALL, 422)


class TestExistenceBeatsState:
    def test_approve_missing_revision_returns_not_found(self, api):
        """PRD §2.6: "Every request is validated against a fixed cascade, and
        an earlier failure masks every later check."
        PRD §2.6: "4. **Path existence** — every identifier in the URL path
        must resolve, validated left to right (see §2.10), each missing
        resource producing its own 404."

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_missing_revision
        """
        resp = client.approve_revision(
            "11111111-2222-3333-4444-555555555555", QM
        )
        validate_error(resp, ApiErrorId.ERR_REVISION_NOT_FOUND, 404)

    def test_approve_draft_revision_returns_invalid_state(self, api):
        """PRD §2.6: "9. **State-machine legality** — the resource's own state
        machine must permit the requested transition from its current state,
        else `ERR_INVALID_STATE` (409)."
        PRD §3.4: "Approval moves the revision from `CLAIM_REVIEW` to
        `APPROVED`"

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_missing_revision
        """
        ns = fixtures.setup_formula_with_revision()
        resp = client.approve_revision(ns.r1["id"], QM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestGlutenFreeSegregationGate:
    def test_segregation_violation_reported_over_moq_shortfall(self, api):
        """PRD §3.6: "Run creation evaluates its gates in a fixed order: first
        the gluten-free segregation rule of §2.7
        (`ERR_ALLERGEN_SEGREGATION_VIOLATION`); then the referenced revision
        must stand in `APPROVED` (`ERR_REVISION_NOT_APPROVED`, HTTP 422); then
        the referenced agreement must be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`,
        HTTP 422); then the agreement's customer must be `ACTIVE`
        (`ERR_CUSTOMER_SUSPENDED`); then `planned_cases` must meet the
        agreement's `moq_cases_per_run`, the boundary inclusive
        (`ERR_MOQ_SHORTFALL`, HTTP 422); and finally the stale-version check
        of §2.5 (`ERR_STALE_VERSION`, HTTP 412)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_gluten_free_moq
        """
        ns = fixtures.setup_gluten_free_line_scenario()
        payload = create_run_payload(
            revision_id=ns.rgf["id"], agreement_id=ns.ag["id"],
            line_id=ns.lw["id"], planned_cases=50,
            expected_agreement_version=fixtures.get_agreement_version(ns.ag["id"]),
        )
        resp = client.create_production_run(payload, PP)
        # planned_cases 50 < MOQ 100, yet the segregation gate fires first.
        validate_error(resp, ApiErrorId.ERR_ALLERGEN_SEGREGATION_VIOLATION, 422)

    def test_segregation_violation_fires_even_when_moq_is_met(self, api):
        """PRD §2.7: "A gluten-free segregation rule guards the line itself: a
        revision claiming `GLUTEN_FREE` may not be planned on a line whose
        `current_allergen_profile` contains `WHEAT` — the attempt is rejected
        at run creation with `ERR_ALLERGEN_SEGREGATION_VIOLATION` (HTTP 422)."
        PRD §3.5: "`GLUTEN_FREE` is substantiated when `WHEAT` does not appear
        in the revision's `allergen_profile`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_gluten_free_moq
        """
        ns = fixtures.setup_gluten_free_line_scenario()
        # Control: the GLUTEN_FREE claim was substantiated (profile has no WHEAT).
        assert ns.gf_review["substantiation_ok"] is True
        payload = create_run_payload(
            revision_id=ns.rgf["id"], agreement_id=ns.ag["id"],
            line_id=ns.lw["id"], planned_cases=100,
            expected_agreement_version=fixtures.get_agreement_version(ns.ag["id"]),
        )
        resp = client.create_production_run(payload, PP)
        validate_error(resp, ApiErrorId.ERR_ALLERGEN_SEGREGATION_VIOLATION, 422)


class TestRunCreateReferentialGates:
    def test_revision_then_agreement_state_gates(self, api):
        """PRD §3.6: "Run creation evaluates its gates in a fixed order: first
        the gluten-free segregation rule of §2.7
        (`ERR_ALLERGEN_SEGREGATION_VIOLATION`); then the referenced revision
        must stand in `APPROVED` (`ERR_REVISION_NOT_APPROVED`, HTTP 422); then
        the referenced agreement must be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`,
        HTTP 422); then the agreement's customer must be `ACTIVE`
        (`ERR_CUSTOMER_SUSPENDED`); then `planned_cases` must meet the
        agreement's `moq_cases_per_run`, the boundary inclusive
        (`ERR_MOQ_SHORTFALL`, HTTP 422); and finally the stale-version check
        of §2.5 (`ERR_STALE_VERSION`, HTTP 412)."

        Design: Corner/validations/c_run_create_referential_gates
        """
        sup = fixtures.create_supplier("S1", "APPROVED")
        whey = fixtures.create_ingredient(
            "WHEY", "PROTEIN", ["MILK"], nominal_protein_pct=0.8
        )
        fixtures.receive_and_release_lot(whey["id"], sup["id"], "WL-1", 100,
                                         coa_protein_pct=0.8)
        cust = fixtures.create_customer("C1")
        agreement = fixtures.create_agreement(cust["id"])  # stays NEGOTIATION
        f1 = fixtures.create_formula(cust["id"], "F1", bar_weight_g=60)
        r1 = fixtures.create_revision(
            f1["id"], [fixtures.line(whey["id"], 40, True)],
            target_protein=15, claim_tags=[],
        )
        ln1 = fixtures.create_line("L1")

        def _create():
            return client.create_production_run(
                create_run_payload(
                    revision_id=r1["id"], agreement_id=agreement["id"],
                    line_id=ln1["id"], planned_cases=100,
                    expected_agreement_version=agreement["version"],
                ),
                PP,
            )

        # Revision still DRAFT: the revision gate fires first.
        validate_error(_create(), ApiErrorId.ERR_REVISION_NOT_APPROVED, 422)
        # Revision APPROVED but agreement still NEGOTIATION.
        fixtures.march_revision_to_approved(r1["id"])
        validate_error(_create(), ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE, 422)


class TestAgreementOptimisticConcurrency:
    def test_stale_agreement_version_rejected_on_run_create(self, api):
        """PRD §2.5: "Creating a production run requires the request to carry
        `expected_agreement_version`, the client-observed `version` of the
        target agreement. Because every successful run creation debits the
        agreement's committed-volume ledger and increments the agreement's
        `version` by one, a client holding an older observed version is acting
        on a stale agreement state; if `expected_agreement_version` does not
        match the agreement's current `version`, the creation is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/c_occ_stale_agreement_on_run_create
        """
        plant = fixtures.setup_basic_plant(whey_qty=300)
        observed_version = plant.ag["version"]
        first = client.create_production_run(
            create_run_payload(
                revision_id=plant.r1["id"], agreement_id=plant.ag["id"],
                line_id=plant.ln1["id"], planned_cases=100,
                expected_agreement_version=observed_version,
            ),
            PP,
        )
        validate_success(first, 201)
        # The first creation advanced the agreement's version; replaying the
        # previously observed version is stale.
        second = client.create_production_run(
            create_run_payload(
                revision_id=plant.r1["id"], agreement_id=plant.ag["id"],
                line_id=plant.ln1["id"], planned_cases=100,
                expected_agreement_version=observed_version,
            ),
            PP,
        )
        validate_error(second, ApiErrorId.ERR_STALE_VERSION, 412)
