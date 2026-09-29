"""Derived aggregates are final on the very next read, with nothing left to settle."""

from test_helpers import (
    ADMIN,
    assert_entitlement_counters,
    assert_pool_split,
    assert_reservation_state,
    assert_satisfaction_survey,
    book_member_stay,
    completed_stay,
    create_classic_tier,
    create_open_park,
    create_park,
    make_park_manager_headers,
    open_park,
    propose_project,
    read_membership,
    read_park,
    read_project,
    read_reservation,
    reset_clock,
    sell_membership_to_new_member,
    submit_survey,
    validate_paginated,
    validate_success,
)


def test_one_survey_publishes_the_rating_and_both_project_scores_at_once(api):
    """The survey request moves three derived numbers, and a check-out moves none of them.

    PRD §3.9: "A survey submission likewise recomputes `priority_score` for every
    capital project at the park and increments the park's `version` by 1, since the
    stored rating it moves is an input to that score."

    Design: Corner/consistency_model/a_survey_write_makes_the_rating_and_every_project_score_final_in_the_same_instant
    """
    reset_clock(api)
    tier = create_classic_tier(api)
    holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Dana Whitlock", "email": "dana.whitlock@example.com"},
    )
    park = create_park(
        api,
        name="Sable Creek Campground",
        park_class="CLASS_C",
        total_sites=30,
        member_allocation_pct=60,
    )
    assert park["rating_score"] == 0.00, "a park with no surveys reports exactly 0.00"
    assert open_park(api, park["id"])["park_status"] == "OPEN"
    manager = make_park_manager_headers(park["id"])
    safety = propose_project(
        api,
        park["id"],
        manager,
        title="Sable Creek bathhouse rebuild",
        category="SAFETY",
        requested_cost_cents=3000000,
        fiscal_year=2027,
    )
    expansion = propose_project(
        api,
        park["id"],
        manager,
        title="Sable Creek pull-through expansion",
        category="EXPANSION",
        requested_cost_cents=9000000,
        fiscal_year=2027,
    )
    # An empty trailing window defaults to 3.00, so the gap is the full 1.50 and the
    # usage intensity is 0: SAFETY is 1.40 x 2.50 x 1.20 and EXPANSION 0.80 x 2.50.
    assert safety["priority_score"] == 4200
    assert expansion["priority_score"] == 2000

    stay = completed_stay(
        api,
        holder["headers"],
        park["id"],
        holder["membership_id"],
        "2026-08-10",
        "2026-08-13",
        check_in_instant="2026-08-10T15:00:00Z",
        check_out_instant="2026-08-13T10:00:00Z",
    )
    assert_reservation_state(stay, "COMPLETED", entitlement_nights_charged=3)
    # The check-out changed the park's stayed nights but is not a re-score trigger.
    assert read_project(api, safety["id"])["priority_score"] == 4200
    assert read_project(api, expansion["id"])["priority_score"] == 2000
    before = read_park(api, park["id"])
    assert before["rating_score"] == 0.00
    version_before = before["version"]

    survey = submit_survey(
        api,
        stay["id"],
        holder["headers"],
        overall_rating=5,
        cleanliness_rating=4,
        staff_rating=5,
        value_rating=4,
    )
    assert_satisfaction_survey(survey)
    # round_half_up(0.40 x 5 + 0.25 x 4 + 0.20 x 5 + 0.15 x 4, 2) = 4.60, and the
    # computed field is in the creating response rather than fetched afterwards.
    assert survey["weighted_score"] == 4.60
    assert survey["park_id"] == park["id"]
    assert survey["membership_id"] == holder["membership_id"]

    after = read_park(api, park["id"])
    assert after["rating_score"] == 4.60, "one survey aged 0 days carries weight 1.0"
    assert after["version"] == version_before + 1

    # Trailing rating 4.60 closes the gap to 0.00 and the usage intensity is
    # round_half_up(3 / (30 x 30), 4) = 0.0033, giving 1685.544 and 802.64.
    rescored_safety = read_project(api, safety["id"])
    assert rescored_safety["priority_score"] == 1686
    assert rescored_safety["status"] == "PROPOSED", "re-scoring is not a decision"
    assert read_project(api, expansion["id"])["priority_score"] == 803

    reread = read_park(api, park["id"])
    assert reread["rating_score"] == after["rating_score"], "no lag and no second value"
    assert reread["version"] == after["version"]


def test_a_cancellation_publishes_the_promoted_stay_in_the_same_instant(api):
    """The queue is empty and the promoted debits are visible on the very next read.

    PRD §2.6: "Three families of counters in this system are derived aggregates that
    must remain exactly consistent with the rows that justify them, and every
    operation that changes a row must complete the corresponding counter movement
    inside the same request."

    Design: Corner/consistency_model/a_cancellation_publishes_the_promoted_reservation_in_the_same_instant
    """
    reset_clock(api)
    tier = create_classic_tier(api)
    first = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Dana Whitlock", "email": "dana.whitlock@example.com"},
    )
    second = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Nathan Boyle", "email": "nathan.boyle@example.com"},
    )
    park = create_open_park(
        api,
        name="Cedar Flats Micro Park",
        park_class="CLASS_C",
        total_sites=2,
        member_allocation_pct=50,
    )
    assert_pool_split(park, member_sites=1, transient_sites=1)

    seated = book_member_stay(
        api, first["headers"], park["id"], first["membership_id"], "2026-08-10", "2026-08-12"
    )
    assert_reservation_state(
        seated, "CONFIRMED", pool_charged="MEMBER_POOL", entitlement_nights_charged=2
    )
    queued = book_member_stay(
        api, second["headers"], park["id"], second["membership_id"], "2026-08-10", "2026-08-12"
    )
    assert_reservation_state(
        queued, "WAITLISTED", pool_charged="NONE", entitlement_nights_charged=0
    )
    assert_entitlement_counters(
        read_membership(api, second["membership_id"]), class_c=0, annual=0
    )

    cancelled = validate_success(api.cancel_reservation(seated["id"], first["headers"]), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_reason"] == "MEMBER_REQUEST"
    assert cancelled["pool_charged"] == "NONE"
    assert cancelled["entitlement_nights_charged"] == 0

    promoted = read_reservation(api, queued["id"])
    assert_reservation_state(
        promoted, "CONFIRMED", pool_charged="MEMBER_POOL", entitlement_nights_charged=2
    )
    assert_entitlement_counters(
        read_membership(api, second["membership_id"]), class_c=2, annual=2
    )
    assert_entitlement_counters(
        read_membership(api, first["membership_id"]), class_c=0, annual=0
    )

    waiting_rows, waiting_meta = validate_paginated(
        api.list_reservations(ADMIN, {"park_id": park["id"], "status": "WAITLISTED"})
    )
    assert waiting_rows == [], "the seat is never free with nobody holding it"
    assert waiting_meta["total_count"] == 0
