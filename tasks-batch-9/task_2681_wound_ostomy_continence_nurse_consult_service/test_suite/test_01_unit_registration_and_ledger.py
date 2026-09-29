"""Unit registration, the opening rental ledger and the natural-key guard."""
from test_helpers import (
    assert_envelope_meta,
    assert_unit,
    create_product,
    create_surface,
    create_unit,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_unit_charge_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import make_director_headers, make_materials_headers


DIRECTOR = make_director_headers()
MATERIALS = make_materials_headers()


def test_registering_a_unit_returns_the_whole_ledger_zeroed(api):
    """A freshly registered unit exposes every ledger figure at its opening value.

    PRD §3.1: "Registration initialises the unit's rental ledger to a known-empty
    state: `rental_encumbered_cents`, `rental_committed_cents` and
    `rental_released_cents` all start at 0, `rental_available_cents` starts equal
    to `rental_budget_cap_cents`, `open_hapi_rca_count` and
    `disputed_staging_count` start at 0, and `survey_posture` starts at `OPEN`."
    PRD §3.1: "Both reporting rates start as null: `last_prevalence_rate` and
    `last_incidence_rate` remain null until a survey round of the matching type
    has published for that unit."

    Design: Corner/entities/unit_create_returns_full_ledger_shape_zeroed
    """
    response = api.create_unit(
        {
            "unit_code": "3E",
            "name": "Three East",
            "bed_count": 18,
            "rental_budget_cap_cents": 250000,
        },
        DIRECTOR,
    )
    data = validate_success(response, expected_status=201)
    assert_envelope_meta(response)
    assert response.json()["response_type"] == "object"

    assert is_valid_uuid(data["id"]), "the id must be a bare server-minted UUID"
    assert not data["id"].startswith("unit"), "the id carries no type prefix"
    assert data["version"] == 1
    assert data["unit_code"] == "3E"
    assert data["name"] == "Three East"
    assert data["bed_count"] == 18
    assert data["rental_budget_cap_cents"] == 250000

    assert data["rental_encumbered_cents"] == 0
    assert data["rental_committed_cents"] == 0
    assert data["rental_released_cents"] == 0
    assert data["rental_available_cents"] == 250000
    assert data["open_hapi_rca_count"] == 0
    assert data["disputed_staging_count"] == 0
    assert data["survey_posture"] == "OPEN"
    assert data["last_prevalence_rate"] is None
    assert data["last_incidence_rate"] is None

    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert data["created_at"] == data["updated_at"], (
        "a row that has never been mutated carries updated_at equal to created_at"
    )
    assert_unit(data)


def test_omitting_the_rental_cap_leaves_the_unit_with_no_headroom(api):
    """The opening cap is optional and defaults to zero, so does the headroom.

    PRD §3.1: "When `rental_budget_cap_cents` is omitted it defaults to 0, and it
    may never be negative."
    PRD §3.1: "`rental_available_cents` is spendable headroom, recomputed on every
    ledger mutation as `rental_budget_cap_cents` less `rental_encumbered_cents`
    less `rental_committed_cents`; it may be exactly 0 but must never be negative,
    and every path that encumbers money checks it first."

    Design: Corner/entities/unit_rental_budget_cap_defaults_to_zero_when_omitted
    """
    data = validate_success(
        api.create_unit(
            {"unit_code": "4W", "name": "Four West", "bed_count": 12}, DIRECTOR
        ),
        expected_status=201,
    )
    assert data["rental_budget_cap_cents"] == 0, "the omitted cap defaults to 0"
    assert data["rental_available_cents"] == 0, "no cap means no headroom at all"
    assert data["survey_posture"] == "OPEN", (
        "the posture default is derived from open_hapi_rca_count, not from the budget"
    )


def test_unit_create_read_and_list_agree_with_each_other(api):
    """Read echoes the stored row and the page counts describe the whole set.

    PRD §2.3: "The `meta` block of a list response carries `limit` and `offset` as
    they were resolved for that request, `total_count` as the number of rows
    matching the supplied filters before pagination is applied, and `has_more` as a
    boolean that is true exactly when `offset` plus the number of returned rows is
    less than `total_count`."
    PRD §3.1: "Units can be listed with a `survey_posture` filter, which is the
    fastest way for a coordinator to find the wards whose rental spending is
    currently gated, and a single unit can be read to see its live ledger, its
    posture and its `version`."

    Design: Corner/endpoints/unit_crud_create_read_and_paginated_list
    """
    first = validate_success(
        api.create_unit(
            {
                "unit_code": "3E",
                "name": "Three East",
                "bed_count": 18,
                "rental_budget_cap_cents": 250000,
            },
            DIRECTOR,
        ),
        expected_status=201,
    )
    second = validate_success(
        api.create_unit(
            {
                "unit_code": "4W",
                "name": "Four West",
                "bed_count": 22,
                "rental_budget_cap_cents": 100000,
            },
            DIRECTOR,
        ),
        expected_status=201,
    )
    third = validate_success(
        api.create_unit(
            {"unit_code": "5N", "name": "Five North", "bed_count": 30}, DIRECTOR
        ),
        expected_status=201,
    )
    for created in (first, second, third):
        assert is_valid_uuid(created["id"])
        assert is_iso8601_timestamp(created["created_at"])
        assert is_iso8601_timestamp(created["updated_at"])
        assert created["version"] == 1
    assert third["rental_budget_cap_cents"] == 0, "the omitted optional cap defaults to 0"

    read = validate_success(api.get_unit(second["id"], make_unit_charge_headers(second["id"])))
    assert read["id"] == second["id"]
    assert read["unit_code"] == "4W"
    assert read["name"] == "Four West"
    assert read["bed_count"] == 22
    assert read["rental_budget_cap_cents"] == 100000
    assert read["rental_encumbered_cents"] == 0
    assert read["rental_committed_cents"] == 0
    assert read["rental_released_cents"] == 0
    assert read["rental_available_cents"] == 100000
    assert read["open_hapi_rca_count"] == 0
    assert read["disputed_staging_count"] == 0
    assert read["survey_posture"] == "OPEN"
    assert read["last_prevalence_rate"] is None
    assert read["last_incidence_rate"] is None

    page1, meta1 = validate_paginated(api.list_units(DIRECTOR, {"limit": 2, "offset": 0}))
    assert len(page1) == 2, "the requested page size is honoured"
    assert meta1["total_count"] == 3, (
        "total_count counts every matching row before pagination, not the page"
    )
    assert meta1["has_more"] is True, "0 plus 2 returned rows is less than 3"
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0

    page2, meta2 = validate_paginated(api.list_units(DIRECTOR, {"limit": 2, "offset": 2}))
    assert len(page2) == 1, "only one row is left beyond the offset"
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False, "2 plus 1 returned row is not less than 3"
    page1_ids = {row["id"] for row in page1}
    assert page2[0]["id"] not in page1_ids, "the offset window does not overlap the first page"
    assert page1_ids | {page2[0]["id"]} == {first["id"], second["id"], third["id"]}

    filtered, meta3 = validate_paginated(api.list_units(DIRECTOR, {"survey_posture": "OPEN"}))
    assert len(filtered) == 3, "every unit sits at the OPEN end of the posture ladder"
    assert meta3["total_count"] == 3
    for row in filtered:
        assert row["survey_posture"] == "OPEN"
        assert row["version"] == 1, "a read never mutates the row it returns"


def test_four_natural_keys_are_globally_unique(api):
    """One error code guards four unrelated natural keys, each of them global.

    PRD §2.10 rung 55: "Natural keys are unique: a unit's `unit_code`, a patient's
    `mrn`, a support surface's `asset_tag` and a formulary product's `sku` —
    `ERR_DUPLICATE_NATURAL_KEY` (409), on `POST /units`, `POST /patients`,
    `POST /support-surfaces` and `POST /formulary-products`."
    PRD §3.2: "The `mrn` is the medical record number, 6 to 16 characters, unique
    across all patients — a reuse is refused with `ERR_DUPLICATE_NATURAL_KEY`."

    Design: Corner/validations/duplicate_natural_keys_rejected_on_all_four_entities
    """
    unit_one = create_unit(
        api, unit_code="3E", name="Three East", bed_count=18, rental_budget_cap_cents=0
    )
    unit_two = create_unit(
        api, unit_code="4W", name="Four West", bed_count=22, rental_budget_cap_cents=0
    )
    charge_one = make_unit_charge_headers(unit_one["id"])
    charge_two = make_unit_charge_headers(unit_two["id"])
    patient = validate_success(
        api.create_patient(
            {"mrn": "MRN-R1", "unit_id": unit_one["id"], "admitted_at": "2026-07-31T00:00:00Z"},
            charge_one,
        ),
        expected_status=201,
    )
    surface = create_surface(
        api,
        asset_tag="BED-200",
        surface_class="FOAM_OVERLAY",
        daily_rate_cents=5000,
        vendor_name="AirBeds Inc",
    )
    product = create_product(
        api,
        sku="DRSG-01",
        name="Foam dressing 10x10",
        category="FOAM",
        unit_cost_cents=800,
        formulary_tier="PREFERRED",
    )

    validate_error(
        api.create_unit(
            {
                "unit_code": "3E",
                "name": "Three East Annex",
                "bed_count": 6,
                "rental_budget_cap_cents": 0,
            },
            DIRECTOR,
        ),
        "ERR_DUPLICATE_NATURAL_KEY",
        expected_status=409,
    )
    validate_error(
        api.create_patient(
            {"mrn": "MRN-R1", "unit_id": unit_two["id"], "admitted_at": "2026-08-01T00:00:00Z"},
            charge_two,
        ),
        "ERR_DUPLICATE_NATURAL_KEY",
        expected_status=409,
    )
    validate_error(
        api.create_support_surface(
            {
                "asset_tag": "BED-200",
                "surface_class": "ALTERNATING_PRESSURE",
                "daily_rate_cents": 9000,
                "vendor_name": "Other Vendor",
            },
            MATERIALS,
        ),
        "ERR_DUPLICATE_NATURAL_KEY",
        expected_status=409,
    )
    validate_error(
        api.create_formulary_product(
            {
                "sku": "DRSG-01",
                "name": "Alginate rope",
                "category": "ALGINATE",
                "unit_cost_cents": 1200,
                "formulary_tier": "RESTRICTED",
            },
            DIRECTOR,
        ),
        "ERR_DUPLICATE_NATURAL_KEY",
        expected_status=409,
    )

    fresh = validate_success(
        api.create_patient(
            {"mrn": "MRN-R2", "unit_id": unit_two["id"], "admitted_at": "2026-08-01T00:00:00Z"},
            charge_two,
        ),
        expected_status=201,
    )
    assert fresh["mrn"] == "MRN-R2", "a distinct key is still accepted"

    assert get_success_data(api.get_unit(unit_one["id"], DIRECTOR))["name"] == "Three East"
    assert (
        get_success_data(api.get_support_surface(surface["id"], MATERIALS))["daily_rate_cents"]
        == 5000
    )
    assert (
        get_success_data(api.get_formulary_product(product["id"], DIRECTOR))["formulary_tier"]
        == "PREFERRED"
    )
    assert get_success_data(api.get_patient(patient["id"], charge_one))["unit_id"] == unit_one["id"]
