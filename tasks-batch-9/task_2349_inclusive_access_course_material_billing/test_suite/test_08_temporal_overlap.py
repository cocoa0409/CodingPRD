"""Two different overlap domains: half-open calendar windows on a capacity-limited
section, and closed integer bands on a title where a null upper bound is infinite.
"""

from test_helpers import (
    AdoptionStatus,
    ApiErrorId,
    SectionIaStatus,
    assert_money,
    factories,
    fixtures,
    make_faculty_headers,
    make_program_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CHEM_SECTION = {
    "subject_code": "CHEM",
    "catalog_number": "105",
    "section_number": "001",
    "instructor_user_id": "fac-6",
    "max_concurrent_titles": 1,
}
ESSENTIALS_TITLE = {
    "isbn": "978-0-11-000005-0",
    "title": "Economics Essentials",
    "list_price_cents": 12000,
}
PROBLEM_SETS_TITLE = {
    "isbn": "978-0-11-000007-0",
    "title": "Chemistry Problem Sets",
    "list_price_cents": 9000,
}
FIRST_WINDOW = {"access_start_date": "2026-08-24", "access_end_date": "2026-10-01"}
TOUCHING_WINDOW = {"access_start_date": "2026-10-01", "access_end_date": "2026-12-12"}
STRADDLING_WINDOW = {"access_start_date": "2026-09-30", "access_end_date": "2026-10-02"}


class TestHalfOpenWindowsAgainstConcurrentCapacity:
    """A cap of one concurrent title tolerates touching windows, not shared days."""

    @staticmethod
    def _capped_section_with_a_touching_second_window(api):
        catalog = fixtures.setup_catalog(
            api, setup_clock="2026-07-05T00:00:00Z", bands=((1, 2, 9000),)
        )
        essentials, _ = fixtures.create_priced_title(
            api, catalog["agreement_id"], ((1, 2, 6000),), **ESSENTIALS_TITLE
        )
        problem_sets, _ = fixtures.create_priced_title(
            api, catalog["agreement_id"], ((1, None, 4000),), **PROBLEM_SETS_TITLE
        )

        section = fixtures.create_section(api, catalog["term_id"], **CHEM_SECTION)
        first = fixtures.create_approved_adoption(
            api, section["id"], catalog["title_id"], section["version"],
            instructor_user_id="fac-6", **FIRST_WINDOW
        )
        touching = fixtures.create_adoption(
            api, section["id"], essentials["id"], instructor_user_id="fac-6",
            **TOUCHING_WINDOW
        )
        fixtures.submit_adoption(api, touching["id"], "fac-6")

        return {
            "term_id": catalog["term_id"],
            "section_id": section["id"],
            "first_id": first["id"],
            "touching_id": touching["id"],
            "problem_sets_id": problem_sets["id"],
        }

    def test_windows_that_merely_touch_both_reach_approved(self, api, program_admin):
        """PRD §3.3: "Windows that merely touch do not overlap: an earlier adoption
        whose `access_end_date` equals a later adoption's `access_start_date`
        contributes nothing to the later window's count."

        Design: Difficulty/resource_temporal_overlap/temporal_overlap_half_open_access_windows_versus_concurrent_title_capacity
        """
        scenario = self._capped_section_with_a_touching_second_window(api)

        approved = fixtures.approve_adoption(api, scenario["touching_id"])
        assert approved["status"] == AdoptionStatus.APPROVED.value
        assert_money(approved["locked_list_price_cents"], 12000)

        adoptions, meta = validate_paginated(
            api.list_adoptions(program_admin, {"section_id": scenario["section_id"]})
        )
        assert meta["total_count"] == 2
        assert all(adoption["status"] == AdoptionStatus.APPROVED.value
                   for adoption in adoptions)

        section = fixtures.read_section(api, scenario["section_id"])
        assert section["max_concurrent_titles"] == 1
        assert section["ia_status"] == SectionIaStatus.NOT_FLAGGED.value

    def test_one_shared_interior_day_is_enough_to_breach_the_cap(self, api,
                                                                program_admin):
        """PRD §3.3: "For every calendar date in the candidate's half-open window —
        from `access_start_date` inclusive up to but excluding `access_end_date` —
        the system counts the approved adoptions on that section whose own
        half-open window contains that date, including the candidate being
        approved."

        Design: Difficulty/resource_temporal_overlap/temporal_overlap_half_open_access_windows_versus_concurrent_title_capacity
        """
        scenario = self._capped_section_with_a_touching_second_window(api)
        fixtures.approve_adoption(api, scenario["touching_id"])

        straddling = fixtures.create_adoption(
            api, scenario["section_id"], scenario["problem_sets_id"],
            instructor_user_id="fac-6", **STRADDLING_WINDOW
        )
        fixtures.submit_adoption(api, straddling["id"], "fac-6")

        # 2026-09-30 is covered by the first window and 2026-10-01 by the second,
        # so on both dates the count would be 2 against a cap of 1.
        response = api.approve_adoption(straddling["id"], program_admin)
        validate_error(response, ApiErrorId.CONCURRENT_TITLE_LIMIT.value)

        refused = fixtures.read_adoption(api, straddling["id"])
        assert refused["status"] == AdoptionStatus.SUBMITTED.value
        assert refused["locked_list_price_cents"] is None

        section = fixtures.read_section(api, scenario["section_id"])
        assert section["max_concurrent_titles"] == 1
        assert section["ia_status"] == SectionIaStatus.NOT_FLAGGED.value

    def test_an_empty_window_and_an_over_long_window_never_author_at_all(self, api):
        """PRD §2.4: "The access window is validated as a half-open interval inside
        the term: `access_end_date` must be strictly later than
        `access_start_date`, `access_start_date` must not be earlier than the
        term's `term_start_date`, and `access_end_date` must not be later than the
        day after the term's `term_end_date`."

        Design: Difficulty/resource_temporal_overlap/temporal_overlap_half_open_access_windows_versus_concurrent_title_capacity
        """
        scenario = self._capped_section_with_a_touching_second_window(api)
        version = fixtures.section_version(api, scenario["section_id"])
        headers = make_faculty_headers("fac-6")

        # An empty window is not a zero-day window.
        response = api.create_adoption(
            factories.adoption_payload(
                scenario["section_id"], scenario["problem_sets_id"], version,
                access_start_date="2026-10-01", access_end_date="2026-10-01",
            ),
            headers,
        )
        validate_error(response, ApiErrorId.ACCESS_WINDOW_INVALID.value)

        # The term ends 2026-12-11, so the last legal exclusive end is 2026-12-12.
        response = api.create_adoption(
            factories.adoption_payload(
                scenario["section_id"], scenario["problem_sets_id"], version,
                access_start_date="2026-08-24", access_end_date="2026-12-13",
            ),
            headers,
        )
        validate_error(response, ApiErrorId.ACCESS_WINDOW_INVALID.value)


class TestPricingBandAdjacencyAgainstOverlap:
    """Closed integer bands, where a null upper bound means every later band collides."""

    @staticmethod
    def _draft_agreement_with_one_band(api):
        fixtures.set_clock(api, "2026-07-01T00:00:00Z")
        agreement = fixtures.create_agreement(api)
        title = fixtures.create_title(api, agreement["id"])
        first = fixtures.add_pricing_band(api, title["id"], (1, 2, 9000))
        return {"title_id": title["id"], "first_tier_id": first["id"]}

    def test_adjacency_is_accepted_and_a_single_shared_point_is_not(self, api):
        """PRD §2.3: "Adjacency is legal and is in fact the intended pattern — a
        band starting exactly one above an existing band's upper bound does not
        overlap it."

        Design: Difficulty/resource_temporal_overlap/temporal_overlap_pricing_tier_bands_adjacent_versus_overlapping
        """
        scenario = self._draft_agreement_with_one_band(api)

        # [3,5] starts exactly one above the upper bound of [1,2].
        adjacent = validate_success(
            api.create_pricing_tier(
                scenario["title_id"],
                factories.pricing_tier_payload(min_enrollment=3, max_enrollment=5,
                                               per_student_price_cents=8000),
                make_program_admin_headers(),
            ),
            expected_status=201,
        )
        assert adjacent["min_enrollment"] == 3
        assert adjacent["max_enrollment"] == 5

        # [5,8] shares exactly the single point 5 with [3,5].
        response = api.create_pricing_tier(
            scenario["title_id"],
            factories.pricing_tier_payload(min_enrollment=5, max_enrollment=8,
                                           per_student_price_cents=7600),
            make_program_admin_headers(),
        )
        validate_error(response, ApiErrorId.TIER_BAND_OVERLAP.value)

    def test_an_unbounded_band_swallows_every_higher_band(self, api, program_admin):
        """PRD §2.3: "Bands of one title may never overlap: a candidate band is
        rejected with `ERR_TIER_BAND_OVERLAP` when the candidate's lower bound is
        less than or equal to an existing band's upper bound *and* that existing
        band's lower bound is less than or equal to the candidate's upper bound,
        treating a null upper bound as unbounded on either side."

        Design: Difficulty/resource_temporal_overlap/temporal_overlap_pricing_tier_bands_adjacent_versus_overlapping
        """
        scenario = self._draft_agreement_with_one_band(api)
        fixtures.add_pricing_band(api, scenario["title_id"], (3, 5, 8000))

        unbounded = validate_success(
            api.create_pricing_tier(
                scenario["title_id"],
                factories.pricing_tier_payload(min_enrollment=6,
                                               max_enrollment=None,
                                               per_student_price_cents=7000),
                make_program_admin_headers(),
            ),
            expected_status=201,
        )
        assert unbounded["max_enrollment"] is None

        # 9 sits far above 6, but [6,null] reaches it.
        response = api.create_pricing_tier(
            scenario["title_id"],
            factories.pricing_tier_payload(min_enrollment=9,
                                           max_enrollment=None,
                                           per_student_price_cents=6500),
            make_program_admin_headers(),
        )
        validate_error(response, ApiErrorId.TIER_BAND_OVERLAP.value)

        # The single-point band [2,2] is wholly contained in [1,2].
        response = api.create_pricing_tier(
            scenario["title_id"],
            factories.pricing_tier_payload(min_enrollment=2, max_enrollment=2,
                                           per_student_price_cents=8800),
            make_program_admin_headers(),
        )
        validate_error(response, ApiErrorId.TIER_BAND_OVERLAP.value)

        tiers, meta = validate_paginated(
            api.list_title_pricing_tiers(scenario["title_id"], program_admin)
        )
        assert meta["total_count"] == 3
        bands = sorted(
            (tier["min_enrollment"], tier["max_enrollment"],
             tier["per_student_price_cents"])
            for tier in tiers
        )
        assert bands == [(1, 2, 9000), (3, 5, 8000), (6, None, 7000)]

        _, reverse_meta = validate_paginated(
            api.list_pricing_tiers(program_admin,
                                   {"title_id": scenario["title_id"]})
        )
        assert reverse_meta["total_count"] == 3
