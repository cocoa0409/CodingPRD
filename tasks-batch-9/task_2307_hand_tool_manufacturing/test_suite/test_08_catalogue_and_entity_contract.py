"""The entity contract: computed defaults on creation, the pinned lot snapshot,
paging, the per-entity not-found family, required fields, type constraints,
immutable lines and the pack-membership junction."""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    add_pack_member,
    api_client,
    assert_immutable_row_fields,
    assert_production_lot,
    assert_specimen_ledger,
    assert_tool_sku,
    claim_line_payload,
    claimant_payload,
    create_furnace,
    create_lot,
    create_pack,
    create_sku,
    furnace_campaign_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    pack_member_payload,
    production_lot_payload,
    read_pack,
    set_clock,
    setup_warranty_scenario,
    tool_sku_payload,
    validate_error,
    validate_paginated,
    validate_success,
    warranty_program_payload,
)

CM = TEST_USERS["channel_manager_headers"]
PP = TEST_USERS["production_planner_headers"]
QE = TEST_USERS["quality_engineer_headers"]
WA = TEST_USERS["warranty_administrator_headers"]
BP = TEST_USERS["brand_protection_analyst_headers"]

BRANDED_SOCKET = {
    "sku_code": "SO-20-BR",
    "tool_family": "SOCKET",
    "channel": "BRANDED",
    "nominal_size_mm": 20,
    "alloy_grade": "CR_V",
    "list_price_cents": 1500,
    "warranty_tier": "LIFETIME",
}
PRIVATE_LABEL_PLIER = {
    "sku_code": "PL-10-PL",
    "tool_family": "PLIER",
    "channel": "PRIVATE_LABEL",
    "nominal_size_mm": 10,
    "alloy_grade": "S2",
    "list_price_cents": 900,
    "warranty_tier": "LIMITED_5Y",
}
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Creation, retrieval and system fields
# ---------------------------------------------------------------------------


def test_registering_a_wrench_pins_its_torque_bar_and_zeroes_every_counter():
    """One POST with the seven required inputs returns 201, the derived 115.8 Nm
    acceptance bar, an OPEN posture and eight counters at zero.

    PRD §3.1: "Four unit counters and four brand-protection fields round out the
    catalogue row, and all eight are server-derived."

    Design: Corner/entities/create_tool_sku_returns_computed_defaults_and_version_one
    """
    created = validate_success(api_client.create_tool_sku(tool_sku_payload(), CM), 201)

    assert_tool_sku(created)
    assert created["sku_code"] == "WR-17-BR"
    assert created["tool_family"] == "WRENCH"
    assert created["channel"] == "BRANDED"
    assert created["nominal_size_mm"] == 17
    assert created["alloy_grade"] == "CR_MO"
    assert created["list_price_cents"] == 3300
    assert created["warranty_tier"] == "LIFETIME"
    assert created["proof_torque_required_nm"] == pytest.approx(115.8, abs=0.01)

    assert created["warranty_posture"] == "OPEN"
    assert created["brand_risk_score"] == 0
    assert created["confirmed_counterfeit_count"] == 0
    assert created["units_received_total"] == 0
    assert created["units_on_hand"] == 0
    assert created["units_reserved"] == 0
    assert created["units_shipped"] == 0
    assert created["lineage_depth"] == 0
    assert created["supersedes_sku_id"] is None
    assert created["version"] == 1


def test_fetching_a_fresh_lot_shows_its_pinned_bar_and_untouched_ledger():
    """A lot copies the acceptance bar from its SKU at opening and starts with
    every specimen available, all three dimensions at their initial values and
    both hardness indices null.

    PRD §3.2: "The new lot begins with `process_status` `FORGED`, `cert_status`
    `DRAFT` and `disposition` `IN_PROCESS`; `specimens_available` equals
    `specimen_pool_total` while `specimens_committed` and `specimens_consumed`
    are zero; `rework_cycle_count` is zero; `hardness_index_sample` and
    `hardness_index_pooled` are both null; `certified_at` is null; and
    `proof_torque_required_nm` is copied from the parent SKU so that later
    catalogue amendments cannot move this lot's acceptance bar."

    Design: Corner/entities/retrieve_production_lot_returns_pinned_and_ledger_fields
    """
    sku = create_sku()
    lot = create_lot(sku["id"], lot_code="LOT-BR-A", unit_count=500, specimen_pool_total=40)

    fetched = validate_success(api_client.get_production_lot(lot["id"], QE))

    assert_production_lot(fetched)
    assert fetched["sku_id"] == sku["id"]
    assert fetched["lot_code"] == "LOT-BR-A"
    assert fetched["unit_count"] == 500
    assert fetched["specimen_pool_total"] == 40
    assert fetched["proof_torque_required_nm"] == pytest.approx(115.8, abs=0.01)
    assert fetched["specimens_available"] == 40
    assert fetched["specimens_committed"] == 0
    assert fetched["specimens_consumed"] == 0
    assert fetched["process_status"] == "FORGED"
    assert fetched["cert_status"] == "DRAFT"
    assert fetched["disposition"] == "IN_PROCESS"
    assert fetched["hardness_index_sample"] is None
    assert fetched["hardness_index_pooled"] is None
    assert fetched["certified_at"] is None
    assert fetched["rework_cycle_count"] == 0
    assert_specimen_ledger(fetched)


def test_a_new_claimant_arrives_with_its_system_fields_at_the_declared_defaults():
    """The client supplies only an address and a type; the status, both fraud
    scores, the lifetime counter and the timestamps are all server-minted.

    PRD §3.7: "A claimant starts `ACTIVE` with `fraud_risk_score_intake`,
    `fraud_risk_score_adjudication` and `lifetime_claim_count` all zero."

    Design: Corner/entities/system_fields_generated_on_claimant_creation
    """
    set_clock(DEFAULT_CLOCK)

    created = validate_success(api_client.create_claimant(claimant_payload(), WA), 201)

    assert is_valid_uuid(created["id"])
    assert created["email"] == "c1@example.com"
    assert created["claimant_type"] == "CONSUMER"
    assert created["status"] == "ACTIVE"
    assert created["fraud_risk_score_intake"] == 0
    assert created["fraud_risk_score_adjudication"] == 0
    assert created["lifetime_claim_count"] == 0
    assert created["version"] == 1
    assert is_iso8601_timestamp(created["created_at"])
    assert created["created_at"].startswith("2026-08-01T00:00:00")
    assert created["updated_at"].startswith("2026-08-01T00:00:00")


# ---------------------------------------------------------------------------
# Listing and pagination
# ---------------------------------------------------------------------------


def _three_catalogue_entries():
    """WR-17-BR, then SO-20-BR, then PL-10-PL, in that creation order."""
    return (
        create_sku(),
        create_sku(**BRANDED_SOCKET),
        create_sku(**PRIVATE_LABEL_PLIER),
    )


def test_the_catalogue_pages_in_creation_order_over_the_whole_filtered_set():
    """total_count spans the filtered set while data holds only the page, and
    has_more flips true then false as the last page is reached.

    PRD §2.3: "Every list response echoes `limit`, `offset`, `total_count` and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_tool_skus_paginates_and_rejects_bad_pagination
    """
    sku1, sku2, sku3 = _three_catalogue_entries()

    first, meta = validate_paginated(api_client.list_tool_skus(CM, params={"limit": 2, "offset": 0}))
    assert len(first) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert [row["id"] for row in first] == [sku1["id"], sku2["id"]]

    second, meta = validate_paginated(
        api_client.list_tool_skus(CM, params={"limit": 2, "offset": 2})
    )
    assert len(second) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert second[0]["id"] == sku3["id"]

    branded, meta = validate_paginated(api_client.list_tool_skus(CM, params={"channel": "BRANDED"}))
    assert len(branded) == 2
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


@pytest.mark.parametrize("params", [{"limit": 0}, {"offset": -1}])
def test_an_out_of_bounds_page_request_is_refused_rather_than_clamped(params):
    """A limit below one and a negative offset are both faults, not values to be
    silently corrected.

    PRD §2.3: "A `limit` outside 1 through 100, or a negative `offset`, is
    rejected with `ERR_INVALID_PAGINATION`."

    Design: Corner/entities/list_tool_skus_paginates_and_rejects_bad_pagination
    """
    _three_catalogue_entries()

    validate_error(
        api_client.list_tool_skus(CM, params=params),
        ApiErrorId.ERR_INVALID_PAGINATION,
        400,
    )


# ---------------------------------------------------------------------------
# The not-found family
# ---------------------------------------------------------------------------


NOT_FOUND_PROBES = [
    ("tool_sku", lambda: api_client.get_tool_sku(NON_EXISTENT_UUID, CM),
     ApiErrorId.ERR_TOOL_SKU_NOT_FOUND),
    ("production_lot", lambda: api_client.get_production_lot(NON_EXISTENT_UUID, PP),
     ApiErrorId.ERR_PRODUCTION_LOT_NOT_FOUND),
    ("furnace", lambda: api_client.get_heat_treat_furnace(NON_EXISTENT_UUID, PP),
     ApiErrorId.ERR_FURNACE_NOT_FOUND),
    ("campaign", lambda: api_client.get_furnace_campaign(NON_EXISTENT_UUID, PP),
     ApiErrorId.ERR_CAMPAIGN_NOT_FOUND),
    ("chamber", lambda: api_client.get_salt_spray_chamber(NON_EXISTENT_UUID, QE),
     ApiErrorId.ERR_CHAMBER_NOT_FOUND),
    ("test_run", lambda: api_client.get_test_run(NON_EXISTENT_UUID, QE),
     ApiErrorId.ERR_TEST_RUN_NOT_FOUND),
    ("pack_configuration", lambda: api_client.get_pack_configuration(NON_EXISTENT_UUID, CM),
     ApiErrorId.ERR_PACK_CONFIG_NOT_FOUND),
    ("warranty_program", lambda: api_client.get_warranty_program(NON_EXISTENT_UUID, WA),
     ApiErrorId.ERR_WARRANTY_PROGRAM_NOT_FOUND),
    ("claimant", lambda: api_client.get_claimant(NON_EXISTENT_UUID, WA),
     ApiErrorId.ERR_CLAIMANT_NOT_FOUND),
    ("warranty_claim", lambda: api_client.get_warranty_claim(NON_EXISTENT_UUID, WA),
     ApiErrorId.ERR_CLAIM_NOT_FOUND),
    ("counterfeit_report", lambda: api_client.get_counterfeit_report(NON_EXISTENT_UUID, BP),
     ApiErrorId.ERR_REPORT_NOT_FOUND),
]


@pytest.mark.parametrize(
    "entity,call,expected", NOT_FOUND_PROBES, ids=[probe[0] for probe in NOT_FOUND_PROBES]
)
def test_each_addressed_entity_answers_with_its_own_not_found_code(entity, call, expected):
    """Eleven single-resource routes resolve their path parameter against their
    own table and each names that table in the refusal.

    PRD §2.4: "The same family of codes applies to single-resource paths:
    `ERR_FURNACE_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_CHAMBER_NOT_FOUND`,
    `ERR_TEST_RUN_NOT_FOUND`, `ERR_WARRANTY_PROGRAM_NOT_FOUND`,
    `ERR_CLAIMANT_NOT_FOUND` and `ERR_REPORT_NOT_FOUND` are each returned when
    the addressed row of that entity does not exist."

    Design: Corner/entities/not_found_family_is_specific_to_the_addressed_entity
    """
    body = validate_error(call(), expected, 404)

    assert body["error_id"] == expected.value
    assert isinstance(body["message"], str) and body["message"]


# ---------------------------------------------------------------------------
# Request shape
# ---------------------------------------------------------------------------


def test_omitting_a_required_input_is_a_request_shape_fault_and_persists_nothing():
    """A missing alloy grade, a missing specimen pool and a missing fraud
    threshold are each ERR_INVALID_REQUEST, and no row survives the attempt.

    PRD §2.7: "a missing required field, a wrongly typed value, a number outside
    its declared range or an undeclared enum member is reported as
    `ERR_INVALID_REQUEST`, while the pagination, window and reading-length faults
    have their own identifiers"

    Design: Corner/entities/missing_required_input_fields_rejected_with_invalid_request
    """
    sku = create_sku()

    sku_payload = tool_sku_payload(sku_code="WR-19-BR", nominal_size_mm=19)
    sku_payload.pop("alloy_grade")
    validate_error(
        api_client.create_tool_sku(sku_payload, CM), ApiErrorId.ERR_INVALID_REQUEST, 400
    )

    lot_payload = production_lot_payload(sku["id"], lot_code="LOT-BR-B", unit_count=100)
    lot_payload.pop("specimen_pool_total")
    validate_error(
        api_client.create_production_lot(lot_payload, PP), ApiErrorId.ERR_INVALID_REQUEST, 400
    )

    program_payload = warranty_program_payload()
    program_payload.pop("fraud_score_threshold")
    validate_error(
        api_client.create_warranty_program(program_payload, WA),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    _, meta = validate_paginated(api_client.list_tool_skus(CM))
    assert meta["total_count"] == 1

    _, meta = validate_paginated(api_client.list_sku_production_lots(sku["id"], PP))
    assert meta["total_count"] == 0


def test_a_bad_enum_and_an_out_of_range_size_differ_from_a_zero_length_window():
    """Shape faults answer with ERR_INVALID_REQUEST while window ordering has its
    own dedicated identifier.

    PRD §3.2: "The interval is half-open: `window_start` is inclusive,
    `window_end` is exclusive, `window_end` must be strictly after
    `window_start`, and both must be whole-minute UTC instants — a violation of
    any of those is `ERR_INVALID_WINDOW`, reported before any state or business
    rule."

    Design: Corner/entities/enum_and_window_type_constraints_rejected
    """
    sku = create_sku()
    furnace = create_furnace()
    lot = create_lot(sku["id"], lot_code="LOT-BR-A", specimen_pool_total=20)

    validate_error(
        api_client.create_tool_sku(
            tool_sku_payload(sku_code="HM-01-BR", tool_family="HAMMER"), CM
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api_client.create_tool_sku(tool_sku_payload(sku_code="WR-99-BR", nominal_size_mm=81), CM),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api_client.create_furnace_campaign(
            furnace_campaign_payload(
                lot["id"],
                furnace["id"],
                window_start="2026-08-02T06:00:00Z",
                window_end="2026-08-02T06:00:00Z",
            ),
            PP,
        ),
        ApiErrorId.ERR_INVALID_WINDOW,
        400,
    )

    _, meta = validate_paginated(
        api_client.list_furnace_campaigns(PP, params={"lot_id": lot["id"]})
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Lineage defaults and recomputed derivations
# ---------------------------------------------------------------------------


def test_an_omitted_ancestor_leaves_a_null_lineage_at_depth_zero():
    """supersedes_sku_id is the only optional input, and leaving it out pins the
    derived depth to zero rather than leaving it null.

    PRD §3.1: "Private-label and professional variants are normally respins of an
    existing catalogue entry, and the optional `supersedes_sku_id` records that
    ancestry; it defaults to null."

    Design: Corner/entities/omitted_supersedes_sku_id_defaults_to_null_lineage_depth_zero
    """
    ancestor = create_sku()

    orphan = create_sku(sku_code="WR-17-BR-V2", list_price_cents=3600)
    assert orphan["supersedes_sku_id"] is None
    assert orphan["lineage_depth"] == 0

    successor = create_sku(
        sku_code="WR-17-BR-V3", list_price_cents=3900, supersedes_sku_id=ancestor["id"]
    )
    assert successor["supersedes_sku_id"] == ancestor["id"]
    assert successor["lineage_depth"] == 1

    rows, meta = validate_paginated(
        api_client.list_tool_skus(CM, params={"supersedes_sku_id": ancestor["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == successor["id"]


def test_amending_the_nominal_size_recomputes_only_that_skus_torque_bar():
    """The acceptance bar is never client-supplied: patching the size from 17 mm
    to 19 mm moves it from 115.8 to 129.4 while a sibling socket keeps its 203.0.

    PRD §3.1: "Amendment re-runs both derivations: `proof_torque_required_nm` is
    recomputed from the amended attributes and `lineage_depth` is re-walked with
    the same cycle-before-depth ordering, and the SKU's `version` increments."

    Design: Corner/entities/computed_proof_torque_recomputed_on_patch_not_client_supplied
    """
    wrench = create_sku()
    socket = create_sku(**BRANDED_SOCKET)
    assert wrench["proof_torque_required_nm"] == pytest.approx(115.8, abs=0.01)
    assert socket["proof_torque_required_nm"] == pytest.approx(203.0, abs=0.01)

    patched = validate_success(
        api_client.patch_tool_sku(wrench["id"], {"nominal_size_mm": 19}, CM)
    )

    assert patched["nominal_size_mm"] == 19
    assert patched["proof_torque_required_nm"] == pytest.approx(129.4, abs=0.01)
    assert patched["version"] == 2

    untouched = validate_success(api_client.get_tool_sku(socket["id"], CM))
    assert untouched["proof_torque_required_nm"] == pytest.approx(203.0, abs=0.01)


# ---------------------------------------------------------------------------
# Immutable child rows and the pack junction
# ---------------------------------------------------------------------------


def test_a_replacement_line_carries_no_version_and_no_updated_at():
    """The line is written once and the parent claim absorbs every later change,
    so the line exposes only an id and a creation instant.

    PRD §2.4: "Two resources are exceptions because they are immutable once
    written: a pack member line and a claim replacement line carry only `id` and
    `created_at`; neither `updated_at` nor `version` exists on them at all."

    Design: Corner/entities/claim_line_is_immutable_and_carries_no_version
    """
    ctx = setup_warranty_scenario(claim_overrides={"serial_code": "SN-0001"})

    line = validate_success(
        api_client.add_claim_line(ctx["claim"]["id"], claim_line_payload(), WA), 201
    )

    assert_immutable_row_fields(line)
    assert line["line_reserve_cents"] == 681
    assert "version" not in line
    assert "updated_at" not in line

    rows, meta = validate_paginated(api_client.list_claim_lines(ctx["claim"]["id"], WA))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == line["id"]

    claim = validate_success(api_client.get_warranty_claim(ctx["claim"]["id"], WA))
    assert claim["line_count"] == 1
    assert claim["reserve_charge_cents"] == 681


def test_a_membership_needs_both_an_existing_pack_and_an_existing_member_sku():
    """Each end of the association is resolved against its own table, so the two
    refusals name two different entities.

    PRD §2.4: "Identifiers supplied in a request body are checked with the same
    code as their entity: an unresolvable `sku_id`, `primary_sku_id` or
    `supersedes_sku_id` gives `ERR_TOOL_SKU_NOT_FOUND`, an unresolvable `lot_id`
    gives `ERR_PRODUCTION_LOT_NOT_FOUND`, `furnace_id` gives
    `ERR_FURNACE_NOT_FOUND`, `chamber_id` gives `ERR_CHAMBER_NOT_FOUND`,
    `claimant_id` gives `ERR_CLAIMANT_NOT_FOUND` and `program_id` gives
    `ERR_WARRANTY_PROGRAM_NOT_FOUND`."

    Design: Corner/entities/pack_member_requires_existing_parent_and_member_sku
    """
    sku = create_sku()
    pack = create_pack(sku["id"], pack_code="PK-RD-1", pack_type="RETAIL_DISPLAY")

    validate_error(
        api_client.add_pack_member(NON_EXISTENT_UUID, pack_member_payload(sku["id"], 2), CM),
        ApiErrorId.ERR_PACK_CONFIG_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.add_pack_member(pack["id"], pack_member_payload(NON_EXISTENT_UUID, 2), CM),
        ApiErrorId.ERR_TOOL_SKU_NOT_FOUND,
        404,
    )

    _, meta = validate_paginated(api_client.list_pack_members(pack["id"], CM))
    assert meta["total_count"] == 0
    assert read_pack(pack["id"])["distinct_member_count"] == 0


def test_one_sku_may_sit_in_two_packs_but_never_twice_in_the_same_pack():
    """The membership line is the junction of the catalogue graph: the pair of
    pack and SKU is what must be unique, not either end on its own.

    PRD §3.6: "A SKU may appear at most once among a pack's members, and a repeat
    is `ERR_DUPLICATE_PACK_MEMBER`."

    Design: Corner/entities/graph_topology_pack_membership_is_many_to_many
    """
    sku1 = create_sku()
    sku2 = create_sku(**BRANDED_SOCKET)
    pack1 = create_pack(sku1["id"], pack_code="PK-RD-1", pack_type="RETAIL_DISPLAY")
    pack2 = create_pack(sku1["id"], pack_code="PK-RD-2", pack_type="RETAIL_DISPLAY")

    member1 = add_pack_member(pack1["id"], sku1["id"], 2)
    member2 = add_pack_member(pack1["id"], sku2["id"], 3)
    member3 = add_pack_member(pack2["id"], sku1["id"], 1)

    validate_error(
        api_client.add_pack_member(pack1["id"], pack_member_payload(sku1["id"], 5), CM),
        ApiErrorId.ERR_DUPLICATE_PACK_MEMBER,
        409,
    )

    assert member1["line_extended_cents"] == 6600
    assert member2["line_extended_cents"] == 4500
    assert member3["line_extended_cents"] == 3300

    _, meta = validate_paginated(api_client.list_pack_members(pack1["id"], CM))
    assert meta["total_count"] == 2

    _, meta = validate_paginated(api_client.list_sku_pack_memberships(sku1["id"], CM))
    assert meta["total_count"] == 2

    pack = read_pack(pack1["id"])
    assert pack["distinct_member_count"] == 2
    assert pack["member_subtotal_cents"] == 11100
    assert pack["status"] == "DRAFT"
