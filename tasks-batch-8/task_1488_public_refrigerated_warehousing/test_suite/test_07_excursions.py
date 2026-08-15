"""Temperature excursions: four-hop quarantine cascade, SoD, claim gating, and
the pallet dual-dimension model."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    allocate_order,
    assert_excursion,
    assert_instant_equals,
    complete_booking,
    confirm_excursion,
    create_allocated_order,
    create_booking,
    create_cell,
    create_customer_with_card,
    create_submitted_order,
    create_zone,
    file_claim,
    get_excursion,
    get_lot,
    get_order,
    get_pallet,
    list_lot_pallets,
    list_order_allocations,
    make_customer_admin_headers,
    make_quality_manager_headers,
    make_warehouse_operator_headers,
    receive_stock,
    release_quarantine,
    report_excursion,
    set_clock,
    setup_stocked_account,
    start_booking,
    submit_order,
    create_order,
    validate_error,
    validate_success,
)

OPERATOR = TEST_USERS["warehouse_operator_headers"]
QUALITY = TEST_USERS["quality_manager_headers"]


class TestExcursionConfirmCascade:
    def _setup_allocated_and_excursion(self):
        """4 pallets; order for 2 ALLOCATED; excursion REPORTED on the zone."""
        sc = setup_stocked_account(customer_name="Exc Co", zone_code="FZ-9",
                                   pallets=4)
        order = create_allocated_order(sc["customer"]["id"], 2)
        excursion = report_excursion(sc["zone"]["id"], observed_temp_c=-4.0)
        return sc, order, excursion

    def test_confirm_quarantines_all_overlapping_pallets(self, api):
        """PRD §3.6: "Confirmation — `REPORTED` → `CONFIRMED_BREACH` — fires a
        four-hop quarantine cascade. First, every pallet in the excursion's zone
        standing at `STORED`, `ALLOCATED`, or `IN_BLAST_FREEZE`, whose custody
        overlaps the excursion window, and whose quality is `OK`, moves to
        `QUARANTINED`, and the count of pallets caught is stored on the excursion
        as `quarantined_pallet_count`."
        PRD §3.3: "Otherwise, if every present pallet is `QUARANTINED` — with at
        least one present — the lot is `FULL_HOLD`."

        Design: Difficulty/transitive_cascade/excursion_confirm_four_hop_cascade
        """
        sc, order, excursion = self._setup_allocated_and_excursion()
        assert get_order(order["id"])["status"] == "ALLOCATED", (
            "pre-trigger: order fully allocated")
        confirmed = confirm_excursion(excursion["id"])
        assert_excursion(confirmed)
        assert confirmed["status"] == "CONFIRMED_BREACH"
        assert confirmed["quarantined_pallet_count"] == 4, (
            "all present pallets overlap the window, STORED and ALLOCATED alike")
        assert get_lot(sc["lot_id"])["status"] == "FULL_HOLD"

    def test_confirm_releases_allocations_and_demotes_order(self, api):
        """PRD §3.6: "Third, any pallet that was `ALLOCATED` when quarantined
        releases its allocation — the allocation moves to `RELEASED`, the pallet
        returns to `STORED`, and its `QUARANTINED` quality is retained. Fourth,
        each order that owned a released allocation demotes from `ALLOCATED` back
        to `SUBMITTED`; an order at `SHORTED` is unchanged."

        Design: Difficulty/transitive_cascade/excursion_confirm_four_hop_cascade
        """
        sc, order, excursion = self._setup_allocated_and_excursion()
        confirm_excursion(excursion["id"])
        allocations = list_order_allocations(order["id"])
        assert len(allocations) == 2
        assert all(a["status"] == "RELEASED" for a in allocations), (
            "every allocation on quarantined pallets is released")
        after = get_order(order["id"])
        assert after["status"] == "SUBMITTED"
        assert after["allocated_pallets"] == 0
        for pallet in list_lot_pallets(sc["lot_id"]):
            assert pallet["status"] == "STORED"
            assert pallet["quality"] == "QUARANTINED", (
                "quarantine is retained after the custody release")


class TestSegregationOfDuties:
    def test_reporter_cannot_confirm_own_excursion(self, api):
        """PRD §3.6: "Adjudication belongs to a `QualityManager`, under
        segregation of duties: the operator who reported an excursion may not be
        the one to confirm or clear it. A confirm or clear attempt whose
        `X-User-ID` equals the excursion's `reported_by_user_id` is rejected with
        `ERR_SOD_VIOLATION`."

        Design: Corner/validations/sod_reporter_cannot_confirm_own_excursion
        """
        zone = create_zone("FZ-SOD", capacity_pallets=5, dock_doors=1)
        excursion = report_excursion(zone["id"], reporter_user_id="op-7")
        # Same X-User-ID as the reporter, presented with the QualityManager role.
        own = api.confirm_temperature_excursion(
            excursion["id"], make_quality_manager_headers("op-7"))
        validate_error(own, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)
        assert get_excursion(excursion["id"])["status"] == "REPORTED"
        # A different QualityManager confirms successfully.
        confirmed = validate_success(
            api.confirm_temperature_excursion(
                excursion["id"], make_quality_manager_headers("qm-9")))
        assert confirmed["status"] == "CONFIRMED_BREACH"


class TestClaimGatedByExcursionState:
    def _setup_reported_excursion(self):
        sc = setup_stocked_account(customer_name="Gate2 Co", zone_code="FZ-19",
                                   capacity_pallets=5, pallets=1)
        excursion = report_excursion(sc["zone"]["id"], observed_temp_c=-6.0)
        return sc, excursion

    def test_claim_against_reported_excursion_rejected(self, api):
        """PRD §3.8: "Two cross-reference gates apply at filing: the excursion
        must stand at `CONFIRMED_BREACH`, else `ERR_EXCURSION_NOT_CONFIRMED`; and
        the `affected_pallet_count` must not exceed that excursion's
        `quarantined_pallet_count`, else `ERR_CLAIM_EXCEEDS_QUARANTINED_COUNT`
        with HTTP status 422."

        Design: Difficulty/cross_entity_state_dependency/claim_create_gated_by_excursion_state
        """
        sc, excursion = self._setup_reported_excursion()
        resp = api.create_claim(
            {"customer_id": sc["customer"]["id"], "excursion_id": excursion["id"],
             "affected_pallet_count": 1, "declared_value_cents": 5000},
            make_customer_admin_headers(sc["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_EXCURSION_NOT_CONFIRMED,
                       expected_status=409)

    def test_claim_accepted_after_confirmation(self, api):
        """PRD §3.8: "The owning `CustomerAdmin` files a **Claim** with the
        `customer_id`, the `excursion_id` giving rise to the loss, an
        `affected_pallet_count` of at least one, and a `declared_value_cents`
        greater than zero stating the bailor-declared value of the goods. Two
        cross-reference gates apply at filing: the excursion must stand at
        `CONFIRMED_BREACH`, else `ERR_EXCURSION_NOT_CONFIRMED`"
        PRD §3.8: "The claim is born `FILED`, and its `settlement_cents` stays
        null unless and until it is approved."

        Design: Difficulty/cross_entity_state_dependency/claim_create_gated_by_excursion_state
        """
        sc, excursion = self._setup_reported_excursion()
        confirm_excursion(excursion["id"])
        confirmed = get_excursion(excursion["id"])
        assert confirmed["quarantined_pallet_count"] == 1
        claim = file_claim(sc["customer"]["id"], excursion["id"],
                           affected_pallet_count=1, declared_value_cents=5000)
        assert claim["status"] == "FILED"
        assert claim["settlement_cents"] is None


class TestPalletParallelDimensions:
    def _setup_quarantined_pair(self):
        sc = setup_stocked_account(customer_name="Par Co", zone_code="FZ-6",
                                   pallets=2)
        excursion = report_excursion(sc["zone"]["id"], observed_temp_c=-2.0)
        confirm_excursion(excursion["id"])
        return sc

    def test_quarantine_blocks_allocate_without_moving_custody(self, api):
        """PRD §3.3: "Every **Pallet** carries two independent, parallel state
        dimensions."
        PRD §3.3: "Neither dimension implies the other, and guards reference both
        — allocation and blast-freeze selection, for instance, each demand a
        pallet that is simultaneously `STORED` and `OK`."

        Design: Difficulty/non_linear_state_machine/pallet_parallel_dimensions_quarantine_blocks_allocate_not_blast
        """
        sc = self._setup_quarantined_pair()
        for pallet in list_lot_pallets(sc["lot_id"]):
            assert pallet["status"] == "STORED", (
                "quarantine moves quality only, custody stays STORED")
            assert pallet["quality"] == "QUARANTINED"
        order = create_submitted_order(sc["customer"]["id"], 1)
        allocate_order(order["id"])
        after = get_order(order["id"])
        assert after["status"] == "SHORTED" and after["allocated_pallets"] == 0, (
            "no STORED+OK candidates while quarantined")

    def test_blast_cycle_after_quarantine_release(self, api):
        """PRD §3.3: "Releasing a quarantined pallet returns its `quality` from
        `QUARANTINED` to `OK` and recomputes the parent lot's status."
        PRD §3.4: "Completing a booking returns every selected pallet from
        `IN_BLAST_FREEZE` to `STORED` and stamps each pallet's
        `last_blast_frozen_at` with now — resetting its dwell clock for the
        aged-inventory surcharge."

        Design: Difficulty/non_linear_state_machine/pallet_parallel_dimensions_quarantine_blocks_allocate_not_blast
        """
        sc = self._setup_quarantined_pair()
        pallets = list_lot_pallets(sc["lot_id"])
        for pallet in pallets:
            release_quarantine(pallet["id"])
        cell = create_cell("BC-P", capacity_pallets=5, turnaround_minutes=30)
        booking = create_booking(cell["id"], sc["lot_id"], pallet_count=1,
                                 window_start="2026-08-05T10:00:00Z",
                                 window_end="2026-08-05T12:00:00Z")
        set_clock("2026-08-05T10:30:00Z")
        start_booking(booking["id"])
        complete_booking(booking["id"])
        # The selector takes received_at ASC, created_at ASC: the first-created
        # pallet (list order [0]) is the one frozen.
        first = get_pallet(pallets[0]["id"])
        assert first["quality"] == "OK"
        assert first["status"] == "STORED", (
            "the blast cycle returns the pallet IN_BLAST_FREEZE -> STORED")
        assert_instant_equals(first["last_blast_frozen_at"], "2026-08-05T10:30:00Z")
