"""Ordered rejection: when two rules are both violated, the earlier rung is the
one that must report, and the later condition must not be named.

Each test drives a request into a state that breaches more than one rule at
once — role against existence, line allocation against capacity, capacity
against posture, the ten-day pass-through rule, the exception-report window and
the assurance floor — and pins the identifier that comes back. The last test is
the mirror image: a receipt that clears every rung and verifies the shipment.
"""

from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    TEST_USERS,
    assert_cents,
    assert_generator_ledger,
    assert_mass,
    assert_mass_ledger_balances,
    assert_ratio,
    assert_unit_state,
    make_generator_headers,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    container_payload,
    discrepancy_resolution_payload,
    manifest_line_payload,
    receipt_line,
    receive_payload,
)
from test_helpers.fixtures import (
    create_approved_profile,
    create_facility,
    create_funded_facility,
    create_generator,
    create_manifest,
    create_storage_unit,
    post_instrument,
    read_facility,
    read_generator,
    read_line,
    read_manifest,
    read_unit,
    set_clock,
    setup_container_in_storage,
    setup_received_manifest,
)

# An identifier of the right shape that no row was ever minted with.
UNKNOWN_ID = "3f1b9c7e-0000-4000-8000-0000000000aa"


class TestRoleCheckPrecedesExistence:
    def test_unauthorised_role_is_reported_before_the_missing_facility(self):
        """A generator asking for a facility that does not exist must be turned away
        on the role, not on the missing row: role authorisation sits above path
        existence, and a permitted role proves the not-found answer was available.

        "All validations are evaluated in ascending priority order and **the first violated rule wins**; no later rule may mask an earlier one, and no earlier rule may be skipped because a later one would also fail."

        "**Role authorisation.** `X-User-Role` is one of the seven declared roles and appears in the endpoint's authorised list — `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint."

        "Not-found errors are entity-specific. A missing facility yields `ERR_FACILITY_NOT_FOUND`, a missing generator `ERR_GENERATOR_NOT_FOUND`, a missing waste profile `ERR_WASTE_PROFILE_NOT_FOUND`, a missing manifest `ERR_MANIFEST_NOT_FOUND`, a missing storage unit `ERR_STORAGE_UNIT_NOT_FOUND`, a missing container `ERR_CONTAINER_NOT_FOUND`, and a missing treatment batch `ERR_TREATMENT_BATCH_NOT_FOUND`."

        Design: Corner/validations/role_check_precedes_existence_check_unauthorized
        """
        set_clock()
        generator = create_generator()

        # A generator is not among the roles that may read a facility record.
        refused = validate_error(
            api_client.get_facility(UNKNOWN_ID, make_generator_headers(generator["id"])),
            "ERR_ROLE_NOT_PERMITTED",
        )
        # The missing row is the later condition and must not be the one reported.
        assert refused["error_id"] != "ERR_FACILITY_NOT_FOUND"

        # The very same unknown identifier, asked for by a role the endpoint does
        # authorise, reaches the existence check and reports the facility-specific
        # not-found answer, so nothing but the role blocked the first attempt.
        validate_error(
            api_client.get_facility(UNKNOWN_ID, TEST_USERS["clerk"]),
            "ERR_FACILITY_NOT_FOUND",
        )


class TestStorageCapacityAggregation:
    def test_capacity_counts_the_container_already_in_the_unit(self):
        """A second drum whose own mass fits easily is refused because the unit
        already holds 900.0 kg of a 1000.0 kg permit, and the refusal is the capacity
        rule rather than the line-allocation rule that still has room to spare.

        "Stored plus reserved mass, including whatever a request is about to add, may never exceed `permitted_capacity_kg`; a breach is `ERR_STORAGE_CAPACITY_EXCEEDED`."

        "**Storage capacity.** Stored plus reserved mass, including the new container or the new batch, stays at or below `permitted_capacity_kg` — `ERR_STORAGE_CAPACITY_EXCEEDED` (409). Applies to container creation and treatment batch creation."

        "Otherwise it is `RESTRICTED` when any container in the unit is `DEFICIENT`, or when `utilization_pct` reaches or exceeds 0.9000 — the utilisation threshold is inclusive, so a unit sitting at exactly 0.9000 is restricted."

        Design: Corner/validations/aggregate_capacity_across_existing_containers_rejected
        """
        scenario = setup_container_in_storage(
            unit_overrides={"permitted_capacity_kg": 1000.0},
            declared_quantity_kg=2000.0,
            declared_container_count=8,
            net_weight_kg=900.0,
            container_overrides={"container_type": "TOTE", "capacity_kg": 1000.0},
        )
        # 900.0 kg stored against a 1000.0 kg permit is a utilisation of exactly
        # 0.9000, which restricts the unit without closing it to placement.
        assert_unit_state(
            scenario.unit,
            posture="RESTRICTED",
            status="ACTIVE",
            container_count=1,
            stored_kg=900.0,
            reserved_kg=0.0,
            utilization_pct=0.9,
        )
        # The receipt line was declared and weighed at 2000.0 kg and has drawn only
        # 900.0 kg, so 1100.0 kg remains unallocated and a 200.0 kg drum fits the line.
        assert_mass(
            scenario.line["received_quantity_kg"], 2000.0, "received_quantity_kg"
        )

        refused = validate_error(
            api_client.create_container(
                container_payload(
                    scenario.line["id"], scenario.unit["id"], net_weight_kg=200.0
                ),
                TEST_USERS["clerk"],
            ),
            "ERR_STORAGE_CAPACITY_EXCEEDED",
        )
        assert refused["error_id"] != "ERR_LINE_MASS_OVER_ALLOCATED"
        assert refused["error_id"] != "ERR_UNIT_POSTURE_BLOCKED"

        # Nothing was placed: the unit and the line are exactly as they were.
        assert_unit_state(
            read_unit(scenario.unit["id"]), container_count=1, stored_kg=900.0
        )
        line = read_line(scenario.manifest["id"])
        assert_mass(
            line["allocated_container_mass_kg"], 900.0, "allocated_container_mass_kg"
        )


class TestLineAllocationPrecedesCapacity:
    def test_over_drawing_the_line_is_reported_before_the_capacity_breach(self):
        """A drum that would both over-draw its receipt line and overfill the unit
        must be refused on the line allocation, which sits three rungs above the
        capacity check.

        "**Line mass allocation.** A container may not draw more mass from its receipt line than remains unallocated on it — `ERR_LINE_MASS_OVER_ALLOCATED` (422). Applies to container creation."

        "Drawing more than remains is `ERR_LINE_MASS_OVER_ALLOCATED`."

        "All validations are evaluated in ascending priority order and **the first violated rule wins**; no later rule may mask an earlier one, and no earlier rule may be skipped because a later one would also fail."

        Design: Corner/validations/line_mass_over_allocation_reported_before_capacity_rejected
        """
        scenario = setup_container_in_storage(
            unit_overrides={"permitted_capacity_kg": 1000.0},
            declared_quantity_kg=1000.0,
            declared_container_count=5,
            net_weight_kg=900.0,
            container_overrides={"container_type": "TOTE", "capacity_kg": 1000.0},
        )
        # The line was weighed at 1000.0 kg and has already given up 900.0 kg, so
        # only 100.0 kg remains unallocated; the unit likewise has only 100.0 kg of
        # permitted capacity left, so a 200.0 kg drum breaches both rules at once.
        assert_mass(
            scenario.line["allocated_container_mass_kg"],
            900.0,
            "allocated_container_mass_kg",
        )
        assert_unit_state(scenario.unit, stored_kg=900.0, container_count=1)

        refused = validate_error(
            api_client.create_container(
                container_payload(
                    scenario.line["id"], scenario.unit["id"], net_weight_kg=200.0
                ),
                TEST_USERS["clerk"],
            ),
            "ERR_LINE_MASS_OVER_ALLOCATED",
        )
        assert refused["error_id"] != "ERR_STORAGE_CAPACITY_EXCEEDED"

        assert_unit_state(
            read_unit(scenario.unit["id"]), container_count=1, stored_kg=900.0
        )
        line = read_line(scenario.manifest["id"])
        assert_mass(
            line["allocated_container_mass_kg"], 900.0, "allocated_container_mass_kg"
        )


class TestTenDayTransferPassThrough:
    def test_stale_accumulation_closes_the_transfer_unit_only(self):
        """Two drums start accumulating on the same day, one in a ten-day transfer
        unit and one in a container area. Once twelve days have passed, the transfer
        unit refuses further placement while the container area accepts it.

        "`accumulation_days` is the number of whole 86,400-second days that have elapsed from `accumulation_start_date` to the current clock instant, taking the floor, and it is recomputed on every read."

        "`ten_day_overdue` is true when the container sits in a unit whose `unit_type` is `TEN_DAY_TRANSFER` and its `accumulation_days` is strictly greater than 10."

        "A ten-day transfer unit is a pass-through, not a store: adding a container to such a unit, or staging or treating in it, is refused with `ERR_TEN_DAY_LIMIT_EXCEEDED` when any container in the unit has been accumulating for more than 10 days."

        Design: Corner/validations/ten_day_rule_rejects_placement_in_transfer_unit_but_not_container_area
        """
        scenario = setup_received_manifest(
            unit_overrides={"unit_code": "TT-01", "unit_type": "TEN_DAY_TRANSFER"},
            declared_quantity_kg=2000.0,
            declared_container_count=8,
        )
        transfer_unit = scenario.unit
        container_area = create_storage_unit(
            scenario.facility["id"], unit_code="CA-01", unit_type="CONTAINER_AREA"
        )

        # Both drums have been accumulating for seven days at the current instant,
        # which the pass-through rule still allows.
        in_transfer = validate_success(
            api_client.create_container(
                container_payload(
                    scenario.line["id"],
                    transfer_unit["id"],
                    net_weight_kg=200.0,
                    accumulation_start_date="2026-07-25T00:00:00Z",
                ),
                TEST_USERS["clerk"],
            ),
            expected_status=201,
        )
        in_container_area = validate_success(
            api_client.create_container(
                container_payload(
                    scenario.line["id"],
                    container_area["id"],
                    net_weight_kg=200.0,
                    accumulation_start_date="2026-07-25T00:00:00Z",
                ),
                TEST_USERS["clerk"],
            ),
            expected_status=201,
        )
        assert in_transfer["accumulation_days"] == 7
        assert in_transfer["ten_day_overdue"] is False

        set_clock("2026-08-06T00:00:00Z")

        # Twelve whole days from 25 July to 6 August.
        aged_transfer = validate_success(
            api_client.get_container(in_transfer["id"], TEST_USERS["clerk"])
        )
        assert aged_transfer["accumulation_days"] == 12
        assert aged_transfer["ten_day_overdue"] is True
        # The same age in a container area is not a ten-day matter at all.
        aged_area = validate_success(
            api_client.get_container(in_container_area["id"], TEST_USERS["clerk"])
        )
        assert aged_area["accumulation_days"] == 12
        assert aged_area["ten_day_overdue"] is False

        refused = validate_error(
            api_client.create_container(
                container_payload(
                    scenario.line["id"],
                    transfer_unit["id"],
                    net_weight_kg=150.0,
                    accumulation_start_date="2026-08-06T00:00:00Z",
                ),
                TEST_USERS["clerk"],
            ),
            "ERR_TEN_DAY_LIMIT_EXCEEDED",
        )
        assert refused["error_id"] != "ERR_STORAGE_CAPACITY_EXCEEDED"

        # The container area, holding a drum of the same age, still accepts waste.
        validate_success(
            api_client.create_container(
                container_payload(
                    scenario.line["id"],
                    container_area["id"],
                    net_weight_kg=150.0,
                    accumulation_start_date="2026-08-06T00:00:00Z",
                ),
                TEST_USERS["clerk"],
            ),
            expected_status=201,
        )

        assert_unit_state(
            read_unit(transfer_unit["id"]), container_count=1, stored_kg=200.0
        )
        assert_unit_state(
            read_unit(container_area["id"]), container_count=2, stored_kg=350.0
        )


class TestDiscrepancyReportWindow:
    def test_resolution_after_the_report_deadline_is_refused(self):
        """A bulk shipment ten percent light becomes discrepant with a fifteen-day
        exception-report window; a resolution attempted the day after the window
        closes is refused and the shipment stays discrepant.

        "Otherwise, a line whose absolute variance reaches or exceeds its tolerance takes a `significance` of `QUANTITY_SIGNIFICANT`; the tolerance is 10 percent expressed as the fraction 0.10 for a bulk line and 2 percent expressed as the fraction 0.02 for a containerised one, and the comparison is inclusive, so a bulk line declared at 1000.0 kg and weighed at 900.0 kg reaches exactly 0.1000 and is significant, while the same line weighed at 905.0 kg yields 0.0950 and is not."

        "Choosing `ACCEPT_ADJUSTED` or `PARTIAL_REJECT` moves the manifest from `DISCREPANT` to `VERIFIED`, and both require two things: the current clock instant must be at or before `discrepancy_report_due_at`, otherwise the resolution is refused with `ERR_DISCREPANCY_REPORT_OVERDUE`; and the body's `discrepancy_report_filed` must be true, otherwise the request is invalid."

        Design: Corner/validations/discrepancy_resolution_after_report_deadline_rejected
        """
        scenario = setup_received_manifest(
            declared_quantity_kg=1000.0,
            declared_container_count=0,
            is_bulk=True,
            received_quantity_kg=900.0,
        )
        assert scenario.manifest["status"] == "DISCREPANT"
        assert scenario.manifest["discrepancy_type"] == "QUANTITY_SIGNIFICANT"
        # (1000.0 - 900.0) / 1000.0 lands exactly on the bulk tolerance of 0.10.
        assert_ratio(scenario.line["variance_pct"], 0.1, "variance_pct")
        # Fifteen days after the arrival instant of 2026-08-01T00:00:00Z.
        assert scenario.manifest["discrepancy_report_due_at"].startswith(
            "2026-08-16T00:00:00"
        )

        set_clock("2026-08-17T00:00:00Z")
        refused = validate_error(
            api_client.resolve_manifest_discrepancy(
                scenario.manifest["id"],
                discrepancy_resolution_payload(
                    "ACCEPT_ADJUSTED",
                    discrepancy_report_filed=True,
                    adjusted_lines=[{"line_number": 1, "accepted_quantity_kg": 900.0}],
                ),
                TEST_USERS["compliance_manager"],
            ),
            "ERR_DISCREPANCY_REPORT_OVERDUE",
        )
        assert refused["error_id"] != "ERR_INVALID_REQUEST"

        unresolved = read_manifest(scenario.manifest["id"])
        assert unresolved["status"] == "DISCREPANT"
        assert unresolved["resolution_type"] == "NONE"
        assert unresolved["discrepancy_report_filed"] is False
        assert unresolved["discrepancy_resolved_at"] is None
        line = read_line(scenario.manifest["id"])
        assert line["line_status"] == "RECEIVED"


class TestAssuranceFloorOnAcceptance:
    def test_an_underfunded_facility_may_not_take_waste_in(self):
        """A facility whose only instrument is a token bond carries a shortfall, and
        the dock refuses the shipment: nothing arrives, nothing is charged and the
        mass ledger stays at zero.

        "`posted_assurance_cents` is the sum of `face_amount_cents` over the facility's instruments whose `status` is `ACTIVE`, and `assurance_shortfall_cents` is the amount by which the required total exceeds the posted total, or zero when the posted total is at least the required total."

        "**Financial assurance.** The facility's `assurance_shortfall_cents` is zero before waste acceptance, container placement, permit renewal filing or instrument cancellation — `ERR_FINANCIAL_ASSURANCE_SHORTFALL` (402). Applies to manifest receipt, container creation, the permit renewal request and instrument cancellation."

        Design: Corner/validations/assurance_shortfall_blocks_waste_acceptance_rejected
        """
        set_clock()
        facility = create_facility()
        post_instrument(
            facility["id"],
            face_amount_cents=1_000_000,
            expected_facility_version=facility["version"],
            instrument_type="SURETY_BOND",
        )
        generator = create_generator()
        profile = create_approved_profile(generator["id"], facility["id"])
        manifest = create_manifest(
            generator["id"],
            facility["id"],
            lines=[manifest_line_payload(profile["id"], 1000.0, 4, False)],
        )

        # An empty facility owes 25,000,000 cents of base closure cost, which sits in
        # the first tier and carries a 5 percent surcharge, plus its post-closure input.
        base = 25_000_000
        estimate = int(
            (Decimal(base) * Decimal("1.05")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        required = estimate + facility["post_closure_cost_cents"] + 0 + 0
        before = read_facility(facility["id"])
        assert_cents(before["closure_base_cost_cents"], base)
        assert before["assurance_tier"] == "TIER_1"
        assert_cents(before["required_assurance_cents"], required)
        assert_cents(before["posted_assurance_cents"], 1_000_000)
        assert_cents(before["assurance_shortfall_cents"], required - 1_000_000)

        refused = validate_error(
            api_client.receive_manifest(
                manifest["id"],
                receive_payload([receipt_line(1, 1000.0, 4)]),
                TEST_USERS["clerk"],
            ),
            "ERR_FINANCIAL_ASSURANCE_SHORTFALL",
        )
        assert refused["error_id"] != "ERR_ACCEPTANCE_CRITERIA_FAILED"

        turned_away = read_manifest(manifest["id"])
        assert turned_away["status"] == "EN_ROUTE"
        assert turned_away["arrived_at"] is None
        line = read_line(manifest["id"])
        assert line["line_status"] == "DECLARED"
        assert_mass(line["received_quantity_kg"], 0.0, "received_quantity_kg")
        assert_generator_ledger(read_generator(generator["id"]), open_cents=0, settled_cents=0)
        after = read_facility(facility["id"])
        assert_mass(after["received_mass_kg"], 0.0, "received_mass_kg")
        assert_mass(after["unallocated_receipt_kg"], 0.0, "unallocated_receipt_kg")
        assert_mass_ledger_balances(after)


class TestCleanReceipt:
    def test_a_receipt_that_clears_every_rule_verifies_the_shipment(self):
        """The mirror image of the refusals: a funded facility, an approved profile
        and a shipment weighed exactly as declared. The manifest verifies straight
        away, the provisional charge is frozen, and every kilogram lands in the
        unallocated pool.

        "Receipt stamps `arrived_at` from the clock, writes each line's received figures, sets each line's `accepted_quantity_kg` equal to its `received_quantity_kg`, and moves each line's `line_status` from `DECLARED` to `RECEIVED`."

        "When `discrepancy_type` computes to `NONE`, the manifest moves from `EN_ROUTE` to `VERIFIED`."

        "The line's charge is the priced quantity multiplied by that rate, rounded half up to whole cents, plus a container handling fee of 750 cents for each container in the line's `received_container_count`."

        "`mass_ledger_kg` is the sum of those five destinations, and it must equal `received_mass_kg` after every operation, with no rounding drift."

        Design: Corner/validations/clean_receipt_satisfies_every_rule_and_verifies_the_manifest
        """
        set_clock()
        facility, _instrument = create_funded_facility()
        generator = create_generator()
        profile = create_approved_profile(generator["id"], facility["id"])
        unit = create_storage_unit(facility["id"])
        assert unit["posture"] == "OPEN"
        manifest = create_manifest(
            generator["id"],
            facility["id"],
            lines=[manifest_line_payload(profile["id"], 1000.0, 4, False)],
        )
        assert manifest["status"] == "EN_ROUTE"

        received = validate_success(
            api_client.receive_manifest(
                manifest["id"],
                receive_payload([receipt_line(1, 1000.0, 4)]),
                TEST_USERS["clerk"],
            )
        )

        assert received["status"] == "VERIFIED"
        assert received["discrepancy_type"] == "NONE"
        assert received["discrepancy_report_due_at"] is None
        assert received["discrepancy_report_filed"] is False
        assert received["arrived_at"].startswith("2026-08-01T00:00:00")
        assert received["final_charge_cents"] is None

        # A SOLID base rate of 30 cents per kilogram times the 1.20 ORGANIC_SOLVENT
        # multiplier, with no land-disposal surcharge, on the weighed 1000.0 kg, plus
        # 750 cents of handling for each of the four received containers.
        rate = Decimal("30") * Decimal("1.20")
        expected_charge = int(
            (Decimal("1000.0") * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        ) + 750 * 4
        assert_cents(received["provisional_charge_cents"], expected_charge)
        assert_mass(received["received_mass_kg"], 1000.0, "received_mass_kg")

        line = read_line(manifest["id"])
        assert line["line_status"] == "RECEIVED"
        assert line["significance"] == "NONE"
        assert_ratio(line["variance_pct"], 0.0, "variance_pct")
        assert_mass(line["received_quantity_kg"], 1000.0, "received_quantity_kg")
        assert_mass(line["accepted_quantity_kg"], 1000.0, "accepted_quantity_kg")
        assert_mass(line["returned_quantity_kg"], 0.0, "returned_quantity_kg")
        assert_cents(line["provisional_line_charge_cents"], expected_charge)

        assert_generator_ledger(
            read_generator(generator["id"]), open_cents=expected_charge, settled_cents=0
        )
        after = read_facility(facility["id"])
        assert_mass(after["received_mass_kg"], 1000.0, "received_mass_kg")
        # Nothing has been containerised yet, so the whole receipt waits in the pool.
        assert_mass(after["unallocated_receipt_kg"], 1000.0, "unallocated_receipt_kg")
        assert_mass(after["held_mass_kg"], 0.0, "held_mass_kg")
        assert_mass(after["mass_ledger_kg"], 1000.0, "mass_ledger_kg")
        assert_mass_ledger_balances(after)
