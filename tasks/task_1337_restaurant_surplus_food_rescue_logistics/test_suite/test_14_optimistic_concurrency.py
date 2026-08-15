"""Optimistic concurrency control on dispatch and receipt issuance (PRD §2.6)."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, ApiErrorId,
    create_donor, create_agency, create_driver, add_window, create_cooler,
    create_offer, create_rate_card, set_clock, dispatch_run, respond_run,
    get_offer_version, get_donor_version, issue_receipt,
    setup_verified_run,
)

ADMIN = TEST_USERS["admin_headers"]

PERIOD = ("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")


class TestStaleOfferVersion:
    def _setup_declined_offer(self, api):
        """An offer dispatched once and declined: OPEN again at a version that
        has advanced past the one captured before the first dispatch."""
        donor = create_donor(legal_name="OCC Bistro", ein="100000029",
                             contact_email="occ@bistro.example")
        agency = create_agency()
        driver = create_driver(cold_chain_certified=True)
        add_window(driver["id"])
        cooler = create_cooler(label="C1")
        offer = create_offer(donor["id"], estimated_weight_lbs=50, publish=True)
        set_clock("2026-08-02T09:30:00Z")
        ov_stale = get_offer_version(offer["id"])
        r1 = dispatch_run(offer["id"], driver_id=driver["id"],
                          agency_id=agency["id"], cooler_ids=[cooler["id"]])
        respond_run(r1["id"], driver["id"], "DECLINE")
        return {"offer": offer, "driver": driver, "agency": agency,
                "cooler": cooler, "ov_stale": ov_stale}

    def test_stale_version_rejected_even_when_offer_open_again(self, api):
        """PRD §2.6: "Dispatching a rescue run requires the request to carry
        `expected_offer_version`, holding the `version` of the target
        `DonationOffer` as the client last observed it. If the offer's current
        `version` has advanced past that value, the dispatch is rejected with
        `ERR_STALE_OFFER_VERSION` (HTTP 412). This guard exists because an offer
        can legitimately be `OPEN` again at a newer version — for instance after
        an earlier run was declined and the offer reverted from `MATCHED` back
        to `OPEN` — so no state precondition can catch the stale write; only the
        version comparison can."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_offer_version_rejected_fresh_accepted
        """
        s = self._setup_declined_offer(api)
        payload = {"offer_id": s["offer"]["id"],
                   "expected_offer_version": s["ov_stale"],
                   "driver_id": s["driver"]["id"],
                   "agency_id": s["agency"]["id"],
                   "cooler_ids": [s["cooler"]["id"]]}
        resp = api.create_rescue_run(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_OFFER_VERSION)

    def test_fresh_version_accepted_after_stale_rejection(self, api):
        """PRD §2.6: "Dispatching a rescue run requires the request to carry
        `expected_offer_version`, holding the `version` of the target
        `DonationOffer` as the client last observed it. If the offer's current
        `version` has advanced past that value, the dispatch is rejected with
        `ERR_STALE_OFFER_VERSION` (HTTP 412)."
        PRD §2.5: "`version` is an integer that increments on every mutation of
        the resource and anchors the optimistic-concurrency rules of §2.6."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_offer_version_rejected_fresh_accepted
        """
        s = self._setup_declined_offer(api)
        payload = {"offer_id": s["offer"]["id"],
                   "expected_offer_version": s["ov_stale"],
                   "driver_id": s["driver"]["id"],
                   "agency_id": s["agency"]["id"],
                   "cooler_ids": [s["cooler"]["id"]]}
        resp = api.create_rescue_run(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_OFFER_VERSION)
        # Dispatch and decline each mutated the offer once since ov_stale.
        ov_fresh = get_offer_version(s["offer"]["id"])
        assert ov_fresh == s["ov_stale"] + 2
        payload["expected_offer_version"] = ov_fresh
        resp = api.create_rescue_run(payload, ADMIN)
        run = validate_success(resp, 201)
        assert run["run_status"] == "PROPOSED"


class TestStaleDonorVersion:
    def _setup_issued_receipt(self, api):
        create_rate_card()
        ctx = setup_verified_run(food_category="SHELF_STABLE",
                                 estimated_weight_lbs=10, actual_weight_lbs=10,
                                 agency_capacity_lbs=100,
                                 verify_clock="2026-08-02T13:20:00Z")
        dv_stale = get_donor_version(ctx["donor"]["id"])
        resp = issue_receipt(ctx["donor"]["id"], *PERIOD)
        rc1 = validate_success(resp, 201)
        return {"ctx": ctx, "dv_stale": dv_stale, "rc1": rc1}

    def test_stale_donor_version_rejected_on_replay(self, api):
        """PRD §2.6: "Issuing a tax receipt requires the request to carry
        `expected_donor_version`, holding the `version` of the `DonorSite` as
        the client last observed it. A mismatch with the donor's current
        `version` is rejected with `ERR_STALE_DONOR_VERSION` (HTTP 412)."
        PRD §3.8: "The donor's `lifetime_tax_value_cents` is recomputed as the
        sum of `deductible_value_cents` over the donor's `ISSUED` receipts only,
        and the act of issuance increments the donor site's `version` by one —
        which is exactly what the `expected_donor_version` guard of §2.6
        watches."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_donor_version_rejected_and_supersede_amends
        """
        s = self._setup_issued_receipt(api)
        # The first issuance bumped DonorSite.version: replaying the captured
        # pre-issuance version is a stale write.
        resp = api.issue_tax_receipt(
            s["ctx"]["donor"]["id"],
            {"period_start": PERIOD[0], "period_end": PERIOD[1],
             "expected_donor_version": s["dv_stale"]},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_DONOR_VERSION)
        # The rejected issuance mutated nothing: the donor's version moved by
        # exactly one (the successful issuance) since dv_stale was captured.
        assert get_donor_version(s["ctx"]["donor"]["id"]) == s["dv_stale"] + 1

    def test_fresh_version_supersedes_identical_period_receipt(self, api):
        """PRD §2.6: "Issuing a receipt for a period that already has an
        `ISSUED` receipt legitimately supersedes that receipt under the
        amendment rule of §3.8, so again only the version check can reject a
        stale write."
        PRD §3.8: "Issuing a new receipt for the same donor with identical
        `period_start` and `period_end` supersedes the previously `ISSUED`
        receipt, which becomes `AMENDED`; an `AMENDED` receipt never contributes
        to anything downstream."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_donor_version_rejected_and_supersede_amends
        """
        s = self._setup_issued_receipt(api)
        donor_id = s["ctx"]["donor"]["id"]
        resp = api.issue_tax_receipt(
            donor_id,
            {"period_start": PERIOD[0], "period_end": PERIOD[1],
             "expected_donor_version": s["dv_stale"]},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_DONOR_VERSION)
        # The fresh version succeeds and legitimately amends the prior receipt.
        resp = issue_receipt(donor_id, *PERIOD)
        rc2 = validate_success(resp, 201)
        assert rc2["deductible_value_cents"] == 1200, "10 lbs x 120 (SHELF_STABLE)"
        resp = api.list_donor_tax_receipts(donor_id, ADMIN,
                                           params={"status": "AMENDED"})
        amended = validate_success(resp)
        assert [r["id"] for r in amended] == [s["rc1"]["id"]]
        resp = api.list_donor_tax_receipts(donor_id, ADMIN,
                                           params={"status": "ISSUED"})
        issued = validate_success(resp)
        assert [r["id"] for r in issued] == [rc2["id"]]
