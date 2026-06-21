"""Resource creation, retrieval, listing, input validation, and FK existence.

Covers the entity-surface claims: 201-on-create with default state, retrieval round-trip,
paginated listing, not-found on missing/dangling ids, required-field and enum validation,
computed-field population on create, system-field minting, and identity-entity immutability
(PRD §2.3-§2.8, §3.1-§3.5).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    assert_commodity_program, assert_policy, assert_coverage_election,
    assert_identity_entity,
    setup_program_and_parties, setup_policy_with_election, setup_election_with_unit,
    create_policy, register_selling_agent, register_producer,
    create_commodity_program_payload, create_coverage_election_payload,
    make_agent_headers, TEST_USERS, NONEXISTENT_FK_UUID,
)

RMA = TEST_USERS["rma_admin_headers"]


def test_create_commodity_program_returns_201_with_defaults(api):
    """PRD §3.1: "A newly created program begins with its status field set to DRAFT and
    harvest_price_published set to false; its harvest_price is null until discovery, and
    the program is not yet sellable."
    PRD §4: "operations that bring a brand-new resource into existence return 201 Created"

    Design: Corner/entities/create_commodity_program_returns_201_with_fields
    """
    res = api.create_commodity_program(
        create_commodity_program_payload(
            crop_code="WHEAT", county_code="20001", crop_year=2026,
            projected_price=6.50, base_premium_rate=0.09, pp_coverage_factor=0.55,
            final_planting_date="2026-04-30T00:00:00Z",
            acreage_reporting_deadline="2026-06-15T00:00:00Z"),
        RMA)
    prog = validate_success(res, 201)
    assert_commodity_program(prog)
    assert prog["status"] == "DRAFT", prog["status"]
    assert prog["harvest_price_published"] is False, prog["harvest_price_published"]


def test_get_policy_returns_stored_entity(api):
    """PRD §3.2: "An Agent then creates a policy for a producer by supplying the
    producer_id, the selling agent_id, and the crop_year the policy covers."

    Design: Corner/entities/get_policy_returns_stored_entity
    """
    ctx = setup_program_and_parties()
    policy = create_policy(ctx["producer"]["id"], ctx["sa"]["id"], ctx["sa_headers"])
    got = validate_success(api.get_policy(policy["id"], ctx["sa_headers"]), 200)
    assert_policy(got)
    assert got["producer_id"] == ctx["producer"]["id"]
    assert got["agent_id"] == ctx["sa"]["id"]


def test_list_commodity_programs_paginated(api):
    """PRD §2.3: "List responses always carry limit, offset, total_count, and has_more
    inside the meta object of the envelope."

    Design: Corner/entities/list_commodity_programs_paginated
    """
    api.create_commodity_program(create_commodity_program_payload(), RMA)
    data, meta = validate_paginated(api.list_commodity_programs(RMA, params={"limit": 10, "offset": 0}))
    assert meta["total_count"] >= 1, meta
    assert meta["has_more"] is False, meta


def test_get_nonexistent_policy_returns_not_found(api):
    """PRD §2.8: "each referenced resource id in the body ... is checked for existence, and
    a dangling reference yields ERR_NOT_FOUND."

    Design: Corner/entities/get_nonexistent_policy_returns_not_found
    """
    res = api.get_policy("00000000-0000-4000-8000-000000000000", RMA)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_election_missing_plan_type_rejected(api):
    """PRD §2.9: "then well-formedness of the request body — required fields present, enum
    values legal, coverage_level drawn from the allowed set, and numeric fields positive
    where positivity is required (ERR_INVALID_REQUEST)."

    Design: Corner/entities/create_coverage_election_missing_plan_type_returns_invalid_request
    """
    ctx = setup_program_and_parties()
    policy = create_policy(ctx["producer"]["id"], ctx["sa"]["id"], ctx["sa_headers"])
    res = api.create_coverage_election(
        {"policy_id": policy["id"], "commodity_program_id": ctx["program"]["id"],
         "aph_yield": 180, "coverage_level": 0.75},
        ctx["sa_headers"])
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_election_invalid_coverage_level_rejected(api):
    """PRD §3.3: "The coverage_level must be exactly one of 0.50, 0.55, 0.60, 0.65, 0.70,
    0.75, 0.80, or 0.85; any other value is malformed input."

    Design: Corner/entities/create_coverage_election_invalid_coverage_level_returns_invalid_request
    """
    ctx = setup_program_and_parties()
    policy = create_policy(ctx["producer"]["id"], ctx["sa"]["id"], ctx["sa_headers"])
    res = api.create_coverage_election(
        create_coverage_election_payload(policy["id"], ctx["program"]["id"],
                                         plan_type="YP", aph_yield=180, coverage_level=0.72),
        ctx["sa_headers"])
    validate_error(res, "ERR_INVALID_REQUEST")


def test_election_computed_fields_set_on_create(api):
    """PRD §3.3: "The `yield_guarantee_bu` — the guaranteed yield in bushels per acre — is
    the product of the `aph_yield` and the `coverage_level`, rounded to two decimal places.
    The `dollar_liability_per_acre_cents` is then the `yield_guarantee_bu` multiplied by the
    program's `projected_price`, that product multiplied by 100 to convert dollars to cents,
    and the whole rounded to a whole number of cents."
    PRD §3.4: "`0.75` maps to 0.55"

    Design: Corner/entities/coverage_election_computed_fields_set_on_create
    """
    ctx = setup_policy_with_election(plan_type="YP", aph_yield=180, coverage_level=0.75)
    elec = ctx["election"]
    assert_coverage_election(elec)
    # 180 * 0.75 = 135.0 ; 135 * 4.00 * 100 = 54000
    assert elec["yield_guarantee_bu"] == 135.0, elec["yield_guarantee_bu"]
    assert elec["dollar_liability_per_acre_cents"] == 54000, elec["dollar_liability_per_acre_cents"]
    assert elec["subsidy_factor"] == 0.55, elec["subsidy_factor"]


def test_policy_system_fields_minted_on_create(api):
    """PRD §2.4: "Each also has a version, an integer that begins at 1 on creation and
    increments by one on every mutation"
    PRD §3.2: "A new policy starts in DRAFT status with all of its ledger fields at zero:
    total_premium_cents, producer_premium_cents, subsidy_cents, total_indemnity_cents, and
    total_insured_acres."

    Design: Corner/entities/system_fields_generated_input_ignored
    """
    sa = register_selling_agent(license_number="SA-SYS")
    producer = register_producer(tax_id="TX-SYS")
    res = api.create_policy(
        {"producer_id": producer["id"], "agent_id": sa["id"], "crop_year": 2026},
        make_agent_headers(sa["id"]))
    policy = validate_success(res, 201)
    assert policy["version"] == 1, policy["version"]
    assert policy["status"] == "DRAFT", policy["status"]
    assert policy["total_premium_cents"] == 0, policy["total_premium_cents"]


def test_producer_has_no_version_field(api):
    """PRD §2.4: "A Producer and an Agent carry only an id and a created_at; they have
    neither an updated_at nor a version, because they are registered once and not
    subsequently mutated through this API."

    Design: Corner/entities/immutable_producer_has_no_version_field
    """
    res = api.create_producer({"name": "Producer Immutable", "tax_id": "C-P6"}, RMA)
    producer = validate_success(res, 201)
    assert_identity_entity(producer)
    assert "version" not in producer, "producer must not carry a version field"


def test_election_wrong_program_fk_returns_not_found(api):
    """PRD §2.8: "after path segments resolve, each referenced resource id in the body
    (such as a policy_id, commodity_program_id, ...) is checked for existence, and a
    dangling reference yields ERR_NOT_FOUND."

    Design: Corner/entities/coverage_election_wrong_program_fk_returns_not_found
    """
    sa = register_selling_agent(license_number="SA-FK")
    producer = register_producer(tax_id="TX-FK")
    sa_headers = make_agent_headers(sa["id"])
    policy = create_policy(producer["id"], sa["id"], sa_headers)
    res = api.create_coverage_election(
        {"policy_id": policy["id"], "commodity_program_id": NONEXISTENT_FK_UUID,
         "plan_type": "YP", "aph_yield": 180, "coverage_level": 0.75},
        sa_headers)
    validate_error(res, "ERR_NOT_FOUND")


def test_list_units_by_election_reverse_reachability(api):
    """PRD §4: "GET /coverage-elections/{id}/units — List units under an election"
    PRD §2.4: "Each has an id, a server-minted UUID with no type prefix."

    Design: Corner/entities/flat_fk_reverse_reachability_units_by_election
    """
    ctx = setup_election_with_unit(plan_type="YP", acres=100, share=1)
    data, meta = validate_paginated(
        api.list_election_units(ctx["election"]["id"], ctx["sa_headers"]))
    ids = [u["id"] for u in data]
    assert ctx["unit"]["id"] in ids, ids
