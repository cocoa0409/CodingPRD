"""List pagination defaults and downward FK sub-resource listings (PRD §2.3, §3)."""
from test_helpers import (
    count_payload,
    create_drug,
    create_intervention,
    create_patient,
    fixtures,
    place_order,
    restock_payload,
    setup_batch,
    validate_paginated,
    validate_success,
)


class TestListPaginationDefaults:
    def test_default_limit_10_and_has_more(self, api, pharmacist_headers):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0."
        PRD §2.3: "List responses carry four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_pagination_defaults_and_has_more
        """
        prescriber, _ = fixtures.make_prescriber()
        drug = create_drug()
        for i in range(12):
            patient = create_patient(full_name=f"Pat PG{i + 1}")
            place_order(patient, drug, prescriber, route="PO",
                        ordered_dose_mg=100.0)
        resp = api.list_medication_orders(pharmacist_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["response_type"] == "array"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        page1, meta1 = validate_paginated(resp)
        assert len(page1) == 10
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_medication_orders(pharmacist_headers, params={"offset": 10})
        )
        assert len(page2) == 2
        assert meta2["offset"] == 10
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False


class TestReverseFkSubresourceListings:
    def test_parent_to_child_listings_reachable(self, api, pharmacist_headers):
        """PRD §3.5: "Preparations are listable per batch and across the pharmacy with `batch_id`, `order_id`, `drug_product_id`, and `status` filters; batches are listable with `status`, `compounder_staff_id`, `qa_pharmacist_staff_id`, and `hood_session_id` filters; the waste records of a batch are listable from the batch."
        PRD §3.6: "Ledger events are listable per pocket and globally with `order_id`, `recorded_by_staff_id`, `witness_staff_id`, and `event_type` filters."
        PRD §3.7: "Discrepancy cases are listable with `pocket_id`, `status`, and `resolved_by_staff_id` filters."
        PRD §3.3: "Every call appends an immutable `ClinicalIntervention` row stamped with the documenting pharmacist's `id` as `pharmacist_staff_id`; the row is a 201-created resource, listable per order and across the pharmacy with a `pharmacist_staff_id` filter."

        Design: Corner/endpoints/fk_reverse_reachability_filtered_lists
        """
        prescriber, _ = fixtures.make_prescriber()
        pharmacist, _ = fixtures.make_pharmacist()
        nurse, _ = fixtures.make_nurse()
        patient = create_patient()
        drug = create_drug(schedule="C_II")
        order = place_order(patient, drug, prescriber, route="IV",
                            ordered_dose_mg=100.0)
        order = fixtures.verify_order(order["id"], pharmacist)
        create_intervention(order["id"], pharmacist, intervention_type="RENAL",
                            note="check", placed_on_hold=False)
        batch_ns = setup_batch([order["id"]], start_session=False)
        inv = fixtures.setup_station_with_pocket(drug=drug, restock_units=10)
        count = fixtures.count_pocket(inv.pocket["id"], 8, pharmacist)
        assert count["discrepancy_case_id"] is not None  # C_II: |−2| >= 2

        preps, meta = validate_paginated(
            api.list_batch_preparations(batch_ns.batch["id"], pharmacist_headers)
        )
        assert meta["total_count"] == 1
        assert preps[0]["status"] == "PLANNED"
        assert preps[0]["batch_id"] == batch_ns.batch["id"]
        assert preps[0]["order_id"] == order["id"]

        events, meta = validate_paginated(
            api.list_pocket_events(inv.pocket["id"], pharmacist_headers)
        )
        assert meta["total_count"] == 2
        count_events = [e for e in events if e["event_type"] == "COUNT"]
        assert len(count_events) == 1
        assert count_events[0]["observed_count_units"] == 8
        assert count_events[0]["expected_on_hand_after"] == 10

        cases, meta = validate_paginated(
            api.list_pocket_discrepancy_cases(inv.pocket["id"], pharmacist_headers)
        )
        assert meta["total_count"] == 1
        assert cases[0]["variance_units"] == -2
        assert cases[0]["status"] == "OPEN"

        interventions, meta = validate_paginated(
            api.list_order_interventions(order["id"], pharmacist_headers)
        )
        assert meta["total_count"] == 1
        assert interventions[0]["intervention_type"] == "RENAL"
