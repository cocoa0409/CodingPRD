"""Just-inside and just-outside halves of the positivity, pagination, authority
ceiling, high-value, certificate and time-range edges."""

from test_helpers import (
    ApiErrorId,
    MOVE_MANAGER,
    MOVE_START,
    PLATFORM_ADMIN,
    api_client,
    accept_vendor_assignment,
    assert_money,
    assert_hours,
    assert_two_dp,
    check_in,
    designate,
    donation_receipt_cents,
    freeze_and_start,
    get_success_data,
    make_power_of_attorney_headers,
    make_vendor_headers,
    new_active_authority,
    new_item,
    new_vendor,
    new_vendor_assignment,
    read_crew_assignment,
    read_item,
    read_party,
    read_time_entry,
    read_vendor,
    read_vendor_assignment,
    setup_engagement,
    setup_move_day_plan_confirmed,
    validate_error,
    validate_paginated,
    validate_success,
    new_engagement,
)


def _engagement_with_a_junk_hauler(coi="2026-12-31"):
    world = setup_engagement(with_client_party=False)
    world["vendor"] = new_vendor("Bayside Junk Haul", "JUNK_HAUL", coi)
    return world


def test_a_vendor_order_quoted_at_zero_is_outside_the_positivity_rung():
    """PRD §2.7: "Every required input field of the endpoint is present and of its
    declared type, and the numeric fields the domain requires to be positive are
    greater than zero: `quoted_cents`, `list_price_cents`, `gross_sale_price_cents`,
    `amount_cents` on a charge line, `truck_capacity_cft`, `truck_count`,
    `footprint_linear_inches`, `volume_cft`, `nominal_linear_inches` and
    `nominal_volume_cft`. Otherwise `ERR_VALIDATION`, HTTP 400."

    Design: Corner/validations/positivity_rung_rejects_a_zero_quoted_cents_vendor_assignment
    """
    world = _engagement_with_a_junk_hauler()
    validate_error(
        api_client.create_vendor_assignment(
            {
                "engagement_id": world["engagement_id"],
                "vendor_id": world["vendor"]["id"],
                "service_kind": "HAUL_AWAY",
                "service_date": "2026-06-15",
                "quoted_cents": 0,
            },
            MOVE_MANAGER,
        ),
        ApiErrorId.ERR_VALIDATION.value,
    )
    _, meta = validate_paginated(
        api_client.list_vendor_assignments(
            MOVE_MANAGER, params={"engagement_id": world["engagement_id"]}
        )
    )
    assert meta["total_count"] == 0


def test_a_vendor_order_quoted_at_one_cent_is_inside_the_positivity_rung():
    """PRD §3.8: "Ordering work from a vendor names the `engagement_id`, the
    `vendor_id`, the `service_kind` from `HAUL_AWAY`, `CONSIGNMENT_PICKUP`,
    `APPRAISAL`, `CLEANING` and `SHREDDING`, the `service_date` and the agreed
    `quoted_cents`."
    PRD §3.8: "Orders are born `REQUESTED` and can be listed and filtered by
    `engagement_id`, by `vendor_id`, by `signed_off_by_party_id`, by `status` and by
    `service_date`."

    Design: Corner/validations/positivity_rung_admits_a_one_cent_quoted_vendor_assignment
    """
    world = _engagement_with_a_junk_hauler()
    order = validate_success(
        api_client.create_vendor_assignment(
            {
                "engagement_id": world["engagement_id"],
                "vendor_id": world["vendor"]["id"],
                "service_kind": "HAUL_AWAY",
                "service_date": "2026-06-15",
                "quoted_cents": 1,
            },
            MOVE_MANAGER,
        ),
        expected_status=201,
    )
    assert order["status"] == "REQUESTED"
    assert_money(order["quoted_cents"], 1, "quoted_cents")
    assert_money(order["paid_cents"], 0, "paid_cents")
    assert_money(order["holdback_cents"], 0, "holdback_cents")


def test_a_limit_of_one_and_a_limit_of_one_hundred_are_both_inside_the_window():
    """PRD §2.3: "Every endpoint that returns an array accepts two optional query
    parameters. `limit` defaults to 10, has a minimum of 1 and a maximum of 100.
    `offset` defaults to 0 and has a minimum of 0; there is no upper bound on it."

    Design: Corner/validations/pagination_limit_one_is_the_inclusive_lower_bound
    """
    world = setup_engagement(with_client_party=False)
    new_engagement(
        world["client"]["id"], home_tier="ONE_BED", scheduled_move_start_utc="2026-07-20T14:00:00.000Z"
    )
    client_id = world["client"]["id"]

    rows, meta = validate_paginated(
        api_client.list_engagements(MOVE_MANAGER, params={"client_id": client_id, "limit": 1, "offset": 0})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(rows) == 1

    rows, meta = validate_paginated(
        api_client.list_engagements(MOVE_MANAGER, params={"client_id": client_id, "limit": 100, "offset": 0})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(rows) == 2


def test_a_limit_of_zero_and_a_negative_offset_are_outside_the_window():
    """PRD §2.3: "A `limit` outside the range 1 to 100 inclusive, a non-integer
    `limit`, a negative `offset` or a non-integer `offset` is rejected with
    `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/validations/pagination_limit_zero_and_negative_offset_are_outside_the_range
    """
    world = setup_engagement(with_client_party=False)
    client_id = world["client"]["id"]
    validate_error(
        api_client.list_engagements(MOVE_MANAGER, params={"client_id": client_id, "limit": 0}),
        ApiErrorId.ERR_VALIDATION.value,
    )
    validate_error(
        api_client.list_engagements(MOVE_MANAGER, params={"client_id": client_id, "offset": -1}),
        ApiErrorId.ERR_VALIDATION.value,
    )


def _poa_with_ceiling(ceiling, item_value, scope="FULL"):
    world = setup_engagement(with_client_party=False, with_poa_party=True)
    new_active_authority(
        world["engagement_id"],
        world["poa_party"]["id"],
        authority_scope=scope,
        approval_ceiling_cents=ceiling,
    )
    world["item"] = new_item(
        world["engagement_id"],
        label="Mantel clock",
        category="MISC",
        footprint_linear_inches=12,
        volume_cft=3,
        appraised_value_cents=item_value,
        appraisal_source="APPRAISED",
    )
    return world


def test_a_ceiling_exactly_equal_to_the_item_value_permits_the_designation():
    """PRD §2.7: "The acting party's `active_authority_ceiling_cents` is greater than
    or equal to the subject value, which is the item's `appraised_value_cents` for a
    single-item approval and the maximum `appraised_value_cents` among the
    engagement's non-`KEEP` items for a sort-plan approval. The boundary is
    inclusive: a ceiling exactly equal to the subject value permits the approval."

    Design: Corner/validations/authority_ceiling_exactly_equal_to_the_item_value_permits_the_designation
    """
    world = _poa_with_ceiling(100000, 100000)
    poa_id = world["poa_party"]["id"]
    validate_success(
        api_client.designate_item(
            world["item"]["id"],
            {"disposition": "DONATE", "acting_party_id": poa_id},
            make_power_of_attorney_headers(poa_id),
        )
    )
    item = read_item(world["item"]["id"])
    assert item["disposition"] == "DONATE"
    assert_money(
        item["donation_receipt_cents"],
        donation_receipt_cents(100000, "APPRAISED"),
        "donation_receipt_cents",
    )
    assert_money(read_party(poa_id)["active_authority_ceiling_cents"], 100000, "active ceiling")


def test_a_ceiling_one_cent_below_the_item_value_is_refused():
    """PRD §2.9: "Every approval that role performs is checked against the authority
    records it holds: at least one must be `ACTIVE`, its `authority_scope` must cover
    the operation family, and — for a single-item approval — its
    `approval_ceiling_cents` must reach the item's `appraised_value_cents`."
    PRD §2.7: "Otherwise `ERR_AUTHORITY_CEILING_EXCEEDED`, HTTP 403. Applies to the
    same seven endpoints as rung 27."

    Design: Corner/validations/authority_ceiling_one_cent_below_the_item_value_is_refused
    """
    world = _poa_with_ceiling(99999, 100000)
    poa_id = world["poa_party"]["id"]
    validate_error(
        api_client.designate_item(
            world["item"]["id"],
            {"disposition": "DONATE", "acting_party_id": poa_id},
            make_power_of_attorney_headers(poa_id),
        ),
        ApiErrorId.ERR_AUTHORITY_CEILING_EXCEEDED.value,
    )
    item = read_item(world["item"]["id"])
    assert item["disposition"] == "UNDECIDED"
    assert_money(item["donation_receipt_cents"], 0, "donation_receipt_cents")
    assert_money(read_party(poa_id)["active_authority_ceiling_cents"], 99999, "active ceiling")


def test_exactly_the_high_value_threshold_demands_a_full_scope():
    """PRD §2.9: "Items valued at or above 250000 cents demand a scope of exactly
    `FULL`, so a `DISPOSITION_ONLY` delegate with a generous ceiling still cannot
    move the piano."
    PRD §2.7: "When the subject item's `appraised_value_cents` is at or above the
    high-value threshold of 250000 cents, the acting `authority_scope` must be
    exactly `FULL`; `DISPOSITION_ONLY` is not enough. Otherwise
    `ERR_HIGH_VALUE_AUTHORITY_REQUIRED`, HTTP 403."

    Design: Corner/validations/high_value_threshold_at_exactly_the_constant_demands_full_scope
    """
    world = _poa_with_ceiling(300000, 250000, scope="DISPOSITION_ONLY")
    poa_id = world["poa_party"]["id"]
    error = validate_error(
        api_client.designate_item(
            world["item"]["id"],
            {"disposition": "SELL", "acting_party_id": poa_id},
            make_power_of_attorney_headers(poa_id),
        ),
        ApiErrorId.ERR_HIGH_VALUE_AUTHORITY_REQUIRED.value,
    )
    assert error["error_id"] != ApiErrorId.ERR_AUTHORITY_CEILING_EXCEEDED.value
    assert read_item(world["item"]["id"])["disposition"] == "UNDECIDED"


def test_one_cent_below_the_high_value_threshold_admits_a_disposition_only_scope():
    """PRD §2.7: "That active record's `authority_scope` covers the operation family:
    `FULL` or `DISPOSITION_ONLY` for disposition, sort-plan and placement approvals,
    `FULL` or `BILLING_ONLY` for invoice disputes and vendor sign-off."
    PRD §3.4: "Moving to `SELL` additionally requires `appraised_value_cents` of at
    least 15000 cents — exactly 15000 is consignable, one cent less is not, and the
    request is then refused with `ERR_ITEM_BELOW_CONSIGN_MINIMUM` — and it clears
    `assigned_room_id` to null."

    Design: Corner/validations/one_cent_below_the_high_value_threshold_admits_disposition_only_scope
    """
    world = _poa_with_ceiling(300000, 249999, scope="DISPOSITION_ONLY")
    poa_id = world["poa_party"]["id"]
    validate_success(
        api_client.designate_item(
            world["item"]["id"],
            {"disposition": "SELL", "acting_party_id": poa_id},
            make_power_of_attorney_headers(poa_id),
        )
    )
    item = read_item(world["item"]["id"])
    assert item["disposition"] == "SELL"
    assert item["assigned_room_id"] is None
    assert read_party(poa_id)["can_approve_dispositions"] is True


def test_a_certificate_expiring_on_the_service_date_still_schedules():
    """PRD §2.7: "The vendor's `coi_expires_on` is not earlier than the assignment's
    `service_date`; a certificate expiring exactly on the service date is valid.
    Otherwise `ERR_VENDOR_COI_EXPIRED`, HTTP 422. Applies to
    `POST /vendor-assignments/{id}/schedule`."

    Design: Corner/validations/coi_expiring_exactly_on_the_service_date_still_schedules
    """
    world = _engagement_with_a_junk_hauler(coi="2026-06-15")
    order = new_vendor_assignment(
        world["engagement_id"], world["vendor"]["id"], "HAUL_AWAY", "2026-06-15", 45000
    )
    accept_vendor_assignment(order["id"], world["vendor"]["id"])

    scheduled = validate_success(api_client.schedule_vendor_assignment(order["id"], MOVE_MANAGER))
    assert scheduled["status"] == "SCHEDULED"
    assert_money(scheduled["holdback_cents"], 4500, "holdback_cents")
    assert read_vendor(world["vendor"]["id"])["blocked_assignment_count"] == 0


def test_a_certificate_expiring_the_day_before_the_service_date_is_refused():
    """PRD §3.8: "The certificate check compares two calendar dates, not instants:
    the vendor's `coi_expires_on` must not be earlier than the assignment's
    `service_date`, so a certificate expiring exactly *on* the service date is still
    valid, and a failure reports `ERR_VENDOR_COI_EXPIRED`."

    Design: Corner/validations/coi_expiring_one_day_before_the_service_date_is_refused
    """
    world = _engagement_with_a_junk_hauler(coi="2026-06-14")
    order = new_vendor_assignment(
        world["engagement_id"], world["vendor"]["id"], "HAUL_AWAY", "2026-06-15", 45000
    )
    accept_vendor_assignment(order["id"], world["vendor"]["id"])

    validate_error(
        api_client.schedule_vendor_assignment(order["id"], MOVE_MANAGER),
        ApiErrorId.ERR_VENDOR_COI_EXPIRED.value,
    )
    assert read_vendor_assignment(order["id"])["status"] == "ACCEPTED"

    validate_success(
        api_client.renew_vendor_coi(
            world["vendor"]["id"], {"coi_expires_on": "2026-06-15"}, PLATFORM_ADMIN
        )
    )
    validate_success(api_client.schedule_vendor_assignment(order["id"], MOVE_MANAGER))
    assert read_vendor_assignment(order["id"])["status"] == "SCHEDULED"
    assert read_vendor(world["vendor"]["id"])["coi_renewal_count"] == 1


def _checked_in_lead():
    world = setup_move_day_plan_confirmed()
    freeze_and_start(world)
    check_in(world["lead_assignment"]["id"], MOVE_START)
    return world


def test_a_one_minute_entry_is_a_valid_range_that_rounds_down_to_zero():
    """PRD §3.7: "Each entry carries a `raw_hours`, the exact interval length in
    hours held to four decimal places by truncation, and a `rounded_hours`, that raw
    figure divided by a quarter-hour increment, rounded half-up to a whole number of
    increments and multiplied back, giving a value at two decimal places."
    PRD §2.8: "Hours are carried to two decimal places except for the raw length of a
    single time interval, which is held to four decimal places and truncated rather
    than rounded."

    Design: Corner/validations/time_entry_of_one_minute_is_a_valid_range_that_rounds_to_zero
    """
    world = _checked_in_lead()
    lead = world["lead_assignment"]["id"]
    entry = validate_success(
        api_client.create_time_entry(
            {
                "crew_assignment_id": lead,
                "entry_kind": "TRAVEL",
                "started_at_utc": "2026-06-15T14:00:00.000Z",
                "ended_at_utc": "2026-06-15T14:01:00.000Z",
            },
            MOVE_MANAGER,
        ),
        expected_status=201,
    )
    stored = read_time_entry(entry["id"])
    assert round(stored["raw_hours"], 4) == 0.0166, (
        f"raw_hours must truncate to four decimals, got {stored['raw_hours']}"
    )
    assert_two_dp(stored["rounded_hours"], 0.00, "rounded_hours")
    assert stored["voided"] is False


def test_an_entry_whose_end_equals_its_start_sits_outside_the_time_range_rung():
    """PRD §3.7: "Each names its `crew_assignment_id`, an `entry_kind` of `LABOR`,
    `TRAVEL` or `BREAK`, a `started_at_utc` and an `ended_at_utc` that must be
    strictly after it."
    PRD §2.7: "`ended_at_utc` is strictly after `started_at_utc` on a time entry, and
    the check-out `at_utc` is strictly after `checked_in_at_utc`. Otherwise
    `ERR_INVALID_TIME_RANGE`, HTTP 422."

    Design: Corner/validations/time_entry_with_equal_start_and_end_is_an_invalid_range
    """
    world = _checked_in_lead()
    lead = world["lead_assignment"]["id"]
    validate_error(
        api_client.create_time_entry(
            {
                "crew_assignment_id": lead,
                "entry_kind": "LABOR",
                "started_at_utc": "2026-06-15T14:00:00.000Z",
                "ended_at_utc": "2026-06-15T14:00:00.000Z",
            },
            MOVE_MANAGER,
        ),
        ApiErrorId.ERR_INVALID_TIME_RANGE.value,
    )
    _, meta = validate_paginated(
        api_client.list_time_entries(MOVE_MANAGER, params={"crew_assignment_id": lead})
    )
    assert meta["total_count"] == 0
    assert_hours(read_crew_assignment(lead)["billing_hours"], 0.00, "billing_hours")
