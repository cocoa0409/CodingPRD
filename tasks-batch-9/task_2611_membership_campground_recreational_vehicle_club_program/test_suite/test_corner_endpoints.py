"""Endpoint contracts: bulk runs, conditional actions, computed reads and filters."""

from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    OFFICER,
    assert_entitlement_counters,
    assert_membership_axes,
    assert_ordered_by_created_at,
    assert_pool_split,
    completed_stay,
    create_affiliate_agreement,
    create_open_park,
    create_park,
    create_president_tier,
    find_by_id,
    list_invoices,
    make_agreement_status_change_payload,
    make_park_payload,
    make_payment_payload,
    open_park,
    propose_project,
    read_agreement,
    read_invoice,
    read_membership,
    read_park,
    reset_clock,
    run_annual_dues,
    sell_membership_to_new_member,
    set_clock,
    suspend_membership,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_annual_dues_run_bills_only_the_rolled_over_membership(api):
    """One of two contracts has rolled its entitlement year; the other is skipped, not failed.

    PRD §3.7: "Alongside issuing the invoice the run rolls `entitlement_year_start`
    forward by the entitlement-year length of 365 days, resets
    `nights_used_class_a`, `nights_used_class_b`, `nights_used_class_c` and
    `annual_nights_used` all to 0, recomputes `dues_balance_cents` and
    `tenure_years`, and increments each invoiced membership's `version` by 1."

    Design: Corner/endpoints/annual_dues_run_bills_and_resets_only_the_memberships_whose_year_rolled_over
    """
    reset_clock(api)
    tier = create_president_tier(api)
    park = create_open_park(
        api,
        name="Elk Meadow RV Resort",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
    )
    older = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Dana Whitlock", "email": "dana.whitlock@example.com"},
        upfront_paid_cents=1850000,
    )
    completed_stay(
        api,
        older["headers"],
        park["id"],
        older["membership_id"],
        "2026-08-05",
        "2026-08-08",
    )
    assert_entitlement_counters(
        read_membership(api, older["membership_id"]), class_b=3, annual=3
    )

    set_clock(api, "2027-06-01")
    younger = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Sergio Alvarado", "email": "sergio.alvarado@example.com"},
        upfront_paid_cents=1850000,
    )
    assert read_invoice(api, younger["invoice_id"])["due_date"] == "2027-07-01"
    before_version = read_membership(api, older["membership_id"])["version"]

    result = run_annual_dues(api, 2027, at_instant="2027-08-05")

    assert result["cycle_year"] == 2027
    assert result["invoices_issued"] == 1, "only the rolled-over membership was eligible"
    assert result["total_billed_cents"] == 59508

    billed = read_membership(api, older["membership_id"])
    assert billed["entitlement_year_start"] == "2027-08-01", (
        "the year rolls forward by 365 days, not to the run date of 2027-08-05"
    )
    assert_entitlement_counters(billed, class_a=0, class_b=0, class_c=0, annual=0)
    assert billed["tenure_years"] == 1
    assert billed["version"] > before_version
    assert billed["dues_balance_cents"] == 119016, "the unpaid 2026 invoice plus the new one"

    new_invoices = list_invoices(api, older["membership_id"], {"cycle_year": 2027})
    assert len(new_invoices) == 1
    fresh = new_invoices[0]
    assert fresh["amount_cents"] == 59508
    assert fresh["loyalty_credit_cents"] == 3132, "one year of tenure is below the five-year band"
    assert fresh["due_date"] == "2027-09-04", "the run date plus the 30-day net term"

    skipped_invoices = list_invoices(api, younger["membership_id"])
    assert len(skipped_invoices) == 1, "the skipped membership was issued no second invoice"
    assert skipped_invoices[0]["due_date"] == "2027-07-01"
    skipped = read_membership(api, younger["membership_id"])
    assert skipped["entitlement_year_start"] == "2027-06-01"
    assert skipped["dues_balance_cents"] == 59508


def test_reinstatement_needs_both_a_clear_balance_and_the_exact_fee(api):
    """Each half of the condition is probed alone and only the pair lifts the suspension.

    PRD §3.7: "A `ClubAdmin` supplies `reinstatement_fee_paid_cents`, and three
    things must all hold: `membership_status` must be `SUSPENDED`, `dues_status`
    must be back at `CURRENT`, and `dues_balance_cents` must be exactly 0 with the
    tendered fee at least the reinstatement fee of 15,000 cents, which is one
    hundred and fifty dollars."

    Design: Corner/endpoints/reinstatement_is_allowed_only_after_the_balance_clears_and_the_exact_fee_arrives
    """
    reset_clock(api)
    tier = create_president_tier(api)
    holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Dana Whitlock", "email": "dana.whitlock@example.com"},
        upfront_paid_cents=1850000,
    )
    suspended = suspend_membership(api, holder["membership_id"], "ADMIN_ACTION")
    assert_membership_axes(suspended, "SUSPENDED", "CURRENT", suspension_reason="ADMIN_ACTION")
    assert suspended["dues_balance_cents"] == 59508

    validate_error(
        api.reinstate_membership(
            holder["membership_id"], {"reinstatement_fee_paid_cents": 15000}, ADMIN
        ),
        "ERR_REINSTATEMENT_FEE_REQUIRED",
        422,
    )
    assert read_membership(api, holder["membership_id"])["membership_status"] == "SUSPENDED"

    paid = validate_success(
        api.pay_dues_invoice(holder["invoice_id"], make_payment_payload(59508), ADMIN), 200
    )
    assert paid["status"] == "PAID"
    settled = read_membership(api, holder["membership_id"])
    assert settled["dues_balance_cents"] == 0
    assert_membership_axes(settled, "SUSPENDED", "CURRENT")

    validate_error(
        api.reinstate_membership(
            holder["membership_id"], {"reinstatement_fee_paid_cents": 10000}, ADMIN
        ),
        "ERR_REINSTATEMENT_FEE_REQUIRED",
        422,
    )
    assert read_membership(api, holder["membership_id"])["membership_status"] == "SUSPENDED"

    lifted = validate_success(
        api.reinstate_membership(
            holder["membership_id"], {"reinstatement_fee_paid_cents": 15000}, ADMIN
        ),
        200,
    )
    assert_membership_axes(lifted, "ACTIVE", "CURRENT", suspension_reason=None)
    assert lifted["version"] > settled["version"]


def test_the_capital_project_list_returns_scores_the_inspection_recomputed(api):
    """A failing inspection re-derives every listed score before the read is served.

    PRD §3.9: "Filing an inspection also sets the park's `last_inspection_at` to
    that `inspected_at`, recomputes `priority_score` for every capital project at
    the park, and increments the park's `version` by 1."

    Design: Corner/endpoints/park_capital_project_read_returns_the_scores_the_latest_inspection_recomputed
    """
    reset_clock(api)
    park = create_open_park(
        api,
        name="Elk Meadow RV Resort",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
    )
    utility = propose_project(
        api,
        park["id"],
        ADMIN,
        title="Rebuild the water main",
        category="UTILITY",
        requested_cost_cents=4500000,
        fiscal_year=2026,
    )
    safety = propose_project(
        api,
        park["id"],
        ADMIN,
        title="Replace the fire suppression loop",
        category="SAFETY",
        requested_cost_cents=12000000,
        fiscal_year=2026,
    )
    amenity = propose_project(
        api,
        park["id"],
        ADMIN,
        title="Refit the clubhouse lounge",
        category="AMENITY",
        requested_cost_cents=1000000,
        fiscal_year=2027,
    )
    assert utility["priority_score"] == 3600
    assert safety["priority_score"] == 3500
    assert amenity["priority_score"] == 3000

    inspection = validate_success(
        api.file_amenity_inspection(
            park["id"],
            {"restroom_score": 2, "hookup_score": 2, "utility_score": 2, "road_score": 2},
            OFFICER,
        ),
        201,
    )
    assert inspection["composite_score"] == 2.00
    assert inspection["result"] == "FAIL"
    assert read_park(api, park["id"])["amenity_compliance_status"] == "NON_COMPLIANT"

    rows, meta = validate_paginated(api.list_park_capital_projects(park["id"], ADMIN))
    assert meta["total_count"] == 3
    assert_ordered_by_created_at(rows)
    # Each score is its proposal-time figure times the 1.30 non-compliant factor.
    assert find_by_id(rows, utility["id"])["priority_score"] == 4680
    assert find_by_id(rows, safety["id"])["priority_score"] == 4550
    assert find_by_id(rows, amenity["id"])["priority_score"] == 3900

    fy_rows, fy_meta = validate_paginated(
        api.list_park_capital_projects(park["id"], ADMIN, {"fiscal_year": 2026})
    )
    assert fy_meta["total_count"] == 2
    assert {row["id"] for row in fy_rows} == {utility["id"], safety["id"]}

    approved_rows, approved_meta = validate_paginated(
        api.list_park_capital_projects(park["id"], ADMIN, {"status": "APPROVED"})
    )
    assert approved_rows == [], "all three projects are still PROPOSED"
    assert approved_meta["total_count"] == 0


def test_park_creation_links_an_existing_agreement_or_refuses_the_link(api):
    """The optional foreign key is the only difference across three creations.

    PRD §3.2: "Optionally the creating `ClubAdmin` supplies an
    `affiliate_agreement_id`; when present the park belongs to a partner
    campground system and its computed `network_type` reads `AFFILIATE`, and when
    null the park is club-owned and `network_type` reads `CLUB_OWNED`."

    Design: Corner/endpoints/park_creation_links_to_an_existing_affiliate_agreement_or_refuses_the_link
    """
    reset_clock(api)
    agreement = create_affiliate_agreement(api, partner_name="Timberline Partner Network")
    assert agreement["status"] == "DRAFT", "park creation does not require an ACTIVE agreement"

    linked = validate_success(
        api.create_park(
            make_park_payload(
                name="Timberline Ridge Partner Park",
                park_class="CLASS_C",
                total_sites=30,
                member_allocation_pct=50,
                affiliate_agreement_id=agreement["id"],
            ),
            ADMIN,
        ),
        201,
    )
    assert linked["network_type"] == "AFFILIATE"
    assert linked["affiliate_agreement_id"] == agreement["id"]

    validate_error(
        api.create_park(
            make_park_payload(
                name="Phantom Partner Park",
                park_class="CLASS_C",
                total_sites=30,
                member_allocation_pct=50,
                affiliate_agreement_id=NON_EXISTENT_UUID,
            ),
            ADMIN,
        ),
        "ERR_AFFILIATE_AGREEMENT_NOT_FOUND",
        404,
    )

    club_owned = validate_success(
        api.create_park(
            make_park_payload(
                name="Elk Meadow RV Resort",
                park_class="CLASS_C",
                total_sites=30,
                member_allocation_pct=50,
            ),
            ADMIN,
        ),
        201,
    )
    assert club_owned["network_type"] == "CLUB_OWNED"
    assert club_owned["affiliate_agreement_id"] is None

    rows, meta = validate_paginated(
        api.list_parks(ADMIN, {"affiliate_agreement_id": agreement["id"]})
    )
    assert meta["total_count"] == 1, "the refused creation left no park row behind"
    assert rows[0]["id"] == linked["id"]
    assert rows[0]["network_type"] == "AFFILIATE"

    # floor(30 * 50 / 100) is 15 either way, so the link does not disturb the split.
    assert_pool_split(read_park(api, linked["id"]), member_sites=15, transient_sites=15)
    assert_pool_split(read_park(api, club_owned["id"]), member_sites=15, transient_sites=15)


def test_park_list_filters_compose_with_each_other_and_with_pagination(api):
    """Two filters intersect, and the page window walks only the filtered set.

    PRD §2.3: "Filters supplied on a list endpoint narrow the result set before
    pagination, never after."

    Design: Corner/endpoints/park_listing_filters_compose_with_each_other_and_with_pagination
    """
    reset_clock(api)
    class_b = [
        create_park(
            api, name=name, park_class="CLASS_B", total_sites=sites, member_allocation_pct=60
        )
        for name, sites in (
            ("Elk Meadow RV Resort", 40),
            ("Birch Hollow Campground", 36),
            ("Cedar Bend Retreat", 28),
        )
    ]
    class_c = [
        create_park(
            api, name=name, park_class="CLASS_C", total_sites=sites, member_allocation_pct=50
        )
        for name, sites in (("Pine Crest Campground", 20), ("Willow Flats Park", 18))
    ]
    assert open_park(api, class_b[0]["id"])["park_status"] == "OPEN"
    assert open_park(api, class_c[0]["id"])["park_status"] == "OPEN"

    b_rows, b_meta = validate_paginated(api.list_parks(ADMIN, {"park_class": "CLASS_B"}))
    assert b_meta["total_count"] == 3
    assert b_meta["has_more"] is False
    assert b_meta["limit"] == 10, "the default page size is echoed when none is supplied"
    assert b_meta["offset"] == 0
    assert {row["id"] for row in b_rows} == {row["id"] for row in class_b}
    assert all(row["park_class"] == "CLASS_B" for row in b_rows)

    page_one_rows, page_one_meta = validate_paginated(
        api.list_parks(ADMIN, {"park_class": "CLASS_B", "limit": 2, "offset": 0})
    )
    assert len(page_one_rows) == 2
    assert page_one_meta["total_count"] == 3, "the count is the filtered population, not all five"
    assert page_one_meta["has_more"] is True

    page_two_rows, page_two_meta = validate_paginated(
        api.list_parks(ADMIN, {"park_class": "CLASS_B", "limit": 2, "offset": 2})
    )
    assert len(page_two_rows) == 1
    assert page_two_meta["total_count"] == 3
    assert page_two_meta["has_more"] is False
    walked = [row["id"] for row in page_one_rows] + [row["id"] for row in page_two_rows]
    assert len(set(walked)) == 3, "the two pages repeat and skip nothing"

    open_rows, open_meta = validate_paginated(api.list_parks(ADMIN, {"park_status": "OPEN"}))
    assert open_meta["total_count"] == 2
    assert all(row["park_status"] == "OPEN" for row in open_rows)

    both_rows, both_meta = validate_paginated(
        api.list_parks(ADMIN, {"park_class": "CLASS_C", "park_status": "OPEN"})
    )
    assert both_meta["total_count"] == 1, "the two filters intersect; a union would return four"
    assert both_rows[0]["id"] == class_c[0]["id"]


def test_agreement_status_changes_follow_the_declared_transitions(api):
    """One endpoint drives all four states, and the two illegal moves are 409s.

    PRD §3.4: "Any other requested move — including `DRAFT` directly to
    `SUSPENDED` or `EXPIRED`, `SUSPENDED` to `EXPIRED`, or any move out of
    `EXPIRED` — is refused with `ERR_INVALID_AGREEMENT_STATE`."

    Design: Corner/endpoints/affiliate_agreement_status_changes_follow_the_declared_action_transitions
    """
    reset_clock(api)
    agreement = create_affiliate_agreement(api, partner_name="Timberline Partner Network")
    assert agreement["status"] == "DRAFT"
    assert agreement["nights_consumed_ytd"] == 0
    assert agreement["settlement_owed_cents"] == 0

    validate_error(
        api.change_affiliate_agreement_status(
            agreement["id"], make_agreement_status_change_payload("SUSPENDED"), ADMIN
        ),
        "ERR_INVALID_AGREEMENT_STATE",
        409,
    )
    assert read_agreement(api, agreement["id"])["status"] == "DRAFT"

    for requested in ("ACTIVE", "SUSPENDED", "ACTIVE", "EXPIRED"):
        moved = validate_success(
            api.change_affiliate_agreement_status(
                agreement["id"], make_agreement_status_change_payload(requested), ADMIN
            ),
            200,
        )
        assert moved["status"] == requested

    validate_error(
        api.change_affiliate_agreement_status(
            agreement["id"], make_agreement_status_change_payload("ACTIVE"), ADMIN
        ),
        "ERR_INVALID_AGREEMENT_STATE",
        409,
    )
    terminal = read_agreement(api, agreement["id"])
    assert terminal["status"] == "EXPIRED", "EXPIRED admits no move out"
    assert terminal["nights_consumed_ytd"] == 0
    assert terminal["settlement_owed_cents"] == 0
