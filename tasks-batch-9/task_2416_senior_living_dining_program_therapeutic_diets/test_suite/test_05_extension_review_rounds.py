"""Therapeutic extensions: the bounded revision loop and item coverage."""
from test_helpers import (
    DIETITIAN,
    DIETITIAN_ALT,
    ApiErrorId,
    add_menu_item,
    api_client,
    create_community,
    create_menu_cycle,
    read_menu_item,
    set_clock,
    validate_error,
    validate_success,
)


def _saltmeadow_extension_at_round_three():
    """An extension driven through three change-request rounds and resubmitted."""
    set_clock("2026-08-10T09:00:00Z")
    community = create_community("Brookdale Saltmeadow", ["ASSISTED_LIVING"])
    cycle = create_menu_cycle(
        community["id"],
        week_count=1,
        effective_start_date="2026-08-10",
        effective_end_date="2026-08-16",
    )
    item = add_menu_item(
        cycle["id"],
        item_code="LS-CHICKEN",
        name="Herb Chicken",
        day_index=1,
        meal_period="LUNCH",
        base_texture="REGULAR",
        required_therapeutic_codes=["LOW_SODIUM"],
    )
    extension = validate_success(
        api_client.create_therapeutic_extension(
            item["id"],
            {"diet_code": "LOW_SODIUM", "nutrient_overrides": {"sodium_mg": 400}},
            DIETITIAN,
        ),
        201,
    )
    rounds = []
    for label in ("round 1", "round 2", "round 3"):
        validate_success(
            api_client.submit_therapeutic_extension(extension["id"], DIETITIAN)
        )
        rounds.append(
            validate_success(
                api_client.review_therapeutic_extension(
                    extension["id"],
                    {"decision": "REQUEST_CHANGES", "reviewer_note": label},
                    DIETITIAN_ALT,
                )
            )
        )
    validate_success(api_client.submit_therapeutic_extension(extension["id"], DIETITIAN))
    return {
        "community": community,
        "cycle": cycle,
        "item": item,
        "extension": extension,
        "rounds": rounds,
    }


def test_the_fourth_change_request_is_refused_at_the_round_ceiling(api):
    """Three change-request rounds are accepted and leave `review_round` at 3; the fourth is
    refused because the round counter is no longer strictly below 3.

    PRD: "As with diet orders, a `REQUEST_CHANGES` decision is only accepted while `review_round`
    is strictly below 3, and the fourth attempt is refused with `ERR_REVIEW_ROUND_LIMIT`."

    Design: Difficulty/non_linear_state_machine/therapeutic_extension_bounded_revision_cycle
    """
    program = _saltmeadow_extension_at_round_three()
    assert [row["review_round"] for row in program["rounds"]] == [1, 2, 3]
    assert program["rounds"][-1]["review_status"] == "CHANGES_REQUESTED"

    response = api.review_therapeutic_extension(
        program["extension"]["id"],
        {"decision": "REQUEST_CHANGES", "reviewer_note": "round 4"},
        DIETITIAN_ALT,
    )
    validate_error(response, ApiErrorId.ERR_REVIEW_ROUND_LIMIT, 409)


def test_approval_is_still_reachable_at_the_ceiling_and_completes_item_coverage(api):
    """The ceiling bounds only the change-request loop: an `APPROVE` from the same `SUBMITTED`
    state succeeds with `review_round` still 3 and flips the item's coverage to `COMPLETE`.

    PRD: "`APPROVE` moves the review status to `APPROVED`, sets `reviewed_by_user_id` to the acting
    `X-User-ID`, and recomputes the owning item's `extension_coverage_status`, which flips to
    `COMPLETE` once every code in `required_therapeutic_codes` has an approved extension."

    Design: Difficulty/non_linear_state_machine/therapeutic_extension_bounded_revision_cycle
    """
    program = _saltmeadow_extension_at_round_three()

    response = api.review_therapeutic_extension(
        program["extension"]["id"],
        {"decision": "APPROVE", "reviewer_note": "accepted"},
        DIETITIAN_ALT,
    )
    approved = validate_success(response)

    assert approved["review_status"] == "APPROVED"
    assert approved["review_round"] == 3
    assert read_menu_item(program["item"]["id"])["extension_coverage_status"] == "COMPLETE"
