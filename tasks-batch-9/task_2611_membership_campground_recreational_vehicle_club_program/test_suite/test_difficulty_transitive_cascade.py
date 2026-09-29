"""Deep cascades that must run to completion inside one request."""

from test_helpers import (
    ADMIN,
    assert_entitlement_counters,
    assert_membership_axes,
    assert_pool_split,
    assert_reservation_state,
    book_member_stay,
    book_transient_stay,
    create_open_park,
    create_president_tier,
    list_invoices,
    make_park_manager_headers,
    pay_invoice_in_full,
    propose_project,
    read_membership,
    read_park,
    read_project,
    read_reservation,
    reset_clock,
    schedule_window,
    sell_membership_to_new_member,
    set_clock,
    validate_success,
)


def _one_seat_park_with_a_waitlisted_rival(api):
    """A single member pad held by a delinquent contract, wanted by a paid-up one."""
    reset_clock(api)
    tier = create_president_tier(api)
    park = create_open_park(
        api,
        name="Salt Fork Micro Park",
        park_class="CLASS_B",
        total_sites=3,
        member_allocation_pct=60,
    )
    assert_pool_split(park, member_sites=1, transient_sites=2)

    alfa = sell_membership_to_new_member(api, tier["id"], upfront_paid_cents=1850000)
    bravo = sell_membership_to_new_member(api, tier["id"], upfront_paid_cents=1850000)
    pay_invoice_in_full(api, bravo["invoice_id"], bravo["headers"])

    walk_in = book_transient_stay(api, park["id"], "2026-11-10", "2026-11-13")
    held = book_member_stay(
        api, alfa["headers"], park["id"], alfa["membership_id"], "2026-11-10", "2026-11-13"
    )
    waiting = book_member_stay(
        api, bravo["headers"], park["id"], bravo["membership_id"], "2026-11-10", "2026-11-13"
    )
    set_clock(api, "2026-10-05")
    return {
        "park": park,
        "alfa": alfa,
        "bravo": bravo,
        "alfa_invoice": list_invoices(api, alfa["membership_id"])[0],
        "walk_in": walk_in,
        "held": held,
        "waiting": waiting,
    }


def test_delinquency_run_ages_the_invoice_and_suspends_the_contract(api):
    """The invoice going PAST_DUE is what drags the contract axis to SUSPENDED.

    PRD §3.7: "Link three moves the contract axis: a membership in `ACTIVE` **or**
    in `TRANSFER_PENDING` becomes `SUSPENDED` with `suspension_reason` set to
    `DUES_DELINQUENCY`."

    Design: Difficulty/transitive_cascade/delinquency_run_cascades_invoice_to_dues_axis_to_suspension_to_cancellation_to_waitlist_promotion
    """
    world = _one_seat_park_with_a_waitlisted_rival(api)

    validate_success(api.run_dues_delinquency(ADMIN), 200)

    invoice = validate_success(api.get_dues_invoice(world["alfa_invoice"]["id"], ADMIN), 200)
    assert invoice["status"] == "PAST_DUE"
    assert invoice["days_past_due"] == 35, "2026-10-05 less the 2026-08-31 due date"
    # 59508 * 1.5% * ceil(35/30) = 2 months = 1785.24, one rounding at the end.
    assert invoice["late_fee_cents"] == 1785

    membership = read_membership(api, world["alfa"]["membership_id"])
    assert_membership_axes(
        membership, "SUSPENDED", "DELINQUENT", suspension_reason="DUES_DELINQUENCY"
    )
    assert membership["dues_balance_cents"] == 61293, "59508 plus the 1785 late fee"


def test_delinquency_suspension_frees_a_seat_and_promotes_the_waitlist(api):
    """The freed member pad is handed straight to the waiting contract.

    PRD §3.7: "Link six works the waitlist at every park that released a
    member-pool seat."

    Design: Difficulty/transitive_cascade/delinquency_run_cascades_invoice_to_dues_axis_to_suspension_to_cancellation_to_waitlist_promotion
    """
    world = _one_seat_park_with_a_waitlisted_rival(api)
    assert_reservation_state(world["waiting"], "WAITLISTED", pool_charged="NONE")

    validate_success(api.run_dues_delinquency(ADMIN), 200)

    cancelled = read_reservation(api, world["held"]["id"])
    assert_reservation_state(
        cancelled, "CANCELLED", pool_charged="NONE", entitlement_nights_charged=0
    )
    assert cancelled["cancellation_reason"] == "MEMBERSHIP_SUSPENDED"
    assert_entitlement_counters(
        read_membership(api, world["alfa"]["membership_id"]), class_b=0, annual=0
    )

    promoted = read_reservation(api, world["waiting"]["id"])
    assert_reservation_state(
        promoted, "CONFIRMED", pool_charged="MEMBER_POOL", entitlement_nights_charged=3
    )
    bravo = read_membership(api, world["bravo"]["membership_id"])
    assert_entitlement_counters(bravo, class_b=3, annual=3)
    assert_membership_axes(bravo, "ACTIVE", "CURRENT")

    walk_in = read_reservation(api, world["walk_in"]["id"])
    assert_reservation_state(walk_in, "CONFIRMED", pool_charged="TRANSIENT_POOL")


def _park_two_stays_and_a_scheduled_window(api):
    """Both member pads let for the same nights a scheduled window will block."""
    reset_clock(api)
    tier = create_president_tier(api)
    park = create_open_park(
        api,
        name="Willow Bend RV Resort",
        park_class="CLASS_B",
        total_sites=4,
        member_allocation_pct=60,
    )
    assert_pool_split(park, member_sites=2, transient_sites=2)

    nia = sell_membership_to_new_member(api, tier["id"], upfront_paid_cents=1850000)
    theo = sell_membership_to_new_member(api, tier["id"], upfront_paid_cents=1850000)
    nia_stay = book_member_stay(
        api, nia["headers"], park["id"], nia["membership_id"], "2026-09-10", "2026-09-13"
    )
    theo_stay = book_member_stay(
        api, theo["headers"], park["id"], theo["membership_id"], "2026-09-10", "2026-09-13"
    )

    project = propose_project(
        api,
        park["id"],
        make_park_manager_headers(park["id"]),
        title="Rebuild water service loop A",
        category="UTILITY",
        requested_cost_cents=4500000,
        fiscal_year=2026,
    )
    window = schedule_window(api, park["id"], "2026-09-11", "2026-09-15", work_type="ROUTINE")
    return {
        "park": park,
        "nia": nia,
        "theo": theo,
        "nia_stay": nia_stay,
        "theo_stay": theo_stay,
        "project": project,
        "window": window,
    }


def test_maintenance_activation_holds_the_park_and_force_cancels_the_stays(api):
    """Activation takes the park offline and evicts every intersecting booking.

    PRD §3.6: "Link two force-cancels every reservation at that park whose
    `status` is `CONFIRMED` or `WAITLISTED` and whose half-open night set
    intersects the window's closed interval from `start_date` through `end_date`:
    a `CONFIRMED` stay becomes `CANCELLED` and a `WAITLISTED` stay becomes
    `EXPIRED`, with `cancellation_reason` recorded as `MAINTENANCE`."

    Design: Difficulty/transitive_cascade/maintenance_activation_cascades_park_hold_to_forced_cancellations_to_probation_to_capital_rescore
    """
    world = _park_two_stays_and_a_scheduled_window(api)

    activated = validate_success(
        api.activate_maintenance_window(
            world["window"]["id"], make_park_manager_headers(world["park"]["id"])
        ),
        200,
    )
    assert activated["status"] == "ACTIVE"
    assert activated["cancelled_reservation_count"] == 2

    assert read_park(api, world["park"]["id"])["park_status"] == "MAINTENANCE_HOLD"

    for stay, holder in (
        (world["nia_stay"], world["nia"]),
        (world["theo_stay"], world["theo"]),
    ):
        cancelled = read_reservation(api, stay["id"])
        assert_reservation_state(
            cancelled, "CANCELLED", pool_charged="NONE", entitlement_nights_charged=0
        )
        assert cancelled["cancellation_reason"] == "MAINTENANCE"
        assert_entitlement_counters(
            read_membership(api, holder["membership_id"]), class_b=0, annual=0
        )


def test_forced_cancellations_floor_compliance_and_rescore_capital_work(api):
    """Two evictions floor the park at PROBATION and lift its project's score.

    PRD §3.6: "Link four adds the cancelled count to the park's
    `forced_cancellation_count`, and once that tally reaches 2 or more for the
    calendar year, the park's `amenity_compliance_status` is moved from
    `COMPLIANT` to `PROBATION`."

    Design: Difficulty/transitive_cascade/maintenance_activation_cascades_park_hold_to_forced_cancellations_to_probation_to_capital_rescore
    """
    world = _park_two_stays_and_a_scheduled_window(api)

    before = read_park(api, world["park"]["id"])
    assert before["amenity_compliance_status"] == "COMPLIANT"
    assert before["forced_cancellation_count"] == 0
    # UTILITY 1.20 * COMPLIANT 1.00 * (1 + (4.50 - 3.00)) * (1 + 0.0000) * 1.20 * 1000
    assert read_project(api, world["project"]["id"])["priority_score"] == 3600

    validate_success(
        api.activate_maintenance_window(
            world["window"]["id"], make_park_manager_headers(world["park"]["id"])
        ),
        200,
    )

    after = read_park(api, world["park"]["id"])
    assert after["forced_cancellation_count"] == 2
    assert after["amenity_compliance_status"] == "PROBATION"

    # The compliance factor alone moves from 1.00 to 1.15: 3.60 -> 4.14.
    assert read_project(api, world["project"]["id"])["priority_score"] == 4140
