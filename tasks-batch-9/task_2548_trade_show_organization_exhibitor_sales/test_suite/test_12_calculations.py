"""
Derived numbers checked one formula at a time: the booth selector's total order,
the attrition input set, the posture-gated discount cap, the registration weight,
the service-rate variant and the ranking tie-break.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    AppointmentState,
    BoothStatus,
    FloorPosture,
    QualificationStatus,
    RateVariant,
    ServiceOrderStatus,
    ShowStatus,
    SpaceContractStatus,
    assert_show_area_ledger,
    factories as f,
    fixtures as fx,
    make_director_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-15T00:00:00Z"

A100 = f.booth_payload("A100", 20, 20, location_class="CORNER",
                       premium_zone="MAIN_AISLE", max_height_ft=16)
C050 = f.inline_booth_payload("C050", 10, 20)
D010 = f.inline_booth_payload("D010", 10, 10)

E010 = f.booth_payload("E010", 15, 20, location_class="INLINE",
                       premium_zone="ENTRANCE", max_height_ft=12)
S010 = f.inline_booth_payload("S010", 10, 20)
S020 = f.booth_payload("S020", 20, 20, location_class="CORNER",
                       premium_zone="NONE", max_height_ft=12)


def _open_contract(client: ApiClient, show_id: str, exhibitor_id: str,
                   requested_sqft: int, **overrides):
    """Ask for space without naming booths, so the server's selector decides."""
    return client.create_space_contract(
        f.space_contract_payload(show_id, exhibitor_id,
                                fx.show_version(client, show_id), requested_sqft,
                                **overrides),
        fx.SALES_REP_HEADERS,
    )


def test_the_selector_takes_the_smallest_fit_unless_placement_was_bought(
    client: ApiClient,
):
    """
    One floor plan answering three requests: plain, premium, and too large to fill.

    "The candidate pool is every booth of the target show whose `status` is
    `AVAILABLE`, whose `combined_parent_booth_id` is null, whose `area_sqft` is at
    least the `requested_sqft`, and which is either not in the `ENTRANCE` premium
    zone or is being selected for a contract where `premium_placement_requested` is
    true."  "When `premium_placement_requested` is false, candidates are ordered by
    `area_sqft` ascending first"  "When `premium_placement_requested` is true, the
    primary key inverts to the traffic zone, ordered `ENTRANCE`, then `MAIN_AISLE`,
    then `FOOD_COURT`, then `NONE`"  "If the candidate pool is empty, no booth is
    held, no partial write is made, and the whole request fails atomically with
    `ERR_NO_ELIGIBLE_BOOTH`."

    Design: Corner/calculations/booth_selector_picks_the_smallest_fit_then_the_best_zone
    """
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [E010, S010, S020])
    show_id = env["show"]["id"]
    booths = env["booth_by_number"]
    nordic = fx.exhibitor(client, "Nordic Furnishings",
                          contact_email="sales@nordic.example", consecutive_years=6)
    harbor = fx.exhibitor(client, "Harbor Ceramics",
                          contact_email="space@harbor.example", consecutive_years=2)
    alder = fx.exhibitor(client, "Alder Textiles",
                         contact_email="space@alder.example", consecutive_years=1)

    plain = validate_success(_open_contract(client, show_id, nordic["id"], 200), 201)
    assert plain["offered_booth_ids"] == [booths["S010"]["id"]]
    assert plain["offered_net_sqft"] == 200

    premium = validate_success(
        _open_contract(client, show_id, harbor["id"], 200,
                       premium_placement_requested=True),
        201,
    )
    assert premium["offered_booth_ids"] == [booths["E010"]["id"]]
    assert premium["offered_net_sqft"] == 300

    validate_error(
        _open_contract(client, show_id, alder["id"], 500),
        ApiErrorId.NO_ELIGIBLE_BOOTH,
        422,
    )
    _, meta = validate_paginated(
        client.list_space_contracts(fx.DIRECTOR_HEADERS,
                                    {"exhibitor_id": alder["id"]})
    )
    assert meta["total_count"] == 0

    assert fx.read_booth(client, booths["S020"]["id"])["status"] == BoothStatus.AVAILABLE
    assert_show_area_ledger(fx.read_show(client, show_id), 900, 500, 0, 400, 56)


def test_a_late_cancellation_manufactures_the_attrition_bill(client: ApiClient):
    """
    Two signed holds, one withdrawn before close: only the survivor performs.

    "Actual performance is the sum of `assigned_net_sqft` across the show's contracts
    whose status is `SIGNED` or `CLOSED_OUT`, and no other status counts: a contract
    that was cancelled no longer counts toward the commitment even though it once
    did, which is exactly how a late cancellation manufactures an attrition bill."
    "The `attrition_settlement_cents` is that shortfall multiplied by eighteen
    dollars — 1800 cents — per square foot."

    Design: Corner/calculations/attrition_counts_only_signed_and_closed_out_contracts
    """
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, C050])
    show_id = env["show"]["id"]
    booths = env["booth_by_number"]
    assert env["venue_contract"]["committed_net_sqft_per_year"] == 1200
    assert env["venue_contract"]["attrition_allowance_pct"] == 15

    nordic = fx.exhibitor(client, "Nordic Furnishings",
                          contact_email="sales@nordic.example", consecutive_years=6)
    harbor = fx.exhibitor(client, "Harbor Ceramics",
                          contact_email="space@harbor.example", consecutive_years=2)
    surviving = fx.signed_contract(client, show_id, nordic["id"], 400,
                                   [booths["A100"]["id"]], 389070,
                                   premium_placement_requested=True)
    withdrawn = fx.signed_contract(client, show_id, harbor["id"], 200,
                                   [booths["C050"]["id"]], 163750)
    assert withdrawn["min_deposit_cents"] == 163750

    fx.transition(client, show_id, ShowStatus.SELLING)
    validate_success(
        client.cancel_space_contract(
            withdrawn["id"], f.cancel_payload("Harbor withdrew from the edition"),
            fx.make_exhibitor_headers(harbor["id"]),
        )
    )
    fx.transition(client, show_id, ShowStatus.ON_SITE)

    before = fx.read_contract(client, surviving["id"])
    assert before["status"] == SpaceContractStatus.SIGNED
    assert before["assigned_net_sqft"] == 400
    assert (
        fx.read_contract(client, withdrawn["id"])["status"]
        == SpaceContractStatus.CANCELLED
    )

    closed = fx.transition(client, show_id, ShowStatus.CLOSED)
    assert closed["status"] == ShowStatus.CLOSED
    assert (
        fx.read_contract(client, surviving["id"])["status"]
        == SpaceContractStatus.CLOSED_OUT
    )
    assert closed["attrition_shortfall_sqft"] == 620
    assert closed["attrition_settlement_cents"] == 1116000

    assert fx.read_booth(client, booths["C050"]["id"])["status"] == BoothStatus.AVAILABLE
    assert fx.read_booth(client, booths["A100"]["id"])["status"] == BoothStatus.ASSIGNED


def test_a_locked_floor_caps_discretionary_discounting_at_the_threshold(
    client: ApiClient,
):
    """
    Eighty-six percent committed: the deep re-offer is refused, the ten-point one is not.

    "Otherwise `committed_ratio_pct` is one hundred multiplied by the sum of
    `held_net_sqft` and `assigned_net_sqft`, divided by `sellable_booth_sqft`,
    rounded half up to a whole percent."  "otherwise it is `SPACE_LOCKED` when
    `committed_ratio_pct` is at least 85"  "that same code answers a re-offer whose
    `approved_discount_pct` exceeds 10 while the posture is `SPACE_LOCKED`,
    effectively capping a locked floor's discretionary discounting at the ordinary
    sales threshold"

    Design: Corner/calculations/space_locked_floor_caps_an_above_threshold_reoffer
    """
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, C050, D010])
    show_id = env["show"]["id"]
    booths = env["booth_by_number"]
    nordic = fx.exhibitor(client, "Nordic Furnishings",
                          contact_email="sales@nordic.example", consecutive_years=6)
    harbor = fx.exhibitor(client, "Harbor Ceramics",
                          contact_email="space@harbor.example", consecutive_years=2)
    negotiating = fx.offered_contract(client, show_id, nordic["id"], 400,
                                      [booths["A100"]["id"]],
                                      premium_placement_requested=True)
    untouched = fx.offered_contract(client, show_id, harbor["id"], 200,
                                    [booths["C050"]["id"]])

    locked = fx.read_show(client, show_id)
    assert locked["sellable_booth_sqft"] == 700
    assert locked["held_net_sqft"] == 600
    assert locked["committed_ratio_pct"] == 86
    assert locked["floor_posture"] == FloorPosture.SPACE_LOCKED

    countered = validate_success(
        client.negotiate(negotiating["id"], f.counter_payload(20),
                         fx.make_exhibitor_headers(nordic["id"]))
    )
    assert countered["status"] == SpaceContractStatus.COUNTERED

    approver = make_director_headers("u_sd_1")
    validate_error(
        client.negotiate(negotiating["id"], f.reoffer_payload(20), approver),
        ApiErrorId.SHOW_FLOOR_SPACE_LOCKED,
        409,
    )
    refused = fx.read_contract(client, negotiating["id"])
    assert refused["status"] == SpaceContractStatus.COUNTERED
    assert refused["approved_discount_pct"] == 0

    reoffered = validate_success(
        client.negotiate(negotiating["id"], f.reoffer_payload(10), approver)
    )
    assert reoffered["status"] == SpaceContractStatus.OFFERED
    assert reoffered["approved_discount_pct"] == 10
    assert reoffered["negotiation_round"] == 1
    assert reoffered["space_fee_cents"] == 1400652
    assert reoffered["min_deposit_cents"] == 350163

    assert (
        fx.read_contract(client, untouched["id"])["status"]
        == SpaceContractStatus.OFFERED
    )


def test_the_category_weight_multiplies_the_raw_total_exactly_once(
    client: ApiClient,
):
    """
    Four badges: the same raw seventy-five sorts three different ways by category.

    "Those three contributions are summed into a raw total, that single raw total is
    multiplied by the category weight — 1.00 for `BUYER`, 1.15 for `VIP_BUYER`, and
    0.50 for `STUDENT` — and the product is rounded half up to an integer, which is
    the stored `qualification_score`. The weight is applied to the summed raw points
    exactly once: weighting each component separately and then summing produces a
    different number and is wrong."  "When `category` is `PRESS` or
    `EXHIBITOR_STAFF`, the `qualification_score` is set to zero and the
    `qualification_status` is set directly to `QUALIFIED`"

    Design: Corner/calculations/category_weight_is_applied_once_to_the_summed_raw_points
    """
    fx.set_clock(client, CLOCK)
    env = fx.selling_show(client, [A100])
    show_id = env["show"]["id"]

    vip = fx.registration(
        client, show_id, fx.REGISTRANT_HEADERS, category="VIP_BUYER",
        company_name="Meridian Department Stores", job_title="VP Merchandising",
        purchasing_authority="DECISION_MAKER", annual_spend_band="K250K_1M",
        email="vp@meridian.example",
    )
    assert vip["qualification_score"] == 86
    assert vip["qualification_status"] == QualificationStatus.QUALIFIED

    buyer = fx.registration(
        client, show_id, fx.REGISTRANT_HEADERS, category="BUYER",
        company_name="Ridgeline Outfitters", job_title="Head of Sourcing",
        purchasing_authority="RECOMMENDER", annual_spend_band="K250K_1M",
        email="hos@ridgeline.example",
    )
    assert buyer["qualification_score"] == 60
    assert buyer["qualification_status"] == QualificationStatus.QUALIFIED

    student = fx.registration(
        client, show_id, fx.REGISTRANT_HEADERS, category="STUDENT",
        company_name="State Design School", job_title="VP Student Chapter",
        purchasing_authority="DECISION_MAKER", annual_spend_band="K250K_1M",
        email="vp@sds.example",
    )
    assert student["qualification_score"] == 38
    assert student["qualification_status"] == QualificationStatus.REJECTED

    press = fx.registration(
        client, show_id, fx.REGISTRANT_HEADERS, category="PRESS",
        company_name="Trade Weekly", job_title="Staff Writer",
        purchasing_authority="NONE", annual_spend_band="UNDER_50K",
        email="sw@tradeweekly.example",
    )
    assert press["qualification_score"] == 0
    assert press["qualification_status"] == QualificationStatus.QUALIFIED

    for row in (vip, buyer, student, press):
        assert row["qualification_status"] != QualificationStatus.PENDING

    qualified, meta = validate_paginated(
        client.list_registrations(show_id, fx.DIRECTOR_HEADERS,
                                  {"qualification_status": "QUALIFIED"})
    )
    assert meta["total_count"] == 3
    assert {row["id"] for row in qualified} == {vip["id"], buyer["id"], press["id"]}


def test_one_calendar_day_swings_the_same_labor_order_by_forty_nine_thousand(
    client: ApiClient,
):
    """
    Eight hours ordered on the deadline, then eight hours ordered the day after.

    "`rate_variant` is decided by the calendar: `ADVANCE` when the date of
    `ordered_at` is on or before the show's `advance_order_deadline`, and `FLOOR`
    when it falls after it."  "Under `FLOOR`, the product of `billable_quantity`,
    `unit_rate_cents` and one point three five is rounded half up first, and a flat
    seventy-five dollars — 7500 cents — is added to that rounded figure afterwards.
    The order of those last two steps is pinned: adding the flat fee before rounding
    would give a different total."

    Design: Corner/calculations/service_order_variant_is_chosen_by_the_deadline_date_alone
    """
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, C050])
    show_id = env["show"]["id"]
    nordic = fx.exhibitor(client, "Nordic Furnishings",
                          contact_email="sales@nordic.example", consecutive_years=6)
    contract = fx.signed_contract(client, show_id, nordic["id"], 400,
                                  [env["booth_by_number"]["A100"]["id"]], 389070,
                                  premium_placement_requested=True)
    headers = fx.make_exhibitor_headers(nordic["id"])
    assert fx.read_show(client, show_id)["advance_order_deadline"] == "2027-02-08"

    fx.set_clock(client, "2027-02-08T09:00:00Z")
    on_the_deadline = validate_success(
        client.create_service_order(
            contract["id"],
            f.service_order_payload("LABOR", 8, "2027-02-08T09:00:00Z"), headers,
        ),
        201,
    )
    assert on_the_deadline["rate_variant"] == RateVariant.ADVANCE
    assert on_the_deadline["unit_rate_cents"] == 9500
    assert on_the_deadline["billable_quantity"] == 8
    assert on_the_deadline["line_total_cents"] == 60800

    fx.set_clock(client, "2027-02-09T09:00:00Z")
    one_day_later = validate_success(
        client.create_service_order(
            contract["id"],
            f.service_order_payload("LABOR", 8, "2027-02-09T09:00:00Z"), headers,
        ),
        201,
    )
    assert one_day_later["rate_variant"] == RateVariant.FLOOR
    assert one_day_later["unit_rate_cents"] == 9500
    assert one_day_later["billable_quantity"] == 8
    assert one_day_later["line_total_cents"] == 110100

    for order in (on_the_deadline, one_day_later):
        assert order["status"] == ServiceOrderStatus.SUBMITTED
        assert order["space_contract_id"] == contract["id"]


def test_a_dead_heat_at_the_desk_is_won_by_the_older_exhibitor_record(
    client: ApiClient,
):
    """
    Equal standings, equal streaks, appointments filed in reverse registration order.

    "Second it orders that set — by snapshotted certified standing descending, then
    by the exhibitor's `consecutive_years` descending, then by the exhibitor's own
    `created_at` ascending, so that a dead heat is won by the longest-registered
    exhibitor. The exhibitor's `id` is never consulted as a tie-break."  "each has
    `certified_points_at_rank` written from its exhibitor's
    `certified_priority_points` at that instant"

    Design: Corner/calculations/selection_rank_breaks_a_dead_heat_on_exhibitor_created_at
    """
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, C050])
    show_id = env["show"]["id"]
    assert env["show"]["selection_desk_capacity"] == 2

    older = fx.exhibitor(client, "Cedarworks Displays",
                         contact_email="space@cedarworks.example",
                         consecutive_years=3, headers=fx.SALES_REP_HEADERS)
    fx.set_clock(client, "2026-08-16T00:00:00Z")
    younger = fx.exhibitor(client, "Basalt Cookware",
                           contact_email="space@basalt.example",
                           consecutive_years=3, headers=fx.SALES_REP_HEADERS)
    assert fx.read_exhibitor(client, older["id"])["certified_priority_points"] == 0
    assert fx.read_exhibitor(client, younger["id"])["certified_priority_points"] == 0

    filed_first = fx.scheduled_appointment(client, show_id, younger["id"], 1,
                                          "2027-03-01T09:00:00Z",
                                          "2027-03-01T11:00:00Z",
                                          fx.SALES_REP_HEADERS)
    filed_second = fx.scheduled_appointment(client, show_id, older["id"], 1,
                                           "2027-03-01T09:00:00Z",
                                           "2027-03-01T11:00:00Z",
                                           fx.SALES_REP_HEADERS)

    fx.set_clock(client, "2027-03-01T09:30:00Z")
    opened = validate_success(
        client.advance_selection_round(show_id, fx.DIRECTOR_HEADERS)
    )
    assert opened["selection_round"] == 1

    ranked = {
        row["id"]: row
        for row in validate_paginated(
            client.list_selection_appointments(fx.DIRECTOR_HEADERS,
                                              {"show_id": show_id})
        )[0]
    }
    winner = ranked[filed_second["id"]]
    runner_up = ranked[filed_first["id"]]
    assert winner["rank"] == 1
    assert winner["state"] == AppointmentState.ACTIVE
    assert runner_up["rank"] == 2
    assert runner_up["state"] == AppointmentState.ACTIVE
    assert winner["certified_points_at_rank"] == 0
    assert runner_up["certified_points_at_rank"] == 0
