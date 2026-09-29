"""Two refusals whose identity depends on which guard the ladder reaches first."""

from test_helpers import (
    GALLERY_MANAGER,
    SCORES_GRADE_A,
    SCORES_GRADE_C,
    STD_SCHEDULE_STEPS,
    ApiErrorId,
    api_client,
    create_item,
    create_zone,
    elect_disposition_payload,
    fetch_agreement,
    fetch_consignor,
    fetch_consignor_ledger,
    fetch_item,
    fetch_zone,
    flag_inventory,
    payout_payload,
    place_item,
    receive_item,
    run_escheatment_epoch,
    run_markdown_epoch,
    screen_item,
    set_clock,
    setup_consignor_with_active_agreement,
    take_custody,
    validate_error,
    write_off_item,
)

TWO_STEP_SCHEDULE = STD_SCHEDULE_STEPS[:2]

LOUNGER = {
    "title": "Patio lounger",
    "category": "OUTDOOR",
    "declared_value_cents": 100_000,
    "photo_count": 4,
    "volume_cuft": 20,
    "footprint_sqft": 10,
}
STOOL = {
    "title": "Garden stool",
    "category": "OUTDOOR",
    "declared_value_cents": 2_500,
    "photo_count": 3,
    "volume_cuft": 5,
    "footprint_sqft": 2,
}
ETCHING = {
    "title": "Gilt frame etching",
    "category": "ART",
    "declared_value_cents": 129_950,
    "photo_count": 4,
    "volume_cuft": 12,
    "footprint_sqft": 4,
}


def _escheated_account_left_holding_seven_hundred_and_one_cents():
    """Escheat the account, then book a second shrinkage credit on top of the zero.

    The residual 701 cents is above zero, so the insufficient-balance guard is
    satisfied, and below the 2,000-cent minimum, so the payout-minimum guard is
    violated at the same time as the escheatment guard.
    """
    world = setup_consignor_with_active_agreement(
        schedule_steps=TWO_STEP_SCHEDULE,
        consignor_overrides={"payout_method": "ACH"},
    )
    consignor_id = world["consignor"]["id"]

    lounger = create_item(world["agreement"]["id"], **LOUNGER)
    stool = create_item(world["agreement"]["id"], **STOOL)
    screen_item(lounger["id"], scores=SCORES_GRADE_C)
    screen_item(stool["id"], scores=SCORES_GRADE_C)
    take_custody(consignor_id, [lounger["id"], stool["id"]])
    receive_item(lounger["id"], scores=SCORES_GRADE_C)
    receive_item(stool["id"], scores=SCORES_GRADE_C)

    world["zone"] = create_zone(
        name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200
    )
    place_item(lounger["id"], world["zone"]["id"], tag_code="T-8001")
    place_item(stool["id"], world["zone"]["id"], tag_code="T-8002")

    flag_inventory(lounger["id"], "MISSING")
    write_off_item(lounger["id"])
    world["balance_before_escheat"] = fetch_consignor(consignor_id)[
        "unclaimed_balance_cents"
    ]

    set_clock("2028-01-28T00:00:00Z")
    run_escheatment_epoch()
    escheated = fetch_consignor(consignor_id)
    world["balance_after_escheat"] = escheated["unclaimed_balance_cents"]
    # Captured before the second write-off: PRD 2.11 says every minted entry other
    # than an ESCHEATMENT_DEBIT does refresh last_activity_at, so the stamp has to
    # be observed while the escheatment debit is the newest entry on the account.
    world["last_activity_after_escheat"] = escheated["last_activity_at"]

    flag_inventory(stool["id"], "MISSING")
    write_off_item(stool["id"])

    world["lounger"] = lounger
    world["stool"] = stool
    return world


def test_escheated_account_answers_before_the_payout_minimum_is_consulted():
    """Both money guards are violated, and the escheatment guard names the error.

    PRD 2.9: "Checks run in the strict order below; the first violated check answers
    the request and no later check is consulted."

    PRD 2.9: "The consignor's `escheat_state` is not `ESCHEATED`, on payout
    disbursement, agreement creation and item intake"

    PRD 3.9: "The balance must be strictly greater than zero, otherwise
    `ERR_INSUFFICIENT_BALANCE`, and it must then be at least the 2,000-cent payout
    minimum, otherwise `ERR_PAYOUT_BELOW_MINIMUM`"

    Design: Difficulty/priority_pair_validation_conflict/escheated_state_p11_beats_payout_minimum_p39
    """
    world = _escheated_account_left_holding_seven_hundred_and_one_cents()
    consignor_id = world["consignor"]["id"]

    before = fetch_consignor(consignor_id)
    assert before["escheat_state"] == "ESCHEATED", (
        f"Expected ESCHEATED before the request, got {before['escheat_state']}"
    )
    assert before["unclaimed_balance_cents"] == 701, (
        f"Expected a residual 701 cents, got {before['unclaimed_balance_cents']}"
    )

    response = api_client.create_payout(
        consignor_id, payout_payload(before["version"]), GALLERY_MANAGER
    )
    validate_error(response, ApiErrorId.ERR_CONSIGNOR_ESCHEATED, 409)

    after = fetch_consignor(consignor_id)
    assert after["unclaimed_balance_cents"] == 701, (
        f"Expected the balance untouched by the refusal, "
        f"got {after['unclaimed_balance_cents']}"
    )
    assert after["version"] == before["version"], (
        f"Expected version {before['version']} unchanged by the refusal, "
        f"got {after['version']}"
    )

    entries = fetch_consignor_ledger(consignor_id)
    assert [e["amount_cents"] for e in entries] == [-19_500, 28_050, -8_550, 701], (
        f"Expected the refused payout to mint nothing, got "
        f"{[e['amount_cents'] for e in entries]}"
    )


def test_the_escheatment_epoch_zeroes_the_balance_without_moving_the_clock_forward():
    """The debit that emptied the account is the one entry that does not reset dormancy.

    PRD 3.9: "one `ESCHEATMENT_DEBIT` entry for the negation of the whole
    `unclaimed_balance_cents` is minted, driving the recomputed balance to exactly 0"

    PRD 2.11: "so escheating a balance cannot restart the dormancy curve that produced
    the escheatment"

    PRD 3.9: "every one of their `ACTIVE` agreements is moved `ACTIVE → TERMINATED` in
    the same run"

    PRD 2.10: "Pieces in `WRITTEN_OFF_INV` and pieces in `RELEASED` are excluded"

    Design: Difficulty/priority_pair_validation_conflict/escheated_state_p11_beats_payout_minimum_p39
    """
    world = _escheated_account_left_holding_seven_hundred_and_one_cents()
    consignor_id = world["consignor"]["id"]

    assert world["balance_before_escheat"] == 8_550, (
        f"Expected 28050 of shrinkage credit less 19500 of surcharge, "
        f"got {world['balance_before_escheat']}"
    )
    assert world["balance_after_escheat"] == 0, (
        f"Expected the escheatment to empty the account, "
        f"got {world['balance_after_escheat']}"
    )

    entries = fetch_consignor_ledger(consignor_id)
    escheats = [e for e in entries if e["entry_type"] == "ESCHEATMENT_DEBIT"]
    assert len(escheats) == 1, (
        f"Expected exactly one escheatment debit, got {len(escheats)}"
    )
    assert escheats[0]["amount_cents"] == -8_550, (
        f"Expected -8550, got {escheats[0]['amount_cents']}"
    )
    assert escheats[0]["balance_after_cents"] == 0, (
        f"Expected a running balance of 0, "
        f"got {escheats[0]['balance_after_cents']}"
    )

    assert world["last_activity_after_escheat"].startswith("2026-08-01T00:00:00"), (
        f"Expected the dormancy clock left at the last real activity, "
        f"got {world['last_activity_after_escheat']}"
    )

    agreement = fetch_agreement(world["agreement"]["id"])
    assert agreement["status"] == "TERMINATED", (
        f"Expected the agreement closed out by the epoch, got {agreement['status']}"
    )

    zone = fetch_zone(world["zone"]["id"])
    assert zone["occupied_sqft"] == 0, (
        f"Expected both written-off pieces to free their footage, "
        f"got {zone['occupied_sqft']}"
    )
    assert zone["utilization_state"] == "NORMAL", (
        f"Expected NORMAL on an empty zone, got {zone['utilization_state']}"
    )


def _etching_parked_exactly_on_its_election_deadline():
    """An unsold ART piece whose fourteen-day election window closes this instant."""
    world = setup_consignor_with_active_agreement(
        consignor_overrides={"payout_method": "ACH"}
    )
    consignor_id = world["consignor"]["id"]

    etching = create_item(world["agreement"]["id"], **ETCHING)
    screen_item(etching["id"], scores=SCORES_GRADE_A)
    take_custody(consignor_id, [etching["id"]])
    receive_item(etching["id"], scores=SCORES_GRADE_A)
    world["zone"] = create_zone(
        name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200
    )
    place_item(etching["id"], world["zone"]["id"], tag_code="T-9001")

    set_clock("2026-11-29T00:00:00Z")
    run_markdown_epoch()
    set_clock("2026-12-13T00:00:00Z")

    world["etching"] = etching
    return world


def test_a_closed_election_window_answers_before_donate_eligibility_is_tested():
    """An ART piece asked to be donated one instant too late reads as a lapsed window.

    PRD 2.9: "The logical clock is strictly before `election_deadline_at`, on
    disposition election — otherwise `ERR_ELECTION_DEADLINE_PASSED` (409)."

    PRD 2.9: "The elected disposition is available for this item, on disposition
    election — otherwise `ERR_DISPOSITION_NOT_ELIGIBLE` (422)."

    PRD 3.7: "`DONATE` is refused for a piece whose `category` is `ART`"

    Design: Difficulty/priority_pair_validation_conflict/election_deadline_p19_beats_disposition_eligibility_p30
    """
    world = _etching_parked_exactly_on_its_election_deadline()
    item_id = world["etching"]["id"]

    before = fetch_item(item_id)
    assert before["lifecycle_state"] == "UNSOLD_PENDING_ELECTION", (
        f"Expected UNSOLD_PENDING_ELECTION, got {before['lifecycle_state']}"
    )
    assert before["markdown_sequence"] == 4, (
        f"Expected the fourth step in force, got {before['markdown_sequence']}"
    )
    assert before["current_price_cents"] == 66_275, (
        f"Expected 66275 at half off 132550, got {before['current_price_cents']}"
    )
    assert before["election_deadline_at"].startswith("2026-12-13T00:00:00"), (
        f"Expected the window to close at the current instant, "
        f"got {before['election_deadline_at']}"
    )

    response = api_client.elect_disposition(
        item_id, elect_disposition_payload("DONATE"), GALLERY_MANAGER
    )
    validate_error(response, ApiErrorId.ERR_ELECTION_DEADLINE_PASSED, 409)

    after = fetch_item(item_id)
    assert after["disposition_election"] == before["disposition_election"], (
        f"Expected no election recorded, got {after['disposition_election']}"
    )
    assert after["election_deadline_at"] == before["election_deadline_at"], (
        f"Expected the deadline untouched, got {after['election_deadline_at']}"
    )
    assert after["lifecycle_state"] == "UNSOLD_PENDING_ELECTION", (
        f"Expected the piece to stay awaiting an election, "
        f"got {after['lifecycle_state']}"
    )
    assert after["version"] == before["version"], (
        f"Expected version {before['version']} unchanged, got {after['version']}"
    )


def test_the_lapsed_window_refuses_a_return_the_piece_is_otherwise_entitled_to():
    """RETURN is eligible for this piece, and it is still refused on the deadline.

    PRD 3.7: "every one of them requires the logical clock to be strictly before
    `election_deadline_at`, on pain of `ERR_ELECTION_DEADLINE_PASSED`"

    PRD 2.9: "Checks run in the strict order below; the first violated check answers
    the request and no later check is consulted."

    Design: Difficulty/priority_pair_validation_conflict/election_deadline_p19_beats_disposition_eligibility_p30
    """
    world = _etching_parked_exactly_on_its_election_deadline()
    item_id = world["etching"]["id"]
    consignor_id = world["consignor"]["id"]
    before = fetch_item(item_id)

    response = api_client.elect_disposition(
        item_id, elect_disposition_payload("RETURN"), GALLERY_MANAGER
    )
    validate_error(response, ApiErrorId.ERR_ELECTION_DEADLINE_PASSED, 409)

    item = fetch_item(item_id)
    assert item["lifecycle_state"] == "UNSOLD_PENDING_ELECTION", (
        f"Expected the piece to stay awaiting an election, "
        f"got {item['lifecycle_state']}"
    )
    assert item["disposition_election"] == before["disposition_election"], (
        f"Expected no election recorded, got {item['disposition_election']}"
    )

    consignor = fetch_consignor(consignor_id)
    assert consignor["unclaimed_balance_cents"] == -17_000, (
        f"Expected only the 17000 collection debit, "
        f"got {consignor['unclaimed_balance_cents']}"
    )
    entries = fetch_consignor_ledger(consignor_id)
    assert len(entries) == 1, (
        f"Expected a single ledger entry, got {len(entries)}: "
        f"{[e['entry_type'] for e in entries]}"
    )
