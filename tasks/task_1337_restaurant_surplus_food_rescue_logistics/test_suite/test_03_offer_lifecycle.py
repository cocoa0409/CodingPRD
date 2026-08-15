"""Donation offer lifecycle: publish gating, re-offer loop, terminal states
(PRD §3.2)."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, ApiErrorId,
    create_donor, create_agency, create_driver, add_window, create_offer,
    set_clock, dispatch_run, respond_run, fail_run,
    make_donor_coordinator_headers, make_volunteer_driver_headers,
    setup_confirmed_run, setup_verified_run,
)

ADMIN = TEST_USERS["admin_headers"]


class TestPublishGatedByDonorStatus:
    def test_publish_rejected_while_donor_pending_review(self, api):
        """PRD §3.2: "Publishing moves an offer from `DRAFT` to `OPEN`, performed
        by the owning `DonorCoordinator` or a `DispatchAdmin`, and carries three
        preconditions: the offer must currently be `DRAFT` (else
        `ERR_INVALID_STATE_TRANSITION`), the donor site must be `ACTIVE` (else
        `ERR_DONOR_NOT_ACTIVE`), and `pickup_window_end` must still lie after
        the current logical clock (else `ERR_PICKUP_WINDOW_PAST`)."

        Design: Difficulty/cross_entity_state_dependency/offer_publish_gated_by_donor_status
        """
        donor = create_donor(legal_name="Gate Bistro", ein="909090909",
                             contact_email="g@bistro.example", activate=False)
        offer = create_offer(donor["id"], food_category="SHELF_STABLE",
                             estimated_weight_lbs=5)
        set_clock("2026-08-02T09:00:00Z")
        resp = api.patch_donation_offer_status(
            offer["id"], "OPEN", make_donor_coordinator_headers(donor["id"]))
        validate_error(resp, ApiErrorId.ERR_DONOR_NOT_ACTIVE)
        resp = api.get_donation_offer(offer["id"], ADMIN)
        assert validate_success(resp)["status"] == "DRAFT"

    def test_publish_succeeds_once_donor_active(self, api):
        """PRD §3.2: "Publishing moves an offer from `DRAFT` to `OPEN`, performed
        by the owning `DonorCoordinator` or a `DispatchAdmin`, and carries three
        preconditions: the offer must currently be `DRAFT` (else
        `ERR_INVALID_STATE_TRANSITION`), the donor site must be `ACTIVE` (else
        `ERR_DONOR_NOT_ACTIVE`), and `pickup_window_end` must still lie after
        the current logical clock (else `ERR_PICKUP_WINDOW_PAST`)."

        Design: Difficulty/cross_entity_state_dependency/offer_publish_gated_by_donor_status
        """
        donor = create_donor(legal_name="Gate Bistro", ein="909090909",
                             contact_email="g@bistro.example", activate=False)
        offer = create_offer(donor["id"], food_category="SHELF_STABLE",
                             estimated_weight_lbs=5)
        set_clock("2026-08-02T09:00:00Z")
        resp = api.patch_donor_site_status(donor["id"], "ACTIVE", ADMIN)
        validate_success(resp)
        # The identical publish request now succeeds: only the donor's state changed.
        resp = api.patch_donation_offer_status(
            offer["id"], "OPEN", make_donor_coordinator_headers(donor["id"]))
        data = validate_success(resp)
        assert data["status"] == "OPEN"


class TestPublishAfterWindowPassed:
    def test_draft_publish_rejected_once_pickup_window_passed(self, api):
        """PRD §3.2: "and `pickup_window_end` must still lie after the current
        logical clock (else `ERR_PICKUP_WINDOW_PAST`)."
        PRD §2.4: "A donation offer in `OPEN` or `MATCHED` whose
        `pickup_window_end` lies in the past transitions to `EXPIRED`."

        Design: Corner/errors/publish_rejected_once_pickup_window_passed
        """
        donor = create_donor(legal_name="Late Bistro", ein="100000021",
                             contact_email="late@bistro.example")
        offer = create_offer(donor["id"], food_category="SHELF_STABLE",
                             estimated_weight_lbs=5)
        set_clock("2026-08-03T00:00:00Z")
        resp = api.patch_donation_offer_status(
            offer["id"], "OPEN", make_donor_coordinator_headers(donor["id"]))
        validate_error(resp, ApiErrorId.ERR_PICKUP_WINDOW_PAST)
        # Lazy expiry applies only to OPEN/MATCHED offers: a DRAFT stays DRAFT.
        resp = api.get_donation_offer(offer["id"], ADMIN)
        assert validate_success(resp)["status"] == "DRAFT"


class TestOfferTerminalLockdown:
    def test_closed_offer_rejects_cancel_and_verified_run_rejects_respond(self, api):
        """PRD §3.2: "`CLOSED`, `CANCELLED`, `EXPIRED`, and `DISCARDED` are the
        terminal states."
        PRD §3.4: "Responding with `decision` `ACCEPT` requires the run to still
        be `PROPOSED` — any other state answers `ERR_RUN_NOT_IN_EXPECTED_STATE`."

        Design: Corner/state_machines/offer_terminal_lockdown_and_double_respond_rejected
        """
        ctx = setup_verified_run(food_category="SHELF_STABLE",
                                 estimated_weight_lbs=40, actual_weight_lbs=40)
        assert ctx["run"]["run_status"] == "VERIFIED"
        # CLOSED is terminal for offers: cancel is not a declared transition.
        resp = api.patch_donation_offer_status(
            ctx["offer"]["id"], "CANCELLED",
            make_donor_coordinator_headers(ctx["donor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        # VERIFIED is terminal for runs: respond admits only PROPOSED.
        # (Only the assigned driver's call reaches the state check; any other
        # caller would be masked out per PRD §2.7 before state is evaluated.)
        resp = api.respond_rescue_run(
            ctx["run"]["id"], "DECLINE",
            make_volunteer_driver_headers(ctx["driver"]["id"]))
        validate_error(resp, ApiErrorId.ERR_RUN_NOT_IN_EXPECTED_STATE)

    def test_second_respond_after_accept_rejected(self, api):
        """PRD §3.4: "Responding with `decision` `ACCEPT` requires the run to
        still be `PROPOSED` — any other state answers
        `ERR_RUN_NOT_IN_EXPECTED_STATE`."

        Design: Corner/state_machines/offer_terminal_lockdown_and_double_respond_rejected
        """
        ctx = setup_confirmed_run(food_category="SHELF_STABLE",
                                  estimated_weight_lbs=10,
                                  agency_capacity_lbs=100)
        assert ctx["run"]["run_status"] == "CONFIRMED"
        resp = api.respond_rescue_run(
            ctx["run"]["id"], "ACCEPT",
            make_volunteer_driver_headers(ctx["driver"]["id"]))
        validate_error(resp, ApiErrorId.ERR_RUN_NOT_IN_EXPECTED_STATE)


class TestReOfferLoopExpiresOnThirdFailure:
    def _run_one_fail_cycle(self, api, offer_id, driver_id, agency_id):
        run = dispatch_run(offer_id, driver_id=driver_id, agency_id=agency_id)
        respond_run(run["id"], driver_id, "ACCEPT")
        fail_run(run["id"], "DONOR", "DONOR_NO_SHOW", as_driver_id=driver_id)

    def test_failures_one_and_two_reoffer(self, api):
        """PRD §3.2: "A pickup-stage failure instead sends the offer back around:
        `failed_attempts` increments by one, and the offer returns from
        `SCHEDULED` to `OPEN` — unless that increment reaches three, in which
        case the offer goes to `EXPIRED` with `failed_attempts` set to 3 and can
        never be re-offered."

        Design: Corner/state_machines/offer_expires_on_third_failed_attempt
        """
        donor = create_donor(legal_name="Third Bistro", ein="100000009",
                             contact_email="t3@bistro.example")
        agency = create_agency(accepts_categories=("SHELF_STABLE",),
                               capacity_shelf_stable_lbs=100)
        driver = create_driver(cooler_slot_count=0)
        add_window(driver["id"])
        offer = create_offer(donor["id"], food_category="SHELF_STABLE",
                             estimated_weight_lbs=10, publish=True)
        set_clock("2026-08-02T09:30:00Z")
        for expected_attempts in (1, 2):
            self._run_one_fail_cycle(api, offer["id"], driver["id"], agency["id"])
            resp = api.get_donation_offer(offer["id"], ADMIN)
            data = validate_success(resp)
            assert data["failed_attempts"] == expected_attempts
            assert data["status"] == "OPEN", (
                f"failure {expected_attempts} must re-offer, not expire")

    def test_third_failure_expires_and_fourth_dispatch_rejected(self, api):
        """PRD §3.2: "A pickup-stage failure instead sends the offer back around:
        `failed_attempts` increments by one, and the offer returns from
        `SCHEDULED` to `OPEN` — unless that increment reaches three, in which
        case the offer goes to `EXPIRED` with `failed_attempts` set to 3 and can
        never be re-offered."
        PRD §3.3: "an offer that is not `OPEN` — after the lazy expiry of §2.4
        has had its say — answers `ERR_OFFER_NOT_OPEN`."

        Design: Corner/state_machines/offer_expires_on_third_failed_attempt
        """
        donor = create_donor(legal_name="Third Bistro", ein="100000009",
                             contact_email="t3@bistro.example")
        agency = create_agency(accepts_categories=("SHELF_STABLE",),
                               capacity_shelf_stable_lbs=100)
        driver = create_driver(cooler_slot_count=0)
        add_window(driver["id"])
        offer = create_offer(donor["id"], food_category="SHELF_STABLE",
                             estimated_weight_lbs=10, publish=True)
        set_clock("2026-08-02T09:30:00Z")
        for _ in range(3):
            self._run_one_fail_cycle(api, offer["id"], driver["id"], agency["id"])
        resp = api.get_donation_offer(offer["id"], ADMIN)
        data = validate_success(resp)
        assert data["failed_attempts"] == 3
        assert data["status"] == "EXPIRED", "the 3rd failure is terminal"

        payload = {"offer_id": offer["id"],
                   "expected_offer_version": data["version"],
                   "driver_id": driver["id"], "agency_id": agency["id"]}
        resp = api.create_rescue_run(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_OFFER_NOT_OPEN)
