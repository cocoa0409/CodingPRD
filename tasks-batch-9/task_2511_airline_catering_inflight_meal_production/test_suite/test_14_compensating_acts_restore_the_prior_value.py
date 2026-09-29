"""Every undo in the service is exact: the aggregate returns to the value it held before."""

from test_helpers import (
    CLOCK_CART,
    CLOCK_SETUP,
    COMPLIANCE,
    LM_ALICE,
    SEAL_PRIMARY,
    SUPERVISOR,
    ApiErrorId,
    assert_instant_equals,
    assert_total_count,
    cabin_cost_per_pax_cents,
    factories as f,
    finding_penalty_cents,
    ingest_flight,
    item_gross_cents,
    load_item,
    make_airline_rep_headers,
    raise_finding,
    raise_waste_manifest,
    read_cart,
    read_flight,
    register_airline,
    register_cart,
    resolve_finding,
    set_clock,
    sign_off_build,
    transition_waste_manifest,
    validate_error,
    validate_paginated,
    validate_success,
)

WASTE_SEAL = "WST-AN411-01"
SB_STD_UTC = "2026-09-20T10:00:00Z"
SB_SERVICE_DATE = "2026-09-20"
REJECTION_REASON = "bonded seal tampered in transit"


def _read_item(api, cart_item_id):
    return validate_success(api.get_cart_item(cart_item_id, LM_ALICE), 200)


def _aggregates(api, cart_id, flight_id):
    """The observable triple: the cart's units, the flight's units, and the flight's cost."""
    cart = read_cart(api, cart_id)
    flight = read_flight(api, flight_id)
    return (
        cart["loaded_units"],
        flight["units_loaded"],
        flight["cost_per_pax_cents"],
    )


def _void(api, cart_id, cart_item_id):
    return validate_success(api.void_cart_item(cart_id, cart_item_id, LM_ALICE), 200)


def _sunbridge_finding(api, finding_type="SEAL_MISMATCH", severity="MAJOR"):
    """A `DOMESTIC` airline with one flight and one manually raised finding against it."""
    set_clock(api, CLOCK_SETUP)
    airline = register_airline(
        api,
        name="Sunbridge Airways",
        iata_code="SB",
        waste_regime="DOMESTIC",
        cost_cap_per_pax_cents=6000,
    )
    flight = ingest_flight(
        api,
        airline["id"],
        flight_number="SB901",
        service_date=SB_SERVICE_DATE,
        std_utc=SB_STD_UTC,
        tail_number="SE-CCC",
        pax_economy=100,
    )
    finding = raise_finding(
        api,
        airline["id"],
        flight["id"],
        finding_type,
        severity,
        evidence_ref="AUD-W1",
    )
    return airline, flight, finding


def _read_airline(api, airline_id):
    return validate_success(api.get_airline(airline_id, COMPLIANCE), 200)


class TestVoidingRestoresEveryLoadedAggregate:
    """One item voided, and two items voided one at a time."""

    def test_voiding_the_only_item_returns_the_triple_to_its_pre_load_value(
        self, released_env
    ):
        """Zero, then a hundred and eighty, then zero again, on all three counters at once.

        PRD §3.6: "The row is never physically deleted: the item moves `ACTIVE → VOID` with `voided_at` set to the logical clock, so the load history survives for audit."

        PRD §3.6: "The cart's `loaded_units` and the flight's `units_loaded`, `unit_balance` and `cost_per_pax_cents` are all recomputed, and the flight's `unit_balance` returns to exactly the value it held before the item was added."

        PRD §3.6: "The owning cart, if `BUILT`, falls back `BUILT → BUILDING`, and its seal axis moves from `SEALED` or `RESEALED` to `BROKEN` on the same row — the break clears `sealed_by_user_id` but deliberately leaves `seal_number` in place for audit."

        Design: Difficulty/compensating_invariant/voiding_a_cart_item_restores_every_loaded_unit_and_cost_aggregate
        """
        env = released_env
        api = env.api
        set_clock(api, CLOCK_CART)
        cart = register_cart(api, env.flight_id)
        assert cart["capacity_units"] == 200
        before = _aggregates(api, cart["id"], env.flight_id)
        assert before == (0, 0, 0)
        assert read_flight(api, env.flight_id)["unit_balance"] == 180

        item = load_item(api, cart["id"], env.batch["id"], 180)
        built = sign_off_build(api, cart["id"])
        assert built["build_status"] == "BUILT"
        during = _aggregates(api, cart["id"], env.flight_id)
        assert during == (180, 180, 1624)
        assert during[2] == cabin_cost_per_pax_cents(item_gross_cents(180, 1450), 180)
        assert read_flight(api, env.flight_id)["unit_balance"] == 0

        voided = _void(api, cart["id"], item["id"])
        assert voided["status"] == "VOID"
        after = _aggregates(api, cart["id"], env.flight_id)
        assert after == before == (0, 0, 0)
        assert read_flight(api, env.flight_id)["unit_balance"] == 180

        # The row survives, quantity intact, stamped at the instant of the void.
        stored = _read_item(api, item["id"])
        assert stored["status"] == "VOID"
        assert stored["qty_units"] == 180
        assert_instant_equals(stored["voided_at"], CLOCK_CART)

        reverted = read_cart(api, cart["id"])
        assert reverted["build_status"] == "BUILDING"
        assert reverted["loaded_units"] == 0
        # The cart was never sealed, so the break has nothing to act on.
        assert reverted["seal_status"] == "UNSEALED"

        # Production is untouched by the compensating act on the cart.
        batch = validate_success(
            api.get_production_batch(env.batch["id"], SUPERVISOR), 200
        )
        assert batch["production_status"] == "RELEASED"
        assert batch["produced_qty"] == 180
        flight = read_flight(api, env.flight_id)
        assert flight["status"] == "PLANNED"
        assert flight["units_produced"] == 180

    def test_voiding_one_of_two_items_leaves_exactly_the_other_ones_contribution(
        self, released_env
    ):
        """A hundred and eighty in two rows, undone one row at a time.

        PRD §3.6: "Each successful load recomputes the cart's `loaded_units` — the sum of `qty_units` over that cart's `ACTIVE` items — along with the flight's `units_loaded`, `unit_balance` and `cost_per_pax_cents`."

        PRD §3.6: "`VOID` items are excluded from every unit and cost aggregate in the service."

        PRD §4: "Lists cart items, filterable by `cart_id`, `production_batch_id` and `status`; `VOID` items are included only when `status` is supplied."

        Design: Difficulty/compensating_invariant/voiding_a_cart_item_restores_every_loaded_unit_and_cost_aggregate
        """
        env = released_env
        api = env.api
        set_clock(api, CLOCK_CART)
        cart = register_cart(api, env.flight_id)
        bigger = load_item(api, cart["id"], env.batch["id"], 100)
        smaller = load_item(api, cart["id"], env.batch["id"], 80)
        assert _aggregates(api, cart["id"], env.flight_id) == (180, 180, 1624)

        _void(api, cart["id"], bigger["id"])
        # Only the eighty-unit row still contributes.
        partial = _aggregates(api, cart["id"], env.flight_id)
        assert partial == (80, 80, 722)
        assert partial[2] == cabin_cost_per_pax_cents(item_gross_cents(80, 1450), 180)
        assert read_flight(api, env.flight_id)["unit_balance"] == 100

        _void(api, cart["id"], smaller["id"])
        assert _aggregates(api, cart["id"], env.flight_id) == (0, 0, 0)
        assert read_flight(api, env.flight_id)["unit_balance"] == 180

        # Neither row was deleted; both are simply excluded from the aggregates.
        _, active = validate_paginated(
            api.list_cart_items(LM_ALICE, {"cart_id": cart["id"]})
        )
        assert_total_count(active, 0)
        rows, voided = validate_paginated(
            api.list_cart_items(LM_ALICE, {"cart_id": cart["id"], "status": "VOID"})
        )
        assert_total_count(voided, 2)
        assert {row["id"] for row in rows} == {bigger["id"], smaller["id"]}
        assert sorted(row["qty_units"] for row in rows) == [80, 100]
        # The cart never reached `BUILT`, so no fallback edge applies to it.
        assert read_cart(api, cart["id"])["build_status"] == "BUILDING"


class TestWithdrawalRestoresThePenaltyAccrual:
    """An acceptance undone, and a dispute undone, on the same two counters."""

    def test_accepting_then_withdrawing_leaves_the_accrual_exactly_where_it_started(
        self, api
    ):
        """Five hundred thousand cents added, then taken away, without a second decrement.

        PRD §3.10: "**Accepting** is also the `ComplianceOfficer`'s and applies to a finding in `OPEN` or in `DISPUTED`, moving it `OPEN → ACCEPTED` or `DISPUTED → ACCEPTED`, adding the finding's `penalty_cents` to the airline's `penalty_accrued_cents`, and decrementing `open_finding_count` by one only when the prior status was `OPEN` — an accepted dispute has already been decremented and is not decremented twice — which again may drive the airline `SUSPENDED → ACTIVE`."

        PRD §3.10: "Withdrawal subtracts the finding's `penalty_cents` from `penalty_accrued_cents` only when the prior status was `ACCEPTED`, and decrements `open_finding_count` only when the prior status was `OPEN`."

        PRD §3.10: "That asymmetry is what makes withdrawal an exact compensating act: an acceptance followed by a withdrawal leaves `penalty_accrued_cents` at precisely its pre-acceptance value."

        Design: Difficulty/compensating_invariant/withdrawing_an_accepted_finding_restores_the_airline_penalty_accrual
        """
        airline, _flight, finding = _sunbridge_finding(api)
        assert finding["status"] == "OPEN"
        assert finding["source"] == "SYSTEM"
        # 200,000 cents for a seal mismatch at the 2.5 multiplier of `MAJOR`.
        assert finding["penalty_cents"] == 500000 == finding_penalty_cents(
            "SEAL_MISMATCH", "MAJOR"
        )

        opened = _read_airline(api, airline["id"])
        assert opened["open_finding_count"] == 1
        assert opened["penalty_accrued_cents"] == 0
        assert opened["status"] == "ACTIVE"

        accepted = resolve_finding(
            api, finding["id"], "ACCEPT", note="seal register reconciled"
        )
        assert accepted["status"] == "ACCEPTED"
        charged = _read_airline(api, airline["id"])
        assert charged["open_finding_count"] == 0
        assert charged["penalty_accrued_cents"] == 500000

        withdrawn = resolve_finding(
            api,
            finding["id"],
            "WITHDRAW",
            headers=make_airline_rep_headers(airline["id"]),
            note="carrier withdrew the claim",
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["version"] == accepted["version"] + 1

        restored = _read_airline(api, airline["id"])
        assert restored["penalty_accrued_cents"] == 0
        # Not minus one: the decrement is conditional on the prior status.
        assert restored["open_finding_count"] == 0
        assert restored["status"] == "ACTIVE"

    def test_withdrawing_a_disputed_finding_moves_neither_counter(self, api):
        """The dispute already decremented the count, and nothing was ever accrued.

        PRD §3.10: "**Disputing** is the `ComplianceOfficer`'s and applies to a finding in `OPEN`, moving it `OPEN → DISPUTED` and decrementing the airline's `open_finding_count` by one, which may drive the airline `SUSPENDED → ACTIVE`."

        PRD §3.10: "Withdrawal subtracts the finding's `penalty_cents` from `penalty_accrued_cents` only when the prior status was `ACCEPTED`, and decrements `open_finding_count` only when the prior status was `OPEN`."

        PRD §3.10: "Every resolution increments the finding's `version`, and resolving a finding already `WITHDRAWN` is refused with `ERR_INVALID_RESOURCE_STATE`."

        Design: Difficulty/compensating_invariant/withdrawing_an_accepted_finding_restores_the_airline_penalty_accrual
        """
        airline, _flight, finding = _sunbridge_finding(api)
        assert finding["penalty_cents"] == 500000

        disputed = resolve_finding(
            api, finding["id"], "DISPUTE", note="carrier contests the seal register"
        )
        assert disputed["status"] == "DISPUTED"
        contested = _read_airline(api, airline["id"])
        assert contested["open_finding_count"] == 0
        assert contested["penalty_accrued_cents"] == 0

        withdrawn = resolve_finding(
            api,
            finding["id"],
            "WITHDRAW",
            headers=make_airline_rep_headers(airline["id"]),
        )
        assert withdrawn["status"] == "WITHDRAWN"
        after = _read_airline(api, airline["id"])
        # Neither branch of the asymmetry fires from `DISPUTED`.
        assert after["open_finding_count"] == 0
        assert after["penalty_accrued_cents"] == 0
        assert after["status"] == "ACTIVE"

        # `WITHDRAWN` is terminal, so the undo cannot be applied twice.
        validate_error(
            api.resolve_audit_finding(
                finding["id"],
                f.resolution_payload("WITHDRAW"),
                make_airline_rep_headers(airline["id"]),
            ),
            ApiErrorId.ERR_INVALID_RESOURCE_STATE.value,
            409,
        )
        assert (
            validate_success(api.get_audit_finding(finding["id"], COMPLIANCE), 200)[
                "status"
            ]
            == "WITHDRAWN"
        )


class TestAReplacementWasteManifestReproducesTheMass:
    """The rejected manifest gives its seal back, and the mass recomputes identically."""

    def test_the_replacement_reuses_the_released_seal_and_reports_the_same_grams(
        self, dispositioned_env
    ):
        """Seven thousand grams, rejected, then seven thousand grams again under one seal.

        PRD §3.9: "`sealed_weight_grams` is recomputed, never submitted: it is the sum, across the owning record's lines, of each line's `destroy_units` multiplied by that line's specification `gross_weight_grams`."

        PRD §3.9: "Rejecting applies from either `DRAFT` or `SEALED`, moves the manifest to `REJECTED`, requires a `rejection_reason` to be supplied, and releases the `seal_number` for reuse by a replacement manifest; `DISPOSED` and `REJECTED` are both terminal."

        PRD §3.9: "Because `sealed_weight_grams` is recomputed from the same immutable disposition lines, a replacement manifest raised after a rejection reproduces the identical gram figure."

        Design: Difficulty/compensating_invariant/replacing_a_rejected_waste_manifest_reproduces_the_identical_sealed_mass
        """
        env = dispositioned_env
        api = env.api
        assert env.airline["waste_regime"] == "BONDED"
        assert env.specs["Y"]["gross_weight_grams"] == 700
        assert read_cart(api, env.cart["id"])["build_status"] == "LOADED"

        first = raise_waste_manifest(
            api, env.uplift["id"], seal_number=WASTE_SEAL
        )
        assert first["status"] == "DRAFT"
        assert first["regime"] == "BONDED"
        assert first["disposal_method"] == "INCINERATION"
        assert first["rejection_reason"] is None
        # Ten destroyed units at 700 grams of gross tray weight each.
        assert first["sealed_weight_grams"] == 7000 == 10 * 700

        # Raising the manifest is what brings the carts home.
        returned = read_cart(api, env.cart["id"])
        assert returned["build_status"] == "RETURNED"
        assert returned["seal_status"] == "BROKEN"
        assert returned["seal_number"] == SEAL_PRIMARY

        rejected = transition_waste_manifest(
            api, first["id"], "REJECT", rejection_reason=REJECTION_REASON
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == REJECTION_REASON
        assert rejected["version"] == first["version"] + 1

        replacement = raise_waste_manifest(
            api, env.uplift["id"], seal_number=WASTE_SEAL
        )
        assert replacement["id"] != first["id"]
        assert replacement["seal_number"] == WASTE_SEAL
        assert replacement["sealed_weight_grams"] == first["sealed_weight_grams"]
        assert replacement["sealed_weight_grams"] == 7000

        sealed = transition_waste_manifest(api, replacement["id"], "SEAL")
        assert sealed["status"] == "SEALED"
        assert sealed["disposal_method"] == "INCINERATION"

        # Neither manifest reached `DISPOSED`, so the record stays where it was.
        assert env.reload_uplift()["status"] == "DISPOSITIONED"
        batch = validate_success(
            api.get_production_batch(env.batch["id"], SUPERVISOR), 200
        )
        assert batch["production_status"] == "DISPOSED"
        assert env.reload_airline()["open_finding_count"] == 0

    def test_a_seal_held_by_a_cart_or_by_a_draft_manifest_is_refused(
        self, dispositioned_env
    ):
        """The seal is released by the rejection, and not one moment earlier.

        PRD §3.9: "The `seal_number` must be unique across waste manifests and carts alike, or the request is refused with `ERR_SEAL_NUMBER_DUPLICATE`."

        PRD §3.9: "The manifest opens in `DRAFT` with `rejection_reason` null, and its creation drives every cart of the flight still in `LOADED` along the build axis `LOADED → RETURNED`, breaking each such cart's seal axis `SEALED → BROKEN` or `RESEALED → BROKEN` and incrementing each cart's `version`."

        Design: Difficulty/compensating_invariant/replacing_a_rejected_waste_manifest_reproduces_the_identical_sealed_mass
        """
        env = dispositioned_env
        api = env.api
        live_cart = read_cart(api, env.cart["id"])
        assert live_cart["seal_status"] == "SEALED"
        assert live_cart["seal_number"] == SEAL_PRIMARY

        # The cart is still holding this number, and the uniqueness spans both tables.
        validate_error(
            api.create_waste_manifest(
                f.waste_manifest_payload(
                    env.uplift["id"], "INCINERATION", SEAL_PRIMARY
                ),
                COMPLIANCE,
            ),
            ApiErrorId.ERR_SEAL_NUMBER_DUPLICATE.value,
            422,
        )
        _, none_yet = validate_paginated(api.list_waste_manifests(COMPLIANCE))
        assert_total_count(none_yet, 0)
        # The refused creation ran no cascade, so the cart is untouched.
        assert read_cart(api, env.cart["id"])["build_status"] == "LOADED"

        first = raise_waste_manifest(api, env.uplift["id"], seal_number=WASTE_SEAL)
        assert first["status"] == "DRAFT"
        assert read_cart(api, env.cart["id"])["version"] == live_cart["version"] + 1

        # While the first manifest is alive its own seal is reserved too.
        validate_error(
            api.create_waste_manifest(
                f.waste_manifest_payload(env.uplift["id"], "INCINERATION", WASTE_SEAL),
                COMPLIANCE,
            ),
            ApiErrorId.ERR_SEAL_NUMBER_DUPLICATE.value,
            422,
        )

        transition_waste_manifest(
            api, first["id"], "REJECT", rejection_reason=REJECTION_REASON
        )
        replacement = raise_waste_manifest(
            api, env.uplift["id"], seal_number=WASTE_SEAL
        )
        assert replacement["seal_number"] == WASTE_SEAL
        assert replacement["sealed_weight_grams"] == 7000
        rows, meta = validate_paginated(api.list_waste_manifests(COMPLIANCE))
        assert_total_count(meta, 2)
        assert {row["id"] for row in rows} == {first["id"], replacement["id"]}
