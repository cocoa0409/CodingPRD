"""Renewal document execution, final-variant pricing, and rescission (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_renewal_document,
    create_offer_for_lease,
    create_offer_payload,
    get_document_for_offer,
    get_lease,
    get_offer,
    issue_offer,
    make_resident_headers,
    resident_accept,
    respond_accept_payload,
    set_clock,
    setup_accepted_offer_scenario,
    setup_executed_renewal_scenario,
    setup_issued_offer_scenario,
    setup_lease_scenario,
    validate_error,
    validate_success,
)

PM1 = TEST_USERS["pm_1_headers"]
LA1 = TEST_USERS["la_1_headers"]


class TestAcceptanceSideEffects:
    def test_accept_creates_document_side_effect(self, api):
        """PRD §3.4: "Acceptance stamps `accepted_on_date` with the clock date, sets
        the `execution_deadline_date` ten days out, moves the offer to `ACCEPTED`,
        and automatically generates the renewal document described in §3.7 — at most
        one document ever exists per offer."
        PRD §3.7: "Resident acceptance of an offer automatically creates the
        RenewalDocument for that offer in `GENERATED` status, denormalizing the
        `lease_id` from the offer; each offer has at most one document."

        Design: Corner/state_machines/accept_creates_document_side_effect
        """
        sc = setup_issued_offer_scenario(
            rate_strategy="CONSERVATIVE", property_name="Side Effect Court",
            unit_number="207")
        resp = api.respond_to_offer(
            sc["offer"]["id"], respond_accept_payload(),
            make_resident_headers(sc["resident"]["id"]))
        offer = validate_success(resp, 200)
        assert offer["status"] == "ACCEPTED"
        assert offer["accepted_on_date"] == "2026-05-01"
        assert offer["execution_deadline_date"] == "2026-05-11"
        doc = get_document_for_offer(offer["id"])
        assert_renewal_document(doc)
        assert doc["status"] == "GENERATED"
        assert doc["lease_id"] == sc["lease"]["id"]


class TestDocumentStateGates:
    def test_countersign_unsigned_document_rejected(self, api):
        """PRD §3.7: "A `PropertyManager` or `RegionalDirector` then countersigns,
        which requires `RESIDENT_SIGNED` (`ERR_DOCUMENT_INVALID_STATE` otherwise) and
        requires the lease not to be `ENDED` — unreachable in practice, since lease
        enforcement voids the document first, but enforced as defense in depth."
        PRD §3.7: "Within three days of countersign — the clock date must be on or
        before `rescind_deadline_date`, else `ERR_RESCISSION_WINDOW_LAPSED` — the
        resident may rescind the executed renewal, which requires the document to be
        `COUNTERSIGNED` (`ERR_DOCUMENT_INVALID_STATE` otherwise) and enforces
        resident ownership."

        Design: Corner/state_machines/countersign_unsigned_document_rejected
        """
        sc = setup_accepted_offer_scenario(
            rate_strategy="CONSERVATIVE", property_name="Sign Gate", unit_number="206")
        doc = sc["document"]
        resp = api.countersign_document(doc["id"], PM1)
        validate_error(resp, ApiErrorId.ERR_DOCUMENT_INVALID_STATE)
        resp = api.rescind_document(
            doc["id"], make_resident_headers(sc["resident"]["id"]))
        validate_error(resp, ApiErrorId.ERR_DOCUMENT_INVALID_STATE)
        assert api.get_renewal_document(doc["id"], PM1).json()["data"]["status"] == "GENERATED"
        assert get_offer(sc["offer"]["id"])["status"] == "ACCEPTED"

    def test_withdraw_executed_offer_rejected(self, api):
        """PRD §3.4: "Any open offer in `DRAFT`, `ISSUED`, or `COUNTERED` may be
        withdrawn by staff; offers already in a terminal state reject the withdrawal
        with `ERR_OFFER_NOT_WITHDRAWABLE`."

        Design: Corner/state_machines/withdraw_executed_offer_rejected
        """
        sc = setup_executed_renewal_scenario(
            rate_strategy="CONSERVATIVE", property_name="Lock Court", unit_number="204")
        assert sc["offer"]["status"] == "EXECUTED"
        resp = api.withdraw_offer(sc["offer"]["id"], LA1)
        validate_error(resp, ApiErrorId.ERR_OFFER_NOT_WITHDRAWABLE)
        assert get_offer(sc["offer"]["id"])["status"] == "EXECUTED"

    def test_resident_cannot_countersign_document(self, api):
        """PRD §2.1: "Beyond authentication, each endpoint authorizes a fixed list of
        roles; a caller whose role is not on the list for the endpoint they invoked
        is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §3.7: "A `PropertyManager` or `RegionalDirector` then countersigns, which
        requires `RESIDENT_SIGNED` (`ERR_DOCUMENT_INVALID_STATE` otherwise) and
        requires the lease not to be `ENDED` — unreachable in practice, since lease
        enforcement voids the document first, but enforced as defense in depth."

        Design: Corner/rbac/resident_cannot_countersign_document
        """
        sc = setup_accepted_offer_scenario(
            rate_strategy="CONSERVATIVE", property_name="Countersign Gate",
            unit_number="CS1")
        res_headers = make_resident_headers(sc["resident"]["id"])
        validate_success(api.sign_document_resident(sc["document"]["id"], res_headers), 200)
        # The owning resident legitimately signed, yet countersign is staff-only.
        resp = api.countersign_document(sc["document"]["id"], res_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        doc = api.get_renewal_document(sc["document"]["id"], PM1).json()["data"]
        assert doc["status"] == "RESIDENT_SIGNED"


class TestFinalVariantPricing:
    def _policy_drift_fixture(self, api):
        """AGGRESSIVE offer at cap snapshot 550, accepted and resident-signed, then
        the policy CPI is patched 150 -> 50 (effective cap 550 -> 450)."""
        sc = setup_lease_scenario(
            band_min=12, band_max=12, market_rent_cents=240000,
            monthly_rent_cents=200000, property_name="Cypress Court", unit_number="101",
            resident_name="Rin Aoki", resident_email="rin.aoki@x.com")
        resp = api.create_renewal_offer(
            sc["lease"]["id"],
            create_offer_payload(sc["lease"]["version"], rate_strategy="AGGRESSIVE"),
            LA1)
        offer = validate_success(resp, 201)
        sc["offer_created"] = offer
        issue_offer(offer["id"])
        resident_accept(offer["id"], sc["resident"]["id"])
        doc = get_document_for_offer(offer["id"])
        res_headers = make_resident_headers(sc["resident"]["id"])
        validate_success(api.sign_document_resident(doc["id"], res_headers), 200)
        sc["document"] = doc
        # Policy drifts after issue: cpi 150 -> 50, so the cap becomes 450.
        resp = api.patch_rent_cap_policy(
            sc["policy"]["id"], {"cpi_adjustment_bps": 50}, TEST_USERS["admin_headers"])
        sc["policy_after"] = validate_success(resp, 200)
        return sc

    def test_provisional_vs_executed_rent_policy_drift_values(self, api):
        """PRD §2.8: "Three consumption rules keep policy edits honest across the
        renewal lifecycle. An offer being created snapshots the policy's effective
        cap onto itself, and that snapshot governs the provisional pricing shown to
        the resident no matter how the policy later drifts. A revision issued
        mid-negotiation is checked against the policy's *current* effective cap, not
        the snapshot — the statute binds the offer at the moment it is re-issued.
        Final execution at document countersign prices the renewal against the
        then-current policy and then-current market rent once more."
        PRD §3.7: "Countersign is the moment the renewal's economics are locked by
        the final pricing variant: the six-step pipeline of §3.3 runs again with the
        policy's *then-current* `effective_cap_bps`, the unit's *then-current*
        `current_market_rent_cents`, and the lease's *then-current*
        `monthly_rent_cents` as the base, while the offer's `rate_strategy` and
        `offered_term_months` carry through unchanged."

        Design: Difficulty/dual_variant_calc/provisional_vs_executed_rent_policy_drift
        """
        sc = self._policy_drift_fixture(api)
        # Provisional variant: gap 2000 bps, AGGRESSIVE, capped at the frozen
        # snapshot 550 -> 211000.
        assert sc["offer_created"]["proposed_rent_cents"] == 211000
        assert sc["offer_created"]["cap_bps_snapshot"] == 550
        assert sc["policy_after"]["effective_cap_bps"] == 450
        resp = api.countersign_document(sc["document"]["id"], PM1)
        doc = validate_success(resp, 200)
        # Final variant: same gap, capped at the THEN-current 450 -> 209000.
        assert doc["executed_rent_cents"] == 209000
        offer = get_offer(sc["offer_created"]["id"])
        assert offer["executed_rent_cents"] == 209000

    def test_provisional_vs_executed_rent_policy_drift_states(self, api):
        """PRD §3.7: "The offer moves from `ACCEPTED` to `EXECUTED`. The lease is
        renewed: its `monthly_rent_cents` becomes the executed rent, its new
        `term_start_date` is the later of the old `term_end_date` and the current
        clock date, `term_months` becomes the offer's `offered_term_months`,
        `term_end_date` is recomputed from those values, status returns to `ACTIVE`,
        `status_before_offer` clears, and the lease's `version` increments by one."

        Design: Difficulty/dual_variant_calc/provisional_vs_executed_rent_policy_drift
        """
        sc = self._policy_drift_fixture(api)
        resp = api.countersign_document(sc["document"]["id"], PM1)
        doc = validate_success(resp, 200)
        assert doc["status"] == "COUNTERSIGNED"
        offer = get_offer(sc["offer_created"]["id"])
        assert offer["status"] == "EXECUTED"
        lease = get_lease(sc["lease"]["id"])
        assert lease["monthly_rent_cents"] == 209000
        assert lease["status"] == "ACTIVE"
        # new start = max(old end 2027-06-01, clock 2026-05-01); +12 months.
        assert lease["term_start_date"] == "2027-06-01"
        assert lease["term_end_date"] == "2028-06-01"
        assert lease["status_before_offer"] is None


class TestRescission:
    def _executed_conservative(self, api):
        return setup_executed_renewal_scenario(
            rate_strategy="CONSERVATIVE", band_min=12, band_max=12,
            market_rent_cents=210000, monthly_rent_cents=200000,
            property_name="Restore Court", unit_number="1201")

    def test_countersign_then_rescind_restores_lease_economics(self, api):
        """PRD §3.7: "Rescission moves the document to `RESCINDED`, moves the offer
        from `EXECUTED` to `VOIDED`, and restores the lease from the document's
        snapshot: the four economic fields return to their `prior_*` values, status
        becomes the captured `prior_lease_status`, and `status_before_offer` clears."

        Design: Difficulty/compensating_invariant/countersign_then_rescind_restores_lease_economics
        """
        sc = self._executed_conservative(api)
        # Forward act applied: executed 203000 (150 bps), new term from old end.
        mid = sc["lease"]
        assert mid["monthly_rent_cents"] == 203000
        assert mid["term_end_date"] == "2028-06-01"
        assert mid["status"] == "ACTIVE"

        resp = api.rescind_document(
            sc["document"]["id"], make_resident_headers(sc["resident"]["id"]))
        validate_success(resp, 200)
        lease = get_lease(sc["lease"]["id"])
        # The compensating action conserves the economics exactly.
        assert lease["monthly_rent_cents"] == 200000
        assert lease["term_start_date"] == "2026-06-01"
        assert lease["term_months"] == 12
        assert lease["term_end_date"] == "2027-06-01"
        assert lease["status"] == "ACTIVE"
        assert lease["status_before_offer"] is None

    def test_countersign_then_rescind_moves_document_and_offer(self, api):
        """PRD §3.7: "Within three days of countersign — the clock date must be on or
        before `rescind_deadline_date`, else `ERR_RESCISSION_WINDOW_LAPSED` — the
        resident may rescind the executed renewal, which requires the document to be
        `COUNTERSIGNED` (`ERR_DOCUMENT_INVALID_STATE` otherwise) and enforces
        resident ownership. Rescission moves the document to `RESCINDED`, moves the
        offer from `EXECUTED` to `VOIDED`, and restores the lease from the document's
        snapshot: the four economic fields return to their `prior_*` values, status
        becomes the captured `prior_lease_status`, and `status_before_offer` clears."

        Design: Difficulty/compensating_invariant/countersign_then_rescind_restores_lease_economics
        """
        sc = self._executed_conservative(api)
        # countersigned 2026-05-01 -> rescind deadline 2026-05-04.
        assert sc["document"]["rescind_deadline_date"] == "2026-05-04"
        resp = api.rescind_document(
            sc["document"]["id"], make_resident_headers(sc["resident"]["id"]))
        doc = validate_success(resp, 200)
        assert doc["status"] == "RESCINDED"
        assert get_offer(sc["offer"]["id"])["status"] == "VOIDED"

    def test_rescind_after_window_rejected(self, api):
        """PRD §3.7: "Within three days of countersign — the clock date must be on or
        before `rescind_deadline_date`, else `ERR_RESCISSION_WINDOW_LAPSED` — the
        resident may rescind the executed renewal, which requires the document to be
        `COUNTERSIGNED` (`ERR_DOCUMENT_INVALID_STATE` otherwise) and enforces
        resident ownership."

        Design: Corner/validations/rescind_after_window_rejected
        """
        sc = setup_executed_renewal_scenario(
            rate_strategy="CONSERVATIVE", band_min=12, band_max=12,
            market_rent_cents=210000, monthly_rent_cents=200000,
            property_name="Window Lapse Court", unit_number="WL1")
        assert sc["document"]["rescind_deadline_date"] == "2026-05-04"
        set_clock("2026-05-05T00:00:00Z")
        resp = api.rescind_document(
            sc["document"]["id"], make_resident_headers(sc["resident"]["id"]))
        validate_error(resp, ApiErrorId.ERR_RESCISSION_WINDOW_LAPSED)
        # The executed economics stand.
        assert get_lease(sc["lease"]["id"])["monthly_rent_cents"] == 203000
