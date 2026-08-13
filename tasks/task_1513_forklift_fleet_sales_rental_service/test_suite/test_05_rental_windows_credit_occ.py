"""Rental reservation windows, credit gates, OCC on unit version, listing,
and immediate consistency of side effects."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_customer_credit_invariant,
    get_customer,
    get_rental_contract,
    get_unit,
    make_customer,
    make_rental_contract,
    make_unit,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRentalWindowAdjacency:
    def test_adjacent_window_allowed(self, api, rental_coordinator_headers):
        """PRD §3.3: "the requested window must not intersect any other
        contract on the same unit whose status is `RESERVED` or `ON_RENT` —
        because windows are half-open, pure adjacency (one contract's end
        equaling another's start) is allowed".

        Design: Difficulty/resource_temporal_overlap/rental_window_halfopen_adjacency
        """
        customer = make_customer(name="Window Co")
        unit = make_unit(serial_number="SN-TO1")
        first = make_rental_contract(customer["id"], unit["id"],
                                     start_date="2026-08-01",
                                     end_date="2026-08-10")
        assert first["status"] == "RESERVED"
        # start 08-10 == first contract's end 08-10: pure adjacency
        second = make_rental_contract(customer["id"], unit["id"],
                                      start_date="2026-08-10",
                                      end_date="2026-08-20")
        assert second["status"] == "RESERVED", \
            "back-to-back (adjacent) windows must be allowed"

    def test_interior_overlap_rejected(self, api, rental_coordinator_headers):
        """PRD §3.3: "the requested window must not intersect any other
        contract on the same unit whose status is `RESERVED` or `ON_RENT` —
        because windows are half-open, pure adjacency (one contract's end
        equaling another's start) is allowed, and `CANCELLED` or `RETURNED`
        contracts never block — else `ERR_RENTAL_WINDOW_OVERLAP`" (PRD §5:
        HTTP 409). A window starting inside an existing contract's window
        crosses its interior.

        Design: Difficulty/resource_temporal_overlap/rental_window_halfopen_adjacency
        """
        customer = make_customer(name="Window Co")
        unit = make_unit(serial_number="SN-TO1X")
        make_rental_contract(customer["id"], unit["id"],
                             start_date="2026-08-01", end_date="2026-08-10")
        make_rental_contract(customer["id"], unit["id"],
                             start_date="2026-08-10", end_date="2026-08-20")
        unit_now = get_unit(unit["id"])
        resp = api.create_rental_contract(
            {"unit_id": unit["id"], "customer_id": customer["id"],
             "start_date": "2026-08-15", "end_date": "2026-08-25",
             "expected_unit_version": unit_now["version"]},
            rental_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_RENTAL_WINDOW_OVERLAP, 409)

    def test_cancelled_window_frees_overlap(self, api,
                                            rental_coordinator_headers):
        """PRD §3.3: "`CANCELLED` or `RETURNED` contracts never block" — after
        cancelling the first reservation, a new contract over its exact window
        succeeds.

        Design: Corner/validations/cancelled_window_frees_overlap
        """
        customer = make_customer(name="Free Co")
        unit = make_unit(serial_number="SN-V8")
        first = make_rental_contract(customer["id"], unit["id"],
                                     start_date="2026-08-01",
                                     end_date="2026-08-10")
        validate_success(api.cancel_rental_contract(first["id"],
                                                    rental_coordinator_headers))
        assert get_rental_contract(first["id"])["status"] == "CANCELLED"
        second = make_rental_contract(customer["id"], unit["id"],
                                      start_date="2026-08-01",
                                      end_date="2026-08-10")
        assert second["status"] == "RESERVED", \
            "a CANCELLED contract's window must not block a new reservation"


class TestCreditHoldInvariant:
    def test_reserve_places_exact_hold(self, api):
        """PRD §3.3: "The resulting `provisional_estimate_cents` is placed on
        the customer as a credit hold: `credit_holds_cents` increases by
        exactly that amount." PRD §2.10: "`available_credit_cents` is derived
        as `credit_limit_cents` minus `outstanding_balance_cents` minus
        `credit_holds_cents`". A 10-day WEEKLY reservation holds 140000, leaving
        9860000 of 10000000 available.

        Design: Difficulty/compensating_invariant/rental_hold_cancel_credit_invariant
        """
        customer = make_customer(name="Invariant Co")
        unit = make_unit(serial_number="SN-CI1")
        contract = make_rental_contract(customer["id"], unit["id"],
                                        start_date="2026-08-01",
                                        end_date="2026-08-11")
        assert contract["provisional_estimate_cents"] == 140000
        data = get_customer(customer["id"])
        assert data["credit_holds_cents"] == 140000
        assert data["available_credit_cents"] == 9860000
        assert_customer_credit_invariant(data)

    def test_cancel_restores_credit_exactly(self, api, rental_coordinator_headers):
        """PRD §3.3: "Cancellation moves a `RESERVED` contract to `CANCELLED`
        and releases its provisional hold from `credit_holds_cents`." After the
        compensating cancel, available credit returns exactly to its
        pre-reserve value with no drift.

        Design: Difficulty/compensating_invariant/rental_hold_cancel_credit_invariant
        """
        customer = make_customer(name="Invariant Co")
        unit = make_unit(serial_number="SN-CI1B")
        contract = make_rental_contract(customer["id"], unit["id"],
                                        start_date="2026-08-01",
                                        end_date="2026-08-11")
        validate_success(api.cancel_rental_contract(contract["id"],
                                                    rental_coordinator_headers))
        data = get_customer(customer["id"])
        assert data["credit_holds_cents"] == 0
        assert data["outstanding_balance_cents"] == 0
        assert data["available_credit_cents"] == 10000000
        assert_customer_credit_invariant(data)


class TestCreditAndDispositionGates:
    def test_rental_create_over_credit_limit_rejected(
            self, api, rental_coordinator_headers):
        """PRD §3.3: "the provisional estimate must fit within
        `available_credit_cents`, else `ERR_CREDIT_LIMIT_EXCEEDED`" — a
        40-day MONTHLY reservation at 10% discount estimates 378000 against
        100000 available, so no hold is placed.

        Design: Corner/validations/rental_create_over_credit_limit_rejected
        """
        customer = make_customer(name="Broke Co", credit_limit_cents=100000,
                                 discount_pct=0.10)
        unit = make_unit(serial_number="SN-V6")
        resp = api.create_rental_contract(
            {"unit_id": unit["id"], "customer_id": customer["id"],
             "start_date": "2026-08-01", "end_date": "2026-09-10",
             "expected_unit_version": unit["version"]},
            rental_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED, 422)
        assert get_customer(customer["id"])["credit_holds_cents"] == 0

    def test_rental_create_wrong_disposition_rejected(self, api,
                                                      rental_coordinator_headers):
        """PRD §3.3: "the unit's `disposition` must be `RENTAL_FLEET`, else
        `ERR_UNIT_DISPOSITION_MISMATCH`".

        Design: Corner/validations/rental_create_wrong_disposition_rejected
        """
        customer = make_customer(name="Disp Co")
        unit = make_unit(serial_number="SN-V7", disposition="NEW_SALE")
        resp = api.create_rental_contract(
            {"unit_id": unit["id"], "customer_id": customer["id"],
             "start_date": "2026-08-01", "end_date": "2026-08-03",
             "expected_unit_version": unit["version"]},
            rental_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_UNIT_DISPOSITION_MISMATCH, 422)

    def test_rental_unknown_unit_returns_not_found(self, api,
                                                   rental_coordinator_headers):
        """PRD §2.5: "Only after every path identifier has been resolved does
        the system verify resources referenced in the request body —
        identifiers such as `unit_id`, `customer_id`, `technician_id`, or
        `operator_id` — each of which likewise yields `ERR_NOT_FOUND` when it
        does not resolve to an existing resource."

        Design: Corner/validations/rental_unknown_unit_returns_not_found
        """
        customer = make_customer(name="Ghost Co")
        unit = make_unit(serial_number="SN-V2B")
        resp = api.create_rental_contract(
            {"unit_id": NON_EXISTENT_UUID, "customer_id": customer["id"],
             "start_date": "2026-08-01", "end_date": "2026-08-03",
             "expected_unit_version": unit["version"]},
            rental_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_rental_end_before_start_rejected(self, api,
                                              rental_coordinator_headers):
        """PRD §3.3: a reservation supplies "an `end_date` strictly later than
        the start"; PRD §2.6 rejects request-body shape violations with
        `ERR_INVALID_REQUEST` (PRD §5: HTTP 400) before any business check.

        Design: Corner/validations/rental_end_before_start_rejected
        """
        customer = make_customer(name="Shape Co")
        unit = make_unit(serial_number="SN-V2")
        resp = api.create_rental_contract(
            {"unit_id": unit["id"], "customer_id": customer["id"],
             "start_date": "2026-08-10", "end_date": "2026-08-01",
             "expected_unit_version": unit["version"]},
            rental_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestOptimisticConcurrency:
    def test_stale_unit_version_rejected(self, api, rental_coordinator_headers):
        """PRD §2.8: "If the unit's current `version` has advanced beyond that
        value — because an earlier reservation, return, or other mutation
        touched it — the create is rejected with `ERR_STALE_VERSION`
        (HTTP 412)".

        Design: Corner/complexity_layers/cl_occ_stale_version_rejected
        """
        customer = make_customer(name="OCC Co")
        unit = make_unit(serial_number="SN-OCC1")
        assert unit["version"] == 1
        make_rental_contract(customer["id"], unit["id"],
                             start_date="2026-08-01", end_date="2026-08-05")
        # unit.version is now 2; replaying the stale version 1 must fail even
        # though the September window itself is valid.
        resp = api.create_rental_contract(
            {"unit_id": unit["id"], "customer_id": customer["id"],
             "start_date": "2026-09-01", "end_date": "2026-09-05",
             "expected_unit_version": 1},
            rental_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        data, meta = validate_paginated(api.list_rental_contracts(
            rental_coordinator_headers, params={"unit_id": unit["id"]}))
        assert meta["total_count"] == 1, "stale create must not persist"

    def test_version_increments_on_mutation(self, api):
        """PRD §2.4: "`version` (integer): starts at 1 when the resource is
        created and increments by exactly 1 on every mutation"; PRD §2.8:
        "Rental-contract creation itself increments the unit's `version` by 1
        as a side effect."

        Design: Corner/complexity_layers/cl_version_increments_on_mutation
        """
        customer = make_customer(name="Ver Co")
        unit = make_unit(serial_number="SN-OCC2")
        assert unit["version"] == 1
        make_rental_contract(customer["id"], unit["id"],
                             start_date="2026-08-01", end_date="2026-08-03")
        assert get_unit(unit["id"])["version"] == 2


class TestListingAndConsistency:
    def test_rental_list_pagination_envelope(self, api,
                                             rental_coordinator_headers):
        """PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope"
        and "the rental-contract and lease-contract lists filter by `unit_id`,
        `customer_id`, or `status`".

        Design: Corner/entities/rental_list_pagination_envelope
        """
        customer = make_customer(name="Page Co")
        unit1 = make_unit(serial_number="SN-PG1")
        unit2 = make_unit(serial_number="SN-PG2")
        make_rental_contract(customer["id"], unit1["id"],
                             start_date="2026-08-01", end_date="2026-08-03")
        make_rental_contract(customer["id"], unit2["id"],
                             start_date="2026-08-01", end_date="2026-08-03")
        resp = api.list_rental_contracts(
            rental_coordinator_headers,
            params={"customer_id": customer["id"], "limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        assert meta["offset"] == 0

    def test_immediate_visibility_of_side_effects(self, api):
        """PRD §3.3: "The resulting `provisional_estimate_cents` is placed on
        the customer as a credit hold: `credit_holds_cents` increases by
        exactly that amount" — visible on the very next read (a 2-day DAILY
        reservation at 15000/day holds 30000).

        Design: Corner/consistency_model/immediate_visibility_of_side_effects
        """
        customer = make_customer(name="Imm Co")
        unit = make_unit(serial_number="SN-IM1")
        contract = make_rental_contract(customer["id"], unit["id"],
                                        start_date="2026-08-01",
                                        end_date="2026-08-03")
        assert contract["provisional_estimate_cents"] == 30000
        data = get_customer(customer["id"])
        assert data["credit_holds_cents"] == 30000
        assert data["available_credit_cents"] == 9970000
        assert_customer_credit_invariant(data)
