"""Verification guards, clinical review loop, interventions (PRD §3.3)."""
from test_helpers import (
    assert_clinical_intervention,
    create_drug,
    create_intervention,
    create_patient,
    fixtures,
    get_patient,
    place_order,
    setup_batch,
    setup_verified_order,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestVerifyAllergyConflict:
    def test_verify_rejects_drug_on_allergy_list(self, api):
        """PRD §3.3: "Three preconditions guard it, surfacing in this order relative to the global priority tiers: the order must still be `PENDING` (a from-state failure yields `ERR_INVALID_STATE`); the ordered drug must not appear in the patient's `allergy_drug_product_ids` (an allergy hit is rejected with `ERR_ALLERGY_CONFLICT`); and the ordered drug's formulary `status` must be `ACTIVE` (a discontinued drug yields `ERR_DRUG_DISCONTINUED`)."

        Design: Corner/validations/verify_allergy_conflict_violation
        """
        prescriber, _ = fixtures.make_prescriber()
        pharmacist, pharmacist_headers = fixtures.make_pharmacist()
        drug = create_drug()
        patient = create_patient(allergy_drug_product_ids=[drug["id"]])
        order = place_order(patient, drug, prescriber, route="PO",
                            ordered_dose_mg=100.0)
        resp = api.verify_order(order["id"], {}, pharmacist_headers)
        validate_error(resp, "ERR_ALLERGY_CONFLICT", 422)
        current = fixtures.get_patient(patient["id"])  # sanity: patient reachable
        assert current["id"] == patient["id"]
        fetched = validate_success(
            api.get_medication_order(order["id"], pharmacist_headers), 200
        )
        assert fetched["verification_status"] == "PENDING"


class TestVerifyPriorityStateBeatsAllergy:
    def _setup_verified_then_allergic(self, api, admin_headers):
        prescriber, _ = fixtures.make_prescriber()
        pharmacist, pharmacist_headers = fixtures.make_pharmacist()
        patient = create_patient()
        drug = create_drug()
        order = place_order(patient, drug, prescriber, route="PO",
                            ordered_dose_mg=100.0)
        order = fixtures.verify_order(order["id"], pharmacist)
        get_success = validate_success(
            api.update_patient(
                patient["id"],
                {"allergy_drug_product_ids": [drug["id"]]},
                admin_headers,
            ),
            200,
        )
        assert drug["id"] in get_success["allergy_drug_product_ids"]
        return order, pharmacist_headers

    def test_verify_on_verified_order_with_allergy_reports_state_error(self, api, admin_headers):
        """PRD §2.7: "When several checks could fail on the same request, the system reports failures in a fixed priority order so that callers see the most fundamental problem first."
        PRD §2.7: "then the state-machine from-state check (`ERR_INVALID_STATE`); then business-safety rules (allergy screen, hazardous-drug certification, hood rating, waste witnessing, segregation of duties, prescriber ownership)"

        Design: Difficulty/priority_pair_validation_conflict/verify_state_beats_allergy_safety
        """
        order, pharmacist_headers = self._setup_verified_then_allergic(api, admin_headers)
        resp = api.verify_order(order["id"], {}, pharmacist_headers)
        # Both a from-state failure (not PENDING) and an allergy hit are live;
        # the state tier surfaces first.
        validate_error(resp, "ERR_INVALID_STATE", 409)

    def test_rejected_reverify_leaves_order_verified(self, api, admin_headers):
        """PRD §3.3: "Verification is a `Pharmacist` action on a `PENDING` order, optionally guarded by `expected_order_version`."

        Design: Difficulty/priority_pair_validation_conflict/verify_state_beats_allergy_safety
        """
        order, pharmacist_headers = self._setup_verified_then_allergic(api, admin_headers)
        api.verify_order(order["id"], {}, pharmacist_headers)
        fetched = validate_success(
            api.get_medication_order(order["id"], pharmacist_headers), 200
        )
        assert fetched["verification_status"] == "VERIFIED"


class TestParallelOrderDimensions:
    def _setup_compounding_order_on_hold(self, api):
        ns = setup_verified_order(route="IV", ordered_dose_mg=100.0)
        batch_ns = setup_batch([ns.order["id"]], start_session=True)
        create_intervention(
            ns.order["id"], ns.pharmacist,
            intervention_type="DOSE_CLARIFICATION", note="rechecking dose",
            placed_on_hold=True,
        )
        return ns, batch_ns

    def test_hold_moves_verification_but_not_fulfillment(self, api, admin_headers):
        """PRD §3.3: "When `placed_on_hold` is true and the order is currently `PENDING` or `VERIFIED`, the order's `verification_status` moves to `ON_HOLD`."

        Design: Difficulty/non_linear_state_machine/order_parallel_dimensions
        """
        ns, _ = self._setup_compounding_order_on_hold(api)
        fetched = validate_success(
            api.get_medication_order(ns.order["id"], admin_headers), 200
        )
        assert fetched["verification_status"] == "ON_HOLD"
        assert fetched["fulfillment_status"] == "COMPOUNDING"

    def test_resume_restores_verification_without_resetting_fulfillment(self, api, admin_headers):
        """PRD §3.3: "Resuming is the reverse `Pharmacist` action on an `ON_HOLD` order, again optionally guarded by `expected_order_version`: the allergy screen re-runs (an allergy now present yields `ERR_ALLERGY_CONFLICT`), the renal adjustment and final dose are recomputed because the patient panel may have changed, fulfillment moves from `NONE` to `QUEUED` for IV or `READY` for non-IV when it was still `NONE`, and the order returns to `VERIFIED` with its `version` incremented."

        Design: Difficulty/non_linear_state_machine/order_parallel_dimensions
        """
        ns, _ = self._setup_compounding_order_on_hold(api)
        resumed = validate_success(
            api.resume_order(ns.order["id"], {}, ns.pharmacist_headers), 200
        )
        assert resumed["verification_status"] == "VERIFIED"
        assert resumed["fulfillment_status"] == "COMPOUNDING"
        rows, meta = validate_paginated(
            api.list_order_interventions(ns.order["id"], admin_headers)
        )
        assert len(rows) == 1
        assert rows[0]["intervention_type"] == "DOSE_CLARIFICATION"


class TestInterventionAppendOnly:
    def test_intervention_carries_only_id_and_created_at_of_common_fields(self, api, pharmacist_headers):
        """PRD §2.4: "Two resource families are deliberately leaner: a `ClinicalIntervention`, an `InventoryEvent`, and a `WasteRecord` each carry only `id` and `created_at` — they are append-only records, and both `updated_at` and `version` are absent from them."

        Design: Corner/entities/intervention_append_only_immutability
        """
        ns = setup_verified_order(route="PO", ordered_dose_mg=100.0)
        row = create_intervention(ns.order["id"], ns.pharmacist,
                                  intervention_type="OTHER", note="note",
                                  placed_on_hold=False)
        assert_clinical_intervention(row)
        fetched = validate_success(api.get_intervention(row["id"], pharmacist_headers), 200)
        assert fetched["pharmacist_staff_id"] == ns.pharmacist["id"]
        assert fetched["placed_on_hold"] is False


class TestVerifyDiscontinuedDrug:
    def test_verify_rejects_order_whose_drug_is_discontinued(self, api, admin_headers, pharmacist_headers):
        """PRD §3.3: "Three preconditions guard it, surfacing in this order relative to the global priority tiers: the order must still be `PENDING` (a from-state failure yields `ERR_INVALID_STATE`); the ordered drug must not appear in the patient's `allergy_drug_product_ids` (an allergy hit is rejected with `ERR_ALLERGY_CONFLICT`); and the ordered drug's formulary `status` must be `ACTIVE` (a discontinued drug yields `ERR_DRUG_DISCONTINUED`)."

        Design: Corner/errors/error_drug_discontinued_on_verify
        """
        prescriber, _ = fixtures.make_prescriber()
        fixtures.make_pharmacist()
        patient = create_patient()
        drug = create_drug()
        order = place_order(patient, drug, prescriber, route="PO",
                            ordered_dose_mg=100.0)
        validate_success(
            api.update_drug_product(drug["id"], {"status": "DISCONTINUED"}, admin_headers),
            200,
        )
        resp = api.verify_order(order["id"], {}, pharmacist_headers)
        validate_error(resp, "ERR_DRUG_DISCONTINUED", 422)
        fetched = validate_success(
            api.get_medication_order(order["id"], pharmacist_headers), 200
        )
        assert fetched["verification_status"] == "PENDING"
