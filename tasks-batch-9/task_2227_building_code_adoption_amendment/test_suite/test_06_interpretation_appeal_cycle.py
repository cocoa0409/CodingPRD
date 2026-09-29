"""The cyclic interpretation lifecycle: appeal, redraft, republish."""
from test_helpers import (
    ADMIN_OPINION_PUBLISHER_ID,
    STAFF_SECOND_DRAFTER_ID,
    fixtures,
    get_success_data,
    make_council_admin_headers,
    make_jurisdiction_official_headers,
    make_technical_staff_headers,
    validate_success,
)


def _published_opinion_world(api):
    """A published statewide opinion owned by Riverbend, with the clock still
    inside the 30-day appeal window."""
    return fixtures.setup_published_interpretation(api)


def _appeal(api, world):
    return fixtures.act_on_interpretation(
        api,
        world,
        "APPEAL",
        appeal_reason="Conflicts with the energy trade-off path.",
        headers=make_jurisdiction_official_headers(world["riverbend_id"]),
    )


def test_01_the_appeal_returns_the_request_to_assigned_and_clears_the_opinion(api):
    """"The appeal moves the request `PUBLISHED` → `ASSIGNED` so that the opinion
    must be drafted and published again", and "on success `appeal_round`
    increments by one and `opinion_text`, `binding_scope`, `drafted_by_user_id`,
    `published_by_user_id`, `published_at` and `opinion_number` are all cleared
    back to null". The `assigned_committee_id` stored at assignment is not among
    the cleared fields, so the request returns to the same drafting committee.

    Design: Difficulty/non_linear_state_machine/interpretation_request_appeal_cycle_returns_to_assigned_and_renumbers
    """
    world = _published_opinion_world(api)
    assert world["interpretation_request"]["opinion_number"] == 1

    validate_success(_appeal(api, world))

    request = get_success_data(
        api.get_interpretation_request(
            world["interpretation_request_id"], make_council_admin_headers()
        )
    )
    assert request["status"] == "ASSIGNED"
    assert request["appeal_round"] == 1
    assert request["opinion_number"] is None
    assert request["opinion_text"] is None
    assert request["binding_scope"] is None
    assert request["published_at"] is None
    assert request["assigned_committee_id"] == world["committee_id"]


def test_02_the_republished_opinion_takes_a_fresh_number(api):
    """"Publication assigns `opinion_number`, which is monotonic per rulemaking
    order: it is one greater than the highest `opinion_number` ever assigned under
    the same `adoption_rule_id` ... Numbers are never reused, so a republication
    after a successful appeal receives a fresh number even though the appeal
    cleared the old one." Closing the loop `PUBLISHED` → `ASSIGNED` →
    `OPINION_DRAFTED` → `PUBLISHED` therefore lands on opinion 2 while
    `appeal_round` stays at 1, and publication "stamps `published_at` from the
    clock".

    Design: Difficulty/non_linear_state_machine/interpretation_request_appeal_cycle_returns_to_assigned_and_renumbers
    """
    world = _published_opinion_world(api)

    _appeal(api, world)
    fixtures.act_on_interpretation(
        api,
        world,
        "ISSUE_OPINION",
        opinion_text=(
            "Additions under 500 square feet follow the new edition when the "
            "trade-off path is used."
        ),
        binding_scope="REQUESTING_JURISDICTION_ONLY",
        headers=make_technical_staff_headers(STAFF_SECOND_DRAFTER_ID),
    )
    validate_success(
        fixtures.act_on_interpretation(
            api,
            world,
            "PUBLISH",
            headers=make_council_admin_headers(ADMIN_OPINION_PUBLISHER_ID),
        )
    )

    request = get_success_data(
        api.get_interpretation_request(
            world["interpretation_request_id"], make_council_admin_headers()
        )
    )
    assert request["status"] == "PUBLISHED"
    assert request["opinion_number"] == 2
    assert request["appeal_round"] == 1
    assert request["binding_scope"] == "REQUESTING_JURISDICTION_ONLY"
    assert request["assigned_committee_id"] == world["committee_id"]
    assert request["published_at"] == "2026-10-05T14:00:00Z"
