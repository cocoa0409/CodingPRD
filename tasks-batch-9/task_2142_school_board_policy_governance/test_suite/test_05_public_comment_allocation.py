"""Speaker cards, the two minute-allocation variants, and the minute ledger."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adjourn_meeting,
    api_client,
    assert_public_comment_minute_conservation,
    file_speaker_card,
    open_meeting,
    public_comment_payload,
    read_agenda_item,
    read_meeting,
    read_speaker_card,
    seat_board,
    set_clock,
    setup_meeting_with_item_and_cards,
    setup_policy_with_draft,
    validate_error,
    validate_paginated,
    validate_success,
)

PUBLIC = TEST_USERS["public_headers"]


def _cards(*specs):
    rows = []
    for name, affiliation, minutes, clock in specs:
        entry = {
            "speaker_name": name,
            "speaker_affiliation": affiliation,
            "requested_minutes": minutes,
        }
        if clock:
            entry["clock_before"] = clock
        rows.append(entry)
    return rows


def test_first_come_capped_grants_then_partially_grants_then_denies():
    """PRD 3.5: "Under **first-come-capped**, the surviving cards are walked in strict
    ascending `submitted_at` order against a running remainder that starts at the full
    budget. Each card's grant is the smallest of three quantities: the `requested_minutes`
    the speaker asked for, the per-speaker ceiling of three minutes, and whatever is left
    in the remainder. If that grant is at least one minute — the per-speaker floor — the
    card becomes `GRANTED`, its `allotted_minutes` is set to the grant, and the remainder
    falls by the same amount. If the grant is below one minute the card becomes `DENIED`
    with `denial_reason` `BUDGET_EXHAUSTED` and `allotted_minutes` 0."

    Design: Corner/calculations/first_come_capped_grants_then_partially_grants_then_denies_for_budget
    """
    members = seat_board(3)
    policy, version = setup_policy_with_draft(
        "BP-5030", "Student Wellness", "STUDENTS", "RECOMMENDED", "5000.30",
        body_text="Wellness draft.", summary_of_change="Initial draft",
    )
    meeting, item, cards = setup_meeting_with_item_and_cards(
        item_type="POLICY_FIRST_READING",
        item_title="First reading BP-5030",
        policy_version_id=version["id"],
        meeting_title="Special Wellness Meeting",
        meeting_type="SPECIAL",
        cards=_cards(
            ("Faye Nunez", "PARENT", 3, None),
            ("Gil Adams", "STAFF", 3, "2026-08-01T01:00:00Z"),
            ("Hana Ito", "COMMUNITY", 3, "2026-08-01T02:00:00Z"),
        ),
    )
    set_clock("2026-09-10T18:00:00Z")
    opened = open_meeting(meeting["id"], [m["id"] for m in members], members[0]["id"])

    assert opened["public_comment_allocation_variant"] == "FIRST_COME_CAPPED"
    first = read_speaker_card(item["id"], cards[0]["id"])
    second = read_speaker_card(item["id"], cards[1]["id"])
    third = read_speaker_card(item["id"], cards[2]["id"])
    assert first["status"] == "GRANTED" and first["allotted_minutes"] == 3
    assert second["status"] == "GRANTED" and second["allotted_minutes"] == 2
    assert third["status"] == "DENIED" and third["allotted_minutes"] == 0
    assert third["denial_reason"] == "BUDGET_EXHAUSTED"
    assert read_meeting(meeting["id"])["public_comment_minutes_remaining"] == 0


def test_a_repeated_speaker_name_is_suppressed_before_any_budget_is_spent():
    """PRD 3.5: "Before either allocation variant runs, duplicates are suppressed. Walking
    the ordered set once, the first card bearing a given `speaker_name` survives; every
    later card with an identical `speaker_name` is set to `DENIED` with `denial_reason`
    `DUPLICATE_SPEAKER` and `allotted_minutes` 0, and is dropped from the set. No minutes
    are charged for a suppressed duplicate."

    Design: Corner/calculations/duplicate_speaker_name_is_denied_before_any_budget_is_spent
    """
    members = seat_board(3)
    policy, version = setup_policy_with_draft(
        "BP-5030", "Student Wellness", "STUDENTS", "RECOMMENDED", "5000.30",
        body_text="Wellness draft.", summary_of_change="Initial draft",
    )
    meeting, item, cards = setup_meeting_with_item_and_cards(
        item_type="POLICY_FIRST_READING",
        item_title="First reading BP-5030",
        policy_version_id=version["id"],
        meeting_title="Special Wellness Meeting",
        meeting_type="SPECIAL",
        cards=_cards(
            ("Faye Nunez", "PARENT", 3, None),
            ("Faye Nunez", "PARENT", 3, "2026-08-01T01:00:00Z"),
        ),
    )
    set_clock("2026-09-10T18:00:00Z")
    open_meeting(meeting["id"], [m["id"] for m in members], members[0]["id"])

    survivor = read_speaker_card(item["id"], cards[0]["id"])
    duplicate = read_speaker_card(item["id"], cards[1]["id"])
    assert survivor["status"] == "GRANTED" and survivor["allotted_minutes"] == 3
    assert duplicate["status"] == "DENIED" and duplicate["allotted_minutes"] == 0
    assert duplicate["denial_reason"] == "DUPLICATE_SPEAKER"

    after = read_meeting(meeting["id"])
    assert after["public_comment_minutes_remaining"] == 2
    assert after["public_comment_allocation_variant"] == "FIRST_COME_CAPPED"


def test_three_cards_stay_below_the_crowd_threshold():
    """PRD 3.5: "The meeting runs the **equal-split** variant when the meeting's
    `public_comment_rule` is `EQUAL_SPLIT`, or when the number of surviving cards has
    reached four or more — four is the crowd threshold at which honouring individual
    requests stops being fair. Otherwise it runs the **first-come-capped** variant.
    Whichever ran is recorded on the meeting as `public_comment_allocation_variant`."
    PRD 3.5: "This variant honours each speaker's request as an upper bound, so a speaker
    who asked for one minute receives exactly one minute and the rest of the budget stays
    unspent, and later cards can be starved entirely once the budget runs out."

    Design: Corner/calculations/three_speaker_cards_stay_below_the_equal_split_threshold
    """
    members = seat_board(3)
    policy, version = setup_policy_with_draft(
        "BP-5030", "Student Wellness", "STUDENTS", "RECOMMENDED", "5000.30",
        body_text="Wellness draft.", summary_of_change="Initial draft",
    )
    meeting, item, cards = setup_meeting_with_item_and_cards(
        item_type="POLICY_FIRST_READING",
        item_title="First reading BP-5030",
        policy_version_id=version["id"],
        cards=_cards(
            ("Faye Nunez", "PARENT", 1, None),
            ("Gil Adams", "STAFF", 1, None),
            ("Hana Ito", "COMMUNITY", 1, None),
        ),
    )
    set_clock("2026-09-10T18:00:00Z")
    open_meeting(meeting["id"], [m["id"] for m in members], members[0]["id"])

    after = read_meeting(meeting["id"])
    assert after["public_comment_allocation_variant"] == "FIRST_COME_CAPPED"
    for card in cards:
        assert read_speaker_card(item["id"], card["id"])["allotted_minutes"] == 1
    assert after["public_comment_minutes_remaining"] == 27


def test_speaker_card_filed_after_the_gavel_is_refused():
    """PRD 3.5: "A card may only be filed while the parent meeting's `status` is `DRAFT`
    or `NOTICED`, and a card filed against an `OPEN` or `ADJOURNED` meeting is refused with
    `ERR_PUBLIC_COMMENT_CLOSED`."

    Design: Corner/validations/speaker_card_filed_after_the_meeting_opened_returns_public_comment_closed
    """
    members = seat_board(3)
    policy, version = setup_policy_with_draft(
        "BP-5030", "Student Wellness", "STUDENTS", "RECOMMENDED", "5000.30",
        body_text="Wellness draft.", summary_of_change="Initial draft",
    )
    meeting, item, _cards = setup_meeting_with_item_and_cards(
        item_type="POLICY_FIRST_READING",
        item_title="First reading BP-5030",
        policy_version_id=version["id"],
    )
    set_clock("2026-09-10T18:00:00Z")
    open_meeting(meeting["id"], [m["id"] for m in members], members[0]["id"])

    response = api_client.create_public_comment(
        item["id"],
        public_comment_payload(
            speaker_name="Late Larry", speaker_affiliation="COMMUNITY", requested_minutes=2
        ),
        PUBLIC,
    )
    validate_error(response, ApiErrorId.ERR_PUBLIC_COMMENT_CLOSED.value)
    assert response.status_code == 409
    assert read_meeting(meeting["id"])["public_comment_minutes_remaining"] == 30
    _rows, meta = validate_paginated(api_client.list_public_comments(item["id"], PUBLIC))
    assert meta["total_count"] == 0


def test_emergency_meeting_has_no_public_comment_period():
    """PRD 3.5: "A meeting whose `public_comment_minutes_budget` is zero has no
    public-comment period at all — this is the emergency meeting case — and so does an
    agenda item whose `requires_public_comment` is false; both are refused with
    `ERR_PUBLIC_COMMENT_NOT_PERMITTED`."
    PRD 3.4: "a regular meeting carries half an hour of public comment, thirty minutes; a
    special meeting carries five minutes; an emergency meeting carries none at all."

    Design: Corner/validations/speaker_card_on_an_emergency_meeting_returns_public_comment_not_permitted
    """
    policy, version = setup_policy_with_draft()
    meeting, item, _cards = setup_meeting_with_item_and_cards(
        item_type="POLICY_FIRST_READING",
        item_title="Emergency first reading BP-4119",
        policy_version_id=version["id"],
        meeting_title="Emergency Board Meeting",
        meeting_type="EMERGENCY",
        scheduled_start_utc="2026-08-02T18:00:00Z",
        post_the_notice=False,
    )

    response = api_client.create_public_comment(
        item["id"],
        public_comment_payload(
            speaker_name="Iris Vega", speaker_affiliation="PARENT", requested_minutes=2
        ),
        PUBLIC,
    )
    validate_error(response, ApiErrorId.ERR_PUBLIC_COMMENT_NOT_PERMITTED.value)
    assert response.status_code == 422
    assert read_meeting(meeting["id"])["public_comment_minutes_budget"] == 0
    assert read_agenda_item(item["id"])["requires_public_comment"] is True


def test_a_sixth_speaker_card_on_one_item_is_refused():
    """PRD 3.5: "And no agenda item may hold more than five speaker cards in `REQUESTED`
    or `GRANTED` status at once; the sixth is refused with `ERR_SPEAKER_LIMIT_REACHED`."

    Design: Corner/validations/sixth_speaker_card_on_one_item_returns_speaker_limit_reached
    """
    policy, version = setup_policy_with_draft(
        "BP-5030", "Student Wellness", "STUDENTS", "RECOMMENDED", "5000.30",
        body_text="Wellness draft.", summary_of_change="Initial draft",
    )
    meeting, item, cards = setup_meeting_with_item_and_cards(
        item_type="POLICY_FIRST_READING",
        item_title="First reading BP-5030",
        policy_version_id=version["id"],
        post_the_notice=False,
        cards=_cards(
            ("Speaker One", "PARENT", 1, None),
            ("Speaker Two", "PARENT", 1, None),
            ("Speaker Three", "STAFF", 1, None),
            ("Speaker Four", "STUDENT", 1, None),
            ("Speaker Five", "COMMUNITY", 1, None),
        ),
    )

    response = api_client.create_public_comment(
        item["id"],
        public_comment_payload(
            speaker_name="Speaker Six", speaker_affiliation="VENDOR", requested_minutes=1
        ),
        PUBLIC,
    )
    validate_error(response, ApiErrorId.ERR_SPEAKER_LIMIT_REACHED.value)
    assert response.status_code == 422

    _rows, meta = validate_paginated(api_client.list_public_comments(item["id"], PUBLIC))
    assert meta["total_count"] == 5
    assert read_speaker_card(item["id"], cards[4]["id"])["status"] == "REQUESTED"


def _two_variant_scenario():
    """Two SPECIAL meetings carrying byte-identical speaker cards, differing only in
    `public_comment_rule`."""
    members = seat_board(3)
    from test_helpers import (
        add_agenda_item,
        draft_version,
        post_notice,
        read_policy,
        register_policy,
        schedule_meeting,
    )

    policy = register_policy()
    first_version = draft_version(
        policy["id"], policy["version"], body_text="Draft one text.", summary_of_change="Initial draft"
    )
    second_version = draft_version(
        policy["id"],
        first_version["policy_version_after"],
        body_text="Draft two text.",
        summary_of_change="Alternate draft",
    )

    meeting_x = schedule_meeting(
        title="Special Meeting X",
        meeting_type="SPECIAL",
        scheduled_start_utc="2026-08-05T18:00:00Z",
    )
    item_x = add_agenda_item(
        meeting_x["id"],
        meeting_x["version"],
        item_type="POLICY_FIRST_READING",
        title="First reading draft one",
        policy_version_id=first_version["id"],
    )
    meeting_y = schedule_meeting(
        title="Special Meeting Y",
        meeting_type="SPECIAL",
        scheduled_start_utc="2026-08-06T18:00:00Z",
        public_comment_rule="EQUAL_SPLIT",
    )
    item_y = add_agenda_item(
        meeting_y["id"],
        meeting_y["version"],
        item_type="POLICY_FIRST_READING",
        title="First reading draft two",
        policy_version_id=second_version["id"],
    )

    dana_x = file_speaker_card(item_x["id"], "Dana Ortiz", "PARENT", 1)
    dana_y = file_speaker_card(item_y["id"], "Dana Ortiz", "PARENT", 1)
    set_clock("2026-08-01T01:00:00Z")
    evan_x = file_speaker_card(item_x["id"], "Evan Park", "COMMUNITY", 1)
    evan_y = file_speaker_card(item_y["id"], "Evan Park", "COMMUNITY", 1)

    post_notice(meeting_x["id"])
    post_notice(meeting_y["id"])

    set_clock("2026-08-05T18:00:00Z")
    open_meeting(meeting_x["id"], [m["id"] for m in members], members[0]["id"])
    set_clock("2026-08-06T18:00:00Z")
    open_meeting(meeting_y["id"], [m["id"] for m in members], members[0]["id"])

    return {
        "meeting_x": meeting_x,
        "item_x": item_x,
        "dana_x": dana_x,
        "evan_x": evan_x,
        "meeting_y": meeting_y,
        "item_y": item_y,
        "dana_y": dana_y,
        "evan_y": evan_y,
    }


def test_first_come_capped_honours_the_request_on_identical_cards():
    """PRD 3.5: "The meeting runs the **equal-split** variant when the meeting's
    `public_comment_rule` is `EQUAL_SPLIT`, or when the number of surviving cards has
    reached four or more — four is the crowd threshold at which honouring individual
    requests stops being fair. Otherwise it runs the **first-come-capped** variant.
    Whichever ran is recorded on the meeting as `public_comment_allocation_variant`."
    PRD 3.5: "This variant honours each speaker's request as an upper bound, so a speaker
    who asked for one minute receives exactly one minute and the rest of the budget stays
    unspent, and later cards can be starved entirely once the budget runs out."

    Design: Difficulty/dual_variant_calc/public_comment_allocation_two_variants_same_speaker_cards
    """
    scenario = _two_variant_scenario()
    meeting_x = read_meeting(scenario["meeting_x"]["id"])
    assert meeting_x["public_comment_allocation_variant"] == "FIRST_COME_CAPPED"

    dana = read_speaker_card(scenario["item_x"]["id"], scenario["dana_x"]["id"])
    evan = read_speaker_card(scenario["item_x"]["id"], scenario["evan_x"]["id"])
    assert dana["allotted_minutes"] == 1
    assert evan["allotted_minutes"] == 1
    assert dana["status"] == "GRANTED"
    assert meeting_x["public_comment_minutes_remaining"] == 3


def test_equal_split_ignores_the_request_on_identical_cards():
    """PRD 3.5: "Under **equal-split**, `requested_minutes` is ignored completely. The
    base share is the budget divided by the number of surviving cards with the remainder
    discarded — the flooring happens first, before any cap is applied — and the capped base
    is the smaller of that base and the three-minute per-speaker ceiling."
    PRD 3.5: "On identical card data, equal-split produces strictly larger per-speaker
    allotments and a strictly smaller `public_comment_minutes_remaining` than
    first-come-capped whenever the speakers asked for less than their equal share."

    Design: Difficulty/dual_variant_calc/public_comment_allocation_two_variants_same_speaker_cards
    """
    scenario = _two_variant_scenario()
    meeting_y = read_meeting(scenario["meeting_y"]["id"])
    assert meeting_y["public_comment_allocation_variant"] == "EQUAL_SPLIT"

    dana = read_speaker_card(scenario["item_y"]["id"], scenario["dana_y"]["id"])
    evan = read_speaker_card(scenario["item_y"]["id"], scenario["evan_y"]["id"])
    assert dana["allotted_minutes"] == 3
    assert evan["allotted_minutes"] == 2
    assert dana["status"] == "GRANTED"
    assert meeting_y["public_comment_minutes_remaining"] == 0


def _equal_split_three_card_scenario():
    members = seat_board(3)
    policy, version = setup_policy_with_draft(
        "BP-5030", "Student Wellness", "STUDENTS", "RECOMMENDED", "5000.30",
        body_text="Wellness draft.", summary_of_change="Initial draft",
    )
    meeting, item, cards = setup_meeting_with_item_and_cards(
        item_type="POLICY_FIRST_READING",
        item_title="First reading BP-5030",
        policy_version_id=version["id"],
        meeting_title="Special Wellness Meeting",
        meeting_type="SPECIAL",
        scheduled_start_utc="2026-08-05T18:00:00Z",
        public_comment_rule="EQUAL_SPLIT",
        cards=_cards(
            ("Faye Nunez", "PARENT", 3, None),
            ("Gil Adams", "STAFF", 3, "2026-08-01T01:00:00Z"),
            ("Hana Ito", "COMMUNITY", 3, "2026-08-01T02:00:00Z"),
        ),
    )
    set_clock("2026-08-05T18:00:00Z")
    open_meeting(meeting["id"], [m["id"] for m in members], members[0]["id"])
    return meeting, item, cards


def test_equal_split_floors_the_base_share_before_the_ceiling_is_applied():
    """PRD 3.5: "Under **equal-split**, `requested_minutes` is ignored completely. The
    base share is the budget divided by the number of surviving cards with the remainder
    discarded — the flooring happens first, before any cap is applied — and the capped base
    is the smaller of that base and the three-minute per-speaker ceiling."
    PRD 2.8: "Public-comment minutes are **whole minutes only**. Every intermediate share
    in the allocation is floored — rounded down to the next whole minute — and never
    rounded to nearest."

    Design: Difficulty/combinatorial_formula/equal_split_floor_then_remainder_sweep_rounding_order
    """
    meeting, item, cards = _equal_split_three_card_scenario()
    assert read_meeting(meeting["id"])["public_comment_allocation_variant"] == "EQUAL_SPLIT"

    allotments = [read_speaker_card(item["id"], c["id"])["allotted_minutes"] for c in cards]
    assert allotments == [2, 2, 1], f"expected the 2 / 2 / 1 split, got {allotments}"


def test_equal_split_walks_the_remainder_out_in_a_single_ordered_sweep():
    """PRD 3.5: "Otherwise every surviving card is `GRANTED` the capped base and the
    remainder is reduced accordingly, after which the integer remainder is walked out in a
    **single** sweep in the same ascending `submitted_at` order: each card that is still
    below the three-minute ceiling gains one more minute and the remainder falls by one,
    and the sweep stops the instant the remainder reaches zero."
    PRD 3.5: "Whatever is left after allocation is written to the meeting as
    `public_comment_minutes_remaining`."

    Design: Difficulty/combinatorial_formula/equal_split_floor_then_remainder_sweep_rounding_order
    """
    meeting, item, cards = _equal_split_three_card_scenario()
    rows = [read_speaker_card(item["id"], c["id"]) for c in cards]

    assert sum(r["allotted_minutes"] for r in rows) == 5
    assert rows[2]["status"] == "GRANTED"
    after = read_meeting(meeting["id"])
    assert after["public_comment_minutes_remaining"] == 0
    assert_public_comment_minute_conservation(after, rows)


def _four_card_scenario():
    members = seat_board(3)
    policy, version = setup_policy_with_draft(
        "BP-5030", "Student Wellness", "STUDENTS", "RECOMMENDED", "5000.30",
        body_text="Wellness draft.", summary_of_change="Initial draft",
    )
    meeting, item, cards = setup_meeting_with_item_and_cards(
        item_type="POLICY_FIRST_READING",
        item_title="First reading BP-5030",
        policy_version_id=version["id"],
        cards=_cards(
            ("Faye Nunez", "PARENT", 1, None),
            ("Gil Adams", "STAFF", 1, None),
            ("Hana Ito", "COMMUNITY", 1, None),
            ("Iris Vega", "STUDENT", 1, None),
        ),
    )
    set_clock("2026-09-10T18:00:00Z")
    opened = open_meeting(meeting["id"], [m["id"] for m in members], members[0]["id"])
    return opened, item, cards


def test_a_fourth_card_flips_a_first_come_capped_meeting_to_equal_split():
    """PRD 3.5: "The meeting runs the **equal-split** variant when the meeting's
    `public_comment_rule` is `EQUAL_SPLIT`, or when the number of surviving cards has
    reached four or more — four is the crowd threshold at which honouring individual
    requests stops being fair. Otherwise it runs the **first-come-capped** variant.
    Whichever ran is recorded on the meeting as `public_comment_allocation_variant`."

    Design: Difficulty/boundary_precision_check/equal_split_override_at_exactly_four_speaker_cards
    """
    opened, item, cards = _four_card_scenario()
    assert opened["public_comment_allocation_variant"] == "EQUAL_SPLIT"
    assert opened["public_comment_rule"] == "FIRST_COME_CAPPED"


def test_at_four_cards_every_speaker_receives_the_capped_base_share():
    """PRD 3.5: "Under **equal-split**, `requested_minutes` is ignored completely. The
    base share is the budget divided by the number of surviving cards with the remainder
    discarded — the flooring happens first, before any cap is applied — and the capped base
    is the smaller of that base and the three-minute per-speaker ceiling."
    PRD 3.5: "Whatever is left after allocation is written to the meeting as
    `public_comment_minutes_remaining`."

    Design: Difficulty/boundary_precision_check/equal_split_override_at_exactly_four_speaker_cards
    """
    opened, item, cards = _four_card_scenario()
    rows = [read_speaker_card(item["id"], c["id"]) for c in cards]
    assert [r["allotted_minutes"] for r in rows] == [3, 3, 3, 3]

    after = read_meeting(opened["id"])
    assert after["public_comment_minutes_remaining"] == 18
    assert after["public_comment_minutes_budget"] == 30
    assert_public_comment_minute_conservation(after, rows)


def _conservation_scenario():
    members = seat_board(3)
    policy, version = setup_policy_with_draft(
        "BP-5030", "Student Wellness", "STUDENTS", "RECOMMENDED", "5000.30",
        body_text="Wellness draft.", summary_of_change="Initial draft",
    )
    meeting, item, cards = setup_meeting_with_item_and_cards(
        item_type="POLICY_FIRST_READING",
        item_title="First reading BP-5030",
        policy_version_id=version["id"],
        meeting_title="Special Wellness Meeting",
        meeting_type="SPECIAL",
        public_comment_rule="FIRST_COME_CAPPED",
        cards=_cards(
            ("Iris Vega", "PARENT", 3, None),
            ("Jonah Park", "STAFF", 3, "2026-08-01T01:00:00Z"),
        ),
    )
    set_clock("2026-09-10T18:00:00Z")
    return members, meeting, item, cards


def test_opening_debits_the_budget_and_the_minute_ledger_balances():
    """PRD 2.10: "A meeting's `public_comment_minutes_budget` always equals its
    `public_comment_minutes_remaining` plus the sum of `allotted_minutes` over every
    speaker card in `GRANTED` status attached to any agenda item on that meeting. Opening a
    meeting is the forward action that debits the budget by every granted minute; releasing
    cards — when an item is tabled at adjournment, or withdrawn because its waiver died —
    is the compensating action that credits every released minute back."

    Design: Difficulty/compensating_invariant/public_comment_minutes_conserved_across_grant_and_release
    """
    members, meeting, item, cards = _conservation_scenario()
    opened = open_meeting(meeting["id"], [m["id"] for m in members], members[0]["id"])
    assert opened["public_comment_minutes_remaining"] == 0

    rows = [read_speaker_card(item["id"], c["id"]) for c in cards]
    assert rows[0]["allotted_minutes"] == 3
    assert rows[1]["allotted_minutes"] == 2
    assert_public_comment_minute_conservation(read_meeting(meeting["id"]), rows)


def test_adjourning_credits_every_released_minute_back_to_the_meeting():
    """PRD 3.6: "Every agenda item still in `POSTED` status when the gavel falls moves to
    `TABLED`, and every `GRANTED` speaker card on a newly tabled item moves to `RELEASED`
    with `denial_reason` `ITEM_WITHDRAWN`, `allotted_minutes` reset to 0, and its minutes
    credited back to `public_comment_minutes_remaining`."
    PRD 2.10: "A meeting's `public_comment_minutes_budget` always equals its
    `public_comment_minutes_remaining` plus the sum of `allotted_minutes` over every
    speaker card in `GRANTED` status attached to any agenda item on that meeting."

    Design: Difficulty/compensating_invariant/public_comment_minutes_conserved_across_grant_and_release
    """
    members, meeting, item, cards = _conservation_scenario()
    open_meeting(meeting["id"], [m["id"] for m in members], members[0]["id"])

    adjourned = adjourn_meeting(meeting["id"])
    assert adjourned["public_comment_minutes_remaining"] == 5

    after = read_meeting(meeting["id"])
    assert after["public_comment_minutes_budget"] == 5
    assert after["public_comment_minutes_remaining"] == 5
    rows = [read_speaker_card(item["id"], c["id"]) for c in cards]
    for row in rows:
        assert row["status"] == "RELEASED"
        assert row["allotted_minutes"] == 0
    assert read_agenda_item(item["id"])["status"] == "TABLED"
    assert_public_comment_minute_conservation(after, rows)
