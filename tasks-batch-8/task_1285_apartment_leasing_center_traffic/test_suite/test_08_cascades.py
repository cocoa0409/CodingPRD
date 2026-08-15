"""Cross-entity cascades: the countersign conversion chain and the lease-cancel
unwind chain (compensation + availability-driven waitlist auto-promotion)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_issued_lease,
    cancel_lease,
    countersign_lease,
    create_guided_tour,
    create_waitlist_entry,
    get_application,
    get_floorplan,
    get_inquiry,
    get_lease,
    get_tour,
    get_waitlist_entry,
    setup_occupied_floorplan,
    setup_site,
    sign_lease,
    validate_success,
)

PM = TEST_USERS["property_manager_headers"]


class TestCountersignConversionChain:
    def _signed_lease_with_tour(self):
        """Site + CONTACTED inquiry with a SCHEDULED guided tour + application
        APPROVED + lease generated and applicant-signed (SIGNED_BY_APPLICANT)."""
        site = setup_site()
        agent_id = site["agent"]["id"]
        bundle = add_issued_lease(
            site, inquiry_overrides={"contact_name": "CI",
                                     "contact_email": "casc-i@x.com",
                                     "source": "REFERRAL"})
        tour = create_guided_tour(bundle["inquiry"]["id"], agent_id,
                                  "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z")
        sign_lease(bundle["lease"]["id"], bundle["application"]["id"])
        return site, bundle, tour

    def test_countersign_executes_lease_and_leases_application(self, api):
        """PRD §2.9: "The conversion chain fires when a lease is countersigned: the
        lease reaches `EXECUTED`, its application advances to `LEASED`, the
        application’s source inquiry advances to `CONVERTED`, and every tour still
        `SCHEDULED` for that inquiry is cancelled — the prospect has signed, so
        remaining appointments are moot."
        PRD §3.6: "A `PropertyManager` countersigns a lease in `SIGNED_BY_APPLICANT`
        (any other state is `ERR_LEASE_INVALID_STATE`); the lease becomes
        `EXECUTED`, `executed_at` is stamped with the current logical time, and the
        conversion chain of §2.9 fires: the application advances to `LEASED`, the
        source inquiry becomes `CONVERTED`, and that inquiry's remaining `SCHEDULED`
        tours are cancelled."

        Design: Difficulty/transitive_cascade/countersign_cascades_application_inquiry_tour
        """
        _site, bundle, _tour = self._signed_lease_with_tour()
        lease = countersign_lease(bundle["lease"]["id"])
        assert lease["status"] == "EXECUTED"
        assert lease.get("executed_at") is not None
        assert get_application(bundle["application"]["id"])["status"] == "LEASED", \
            "link 1 of the chain: the application advances on execution"

    def test_countersign_converts_inquiry_and_cancels_tours(self, api):
        """PRD §2.9: "The conversion chain fires when a lease is countersigned: the
        lease reaches `EXECUTED`, its application advances to `LEASED`, the
        application’s source inquiry advances to `CONVERTED`, and every tour still
        `SCHEDULED` for that inquiry is cancelled — the prospect has signed, so
        remaining appointments are moot."
        PRD §3.3: "Conversion is the happy mirror image and never happens by
        request: when a lease for an application born of the inquiry reaches
        `EXECUTED`, an inquiry in `CONTACTED` or `TOUR_SCHEDULED` becomes
        `CONVERTED` automatically, and its remaining `SCHEDULED` tours are cancelled
        because the prospect has signed."

        Design: Difficulty/transitive_cascade/countersign_cascades_application_inquiry_tour
        """
        _site, bundle, tour = self._signed_lease_with_tour()
        countersign_lease(bundle["lease"]["id"])
        # Links 2 and 3: the source inquiry converts, and that conversion — not
        # the countersign directly — cancels its still-SCHEDULED tour.
        assert get_inquiry(bundle["inquiry"]["id"])["status"] == "CONVERTED"
        assert get_tour(tour["id"])["status"] == "CANCELLED"


class TestLeaseCancelUnwindChain:
    def test_lease_cancel_compensates_application_and_frees_unit(self, api):
        """PRD §2.9: "The unwind chain fires when a lease is cancelled: the lease
        leaves the committed set and `available_units` rises, every `SCHEDULED` or
        `READY` move-in of the lease is cancelled, the freed unit triggers
        auto-promotion of the waitlist queue head when effective availability
        permits, and — only when the cancelled lease was `EXECUTED` — the
        application compensates from `LEASED` back to `APPROVED`."
        PRD §3.6: "Cancelling an `EXECUTED` lease adds the compensation step: the
        application returns from `LEASED` to `APPROVED` with its
        `required_deposit_cents` retained, becoming leasable again."

        Design: Difficulty/transitive_cascade/lease_cancel_frees_unit_and_promotes_queue_head
        """
        occ = setup_occupied_floorplan()  # 1 unit, EXECUTED lease, app LEASED
        site, pipeline = occ["site"], occ["pipeline"]
        create_waitlist_entry(site["floorplan"]["id"], site["agent"]["id"],
                              contact_name="E1", contact_email="e1@x.com")
        create_waitlist_entry(site["floorplan"]["id"], site["agent"]["id"],
                              contact_name="E2", contact_email="e2@x.com")

        cancelled = cancel_lease(pipeline["lease"]["id"])
        assert cancelled["status"] == "CANCELLED"
        # Compensation: LEASED -> APPROVED (link riding the same trigger).
        assert get_application(pipeline["application"]["id"])["status"] == "APPROVED"
        # The unit is freed: the committed set shrinks and availability rises.
        floorplan = get_floorplan(site["floorplan"]["id"])
        assert floorplan["committed_units"] == 0
        assert floorplan["available_units"] == 1

    def test_lease_cancel_auto_promotes_waitlist_head(self, api):
        """PRD §3.6: "In all three cases the lease leaves the committed set
        (`committed_units` is recomputed and `available_units` rises by one), every
        `SCHEDULED` or `READY` move-in of the lease is cancelled, and the freed unit
        triggers auto-promotion of the waitlist queue head when effective
        availability is at least one."
        PRD §3.4: "A promoted entry becomes `OFFERED`, and its `offer_expires_at` is
        set to the current logical time plus a seventy-two-hour offer window."

        Design: Difficulty/transitive_cascade/lease_cancel_frees_unit_and_promotes_queue_head
        """
        from test_helpers import assert_same_instant
        occ = setup_occupied_floorplan()
        site, pipeline = occ["site"], occ["pipeline"]
        entry1 = create_waitlist_entry(site["floorplan"]["id"], site["agent"]["id"],
                                       contact_name="E1", contact_email="e1@x.com")
        entry2 = create_waitlist_entry(site["floorplan"]["id"], site["agent"]["id"],
                                       contact_name="E2", contact_email="e2@x.com")

        cancel_lease(pipeline["lease"]["id"])
        # The availability increment itself auto-promotes the queue head at the
        # default logical clock: offer_expires_at = 2026-08-01T00:00:00Z + 72h.
        promoted = get_waitlist_entry(entry1["id"])
        assert promoted["status"] == "OFFERED"
        assert_same_instant(promoted["offer_expires_at"], "2026-08-04T00:00:00Z",
                            label="offer_expires_at")
        # Only the head moves; the rest of the queue is untouched.
        waiting = get_waitlist_entry(entry2["id"])
        assert waiting["status"] == "WAITING"
        assert waiting["position"] == 2
