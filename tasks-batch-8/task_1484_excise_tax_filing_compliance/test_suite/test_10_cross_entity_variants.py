"""Cross-entity state gating, dual-variant calculations, default-assessment
cascades, and the parallel filing/settlement axes (PRD §3.1, §3.4, §3.5,
§3.6)."""
from test_helpers import (
    ApiErrorId,
    apply_claim,
    approve_claim,
    create_active_certificate,
    create_certificate,
    create_claim,
    create_classified_event,
    create_dispatched_movement,
    create_jurisdiction,
    create_rated_event,
    file_return,
    list_period_deposits,
    make_analyst_headers,
    make_reviewer_headers,
    new_admin_headers,
    new_analyst_headers,
    new_reviewer_headers,
    rate_event,
    setup_active_registration,
    setup_filed_return,
    submit_claim,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEventRatingGatedOnRegistrationState:
    def test_rate_rejected_while_registration_suspended(self, api):
        """PRD §3.4: "Recording requires an `ACTIVE` registration, failing
        with `ERR_REGISTRATION_NOT_ACTIVE` otherwise; the same
        registration-active requirement, with the same error, guards
        classification, rating, bonded movement creation and dispatch, and
        return creation."

        Design: Difficulty/cross_entity_state_dependency/event_rating_gated_on_registration_state
        """
        ctx = setup_active_registration()
        ev = create_classified_event(ctx["registration"], ctx["jurisdiction"],
                                     ctx["product_class"], quantity_units=1000)
        admin = new_admin_headers()
        validate_success(
            api.suspend_registration(ctx["registration"]["id"], admin))
        resp = api.rate_event(ev["id"], {}, new_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_REGISTRATION_NOT_ACTIVE)
        event = validate_success(
            api.get_taxable_event(ev["id"], new_analyst_headers()))
        assert event["status"] == "CLASSIFIED"

    def test_rate_succeeds_after_reinstatement(self, api):
        """PRD §3.1: "may reinstate a `SUSPENDED` or `BOND_DEFICIENT`
        registration back to `ACTIVE`" and §3.4: "Rating determines the tax,
        moving an event from `CLASSIFIED` to `RATED`" — once the registration
        is ACTIVE again the same rate call succeeds.

        Design: Difficulty/cross_entity_state_dependency/event_rating_gated_on_registration_state
        """
        ctx = setup_active_registration()
        ev = create_classified_event(ctx["registration"], ctx["jurisdiction"],
                                     ctx["product_class"], quantity_units=1000)
        admin = new_admin_headers()
        validate_success(
            api.suspend_registration(ctx["registration"]["id"], admin))
        validate_success(
            api.reinstate_registration(ctx["registration"]["id"], admin))
        rated = rate_event(ev["id"])
        assert rated["status"] == "RATED"
        assert rated["tax_cents"] == 24300


class TestEventExemptionGatedOnCertificateState:
    def test_rate_with_pending_certificate_rejected_then_active_ok(self, api):
        """PRD §3.4: "Linking an `exemption_certificate_id` requires the
        certificate to be `ACTIVE` at rating time, failing with
        `ERR_CERTIFICATE_NOT_ACTIVE` otherwise" and "When an exemption
        certificate is linked instead, the gross is computed identically and
        `tax_cents` is likewise zero".

        Design: Difficulty/cross_entity_state_dependency/event_exemption_gated_on_certificate_state
        """
        ctx = setup_active_registration()
        crt = create_certificate(ctx["registration"],
                                 customer_reference="CUST-1",
                                 valid_from="2026-03-01T00:00:00Z",
                                 valid_to="2026-12-31T00:00:00Z")
        assert crt["status"] == "PENDING_VERIFICATION"
        ev = create_classified_event(
            ctx["registration"], ctx["jurisdiction"], ctx["product_class"],
            quantity_units=1000, customer_reference="CUST-1")

        resp = api.rate_event(
            ev["id"], {"exemption_certificate_id": crt["id"]},
            new_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_NOT_ACTIVE)

        validate_success(
            api.verify_exemption_certificate(crt["id"], new_reviewer_headers()))
        rated = rate_event(ev["id"], exemption_certificate_id=crt["id"])
        assert rated["tax_cents"] == 0
        assert rated["gross_tax_cents"] == 24300

    def test_rate_with_revoked_certificate_rejected(self, api):
        """PRD §3.4: "Linking an `exemption_certificate_id` requires the
        certificate to be `ACTIVE` at rating time, failing with
        `ERR_CERTIFICATE_NOT_ACTIVE` otherwise" and §3.5: "revocation of an
        `ACTIVE` certificate ends in `REVOKED`".

        Design: Difficulty/cross_entity_state_dependency/event_exemption_gated_on_certificate_state
        """
        ctx = setup_active_registration()
        crt = create_active_certificate(ctx["registration"],
                                        customer_reference="CUST-1",
                                        valid_from="2026-03-01T00:00:00Z",
                                        valid_to="2026-12-31T00:00:00Z")
        validate_success(
            api.revoke_exemption_certificate(crt["id"], new_reviewer_headers()))
        ev = create_classified_event(
            ctx["registration"], ctx["jurisdiction"], ctx["product_class"],
            quantity_units=1000, customer_reference="CUST-1")
        resp = api.rate_event(
            ev["id"], {"exemption_certificate_id": crt["id"]},
            new_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_NOT_ACTIVE)


class TestDualVariantEventTax:
    def _setup_standard_and_defaulted(self, api):
        """One jurisdiction with DIESEL@24300mc and GASOLINE@41100mc; a
        STANDARD 400-unit DIESEL event rated, and a 400-unit DIESEL movement
        defaulted by the clock sweep past its 30-day transit deadline."""
        ctx = setup_active_registration(
            product_classes=[("DIESEL", 24300), ("GASOLINE", 41100)])
        pc_diesel = ctx["product_class"]
        ev_std = create_rated_event(ctx["registration"], ctx["jurisdiction"],
                                    pc_diesel, quantity_units=400)
        mvt = create_dispatched_movement(ctx["registration"], ctx["bond"],
                                         pc_diesel, quantity_units=400)
        # Dispatched at the 2026-08-01 default clock; deadline +30 days.
        validate_success(
            api.set_clock("2026-09-02T00:00:00Z", new_admin_headers()))
        events, _meta = validate_paginated(api.list_taxable_events(
            new_analyst_headers(),
            params={"bonded_movement_id": mvt["id"]}))
        assert len(events) == 1, "the default spawns exactly one event"
        return ev_std, events[0]

    def test_standard_event_tax_uses_own_class_rate(self, api):
        """PRD §3.4: "In the plain case the gross is computed the same way
        and `tax_cents` equals the gross" — round_half_up(400 x 24300 / 1000)
        == 9720 for the STANDARD determination.

        Design: Difficulty/dual_variant_calc/event_tax_standard_vs_default_assessment
        """
        ev_std, _ev_def = self._setup_standard_and_defaulted(api)
        assert ev_std["determination"] == "STANDARD"
        assert ev_std["tax_cents"] == 9720
        assert ev_std["gross_tax_cents"] == 9720

    def test_default_assessment_event_uses_punitive_rate(self, api):
        """PRD §3.5: "Rather than the event's own product class rate, it uses
        one and a half times the highest `rate_millicents_per_unit` among all
        tax rates of the registration's jurisdiction whose windows contain
        the default date, across every product class" — max is 41100mc
        (GASOLINE), punitive 61650mc, so the 400-unit default assesses
        round_half_up(400 x 61650 / 1000) == 24660, not 9720.

        Design: Difficulty/dual_variant_calc/event_tax_standard_vs_default_assessment
        """
        _ev_std, ev_def = self._setup_standard_and_defaulted(api)
        assert ev_def["determination"] == "DEFAULT_ASSESSMENT"
        assert ev_def["tax_cents"] == 24660
        assert ev_def["tax_cents"] != 9720, (
            "identical quantity diverges by variant: 24660 != 9720")


class TestMovementDefaultCascade:
    def _setup_timeout_default(self, api):
        """DIESEL@24300 + GASOLINE@41100; 400-unit DIESEL movement dispatched
        at 2026-08-01, then the clock advanced past its 30-day deadline."""
        ctx = setup_active_registration(
            product_classes=[("DIESEL", 24300), ("GASOLINE", 41100)])
        mvt = create_dispatched_movement(ctx["registration"], ctx["bond"],
                                         ctx["product_class"],
                                         quantity_units=400)
        validate_success(
            api.set_clock("2026-09-02T00:00:00Z", new_admin_headers()))
        return ctx, mvt

    def test_movement_timeout_default_spawns_default_assessment_event(self, api):
        """PRD §3.5: "the clock sweep declares one automatically when the
        current date passes `dispatched_at` plus `transit_deadline_days`" and
        "First, the system creates a taxable event with `determination`
        `DEFAULT_ASSESSMENT`, quantity equal to the defaulted quantity,
        `event_date` equal to the default date, and status already `RATED`.
        Second, that event is auto-included into the `DRAFT` or `SUBMITTED`
        return of its period — created if missing — and the return's totals
        are recomputed".

        Design: Difficulty/transitive_cascade/movement_default_assessment_cascade
        """
        ctx, mvt = self._setup_timeout_default(api)
        movement = validate_success(
            api.get_bonded_movement(mvt["id"], new_analyst_headers()))
        assert movement["status"] == "DEFAULTED"
        assert movement["defaulted_quantity_units"] == 400

        events, _meta = validate_paginated(api.list_taxable_events(
            new_analyst_headers(),
            params={"bonded_movement_id": mvt["id"]}))
        assert len(events) == 1
        ev = events[0]
        assert ev["determination"] == "DEFAULT_ASSESSMENT"
        assert ev["status"] == "RATED"
        assert ev["quantity_units"] == 400
        assert ev["tax_cents"] == 24660  # 400 x 61650mc punitive / 1000

        assert ev["return_id"], "auto-included into the period return"
        ret = validate_success(
            api.get_return(ev["return_id"], new_analyst_headers()))
        assert ret["period"] == "2026-09"
        assert ret["gross_tax_cents"] == 24660

    def test_movement_timeout_default_creates_schedule_and_aggravates(self, api):
        """PRD §3.5: "Third, ACTUAL-method deposits of that period are
        recomputed, and the registration's bond requirement is recomputed,
        which may flip the `requirement_variant` to `AGGRAVATED`."
        PRD §3.7: "When no such prior filed return exists, the schedule falls
        back to a floor of 10,000 cents (one hundred dollars) per deposit."
        PRD §3.1: "The `AGGRAVATED` variant applies whenever any bonded
        movement of the registration reached `DEFAULTED` or `PARTIAL_DEFAULT`,
        or any credit claim reached `REVERSED`, within the trailing twelve
        months: the window widens to the twelve most recent filed periods,
        the multiplier rises to five, and the floor rises to 2,500,000 cents
        (twenty-five thousand dollars)".

        Design: Difficulty/transitive_cascade/movement_default_assessment_cascade
        """
        ctx, _mvt = self._setup_timeout_default(api)
        deps = list_period_deposits(ctx["registration"]["id"], "2026-09")
        assert deps, "the auto-created 2026-09 return carries a schedule"
        assert deps[0]["scheduled_amount_cents"] == 10000, (
            "SAFE_HARBOR floor: no prior FILED return exists")

        status = validate_success(api.get_bond_status(
            ctx["registration"]["id"], new_admin_headers()))
        assert status["requirement_variant"] == "AGGRAVATED"
        assert status["bond_required_cents"] == 2500000, (
            "AGGRAVATED floor with no filed history")


class TestMovementPartialDefaultConservation:
    def _setup_partial_default(self, api):
        """1000-unit movement, 600 received, then default declared: only the
        400-unit shortfall defaults. DIESEL@24300mc is the jurisdiction's
        only rate, so the punitive rate is round_half_up(1.5 x 24300) ==
        36450mc."""
        ctx = setup_active_registration()
        mvt = create_dispatched_movement(ctx["registration"], ctx["bond"],
                                         ctx["product_class"],
                                         quantity_units=1000)
        validate_success(
            api.receive_movement(mvt["id"], 600, new_analyst_headers()))
        return ctx, mvt

    def test_partial_default_conserves_movement_units(self, api):
        """PRD §3.5: "From `RECEIVED`, only the shortfall defaults:
        `defaulted_quantity_units` is the shipped quantity minus the received
        quantity, which must be strictly less than the shipped quantity, and
        the movement ends in `PARTIAL_DEFAULT`." — 600 received + 400
        defaulted == 1000 shipped.

        Design: Difficulty/compensating_invariant/movement_partial_default_conserves_units
        """
        _ctx, mvt = self._setup_partial_default(api)
        defaulted = validate_success(
            api.default_movement(mvt["id"], new_admin_headers()))
        assert defaulted["status"] == "PARTIAL_DEFAULT"
        assert defaulted["quantity_received_units"] == 600
        assert defaulted["defaulted_quantity_units"] == 400
        assert (defaulted["quantity_received_units"]
                + defaulted["defaulted_quantity_units"]
                == defaulted["quantity_units"] == 1000), (
            "units are conserved: nothing created or destroyed")

    def test_partial_default_spawns_event_for_shortfall_only(self, api):
        """PRD §3.5: "the system creates a taxable event with
        `determination` `DEFAULT_ASSESSMENT`, quantity equal to the defaulted
        quantity" — the spawned event carries exactly the 400-unit shortfall,
        taxed at the punitive rate: round_half_up(400 x 36450 / 1000) ==
        14580.

        Design: Difficulty/compensating_invariant/movement_partial_default_conserves_units
        """
        _ctx, mvt = self._setup_partial_default(api)
        validate_success(api.default_movement(mvt["id"], new_admin_headers()))
        events, _meta = validate_paginated(api.list_taxable_events(
            new_analyst_headers(),
            params={"bonded_movement_id": mvt["id"]}))
        assert len(events) == 1
        assert events[0]["quantity_units"] == 400
        assert events[0]["tax_cents"] == 14580


class TestBondRequirementVariants:
    def _setup_two_registrants_filed(self, api):
        """Two registrants, each with an ACTIVE SAFE_HARBOR registration
        bonded at 3,000,000 and a FILED 2026-08 return with taxable_tax_cents
        == 486000 (one 20000-unit DIESEL event at 24300mc)."""
        ctx1 = setup_active_registration(bond_amount=3000000)
        ctx2 = setup_active_registration(bond_amount=3000000)
        for ctx in (ctx1, ctx2):
            ev = create_rated_event(ctx["registration"], ctx["jurisdiction"],
                                    ctx["product_class"], quantity_units=20000)
            validate_success(
                api.submit_return(ev["return_id"],
                                  make_analyst_headers("analyst-1")))
            file_return(ev["return_id"])
        return ctx1, ctx2

    def test_bond_requirement_standard_after_clean_filing(self, api):
        """PRD §3.1: "otherwise the average `taxable_tax_cents` across those
        periods is computed, rounded half-up to a whole cent, and the
        requirement is the larger of three times that average and the floor"
        — max(3 x 486000, 1000000) == 1458000 under STANDARD.

        Design: Difficulty/dual_variant_calc/bond_requirement_standard_vs_aggravated
        """
        ctx1, _ctx2 = self._setup_two_registrants_filed(api)
        status = validate_success(api.get_bond_status(
            ctx1["registration"]["id"], new_admin_headers()))
        assert status["requirement_variant"] == "STANDARD"
        assert status["bond_required_cents"] == 1458000

    def test_bond_requirement_aggravated_after_movement_default(self, api):
        """PRD §3.1: "The `AGGRAVATED` variant applies whenever any bonded
        movement of the registration reached `DEFAULTED` or `PARTIAL_DEFAULT`,
        or any credit claim reached `REVERSED`, within the trailing twelve
        months: the window widens to the twelve most recent filed periods,
        the multiplier rises to five, and the floor rises to 2,500,000 cents
        (twenty-five thousand dollars)" — max(5 x 486000, 2500000) == 2500000
        (the floor binds).

        Design: Difficulty/dual_variant_calc/bond_requirement_standard_vs_aggravated
        """
        _ctx1, ctx2 = self._setup_two_registrants_filed(api)
        mvt = create_dispatched_movement(ctx2["registration"], ctx2["bond"],
                                         ctx2["product_class"],
                                         quantity_units=100)
        validate_success(api.default_movement(mvt["id"], new_admin_headers()))
        status = validate_success(api.get_bond_status(
            ctx2["registration"]["id"], new_admin_headers()))
        assert status["requirement_variant"] == "AGGRAVATED"
        assert status["bond_required_cents"] == 2500000


class TestParallelStateDimensions:
    def _setup_settled_then_claim(self, api):
        """EXPORT event rated; depA paid exactly the tax so the filing
        settles at net 0; then a 24300 EXPORT claim approved."""
        ctx = setup_active_registration()
        ev = create_rated_event(ctx["registration"], ctx["jurisdiction"],
                                ctx["product_class"], quantity_units=1000,
                                is_export=True)
        ret_id = ev["return_id"]
        dep_a = list_period_deposits(ctx["registration"]["id"], "2026-08")[0]
        validate_success(
            api.pay_deposit(dep_a["id"], 24300, new_analyst_headers()))
        validate_success(
            api.submit_return(ret_id, make_analyst_headers("analyst-1")))
        filed = file_return(ret_id)
        clm = create_claim(ctx["registration"], filed, [ev["id"]],
                           headers=make_analyst_headers("analyst-1"))
        submit_claim(clm["id"], headers=make_analyst_headers("analyst-1"))
        approve_claim(clm["id"], 24300,
                      headers=make_reviewer_headers("reviewer-1"))
        return ctx, ev, filed, clm

    def test_settlement_axis_moves_independently_of_filing_axis(self, api):
        """PRD §3.6: "Two state dimensions then evolve independently." and
        "A settlement transition never changes the filing status, and a filing
        transition never changes the settlement status directly." — filing
        lands FILED + SETTLED (net 24300 - 24300 == 0); the claim application
        then moves settlement alone to OVERPAID with net -24300.

        Design: Difficulty/non_linear_state_machine/tax_return_parallel_filing_and_settlement_dimensions
        """
        _ctx, _ev, filed, clm = self._setup_settled_then_claim(api)
        assert filed["filing_status"] == "FILED"
        assert filed["settlement_status"] == "SETTLED"

        validate_success(api.apply_credit_claim(clm["id"], new_analyst_headers()))
        ret = validate_success(api.get_return(filed["id"], new_analyst_headers()))
        assert ret["settlement_status"] == "OVERPAID"
        assert ret["net_due_cents"] == -24300
        assert ret["filing_status"] == "FILED"

    def test_full_reversal_restores_settled_without_touching_filing(self, api):
        """PRD §3.6: "When a claim reversal pushes the net due back above
        zero, the settlement flips from `SETTLED` or `OVERPAID` back to
        `AWAITING_PAYMENT`" — here the full 24300 reversal restores net due
        to exactly zero, so settlement returns to `SETTLED` while
        filing_status stays `FILED`.

        Design: Difficulty/non_linear_state_machine/tax_return_parallel_filing_and_settlement_dimensions
        """
        _ctx, _ev, filed, clm = self._setup_settled_then_claim(api)
        validate_success(api.apply_credit_claim(clm["id"], new_analyst_headers()))
        validate_success(api.reverse_credit_claim(
            clm["id"], 24300, make_reviewer_headers("reviewer-2")))
        ret = validate_success(api.get_return(filed["id"], new_analyst_headers()))
        assert ret["settlement_status"] == "SETTLED"
        assert ret["net_due_cents"] == 0
        assert ret["filing_status"] == "FILED"


class TestEventJurisdictionAlignment:
    def test_event_jurisdiction_mismatch_rejected(self, api):
        """PRD §3.4: "The event's `jurisdiction_id` must equal the
        registration's own jurisdiction, failing with
        `ERR_REGISTRATION_JURISDICTION_MISMATCH` otherwise."

        Design: Corner/validations/event_jurisdiction_mismatch_rejected
        """
        ctx = setup_active_registration(
            jurisdiction_overrides={"code": "CA-BOE", "name": "California"})
        other_jur = create_jurisdiction(code="NV-TX", name="Nevada")
        resp = api.create_taxable_event(
            {"registration_id": ctx["registration"]["id"],
             "jurisdiction_id": other_jur["id"],
             "product_class_id": ctx["product_class"]["id"],
             "event_date": "2026-08-03T00:00:00Z", "quantity_units": 10},
            new_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_REGISTRATION_JURISDICTION_MISMATCH)
