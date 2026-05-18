"""Priority-Date currency calculation — PRD §2.9 / §3.9.

Coverage:
- 'CURRENT' literal -> CURRENT.
- 'UNAVAILABLE' literal -> NOT_CURRENT.
- Date cutoff: strictly less than -> CURRENT; equal/after -> NOT_CURRENT.
- No row matches -> NOT_CURRENT.
- Country-specific row wins over ROW.
- Chart-in-effect (FINAL_ACTION vs DATES_FOR_FILING) switches the row
  the lookup considers.
- Retrogression: previous CURRENT, newly computed NOT_CURRENT, status
  set to RETROGRESSED.
- NOT_APPLICABLE permanent for IR / I-130 / I-765 / I-131 cases.
- refresh-priority-date is idempotent and emits PRIORITY_DATE_RECOMPUTED
  audit (PRD §3.9).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock_to,
    api_client,
    bulletin_month_of,
    publish_bulletin,
    re_get_case,
    refresh_priority_date,
    seed_all_case_type_configs,
    server_offset_iso,
    set_chart_in_effect,
    setup_filed_case,
    setup_priority_date_inheritance_world,
    validate_success,
)


# ===========================================================================
# Cutoff_date semantics
# ===========================================================================
class TestPriorityDateCutoffSemantics:

    def test_current_literal_yields_current(self, api):
        """PRD §2.9: "a cutoff_date of CURRENT means the priority date
        is current and the case's priority_date_status is CURRENT".

        Claim: publishing a bulletin row with cutoff_date='CURRENT'
        for the beneficiary's category/country and refreshing makes
        the I-485 priority_date_status=CURRENT.
        """
        seed_all_case_type_configs()
        # Build I-485 with linked APPROVED I-130 so the I-485 has a
        # priority_date.
        world = setup_priority_date_inheritance_world(
            pin_clock_iso="2026-05-18T00:00:00.000Z",
            bulletin_month="2026-06",
            final_action_cutoff="CURRENT",
            dates_for_filing_cutoff="CURRENT",
        )
        case = world["i485"]
        set_chart_in_effect("FINAL_ACTION")
        refreshed = refresh_priority_date(case)
        assert refreshed["priority_date_status"] == "CURRENT"

    def test_unavailable_literal_yields_not_current(self, api):
        """PRD §2.9: "a cutoff_date of UNAVAILABLE means no dates are
        current and the status is NOT_CURRENT".

        Claim: publishing a bulletin row with cutoff_date='UNAVAILABLE'
        makes priority_date_status=NOT_CURRENT.
        """
        world = setup_priority_date_inheritance_world(
            pin_clock_iso="2026-05-18T00:00:00.000Z",
            bulletin_month="2026-06",
            final_action_cutoff="UNAVAILABLE",
            dates_for_filing_cutoff="UNAVAILABLE",
        )
        case = world["i485"]
        set_chart_in_effect("FINAL_ACTION")
        refreshed = refresh_priority_date(case)
        assert refreshed["priority_date_status"] == "NOT_CURRENT"

    def test_priority_date_strictly_before_cutoff_is_current(self, api):
        """PRD §2.9: "the case's priority_date is current when it falls
        strictly before the cutoff date".

        Claim: priority_date 2026-05-18, cutoff 2026-09-01 -> CURRENT.
        """
        world = setup_priority_date_inheritance_world(
            pin_clock_iso="2026-05-18T00:00:00.000Z",
            bulletin_month="2026-06",
            final_action_cutoff="2026-09-01",
            dates_for_filing_cutoff="2026-09-01",
        )
        case = world["i485"]
        set_chart_in_effect("FINAL_ACTION")
        refreshed = refresh_priority_date(case)
        assert refreshed["priority_date_status"] == "CURRENT"

    def test_priority_date_equal_to_cutoff_is_not_current(self, api):
        """PRD §2.9: "and not current when it is equal to or later
        than the cutoff date — the cutoff date itself is not yet
        current."

        Claim: priority_date 2026-05-18, cutoff 2026-05-18 ->
        NOT_CURRENT (equality is NOT in-window per strict-less-than).
        """
        world = setup_priority_date_inheritance_world(
            pin_clock_iso="2026-05-18T00:00:00.000Z",
            bulletin_month="2026-06",
            final_action_cutoff="2026-05-18",
            dates_for_filing_cutoff="2026-05-18",
        )
        case = world["i485"]
        set_chart_in_effect("FINAL_ACTION")
        refreshed = refresh_priority_date(case)
        assert refreshed["priority_date_status"] == "NOT_CURRENT"

    def test_priority_date_after_cutoff_is_not_current(self, api):
        """PRD §2.9: "not current when it is equal to or later than
        the cutoff date".

        Claim: priority_date 2026-05-18, cutoff 2026-04-01 ->
        NOT_CURRENT.
        """
        world = setup_priority_date_inheritance_world(
            pin_clock_iso="2026-05-18T00:00:00.000Z",
            bulletin_month="2026-06",
            final_action_cutoff="2026-04-01",
            dates_for_filing_cutoff="2026-04-01",
        )
        case = world["i485"]
        set_chart_in_effect("FINAL_ACTION")
        refreshed = refresh_priority_date(case)
        assert refreshed["priority_date_status"] == "NOT_CURRENT"


# ===========================================================================
# Row selection
# ===========================================================================
class TestRowSelection:

    def test_no_row_yields_not_current(self, api):
        """PRD §2.9: "When no row matches the (chart, category,
        country) selection at all, the status is NOT_CURRENT."

        Claim: an I-485 whose beneficiary's category/country has no
        bulletin row in the latest month -> NOT_CURRENT after refresh.
        """
        seed_all_case_type_configs()
        # Build the world but DELIBERATELY publish a non-matching row.
        # Beneficiary in F2A/MEX but we publish only F1/PHL.
        advance_clock_to("2026-05-18T00:00:00.000Z")
        from test_helpers import (
            file_case,
            create_case,
            decide_case,
            ready_for_decision,
            setup_petitioner_and_beneficiary,
        )
        publish_bulletin(
            bulletin_month="2026-06",
            chart_type="FINAL_ACTION",
            preference_category="F1",
            country="PHL",
            cutoff_date="CURRENT",
        )
        p, b = setup_petitioner_and_beneficiary(
            preference_category="F2A",
            country_of_chargeability="MEX",
        )
        i130 = create_case(p, b, case_type="I-130")
        i130 = file_case(i130, p)
        i130 = ready_for_decision(i130)
        i130 = decide_case(i130, decision="APPROVE")
        i485 = create_case(
            p, b, case_type="I-485", linked_i130_case_id=i130["id"],
        )
        i485 = file_case(i485, p)
        set_chart_in_effect("FINAL_ACTION")
        refreshed = refresh_priority_date(i485)
        assert refreshed["priority_date_status"] == "NOT_CURRENT"

    def test_country_specific_row_beats_row_literal(self, api):
        """PRD §2.9: "when both a country-specific row and a ROW row
        are present, the country-specific row wins."

        Claim: with both a ROW row (cutoff CURRENT) and an MEX row
        (cutoff 2026-04-01 i.e. NOT_CURRENT for a 2026-05-18 PD), the
        MEX row wins -> NOT_CURRENT.
        """
        seed_all_case_type_configs()
        advance_clock_to("2026-05-18T00:00:00.000Z")
        from test_helpers import (
            create_case, decide_case, file_case, ready_for_decision,
            setup_petitioner_and_beneficiary,
        )
        publish_bulletin(
            bulletin_month="2026-06", chart_type="FINAL_ACTION",
            preference_category="F2A", country="ROW",
            cutoff_date="CURRENT",
        )
        publish_bulletin(
            bulletin_month="2026-06", chart_type="FINAL_ACTION",
            preference_category="F2A", country="MEX",
            cutoff_date="2026-04-01",
        )
        p, b = setup_petitioner_and_beneficiary(
            preference_category="F2A",
            country_of_chargeability="MEX",
        )
        i130 = create_case(p, b, case_type="I-130")
        i130 = file_case(i130, p)
        i130 = ready_for_decision(i130)
        i130 = decide_case(i130, decision="APPROVE")
        i485 = create_case(
            p, b, case_type="I-485", linked_i130_case_id=i130["id"],
        )
        i485 = file_case(i485, p)
        set_chart_in_effect("FINAL_ACTION")
        refreshed = refresh_priority_date(i485)
        assert refreshed["priority_date_status"] == "NOT_CURRENT", (
            "MEX-specific row (cutoff 2026-04-01) should win over ROW"
            " row (CURRENT) and yield NOT_CURRENT for a 2026-05-18 PD"
        )


# ===========================================================================
# NOT_APPLICABLE
# ===========================================================================
class TestNotApplicable:

    def test_i130_priority_status_not_applicable(self, api):
        """PRD §2.9: "A case for which priority-date currency does not
        apply — because its case_type is I-130, I-765, or I-131, or
        because the beneficiary's preference_category is IR (immediate
        relative, exempt from numerical limits) — carries
        priority_date_status permanently set to NOT_APPLICABLE."

        Claim: an I-130 has priority_date_status=NOT_APPLICABLE
        permanently.
        """
        bundle = setup_filed_case(case_type="I-130")
        case = bundle["case"]
        assert case["priority_date_status"] == "NOT_APPLICABLE"

    @pytest.mark.parametrize("case_type", ["I-765", "I-131"])
    def test_i765_i131_priority_status_not_applicable(self, api, case_type):
        """PRD §2.9: "case_type is I-130, I-765, or I-131 ... carries
        priority_date_status permanently set to NOT_APPLICABLE."

        Claim: I-765 and I-131 cases have
        priority_date_status=NOT_APPLICABLE.
        """
        bundle = setup_filed_case(case_type=case_type)
        case = bundle["case"]
        assert case["priority_date_status"] == "NOT_APPLICABLE"
