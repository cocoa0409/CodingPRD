"""Menu cycles: the draft-to-published loop, its gates and the committee refresh."""
from test_helpers import (
    DIETITIAN,
    DIETITIAN_ALT,
    DINING_MANAGER,
    ApiErrorId,
    add_menu_item,
    cast_ballot,
    create_community,
    create_menu_cycle,
    create_resident,
    publish_menu_cycle,
    read_community,
    read_menu_cycle,
    read_menu_item,
    set_clock,
    setup_published_menu_cycle,
    submit_menu_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_stocked_cycle_walks_draft_to_signoff_to_published(api):
    """The rotation moves `DRAFT` -> `PENDING_DIETITIAN_SIGNOFF` -> `PUBLISHED`, stamps the
    publishing dietitian and becomes the community's active cycle because the logical clock date
    sits inside its effective range.

    PRD: "On success the cycle moves to `PUBLISHED` with `signed_off_by_user_id` set to the acting
    `X-User-ID`."

    Design: Corner/state_machines/menu_cycle_draft_to_signoff_to_published_happy_path
    """
    set_clock("2026-08-12T08:00:00Z")
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    cycle = create_menu_cycle(
        community["id"],
        cycle_number=1,
        week_count=1,
        effective_start_date="2026-08-10",
        effective_end_date="2026-08-16",
    )
    item = add_menu_item(
        cycle["id"],
        item_code="REG-COD",
        name="Baked Cod",
        day_index=1,
        meal_period="LUNCH",
        base_texture="REGULAR",
    )

    assert cycle["status"] == "DRAFT"
    assert item["extension_coverage_status"] == "NOT_REQUIRED"
    assert read_community(community["id"])["active_menu_cycle_id"] is None

    submitted = validate_success(api.submit_menu_cycle(cycle["id"], DINING_MANAGER))
    assert submitted["status"] == "PENDING_DIETITIAN_SIGNOFF"

    published = validate_success(api.publish_menu_cycle(cycle["id"], DIETITIAN))
    assert published["status"] == "PUBLISHED"
    assert published["signed_off_by_user_id"] == DIETITIAN["X-User-ID"]
    assert read_community(community["id"])["active_menu_cycle_id"] == cycle["id"]


def test_publication_waits_for_the_therapeutic_extension_to_be_approved(api):
    """A submitted-but-unapproved extension leaves the item `INCOMPLETE`, so publication is refused
    and the cycle keeps waiting at sign-off; approving the extension completes coverage and the same
    publication then succeeds.

    PRD: "Every item of the cycle whose `required_therapeutic_codes` is non-empty must have
    `extension_coverage_status` equal to `COMPLETE`, or publication is refused with
    `ERR_THERAPEUTIC_COVERAGE_INCOMPLETE`."

    Design: Corner/state_machines/menu_cycle_publish_with_incomplete_coverage_rejected
    """
    set_clock("2026-08-12T08:00:00Z")
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    cycle = create_menu_cycle(
        community["id"],
        cycle_number=1,
        week_count=1,
        effective_start_date="2026-08-10",
        effective_end_date="2026-08-16",
    )
    item = add_menu_item(
        cycle["id"],
        item_code="LS-SOUP",
        name="Low Sodium Minestrone",
        day_index=1,
        meal_period="LUNCH",
        base_texture="REGULAR",
        required_therapeutic_codes=["LOW_SODIUM"],
    )
    assert item["extension_coverage_status"] == "INCOMPLETE"

    extension = validate_success(
        api.create_therapeutic_extension(
            item["id"],
            {"diet_code": "LOW_SODIUM", "nutrient_overrides": {"sodium_mg": 380}},
            DIETITIAN,
        ),
        201,
    )
    validate_success(api.submit_therapeutic_extension(extension["id"], DIETITIAN))
    submit_menu_cycle(cycle["id"])

    refused = api.publish_menu_cycle(cycle["id"], DIETITIAN_ALT)
    validate_error(refused, ApiErrorId.ERR_THERAPEUTIC_COVERAGE_INCOMPLETE, 409)
    assert read_menu_cycle(cycle["id"])["status"] == "PENDING_DIETITIAN_SIGNOFF"

    approved = validate_success(
        api.review_therapeutic_extension(
            extension["id"],
            {"decision": "APPROVE", "reviewer_note": "sodium target met"},
            DIETITIAN_ALT,
        )
    )
    assert approved["review_status"] == "APPROVED"
    assert read_menu_item(item["id"])["extension_coverage_status"] == "COMPLETE"

    published = validate_success(api.publish_menu_cycle(cycle["id"], DIETITIAN_ALT))
    assert published["status"] == "PUBLISHED"


def test_an_empty_cycle_cannot_be_submitted_until_it_owns_an_item(api):
    """Submission has a row-shape precondition of its own: with no items the cycle is refused and
    stays `DRAFT`, and adding a single dish is enough to let the same submission through.

    PRD: "Submitting the cycle itself for sign-off is a `DiningServicesManager` action, accepted
    only from `DRAFT` and only when the cycle owns at least one menu item — an empty cycle cannot be
    submitted and reports `ERR_INVALID_STATE`."

    Design: Corner/state_machines/menu_cycle_submit_with_no_items_cannot_proceed
    """
    set_clock("2026-08-12T08:00:00Z")
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    cycle = create_menu_cycle(
        community["id"],
        cycle_number=1,
        week_count=1,
        effective_start_date="2026-08-10",
        effective_end_date="2026-08-16",
    )

    refused = api.submit_menu_cycle(cycle["id"], DINING_MANAGER)
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE, 409)
    assert read_menu_cycle(cycle["id"])["status"] == "DRAFT"

    add_menu_item(
        cycle["id"],
        item_code="REG-COD",
        name="Baked Cod",
        day_index=1,
        meal_period="LUNCH",
        base_texture="REGULAR",
    )

    submitted = validate_success(api.submit_menu_cycle(cycle["id"], DINING_MANAGER))
    assert submitted["status"] == "PENDING_DIETITIAN_SIGNOFF"


def test_publication_cannot_skip_the_signoff_step(api):
    """Publishing straight out of `DRAFT` is refused by the state tier, and the cycle keeps its
    unsigned posture: no dietitian is recorded and the community has no active cycle.

    PRD: "Publication is the `RegisteredDietitian`'s sign-off and is accepted only from
    `PENDING_DIETITIAN_SIGNOFF`."

    Design: Corner/state_machines/menu_cycle_publish_from_draft_cannot_skip_signoff
    """
    set_clock("2026-08-12T08:00:00Z")
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    cycle = create_menu_cycle(
        community["id"],
        cycle_number=1,
        week_count=1,
        effective_start_date="2026-08-10",
        effective_end_date="2026-08-16",
    )
    add_menu_item(
        cycle["id"],
        item_code="REG-COD",
        name="Baked Cod",
        day_index=1,
        meal_period="LUNCH",
        base_texture="REGULAR",
    )

    response = api.publish_menu_cycle(cycle["id"], DIETITIAN)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

    stalled = read_menu_cycle(cycle["id"])
    assert stalled["status"] == "DRAFT"
    assert stalled["signed_off_by_user_id"] is None
    assert read_community(community["id"])["active_menu_cycle_id"] is None


def test_the_refresh_returns_the_cycle_to_draft_and_acknowledges_the_ballots(api):
    """Two negative ballots among five active residents reach quorum and auto-transition the
    published cycle to `REFRESH_PENDING`; the refresh then resets the loop to `DRAFT` at round 1
    with a zeroed index and clears the ballot pool.

    PRD: "It returns the cycle to `DRAFT` so the next rotation can be authored, increments
    `refresh_round` by 1, stores the supplied `refresh_reason`, and resets `refresh_index` to 0.00
    and `refresh_tier` to `ADVISORY`."

    Design: Corner/state_machines/menu_cycle_refresh_pending_returns_to_draft_and_acknowledges_ballots
    """
    set_clock("2026-08-12T08:00:00Z")
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    voters = [
        create_resident(community["id"], full_name=name, baseline_weight_kg=weight)
        for name, weight in (
            ("Voter One", 70.0),
            ("Voter Two", 71.0),
            ("Silent Three", 72.0),
            ("Silent Four", 73.0),
            ("Silent Five", 74.0),
        )
    ]
    program = setup_published_menu_cycle(
        community["id"],
        cycle_number=1,
        week_count=1,
        effective_start_date="2026-08-10",
        effective_end_date="2026-08-16",
        items=[
            {
                "item_code": "REG-COD",
                "name": "Baked Cod",
                "day_index": 1,
                "meal_period": "LUNCH",
                "base_texture": "REGULAR",
            }
        ],
    )
    cycle_id = program["cycle"]["id"]
    assert read_community(community["id"])["active_menu_cycle_id"] == cycle_id

    first_ballot = cast_ballot(cycle_id, voters[0]["id"], "REG-COD", "NEGATIVE")
    cast_ballot(cycle_id, voters[1]["id"], "REG-COD", "NEGATIVE")
    assert first_ballot["vote_weight"] == 1

    pending = read_menu_cycle(cycle_id)
    assert pending["status"] == "REFRESH_PENDING"
    assert float(pending["refresh_index"]) == 40.00
    assert pending["refresh_tier"] == "QUORUM"
    assert pending["refresh_round"] == 0
    assert read_community(community["id"])["active_menu_cycle_id"] is None

    refreshed = validate_success(
        api.refresh_menu_cycle(
            cycle_id,
            {"refresh_reason": "committee rejected the cod entree"},
            DINING_MANAGER,
        )
    )
    assert refreshed["status"] == "DRAFT"
    assert refreshed["refresh_round"] == 1
    assert float(refreshed["refresh_index"]) == 0.00
    assert refreshed["refresh_tier"] == "ADVISORY"
    assert refreshed["refresh_reason"] == "committee rejected the cod entree"

    acknowledged, meta = validate_paginated(
        api.list_cycle_committee_feedback(
            cycle_id, DINING_MANAGER, params={"status": "ACKNOWLEDGED"}
        )
    )
    assert meta["total_count"] == 2
    assert acknowledged[0]["status"] == "ACKNOWLEDGED"


def test_publication_archives_only_the_strictly_earlier_published_cycle(api):
    """Of three cycles in one community only the already-published one that ended before the new
    range starts is archived; the untouched `DRAFT` cycle keeps its status and the new cycle becomes
    the active one.

    PRD: "Publication also cascades: every other cycle of the community that is `PUBLISHED` and
    whose `effective_end_date` falls strictly before this cycle's `effective_start_date` moves to
    `ARCHIVED`."

    Design: Corner/state_machines/publish_archives_only_strictly_earlier_published_cycles
    """
    set_clock("2026-08-12T08:00:00Z")
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    earlier = setup_published_menu_cycle(
        community["id"],
        cycle_number=1,
        week_count=1,
        effective_start_date="2026-08-01",
        effective_end_date="2026-08-07",
        items=[
            {
                "item_code": "C1-COD",
                "name": "Baked Cod",
                "day_index": 1,
                "meal_period": "LUNCH",
                "base_texture": "REGULAR",
            }
        ],
    )
    current = create_menu_cycle(
        community["id"],
        cycle_number=2,
        week_count=1,
        effective_start_date="2026-08-10",
        effective_end_date="2026-08-16",
    )
    add_menu_item(
        current["id"],
        item_code="C2-COD",
        name="Baked Cod",
        day_index=1,
        meal_period="LUNCH",
        base_texture="REGULAR",
    )
    submit_menu_cycle(current["id"])
    later = create_menu_cycle(
        community["id"],
        cycle_number=3,
        week_count=1,
        effective_start_date="2026-08-20",
        effective_end_date="2026-08-26",
    )
    add_menu_item(
        later["id"],
        item_code="C3-COD",
        name="Baked Cod",
        day_index=1,
        meal_period="LUNCH",
        base_texture="REGULAR",
    )

    published = publish_menu_cycle(current["id"])

    assert published["status"] == "PUBLISHED"
    assert read_menu_cycle(earlier["cycle"]["id"])["status"] == "ARCHIVED"
    assert read_menu_cycle(later["id"])["status"] == "DRAFT"
    assert read_community(community["id"])["active_menu_cycle_id"] == current["id"]
