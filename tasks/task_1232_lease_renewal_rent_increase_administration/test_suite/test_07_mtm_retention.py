"""Month-to-month conversion and retention reporting (PRD §3.2, §3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_lease,
    create_notice,
    create_offer_for_lease,
    create_offer_payload,
    create_policy,
    create_property,
    create_resident,
    create_unit,
    get_document_for_offer,
    get_lease,
    issue_offer,
    make_resident_headers,
    resident_accept,
    serve_notice,
    set_clock,
    setup_lease_scenario,
    setup_accepted_offer_scenario,
    validate_error,
    validate_success,
)

PM1 = TEST_USERS["pm_1_headers"]
LA1 = TEST_USERS["la_1_headers"]


class TestMtmConversionRounding:
    def _mtm_fixture(self, api):
        """Lease rent 199990 (adversarial odd value), no offers, converted at the
        half-open term end 2027-06-01."""
        sc = setup_lease_scenario(property_name="Rounding Court", unit_number="401",
                                  market_rent_cents=220000, monthly_rent_cents=199990)
        set_clock("2027-06-01T00:00:00Z")
        return sc

    def test_mtm_rent_nested_rounding_order(self, api):
        """PRD §3.2: "The rounding order is pinned: the base is rounded to whole
        cents first, the premium is applied to that rounded base, and the result is
        rounded again. Growing the rent by cap and premium in a single expression
        with one final rounding is a forbidden shortcut, because it can differ from
        the pinned order by a cent."

        Design: Difficulty/combinatorial_formula/mtm_rent_nested_rounding_order
        """
        sc = self._mtm_fixture(api)
        lease = get_lease(sc["lease"]["id"])
        # No issued offer: base = round_half_up(199990 * 1.055) = 210989, then
        # round_half_up(210989 * 1.15) = 242637. The single-rounding variant would
        # answer 242638 — the forbidden shortcut.
        assert lease["monthly_rent_cents"] == 242637

    def test_mtm_conversion_status_and_date(self, api):
        """PRD §3.2: "When the logical clock's sweep finds a lease in `ACTIVE` or
        `RENEWAL_PENDING` whose `term_end_date` has been reached or passed, the lease
        converts to month-to-month: its status becomes `MTM`, `mtm_converted_on`
        records the clock date, and its rent is reset by the month-to-month premium
        calculation."

        Design: Difficulty/combinatorial_formula/mtm_rent_nested_rounding_order
        """
        sc = self._mtm_fixture(api)
        lease = get_lease(sc["lease"]["id"])
        assert lease["status"] == "MTM"
        assert lease["mtm_converted_on"] == "2027-06-01"


class TestAcceptedOfferSweep:
    def test_accepted_offer_voided_after_execution_deadline(self, api):
        """PRD §3.4: "Two terminal outcomes belong to the clock sweep instead: an
        offer in `ISSUED` or `COUNTERED` whose `response_deadline_date` has passed
        becomes `EXPIRED`, and an offer in `ACCEPTED` whose `execution_deadline_date`
        has passed becomes `VOIDED` — which also voids its renewal document if that
        document is still unsigned or resident-signed. Both sweep outcomes void
        pending concessions and run the lease revert check."
        PRD §3.7: "Separately, a document that never reaches countersign is voided
        whenever its offer is voided — whether by a lapsed execution deadline or by
        lease enforcement."

        Design: Corner/state_machines/accepted_offer_voided_after_execution_deadline
        """
        sc = setup_accepted_offer_scenario(
            rate_strategy="CONSERVATIVE", property_name="Void Court", unit_number="210")
        # Accepted 2026-05-01 -> execution deadline 2026-05-11, never signed.
        assert sc["offer"]["execution_deadline_date"] == "2026-05-11"
        set_clock("2026-05-12T00:00:00Z")
        from test_helpers import get_document, get_offer
        assert get_offer(sc["offer"]["id"])["status"] == "VOIDED"
        assert get_document(sc["document"]["id"])["status"] == "VOIDED"
        assert get_lease(sc["lease"]["id"])["status"] == "ACTIVE"


class TestRetentionCohort:
    def _cohort_fixture(self, api):
        """Four leases ending 2027-06-01: L1/L2 fully renewed, L3 enforced to ENDED,
        L4 converts to MTM. Window [2027-06-01, 2027-06-30]."""
        policy = create_policy()
        prop = create_property(policy["id"], name="Retention Gardens")
        units, residents, leases = [], [], []
        for i in range(1, 5):
            units.append(create_unit(prop["id"], market_rent_cents=210000,
                                     unit_number=f"20{i}"))
            residents.append(create_resident(full_name=f"Res {i}", email=f"res{i}@x.com"))
            leases.append(create_lease(units[-1]["id"], residents[-1]["id"]))

        # L1, L2: full renewal loop (CONSERVATIVE 203000) at the default clock.
        for idx in (0, 1):
            offer = create_offer_for_lease(leases[idx], rate_strategy="CONSERVATIVE")
            issue_offer(offer["id"])
            resident_accept(offer["id"], residents[idx]["id"])
            doc = get_document_for_offer(offer["id"])
            validate_success(
                api.sign_document_resident(doc["id"],
                                           make_resident_headers(residents[idx]["id"])),
                200)
            validate_success(api.countersign_document(doc["id"], PM1), 200)

        # L3: non-renewal enforced at its term end.
        notice = create_notice(leases[2]["id"], "OWNER_OCCUPANCY", "2027-06-01",
                               creator_headers=LA1)
        serve_notice(notice["id"], server_headers=PM1)
        set_clock("2026-05-12T00:00:00Z")  # cure lapse -> CONFIRMED
        set_clock("2027-06-01T00:00:00Z")  # enforce L3 -> ENDED; convert L4 -> MTM
        return prop

    def _metrics(self, api, prop_id, variant):
        return validate_success(
            api.get_retention_metrics(
                prop_id, PM1,
                params={"cohort_start": "2027-06-01", "cohort_end": "2027-06-30",
                        "variant": variant}),
            200)

    def test_retention_trailing_variant_counts(self, api):
        """PRD §3.8: "The cohort gathers every lease of the property whose
        `term_end_date` falls inside the window, plus every lease holding a renewal
        document that reached `COUNTERSIGNED` whose `prior_term_end_date` falls
        inside the window — an executed renewal moves the lease's own term end out of
        the window, so the document's captured prior end is what anchors the lease to
        its original cohort."
        PRD §3.8: "Under `TRAILING`, retained means a cohort lease holding a renewal
        document that is currently `COUNTERSIGNED` with its `prior_term_end_date` in
        the window; a document since rescinded does not count, because the renewal
        was undone."

        Design: Difficulty/dual_variant_calc/retention_trailing_vs_pipeline_cohort
        """
        prop = self._cohort_fixture(api)
        data = self._metrics(api, prop["id"], "TRAILING")
        assert data["variant"] == "TRAILING"
        assert data["cohort_size"] == 4       # L1/L2 anchored by prior_term_end_date
        assert data["retained_count"] == 2    # the two countersigned renewals
        assert data["mtm_count"] == 1         # L4
        assert data["lost_count"] == 1        # L3 ENDED without an executed renewal
        assert data["retention_rate_bps"] == 5000  # round_half_up(2/4 * 10000)

    def test_retention_pipeline_variant_diverges(self, api):
        """PRD §3.8: "Under `PIPELINE`, retained additionally includes cohort leases
        with an offer currently `ACCEPTED` but not yet executed, and cohort leases
        currently in `MTM` — so the pipeline figure is always at least the trailing
        figure for the same cohort."
        PRD §3.8: "The report returns `cohort_size`, `retained_count`, `mtm_count`,
        `lost_count` (leases `ENDED` without an executed renewal), and
        `pending_count` (leases with an open offer not yet accepted), echoes the
        `variant`, and computes `retention_rate_bps` as the retained share of the
        cohort expressed in basis points and rounded half-up — null when the cohort
        is empty."

        Design: Difficulty/dual_variant_calc/retention_trailing_vs_pipeline_cohort
        """
        prop = self._cohort_fixture(api)
        trailing = self._metrics(api, prop["id"], "TRAILING")
        pipeline = self._metrics(api, prop["id"], "PIPELINE")
        assert pipeline["cohort_size"] == 4
        assert pipeline["retained_count"] == 3      # + the MTM conversion
        assert pipeline["retention_rate_bps"] == 7500  # round_half_up(3/4 * 10000)
        # The variant delta is exactly the single MTM conversion (2500 bps).
        assert pipeline["retention_rate_bps"] - trailing["retention_rate_bps"] == 2500


class TestRetentionEdgeCases:
    def test_empty_cohort_retention_rate_null_trailing(self, api):
        """PRD §3.8: "The report returns `cohort_size`, `retained_count`,
        `mtm_count`, `lost_count` (leases `ENDED` without an executed renewal), and
        `pending_count` (leases with an open offer not yet accepted), echoes the
        `variant`, and computes `retention_rate_bps` as the retained share of the
        cohort expressed in basis points and rounded half-up — null when the cohort
        is empty."

        Design: Difficulty/boundary_precision_check/empty_cohort_retention_rate_null
        """
        policy = create_policy()
        prop = create_property(policy["id"], name="Empty Court")
        data = validate_success(
            api.get_retention_metrics(
                prop["id"], PM1,
                params={"cohort_start": "2027-06-01", "cohort_end": "2027-06-30",
                        "variant": "TRAILING"}),
            200)
        assert data["cohort_size"] == 0
        assert data["retained_count"] == 0
        assert data["retention_rate_bps"] is None, (
            "an empty cohort yields a null rate, not 0 and not an error"
        )

    def test_empty_cohort_retention_rate_null_pipeline(self, api):
        """PRD §3.8: "The report returns `cohort_size`, `retained_count`,
        `mtm_count`, `lost_count` (leases `ENDED` without an executed renewal), and
        `pending_count` (leases with an open offer not yet accepted), echoes the
        `variant`, and computes `retention_rate_bps` as the retained share of the
        cohort expressed in basis points and rounded half-up — null when the cohort
        is empty."

        Design: Difficulty/boundary_precision_check/empty_cohort_retention_rate_null
        """
        policy = create_policy()
        prop = create_property(policy["id"], name="Empty Court")
        data = validate_success(
            api.get_retention_metrics(
                prop["id"], PM1,
                params={"cohort_start": "2027-06-01", "cohort_end": "2027-06-30",
                        "variant": "PIPELINE"}),
            200)
        assert data["cohort_size"] == 0
        assert data["retention_rate_bps"] is None

    def test_retention_input_set_filtering(self, api):
        """PRD §3.8: "The cohort gathers every lease of the property whose
        `term_end_date` falls inside the window, plus every lease holding a renewal
        document that reached `COUNTERSIGNED` whose `prior_term_end_date` falls
        inside the window — an executed renewal moves the lease's own term end out of
        the window, so the document's captured prior end is what anchors the lease to
        its original cohort. A lease never appears twice in the same window."

        Design: Corner/calculations/retention_input_set_filtering
        """
        policy = create_policy()
        prop = create_property(policy["id"], name="Filter Court")
        u1 = create_unit(prop["id"], unit_number="W1")
        u2 = create_unit(prop["id"], unit_number="W2")
        r1 = create_resident(full_name="Win Dow1", email="win.dow1@x.com")
        r2 = create_resident(full_name="Win Dow2", email="win.dow2@x.com")
        # Ends 2027-06-15: inside the June window.
        create_lease(u1["id"], r1["id"], term_start_date="2026-06-15", term_months=12)
        # Ends 2027-07-01: outside the June window.
        create_lease(u2["id"], r2["id"], term_start_date="2026-07-01", term_months=12)
        data = validate_success(
            api.get_retention_metrics(
                prop["id"], PM1,
                params={"cohort_start": "2027-06-01", "cohort_end": "2027-06-30",
                        "variant": "TRAILING"}),
            200)
        assert data["cohort_size"] == 1, "the July lease must be excluded"
        # Non-empty cohort with nothing retained: a computed 0, not null.
        assert data["retention_rate_bps"] == 0

    def test_retention_metrics_missing_variant_returns_400(self, api):
        """PRD §2.9: "Required fields must be present, types correct, enum members
        valid, dates well-formed `YYYY-MM-DD`, and integer ranges honored — for
        example `term_months` must be at least 1, a property's `min_term_months` must
        not exceed its `max_term_months`, a resident response's `response_type` must
        be one of `ACCEPT`, `DECLINE`, or `COUNTER`, a `COUNTER` response must carry
        a `counter_rent_cents` greater than zero, and a notice citing
        `LEASE_VIOLATION` must carry an `evidence_ref`. Any failure returns
        `ERR_INVALID_REQUEST`."
        PRD §3.8: "The retention report takes a `cohort_start` and `cohort_end`
        bounding an inclusive window plus a `variant` selector, and is available to
        `PlatformAdmin`, `RegionalDirector`, and `PropertyManager`."

        Design: Corner/endpoints/retention_metrics_missing_variant_returns_400
        """
        policy = create_policy()
        prop = create_property(policy["id"], name="Variant Court")
        resp = api.get_retention_metrics(
            prop["id"], PM1,
            params={"cohort_start": "2027-06-01", "cohort_end": "2027-06-30"})
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
