"""Declaring the mill's reference rows: what a create echoes back, which fields the
system stamps itself, which omissions are legal defaults and which are refusals.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    is_valid_uuid, is_iso8601_timestamp, TEST_USERS,
    create_customer_payload, create_fiber_grade_payload,
    create_paper_grade_spec_payload, register_machine,
)

PLANNER = TEST_USERS["planner_headers"]
BUYER = TEST_USERS["buyer_headers"]
OPERATOR = TEST_USERS["operator_headers"]


def test_registering_a_customer_echoes_the_whole_roll_envelope_and_stamps_active():
    """PRD §3.6: "A customer is registered by a `MillPlanner` with its legal `name` of
    1 to 120 characters, an `allocation_priority_tier` of `P1`, `P2` or `P3` defaulting
    to `P3` — the lower the number, the higher the customer ranks when rolls are being
    allocated — and the roll envelope the customer's own handling equipment can accept:
    `max_roll_diameter_mm` from 800 through 1800, `max_roll_width_mm` from 400 through
    2800, and a `wrap_spec` of `KRAFT_ONLY`, `POLY_COATED` or `STRETCH_HOOD` defaulting
    to `KRAFT_ONLY`."
    PRD §3.6: "A new customer opens with `status` of `ACTIVE`; the planner may later set
    that `status` to `SUSPENDED` or back to `ACTIVE`, and a `SUSPENDED` customer can
    neither submit new orders nor have existing ones sequenced onto runs."
    PRD §2.4: "Most resources additionally carry `updated_at` — same ISO 8601 UTC format
    with three fractional digits, refreshed on every mutation of that row — and
    `version`, an integer that starts at 1 on creation and increments by exactly one on
    every mutation."

    Design: Corner/entities/create_customer_returns_201_with_full_roll_spec_envelope
    """
    response = api_client.create_customer(create_customer_payload(
        name="Gulf Coast Box Co", allocation_priority_tier="P1",
        max_roll_diameter_mm=1400, max_roll_width_mm=2400,
        wrap_spec="KRAFT_ONLY"), PLANNER)
    customer = validate_success(response, 201)

    assert response.json()["response_type"] == "object"
    assert customer["name"] == "Gulf Coast Box Co"
    assert customer["allocation_priority_tier"] == "P1"
    assert customer["max_roll_diameter_mm"] == 1400
    assert customer["max_roll_width_mm"] == 2400
    assert customer["wrap_spec"] == "KRAFT_ONLY"
    assert customer["status"] == "ACTIVE"
    assert customer["version"] == 1
    assert is_valid_uuid(customer["id"])
    assert is_iso8601_timestamp(customer["created_at"])
    assert is_iso8601_timestamp(customer["updated_at"])


def test_a_customer_omitting_tier_and_wrap_falls_back_to_the_declared_defaults():
    """PRD §3.6: "A customer is registered by a `MillPlanner` with its legal `name` of
    1 to 120 characters, an `allocation_priority_tier` of `P1`, `P2` or `P3` defaulting
    to `P3` — the lower the number, the higher the customer ranks when rolls are being
    allocated — and the roll envelope the customer's own handling equipment can accept:
    `max_roll_diameter_mm` from 800 through 1800, `max_roll_width_mm` from 400 through
    2800, and a `wrap_spec` of `KRAFT_ONLY`, `POLY_COATED` or `STRETCH_HOOD` defaulting
    to `KRAFT_ONLY`."
    PRD §3.6: "A new customer opens with `status` of `ACTIVE`; the planner may later set
    that `status` to `SUSPENDED` or back to `ACTIVE`, and a `SUSPENDED` customer can
    neither submit new orders nor have existing ones sequenced onto runs."

    Design: Corner/entities/customer_defaults_applied_when_tier_and_wrap_omitted
    """
    customer = validate_success(api_client.create_customer(
        {"name": "Piedmont Tissue LLC", "max_roll_diameter_mm": 1100,
         "max_roll_width_mm": 1800}, PLANNER), 201)

    assert customer["allocation_priority_tier"] == "P3"
    assert customer["wrap_spec"] == "KRAFT_ONLY"
    assert customer["status"] == "ACTIVE"


def test_a_paper_grade_spec_without_a_basis_weight_is_not_stored():
    """PRD §3.4: "Each spec names its `family`, either `CONTAINERBOARD` or `TISSUE`; a
    `basis_weight_gsm` target from 12 through 400 at one decimal place; a
    `target_moisture_pct` from 2 through 12 at two decimal places with a
    `moisture_tolerance_pct` from 0.1 through 3 at two decimal places giving the
    half-width of the acceptable band on either side of the target; a `min_sct_kn_m`
    minimum short-span compressive strength of at least zero at two decimal places; an
    optional `min_brightness_iso` from 0 through 100 at one decimal place, left null for
    grades with no brightness requirement; a `requires_deink_pulp` boolean marking
    grades that may only be fed by pulp that has completed at least one deink pass; and
    a unique `rank_order` integer from 1 through 99 used for grade-change sequencing and
    tie-breaks."
    PRD §2.7: "A missing required field, a value of the wrong type, a number outside its
    declared range, an enum member that is not declared, an unparseable datetime, or an
    array that breaches its cardinality bounds or its uniqueness key is rejected with
    `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/entities/create_paper_grade_spec_missing_basis_weight_rejected
    """
    payload = create_paper_grade_spec_payload(
        product_code="TL_140", target_moisture_pct=7.50,
        moisture_tolerance_pct=0.50, min_sct_kn_m=2.50, rank_order=10)
    payload.pop("basis_weight_gsm")

    response = api_client.create_paper_grade_spec(payload, PLANNER)
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)
    assert response.json()["response_type"] == "error"

    listing = api_client.list_paper_grade_specs(PLANNER)
    assert listing.json()["meta"]["total_count"] == 0


def test_an_index_symbol_outside_the_four_published_series_is_refused():
    """PRD §3.1: "A `FiberBuyer` declares each grade with its `grade_code` — a business
    key that must be unique and must take the shape of two to four uppercase letters, an
    underscore, and exactly two digits, so `OCC_11`, `DLK_37`, `SOP_37` and `ONP_58` are
    all well-formed — together with the `index_symbol` that prices it, which must be one
    of `PPI_OCC`, `PPI_DLK`, `PPI_SOP` or `PPI_ONP`."
    PRD §2.7: "A missing required field, a value of the wrong type, a number outside its
    declared range, an enum member that is not declared, an unparseable datetime, or an
    array that breaches its cardinality bounds or its uniqueness key is rejected with
    `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/entities/fiber_grade_rejects_undeclared_index_symbol_enum_member
    """
    response = api_client.create_fiber_grade(create_fiber_grade_payload(
        grade_code="MIX_54", index_symbol="PPI_MIX", max_contamination_pct=8.00,
        max_moisture_pct=14.00, nominal_yield_pct=78.00, rank_order=9), BUYER)
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)

    assert api_client.list_fiber_grades(BUYER).json()["meta"]["total_count"] == 0


def test_a_lower_case_hyphenated_grade_code_fails_the_business_key_shape():
    """PRD §3.1: "A `FiberBuyer` declares each grade with its `grade_code` — a business
    key that must be unique and must take the shape of two to four uppercase letters, an
    underscore, and exactly two digits, so `OCC_11`, `DLK_37`, `SOP_37` and `ONP_58` are
    all well-formed — together with the `index_symbol` that prices it, which must be one
    of `PPI_OCC`, `PPI_DLK`, `PPI_SOP` or `PPI_ONP`."
    PRD §2.7: "Uniqueness collisions on business keys — a duplicate `grade_code`,
    `product_code`, machine `name`, `permit_number`, `manifest_number`, a duplicate
    `rank_order`, or a second non-voided reading for the same permit and `reading_date`
    — yield `ERR_DUPLICATE_KEY` (HTTP 409)."

    Design: Corner/entities/fiber_grade_rejects_grade_code_failing_business_key_regex
    """
    response = api_client.create_fiber_grade(create_fiber_grade_payload(
        grade_code="occ-11", rank_order=1), BUYER)
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)

    assert api_client.list_fiber_grades(BUYER).json()["meta"]["total_count"] == 0, \
        "a shape failure is not a uniqueness failure and stores nothing"


def test_a_declared_fiber_grade_carries_no_version_and_no_updated_at():
    """PRD §2.4: "Four resource kinds are deliberate exceptions: `FiberGrade`,
    `MarketIndexQuote`, `PaperGradeSpec`, and `RejectStream` rows carry only `id` and
    `created_at`."
    PRD §2.4: "For those four entity kinds, both `updated_at` and `version` are absent
    from the persisted row and from every response body."
    PRD §3.1: "`downgrade_target_grade_code` names, by grade code, the fallback grade a
    truck rejected at its contracted grade may still be accepted as; leaving it null
    means the grade has no fallback and a dirty truck has nowhere to go."

    Design: Corner/entities/fiber_grade_is_immutable_no_version_and_no_update_endpoint
    """
    grade = validate_success(api_client.create_fiber_grade(
        create_fiber_grade_payload(grade_code="OCC_11", rank_order=1), BUYER), 201)

    assert "version" not in grade
    assert "updated_at" not in grade
    assert grade["grade_code"] == "OCC_11"
    assert grade["downgrade_target_grade_code"] is None
    assert is_iso8601_timestamp(grade["created_at"])

    listing = api_client.list_fiber_grades(BUYER, {"grade_code": "OCC_11"}).json()
    assert listing["meta"]["total_count"] == 1
    assert "version" not in listing["data"][0]
    assert "updated_at" not in listing["data"][0]


def test_a_freshly_registered_machine_reads_back_runnable_with_no_product_yet():
    """PRD §3.4: "A newly registered machine opens with `status` of `RUNNABLE`, `version`
    of 1, and `current_product_code` null."
    PRD §3.4: "`current_product_code` always names the product of the most recently
    completed run on that machine, and is null while no run has completed there."

    Design: Corner/entities/get_paper_machine_returns_stored_row_with_occ_version
    """
    machine = register_machine(name="PM1", wire_width_mm=5600, max_tons_per_hour=20.00,
                               changeover_buffer_minutes=30, steam_tph_per_ton=2.500)

    stored = get_success_data(api_client.get_paper_machine(machine["id"], OPERATOR))
    assert stored["id"] == machine["id"]
    assert stored["name"] == "PM1"
    assert stored["wire_width_mm"] == 5600
    assert stored["max_tons_per_hour"] == pytest.approx(20.00, abs=1e-6)
    assert stored["changeover_buffer_minutes"] == 30
    assert stored["steam_tph_per_ton"] == pytest.approx(2.500, abs=1e-6)
    assert stored["status"] == "RUNNABLE"
    assert stored["current_product_code"] is None
    assert stored["version"] == 1
