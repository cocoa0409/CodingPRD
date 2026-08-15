"""Manifest, boarding, and the voyage: cross-entity gating, amendment cycle,
check-in sweeps, and completion cascades (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_passenger,
    assign_confirmed_bartender,
    create_booking,
    create_customer,
    create_paid_booking,
    create_placed_provision_order,
    freeze_manifest,
    get_booking,
    get_cruise,
    get_manifest,
    open_boarding,
    pay_booking,
    setup_inventory,
    validate_error,
    validate_success,
)

OM = TEST_USERS["ops_manager_headers"]
CAPTAIN = TEST_USERS["captain_headers"]
ATTENDANT = TEST_USERS["dock_attendant_headers"]


class TestOpenBoardingGatedOnManifest:
    def test_open_boarding_requires_frozen_manifest(self, api):
        """PRD §3.6: "Opening requires the cruise to stand at `SCHEDULED`
        (otherwise `ERR_INVALID_STATE`), requires the manifest to exist and stand
        at `FROZEN` (otherwise `ERR_MANIFEST_NOT_FROZEN`), and requires
        `reserved_covers` to sit within the vessel's `coast_guard_capacity`
        (otherwise `ERR_CAPACITY_EXCEEDED`)."

        Design: Difficulty/cross_entity_state_dependency/cruise_boarding_gated_on_manifest_frozen
        """
        inv = setup_inventory()
        cruise = inv["cruise"]
        customer = create_customer("a@example.com", "A")
        create_paid_booking(cruise["id"], customer["id"], 1, cruise["version"])

        # Manifest still DRAFT: rejected.
        resp = api.open_boarding(cruise["id"], OM)
        validate_error(resp, ApiErrorId.ERR_MANIFEST_NOT_FROZEN)

        freeze_manifest(cruise["id"])
        opened = open_boarding(cruise["id"])
        assert opened["status"] == "BOARDING", (
            f"After freeze, open-boarding must move the cruise to BOARDING, got "
            f"{opened['status']}"
        )

    def test_manifest_freeze_capacity_gate_and_reopen(self, api):
        """PRD §3.6: "Freezing requires the manifest to stand at `DRAFT`
        (otherwise `ERR_INVALID_STATE`) and requires the current
        `passenger_count` not to exceed the snapshot `coast_guard_capacity`
        (otherwise `ERR_CAPACITY_EXCEEDED`); at freeze time the passenger count
        is snapshotted."
        PRD §3.6: "Opening requires the cruise to stand at `SCHEDULED`
        (otherwise `ERR_INVALID_STATE`), requires the manifest to exist and stand
        at `FROZEN` (otherwise `ERR_MANIFEST_NOT_FROZEN`), and requires
        `reserved_covers` to sit within the vessel's `coast_guard_capacity`
        (otherwise `ERR_CAPACITY_EXCEEDED`)."

        Design: Difficulty/cross_entity_state_dependency/cruise_boarding_gated_on_manifest_frozen
        """
        inv = setup_inventory(vessel_capacity=100)
        cruise = inv["cruise"]
        customer = create_customer("m@example.com", "M")
        create_paid_booking(cruise["id"], customer["id"], 1, cruise["version"])
        # The DRAFT manifest is a hard gate; freezing lifts it deterministically.
        validate_error(api.open_boarding(cruise["id"], OM),
                       ApiErrorId.ERR_MANIFEST_NOT_FROZEN)
        frozen = freeze_manifest(cruise["id"])
        assert frozen["status"] == "FROZEN"
        assert get_manifest(cruise["id"])["status"] == "FROZEN"
        opened = open_boarding(cruise["id"])
        assert opened["status"] == "BOARDING"

    def test_open_boarding_twice_rejected_by_state(self, api):
        """PRD §3.6: "Opening requires the cruise to stand at `SCHEDULED`
        (otherwise `ERR_INVALID_STATE`)"
        PRD §2.8: "When a request is well-formed and an endpoint enforces several
        of the following rules, the system evaluates them in this fixed order,
        and the first failure determines the error returned"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_capacity_conflict
        """
        # Capacity filled exactly (reserved_covers == coast_guard_capacity == 2).
        inv = setup_inventory(vessel_capacity=2)
        cruise = inv["cruise"]
        cust_a = create_customer("a@example.com", "A")
        create_paid_booking(cruise["id"], cust_a["id"], 1, cruise["version"])
        version2 = get_cruise(cruise["id"])["version"]
        cust_b = create_customer("b@example.com", "B")
        create_paid_booking(cruise["id"], cust_b["id"], 1, version2)
        freeze_manifest(cruise["id"])
        open_boarding(cruise["id"])

        # Second open-boarding: cruise already BOARDING — the rung-4 state check
        # fires before any business rule.
        resp = api.open_boarding(cruise["id"], OM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_double_open_boarding_state_error_is_stable(self, api):
        """PRD §2.8: "4. Target entity state permits the requested transition —
        `ERR_INVALID_STATE` (409)."
        PRD §3.6: "With a frozen manifest in hand, an `OperationsManager` opens
        boarding, moving the cruise from `SCHEDULED` to `BOARDING`. Opening
        requires the cruise to stand at `SCHEDULED` (otherwise
        `ERR_INVALID_STATE`)"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_capacity_conflict
        """
        # Second scenario for the same pair: the state failure is reproducible
        # on a fresh cruise that has already left SCHEDULED, independent of any
        # business condition.
        inv = setup_inventory(vessel_capacity=2)
        cruise = inv["cruise"]
        freeze_manifest(cruise["id"])
        open_boarding(cruise["id"])
        assert get_cruise(cruise["id"])["status"] == "BOARDING"
        resp = api.open_boarding(cruise["id"], OM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_cruise(cruise["id"])["status"] == "BOARDING", (
            "A rejected re-open must leave the cruise in BOARDING"
        )


class TestManifestLifecycle:
    def test_amend_cycle_allows_refreeze(self, api):
        """PRD §3.6: "the `Captain` may amend the manifest, returning it from
        `FROZEN` to `DRAFT` — permitted only while the cruise itself is still
        `SCHEDULED`, otherwise `ERR_INVALID_STATE` — and this `DRAFT` → `FROZEN`
        → `DRAFT` amendment cycle may repeat."

        Design: Corner/state_machines/manifest_amend_cycle_allows_refreeze
        """
        inv = setup_inventory()
        cruise = inv["cruise"]
        customer = create_customer("a@example.com", "A")
        create_paid_booking(cruise["id"], customer["id"], 1, cruise["version"])

        frozen = freeze_manifest(cruise["id"])
        assert frozen["status"] == "FROZEN"
        amended = validate_success(api.amend_manifest(cruise["id"], CAPTAIN))
        assert amended["status"] == "DRAFT"
        refrozen = freeze_manifest(cruise["id"])
        assert refrozen["status"] == "FROZEN", (
            f"The amendment cycle must permit a second freeze, got "
            f"{refrozen['status']}"
        )

    def test_manifest_auto_created_with_capacity_snapshot(self, api):
        """PRD §3.2: "Scheduling also auto-creates the cruise's
        **BoardingManifest** in `DRAFT` status, carrying a snapshot of the
        vessel's `coast_guard_capacity` taken at manifest creation; exactly one
        manifest ever exists per cruise."
        PRD §3.6: "Reading the manifest yields a collection of zero or one
        element."

        Design: Corner/entities/nested_child_visible_through_parent_subresource
        """
        inv = setup_inventory(vessel_capacity=100)
        data = validate_success(api.get_cruise_manifest(inv["cruise"]["id"],
                                                        CAPTAIN))
        assert isinstance(data, list) and len(data) == 1, (
            f"Expected a 0-or-1-element manifest collection with one entry, got "
            f"{data!r}"
        )
        manifest = data[0]
        assert manifest["status"] == "DRAFT"
        assert manifest["coast_guard_capacity"] == 100


class TestDepartAndNoShowSweep:
    def test_depart_from_scheduled_invalid(self, api):
        """PRD §3.6: "Departure requires the `BOARDING` state (otherwise
        `ERR_INVALID_STATE`), requires `boarded_count` within certified capacity
        (otherwise `ERR_CAPACITY_EXCEEDED`), and requires the manifest to stand
        at `FROZEN` (otherwise `ERR_MANIFEST_NOT_FROZEN`)."

        Design: Corner/state_machines/depart_from_scheduled_invalid
        """
        inv = setup_inventory()
        resp = api.depart_cruise(inv["cruise"]["id"], CAPTAIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_depart_sweeps_unboarded_confirmed_bookings_to_no_show(self, api):
        """PRD §3.6: "Departure strands no-shows: every booking standing at
        `PAID` and `CONFIRMED` whose passengers all remain unboarded moves to
        `NO_SHOW`."
        PRD §3.6: "When every passenger of a `CONFIRMED` booking has boarded,
        that booking advances automatically from `CONFIRMED` to `BOARDED`,
        recomputing `boarded_count` again and refreshing the manifest's
        `passenger_count` if the manifest is still in `DRAFT`."

        Design: Corner/state_machines/depart_no_show_sweep_side_effect
        """
        inv = setup_inventory()
        cruise = inv["cruise"]
        customer = create_customer("a@example.com", "A")
        bk_a = create_booking(cruise["id"], customer["id"], 1, cruise["version"])
        p1 = add_passenger(bk_a["id"], customer["id"], "P1", "1990-01-01")
        pay_booking(bk_a["id"], customer["id"])
        version2 = get_cruise(cruise["id"])["version"]
        bk_b = create_booking(cruise["id"], customer["id"], 1, version2)
        pay_booking(bk_b["id"], customer["id"])

        freeze_manifest(cruise["id"])
        open_boarding(cruise["id"])
        resp = api.check_in_passenger(bk_a["id"], p1["id"], ATTENDANT)
        validate_success(resp)

        departed = validate_success(api.depart_cruise(cruise["id"], CAPTAIN))
        assert departed["status"] == "UNDERWAY"
        assert get_booking(bk_a["id"])["booking_status"] == "BOARDED"
        assert get_booking(bk_b["id"])["booking_status"] == "NO_SHOW", (
            "The unboarded PAID+CONFIRMED booking must be swept to NO_SHOW"
        )
        assert get_cruise(cruise["id"])["boarded_count"] == 1


class TestGalleyCoversVariantDivergence:
    def _setup_placed_order_cruise(self, api):
        """Cruise: booking A party4 PAID, booking B party2 left PENDING; order
        placed (provisional 6); A's 4 passengers check in; 1 CONFIRMED crew;
        cruise departs. Returns context."""
        inv = setup_inventory()
        cruise = inv["cruise"]
        cust_a = create_customer("a@example.com", "A")
        bk_a = create_paid_booking(cruise["id"], cust_a["id"], 4,
                                   cruise["version"])
        version2 = get_cruise(cruise["id"])["version"]
        cust_b = create_customer("b@example.com", "B")
        bk_b = create_booking(cruise["id"], cust_b["id"], 2, version2)

        order = create_placed_provision_order(cruise["id"])
        crew = assign_confirmed_bartender(cruise["id"])

        passengers = [
            add_passenger(bk_a["id"], cust_a["id"], f"P{i+1}",
                          f"1990-01-0{i+1}")
            for i in range(4)
        ]
        freeze_manifest(cruise["id"])
        open_boarding(cruise["id"])
        for p in passengers:
            validate_success(api.check_in_passenger(bk_a["id"], p["id"],
                                                    ATTENDANT))
        validate_success(api.depart_cruise(cruise["id"], CAPTAIN))
        return {**inv, "cust_a": cust_a, "bk_a": bk_a, "bk_b": bk_b,
                "order": order, "crew": crew}

    def test_provisional_forward_looking_vs_final_chronological(self, api):
        """PRD §3.5: "at creation the server computes the forward-looking
        `provisional_covers` — the sum of `party_size` over the cruise's bookings
        whose `booking_status` is `RESERVED` or `CONFIRMED` and whose
        `payment_status` is `PENDING` or `PAID`"
        PRD §3.5: "its `final_covers` is computed on the chronological variant:
        the count of the cruise's booking passengers with a non-null
        `boarded_at`, plus the count of the cruise's staff assignments standing
        at `CONFIRMED` — crew meals are provisioned in the settlement, not the
        forecast."

        Design: Difficulty/dual_variant_calc/galley_covers_forward_vs_chronological_diverge
        """
        ctx = self._setup_placed_order_cruise(api)
        cruise_id = ctx["cruise"]["id"]
        completed = validate_success(api.complete_cruise(cruise_id, CAPTAIN))
        assert completed["status"] == "COMPLETED"

        orders = validate_success(
            api.list_provision_orders(cruise_id, TEST_USERS["galley_manager_headers"]))
        order = next(o for o in orders if o["id"] == ctx["order"]["id"])
        # Forward-looking: 4 PAID + 2 PENDING = 6.
        assert order["provisional_covers"] == 6, (
            f"provisional_covers must be 6 (4 PAID + 2 PENDING), got "
            f"{order['provisional_covers']}"
        )
        # Chronological: 4 boarded + 1 CONFIRMED crew = 5.
        assert order["final_covers"] == 5, (
            f"final_covers must be 5 (4 boarded + 1 crew), got "
            f"{order['final_covers']}"
        )
        assert order["status"] == "SETTLED"
        # The never-paid booking is untouched by the depart NO_SHOW sweep.
        assert get_booking(ctx["bk_b"]["id"])["booking_status"] == "RESERVED"
        assert get_booking(ctx["bk_a"]["id"])["booking_status"] == "BOARDED"

    def test_divergence_proves_variants_not_aliases(self, api):
        """PRD §3.5: "The two cover counts legitimately disagree whenever
        reservations diverge from boarded reality; no-shows consume forecast
        covers but not final ones, and confirmed crew appear only in the final."

        Design: Difficulty/dual_variant_calc/galley_covers_forward_vs_chronological_diverge
        """
        ctx = self._setup_placed_order_cruise(api)
        cruise_id = ctx["cruise"]["id"]
        validate_success(api.complete_cruise(cruise_id, CAPTAIN))
        orders = validate_success(
            api.list_provision_orders(cruise_id, TEST_USERS["galley_manager_headers"]))
        order = next(o for o in orders if o["id"] == ctx["order"]["id"])
        assert order["provisional_covers"] != order["final_covers"], (
            "The forward-looking and chronological variants must disagree here: "
            "the PENDING booking inflates only the forecast and the CONFIRMED "
            "crew member appears only in the settlement"
        )
        assert order["provisional_covers"] == 6
        assert order["final_covers"] == 5
