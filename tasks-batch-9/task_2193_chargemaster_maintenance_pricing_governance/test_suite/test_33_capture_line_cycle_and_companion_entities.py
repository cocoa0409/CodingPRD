"""The append-only capture line, code-cycle defaults and the facility-scoped companion link."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, factories, ApiErrorId,
    setup_base, create_facility, create_department, create_item, create_batch, append_line,
    create_cycle, create_entry, read_cycle, set_clock,
    assert_captured_charge, assert_code_update_cycle, assert_code_update_entry,
    ANALYST,
)


def _setup():
    set_clock("2026-09-01T00:00:00Z")
    return setup_base(
        facility_overrides={
            "name": "Mercy General", "cms_certification_number": "CCN-2193-MERCY",
            "rounding_mode": "NEAREST_CENT",
        },
        revenue_code_overrides={
            "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
            "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
            "pricing_class": "PROCEDURE", "status": "ACTIVE",
        },
        department_overrides={"name": "Cardiac Cath Lab", "cost_center_code": "CC-4100"},
    )


def test_a_capture_line_carries_no_version_and_no_updated_at():
    """PRD §2.4: "Two entities are deliberately narrower. `RevenueCode` is national reference data
    and `CapturedCharge` is an append-only capture line; both carry only `id` and `created_at`.
    Neither has an `updated_at` field and neither has a `version` field — those two keys are absent
    from their representations entirely, and no client may pass a version expectation for them."
    PRD §3.9: "A line is created with `match_status` of `UNRECONCILED`, `charge_item_id` null,
    `expected_charge_cents` null and `line_variance_bp` null; the batch's `line_count` and
    `total_posted_charge_cents` are recomputed and `ChargeCaptureBatch.version` advances by 1."
    PRD §3.9: "Lines carry only `id` and `created_at` — no `updated_at`, no `version`."

    Design: Corner/entities/captured_charge_is_immutable_append_only_with_no_version_field
    """
    base = _setup()
    batch = create_batch(
        base,
        window_start_date="2026-09-01T00:00:00Z",
        window_end_date="2026-09-30T00:00:00Z",
    )
    assert batch["status"] == "INGESTED"
    created = append_line(
        batch["id"], "CDM-1001", base["manager_headers"],
        encounter_id="ENC-1", payer_code="BCBS_STATE",
        service_datetime="2026-09-01T00:00:00Z", quantity=1, posted_charge_cents=240000,
    )

    line = validate_success(api_client.get_captured_charge(created["id"], ANALYST), 200)
    assert_captured_charge(line)
    assert line["id"] == created["id"]
    assert line["created_at"].startswith("2026-09-01T00:00:00")
    assert "version" not in line, "a CapturedCharge has no version counter at all"
    assert "updated_at" not in line
    assert line["match_status"] == "UNRECONCILED"
    assert line["charge_item_id"] is None
    assert line["expected_charge_cents"] is None
    assert line["line_variance_bp"] is None


def test_a_cycle_and_its_first_entry_land_on_their_declared_defaults():
    """PRD §3.7: "A `RevenueIntegrityAnalyst` opens a `CodeUpdateCycle` against a `facility_id`
    with a `cycle_year`, a `code_set` of `CPT` or `HCPCS`, and an optional `cost_inflator_bp`
    defaulting to 10300 basis points — a three percent cost inflation applied when a crosswalk also
    moves the revenue code."
    PRD §3.7: "A new cycle sits in `LOADED` with `entry_count`, `unmapped_entry_count` and
    `applied_entry_count` at 0, `pre_activation_active_item_count` and
    `pre_activation_aggregate_gross_charge_cents` null, and `activated_at` and `rolled_back_at`
    null."
    PRD §3.7: "An entry is created in `PENDING`; the cycle's `entry_count` and
    `unmapped_entry_count` are recomputed and `CodeUpdateCycle.version` advances by 1."

    Design: Corner/entities/code_update_cycle_and_entry_defaults_loaded_pending_and_inflator
    """
    base = _setup()
    resp = api_client.create_code_update_cycle(
        {"facility_id": base["facility"]["id"], "cycle_year": 2027, "code_set": "CPT"}, ANALYST
    )
    cycle = validate_success(resp, 201)
    assert_code_update_cycle(cycle)
    assert cycle["status"] == "LOADED"
    assert cycle["cost_inflator_bp"] == 10300, "the declared default when omitted"
    assert cycle["entry_count"] == 0
    assert cycle["unmapped_entry_count"] == 0
    assert cycle["applied_entry_count"] == 0
    assert cycle["pre_activation_active_item_count"] is None
    assert cycle["pre_activation_aggregate_gross_charge_cents"] is None
    assert cycle["activated_at"] is None
    assert cycle["rolled_back_at"] is None

    entry = validate_success(
        api_client.create_code_update_entry(
            cycle["id"],
            {"action": "CROSSWALK", "old_code_value": "93458", "new_code_value": "93459"},
            ANALYST,
        ),
        201,
    )
    assert_code_update_entry(entry)
    assert entry["status"] == "PENDING"
    assert entry["target_charge_item_id"] is None
    assert entry["carried_gross_charge_cents"] is None
    assert entry["mapped_by_user_id"] is None
    assert entry["new_revenue_code_id"] is None, "left null when the revenue code is unchanged"

    reread = read_cycle(cycle["id"])
    assert reread["entry_count"] == 1
    assert reread["unmapped_entry_count"] == 1
    assert reread["applied_entry_count"] == 0


def test_a_companion_link_may_not_reach_across_facilities():
    """PRD §3.3: "A supplied `companion_required_item_id` must reference a *different* charge item
    in the *same* facility whose `lifecycle_status` is not `ARCHIVED`; pointing at the item itself,
    at another facility's item, or at an archived item is `ERR_COMPANION_ITEM_INVALID` (422)."
    PRD §2.9: "10. Body foreign keys resolve, checked left to right in this declaration order:
    `department_id`, then `revenue_code_id` or `proposed_revenue_code_id`, then `charge_item_id`,
    then `companion_required_item_id`, then `duplicate_of_item_id`, then
    `recovery_captured_charge_id` — `ERR_REFERENCED_RESOURCE_NOT_FOUND` (404)."

    Design: Corner/entities/companion_item_in_another_facility_cannot_be_linked_across_facilities
    """
    base_a = _setup()
    facility_b = create_facility(
        name="Northgate Regional", cms_certification_number="CCN-2193-NORTH",
        rounding_mode="NEAREST_CENT",
    )
    department_b = create_department(
        facility_b["id"], name="Radiology", cost_center_code="CC-B-320",
    )
    item_b = create_item(
        {"facility": facility_b, "department": department_b,
         "revenue_code": base_a["revenue_code"]},
        cdm_number="CDM-B001", description="COMPANION IN ANOTHER FACILITY",
        code_type="REV_ONLY", code_value=None, cost_basis_cents=4000,
        medicare_rate_cents=1000, market_p75_cents=90000,
        effective_from="2026-09-01T00:00:00Z",
    )

    resp = api_client.create_charge_item(
        factories.create_charge_item_payload(
            base_a["facility"]["id"], base_a["department"]["id"], base_a["revenue_code"]["id"],
            cdm_number="CDM-A001", description="TRIGGER LINE", code_type="REV_ONLY",
            code_value=None, cost_basis_cents=4000, medicare_rate_cents=1000,
            market_p75_cents=90000, effective_from="2026-09-01T00:00:00Z",
            companion_required_item_id=item_b["id"], companion_window_hours=24,
        ),
        ANALYST,
    )
    validate_error(resp, ApiErrorId.ERR_COMPANION_ITEM_INVALID.value, 422)
    assert (resp.json().get("data") or {}).get("error_id") != (
        ApiErrorId.ERR_REFERENCED_RESOURCE_NOT_FOUND.value
    ), "the id resolves; it is the cross-facility association that is illegal"

    rows, meta = validate_paginated(
        api_client.list_charge_items(ANALYST, params={"facility_id": base_a["facility"]["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []
