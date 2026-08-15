"""Reservation holds: validation, OCC, capacity windows, amend cycle, hold expiry."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    acquire_unit,
    assert_reservation,
    confirm_production,
    create_active_renter,
    create_catalog_item,
    create_confirmed_production,
    create_production_draft,
    create_reservation_payload,
    get_production,
    get_reservation,
    make_renter_contact_headers,
    parse_iso,
    place_reservation,
    publish_rate_card,
    set_logical_clock,
    setup_confirmed_reservation_scenario,
    confirm_reservation,
    validate_error,
    validate_success,
)


def _base_scenario(api, closing_date="2026-10-26", num_units=2):
    """Rate card, item with units, ACTIVE renter, CONFIRMED production."""
    publish_rate_card(api)
    item = create_catalog_item(api, name="I1")
    for i in range(num_units):
        acquire_unit(api, item["id"], barcode=f"BC-{uuid_tag()}-{i}")
    renter = create_active_renter(api, name="R")["renter"]
    production = create_confirmed_production(api, renter, closing_date=closing_date)
    return item, renter, production


def uuid_tag() -> str:
    from uuid import uuid4
    return uuid4().hex[:6]


class TestReservationValidation:
    def test_reservation_create_missing_required_field_rejected(self, api):
        """PRD §2.9: "missing required field, wrong type, invalid enum member, or malformed
        date, reported as `ERR_VALIDATION`; this is the lowest-priority check and surfaces
        only after all business rules pass."
        PRD §3.4: "A `RenterContact` places a hold with a payload containing the
        `production_id`, the `item_id`, the `quantity` (at least 1, else
        `ERR_QUANTITY_INVALID`), the inclusive `window_start_date` and `window_end_date` of
        need, and the OCC guard `expected_production_version`".

        Design: Corner/entities/reservation_create_missing_required_field_rejected
        """
        item, renter, production = _base_scenario(api)
        payload = create_reservation_payload(
            production_id=production["id"], item_id=item["id"],
            window_start_date="2026-09-01", window_end_date="2026-09-10",
            expected_production_version=get_production(api, production["id"])["version"],
        )
        del payload["quantity"]
        resp = api.create_reservation(payload, make_renter_contact_headers(renter["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)

    def test_reservation_quantity_zero_rejected(self, api):
        """PRD §3.4: "the `quantity` (at least 1, else `ERR_QUANTITY_INVALID`)".

        Design: Corner/validations/reservation_quantity_zero_rejected
        """
        item, renter, production = _base_scenario(api)
        payload = create_reservation_payload(
            production_id=production["id"], item_id=item["id"], quantity=0,
            expected_production_version=get_production(api, production["id"])["version"],
        )
        resp = api.create_reservation(payload, make_renter_contact_headers(renter["id"]))
        validate_error(resp, ApiErrorId.ERR_QUANTITY_INVALID, 400)

    def test_error_window_out_of_bounds_and_date_order(self, api):
        """PRD §3.4: "the window within the production's bounds — `window_end_date` on or
        after `window_start_date`, and the whole window inside the span from
        `rehearsal_start_date` through `return_by_date` inclusive, else
        `ERR_WINDOW_OUT_OF_BOUNDS`."
        PRD §3.3: "The dates must satisfy rehearsal start on or before performance start on
        or before closing, at creation and again at confirmation, else `ERR_DATE_ORDER`."

        Design: Corner/errors/error_window_out_of_bounds_and_date_order
        """
        # Confirmed long-run production: closing 2026-10-26 -> return_by_date 2026-10-29.
        item, renter, production = _base_scenario(api, closing_date="2026-10-26")
        assert get_production(api, production["id"])["return_by_date"].startswith("2026-10-29")

        payload = create_reservation_payload(
            production_id=production["id"], item_id=item["id"],
            window_start_date="2026-10-20", window_end_date="2026-10-30",
            expected_production_version=get_production(api, production["id"])["version"],
        )
        resp = api.create_reservation(payload, make_renter_contact_headers(renter["id"]))
        validate_error(resp, ApiErrorId.ERR_WINDOW_OUT_OF_BOUNDS, 422)

        # A production whose closing precedes its opening night fails at creation.
        resp = api.create_production(
            {
                "renter_id": renter["id"],
                "title": "Bad",
                "rehearsal_start_date": "2026-08-10",
                "performance_start_date": "2026-09-01",
                "closing_date": "2026-08-01",
            },
            make_renter_contact_headers(renter["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DATE_ORDER, 422)


class TestReservationOcc:
    def test_stale_version_beats_window_bounds(self, api):
        """PRD §2.9: "the server evaluates them in a fixed priority order, so that the
        surfaced error is deterministic" — item 6, "`expected_production_version` equals the
        current `Production.version` on reservation and pull-list creation, else
        `ERR_STALE_VERSION`; evaluated here, immediately after state checks and before any
        business rule", precedes item 9, "Temporal rules — date windows ...
        (`ERR_WINDOW_OUT_OF_BOUNDS`)".

        Design: Corner/validations/stale_version_beats_window_bounds
        """
        item, renter, production = _base_scenario(api)
        stale_version = get_production(api, production["id"])["version"]
        # First create bumps the production version, leaving stale_version behind.
        place_reservation(api, production["id"], renter, item["id"], quantity=1,
                          window_start_date="2026-09-01", window_end_date="2026-09-10")

        # The second attempt carries BOTH a stale version and an out-of-bounds window.
        payload = create_reservation_payload(
            production_id=production["id"], item_id=item["id"], quantity=1,
            window_start_date="2026-08-01", window_end_date="2026-08-05",
            expected_production_version=stale_version,
        )
        resp = api.create_reservation(payload, make_renter_contact_headers(renter["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    def test_occ_stale_version_on_reservation_create(self, api):
        """PRD §2.7: "If that value does not equal the production's current `version` — for
        example because another reservation was created against it, or the production was
        confirmed, since the client last read it — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from writing against a
        production it has not observed. Both reservation creation and pull-list creation
        increment the production's `version` by one on success".

        Design: Corner/cross_cutting_layers/occ_stale_version_on_reservation_create
        """
        item, renter, production = _base_scenario(api)
        observed = get_production(api, production["id"])["version"]
        first = place_reservation(api, production["id"], renter, item["id"], quantity=1,
                                  window_start_date="2026-09-01", window_end_date="2026-09-05")
        assert_reservation(first)
        assert get_production(api, production["id"])["version"] == observed + 1

        payload = create_reservation_payload(
            production_id=production["id"], item_id=item["id"], quantity=1,
            window_start_date="2026-09-06", window_end_date="2026-09-10",
            expected_production_version=observed,
        )
        resp = api.create_reservation(payload, make_renter_contact_headers(renter["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        # Re-reading and retrying with the current version succeeds.
        fresh = get_production(api, production["id"])["version"]
        payload["expected_production_version"] = fresh
        retry = api.create_reservation(payload, make_renter_contact_headers(renter["id"]))
        data = validate_success(retry, 201)
        assert data["status"] == "HELD"


class TestHoldLifecycle:
    def test_error_hold_expired_on_late_confirm(self, api):
        """PRD §3.4: "the hold must be unexpired — the current logical timestamp on or before
        `hold_expires_at`, else `ERR_HOLD_EXPIRED`" and "its `hold_expires_at` set to the
        current logical clock plus 72 hours."

        Design: Corner/errors/error_hold_expired_on_late_confirm
        """
        item, renter, production = _base_scenario(api)
        # Created at the startup clock 2026-08-01T00:00:00Z -> expires 2026-08-04T00:00:00Z.
        reservation = place_reservation(api, production["id"], renter, item["id"])
        assert parse_iso(reservation["hold_expires_at"]) == datetime(
            2026, 8, 4, 0, 0, 0, tzinfo=timezone.utc,
        )

        set_logical_clock(api, "2026-08-04T00:00:01Z")
        resp = api.confirm_reservation(
            reservation["id"], make_renter_contact_headers(renter["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_HOLD_EXPIRED, 409)
        # No ops sweep ran, so the hold is lazily rejected, not state-mutated.
        assert get_reservation(api, reservation["id"])["status"] == "HELD"

    def test_reservation_release_twice_rejected(self, api):
        """PRD §3.4: "The reservation states are `HELD`, `CONFIRMED`, `RELEASED`, `EXPIRED`,
        and `FULFILLED`, the last three terminal" and "A `RenterContact` may release a `HELD`
        reservation unconditionally".
        PRD §2.9: "the target resource is in a valid from-state for the requested transition;
        this covers `ERR_INVALID_STATE`".

        Design: Corner/state_machines/reservation_release_twice_rejected
        """
        publish_rate_card(api)
        item = create_catalog_item(api, name="I1")
        acquire_unit(api, item["id"], barcode=f"BC-{uuid_tag()}")
        renter = create_active_renter(api, name="R")["renter"]
        production = create_production_draft(api, renter, closing_date="2026-10-26")
        reservation = place_reservation(api, production["id"], renter, item["id"])

        first = validate_success(
            api.release_reservation(reservation["id"], make_renter_contact_headers(renter["id"]))
        )
        assert first["status"] == "RELEASED"

        resp = api.release_reservation(
            reservation["id"], make_renter_contact_headers(renter["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestAmendRequoteCycle:
    def _confirmed_long_run_reservation(self, api):
        ctx = setup_confirmed_reservation_scenario(api, quantity=1, num_units=2)
        assert ctx["reservation"]["quoted_charge_cents"] == 8000
        assert ctx["reservation"]["status"] == "CONFIRMED"
        return ctx

    def test_amend_drops_confirmed_to_held_and_requotes(self, api):
        """PRD §3.4: "Amending a `CONFIRMED` reservation drops it back to `HELD`; amending a
        `HELD` reservation keeps it `HELD`. Either way the quote is recomputed under the
        production's pinned rate card and `hold_expires_at` resets to the current logical
        clock plus another 72 hours."

        Design: Difficulty/non_linear_state_machine/reservation_amend_requote_cycle
        """
        ctx = self._confirmed_long_run_reservation(api)
        reservation = ctx["reservation"]
        renter = ctx["renter"]
        hold_before = parse_iso(reservation["hold_expires_at"])
        assert hold_before == datetime(2026, 8, 4, 0, 0, 0, tzinfo=timezone.utc)

        set_logical_clock(api, "2026-08-02T00:00:00Z")
        amended = validate_success(
            api.amend_reservation(
                reservation["id"], {"quantity": 2},
                make_renter_contact_headers(renter["id"]),
            )
        )
        assert amended["status"] == "HELD", "amend cycles CONFIRMED back to HELD"
        # 2 * 5000 * ceil(10/7) weeks * (1 - 0.20) = 16000.
        assert amended["quoted_charge_cents"] == 16000
        hold_after = parse_iso(amended["hold_expires_at"])
        assert hold_after == datetime(2026, 8, 5, 0, 0, 0, tzinfo=timezone.utc), (
            "hold_expires_at resets to the amend-time clock plus 72 hours"
        )

    def test_reconfirm_after_amend_freezes_new_quote(self, api):
        """PRD §3.4: "Success moves the reservation `HELD` → `CONFIRMED` and **freezes**
        `quoted_charge_cents`; it is no longer recomputed except via amendment." and "An
        amended reservation must be re-confirmed before any new pull-list submission can draw
        on it."

        Design: Difficulty/non_linear_state_machine/reservation_amend_requote_cycle
        """
        ctx = self._confirmed_long_run_reservation(api)
        reservation = ctx["reservation"]
        renter = ctx["renter"]

        set_logical_clock(api, "2026-08-02T00:00:00Z")
        amended = validate_success(
            api.amend_reservation(
                reservation["id"], {"quantity": 2},
                make_renter_contact_headers(renter["id"]),
            )
        )
        assert amended["status"] == "HELD"

        reconfirmed = validate_success(
            api.confirm_reservation(
                reservation["id"], make_renter_contact_headers(renter["id"]),
            )
        )
        assert reconfirmed["status"] == "CONFIRMED"
        assert reconfirmed["quoted_charge_cents"] == 16000, (
            "the re-confirmed reservation freezes the recomputed 16000 quote"
        )


class TestConfirmRequiresConfirmedProduction:
    def test_confirm_on_draft_production_rejected(self, api):
        """PRD §3.4: "Confirmation of a hold, by the `RenterContact`, re-validates but does
        not recompute the quote: the production must be `CONFIRMED` (`ERR_INVALID_STATE`)".

        Design: Difficulty/cross_entity_state_dependency/reservation_confirm_requires_confirmed_production
        """
        publish_rate_card(api)
        item = create_catalog_item(api, name="Tailcoat")
        acquire_unit(api, item["id"], barcode=f"BC-{uuid_tag()}")
        renter = create_active_renter(api, name="Renter R")["renter"]
        production = create_production_draft(api, renter, closing_date="2026-10-26")
        reservation = place_reservation(api, production["id"], renter, item["id"])
        assert reservation["status"] == "HELD"

        resp = api.confirm_reservation(
            reservation["id"], make_renter_contact_headers(renter["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        assert get_reservation(api, reservation["id"])["status"] == "HELD"

    def test_confirm_succeeds_once_production_confirmed(self, api):
        """PRD §3.4: "the production must be `CONFIRMED` (`ERR_INVALID_STATE`)" and "Success
        moves the reservation `HELD` → `CONFIRMED` and **freezes** `quoted_charge_cents`;
        it is no longer recomputed except via amendment." and "Confirmation of a hold, by
        the `RenterContact`, re-validates but does not recompute the quote".

        Design: Difficulty/cross_entity_state_dependency/reservation_confirm_requires_confirmed_production
        """
        publish_rate_card(api)
        item = create_catalog_item(api, name="Tailcoat")
        acquire_unit(api, item["id"], barcode=f"BC-{uuid_tag()}")
        renter = create_active_renter(api, name="Renter R")["renter"]
        production = create_production_draft(api, renter, closing_date="2026-10-26")
        reservation = place_reservation(api, production["id"], renter, item["id"])
        # Placed while the production is DRAFT, so no rate card is pinned yet
        # (PRD §3.3 pins it at confirmation): the 10-day window prices WEEKLY,
        # 1 * 5000 * ceil(10/7) = 10000.
        assert reservation["quoted_charge_cents"] == 10000

        confirm_production(api, production, renter)
        confirmed = validate_success(
            api.confirm_reservation(
                reservation["id"], make_renter_contact_headers(renter["id"]),
            )
        )
        assert confirmed["status"] == "CONFIRMED"
        # Confirmation re-validates but does NOT recompute the quote (PRD §3.4):
        # the WEEKLY 10000 quoted under the DRAFT production is frozen as-is.
        assert confirmed["quoted_charge_cents"] == 10000


class TestAggregateWindowCapacity:
    def _setup_two_unit_capacity(self, api):
        """R1 qty 2 Sep 1-10 CONFIRMED consumes the whole 2-unit pool for those days."""
        publish_rate_card(api)
        item = create_catalog_item(api, name="Tailcoat")
        acquire_unit(api, item["id"], barcode=f"BC-{uuid_tag()}-1")
        acquire_unit(api, item["id"], barcode=f"BC-{uuid_tag()}-2")
        renter = create_active_renter(api, name="Renter R")["renter"]
        production = create_confirmed_production(api, renter, closing_date="2026-10-26")
        r1 = place_reservation(api, production["id"], renter, item["id"], quantity=2,
                               window_start_date="2026-09-01", window_end_date="2026-09-10")
        r1 = confirm_reservation(api, r1, renter)
        assert r1["status"] == "CONFIRMED"
        return item, renter, production

    def test_boundary_day_overlap_rejected(self, api):
        """PRD §3.4: "Window overlap uses **inclusive** date intervals: a window overlaps
        another when its start is on or before the other's end and the other's start is on or
        before its end. Consequently two windows sharing a boundary day (one's end equal to
        the other's start) do overlap, while windows separated by even one day do not." and
        "The request is valid only if the requested `quantity` is no more than the remainder;
        otherwise it fails with `ERR_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/aggregate_window_capacity_inclusive_overlap
        """
        item, renter, production = self._setup_two_unit_capacity(api)
        # Sep 10-15 shares boundary day Sep 10 with the CONFIRMED qty-2 hold.
        resp = api.create_reservation(
            create_reservation_payload(
                production_id=production["id"], item_id=item["id"], quantity=1,
                window_start_date="2026-09-10", window_end_date="2026-09-15",
                expected_production_version=get_production(api, production["id"])["version"],
            ),
            make_renter_contact_headers(renter["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED, 409)

    def test_adjacent_window_accepted(self, api):
        """PRD §3.4: "Consequently two windows sharing a boundary day (one's end equal to the
        other's start) do overlap, while windows separated by even one day do not."

        Design: Difficulty/resource_temporal_overlap/aggregate_window_capacity_inclusive_overlap
        """
        item, renter, production = self._setup_two_unit_capacity(api)
        # Sep 11-15 starts the day AFTER the hold's end — no overlap, fits the pool.
        r3 = place_reservation(api, production["id"], renter, item["id"], quantity=1,
                               window_start_date="2026-09-11", window_end_date="2026-09-15")
        assert_reservation(r3)
        assert r3["status"] == "HELD"
