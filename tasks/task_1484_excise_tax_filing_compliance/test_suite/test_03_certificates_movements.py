"""Exemption certificates and bonded movements (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    create_active_certificate,
    create_certificate,
    create_classified_event,
    create_dispatched_movement,
    create_event,
    create_jurisdiction,
    create_movement,
    create_pending_registration,
    create_rated_event,
    create_registrant,
    new_admin_headers,
    new_analyst_headers,
    new_reviewer_headers,
    rate_event,
    setup_active_registration,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCertificateLifecycle:
    def test_certificate_verify_valid_transition(self, api):
        """PRD §3.5: "A new certificate starts in `PENDING_VERIFICATION`. A
        `TaxReviewer` or `ComplianceAdmin` then verifies it, moving it to
        `ACTIVE`".

        Design: Corner/state_machines/certificate_verify_valid_transition
        """
        jur = create_jurisdiction()
        rgt = create_registrant()
        rgn = create_pending_registration(rgt["id"], jur["id"])
        crt = create_certificate(rgn, customer_reference="CUST-1")
        assert crt["status"] == "PENDING_VERIFICATION"

        verified = validate_success(
            api.verify_exemption_certificate(crt["id"], new_reviewer_headers()))
        assert verified["status"] == "ACTIVE"

    def test_certificate_auto_expiry_on_clock_sweep(self, api):
        """PRD §3.5: "The clock sweep expires an `ACTIVE` certificate once the
        current date passes its `valid_to`, moving it to `EXPIRED`." (the
        validity window is a closed interval, so the certificate is still
        valid on `valid_to` itself).

        Design: Corner/state_machines/certificate_auto_expiry_on_clock_sweep
        """
        jur = create_jurisdiction()
        rgt = create_registrant()
        rgn = create_pending_registration(rgt["id"], jur["id"])
        crt = create_active_certificate(
            rgn, customer_reference="CUST-1",
            valid_from="2026-03-01T00:00:00Z", valid_to="2026-08-20T00:00:00Z")
        admin = new_admin_headers()

        validate_success(api.set_clock("2026-08-20T00:00:00Z", admin))
        on_date = validate_success(
            api.get_exemption_certificate(crt["id"], admin))
        assert on_date["status"] == "ACTIVE", (
            "valid_to is inclusive; the certificate is still ACTIVE on it")

        validate_success(api.set_clock("2026-08-21T00:00:00Z", admin))
        after = validate_success(api.get_exemption_certificate(crt["id"], admin))
        assert after["status"] == "EXPIRED"


class TestCertificateWindowGap:
    def _setup(self):
        jur = create_jurisdiction()
        rgt = create_registrant()
        rgn = create_pending_registration(rgt["id"], jur["id"])
        crt1 = create_certificate(
            rgn, customer_reference="CUST-9", certificate_type="RESALE",
            valid_from="2026-03-01T00:00:00Z", valid_to="2026-06-30T00:00:00Z")
        return rgn, crt1

    def test_certificate_touching_window_rejected(self, api):
        """PRD §3.5: "For the same registration, customer reference, and
        product class (counting null as its own class), certificate windows
        must keep a gap of at least one day from any other certificate still
        in `PENDING_VERIFICATION` or `ACTIVE`; windows that touch or overlap
        are rejected with `ERR_CERTIFICATE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/certificate_closed_interval_gap_required
        """
        rgn, _crt1 = self._setup()
        resp = api.create_exemption_certificate(
            {"registration_id": rgn["id"], "customer_reference": "CUST-9",
             "certificate_type": "RESALE",
             "valid_from": "2026-06-30T00:00:00Z",
             "valid_to": "2026-12-31T00:00:00Z"},
            new_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_WINDOW_OVERLAP)

    def test_certificate_one_day_gap_accepted(self, api):
        """PRD §3.5: "certificate windows must keep a gap of at least one day
        from any other certificate still in `PENDING_VERIFICATION` or
        `ACTIVE`; windows that touch or overlap are rejected with
        `ERR_CERTIFICATE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/certificate_closed_interval_gap_required
        """
        rgn, _crt1 = self._setup()
        created = validate_success(api.create_exemption_certificate(
            {"registration_id": rgn["id"], "customer_reference": "CUST-9",
             "certificate_type": "RESALE",
             "valid_from": "2026-07-02T00:00:00Z",
             "valid_to": "2026-12-31T00:00:00Z"},
            new_analyst_headers()), expected_status=201)
        assert created["status"] == "PENDING_VERIFICATION"


class TestCertificateApplicability:
    def test_certificate_wrong_customer_rejected(self, api):
        """PRD §3.4: "the `customer_reference` must equal the event's, and an
        `EXPORT` certificate may only be applied to events whose `is_export`
        flag is set — any mismatch is rejected with
        `ERR_CERTIFICATE_NOT_APPLICABLE`."

        Design: Corner/validations/certificate_wrong_customer_rejected
        """
        ctx = setup_active_registration()
        crt = create_active_certificate(
            ctx["registration"], customer_reference="CUST-1",
            valid_from="2026-03-01T00:00:00Z", valid_to="2026-12-31T00:00:00Z")
        ev = create_classified_event(
            ctx["registration"], ctx["jurisdiction"], ctx["product_class"],
            quantity_units=100, customer_reference="CUST-2")
        resp = api.rate_event(
            ev["id"], {"exemption_certificate_id": crt["id"]},
            new_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_NOT_APPLICABLE)


class TestCertificateValidToBoundary:
    def _setup(self):
        ctx = setup_active_registration()
        crt = create_active_certificate(
            ctx["registration"], customer_reference="CUST-1",
            valid_from="2026-03-01T00:00:00Z", valid_to="2026-08-31T00:00:00Z")
        return ctx, crt

    def test_certificate_valid_to_inclusive_exempts(self, api):
        """PRD §2.7: "Exemption certificate validity windows behave
        differently: they are closed intervals, inclusive at both `valid_from`
        and `valid_to`."
        PRD §3.4: "When an exemption certificate is linked instead, the gross
        is computed identically and `tax_cents` is likewise zero".

        Design: Difficulty/boundary_precision_check/certificate_valid_to_inclusive_boundary
        """
        ctx, crt = self._setup()
        ev = create_classified_event(
            ctx["registration"], ctx["jurisdiction"], ctx["product_class"],
            event_date="2026-08-31T00:00:00Z", quantity_units=1000,
            customer_reference="CUST-1")
        rated = rate_event(ev["id"], exemption_certificate_id=crt["id"])
        assert rated["tax_cents"] == 0
        assert rated["gross_tax_cents"] == 24300, (
            "gross is still recorded; only the tax due is relieved")

    def test_certificate_day_after_valid_to_rejected(self, api):
        """PRD §3.4: "the `event_date` must lie within the certificate's
        closed validity window, the certificate's `product_class_id` must be
        null or match the event's class, the `customer_reference` must equal
        the event's, and an `EXPORT` certificate may only be applied to events
        whose `is_export` flag is set — any mismatch is rejected with
        `ERR_CERTIFICATE_NOT_APPLICABLE`."

        Design: Difficulty/boundary_precision_check/certificate_valid_to_inclusive_boundary
        """
        ctx, crt = self._setup()
        ev = create_classified_event(
            ctx["registration"], ctx["jurisdiction"], ctx["product_class"],
            event_date="2026-09-01T00:00:00Z", quantity_units=1000,
            customer_reference="CUST-1")
        resp = api.rate_event(
            ev["id"], {"exemption_certificate_id": crt["id"]},
            new_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_NOT_APPLICABLE)


class TestMovementLifecycle:
    def test_movement_dispatch_receive_discharge_happy_path(self, api):
        """PRD §3.5: "Dispatch marks the goods shipped, moving the movement
        from `INITIATED` to `IN_TRANSIT` and stamping `dispatched_at` with the
        logical clock" and "Discharge by a `TaxReviewer` or `ComplianceAdmin`
        relieves the bond and confirms the suspension with no tax assessed,
        moving the movement from `RECEIVED` to `DISCHARGED`".

        Design: Corner/endpoints/movement_dispatch_receive_discharge_happy_path
        """
        ctx = setup_active_registration()
        mvt = create_movement(ctx["registration"], ctx["bond"],
                              ctx["product_class"], quantity_units=500)
        assert mvt["status"] == "INITIATED"

        dispatched = validate_success(
            api.dispatch_movement(mvt["id"], new_analyst_headers()))
        assert dispatched["status"] == "IN_TRANSIT"
        assert dispatched["dispatched_at"].startswith("2026-08-01T00:00:00"), (
            "dispatched_at must be stamped with the logical clock")

        received = validate_success(api.receive_movement(
            mvt["id"], 500, new_analyst_headers()))
        assert received["status"] == "RECEIVED"
        assert received["quantity_received_units"] == 500

        discharged = validate_success(
            api.discharge_movement(mvt["id"], new_reviewer_headers()))
        assert discharged["status"] == "DISCHARGED"

        events, meta = validate_paginated(api.list_taxable_events(
            new_analyst_headers(),
            params={"bonded_movement_id": mvt["id"]}))
        assert meta["total_count"] == 0 and events == [], (
            "a cleanly discharged movement creates no assessment event")

    def test_discharge_in_transit_movement_rejected(self, api):
        """PRD §3.5: "Discharge by a `TaxReviewer` or `ComplianceAdmin`
        relieves the bond and confirms the suspension with no tax assessed,
        moving the movement from `RECEIVED` to `DISCHARGED`" — from
        `IN_TRANSIT` the transition does not exist, so the request fails
        `ERR_INVALID_STATE` per §2.10 "(5) state legality of the requested
        transition, including terminal-state lockdown, yielding
        `ERR_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/discharge_in_transit_movement_rejected
        """
        ctx = setup_active_registration()
        mvt = create_dispatched_movement(
            ctx["registration"], ctx["bond"], ctx["product_class"],
            quantity_units=50)
        resp = api.discharge_movement(mvt["id"], new_reviewer_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_movement_receipt_above_dispatched_rejected(self, api):
        """PRD §3.5: "Receipt confirmation moves it from `IN_TRANSIT` to
        `RECEIVED`, stamping `received_at` and recording
        `quantity_received_units`, which must lie between zero and the shipped
        `quantity_units` inclusive — anything outside that range is rejected
        with `ERR_MOVEMENT_QUANTITY_EXCEEDS`."

        Design: Corner/validations/movement_receipt_above_dispatched_rejected
        """
        ctx = setup_active_registration()
        mvt = create_dispatched_movement(
            ctx["registration"], ctx["bond"], ctx["product_class"],
            quantity_units=1000)
        resp = api.receive_movement(mvt["id"], 1001, new_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_MOVEMENT_QUANTITY_EXCEEDS)

    def test_movement_default_transit_deadline_applied(self, api):
        """PRD §3.5: "an optional `transit_deadline_days` that defaults to
        thirty days" and "the clock sweep declares one automatically when the
        current date passes `dispatched_at` plus `transit_deadline_days` while
        the movement is still in transit."

        Design: Corner/entities/movement_default_transit_deadline_applied
        """
        ctx = setup_active_registration()
        mvt = create_movement(ctx["registration"], ctx["bond"],
                              ctx["product_class"], quantity_units=10)
        assert mvt["transit_deadline_days"] == 30, "default deadline is 30 days"
        # Dispatched at the default clock 2026-08-01.
        validate_success(api.dispatch_movement(mvt["id"], new_analyst_headers()))
        admin = new_admin_headers()

        # 2026-08-31 is exactly dispatched_at + 30 days: not yet past.
        validate_success(api.set_clock("2026-08-31T00:00:00Z", admin))
        at_deadline = validate_success(api.get_bonded_movement(mvt["id"], admin))
        assert at_deadline["status"] == "IN_TRANSIT"

        validate_success(api.set_clock("2026-09-01T00:00:00Z", admin))
        past = validate_success(api.get_bonded_movement(mvt["id"], admin))
        assert past["status"] == "DEFAULTED"


class TestMovementLinkageAtRating:
    def test_movement_link_wrong_state_rejected(self, api):
        """PRD §3.4: "Linking a `bonded_movement_id` requires the movement to
        belong to the same registration and product class and to be in
        `IN_TRANSIT` or `RECEIVED`, failing with `ERR_MOVEMENT_NOT_LINKABLE`
        otherwise."

        Design: Corner/validations/movement_link_wrong_state_rejected
        """
        ctx = setup_active_registration()
        mvt = create_movement(ctx["registration"], ctx["bond"],
                              ctx["product_class"], quantity_units=100)
        assert mvt["status"] == "INITIATED"
        ev = create_classified_event(
            ctx["registration"], ctx["jurisdiction"], ctx["product_class"],
            quantity_units=100)
        resp = api.rate_event(
            ev["id"], {"bonded_movement_id": mvt["id"]}, new_analyst_headers())
        validate_error(resp, ApiErrorId.ERR_MOVEMENT_NOT_LINKABLE)

    def test_in_bond_movement_suspends_tax_at_rating(self, api):
        """PRD §3.4: "When a bonded movement is linked, the goods move in
        bond: the event's `gross_tax_cents` is its `quantity_units` multiplied
        by the resolved rate in milli-cents per unit and divided by one
        thousand, rounded half-up to whole cents, and its `tax_cents` is zero
        because the suspension holds."
        PRD §3.6: "`exempted_cents` is the difference between the two sums —
        the total relieved by exemptions and bonded suspensions."

        Design: Corner/calculations/in_bond_movement_suspends_tax_at_rating
        """
        ctx = setup_active_registration()
        mvt = create_dispatched_movement(
            ctx["registration"], ctx["bond"], ctx["product_class"],
            quantity_units=1000)
        ev = create_classified_event(
            ctx["registration"], ctx["jurisdiction"], ctx["product_class"],
            quantity_units=1000)
        rated = rate_event(ev["id"], bonded_movement_id=mvt["id"])
        assert rated["tax_cents"] == 0
        assert rated["gross_tax_cents"] == 24300

        ret = validate_success(
            api.get_return(rated["return_id"], new_analyst_headers()))
        assert ret["taxable_tax_cents"] == 0
        assert ret["exempted_cents"] == 24300
