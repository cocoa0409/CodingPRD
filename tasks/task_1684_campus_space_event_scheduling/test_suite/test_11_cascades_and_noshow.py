"""Transitive cascades: the placement-finalize bump chain, the daily-close
no-show/suspension chain, and the external-insurance confirmation gates."""

from test_helpers import (
    SCHEDULER,
    SERVICE_COORDINATOR,
    ApiErrorId,
    create_crew,
    create_order,
    create_run,
    daily_close,
    finalize_run,
    find_invoice_for_event,
    get_block,
    get_event,
    get_grant,
    get_invoice,
    get_order,
    get_org,
    org_headers,
    quote_order,
    approve_order,
    schedule_order,
    set_clock,
    setup_approved_event,
    setup_finalize_bump_chain,
    setup_noshow_chain_with_pending_request,
    validate_error,
    validate_success,
)


class TestFinalizeBumpChain:
    def test_finalize_places_block_and_bumps_the_confirmed_event(self, api):
        """PRD §3.3: "Placed blocks move to `PLACED` with `assigned_room_id` and
        `scheduling_run_id` set."
        PRD §3.4: "`REQUESTED` and `APPROVED` events are always bumpable;
        `CONFIRMED` events are bumpable only under the 72-hour and
        no-outstanding-grants shield described above."
        PRD §3.4: "The bump cascade clears the event's `room_id` to null, voids
        its `PROVISIONAL` invoice in a full waiver when one exists, cancels all
        non-terminal service orders with `fee_waived` set true, and revokes its
        `REQUESTED` access grants."

        Design: Difficulty/transitive_cascade/finalize_bump_chain_run_block_event_invoice_org
        """
        scn = setup_finalize_bump_chain()
        run = create_run(scn.term["id"])
        finalized = finalize_run(run["id"])
        assert finalized["status"] == "FINALIZED"
        assert finalized["placed_count"] == 1
        assert finalized["bumped_event_ids"] == [scn.event["id"]]

        block = get_block(scn.block["id"])
        assert block["status"] == "PLACED"
        assert block["assigned_room_id"] == scn.room["id"]

        event = get_event(scn.event["id"])
        assert event["status"] == "BUMPED"
        assert event["room_id"] is None

    def test_bump_chain_voids_invoice_cancels_order_revokes_grant(self, api):
        """PRD §3.4: "The bump cascade clears the event's `room_id` to null,
        voids its `PROVISIONAL` invoice in a full waiver when one exists,
        cancels all non-terminal service orders with `fee_waived` set true, and
        revokes its `REQUESTED` access grants."
        PRD §3.1: "`outstanding_balance_cents` is the sum, over the
        organization's invoices in `PROVISIONAL`, `FINALIZED`, or
        `PARTIALLY_PAID` status, of each invoice's `total_cents` less its
        `paid_cents` and `waived_cents`; voided invoices contribute nothing."

        Design: Difficulty/transitive_cascade/finalize_bump_chain_run_block_event_invoice_org
        """
        scn = setup_finalize_bump_chain()
        assert scn.invoice["total_cents"] == 16000, "room 10000 + quoted 6000"
        assert scn.out_before == 16000

        run = create_run(scn.term["id"])
        finalize_run(run["id"])

        invoice = get_invoice(scn.invoice["id"])
        assert invoice["status"] == "VOIDED", "bump waiver voids the provisional"

        order = get_order(scn.order["id"])
        assert order["status"] == "CANCELLED"
        assert order["fee_waived"] is True

        assert get_grant(scn.grant["id"])["status"] == "REVOKED"
        assert get_org(scn.org["id"])["outstanding_balance_cents"] == 0, (
            "ledger synced at the end of the chain"
        )


class TestDailyCloseNoShowChain:
    def test_third_no_show_suspends_the_org(self, api):
        """PRD §3.4: "a `CONFIRMED` event whose clock has passed fifteen minutes
        after `start_at` with no recorded check-in moves to `NO_SHOW`."
        PRD §3.4: "The organization's `no_show_count` is incremented by one and
        its `standing` recomputed — exactly two strikes means `PROBATION`, three
        or more means `SUSPENDED` with the full suspension cascade."
        PRD §2.4: "Because the order is pinned, a single checkpoint can, for
        example, mark a no-show, push an organization to `SUSPENDED`, and
        cascade that suspension onto the organization's other events within one
        run."

        Design: Difficulty/transitive_cascade/daily_close_noshow_strike_standing_suspension_decline
        """
        scn = setup_noshow_chain_with_pending_request()
        counters = daily_close()
        assert counters["no_shows_marked"] == 3
        assert counters["orgs_suspended"] == 1

        for ev in scn.no_show_events:
            assert get_event(ev["id"])["status"] == "NO_SHOW"

        org = get_org(scn.org["id"])
        assert org["no_show_count"] == 3
        assert org["standing"] == "SUSPENDED"

    def test_suspension_cascade_declines_the_pending_request(self, api):
        """PRD §3.1: "The organization's events still in `REQUESTED` move to
        `DECLINED` with `decline_reason` recording `ORG_SUSPENDED`; its events
        in `APPROVED` move to `CANCELLED` with `cancel_reason` recording
        `ORG_SUSPENDED`, a cancellation fee of zero, and their `PROVISIONAL`
        invoices voided; its access grants still in `REQUESTED` are revoked."

        Design: Difficulty/transitive_cascade/daily_close_noshow_strike_standing_suspension_decline
        """
        scn = setup_noshow_chain_with_pending_request()
        daily_close()

        pending = get_event(scn.pending_event["id"])
        assert pending["status"] == "DECLINED"
        assert pending["decline_reason"] == "ORG_SUSPENDED"


class TestConfirmGatedByOrgInsurance:
    def test_external_confirm_blocked_then_allowed_after_insurance_patch(self, api):
        """PRD §3.4: "For an `EXTERNAL` organization, the
        `insurance_certificate_expiry` must fall on or after the event's
        `end_at` and `insurance_coverage_cents` must be at least 100000000 cents
        of liability coverage, failing which the confirmation is rejected with
        `ERR_INSURANCE_INVALID`."
        PRD §3.1: "A `Scheduler` may later update the contact and insurance
        fields; each update increments the organization's `version` by one."

        Design: Difficulty/cross_entity_state_dependency/event_confirm_gated_by_org_insurance
        """
        scn = setup_approved_event(
            org_overrides={
                "name": "Garden Club",
                "org_type": "EXTERNAL",
                "contact_email": "garden@ext.org",
            },
            room_overrides={"name": "QUAD-1", "building_code": "QUAD", "capacity": 500},
            event_overrides={
                "title": "Plant Sale",
                "expected_attendance": 300,
                "start_at": "2026-09-10T14:00:00Z",
                "end_at": "2026-09-10T16:00:00Z",
            },
        )
        blocked = api.confirm_event(scn.event["id"], org_headers(scn.org))
        validate_error(blocked, ApiErrorId.ERR_INSURANCE_INVALID)
        assert get_event(scn.event["id"])["status"] == "APPROVED"

        validate_success(
            api.update_organization(
                scn.org["id"],
                {
                    "insurance_certificate_expiry": "2026-12-31T00:00:00Z",
                    "insurance_coverage_cents": 100000000,
                },
                SCHEDULER,
            ),
            200,
        )
        confirmed = validate_success(
            api.confirm_event(scn.event["id"], org_headers(scn.org)), 200
        )
        assert confirmed["status"] == "CONFIRMED"

    def test_coverage_below_floor_blocked_exactly_at_floor_allowed(self, api):
        """PRD §3.4: "For an `EXTERNAL` organization, the
        `insurance_certificate_expiry` must fall on or after the event's
        `end_at` and `insurance_coverage_cents` must be at least 100000000 cents
        of liability coverage, failing which the confirmation is rejected with
        `ERR_INSURANCE_INVALID`."

        Design: Difficulty/cross_entity_state_dependency/event_confirm_gated_by_org_insurance
        """
        scn = setup_approved_event(
            org_overrides={
                "name": "City Choir",
                "org_type": "EXTERNAL",
                "contact_email": "choir@ext.org",
                "insurance_certificate_expiry": "2026-12-31T00:00:00Z",
                "insurance_coverage_cents": 99999999,
            },
            room_overrides={"capacity": 100},
            event_overrides={
                "title": "Concert",
                "expected_attendance": 80,
                "start_at": "2026-09-10T14:00:00Z",
                "end_at": "2026-09-10T16:00:00Z",
            },
        )
        blocked = api.confirm_event(scn.event["id"], org_headers(scn.org))
        validate_error(blocked, ApiErrorId.ERR_INSURANCE_INVALID)

        validate_success(
            api.update_organization(
                scn.org["id"], {"insurance_coverage_cents": 100000000}, SCHEDULER
            ),
            200,
        )
        confirmed = validate_success(
            api.confirm_event(scn.event["id"], org_headers(scn.org)), 200
        )
        assert confirmed["status"] == "CONFIRMED", "the 100000000 floor is inclusive"


class TestInsuranceSafetyBeatsExpiredWindow:
    def _setup_expired_window_external(self, api, org_overrides):
        scn = setup_approved_event(
            org_overrides=org_overrides,
            room_overrides={"capacity": 100},
            event_overrides={
                "title": "Concert",
                "expected_attendance": 80,
                "start_at": "2026-09-10T14:00:00Z",
                "end_at": "2026-09-10T16:00:00Z",
            },
        )
        # Approved at the initial clock 2026-08-01 -> confirm_deadline 2026-08-03.
        set_clock("2026-08-04T00:00:00Z")
        return scn

    def test_expired_insurance_and_expired_window_reports_insurance(self, api):
        """PRD §2.9: "Every request is evaluated against ten validation tiers in
        a fixed relative order, and the ordering is normative: a failure in an
        earlier tier surfaces its error and masks any failures in later tiers."
        PRD §3.4: "The actor must own the event — a mismatch is masked as
        `ERR_NOT_FOUND` — and three gates apply in tier order. For an `EXTERNAL`
        organization, the `insurance_certificate_expiry` must fall on or after
        the event's `end_at` and `insurance_coverage_cents` must be at least
        100000000 cents of liability coverage, failing which the confirmation is
        rejected with `ERR_INSURANCE_INVALID`. The confirmation must arrive on
        or before the `confirm_deadline`, otherwise `ERR_CONFIRM_WINDOW_EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/confirm_external_insurance_safety_beats_expired_window_temporal
        """
        scn = self._setup_expired_window_external(
            api,
            {
                "name": "City Choir",
                "org_type": "EXTERNAL",
                "contact_email": "choir@ext.org",
                "insurance_certificate_expiry": "2026-08-20T00:00:00Z",
                "insurance_coverage_cents": 100000000,
            },
        )
        response = api.confirm_event(scn.event["id"], org_headers(scn.org))
        validate_error(response, ApiErrorId.ERR_INSURANCE_INVALID)
        assert get_event(scn.event["id"])["status"] == "APPROVED"

    def test_short_coverage_and_expired_window_reports_insurance(self, api):
        """PRD §2.9: "Compliance holds: external-client insurance validity at
        confirmation (`ERR_INSURANCE_INVALID`), the waiver segregation-of-duties
        rule (`ERR_SEGREGATION_OF_DUTIES`), and the suspended-organization bar
        on event creation and approval (`ERR_ORG_SUSPENDED`)."
        PRD §2.9: "Temporal windows: the term priority lock on approval and
        rebooking (`ERR_TERM_PRIORITY_LOCKED`), the confirmation window
        (`ERR_CONFIRM_WINDOW_EXPIRED`), and the check-in window
        (`ERR_CHECKIN_WINDOW_CLOSED`)."

        Design: Difficulty/priority_pair_validation_conflict/confirm_external_insurance_safety_beats_expired_window_temporal
        """
        scn = self._setup_expired_window_external(
            api,
            {
                "name": "City Choir",
                "org_type": "EXTERNAL",
                "contact_email": "choir@ext.org",
                "insurance_certificate_expiry": "2026-12-31T00:00:00Z",
                "insurance_coverage_cents": 50000000,
            },
        )
        response = api.confirm_event(scn.event["id"], org_headers(scn.org))
        validate_error(response, ApiErrorId.ERR_INSURANCE_INVALID)
        assert get_event(scn.event["id"])["status"] == "APPROVED"


def test_noshow_final_invoice_composition_external(api):
    """PRD §3.4: "Its invoice is finalized with the room charged at 100%, the
    fulfilled service charges, and a flat 5000-cent `no_show_fee_cents`, with no
    insurance surcharge applied."
    PRD §3.4: "Fulfilled orders move to `INVOICED`; every other non-terminal
    order is cancelled with `fee_waived` false."
    PRD §3.6: "On no-show, the total is the room charge at full value plus the
    final service charge plus the flat 5000-cent no-show fee plus deposit
    charges, with no surcharge."

    Design: Corner/calculations/noshow_final_invoice_composition_external
    """
    scn = setup_approved_event(
        org_overrides={
            "name": "CaterCo Client",
            "org_type": "EXTERNAL",
            "contact_email": "cc@ext.org",
            "insurance_certificate_expiry": "2026-12-31T00:00:00Z",
            "insurance_coverage_cents": 100000000,
        },
        room_overrides={"name": "NSH-1", "building_code": "NSH", "capacity": 40},
        event_overrides={
            "title": "Gala",
            "expected_attendance": 30,
            "start_at": "2026-09-10T16:00:00Z",
            "end_at": "2026-09-10T17:00:00Z",
        },
    )
    order = create_order(
        scn.event["id"], scn.org, category="CATERING", quantity=1,
        service_start_at="2026-09-10T15:30:00Z",
        service_end_at="2026-09-10T16:30:00Z",
    )
    quote_order(order["id"], 4000)
    approve_order(order["id"], scn.org)
    crew = create_crew(
        name="Cater One", category="CATERING", concurrent_capacity=1,
        shift_start="08:00", shift_end="20:00",
    )
    schedule_order(order["id"], crew["id"])
    validate_success(api.confirm_event(scn.event["id"], org_headers(scn.org)), 200)

    prov = find_invoice_for_event(scn.event["id"])
    assert prov["total_cents"] == 16320, "12000 + 4000 + 320 surcharge"
    assert prov["insurance_surcharge_cents"] == 320

    set_clock("2026-09-10T17:00:00Z")
    validate_success(
        api.fulfill_service_order(order["id"], SERVICE_COORDINATOR), 200
    )

    daily_close()
    event = get_event(scn.event["id"])
    assert event["status"] == "NO_SHOW"

    invoice = get_invoice(prov["id"])
    assert invoice["status"] == "FINALIZED"
    assert invoice["room_charge_cents"] == 12000
    assert invoice["service_charge_cents"] == 4000
    assert invoice["insurance_surcharge_cents"] == 0, "surcharge pinned OFF for no-show"
    assert invoice["no_show_fee_cents"] == 5000
    assert invoice["total_cents"] == 21000

    assert get_order(order["id"])["status"] == "INVOICED"

    org = get_org(scn.org["id"])
    assert org["no_show_count"] == 1
    assert org["standing"] == "GOOD"
