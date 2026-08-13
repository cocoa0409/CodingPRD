"""Leases: generation gates (leasability, OCC, offer pinning, override floor),
snapshot semantics, signing deadline expiry, regeneration blocking, and the
committed-units ledger across supersede and cancel."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_conditions_cleared_application,
    add_issued_lease,
    add_leasable_application,
    create_lease_payload,
    create_floorplan,
    create_pricing_offer,
    get_application,
    get_floorplan,
    get_lease,
    publish_offer,
    set_clock,
    setup_site,
    sign_lease,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["property_manager_headers"]


class TestLeaseGenerationGates:
    def test_lease_generation_rejected_while_application_screening(self, api):
        """PRD §3.6: "The application must be `APPROVED` or `CONDITIONS_CLEARED`;
        anything else is `ERR_APPLICATION_NOT_LEASABLE`."

        Design: Difficulty/cross_entity_state_dependency/lease_generation_requires_leasable_application
        """
        site = setup_site(floorplan_overrides={"total_units": 1})
        bundle = add_leasable_application(site, decision=None)  # stays SCREENING

        resp = api.create_lease(
            create_lease_payload(bundle["application"]["id"],
                                 bundle["application_version"]),
            PM)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_LEASABLE)
        data, _ = validate_paginated(api.list_leases(
            PM, params={"application_id": bundle["application"]["id"]}))
        assert data == [], "a rejected generation must not persist a lease"

    def test_lease_generation_rejected_after_application_withdrawn(self, api):
        """PRD §3.6: "The application must be `APPROVED` or `CONDITIONS_CLEARED`;
        anything else is `ERR_APPLICATION_NOT_LEASABLE`."
        PRD §3.5: "Withdrawal is permitted from `SCREENING` or
        `APPROVED_WITH_CONDITIONS` and lands the application in the terminal
        `WITHDRAWN` state; from anywhere else the request is
        `ERR_APPLICATION_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/lease_generation_requires_leasable_application
        """
        from test_helpers import withdraw_application
        site = setup_site(floorplan_overrides={"total_units": 1})
        bundle = add_leasable_application(site, decision=None)
        withdrawn = withdraw_application(bundle["application"]["id"],
                                         site["agent"]["id"])

        resp = api.create_lease(
            create_lease_payload(bundle["application"]["id"], withdrawn["version"]),
            PM)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_LEASABLE)


class TestLeaseSnapshots:
    def test_lease_snapshots_property_addenda_at_generation(self, api):
        """PRD §3.6: "Each generated lease copies its `floorplan_id` from the
        application, snapshots `deposit_cents` from the application's
        `required_deposit_cents`, snapshots `addenda_codes` from the property's
        `required_addenda` — addenda vary by property, so the lease freezes them at
        generation — and sets `signing_deadline` to forty-eight hours after
        creation."
        PRD §3.6: "The lease pins `monthly_rent_cents` by a fixed precedence: a
        valid `rent_override_cents` wins; otherwise the selected published offer's
        `effective_monthly_rent_cents`; with no offer selected, the floorplan's
        `base_rent_cents`."

        Design: Corner/endpoints/lease_snapshots_property_addenda_at_generation
        """
        from test_helpers import assert_same_instant, generate_lease
        site = setup_site(
            property_overrides={
                "required_addenda": ["PET_ADDENDUM", "PARKING_ADDENDUM"]})
        bundle = add_conditions_cleared_application(
            site, app_overrides={"annual_income_cents": 8000000, "credit_score": 650})
        assert bundle["application"]["status"] == "CONDITIONS_CLEARED"

        lease = generate_lease(bundle["application"]["id"],
                               bundle["application_version"])
        assert lease["status"] == "ISSUED"
        assert lease["addenda_codes"] == ["PET_ADDENDUM", "PARKING_ADDENDUM"]
        assert lease["deposit_cents"] == 400000, "2x conditional deposit snapshot"
        assert lease["monthly_rent_cents"] == 200000
        # Generated at the default logical clock 2026-08-01T00:00:00Z + 48h.
        assert_same_instant(lease["signing_deadline"], "2026-08-03T00:00:00Z",
                            label="signing_deadline")


class TestSigningDeadline:
    def test_sign_expired_lease_returns_invalid_state(self, api):
        """PRD §3.6: "Signing requires the lease to be `ISSUED` (any other state is
        `ERR_LEASE_INVALID_STATE`), requires the current logical time to fall
        strictly before `signing_deadline` — at or past the deadline the lease is
        treated as `EXPIRED` and the signing attempt is likewise rejected with
        `ERR_LEASE_INVALID_STATE` — and requires the caller's `X-User-ID` to equal
        the lease's `application_id`, with a mismatch rejected as
        `ERR_APPLICANT_MISMATCH`."
        PRD §3.6: "A lease that passes its deadline unsigned expires lazily per
        §2.4: it leaves the committed set, the floorplan's `committed_units` is
        recomputed, and the freed unit may trigger auto-promotion of the waitlist
        queue head."

        Design: Corner/state_machines/sign_expired_lease_returns_invalid_state
        """
        from test_helpers import make_applicant_headers
        site = setup_site(floorplan_overrides={"total_units": 1})
        bundle = add_issued_lease(site)
        assert get_floorplan(site["floorplan"]["id"])["committed_units"] == 1

        # Advance the logical clock to exactly the signing deadline (created at
        # 2026-08-01T00:00:00Z + 48h): the boundary is inclusive for expiry.
        set_clock("2026-08-03T00:00:00Z")
        resp = api.sign_lease(bundle["lease"]["id"],
                              make_applicant_headers(bundle["application"]["id"]))
        validate_error(resp, ApiErrorId.ERR_LEASE_INVALID_STATE)
        assert get_lease(bundle["lease"]["id"])["status"] == "EXPIRED"
        assert get_floorplan(site["floorplan"]["id"])["committed_units"] == 0, \
            "the expired lease leaves the committed set"


class TestRegeneration:
    def test_regenerate_blocked_when_lease_signed(self, api):
        """PRD §3.6: "Regeneration is blocked entirely once any lease for the
        application has reached `SIGNED_BY_APPLICANT` or `EXECUTED` — the parties
        are already committed, and the request is rejected with
        `ERR_LEASE_ALREADY_COMMITTED`."

        Design: Corner/validations/regenerate_blocked_when_lease_signed
        """
        site = setup_site()
        bundle = add_issued_lease(site)
        sign_lease(bundle["lease"]["id"], bundle["application"]["id"])
        fresh_version = get_application(bundle["application"]["id"])["version"]

        # Even a fresh OCC version cannot rescue regeneration of a signed lease.
        resp = api.create_lease(
            create_lease_payload(bundle["application"]["id"], fresh_version), PM)
        validate_error(resp, ApiErrorId.ERR_LEASE_ALREADY_COMMITTED)
        data, _ = validate_paginated(api.list_leases(
            PM, params={"application_id": bundle["application"]["id"]}))
        assert [lease["id"] for lease in data] == [bundle["lease"]["id"]]
        assert data[0]["status"] == "SIGNED_BY_APPLICANT"


class TestRentOverride:
    def test_rent_override_below_floor_rejected(self, api):
        """PRD §3.6: "An override is valid only when it reaches at least eighty
        percent of the rent that would otherwise be pinned, with that floor computed
        and rounded half-up to whole cents; a lower override is rejected with
        `ERR_RENT_OVERRIDE_TOO_LOW` (HTTP 422)."
        PRD §3.6: "The lease pins `monthly_rent_cents` by a fixed precedence: a
        valid `rent_override_cents` wins; otherwise the selected published offer's
        `effective_monthly_rent_cents`; with no offer selected, the floorplan's
        `base_rent_cents`."

        Design: Corner/validations/rent_override_below_floor_rejected
        """
        site = setup_site()
        bundle = add_leasable_application(site, decision="APPROVED")
        app_id = bundle["application"]["id"]
        version = bundle["application_version"]

        # Computed rent 200000 -> floor round_half_up(0.8 * 200000) = 160000.
        resp = api.create_lease(
            create_lease_payload(app_id, version, rent_override_cents=159999), PM)
        validate_error(resp, ApiErrorId.ERR_RENT_OVERRIDE_TOO_LOW, 422)

        # The failed attempt created nothing and did not advance the application,
        # so the same expected version succeeds on retry at the inclusive floor.
        ok = api.create_lease(
            create_lease_payload(app_id, version, rent_override_cents=160000), PM)
        lease = validate_success(ok, 201)
        assert lease["monthly_rent_cents"] == 160000
        assert lease["deposit_cents"] == 200000, "1x standard deposit snapshot"


class TestOptimisticConcurrency:
    def test_occ_stale_version_rejected_then_fresh_succeeds(self, api):
        """PRD §2.8: "A generation request must carry
        `expected_application_version`, holding the `version` of the application as
        the client last observed it; the field is not optional. If the application's
        current `version` no longer matches the submitted value — because another
        write has advanced the application since the client last read it — the
        generation is rejected with `ERR_STALE_VERSION` (HTTP 412), and no lease is
        created."
        PRD §2.8: "A successful generation itself advances the application's
        `version` by one."
        PRD §3.6: "When a prior lease for the same application is still `ISSUED`,
        generating a new lease supersedes it: the old lease becomes `SUPERSEDED`
        with `superseded_by_id` pointing at the new lease, and because the departing
        lease leaves the committed set exactly as the new `ISSUED` lease enters it,
        `committed_units` nets out unchanged."

        Design: Corner/cross_cutting_layers/occ_stale_version_rejected_then_fresh_succeeds
        """
        site = setup_site()
        bundle = add_leasable_application(site, decision="APPROVED")
        app_id = bundle["application"]["id"]
        observed_version = bundle["application_version"]

        first = api.create_lease(create_lease_payload(app_id, observed_version), PM)
        lease1 = validate_success(first, 201)
        assert lease1["status"] == "ISSUED"

        # Replaying the pre-generation version is now stale.
        stale = api.create_lease(create_lease_payload(app_id, observed_version), PM)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

        current_version = get_application(app_id)["version"]
        assert current_version == observed_version + 1, \
            "each successful generation advances the application version by one"

        second = api.create_lease(create_lease_payload(app_id, current_version), PM)
        lease2 = validate_success(second, 201)
        assert lease2["status"] == "ISSUED"
        superseded = get_lease(lease1["id"])
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["superseded_by_id"] == lease2["id"]


class TestCommittedUnitsInvariant:
    def test_lease_regeneration_supersedes_conserving_committed_units(self, api):
        """PRD §2.7: "`committed_units` counts the floorplan's leases whose status
        is `ISSUED`, `SIGNED_BY_APPLICANT`, or `EXECUTED` — a lease joins the
        committed set the moment it is generated, not when it is signed."
        PRD §3.6: "When a prior lease for the same application is still `ISSUED`,
        generating a new lease supersedes it: the old lease becomes `SUPERSEDED`
        with `superseded_by_id` pointing at the new lease, and because the departing
        lease leaves the committed set exactly as the new `ISSUED` lease enters it,
        `committed_units` nets out unchanged."

        Design: Difficulty/compensating_invariant/lease_generate_supersede_cancel_conserves_committed_units
        """
        site = setup_site()
        bundle = add_issued_lease(site)
        lease1 = bundle["lease"]
        assert get_floorplan(site["floorplan"]["id"])["committed_units"] == 1, \
            "the ISSUED lease commits one unit from the moment of generation"

        fresh_version = get_application(bundle["application"]["id"])["version"]
        lease2 = validate_success(api.create_lease(
            create_lease_payload(bundle["application"]["id"], fresh_version), PM), 201)

        superseded = get_lease(lease1["id"])
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["superseded_by_id"] == lease2["id"]
        floorplan = get_floorplan(site["floorplan"]["id"])
        assert floorplan["committed_units"] == 1, \
            "supersede is net-zero: the old lease leaves as the new one enters"
        assert floorplan["available_units"] == 1

    def test_lease_cancel_restores_committed_baseline(self, api):
        """PRD §2.7: "The ledger is recomputed immediately on every event that
        changes the committed set: lease generation (a new `ISSUED` lease enters),
        lease supersession (the departing lease leaves exactly as its replacement
        enters, for a net change of zero), lease countersignature (the lease already
        counted since issuance, so the count is refreshed but unchanged), lease
        expiry and lease cancellation (the lease leaves and `available_units` rises
        by one)."
        PRD §3.6: "A `PropertyManager` may cancel from `ISSUED`,
        `SIGNED_BY_APPLICANT`, or `EXECUTED` — from any other state it is
        `ERR_LEASE_INVALID_STATE`."

        Design: Difficulty/compensating_invariant/lease_generate_supersede_cancel_conserves_committed_units
        """
        site = setup_site()
        bundle = add_issued_lease(site)
        fresh_version = get_application(bundle["application"]["id"])["version"]
        lease2 = validate_success(api.create_lease(
            create_lease_payload(bundle["application"]["id"], fresh_version), PM), 201)

        cancelled = validate_success(api.cancel_lease(lease2["id"], PM))
        assert cancelled["status"] == "CANCELLED"
        floorplan = get_floorplan(site["floorplan"]["id"])
        assert floorplan["committed_units"] == 0, \
            "cancel restores the baseline — no drift in the conserved quantity"
        assert floorplan["available_units"] == 2
        # The lease was never executed, so no LEASED compensation applies.
        assert get_application(bundle["application"]["id"])["status"] == "APPROVED"


class TestLeaseValidationPriority:
    def test_lease_create_offer_mismatch_beats_rent_floor(self, api):
        """PRD §2.10: "Eighth, cross-reference integrity: an application must match
        its source's floorplan (`ERR_APPLICATION_FLOORPLAN_MISMATCH`) and a lease's
        selected offer must belong to the application's floorplan
        (`ERR_OFFER_FLOORPLAN_MISMATCH`). Ninth and last, money checks: the deposit
        payment must cover the requirement (`ERR_DEPOSIT_INSUFFICIENT`) and a rent
        override must clear its floor (`ERR_RENT_OVERRIDE_TOO_LOW`). Because the
        order is fixed, a request that would fail two checks always reports the
        earlier one — a mid-flight state problem surfaces before a money problem,
        and a missing resource before either."

        Design: Difficulty/priority_pair_validation_conflict/lease_create_offer_mismatch_beats_rent_floor
        """
        site = setup_site()
        floorplan2 = create_floorplan(site["property"]["id"], name="2BR", bedrooms=2,
                                      base_rent_cents=300000)
        offer2 = create_pricing_offer(site["property"]["id"], floorplan2["id"],
                                      base_rent_cents=300000,
                                      concession_type="PERCENT_OFF",
                                      concession_value=10)
        publish_offer(offer2["id"])  # effective rent 270000; 80% floor 216000
        bundle = add_leasable_application(site, decision="APPROVED")

        # The pinned offer belongs to a different floorplan AND the override is
        # below the floor; the cross-reference error (eighth) must win.
        resp = api.create_lease(
            create_lease_payload(bundle["application"]["id"],
                                 bundle["application_version"],
                                 pricing_offer_id=offer2["id"],
                                 rent_override_cents=1000),
            PM)
        validate_error(resp, ApiErrorId.ERR_OFFER_FLOORPLAN_MISMATCH, 422)
        data, _ = validate_paginated(api.list_leases(
            PM, params={"application_id": bundle["application"]["id"]}))
        assert data == []

    def test_lease_create_offer_from_wrong_floorplan_rejected(self, api):
        """PRD §3.6: "The request may select a `pricing_offer_id`, which must be
        `PUBLISHED` at generation time (a draft, retired, or expired offer is
        `ERR_PRICING_OFFER_INVALID_STATE`) and must belong to the application's
        floorplan (otherwise `ERR_OFFER_FLOORPLAN_MISMATCH`, HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/lease_create_offer_mismatch_beats_rent_floor
        """
        site = setup_site()
        floorplan2 = create_floorplan(site["property"]["id"], name="2BR", bedrooms=2,
                                      base_rent_cents=300000)
        offer2 = create_pricing_offer(site["property"]["id"], floorplan2["id"],
                                      base_rent_cents=300000,
                                      concession_type="PERCENT_OFF",
                                      concession_value=10)
        publish_offer(offer2["id"])
        bundle = add_leasable_application(site, decision="APPROVED")

        # The cross-reference violation alone (no override) yields the same error.
        resp = api.create_lease(
            create_lease_payload(bundle["application"]["id"],
                                 bundle["application_version"],
                                 pricing_offer_id=offer2["id"]),
            PM)
        validate_error(resp, ApiErrorId.ERR_OFFER_FLOORPLAN_MISMATCH, 422)
