"""Dual-variant calculations: the same inputs read two legitimate ways."""

from test_helpers import (
    assert_entitlement_counters,
    assert_reservation_state,
    check_in,
    completed_stay,
    create_open_park,
    create_president_tier,
    make_check_out_payload,
    make_park_manager_headers,
    make_reservation_payload,
    make_satisfaction_survey_payload,
    read_membership,
    read_park,
    reset_clock,
    sell_membership_to_new_member,
    set_clock,
    submit_survey,
    validate_success,
)


def _six_night_class_b_stay(api):
    """A CONFIRMED six-night CLASS_B stay whose ledger is otherwise clean."""
    reset_clock(api)
    tier = create_president_tier(api)
    holder = sell_membership_to_new_member(api, tier["id"])
    park = create_open_park(
        api,
        name="Mesa Verde RV Resort",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
    )
    response = api.create_reservation(
        make_reservation_payload(
            park["id"], holder["membership_id"], "2026-08-14", "2026-08-20"
        ),
        holder["headers"],
    )
    reservation = validate_success(response, 201)
    return holder, park, reservation


def test_confirmation_charges_the_provisional_night_count(api):
    """A confirmed stay debits the whole scheduled span before anyone arrives.

    PRD §3.3: "A member request that wins a seat resolves to `CONFIRMED` and
    writes the full set of debits: `entitlement_nights_charged` is set to the
    **provisional** night count — the `scheduled_departure_date` minus the
    `arrival_date` in whole days — and that same figure is added to the
    membership's class bucket, with `annual_nights_used` recomputed as the sum
    of the three class buckets."

    Design: Difficulty/dual_variant_calc/entitlement_nights_provisional_at_confirmation_vs_final_at_checkout
    """
    holder, _park, reservation = _six_night_class_b_stay(api)

    assert_reservation_state(reservation, "CONFIRMED", entitlement_nights_charged=6)
    assert reservation["nights"] == 6, "the half-open span 08-14..08-20 is six nights"

    membership = read_membership(api, holder["membership_id"])
    assert_entitlement_counters(membership, class_b=6, annual=6)


def test_check_out_switches_the_charge_to_its_final_form(api):
    """An early departure rewrites the provisional debit down to what was used.

    PRD §3.5: "The entitlement charge now switches to its **final** form: the
    final night count is `actual_departure_date` minus `arrival_date` in whole
    days, the difference between the previously charged
    `entitlement_nights_charged` and that final count — a figure that is 0 on an
    on-time departure and positive on an early one — is subtracted from the
    membership's class bucket, `annual_nights_used` is recomputed, and
    `entitlement_nights_charged` is rewritten to the final count."

    Design: Difficulty/dual_variant_calc/entitlement_nights_provisional_at_confirmation_vs_final_at_checkout
    """
    holder, _park, reservation = _six_night_class_b_stay(api)
    check_in(api, reservation["id"], holder["headers"], "2026-08-14")

    set_clock(api, "2026-08-17")
    response = api.check_out_reservation(
        reservation["id"], make_check_out_payload("2026-08-17"), holder["headers"]
    )
    completed = validate_success(response, 200)

    assert_reservation_state(completed, "COMPLETED", entitlement_nights_charged=3)
    assert completed["departure_date"] == "2026-08-17", (
        "departure_date is overwritten with actual_departure_date"
    )
    assert completed["nights"] == 3, "nights is recomputed from the actual departure"

    membership = read_membership(api, holder["membership_id"])
    assert_entitlement_counters(membership, class_b=3, annual=3)


def _park_with_two_divergent_surveys(api):
    """One park carrying a 5.00 survey aged 181 days and a fresh 2.10 survey."""
    set_clock(api, "2026-02-01")
    tier = create_president_tier(api)
    holder = sell_membership_to_new_member(api, tier["id"])
    park = create_open_park(
        api,
        name="Cedar Bluff RV Resort",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
    )

    february = completed_stay(
        api,
        holder["headers"],
        park["id"],
        holder["membership_id"],
        "2026-02-08",
        "2026-02-10",
    )
    old_survey = submit_survey(
        api,
        february["id"],
        holder["headers"],
        overall_rating=5,
        cleanliness_rating=5,
        staff_rating=5,
        value_rating=5,
    )

    set_clock(api, "2026-08-01")
    august = completed_stay(
        api,
        holder["headers"],
        park["id"],
        holder["membership_id"],
        "2026-08-08",
        "2026-08-10",
    )
    return holder, park, old_survey, august


def test_stored_park_rating_never_drops_an_old_survey(api):
    """The stored rating keeps a 181-day-old rave at reduced weight.

    PRD §3.9: "Each survey is weighted by its age in whole days from
    `submitted_at` to the current logical date: a survey aged at most 90 days
    weighs 1.0, one aged at most 365 days weighs 0.6, and anything older weighs
    0.3."

    Design: Difficulty/dual_variant_calc/park_rating_lifetime_decay_vs_trailing_window_mean_divergence
    """
    holder, park, old_survey, august = _park_with_two_divergent_surveys(api)

    assert old_survey["weighted_score"] == 5.00, (
        "a straight-five survey weights to 5.00"
    )

    response = api.submit_satisfaction_survey(
        august["id"],
        make_satisfaction_survey_payload(
            overall_rating=2, cleanliness_rating=3, staff_rating=2, value_rating=1
        ),
        holder["headers"],
    )
    new_survey = validate_success(response, 201)
    assert new_survey["weighted_score"] == 2.10, (
        "0.40*2 + 0.25*3 + 0.20*2 + 0.15*1 rounds half up to 2.10"
    )

    # (0.6 * 5.00 + 1.0 * 2.10) / (0.6 + 1.0) = 5.1 / 1.6 = 3.1875 -> 3.19
    assert read_park(api, park["id"])["rating_score"] == 3.19, (
        "the lifetime form is a recency-weighted mean over every survey ever filed"
    )


def test_capital_priority_scores_off_the_trailing_window_mean(api):
    """Capital scoring hard-drops the same survey the stored rating still counts.

    PRD §3.9: "It hard-drops every survey older than 180 days and takes the
    plain unweighted arithmetic mean of the surviving surveys' `weighted_score`
    values, rounded half up to two decimal places."

    Design: Difficulty/dual_variant_calc/park_rating_lifetime_decay_vs_trailing_window_mean_divergence
    """
    holder, park, _old_survey, august = _park_with_two_divergent_surveys(api)

    validate_success(
        api.submit_satisfaction_survey(
            august["id"],
            make_satisfaction_survey_payload(
                overall_rating=2, cleanliness_rating=3, staff_rating=2, value_rating=1
            ),
            holder["headers"],
        ),
        201,
    )

    set_clock(api, "2026-08-20")
    response = api.create_capital_project(
        {
            "park_id": park["id"],
            "title": "Replace 30A pedestals loop C",
            "category": "UTILITY",
            "requested_cost_cents": 4500000,
            "fiscal_year": 2026,
        },
        make_park_manager_headers(park["id"]),
    )
    project = validate_success(response, 201)

    # UTILITY 1.20 * COMPLIANT 1.00 * (1 + (4.50 - 2.10)) * (1 + 0.0033) * 1.20
    # * 1000, one half-up rounding at the very end.
    assert project["priority_score"] == 4912, (
        "the trailing window drops the 191-day-old February survey, leaving 2.10"
    )
    assert project["priority_score"] != 3337, (
        "the stored recency-weighted rating of 3.19 must not feed this score"
    )
    assert read_park(api, park["id"])["rating_score"] == 3.19, (
        "the two forms coexist: the stored rating is unmoved by the scoring pass"
    )
