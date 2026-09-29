"""Rule boundaries, priority ordering and cross-entity preconditions."""

from test_helpers import (
    ADMIN,
    assert_entitlement_counters,
    assert_membership_axes,
    assert_reservation_state,
    book_member_stay,
    create_active_agreement,
    create_affiliate_open_park,
    create_classic_tier,
    create_member,
    create_open_park,
    create_president_tier,
    create_tier,
    make_payment_payload,
    make_reservation_payload,
    make_transfer_request_payload,
    parse_instant,
    read_agreement,
    read_invoice,
    read_membership,
    read_reservation,
    reset_clock,
    run_delinquency_sweep,
    sell_membership_to_new_member,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_resale_permission_is_reported_ahead_of_the_resale_hold(api):
    """One request breaks both resale rules and must name the lower-numbered one.

    PRD §3.8: "For a resale specifically, the pinned tier must have
    `resale_allowed` true, refused otherwise with `ERR_RESALE_NOT_PERMITTED`, and
    at least the resale hold of 730 days must have elapsed between the
    membership's `purchased_at` and the current logical date, refused otherwise
    with `ERR_RESALE_HOLD_ACTIVE` — the same two-year horizon the computed
    `resale_eligible_at` field publishes, and a hold that gates resales only,
    never gifts or estate transfers."

    Design: Corner/validations/resale_permission_at_priority_thirty_seven_outranks_the_resale_hold_at_thirty_eight
    """
    reset_clock(api)
    classic = create_classic_tier(api)
    president = create_president_tier(api)
    assert classic["resale_allowed"] is False
    assert president["resale_allowed"] is True
    classic_holder = sell_membership_to_new_member(
        api,
        classic["id"],
        member_overrides={"full_name": "Dana Whitlock", "email": "dana.whitlock@example.com"},
    )
    president_holder = sell_membership_to_new_member(
        api,
        president["id"],
        member_overrides={"full_name": "Sergio Alvarado", "email": "sergio.alvarado@example.com"},
        upfront_paid_cents=1850000,
    )
    receiver = create_member(api, full_name="Nathan Boyle", email="nathan.boyle@example.com")
    gift_receiver = create_member(api, full_name="Grace Okafor", email="grace.okafor@example.com")

    validate_error(
        api.create_transfer_request(
            make_transfer_request_payload(
                classic_holder["membership_id"],
                receiver["id"],
                "RESALE",
                1,
                sale_price_cents=1200000,
            ),
            classic_holder["headers"],
        ),
        "ERR_RESALE_NOT_PERMITTED",
        422,
    )
    validate_error(
        api.create_transfer_request(
            make_transfer_request_payload(
                president_holder["membership_id"],
                receiver["id"],
                "RESALE",
                1,
                sale_price_cents=1200000,
            ),
            president_holder["headers"],
        ),
        "ERR_RESALE_HOLD_ACTIVE",
        422,
    )

    untouched = read_membership(api, classic_holder["membership_id"])
    assert_membership_axes(untouched, "ACTIVE", "CURRENT")
    assert untouched["version"] == 1, "a refused submission mutates nothing"

    gift = validate_success(
        api.create_transfer_request(
            make_transfer_request_payload(
                classic_holder["membership_id"], gift_receiver["id"], "GIFT", 1
            ),
            classic_holder["headers"],
        ),
        201,
    )
    assert gift["status"] == "SUBMITTED"
    assert gift["transfer_fee_cents"] == 30000, "round_half_up(60000 * 0.50) on a gift"


def test_a_dues_payment_one_cent_out_either_way_is_refused(api):
    """45359 and 45361 both fail; only the exact 45360 settles the invoice.

    PRD §3.7: "Neither a partial payment nor an over-payment is accepted, and
    either is refused with `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Design: Corner/validations/dues_payment_must_equal_the_outstanding_balance_to_the_cent
    """
    reset_clock(api)
    tier = create_classic_tier(api)
    holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Dana Whitlock", "email": "dana.whitlock@example.com"},
    )
    invoice_id = holder["invoice_id"]
    assert read_invoice(api, invoice_id)["amount_cents"] == 45360

    validate_error(
        api.pay_dues_invoice(invoice_id, make_payment_payload(45359), holder["headers"]),
        "ERR_PAYMENT_AMOUNT_MISMATCH",
        422,
    )
    validate_error(
        api.pay_dues_invoice(invoice_id, make_payment_payload(45361), holder["headers"]),
        "ERR_PAYMENT_AMOUNT_MISMATCH",
        422,
    )
    refused = read_invoice(api, invoice_id)
    assert refused["status"] == "OPEN"
    assert refused["paid_amount_cents"] == 0, "neither refused tender was applied"
    assert refused["paid_at"] is None

    settled = validate_success(
        api.pay_dues_invoice(invoice_id, make_payment_payload(45360), holder["headers"]), 200
    )
    assert settled["status"] == "PAID"
    assert settled["paid_amount_cents"] == 45360
    assert parse_instant(settled["paid_at"]) == parse_instant("2026-08-01T00:00:00Z")

    membership = read_membership(api, holder["membership_id"])
    assert membership["dues_balance_cents"] == 0
    assert membership["dues_status"] == "CURRENT"


def test_a_confirmed_stay_blocks_a_transfer_until_it_is_cancelled(api):
    """Only the reservation's state differs between the refusal and the acceptance.

    PRD §2.8: "Open reservations block a transfer —
    `ERR_TRANSFER_BLOCKED_OPEN_RESERVATIONS` (HTTP 409), on transfer submission:
    the membership must hold no reservation in `PENDING`, `CONFIRMED`,
    `WAITLISTED`, `CHECKED_IN` or `EXTENSION_REVIEW`."

    Design: Corner/validations/transfer_is_blocked_while_the_membership_still_holds_an_open_reservation
    """
    reset_clock(api)
    tier = create_president_tier(api)
    park = create_open_park(
        api,
        name="Cedar Spring RV Resort",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
    )
    holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Dana Whitlock", "email": "dana.whitlock@example.com"},
        upfront_paid_cents=1850000,
    )
    receiver = create_member(api, full_name="Nathan Boyle", email="nathan.boyle@example.com")
    stay = book_member_stay(
        api, holder["headers"], park["id"], holder["membership_id"], "2026-08-10", "2026-08-13"
    )
    assert stay["status"] == "CONFIRMED"
    blocked_version = read_membership(api, holder["membership_id"])["version"]

    validate_error(
        api.create_transfer_request(
            make_transfer_request_payload(
                holder["membership_id"], receiver["id"], "GIFT", blocked_version
            ),
            holder["headers"],
        ),
        "ERR_TRANSFER_BLOCKED_OPEN_RESERVATIONS",
        409,
    )
    still_active = read_membership(api, holder["membership_id"])
    assert_membership_axes(still_active, "ACTIVE", "CURRENT")
    assert still_active["version"] == blocked_version, "the refused submission bumped no version"

    cancelled = validate_success(
        api.cancel_reservation(stay["id"], holder["headers"]), 200
    )
    assert cancelled["status"] == "CANCELLED"
    freed_version = read_membership(api, holder["membership_id"])["version"]
    assert freed_version == blocked_version + 1, "the credit-back bumped the membership version"

    accepted = validate_success(
        api.create_transfer_request(
            make_transfer_request_payload(
                holder["membership_id"], receiver["id"], "GIFT", freed_version
            ),
            holder["headers"],
        ),
        201,
    )
    assert accepted["status"] == "SUBMITTED"
    assert accepted["transfer_fee_cents"] == 47500
    assert read_membership(api, holder["membership_id"])["membership_status"] == "TRANSFER_PENDING"


def test_grace_restricts_class_a_parks_only(api):
    """The same membership is refused at CLASS_A and admitted at CLASS_C on one flag.

    PRD §3.3: "A membership in `GRACE` retains partial privileges — it may still
    book `CLASS_B` and `CLASS_C` parks — but is refused at `CLASS_A` parks with
    `ERR_CLASS_A_RESTRICTED_IN_GRACE`, which is the club's gentle first
    consequence of an unpaid invoice."

    Design: Corner/validations/class_a_booking_is_refused_only_while_the_dues_status_flag_is_grace
    """
    reset_clock(api)
    tier = create_president_tier(api)
    class_a_park = create_open_park(
        api,
        name="Crystal Shore RV Resort",
        park_class="CLASS_A",
        total_sites=40,
        member_allocation_pct=60,
    )
    class_c_park = create_open_park(
        api,
        name="Pine Crest Campground",
        park_class="CLASS_C",
        total_sites=40,
        member_allocation_pct=60,
    )
    holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Dana Whitlock", "email": "dana.whitlock@example.com"},
        upfront_paid_cents=1850000,
    )
    while_current = book_member_stay(
        api,
        holder["headers"],
        class_a_park["id"],
        holder["membership_id"],
        "2026-08-10",
        "2026-08-13",
    )
    assert_reservation_state(while_current, "CONFIRMED", entitlement_nights_charged=3)

    set_clock(api, "2026-09-01")
    sweep = run_delinquency_sweep(api)
    assert sweep["invoices_swept"] == 1
    assert sweep["memberships_to_grace"] == 1
    assert read_invoice(api, holder["invoice_id"])["days_past_due"] == 1
    graced = read_membership(api, holder["membership_id"])
    assert_membership_axes(graced, "ACTIVE", "GRACE")

    validate_error(
        api.create_reservation(
            make_reservation_payload(
                class_a_park["id"], holder["membership_id"], "2026-09-10", "2026-09-13"
            ),
            holder["headers"],
        ),
        "ERR_CLASS_A_RESTRICTED_IN_GRACE",
        422,
    )
    assert_entitlement_counters(
        read_membership(api, holder["membership_id"]), class_a=3, annual=3
    )
    rows, _meta = validate_paginated(
        api.list_reservations(ADMIN, {"membership_id": holder["membership_id"]})
    )
    assert len(rows) == 1, "the refused CLASS_A attempt created no reservation row"

    admitted = validate_success(
        api.create_reservation(
            make_reservation_payload(
                class_c_park["id"], holder["membership_id"], "2026-09-10", "2026-09-12"
            ),
            holder["headers"],
        ),
        201,
    )
    assert_reservation_state(
        admitted, "CONFIRMED", pool_charged="MEMBER_POOL", entitlement_nights_charged=2
    )


def test_the_absolute_run_ceiling_binds_although_every_stay_is_within_the_tier_limit(api):
    """Three legal stays merge into a 48-night run that no tier limit can excuse.

    PRD §3.3: "Independently, and whether or not an exception exists, the merged
    run must be no greater than the network's absolute run ceiling of 45 nights;
    breaching that is refused with `ERR_ABSOLUTE_OCCUPANCY_CAP`, and no
    exception, grant or approval anywhere in this system lifts it."

    Design: Corner/validations/absolute_run_cap_binds_although_each_individual_stay_is_within_the_tier_limit
    """
    reset_clock(api)
    tier = create_tier(
        api,
        code="LONGSTAY",
        name="Long Stay Class",
        tier_rank=4,
        upfront_cost_cents=2400000,
        annual_dues_cents=70000,
        entitlement_nights_class_a=60,
        entitlement_nights_class_b=60,
        entitlement_nights_class_c=60,
        annual_total_night_cap=180,
        advance_window_days=365,
        max_consecutive_stay_nights=44,
        min_out_nights_between_stays=1,
        affiliate_access_enabled=False,
        resale_allowed=False,
        transfer_fee_cents=120000,
    )
    park = create_open_park(
        api,
        name="Pine Crest Campground",
        park_class="CLASS_C",
        total_sites=40,
        member_allocation_pct=60,
    )
    holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Dana Whitlock", "email": "dana.whitlock@example.com"},
        upfront_paid_cents=2400000,
    )

    first = book_member_stay(
        api, holder["headers"], park["id"], holder["membership_id"], "2026-08-05", "2026-08-25"
    )
    assert first["consecutive_run_nights"] == 20
    second = book_member_stay(
        api, holder["headers"], park["id"], holder["membership_id"], "2026-08-26", "2026-09-15"
    )
    assert second["consecutive_run_nights"] == 41, "the one-night gap links the two stays"

    response = api.create_reservation(
        make_reservation_payload(
            park["id"], holder["membership_id"], "2026-09-16", "2026-09-22"
        ),
        holder["headers"],
    )
    # 2026-08-05 through 2026-09-22 is 48 nights, past the network ceiling of 45.
    validate_error(response, "ERR_ABSOLUTE_OCCUPANCY_CAP", 422)

    rows, _meta = validate_paginated(
        api.list_reservations(ADMIN, {"membership_id": holder["membership_id"]})
    )
    assert len(rows) == 2, "no third reservation row was created"
    assert read_reservation(api, second["id"])["consecutive_run_nights"] == 41
    # 46 of 60 class C nights were available, so no fiscal rule can be the cause.
    assert_entitlement_counters(
        read_membership(api, holder["membership_id"]), class_c=40, annual=40
    )


def test_an_out_and_back_gap_exactly_at_the_tier_minimum_passes(api):
    """Two nights out is refused and exactly three nights out is accepted.

    PRD §3.3: "A gap exactly equal to the requirement passes; only a strictly
    smaller gap is refused, with `ERR_OUT_AND_BACK_VIOLATION`."

    Design: Corner/validations/out_and_back_gap_exactly_at_the_tier_minimum_is_accepted
    """
    reset_clock(api)
    tier = create_classic_tier(api)
    assert tier["min_out_nights_between_stays"] == 3
    park = create_open_park(
        api,
        name="Pine Crest Campground",
        park_class="CLASS_C",
        total_sites=40,
        member_allocation_pct=60,
    )
    holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Dana Whitlock", "email": "dana.whitlock@example.com"},
    )
    first = book_member_stay(
        api, holder["headers"], park["id"], holder["membership_id"], "2026-08-05", "2026-08-08"
    )
    assert_reservation_state(first, "CONFIRMED", entitlement_nights_charged=3)

    validate_error(
        api.create_reservation(
            make_reservation_payload(
                park["id"], holder["membership_id"], "2026-08-10", "2026-08-12"
            ),
            holder["headers"],
        ),
        "ERR_OUT_AND_BACK_VIOLATION",
        422,
    )
    assert_entitlement_counters(
        read_membership(api, holder["membership_id"]), class_c=3, annual=3
    )

    accepted = validate_success(
        api.create_reservation(
            make_reservation_payload(
                park["id"], holder["membership_id"], "2026-08-11", "2026-08-13"
            ),
            holder["headers"],
        ),
        201,
    )
    assert_reservation_state(
        accepted, "CONFIRMED", pool_charged="MEMBER_POOL", entitlement_nights_charged=2
    )
    assert accepted["consecutive_run_nights"] == 2, (
        "a three-night gap is wider than the one-night link, so the runs stay separate"
    )
    assert_entitlement_counters(
        read_membership(api, holder["membership_id"]), class_c=5, annual=5
    )


def test_affiliate_tier_eligibility_is_reported_before_the_quota_arithmetic(api):
    """The rank-1 no-access tier fails eligibility, so the exhausted quota never speaks.

    PRD §3.3: "At a partner-network park, the booking tier must have
    `affiliate_access_enabled` true and its `tier_rank` must be at least the
    agreement's `min_tier_rank`; failing either is refused with
    `ERR_AFFILIATE_TIER_INELIGIBLE`."

    Design: Corner/validations/affiliate_tier_eligibility_is_resolved_before_the_quota_arithmetic
    """
    reset_clock(api)
    tier = create_classic_tier(api)
    assert tier["tier_rank"] == 1
    assert tier["affiliate_access_enabled"] is False
    agreement = create_active_agreement(
        api,
        partner_name="Timberline Partner Network",
        annual_member_night_quota=1,
        reciprocity_ratio=1.5,
        min_tier_rank=2,
        advance_window_cap_days=45,
        per_stay_night_cap=7,
        settlement_rate_cents_per_night=1500,
    )
    park = create_affiliate_open_park(
        api,
        agreement["id"],
        name="Timberline Ridge Partner Park",
        park_class="CLASS_C",
        total_sites=40,
        member_allocation_pct=60,
    )
    assert park["network_type"] == "AFFILIATE"
    assert agreement["status"] == "ACTIVE"
    holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Dana Whitlock", "email": "dana.whitlock@example.com"},
    )

    response = api.create_reservation(
        make_reservation_payload(
            park["id"], holder["membership_id"], "2026-08-10", "2026-08-12"
        ),
        holder["headers"],
    )
    # ceil(2 * 1.5) is 3 against a quota of 1, yet eligibility is the rule that reports.
    validate_error(response, "ERR_AFFILIATE_TIER_INELIGIBLE", 422)

    after = read_agreement(api, agreement["id"])
    assert after["nights_consumed_ytd"] == 0, "the quota arithmetic never ran"
    assert after["settlement_owed_cents"] == 0
    assert_entitlement_counters(
        read_membership(api, holder["membership_id"]), class_c=0, annual=0
    )
