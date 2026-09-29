"""Error triggering: existence probes, state guards and capacity refusals."""

from test_helpers import (
    ADMIN,
    CLUB_ADMIN_PRIMARY_ID,
    GUEST,
    NON_EXISTENT_UUID,
    OFFICER,
    assert_entitlement_counters,
    assert_membership_axes,
    assert_occupancy_exception,
    assert_pool_split,
    assert_reservation_state,
    book_member_stay,
    book_transient_stay,
    cancel,
    check_in,
    create_classic_tier,
    create_member,
    create_open_park,
    create_park,
    create_president_tier,
    create_tier,
    decide_exception,
    extend,
    find_by_id,
    list_reservation_exceptions,
    make_capital_decision_payload,
    make_exception_decision_payload,
    make_member_headers,
    make_park_manager_headers,
    make_payment_payload,
    make_payment_reversal_payload,
    make_reservation_payload,
    make_transfer_decision_payload,
    make_transfer_request_payload,
    make_transient_reservation_payload,
    parse_instant,
    read_invoice,
    read_membership,
    read_park,
    read_reservation,
    reset_clock,
    run_delinquency_sweep,
    sell_membership_to_new_member,
    schedule_window,
    submit_transfer,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_every_unknown_identifier_reports_its_own_not_found_error(api):
    """Eight endpoints, eight distinct 404s, each probed with only one id falsified.

    PRD §2.8: "Membership existence for every membership id in a path or body —
    `ERR_MEMBERSHIP_NOT_FOUND`, on reading one membership, listing a membership's
    dues invoices, suspension, reinstatement, member booking, and transfer
    submission."

    Design: Corner/errors/every_unknown_identifier_reports_its_own_not_found_error
    """
    reset_clock(api)
    tier = create_president_tier(api)
    member = create_member(api, full_name="Dana Whitlock", email="dana.whitlock@example.com")
    park = create_park(
        api,
        name="Elk Meadow RV Resort",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
    )

    membership_error = validate_error(
        api.get_membership(NON_EXISTENT_UUID, ADMIN), "ERR_MEMBERSHIP_NOT_FOUND", 404
    )
    assert membership_error["message"], "every error envelope carries a message"

    validate_error(
        api.create_membership(
            {
                "member_id": member["id"],
                "tier_id": NON_EXISTENT_UUID,
                "upfront_paid_cents": 1850000,
            },
            ADMIN,
        ),
        "ERR_TIER_NOT_FOUND",
        404,
    )
    validate_error(
        api.create_membership(
            {
                "member_id": NON_EXISTENT_UUID,
                "tier_id": tier["id"],
                "upfront_paid_cents": 1850000,
            },
            ADMIN,
        ),
        "ERR_MEMBER_NOT_FOUND",
        404,
    )

    # Issued as ClubAdmin, so no ownership rule can shadow the existence check, and
    # the existence rule reports ahead of the payment-amount rule.
    validate_error(
        api.pay_dues_invoice(NON_EXISTENT_UUID, make_payment_payload(45360), ADMIN),
        "ERR_DUES_INVOICE_NOT_FOUND",
        404,
    )
    validate_error(
        api.decide_transfer_request(
            NON_EXISTENT_UUID,
            make_transfer_decision_payload("REJECT", rejection_reason="probe"),
            ADMIN,
        ),
        "ERR_TRANSFER_REQUEST_NOT_FOUND",
        404,
    )
    validate_error(
        api.activate_maintenance_window(NON_EXISTENT_UUID, make_park_manager_headers(park["id"])),
        "ERR_MAINTENANCE_WINDOW_NOT_FOUND",
        404,
    )
    validate_error(
        api.decide_capital_project(
            NON_EXISTENT_UUID, make_capital_decision_payload("APPROVE", park["version"]), ADMIN
        ),
        "ERR_CAPITAL_PROJECT_NOT_FOUND",
        404,
    )
    validate_error(
        api.decide_occupancy_exception(
            NON_EXISTENT_UUID,
            make_exception_decision_payload("GRANT", granted_run_nights=30),
            OFFICER,
        ),
        "ERR_OCCUPANCY_EXCEPTION_NOT_FOUND",
        404,
    )

    _rows, meta = validate_paginated(api.list_memberships(ADMIN))
    assert meta["total_count"] == 0, "neither half-valid membership body persisted a contract"


def test_deciding_a_transfer_request_twice_reports_the_invalid_state(api):
    """The second decision is refused even though it names the opposite verb.

    PRD §3.8: "The request must be `SUBMITTED`, and a second decision is refused
    with `ERR_INVALID_TRANSFER_STATE`."

    Design: Corner/errors/deciding_a_transfer_request_twice_reports_the_invalid_transfer_state
    """
    reset_clock(api)
    tier = create_president_tier(api)
    holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Dana Whitlock", "email": "dana.whitlock@example.com"},
        upfront_paid_cents=1850000,
    )
    receiver = create_member(api, full_name="Nathan Boyle", email="nathan.boyle@example.com")
    request = submit_transfer(
        api, holder["headers"], holder["membership_id"], receiver["id"], transfer_type="GIFT"
    )
    assert request["status"] == "SUBMITTED"

    rejected = validate_success(
        api.decide_transfer_request(
            request["id"],
            make_transfer_decision_payload("REJECT", rejection_reason="Receiving member withdrew"),
            ADMIN,
        ),
        200,
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["decided_by_user_id"] == CLUB_ADMIN_PRIMARY_ID
    assert_membership_axes(read_membership(api, holder["membership_id"]), "ACTIVE", "CURRENT")

    validate_error(
        api.decide_transfer_request(
            request["id"], make_transfer_decision_payload("APPROVE"), ADMIN
        ),
        "ERR_INVALID_TRANSFER_STATE",
        409,
    )

    final = validate_success(api.get_transfer_request(request["id"], ADMIN), 200)
    assert final["status"] == "REJECTED", "the refused APPROVE did not overwrite the decision"
    assert final["successor_membership_id"] is None, "the refused APPROVE minted nothing"
    assert_membership_axes(read_membership(api, holder["membership_id"]), "ACTIVE", "CURRENT")


def test_an_invoice_is_payable_only_while_open_and_reversible_only_while_paid(api):
    """One invoice walks OPEN to PAID and back, and each illegal direction is a 409.

    PRD §2.8: "Dues invoice state — `ERR_DUES_INVOICE_NOT_PAYABLE` (HTTP 409): a
    payment requires the invoice to be `OPEN` or `PAST_DUE`, and a reversal
    requires it to be `PAID`."

    PRD §3.7: "When the current logical date is on or before the invoice's
    `due_date`, the invoice returns to `OPEN`, `late_fee_cents` is set back to 0,
    and `dues_status` stays `CURRENT` — nothing was ever late."

    Design: Corner/errors/an_invoice_is_payable_only_while_open_and_reversible_only_while_paid
    """
    reset_clock(api)
    tier = create_classic_tier(api)
    holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Dana Whitlock", "email": "dana.whitlock@example.com"},
    )
    invoice_id = holder["invoice_id"]
    opened = read_invoice(api, invoice_id)
    assert opened["status"] == "OPEN"
    assert opened["amount_cents"] == 45360
    assert opened["due_date"] == "2026-08-31", "the clock is still inside the term"

    validate_error(
        api.reverse_dues_payment(
            invoice_id,
            make_payment_reversal_payload(reason="Probe before any payment exists"),
            ADMIN,
        ),
        "ERR_DUES_INVOICE_NOT_PAYABLE",
        409,
    )

    paid = validate_success(
        api.pay_dues_invoice(invoice_id, make_payment_payload(45360), ADMIN), 200
    )
    assert paid["status"] == "PAID"
    assert paid["paid_amount_cents"] == 45360

    # The invoice state rule reports here, not the payment-amount rule the same
    # 45360 body would trip once paid_amount_cents is non-zero.
    validate_error(
        api.pay_dues_invoice(invoice_id, make_payment_payload(45360), ADMIN),
        "ERR_DUES_INVOICE_NOT_PAYABLE",
        409,
    )

    reopened = validate_success(
        api.reverse_dues_payment(
            invoice_id, make_payment_reversal_payload(reason="Card chargeback"), ADMIN
        ),
        200,
    )
    assert reopened["status"] == "OPEN"
    assert reopened["paid_amount_cents"] == 0
    assert reopened["paid_at"] is None
    assert reopened["late_fee_cents"] == 0
    assert read_membership(api, holder["membership_id"])["dues_status"] == "CURRENT"

    validate_error(
        api.reverse_dues_payment(
            invoice_id, make_payment_reversal_payload(reason="Duplicate chargeback"), ADMIN
        ),
        "ERR_DUES_INVOICE_NOT_PAYABLE",
        409,
    )
    assert read_invoice(api, invoice_id)["status"] == "OPEN", (
        "the guard reads the live status rather than a one-shot flag"
    )


def test_a_scheduled_window_and_the_season_edge_both_block_a_night(api):
    """The window's closed interval and the season's last day are probed on both sides.

    PRD §2.8: "Maintenance conflict — `ERR_MAINTENANCE_WINDOW_CONFLICT` (HTTP
    409), on member booking, transient booking and extension: no night of the
    requested or extended stay may fall inside the closed inclusive interval
    running from `start_date` through `end_date` of any `SCHEDULED` or `ACTIVE`
    maintenance window at that park."

    PRD §2.6: "A park's operating season is likewise closed on both ends:
    `season_open_date` is the first operable date and `season_close_date` is the
    last, inclusive, and `season_close_date` must be strictly after
    `season_open_date`."

    Design: Corner/errors/a_scheduled_window_blocks_its_closed_interval_and_the_season_edge_blocks_the_night_after_close
    """
    reset_clock(api)
    tier = create_president_tier(api)
    holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Dana Whitlock", "email": "dana.whitlock@example.com"},
        upfront_paid_cents=1850000,
    )
    park = create_open_park(
        api,
        name="Birch Hollow Campground",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
        season_open_date="2026-06-01",
        season_close_date="2026-09-30",
    )
    window = schedule_window(api, park["id"], "2026-08-20", "2026-08-24", work_type="ROUTINE")
    assert window["status"] == "SCHEDULED", "the window is never activated"
    assert park["park_status"] == "OPEN"

    # Nights 08-18, 08-19 and 08-20; the last is start_date of the closed interval.
    validate_error(
        api.create_reservation(
            make_reservation_payload(
                park["id"], holder["membership_id"], "2026-08-18", "2026-08-21"
            ),
            holder["headers"],
        ),
        "ERR_MAINTENANCE_WINDOW_CONFLICT",
        409,
    )
    # Nights 08-24 and 08-25; the first is end_date, which is blocked inclusively.
    validate_error(
        api.create_reservation(
            make_reservation_payload(
                park["id"], holder["membership_id"], "2026-08-24", "2026-08-26"
            ),
            holder["headers"],
        ),
        "ERR_MAINTENANCE_WINDOW_CONFLICT",
        409,
    )

    after_window = validate_success(
        api.create_reservation(
            make_reservation_payload(
                park["id"], holder["membership_id"], "2026-08-25", "2026-08-27"
            ),
            holder["headers"],
        ),
        201,
    )
    assert_reservation_state(after_window, "CONFIRMED", pool_charged="MEMBER_POOL")
    assert after_window["nights"] == 2, "nights 08-25 and 08-26 sit entirely after the window"

    # Nights 09-28, 09-29, 09-30 and 10-01; the last is past season_close_date.
    validate_error(
        api.create_reservation(
            make_reservation_payload(
                park["id"], holder["membership_id"], "2026-09-28", "2026-10-02"
            ),
            holder["headers"],
        ),
        "ERR_STAY_OUTSIDE_SEASON",
        422,
    )
    on_the_edge = validate_success(
        api.create_reservation(
            make_reservation_payload(
                park["id"], holder["membership_id"], "2026-09-28", "2026-10-01"
            ),
            holder["headers"],
        ),
        201,
    )
    assert_reservation_state(on_the_edge, "CONFIRMED", pool_charged="MEMBER_POOL")
    assert on_the_edge["nights"] == 3, "the last night IS season_close_date and is operable"

    assert read_park(api, park["id"])["park_status"] == "OPEN"
    rows, _meta = validate_paginated(
        api.list_park_maintenance_windows(park["id"], make_park_manager_headers(park["id"]))
    )
    still_scheduled = find_by_id(rows, window["id"])
    assert still_scheduled["status"] == "SCHEDULED", "blocking needs no activation"
    assert still_scheduled["cancelled_reservation_count"] == 0


def test_the_transient_pool_refuses_the_public_while_the_member_pool_waitlists(api):
    """The same exhausted night yields a WAITLISTED member row and a refused guest.

    PRD §3.4: "When it fails on even one night, the booking is refused with
    `ERR_NO_TRANSIENT_CAPACITY`: the public is never waitlisted and never borrows a
    member pad."

    Design: Corner/errors/the_transient_pool_refuses_the_public_outright_while_the_member_pool_waitlists
    """
    reset_clock(api)
    tier = create_classic_tier(api)
    park = create_open_park(
        api,
        name="Cedar Flats Micro Park",
        park_class="CLASS_C",
        total_sites=2,
        member_allocation_pct=50,
    )
    # floor(2 * 50 / 100) is one member pad, leaving one transient pad.
    assert_pool_split(park, member_sites=1, transient_sites=1)
    seated = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Dana Whitlock", "email": "dana.whitlock@example.com"},
    )
    queued = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Nathan Boyle", "email": "nathan.boyle@example.com"},
    )

    guest = book_transient_stay(
        api, park["id"], "2026-08-10", "2026-08-12", guest_name="Priya Raman"
    )
    assert_reservation_state(guest, "CONFIRMED", pool_charged="TRANSIENT_POOL")
    member_stay = book_member_stay(
        api, seated["headers"], park["id"], seated["membership_id"], "2026-08-10", "2026-08-12"
    )
    assert_reservation_state(member_stay, "CONFIRMED", pool_charged="MEMBER_POOL")

    waitlisted = validate_success(
        api.create_reservation(
            make_reservation_payload(
                park["id"], queued["membership_id"], "2026-08-10", "2026-08-12"
            ),
            queued["headers"],
        ),
        201,
    )
    assert_reservation_state(
        waitlisted, "WAITLISTED", pool_charged="NONE", entitlement_nights_charged=0
    )

    validate_error(
        api.create_transient_reservation(
            make_transient_reservation_payload(
                park["id"], "2026-08-11", "2026-08-13", guest_name="Owen Deleon"
            ),
            GUEST,
        ),
        "ERR_NO_TRANSIENT_CAPACITY",
        409,
    )

    adjacent = validate_success(
        api.create_transient_reservation(
            make_transient_reservation_payload(
                park["id"], "2026-08-12", "2026-08-14", guest_name="Owen Deleon"
            ),
            GUEST,
        ),
        201,
    )
    assert_reservation_state(adjacent, "CONFIRMED", pool_charged="TRANSIENT_POOL")

    _rows, meta = validate_paginated(
        api.list_reservations(ADMIN, {"park_id": park["id"], "booker_type": "TRANSIENT"})
    )
    assert meta["total_count"] == 2, "the refused public booking left no row behind"


def test_an_occupancy_exception_can_only_be_decided_once_in_either_direction(api):
    """A GRANTED exception refuses both a repeat GRANT and an opposing DENY.

    PRD §3.5: "The exception must be `REQUESTED`; a second decision on an
    already-resolved exception is refused with `ERR_EXCEPTION_ALREADY_DECIDED`."

    Design: Corner/errors/an_occupancy_exception_can_only_be_decided_once_in_either_direction
    """
    reset_clock(api)
    tier = create_tier(
        api,
        code="SHORTSTAY",
        name="Short Stay Class",
        tier_rank=2,
        upfront_cost_cents=1200000,
        annual_dues_cents=50000,
        entitlement_nights_class_a=0,
        entitlement_nights_class_b=20,
        entitlement_nights_class_c=20,
        annual_total_night_cap=40,
        advance_window_days=120,
        max_consecutive_stay_nights=3,
        min_out_nights_between_stays=1,
        affiliate_access_enabled=False,
        resale_allowed=False,
        transfer_fee_cents=70000,
    )
    park = create_open_park(
        api,
        name="Willow Bend Campground",
        park_class="CLASS_C",
        total_sites=20,
        member_allocation_pct=60,
    )
    holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Dana Whitlock", "email": "dana.whitlock@example.com"},
        upfront_paid_cents=1200000,
    )
    stay = book_member_stay(
        api, holder["headers"], park["id"], holder["membership_id"], "2026-08-10", "2026-08-13"
    )
    assert stay["consecutive_run_nights"] == 3, "the stay sits exactly at the tier limit"
    check_in(api, stay["id"], holder["headers"], "2026-08-10T13:00:00Z")
    reviewed = extend(api, stay["id"], holder["headers"], "2026-08-16", reason="MEDICAL")
    assert_reservation_state(reviewed, "EXTENSION_REVIEW")
    assert reviewed["departure_date"] == "2026-08-16"

    exceptions = list_reservation_exceptions(api, stay["id"])
    assert len(exceptions) == 1
    exception = exceptions[0]
    assert_occupancy_exception(exception)
    assert exception["status"] == "REQUESTED"
    assert exception["requested_run_nights"] == 6
    assert exception["tier_limit_nights"] == 3

    granted = decide_exception(
        api,
        exception["id"],
        "GRANT",
        granted_run_nights=6,
        decision_note="Documented medical hold",
    )
    assert granted["status"] == "GRANTED"
    assert granted["granted_run_nights"] == 6

    validate_error(
        api.decide_occupancy_exception(
            exception["id"],
            make_exception_decision_payload("GRANT", granted_run_nights=6),
            OFFICER,
        ),
        "ERR_EXCEPTION_ALREADY_DECIDED",
        409,
    )
    validate_error(
        api.decide_occupancy_exception(
            exception["id"],
            make_exception_decision_payload("DENY", decision_note="Reversal attempt"),
            OFFICER,
        ),
        "ERR_EXCEPTION_ALREADY_DECIDED",
        409,
    )

    final_exception = validate_success(api.get_occupancy_exception(exception["id"], OFFICER), 200)
    assert final_exception["status"] == "GRANTED", "an already-decided exception cannot be flipped"
    assert final_exception["granted_run_nights"] == 6

    final_stay = read_reservation(api, stay["id"])
    assert_reservation_state(final_stay, "CHECKED_IN", entitlement_nights_charged=6)
    assert final_stay["departure_date"] == "2026-08-16", "the refused DENY rolled nothing back"
    assert final_stay["extension_denied_count"] == 0
    assert_entitlement_counters(
        read_membership(api, holder["membership_id"]), class_c=6, annual=6
    )


def test_the_third_transfer_in_a_chain_is_refused_at_the_chain_limit(api):
    """Two approvals are permitted and the third submission is refused.

    PRD §3.8: "Finally the chain limit binds: `transfer_count` must be strictly
    below the maximum of 2 transfers per chain, refused otherwise with
    `ERR_TRANSFER_LIMIT_REACHED`, so an original purchase may change hands twice
    and no more."

    Design: Corner/errors/the_third_transfer_in_a_chain_is_refused_at_the_chain_limit
    """
    reset_clock(api)
    tier = create_president_tier(api)
    origin = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Dana Whitlock", "email": "dana.whitlock@example.com"},
        upfront_paid_cents=1850000,
    )
    second = create_member(api, full_name="Nathan Boyle", email="nathan.boyle@example.com")
    third = create_member(api, full_name="Priya Raman", email="priya.raman@example.com")
    fourth = create_member(api, full_name="Owen Deleon", email="owen.deleon@example.com")
    generation_zero = read_membership(api, origin["membership_id"])
    assert generation_zero["transfer_count"] == 0

    first_request = submit_transfer(
        api, origin["headers"], origin["membership_id"], second["id"], transfer_type="GIFT"
    )
    first_decision = validate_success(
        api.decide_transfer_request(
            first_request["id"], make_transfer_decision_payload("APPROVE"), ADMIN
        ),
        200,
    )
    generation_one = read_membership(api, first_decision["successor_membership_id"])
    assert generation_one["transfer_count"] == 1
    assert generation_one["transferred_from_membership_id"] == origin["membership_id"]
    assert parse_instant(generation_one["tenure_origin_at"]) == parse_instant(
        generation_zero["tenure_origin_at"]
    ), "tenure travels with the chain"

    second_request = submit_transfer(
        api,
        make_member_headers(second["id"]),
        generation_one["id"],
        third["id"],
        transfer_type="GIFT",
    )
    second_decision = validate_success(
        api.decide_transfer_request(
            second_request["id"], make_transfer_decision_payload("APPROVE"), ADMIN
        ),
        200,
    )
    generation_two = read_membership(api, second_decision["successor_membership_id"])
    assert generation_two["transfer_count"] == 2
    assert parse_instant(generation_two["tenure_origin_at"]) == parse_instant(
        generation_zero["tenure_origin_at"]
    )
    assert_membership_axes(generation_two, "ACTIVE", "CURRENT")

    validate_error(
        api.create_transfer_request(
            make_transfer_request_payload(
                generation_two["id"], fourth["id"], "GIFT", generation_two["version"]
            ),
            make_member_headers(third["id"]),
        ),
        "ERR_TRANSFER_LIMIT_REACHED",
        422,
    )

    unchanged = read_membership(api, generation_two["id"])
    assert_membership_axes(unchanged, "ACTIVE", "CURRENT")
    assert unchanged["version"] == generation_two["version"], "the refusal froze nothing"
    _rows, meta = validate_paginated(
        api.list_transfer_requests(ADMIN, {"membership_id": generation_two["id"]})
    )
    assert meta["total_count"] == 0, "no request row was persisted for the refused attempt"


def test_grace_dues_may_book_but_may_neither_submit_nor_have_a_transfer_decided(api):
    """One dues status yields a 201 on booking and a 409 on both transfer legs.

    PRD §3.8: "The membership's `membership_status` must be `ACTIVE`, refused
    otherwise with `ERR_MEMBERSHIP_NOT_ACTIVE`, and its `dues_status` must be
    `CURRENT` — the transfer path is stricter than the booking path, which
    tolerates `GRACE` — refused otherwise with `ERR_DUES_NOT_CURRENT`."

    PRD §3.8: "Approval additionally requires the membership to be in
    `TRANSFER_PENDING` with `dues_status` still `CURRENT`, refused otherwise with
    `ERR_DUES_NOT_CURRENT`."

    Design: Corner/errors/grace_dues_may_still_book_but_may_neither_submit_nor_have_a_transfer_decided
    """
    reset_clock(api)
    tier = create_classic_tier(api)
    booker = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Dana Whitlock", "email": "dana.whitlock@example.com"},
    )
    pending = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Priya Raman", "email": "priya.raman@example.com"},
    )
    receiver = create_member(api, full_name="Nathan Boyle", email="nathan.boyle@example.com")
    park = create_open_park(
        api,
        name="Harvest Ridge Campground",
        park_class="CLASS_B",
        total_sites=30,
        member_allocation_pct=60,
    )
    early_request = submit_transfer(
        api, pending["headers"], pending["membership_id"], receiver["id"], transfer_type="GIFT"
    )
    assert early_request["status"] == "SUBMITTED", "submitted while its dues were still CURRENT"

    sweep = run_delinquency_sweep(api, at_instant="2026-09-10")
    assert sweep["memberships_to_grace"] == 2
    assert sweep["memberships_to_delinquent"] == 0, "ten days past due is short of the 30-day band"
    graced = read_membership(api, booker["membership_id"])
    assert_membership_axes(graced, "ACTIVE", "GRACE")
    assert_membership_axes(
        read_membership(api, pending["membership_id"]), "TRANSFER_PENDING", "GRACE"
    )
    aged = read_invoice(api, booker["invoice_id"])
    assert aged["status"] == "PAST_DUE"
    assert aged["days_past_due"] == 10
    # ceil(10 / 30) is one month late, and round_half_up(45360 * 0.015 * 1) is 680.
    assert aged["late_fee_cents"] == 680
    assert graced["dues_balance_cents"] == 46040

    validate_error(
        api.create_transfer_request(
            make_transfer_request_payload(
                booker["membership_id"], receiver["id"], "GIFT", graced["version"]
            ),
            booker["headers"],
        ),
        "ERR_DUES_NOT_CURRENT",
        409,
    )
    validate_error(
        api.decide_transfer_request(
            early_request["id"], make_transfer_decision_payload("APPROVE"), ADMIN
        ),
        "ERR_DUES_NOT_CURRENT",
        409,
    )

    booked = validate_success(
        api.create_reservation(
            make_reservation_payload(
                park["id"], booker["membership_id"], "2026-09-20", "2026-09-22"
            ),
            booker["headers"],
        ),
        201,
    )
    assert_reservation_state(booked, "CONFIRMED", pool_charged="MEMBER_POOL")
    assert cancel(api, booked["id"], booker["headers"])["status"] == "CANCELLED"

    settled = validate_success(
        api.pay_dues_invoice(
            booker["invoice_id"], make_payment_payload(46040), booker["headers"]
        ),
        200,
    )
    assert settled["status"] == "PAID", "45360 of dues plus the 680 late fee"
    cured = read_membership(api, booker["membership_id"])
    assert_membership_axes(cured, "ACTIVE", "CURRENT")
    assert cured["dues_balance_cents"] == 0

    accepted = submit_transfer(
        api, booker["headers"], booker["membership_id"], receiver["id"], transfer_type="GIFT"
    )
    assert accepted["status"] == "SUBMITTED"
    assert accepted["transfer_fee_cents"] == 30000, "round_half_up(60000 * 0.50) on a gift"

    still_open = validate_success(api.get_transfer_request(early_request["id"], ADMIN), 200)
    assert still_open["status"] == "SUBMITTED", "the refused decision left it decidable"
    assert still_open["successor_membership_id"] is None
