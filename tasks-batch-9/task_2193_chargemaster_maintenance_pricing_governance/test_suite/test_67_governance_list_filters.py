"""Every governance collection: AND-combined filters, filtered total_count, and the offset window."""
from test_helpers import (
    api_client, validate_paginated,
    setup_base, create_department, create_item, reprice_item, create_change_request,
    decide_change_request, create_cycle, create_entry, create_batch,
    build_transparency_file, read_facility, set_clock,
    make_manager_headers, ADMIN, ANALYST, APPROVER, COMPLIANCE, MANAGER2_USER_ID,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-LISTS",
        "rounding_mode": "NEAREST_CENT", "aggregate_markup_limit_bp": 40000,
    },
    revenue_code_overrides={
        "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
        "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
        "pricing_class": "PROCEDURE", "status": "ACTIVE",
    },
    department_overrides={"name": "Cardiac Cath Lab", "cost_center_code": "CC-100",
                         "allowed_revenue_code_values": []},
    price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z"},
)


def test_each_collection_reports_the_filtered_population_and_an_empty_filter_is_still_a_page():
    """PRD §3.5: "Requests are discoverable by filter on `department_id`, `charge_item_id`,
    `proposed_revenue_code_id`, `status` and `request_type`"
    PRD §2.3: "`total_count` is the number of records matching the filters before pagination is applied,
    and `has_more` is true when records remain beyond the current window."
    PRD §3.7: "Cycles are discoverable by filter on `facility_id`, `code_set`, `cycle_year` and `status`."
    PRD §3.7: "Entries are discoverable by filter on `cycle_id`, `target_charge_item_id`,
    `new_revenue_code_id`, `prior_revenue_code_id`, `status` and `action` — and because entries are
    mutated by cascade rather than by direct client action, that filtered listing is their only discovery
    channel."
    PRD §3.9: "Captured lines are filterable by `batch_id`, `charge_item_id`, `encounter_id` and
    `match_status`; findings are filterable by `batch_id`, `department_id`,
    `trigger_captured_charge_id`, `expected_charge_item_id`, `recovery_captured_charge_id` and `status`.
    Batches themselves are filterable by `facility_id`, `department_id` and `status`, and departments by
    `facility_id` and `capture_hold`."
    PRD §3.10: "Files are discoverable by filter on `facility_id`, `superseded_by_file_id` and `status`."

    Design: Corner/endpoints/every_governance_list_endpoint_filters_by_scope_status_and_pagination_window
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    facility_id = base["facility"]["id"]
    department_id = base["department"]["id"]
    radiology = create_department(facility_id, MANAGER2_USER_ID, name="Radiology",
                                  cost_center_code="CC-200")
    manager2 = make_manager_headers(MANAGER2_USER_ID)

    item = create_item(base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
                       code_type="CPT", code_value="93458", cost_basis_cents=100000,
                       medicare_rate_cents=50000, market_p75_cents=900000,
                       effective_from="2026-09-01T00:00:00Z")
    assert reprice_item(item["id"])["gross_charge_cents"] == 240000

    first = create_change_request(base, item["id"], "PRICE_CHANGE",
                                  justification="First cost basis revision request",
                                  proposed_cost_basis_cents=150000)
    withdrawn = create_change_request(base, item["id"], "PRICE_CHANGE",
                                      justification="Second cost basis revision request",
                                      proposed_cost_basis_cents=160000)
    gone = decide_change_request(withdrawn["id"], "WITHDRAW", base["manager_headers"],
                                decision_note="Superseded by a later request")
    assert gone["status"] == "WITHDRAWN"
    third = create_change_request(base, item["id"], "PRICE_CHANGE",
                                  justification="Third cost basis revision request",
                                  proposed_cost_basis_cents=170000)

    cycle = create_cycle(facility_id, cycle_year=2027, code_set="CPT")
    assert cycle["status"] == "LOADED"
    added = create_entry(cycle["id"], "ADD", old_code_value=None, new_code_value="0001U")
    deleted = create_entry(cycle["id"], "DELETE", old_code_value="93458", new_code_value=None)

    batch_one = create_batch(base, window_start_date="2026-09-01T00:00:00Z",
                             window_end_date="2026-09-07T23:59:59Z")
    batch_two = create_batch(base, headers=manager2, department_id=radiology["id"],
                             window_start_date="2026-09-01T00:00:00Z",
                             window_end_date="2026-09-07T23:59:59Z")
    assert batch_one["status"] == "INGESTED" and batch_two["status"] == "INGESTED"

    file_one = build_transparency_file(facility_id, read_facility(facility_id)["version"],
                                       file_format="CSV")
    assert file_one["status"] == "BUILDING"

    submitted, submitted_meta = validate_paginated(api_client.list_change_requests(
        APPROVER, {"charge_item_id": item["id"], "status": "SUBMITTED"}))
    assert submitted_meta["total_count"] == 2
    assert {row["id"] for row in submitted} == {first["id"], third["id"]}
    assert withdrawn["id"] not in {row["id"] for row in submitted}

    page_one, page_one_meta = validate_paginated(api_client.list_change_requests(
        COMPLIANCE, {"department_id": department_id, "limit": 2, "offset": 0}))
    assert page_one_meta["total_count"] == 3
    assert page_one_meta["has_more"] is True
    assert len(page_one) == 2

    page_two, page_two_meta = validate_paginated(api_client.list_change_requests(
        COMPLIANCE, {"department_id": department_id, "limit": 2, "offset": 2}))
    assert page_two_meta["total_count"] == 3
    assert page_two_meta["has_more"] is False
    assert len(page_two) == 1
    assert {row["id"] for row in page_one} | {row["id"] for row in page_two} == {
        first["id"], withdrawn["id"], third["id"]}

    empty, empty_meta = validate_paginated(api_client.list_change_requests(
        ADMIN, {"charge_item_id": item["id"], "status": "IMPLEMENTED"}))
    assert empty == []
    assert empty_meta["total_count"] == 0
    assert empty_meta["has_more"] is False

    cycles, cycles_meta = validate_paginated(api_client.list_code_update_cycles(
        ANALYST, {"facility_id": facility_id, "status": "LOADED", "code_set": "CPT",
                  "cycle_year": 2027}))
    assert cycles_meta["total_count"] == 1, "all four filters are ANDed"
    assert cycles[0]["id"] == cycle["id"]

    entries, entries_meta = validate_paginated(api_client.list_code_update_entries(
        COMPLIANCE, {"cycle_id": cycle["id"], "status": "PENDING", "limit": 100}))
    assert entries_meta["total_count"] == 2
    assert {row["id"] for row in entries} == {added["id"], deleted["id"]}

    deletes, deletes_meta = validate_paginated(api_client.list_code_update_entries(
        ANALYST, {"cycle_id": cycle["id"], "action": "DELETE"}))
    assert deletes_meta["total_count"] == 1
    assert deletes[0]["id"] == deleted["id"]

    batches, batches_meta = validate_paginated(api_client.list_charge_capture_batches(
        ANALYST, {"facility_id": facility_id, "status": "INGESTED"}))
    assert batches_meta["total_count"] == 2
    assert {row["id"] for row in batches} == {batch_one["id"], batch_two["id"]}

    scoped, scoped_meta = validate_paginated(api_client.list_charge_capture_batches(
        manager2, {"facility_id": facility_id, "department_id": radiology["id"]}))
    assert scoped_meta["total_count"] == 1
    assert scoped[0]["id"] == batch_two["id"]

    files, files_meta = validate_paginated(api_client.list_transparency_files(
        COMPLIANCE, {"facility_id": facility_id, "status": "BUILDING"}))
    assert files_meta["total_count"] == 1
    assert files[0]["id"] == file_one["id"]

    lines, lines_meta = validate_paginated(api_client.list_captured_charges(
        ANALYST, {"batch_id": batch_one["id"]}))
    assert lines == []
    assert lines_meta["total_count"] == 0, "no line was ever appended"

    findings, findings_meta = validate_paginated(api_client.list_missing_charge_findings(
        ANALYST, {"department_id": department_id, "status": "OPEN"}))
    assert findings == []
    assert findings_meta["total_count"] == 0
    for meta in (submitted_meta, page_one_meta, cycles_meta, entries_meta, batches_meta,
                 files_meta, lines_meta, findings_meta):
        assert set(["limit", "offset", "total_count", "has_more"]) <= set(meta)
