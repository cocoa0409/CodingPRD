"""Optimistic concurrency on the two shared parents, the brand-protection
roll-up re-derived on every status change, and the currency of every derived
field in the response that produced it."""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_claim_line,
    api_client,
    approve_claim_payload,
    assert_reserve_ledger,
    assert_unit_ledger,
    clear_hold_payload,
    confirm_report,
    create_lot,
    create_report,
    create_sku,
    dismiss_report,
    hold_payload,
    make_warranty_administrator_headers,
    read_claim,
    read_lot,
    read_program,
    read_sku,
    release_payload,
    setup_warranty_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

CM = TEST_USERS["channel_manager_headers"]
PP = TEST_USERS["production_planner_headers"]
WA = TEST_USERS["warranty_administrator_headers"]
BP = TEST_USERS["brand_protection_analyst_headers"]

WA_ONE = make_warranty_administrator_headers("wa-1")
WA_TWO = make_warranty_administrator_headers("wa-2")
HANDLE_LINE = {"component_code": "HANDLE", "component_list_price_cents": 1099, "quantity": 1}
PIN_LINE = {"component_code": "PIN", "component_list_price_cents": 755, "quantity": 3}
WEAK_SIGHTING = {"evidence_grade": "WEAK", "unit_estimate": 10}


# ---------------------------------------------------------------------------
# The release token is checked against the parent SKU, not against the lot
# ---------------------------------------------------------------------------


def _a_sku_at_version_two_and_an_uncertified_lot():
    """One price amendment lifts the SKU to version 2, which leaves a token both
    below and above the current value available without reaching zero."""
    sku = create_sku()
    lot = create_lot(sku["id"], specimen_pool_total=20)
    amended = validate_success(api_client.patch_tool_sku(sku["id"], {"list_price_cents": 3900}, CM))
    assert amended["version"] == 2
    return {"sku": amended, "lot": lot}


@pytest.mark.parametrize("offset", [-1, 1], ids=["one_below", "one_above"])
def test_the_release_token_must_equal_the_parent_version_in_both_directions(offset):
    """A token one behind and a token one ahead are refused alike, so the check is
    an equality and not a floor.

    PRD §2.6: "If that value does not equal the SKU's current `version`, the release
    is rejected with `ERR_STALE_SKU_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/lot_release_optimistic_concurrency_on_the_parent_sku
    """
    ctx = _a_sku_at_version_two_and_an_uncertified_lot()
    lot_id = ctx["lot"]["id"]

    body = validate_error(
        api_client.release_production_lot(
            lot_id, release_payload(ctx["sku"]["version"] + offset), PP
        ),
        ApiErrorId.ERR_STALE_SKU_VERSION,
        412,
    )
    assert body["error_id"] != ApiErrorId.ERR_LOT_NOT_CERTIFIED

    refused = read_lot(lot_id)
    assert refused["version"] == ctx["lot"]["version"]
    assert refused["disposition"] == "IN_PROCESS"
    assert read_sku(ctx["sku"]["id"])["units_received_total"] == 0


def test_the_exactly_current_token_gets_past_the_concurrency_gate():
    """The release then fails on the dossier instead, which is how the satisfied
    version check makes itself visible.

    PRD §2.6: "Releasing a production lot into finished stock requires the
    non-optional field `expected_sku_version` in the request body, carrying the
    `version` of the parent `ToolSku` as the client last read it."

    Design: Corner/cross_cutting_complexity_layers/lot_release_optimistic_concurrency_on_the_parent_sku
    """
    ctx = _a_sku_at_version_two_and_an_uncertified_lot()
    lot_id = ctx["lot"]["id"]

    body = validate_error(
        api_client.release_production_lot(lot_id, release_payload(ctx["sku"]["version"]), PP),
        ApiErrorId.ERR_LOT_NOT_CERTIFIED,
        409,
    )
    assert body["error_id"] != ApiErrorId.ERR_STALE_SKU_VERSION

    assert read_lot(lot_id)["disposition"] == "IN_PROCESS"
    assert read_sku(ctx["sku"]["id"])["version"] == 2


def test_an_unrelated_catalogue_amendment_invalidates_a_previously_valid_token():
    """A price change nobody on the shop floor asked for moves the parent version, so
    the planner's freshly correct token is stale by the time the release is attempted
    and the lot itself is untouched throughout.

    PRD §2.4: "a `version` integer that starts at 1 on creation and increments by one
    on every mutation of that row — including mutations that only touch derived fields
    such as a recomputed hardness index, a refreshed reserve balance or a re-derived
    warranty posture."

    Design: Corner/cross_cutting_complexity_layers/lot_release_optimistic_concurrency_on_the_parent_sku
    """
    ctx = _a_sku_at_version_two_and_an_uncertified_lot()
    lot_id = ctx["lot"]["id"]
    token = ctx["sku"]["version"]

    repriced = validate_success(api_client.patch_tool_sku(ctx["sku"]["id"], {"list_price_cents": 4100}, CM))
    assert repriced["version"] == token + 1

    validate_error(
        api_client.release_production_lot(lot_id, release_payload(token), PP),
        ApiErrorId.ERR_STALE_SKU_VERSION,
        412,
    )

    unmoved = read_lot(lot_id)
    assert unmoved["version"] == ctx["lot"]["version"]
    assert unmoved["disposition"] == "IN_PROCESS"
    assert unmoved["cert_status"] == "DRAFT"


# ---------------------------------------------------------------------------
# The approval token is moved by side effects on the shared programme
# ---------------------------------------------------------------------------


def _a_funded_claim_and_its_programme():
    """Ten units on hand, five million cents of reserve, a fraud threshold of 60 and
    a single 681-cent line, so every gate above the version check would pass."""
    return setup_warranty_scenario(lines=(HANDLE_LINE,))


def test_a_programme_token_above_the_current_version_is_refused_before_any_fiscal_gate():
    """Stock, reserve, fraud and line count are all satisfied, and the approval is
    still answered on the token.

    PRD §2.6: "If that value does not equal the programme's current `version`, the
    approval is rejected with `ERR_STALE_PROGRAM_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/claim_approval_optimistic_concurrency_on_the_parent_programme
    """
    ctx = _a_funded_claim_and_its_programme()
    token = read_program(ctx["program"]["id"])["version"]

    body = validate_error(
        api_client.approve_warranty_claim(
            ctx["claim"]["id"], approve_claim_payload(token + 1), WA
        ),
        ApiErrorId.ERR_STALE_PROGRAM_VERSION,
        412,
    )
    assert body["error_id"] != ApiErrorId.ERR_RESERVE_INSUFFICIENT

    assert read_claim(ctx["claim"]["id"])["status"] == "SUBMITTED"
    program = read_program(ctx["program"]["id"])
    assert program["reserve_balance_cents"] == 5_000_000
    assert program["version"] == token


def test_a_hold_and_a_clear_hold_leave_a_token_two_versions_stale():
    """Neither of those verbs touches the reserve, yet each moves the programme's
    version through its hold counter, so the token read beforehand is worthless.

    PRD §2.6: "Because a hold, a clear-hold, a fraud denial, another approval and a
    revocation all increment the programme's `version`, an administrator who read the
    programme before any of those events must re-read it before approving."

    Design: Corner/cross_cutting_complexity_layers/claim_approval_optimistic_concurrency_on_the_parent_programme
    """
    ctx = _a_funded_claim_and_its_programme()
    claim_id = ctx["claim"]["id"]
    stale_token = read_program(ctx["program"]["id"])["version"]

    validate_success(
        api_client.hold_warranty_claim(claim_id, hold_payload(hold_reason="SPOT_CHECK"), WA_ONE)
    )
    validate_success(
        api_client.clear_hold_warranty_claim(
            claim_id, clear_hold_payload(clearance_note="Spot check clean"), WA_TWO
        )
    )

    program = read_program(ctx["program"]["id"])
    assert program["version"] == stale_token + 2
    assert program["open_hold_count"] == 0

    validate_error(
        api_client.approve_warranty_claim(claim_id, approve_claim_payload(stale_token), WA_TWO),
        ApiErrorId.ERR_STALE_PROGRAM_VERSION,
        412,
    )

    assert read_claim(claim_id)["status"] == "SUBMITTED"
    assert read_program(ctx["program"]["id"])["reserve_balance_cents"] == 5_000_000


def test_the_refreshed_token_approves_and_draws_the_reserve_down_once():
    """Re-reading the programme after the round trip yields a token that approves,
    and the balance moves by exactly the claim's frozen charge.

    PRD §2.9: "The third is reserve money. A warranty programme is funded once with
    `reserve_funded_cents`, immutable thereafter, and at every instant
    `reserve_funded_cents` equals `reserve_balance_cents` plus the sum of the
    `reserve_charge_cents` of the programme's claims that are currently in `APPROVED`
    or `FULFILLED` status."

    Design: Corner/cross_cutting_complexity_layers/claim_approval_optimistic_concurrency_on_the_parent_programme
    """
    ctx = _a_funded_claim_and_its_programme()
    claim_id = ctx["claim"]["id"]
    validate_success(
        api_client.hold_warranty_claim(claim_id, hold_payload(hold_reason="SPOT_CHECK"), WA_ONE)
    )
    validate_success(
        api_client.clear_hold_warranty_claim(
            claim_id, clear_hold_payload(clearance_note="Spot check clean"), WA_TWO
        )
    )
    fresh_token = read_program(ctx["program"]["id"])["version"]

    approved = validate_success(
        api_client.approve_warranty_claim(claim_id, approve_claim_payload(fresh_token), WA_TWO)
    )

    assert approved["status"] == "APPROVED"
    assert approved["reserve_charge_cents"] == 681

    program = read_program(ctx["program"]["id"])
    assert program["version"] == fresh_token + 1
    assert program["reserve_balance_cents"] == 4_999_319
    assert_reserve_ledger(program, [read_claim(claim_id)])


# ---------------------------------------------------------------------------
# The brand-protection roll-up is re-derived from the confirmed set every time
# ---------------------------------------------------------------------------


def _four_sightings_on_one_branded_wrench():
    """Three weak sightings of ten units each, worth five points apiece, and one
    moderate sighting of six hundred units worth thirty-five, all on a flagship SKU
    whose channel exposure is the full 1.0."""
    sku = create_sku()
    weak = [
        create_report(sku["id"], seller_handle=handle, **WEAK_SIGHTING)
        for handle in ("s-1", "s-2", "s-3")
    ]
    moderate = create_report(
        sku["id"],
        headers=CM,
        channel_name="OpenMarket",
        seller_handle="s-4",
        evidence_grade="MODERATE",
        unit_estimate=600,
    )
    return {"sku": sku, "weak": weak, "moderate": moderate}


def test_each_sighting_freezes_its_own_points_from_the_grade_and_the_scale():
    """Five points of weak evidence with a negligible scale, and fifteen points of
    moderate evidence with twenty for the six hundred units, both taken at the full
    branded exposure.

    PRD §3.9: "Those two contributions are added, then multiplied by the channel
    exposure factor of the SKU — 1.0 for `BRANDED`, since a counterfeit of the
    flagship brand does the most damage, 0.6 for `PRIVATE_LABEL` and 0.8 for
    `PROFESSIONAL` — and the product is rounded half up to a whole number of points."

    Design: Corner/cross_cutting_complexity_layers/brand_risk_derived_fields_reconcile_after_confirm_and_dismiss
    """
    ctx = _four_sightings_on_one_branded_wrench()

    for report in ctx["weak"]:
        assert report["risk_points"] == 5
        assert report["status"] == "OPEN"

    assert ctx["moderate"]["risk_points"] == 35
    assert ctx["moderate"]["status"] == "OPEN"


def test_four_open_sightings_leave_the_sku_exactly_as_it_was_created():
    """The SKU was created with a clean sheet and filing four sightings against it
    changes none of the three denormalised figures.

    PRD §3.9: "A new report is `OPEN` with `confirmation_note` and `dismissal_note`
    null, and an `OPEN` report contributes **nothing** to the SKU: `brand_risk_score`
    is untouched until an analyst confirms the sighting."

    Design: Corner/cross_cutting_complexity_layers/brand_risk_derived_fields_reconcile_after_confirm_and_dismiss
    """
    ctx = _four_sightings_on_one_branded_wrench()
    assert ctx["sku"]["warranty_posture"] == "OPEN"
    assert ctx["sku"]["brand_risk_score"] == 0
    assert ctx["sku"]["confirmed_counterfeit_count"] == 0

    unaffected = read_sku(ctx["sku"]["id"])
    assert unaffected["brand_risk_score"] == 0
    assert unaffected["confirmed_counterfeit_count"] == 0
    assert unaffected["warranty_posture"] == "OPEN"

    _, meta = validate_paginated(api_client.list_counterfeit_reports(BP, params={"status": "OPEN"}))
    assert meta["total_count"] == 4


def test_two_confirmations_and_a_dismissal_reconcile_to_ten_points():
    """Only the confirmed pair enters the roll-up, and the dismissed sighting leaves
    the score exactly where the second confirmation put it.

    PRD §3.9: "Nothing else happens at all: no roll-up, no posture change, no claim
    cascade, and the SKU's `brand_risk_score` is exactly what it was before, because
    dismissed reports never enter the roll-up."

    Design: Corner/cross_cutting_complexity_layers/brand_risk_derived_fields_reconcile_after_confirm_and_dismiss
    """
    ctx = _four_sightings_on_one_branded_wrench()
    first, second, third = ctx["weak"]

    assert confirm_report(first["id"])["status"] == "CONFIRMED"
    confirm_report(second["id"])
    after_confirmations = read_sku(ctx["sku"]["id"])
    assert after_confirmations["brand_risk_score"] == 10

    assert dismiss_report(third["id"])["status"] == "DISMISSED"

    reconciled = read_sku(ctx["sku"]["id"])
    assert reconciled["brand_risk_score"] == 10
    assert reconciled["confirmed_counterfeit_count"] == 2
    assert reconciled["warranty_posture"] == "OPEN"


def test_confirming_the_moderate_sighting_crosses_the_restriction_threshold():
    """Ten points from the weak pair plus thirty-five from the moderate sighting land
    on forty-five, which is over the inclusive restriction threshold and well under
    suspension.

    PRD §3.9: "Link three re-derives `warranty_posture` from that score against two
    inclusive thresholds: a score of 85 or more makes the posture `SUSPENDED`, a score
    of 40 or more but below 85 makes it `RESTRICTED`, and anything below 40 leaves it
    `OPEN`."

    Design: Corner/cross_cutting_complexity_layers/brand_risk_derived_fields_reconcile_after_confirm_and_dismiss
    """
    ctx = _four_sightings_on_one_branded_wrench()
    first, second, third = ctx["weak"]
    confirm_report(first["id"])
    confirm_report(second["id"])
    dismiss_report(third["id"])

    confirm_report(ctx["moderate"]["id"])

    restricted = read_sku(ctx["sku"]["id"])
    assert restricted["brand_risk_score"] == 45
    assert restricted["confirmed_counterfeit_count"] == 3
    assert restricted["warranty_posture"] == "RESTRICTED"

    _, open_meta = validate_paginated(
        api_client.list_counterfeit_reports(BP, params={"status": "OPEN"})
    )
    assert open_meta["total_count"] == 0

    _, confirmed_meta = validate_paginated(
        api_client.list_counterfeit_reports(BP, params={"status": "CONFIRMED"})
    )
    assert confirmed_meta["total_count"] == 3


# ---------------------------------------------------------------------------
# Every derived field is current in the response that produced it
# ---------------------------------------------------------------------------


def _a_two_line_claim_worth_two_thousand_and_eighty_five_cents():
    """A 681-cent handle and a 1404-cent set of three pins, each line rounded before
    the sum, on a branded lifetime SKU with ten units on the shelf."""
    return setup_warranty_scenario(lines=(HANDLE_LINE,))


def test_each_line_response_already_carries_its_own_rounded_reserve_share():
    """The second line's own response reports 1404 cents, and the claim's roll-ups
    are current in the very next read.

    PRD §3.7: "Each line stores `line_reserve_cents`: the line's
    `component_list_price_cents` multiplied by its `quantity`, multiplied by the
    channel reserve percentage of the claim's SKU — 62 percent for `BRANDED`, 45
    percent for `PRIVATE_LABEL`, 78 percent for `PROFESSIONAL` — multiplied by the
    warranty tier factor of that SKU, which is 1.00 for `LIFETIME`, 0.70 for
    `LIMITED_5Y` and 0.00 for `NONE`, and then rounded half up to a whole cent."

    Design: Corner/consistency_model/every_derived_field_is_current_in_the_mutating_response
    """
    ctx = _a_two_line_claim_worth_two_thousand_and_eighty_five_cents()
    claim_id = ctx["claim"]["id"]
    assert ctx["lines"][0]["line_reserve_cents"] == 681

    pins = add_claim_line(claim_id, **PIN_LINE)
    assert pins["line_reserve_cents"] == 1404

    lined = read_claim(claim_id)
    assert lined["line_count"] == 2
    assert lined["replacement_unit_count"] == 4
    assert lined["reserve_charge_cents"] == 2085

    _, meta = validate_paginated(api_client.list_claim_lines(claim_id, WA))
    assert meta["total_count"] == 2


def test_the_approval_response_agrees_with_the_reads_that_immediately_follow_it():
    """The mutating response already carries the frozen charge and the unit count, and
    the programme and the SKU read back exactly what it implied.

    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."

    Design: Corner/consistency_model/every_derived_field_is_current_in_the_mutating_response
    """
    ctx = _a_two_line_claim_worth_two_thousand_and_eighty_five_cents()
    claim_id = ctx["claim"]["id"]
    add_claim_line(claim_id, **PIN_LINE)
    token = read_program(ctx["program"]["id"])["version"]

    approved = validate_success(
        api_client.approve_warranty_claim(claim_id, approve_claim_payload(token), WA_ONE)
    )

    assert approved["status"] == "APPROVED"
    assert approved["reserve_charge_cents"] == 2085
    assert approved["replacement_unit_count"] == 4

    program = read_program(ctx["program"]["id"])
    assert program["reserve_balance_cents"] == 4_997_915
    assert_reserve_ledger(program, [read_claim(claim_id)])

    sku = read_sku(ctx["sku"]["id"])
    assert sku["units_on_hand"] == 6
    assert sku["units_reserved"] == 4
    assert_unit_ledger(sku)
