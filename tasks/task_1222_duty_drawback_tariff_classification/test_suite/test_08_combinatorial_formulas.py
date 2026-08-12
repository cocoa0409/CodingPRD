"""Combinatorial formulas: the lesser-of substitution refund and the pinned
per-line-then-sum claim aggregation order."""
from test_helpers import add_claim, add_claim_line, file_claim, setup_trade_scenario, TEST_USERS, validate_success

ANALYST = TEST_USERS["analyst_headers"]
BROKER = TEST_USERS["broker_headers"]


def _setup_substitution_scenario():
    """Client + CERTIFIED classification + entry (unit eligible 825) + export
    (qty 200, fob 300000, substituted rate 1000 -> substitute unit duty 150) +
    SUBSTITUTION claim in DRAFT."""
    ctx = setup_trade_scenario(
        export_overrides={
            "quantity": 200,
            "fob_value_cents": 300000,
            "substituted_duty_rate_bps": 1000,
        }
    )
    claim = add_claim(ctx["client"]["id"], claim_type="SUBSTITUTION")
    ctx["claim"] = claim
    return ctx


def test_substitution_lesser_of_picks_the_substitute_unit_when_smaller(api):
    """PRD 3.4: "Under substitution, the lesser-of rule of 19 U.S.C. §1313(l)
    applies: the import side's per-unit eligible duty is computed the same way,
    while the substitute side's per-unit duty is the shipment's
    `substituted_duty_rate_bps` multiplied by its `fob_value_cents` and divided
    by the product of 10000 and the shipment's `quantity`, again as an exact
    rational; the refund base is whichever per-unit figure is smaller,
    multiplied by 9900 basis points and by `matched_quantity`, rounded half up."

    Design: Difficulty/combinatorial_formula/substitution_lesser_of_unit_duty
    """
    ctx = _setup_substitution_scenario()

    line = validate_success(
        api.add_claim_line(
            ctx["claim"]["id"],
            {
                "import_entry_id": ctx["entry"]["id"],
                "export_shipment_id": ctx["export"]["id"],
                "matched_quantity": 50,
            },
            ANALYST,
        ),
        201,
    )
    # min(import unit 825, substitute unit 150) * 0.99 * 50 = 7425
    assert line["drawback_amount_cents"] == 7425, (
        f"lesser-of must select the substitute unit (150): expected 7425, "
        f"got {line['drawback_amount_cents']}"
    )

    entry = validate_success(api.get_import_entry(ctx["entry"]["id"], ANALYST))
    assert entry["unclaimed_duty_cents"] == 75075
    assert entry["matched_quantity"] == 50
    assert entry["status"] == "PARTIALLY_MATCHED"

    export = validate_success(api.get_export_shipment(ctx["export"]["id"], ANALYST))
    assert export["value_pool_remaining_cents"] == 292575
    assert export["matched_quantity"] == 50

    claim = validate_success(api.get_claim(ctx["claim"]["id"], ANALYST))
    assert claim["estimate_cents"] == 7425


def test_substitution_refund_is_not_the_direct_identification_figure(api):
    """PRD 3.4: "Under direct identification, the entry's current
    `drawback_eligible_duty_cents` is divided by its `line_quantity` as an exact
    rational to obtain a per-unit eligible duty; that unit figure is multiplied
    by 9900 basis points (the 99% refund rate) and by the line's
    `matched_quantity`, and the result is rounded half up."
    PRD 3.4: "the refund base is whichever per-unit figure is smaller,
    multiplied by 9900 basis points and by `matched_quantity`, rounded half up."

    Design: Difficulty/combinatorial_formula/substitution_lesser_of_unit_duty
    """
    ctx = _setup_substitution_scenario()
    direct_amount = validate_success(
        # A DIRECT twin claim proves the same entry/quantity would refund 40838
        # when no lesser-of substitute unit binds.
        api.create_claim(
            {
                "client_id": ctx["client"]["id"],
                "claim_type": "DIRECT_IDENTIFICATION",
                "period_start": "2026-04-01T00:00:00Z",
                "period_end": "2026-06-30T00:00:00Z",
            },
            ANALYST,
        ),
        201,
    )
    direct_line = validate_success(
        api.add_claim_line(
            direct_amount["id"],
            {
                "import_entry_id": ctx["entry"]["id"],
                "export_shipment_id": ctx["export"]["id"],
                "matched_quantity": 50,
            },
            ANALYST,
        ),
        201,
    )
    assert direct_line["drawback_amount_cents"] == 40838

    # Disjoint period: PRD 3.4 rejects a second same-type claim whose closed
    # period interval overlaps the scenario's existing SUBSTITUTION claim.
    sub_claim = add_claim(
        ctx["client"]["id"],
        claim_type="SUBSTITUTION",
        period_start="2026-07-01T00:00:00Z",
        period_end="2026-09-30T00:00:00Z",
    )
    sub_line = validate_success(
        api.add_claim_line(
            sub_claim["id"],
            {
                "import_entry_id": ctx["entry"]["id"],
                "export_shipment_id": ctx["export"]["id"],
                "matched_quantity": 50,
            },
            ANALYST,
        ),
        201,
    )
    assert sub_line["drawback_amount_cents"] == 7425
    assert sub_line["drawback_amount_cents"] < direct_line["drawback_amount_cents"], (
        "the substitute branch of the conditional formula must win over the import side"
    )


def test_claim_total_rounds_each_line_before_summing(api):
    """PRD 3.4: "The aggregation order is pinned: each line is first rounded
    half up to integer cents, and those integers are then summed. Summing raw
    unrounded values and rounding once at the end is forbidden — two lines whose
    raw refunds are each a half-cent value must contribute two rounded cents to
    the total, not lose both halves to a single final rounding."

    Design: Difficulty/combinatorial_formula/claim_total_per_line_rounding_order
    """
    ctx = setup_trade_scenario()
    claim = add_claim(ctx["client"]["id"])
    line_1 = add_claim_line(
        claim["id"], ctx["entry"]["id"], ctx["export"]["id"], matched_quantity=50
    )
    line_2 = add_claim_line(
        claim["id"], ctx["entry"]["id"], ctx["export"]["id"], matched_quantity=50
    )
    # Each raw refund is 40837.5; per-line rounding gives 40838 twice.
    assert line_1["drawback_amount_cents"] == 40838
    assert line_2["drawback_amount_cents"] == 40838

    filed = file_claim(claim["id"])
    assert filed["claimed_duty_cents"] == 81676, (
        f"per-line-then-sum must give 81676, not the forbidden sum-then-round "
        f"81675; got {filed['claimed_duty_cents']}"
    )


def test_per_line_rounding_visible_in_both_lines_and_frozen_total(api):
    """PRD 2.4: "Every rounding in the system is round half up to integer cents,
    applied at precisely the step each calculation specifies — and several
    calculations deliberately pin a per-component rounding followed by an
    integer sum, because rounding a grand total instead would produce a
    different cent figure."
    PRD 3.4: "On filing, the claim transitions `DRAFT → FILED`, `filed_at` and
    `filed_by_user_id` are stamped, and `claimed_duty_cents` is frozen as the
    sum of the then-current per-line `drawback_amount_cents` values."

    Design: Difficulty/combinatorial_formula/claim_total_per_line_rounding_order
    """
    ctx = setup_trade_scenario()
    claim = add_claim(ctx["client"]["id"])
    line_1 = add_claim_line(
        claim["id"], ctx["entry"]["id"], ctx["export"]["id"], matched_quantity=50
    )
    line_2 = add_claim_line(
        claim["id"], ctx["entry"]["id"], ctx["export"]["id"], matched_quantity=50
    )

    filed = file_claim(claim["id"])
    assert (
        filed["claimed_duty_cents"]
        == line_1["drawback_amount_cents"] + line_2["drawback_amount_cents"]
        == 81676
    )

    entry = validate_success(api.get_import_entry(ctx["entry"]["id"], ANALYST))
    assert entry["unclaimed_duty_cents"] == 824, (
        f"82500 - 81676 = 824; got {entry['unclaimed_duty_cents']}"
    )
    assert entry["matched_quantity"] == 100
    assert entry["status"] == "MATCHED"
