"""Certification's mandatory battery, the rework allowance, the global uniqueness
of business codes, and the pack membership and approval gates."""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_lot,
    api_client,
    assert_specimen_ledger,
    claimant_payload,
    create_claimant,
    create_furnace,
    create_pack,
    create_program,
    create_sku,
    heat_treat_furnace_payload,
    pack_member_payload,
    production_lot_payload,
    read_lot,
    read_pack,
    rework_payload,
    schedule_test_run,
    setup_lot_at_stage,
    submit_results,
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

FAILING_HARDNESS = (40.0, 41.0)
PASSING_HARDNESS = (52.0, 53.0)
FIRST_SLOT = ("2026-08-03T08:00:00Z", "2026-08-03T09:00:00Z")
SECOND_SLOT = ("2026-08-04T08:00:00Z", "2026-08-04T09:00:00Z")
THIRD_SLOT = ("2026-08-05T08:00:00Z", "2026-08-05T09:00:00Z")

BRANDED_SOCKET = {
    "sku_code": "SO-20-BR",
    "tool_family": "SOCKET",
    "channel": "BRANDED",
    "nominal_size_mm": 20,
    "alloy_grade": "CR_V",
    "list_price_cents": 1500,
    "warranty_tier": "LIFETIME",
}
PROFESSIONAL_WRENCH = {
    "sku_code": "WR-17-PR",
    "tool_family": "WRENCH",
    "channel": "PROFESSIONAL",
    "nominal_size_mm": 17,
    "alloy_grade": "CR_MO",
    "list_price_cents": 4200,
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


# ---------------------------------------------------------------------------
# The mandatory battery
# ---------------------------------------------------------------------------


def test_one_passing_hardness_run_does_not_certify_a_wrench_lot():
    """The metal is assembled and the pooled index is comfortably above the 51.0
    floor, but three of the four wrench tests have no passing run at all.

    PRD §3.5: "Next, every test type in the mandatory battery for the SKU's
    `tool_family` must have at least one `PASSED` run on this lot, and a gap is
    `ERR_MANDATORY_TEST_MISSING`."

    Design: Corner/validations/certification_requires_every_mandatory_test_for_the_family
    """
    ctx = setup_lot_at_stage("ASSEMBLED", lot_overrides={"specimen_pool_total": 20})
    lot_id = ctx["lot"]["id"]
    run = schedule_test_run(lot_id, "HARDNESS", 2, FIRST_SLOT)
    resolved = submit_results(run["id"], PASSING_HARDNESS)
    assert resolved["status"] == "PASSED"

    before = read_lot(lot_id)
    assert before["hardness_index_pooled"] == pytest.approx(52.50, abs=0.01)

    validate_error(
        api_client.certify_production_lot(lot_id, QE),
        ApiErrorId.ERR_MANDATORY_TEST_MISSING,
        422,
    )

    after = read_lot(lot_id)
    assert after["cert_status"] == "IN_TEST"
    assert after["certified_at"] is None


# ---------------------------------------------------------------------------
# The rework allowance
# ---------------------------------------------------------------------------


def _assembled_lot_of_forty_specimens():
    return setup_lot_at_stage("ASSEMBLED", lot_overrides={"specimen_pool_total": 40})


def test_rework_returns_all_three_dimensions_and_discards_the_metallurgy():
    """A rejected lot goes back to DRAFT, loses its quarantine, drops from ASSEMBLED
    to MACHINED and forgets the index its passing run had established.

    PRD §3.5: "Both hardness indices are reset to null, discarding the dossier's
    metallurgical history, and `rework_cycle_count` increments."

    Design: Corner/validations/rework_allowance_exhausts_after_two_cycles
    """
    ctx = _assembled_lot_of_forty_specimens()
    lot_id = ctx["lot"]["id"]
    submit_results(schedule_test_run(lot_id, "HARDNESS", 2, FIRST_SLOT)["id"], PASSING_HARDNESS)
    assert read_lot(lot_id)["hardness_index_sample"] == pytest.approx(52.50, abs=0.01)

    submit_results(schedule_test_run(lot_id, "HARDNESS", 2, SECOND_SLOT)["id"], FAILING_HARDNESS)
    rejected = read_lot(lot_id)
    assert rejected["cert_status"] == "REJECTED"
    assert rejected["disposition"] == "QUARANTINED"

    reworked = validate_success(
        api_client.rework_production_lot(
            lot_id, rework_payload(rework_note="Re-machine and re-plate, cycle 1"), PP
        )
    )

    assert reworked["cert_status"] == "DRAFT"
    assert reworked["disposition"] == "IN_PROCESS"
    assert reworked["process_status"] == "MACHINED"
    assert reworked["rework_cycle_count"] == 1
    assert reworked["hardness_index_sample"] is None
    assert reworked["hardness_index_pooled"] is None
    assert_specimen_ledger(reworked)


def test_the_third_rework_is_refused_and_leaves_the_lot_scrap():
    """Two completed cycles exhaust the allowance, so the third attempt changes
    nothing and the lot stays rejected and quarantined.

    PRD §3.5: "The dossier must be `REJECTED`, otherwise
    `ERR_LOT_CERT_STATE_INVALID`, and `rework_cycle_count` must still be below the
    rework limit of two completed cycles, otherwise `ERR_REWORK_LIMIT_EXCEEDED` — a
    lot that has already been reworked twice is scrap."

    Design: Corner/validations/rework_allowance_exhausts_after_two_cycles
    """
    ctx = _assembled_lot_of_forty_specimens()
    lot_id = ctx["lot"]["id"]

    for cycle, slot in enumerate((FIRST_SLOT, SECOND_SLOT, THIRD_SLOT), start=1):
        submit_results(schedule_test_run(lot_id, "HARDNESS", 2, slot)["id"], FAILING_HARDNESS)
        assert read_lot(lot_id)["cert_status"] == "REJECTED"
        if cycle == 3:
            break
        accepted = validate_success(
            api_client.rework_production_lot(
                lot_id, rework_payload(rework_note=f"Re-machine and re-plate, cycle {cycle}"), PP
            )
        )
        assert accepted["rework_cycle_count"] == cycle
        advance_lot(lot_id, "PLATED")

    validate_error(
        api_client.rework_production_lot(
            lot_id, rework_payload(rework_note="Re-machine and re-plate, cycle 3"), PP
        ),
        ApiErrorId.ERR_REWORK_LIMIT_EXCEEDED,
        409,
    )

    lot = read_lot(lot_id)
    assert lot["rework_cycle_count"] == 2
    assert lot["cert_status"] == "REJECTED"
    assert lot["disposition"] == "QUARANTINED"
    assert lot["specimens_consumed"] == 6
    assert lot["specimens_available"] == 34
    assert_specimen_ledger(lot)


# ---------------------------------------------------------------------------
# Business codes are unique per column, globally
# ---------------------------------------------------------------------------


def _one_of_every_coded_row():
    sku = create_sku()
    furnace = create_furnace()
    program = create_program()
    claimant = create_claimant()
    return sku, furnace, program, claimant


def test_repeating_any_business_code_is_refused_and_creates_nothing():
    """A SKU code, a furnace code, a programme code and a claimant email are each
    unique across their own column no matter what else the payload says.

    PRD §3.1: "Reusing a `sku_code` — or any other globally unique business code,
    namely `lot_code`, `furnace_code`, `chamber_code`, `pack_code`, `program_code`
    and a claimant's `email` — is refused with `ERR_DUPLICATE_CODE`."

    Design: Corner/validations/unique_codes_enforced_across_every_coded_entity
    """
    _one_of_every_coded_row()

    repeats = [
        api_client.create_tool_sku(
            tool_sku_payload(
                sku_code="WR-17-BR",
                tool_family="SOCKET",
                channel="PROFESSIONAL",
                nominal_size_mm=20,
                alloy_grade="CR_V",
                list_price_cents=1500,
            ),
            CM,
        ),
        api_client.create_heat_treat_furnace(
            heat_treat_furnace_payload(
                furnace_code="FCE-1", max_charge_kg=400, alloy_grades_supported=["S2"]
            ),
            PP,
        ),
        api_client.create_warranty_program(
            warranty_program_payload(
                program_code="LIFETIME-1", reserve_funded_cents=100, fraud_score_threshold=5
            ),
            WA,
        ),
        api_client.create_claimant(
            claimant_payload(email="c1@example.com", claimant_type="PRO_ACCOUNT"), WA
        ),
    ]
    for response in repeats:
        validate_error(response, ApiErrorId.ERR_DUPLICATE_CODE, 409)

    for lister in (
        lambda: api_client.list_tool_skus(CM),
        lambda: api_client.list_heat_treat_furnaces(PP),
        lambda: api_client.list_warranty_programs(WA),
        lambda: api_client.list_claimants(WA),
    ):
        _, meta = validate_paginated(lister())
        assert meta["total_count"] == 1


def test_the_same_string_may_be_a_lot_code_and_a_sku_code_at_once():
    """Uniqueness is scoped to the column, not to the string, so a lot may borrow
    an existing SKU's code.

    PRD §3.2: "A `ProductionPlanner` opens one against a SKU by supplying that
    `sku_id`, a `lot_code` unique across all lots, a `unit_count` of at least one
    finished unit, and a `specimen_pool_total` of at least one — the
    destructive-test specimens drawn from the lot, a figure that is immutable once
    the lot exists."

    Design: Corner/validations/unique_codes_enforced_across_every_coded_entity
    """
    sku, _, _, _ = _one_of_every_coded_row()

    lot = validate_success(
        api_client.create_production_lot(
            production_lot_payload(
                sku["id"], lot_code="WR-17-BR", unit_count=100, specimen_pool_total=10
            ),
            PP,
        ),
        201,
    )

    assert lot["lot_code"] == "WR-17-BR"
    assert lot["lot_code"] == sku["sku_code"]
    assert lot["process_status"] == "FORGED"


# ---------------------------------------------------------------------------
# Pack membership
# ---------------------------------------------------------------------------


def _branded_pack_with_one_member():
    hero = create_sku()
    partner = create_sku(**BRANDED_SOCKET)
    pack = create_pack(hero["id"], pack_code="PK-RD-1", pack_type="RETAIL_DISPLAY")
    validate_success(api_client.add_pack_member(pack["id"], pack_member_payload(hero["id"], 2), CM), 201)
    return hero, partner, pack


def test_a_sku_may_not_be_listed_twice_in_the_same_pack():
    """The hero SKU is already a member, so appending it again is a duplicate rather
    than a second line.

    PRD §3.6: "A SKU may appear at most once among a pack's members, and a repeat is
    `ERR_DUPLICATE_PACK_MEMBER`."

    Design: Corner/validations/pack_membership_rejects_duplicate_sku_and_mixed_channel
    """
    hero, _, pack = _branded_pack_with_one_member()

    validate_error(
        api_client.add_pack_member(pack["id"], pack_member_payload(hero["id"], 1), CM),
        ApiErrorId.ERR_DUPLICATE_PACK_MEMBER,
        409,
    )

    assert read_pack(pack["id"])["distinct_member_count"] == 1


@pytest.mark.parametrize(
    "foreign_sku", [PROFESSIONAL_WRENCH, PRIVATE_LABEL_PLIER], ids=["professional", "private_label"]
)
def test_a_pack_holds_exactly_one_commercial_channel(foreign_sku):
    """The rule is one channel per pack rather than mere professional isolation, so
    both a professional and a private-label member are refused from a branded pack.

    PRD §3.6: "All members must share a single commercial channel — a
    `PROFESSIONAL` tool may not be packed alongside a `BRANDED` or `PRIVATE_LABEL`
    one — and a member whose `channel` differs from the channel already established
    for the pack is refused with `ERR_CHANNEL_MIX_FORBIDDEN`."

    Design: Corner/validations/pack_membership_rejects_duplicate_sku_and_mixed_channel
    """
    _, _, pack = _branded_pack_with_one_member()
    outsider = create_sku(**foreign_sku)

    validate_error(
        api_client.add_pack_member(pack["id"], pack_member_payload(outsider["id"], 1), CM),
        ApiErrorId.ERR_CHANNEL_MIX_FORBIDDEN,
        422,
    )

    assert read_pack(pack["id"])["distinct_member_count"] == 1


def test_a_second_member_of_the_same_channel_is_accepted_and_priced_at_list():
    """Three sockets at 1500 cents extend to 4500 in a display carton, and the pack
    now lists two members.

    PRD §3.6: "The discount is 1.00 for `RETAIL_DISPLAY` and for `SECURITY` — those
    formats are sold at list — and 0.88 for `MULTIPACK`, the twelve-percent volume
    concession that makes a multipack worth buying."

    Design: Corner/validations/pack_membership_rejects_duplicate_sku_and_mixed_channel
    """
    _, partner, pack = _branded_pack_with_one_member()

    line = validate_success(
        api_client.add_pack_member(pack["id"], pack_member_payload(partner["id"], 3), CM), 201
    )

    assert line["line_extended_cents"] == 4500

    assert read_pack(pack["id"])["distinct_member_count"] == 2
    _, meta = validate_paginated(api_client.list_pack_members(pack["id"], CM))
    assert meta["total_count"] == 2


# ---------------------------------------------------------------------------
# Pack approval: the member gate runs ahead of the shape gate
# ---------------------------------------------------------------------------


def test_an_empty_multipack_is_refused_on_its_shape_alone():
    """With no members the certification gate is vacuously satisfied, so the only
    live fault is the multipack's two-member minimum.

    PRD §3.6: "a `MULTIPACK` must have at least 2 members and a total `quantity`
    across all members of at least 3. A violation is `ERR_PACK_CONFIG_INVALID`."

    Design: Corner/validations/pack_approval_certification_gate_masks_the_shape_gate
    """
    sku = create_sku()
    pack = create_pack(sku["id"], pack_code="PK-MP-1", pack_type="MULTIPACK")

    validate_error(
        api_client.approve_pack_configuration(pack["id"], CM),
        ApiErrorId.ERR_PACK_CONFIG_INVALID,
        422,
    )

    unchanged = read_pack(pack["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["security_surcharge_cents"] == 0
    assert unchanged["pack_total_cents"] == 0


def test_a_single_uncertified_member_masks_the_still_broken_shape():
    """Appending one member leaves the multipack shape invalid, yet the reported
    fault switches to the uncertified member because that gate runs first.

    PRD §3.6: "Every member SKU must have at least one production lot whose
    `cert_status` is `CERTIFIED`, since untested product cannot go on a shelf; a
    member without one is `ERR_MEMBER_SKU_NOT_CERTIFIED`, and the check is
    vacuously satisfied by a pack with no members at all."

    Design: Corner/validations/pack_approval_certification_gate_masks_the_shape_gate
    """
    sku = create_sku()
    pack = create_pack(sku["id"], pack_code="PK-MP-1", pack_type="MULTIPACK")
    validate_success(api_client.add_pack_member(pack["id"], pack_member_payload(sku["id"], 1), CM), 201)

    body = validate_error(
        api_client.approve_pack_configuration(pack["id"], CM),
        ApiErrorId.ERR_MEMBER_SKU_NOT_CERTIFIED,
        409,
    )
    assert body["error_id"] != ApiErrorId.ERR_PACK_CONFIG_INVALID

    unchanged = read_pack(pack["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["distinct_member_count"] == 1
    assert unchanged["pack_total_cents"] == 0
