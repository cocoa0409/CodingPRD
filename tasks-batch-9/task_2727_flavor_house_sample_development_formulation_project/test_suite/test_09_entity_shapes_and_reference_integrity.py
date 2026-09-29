"""Entity shapes, declared defaults and reference integrity on creation."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_common_fields,
    assert_envelope_meta,
    assert_pagination_meta,
)
from test_helpers.constants import UNKNOWN_UUIDS
from test_helpers.factories import (
    create_customer_brief_payload,
    create_formula_payload,
    create_raw_material_payload,
    sub_formula_component_payload,
)
from test_helpers.fixtures import (
    add_material_line,
    add_sub_formula_line,
    cost_formula,
    create_accepted_brief,
    create_brief,
    create_formula,
    create_material,
    list_data,
    read_component,
    read_formula,
)
from test_helpers.test_users import (
    ACCOUNT_MANAGER,
    FLAVORIST,
    LAB_TECH,
    PURCHASING_MANAGER,
    TECHNICAL_DIRECTOR,
)


def test_brief_creation_answers_the_standard_envelope_with_system_defaults(api):
    """A 201 body carries only meta/response_type/data and the declared defaults.

    The PRD fixes the envelope: the body has `meta`, `response_type` and
    `data`, with `api_request_id` "a server-generated unique identifier for
    the request that starts with `req_`" and `response_type` "either "object"
    for a single resource or "array" for a list".  Section 3.1 fixes the row:
    "A brief begins life in `DRAFT`, with `clarification_round_count` at 0 and
    `version` at 1.  Its `clarification_note`, `decision_note`, `outcome`,
    `loss_reason` and `closed_at` are all null at that point."  The clock
    "reads exactly `2026-08-01T00:00:00Z`" before any request moves it.

    Design: Corner/entities/brief_creation_returns_envelope_and_system_defaults
    """
    response = api.create_customer_brief(
        create_customer_brief_payload(brief_code="BRF-0001"), ACCOUNT_MANAGER)
    assert response.status_code == 201, response.text

    body = response.json()
    assert set(body.keys()) == {"meta", "response_type", "data"}
    assert_envelope_meta(body, "object")

    brief = body["data"]
    assert brief["brief_code"] == "BRF-0001"
    assert float(brief["dosage_pct"]) == 1.0
    assert brief["status"] == "DRAFT"
    assert brief["clarification_round_count"] == 0
    assert brief["clarification_note"] is None
    assert brief["decision_note"] is None
    assert brief["outcome"] is None
    assert brief["loss_reason"] is None
    assert brief["closed_at"] is None
    assert_common_fields(brief, expected_version=1)


def test_brief_retrieval_returns_the_stored_row(api):
    """The read echoes the tier, the kosher demand and both exclusions.

    Section 3.1 says `natural_claim_required`, `kosher_required` and
    `halal_required` "each default to false when omitted, and
    `allergen_exclusions` defaults to an empty array; when supplied it must be
    a duplicate-free subset" of the eleven codes, and the read endpoint is open
    to all roles.

    Design: Corner/entities/brief_retrieval_returns_the_stored_row
    """
    created = create_brief(api, brief_code="BRF-0001",
                           confidentiality_tier="TIER_2_RESTRICTED",
                           kosher_required=True,
                           allergen_exclusions=["MILK", "PEANUT"])

    brief = get_success_data(api.get_customer_brief(created["id"], LAB_TECH), 200)

    assert brief["customer_name"] == "Nordica Dairy"
    assert brief["confidentiality_tier"] == "TIER_2_RESTRICTED"
    assert brief["kosher_required"] is True
    assert brief["natural_claim_required"] is False
    assert brief["allergen_exclusions"] == ["MILK", "PEANUT"]
    assert brief["version"] == 1


def test_brief_listing_filters_by_status_and_reports_pagination_fields(api):
    """A one-row page of the two DRAFT briefs reports total_count 2 and has_more.

    The PRD says briefs "can be listed and filtered by `status`, by
    `customer_name` and by `outcome`", `limit` "caps the number of records
    returned" and `offset` "is the number of records to skip before the page
    begins", with `limit`, `offset`, `total_count` and `has_more` "included for
    list endpoints".

    Design: Corner/entities/brief_listing_filters_by_status_and_reports_pagination_fields
    """
    first = create_brief(api, brief_code="BRF-0001")
    second = create_brief(api, brief_code="BRF-0002", matrix_type="BAKERY_SWEET",
                          target_profile="RED_FRUIT", dosage_pct=0.5,
                          annual_volume_kg=200,
                          cost_in_use_cap_cents_per_tonne=90000)
    create_brief(api, brief_code="BRF-0003", customer_name="Alpine Snacks",
                 matrix_type="SAVOURY_SNACK", target_profile="SAVOURY_UMAMI",
                 dosage_pct=0.2, annual_volume_kg=3000,
                 cost_in_use_cap_cents_per_tonne=70000)
    get_success_data(api.submit_customer_brief(second["id"], ACCOUNT_MANAGER), 200)

    response = api.list_customer_briefs(TECHNICAL_DIRECTOR,
                                        {"status": "DRAFT", "limit": 1, "offset": 0})
    rows, meta = validate_paginated(response)

    assert len(rows) == 1
    assert rows[0]["id"] == first["id"]
    assert_pagination_meta(meta, limit=1, offset=0, total_count=2, has_more=True)
    assert all(row["status"] != "SUBMITTED" for row in rows)


def test_formula_get_with_unknown_id_returns_formula_not_found(api):
    """A well-shaped id that resolves to nothing is ERR_FORMULA_NOT_FOUND.

    The PRD gives each path identifier "its own not-found error, all reported
    with HTTP 404", listing `ERR_FORMULA_NOT_FOUND` for `formula_id`, and the
    error envelope carries `response_type` "error" with the code at
    `data.error_id`.

    Design: Corner/entities/formula_get_with_unknown_id_returns_formula_not_found
    """
    response = api.get_formula(UNKNOWN_UUIDS["formula"], FLAVORIST)

    validate_error(response, ApiErrorId.ERR_FORMULA_NOT_FOUND.value, 404)
    assert response.json()["response_type"] == "error"


def test_raw_material_missing_cost_per_kg_cents_rejected(api):
    """A material without its list price never reaches the catalogue.

    Section 3.2 requires "a list price `cost_per_kg_cents` of at least 1 cent
    per kilogram" on registration, and §2.11 step 4 rejects a body where a
    required field is absent with `ERR_INVALID_REQUEST`.

    Design: Corner/entities/raw_material_missing_cost_per_kg_cents_rejected
    """
    payload = create_raw_material_payload()
    payload.pop("cost_per_kg_cents")

    response = api.create_raw_material(payload, PURCHASING_MANAGER)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    body = list_data(api, api.list_raw_materials, PURCHASING_MANAGER)
    assert body["meta"]["total_count"] == 0


def test_brief_claim_flags_and_exclusions_take_declared_defaults(api):
    """Omitting the four optional label constraints yields false / false / false / [].

    Section 3.1: "`natural_claim_required`, `kosher_required` and
    `halal_required` each default to false when omitted, and
    `allergen_exclusions` defaults to an empty array".

    Design: Corner/entities/brief_claim_flags_and_exclusions_take_declared_defaults
    """
    brief = create_brief(api, brief_code="BRF-0001")

    assert brief["natural_claim_required"] is False
    assert brief["kosher_required"] is False
    assert brief["halal_required"] is False
    assert brief["allergen_exclusions"] == []


def test_raw_material_system_fields_input_ignored(api):
    """Client-supplied id, created_at, version and claim_status are not honoured.

    The PRD reserves those fields for the server: "Every resource is identified
    by an `id` that the server mints as a UUID", "`version` is an integer that
    starts at 1 when the resource is created", and of the material's derived
    pair, "Two of a material's fields are derived rather than entered", with
    "A newly registered material starts with `claim_status` reading `CLEAR` and
    `verified_claim_types` empty".  Section 2.11 step 4 confines request-shape
    rejection to missing required fields and values that violate their declared
    type, enum, range, subset or decimal-place constraints, so a body carrying
    server-owned fields is still accepted.

    Design: Corner/entities/raw_material_system_fields_input_ignored
    """
    response = api.create_raw_material(
        create_raw_material_payload(
            id="00000000-0000-4000-8000-0000000000ff",
            created_at="1999-01-01T00:00:00Z",
            version=77,
            claim_status="RESTRICTED"),
        PURCHASING_MANAGER)
    material = get_success_data(response, 201)

    assert material["id"] != "00000000-0000-4000-8000-0000000000ff"
    assert material["created_at"] != "1999-01-01T00:00:00Z"
    assert material["version"] == 1
    assert material["claim_status"] == "CLEAR"
    assert material["verified_claim_types"] == []


def test_raw_material_invalid_natural_status_enum_rejected(api):
    """ORGANIC is outside the declared natural_status enumeration.

    Section 3.2 fixes the enumeration as "a `natural_status` drawn from
    `NATURAL`, `NATURAL_FLAVOR_WONF`, `NATURE_IDENTICAL` and `ARTIFICIAL`", and
    §2.11 step 4 rejects a value outside its declared enum membership with
    `ERR_INVALID_REQUEST`.

    Design: Corner/entities/raw_material_invalid_natural_status_enum_rejected
    """
    response = api.create_raw_material(
        create_raw_material_payload(natural_status="ORGANIC"), PURCHASING_MANAGER)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    body = list_data(api, api.list_raw_materials, PURCHASING_MANAGER)
    assert body["meta"]["total_count"] == 0


def test_formula_create_with_unknown_brief_id_not_found(api):
    """A dangling brief_id in the body reports the brief's own not-found code.

    The PRD applies the path not-found codes to body references too: "The same
    not-found errors are used for identifiers supplied inside a request body or
    a query string rather than in the path ... a dangling reference is reported
    with the not-found error of the entity type that was expected.  This
    applies to ... formula creation".

    Design: Corner/entities/formula_create_with_unknown_brief_id_not_found
    """
    response = api.create_formula(
        create_formula_payload(UNKNOWN_UUIDS["brief"]), FLAVORIST)
    validate_error(response, ApiErrorId.ERR_BRIEF_NOT_FOUND.value, 404)

    body = list_data(api, api.list_formulas, FLAVORIST)
    assert body["meta"]["total_count"] == 0


def test_sub_formula_component_priced_through_the_dag(api):
    """The sub-formula line is priced from the child's own bench cost.

    Section 3.4: "For a `RAW_MATERIAL` line the unit price is the referenced
    material's `cost_per_kg_cents`; for a `SUB_FORMULA` line it is the
    referenced formula's own `bench_cost_per_kg_cents`, already resolved.  The
    line's `contribution_cents` is that unit price multiplied by the line's
    `weight_pct`, divided by 100, and rounded half up".  Both halves of the
    parent therefore contribute 2000 x 50 / 100 = 1000, summing to 2000, and
    the bench cost-in-use is 2000 x 1.0000 x 10 = 20000.

    Design: Corner/entities/sub_formula_component_priced_through_the_dag
    """
    material = create_material(api, material_code="GUM-BASE")
    brief = create_accepted_brief(api, brief_code="BRF-0001")

    sub = create_formula(api, brief["id"], name="Vanilla Base SF")
    add_material_line(api, sub["id"], material["id"], 100.0)
    costed_sub = cost_formula(api, sub["id"])
    assert costed_sub["bench_cost_per_kg_cents"] == 2000
    assert costed_sub["status"] == "COSTED"

    parent = create_formula(api, brief["id"], name="Vanilla Cream F1")
    sub_line = add_sub_formula_line(api, parent["id"], sub["id"], 50.0)
    raw_line = add_material_line(api, parent["id"], material["id"], 50.0)

    costed_parent = cost_formula(api, parent["id"])

    assert read_component(api, sub_line["id"])["contribution_cents"] == 1000
    assert read_component(api, raw_line["id"])["contribution_cents"] == 1000
    assert costed_parent["bench_cost_per_kg_cents"] == 2000
    assert costed_parent["bench_cost_in_use_cents_per_tonne"] == 20000
    assert costed_parent["component_count"] == 2
    assert float(costed_parent["total_weight_pct"]) == 100.0
    assert costed_parent["status"] == "COSTED"

    body = list_data(api, api.list_formula_components, FLAVORIST,
                     sub_formula_id=sub["id"])
    assert body["meta"]["total_count"] == 1
    assert body["data"][0]["id"] == sub_line["id"]


def test_sub_formula_self_reference_rejected(api):
    """A formula may not stand as its own ingredient.

    Section 3.3: "A sub-formula line is refused when the referenced formula is
    the parent formula itself, and equally when the referenced formula
    transitively contains the parent formula anywhere below it.  Either case is
    `ERR_FORMULA_CYCLE`."

    Design: Corner/entities/sub_formula_self_reference_rejected
    """
    material = create_material(api, material_code="GUM-BASE")
    brief = create_accepted_brief(api, brief_code="BRF-0001")
    formula = create_formula(api, brief["id"], name="Vanilla Cream F1")
    add_material_line(api, formula["id"], material["id"], 100.0)
    cost_formula(api, formula["id"])

    response = api.add_formula_component(
        formula["id"], sub_formula_component_payload(formula["id"], 10.0), FLAVORIST)
    validate_error(response, ApiErrorId.ERR_FORMULA_CYCLE.value, 422)

    unchanged = read_formula(api, formula["id"])
    assert unchanged["component_count"] == 1
    assert float(unchanged["total_weight_pct"]) == 100.0
    assert unchanged["status"] == "COSTED"


def test_formula_parent_from_another_brief_rejected(api):
    """A revision lineage may not cross briefs.

    Section 3.3: "`parent_formula_id` names the iteration this formula revises
    and is left out for the first attempt at a brief; when it is supplied it
    must name a formula belonging to the same brief, and naming a formula from a
    different brief is rejected with `ERR_PARENT_FORMULA_MISMATCH`."

    Design: Corner/entities/formula_parent_from_another_brief_rejected
    """
    first = create_accepted_brief(api, brief_code="BRF-0001")
    second = create_accepted_brief(api, brief_code="BRF-0002",
                                   customer_name="Alpine Snacks",
                                   matrix_type="SAVOURY_SNACK",
                                   target_profile="SAVOURY_UMAMI",
                                   dosage_pct=0.2, annual_volume_kg=3000,
                                   cost_in_use_cap_cents_per_tonne=70000)
    foreign = create_formula(api, second["id"], name="Umami Snack F1")

    response = api.create_formula(
        create_formula_payload(first["id"], name="Vanilla Cream F2",
                               parent_formula_id=foreign["id"]),
        FLAVORIST)
    validate_error(response, ApiErrorId.ERR_PARENT_FORMULA_MISMATCH.value, 422)

    body = list_data(api, api.list_formulas, FLAVORIST, brief_id=first["id"])
    assert body["meta"]["total_count"] == 0
