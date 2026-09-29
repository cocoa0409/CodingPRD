"""One optional field that splits a resolution into two terminal states, the filter
parameters that are the only way back from a parent to its children, the pagination window
at its edges, and the create bodies that try to set fields the endpoint never declared."""

from test_helpers import (
    ApiErrorId,
    assert_complaint,
    assert_fund,
    assert_hotel,
    assert_hotel_counters_zero,
    assert_ledger_entry,
    assert_member,
    assert_rate_plan_derivation,
    assert_single_row,
    assert_stay,
    collect_all,
    count_entries_of_type,
    entries_of_type,
    factories as fac,
    fixtures as fx,
    is_valid_uuid,
    make_admin_headers,
    make_auditor_headers,
    make_care_agent_headers,
    make_hotel_owner_headers,
    make_member_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

_SMUGGLED_HOTEL_ID = "00000000-0000-4000-8000-0000000000ff"
_UNMATCHED_HOTEL_ID = "00000000-0000-4000-8000-000000000000"


# ----------------------------------------------------------------------
# Scenario builders
# ----------------------------------------------------------------------
def _three_reviewed_complaints_for_one_funded_guest(api):
    """A guest holding twenty thousand settled points and three complaints, each taken
    under review and each awaiting its resolution."""
    member = fx.enroll_member(
        api, email="gw1@example.com", full_name="Lucia Ferrer", enrollment_date="2026-02-11"
    )
    member_id = member["id"]
    purchase = fx.settled_purchase(api, member_id, 20_000, channel="DIRECT_PURCHASE")
    member_headers = make_member_headers(member_id)
    care = make_care_agent_headers("care-gw-01")

    def _file(subject_type, description):
        return validate_success(
            api.create_complaint(
                fac.create_complaint_payload(
                    member_id, subject_type=subject_type, description=description
                ),
                member_headers,
            ),
            201,
        )

    granted = _file(
        "POINT_SHORTFALL",
        "My April stay credited fewer points than the rate card promised.",
    )
    omitted = _file("POINT_SHORTFALL", "My May stay is also short.")
    explicit_zero = _file(
        "BLACKOUT_DISPUTE", "The blackout on my anniversary weekend seems wrong."
    )
    fx.review_complaint(api, granted["id"], headers=care)
    fx.review_complaint(api, omitted["id"], headers=care)
    fx.review_complaint(api, explicit_zero["id"], headers=make_admin_headers())

    return {
        "member": member,
        "member_id": member_id,
        "purchase": purchase,
        "care": care,
        "granted": granted,
        "omitted": omitted,
        "explicit_zero": explicit_zero,
    }


def _linkline_with_one_child_of_every_kind(api):
    """A property with one rate plan and one draft blackout window, and a guest with one
    settled sale and one posted ten-night stay."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Linkline Lodge",
        brand_code="LLL",
        market_tier="SELECT",
        program_fee_pct=0.05,
        rooms_count=70,
        trailing_12m_occupancy_pct=0.68,
        trailing_12m_adr_cents=14_000,
    )
    hotel_id = bundle["hotel"]["id"]
    window = fx.draft_blackout(
        api,
        hotel_id,
        "2026-12-24",
        "2026-12-26",
        scope="STANDARD_ONLY",
        headers=make_hotel_owner_headers(hotel_id),
    )
    member = fx.enroll_member(
        api, email="lk1@example.com", full_name="Peder Lund", enrollment_date="2026-01-19"
    )
    member_id = member["id"]
    purchase = fx.settled_purchase(api, member_id, 20_000, channel="DIRECT_PURCHASE")
    pending = fx.record_purchase(api, member_id, 5_000, channel="DIRECT_PURCHASE")
    stay = fx.posted_stay(
        api,
        hotel_id,
        member_id,
        bundle["rate_plan"]["id"],
        "2026-06-01",
        "2026-06-11",
        100_000,
    )

    bundle["window"] = window
    bundle["member"] = member
    bundle["purchase"] = purchase
    bundle["pending_purchase"] = pending
    bundle["stay"] = stay
    return bundle


def _exactly_three_members(api):
    """Three guests enrolled on three consecutive days and nothing else in the
    programme."""
    first = fx.enroll_member(
        api, email="pg1@example.com", full_name="Aiko Tanaka", enrollment_date="2026-01-05"
    )
    second = fx.enroll_member(
        api, email="pg2@example.com", full_name="Bela Kovacs", enrollment_date="2026-01-06"
    )
    third = fx.enroll_member(
        api,
        email="pg3@example.com",
        full_name="Cato Rasmussen",
        enrollment_date="2026-01-07",
    )
    return {"first": first, "second": second, "third": third}


def _one_member_for_the_smuggled_bodies(api):
    """A single guest, so a stay can be captured against a freshly enrolled property."""
    return fx.enroll_member(
        api, email="ig1@example.com", full_name="Marta Silva", enrollment_date="2026-01-08"
    )


# ----------------------------------------------------------------------
# One optional field, two terminal states.
# ----------------------------------------------------------------------
class TestResolveSplitsIntoGoodwillAndUpheldArmsOnOneOptionalField:
    def test_a_positive_figure_takes_the_goodwill_arm(self, api):
        """Two thousand points asked for is two thousand points granted, and the closing
        narrative is recorded alongside the figure.

        PRD: "When `goodwill_points` is greater than zero the complaint moves
        `UNDER_REVIEW → RESOLVED_GOODWILL`: `resolution` is recorded,
        `goodwill_points_granted` is set to the requested figure, one `GOODWILL` ledger
        entry is written crediting the complaining member with that many points"

        Design: Corner/endpoints/resolve_splits_into_goodwill_and_upheld_arms_on_one_optional_field
        """
        bundle = _three_reviewed_complaints_for_one_funded_guest(api)

        resolved = fx.resolve_complaint(
            api,
            bundle["granted"]["id"],
            resolution="Shortfall confirmed and topped up as a gesture.",
            goodwill_points=2_000,
            headers=bundle["care"],
        )

        assert_complaint(
            resolved,
            status="RESOLVED_GOODWILL",
            goodwill_points_granted=2_000,
            resolution="Shortfall confirmed and topped up as a gesture.",
        )

    def test_omitting_the_field_entirely_takes_the_upheld_arm(self, api):
        """The same endpoint, the same reviewer and the same narrative, with the optional
        figure simply absent from the body.

        PRD: "When `goodwill_points` is omitted or zero the complaint moves
        `UNDER_REVIEW → RESOLVED_UPHELD` instead: `resolution` is recorded,
        `goodwill_points_granted` stays 0, **no** ledger entry is written, the member's
        balance does not move, the fund is not revalued"

        Design: Corner/endpoints/resolve_splits_into_goodwill_and_upheld_arms_on_one_optional_field
        """
        bundle = _three_reviewed_complaints_for_one_funded_guest(api)

        resolved = fx.resolve_complaint(
            api,
            bundle["omitted"]["id"],
            resolution="The rate card was applied correctly.",
            headers=bundle["care"],
        )

        assert_complaint(
            resolved,
            status="RESOLVED_UPHELD",
            goodwill_points_granted=0,
            resolution="The rate card was applied correctly.",
        )

    def test_an_explicit_zero_lands_in_the_same_place_as_an_absent_field(self, api):
        """A body that names the field and sets it to nothing is not a third branch, and
        the administrator closing it out reaches the same terminal state.

        PRD: "A `MemberCareAgent` or an administrator closes the review out with a
        mandatory `resolution` narrative and an optional `goodwill_points` figure, and that
        figure alone decides which of two sibling branches is taken."

        Design: Corner/endpoints/resolve_splits_into_goodwill_and_upheld_arms_on_one_optional_field
        """
        bundle = _three_reviewed_complaints_for_one_funded_guest(api)

        resolved = fx.resolve_complaint(
            api,
            bundle["explicit_zero"]["id"],
            resolution="The blackout window was published in advance.",
            goodwill_points=0,
            headers=make_admin_headers(),
        )

        assert_complaint(
            resolved,
            status="RESOLVED_UPHELD",
            goodwill_points_granted=0,
            subject_type="BLACKOUT_DISPUTE",
        )

    def test_only_the_granting_arm_leaves_a_ledger_entry_behind(self, api):
        """Three resolutions, one of them generous, produce exactly one goodwill credit
        across the whole ledger.

        PRD: "one `GOODWILL` ledger entry is written crediting the complaining member with
        that many points"

        Design: Corner/endpoints/resolve_splits_into_goodwill_and_upheld_arms_on_one_optional_field
        """
        bundle = _three_reviewed_complaints_for_one_funded_guest(api)
        member_id = bundle["member_id"]
        fx.resolve_complaint(
            api, bundle["granted"]["id"], goodwill_points=2_000, headers=bundle["care"]
        )
        fx.resolve_complaint(api, bundle["omitted"]["id"], headers=bundle["care"])
        fx.resolve_complaint(
            api,
            bundle["explicit_zero"]["id"],
            goodwill_points=0,
            headers=make_admin_headers(),
        )

        entries = collect_all(
            api.list_ledger_entries,
            make_auditor_headers("aud-gw-01"),
            member_id=member_id,
        )

        goodwill = entries_of_type(entries, "GOODWILL")
        assert len(goodwill) == 1, (
            f"three resolutions wrote {len(goodwill)} goodwill entries, expected exactly "
            "the one from the granting arm"
        )
        assert_ledger_entry(
            goodwill[0],
            entry_type="GOODWILL",
            points=2_000,
            member_id=member_id,
            liability_unit_cost=600,
        )
        assert count_entries_of_type(entries, "PURCHASE") == 1, (
            "the settled sale should still be the guest's only other entry"
        )

    def test_the_balance_moves_by_the_granted_figure_and_no_further(self, api):
        """Twenty thousand bought plus two thousand granted is twenty-two thousand, and the
        two upheld arms add nothing.

        PRD: "the member's `point_balance` and `lifetime_points_earned` are recomputed, and
        the fund's `outstanding_points`, `point_liability_cents`, `solvency_ratio` and
        `status` are recomputed."

        Design: Corner/endpoints/resolve_splits_into_goodwill_and_upheld_arms_on_one_optional_field
        """
        bundle = _three_reviewed_complaints_for_one_funded_guest(api)
        member_id = bundle["member_id"]
        fx.resolve_complaint(
            api, bundle["granted"]["id"], goodwill_points=2_000, headers=bundle["care"]
        )
        fx.resolve_complaint(api, bundle["omitted"]["id"], headers=bundle["care"])
        fx.resolve_complaint(
            api,
            bundle["explicit_zero"]["id"],
            goodwill_points=0,
            headers=make_admin_headers(),
        )

        assert_member(fx.read_member(api, member_id), point_balance=22_000)

    def test_the_fund_carries_the_grant_and_nothing_from_the_upheld_arms(self, api):
        """Twenty-two thousand outstanding points at 600 cents a thousand, less the default
        one-fifth breakage, is 10,560 cents of liability.

        PRD: "The `point_liability_cents` is that outstanding total, valued at 600 cents
        per thousand points, multiplied by one minus `breakage_rate_pct`, rounded half up
        to whole cents."

        Design: Corner/endpoints/resolve_splits_into_goodwill_and_upheld_arms_on_one_optional_field
        """
        bundle = _three_reviewed_complaints_for_one_funded_guest(api)
        fx.resolve_complaint(
            api, bundle["granted"]["id"], goodwill_points=2_000, headers=bundle["care"]
        )
        fx.resolve_complaint(api, bundle["omitted"]["id"], headers=bundle["care"])
        fx.resolve_complaint(
            api,
            bundle["explicit_zero"]["id"],
            goodwill_points=0,
            headers=make_admin_headers(),
        )

        assert_fund(
            fx.read_fund(api), outstanding_points=22_000, liability_cents=10_560
        )


# ----------------------------------------------------------------------
# Children are reachable only by filtering the collection.
# ----------------------------------------------------------------------
class TestFilteredListsAreTheOnlyReversePathFromParentToChildren:
    def test_a_propertys_rate_plans_are_found_by_filtering_the_rate_plan_collection(
        self, api
    ):
        """The property row carries no array of rate plans, so the way back down is the
        collection filtered on the parent's identifier.

        PRD: "Rate plans filter on `hotel_id` and `rate_category`. Award price windows
        filter on `hotel_id` and `season`."

        Design: Corner/endpoints/filtered_lists_are_the_only_reverse_path_from_parent_to_children
        """
        bundle = _linkline_with_one_child_of_every_kind(api)
        hotel_id = bundle["hotel"]["id"]

        rows, meta = validate_paginated(
            api.list_rate_plans(make_admin_headers(), params={"hotel_id": hotel_id})
        )

        assert meta["total_count"] == 1, (
            f"the property has one rate plan, the filtered list counted {meta['total_count']}"
        )
        assert_single_row(rows, bundle["rate_plan"]["id"])
        assert rows[0]["hotel_id"] == hotel_id, (
            "the returned plan should name the property that was filtered on"
        )

    def test_a_rate_plans_stays_are_found_by_filtering_the_stay_collection(self, api):
        """The rate plan is the third parent of a stay, and it is filterable in its own
        right rather than only through the property.

        PRD: "Paid stays filter on `member_id`, `hotel_id`, `rate_plan_id` and `status`."

        Design: Corner/endpoints/filtered_lists_are_the_only_reverse_path_from_parent_to_children
        """
        bundle = _linkline_with_one_child_of_every_kind(api)

        rows, meta = validate_paginated(
            api.list_stays(
                make_admin_headers(),
                params={"rate_plan_id": bundle["rate_plan"]["id"]},
            )
        )

        assert meta["total_count"] == 1, (
            f"one stay was captured on that plan, the list counted {meta['total_count']}"
        )
        assert_single_row(rows, bundle["stay"]["id"])
        assert_stay(rows[0], status="POSTED_QUALIFYING", nights=10)

    def test_a_purchases_ledger_entry_is_found_by_filtering_on_the_source(self, api):
        """The purchase does not publish the entry it caused; the entry is found by asking
        the ledger which rows name that purchase as their source.

        PRD: "Point ledger entries filter on `member_id`, `source_stay_id`,
        `source_redemption_id`, `source_purchase_id`, `reversal_of_entry_id` and
        `entry_type`."

        Design: Corner/endpoints/filtered_lists_are_the_only_reverse_path_from_parent_to_children
        """
        bundle = _linkline_with_one_child_of_every_kind(api)
        purchase_id = bundle["purchase"]["id"]

        rows, meta = validate_paginated(
            api.list_ledger_entries(
                make_auditor_headers("aud-lk-01"),
                params={"source_purchase_id": purchase_id},
            )
        )

        assert meta["total_count"] == 1, (
            f"a settled direct sale writes one entry, the list counted {meta['total_count']}"
        )
        assert_ledger_entry(
            rows[0],
            entry_type="PURCHASE",
            points=20_000,
            member_id=bundle["member"]["id"],
            source_purchase_id=purchase_id,
        )

    def test_two_filters_on_one_collection_narrow_together_rather_than_either_or(
        self, api
    ):
        """The guest holds a settled sale and a pending one, and asking for the guest and
        the settled status returns only the row that satisfies both.

        PRD: "Point purchases filter on `member_id`, `partner_id`, `channel` and `status`."

        Design: Corner/endpoints/filtered_lists_are_the_only_reverse_path_from_parent_to_children
        """
        bundle = _linkline_with_one_child_of_every_kind(api)
        member_id = bundle["member"]["id"]
        headers = make_admin_headers()

        both, both_meta = validate_paginated(
            api.list_point_purchases(headers, params={"member_id": member_id})
        )
        settled, settled_meta = validate_paginated(
            api.list_point_purchases(
                headers, params={"member_id": member_id, "status": "SETTLED"}
            )
        )

        assert both_meta["total_count"] == 2, (
            f"the guest bought twice, the unfiltered-by-status list counted "
            f"{both_meta['total_count']}"
        )
        assert len(both) == 2, "both purchases should be on the first page"
        assert settled_meta["total_count"] == 1, (
            "adding the status filter should intersect rather than union, expected 1, got "
            f"{settled_meta['total_count']}"
        )
        assert_single_row(settled, bundle["purchase"]["id"])

    def test_a_propertys_draft_blackouts_are_found_by_the_pair_of_filters(self, api):
        """One draft window at one property, reached by naming the property and the status
        the window is sitting in.

        PRD: "Blackout windows filter on `hotel_id` and `status`. Members filter on
        `elite_tier` and `email`."

        Design: Corner/endpoints/filtered_lists_are_the_only_reverse_path_from_parent_to_children
        """
        bundle = _linkline_with_one_child_of_every_kind(api)
        hotel_id = bundle["hotel"]["id"]

        rows, meta = validate_paginated(
            api.list_blackout_windows(
                make_admin_headers(), params={"hotel_id": hotel_id, "status": "DRAFT"}
            )
        )

        assert meta["total_count"] == 1, (
            f"one window was drafted, the list counted {meta['total_count']}"
        )
        assert_single_row(rows, bundle["window"]["id"])
        assert rows[0]["scope"] == "STANDARD_ONLY", (
            f"the draft was scoped to standard redemptions, the row reads {rows[0]['scope']}"
        )

    def test_a_filter_value_that_matches_nothing_is_an_empty_page_not_a_refusal(
        self, api
    ):
        """A filter is an equality predicate over the collection, not a lookup of the
        parent, so an identifier that names no property answers with no rows.

        PRD: "Beyond pagination, each collection accepts a fixed set of equality filters,
        and no others."

        Design: Corner/endpoints/filtered_lists_are_the_only_reverse_path_from_parent_to_children
        """
        _linkline_with_one_child_of_every_kind(api)

        response = api.list_stays(
            make_admin_headers(), params={"hotel_id": _UNMATCHED_HOTEL_ID}
        )

        rows, meta = validate_paginated(response)

        assert response.status_code == 200, (
            "an unmatched filter value is a valid query, expected HTTP 200, got "
            f"{response.status_code}"
        )
        assert rows == [], f"expected no rows for an unmatched property, got {len(rows)}"
        assert meta["total_count"] == 0, (
            f"expected a total of 0, got {meta['total_count']}"
        )
        assert meta["has_more"] is False, "an empty page cannot have more behind it"


# ----------------------------------------------------------------------
# The window walks the collection, and its edges are refused.
# ----------------------------------------------------------------------
class TestListPaginationWalksTheCollectionAndRejectsOutOfRangeWindows:
    def test_the_default_window_returns_everything_and_says_so(self, api):
        """Three rows fit inside the default page of ten, so the meta reports the defaults
        and denies that anything is behind it.

        PRD: "`limit` sets the maximum number of rows returned; it defaults to 10, accepts
        a minimum of 1 and a maximum of 100."

        Design: Corner/endpoints/list_pagination_walks_the_collection_and_rejects_out_of_range_windows
        """
        _exactly_three_members(api)

        rows, meta = validate_paginated(api.list_members(make_admin_headers()))

        assert meta["limit"] == 10, f"limit defaults to 10, got {meta['limit']}"
        assert meta["offset"] == 0, f"offset defaults to 0, got {meta['offset']}"
        assert meta["total_count"] == 3, (
            f"three guests were enrolled, the meta counted {meta['total_count']}"
        )
        assert meta["has_more"] is False, "all three rows fit on the default page"
        assert len(rows) == 3, f"expected all three rows, got {len(rows)}"

    def test_the_first_narrow_page_is_the_oldest_two_rows(self, api):
        """A page of two starts at the earliest-written row, because the collection is
        ordered by when the rows were created.

        PRD: "Unless a specific endpoint says otherwise, collections are sorted by
        `created_at` ascending."

        Design: Corner/endpoints/list_pagination_walks_the_collection_and_rejects_out_of_range_windows
        """
        bundle = _exactly_three_members(api)

        rows, meta = validate_paginated(
            api.list_members(make_admin_headers(), params={"limit": 2, "offset": 0})
        )

        assert len(rows) == 2, f"a limit of two should return two rows, got {len(rows)}"
        assert meta["total_count"] == 3, (
            f"the total counts the collection, not the page, got {meta['total_count']}"
        )
        assert meta["has_more"] is True, "one row is still behind the first page of two"
        assert rows[0]["id"] == bundle["first"]["id"], (
            "the first row of the first page should be the earliest guest enrolled"
        )
        assert rows[1]["id"] == bundle["second"]["id"], (
            "the second row should be the second guest enrolled"
        )

    def test_the_last_page_is_short_and_admits_nothing_follows(self, api):
        """Skipping two of three leaves a single row, and the meta stops claiming there is
        more.

        PRD: "The `meta` object of every list response carries `limit`, `offset`,
        `total_count` and `has_more`."

        Design: Corner/endpoints/list_pagination_walks_the_collection_and_rejects_out_of_range_windows
        """
        bundle = _exactly_three_members(api)

        rows, meta = validate_paginated(
            api.list_members(make_admin_headers(), params={"limit": 2, "offset": 2})
        )

        assert len(rows) == 1, f"one row remains after skipping two, got {len(rows)}"
        assert meta["total_count"] == 3, (
            f"the total is unchanged by the window, got {meta['total_count']}"
        )
        assert meta["has_more"] is False, "the third row is the last one"
        assert rows[0]["id"] == bundle["third"]["id"], (
            "the tail of the collection should be the last guest enrolled"
        )

    def test_a_window_that_starts_past_the_end_is_empty_rather_than_refused(self, api):
        """An offset of three over three rows is a legal window that happens to contain
        nothing.

        PRD: "`offset` sets the number of rows to skip and defaults to 0."

        Design: Corner/endpoints/list_pagination_walks_the_collection_and_rejects_out_of_range_windows
        """
        _exactly_three_members(api)

        response = api.list_members(
            make_admin_headers(), params={"limit": 2, "offset": 3}
        )

        rows, meta = validate_paginated(response)

        assert response.status_code == 200, (
            f"skipping the whole collection is not an error, got {response.status_code}"
        )
        assert rows == [], f"expected an empty page, got {len(rows)} rows"
        assert meta["total_count"] == 3, (
            f"the collection still holds three rows, meta says {meta['total_count']}"
        )
        assert meta["has_more"] is False, "there is nothing beyond an exhausted collection"

    def test_a_limit_below_the_minimum_is_refused_rather_than_raised(self, api):
        """Asking for no rows at all is outside the accepted range, and the collection
        refuses instead of quietly substituting the default.

        PRD: "Every collection endpoint is paginated through two query parameters."

        Design: Corner/endpoints/list_pagination_walks_the_collection_and_rejects_out_of_range_windows
        """
        _exactly_three_members(api)

        validate_error(
            api.list_members(make_admin_headers(), params={"limit": 0}),
            ApiErrorId.ERR_INVALID_REQUEST,
        )

    def test_a_limit_above_the_maximum_is_refused_rather_than_clamped(self, api):
        """One past the hundred-row ceiling is refused, so a caller cannot drain a
        collection in a single oversized page.

        PRD: "`limit` sets the maximum number of rows returned; it defaults to 10, accepts
        a minimum of 1 and a maximum of 100."

        Design: Corner/endpoints/list_pagination_walks_the_collection_and_rejects_out_of_range_windows
        """
        _exactly_three_members(api)

        validate_error(
            api.list_members(make_admin_headers(), params={"limit": 101}),
            ApiErrorId.ERR_INVALID_REQUEST,
        )

    def test_a_negative_offset_is_refused_rather_than_treated_as_zero(self, api):
        """Skipping a negative number of rows is not a window at all, and it is not read as
        the default of nothing skipped.

        PRD: "`offset` sets the number of rows to skip and defaults to 0."

        Design: Corner/endpoints/list_pagination_walks_the_collection_and_rejects_out_of_range_windows
        """
        _exactly_three_members(api)

        validate_error(
            api.list_members(make_admin_headers(), params={"offset": -1}),
            ApiErrorId.ERR_INVALID_REQUEST,
        )


# ----------------------------------------------------------------------
# Bodies that try to set what the endpoint never declared.
# ----------------------------------------------------------------------
def _smuggled_bodies_at_every_step(api):
    """A property, a rate plan and a stay, each created from a body that also carried the
    system-owned and derived fields the endpoint never asked for."""
    member = _one_member_for_the_smuggled_bodies(api)
    hotel = validate_success(
        api.create_hotel(
            fac.create_hotel_payload(
                name="Ignoreville Hotel",
                brand_code="IGH",
                market_tier="URBAN",
                program_fee_pct=0.05,
                rooms_count=100,
                trailing_12m_occupancy_pct=0.82,
                trailing_12m_adr_cents=30_000,
                id=_SMUGGLED_HOTEL_ID,
                status="ACTIVE",
                version=9,
                fee_ledger_balance_cents=500_000,
                benefit_denial_count=3,
                blackout_days_used_current_year=55,
            ),
            make_admin_headers(),
        ),
        201,
    )
    hotel_id = hotel["id"]
    rate_plan = validate_success(
        api.create_rate_plan(
            hotel_id,
            fac.create_rate_plan_payload(
                rate_code="BAR",
                rate_category="TRANSIENT",
                base_earn_rate_per_dollar=99,
                is_qualifying=False,
                program_fee_eligible=False,
                counts_toward_elite=False,
            ),
            make_hotel_owner_headers(hotel_id),
        ),
        201,
    )
    fx.activate_hotel(api, hotel_id)
    stay = validate_success(
        api.create_stay(
            fac.create_stay_payload(
                member["id"],
                hotel_id,
                rate_plan["id"],
                checkin_date="2026-06-01",
                checkout_date="2026-06-04",
                room_revenue_cents=50_000,
                nights=99,
                tier_at_checkin="PLATINUM",
                status="POSTED_QUALIFYING",
                base_points_awarded=7_777,
                program_fee_assessed_cents=12_345,
            ),
            make_admin_headers(),
        ),
        201,
    )
    return {"member": member, "hotel": hotel, "rate_plan": rate_plan, "stay": stay}


class TestSystemAndComputedFieldsSentInACreateBodyAreInputIgnored:
    def test_the_server_mints_its_own_identifier_over_the_one_supplied(self, api):
        """The body named the identifier it wanted, and the row that came back carries a
        different one that the server chose.

        PRD: "Every resource the API returns carries a server-minted `id`: a UUID string
        with no type prefix and no embedded meaning."

        Design: Corner/endpoints/system_and_computed_fields_sent_in_a_create_body_are_input_ignored
        """
        bundle = _smuggled_bodies_at_every_step(api)
        hotel = bundle["hotel"]

        assert hotel["id"] != _SMUGGLED_HOTEL_ID, (
            "the identifier in the request body was accepted as the row's identity"
        )
        assert is_valid_uuid(hotel["id"]), (
            f"the minted identifier should be a UUID string, got {hotel['id']}"
        )
        assert hotel["name"] == "Ignoreville Hotel", (
            "the declared input fields should still have been read from the same body"
        )

    def test_the_smuggled_status_and_version_do_not_shortcut_onboarding(self, api):
        """A body claiming the property is already active and on its ninth revision still
        produces a property waiting to be activated for the first time.

        PRD: "A newly enrolled property lands in `ONBOARDING` with
        `fee_ledger_balance_cents`, `reimbursement_owed_cents`,
        `benefit_recovery_owed_cents`, `benefit_denial_count` and
        `blackout_days_used_current_year` all at 0, `termination_reason` null, and `version`
        at 1."

        Design: Corner/endpoints/system_and_computed_fields_sent_in_a_create_body_are_input_ignored
        """
        bundle = _smuggled_bodies_at_every_step(api)

        assert_hotel(bundle["hotel"], status="ONBOARDING", version=1)
        assert bundle["hotel"]["termination_reason"] is None, (
            "a freshly enrolled property carries no termination reason"
        )

    def test_the_smuggled_counters_are_all_still_at_zero(self, api):
        """A pre-loaded fee ledger, three denials and fifty-five consumed blackout days
        were all offered and none of them stuck.

        PRD: "an integer that starts at 1 when the row is created and increments by exactly
        1 on every mutation of that row"

        Design: Corner/endpoints/system_and_computed_fields_sent_in_a_create_body_are_input_ignored
        """
        bundle = _smuggled_bodies_at_every_step(api)

        assert_hotel_counters_zero(bundle["hotel"])

    def test_the_rate_plans_flags_follow_the_category_and_not_the_body(self, api):
        """The body asked for ninety-nine points a dollar and for a plan that earns nothing
        toward the programme, and the category overruled all four fields.

        PRD: "Everything else on the rate plan is derived from `rate_category` alone and is
        never accepted from the request."

        Design: Corner/endpoints/system_and_computed_fields_sent_in_a_create_body_are_input_ignored
        """
        bundle = _smuggled_bodies_at_every_step(api)
        rate_plan = bundle["rate_plan"]

        assert_rate_plan_derivation(rate_plan)
        assert rate_plan["base_earn_rate_per_dollar"] == 10, (
            "a transient plan earns ten points per dollar, the row reads "
            f"{rate_plan['base_earn_rate_per_dollar']}"
        )
        assert rate_plan["is_qualifying"] is True, (
            "a transient plan is qualifying whatever the request claimed"
        )

    def test_the_stays_nights_and_tier_snapshot_are_computed_not_accepted(self, api):
        """Ninety-nine nights and a platinum guest were offered; the dates give three
        nights and the guest's own row gives the base tier.

        PRD: "On creation, the system computes `nights` as the number of days from
        `checkin_date` to `checkout_date` — a half-open interval that includes the arrival
        date and excludes the departure date"

        Design: Corner/endpoints/system_and_computed_fields_sent_in_a_create_body_are_input_ignored
        """
        bundle = _smuggled_bodies_at_every_step(api)

        assert_stay(
            bundle["stay"], nights=3, tier_at_checkin="BASE", room_revenue_cents=50_000
        )

    def test_the_stay_lands_pending_with_every_money_field_at_zero(self, api):
        """The body pre-declared the stay posted and pre-loaded its points and its fee, and
        the row came back at the start of its lifecycle with nothing earned.

        PRD: "snapshots the guest's current `elite_tier` into `tier_at_checkin`. The stay
        lands in `PENDING_POSTING` with `base_points_awarded`, `bonus_points_awarded` and
        `program_fee_assessed_cents` at 0, `bonus_multiplier_applied` at 0.00, and
        `dispute_reason` and `void_reason` both null."

        Design: Corner/endpoints/system_and_computed_fields_sent_in_a_create_body_are_input_ignored
        """
        bundle = _smuggled_bodies_at_every_step(api)
        stay = bundle["stay"]

        assert_stay(
            stay,
            status="PENDING_POSTING",
            base_points=0,
            bonus_points=0,
            fee_cents=0,
            bonus_multiplier=0.0,
            version=1,
        )
        assert stay["dispute_reason"] is None, "a captured stay carries no dispute reason"
        assert stay["void_reason"] is None, "a captured stay carries no void reason"
