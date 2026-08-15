"""Pull lists: OCC, submission gates, unit selector, dispatch gates, cancellation."""
from test_helpers import (
    ApiErrorId,
    acquire_unit,
    advance_ticket,
    check_in_line,
    cleaning_ticket_for_unit,
    create_active_renter,
    create_catalog_item,
    create_confirmed_production,
    create_confirmed_reservation,
    create_production_draft,
    create_pull_list_for,
    dispatch_pull_list,
    generate_invoice,
    get_item,
    get_production,
    get_pull_list,
    get_renter,
    get_reservation,
    get_unit,
    issue_invoice,
    list_lines,
    make_renter_contact_headers,
    make_wardrobe_staff_headers,
    pick_all_lines,
    publish_rate_card,
    set_logical_clock,
    setup_confirmed_reservation_scenario,
    submit_and_get_lines,
    submit_pull_list,
    validate_error,
    validate_success,
)


def _pull_list_scenario(api, quantity=1, num_units=2, **kwargs):
    """CONFIRMED reservation plus a DRAFT pull list for the production."""
    ctx = setup_confirmed_reservation_scenario(
        api, quantity=quantity, num_units=num_units, **kwargs,
    )
    ctx["pull_list"] = create_pull_list_for(
        api, ctx["production"]["id"], ctx["renter"],
    )
    return ctx


class TestPullListOcc:
    def test_occ_stale_version_on_pull_list_create(self, api):
        """PRD §2.7: "If that value does not equal the production's current `version` — for
        example because another reservation was created against it, or the production was
        confirmed, since the client last read it — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)" and "Both reservation creation and pull-list creation
        increment the production's `version` by one on success, so any previously captured
        `expected_production_version` becomes stale after either write."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_pull_list_create
        """
        ctx = setup_confirmed_reservation_scenario(api)
        renter = ctx["renter"]
        production_id = ctx["production"]["id"]
        stale = get_production(api, production_id)["version"]

        first = create_pull_list_for(api, production_id, renter)
        assert first["status"] == "DRAFT"
        assert get_production(api, production_id)["version"] == stale + 1

        resp = api.create_pull_list(
            {"production_id": production_id, "expected_production_version": stale},
            make_renter_contact_headers(renter["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        fresh = get_production(api, production_id)["version"]
        retry = api.create_pull_list(
            {"production_id": production_id, "expected_production_version": fresh},
            make_renter_contact_headers(renter["id"]),
        )
        assert validate_success(retry, 201)["status"] == "DRAFT"


class TestSubmitGates:
    def test_error_nothing_to_pull_rejected(self, api, wardrobe_staff_headers):
        """PRD §3.5: "the production must have at least one reservation in `CONFIRMED` status
        not already covered by lines on a pull list in `PICKING`, `DISPATCHED`, or `CLOSED`
        status (`ERR_NOTHING_TO_PULL`)".

        Design: Corner/errors/error_nothing_to_pull_rejected
        """
        publish_rate_card(api)
        renter = create_active_renter(api, name="R")["renter"]
        production = create_confirmed_production(api, renter, closing_date="2026-09-20")
        pull_list = create_pull_list_for(api, production["id"], renter)

        resp = api.submit_pull_list(pull_list["id"], wardrobe_staff_headers)
        validate_error(resp, ApiErrorId.ERR_NOTHING_TO_PULL, 409)
        assert get_pull_list(api, pull_list["id"])["status"] == "DRAFT"

    def test_pull_list_dispatch_with_pending_line_rejected(self, api, wardrobe_staff_headers):
        """PRD §3.5: "Dispatch then requires every line in `PICKED` status
        (`ERR_LINES_NOT_PICKED`)".

        Design: Corner/state_machines/pull_list_dispatch_with_pending_line_rejected
        """
        ctx = _pull_list_scenario(api, quantity=2, num_units=2)
        pull_list, lines = submit_and_get_lines(api, ctx["pull_list"]["id"])
        assert len(lines) == 2
        # Pick only the first line; the second stays PENDING.
        validate_success(api.pick_line(lines[0]["id"], wardrobe_staff_headers))

        resp = api.dispatch_pull_list(pull_list["id"], wardrobe_staff_headers)
        validate_error(resp, ApiErrorId.ERR_LINES_NOT_PICKED, 409)
        # No partial dispatch: both units are still AVAILABLE on the shelf.
        for unit in ctx["units"]:
            assert get_unit(api, unit["id"])["status"] == "AVAILABLE"

    def test_error_reservation_in_use_on_release(self, api):
        """PRD §3.4: "A `RenterContact` may release a `HELD` reservation unconditionally, and
        may release a `CONFIRMED` one only while no pull-list line in `PENDING`, `PICKED`, or
        `OUT` status references it — otherwise the release is rejected with
        `ERR_RESERVATION_IN_USE`." and "Submission alone does not fulfill: a
        submitted-but-undispatched reservation stays `CONFIRMED`, referenced by its active
        lines".

        Design: Corner/errors/error_reservation_in_use_on_release
        """
        ctx = _pull_list_scenario(api)
        submit_pull_list(api, ctx["pull_list"]["id"])

        resp = api.release_reservation(
            ctx["reservation"]["id"], make_renter_contact_headers(ctx["renter"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RESERVATION_IN_USE, 409)
        assert get_reservation(api, ctx["reservation"]["id"])["status"] == "CONFIRMED"


class TestUnitSelector:
    def test_unit_selector_ranking_tiebreak_and_grade_d_exclusion(
        self, api, wardrobe_staff_headers,
    ):
        """PRD §3.5: "Candidates are ranked by `condition_grade` ascending (`A` first), then
        `last_returned_date` ascending with nulls first, then `created_at` ascending, and the
        top `quantity` units are taken."
        PRD §3.2: "Grade `D` units are never assigned to pull lists."

        Design: Corner/calculations/unit_selector_ranking_tiebreak_and_grade_d_exclusion
        """
        publish_rate_card(api)
        item = create_catalog_item(api, name="I1")
        u1 = acquire_unit(api, item["id"], barcode="BC-T1", condition_grade="B")
        u2 = acquire_unit(api, item["id"], barcode="BC-T2", condition_grade="B")
        u3 = acquire_unit(api, item["id"], barcode="BC-T3", condition_grade="D",
                          acquisition_date="2020-01-15")
        renter = create_active_renter(api, name="R")["renter"]
        production = create_confirmed_production(api, renter, closing_date="2026-10-26")

        # Cycle 1: both B units have never been rented -> created_at ASC picks u1.
        create_confirmed_reservation(
            api, production["id"], renter, item["id"], quantity=1,
            window_start_date="2026-09-01", window_end_date="2026-09-05",
        )
        pl1 = create_pull_list_for(api, production["id"], renter)
        _, lines1 = submit_and_get_lines(api, pl1["id"])
        assert lines1[0]["item_unit_id"] == u1["id"], (
            "equal grades, both never rented: created_at ASC must select the first unit"
        )

        pick_all_lines(api, lines1)
        dispatch_pull_list(api, pl1["id"])
        set_logical_clock(api, "2026-09-05T00:00:00Z")
        line1 = check_in_line(api, lines1[0]["id"])
        assert line1["status"] == "RETURNED"
        ticket = cleaning_ticket_for_unit(api, u1["id"])
        for _ in range(3):
            ticket = advance_ticket(api, ticket["id"])
        assert ticket["status"] == "READY"
        assert get_unit(api, u1["id"])["status"] == "AVAILABLE"

        # Cycle 2: u1 now carries last_returned_date; nulls-first ranking picks u2.
        create_confirmed_reservation(
            api, production["id"], renter, item["id"], quantity=1,
            window_start_date="2026-09-10", window_end_date="2026-09-15",
        )
        pl2 = create_pull_list_for(api, production["id"], renter)
        _, lines2 = submit_and_get_lines(api, pl2["id"])
        assert lines2[0]["item_unit_id"] == u2["id"], (
            "last_returned_date ASC nulls first: the never-rented u2 beats u1"
        )

        # The grade-D unit was never a candidate in either cycle.
        assert get_unit(api, u3["id"])["status"] == "AVAILABLE"
        assigned = {l["item_unit_id"] for l in lines1 + lines2}
        assert u3["id"] not in assigned

    def test_grade_a_condition_multiplier_applies(self, api, wardrobe_staff_headers):
        """PRD §3.5: "The reservation's frozen-or-current `quoted_charge_cents` is divided by
        its `quantity` and rounded half up to a whole cent, pinning the division rounding at
        this step; that per-unit figure is then multiplied by a condition multiplier taken
        from the unit's `condition_grade` at assignment — 1.20 for grade `A`, 1.00 for grade
        `B`, 0.85 for grade `C` — and the result is rounded half up again."

        Design: Corner/calculations/grade_a_condition_multiplier_applies
        """
        publish_rate_card(api)
        item = create_catalog_item(api, name="I1")
        ua = acquire_unit(api, item["id"], barcode="BC-A1", condition_grade="A",
                          acquisition_date="2026-01-15", acquisition_cost_cents=90000)
        renter = create_active_renter(api, name="R")["renter"]
        production = create_confirmed_production(api, renter, closing_date="2026-10-26")
        reservation = create_confirmed_reservation(
            api, production["id"], renter, item["id"], quantity=1,
            window_start_date="2026-09-01", window_end_date="2026-09-10",
        )
        assert reservation["quoted_charge_cents"] == 8000  # unmultiplied LONG_RUN quote

        pull_list = create_pull_list_for(api, production["id"], renter)
        _, lines = submit_and_get_lines(api, pull_list["id"])
        assert lines[0]["item_unit_id"] == ua["id"]
        # round_half_up(8000 / 1) * 1.20 -> 9600 on the line only.
        assert lines[0]["rental_charge_cents"] == 9600
        assert get_reservation(api, reservation["id"])["quoted_charge_cents"] == 8000


class TestDispatchRenterGate:
    def _picked_list(self, api):
        ctx = _pull_list_scenario(api, quantity=1, num_units=1)
        pull_list, lines = submit_and_get_lines(api, ctx["pull_list"]["id"])
        pick_all_lines(api, lines)
        set_logical_clock(api, "2026-08-31T00:00:00Z")
        ctx["pull_list"] = pull_list
        ctx["lines"] = lines
        return ctx

    def test_dispatch_rejected_while_renter_suspended(self, api, house_admin_headers,
                                                      wardrobe_staff_headers):
        """PRD §3.5: "Dispatch then requires every line in `PICKED` status
        (`ERR_LINES_NOT_PICKED`), plus three renter gates: the renter `ACTIVE`
        (`ERR_RENTER_SUSPENDED`), not on credit hold (`ERR_CREDIT_LIMIT_EXCEEDED`), and
        holding a certificate in `VERIFIED` status with `expiry_date` on or after the current
        logical date (`ERR_INSURANCE_NOT_VERIFIED`)."

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_active_insured_renter
        """
        ctx = self._picked_list(api)
        resp = api.update_renter(ctx["renter"]["id"], {"status": "SUSPENDED"},
                                 house_admin_headers)
        assert validate_success(resp)["status"] == "SUSPENDED"

        resp = api.dispatch_pull_list(ctx["pull_list"]["id"], wardrobe_staff_headers)
        validate_error(resp, ApiErrorId.ERR_RENTER_SUSPENDED, 409)
        assert get_pull_list(api, ctx["pull_list"]["id"])["status"] == "PICKING"

    def test_dispatch_succeeds_after_renter_reactivated(self, api, house_admin_headers,
                                                        wardrobe_staff_headers):
        """PRD §3.1: "manual reactivation requires at least one certificate in `VERIFIED`
        status with `expiry_date` on or after the current logical date, failing with
        `ERR_INSURANCE_NOT_VERIFIED` otherwise."
        PRD §3.5: "Dispatch moves the list `PICKING` → `DISPATCHED`".

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_active_insured_renter
        """
        ctx = self._picked_list(api)
        validate_success(
            api.update_renter(ctx["renter"]["id"], {"status": "SUSPENDED"},
                              house_admin_headers)
        )
        reactivated = validate_success(
            api.update_renter(ctx["renter"]["id"], {"status": "ACTIVE"},
                              house_admin_headers)
        )
        assert reactivated["status"] == "ACTIVE"

        dispatched = validate_success(
            api.dispatch_pull_list(ctx["pull_list"]["id"], wardrobe_staff_headers)
        )
        assert dispatched["status"] == "DISPATCHED"


class TestUnitBufferExclusionAtSubmit:
    def _setup(self, api):
        """One unit; R1 Sep 1-10 CONFIRMED and submitted (line occupies the unit buffered
        through Sep 12); R2 Sep 11-13 CONFIRMED (passes the aggregate check)."""
        publish_rate_card(api)
        item = create_catalog_item(api, name="Tailcoat")
        u1 = acquire_unit(api, item["id"], barcode="BC-1901")
        renter = create_active_renter(api, name="Renter R")["renter"]
        production = create_confirmed_production(api, renter, closing_date="2026-10-26")
        create_confirmed_reservation(  # the hold is exercised through its pull-list line
            api, production["id"], renter, item["id"], quantity=1,
            window_start_date="2026-09-01", window_end_date="2026-09-10",
        )
        pl1 = create_pull_list_for(api, production["id"], renter)
        pl1, lines1 = submit_and_get_lines(api, pl1["id"])
        assert lines1[0]["item_unit_id"] == u1["id"]

        # Sep 11-13 does not inclusively overlap Sep 1-10 -> reservation confirms fine.
        r2 = create_confirmed_reservation(
            api, production["id"], renter, item["id"], quantity=1,
            window_start_date="2026-09-11", window_end_date="2026-09-13",
        )
        assert r2["status"] == "CONFIRMED"
        return {"item": item, "u1": u1, "renter": renter, "production": production,
                "r2": r2}

    def test_submit_fails_with_buffer_conflict(self, api, wardrobe_staff_headers):
        """PRD §3.5: "Note this is a per-unit **strict buffered** exclusion, unlike the
        reservation-level inclusive aggregate check of §3.4: back-to-back windows falling
        inside the buffer are rejected for that unit." and "any shortfall rejects the entire
        submission with `ERR_NO_UNITS_AVAILABLE` and no lines are created at all."

        Design: Difficulty/resource_temporal_overlap/unit_buffer_exclusion_at_submit
        """
        ctx = self._setup(api)
        pl2 = create_pull_list_for(api, ctx["production"]["id"], ctx["renter"])
        resp = api.submit_pull_list(pl2["id"], wardrobe_staff_headers)
        # COSTUME buffer is 2 days: the line occupies the unit Sep 1 .. Sep 12,
        # which collides with the requested Sep 11 start.
        validate_error(resp, ApiErrorId.ERR_NO_UNITS_AVAILABLE, 409)

    def test_submit_atomic_no_lines_created(self, api, wardrobe_staff_headers):
        """PRD §3.5: "any shortfall rejects the entire submission with
        `ERR_NO_UNITS_AVAILABLE` and no lines are created at all."

        Design: Difficulty/resource_temporal_overlap/unit_buffer_exclusion_at_submit
        """
        ctx = self._setup(api)
        pl2 = create_pull_list_for(api, ctx["production"]["id"], ctx["renter"])
        resp = api.submit_pull_list(pl2["id"], wardrobe_staff_headers)
        validate_error(resp, ApiErrorId.ERR_NO_UNITS_AVAILABLE, 409)

        assert get_pull_list(api, pl2["id"])["status"] == "DRAFT"
        assert list_lines(api, pull_list_id=pl2["id"]) == []


class TestUnitPoolConserved:
    def _setup(self, api):
        publish_rate_card(api)
        item = create_catalog_item(api, name="Tailcoat")
        u1 = acquire_unit(api, item["id"], barcode="BC-2001")
        u2 = acquire_unit(api, item["id"], barcode="BC-2002")
        renter = create_active_renter(api, name="Renter R")["renter"]
        production = create_confirmed_production(api, renter, closing_date="2026-10-26")
        r1 = create_confirmed_reservation(
            api, production["id"], renter, item["id"], quantity=2,
            window_start_date="2026-09-01", window_end_date="2026-09-10",
        )
        pl = create_pull_list_for(api, production["id"], renter)
        return {"item": item, "u1": u1, "u2": u2, "renter": renter,
                "production": production, "r1": r1, "pl": pl}

    def test_submit_preserves_unit_pool(self, api):
        """PRD §3.2: "The computed `serviceable_unit_count` on an item counts exactly its
        units whose status is not `AWAITING_DISPOSAL` and not `DISPOSED` — this is the pool
        every reservation capacity check draws on."
        PRD §3.5: "the units were never removed from `AVAILABLE`".

        Design: Difficulty/compensating_invariant/unit_pool_conserved_across_submit_cancel
        """
        ctx = self._setup(api)
        assert get_item(api, ctx["item"]["id"])["serviceable_unit_count"] == 2

        pull_list = submit_pull_list(api, ctx["pl"]["id"])
        assert pull_list["status"] == "PICKING"
        # Assignment alone must not shrink the pool or move the physical units.
        assert get_item(api, ctx["item"]["id"])["serviceable_unit_count"] == 2
        assert get_unit(api, ctx["u1"]["id"])["status"] == "AVAILABLE"
        assert get_unit(api, ctx["u2"]["id"])["status"] == "AVAILABLE"

    def test_cancel_restores_assignments_and_reservation(self, api, wardrobe_staff_headers):
        """PRD §3.5: "Cancelling a `PICKING` list deletes all its `PENDING` and `PICKED`
        lines and releases the unit assignments (the units were never removed from
        `AVAILABLE`), while the covered reservations stay `CONFIRMED` — fulfillment happens
        only at dispatch, so no rollback is needed."

        Design: Difficulty/compensating_invariant/unit_pool_conserved_across_submit_cancel
        """
        ctx = self._setup(api)
        submit_pull_list(api, ctx["pl"]["id"])

        cancelled = validate_success(
            api.cancel_pull_list(ctx["pl"]["id"], wardrobe_staff_headers)
        )
        assert cancelled["status"] == "CANCELLED"
        assert get_item(api, ctx["item"]["id"])["serviceable_unit_count"] == 2
        assert get_unit(api, ctx["u1"]["id"])["status"] == "AVAILABLE"
        assert get_unit(api, ctx["u2"]["id"])["status"] == "AVAILABLE"
        assert get_reservation(api, ctx["r1"]["id"])["status"] == "CONFIRMED"
        assert list_lines(api, pull_list_id=ctx["pl"]["id"]) == []


class TestStateBeatsFiscalOnDispatch:
    def _setup(self, api, house_admin_headers):
        """PL1 (P1, long-run) PICKING with its line PICKED; renter on credit hold from an
        issued P2 invoice after the limit is lowered; then PL1 is cancelled — both a state
        violation and a fiscal violation exist at once."""
        publish_rate_card(api)
        item = create_catalog_item(api, name="Tailcoat")
        acquire_unit(api, item["id"], barcode="BC-1001")
        acquire_unit(api, item["id"], barcode="BC-1002")
        renter = create_active_renter(api, name="Renter R")["renter"]

        p1 = create_confirmed_production(api, renter, title="P1", closing_date="2026-10-26")
        create_confirmed_reservation(
            api, p1["id"], renter, item["id"], quantity=1,
            window_start_date="2026-09-01", window_end_date="2026-09-10",
        )
        pl1 = create_pull_list_for(api, p1["id"], renter)
        pl1, lines1 = submit_and_get_lines(api, pl1["id"])
        pick_all_lines(api, lines1)

        p2 = create_confirmed_production(api, renter, title="P2", closing_date="2026-09-20")
        create_confirmed_reservation(
            api, p2["id"], renter, item["id"], quantity=1,
            window_start_date="2026-09-11", window_end_date="2026-09-15",
        )
        pl2 = create_pull_list_for(api, p2["id"], renter)
        pl2, lines2 = submit_and_get_lines(api, pl2["id"])
        pick_all_lines(api, lines2)
        dispatch_pull_list(api, pl2["id"])

        invoice = generate_invoice(api, p2["id"])
        assert invoice["total_cents"] == 5000  # DAILY: 1 * 1000 * 5 days
        issue_invoice(api, invoice["id"])

        patched = validate_success(
            api.update_renter(renter["id"], {"credit_limit_cents": 4000},
                              house_admin_headers)
        )
        assert patched["credit_hold"] is True  # 5000 outstanding > 4000 limit

        cancelled = validate_success(
            api.cancel_pull_list(pl1["id"], make_wardrobe_staff_headers())
        )
        assert cancelled["status"] == "CANCELLED"
        return {"renter": renter, "pl1": pl1}

    def test_dispatch_on_cancelled_list_with_credit_hold_gives_invalid_state(
        self, api, house_admin_headers, wardrobe_staff_headers,
    ):
        """PRD §2.9: "the server evaluates them in a fixed priority order, so that the
        surfaced error is deterministic" — item 5, "**State** — the target resource is in a
        valid from-state for the requested transition; this covers `ERR_INVALID_STATE`",
        precedes item 11, "**Fiscal rules last** — credit-hold gates
        (`ERR_CREDIT_LIMIT_EXCEEDED`)".

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_dispatch
        """
        ctx = self._setup(api, house_admin_headers)
        resp = api.dispatch_pull_list(ctx["pl1"]["id"], wardrobe_staff_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_fiscal_error_not_surfaced_when_state_fails(
        self, api, house_admin_headers, wardrobe_staff_headers,
    ):
        """PRD §2.9: "11. **Fiscal rules last** — credit-hold gates
        (`ERR_CREDIT_LIMIT_EXCEEDED`)" — with both rules violated, the state error
        (`ERR_INVALID_STATE`, priority 5) is the one returned, never the fiscal error.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_dispatch
        """
        ctx = self._setup(api, house_admin_headers)
        # Sanity: the fiscal violation genuinely holds at dispatch time.
        assert get_renter(api, ctx["renter"]["id"])["credit_hold"] is True

        resp = api.dispatch_pull_list(ctx["pl1"]["id"], wardrobe_staff_headers)
        err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        assert err["error_id"] != ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED
        assert get_pull_list(api, ctx["pl1"]["id"])["status"] == "CANCELLED"


class TestReferentialBeatsTemporalOnReserve:
    def _setup(self, api, house_admin_headers):
        publish_rate_card(api)
        item = create_catalog_item(api, name="Tailcoat")
        acquire_unit(api, item["id"], barcode="BC-1101")
        renter = create_active_renter(api, name="Renter R")["renter"]
        production = create_production_draft(api, renter, closing_date="2026-09-20")
        deaccessioned = validate_success(
            api.request_deaccession(item["id"], house_admin_headers)
        )
        assert deaccessioned["status"] == "DEACCESSION_PENDING"
        return {"item": item, "renter": renter, "production": production}

    def test_deaccessioned_item_and_bad_window_gives_not_rentable(
        self, api, house_admin_headers,
    ):
        """PRD §2.9: item 8, "**Referential usability** — referenced objects are usable: the
        item is rentable (`ERR_ITEM_NOT_RENTABLE`)", precedes item 9, "**Temporal rules** —
        date windows: `window_end_date` on or after `window_start_date` and the window within
        production bounds (`ERR_WINDOW_OUT_OF_BOUNDS`)".
        PRD §3.2: "new reservations against it are rejected with `ERR_ITEM_NOT_RENTABLE`."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_reserve
        """
        ctx = self._setup(api, house_admin_headers)
        # Window 2026-08-01..2026-08-05 also precedes rehearsal_start_date 2026-08-10.
        resp = api.create_reservation(
            {
                "production_id": ctx["production"]["id"],
                "item_id": ctx["item"]["id"],
                "quantity": 1,
                "window_start_date": "2026-08-01",
                "window_end_date": "2026-08-05",
                "expected_production_version": get_production(
                    api, ctx["production"]["id"],
                )["version"],
            },
            make_renter_contact_headers(ctx["renter"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_RENTABLE, 409)

    def test_temporal_error_not_surfaced_when_referential_fails(
        self, api, house_admin_headers,
    ):
        """PRD §2.9: "the server evaluates them in a fixed priority order, so that the
        surfaced error is deterministic" — referential usability (8) beats temporal rules
        (9), so the out-of-bounds window must not surface `ERR_WINDOW_OUT_OF_BOUNDS` here.

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_reserve
        """
        ctx = self._setup(api, house_admin_headers)
        assert get_item(api, ctx["item"]["id"])["status"] == "DEACCESSION_PENDING"

        resp = api.create_reservation(
            {
                "production_id": ctx["production"]["id"],
                "item_id": ctx["item"]["id"],
                "quantity": 1,
                "window_start_date": "2026-08-01",
                "window_end_date": "2026-08-05",
                "expected_production_version": get_production(
                    api, ctx["production"]["id"],
                )["version"],
            },
            make_renter_contact_headers(ctx["renter"]["id"]),
        )
        err = validate_error(resp, ApiErrorId.ERR_ITEM_NOT_RENTABLE, 409)
        assert err["error_id"] != ApiErrorId.ERR_WINDOW_OUT_OF_BOUNDS
