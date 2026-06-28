"""Entity creation, computed/default fields, immutability, and calculation boundaries.
Translates Corner queue sections entities and calculations.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, NON_EXISTENT_UUID,
    create_homeowner_payload, create_project_payload, create_measurement_payload,
    create_manufacture_order_payload,
    setup_measured_project, setup_approved_to_build, setup_completed_project,
    set_clock, TEST_USERS,
)

SD = TEST_USERS["sales_designer_headers"]
MF = TEST_USERS["manufacturer_headers"]


# ─── entities ──────────────────────────────────────────────────────────────

def test_create_project_starts_in_draft_with_system_fields(api):
    """PRD §3.1: "A new project begins in `DRAFT` with `version` 1. Its measured dimensions —
    `width_in`, `depth_in`, and the derived `footprint_sqft` — all begin at 0 until a
    measurement is accepted, its `accepted_quote_id` begins null, and the two computed gating
    flags `requires_hoa` and `requires_engineering` both begin false."

    Design: Corner/entities/create_project_starts_in_draft_with_system_fields
    """
    ho = get_success_data(api.create_homeowner(create_homeowner_payload(email="c1@x.com"), SD))
    pj = validate_success(api.create_project(
        create_project_payload(ho["id"], address_line="A1", structure_type="SCREEN_ROOM",
                               material="ALUMINUM"), SD), 201)
    assert pj["status"] == "DRAFT", pj
    assert pj["version"] == 1, pj
    assert pj["footprint_sqft"] == 0, pj
    assert pj["accepted_quote_id"] is None, pj


def test_create_project_missing_required_field_rejected(api):
    """PRD §2.7: "Request well-formedness — required body fields present and well-typed, enum
    values within their declared sets — is checked as `ERR_INVALID_REQUEST` (HTTP 400)"

    Design: Corner/entities/create_project_missing_required_field_rejected
    """
    ho = get_success_data(api.create_homeowner(create_homeowner_payload(email="c2@x.com"), SD))
    payload = {"homeowner_id": ho["id"], "address_line": "A2", "material": "ALUMINUM"}
    res = api.create_project(payload, SD)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_project_invalid_enum_rejected(api):
    """PRD §2.7: "required body fields present and well-typed, enum values within their
    declared sets — is checked as `ERR_INVALID_REQUEST` (HTTP 400)"

    Design: Corner/entities/create_project_invalid_enum_rejected
    """
    ho = get_success_data(api.create_homeowner(create_homeowner_payload(email="c3@x.com"), SD))
    res = api.create_project(create_project_payload(
        ho["id"], address_line="A3", structure_type="GREENHOUSE", material="ALUMINUM"), SD)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_get_project_nonexistent_returns_not_found(api):
    """PRD §2.5: "the system resolves every path identifier and every body foreign key
    left-to-right, in the order they appear, and rejects the request with `ERR_NOT_FOUND`
    (HTTP 404) at the **first** identifier that does not resolve to an existing entity."

    Design: Corner/entities/get_project_nonexistent_returns_not_found
    """
    res = api.get_project(NON_EXISTENT_UUID, SD)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_project_unknown_homeowner_fk_not_found(api):
    """PRD §2.5: "the system resolves every path identifier and every body foreign key
    left-to-right, in the order they appear, and rejects the request with `ERR_NOT_FOUND`
    (HTTP 404) at the **first** identifier that does not resolve to an existing entity."

    Design: Corner/entities/create_project_unknown_homeowner_fk_not_found
    """
    res = api.create_project(create_project_payload(
        "11111111-1111-4111-8111-111111111111", address_line="A4",
        structure_type="SCREEN_ROOM", material="ALUMINUM"), SD)
    validate_error(res, "ERR_NOT_FOUND")


def test_footprint_computed_on_measurement_accept(api):
    """PRD §3.1: "recomputes the project's `footprint_sqft` as the width in inches multiplied
    by the depth in inches, divided by 144 (the number of square inches in a square foot),
    rounded half up to two decimal places."

    Design: Corner/entities/footprint_computed_ignores_client_supplied_value
    """
    ho, pj, m = setup_measured_project(
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
        measurement_overrides={"width_in": 120, "depth_in": 144, "wall_height_in": 96,
                               "existing_slab": True},
    )
    # 120 * 144 / 144 = 120.00
    assert pj["footprint_sqft"] == 120.00, pj["footprint_sqft"]
    assert pj["width_in"] == 120, pj["width_in"]
    assert pj["status"] == "MEASURED", pj


def test_requires_engineering_false_for_low_load_three_season(api):
    """PRD §3.1: "The boundaries are exact: a snow load of exactly 30.0 does not trigger
    engineering, whereas a wind speed of exactly 130 does."

    Design: Corner/entities/requires_engineering_false_for_low_load_three_season
    """
    # THREE_SEASON, snow 30 (not > 30), wind 120 (< 130) -> false.
    ho, pj, m = setup_measured_project(
        homeowner_overrides={"ground_snow_load_psf": 30, "design_wind_speed_mph": 120},
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
    )
    pj = get_success_data(api.finalize_design(pj["id"], SD))
    assert pj["requires_engineering"] is False, pj
    assert pj["status"] == "DESIGNED", pj


def test_hoa_governed_default_false_when_omitted(api):
    """PRD §3.1: "`hoa_governed` (whether the property sits inside an HOA-governed community,
    defaulting to false)"

    Design: Corner/entities/hoa_governed_default_false_when_omitted
    """
    payload = {"email": "c8@x.com", "full_name": "C8", "ground_snow_load_psf": 10,
               "design_wind_speed_mph": 90}
    ho = validate_success(api.create_homeowner(payload, SD), 201)
    assert ho["hoa_governed"] is False, ho


def test_warranty_immutable_with_computed_term(api):
    """PRD §3.7: "`term_years` is 1 year for a `SCREEN_ROOM`, 5 years for a `THREE_SEASON`, and
    10 years for a `FOUR_SEASON`. Its `starts_at` is the moment of completion (the inspection
    pass time, read from the logical clock), and its `expires_at` is `starts_at` plus the term
    in years multiplied by 365 days, computed to the day."
    PRD §3.7: "As noted in §2.4, the warranty is immutable: it carries only `id` and
    `created_at`, with no `updated_at` and no `version`."

    Design: Corner/entities/warranty_immutable_entity_has_no_version
    """
    set_clock("2026-05-10T00:00:00Z")
    ho, pj, ins = setup_completed_project(
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
        scheduled_start="2026-05-11T08:00:00Z", scheduled_end="2026-05-11T17:00:00Z",
    )
    assert pj["status"] == "COMPLETED", pj
    body = api.list_project_warranties(pj["id"], SD).json()
    warranties = body["data"]
    assert len(warranties) == 1, warranties
    w = warranties[0]
    assert w["term_years"] == 5, w
    assert w["starts_at"] == "2026-05-10T00:00:00.000Z", w
    assert w["expires_at"] == "2031-05-09T00:00:00.000Z", w
    assert "version" not in w, w


# ─── calculations ────────────────────────────────────────────────────────

def test_engineering_requirement_wind_exactly_130_triggers(api):
    """PRD §3.1: "The boundaries are exact: a snow load of exactly 30.0 does not trigger
    engineering, whereas a wind speed of exactly 130 does."

    Design: Corner/calculations/engineering_requirement_wind_exactly_130_triggers
    """
    ho, pj, m = setup_measured_project(
        homeowner_overrides={"ground_snow_load_psf": 10, "design_wind_speed_mph": 130},
        project_overrides={"structure_type": "THREE_SEASON", "material": "ALUMINUM"},
    )
    pj = get_success_data(api.finalize_design(pj["id"], SD))
    assert pj["requires_engineering"] is True, pj


def test_lead_time_footprint_exactly_200_no_surcharge(api):
    """PRD §3.5: "If the project's `footprint_sqft` is strictly greater than 200 square feet,
    14 days are added (a footprint of exactly 200.00 does not surcharge)."
    PRD §3.5: "The lead time begins at a material base — 21 days for `ALUMINUM`, 28 days for
    `VINYL`, and 35 days for `THERMAL_BREAK_ALUMINUM`."

    Design: Corner/calculations/lead_time_footprint_exactly_200_no_surcharge
    """
    set_clock("2026-05-01T00:00:00Z")
    # VINYL THREE_SEASON, 180x160 -> footprint 200.00 exactly.
    ho, pj, q, pa = setup_approved_to_build(
        project_overrides={"structure_type": "THREE_SEASON", "material": "VINYL"},
        measurement_overrides={"width_in": 180, "depth_in": 160, "wall_height_in": 96,
                               "existing_slab": True},
    )
    mo = validate_success(api.create_manufacture_order(
        create_manufacture_order_payload(pj["id"], q["id"]), MF), 201)
    # VINYL base 28; 200.00 NOT > 200 so no surcharge; not FOUR_SEASON -> 28.
    assert mo["lead_time_days"] == 28, mo["lead_time_days"]
    assert mo["promised_ready_at"] == "2026-05-29T00:00:00.000Z", mo["promised_ready_at"]
