"""Per-occurrence seasonal pricing across a rate-year boundary, and the
insurance coverage-window rule at the exact event end (PRD §3.2, §3.3, §3.9)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    invoice_of_kind,
    make_site, make_facility, make_policy, make_renter, make_insurance,
    make_booking_env, make_draft_request, submit_request, begin_review, approve,
    make_renter_headers,
    api_client,
    TEST_USERS,
    ApiErrorId,
)

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]

NP_ATH_2026 = {
    "policy_code": "NP-ATH-2026", "rate_class": "NONPROFIT", "facility_tier": "ATHLETIC",
    "hourly_rate_cents": 9000, "deposit_basis_points": 2000,
    "custodial_hourly_cents": 4500, "deposit_floor_cents": 15000,
    "effective_from": "2026-07-01T00:00:00Z", "effective_to": "2027-01-01T00:00:00Z",
}
NP_ATH_2027 = {
    "policy_code": "NP-ATH-2027", "rate_class": "NONPROFIT", "facility_tier": "ATHLETIC",
    "hourly_rate_cents": 10000, "deposit_basis_points": 2000,
    "custodial_hourly_cents": 5000, "deposit_floor_cents": 15000,
    "effective_from": "2027-01-01T00:00:00Z",
}


class TestSeasonalRateYearStraddle:
    def test_seasonal_rate_year_straddle_per_occurrence_pricing(self, api):
        """PRD §3.9: "Pricing is per occurrence: each occurrence is billed under
        the `ACTIVE` policy covering its own start, so a series that straddles a
        rate-year boundary bills its later occurrences at the new rate."
        PRD §3.2: "A policy applies to events starting at or after its
        `effective_from` and strictly before its `effective_to`."
        PRD §3.9: "Generation expands the recurrence rule across the season
        window in site-local time, producing occurrence dates in chronological
        order; each occurrence becomes a RentalRequest that is auto-submitted and
        run through the approval pipeline in date order, earliest first."

        Design: Corner/calculations/seasonal_rate_year_straddle_per_occurrence_pricing
        """
        site = make_site("FHS", display_name="Fairview High")
        field = make_facility(site["id"], facility_code="FIELD",
                              facility_tier="ATHLETIC", capacity=1000)
        make_policy(**NP_ATH_2026)
        make_policy(**NP_ATH_2027)
        org = make_renter("City Soccer League")
        make_insurance(org["id"], per_occurrence_limit_cents=500000000,
                       aggregate_limit_cents=1000000000,
                       effective_to="2027-06-01T00:00:00Z")

        # Weekly Saturday 18:00-21:00 local, season 2026-12-26 .. 2027-01-16:
        # occurrences Dec 26, Jan 2, Jan 9, Jan 16 (site-local). season_end is
        # pinned at local midnight AFTER the last Saturday (2027-01-17T08:00Z =
        # 2027-01-17T00:00 PST) so the Jan 16 occurrence — 2027-01-17T02:00Z —
        # falls inside the inclusive season window under any reading.
        series = validate_success(api.create_seasonal_permit(
            {"renter_org_id": org["id"], "facility_id": field["id"],
             "series_name": "Winter Soccer Saturdays",
             "recurrence_rule": "WEEKLY:SAT:18:00-21:00",
             "season_start": "2026-12-26T00:00:00Z",
             "season_end": "2027-01-17T08:00:00Z"},
            make_renter_headers(org["id"])), 201)
        assert series["series_status"] == "ACTIVE"

        permits = validate_success(api.list_permits(
            DIRECTOR, params={"seasonal_permit_id": series["id"]}))
        assert len(permits) == 4, "one Permit per Saturday in the season window"

        by_start = {p["occupancy_start"][:10]: p for p in permits}
        occ1 = by_start["2026-12-27"]   # Dec 26 18:00 PST = 2026-12-27T02:00Z
        later = [by_start[d] for d in ("2027-01-03", "2027-01-10", "2027-01-17")]

        # Occurrence 1 starts before 2027-01-01 -> FY2026 policy (9000/h).
        inv1 = invoice_of_kind(
            validate_success(api.list_permit_invoices(occ1["id"], DIRECTOR)),
            "PROVISIONAL")
        assert inv1["rental_fee_cents"] == 27000        # 3h x 9000
        assert inv1["staffing_charge_cents"] == 18000   # 4.0h x 4500
        assert inv1["after_hours_charge_cents"] == 13500  # 0.75 x 18000
        assert inv1["discount_cents"] == 2925           # subtotal 58500 -> 5%
        assert inv1["total_cents"] == 55575
        assert occ1["deposit_required_cents"] == 15000  # max(15000, 5400)

        # Occurrences 2-4 start at/after 2027-01-01 -> FY2027 policy (10000/h).
        for occ in later:
            inv = invoice_of_kind(
                validate_success(api.list_permit_invoices(occ["id"], DIRECTOR)),
                "PROVISIONAL")
            assert inv["rental_fee_cents"] == 30000     # 3h x 10000
            assert inv["staffing_charge_cents"] == 20000  # 4.0h x 5000
            assert inv["after_hours_charge_cents"] == 15000
            assert inv["discount_cents"] == 3250        # subtotal 65000 -> 5%
            assert inv["total_cents"] == 61750
            assert occ["deposit_required_cents"] == 15000  # max(15000, 6000)


class TestInsuranceCoverageWindow:
    def test_certificate_ending_exactly_at_event_end_satisfies(self, api):
        """PRD §3.3: "A certificate satisfies a request exactly when it is
        `VALID`, its `effective_from` is at or before the request's `ends_at`,
        its `effective_to` is at or after the request's `ends_at`, and both
        limits meet the tier floors for the request's `headcount_estimate`."

        Design: Corner/calculations/insurance_window_must_cover_event_end
        """
        env = make_booking_env(insurance_overrides={
            "per_occurrence_limit_cents": 200000000,
            "aggregate_limit_cents": 400000000,
            "effective_to": "2026-12-05T04:00:00Z",  # exactly the event end
        })
        req = make_draft_request(env, event_title="Boundary Event",
                                 headcount_estimate=50,
                                 starts_at="2026-12-05T01:00:00Z",
                                 ends_at="2026-12-05T04:00:00Z")
        submit_request(env, req["id"])
        reviewed = begin_review(req["id"])
        # effective_to >= ends_at (equality included): the gate passes.
        permit = approve(req["id"], reviewed["version"])
        assert permit["lifecycle_status"] == "ISSUED"

    def test_short_window_fails_and_revocation_cascades(self, api):
        """PRD §3.3: "A certificate is `VALID` at upload, becomes `EXPIRED`
        automatically when the logical clock passes its `effective_to`, and may
        be moved to `REVOKED` by a `FacilitiesDirector` giving a `reason`. Either
        loss of coverage cascades: any request sitting in `UNDER_REVIEW` that
        relied solely on that certificate is sent back to `REVISION_REQUESTED`
        for an insurance reason, and the renter must upload a new certificate."
        PRD §3.3: "The sufficiency check runs as pre-validation when a
        certificate is uploaded and again as a hard gate at submission,
        resubmission, and approval; failure there is `ERR_INSURANCE_INSUFFICIENT`."

        Design: Corner/calculations/insurance_window_must_cover_event_end
        """
        env = make_booking_env(insurance_overrides={
            "per_occurrence_limit_cents": 200000000,
            "aggregate_limit_cents": 400000000,
            "effective_to": "2026-12-05T04:00:00Z",
        })
        cert_exact = env["cert"]
        # Request 1 reaches UNDER_REVIEW covered by cert_exact.
        req1 = make_draft_request(env, event_title="Boundary Event",
                                  headcount_estimate=50,
                                  starts_at="2026-12-05T01:00:00Z",
                                  ends_at="2026-12-05T04:00:00Z")
        submit_request(env, req1["id"])
        begin_review(req1["id"])
        # Request 2 is submitted (same covered window) but never reviewed.
        req2 = make_draft_request(env, event_title="Short Covered Event",
                                  headcount_estimate=50,
                                  starts_at="2026-12-05T01:00:00Z",
                                  ends_at="2026-12-05T04:00:00Z")
        submit_request(env, req2["id"])

        # Revoking the sole certificate sends only the UNDER_REVIEW request back.
        validate_success(api.revoke_insurance_certificate(
            cert_exact["id"], {"reason": "Insurer cancelled policy"}, DIRECTOR))
        after_revoke = validate_success(api.get_request(req1["id"], DIRECTOR))
        assert after_revoke["request_status"] == "REVISION_REQUESTED"
        assert validate_success(api.get_request(req2["id"], DIRECTOR))[
            "request_status"] == "SUBMITTED"

        # Re-revoking an already-REVOKED certificate is not a legal transition.
        res = api.revoke_insurance_certificate(
            cert_exact["id"], {"reason": "cleanup attempt"}, DIRECTOR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        # The replacement certificate ends one hour before the event end, so
        # request 2 now fails the approval-time insurance hard gate.
        make_insurance(env["org"]["id"], insurer_name="ShortCover",
                       per_occurrence_limit_cents=200000000,
                       aggregate_limit_cents=400000000,
                       effective_from="2026-01-01T00:00:00Z",
                       effective_to="2026-12-05T03:00:00Z")
        reviewed2 = begin_review(req2["id"])
        res2 = api.approve_request(
            req2["id"], {"expected_request_version": reviewed2["version"]}, DIRECTOR)
        validate_error(res2, ApiErrorId.ERR_INSURANCE_INSUFFICIENT)
