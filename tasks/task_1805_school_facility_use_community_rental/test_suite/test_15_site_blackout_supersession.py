"""A school calendar event with facility_id null is a site-wide blackout: one
tier-0 event supersedes ISSUED permits on every facility of the site — an
aggregate semantic, not per-facility interval arithmetic (PRD §3.1, §3.7)."""
import pytest

from test_helpers import (
    validate_success,
    invoice_of_kind,
    make_site, make_facility, make_policy,
    add_renter_with_insurance,
    make_approved_permit_in_env, make_calendar_event,
    get_single_work_order,
    api_client,
    TEST_USERS,
)

DIRECTOR = TEST_USERS["director_headers"]

NP_STD_POLICY = {
    "policy_code": "NP-STD", "rate_class": "NONPROFIT", "facility_tier": "STANDARD",
    "hourly_rate_cents": 5000, "deposit_basis_points": 2000,
    "custodial_hourly_cents": 4000, "effective_from": "2026-01-01T00:00:00Z",
    "deposit_floor_cents": 10000,
}
FP_PRE_POLICY = {
    "policy_code": "FP-PRE", "rate_class": "FOR_PROFIT", "facility_tier": "PREMIUM",
    "hourly_rate_cents": 15000, "deposit_basis_points": 3000,
    "custodial_hourly_cents": 6000, "effective_from": "2026-01-01T00:00:00Z",
    "deposit_floor_cents": 20000,
}


def _site_with_two_issued_permits(api):
    """One site with GYM (STANDARD) and AUD (PREMIUM); a NONPROFIT renter holds
    an ISSUED permit on GYM and a FOR_PROFIT renter holds one on AUD, both on
    the night of 2026-11-14. Returns (site, gym_permit, aud_permit)."""
    site = make_site("RHS")
    gym = make_facility(site["id"], facility_code="GYM", facility_tier="STANDARD",
                        capacity=300)
    aud = make_facility(site["id"], facility_code="AUD", facility_tier="PREMIUM",
                        capacity=500)
    make_policy(**NP_STD_POLICY)
    make_policy(**FP_PRE_POLICY)
    org_np, _ = add_renter_with_insurance("Renter NP")
    org_fp, _ = add_renter_with_insurance("Renter FP", rate_class="FOR_PROFIT")

    env_gym = {"site": site, "facility": gym, "org": org_np}
    req_g, p_gym = make_approved_permit_in_env(
        env_gym, event_title="Gym Night", headcount_estimate=100,
        starts_at="2026-11-14T01:00:00Z", ends_at="2026-11-14T04:00:00Z")
    env_aud = {"site": site, "facility": aud, "org": org_fp}
    req_a, p_aud = make_approved_permit_in_env(
        env_aud, event_title="Aud Night", headcount_estimate=300,
        starts_at="2026-11-14T02:00:00Z", ends_at="2026-11-14T05:00:00Z")
    return site, p_gym, p_aud


class TestSiteWideBlackoutAggregateOverlap:
    def test_blackout_supersedes_permits_on_every_facility(self, api):
        """PRD §3.1: "The optional `facility_id` scopes the event to one facility;
        leaving it null declares a site-wide blackout that occupies every
        facility of the site."
        PRD §3.1: "Creating a tier-0 event whose window overlaps the blocked
        interval of an already-`ISSUED` community permit preempts that permit to
        `SUPERSEDED` with a full administrative refund (§3.7); creating any other
        event that collides with an `ISSUED` or `ACTIVE` permit's blocked
        interval is instead rejected with `ERR_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/site_wide_blackout_aggregate_overlap
        """
        site, p_gym, p_aud = _site_with_two_issued_permits(api)
        make_calendar_event(
            site["id"], facility_id=None,
            title="Emergency Assembly — All Facilities",
            starts_at="2026-11-14T00:00:00Z", ends_at="2026-11-14T06:00:00Z",
            event_priority_tier=0)

        gym_after = validate_success(api.get_permit(p_gym["id"], DIRECTOR))
        aud_after = validate_success(api.get_permit(p_aud["id"], DIRECTOR))
        assert gym_after["lifecycle_status"] == "SUPERSEDED"
        # Same blackout collides with a permit on a DIFFERENT facility — the
        # site-wide aggregate semantic.
        assert aud_after["lifecycle_status"] == "SUPERSEDED"

    def test_blackout_cancels_work_orders_and_voids_provisionals(self, api):
        """PRD §3.7: "the refund waterfall runs under the administrative class —
        deposit and any fees returned in full, no cancellation fee — the
        financial dimension moves to `REFUND_PENDING`, and the work order is
        cancelled."
        PRD §3.6: "A `DRAFT` or `ISSUED` invoice moves to the terminal `VOID`
        when the provisional is superseded by the final or when its permit is
        cancelled, lapsed, or superseded; voiding an invoice that was `ISSUED`
        subtracts its `total_cents` from the outstanding balance, reversing the
        accrual."

        Design: Difficulty/resource_temporal_overlap/site_wide_blackout_aggregate_overlap
        """
        site, p_gym, p_aud = _site_with_two_issued_permits(api)
        make_calendar_event(
            site["id"], facility_id=None,
            title="Emergency Assembly — All Facilities",
            starts_at="2026-11-14T00:00:00Z", ends_at="2026-11-14T06:00:00Z",
            event_priority_tier=0)

        for permit in (p_gym, p_aud):
            order = get_single_work_order(permit["id"])
            assert order["wo_status"] == "CANCELLED"
            invoices = validate_success(api.list_permit_invoices(permit["id"], DIRECTOR))
            prov = invoice_of_kind(invoices, "PROVISIONAL")
            assert prov["invoice_status"] == "VOID"
