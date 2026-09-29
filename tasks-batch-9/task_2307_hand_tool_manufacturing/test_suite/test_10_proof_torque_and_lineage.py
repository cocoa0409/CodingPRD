"""The proof-torque derivation across every constant table, its industry band
clamps, and the supersession walk that derives lineage depth."""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_sku,
    read_sku,
    set_clock,
    tool_sku_payload,
    validate_error,
    validate_paginated,
)

CM = TEST_USERS["channel_manager_headers"]

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

WRENCH_BRANDED = {
    "sku_code": "WR-17-BR",
    "tool_family": "WRENCH",
    "channel": "BRANDED",
    "nominal_size_mm": 17,
    "alloy_grade": "CR_MO",
    "list_price_cents": 3300,
    "warranty_tier": "LIFETIME",
}
WRENCH_PROFESSIONAL = {
    "sku_code": "WR-17-PR",
    "tool_family": "WRENCH",
    "channel": "PROFESSIONAL",
    "nominal_size_mm": 17,
    "alloy_grade": "CR_MO",
    "list_price_cents": 4200,
    "warranty_tier": "LIFETIME",
}
SOCKET_BRANDED = {
    "sku_code": "SO-19-BR",
    "tool_family": "SOCKET",
    "channel": "BRANDED",
    "nominal_size_mm": 19,
    "alloy_grade": "CR_V",
    "list_price_cents": 1500,
    "warranty_tier": "LIFETIME",
}
PLIER_PRIVATE_LABEL = {
    "sku_code": "PL-10-PL",
    "tool_family": "PLIER",
    "channel": "PRIVATE_LABEL",
    "nominal_size_mm": 10,
    "alloy_grade": "S2",
    "list_price_cents": 900,
    "warranty_tier": "LIMITED_5Y",
}
TINY_PLIER = {
    "sku_code": "PL-04-PL",
    "tool_family": "PLIER",
    "channel": "PRIVATE_LABEL",
    "nominal_size_mm": 4,
    "alloy_grade": "CR_V",
    "list_price_cents": 500,
    "warranty_tier": "LIMITED_5Y",
}
GIANT_SOCKET = {
    "sku_code": "SO-80-PR",
    "tool_family": "SOCKET",
    "channel": "PROFESSIONAL",
    "nominal_size_mm": 80,
    "alloy_grade": "S2",
    "list_price_cents": 9900,
    "warranty_tier": "LIFETIME",
}

WRENCH_CHAIN_BASE = {
    "tool_family": "WRENCH",
    "channel": "BRANDED",
    "nominal_size_mm": 17,
    "alloy_grade": "CR_MO",
    "warranty_tier": "LIFETIME",
}


# ---------------------------------------------------------------------------
# The five-step derivation and its constant tables
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "attributes,expected_nm",
    [
        (WRENCH_BRANDED, 115.8),
        (WRENCH_PROFESSIONAL, 128.1),
        (SOCKET_BRANDED, 164.4),
        (PLIER_PRIVATE_LABEL, 36.4),
    ],
    ids=["wrench_branded", "wrench_professional", "socket_branded", "plier_private_label"],
)
def test_the_acceptance_bar_follows_the_family_alloy_channel_and_size_tables(
    attributes, expected_nm
):
    """Four SKUs differing only in the inputs the formula consumes pin the base
    rate, the alloy factor, the channel factor and the per-millimetre adder.

    PRD §3.1: "Step one takes a raw figure: a base torque per millimetre of
    nominal size — 4.2 newton-metres per millimetre for a `WRENCH`, 6.5 for a
    `SOCKET`, 2.8 for a `PLIER` — multiplied by `nominal_size_mm`, multiplied by
    an alloy factor of 1.00 for `CR_V`, 1.15 for `CR_MO` or 1.30 for `S2`."

    Design: Corner/calculations/proof_torque_correct_result_across_family_alloy_and_channel
    """
    set_clock(DEFAULT_CLOCK)

    sku = create_sku(**attributes)

    assert sku["proof_torque_required_nm"] == pytest.approx(expected_nm, abs=0.01)


def test_the_size_tier_adder_is_added_before_the_rounding_step():
    """A 19 mm socket lands on 164.35 before rounding, and rounding half up at one
    decimal place makes it 164.4 rather than 164.3.

    PRD §3.1: "Step three adds a size-tier term, computed as a per-millimetre
    adder multiplied by `nominal_size_mm`, where the adder is zero for a size of
    10 millimetres or less, 1.5 for a size greater than 10 and up to and including
    19, and 3.0 for a size greater than 19."

    Design: Corner/calculations/proof_torque_correct_result_across_family_alloy_and_channel
    """
    set_clock(DEFAULT_CLOCK)

    socket = create_sku(**SOCKET_BRANDED)
    plier = create_sku(**PLIER_PRIVATE_LABEL)

    assert socket["proof_torque_required_nm"] == pytest.approx(164.4, abs=0.01)
    assert plier["proof_torque_required_nm"] == pytest.approx(36.4, abs=0.01)


@pytest.mark.parametrize(
    "attributes,expected_nm",
    [
        (TINY_PLIER, 12.0),
        (GIANT_SOCKET, 900.0),
        (WRENCH_BRANDED, 115.8),
    ],
    ids=["lifted_to_floor", "cut_to_ceiling", "inside_the_band"],
)
def test_the_industry_band_clamps_the_result_after_the_additive_term(attributes, expected_nm):
    """A 4 mm plier computes 11.2 and is lifted to 12.0; an 80 mm S2 professional
    socket computes 1085.0 and is cut to 900.0; the mid-range wrench passes
    through untouched.

    PRD §3.1: "Step four clamps the result into the industry band, raising
    anything below 12.0 newton-metres up to 12.0 and cutting anything above 900.0
    newton-metres down to 900.0."

    Design: Corner/calculations/proof_torque_floor_and_ceiling_clamps_applied_after_additive_term
    """
    set_clock(DEFAULT_CLOCK)

    sku = create_sku(**attributes)

    assert sku["proof_torque_required_nm"] == pytest.approx(expected_nm, abs=0.01)


def test_clamping_before_the_additive_term_would_have_given_a_different_ceiling_answer():
    """The 80 mm socket's raw 845.0 sits inside the band and only the 240.0 size
    adder pushes it out, so the clamp must run last to reach 900.0.

    PRD §3.1: "The order matters: applying the clamp before the additive size-tier
    term, or rounding before the clamp, produces a different number."

    Design: Corner/calculations/proof_torque_floor_and_ceiling_clamps_applied_after_additive_term
    """
    set_clock(DEFAULT_CLOCK)

    giant = create_sku(**GIANT_SOCKET)

    assert giant["proof_torque_required_nm"] == pytest.approx(900.0, abs=0.01)
    assert giant["proof_torque_required_nm"] != pytest.approx(1085.0, abs=0.01)
    assert giant["nominal_size_mm"] == 80


# ---------------------------------------------------------------------------
# The supersession walk
# ---------------------------------------------------------------------------


def _four_deep_wrench_chain():
    """V4 -> V3 -> V2 -> V1, the deepest chain the catalogue accepts."""
    set_clock(DEFAULT_CLOCK)
    v1 = create_sku(sku_code="WR-17-V1", list_price_cents=3300, **WRENCH_CHAIN_BASE)
    v2 = create_sku(
        sku_code="WR-17-V2", list_price_cents=3400, supersedes_sku_id=v1["id"], **WRENCH_CHAIN_BASE
    )
    v3 = create_sku(
        sku_code="WR-17-V3", list_price_cents=3500, supersedes_sku_id=v2["id"], **WRENCH_CHAIN_BASE
    )
    v4 = create_sku(
        sku_code="WR-17-V4", list_price_cents=3600, supersedes_sku_id=v3["id"], **WRENCH_CHAIN_BASE
    )
    return v1, v2, v3, v4


def test_each_respin_counts_its_hops_back_to_the_rootless_ancestor():
    """The walk starts at the named ancestor, so the chain reads 0, 1, 2, 3 and the
    fourth respin sits exactly on the limit.

    PRD §3.1: "When it is supplied and non-null it must resolve to an existing
    SKU, that ancestor must share the new SKU's `tool_family` — otherwise
    `ERR_LINEAGE_FAMILY_MISMATCH` — and the resulting chain is walked to derive
    `lineage_depth`, the number of hops from this SKU to an ancestor whose own
    `supersedes_sku_id` is null."

    Design: Corner/calculations/sku_lineage_depth_walk_and_chain_rejections
    """
    v1, v2, v3, v4 = _four_deep_wrench_chain()

    assert v1["lineage_depth"] == 0
    assert v1["supersedes_sku_id"] is None
    assert v2["lineage_depth"] == 1
    assert v3["lineage_depth"] == 2
    assert v4["lineage_depth"] == 3


def test_a_fifth_respin_exceeds_the_depth_limit_and_creates_no_row():
    """A hop count of four is refused outright, leaving the catalogue at four
    entries.

    PRD §3.1: "If the hop count would exceed three, the request is refused with
    `ERR_LINEAGE_DEPTH_EXCEEDED`."

    Design: Corner/calculations/sku_lineage_depth_walk_and_chain_rejections
    """
    _, _, _, v4 = _four_deep_wrench_chain()

    validate_error(
        api_client.create_tool_sku(
            tool_sku_payload(
                sku_code="WR-17-V5",
                list_price_cents=3700,
                supersedes_sku_id=v4["id"],
                **WRENCH_CHAIN_BASE,
            ),
            CM,
        ),
        ApiErrorId.ERR_LINEAGE_DEPTH_EXCEEDED,
        422,
    )

    _, meta = validate_paginated(api_client.list_tool_skus(CM))
    assert meta["total_count"] == 4


def test_a_respin_may_not_claim_an_ancestor_from_another_tool_family():
    """A socket cannot supersede a wrench, and the family check is reported in its
    own right.

    PRD §3.1: "that ancestor must share the new SKU's `tool_family` — otherwise
    `ERR_LINEAGE_FAMILY_MISMATCH`"

    Design: Corner/calculations/sku_lineage_depth_walk_and_chain_rejections
    """
    v1, _, _, _ = _four_deep_wrench_chain()

    validate_error(
        api_client.create_tool_sku(
            tool_sku_payload(
                sku_code="SO-20-V1",
                tool_family="SOCKET",
                channel="BRANDED",
                nominal_size_mm=20,
                alloy_grade="CR_V",
                list_price_cents=1500,
                warranty_tier="LIFETIME",
                supersedes_sku_id=v1["id"],
            ),
            CM,
        ),
        ApiErrorId.ERR_LINEAGE_FAMILY_MISMATCH,
        422,
    )

    _, meta = validate_paginated(api_client.list_tool_skus(CM))
    assert meta["total_count"] == 4


def test_naming_yourself_as_your_own_predecessor_is_reported_as_a_cycle():
    """The cycle test runs ahead of the depth test, so a self-reference is never a
    depth problem, and the amendment leaves the row alone.

    PRD §3.1: "If the walk ever revisits a SKU it has already seen, including the
    SKU being registered or amended itself, the request is refused with
    `ERR_SKU_LINEAGE_CYCLE`; the cycle test runs first, so a SKU that names itself
    as its own predecessor is reported as a cycle and never as a depth problem."

    Design: Corner/calculations/sku_lineage_depth_walk_and_chain_rejections
    """
    v1, _, _, _ = _four_deep_wrench_chain()

    body = validate_error(
        api_client.patch_tool_sku(v1["id"], {"supersedes_sku_id": v1["id"]}, CM),
        ApiErrorId.ERR_SKU_LINEAGE_CYCLE,
        422,
    )
    assert body["error_id"] != ApiErrorId.ERR_LINEAGE_DEPTH_EXCEEDED

    unchanged = read_sku(v1["id"])
    assert unchanged["supersedes_sku_id"] is None
    assert unchanged["lineage_depth"] == 0


def test_pointing_the_root_at_its_own_descendant_closes_the_chain_into_a_cycle():
    """Walking from V4 reaches V1 again, which is the SKU being amended, so the
    amendment is refused and the root keeps its null ancestor.

    PRD §3.1: "The walk starts at the candidate ancestor and follows each row's
    `supersedes_sku_id`."

    Design: Corner/calculations/sku_lineage_depth_walk_and_chain_rejections
    """
    v1, _, _, v4 = _four_deep_wrench_chain()

    validate_error(
        api_client.patch_tool_sku(v1["id"], {"supersedes_sku_id": v4["id"]}, CM),
        ApiErrorId.ERR_SKU_LINEAGE_CYCLE,
        422,
    )

    unchanged = read_sku(v1["id"])
    assert unchanged["supersedes_sku_id"] is None
    assert unchanged["lineage_depth"] == 0
    assert read_sku(v4["id"])["lineage_depth"] == 3
