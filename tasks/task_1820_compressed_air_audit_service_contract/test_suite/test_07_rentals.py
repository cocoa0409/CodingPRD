"""Rental fleet, reservations, billing variants, escrow, and asset selector claims."""
from test_helpers import (
    ApiErrorId,
    assert_rental_reservation,
    create_and_activate_contract,
    create_compressor,
    create_facility,
    create_leak_survey,
    create_leak_tag,
    create_rental_asset,
    create_rental_reservation_payload,
    create_reservation,
    deliver_and_return,
    get_facility,
    make_contract_manager_headers,
    make_dealer_admin_headers,
    make_energy_engineer_headers,
    make_facility_manager_headers,
    make_service_tech_headers,
    setup_rental_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_dealer_admin_headers()
ENGINEER = make_energy_engineer_headers("eng-1")
TECH = make_service_tech_headers("tech-1")
CONTRACT_MGR = make_contract_manager_headers()


class TestFleetRegistry:
    def test_duplicate_fleet_tag_rejected(self, api):
        """PRD §3.8: "A `DealerAdmin` registers each **RentalAsset** with a globally
        unique `fleet_tag` — a duplicate is rejected with `ERR_DUPLICATE_FLEET_TAG`
        — its `rated_cfm` capacity, the per-calendar-day `daily_rate_cents`, and the
        escrow `deposit_cents` held while the unit is out."

        Design: Corner/entities/corner_duplicate_fleet_tag_rejected
        """
        create_rental_asset(fleet_tag="A1")
        resp = api.create_rental_asset(
            {"fleet_tag": "A1", "rated_cfm": 300, "daily_rate_cents": 20000, "deposit_cents": 60000},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_FLEET_TAG, 409)


class TestQuoteVsActual:
    def test_quote_variant_uses_planned_days(self, api):
        """PRD §3.8: "A created reservation starts `RESERVED`: `rental_asset_id`
        holds the explicit or selected asset, `deposit_cents` snapshots the asset's
        deposit at that moment, `planned_days` counts every calendar day from
        `start_date` through `end_date` inclusive, and `quoted_cents` is the quote
        variant of the rental bill — `planned_days` times the asset's
        `daily_rate_cents`, with no minimum-days floor and no long-term discount."

        Design: Difficulty/dual_variant_calc/rental_quote_vs_actual_bill_diverge
        """
        scenario = setup_rental_scenario(name="F-RB")
        reservation = create_reservation(
            scenario["facility"]["id"],
            scenario["compressor"]["id"],
            "2026-09-01",
            "2026-09-10",
            rental_asset_id=scenario["assets"][0]["id"],
        )
        assert_rental_reservation(reservation)
        assert reservation["planned_days"] == 10
        assert reservation["quoted_cents"] == 350000, (
            f"10 planned days x 35000c, got {reservation['quoted_cents']}"
        )
        assert reservation["deposit_cents"] == 100000

    def test_actual_variant_at_return_diverges_from_quote(self, api):
        """PRD §3.8: "Return computes the actual variant of the bill into
        `actual_bill_cents`: the actual rental days run from `start_date` through
        `actual_return_date` inclusive; billable days are the actual days raised to
        a minimum of 3 when the rental ran shorter; the first 27 billable days are
        charged at the full daily rate and any billable days beyond the
        twenty-seventh at 85 percent of it; and the resulting amount is rounded
        half-up exactly once, at the end, to a whole cent."
        PRD §3.8: "Quote and actual are two legitimate variants of one reservation:
        the quote is computed over planned days at creation, the actual over real
        duration with its floor and discount at return, and the two totals may
        differ."

        Design: Difficulty/dual_variant_calc/rental_quote_vs_actual_bill_diverge
        """
        scenario = setup_rental_scenario(name="F-RB2")
        reservation = create_reservation(
            scenario["facility"]["id"],
            scenario["compressor"]["id"],
            "2026-09-01",
            "2026-09-10",
            rental_asset_id=scenario["assets"][0]["id"],
        )
        reservation = deliver_and_return(reservation["id"], "2026-09-04")
        assert reservation["status"] == "RETURNED"
        # actual days 4 -> billable 4 (above the 3-day floor) -> 4 x 35000
        assert reservation["actual_bill_cents"] == 140000, (
            f"actual bill must be 140000, got {reservation['actual_bill_cents']}"
        )
        assert reservation["quoted_cents"] == 350000
        assert reservation["quoted_cents"] != reservation["actual_bill_cents"]

    def test_rental_min_days_floor(self, api):
        """PRD §3.8: "billable days are the actual days raised to a minimum of 3
        when the rental ran shorter"

        Design: Corner/calculations/corner_rental_min_days_floor
        """
        scenario = setup_rental_scenario(name="F-MIN")
        reservation = create_reservation(
            scenario["facility"]["id"],
            scenario["compressor"]["id"],
            "2026-09-01",
            "2026-09-02",
            rental_asset_id=scenario["assets"][0]["id"],
        )
        assert reservation["quoted_cents"] == 70000, "the quote variant has no floor"
        reservation = deliver_and_return(reservation["id"], "2026-09-02")
        assert reservation["actual_bill_cents"] == 105000, (
            f"2 actual days bill the 3-day minimum: 3 x 35000, "
            f"got {reservation['actual_bill_cents']}"
        )

    def test_rental_long_term_discount_boundary(self, api):
        """PRD §3.8: "the first 27 billable days are charged at the full daily rate
        and any billable days beyond the twenty-seventh at 85 percent of it"

        Design: Corner/calculations/corner_rental_long_term_discount_boundary
        """
        scenario = setup_rental_scenario(
            name="F-LT",
            assets=[
                {"fleet_tag": "A1", "rated_cfm": 500, "daily_rate_cents": 35000, "deposit_cents": 100000},
                {"fleet_tag": "A2", "rated_cfm": 500, "daily_rate_cents": 35000, "deposit_cents": 100000},
            ],
        )
        facility = scenario["facility"]
        compressor = scenario["compressor"]
        a1, a2 = scenario["assets"]

        r27 = create_reservation(facility["id"], compressor["id"], "2026-09-01", "2026-09-27", rental_asset_id=a1["id"])
        r28 = create_reservation(facility["id"], compressor["id"], "2026-09-01", "2026-09-28", rental_asset_id=a2["id"])
        r27 = deliver_and_return(r27["id"], "2026-09-27")
        r28 = deliver_and_return(r28["id"], "2026-09-28")

        assert r27["actual_bill_cents"] == 945000, (
            f"27 days all at full rate: 27 x 35000, got {r27['actual_bill_cents']}"
        )
        # 28 days: 27 full + 1 at 0.85 x 35000 = 29750
        assert r28["actual_bill_cents"] == 974750, (
            f"day 28 is discounted: 945000 + 29750, got {r28['actual_bill_cents']}"
        )


class TestReservationLifecycle:
    def test_invoice_locks_final_bill(self, api):
        """PRD §3.8: "A `ContractManager` invoices a `RETURNED` reservation to the
        terminal `INVOICED` state, locking `final_bill_cents` as a frozen copy of
        `actual_bill_cents`."

        Design: Corner/endpoints/corner_invoice_locks_final_bill
        """
        scenario = setup_rental_scenario(name="F-INV3")
        reservation = create_reservation(
            scenario["facility"]["id"],
            scenario["compressor"]["id"],
            "2026-09-01",
            "2026-09-10",
            rental_asset_id=scenario["assets"][0]["id"],
        )
        reservation = deliver_and_return(reservation["id"], "2026-09-04")
        assert reservation["actual_bill_cents"] == 140000

        reservation = validate_success(api.invoice_reservation(reservation["id"], CONTRACT_MGR))
        assert reservation["status"] == "INVOICED"
        assert reservation["final_bill_cents"] == 140000, (
            "invoice locks final_bill_cents as a frozen copy of actual_bill_cents"
        )

    def test_rental_date_range_invalid(self, api):
        """PRD §3.8: "and `end_date` must not precede `start_date`
        (`ERR_RENTAL_DATE_RANGE_INVALID`, HTTP 422)"
        PRD §3.8: "Return, also by a `ServiceTech`, moves it from `ON_RENT` to
        `RETURNED`; the body carries `actual_return_date`, which must not precede
        the `start_date` (`ERR_RENTAL_DATE_RANGE_INVALID`)."

        Design: Corner/validations/corner_rental_date_range_invalid
        """
        scenario = setup_rental_scenario(name="F-RDR")
        facility = scenario["facility"]
        compressor = scenario["compressor"]
        asset = scenario["assets"][0]
        reservation = create_reservation(
            facility["id"], compressor["id"], "2026-09-05", "2026-09-10",
            rental_asset_id=asset["id"],
        )
        validate_success(api.deliver_reservation(reservation["id"], TECH))

        # No explicit asset: PRD §3.8 pins the within-temporal-tier order —
        # explicit-asset gates fire before the date-range check, so naming an
        # unavailable asset could never surface ERR_RENTAL_DATE_RANGE_INVALID.
        resp = api.create_rental_reservation(
            create_rental_reservation_payload(
                facility_id=facility["id"],
                down_compressor_id=compressor["id"],
                start_date="2026-11-10",
                end_date="2026-11-05",
            ),
            make_facility_manager_headers(facility["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RENTAL_DATE_RANGE_INVALID, 422)

        resp = api.return_reservation(
            reservation["id"], {"actual_return_date": "2026-09-03"}, TECH
        )
        validate_error(resp, ApiErrorId.ERR_RENTAL_DATE_RANGE_INVALID, 422)
        reservation = validate_success(api.get_rental_reservation(reservation["id"], TECH))
        assert reservation["status"] == "ON_RENT", "rejected return must leave the reservation ON_RENT"


class TestTurnaroundBuffer:
    def test_turnaround_day_rejected_and_next_available_date(self, api):
        """PRD §3.8: "Return also frees the asset to `AVAILABLE` with
        `next_available_date` set to the day after the return — the turnaround
        buffer the overlap rule enforces"
        PRD §3.8: "A new reservation whose own inclusive start-to-end interval
        intersects any occupied interval is rejected with
        `ERR_RENTAL_ASSET_UNAVAILABLE`; because the buffer day belongs to the
        earlier reservation, a new start exactly two calendar days after an occupied
        end is the earliest legal adjacency."

        Design: Difficulty/resource_temporal_overlap/rental_asset_turnaround_buffer_overlap
        """
        scenario = setup_rental_scenario(name="F-OV1")
        facility = scenario["facility"]
        compressor = scenario["compressor"]
        asset = scenario["assets"][0]
        r1 = create_reservation(
            facility["id"], compressor["id"], "2026-09-01", "2026-09-10",
            rental_asset_id=asset["id"],
        )
        deliver_and_return(r1["id"], "2026-09-10")

        asset = validate_success(api.get_rental_asset(asset["id"], ADMIN))
        assert asset["status"] == "AVAILABLE"
        assert asset["next_available_date"] == "2026-09-11", (
            f"turnaround day after the 2026-09-10 return, got {asset['next_available_date']}"
        )

        resp = api.create_rental_reservation(
            create_rental_reservation_payload(
                facility_id=facility["id"],
                down_compressor_id=compressor["id"],
                start_date="2026-09-11",
                end_date="2026-09-12",
                rental_asset_id=asset["id"],
            ),
            make_facility_manager_headers(facility["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RENTAL_ASSET_UNAVAILABLE, 409)

    def test_earliest_legal_adjacency_after_turnaround(self, api):
        """PRD §3.8: "For a candidate asset, each existing reservation in
        `RESERVED`, `ON_RENT`, `RETURNED`, or `INVOICED` occupies an interval from
        its `start_date` through one day after its effective end — the effective end
        being its `actual_return_date` once the reservation is `RETURNED` or
        `INVOICED`, otherwise its planned `end_date` — with both endpoints
        inclusive. A new reservation whose own inclusive start-to-end interval
        intersects any occupied interval is rejected with
        `ERR_RENTAL_ASSET_UNAVAILABLE`; because the buffer day belongs to the
        earlier reservation, a new start exactly two calendar days after an occupied
        end is the earliest legal adjacency."

        Design: Difficulty/resource_temporal_overlap/rental_asset_turnaround_buffer_overlap
        """
        scenario = setup_rental_scenario(name="F-OV1B")
        facility = scenario["facility"]
        compressor = scenario["compressor"]
        asset = scenario["assets"][0]
        r1 = create_reservation(
            facility["id"], compressor["id"], "2026-09-01", "2026-09-10",
            rental_asset_id=asset["id"],
        )
        deliver_and_return(r1["id"], "2026-09-10")

        r2 = validate_success(
            api.create_rental_reservation(
                create_rental_reservation_payload(
                    facility_id=facility["id"],
                    down_compressor_id=compressor["id"],
                    start_date="2026-09-12",
                    end_date="2026-09-13",
                    rental_asset_id=asset["id"],
                ),
                make_facility_manager_headers(facility["id"]),
            ),
            201,
        )
        assert r2["status"] == "RESERVED", (
            "starting exactly two days after the occupied end is the earliest legal adjacency"
        )


class TestEscrowIdentity:
    def test_reserve_adds_deposit_to_escrow(self, api):
        """PRD §3.8: "The reservation also moves money: the facility's
        `rental_escrow_cents` grows by the snapshotted deposit."

        Design: Difficulty/compensating_invariant/rental_escrow_reserve_cancel_identity
        """
        scenario = setup_rental_scenario(name="F-INV1")
        facility = scenario["facility"]
        assert get_facility(facility["id"])["rental_escrow_cents"] == 0

        create_reservation(
            facility["id"],
            scenario["compressor"]["id"],
            "2026-09-01",
            "2026-09-05",
            rental_asset_id=scenario["assets"][0]["id"],
        )
        assert get_facility(facility["id"])["rental_escrow_cents"] == 100000, (
            "reserving adds the 100000c deposit to the facility escrow"
        )

    def test_cancel_releases_escrow_to_zero(self, api):
        """PRD §3.8: "A `FacilityManager` cancels a `RESERVED` reservation to the
        terminal `CANCELLED` state, which releases the deposit — the facility's
        `rental_escrow_cents` decreases by the snapshotted amount, so a
        create-then-cancel pair nets zero escrow drift."

        Design: Difficulty/compensating_invariant/rental_escrow_reserve_cancel_identity
        """
        scenario = setup_rental_scenario(name="F-INV1B")
        facility = scenario["facility"]
        reservation = create_reservation(
            facility["id"],
            scenario["compressor"]["id"],
            "2026-09-01",
            "2026-09-05",
            rental_asset_id=scenario["assets"][0]["id"],
        )

        reservation = validate_success(
            api.cancel_reservation(reservation["id"], make_facility_manager_headers(facility["id"]))
        )
        assert reservation["status"] == "CANCELLED"
        assert get_facility(facility["id"])["rental_escrow_cents"] == 0, (
            "the compensating cancel must return escrow exactly to its pre-reserve value"
        )


class TestCrossEntityRentalGates:
    def _two_basic_facilities(self, api):
        f1 = create_facility(name="F1-XG")
        c1 = create_compressor(f1["id"], asset_tag="C1")
        create_and_activate_contract(f1["id"], tier="BASIC", monthly_fee_cents=200000)
        f2 = create_facility(name="F2-XG")
        c9 = create_compressor(f2["id"], asset_tag="C9")
        create_and_activate_contract(f2["id"], tier="BASIC", monthly_fee_cents=200000)
        validate_success(api.mark_down(c9["id"], TECH))
        asset = create_rental_asset(fleet_tag="A1")
        return f1, c1, f2, c9, asset

    def test_rental_gated_by_compressor_state(self, api):
        """PRD §3.8: "The gates run in the priority order of §2.9: the facility must
        be `ACTIVE` (`ERR_FACILITY_NOT_ACTIVE`); the facility must have an `ACTIVE`
        contract — `ERR_NO_ACTIVE_CONTRACT` when there is none and nothing
        suspended, `ERR_CONTRACT_SUSPENDED` when the latest non-terminal contract is
        `SUSPENDED`; the referenced compressor's status must be `DOWN`
        (`ERR_COMPRESSOR_NOT_DOWN`); the down compressor must belong to the calling
        facility (`ERR_FACILITY_MISMATCH`)"

        Design: Difficulty/cross_entity_state_dependency/rental_gated_by_compressor_state_and_contract_tier
        """
        f1, c1, _, _, asset = self._two_basic_facilities(api)
        # Compressor IN_SERVICE (never marked down): the state gate fires before
        # the BASIC tier entitlement is ever consulted.
        resp = api.create_rental_reservation(
            create_rental_reservation_payload(
                facility_id=f1["id"],
                down_compressor_id=c1["id"],
                start_date="2026-09-01",
                end_date="2026-09-05",
                rental_asset_id=asset["id"],
            ),
            make_facility_manager_headers(f1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_COMPRESSOR_NOT_DOWN, 409)
        _, meta = validate_paginated(
            api.list_rental_reservations(CONTRACT_MGR, params={"facility_id": f1["id"]})
        )
        assert meta["total_count"] == 0

    def test_rental_gated_by_contract_tier(self, api):
        """PRD §3.8: "and finally the fiscal tier: the facility's `ACTIVE` contract
        must be `STANDARD` or `PREMIUM` — `BASIC` entitles the customer to no rental
        — or the reservation is rejected with `ERR_CONTRACT_TIER_INELIGIBLE`."

        Design: Difficulty/cross_entity_state_dependency/rental_gated_by_compressor_state_and_contract_tier
        """
        _, _, f2, c9, asset = self._two_basic_facilities(api)
        # Compressor DOWN: the state gate passes and the BASIC tier gate fires.
        resp = api.create_rental_reservation(
            create_rental_reservation_payload(
                facility_id=f2["id"],
                down_compressor_id=c9["id"],
                start_date="2026-09-01",
                end_date="2026-09-05",
                rental_asset_id=asset["id"],
            ),
            make_facility_manager_headers(f2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_TIER_INELIGIBLE, 409)
        _, meta = validate_paginated(
            api.list_rental_reservations(CONTRACT_MGR, params={"facility_id": f2["id"]})
        )
        assert meta["total_count"] == 0


class TestValidationOrderOnReservation:
    def _two_facilities_with_overlap(self, api):
        f1 = create_facility(name="F1-PP2")
        c1 = create_compressor(f1["id"], asset_tag="C1")
        create_and_activate_contract(f1["id"])
        validate_success(api.mark_down(c1["id"], TECH))
        asset = create_rental_asset(fleet_tag="A1")
        create_reservation(f1["id"], c1["id"], "2026-09-01", "2026-09-10", rental_asset_id=asset["id"])

        f2 = create_facility(name="F2-PP2")
        c9 = create_compressor(f2["id"], asset_tag="C9")
        create_and_activate_contract(f2["id"])
        validate_success(api.mark_down(c9["id"], TECH))
        return f1, c1, f2, c9, asset

    def test_referential_beats_temporal_error_reported(self, api):
        """PRD §3.8: "the referenced compressor's status must be `DOWN`
        (`ERR_COMPRESSOR_NOT_DOWN`); the down compressor must belong to the calling
        facility (`ERR_FACILITY_MISMATCH`); then the temporal tier — the asset must
        be free of buffered overlap and, when explicitly named, must itself be
        `AVAILABLE` with `rated_cfm` at least the down unit's `rated_cfm`
        (`ERR_RENTAL_ASSET_UNAVAILABLE` on either count)"
        PRD §2.9: "7. **Cross-facility referential integrity** — every referenced
        entity (baseline or post profile, retrofit project, contract, savings case,
        compressor) must belong to the same facility as the resource being created
        or acted upon; violations yield `ERR_FACILITY_MISMATCH` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_reservation
        """
        _, c1, f2, _, asset = self._two_facilities_with_overlap(api)
        # Foreign (F1-owned) compressor AND dates overlapping the asset's buffered
        # reservation: the referential tier reports before the temporal tier.
        resp = api.create_rental_reservation(
            create_rental_reservation_payload(
                facility_id=f2["id"],
                down_compressor_id=c1["id"],
                start_date="2026-09-05",
                end_date="2026-09-07",
                rental_asset_id=asset["id"],
            ),
            make_facility_manager_headers(f2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FACILITY_MISMATCH, 409)

    def test_referential_beats_temporal_creates_nothing(self, api):
        """PRD §3.8: "the referenced compressor's status must be `DOWN`
        (`ERR_COMPRESSOR_NOT_DOWN`); the down compressor must belong to the calling
        facility (`ERR_FACILITY_MISMATCH`); then the temporal tier"
        PRD §2.9: "A request that fails several rules reports exactly one error: the
        one from the lowest-numbered validation tier."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_reservation
        """
        _, c1, f2, _, asset = self._two_facilities_with_overlap(api)
        resp = api.create_rental_reservation(
            create_rental_reservation_payload(
                facility_id=f2["id"],
                down_compressor_id=c1["id"],
                start_date="2026-09-05",
                end_date="2026-09-07",
                rental_asset_id=asset["id"],
            ),
            make_facility_manager_headers(f2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FACILITY_MISMATCH, 409)
        _, meta = validate_paginated(
            api.list_rental_reservations(CONTRACT_MGR, params={"facility_id": f2["id"]})
        )
        assert meta["total_count"] == 0, "a rejected reservation must not persist"


class TestAssetSelector:
    def test_selector_smallest_sufficient_and_tiebreak(self, api):
        """PRD §3.8: "Eligible assets are `AVAILABLE`, have `rated_cfm` at least the
        down compressor's `rated_cfm`, and carry no buffered overlap as just
        defined. The selector ranks survivors by `rated_cfm` ascending — the
        smallest sufficient unit wins — with ties broken by `created_at` ascending,
        and an empty eligible pool is rejected with
        `ERR_NO_RENTAL_ASSET_AVAILABLE`."
        PRD §3.8: "`deposit_cents` snapshots the asset's deposit at that moment"

        Design: Corner/cross_cutting_complexity_layers/corner_selector_smallest_sufficient_and_tiebreak
        """
        scenario = setup_rental_scenario(
            name="F-SEL",
            assets=[
                {"fleet_tag": "A1", "rated_cfm": 500, "daily_rate_cents": 35000, "deposit_cents": 100000},
                {"fleet_tag": "A2", "rated_cfm": 800, "daily_rate_cents": 60000, "deposit_cents": 150000},
                {"fleet_tag": "A3", "rated_cfm": 800, "daily_rate_cents": 60000, "deposit_cents": 150000},
            ],
        )
        facility = scenario["facility"]
        compressor = scenario["compressor"]
        a1, a2, _ = scenario["assets"]

        r1 = create_reservation(facility["id"], compressor["id"], "2026-09-01", "2026-09-05")
        assert r1["rental_asset_id"] == a1["id"], "the 500 CFM unit is the smallest sufficient"

        validate_success(
            api.cancel_reservation(r1["id"], make_facility_manager_headers(facility["id"]))
        )
        validate_success(
            api.set_rental_asset_maintenance(a1["id"], {"in_maintenance": True}, TECH)
        )

        r2 = create_reservation(facility["id"], compressor["id"], "2026-09-01", "2026-09-05")
        assert r2["rental_asset_id"] == a2["id"], (
            "with A1 in maintenance, the earlier-created 800 CFM unit wins the tie"
        )
        assert r2["deposit_cents"] == 150000, "deposit snapshots the selected asset's deposit"

    def test_selector_empty_pool_and_undersized(self, api):
        """PRD §3.8: "an empty eligible pool is rejected with
        `ERR_NO_RENTAL_ASSET_AVAILABLE`"
        PRD §3.8: "when explicitly named, must itself be `AVAILABLE` with
        `rated_cfm` at least the down unit's `rated_cfm`
        (`ERR_RENTAL_ASSET_UNAVAILABLE` on either count)"

        Design: Corner/cross_cutting_complexity_layers/corner_selector_empty_pool_and_undersized
        """
        scenario = setup_rental_scenario(
            name="F-EMP",
            assets=[{"fleet_tag": "A3", "rated_cfm": 300, "daily_rate_cents": 20000, "deposit_cents": 60000}],
        )
        facility = scenario["facility"]
        compressor = scenario["compressor"]
        a3 = scenario["assets"][0]

        resp = api.create_rental_reservation(
            create_rental_reservation_payload(
                facility_id=facility["id"],
                down_compressor_id=compressor["id"],
                start_date="2026-09-01",
                end_date="2026-09-05",
            ),
            make_facility_manager_headers(facility["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NO_RENTAL_ASSET_AVAILABLE, 409)

        resp = api.create_rental_reservation(
            create_rental_reservation_payload(
                facility_id=facility["id"],
                down_compressor_id=compressor["id"],
                start_date="2026-09-01",
                end_date="2026-09-05",
                rental_asset_id=a3["id"],
            ),
            make_facility_manager_headers(facility["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RENTAL_ASSET_UNAVAILABLE, 409)

        _, meta = validate_paginated(
            api.list_rental_reservations(CONTRACT_MGR, params={"facility_id": facility["id"]})
        )
        assert meta["total_count"] == 0


class TestFilteredReads:
    def test_filtered_list_fk_reverse_reachability(self, api):
        """PRD §3.8: "The reservation list read filters by `facility_id`,
        `rental_asset_id`, `down_compressor_id`, and `status`."
        PRD §3.4: "the tag list read filters by `survey_id` and `status`."

        Design: Corner/endpoints/corner_filtered_list_fk_reverse_reachability
        """
        scenario = setup_rental_scenario(
            name="F-FK",
            assets=[
                {"fleet_tag": "A1", "rated_cfm": 500, "daily_rate_cents": 35000, "deposit_cents": 100000},
                {"fleet_tag": "A2", "rated_cfm": 800, "daily_rate_cents": 60000, "deposit_cents": 150000},
            ],
        )
        facility = scenario["facility"]
        compressor = scenario["compressor"]
        a1, a2 = scenario["assets"]
        reservation = create_reservation(
            facility["id"], compressor["id"], "2026-09-01", "2026-09-05",
            rental_asset_id=a1["id"],
        )
        survey = create_leak_survey(facility["id"])
        t1 = create_leak_tag(survey["id"], 
            location_description="a", cfm_loss=3.0, repair_quote_cents=100000)
        t2 = create_leak_tag(survey["id"], 
            location_description="b", cfm_loss=4.0, repair_quote_cents=120000)

        data, meta = validate_paginated(
            api.list_rental_reservations(CONTRACT_MGR, params={"rental_asset_id": a1["id"]})
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == reservation["id"]

        data, meta = validate_paginated(
            api.list_rental_reservations(CONTRACT_MGR, params={"rental_asset_id": a2["id"]})
        )
        assert meta["total_count"] == 0, "an unused asset filters to an empty array"
        assert data == []

        data, meta = validate_paginated(
            api.list_leak_tags(ENGINEER, params={"survey_id": survey["id"]})
        )
        assert meta["total_count"] == 2
        assert {t["id"] for t in data} == {t1["id"], t2["id"]}

    def test_immediate_read_after_write_consistency(self, api):
        """PRD §1: "every consequential write propagates its effects — facility
        posture changes, staleness flags, escrow balances, credit accruals,
        supersede cascades — atomically within the triggering request, so a reader
        of the API always observes a consistent facility state."
        PRD §3.8: "`planned_days` counts every calendar day from `start_date`
        through `end_date` inclusive, and `quoted_cents` is the quote variant of the
        rental bill — `planned_days` times the asset's `daily_rate_cents`, with no
        minimum-days floor and no long-term discount."

        Design: Corner/consistency_model/corner_immediate_read_after_write_consistency
        """
        scenario = setup_rental_scenario(name="F-CON")
        created = validate_success(
            api.create_rental_reservation(
                create_rental_reservation_payload(
                    facility_id=scenario["facility"]["id"],
                    down_compressor_id=scenario["compressor"]["id"],
                    start_date="2026-09-01",
                    end_date="2026-09-10",
                    rental_asset_id=scenario["assets"][0]["id"],
                ),
                make_facility_manager_headers(scenario["facility"]["id"]),
            ),
            201,
        )
        assert created["planned_days"] == 10
        assert created["quoted_cents"] == 350000

        reread = validate_success(api.get_rental_reservation(created["id"], CONTRACT_MGR))
        assert reread["quoted_cents"] == created["quoted_cents"], (
            "an immediate re-read must observe the computed quote identically"
        )
        assert reread["planned_days"] == 10
        assert reread["version"] == created["version"], (
            "no mutation happened between create and read, so the version is unchanged"
        )
