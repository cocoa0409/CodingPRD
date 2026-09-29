"""The file family's four guards: OCC token, the FAILED branch, the blackout, and both terminals."""
from test_helpers import (
    api_client, validate_error, validate_success, ApiErrorId, factories,
    setup_base, create_item, reprice_item, item_lifecycle, create_payer_contract,
    create_cycle, create_entry, cycle_lifecycle, read_cycle, read_entry, read_item,
    read_facility, build_transparency_file, file_lifecycle, read_file, set_clock,
    ANALYST, APPROVER, COMPLIANCE, ADMIN,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-FILEERR",
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


def _lifecycle_error(file_id, action, error_id, status):
    validate_error(api_client.transparency_file_lifecycle(file_id, {"action": action}, COMPLIANCE),
                   error_id, status)


def test_an_empty_build_fails_validation_and_a_stale_token_and_a_mapping_cycle_both_refuse():
    """PRD §3.10: "Validation is where the file branches. The `VALIDATE` action routes
    `BUILDING → VALIDATED` when the recomputed `validation_errors` array is empty, and
    `BUILDING → FAILED` when it is non-empty — the two outcomes are the same request with opposite
    verdicts, and the non-empty case arises when at least one `ACTIVE` item is `PRICE_STALE` or when
    `payer_column_count` is 0."
    PRD §3.10: "It gains the string `'NO_PUBLISHABLE_ITEMS'` when `included_item_count` is 0, the string
    `'NO_ACTIVE_PAYER_COLUMNS'` when `payer_column_count` is 0, and the string `'STALE_PRICED_ITEMS'`
    when any charge item of the facility whose `lifecycle_status` is `ACTIVE` has `price_status` of
    `PRICE_STALE`."
    PRD §3.10: "Every transparency lifecycle action accepts an optional `note`, and an action not declared
    from the file's current status — publishing straight from `BUILDING`, validating something already
    `PUBLISHED` — is `ERR_INVALID_FILE_STATE` (409)."
    PRD §2.8: "A new build legitimately supersedes an earlier published file for the same facility, so
    state alone does not block a second build; instead, a build whose `expected_facility_version` does not
    equal the live `Facility.version` is rejected with `ERR_STALE_FACILITY_VERSION` (HTTP 412), because
    the facility's inclusion set has moved since the client last observed it."
    PRD §3.10: "No `CodeUpdateCycle` of the facility may be in `MAPPING` or `CROSSWALK_APPROVED` status —
    publishing during a crosswalk blackout is refused with `ERR_TRANSPARENCY_BLACKOUT` (409) — and
    `included_item_count` must be at least 1, otherwise `ERR_NO_PUBLISHABLE_ITEMS` (422)."
    PRD §3.10: "`FAILED` and `SUPERSEDED` are the file's terminal states."

    Design: Corner/errors/transparency_file_build_rejects_stale_facility_version_terminal_files_and_publish_during_mapping
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    facility_id = base["facility"]["id"]
    contract = create_payer_contract(
        facility_id, payer_code="AETNA", product_line="COMMERCIAL",
        reimbursement_method="PERCENT_OF_CHARGE", percent_of_charge_bp=6000,
        term_start_date="2026-01-01T00:00:00Z", term_end_date="2027-12-31T00:00:00Z",
        trailing_units=100)
    assert contract["status"] == "ACTIVE"

    item = create_item(base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
                       code_type="CPT", code_value="93458", cost_basis_cents=100000,
                       medicare_rate_cents=50000, market_p75_cents=900000,
                       effective_from="2026-09-01T00:00:00Z")
    assert reprice_item(item["id"])["gross_charge_cents"] == 240000

    stale_version = read_facility(facility_id)["version"]
    first = build_transparency_file(facility_id, stale_version, file_format="CSV")
    assert first["status"] == "BUILDING"
    assert first["included_item_count"] == 0, "the facility's only item is still DRAFT"
    assert first["published_at"] is None
    assert read_facility(facility_id)["chargemaster_posture"] == "FROZEN"

    failed = file_lifecycle(first["id"], "VALIDATE")
    assert failed["status"] == "FAILED", "an empty inclusion set routes VALIDATE to FAILED"
    assert failed["validation_errors"] == ["NO_PUBLISHABLE_ITEMS"]
    _lifecycle_error(first["id"], "PUBLISH", ApiErrorId.ERR_INVALID_FILE_STATE.value, 409)
    _lifecycle_error(first["id"], "VALIDATE", ApiErrorId.ERR_INVALID_FILE_STATE.value, 409)
    assert read_facility(facility_id)["chargemaster_posture"] == "OPEN", (
        "the FAILED file no longer holds the facility frozen"
    )

    item_lifecycle(item["id"], "SUBMIT_FOR_REVIEW", ANALYST)
    item_lifecycle(item["id"], "APPROVE", APPROVER)
    active = item_lifecycle(item["id"], "ACTIVATE", APPROVER)
    assert active["lifecycle_status"] == "ACTIVE"
    assert active["price_status"] == "PRICED_CURRENT"

    validate_error(
        api_client.create_transparency_file(
            factories.create_transparency_file_payload(facility_id, stale_version,
                                                       file_format="CSV"),
            COMPLIANCE),
        ApiErrorId.ERR_STALE_FACILITY_VERSION.value, 412,
    )

    fresh_version = read_facility(facility_id)["version"]
    assert fresh_version > stale_version, "activating the item moved the facility on"
    second = build_transparency_file(facility_id, fresh_version, file_format="CSV")
    assert second["status"] == "BUILDING"

    validated = file_lifecycle(second["id"], "VALIDATE")
    assert validated["status"] == "VALIDATED"
    assert validated["validation_errors"] == []
    assert validated["included_item_count"] == 1
    assert validated["payer_column_count"] == 1
    assert validated["total_gross_charge_cents"] == 240000
    assert read_item(item["id"])["price_status"] == "PRICE_FROZEN"
    assert read_facility(facility_id)["chargemaster_posture"] == "FROZEN"

    cycle = create_cycle(facility_id, cycle_year=2027, code_set="CPT")
    entry = create_entry(cycle["id"], "REVISE", old_code_value="93458",
                         new_code_value="93458A")
    mapping = cycle_lifecycle(cycle["id"], "START_MAPPING")
    assert mapping["status"] == "MAPPING", (
        "START_MAPPING is not one of the six writes a FROZEN posture rejects"
    )

    _lifecycle_error(second["id"], "PUBLISH", ApiErrorId.ERR_TRANSPARENCY_BLACKOUT.value, 409)
    assert read_file(second["id"])["status"] == "VALIDATED", "the refused publish mutated nothing"

    cancelled = cycle_lifecycle(cycle["id"], "CANCEL", COMPLIANCE)
    assert cancelled["status"] == "CANCELLED"
    assert read_cycle(cycle["id"])["applied_entry_count"] == 0
    cancelled_entry = read_entry(entry["id"])
    assert cancelled_entry["status"] == "DEFERRED"
    assert cancelled_entry["defer_reason"] == "CYCLE_CANCELLED"

    published = file_lifecycle(second["id"], "PUBLISH")
    assert published["status"] == "PUBLISHED"
    assert published["published_at"].startswith("2026-09-01T00:00:00")
    assert len(published["content_hash"]) == 64, "a SHA-256 digest in hex is 64 characters"
    int(published["content_hash"], 16)
    assert read_item(item["id"])["price_status"] == "PRICED_CURRENT", "publication thaws the file"
    after_publish = read_facility(facility_id)
    assert after_publish["published_transparency_file_id"] == second["id"]
    assert after_publish["transparency_status"] == "CURRENT"
    assert after_publish["chargemaster_posture"] == "OPEN"

    _lifecycle_error(second["id"], "PUBLISH", ApiErrorId.ERR_INVALID_FILE_STATE.value, 409)
    final = validate_success(api_client.get_transparency_file(second["id"], ADMIN), 200)
    assert final["status"] == "PUBLISHED"
    assert final["superseded_by_file_id"] is None
    assert read_file(first["id"])["status"] == "FAILED", (
        "the failed build was never superseded by the published one"
    )
