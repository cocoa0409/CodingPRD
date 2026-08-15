"""Cross-entity cascades: suspension, cancellation, deaccession, ops sweep, settlement."""
from test_helpers import (
    ApiErrorId,
    acquire_unit,
    advance_ticket,
    check_in_line,
    cleaning_ticket_for_unit,
    confirm_reservation,
    create_active_renter,
    create_catalog_item,
    create_confirmed_production,
    create_confirmed_reservation,
    create_production_draft,
    create_pull_list_for,
    decide_certificate,
    dispatch_pull_list,
    generate_invoice,
    get_item,
    get_production,
    get_pull_list,
    get_renter,
    get_reservation,
    get_unit,
    issue_invoice,
    make_renter_contact_headers,
    make_wardrobe_staff_headers,
    pick_all_lines,
    place_reservation,
    publish_rate_card,
    record_payment,
    register_renter,
    run_daily_ops,
    set_logical_clock,
    setup_confirmed_reservation_scenario,
    setup_dispatched_scenario,
    submit_and_get_lines,
    submit_certificate,
    submit_pull_list,
    validate_error,
    validate_success,
)


class TestProductionCancellation:
    def test_production_cancel_releases_reservations(self, api):
        """PRD §3.3: "Cancellation releases the production's reservations — `HELD` and
        `CONFIRMED` alike become `RELEASED` — and cancels its pull lists still in `DRAFT`."

        Design: Corner/state_machines/production_cancel_releases_reservations
        """
        publish_rate_card(api)
        item = create_catalog_item(api, name="I1")
        acquire_unit(api, item["id"], barcode="BC-X2")
        acquire_unit(api, item["id"], barcode="BC-X3")
        renter = create_active_renter(api, name="R")["renter"]
        production = create_confirmed_production(api, renter, closing_date="2026-10-26")
        r1 = create_confirmed_reservation(
            api, production["id"], renter, item["id"], quantity=1,
            window_start_date="2026-09-01", window_end_date="2026-09-10",
        )
        r2 = place_reservation(
            api, production["id"], renter, item["id"], quantity=1,
            window_start_date="2026-09-11", window_end_date="2026-09-15",
        )
        assert r2["status"] == "HELD"

        cancelled = validate_success(
            api.cancel_production(production["id"], make_renter_contact_headers(renter["id"]))
        )
        assert cancelled["status"] == "CANCELLED"
        assert get_reservation(api, r1["id"])["status"] == "RELEASED"
        assert get_reservation(api, r2["id"])["status"] == "RELEASED"

    def test_error_production_has_active_pulls_on_cancel(self, api):
        """PRD §3.3: "Cancelling a `CONFIRMED` production is refused with
        `ERR_PRODUCTION_HAS_ACTIVE_PULLS` while any of its pull lists is `PICKING` or
        `DISPATCHED`."

        Design: Corner/errors/error_production_has_active_pulls_on_cancel
        """
        ctx = setup_confirmed_reservation_scenario(api, quantity=1, num_units=1)
        renter = ctx["renter"]
        pull_list = create_pull_list_for(api, ctx["production"]["id"], renter)
        submit_pull_list(api, pull_list["id"])

        resp = api.cancel_production(
            ctx["production"]["id"], make_renter_contact_headers(renter["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PRODUCTION_HAS_ACTIVE_PULLS, 409)

        # Once the list is cancelled, the same production cancel succeeds.
        validate_success(api.cancel_pull_list(pull_list["id"], make_wardrobe_staff_headers()))
        ok = validate_success(
            api.cancel_production(
                ctx["production"]["id"], make_renter_contact_headers(renter["id"]),
            )
        )
        assert ok["status"] == "CANCELLED"


class TestCertificateExpiryCascade:
    def _setup(self, api):
        """Renter R1 whose only VERIFIED certificate lapses 2026-08-19; two HELD
        reservations whose own 72h holds have NOT lapsed at the 2026-08-20 ops run."""
        publish_rate_card(api)
        item = create_catalog_item(api, name="Tailcoat")
        acquire_unit(api, item["id"], barcode="BC-701")
        acquire_unit(api, item["id"], barcode="BC-702")
        r1 = register_renter(api, name="Renter Short", renter_type="THEATRE")
        cert1 = submit_certificate(api, r1["id"], coverage_cents=100000,
                                   expiry_date="2026-08-19")
        decide_certificate(api, cert1["id"], decision="VERIFIED")
        p1 = create_production_draft(api, get_renter(api, r1["id"]), title="P",
                                     closing_date="2026-09-20")
        r1 = get_renter(api, r1["id"])

        set_logical_clock(api, "2026-08-18T00:00:00Z")
        ra = place_reservation(api, p1["id"], r1, item["id"], quantity=1,
                               window_start_date="2026-09-01", window_end_date="2026-09-05")
        set_logical_clock(api, "2026-08-19T00:00:00Z")
        rb = place_reservation(api, p1["id"], r1, item["id"], quantity=1,
                               window_start_date="2026-09-06", window_end_date="2026-09-10")

        # A second, healthy renter to probe freed capacity afterwards.
        probe = create_active_renter(api, name="Renter Probe", coverage_cents=600000,
                                     expiry_date="2027-06-30")["renter"]
        p2 = create_production_draft(api, probe, title="Probe", closing_date="2026-09-20")
        return {"item": item, "r1": r1, "cert1": cert1, "p1": p1, "ra": ra, "rb": rb,
                "probe": probe, "p2": p2}

    def test_cert_expiry_suspends_renter_and_expires_holds(self, api):
        """PRD §2.4: the sweep "expires every certificate in `SUBMITTED` or `VERIFIED`
        status whose `expiry_date` is before the current logical date (with the
        renter-suspension cascade described in §3.1 when a `VERIFIED` certificate lapses)".
        PRD §3.1: "Both paths trigger the same cascade: every reservation in `HELD` status
        on the renter's productions becomes `EXPIRED`, every reservation in `CONFIRMED`
        status becomes `RELEASED` with its held quantity freed".

        Design: Difficulty/transitive_cascade/certificate_expiry_suspension_cascade
        """
        ctx = self._setup(api)
        set_logical_clock(api, "2026-08-20T00:00:00Z")
        ops = run_daily_ops(api)

        # Hop 1: the lapsed certificate expires.
        assert ctx["cert1"]["id"] in ops["expired_certificate_ids"]
        # Hop 2: with no other VERIFIED unexpired certificate, the renter suspends.
        assert get_renter(api, ctx["r1"]["id"])["status"] == "SUSPENDED"
        # Hop 3: BOTH HELD reservations expire via the cascade — RA's own hold lapses
        # 2026-08-21 and RB's 2026-08-22, both AFTER this 2026-08-20 run, so only the
        # cascade can explain their EXPIRED state.
        assert ctx["ra"]["id"] in ops["expired_reservation_ids"]
        assert ctx["rb"]["id"] in ops["expired_reservation_ids"]
        assert get_reservation(api, ctx["ra"]["id"])["status"] == "EXPIRED"
        assert get_reservation(api, ctx["rb"]["id"])["status"] == "EXPIRED"

    def test_cascade_frees_capacity_for_other_renters(self, api):
        """PRD §3.1: "every reservation in `CONFIRMED` status becomes `RELEASED` with its
        held quantity freed" — and §3.4's availability calculation counts only reservations
        "in `HELD` or `CONFIRMED` status", so cascade-expired holds stop consuming capacity.

        Design: Difficulty/transitive_cascade/certificate_expiry_suspension_cascade
        """
        ctx = self._setup(api)
        set_logical_clock(api, "2026-08-20T00:00:00Z")
        run_daily_ops(api)

        # The probe renter can now hold BOTH units over the exact expired windows.
        probe_reservation = place_reservation(
            api, ctx["p2"]["id"], ctx["probe"], ctx["item"]["id"], quantity=2,
            window_start_date="2026-09-01", window_end_date="2026-09-10",
        )
        assert probe_reservation["status"] == "HELD"
        assert probe_reservation["quantity"] == 2


class TestManualSuspendCascade:
    def _setup(self, api):
        """ACTIVE renter with a CONFIRMED reservation and a HELD reservation."""
        publish_rate_card(api)
        item = create_catalog_item(api, name="Tailcoat")
        acquire_unit(api, item["id"], barcode="BC-801")
        acquire_unit(api, item["id"], barcode="BC-802")
        renter = create_active_renter(api, name="Renter R")["renter"]
        production = create_confirmed_production(api, renter, closing_date="2026-09-20")
        r_conf = create_confirmed_reservation(
            api, production["id"], renter, item["id"], quantity=1,
            window_start_date="2026-09-01", window_end_date="2026-09-05",
        )
        r_held = place_reservation(
            api, production["id"], renter, item["id"], quantity=1,
            window_start_date="2026-09-06", window_end_date="2026-09-10",
        )
        return {"renter": renter, "r_conf": r_conf, "r_held": r_held}

    def test_manual_suspend_releases_confirmed_reservation(self, api, house_admin_headers):
        """PRD §3.1: "A `HouseAdmin` may patch a renter ... to move `status` between
        `ACTIVE` and `SUSPENDED` only" and "Both paths trigger the same cascade: every
        reservation in `HELD` status on the renter's productions becomes `EXPIRED`, every
        reservation in `CONFIRMED` status becomes `RELEASED` with its held quantity freed".

        Design: Difficulty/transitive_cascade/manual_suspend_release_cascade
        """
        ctx = self._setup(api)
        suspended = validate_success(
            api.update_renter(ctx["renter"]["id"], {"status": "SUSPENDED"},
                              house_admin_headers)
        )
        assert suspended["status"] == "SUSPENDED"
        # CONFIRMED branch of the cascade.
        assert get_reservation(api, ctx["r_conf"]["id"])["status"] == "RELEASED"

    def test_manual_suspend_expires_held_reservation(self, api, house_admin_headers):
        """PRD §3.1: "Both paths trigger the same cascade: every reservation in `HELD`
        status on the renter's productions becomes `EXPIRED`, every reservation in
        `CONFIRMED` status becomes `RELEASED` with its held quantity freed, and from then on
        reservation confirmation and pull-list dispatch for that renter fail with
        `ERR_RENTER_SUSPENDED`."

        Design: Difficulty/transitive_cascade/manual_suspend_release_cascade
        """
        ctx = self._setup(api)
        validate_success(
            api.update_renter(ctx["renter"]["id"], {"status": "SUSPENDED"},
                              house_admin_headers)
        )
        # HELD branch of the cascade.
        assert get_reservation(api, ctx["r_held"]["id"])["status"] == "EXPIRED"
        assert get_reservation(api, ctx["r_conf"]["id"])["status"] == "RELEASED"


class TestDeaccession:
    def test_deaccession_blocked_while_unit_out(self, api, house_admin_headers):
        """PRD §3.2: "Requesting deaccession requires that no reservation for the item is in
        `HELD` or `CONFIRMED` status (`ERR_ITEM_HAS_ACTIVE_HOLDS`) and that every unit of the
        item is `AVAILABLE`, `AWAITING_DISPOSAL`, or `DISPOSED` — a single unit `OUT`,
        `CLEANING`, or `REPAIR` blocks the request with `ERR_DEACCESSION_BLOCKED`."

        Design: Difficulty/cross_entity_state_dependency/deaccession_blocked_while_unit_out
        """
        ctx = setup_dispatched_scenario(api, quantity=1, num_units=1)
        assert get_unit(api, ctx["units"][0]["id"])["status"] == "OUT"

        resp = api.request_deaccession(ctx["item"]["id"], house_admin_headers)
        validate_error(resp, ApiErrorId.ERR_DEACCESSION_BLOCKED, 409)
        assert get_item(api, ctx["item"]["id"])["status"] == "ACTIVE"

    def test_deaccession_allowed_once_unit_available(self, api, house_admin_headers):
        """PRD §3.2: "On success the item moves `ACTIVE` → `DEACCESSION_PENDING`, every
        `AVAILABLE` unit moves to `AWAITING_DISPOSAL`" and "Reaching `READY` ... returns the
        unit from `CLEANING` or `REPAIR` to `AVAILABLE`." (§3.6).

        Design: Difficulty/cross_entity_state_dependency/deaccession_blocked_while_unit_out
        """
        ctx = setup_dispatched_scenario(api, quantity=1, num_units=1)
        unit_id = ctx["units"][0]["id"]

        set_logical_clock(api, "2026-09-10T00:00:00Z")
        check_in_line(api, ctx["lines"][0]["id"])
        ticket = cleaning_ticket_for_unit(api, unit_id)
        for _ in range(3):
            ticket = advance_ticket(api, ticket["id"])
        assert ticket["status"] == "READY"
        assert get_unit(api, unit_id)["status"] == "AVAILABLE"

        ok = validate_success(api.request_deaccession(ctx["item"]["id"], house_admin_headers))
        assert ok["status"] == "DEACCESSION_PENDING"
        assert get_unit(api, unit_id)["status"] == "AWAITING_DISPOSAL"

    def test_error_item_has_active_holds_on_deaccession(self, api, house_admin_headers):
        """PRD §3.2: "Requesting deaccession requires that no reservation for the item is in
        `HELD` or `CONFIRMED` status (`ERR_ITEM_HAS_ACTIVE_HOLDS`)".

        Design: Corner/errors/error_item_has_active_holds_on_deaccession
        """
        ctx = setup_confirmed_reservation_scenario(api, quantity=1, num_units=1)
        # The physical unit sits AVAILABLE; the CONFIRMED hold alone blocks deaccession.
        assert get_unit(api, ctx["units"][0]["id"])["status"] == "AVAILABLE"

        resp = api.request_deaccession(ctx["item"]["id"], house_admin_headers)
        validate_error(resp, ApiErrorId.ERR_ITEM_HAS_ACTIVE_HOLDS, 409)
        assert get_item(api, ctx["item"]["id"])["status"] == "ACTIVE"

    def test_derived_field_serviceable_count_reconciled(self, api):
        """PRD §3.2: "The computed `serviceable_unit_count` on an item counts exactly its
        units whose status is not `AWAITING_DISPOSAL` and not `DISPOSED`" and "a new unit
        starts `AVAILABLE`, and the item's `serviceable_unit_count` increases by one."
        PRD §3.6: "the unit moves `OUT` → `DISPOSED`, `serviceable_unit_count` is
        recomputed".

        Design: Corner/cross_cutting_layers/derived_field_serviceable_count_reconciled
        """
        publish_rate_card(api)
        item = create_catalog_item(api, name="I1")
        assert get_item(api, item["id"])["serviceable_unit_count"] == 0

        acquire_unit(api, item["id"], barcode="BC-DF1")
        acquire_unit(api, item["id"], barcode="BC-DF2")
        assert get_item(api, item["id"])["serviceable_unit_count"] == 2

        renter = create_active_renter(api, name="R")["renter"]
        production = create_confirmed_production(api, renter, closing_date="2026-10-26")
        create_confirmed_reservation(api, production["id"], renter, item["id"], quantity=1)
        pull_list = create_pull_list_for(api, production["id"], renter)
        _, lines = submit_and_get_lines(api, pull_list["id"])
        pick_all_lines(api, lines)
        dispatch_pull_list(api, pull_list["id"])
        # A unit OUT is still serviceable (not AWAITING_DISPOSAL/DISPOSED).
        assert get_item(api, item["id"])["serviceable_unit_count"] == 2

        validate_success(api.report_lost(lines[0]["id"], make_wardrobe_staff_headers()))
        # The lost unit is DISPOSED; the recomputed count drops to 1.
        assert get_item(api, item["id"])["serviceable_unit_count"] == 1


class TestDailyOps:
    def test_ops_run_checkpoint_expires_stale_holds(self, api):
        """PRD §2.4: the sweep "expires every `HELD` reservation whose `hold_expires_at` is
        before the current logical timestamp" — and only `HELD` holds: a `CONFIRMED`
        reservation created at the same instant is untouched.

        Design: Corner/cross_cutting_layers/ops_run_checkpoint_expires_stale_holds
        """
        publish_rate_card(api)
        item = create_catalog_item(api, name="I1")
        acquire_unit(api, item["id"], barcode="BC-OP1")
        acquire_unit(api, item["id"], barcode="BC-OP2")
        renter = create_active_renter(api, name="R")["renter"]
        production = create_confirmed_production(api, renter, closing_date="2026-10-26")
        # Both created at the startup clock 2026-08-01; r1's hold lapses 2026-08-04.
        r1 = place_reservation(api, production["id"], renter, item["id"], quantity=1,
                               window_start_date="2026-09-01", window_end_date="2026-09-05")
        r2 = place_reservation(api, production["id"], renter, item["id"], quantity=1,
                               window_start_date="2026-09-06", window_end_date="2026-09-10")
        confirm_reservation(api, r2, renter)

        set_logical_clock(api, "2026-08-05T00:00:00Z")
        ops = run_daily_ops(api)
        assert r1["id"] in ops["expired_reservation_ids"]
        assert r2["id"] not in ops["expired_reservation_ids"]
        assert get_reservation(api, r2["id"])["status"] == "CONFIRMED"

    def test_production_ops_advance_and_full_settle(self, api):
        """PRD §2.4: "Date advancement is **transitive within a single run**: a `CONFIRMED`
        production evaluated when the current date is already past `closing_date` moves
        `CONFIRMED` → `IN_RUN` → `WRAP` in that one run, and the `WRAP` → `SETTLED`
        evaluation then runs in the same pass."
        PRD §3.8: "A production in `WRAP` moves to `SETTLED` only when all of the following
        hold: every pull list of the production is `CLOSED` or `CANCELLED`; every invoice of
        the production is `PAID`, `CREDITED`, or `VOID`; and no unbilled charges remain".

        Design: Corner/state_machines/production_ops_advance_and_full_settle
        """
        ctx = setup_dispatched_scenario(api, quantity=1, num_units=1)
        production_id = ctx["production"]["id"]

        # Rental invoice (8000) fully paid.
        inv1 = issue_invoice(api, generate_invoice(api, production_id)["id"])
        paid1 = record_payment(api, inv1["id"], inv1["balance_cents"])
        assert paid1["status"] == "PAID"

        # Clean check-in on the due date: the single-line pull list auto-closes.
        set_logical_clock(api, "2026-09-10T00:00:00Z")
        line = check_in_line(api, ctx["lines"][0]["id"])
        assert line["status"] == "RETURNED"
        assert get_pull_list(api, ctx["pull_list"]["id"])["status"] == "CLOSED"

        # Supplemental cleaning invoice (1500) fully paid.
        inv2 = issue_invoice(api, generate_invoice(api, production_id)["id"])
        assert inv2["cleaning_charges_cents"] == 1500
        paid2 = record_payment(api, inv2["id"], inv2["balance_cents"])
        assert paid2["status"] == "PAID"

        # One sweep past closing settles the production end to end.
        set_logical_clock(api, "2026-10-27T00:00:00Z")
        ops = run_daily_ops(api)
        assert production_id in ops["advanced_production_ids"]
        assert production_id in ops["settled_production_ids"]
        assert get_production(api, production_id)["status"] == "SETTLED"
