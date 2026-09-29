"""Half-open night intervals contending for one resource."""

from test_helpers import (
    ADMIN,
    assert_entitlement_counters,
    assert_pool_split,
    assert_reservation_state,
    assert_waitlisted_debits_nothing,
    book_member_stay,
    book_transient_stay,
    create_open_park,
    create_president_tier,
    make_reservation_payload,
    read_membership,
    read_reservation,
    reset_clock,
    sell_membership_to_new_member,
    validate_error,
    validate_paginated,
    validate_success,
)


def _president_holder_with_a_fourteen_night_run(api):
    """A CONFIRMED 2026-08-05..2026-08-19 stay at a park where capacity never binds."""
    reset_clock(api)
    tier = create_president_tier(api)
    park = create_open_park(
        api,
        name="Juniper Basin Campground",
        park_class="CLASS_C",
        total_sites=40,
        member_allocation_pct=60,
    )
    holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Lena Sotelo", "email": "lena@example.com"},
        upfront_paid_cents=1850000,
    )
    first = book_member_stay(
        api, holder["headers"], park["id"], holder["membership_id"], "2026-08-05", "2026-08-19"
    )
    assert first["nights"] == 14
    assert first["consecutive_run_nights"] == 14, "a standalone stay is its own run"
    return holder, park, first


def test_a_one_night_gap_merges_the_run_past_the_stay_length_limit(api):
    """The gap clears out-and-back yet still links the two stays into one run.

    PRD §3.3: "For each following stay, if its `arrival_date` is no later than the current
    run's departure date advanced by the link gap of 1 night, the stay merges into the run and
    the run's departure date becomes the later of the run's existing departure date and that
    stay's `departure_date`; otherwise a new run begins with that stay."

    Design: Difficulty/resource_temporal_overlap/membership_stay_run_merges_across_a_one_night_gap_that_out_and_back_already_allows
    """
    holder, park, _first = _president_holder_with_a_fourteen_night_run(api)

    response = api.create_reservation(
        make_reservation_payload(
            park["id"], holder["membership_id"], "2026-08-20", "2026-08-30"
        ),
        holder["headers"],
    )
    # The merged run 2026-08-05..2026-08-30 is 25 nights against a limit of 21.
    validate_error(response, "ERR_STAY_LENGTH_EXCEEDED", 422)

    rows, _meta = validate_paginated(
        api.list_reservations(ADMIN, {"membership_id": holder["membership_id"]})
    )
    assert len(rows) == 1, "the rejected attempt created no reservation row"
    assert_entitlement_counters(
        read_membership(api, holder["membership_id"]), class_c=14, annual=14
    )


def test_a_three_night_gap_breaks_the_run_and_the_same_length_is_accepted(api):
    """A gap wider than one night starts a fresh run, so the length limit is clear.

    PRD §3.3: "A single night off the network therefore does *not* break a run — only a gap of
    two or more nights does."

    Design: Difficulty/resource_temporal_overlap/membership_stay_run_merges_across_a_one_night_gap_that_out_and_back_already_allows
    """
    holder, park, _first = _president_holder_with_a_fourteen_night_run(api)

    second = validate_success(
        api.create_reservation(
            make_reservation_payload(
                park["id"], holder["membership_id"], "2026-08-22", "2026-09-01"
            ),
            holder["headers"],
        ),
        201,
    )
    assert_reservation_state(second, "CONFIRMED", entitlement_nights_charged=10)
    assert second["nights"] == 10
    assert second["consecutive_run_nights"] == 10, "the three-night gap prevents any merge"

    assert_entitlement_counters(
        read_membership(api, holder["membership_id"]), class_c=24, annual=24
    )


def _one_member_pad_and_a_transient_holdover(api):
    """A three-site park whose lone member pad is the only contested resource."""
    reset_clock(api)
    tier = create_president_tier(api)
    park = create_open_park(
        api,
        name="Hollow Rock Micro Park",
        park_class="CLASS_B",
        total_sites=3,
        member_allocation_pct=60,
    )
    assert_pool_split(park, member_sites=1, transient_sites=2)
    holdover = book_transient_stay(
        api, park["id"], "2026-08-10", "2026-08-16", guest_name="Holdover Guest"
    )

    probes = [
        sell_membership_to_new_member(
            api,
            tier["id"],
            member_overrides={"full_name": name, "email": email},
            upfront_paid_cents=1850000,
        )
        for name, email in (
            ("Early Leaver", "early@example.com"),
            ("Late Arriver", "late@example.com"),
            ("Straddler Reyes", "straddle@example.com"),
        )
    ]
    return park, holdover, probes


def test_a_departure_day_is_not_an_occupied_night(api):
    """Two stays meeting on 2026-08-13 share one pad without overselling it.

    PRD §2.10: "A reservation's occupied night set is **half-open**: it contains every date
    from `arrival_date` up to but not including `departure_date`. The departure day is never
    an occupied night, which is why a stay departing on a given date and another stay arriving
    on that same date do not collide and do not compete for the same pad."

    Design: Difficulty/resource_temporal_overlap/park_nightly_site_inventory_tolerates_departure_arrival_adjacency_but_waitlists_a_true_overlap
    """
    park, _holdover, probes = _one_member_pad_and_a_transient_holdover(api)
    early, late, _straddler = probes

    first = validate_success(
        api.create_reservation(
            make_reservation_payload(
                park["id"], early["membership_id"], "2026-08-10", "2026-08-13"
            ),
            early["headers"],
        ),
        201,
    )
    assert_reservation_state(
        first, "CONFIRMED", pool_charged="MEMBER_POOL", entitlement_nights_charged=3
    )

    second = validate_success(
        api.create_reservation(
            make_reservation_payload(
                park["id"], late["membership_id"], "2026-08-13", "2026-08-16"
            ),
            late["headers"],
        ),
        201,
    )
    assert_reservation_state(
        second, "CONFIRMED", pool_charged="MEMBER_POOL", entitlement_nights_charged=3
    )

    assert_entitlement_counters(read_membership(api, early["membership_id"]), class_b=3, annual=3)
    assert_entitlement_counters(read_membership(api, late["membership_id"]), class_b=3, annual=3)


def test_a_true_overlap_is_waitlisted_rather_than_borrowing_below_the_floor(api):
    """Nights already taken send the straddling stay to the waitlist for nothing.

    PRD §3.3: "A member request that clears every rule but wins no seat resolves to
    `WAITLISTED` rather than being refused. A waitlisted stay debits absolutely nothing:
    `pool_charged` stays `NONE`, `entitlement_nights_charged` stays 0,
    `affiliate_nights_charged` stays 0, and `departure_date` is still set from
    `scheduled_departure_date` so the desired night set is on record for the promotion sweep."

    Design: Difficulty/resource_temporal_overlap/park_nightly_site_inventory_tolerates_departure_arrival_adjacency_but_waitlists_a_true_overlap
    """
    park, _holdover, probes = _one_member_pad_and_a_transient_holdover(api)
    early, late, straddler = probes
    book_member_stay(
        api, early["headers"], park["id"], early["membership_id"], "2026-08-10", "2026-08-13"
    )
    book_member_stay(
        api, late["headers"], park["id"], late["membership_id"], "2026-08-13", "2026-08-16"
    )

    contested = validate_success(
        api.create_reservation(
            make_reservation_payload(
                park["id"], straddler["membership_id"], "2026-08-12", "2026-08-14"
            ),
            straddler["headers"],
        ),
        201,
    )
    assert_waitlisted_debits_nothing(contested)
    assert contested["pool_charged"] != "BORROWED_TRANSIENT", (
        "borrowing may not take the transient pool below its public floor of one site"
    )
    assert_entitlement_counters(
        read_membership(api, straddler["membership_id"]), class_b=0, annual=0
    )
    assert read_reservation(api, contested["id"])["status"] == "WAITLISTED"
