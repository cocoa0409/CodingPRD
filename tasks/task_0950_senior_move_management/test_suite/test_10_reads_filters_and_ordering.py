"""List ordering, filtering, pagination windows, the computed summary read and
the ops-run report."""

from test_helpers import (
    ApiErrorId,
    BILLING_ADMIN,
    MOVE_MANAGER,
    PACKAGE_BASE_CENTS,
    PLATFORM_ADMIN,
    api_client,
    append_manual_line,
    assert_money,
    assert_two_dp,
    designate,
    heuristic_volume_cft,
    invoice_of,
    long_carry_surcharge_cents,
    make_family_member_headers,
    milestone_by_key,
    new_client,
    new_engagement,
    new_family_hold,
    new_item,
    read_engagement,
    read_item,
    read_milestone,
    read_summary,
    set_clock,
    setup_engagement,
    stairs_surcharge_cents,
    travel_surcharge_cents,
    validate_error,
    validate_paginated,
    validate_success,
)

MISSING_ENGAGEMENT = "00000000-0000-4000-8000-000000000001"
MISSING_VENDOR = "00000000-0000-4000-8000-000000000002"
MISSING_ITEM = "00000000-0000-4000-8000-000000000003"


def test_an_unknown_status_filter_returns_an_empty_page_not_an_enum_error():
    """PRD §2.7: "Every enum-typed input field carries a declared member of that
    enum. This applies to `billing_mode`, `home_tier`, `package_tier`, `party_type`,
    `authority_scope`, `unit_type`, `room_type`, `category`, `appraisal_source`,
    `disposition`, `target_handling_state`, `entry_kind`, `crew_role`, `vendor_type`,
    `service_kind`, `line_type`, `priority`, `severity`, `resolution` and
    `milestone_key`, and to no other field. Otherwise `ERR_INVALID_ENUM`, HTTP 400.
    No other field routes to this error."
    PRD §3.1: "Engagements can be listed and filtered by `client_id`, by `status` and
    by `phase`."

    Design: Corner/endpoints/off_enum_status_filter_returns_an_empty_page_not_an_enum_error
    """
    world = setup_engagement(with_client_party=False)

    rows, meta = validate_paginated(
        api_client.list_engagements(MOVE_MANAGER, params={"status": "ARCHIVED"})
    )
    assert meta["total_count"] == 0
    assert meta["has_more"] is False

    rows, meta = validate_paginated(
        api_client.list_engagements(MOVE_MANAGER, params={"status": "ACTIVE"})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == world["engagement_id"]

    _, meta = validate_paginated(
        api_client.list_engagements(MOVE_MANAGER, params={"client_id": world["client"]["id"]})
    )
    assert meta["total_count"] == 1


def test_milestones_order_by_sequence_index_while_ledger_lines_order_by_created_at():
    """PRD §2.3: "The default ordering for every list endpoint is `created_at`
    ascending, with one deliberate exception: the milestone list is ordered by
    `sequence_index` ascending, so the first element of the returned array is the
    `ASSESSMENT` milestone and the sixth is `CLOSE_OUT`."

    Design: Corner/endpoints/milestone_list_orders_by_sequence_index_while_invoice_lines_order_by_created_at
    """
    set_clock("2026-05-02T09:00:00.000Z")
    client = new_client(email=None)
    engagement = new_engagement(
        client["id"], billing_mode="PACKAGE", package_tier="STUDIO", home_tier="STUDIO"
    )
    invoice = invoice_of(engagement["id"])
    append_manual_line(invoice["id"], 1000, "adjustment one")
    append_manual_line(invoice["id"], 2000, "adjustment two")

    rows, meta = validate_paginated(
        api_client.list_milestones(MOVE_MANAGER, params={"engagement_id": engagement["id"]})
    )
    assert meta["total_count"] == 6
    assert rows[0]["milestone_key"] == "ASSESSMENT"
    assert rows[0]["sequence_index"] == 1
    assert rows[5]["milestone_key"] == "CLOSE_OUT"
    assert rows[5]["sequence_index"] == 6

    lines, line_meta = validate_paginated(
        api_client.list_invoice_lines(BILLING_ADMIN, params={"invoice_id": invoice["id"]})
    )
    assert line_meta["total_count"] == 3
    assert lines[0]["line_type"] == "PACKAGE_BASE"
    assert_money(lines[0]["amount_cents"], PACKAGE_BASE_CENTS["STUDIO"], "base line")
    assert lines[1]["memo"] == "adjustment one"
    assert lines[2]["memo"] == "adjustment two"
    assert_money(
        validate_success(api_client.get_invoice(invoice["id"], BILLING_ADMIN))["subtotal_cents"],
        PACKAGE_BASE_CENTS["STUDIO"] + 3000,
        "subtotal_cents",
    )


def test_body_foreign_keys_are_resolved_in_the_declared_rung_order():
    """PRD §2.12: "Path parameters are resolved strictly left to right. For a nested
    path, the outer id is resolved and its 404 returned before the inner id is
    examined, and only once every path id resolves are body foreign keys checked in
    the rung order of gate 2."
    PRD §2.6: "2. **Path and foreign-key existence.** Every id in the path resolves,
    validated left to right, and then every foreign key in the body resolves, in the
    declared rung order. Ladder rungs 8 through 21."

    Design: Corner/endpoints/body_foreign_keys_are_checked_in_declared_rung_order_engagement_before_vendor
    """
    set_clock("2026-05-02T09:00:00.000Z")
    validate_error(
        api_client.create_consignment_lot(
            {
                "engagement_id": MISSING_ENGAGEMENT,
                "vendor_id": MISSING_VENDOR,
                "list_price_cents": 50000,
                "listed_on": "2026-05-02",
                "item_ids": [MISSING_ITEM],
            },
            MOVE_MANAGER,
        ),
        ApiErrorId.ERR_ENGAGEMENT_NOT_FOUND.value,
    )
    _, meta = validate_paginated(api_client.list_consignment_lots(MOVE_MANAGER))
    assert meta["total_count"] == 0


def test_family_hold_filters_separate_the_open_row_from_the_withdrawn_one():
    """PRD §3.5: "Holds can be listed and filtered by `inventory_item_id`, by
    `raised_by_party_id`, by `resolved_by_party_id` and by `status`."
    PRD §3.5: "Withdrawal is the raiser's own exit, available only from `OPEN`, open
    to the move manager and to a family member, and when the actor is a family member
    the `X-User-ID` must equal the hold's `raised_by_party_id`; it recomputes
    `hold_state` to `NONE` when no other hold on the item remains `OPEN` or `ESCALATED`."

    Design: Corner/endpoints/family_hold_list_filter_by_status_separates_open_from_withdrawn
    """
    world = setup_engagement(with_client_party=False, with_family_party=True)
    eng_id = world["engagement_id"]
    party_id = world["family_party"]["id"]
    headers = make_family_member_headers(party_id)
    first = new_item(eng_id, label="Walnut sideboard", footprint_linear_inches=60, volume_cft=45)
    second = new_item(eng_id, label="Wing chair", footprint_linear_inches=30, volume_cft=20)
    open_hold = new_family_hold(
        first["id"], party_id, headers=headers, reason="Grandchild wants the sideboard"
    )
    withdrawn_hold = new_family_hold(
        second["id"], party_id, headers=headers, reason="Second thoughts on the chair"
    )
    validate_success(api_client.withdraw_family_hold(withdrawn_hold["id"], headers))

    _, meta = validate_paginated(
        api_client.list_family_holds(MOVE_MANAGER, params={"raised_by_party_id": party_id})
    )
    assert meta["total_count"] == 2

    rows, meta = validate_paginated(
        api_client.list_family_holds(
            MOVE_MANAGER, params={"raised_by_party_id": party_id, "status": "OPEN"}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == open_hold["id"]

    rows, meta = validate_paginated(
        api_client.list_family_holds(
            MOVE_MANAGER, params={"raised_by_party_id": party_id, "status": "WITHDRAWN"}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == withdrawn_hold["id"]
    assert rows[0]["raised_by_party_id"] == party_id
    assert read_item(first["id"])["hold_state"] == "HELD"
    assert read_item(second["id"])["hold_state"] == "NONE"


def test_the_summary_reports_projections_the_plain_engagement_read_does_not():
    """PRD §3.1: "A computed summary read is offered alongside the plain engagement
    read. It reports `engagement_id`, the derived `phase`, the `billing_mode`,
    `accrued_labor_cents`, `billing_hours_total`, a `volume_estimate_variant` and its
    `volume_estimate_cft`, a `projected_total_cents`, an `open_hold_count`, a
    `progress_pct` and a `next_unpack_session_id`."
    PRD §3.1: "`open_hold_count` counts the family holds in status `OPEN` or `ESCALATED`."

    Design: Corner/endpoints/summary_projection_carries_fields_the_plain_engagement_read_does_not
    """
    world = setup_engagement(
        with_client_party=False,
        with_family_party=True,
        mileage_miles=15,
        origin_stairs_flights=1,
        origin_long_carry_feet=75,
    )
    eng_id = world["engagement_id"]
    item = new_item(eng_id, label="Walnut sideboard", footprint_linear_inches=60, volume_cft=45)
    new_family_hold(
        item["id"],
        world["family_party"]["id"],
        headers=make_family_member_headers(world["family_party"]["id"]),
        reason="Grandchild wants the sideboard",
    )

    engagement = validate_success(api_client.get_engagement(eng_id, MOVE_MANAGER))
    assert engagement["status"] == "ACTIVE"
    assert engagement["phase"] == "ASSESSMENT"
    assert_money(engagement["accrued_labor_cents"], 0, "accrued_labor_cents")
    assert_two_dp(engagement["total_inventory_volume_cft"], 45.00, "total_inventory_volume_cft")

    summary = read_summary(eng_id)
    assert summary["engagement_id"] == eng_id
    assert summary["open_hold_count"] == 1
    assert summary["next_unpack_session_id"] is None
    assert_two_dp(summary["volume_estimate_cft"], 45.00, "volume_estimate_cft")
    assert_money(summary["projected_total_cents"], 0, "projected_total_cents")


def test_the_ops_run_report_counts_its_three_sweeps_and_advances_the_sequence():
    """PRD §3.10: "Each run raises the engagement's `ops_run_seq` by one — a monotone
    counter that never decreases — and raises the engagement's `version` by one."
    PRD §3.10: "It answers with the `engagement_id`, a `milestones_flagged_overdue`
    count, an `authorities_expired` count, a `vendor_assignments_blocked` count and
    the new `ops_run_seq`."

    Design: Corner/endpoints/ops_run_reports_its_counters_and_advances_the_ops_run_sequence
    """
    world = setup_engagement(with_client_party=False)
    eng_id = world["engagement_id"]
    assessment_id = milestone_by_key(eng_id, "ASSESSMENT")["id"]
    sort_plan_id = milestone_by_key(eng_id, "SORT_PLAN")["id"]
    set_clock("2026-05-12T09:00:00.000Z")

    first = validate_success(api_client.ops_run(eng_id, MOVE_MANAGER))
    assert first["milestones_flagged_overdue"] == 1
    assert first["authorities_expired"] == 0
    assert first["vendor_assignments_blocked"] == 0
    assert first["ops_run_seq"] == 1
    assert first["engagement_id"] == eng_id

    second = validate_success(api_client.ops_run(eng_id, PLATFORM_ADMIN))
    assert second["ops_run_seq"] == 2

    assert read_milestone(assessment_id)["overdue_status"] == "OVERDUE"
    assert read_milestone(sort_plan_id)["overdue_status"] == "ON_TIME"


def test_inventory_pagination_walks_the_created_at_order_page_by_page():
    """PRD §2.3: "For list responses the `meta` object carries `limit`, `offset`,
    `total_count` and `has_more`. `total_count` is the number of records matching the
    supplied filters before the window is applied, and `has_more` is true when
    records remain beyond the current window."
    PRD §2.3: "The default ordering for every list endpoint is `created_at`
    ascending, with one deliberate exception: the milestone list is ordered by
    `sequence_index` ascending, so the first element of the returned array is the
    `ASSESSMENT` milestone and the sixth is `CLOSE_OUT`."

    Design: Corner/endpoints/inventory_item_pagination_offset_and_has_more_walk_the_created_at_order
    """
    world = setup_engagement(with_client_party=False)
    eng_id = world["engagement_id"]
    first = new_item(eng_id, label="Item one", footprint_linear_inches=20, volume_cft=10)
    second = new_item(eng_id, label="Item two", category="LINENS", footprint_linear_inches=12, volume_cft=6)
    third = new_item(eng_id, label="Item three", category="MISC", footprint_linear_inches=8, volume_cft=4)

    rows, meta = validate_paginated(
        api_client.list_inventory_items(
            MOVE_MANAGER, params={"engagement_id": eng_id, "limit": 2, "offset": 0}
        )
    )
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert [row["id"] for row in rows] == [first["id"], second["id"]]

    rows, meta = validate_paginated(
        api_client.list_inventory_items(
            MOVE_MANAGER, params={"engagement_id": eng_id, "limit": 2, "offset": 2}
        )
    )
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert [row["id"] for row in rows] == [third["id"]]

    engagement = read_engagement(eng_id)
    assert engagement["inventory_item_count"] == 3
    assert_two_dp(engagement["total_inventory_volume_cft"], 20.00, "total_inventory_volume_cft")
