"""Order creation: schema, supersede side effect, patient OCC (PRD §2.5, §3.3)."""
from test_helpers import (
    create_drug,
    create_patient,
    fixtures,
    get_patient,
    place_order,
    validate_error,
    validate_success,
)


class TestOrderCreateSchema:
    def test_missing_drug_product_id_rejected(self, api, admin_headers):
        """PRD §3.3: "A `Prescriber` creates a medication order by naming the `patient_id`, the `drug_product_id`, the administration `route` (`IV`, `PO`, or `IM`), the `ordered_dose_mg` per administration, the `frequency_per_day`, optionally the `duration_days` (defaulting to 1), and the OCC field `expected_patient_version` (§2.5)."
        PRD §2.7: "then request-body well-formedness — required fields present, types valid, enum values in range (`ERR_INVALID_REQUEST`)"

        Design: Corner/entities/order_create_missing_required_field_returns_400
        """
        prescriber, prescriber_headers = fixtures.make_prescriber()
        patient = create_patient()
        resp = api.create_medication_order(
            {
                "patient_id": patient["id"],
                "route": "PO",
                "ordered_dose_mg": 100.0,
                "frequency_per_day": 1,
                "expected_patient_version": patient["version"],
            },
            prescriber_headers,
        )
        validate_error(resp, "ERR_INVALID_REQUEST", 400)


class TestSupersedeOnRecreate:
    def _setup_verified_then_recreate(self, api):
        prescriber, _ = fixtures.make_prescriber()
        pharmacist, _ = fixtures.make_pharmacist()
        patient = create_patient()
        drug = create_drug()
        order1 = place_order(patient, drug, prescriber, route="PO",
                             ordered_dose_mg=100.0)
        order1 = fixtures.verify_order(order1["id"], pharmacist)
        order2 = place_order(patient, drug, prescriber, route="PO",
                             ordered_dose_mg=150.0)
        return patient, order1, order2

    def test_second_create_supersedes_prior_open_order(self, api, admin_headers):
        """PRD §3.3: "Order creation carries an implicit replacement rule: when the same prescriber creates an order for a patient and drug that already has an open order — one whose `verification_status` is `PENDING`, `VERIFIED`, or `ON_HOLD` and whose `fulfillment_status` is neither `DISPENSED` nor `ADMINISTERED` — the prior order is superseded: its `verification_status` becomes `SUPERSEDED`, its `version` increments, and the same three-level cancellation cascade described for discontinuation below runs against its preparations, batches, and hood sessions."

        Design: Corner/state_machines/order_supersede_cascade_via_new_order
        """
        _, order1, order2 = self._setup_verified_then_recreate(api)
        old = validate_success(
            api.get_medication_order(order1["id"], admin_headers), 200
        )
        assert old["verification_status"] == "SUPERSEDED"
        assert order2["verification_status"] == "PENDING"
        assert order2["ordered_dose_mg"] == 150.0

    def test_each_successful_create_increments_patient_version(self, api):
        """PRD §3.3: "This supersede is why order creation is OCC-guarded on the patient: a successful create also increments the patient's `version` by 1, so a client holding a pre-supersede patient version is necessarily acting on a stale view."

        Design: Corner/state_machines/order_supersede_cascade_via_new_order
        """
        patient, _, _ = self._setup_verified_then_recreate(api)
        assert get_patient(patient["id"])["version"] == patient["version"] + 2


class TestOrderCreateOcc:
    def test_stale_expected_patient_version_rejected(self, api):
        """PRD §2.5: "Creating a medication order requires the request to carry `expected_patient_version`, the `version` of the target `PatientProfile` as the client last observed it. If the patient's current `version` has advanced since that observation — for example because another order creation against the same patient superseded a prior open order and bumped the patient's version — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from writing against a patient record it has not observed."

        Design: Corner/cross_cutting_layers/occ_order_create_stale_patient_version
        """
        prescriber, prescriber_headers = fixtures.make_prescriber()
        patient = create_patient()
        drug_a = create_drug(name="DrugOCCA")
        drug_b = create_drug(name="DrugOCCB")
        initial_version = patient["version"]
        place_order(patient, drug_a, prescriber, route="PO", ordered_dose_mg=100.0)
        resp = api.create_medication_order(
            {
                "patient_id": patient["id"],
                "drug_product_id": drug_b["id"],
                "route": "PO",
                "ordered_dose_mg": 50.0,
                "frequency_per_day": 1,
                "expected_patient_version": initial_version,
            },
            prescriber_headers,
        )
        validate_error(resp, "ERR_STALE_VERSION", 412)

    def test_retry_with_fresh_patient_version_succeeds(self, api, admin_headers):
        """PRD §2.5: "A successful create itself increments the patient's `version` by 1."

        Design: Corner/cross_cutting_layers/occ_order_create_stale_patient_version
        """
        prescriber, prescriber_headers = fixtures.make_prescriber()
        patient = create_patient()
        drug_a = create_drug(name="DrugOCCA")
        drug_b = create_drug(name="DrugOCCB")
        place_order(patient, drug_a, prescriber, route="PO", ordered_dose_mg=100.0)
        fresh_version = get_patient(patient["id"])["version"]
        assert fresh_version == patient["version"] + 1
        order2 = validate_success(
            api.create_medication_order(
                {
                    "patient_id": patient["id"],
                    "drug_product_id": drug_b["id"],
                    "route": "PO",
                    "ordered_dose_mg": 50.0,
                    "frequency_per_day": 1,
                    "expected_patient_version": fresh_version,
                },
                prescriber_headers,
            ),
            201,
        )
        assert order2["verification_status"] == "PENDING"
