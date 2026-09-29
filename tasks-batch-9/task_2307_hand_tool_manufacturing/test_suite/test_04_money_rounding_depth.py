"""Round-each-line-then-sum discipline on claim reserves, and the security pack
surcharge tier keyed on the pre-surcharge subtotal."""

import pytest

from test_helpers import (
    TEST_USERS,
    add_pack_member,
    api_client,
    assert_integer_cents,
    create_pack,
    read_claim,
    read_lot,
    setup_certified_lot,
    setup_warranty_scenario,
    validate_paginated,
    validate_success,
)

CM = TEST_USERS["channel_manager_headers"]
WA = TEST_USERS["warranty_administrator_headers"]

REPLACEMENT_LINES = (
    {"component_code": "HANDLE", "component_list_price_cents": 1099, "quantity": 1},
    {"component_code": "HEAD", "component_list_price_cents": 2599, "quantity": 1},
    {"component_code": "PIN", "component_list_price_cents": 755, "quantity": 3},
)
EXPECTED_LINE_RESERVES = (681, 1611, 1404)


# ---------------------------------------------------------------------------
# The security pack surcharge
# ---------------------------------------------------------------------------


def _security_pack_of_six_units():
    """A certified BRANDED wrench at 3300 cents, packed six to a security pack so
    the subtotal lands at 19,800 cents — just inside the middle tier."""
    ctx = setup_certified_lot()
    pack = create_pack(ctx["sku"]["id"], pack_code="PK-SEC-1", pack_type="SECURITY")
    member = add_pack_member(pack["id"], ctx["sku"]["id"], 6)
    ctx["pack"] = pack
    ctx["member"] = member
    return ctx


def test_a_security_pack_member_line_is_extended_at_full_list_price():
    """Security packs are sold at list, so six units of a 3300 cent wrench extend
    to 19,800 cents with no concession.

    PRD §3.6: "The discount is 1.00 for `RETAIL_DISPLAY` and for `SECURITY` —
    those formats are sold at list — and 0.88 for `MULTIPACK`, the
    twelve-percent volume concession that makes a multipack worth buying."

    Design: Difficulty/combinatorial_formula/security_pack_surcharge_tier_keyed_on_presurcharge_subtotal
    """
    ctx = _security_pack_of_six_units()

    assert_integer_cents(ctx["member"]["line_extended_cents"], "line_extended_cents")
    assert ctx["member"]["line_extended_cents"] == 19800
    assert ctx["member"]["quantity"] == 6


def test_the_security_surcharge_tier_is_keyed_on_the_pre_surcharge_subtotal():
    """A 19,800 cent subtotal sits inside the 20,000 cent break and therefore
    draws the flat 700 cent charge, not four percent of a finished total.

    PRD §3.6: "Step two derives `security_surcharge_cents`, the anti-theft
    packaging charge, and it is keyed on the **pre-surcharge** subtotal: for any
    pack whose `pack_type` is not `SECURITY` the surcharge is zero; for a
    `SECURITY` pack it is a flat 350 cents when `member_subtotal_cents` is 5,000
    cents or less, a flat 700 cents when the subtotal is 20,000 cents or less,
    and otherwise four percent of `member_subtotal_cents` rounded half up to a
    whole cent."

    Design: Difficulty/combinatorial_formula/security_pack_surcharge_tier_keyed_on_presurcharge_subtotal
    """
    ctx = _security_pack_of_six_units()

    approved = validate_success(
        api_client.approve_pack_configuration(ctx["pack"]["id"], CM)
    )

    assert approved["member_subtotal_cents"] == 19800
    assert approved["security_surcharge_cents"] == 700
    assert approved["pack_total_cents"] == 20500
    assert approved["pack_total_cents"] != 20620


def test_approval_prices_the_pack_and_counts_its_distinct_members():
    """One member line, priced from its SKU's current list price, and the pack
    leaves DRAFT for APPROVED.

    PRD §3.6: "Step three sets `pack_total_cents` to `member_subtotal_cents` plus
    `security_surcharge_cents`."

    Design: Difficulty/combinatorial_formula/security_pack_surcharge_tier_keyed_on_presurcharge_subtotal
    """
    ctx = _security_pack_of_six_units()

    approved = validate_success(
        api_client.approve_pack_configuration(ctx["pack"]["id"], CM)
    )

    assert approved["status"] == "APPROVED"
    assert approved["distinct_member_count"] == 1
    assert approved["pack_total_cents"] == (
        approved["member_subtotal_cents"] + approved["security_surcharge_cents"]
    )

    lot = read_lot(ctx["lot"]["id"])
    assert lot["cert_status"] == "CERTIFIED"
    assert lot["hardness_index_pooled"] == pytest.approx(52.50, abs=0.01)


# ---------------------------------------------------------------------------
# Per-line reserve rounding
# ---------------------------------------------------------------------------


def _claim_with_three_replacement_lines():
    """A BRANDED LIFETIME claim carrying three lines whose unrounded reserve
    shares all have fractional cents."""
    return setup_warranty_scenario(lines=REPLACEMENT_LINES)


@pytest.mark.parametrize(
    "index,component_code,expected",
    [
        (0, "HANDLE", 681),
        (1, "HEAD", 1611),
        (2, "PIN", 1404),
    ],
)
def test_each_replacement_line_is_rounded_to_a_whole_cent_on_its_own(
    index, component_code, expected
):
    """At 62 percent for BRANDED and a 1.00 LIFETIME factor, 1099, 2599 and 755
    times three all land on fractional cents and each is rounded alone.

    PRD §3.7: "Each line stores `line_reserve_cents`: the line's
    `component_list_price_cents` multiplied by its `quantity`, multiplied by the
    channel reserve percentage of the claim's SKU — 62 percent for `BRANDED`, 45
    percent for `PRIVATE_LABEL`, 78 percent for `PROFESSIONAL` — multiplied by
    the warranty tier factor of that SKU, which is 1.00 for `LIFETIME`, 0.70 for
    `LIMITED_5Y` and 0.00 for `NONE`, and then rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/claim_reserve_per_line_rounding_order
    """
    ctx = _claim_with_three_replacement_lines()
    line = ctx["lines"][index]

    assert line["component_code"] == component_code
    assert_integer_cents(line["line_reserve_cents"], "line_reserve_cents")
    assert line["line_reserve_cents"] == expected


def test_the_claim_reserve_charge_sums_the_already_rounded_lines():
    """681 plus 1611 plus 1404 is 3696 cents; carrying one unrounded product
    across all three lines would give 3697 and be wrong by a cent.

    PRD §3.7: "The claim's three roll-ups are refreshed from its lines in
    `created_at` ascending order: `reserve_charge_cents` is the **sum of the
    already-rounded per-line amounts**, `replacement_unit_count` is the sum of
    the lines' `quantity` values, and `line_count` is the number of lines."

    Design: Difficulty/combinatorial_formula/claim_reserve_per_line_rounding_order
    """
    ctx = _claim_with_three_replacement_lines()
    claim = read_claim(ctx["claim"]["id"])

    assert sum(EXPECTED_LINE_RESERVES) == 3696
    assert claim["reserve_charge_cents"] == 3696
    assert claim["reserve_charge_cents"] != 3697


def test_the_claim_rolls_up_its_line_count_and_its_replacement_units():
    """Three lines carrying one, one and three units give a replacement count of
    five.

    PRD §2.5: "Reserve charges and pack member extensions round **each line
    first and then sum the rounded lines exactly**; taking one product across all
    lines and rounding the sum is wrong and can differ by a cent."

    Design: Difficulty/combinatorial_formula/claim_reserve_per_line_rounding_order
    """
    ctx = _claim_with_three_replacement_lines()
    claim = read_claim(ctx["claim"]["id"])

    assert claim["line_count"] == 3
    assert claim["replacement_unit_count"] == 5

    lines, meta = validate_paginated(api_client.list_claim_lines(claim["id"], WA))
    assert meta["total_count"] == 3
    assert [line["line_reserve_cents"] for line in lines] == list(EXPECTED_LINE_RESERVES)
