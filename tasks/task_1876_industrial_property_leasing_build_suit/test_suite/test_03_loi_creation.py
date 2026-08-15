"""LOI creation: derived economics and the creation battery (PRD §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_loi,
    create_accepted_loi,
    create_completed_tour,
    create_draft_loi,
    create_loi_payload,
    create_requirement,
    create_second_requirement,
    create_site,
    request_tour,
    set_logical_clock,
    setup_toured_pair,
    submit_loi,
    validate_error,
    validate_success,
)

LM = TEST_USERS["leasing_manager_headers"]
REP_1 = TEST_USERS["tenant_rep_1_headers"]
REP_2 = TEST_USERS["tenant_rep_2_headers"]


class TestDerivedEconomicsOnCreate:
    def test_aggregate_rent_escalation_compounding(self, api):
        """PRD §3.3: "`aggregate_rent_total` is the total base rent over the
        term: year one contributes `base_rate_psf` multiplied by `leased_sf`,
        and each subsequent year contributes that same year-one amount grown
        at the annual rate `escalation_pct`, compounding once per elapsed
        year" and "The yearly amounts are summed unrounded, and the sum is
        rounded half-up exactly once, to cents." and "A created LOI starts
        `DRAFT` with `negotiation_round` at zero, and both derived economics
        are computed immediately at the stated terms."

        Design: Corner/calculations/aggregate_rent_escalation_compounding
        """
        req, site, _tour = setup_toured_pair()
        resp = api.create_loi(create_loi_payload(req["id"], site["id"]), REP_1)
        data = validate_success(resp, 201)
        assert_loi(data)
        assert data["aggregate_rent_total"] == pytest.approx(4247308.65, abs=0.005), (
            f"8.00 x 100000 x sum(1.03^k, k=0..4) summed unrounded then "
            f"rounded once must be 4247308.65, got {data['aggregate_rent_total']}"
        )
        assert data["net_effective_rent_psf"] == pytest.approx(5.69, abs=0.005)
        assert data["negotiation_round"] == 0
        assert data["status"] == "DRAFT"

    def test_loi_create_computed_field_input_ignored(self, api):
        """PRD §3.3: "A created LOI starts `DRAFT` with `negotiation_round` at
        zero, and both derived economics are computed immediately at the
        stated terms." — the economics stated are `term_years`, `leased_sf`,
        `base_rate_psf`, `ti_allowance_psf`, `free_rent_months`,
        `escalation_pct`, and optionally `commission_basis`.

        Design: Corner/calculations/loi_create_computed_field_input_ignored
        """
        req, site, _tour = setup_toured_pair()
        payload = create_loi_payload(req["id"], site["id"])
        payload["net_effective_rent_psf"] = 99.99  # client-sent derived field
        resp = api.create_loi(payload, REP_1)
        data = validate_success(resp, 201)
        assert data["net_effective_rent_psf"] == pytest.approx(5.69, abs=0.005), (
            f"Derived economics are server-computed from the stated terms; "
            f"a client-sent 99.99 must be discarded, got "
            f"{data['net_effective_rent_psf']}"
        )


class TestCompletedTourGate:
    """LOI creation requires a COMPLETED tour for the pair (PRD §3.3)."""

    def _setup_confirmed_only(self, api):
        req = create_requirement(REP_1)
        site = create_site()
        tour = request_tour(site["id"], req["id"], REP_1)
        validate_success(api.confirm_tour(tour["id"], LM))
        return req, site, tour

    def test_loi_create_with_confirmed_tour_rejected(self, api):
        """PRD §3.3: "at least one `COMPLETED` tour must exist for the
        requirement/site pair (`ERR_NO_COMPLETED_TOUR`, 409)".

        Design: Difficulty/cross_entity_state_dependency/loi_create_requires_completed_tour
        """
        req, site, _tour = self._setup_confirmed_only(api)
        resp = api.create_loi(create_loi_payload(req["id"], site["id"]), REP_1)
        validate_error(resp, ApiErrorId.ERR_NO_COMPLETED_TOUR)

    def test_loi_create_after_tour_completion_succeeds(self, api):
        """PRD §3.3: "at least one `COMPLETED` tour must exist for the
        requirement/site pair (`ERR_NO_COMPLETED_TOUR`, 409)" and "A created
        LOI starts `DRAFT`".

        Design: Difficulty/cross_entity_state_dependency/loi_create_requires_completed_tour
        """
        req, site, tour = self._setup_confirmed_only(api)
        set_logical_clock(tour["end_at"])
        validate_success(api.complete_tour(tour["id"], REP_1))
        resp = api.create_loi(create_loi_payload(req["id"], site["id"]), REP_1)
        data = validate_success(resp, 201)
        assert_loi(data)
        assert data["status"] == "DRAFT", (
            "Once a COMPLETED tour exists for the pair, LOI creation must "
            "succeed and start DRAFT"
        )


class TestCreationBattery:
    def test_hard_minimums_not_met_at_loi_create_returns_422(self, api):
        """PRD §3.3: "the site must satisfy all five hard minimums defined in
        §3.2 (`ERR_HARD_MINIMUMS_NOT_MET`, 422)".

        Design: Corner/validations/hard_minimums_not_met_at_loi_create_returns_422
        """
        req = create_requirement(REP_1)
        site = create_site(
            site_name="Low Clear Center", total_sf=100000, clear_height_ft=30,
            dock_doors=16, power_amps=3000, yard_depth_ft=150,
            asking_rate_psf=5.00,
        )
        create_completed_tour(site["id"], req["id"], REP_1)
        resp = api.create_loi(create_loi_payload(req["id"], site["id"]), REP_1)
        validate_error(resp, ApiErrorId.ERR_HARD_MINIMUMS_NOT_MET)

    def test_duplicate_open_loi_returns_409(self, api):
        """PRD §3.3: "no other LOI for the same pair may be open — that is, in
        `DRAFT`, `SUBMITTED`, `COUNTERED`, or `ACCEPTED`
        (`ERR_LOI_ALREADY_OPEN`, 409)".

        Design: Corner/validations/duplicate_open_loi_returns_409
        """
        req, site, _tour = setup_toured_pair()
        create_draft_loi(req["id"], site["id"], REP_1)
        resp = api.create_loi(
            create_loi_payload(
                req["id"], site["id"], term_years=7, leased_sf=110000,
                base_rate_psf=8.50, ti_allowance_psf=15.00,
                free_rent_months=3, escalation_pct=0.025,
            ),
            REP_1,
        )
        validate_error(resp, ApiErrorId.ERR_LOI_ALREADY_OPEN)

    def test_loi_create_on_reserved_site_returns_site_not_listed(self, api):
        """PRD §3.3: "Creation is gated by a six-check battery evaluated in
        this exact order: the site must be `LISTED` (`ERR_SITE_NOT_LISTED`)".

        Design: Corner/validations/loi_create_on_reserved_site_returns_site_not_listed
        """
        req1 = create_requirement(REP_1)
        req2 = create_second_requirement()
        site = create_site()
        # Both tours complete while the site is LISTED; the second starts at
        # 11:30, exactly outside the first tour's buffered window.
        create_completed_tour(site["id"], req1["id"], REP_1)
        create_completed_tour(
            site["id"], req2["id"], REP_2,
            start_at="2026-08-10T11:30:00Z", end_at="2026-08-10T12:30:00Z",
        )
        create_accepted_loi(req1["id"], site["id"], REP_1)
        site_after = validate_success(api.get_site(site["id"], LM))
        assert site_after["status"] == "RESERVED"
        resp = api.create_loi(create_loi_payload(req2["id"], site["id"]), REP_2)
        validate_error(resp, ApiErrorId.ERR_SITE_NOT_LISTED)

    def test_leased_sf_out_of_range_returns_422(self, api):
        """PRD §3.3: "`leased_sf` must lie within the requirement's band from
        `min_sf` to `max_sf`, inclusive at both ends (`ERR_SF_OUT_OF_RANGE`,
        422)".

        Design: Corner/validations/leased_sf_out_of_range_returns_422
        """
        req, site, _tour = setup_toured_pair()
        resp = api.create_loi(
            create_loi_payload(req["id"], site["id"], leased_sf=130000), REP_1
        )
        validate_error(resp, ApiErrorId.ERR_SF_OUT_OF_RANGE)

    def test_insufficient_sf_at_loi_create_returns_422(self, api):
        """PRD §3.3: "the site's `available_sf` must be at least `leased_sf`
        (`ERR_INSUFFICIENT_SF`, 422)".

        Design: Corner/validations/insufficient_sf_at_loi_create_returns_422
        """
        req = create_requirement(REP_1)
        site = create_site(
            site_name="Small Exact Center", total_sf=90000, clear_height_ft=32,
            dock_doors=16, power_amps=3000, yard_depth_ft=150,
            asking_rate_psf=5.00,
        )
        create_completed_tour(site["id"], req["id"], REP_1)
        resp = api.create_loi(
            create_loi_payload(req["id"], site["id"], leased_sf=100000), REP_1
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SF)


class TestNerMultiInputInteraction:
    """NER combines five-plus inputs with non-linear interaction (PRD §3.3)."""

    def _create_and_submit_loi_c(self, api):
        req = create_requirement(
            REP_1, tenant_name="Coastal R&D", use_type="R_AND_D"
        )
        site = create_site(site_name="Valley Commerce Center",
                           asking_rate_psf=5.00)
        create_completed_tour(site["id"], req["id"], REP_1)
        loi = create_draft_loi(
            req["id"], site["id"], REP_1,
            term_years=10, leased_sf=100000, base_rate_psf=12.00,
            ti_allowance_psf=75.00, free_rent_months=12, escalation_pct=0.02,
        )
        return submit_loi(loi, REP_1)

    def test_ner_aggregate_with_escalation_compounding(self, api):
        """PRD §3.3: "`aggregate_rent_total` is the total base rent over the
        term ... each subsequent year contributes that same year-one amount
        grown at the annual rate `escalation_pct`, compounding once per
        elapsed year" and "The yearly amounts are summed unrounded, and the
        sum is rounded half-up exactly once, to cents."

        Design: Difficulty/combinatorial_formula/ner_multi_input_interaction
        """
        data = self._create_and_submit_loi_c(api)
        # 12.00 x 100000 x sum(1.02^k, k=0..9), summed unrounded, rounded once.
        assert data["aggregate_rent_total"] == pytest.approx(
            13139665.20, abs=0.005
        ), (
            f"10-year aggregate at 2% escalation must be 13139665.20, got "
            f"{data['aggregate_rent_total']}"
        )

    def test_ner_with_ti_cap_applied(self, api):
        """PRD §3.3: "the improvement credit equals the lesser of
        `ti_allowance_psf` and a fifty-dollar-per-square-foot cap, multiplied
        by `leased_sf`, rounded half-up to cents. Both credits are subtracted
        from `aggregate_rent_total`, and the difference is divided by the
        product of `term_years` and `leased_sf`, rounded half-up to cents."

        TI 75.00 is capped to 50.00/SF (credit 5000000.00, not 7500000.00), so
        NER lands at 6.94, not 4.44.

        Design: Difficulty/combinatorial_formula/ner_multi_input_interaction
        """
        data = self._create_and_submit_loi_c(api)
        assert data["net_effective_rent_psf"] == pytest.approx(6.94, abs=0.005), (
            f"NER with the 50.00/SF TI cap must be 6.94, got "
            f"{data['net_effective_rent_psf']}"
        )
