"""Collection filters, pagination windows, sub-resource scoping and the
logical clock."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    abort_cycle,
    api_client,
    assert_instant_equals,
    build_cycle_scenario,
    create_chamber,
    create_customer,
    create_cycle,
    create_lot,
    create_permit,
    create_product,
    create_qualified_qualification,
    create_recipe,
    get_lot,
    get_qualification,
    officer,
    operator,
    record_dose_audit,
    remove_load_position,
    report_adverse_event,
    set_clock,
    setup_reference_data,
    setup_released_lot,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["regulatory_admin_headers"]


def test_cycles_list_applies_the_status_filter():
    """PRD 2.3: "The cycle list accepts `chamber_id`, `recipe_id` and
    `status`."
    PRD 3.6: "The cycle itself walks `RUNNING → CANCELLED`, which is terminal
    and which releases both the chamber occupancy and the permit concurrency
    slot for future scheduling."

    Design: Corner/endpoints/corner_cycles_list_filtered_by_status
    """
    env = setup_reference_data(qualify=False)
    cycle_a = create_cycle(env["chamber"]["id"], env["recipe"]["id"], cycle_code="C-A")
    abort_cycle(cycle_a["id"], reason="customer cancelled the booking")
    cycle_b = create_cycle(
        env["chamber"]["id"],
        env["recipe"]["id"],
        cycle_code="C-B",
        scheduled_start_at="2026-08-12T00:00:00Z",
        scheduled_end_at="2026-08-12T06:00:00Z",
    )

    planned, planned_meta = validate_paginated(
        api_client.list_cycles(operator(), params={"status": "PLANNED"})
    )
    by_chamber, chamber_meta = validate_paginated(
        api_client.list_cycles(operator(), params={"chamber_id": env["chamber"]["id"]})
    )

    assert planned_meta["total_count"] == 1
    assert planned[0]["id"] == cycle_b["id"]
    assert chamber_meta["total_count"] == 2
    assert {row["id"] for row in by_chamber} == {cycle_a["id"], cycle_b["id"]}


def test_lot_list_offset_window_pages_without_overlap():
    """PRD 2.3: "`offset` sets how many rows are skipped before the page begins
    and defaults to 0."
    PRD 2.3: "Unless a specific endpoint states otherwise, every list is sorted
    by `created_at` in ascending order, so that a plant record reads
    chronologically."

    Design: Corner/endpoints/corner_lots_list_offset_window_is_stable
    """
    env = setup_reference_data(qualify=False)
    lots = [
        create_lot(env["customer"]["id"], env["product"]["id"], lot_code=f"L-00{i}")
        for i in (1, 2, 3)
    ]

    first, first_meta = validate_paginated(
        api_client.list_lots(
            ADMIN, params={"customer_id": env["customer"]["id"], "limit": 2, "offset": 0}
        )
    )
    second, second_meta = validate_paginated(
        api_client.list_lots(
            ADMIN, params={"customer_id": env["customer"]["id"], "limit": 2, "offset": 2}
        )
    )

    assert first_meta["total_count"] == 3
    assert first_meta["limit"] == 2 and first_meta["offset"] == 0
    assert first_meta["has_more"] is True
    assert len(first) == 2
    assert second_meta["total_count"] == 3
    assert second_meta["offset"] == 2
    assert second_meta["has_more"] is False
    assert len(second) == 1
    ids = [row["id"] for row in first] + [row["id"] for row in second]
    assert len(set(ids)) == 3
    assert set(ids) == {lot["id"] for lot in lots}


def test_qualifications_list_filters_by_recipe_and_by_product():
    """PRD 2.3: "The qualification list accepts `product_id`, `recipe_id` and
    `status`."
    PRD 3.3: "Where the outcome is not `FAIL`, the audit's `next_audit_due_at`
    is `performed_at` advanced by the interval in whole days; where the outcome
    is `FAIL`, `next_audit_due_at` is null."

    Design: Corner/endpoints/corner_qualifications_filtered_by_recipe_id
    """
    env = setup_reference_data(qualify=False)
    recipe_g = env["recipe"]
    recipe_h = create_recipe("GAMMA", recipe_code="RH")
    product_2 = create_product(env["customer"]["id"], product_code="P2")
    q_p1_rg = create_qualified_qualification(env["product"]["id"], recipe_g["id"])
    q_p1_rh = create_qualified_qualification(env["product"]["id"], recipe_h["id"])
    q_p2_rg = create_qualified_qualification(product_2["id"], recipe_g["id"])
    create_qualified_qualification(product_2["id"], recipe_h["id"])

    by_recipe, recipe_meta = validate_paginated(
        api_client.list_qualifications(ADMIN, params={"recipe_id": recipe_g["id"]})
    )
    by_product, product_meta = validate_paginated(
        api_client.list_qualifications(
            ADMIN, params={"product_id": env["product"]["id"], "status": "QUALIFIED"}
        )
    )

    # setup_reference_data(qualify=False) already bound product 1 to recipe_g
    # with a PENDING qualification, so recipe_g carries three rows in total.
    assert recipe_meta["total_count"] == 3
    assert {row["id"] for row in by_recipe} == {
        env["qualification"]["id"],
        q_p1_rg["id"],
        q_p2_rg["id"],
    }
    assert product_meta["total_count"] == 2
    assert {row["id"] for row in by_product} == {q_p1_rg["id"], q_p1_rh["id"]}
    stored = get_qualification(q_p1_rg["id"])
    assert stored["status"] == "QUALIFIED"
    assert_instant_equals(
        stored["next_audit_due_at"], "2026-11-03T00:00:00Z", "next_audit_due_at"
    )


def test_permit_chamber_subresource_returns_only_its_own_chambers():
    """PRD 3.2: "A **Chamber** is commissioned under exactly one permit,
    identified by `permit_id`, and carries a `chamber_code` of 1 to 32
    characters unique across the facility, a `modality` of `ETO`, `GAMMA` or
    `EBEAM`, a `pallet_capacity` of at least one pallet, a `turnaround_minutes`
    value of zero or more expressing the purge and cooldown buffer that must
    follow every dwell, and an `abatement_efficiency_pct` between 0 and 100
    inclusive describing how much of the raw ethylene-oxide charge the
    chamber's abatement train destroys."
    PRD 2.3: "The customer-scoped product list, the permit-scoped chamber list,
    the audit history of a qualification, the aeration records of a lot, the
    adverse events of a lot and the indicators of a load-map slot accept
    pagination only."

    Design: Corner/endpoints/corner_permit_chambers_subresource_returns_only_its_own_chambers
    """
    set_clock("2026-08-10T00:00:00Z")
    permit_a = create_permit(permit_code="AP-2026", permit_year=2026)
    permit_b = create_permit(permit_code="AP-2027", permit_year=2027)
    chamber_a = create_chamber(permit_a["id"], "ETO", chamber_code="CH-E1")
    chamber_b = create_chamber(permit_b["id"], "ETO", chamber_code="CH-E2")

    rows_a, meta_a = validate_paginated(
        api_client.list_permit_chambers(permit_a["id"], ADMIN)
    )
    rows_b, meta_b = validate_paginated(
        api_client.list_permit_chambers(permit_b["id"], ADMIN)
    )

    assert meta_a["total_count"] == 1 and rows_a[0]["id"] == chamber_a["id"]
    assert meta_b["total_count"] == 1 and rows_b[0]["id"] == chamber_b["id"]
    assert rows_b[0]["permit_id"] == permit_b["id"]


def test_dose_audit_history_accumulates_per_qualification():
    """PRD 3.3: "The parent qualification is then updated in lockstep: its
    `audit_interval_days` becomes the selected interval, its `last_audit_at`
    becomes `performed_at`, and its `next_audit_due_at` becomes the audit's."
    PRD 3.3: "Zero positives is a `PASS` and buys an interval of 90 days."

    Design: Corner/endpoints/corner_dose_audit_history_subresource_accumulates
    """
    env = setup_reference_data(qualify=False)
    record_dose_audit(
        env["qualification"]["id"], performed_at="2026-08-05T00:00:00Z", positives=0
    )
    second = record_dose_audit(
        env["qualification"]["id"], performed_at="2026-11-03T00:00:00Z", positives=0
    )

    rows, meta = validate_paginated(
        api_client.list_dose_audits(env["qualification"]["id"], ADMIN)
    )

    assert meta["total_count"] == 2
    assert_instant_equals(
        second["next_audit_due_at"], "2027-02-01T00:00:00Z", "next_audit_due_at"
    )
    qualification = get_qualification(env["qualification"]["id"])
    assert_instant_equals(
        qualification["last_audit_at"], "2026-11-03T00:00:00Z", "last_audit_at"
    )
    assert_instant_equals(
        qualification["next_audit_due_at"], "2027-02-01T00:00:00Z", "next_audit_due_at"
    )
    assert qualification["status"] == "QUALIFIED"
    assert qualification["consecutive_conditional_count"] == 0
    assert len(rows) == 2


def test_lot_adverse_event_subresource_lists_every_report_for_that_lot():
    """PRD 2.6: "Each `AdverseEvent` records `lot_version_after`, a snapshot of
    the subject lot's `version` immediately after the event was persisted, and
    creating the event itself increments the lot's `version` by one."
    PRD 3.9: "The event is created in `status` `REPORTED` with
    `reported_by_user_id` set from the caller's `X-User-ID`, `lot_version_after`
    snapshotting the lot's `version` immediately after the write, and
    `disposition` null."

    Design: Corner/endpoints/corner_lot_adverse_events_subresource_lists_all_reports
    """
    env = setup_released_lot()
    other_lot = create_lot(
        env["customer"]["id"], env["product"]["id"], lot_code="L-002"
    )
    first = report_adverse_event(
        env["lot"]["id"],
        reporter_headers=officer(),
        event_type="STERILITY_COMPLAINT",
        severity="HIGH",
        description="Field sterility complaint on implanted device",
    )
    second = report_adverse_event(
        env["lot"]["id"],
        reporter_headers=officer(),
        event_type="PACKAGING_BREACH",
        severity="LOW",
        description="Outer carton seal breached in transit",
    )

    rows, meta = validate_paginated(
        api_client.list_adverse_events(env["lot"]["id"], officer())
    )
    _, empty_meta = validate_paginated(
        api_client.list_adverse_events(other_lot["id"], officer())
    )

    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], second["id"]}
    assert empty_meta["total_count"] == 0
    assert second["lot_version_after"] == first["lot_version_after"] + 1
    assert first["status"] == "REPORTED"
    assert first["disposition"] is None
    assert get_lot(env["lot"]["id"])["status"] == "RELEASED"


def test_delete_load_position_returns_204_and_is_a_hard_delete():
    """PRD 4: "Removing a load-map slot returns `204 No Content` with no
    response body."
    PRD 3.5: "The row is hard-deleted — there is no soft-delete or tombstone —
    and the same arithmetic runs in reverse: the cycle's `loaded_pallet_count`
    falls by the removed `pallet_count`, `load_density_g_per_cm3` is
    recomputed, the lot's `staged_pallet_count` falls and
    `available_pallet_count` is refreshed, and the lot walks `STAGED →
    RECEIVED` when it retains no load position on any cycle anywhere."
    PRD 2.7: "On a nested path the outer segment is resolved before the inner
    one: deleting a load-map slot resolves the cycle first and only then the
    `position_id` segment, and a slot that exists but belongs to a different
    cycle than the one named in the path is itself reported as
    `ERR_LOAD_POSITION_NOT_FOUND`."

    Design: Corner/endpoints/corner_delete_load_position_returns_204_with_no_body
    """
    env = build_cycle_scenario(stage="loading", place_indicators=False)

    first = remove_load_position(env["cycle"]["id"], env["position"]["id"])
    assert first.status_code == 204
    assert first.text == ""

    repeat = api_client.delete_load_position(
        env["cycle"]["id"], env["position"]["id"], operator()
    )

    validate_error(repeat, ApiErrorId.ERR_LOAD_POSITION_NOT_FOUND)
    _, meta = validate_paginated(
        api_client.list_load_positions(operator(), params={"cycle_id": env["cycle"]["id"]})
    )
    assert meta["total_count"] == 0
    lot = get_lot(env["lot"]["id"])
    assert lot["status"] == "RECEIVED"
    assert lot["staged_pallet_count"] == 0


def test_logical_clock_starts_at_the_declared_instant():
    """PRD 2.4: "The server holds a single logical clock whose startup value is
    exactly `2026-08-01T00:00:00Z`; before any client sets it, every read of
    "now" returns that instant, and the server never falls back to real time."
    PRD 2.4: "A `RegulatoryAdmin` may move the clock through an administrative
    test-driving capability that accepts a single field, `to_iso8601`, carrying
    the instant the clock should read from that point on."
    PRD 2.4: "Alongside it, every resource carries `created_at`, an ISO 8601
    UTC timestamp with three fractional digits recording when the row was
    persisted."

    Design: Corner/endpoints/corner_logical_clock_startup_default_is_2026_08_01
    """
    before = create_customer(account_code="ACME-01")

    assert_instant_equals(before["created_at"], "2026-08-01T00:00:00Z", "created_at")

    validate_success(api_client.set_clock({"to_iso8601": "2026-09-01T12:30:00Z"}, ADMIN))
    after = create_customer(account_code="BETA-02")

    assert_instant_equals(after["created_at"], "2026-09-01T12:30:00Z", "created_at")


def test_customer_product_subresource_is_scoped_to_its_customer():
    """PRD 3.1: "Under a customer sit **Products** — families of finished goods
    that behave identically under sterilization. A product is registered with
    its owning `customer_id`, a `product_code` of 1 to 32 characters that must
    be unique within that customer, and the physical and toxicological
    constants that drive the rest of the system."
    PRD 2.3: "The customer-scoped product list, the permit-scoped chamber list,
    the audit history of a qualification, the aeration records of a lot, the
    adverse events of a lot and the indicators of a load-map slot accept
    pagination only."

    Design: Corner/endpoints/corner_customer_products_subresource_is_scoped
    """
    set_clock("2026-08-10T00:00:00Z")
    customer_a = create_customer(account_code="ACME-01")
    customer_b = create_customer(account_code="BETA-02")
    product_1 = create_product(customer_a["id"], product_code="P1")
    product_2 = create_product(customer_a["id"], product_code="P2")
    product_3 = create_product(customer_b["id"], product_code="P3")

    rows_a, meta_a = validate_paginated(
        api_client.list_customer_products(customer_a["id"], ADMIN)
    )
    rows_b, meta_b = validate_paginated(
        api_client.list_customer_products(customer_b["id"], ADMIN)
    )

    assert meta_a["total_count"] == 2
    assert {row["id"] for row in rows_a} == {product_1["id"], product_2["id"]}
    assert meta_b["total_count"] == 1
    assert rows_b[0]["id"] == product_3["id"]
    assert rows_b[0]["customer_id"] == customer_b["id"]
