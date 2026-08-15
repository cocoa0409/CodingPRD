"""Validation priority ordering when several checks could reject the same
request (PRD §2.8)."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, ApiErrorId,
    create_donor, create_agency, create_driver, add_window, create_cooler,
    create_offer, set_clock, dispatch_run, get_offer_version,
)

ADMIN = TEST_USERS["admin_headers"]


class TestStateErrorBeatsFiscalError:
    def _setup(self, api):
        """Offer O already MATCHED via a first dispatch; AG2 has 1 lb of cold
        capacity left for the 50-lb second dispatch attempt."""
        donor = create_donor(legal_name="Prio Bistro", ein="121212121",
                             contact_email="pr@bistro.example")
        ag1 = create_agency(name="AG1")
        ag2 = create_agency(name="AG2", capacity_cold_held_lbs=1)
        driver = create_driver(cold_chain_certified=True)
        add_window(driver["id"])
        cooler = create_cooler(label="C1")
        offer = create_offer(donor["id"], estimated_weight_lbs=50, publish=True)
        set_clock("2026-08-02T09:30:00Z")
        dispatch_run(offer["id"], driver_id=driver["id"], agency_id=ag1["id"],
                     cooler_ids=[cooler["id"]])
        return {"donor": donor, "ag2": ag2, "driver": driver,
                "cooler": cooler, "offer": offer}

    def test_matched_offer_dispatch_reports_state_not_capacity(self, api):
        """PRD §2.8: "6. **State admissibility** — the target resource's
        lifecycle must admit the operation, including cross-entity state
        preconditions such as an active donor at publish time or an active
        driver at window declaration or pinned dispatch"
        PRD §2.8: "11. **Capacity quotas** — vehicle capacity, agency
        committed-versus-capacity, cooler liters within slot limits, delivery
        overage, and the two fiscal gates on receipts"

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_fiscal_error_on_dispatch
        """
        s = self._setup(api)
        payload = {"offer_id": s["offer"]["id"],
                   "expected_offer_version": get_offer_version(s["offer"]["id"]),
                   "driver_id": s["driver"]["id"], "agency_id": s["ag2"]["id"],
                   "cooler_ids": [s["cooler"]["id"]]}
        resp = api.create_rescue_run(payload, ADMIN)
        # The offer is MATCHED (state, tier 6) AND the pinned agency is 49 lbs
        # short (fiscal, tier 11): the state error must be the one reported.
        validate_error(resp, ApiErrorId.ERR_OFFER_NOT_OPEN)

    def test_rejected_dispatch_mutates_nothing(self, api):
        """PRD §2.8: "When several checks could reject the same request, they
        fire in a fixed order so the surfaced error is deterministic."
        PRD §3.3: "an offer that is not `OPEN` — after the lazy expiry of §2.4
        has had its say — answers `ERR_OFFER_NOT_OPEN`."

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_fiscal_error_on_dispatch
        """
        s = self._setup(api)
        version_before = get_offer_version(s["offer"]["id"])
        payload = {"offer_id": s["offer"]["id"],
                   "expected_offer_version": version_before,
                   "driver_id": s["driver"]["id"], "agency_id": s["ag2"]["id"],
                   "cooler_ids": [s["cooler"]["id"]]}
        resp = api.create_rescue_run(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_OFFER_NOT_OPEN)
        resp = api.get_donation_offer(s["offer"]["id"], ADMIN)
        offer = validate_success(resp)
        assert offer["status"] == "MATCHED"
        assert offer["version"] == version_before
        resp = api.get_recipient_agency(s["ag2"]["id"], ADMIN)
        assert validate_success(resp)["committed_cold_held_lbs"] == 0


class TestSafetyErrorBeatsTemporalError:
    def test_uncertified_and_windowless_driver_reports_certification(self, api):
        """PRD §2.8: "8. **Cold-chain safety** — certification, the pickup kill
        screen, and the delivery danger-zone verdict
        (`ERR_DRIVER_NOT_COLD_CHAIN_CERTIFIED`, `ERR_SAFETY_VIOLATION_AT_PICKUP`,
        `ERR_SAFETY_VERDICT_VIOLATION`)."
        PRD §2.8: "9. **Temporal interval rules** — availability-window overlap,
        driver window coverage, cooler buffered-interval conflicts, and
        rate-card window overlap"

        Design: Difficulty/priority_pair_validation_conflict/safety_error_beats_temporal_error_on_dispatch
        """
        donor = create_donor(legal_name="Safe Bistro", ein="343434343",
                             contact_email="s@bistro.example")
        agency = create_agency()
        vx = create_driver(full_name="V X", email="vx@example.com",
                           cold_chain_certified=False)
        cooler = create_cooler(label="C1")
        offer = create_offer(donor["id"], estimated_weight_lbs=10, publish=True)
        set_clock("2026-08-02T09:30:00Z")
        payload = {"offer_id": offer["id"],
                   "expected_offer_version": get_offer_version(offer["id"]),
                   "driver_id": vx["id"], "agency_id": agency["id"],
                   "cooler_ids": [cooler["id"]]}
        resp = api.create_rescue_run(payload, ADMIN)
        # VX is BOTH uncertified (tier 8) AND missing a covering window
        # (tier 9): the safety error must be the one reported.
        validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_COLD_CHAIN_CERTIFIED)

    def test_certified_driver_without_window_reports_window(self, api):
        """PRD §3.3: "a missing cold-chain certificate on a cold-chain offer
        answers `ERR_DRIVER_NOT_COLD_CHAIN_CERTIFIED`, insufficient vehicle
        capacity answers `ERR_DRIVER_CAPACITY_EXCEEDED`, and the absence of a
        covering `OPEN` window answers `ERR_DRIVER_WINDOW_MISSING`."

        Design: Difficulty/priority_pair_validation_conflict/safety_error_beats_temporal_error_on_dispatch
        """
        donor = create_donor(legal_name="Safe Bistro", ein="343434343",
                             contact_email="s@bistro.example")
        agency = create_agency()
        vc = create_driver(full_name="V C", email="vc@example.com",
                           cold_chain_certified=True)
        cooler = create_cooler(label="C1")
        offer = create_offer(donor["id"], estimated_weight_lbs=10, publish=True)
        set_clock("2026-08-02T09:30:00Z")
        payload = {"offer_id": offer["id"],
                   "expected_offer_version": get_offer_version(offer["id"]),
                   "driver_id": vc["id"], "agency_id": agency["id"],
                   "cooler_ids": [cooler["id"]]}
        resp = api.create_rescue_run(payload, ADMIN)
        # Control: with certification satisfied, the very same setup surfaces
        # the tier-9 temporal error — both violations were genuinely present.
        validate_error(resp, ApiErrorId.ERR_DRIVER_WINDOW_MISSING)


class TestSchemaBeatsExistence:
    def test_malformed_dispatch_body_beats_bogus_foreign_key(self, api):
        """PRD §2.8: "3. **Body well-formedness** — required fields present, no
        unknown fields, correct types, valid enum members, positive integers
        where noted, `window_end` after `window_start`, pickup window length
        within the permitted band"
        PRD §2.8: "4. **Existence** — path identifiers left to right, then body
        foreign keys (the resource-specific 404 family of §2.7)."

        Design: Corner/validations/schema_validation_beats_existence_rejected
        """
        # Missing the required offer_id AND carrying a bogus driver_id: the
        # schema check (tier 3) fires before any 404 resolution (tier 4).
        resp = api.create_rescue_run(
            {"driver_id": "00000000-0000-4000-8000-0000000000zz"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
