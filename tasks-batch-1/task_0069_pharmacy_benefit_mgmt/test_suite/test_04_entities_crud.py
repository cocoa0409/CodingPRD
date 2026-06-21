"""Entity creation, defaults, computed fields, immutability, and listing
(PRD §2.4, §3.1, §3.2). Corner queue: entities section.
"""
from test_helpers import fixtures as fx, validate_success, validate_error, validate_paginated, ApiErrorId
from test_helpers.api_client import api_client
from test_helpers import assert_benefit_plan, assert_step_therapy_protocol


# ─── Corner / entities.create_plan_returns_201_with_all_fields ──────────────
def test_create_plan_returns_201_active_version_1(api):
    """PRD §3.1: "A plan begins life with `status` of `ACTIVE` and version 1"
    PRD §2.4: "an integer `version` that begins at 1 on creation"

    Design: Corner/entities/create_plan_returns_201_with_all_fields
    """
    resp = api_client.create_plan(
        {"name": "Gold", "plan_year": 2026, "deductible_cents": 50000,
         "oop_max_cents": 200000,
         "tier_copay_cents": {"TIER_1": 1000, "TIER_2": 3500, "TIER_3": 7000, "SPECIALTY": 25000}},
        fx.ADMIN,
    )
    data = validate_success(resp, 201)
    assert_benefit_plan(data)
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1
    assert data["deductible_cents"] == 50000


# ─── Corner / entities.get_member_not_found_returns_404 ─────────────────────
def test_get_member_not_found_returns_404(api):
    """PRD §2.7: "every resource referenced by a path identifier or a foreign-key body
    field must exist, validated left to right in the order the references are read —
    member, then drug, then plan, then prior authorization, then copay card — and the
    first missing reference yields `ERR_NOT_FOUND`."

    Design: Corner/entities/get_member_not_found_returns_404
    """
    resp = api_client.get_member("00000000-0000-4000-8000-000000000000", fx.ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ─── Corner / entities.create_drug_missing_tier_returns_invalid_request ─────
def test_create_drug_missing_tier_returns_invalid_request(api):
    """PRD §2.7: "a request whose body is missing a required field, carries an ill-typed value, presents an out-of-range number, or supplies an enum value outside its allowed set is rejected with `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_drug_missing_tier_returns_invalid_request
    """
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    resp = api_client.create_formulary_drug(
        {"plan_id": plan["id"], "ndc": "N", "drug_name": "N", "ingredient_cost_cents": 30000},
        fx.ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─── Corner / entities.create_drug_invalid_tier_enum_returns_invalid_request ─
def test_create_drug_invalid_tier_enum_returns_invalid_request(api):
    """PRD §2.7: "supplies an enum value outside its allowed set is rejected with `ERR_INVALID_REQUEST` (HTTP 422)."
    PRD §3.1: "a `tier` that is one of `TIER_1`, `TIER_2`, `TIER_3`, or `SPECIALTY"

    Design: Corner/entities/create_drug_invalid_tier_enum_returns_invalid_request
    """
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    resp = api_client.create_formulary_drug(
        {"plan_id": plan["id"], "ndc": "N", "drug_name": "N", "tier": "TIER_9",
         "ingredient_cost_cents": 30000},
        fx.ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─── Corner / entities.drug_defaults_applied_when_optional_fields_omitted ────
def test_drug_defaults_applied_when_optional_fields_omitted(api):
    """PRD §3.1: "`is_specialty` (default false) marks the drug as a specialty product;
    `pa_required` (default false) marks the drug as requiring an approved prior
    authorization before any claim against it can pay;"
    PRD §3.1: "and `rebate_per_fill_cents` (default 0, and zero or greater) is the
    manufacturer rebate the plan accrues per paid 30-day-equivalent fill."
    PRD §3.1: "A drug begins `ACTIVE`"

    Design: Corner/entities/drug_defaults_applied_when_optional_fields_omitted
    """
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="N", drug_name="N", tier="TIER_1",
                          ingredient_cost_cents=10000)
    assert drug["pa_required"] is False
    assert drug["is_specialty"] is False
    assert drug["rebate_per_fill_cents"] == 0
    assert drug["status"] == "ACTIVE"


# ─── Corner / entities.member_computed_accumulators_start_zero ──────────────
def test_member_accumulators_start_zero(api):
    """PRD §3.2: "A new member starts `ACTIVE`, with both accumulators — `deductible_met_cents` and `oop_met_cents` — at 0. These two accumulators are computed fields: they are never written directly"

    Design: Corner/entities/member_computed_accumulators_start_zero_input_ignored
    """
    plan = fx.create_plan(deductible_cents=50000, oop_max_cents=200000)
    m = fx.create_member(plan["id"])
    assert m["deductible_met_cents"] == 0
    assert m["oop_met_cents"] == 0
    assert m["status"] == "ACTIVE"


# ─── Corner / entities.protocol_immutable_no_version_field ──────────────────
def test_step_therapy_protocol_has_no_version_field(api):
    """PRD §2.4: "Step-therapy protocols are the single exception: they are lightweight reference records that are immutable after creation. A `StepTherapyProtocol` carries only an `id` and a `created_at` timestamp; it has neither an `updated_at` field nor a `version` field."

    Design: Corner/entities/protocol_immutable_no_version_field
    """
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    resp = api_client.create_step_therapy_protocol(
        {"plan_id": plan["id"], "name": "ST", "first_line_ndcs": ["A1", "A2"]},
        fx.ADMIN,
    )
    data = validate_success(resp, 201)
    assert_step_therapy_protocol(data)
    assert data["name"] == "ST"
    assert "version" not in data
    assert "updated_at" not in data


# ─── Corner / entities.list_plans_pagination_envelope ───────────────────────
def test_list_plans_pagination_envelope(api):
    """PRD §2.3: "List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_plans_pagination_envelope
    """
    fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    resp = api_client.list_plans(fx.ADMIN)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 1
