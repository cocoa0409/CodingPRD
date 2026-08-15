"""Role authorization and ownership masking (PRD §2.1, §2.7, §4)."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, ApiErrorId,
    create_donor, create_agency, create_driver, add_window, create_offer,
    set_clock, dispatch_run, respond_run, record_pickup, record_delivery,
    fail_run, get_offer_version,
    make_donor_coordinator_headers, make_volunteer_driver_headers,
    make_agency_coordinator_headers,
    setup_confirmed_run,
)
from test_helpers.factories import (
    create_donation_offer_payload, create_availability_window_payload,
)

ADMIN = TEST_USERS["admin_headers"]


class TestRoleDenial:
    def test_donor_cannot_dispatch_run(self, api):
        """PRD §2.1: "If the caller's role is not among the roles an endpoint
        admits, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: POST /api/rescue-runs admits only DispatchAdmin.

        Design: Corner/rbac/donor_cannot_dispatch_run_forbidden
        """
        donor = create_donor(legal_name="RB Bistro", ein="100000025",
                             contact_email="rb@bistro.example")
        offer = create_offer(donor["id"], food_category="SHELF_STABLE",
                             estimated_weight_lbs=5, publish=True)
        payload = {"offer_id": offer["id"],
                   "expected_offer_version": get_offer_version(offer["id"])}
        resp = api.create_rescue_run(
            payload, make_donor_coordinator_headers(donor["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_driver_cannot_adjudicate_strike(self, api):
        """PRD §2.1: "If the caller's role is not among the roles an endpoint
        admits, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: POST /api/strike-reports/{id}/adjudicate admits only
        DispatchAdmin.

        Design: Corner/rbac/driver_cannot_adjudicate_strike_forbidden
        """
        ctx = setup_confirmed_run(food_category="SHELF_STABLE",
                                  estimated_weight_lbs=10,
                                  agency_capacity_lbs=100)
        fail_run(ctx["run"]["id"], "DONOR", "DONOR_NO_SHOW",
                 as_driver_id=ctx["driver"]["id"])
        resp = api.list_run_strike_reports(ctx["run"]["id"], ADMIN)
        strike = validate_success(resp)[0]
        # The role check (tier 2) fires before any segregation-of-duties
        # evaluation: the driver's call is a 403, full stop.
        resp = api.adjudicate_strike_report(
            strike["id"], "UPHELD",
            make_volunteer_driver_headers(ctx["driver"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestOwnershipMasking:
    def test_donor_coordinator_masked_from_other_donors_resources(self, api):
        """PRD §2.7: "Ownership violations are deliberately masked as the same
        not-found errors rather than a distinct authorization failure. A
        `DonorCoordinator` may touch only its own donor record, its own offers,
        and its own tax receipts; addressing another donor's resources answers
        `ERR_DONOR_NOT_FOUND` or `ERR_OFFER_NOT_FOUND` as if the resource did
        not exist."
        PRD §3.2: "the owning `donor_site_id` (which must equal the caller's
        `X-User-ID`)"

        Design: Corner/validations/ownership_mismatch_masked_as_not_found
        """
        d1 = create_donor(legal_name="Own One", ein="100000016",
                          contact_email="o1@bistro.example", activate=False)
        d2 = create_donor(legal_name="Own Two", ein="100000017",
                          contact_email="o2@bistro.example", activate=False)
        resp = api.create_donation_offer(
            create_donation_offer_payload(donor_site_id=d2["id"],
                                          food_category="SHELF_STABLE",
                                          estimated_weight_lbs=5),
            make_donor_coordinator_headers(d2["id"]))
        assert resp.status_code == 201, f"Setup failed: {resp.text}"
        # Reading another donor's record.
        resp = api.get_donor_site(d2["id"], make_donor_coordinator_headers(d1["id"]))
        validate_error(resp, ApiErrorId.ERR_DONOR_NOT_FOUND)
        # Listing another donor's offers.
        resp = api.list_donor_offers(
            d2["id"], make_donor_coordinator_headers(d1["id"]))
        validate_error(resp, ApiErrorId.ERR_DONOR_NOT_FOUND)
        # Posting an offer as another donor.
        resp = api.create_donation_offer(
            create_donation_offer_payload(donor_site_id=d2["id"],
                                          food_category="SHELF_STABLE",
                                          estimated_weight_lbs=5),
            make_donor_coordinator_headers(d1["id"]))
        validate_error(resp, ApiErrorId.ERR_DONOR_NOT_FOUND)

    def test_agency_coordinator_cannot_verify_other_agencys_run(self, api):
        """PRD §2.7: "An `AgencyCoordinator` may touch only its own agency
        record and runs targeting its agency; anything else answers
        `ERR_AGENCY_NOT_FOUND` or `ERR_RUN_NOT_FOUND`."

        Design: Corner/rbac/agency_cannot_verify_other_agencys_run_not_found
        """
        donor = create_donor(legal_name="AV Bistro", ein="100000027",
                             contact_email="av@bistro.example")
        ag1 = create_agency(name="AG1", accepts_categories=("SHELF_STABLE",),
                            capacity_shelf_stable_lbs=100)
        ag2 = create_agency(name="AG2", accepts_categories=("SHELF_STABLE",),
                            capacity_shelf_stable_lbs=100)
        driver = create_driver(cooler_slot_count=0)
        add_window(driver["id"])
        offer = create_offer(donor["id"], food_category="SHELF_STABLE",
                             estimated_weight_lbs=10, publish=True)
        set_clock("2026-08-02T09:30:00Z")
        run = dispatch_run(offer["id"], driver_id=driver["id"],
                           agency_id=ag1["id"])
        respond_run(run["id"], driver["id"], "ACCEPT")
        record_pickup(run["id"], driver["id"])
        record_delivery(run["id"], driver["id"], actual_weight_lbs=10)
        # AG2's coordinator cannot even confirm the run exists.
        resp = api.verify_delivery(
            run["id"], make_agency_coordinator_headers(ag2["id"]))
        validate_error(resp, ApiErrorId.ERR_RUN_NOT_FOUND)

    def test_driver_masked_from_other_drivers_runs_and_windows(self, api):
        """PRD §2.7: "A `VolunteerDriver` may touch only its own record, its own
        availability windows, and runs assigned to it; anything else answers
        `ERR_DRIVER_NOT_FOUND` or `ERR_RUN_NOT_FOUND`."
        PRD §3.4: "Only the assigned driver may act on a run at the driving
        stages, and only the destination agency's coordinator may countersign
        it; anyone else addressing the run is masked out with
        `ERR_RUN_NOT_FOUND` as §2.7 describes."

        Design: Corner/rbac/driver_cannot_respond_or_window_for_other_driver_not_found
        """
        donor = create_donor(legal_name="DV Bistro", ein="100000028",
                             contact_email="dv@bistro.example")
        agency = create_agency(accepts_categories=("SHELF_STABLE",),
                               capacity_shelf_stable_lbs=100)
        v1 = create_driver(full_name="V One", email="v1@example.com",
                           cooler_slot_count=0)
        add_window(v1["id"])
        v2 = create_driver(full_name="V Two", email="v2@example.com",
                           cooler_slot_count=0)
        offer = create_offer(donor["id"], food_category="SHELF_STABLE",
                             estimated_weight_lbs=10, publish=True)
        set_clock("2026-08-02T09:30:00Z")
        run = dispatch_run(offer["id"], driver_id=v1["id"],
                           agency_id=agency["id"])
        # V2 is not the assigned driver.
        resp = api.respond_rescue_run(
            run["id"], "ACCEPT", make_volunteer_driver_headers(v2["id"]))
        validate_error(resp, ApiErrorId.ERR_RUN_NOT_FOUND)
        # V1 cannot declare a window under V2's record.
        resp = api.create_availability_window(
            v2["id"],
            create_availability_window_payload(
                window_start="2026-08-03T09:00:00Z",
                window_end="2026-08-03T12:00:00Z"),
            make_volunteer_driver_headers(v1["id"]))
        validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_FOUND)
