"""Asset editing under OCC, placement-in-service replay, and external
property-tax / insurance schedules."""
from test_helpers import (
    ACCT,
    CTRL,
    TAX,
    ApiErrorId,
    assert_fixed_asset,
    create_and_post_disposal,
    create_class,
    create_in_service_asset,
    create_schedule,
    current_asset_version,
    refresh_asset,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_place_in_service_twice_returns_invalid_state(api):
    """PRD §3.2: "An `AssetAccountant` places a `DRAFT` asset in service by
    supplying the `in_service_date`; the asset transitions from `DRAFT` to
    `IN_SERVICE` and the date is recorded. Placing an asset that is not `DRAFT`
    in service is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/place_in_service_twice_returns_invalid_state
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-021", description="Twice placed",
        acquisition_cost_cents=500000,
    )
    assert asset["in_service_date"] == "2026-01-10"

    resp = api.place_in_service(
        asset["id"], {"in_service_date": "2026-02-01"}, ACCT
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    after = refresh_asset(asset["id"])
    assert after["status"] == "IN_SERVICE"
    assert after["in_service_date"] == "2026-01-10", (
        "the rejected replay must not move the recorded date"
    )


def test_immutable_field_patch_on_in_service_rejected(api):
    """PRD §3.2: "Once the asset is `IN_SERVICE`, the edit surface narrows to the
    prospective, non-historical fields: only `useful_life_months`,
    `salvage_value_cents`, `location`, `cost_center`, and `description` may be
    touched. An edit to an in-service asset naming any other field is rejected
    with `ERR_FIELD_IMMUTABLE` (HTTP 422)."

    Design: Corner/validations/immutable_field_patch_on_in_service_rejected
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-052", description="Immutable cost",
        acquisition_cost_cents=500000,
    )
    version = current_asset_version(asset["id"])

    resp = api.patch_fixed_asset(
        asset["id"],
        {"expected_asset_version": version, "acquisition_cost_cents": 999999},
        ACCT,
    )
    validate_error(resp, ApiErrorId.ERR_FIELD_IMMUTABLE, 422)

    after = refresh_asset(asset["id"])
    assert after["acquisition_cost_cents"] == 500000
    assert after["version"] == version, "a rejected edit must not mutate the asset"


def test_asset_update_stale_occ_conflict(api):
    """PRD §2.6: "A request to modify an asset's attributes must carry
    `expected_asset_version`, a non-optional input field equal to the asset's
    `version` as last observed by the client. Because every mutation of the asset
    — including cascaded mutations such as depreciation postings and impairment
    write-downs — increments `FixedAsset.version`, a client holding an older
    version is writing against a stale basis. If `expected_asset_version` does
    not match the asset's current `version`, the edit is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.6: "A successful guarded write increments the asset's `version` by 1,
    so the client must re-read before issuing its next guarded write."

    Design: Corner/complexity_layers/asset_update_stale_occ_conflict
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-080", description="OCC asset",
        acquisition_cost_cents=500000,
    )
    stale_version = current_asset_version(asset["id"])

    patched = validate_success(
        api.patch_fixed_asset(
            asset["id"],
            {"expected_asset_version": stale_version, "location": "PLANT-9"},
            ACCT,
        ),
        200,
    )
    assert_fixed_asset(patched)
    assert patched["location"] == "PLANT-9"
    assert patched["version"] == stale_version + 1

    replay = api.patch_fixed_asset(
        asset["id"],
        {"expected_asset_version": stale_version, "location": "PLANT-8"},
        ACCT,
    )
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION, 412)

    after = refresh_asset(asset["id"])
    assert after["location"] == "PLANT-9"
    assert after["version"] == stale_version + 1


def test_property_tax_amount_and_insurance_null(api):
    """PRD §3.7: "For a `PROPERTY_TAX` row, the system derives the tax at import
    time: `property_tax_amount_cents` is the `assessed_value_cents` multiplied by
    the 1.25% mill rate, rounded half-up to a whole cent. For an `INSURANCE` row,
    `property_tax_amount_cents` is null."
    PRD §3.7: "The row is born in status `IMPORTED`."

    Design: Corner/calculations/property_tax_amount_and_insurance_null
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-031", description="Scheduled asset",
        acquisition_cost_cents=500000,
    )

    tax_row = create_schedule(
        asset["id"], schedule_type="PROPERTY_TAX", schedule_year=2026,
        assessed_value_cents=8000000,
    )
    assert tax_row["property_tax_amount_cents"] == 100000, (
        "round_half_up(8000000 * 0.0125)"
    )
    assert tax_row["status"] == "IMPORTED"

    ins_row = create_schedule(
        asset["id"], schedule_type="INSURANCE", schedule_year=2026,
        annual_premium_cents=120000,
    )
    assert ins_row["property_tax_amount_cents"] is None
    assert ins_row["annual_premium_cents"] == 120000
    assert ins_row["status"] == "IMPORTED"


def test_duplicate_schedule_rejected(api):
    """PRD §3.7: "Only one row may exist per combination of asset, schedule type,
    and year; a duplicate is rejected with `ERR_DUPLICATE_SCHEDULE`."

    Design: Corner/validations/duplicate_schedule_rejected
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-053", description="Schedule host",
        acquisition_cost_cents=500000,
    )
    create_schedule(
        asset["id"], schedule_type="PROPERTY_TAX", schedule_year=2026,
        assessed_value_cents=8000000,
    )

    resp = api.create_external_schedule(
        {"asset_id": asset["id"], "schedule_type": "PROPERTY_TAX",
         "schedule_year": 2026, "assessed_value_cents": 9000000},
        TAX,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SCHEDULE, 409)


def test_invalid_schedule_fields_rejected(api):
    """PRD §3.7: "The two types carry different payloads: a `PROPERTY_TAX` row
    requires `assessed_value_cents` and leaves `annual_premium_cents` null, while
    an `INSURANCE` row requires `annual_premium_cents` and leaves
    `assessed_value_cents` null; mixing these up is rejected with
    `ERR_INVALID_SCHEDULE_FIELDS` (HTTP 422)."

    Design: Corner/validations/invalid_schedule_fields_rejected
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-054", description="Schedule fields",
        acquisition_cost_cents=500000,
    )

    tax_missing_value = api.create_external_schedule(
        {"asset_id": asset["id"], "schedule_type": "PROPERTY_TAX",
         "schedule_year": 2026},
        TAX,
    )
    validate_error(tax_missing_value, ApiErrorId.ERR_INVALID_SCHEDULE_FIELDS, 422)

    ins_missing_premium = api.create_external_schedule(
        {"asset_id": asset["id"], "schedule_type": "INSURANCE",
         "schedule_year": 2026},
        TAX,
    )
    validate_error(ins_missing_premium, ApiErrorId.ERR_INVALID_SCHEDULE_FIELDS, 422)


def test_apply_schedule_on_disposed_asset_rejected(api):
    """PRD §3.7: "A `Controller` subsequently applies the row, moving it from
    `IMPORTED` to the terminal status `APPLIED`; applying against a `DISPOSED`
    asset is rejected with `ERR_ALREADY_DISPOSED`, and applying a row not in
    `IMPORTED` is `ERR_INVALID_STATE`."

    Design: Corner/validations/apply_schedule_on_disposed_asset_rejected
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-058", description="Disposed host",
        acquisition_cost_cents=500000,
    )
    schedule = create_schedule(
        asset["id"], schedule_type="INSURANCE", schedule_year=2026,
        annual_premium_cents=120000,
    )
    # Day 10 < 15: no final entries; SCRAP is exempt from the compliance gate.
    posted = create_and_post_disposal(
        asset["id"], disposal_type="SCRAP", proceeds_cents=0,
        effective_date="2026-02-10",
    )
    assert posted["status"] == "POSTED"
    assert refresh_asset(asset["id"])["status"] == "DISPOSED"

    resp = api.apply_external_schedule(schedule["id"], CTRL)
    validate_error(resp, ApiErrorId.ERR_ALREADY_DISPOSED, 409)

    schedules, meta = validate_paginated(
        api.list_asset_external_schedules(asset["id"], ACCT)
    )
    assert meta["total_count"] == 1
    assert schedules[0]["status"] == "IMPORTED"
