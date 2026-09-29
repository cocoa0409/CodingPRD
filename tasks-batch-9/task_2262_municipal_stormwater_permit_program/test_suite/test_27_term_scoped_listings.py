"""Term-scoped child listings: how a filter, a page window and total_count
interact on the outfall, construction-site and annual-report collections."""

import pytest
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.test_users import (
    INSPECTOR_HEADERS,
    MANAGER_HEADERS,
    OFFICER_HEADERS,
    OPERATIONS_HEADERS,
)

OUTFALL_FIELDS = {
    "receiving_water": "Mill Creek",
    "drainage_area_acres": 45.00,
    "baseline_concentration_mg_per_l": 0.45,
    "design_runoff_kl": 20000,
    "sweeping_capacity_lane_miles_per_month": 40.00,
}
TIERS = {
    "OF-01": "HIGH",
    "OF-02": "HIGH",
    "OF-03": "MEDIUM",
    "OF-04": "LOW",
    "OF-05": "HIGH",
}


def _codes(rows):
    """The outfall codes of a page, in the order the server returned them."""
    return [row["outfall_code"] for row in rows]


class TestTheOutfallListingPagesAFilteredSet:
    """Five outfalls, one retired, and six different views of them."""

    @pytest.fixture
    def inventory(self):
        """An ACTIVE term with OF-01 through OF-05, OF-04 retired after activation."""
        term = fx.create_permit_term(funding_target_cents=25000)
        fx.register_standard_measure_set(term["id"])
        outfalls = {
            code: fx.create_outfall(
                term["id"], code, priority_tier=tier, **OUTFALL_FIELDS
            )
            for code, tier in TIERS.items()
        }
        validate_success(api_client.activate_permit_term(term["id"], MANAGER_HEADERS))
        validate_success(
            api_client.retire_outfall(outfalls["OF-04"]["id"], MANAGER_HEADERS)
        )
        return {"term_id": term["id"], "outfalls": outfalls}

    def test_01_the_unfiltered_page_holds_every_row_including_the_retired_one(
        self, inventory
    ):
        """Retirement is a status, not a deletion, so all five are listed.

        PRD: "`limit` is the maximum number of rows returned; it defaults to 10, has a
        minimum of 1 and a maximum of 100." And: "Every list response reports `limit`,
        `offset`, `total_count` and `has_more` in the `meta` object of the envelope." And:
        "Unless a narrative says otherwise, list endpoints return rows sorted by
        `created_at` in ascending order." And: "Retirement writes `RETIRED` into `status`,
        which removes the row from annual screening-coverage denominators and from the
        annual net load total, recomputes the term's `exceeding_outfall_count` and
        `compliance_posture`, and increments the outfall's `version` by one."

        Design: Corner/endpoints/nested_listing_pages_and_filters_interact_and_total_count_follows_the_filter
        """
        rows, meta = validate_paginated(
            api_client.list_term_outfalls(inventory["term_id"], OPERATIONS_HEADERS)
        )

        assert _codes(rows) == ["OF-01", "OF-02", "OF-03", "OF-04", "OF-05"], (
            f"all five in creation order, got {_codes(rows)}"
        )
        assert meta["limit"] == 10, f"the default page size is 10, got {meta['limit']}"
        assert meta["offset"] == 0, f"the default offset is 0, got {meta['offset']}"
        assert meta["total_count"] == 5, (
            f"the whole inventory is counted, got {meta['total_count']}"
        )
        assert meta["has_more"] is False, "one page holds them all"
        retired = [row for row in rows if row["outfall_code"] == "OF-04"][0]
        assert retired["status"] == "RETIRED", "and the retired row is still listed"

    def test_02_an_offset_walks_into_the_middle_of_the_unfiltered_set(self, inventory):
        """Skipping two of five leaves more behind the page.

        PRD: "`offset` is the number of rows skipped before the page begins; it defaults
        to 0 and may not be negative." And: "Every list response reports `limit`,
        `offset`, `total_count` and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/nested_listing_pages_and_filters_interact_and_total_count_follows_the_filter
        """
        rows, meta = validate_paginated(
            api_client.list_term_outfalls(
                inventory["term_id"], OPERATIONS_HEADERS, {"limit": 2, "offset": 2}
            )
        )

        assert _codes(rows) == ["OF-03", "OF-04"], (
            f"the third and fourth rows, got {_codes(rows)}"
        )
        assert meta["total_count"] == 5, (
            f"the count ignores the page window, got {meta['total_count']}"
        )
        assert meta["has_more"] is True, "OF-05 is still waiting"

    def test_03_the_filter_is_applied_before_the_page_window(self, inventory):
        """Three HIGH outfalls, offset two, so one row and nothing more.

        PRD: "Collections accept optional equality filters, and a filter that is omitted
        does not narrow the result." And: "Permit terms filter on `status` and
        `compliance_posture`. A term's control measures filter on `measure_code`, `status`
        and `goal_status`; its outfalls on `screening_status`, `tmdl_status`, `status` and
        `priority_tier`; its construction sites on `plan_status` and `field_status`; its
        accounts on `parcel_class`; its annual reports on `status`."

        Design: Corner/endpoints/nested_listing_pages_and_filters_interact_and_total_count_follows_the_filter
        """
        rows, meta = validate_paginated(
            api_client.list_term_outfalls(
                inventory["term_id"],
                OPERATIONS_HEADERS,
                {"priority_tier": "HIGH", "limit": 2, "offset": 2},
            )
        )

        assert _codes(rows) == ["OF-05"], (
            f"the third HIGH row and no other, got {_codes(rows)}"
        )
        assert meta["total_count"] == 3, (
            f"the count follows the filter, not the table, got {meta['total_count']}"
        )
        assert meta["has_more"] is False, "the filtered set is exhausted"

    def test_04_a_status_filter_selects_the_single_retired_row(self, inventory):
        """One of the five carries RETIRED, and the count says so.

        PRD: "Collections accept optional equality filters, and a filter that is omitted
        does not narrow the result." And: "Retirement writes `RETIRED` into `status`, which
        removes the row from annual screening-coverage denominators and from the annual net
        load total, recomputes the term's `exceeding_outfall_count` and
        `compliance_posture`, and increments the outfall's `version` by one."

        Design: Corner/endpoints/nested_listing_pages_and_filters_interact_and_total_count_follows_the_filter
        """
        rows, meta = validate_paginated(
            api_client.list_term_outfalls(
                inventory["term_id"], OPERATIONS_HEADERS, {"status": "RETIRED"}
            )
        )

        assert meta["total_count"] == 1, (
            f"exactly one outfall was retired, got {meta['total_count']}"
        )
        assert _codes(rows) == ["OF-04"], f"and it is OF-04, got {_codes(rows)}"
        assert rows[0]["id"] == inventory["outfalls"]["OF-04"]["id"], (
            "the row is the one that was retired"
        )

    def test_05_two_filters_combine_conjunctively(self, inventory):
        """Never screened and MEDIUM tier together single out OF-03.

        PRD: "Collections accept optional equality filters, and a filter that is omitted
        does not narrow the result." And: "Permit terms filter on `status` and
        `compliance_posture`. A term's control measures filter on `measure_code`, `status`
        and `goal_status`; its outfalls on `screening_status`, `tmdl_status`, `status` and
        `priority_tier`; its construction sites on `plan_status` and `field_status`; its
        accounts on `parcel_class`; its annual reports on `status`."

        Design: Corner/endpoints/nested_listing_pages_and_filters_interact_and_total_count_follows_the_filter
        """
        rows, meta = validate_paginated(
            api_client.list_term_outfalls(
                inventory["term_id"],
                OPERATIONS_HEADERS,
                {"screening_status": "NOT_SCREENED", "priority_tier": "MEDIUM"},
            )
        )

        assert meta["total_count"] == 1, (
            f"only OF-03 answers both filters, got {meta['total_count']}"
        )
        assert _codes(rows) == ["OF-03"], f"and it is OF-03, got {_codes(rows)}"

    def test_06_an_offset_past_the_end_is_an_empty_page_not_an_error(self, inventory):
        """Skipping all five rows is legal and leaves nothing more.

        PRD: "`offset` is the number of rows skipped before the page begins; it defaults
        to 0 and may not be negative." And: "Every list response reports `limit`,
        `offset`, `total_count` and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/nested_listing_pages_and_filters_interact_and_total_count_follows_the_filter
        """
        rows, meta = validate_paginated(
            api_client.list_term_outfalls(
                inventory["term_id"], OPERATIONS_HEADERS, {"offset": 5}
            )
        )

        assert rows == [], f"the page is empty, got {_codes(rows)}"
        assert meta["total_count"] == 5, (
            f"the count still reports the whole set, got {meta['total_count']}"
        )
        assert meta["has_more"] is False, "there is nothing beyond the end"


class TestSiteListingsExposeBothDimensionsSeparately:
    """Three sites at three plan states, and one report filtered by status."""

    @pytest.fixture
    def three_sites(self, active_program):
        """SITE-A submitted, SITE-B approved and disturbed, SITE-C returned."""
        term_id = active_program["term_id"]
        site_a = fx.create_site(
            term_id,
            site_name="SITE-A",
            operator_name="Northgate Civil",
            disturbed_acres=1.50,
        )
        site_b = fx.create_site(
            term_id,
            site_name="SITE-B",
            operator_name="Southline Build",
            disturbed_acres=3.00,
        )
        site_c = fx.create_site(
            term_id,
            site_name="SITE-C",
            operator_name="Eastworks Civil",
            disturbed_acres=1.20,
        )
        for site, reference, decision in [
            (site_b, "ESC-B", "APPROVE"),
            (site_c, "ESC-C", "RETURN"),
        ]:
            validate_success(
                api_client.submit_esc_plan(
                    site["id"],
                    factories.submit_esc_plan_payload(reference),
                    INSPECTOR_HEADERS,
                )
            )
            validate_success(
                api_client.esc_review(
                    site["id"],
                    factories.esc_review_payload(decision),
                    INSPECTOR_HEADERS,
                )
            )
        report = validate_success(
            api_client.create_annual_report(
                factories.annual_report_payload(term_id, "2026-01-01", "2026-12-31"),
                MANAGER_HEADERS,
            ),
            201,
        )
        return {
            "term_id": term_id,
            "site_a": site_a,
            "site_b": site_b,
            "site_c": site_c,
            "report": report,
        }

    def test_07_the_unfiltered_listing_shows_the_three_plan_states(self, three_sites):
        """Only the approved plan carried its site into disturbance.

        PRD: "`plan_status` tracks erosion and sediment control plan review through
        `SUBMITTED`, `ESC_REVIEW`, `RETURNED` and `APPROVED`, starting at `SUBMITTED`; it
        is cyclic through `RETURNED`. `field_status` tracks the physical condition of the
        site through `PRE_CONSTRUCTION`, `ACTIVE_DISTURBANCE`, `STOP_WORK` and `CLOSED`,
        starting at `PRE_CONSTRUCTION`, with `CLOSED` terminal." And: "`APPROVE` writes
        `APPROVED` into `plan_status` and, if and only if `field_status` is still
        `PRE_CONSTRUCTION`, additionally advances `field_status` to `ACTIVE_DISTURBANCE` —
        the point at which the site becomes eligible for erosion-control inspections."

        Design: Corner/endpoints/term_scoped_child_listings_filter_sites_by_dimension_and_reports_by_status
        """
        rows, meta = validate_paginated(
            api_client.list_term_construction_sites(
                three_sites["term_id"], INSPECTOR_HEADERS
            )
        )

        assert meta["total_count"] == 3, (
            f"three sites are enrolled, got {meta['total_count']}"
        )
        assert meta["has_more"] is False, "one page holds them"
        by_name = {row["site_name"]: row for row in rows}
        assert by_name["SITE-A"]["plan_status"] == "SUBMITTED", "SITE-A awaits review"
        assert by_name["SITE-B"]["plan_status"] == "APPROVED", "SITE-B is approved"
        assert by_name["SITE-C"]["plan_status"] == "RETURNED", "SITE-C came back"
        assert by_name["SITE-A"]["field_status"] == "PRE_CONSTRUCTION", (
            "an unreviewed plan leaves the ground untouched"
        )
        assert by_name["SITE-C"]["field_status"] == "PRE_CONSTRUCTION", (
            "a returned plan leaves the ground untouched"
        )
        assert by_name["SITE-B"]["field_status"] == "ACTIVE_DISTURBANCE", (
            "approval advanced the field dimension of SITE-B"
        )

    def test_08_the_plan_dimension_filters_on_its_own(self, three_sites):
        """One of the three plans is APPROVED.

        PRD: "Permit terms filter on `status` and `compliance_posture`. A term's control
        measures filter on `measure_code`, `status` and `goal_status`; its outfalls on
        `screening_status`, `tmdl_status`, `status` and `priority_tier`; its construction
        sites on `plan_status` and `field_status`; its accounts on `parcel_class`; its
        annual reports on `status`."

        Design: Corner/endpoints/term_scoped_child_listings_filter_sites_by_dimension_and_reports_by_status
        """
        rows, meta = validate_paginated(
            api_client.list_term_construction_sites(
                three_sites["term_id"], INSPECTOR_HEADERS, {"plan_status": "APPROVED"}
            )
        )

        assert meta["total_count"] == 1, (
            f"one approved plan, got {meta['total_count']}"
        )
        assert rows[0]["id"] == three_sites["site_b"]["id"], "and it is SITE-B"

    def test_09_the_two_dimensions_combine_conjunctively(self, three_sites):
        """A returned plan over untouched ground is SITE-C alone.

        PRD: "Each site carries **two independent state dimensions on the same row**, and
        most operations move exactly one of them." And: "Collections accept optional
        equality filters, and a filter that is omitted does not narrow the result."

        Design: Corner/endpoints/term_scoped_child_listings_filter_sites_by_dimension_and_reports_by_status
        """
        rows, meta = validate_paginated(
            api_client.list_term_construction_sites(
                three_sites["term_id"],
                OFFICER_HEADERS,
                {"plan_status": "RETURNED", "field_status": "PRE_CONSTRUCTION"},
            )
        )

        assert meta["total_count"] == 1, (
            f"only SITE-C answers both, got {meta['total_count']}"
        )
        assert rows[0]["id"] == three_sites["site_c"]["id"], "and it is SITE-C"

    def test_10_a_filter_matching_nothing_returns_an_empty_set(self, three_sites):
        """No site has been closed, and the count is 0 rather than 3.

        PRD: "Collections accept optional equality filters, and a filter that is omitted
        does not narrow the result." And: "Closing the file is the inspector's act,
        carrying a `final_stabilization_note`, and moves `field_status` from
        `ACTIVE_DISTURBANCE` to `CLOSED`."

        Design: Corner/endpoints/term_scoped_child_listings_filter_sites_by_dimension_and_reports_by_status
        """
        rows, meta = validate_paginated(
            api_client.list_term_construction_sites(
                three_sites["term_id"], INSPECTOR_HEADERS, {"field_status": "CLOSED"}
            )
        )

        assert rows == [], "no closed site exists"
        assert meta["total_count"] == 0, (
            f"the empty filtered set counts 0, got {meta['total_count']}"
        )

        paged_rows, paged_meta = validate_paginated(
            api_client.list_term_construction_sites(
                three_sites["term_id"], INSPECTOR_HEADERS, {"limit": 1, "offset": 1}
            )
        )
        assert len(paged_rows) == 1, "an unfiltered page of one holds one row"
        assert paged_meta["total_count"] == 3, "over a set of three"
        assert paged_meta["has_more"] is True, "with a third row still to come"

    def test_11_the_report_listing_filters_on_report_status(self, three_sites):
        """The one report is DRAFT, so DRAFT finds it and SUBMITTED does not.

        PRD: "Permit terms filter on `status` and `compliance_posture`. A term's control
        measures filter on `measure_code`, `status` and `goal_status`; its outfalls on
        `screening_status`, `tmdl_status`, `status` and `priority_tier`; its construction
        sites on `plan_status` and `field_status`; its accounts on `parcel_class`; its
        annual reports on `status`." And: "A new report has `status` `DRAFT`, every
        statistic at its zero value, `invalidation_count` at 0, and `compiled_at`,
        `compiled_by_user_id`, `certified_at`, `certified_by_user_id`,
        `certification_statement`, `submitted_at` and `invalidated_reason` all null."

        Design: Corner/endpoints/term_scoped_child_listings_filter_sites_by_dimension_and_reports_by_status
        """
        drafts, draft_meta = validate_paginated(
            api_client.list_term_annual_reports(
                three_sites["term_id"], OPERATIONS_HEADERS, {"status": "DRAFT"}
            )
        )
        assert draft_meta["total_count"] == 1, (
            f"one draft report, got {draft_meta['total_count']}"
        )
        assert drafts[0]["id"] == three_sites["report"]["id"], "and it is the one opened"
        assert drafts[0]["compliance_index"] == pytest.approx(0.00, abs=0.01), (
            f"nothing compiled yet, got {drafts[0]['compliance_index']}"
        )
        assert drafts[0]["invalidation_count"] == 0, "and never invalidated"

        submitted, submitted_meta = validate_paginated(
            api_client.list_term_annual_reports(
                three_sites["term_id"], OPERATIONS_HEADERS, {"status": "SUBMITTED"}
            )
        )
        assert submitted == [], "nothing has been submitted"
        assert submitted_meta["total_count"] == 0, (
            f"and the count agrees, got {submitted_meta['total_count']}"
        )
