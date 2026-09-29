"""Interval contention under two different interval semantics.

The chain of title uses half-open calendar dates compared across every party of
the site, with an empty end date running to the far future. Field-work windows
use timestamps padded by a mobilisation buffer and are counted against a
per-contract concurrency limit.
"""
from test_helpers import ApiErrorId, api_client, factories
from test_helpers.assertions import (
    assert_pagination_meta,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    add_ownership_period,
    add_sample,
    add_alternative,
    add_work_window,
    award_contract,
    create_investigation,
    create_listed_site,
    create_party,
    create_rod,
    create_solicitation,
    file_comment,
    open_comment_period,
    read_contract,
    read_party,
    read_site,
    review_investigation,
    set_clock,
    sign_rod,
    submit_investigation,
)
from test_helpers.test_users import TEST_USERS, make_contractor_headers

AUTHOR = TEST_USERS["author_pm_headers"]


def _mill_race_chain_of_title():
    """One recorded link of the chain, and two parties who could hold more."""
    set_clock("2027-02-01T09:00:00Z")
    site = create_listed_site(name="Mill Race Coke Works", epa_region=3, hrs_score=55.40)
    prp_a = create_party(
        site["id"],
        legal_name="Mill Race Coke Co",
        party_type="OWNER_OPERATOR",
        viability_score=70,
    )
    prp_b = create_party(
        site["id"],
        legal_name="Race Street Holdings LP",
        party_type="OWNER_OPERATOR",
        viability_score=64,
    )
    op1 = add_ownership_period(
        site["id"], prp_a["id"], "1962-03-01", "1978-06-01", "PURCHASE"
    )
    return site, prp_a, prp_b, op1


def _propose_period(site_id, prp_id, start_date, end_date, acquisition_type):
    return api_client.create_ownership_period(
        site_id,
        factories.ownership_period_payload(
            prp_id=prp_id,
            start_date=start_date,
            end_date=end_date,
            acquisition_type=acquisition_type,
        ),
        AUTHOR,
    )


class TestChainOfTitleHalfOpenAdjacencyAndOpenEndedPeriods:
    def test_touching_endpoints_and_a_zero_length_period_are_both_accepted(self):
        """Adjacency is legal and a same-day period spans no days at all.

        PRD: "From the two dates the system derives `ownership_days` as the whole number of days on the half-open interval that runs from the start date up to but not including the end date; a period whose end date equals its start date therefore yields zero days."

        Design: Difficulty/resource_temporal_overlap/chain_of_title_half_open_adjacency_and_open_ended_period_conflict
        """
        site, prp_a, prp_b, op1 = _mill_race_chain_of_title()
        assert op1["ownership_days"] == 5936

        op2 = validate_success(
            _propose_period(site["id"], prp_b["id"], "1978-06-01", "1995-01-01", "MERGER"),
            201,
        )
        assert op2["ownership_days"] == 6058

        op3 = validate_success(
            _propose_period(site["id"], prp_a["id"], "1995-01-01", "1995-01-01", "LEASE"),
            201,
        )
        assert op3["ownership_days"] == 0

    def test_a_period_straddling_another_partys_end_date_is_refused(self):
        """The conflict test spans parties, not merely one party's own periods.

        PRD: "A proposed period conflicts with an existing period of the same site when the proposed start date falls strictly before the existing end date **and** the existing start date falls strictly before the proposed end date; that test applies across any pair of parties, not merely two periods of the same party."

        Design: Difficulty/resource_temporal_overlap/chain_of_title_half_open_adjacency_and_open_ended_period_conflict
        """
        site, _, prp_b, _ = _mill_race_chain_of_title()

        validate_error(
            _propose_period(
                site["id"], prp_b["id"], "1978-05-31", "1978-06-02", "FORECLOSURE"
            ),
            ApiErrorId.ERR_OWNERSHIP_PERIOD_OVERLAP.value,
        )

    def test_an_open_ended_period_runs_to_the_far_future_and_blocks_everything_after_it(self):
        """An empty end date is evaluated as 9999-12-31 for interval arithmetic.

        PRD: "An empty `end_date` means the party still holds title, and for all interval arithmetic such an open period is treated as ending on 9999-12-31."

        Design: Difficulty/resource_temporal_overlap/chain_of_title_half_open_adjacency_and_open_ended_period_conflict
        """
        site, prp_a, prp_b, _ = _mill_race_chain_of_title()
        _propose_period(site["id"], prp_b["id"], "1978-06-01", "1995-01-01", "MERGER")
        _propose_period(site["id"], prp_a["id"], "1995-01-01", "1995-01-01", "LEASE")

        op5 = validate_success(
            _propose_period(site["id"], prp_b["id"], "1995-01-01", None, "PURCHASE"), 201
        )
        assert op5["ownership_days"] == 2_923_765

        validate_error(
            _propose_period(site["id"], prp_a["id"], "2000-01-01", "2001-01-01", "PURCHASE"),
            ApiErrorId.ERR_OWNERSHIP_PERIOD_OVERLAP.value,
        )

    def test_only_accepted_periods_feed_the_party_totals_and_the_listing(self):
        """Each party's total is the sum over its own accepted periods.

        PRD: "Ownership periods are immutable once written; recording one refreshes the holding party's `ownership_days_total`, which is simply the sum of `ownership_days` over that party's periods for the site, and re-derives the provisional percentages of the site's round if a round is currently drafting."

        Design: Difficulty/resource_temporal_overlap/chain_of_title_half_open_adjacency_and_open_ended_period_conflict
        """
        site, prp_a, prp_b, _ = _mill_race_chain_of_title()
        _propose_period(site["id"], prp_b["id"], "1978-06-01", "1995-01-01", "MERGER")
        _propose_period(site["id"], prp_a["id"], "1995-01-01", "1995-01-01", "LEASE")
        _propose_period(
            site["id"], prp_b["id"], "1978-05-31", "1978-06-02", "FORECLOSURE"
        )
        _propose_period(site["id"], prp_b["id"], "1995-01-01", None, "PURCHASE")
        _propose_period(site["id"], prp_a["id"], "2000-01-01", "2001-01-01", "PURCHASE")

        assert read_party(prp_a["id"])["ownership_days_total"] == 5936
        assert read_party(prp_b["id"])["ownership_days_total"] == 2_929_823

        rows, meta = validate_paginated(
            api_client.list_site_ownership_periods(site["id"], AUTHOR, {"limit": 50})
        )
        assert_pagination_meta(meta, total_count=4)
        assert len(rows) == 4


def _kestrel_flats_awarded_contract():
    """A signed remedy and an awarded contract allowing two concurrent windows."""
    set_clock("2028-01-05T09:00:00Z")
    site = create_listed_site(
        name="Kestrel Flats Wood Treating", epa_region=8, hrs_score=47.80
    )
    investigation = create_investigation(
        site["id"],
        exposure_medium="SOIL",
        scope_summary="OU-1 creosote DNAPL and soil",
    )
    add_sample(
        investigation["id"], "SOIL", "BENZO_A_PYRENE", 30.0, "VALID",
        "2027-12-10T10:00:00Z", "LAB-K-0001",
    )
    submit_investigation(investigation["id"])
    review_investigation(investigation["id"], "APPROVE")
    alternative = add_alternative(
        investigation["id"],
        label="EXCAVATION_OFFSITE_DISPOSAL",
        capital_cost_cents=480_000_000,
        annual_om_cost_cents=6_000_000,
        om_years=30,
        discount_rate_bp=700,
        effectiveness_score=84,
        implementability_score=76,
    )
    rod = create_rod(
        site["id"],
        investigation["id"],
        comment_period_days=30,
        proposed_plan_summary="Excavate the DNAPL source area and dispose off site.",
    )
    open_comment_period(rod["id"])
    file_comment(
        rod["id"],
        commenter_name="Kestrel Flats Neighborhood Council",
        comment_text="Please schedule hauling outside school hours.",
    )
    set_clock("2028-02-10T09:00:00Z")
    sign_rod(
        rod["id"],
        alternative_id=alternative["id"],
        responsiveness_summary="Hauling limited to 09:00-15:00 on school days.",
    )
    contract = create_solicitation(
        site["id"],
        rod["id"],
        engineer_estimate_cents=500_000_000,
        solicitation_reference="SOL-2028-KFW-01",
    )
    award_contract(
        contract["id"],
        500_000_000,
        contractor_name="Kestrel Environmental Constructors",
        max_concurrent_windows=2,
    )
    return site, contract


def _propose_window(contract_id, activity_type, start_at, end_at, crew_size):
    return api_client.create_work_window(
        contract_id,
        factories.work_window_payload(
            activity_type=activity_type,
            start_at=start_at,
            end_at=end_at,
            crew_size=crew_size,
        ),
        make_contractor_headers(contract_id),
    )


class TestWorkWindowBufferedCapacity:
    def test_the_mobilisation_buffer_pads_each_window_by_four_hours_at_both_ends(self):
        """The buffered interval, not the raw one, is what contends.

        PRD: "The system derives `buffered_start_at` as the window's `start_at` moved 4 hours earlier and `buffered_end_at` as its `end_at` moved 4 hours later, and it is these mobilisation-buffered intervals — not the raw ones — that are tested for contention."

        Design: Difficulty/resource_temporal_overlap/work_window_buffered_capacity_counts_windows_six_hours_apart
        """
        _, contract = _kestrel_flats_awarded_contract()

        ww1 = validate_success(
            _propose_window(
                contract["id"], "CONSTRUCTION",
                "2029-03-01T08:00:00Z", "2029-03-01T16:00:00Z", 12,
            ),
            201,
        )
        assert ww1["buffered_start_at"].startswith("2029-03-01T04:00:00")
        assert ww1["buffered_end_at"].startswith("2029-03-01T20:00:00")

    def test_two_windows_six_raw_hours_apart_occupy_two_of_the_two_slots(self):
        """Padding makes non-overlapping raw intervals contend.

        PRD: "The buffer is what makes this non-obvious: two windows six hours apart do not overlap on their raw intervals, but they do overlap once each is padded by four hours on both sides."

        Design: Difficulty/resource_temporal_overlap/work_window_buffered_capacity_counts_windows_six_hours_apart
        """
        _, contract = _kestrel_flats_awarded_contract()
        add_work_window(
            contract["id"], "2029-03-01T08:00:00Z", "2029-03-01T16:00:00Z",
            activity_type="CONSTRUCTION", crew_size=12,
        )

        ww2 = validate_success(
            _propose_window(
                contract["id"], "CONSTRUCTION",
                "2029-03-01T22:00:00Z", "2029-03-02T06:00:00Z", 6,
            ),
            201,
        )
        assert ww2["buffered_start_at"].startswith("2029-03-01T18:00:00")
        assert ww2["buffered_end_at"].startswith("2029-03-02T10:00:00")
        assert read_contract(contract["id"])["work_window_count"] == 2

    def test_a_third_window_intersecting_both_exceeds_the_concurrency_limit(self):
        """The new window itself counts towards the limit.

        PRD: "If that count plus the new window itself would exceed the contract's `max_concurrent_windows`, the request is refused with `ERR_WORK_WINDOW_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/work_window_buffered_capacity_counts_windows_six_hours_apart
        """
        _, contract = _kestrel_flats_awarded_contract()
        add_work_window(
            contract["id"], "2029-03-01T08:00:00Z", "2029-03-01T16:00:00Z",
            activity_type="CONSTRUCTION", crew_size=12,
        )
        add_work_window(
            contract["id"], "2029-03-01T22:00:00Z", "2029-03-02T06:00:00Z",
            activity_type="CONSTRUCTION", crew_size=6,
        )

        validate_error(
            _propose_window(
                contract["id"], "LONG_TERM_MONITORING",
                "2029-03-01T19:00:00Z", "2029-03-01T21:00:00Z", 2,
            ),
            ApiErrorId.ERR_WORK_WINDOW_CAPACITY_EXCEEDED.value,
        )
        assert read_contract(contract["id"])["work_window_count"] == 2

    def test_buffered_adjacency_does_not_intersect_and_the_refusal_counted_nothing(self):
        """A buffered end instant meeting a buffered start instant is free.

        PRD: "The count of concurrent windows is the number of existing windows **on the same contract** whose buffered interval intersects the new window's buffered interval, treated as half-open: a window whose buffered end instant coincides exactly with another's buffered start instant does not intersect it."

        Design: Difficulty/resource_temporal_overlap/work_window_buffered_capacity_counts_windows_six_hours_apart
        """
        site, contract = _kestrel_flats_awarded_contract()
        add_work_window(
            contract["id"], "2029-03-01T08:00:00Z", "2029-03-01T16:00:00Z",
            activity_type="CONSTRUCTION", crew_size=12,
        )
        add_work_window(
            contract["id"], "2029-03-01T22:00:00Z", "2029-03-02T06:00:00Z",
            activity_type="CONSTRUCTION", crew_size=6,
        )
        _propose_window(
            contract["id"], "LONG_TERM_MONITORING",
            "2029-03-01T19:00:00Z", "2029-03-01T21:00:00Z", 2,
        )

        ww4 = validate_success(
            _propose_window(
                contract["id"], "MAINTENANCE_SHUTDOWN",
                "2029-03-02T14:00:00Z", "2029-03-02T18:00:00Z", 4,
            ),
            201,
        )
        assert ww4["buffered_start_at"].startswith("2029-03-02T10:00:00")

        after = read_contract(contract["id"])
        assert after["work_window_count"] == 3
        assert after["status"] == "AWARDED"
        rows, meta = validate_paginated(
            api_client.list_work_windows(contract["id"], AUTHOR, {"limit": 50})
        )
        assert_pagination_meta(meta, total_count=3)
        assert len(rows) == 3

        site_after = read_site(site["id"])
        assert site_after["listing_status"] == "CONSTRUCTION"
        assert site_after["cost_posture"] == "OPEN"
        assert site_after["total_response_cost_cents"] == 500_000_000
