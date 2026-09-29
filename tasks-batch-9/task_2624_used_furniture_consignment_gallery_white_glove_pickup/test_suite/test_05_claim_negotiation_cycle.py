"""The information-request loop on a damage claim, and where it stops."""

from test_helpers import (
    GALLERY_MANAGER,
    SCORES_GRADE_B,
    ApiErrorId,
    adjudicate_claim,
    fetch_damage_claim,
    request_claim_info,
    request_info_payload,
    resubmit_claim,
    setup_damage_claim,
    validate_error,
)

CLAIM_SOFA = {
    "title": "Tuxedo sofa",
    "category": "SOFA",
    "declared_value_cents": 189_950,
    "photo_count": 5,
    "volume_cuft": 55,
    "footprint_sqft": 24,
}


def _claim_at_the_end_of_the_loop():
    """A claim that has already been through both permitted information passes."""
    world = setup_damage_claim(
        claim_amount_cents=30_000,
        sale_price_cents=126_317,
        screen_scores=SCORES_GRADE_B,
        item_overrides=CLAIM_SOFA,
    )
    claim_id = world["claim"]["id"]
    buyer_id = world["buyer"]["id"]

    request_claim_info(claim_id, "Send photographs of the scuff")
    resubmit_claim(claim_id, buyer_id, "Photographs attached, 12cm on the left arm")
    request_claim_info(claim_id, "Also send the crew handover sheet")
    resubmit_claim(claim_id, buyer_id, "Handover sheet attached, signed by the crew lead")
    return world


def test_both_permitted_information_passes_advance_the_resubmission_counter():
    """Two full round trips are legal, and only the resubmission side counts.

    PRD 3.8: "which moves it `SUBMITTED → INFO_REQUESTED`, stores the note, leaves
    `resubmission_count` unchanged"; "With `withdraw` false or absent, the claim moves
    `INFO_REQUESTED → SUBMITTED`, `resubmission_count` is incremented by 1, and the
    stored `description` is replaced by the resubmitted narrative."

    Design: Difficulty/non_linear_state_machine/damage_claim_info_request_cycle_terminates_on_third_pass
    """
    world = setup_damage_claim(
        claim_amount_cents=30_000,
        sale_price_cents=126_317,
        screen_scores=SCORES_GRADE_B,
        item_overrides=CLAIM_SOFA,
    )
    claim_id = world["claim"]["id"]
    buyer_id = world["buyer"]["id"]

    assert world["claim"]["status"] == "SUBMITTED", (
        f"Expected SUBMITTED, got {world['claim']['status']}"
    )
    assert world["claim"]["resubmission_count"] == 0, (
        f"Expected 0, got {world['claim']['resubmission_count']}"
    )

    request_claim_info(claim_id, "Send photographs of the scuff")
    resubmit_claim(claim_id, buyer_id, "Photographs attached, 12cm on the left arm")
    after_first = fetch_damage_claim(claim_id)
    assert after_first["status"] == "SUBMITTED", (
        f"Expected SUBMITTED, got {after_first['status']}"
    )
    assert after_first["resubmission_count"] == 1, (
        f"Expected 1, got {after_first['resubmission_count']}"
    )

    request_claim_info(claim_id, "Also send the crew handover sheet")
    after_second_request = fetch_damage_claim(claim_id)
    assert after_second_request["status"] == "INFO_REQUESTED", (
        f"Expected INFO_REQUESTED, got {after_second_request['status']}"
    )
    assert after_second_request["resubmission_count"] == 1, (
        "An information request must not advance the counter, got "
        f"{after_second_request['resubmission_count']}"
    )

    resubmit_claim(claim_id, buyer_id, "Handover sheet attached, signed by the crew lead")
    after_second = fetch_damage_claim(claim_id)
    assert after_second["status"] == "SUBMITTED", (
        f"Expected SUBMITTED, got {after_second['status']}"
    )
    assert after_second["resubmission_count"] == 2, (
        f"Expected 2, got {after_second['resubmission_count']}"
    )


def test_third_information_request_is_refused_by_the_counter_guard(api):
    """The loop terminates on the count, not on the claim's state.

    PRD 3.8: "The negotiation cycle is bounded at two passes: both the information
    request and the resubmission require `resubmission_count` to be strictly below 2,
    and an attempt beyond that is refused with `ERR_CLAIM_RESUBMIT_LIMIT`."

    Design: Difficulty/non_linear_state_machine/damage_claim_info_request_cycle_terminates_on_third_pass
    """
    world = _claim_at_the_end_of_the_loop()
    claim_id = world["claim"]["id"]
    before = fetch_damage_claim(claim_id)
    assert before["status"] == "SUBMITTED", (
        "The from-state guard is satisfied at this moment, got "
        f"{before['status']}"
    )

    response = api.request_claim_info(
        claim_id,
        request_info_payload("One more round of detail please"),
        GALLERY_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_CLAIM_RESUBMIT_LIMIT, 409)

    after = fetch_damage_claim(claim_id)
    assert after["status"] == "SUBMITTED", (
        f"The refused call must change nothing, got {after['status']}"
    )
    assert after["resubmission_count"] == 2, (
        f"Expected 2, got {after['resubmission_count']}"
    )
    assert after["version"] == before["version"], (
        f"Expected version {before['version']}, got {after['version']}"
    )


def test_claim_stalled_at_the_limit_can_still_be_adjudicated():
    """Exhausting the loop leaves the claim resolvable, not wedged.

    PRD 3.8: "the gallery bucket is the smaller of `adjudicated_amount_cents` and
    5,000 cents, and the remainder is `adjudicated_amount_cents` less that bucket.
    When `fault_party` is `CONSIGNOR` the whole remainder becomes
    `consignor_debited_cents`"

    Design: Difficulty/non_linear_state_machine/damage_claim_info_request_cycle_terminates_on_third_pass
    """
    world = _claim_at_the_end_of_the_loop()

    claim = adjudicate_claim(world["claim"]["id"], True, "CONSIGNOR")

    assert claim["status"] == "APPROVED", (
        f"Expected APPROVED, got {claim['status']}"
    )
    assert claim["adjudicated_amount_cents"] == 30_000, (
        f"Expected 30000, got {claim['adjudicated_amount_cents']}"
    )
    assert claim["gallery_absorbed_cents"] == 5_000, (
        f"Expected the 5000 deductible, got {claim['gallery_absorbed_cents']}"
    )
    assert claim["consignor_debited_cents"] == 25_000, (
        f"Expected 25000, got {claim['consignor_debited_cents']}"
    )
