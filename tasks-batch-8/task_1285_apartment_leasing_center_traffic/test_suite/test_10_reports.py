"""Closing-ratio report: the ALL and QUALIFIED bases diverge on the same inquiry
set, grouped by assigned agent and lead source over a half-open window."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_executed_lease,
    assert_same_instant,
    create_contacted_inquiry,
    create_inquiry,
    claim_inquiry,
    setup_site,
    validate_success,
)

PM = TEST_USERS["property_manager_headers"]

WINDOW_START = "2026-08-01T00:00:00Z"
WINDOW_END = "2026-09-01T00:00:00Z"


def _closing_scenario():
    """One agent, one property: three WEB_FORM inquiries (one responded and
    converted end-to-end, one responded only, one claimed only) plus one PHONE
    inquiry (responded, never closed). Returns (property, agent)."""
    site = setup_site(floorplan_overrides={"base_rent_cents": 200000,
                                           "total_units": 3})
    agent_id = site["agent"]["id"]
    # I1: claimed + responded (qualified, never closed).
    create_contacted_inquiry(site["property"]["id"], agent_id,
                             floorplan_id=site["floorplan"]["id"],
                             contact_name="I1", contact_email="i1@x.com",
                             source="WEB_FORM")
    # I2: claimed + responded + executed lease (closed -> CONVERTED).
    add_executed_lease(site, inquiry_overrides={"contact_name": "I2",
                                                "contact_email": "i2@x.com",
                                                "source": "WEB_FORM"})
    # I3: claimed only, never responded (unqualified).
    inquiry3 = create_inquiry(site["property"]["id"], agent_id=agent_id,
                              floorplan_id=site["floorplan"]["id"],
                              contact_name="I3", contact_email="i3@x.com",
                              source="WEB_FORM")
    claim_inquiry(inquiry3["id"], agent_id)
    # I4: claimed + responded, PHONE source (qualified, not closed).
    create_contacted_inquiry(site["property"]["id"], agent_id,
                             floorplan_id=site["floorplan"]["id"],
                             contact_name="I4", contact_email="i4@x.com",
                             source="PHONE")
    return site


def _report(api, property_id, basis):
    return validate_success(api.get_closing_report(
        PM, params={"property_id": property_id, "window_start": WINDOW_START,
                    "window_end": WINDOW_END, "basis": basis}))


class TestClosingRatioBases:
    def test_closing_ratio_basis_all_counts_every_assigned_inquiry(self, api):
        """PRD §3.8: "Under basis `ALL`, the denominator counts every assigned
        inquiry of the group inside the window, even ones never contacted."
        PRD §3.8: "The reported ratio, `closing_ratio_pct`, is one hundred times the
        closed count divided by the denominator, rounded half-up to one decimal
        place, and groups whose denominator is zero are omitted from the response
        entirely."
        PRD §3.8: "The response echoes the request's `property_id`, `window_start`,
        `window_end`, and `basis`, and carries the computed `rows`."

        Design: Difficulty/dual_variant_calc/closing_ratio_all_vs_qualified_basis_diverge
        """
        site = _closing_scenario()
        report = _report(api, site["property"]["id"], "ALL")
        assert report["property_id"] == site["property"]["id"]
        assert report["basis"] == "ALL"
        assert_same_instant(report["window_start"], WINDOW_START, label="window_start")
        assert_same_instant(report["window_end"], WINDOW_END, label="window_end")

        ratios = sorted(row["closing_ratio_pct"] for row in report["rows"])
        # WEB_FORM group: 1 closed / 3 assigned -> 33.3; PHONE group: 0 / 1 -> 0.0.
        assert ratios == [pytest.approx(0.0, abs=0.05),
                          pytest.approx(33.3, abs=0.05)]

    def test_closing_ratio_basis_qualified_counts_only_responded(self, api):
        """PRD §3.8: "Under basis `QUALIFIED`, the denominator counts only group
        inquiries with a recorded `first_responded_at`, so the qualified basis
        produces a strictly larger ratio whenever uncontacted inquiries exist in the
        window."
        PRD §3.8: "The reported ratio, `closing_ratio_pct`, is one hundred times the
        closed count divided by the denominator, rounded half-up to one decimal
        place, and groups whose denominator is zero are omitted from the response
        entirely."

        Design: Difficulty/dual_variant_calc/closing_ratio_all_vs_qualified_basis_diverge
        """
        site = _closing_scenario()
        qualified = _report(api, site["property"]["id"], "QUALIFIED")
        ratios_q = sorted(row["closing_ratio_pct"] for row in qualified["rows"])
        # WEB_FORM group: 1 closed / 2 responded -> 50.0; PHONE group: 0 / 1 -> 0.0.
        assert ratios_q == [pytest.approx(0.0, abs=0.05),
                            pytest.approx(50.0, abs=0.05)]

        # The two bases diverge on the identical underlying data: the ALL variant
        # of the WEB_FORM group is 1/3 = 33.3, strictly smaller than 50.0.
        all_report = _report(api, site["property"]["id"], "ALL")
        ratios_all = sorted(row["closing_ratio_pct"] for row in all_report["rows"])
        assert ratios_all[1] == pytest.approx(33.3, abs=0.05)
        assert ratios_q[1] != ratios_all[1]
