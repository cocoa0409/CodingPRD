"""The three verbs the member resource actually offers, the two action endpoints that
answer with a subject row rather than the rows they moved, and the singleton fund whose
figures derive themselves without anyone asking."""

from test_helpers import (
    assert_fund,
    assert_fund_posture_matches_ratio,
    assert_ledger_entry,
    assert_member,
    assert_member_counters_zero,
    assert_stay,
    collect_all,
    factories as fac,
    fixtures as fx,
    is_iso8601_timestamp,
    make_admin_headers,
    make_auditor_headers,
    make_care_agent_headers,
    make_member_headers,
    read_entity,
    validate_paginated,
    validate_success,
)


# ----------------------------------------------------------------------
# Scenario builders
# ----------------------------------------------------------------------
def _two_members_one_dated_and_one_defaulted(api):
    """One guest enrolled with an explicit joining date by the programme, one enrolled by
    the care desk with the date left out."""
    dated = validate_success(
        api.create_member(
            fac.create_member_payload(
                email="crud1@example.com",
                full_name="Anya Petrov",
                enrollment_date="2026-03-09",
            ),
            make_admin_headers(),
        ),
        201,
    )
    defaulted_payload = fac.create_member_payload(
        email="crud2@example.com", full_name="Tomas Halle"
    )
    defaulted_payload.pop("enrollment_date", None)
    defaulted = validate_success(
        api.create_member(defaulted_payload, make_care_agent_headers("care-cr-01")),
        201,
    )
    return {"dated": dated, "defaulted": defaulted}


def _actionpoint_with_a_funded_guest_and_a_captured_stay(api):
    """A trading property, a guest holding twenty thousand bought points, and a ten-night
    stay sitting in `PENDING_POSTING`."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Actionpoint Hotel",
        brand_code="APH",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=150,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=30_000,
    )
    member = fx.enroll_member(
        api, email="ap1@example.com", full_name="Nils Sandvik", enrollment_date="2026-02-02"
    )
    member_id = member["id"]
    purchase = fx.settled_purchase(api, member_id, 20_000, channel="DIRECT_PURCHASE")
    stay = fx.capture_stay(
        api,
        bundle["hotel"]["id"],
        member_id,
        bundle["rate_plan"]["id"],
        "2026-06-01",
        "2026-06-11",
        100_000,
    )

    bundle["member"] = member
    bundle["purchase"] = purchase
    bundle["stay"] = stay
    return bundle


def _one_member_and_nothing_else(api):
    """A single enrolled guest, so the programme fund has never been touched."""
    return fx.enroll_member(
        api, email="fd1@example.com", full_name="Greta Aalto", enrollment_date="2026-01-15"
    )


def _the_same_member_after_one_settled_sale(api):
    """The same guest after one twenty-thousand-point direct sale has settled."""
    member = _one_member_and_nothing_else(api)
    purchase = fx.settled_purchase(api, member["id"], 20_000, channel="DIRECT_PURCHASE")
    return {"member": member, "purchase": purchase}


# ----------------------------------------------------------------------
# The member resource: create, read, filtered list.
# ----------------------------------------------------------------------
class TestMemberResourceSupportsCreateReadAndFilteredListAndNothingElse:
    def test_the_create_response_is_the_whole_row_computed_fields_included(self, api):
        """Three fields go in and a fully derived guest comes back, already carrying the
        starting tier and the five zeroed counters.

        PRD: "A new member starts at `elite_tier` `BASE` with `qualifying_nights_ytd`,
        `qualifying_revenue_cents_ytd`, `point_balance`, `lifetime_points_earned` and
        `points_purchased_current_year` all at 0."

        Design: Corner/endpoints/member_resource_supports_create_read_and_filtered_list_and_nothing_else
        """
        bundle = _two_members_one_dated_and_one_defaulted(api)

        assert bundle["dated"]["email"] == "crud1@example.com", (
            f"the create echoed email {bundle['dated']['email']}"
        )
        assert_member(bundle["dated"], elite_tier="BASE", version=1)
        assert_member_counters_zero(bundle["dated"])

    def test_the_omitted_joining_date_falls_back_to_the_logical_clock(self, api):
        """The care desk left the date out, and the programme filled it from its own clock
        rather than from the host's calendar.

        PRD: "When `enrollment_date` is omitted it defaults to the logical clock's current
        date, meaning the date part of the current logical UTC timestamp."

        Design: Corner/endpoints/member_resource_supports_create_read_and_filtered_list_and_nothing_else
        """
        bundle = _two_members_one_dated_and_one_defaulted(api)

        assert bundle["defaulted"]["enrollment_date"] == "2026-08-01", (
            "the defaulted joining date should be the logical clock's date, got "
            f"{bundle['defaulted']['enrollment_date']}"
        )
        assert bundle["dated"]["enrollment_date"] == "2026-03-09", (
            "the supplied joining date should be kept verbatim"
        )

    def test_the_read_returns_exactly_what_the_create_stored(self, api):
        """The guest reads their own row, and every field the create reported comes back
        unchanged.

        PRD: "A `ProgramAdministrator` or a `MemberCareAgent` creates a member from an
        `email` — which must be globally unique across the programme and must contain an
        at-sign — a `full_name` for display, and an optional `enrollment_date` in
        `YYYY-MM-DD` form."

        Design: Corner/endpoints/member_resource_supports_create_read_and_filtered_list_and_nothing_else
        """
        bundle = _two_members_one_dated_and_one_defaulted(api)
        member_id = bundle["dated"]["id"]

        row = read_entity(api.get_member, member_id, make_member_headers(member_id))

        assert row["id"] == member_id, "the read addressed the wrong row"
        assert row["email"] == "crud1@example.com", (
            f"the read reports email {row['email']}"
        )
        assert row["full_name"] == "Anya Petrov", (
            f"the read reports name {row['full_name']}"
        )
        assert_member(row, point_balance=0, lifetime_points_earned=0)

    def test_the_email_filter_is_an_exact_match_rather_than_a_search(self, api):
        """One address is supplied and one row comes back — the collection is narrowed by
        equality, not by matching a fragment.

        PRD: "Blackout windows filter on `hotel_id` and `status`. Members filter on
        `elite_tier` and `email`."

        Design: Corner/endpoints/member_resource_supports_create_read_and_filtered_list_and_nothing_else
        """
        bundle = _two_members_one_dated_and_one_defaulted(api)

        rows, meta = validate_paginated(
            api.list_members(
                make_auditor_headers("aud-cr-01"), params={"email": "crud2@example.com"}
            )
        )

        assert meta["total_count"] == 1, (
            f"the email filter should select one guest, got {meta['total_count']}"
        )
        assert rows[0]["id"] == bundle["defaulted"]["id"], (
            "the email filter selected the wrong guest"
        )

    def test_the_tier_filter_narrows_the_same_collection_independently(self, api):
        """Both guests are at the starting tier, and asking for the top tier answers with an
        empty page rather than a refusal.

        PRD: "Beyond pagination, each collection accepts a fixed set of equality filters,
        and no others."

        Design: Corner/endpoints/member_resource_supports_create_read_and_filtered_list_and_nothing_else
        """
        _two_members_one_dated_and_one_defaulted(api)
        auditor = make_auditor_headers("aud-cr-01")

        base_rows, base_meta = validate_paginated(
            api.list_members(auditor, params={"elite_tier": "BASE"})
        )
        top_rows, top_meta = validate_paginated(
            api.list_members(auditor, params={"elite_tier": "PLATINUM"})
        )

        assert base_meta["total_count"] == 2, (
            f"both guests should be at the starting tier, got {base_meta['total_count']}"
        )
        assert len(base_rows) == 2, "the starting-tier page should carry both rows"
        assert top_meta["total_count"] == 0, (
            f"nobody should be at the top tier, got {top_meta['total_count']}"
        )
        assert top_rows == [], "the unmatched filter should answer with an empty page"


# ----------------------------------------------------------------------
# Action endpoints answer with a subject row, never with their side effects.
# ----------------------------------------------------------------------
class TestActionEndpointsAnswerWithTheirSubjectRowAndHideTheirSideEffects:
    def test_posting_answers_with_the_stay_it_acted_on(self, api):
        """The visible work of the posting is two counters and a ledger row, and the
        response body is still the stay.

        PRD: "The stay lands in `PENDING_POSTING` with `base_points_awarded`,
        `bonus_points_awarded` and `program_fee_assessed_cents` at 0,
        `bonus_multiplier_applied` at 0.00, and `dispute_reason` and `void_reason` both
        null."

        Design: Corner/endpoints/action_endpoints_answer_with_their_subject_row_and_hide_their_side_effects
        """
        bundle = _actionpoint_with_a_funded_guest_and_a_captured_stay(api)

        posted = fx.post_stay(api, bundle["stay"]["id"])

        assert_stay(bundle["stay"], status="PENDING_POSTING", base_points=0, fee_cents=0)
        assert posted["id"] == bundle["stay"]["id"], (
            "the posting response should be the same stay row"
        )
        assert_stay(posted, status="POSTED_QUALIFYING", nights=10)

    def test_the_posted_stay_carries_its_own_derived_money_and_points(self, api):
        """A thousand dollars of room revenue at ten points a dollar and a five-percent fee,
        with no bonus because the guest arrived unranked.

        PRD: "`base_points_awarded` is the stay's `room_revenue_cents` multiplied by the
        rate plan's `base_earn_rate_per_dollar`, divided by one hundred to convert cents
        into whole dollars, with the result rounded **down** to a whole point."

        Design: Corner/endpoints/action_endpoints_answer_with_their_subject_row_and_hide_their_side_effects
        """
        bundle = _actionpoint_with_a_funded_guest_and_a_captured_stay(api)

        posted = fx.post_stay(api, bundle["stay"]["id"])

        assert_stay(
            posted,
            base_points=10_000,
            bonus_points=0,
            fee_cents=5_000,
            bonus_multiplier=0.0,
            tier_at_checkin="BASE",
        )

    def test_the_ledger_rows_are_only_reachable_through_their_own_read(self, api):
        """The posting response never carried the ledger, and the single earning row it
        wrote has to be looked up by the stay that caused it.

        PRD: "One `EARN_BASE` entry is written with `points` equal to
        `base_points_awarded` and `source_stay_id` naming the stay; one `EARN_BONUS` entry
        is written with `points` equal to `bonus_points_awarded` and the same
        `source_stay_id`, and that second entry is emitted **only** when
        `bonus_points_awarded` is greater than zero."

        Design: Corner/endpoints/action_endpoints_answer_with_their_subject_row_and_hide_their_side_effects
        """
        bundle = _actionpoint_with_a_funded_guest_and_a_captured_stay(api)
        stay_id = bundle["stay"]["id"]
        posted = fx.post_stay(api, stay_id)

        entries = collect_all(
            api.list_ledger_entries,
            make_auditor_headers("aud-ap-01"),
            source_stay_id=stay_id,
        )

        assert "ledger" not in posted, (
            "the posting response should not embed the rows it wrote"
        )
        assert len(entries) == 1, (
            f"a zero bonus should write one earning row alone, got {len(entries)}"
        )
        assert_ledger_entry(
            entries[0],
            entry_type="EARN_BASE",
            points=10_000,
            member_id=bundle["member"]["id"],
            source_stay_id=stay_id,
        )

    def test_the_adjustment_endpoint_answers_with_the_entry_it_minted(self, api):
        """The caller cares about the guest's balance, and the body that comes back is the
        immutable ledger row instead.

        PRD: "This is the only endpoint whose response body is a ledger entry rather than
        the resource named in the path."

        Design: Corner/endpoints/action_endpoints_answer_with_their_subject_row_and_hide_their_side_effects
        """
        bundle = _actionpoint_with_a_funded_guest_and_a_captured_stay(api)
        member_id = bundle["member"]["id"]
        fx.post_stay(api, bundle["stay"]["id"])

        entry = validate_success(
            api.create_point_adjustment(
                fac.point_adjustment_payload(
                    member_id,
                    500,
                    fx.member_version(api, member_id),
                    adjustment_reason="Service recovery for a late room.",
                ),
                make_admin_headers(),
            ),
            201,
        )

        assert_ledger_entry(
            entry,
            entry_type="GOODWILL",
            points=500,
            member_id=member_id,
            adjustment_reason="Service recovery for a late room.",
            liability_unit_cost=600,
        )

    def test_the_row_that_actually_moved_shows_up_only_on_a_follow_up_read(self, api):
        """Twenty thousand bought, ten thousand earned and five hundred granted are all on
        the guest, and none of the three responses said so.

        PRD: "On success a `GOODWILL` ledger entry is written carrying the signed `points`
        and the supplied `adjustment_reason`, the member's `point_balance` moves by that
        amount, the member's `version` increments, and the fund's valuation and posture are
        recomputed."

        Design: Corner/endpoints/action_endpoints_answer_with_their_subject_row_and_hide_their_side_effects
        """
        bundle = _actionpoint_with_a_funded_guest_and_a_captured_stay(api)
        member_id = bundle["member"]["id"]
        fx.post_stay(api, bundle["stay"]["id"])
        version_before = fx.member_version(api, member_id)
        fx.grant_goodwill_points(
            api, member_id, 500, reason="Service recovery for a late room."
        )

        member = fx.read_member(api, member_id)

        assert_member(member, point_balance=30_500)
        assert member["version"] > version_before, (
            "the grant should have moved the guest's version from "
            f"{version_before}, got {member['version']}"
        )


# ----------------------------------------------------------------------
# The singleton fund read is pure; only two actions ever write to it.
# ----------------------------------------------------------------------
class TestProgramFundReadIsComputedAndRepeatingItChangesNothing:
    def test_the_fund_exists_from_server_start_with_its_opening_figures(self, api):
        """Nobody has created the fund and nobody could; it is there to be read the moment
        the programme is up.

        PRD: "The programme fund is a singleton that exists from server start with
        `cash_balance_cents` 0, `outstanding_points` 0, `breakage_rate_pct` 0.20,
        `point_liability_cents` 0, `solvency_ratio` 999.0, `status` `HEALTHY` and
        `last_revalued_at` null."

        Design: Corner/endpoints/program_fund_read_is_computed_and_repeating_it_changes_nothing
        """
        _one_member_and_nothing_else(api)

        fund = validate_success(api.get_program_fund(make_auditor_headers("aud-fd-01")))

        assert_fund(
            fund,
            cash_cents=0,
            outstanding_points=0,
            breakage_rate_pct=0.2,
            liability_cents=0,
            solvency_ratio=999.0,
            status="HEALTHY",
        )
        assert fund["last_revalued_at"] is None, (
            "no revaluation has been asked for, so the stamp should be unset, got "
            f"{fund['last_revalued_at']}"
        )

    def test_reading_the_fund_twice_is_not_a_write(self, api):
        """A second read by a different role reports the same figures and still no
        revaluation stamp.

        PRD: "Its `outstanding_points` is the signed sum of `points` across **every**
        ledger entry of every member, with no status filter and no exclusion list"

        Design: Corner/endpoints/program_fund_read_is_computed_and_repeating_it_changes_nothing
        """
        _one_member_and_nothing_else(api)

        first = validate_success(api.get_program_fund(make_auditor_headers("aud-fd-01")))
        second = validate_success(api.get_program_fund(make_admin_headers()))

        assert second["cash_balance_cents"] == first["cash_balance_cents"], (
            "the second read reports different cash"
        )
        assert second["solvency_ratio"] == first["solvency_ratio"], (
            "the second read reports a different ratio"
        )
        assert second["version"] == first["version"], (
            f"reading bumped the version from {first['version']} to {second['version']}"
        )
        assert second["last_revalued_at"] is None, "reading is not a revaluation"

    def test_a_settled_sale_moves_the_cash_and_the_outstanding_total(self, api):
        """Twenty lots at the direct list price are below the discount floor, so the sale
        brings in a round 25,000 cents and adds its points to the outstanding total.

        PRD: "The fund's `cash_balance_cents` rises by `cash_due_cents`. Because those
        entries and that cash movement happened, the member's `point_balance` and
        `lifetime_points_earned`, the member's `points_purchased_current_year`, the
        partner's `purchased_points_mtd` where a partner is referenced, and the fund's
        `outstanding_points`, `point_liability_cents`, `solvency_ratio` and `status` are all
        recomputed."

        Design: Corner/endpoints/program_fund_read_is_computed_and_repeating_it_changes_nothing
        """
        _the_same_member_after_one_settled_sale(api)

        fund = validate_success(api.get_program_fund(make_auditor_headers("aud-fd-01")))

        assert_fund(fund, cash_cents=25_000, outstanding_points=20_000)

    def test_the_liability_and_the_posture_derive_themselves_unasked(self, api):
        """No one called revalue, and the liability, the ratio and the posture are already
        correct — and the revaluation stamp is still unset.

        PRD: "The `point_liability_cents` is that outstanding total, valued at 600 cents
        per thousand points, multiplied by one minus `breakage_rate_pct`, rounded half up to
        whole cents."

        Design: Corner/endpoints/program_fund_read_is_computed_and_repeating_it_changes_nothing
        """
        _the_same_member_after_one_settled_sale(api)

        fund = validate_success(api.get_program_fund(make_auditor_headers("aud-fd-01")))

        assert_fund(
            fund, liability_cents=9_600, solvency_ratio=2.6042, status="HEALTHY"
        )
        assert_fund_posture_matches_ratio(fund)
        assert fund["last_revalued_at"] is None, (
            "the settlement moved the figures but should not have stamped a revaluation, "
            f"got {fund['last_revalued_at']}"
        )

    def test_the_explicit_revalue_changes_no_figure_and_only_stamps_the_clock(self, api):
        """Arithmetically the revaluation is a no-op here, and the one thing it does is
        record the instant it happened.

        PRD: "That whole derivation re-runs from scratch at the end of every request that
        writes a ledger entry or moves programme cash, so the fund is never stale, and it
        can be re-derived on demand by an administrator or the `ProgramAuditor`, which also
        sets `last_revalued_at` to the clock's current instant and increments the fund's
        `version`."

        Design: Corner/endpoints/program_fund_read_is_computed_and_repeating_it_changes_nothing
        """
        _the_same_member_after_one_settled_sale(api)

        revalued = validate_success(
            api.revalue_program_fund(make_auditor_headers("aud-fd-01"))
        )

        assert_fund(revalued, liability_cents=9_600, solvency_ratio=2.6042)
        assert is_iso8601_timestamp(revalued["last_revalued_at"]), (
            "the revaluation stamp should be an ISO 8601 instant, got "
            f"{revalued['last_revalued_at']}"
        )
        assert revalued["last_revalued_at"].startswith("2026-08-01T00:00:00"), (
            "the stamp should read the logical clock's instant, got "
            f"{revalued['last_revalued_at']}"
        )

    def test_restating_the_breakage_assumption_moves_the_liability(self, api):
        """Thirty-five percent breakage values the same twenty thousand points at 7,800
        cents, which lifts the ratio without changing the posture.

        PRD: "An administrator may additionally restate the assumption by supplying a new
        `breakage_rate_pct` between 0.0 and 0.35 inclusive; that overwrites the field,
        immediately re-runs the valuation and posture derivation, and increments the
        `version` — but it does **not** touch `last_revalued_at`, which records only an
        explicit revaluation."

        Design: Corner/endpoints/program_fund_read_is_computed_and_repeating_it_changes_nothing
        """
        _the_same_member_after_one_settled_sale(api)

        restated = fx.set_breakage_rate(api, 0.35)

        assert_fund(
            restated,
            breakage_rate_pct=0.35,
            liability_cents=7_800,
            solvency_ratio=3.2051,
            status="HEALTHY",
        )
        assert_fund_posture_matches_ratio(restated)
