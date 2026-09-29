"""Warranty intake precedence, the stock and line gates on approval, and the
clearance that waives the fraud score."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_claim_line,
    api_client,
    approve_claim,
    approve_claim_payload,
    assert_unit_ledger,
    book_stock,
    claimant_block_payload,
    clear_hold,
    create_claim,
    create_claimant,
    create_program,
    create_sku,
    read_claim,
    read_claimant,
    read_program,
    read_sku,
    validate_error,
    validate_paginated,
    validate_success,
    warranty_claim_payload,
)

WA = TEST_USERS["warranty_administrator_headers"]
CM = TEST_USERS["channel_manager_headers"]

UNCOVERED_SKU = {"sku_code": "WR-17-NC", "warranty_tier": "NONE"}
SECOND_SKU = {"sku_code": "WR-19-BR", "nominal_size_mm": 19}
HANDLE = {"component_code": "HANDLE", "component_list_price_cents": 1099}


# ---------------------------------------------------------------------------
# Intake precedence
# ---------------------------------------------------------------------------


def _blocked_claimant_and_an_uncovered_sku():
    sku = create_sku(**UNCOVERED_SKU)
    program = create_program()
    claimant = create_claimant()
    blocked = validate_success(
        api_client.block_claimant(claimant["id"], claimant_block_payload(), WA)
    )
    assert blocked["status"] == "BLOCKED"
    return sku, program, claimant


def test_a_missing_claim_reason_outranks_both_the_block_and_the_missing_coverage():
    """Every substantive gate is violated at once, yet the reply is the shape fault
    because request shape sits above them all on the ladder.

    PRD §2.7: "In ascending order the rungs are: authentication of the role header;
    role authorisation for the endpoint; claimant ownership; existence of every
    identifier named in the path and then in the body; request shape, meaning
    required fields present and correctly typed, enum values drawn from the declared
    members, integers within their declared ranges, pagination bounds, window sanity
    and the reading-array length"

    Design: Corner/validations/claim_intake_gate_precedence_blocked_beats_tier_beats_duplicate
    """
    sku, program, claimant = _blocked_claimant_and_an_uncovered_sku()
    reasonless = warranty_claim_payload(claimant["id"], sku["id"], program["id"])
    reasonless.pop("claim_reason")

    body = validate_error(
        api_client.create_warranty_claim(reasonless, WA), ApiErrorId.ERR_INVALID_REQUEST, 400
    )
    assert body["error_id"] != ApiErrorId.ERR_CLAIMANT_BLOCKED

    _, meta = validate_paginated(api_client.list_warranty_claims(WA))
    assert meta["total_count"] == 0


def test_a_blocked_claimant_is_reported_ahead_of_the_uncovered_warranty_tier():
    """The claimant named in the body is in a terminal state, which is a
    cross-entity state dependency and therefore outranks the coverage rule.

    PRD §3.7: "`BLOCKED` is terminal, and a blocked claimant may not be named on a
    new claim: that refusal is `ERR_CLAIMANT_BLOCKED`."

    Design: Corner/validations/claim_intake_gate_precedence_blocked_beats_tier_beats_duplicate
    """
    sku, program, claimant = _blocked_claimant_and_an_uncovered_sku()

    body = validate_error(
        api_client.create_warranty_claim(
            warranty_claim_payload(claimant["id"], sku["id"], program["id"]), WA
        ),
        ApiErrorId.ERR_CLAIMANT_BLOCKED,
        409,
    )
    assert body["error_id"] != ApiErrorId.ERR_WARRANTY_TIER_NOT_COVERED

    _, meta = validate_paginated(api_client.list_warranty_claims(WA))
    assert meta["total_count"] == 0


def test_losing_coverage_is_reported_ahead_of_the_duplicate_serial():
    """Amending the tier to NONE strands the open claim, so a refiling of the very
    same serial is answered on coverage rather than on the duplicate.

    PRD §3.7: "A SKU whose `warranty_tier` is `NONE` carries no coverage and cannot
    be claimed against: `ERR_WARRANTY_TIER_NOT_COVERED`."

    Design: Corner/validations/claim_intake_gate_precedence_blocked_beats_tier_beats_duplicate
    """
    sku = create_sku()
    program = create_program()
    claimant = create_claimant()
    first = create_claim(claimant["id"], sku["id"], program["id"], serial_code="SN-1")
    assert first["status"] == "SUBMITTED"

    amended = validate_success(api_client.patch_tool_sku(sku["id"], {"warranty_tier": "NONE"}, CM))
    assert amended["warranty_tier"] == "NONE"

    body = validate_error(
        api_client.create_warranty_claim(
            warranty_claim_payload(claimant["id"], sku["id"], program["id"], serial_code="SN-1"),
            WA,
        ),
        ApiErrorId.ERR_WARRANTY_TIER_NOT_COVERED,
        422,
    )
    assert body["error_id"] != ApiErrorId.ERR_DUPLICATE_OPEN_CLAIM

    _, meta = validate_paginated(api_client.list_warranty_claims(WA))
    assert meta["total_count"] == 1


def test_a_second_serial_files_where_the_repeated_one_is_refused():
    """The live claim blocks its own serial only, and the second filing scores two
    claims at nine points each.

    PRD §3.7: "if they already have a claim in `SUBMITTED`, `FRAUD_HOLD` or
    `APPROVED` status on the same `sku_id` and `serial_code` pair, the new filing is
    `ERR_DUPLICATE_OPEN_CLAIM`, while claims that ended in `DENIED`, `DENIED_FRAUD`,
    `FULFILLED` or `REVOKED` no longer block a refiling."

    Design: Corner/validations/claim_intake_gate_precedence_blocked_beats_tier_beats_duplicate
    """
    sku = create_sku()
    program = create_program()
    claimant = create_claimant()
    first = create_claim(claimant["id"], sku["id"], program["id"], serial_code="SN-1")
    assert first["fraud_score_at_intake"] == 9

    validate_error(
        api_client.create_warranty_claim(
            warranty_claim_payload(claimant["id"], sku["id"], program["id"], serial_code="SN-1"),
            WA,
        ),
        ApiErrorId.ERR_DUPLICATE_OPEN_CLAIM,
        409,
    )

    second = validate_success(
        api_client.create_warranty_claim(
            warranty_claim_payload(claimant["id"], sku["id"], program["id"], serial_code="SN-2"),
            WA,
        ),
        201,
    )
    assert second["status"] == "SUBMITTED"
    assert second["fraud_score_at_intake"] == 18

    owner = read_claimant(claimant["id"])
    assert owner["fraud_risk_score_intake"] == 18
    assert owner["lifetime_claim_count"] == 2

    _, meta = validate_paginated(api_client.list_warranty_claims(WA))
    assert meta["total_count"] == 2


# ---------------------------------------------------------------------------
# Approval needs both a line to ship and the stock to ship it from
# ---------------------------------------------------------------------------


def _one_unit_on_the_shelf_and_two_claims():
    """A single finished unit in stock, one line-less claim and one claim asking for
    two replacement units."""
    sku = create_sku()
    book_stock(sku["id"], 1)
    program = create_program()
    claimant = create_claimant()
    lineless = create_claim(claimant["id"], sku["id"], program["id"], serial_code="SN-1")
    lined = create_claim(claimant["id"], sku["id"], program["id"], serial_code="SN-2")
    line = add_claim_line(lined["id"], quantity=2, **HANDLE)
    return {
        "sku": read_sku(sku["id"]),
        "program": program,
        "lineless": lineless,
        "lined": read_claim(lined["id"]),
        "line": line,
    }


def test_a_claim_with_nothing_to_ship_is_refused_even_with_stock_to_spare():
    """No lines means no replacement units, so the stock gate is satisfied and the
    empty claim is the only fault left.

    PRD §3.8: "The claim's `line_count` must be at least 1, since there is nothing
    to ship otherwise (`ERR_CLAIM_HAS_NO_LINES`)."

    Design: Corner/validations/approval_requires_stock_and_at_least_one_line
    """
    ctx = _one_unit_on_the_shelf_and_two_claims()
    program = read_program(ctx["program"]["id"])

    validate_error(
        api_client.approve_warranty_claim(
            ctx["lineless"]["id"], approve_claim_payload(program["version"]), WA
        ),
        ApiErrorId.ERR_CLAIM_HAS_NO_LINES,
        422,
    )

    unchanged = read_claim(ctx["lineless"]["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["line_count"] == 0
    assert unchanged["replacement_unit_count"] == 0
    assert read_program(ctx["program"]["id"])["reserve_balance_cents"] == 5_000_000


def test_a_two_unit_claim_cannot_be_approved_against_a_single_unit_of_stock():
    """The shelf holds one unit against a two-unit claim, and the refusal moves
    neither the unit ledger nor the reserve.

    PRD §3.8: "The SKU's `units_on_hand` must be at least the claim's
    `replacement_unit_count` (`ERR_REPLACEMENT_STOCK_INSUFFICIENT`)."

    Design: Corner/validations/approval_requires_stock_and_at_least_one_line
    """
    ctx = _one_unit_on_the_shelf_and_two_claims()
    program = read_program(ctx["program"]["id"])

    assert ctx["line"]["line_reserve_cents"] == 1363
    assert ctx["lined"]["replacement_unit_count"] == 2
    assert ctx["lined"]["reserve_charge_cents"] == 1363

    validate_error(
        api_client.approve_warranty_claim(
            ctx["lined"]["id"], approve_claim_payload(program["version"]), WA
        ),
        ApiErrorId.ERR_REPLACEMENT_STOCK_INSUFFICIENT,
        409,
    )

    sku = read_sku(ctx["sku"]["id"])
    assert sku["units_on_hand"] == 1
    assert sku["units_reserved"] == 0
    assert_unit_ledger(sku)
    assert read_claim(ctx["lined"]["id"])["status"] == "SUBMITTED"


def test_booking_more_units_lets_the_same_approval_settle_both_ledgers():
    """A five-unit receipt lifts the shelf to six, and the approval then moves two
    units into reserved and 1363 cents out of the reserve.

    PRD §3.8: "On the SKU, `replacement_unit_count` units move out of
    `units_on_hand` and into `units_reserved`, and the SKU's `version` increments."

    Design: Corner/validations/approval_requires_stock_and_at_least_one_line
    """
    ctx = _one_unit_on_the_shelf_and_two_claims()
    restocked = book_stock(ctx["sku"]["id"], 5)
    assert restocked["units_on_hand"] == 6

    approved = approve_claim(ctx["lined"]["id"], ctx["program"]["id"], WA)
    assert approved["status"] == "APPROVED"
    assert approved["reserve_charge_cents"] == 1363
    assert approved["replacement_unit_count"] == 2

    sku = read_sku(ctx["sku"]["id"])
    assert sku["units_received_total"] == 6
    assert sku["units_on_hand"] == 4
    assert sku["units_reserved"] == 2
    assert sku["units_shipped"] == 0
    assert_unit_ledger(sku)

    assert read_program(ctx["program"]["id"])["reserve_balance_cents"] == 4_998_637
    assert read_claim(ctx["lineless"]["id"])["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# The fraud gate and the clearance that waives it
# ---------------------------------------------------------------------------


def _two_claims_sharing_one_serial():
    """A claimant with two claims quoting the same serial on two different SKUs:
    the first is submitted at nine points, the second is scored at 36 and lands
    straight on hold under a threshold of 30."""
    first_sku = create_sku()
    second_sku = create_sku(**SECOND_SKU)
    book_stock(first_sku["id"], 10)
    book_stock(second_sku["id"], 10)
    program = create_program(fraud_score_threshold=30)
    claimant = create_claimant()

    first = create_claim(claimant["id"], first_sku["id"], program["id"], serial_code="SN-A")
    add_claim_line(first["id"], quantity=1, **HANDLE)
    second = create_claim(claimant["id"], second_sku["id"], program["id"], serial_code="SN-A")
    add_claim_line(second["id"], quantity=1, **HANDLE)

    return {
        "first_sku": first_sku,
        "second_sku": second_sku,
        "program": program,
        "claimant": claimant,
        "first": read_claim(first["id"]),
        "second": read_claim(second["id"]),
    }


def test_a_repeated_serial_scores_the_second_claim_onto_an_automatic_hold():
    """Two claims quoting one serial contribute 18 duplicate points on top of the
    two-claim count, and 36 is at the programme's threshold of 30.

    PRD §3.7: "If it is at or above the threshold, the claim is persisted
    **directly** in `FRAUD_HOLD` with `hold_reason` set to the literal string
    `INTAKE_FRAUD_SCORE` and `held_by_user_id` left null, and the programme's
    `open_hold_count` and `version` both increment."

    Design: Corner/validations/approval_fraud_gate_yields_to_an_explicit_clearance
    """
    ctx = _two_claims_sharing_one_serial()

    assert ctx["first"]["status"] == "SUBMITTED"
    assert ctx["first"]["fraud_score_at_intake"] == 9

    assert ctx["second"]["status"] == "FRAUD_HOLD"
    assert ctx["second"]["fraud_score_at_intake"] == 36
    assert ctx["second"]["hold_reason"] == "INTAKE_FRAUD_SCORE"
    assert ctx["second"]["held_by_user_id"] is None
    assert ctx["second"]["fraud_cleared"] is False

    assert read_program(ctx["program"]["id"])["open_hold_count"] == 1


def test_an_uncleared_claim_from_the_scored_claimant_cannot_be_approved():
    """Clearing the held claim recomputes the claimant's adjudication score to 36,
    and that score then blocks the sibling claim, which carries no clearance.

    PRD §3.8: "The claimant's `fraud_risk_score_adjudication` must be strictly below
    the programme's `fraud_score_threshold`, **unless** `fraud_cleared` is true, in
    which case a manual clearance waives this gate — but note that clearance waives
    only the score gate and never the posture gate (`ERR_FRAUD_SCORE_TOO_HIGH`)."

    Design: Corner/validations/approval_fraud_gate_yields_to_an_explicit_clearance
    """
    ctx = _two_claims_sharing_one_serial()
    clear_hold(ctx["second"]["id"], WA)

    scored = read_claimant(ctx["claimant"]["id"])
    assert scored["fraud_risk_score_adjudication"] == 36

    program = read_program(ctx["program"]["id"])
    validate_error(
        api_client.approve_warranty_claim(
            ctx["first"]["id"], approve_claim_payload(program["version"]), WA
        ),
        ApiErrorId.ERR_FRAUD_SCORE_TOO_HIGH,
        409,
    )

    refused = read_claim(ctx["first"]["id"])
    assert refused["status"] == "SUBMITTED"
    assert refused["fraud_cleared"] is False
    assert read_program(ctx["program"]["id"])["reserve_balance_cents"] == 5_000_000


def test_an_explicit_clearance_waives_the_score_and_lets_the_reserve_be_spent():
    """The cleared claim keeps its 36-point claimant but approves anyway, spending
    681 cents of the reserve and emptying the hold queue.

    PRD §3.8: "Clearing moves the claim `FRAUD_HOLD → SUBMITTED`, sets
    `fraud_cleared` to true, and clears `hold_reason` to null — but **retains**
    `held_by_user_id`, because the duty separation must still bind at approval time."

    Design: Corner/validations/approval_fraud_gate_yields_to_an_explicit_clearance
    """
    ctx = _two_claims_sharing_one_serial()

    cleared = clear_hold(ctx["second"]["id"], WA)
    assert cleared["status"] == "SUBMITTED"
    assert cleared["fraud_cleared"] is True
    assert cleared["hold_reason"] is None
    assert read_program(ctx["program"]["id"])["open_hold_count"] == 0

    approved = approve_claim(ctx["second"]["id"], ctx["program"]["id"], WA)
    assert approved["status"] == "APPROVED"
    assert approved["reserve_charge_cents"] == 681
    assert approved["fraud_cleared"] is True

    assert read_claimant(ctx["claimant"]["id"])["fraud_risk_score_adjudication"] == 36
    assert read_program(ctx["program"]["id"])["reserve_balance_cents"] == 4_999_319

    sku = read_sku(ctx["second_sku"]["id"])
    assert sku["units_on_hand"] == 9
    assert sku["units_reserved"] == 1
    assert_unit_ledger(sku)
