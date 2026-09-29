"""The casing cycle, the two independent call dimensions, and the cure fork."""

from test_helpers import (
    entries_of_type,
    fixtures,
    validate_paginated,
    validate_success,
)


class TestCasingRetreadCycle:
    """The casing's life is a cycle: it comes back to where it started."""

    def test_retread_completion_mints_the_asset_that_will_close_the_cycle(self, api):
        """PRD §3.5: "In hop 2, because the job completed, the casing advances
        `IN_RETREAD → RETREADED`, its `retread_count` increases by 1 and its
        `inspection_grade` is cleared to empty."
        PRD §2.6: "This matters for resources the API never returns from a creation
        response — the tire asset minted by a retread completion, for instance, is
        discoverable only by filtering the job list on `produced_tire_asset_id` or
        the asset list on `casing_id`."

        Design: Difficulty/non_linear_state_machine/casing_retread_cycle_returns_to_on_wheel
        """
        program = fixtures.setup_plant_program()
        casing = fixtures.create_casing(program["fleet"]["id"])
        assert casing["status"] == "ON_WHEEL"
        assert casing["retread_count"] == 0

        collected = fixtures.collect_casing(casing["id"], program["location"]["id"])
        assert collected["status"] == "COLLECTED"
        inspected = fixtures.inspect_casing(casing["id"], "B", collected["version"])
        assert inspected["status"] == "INSPECTED"
        job = fixtures.schedule_retread_job(casing["id"], program["line"]["id"])
        assert fixtures.read_casing(casing["id"])["status"] == "RETREAD_QUEUED"
        fixtures.start_job(job["id"])
        assert fixtures.read_casing(casing["id"])["status"] == "IN_RETREAD"

        completed = fixtures.complete_job(job["id"])

        after = fixtures.read_casing(casing["id"])
        assert after["status"] == "RETREADED"
        assert after["retread_count"] == 1
        assert after.get("inspection_grade") is None
        assert after["collected_at_location_id"] == program["location"]["id"], (
            "the carcass is still in the yard until the new assembly is mounted"
        )

        produced_id = completed["produced_tire_asset_id"]
        assets = fixtures.list_assets_for_casing(casing["id"])
        assert [a["id"] for a in assets] == [produced_id]
        assert assets[0]["status"] == "IN_INVENTORY"
        assert assets[0]["brand"] == casing["brand"]

    def test_mounting_the_retreaded_product_returns_the_casing_to_on_wheel(self, api):
        """PRD §3.3: "A successful mount stores all five supplied values,
        increments the asset's `version`, and — when the underlying casing is
        sitting in `RETREADED` — cascades that casing `RETREADED → ON_WHEEL`,
        recomputes the `casings_in_holding_count` of the location named in the
        casing's `collected_at_location_id`, then clears `collected_at_location_id`
        and increments the casing's `version`."
        PRD §3.3: "That cascade is what closes the retread cycle: the carcass is
        back on a truck and eligible for collection and another retread round."

        Design: Difficulty/non_linear_state_machine/casing_retread_cycle_returns_to_on_wheel
        """
        program = fixtures.setup_plant_program()
        vehicle = fixtures.create_vehicle(program["fleet"]["id"])
        casing = fixtures.create_casing(program["fleet"]["id"])
        fixtures.collect_casing(casing["id"], program["location"]["id"])
        assert (
            fixtures.read_location(program["location"]["id"])[
                "casings_in_holding_count"
            ]
            == 1
        )
        inspected = fixtures.read_casing(casing["id"])
        fixtures.inspect_casing(casing["id"], "B", inspected["version"])
        job = fixtures.schedule_retread_job(casing["id"], program["line"]["id"])
        fixtures.start_job(job["id"])
        completed = fixtures.complete_job(job["id"])

        mounted = validate_success(
            api.mount_tire_asset(
                completed["produced_tire_asset_id"],
                {
                    "vehicle_id": vehicle["id"],
                    "position": "DRIVE",
                    "mounted_at": "2026-08-21T08:00:00Z",
                    "odometer_at_mount": 100000,
                    "tread_depth_at_mount_32nds": 24,
                },
                fixtures.TECH,
            )
        )

        assert mounted["status"] == "MOUNTED"
        closed = fixtures.read_casing(casing["id"])
        assert closed["status"] == "ON_WHEEL", "the cycle has returned to its origin"
        assert closed["retread_count"] == 1, (
            "but the carcass now carries one more retread than it started with"
        )
        assert closed.get("collected_at_location_id") is None
        assert (
            fixtures.read_location(program["location"]["id"])[
                "casings_in_holding_count"
            ]
            == 0
        )

        # Eligible for another round: pull the assembly, collect the carcass again.
        validate_success(
            api.pull_tire_asset(mounted["id"], {"pull_reason": "Worn out"}, fixtures.TECH)
        )
        recollected = fixtures.collect_casing(casing["id"], program["location"]["id"])
        assert recollected["status"] == "COLLECTED"
        assert recollected["retread_count"] == 1


class TestCallDimensionsAreIndependent:
    """One row, two state machines that do not imply each other."""

    def test_dispatch_dimension_advances_while_billing_stays_unbilled(self, api):
        """PRD §3.6: "A road service call is unusual in this system in that it
        advances along **two independent state dimensions on the same row**."
        PRD §3.6: "The two dimensions evolve separately and neither implies the
        other; the single exception is noted at the end of this subsection."

        Design: Difficulty/non_linear_state_machine/road_service_call_parallel_dispatch_and_billing_dimensions
        """
        program = fixtures.setup_fleet_program()
        vehicle = fixtures.create_vehicle(program["fleet"]["id"])
        technician = fixtures.create_technician(program["location"]["id"])

        opened = fixtures.open_call(
            program["fleet"]["id"],
            vehicle["id"],
            program["location"]["id"],
            "2026-08-05T13:00:00Z",
        )
        assert opened["dispatch_status"] == "OPEN"
        assert opened["billing_status"] == "UNBILLED"

        dispatched = fixtures.dispatch_call(
            opened["id"], "2026-08-05T13:05:00Z", 2, technician["id"]
        )
        assert dispatched["dispatch_status"] == "DISPATCHED"
        assert dispatched["billing_status"] == "UNBILLED"

        on_site = fixtures.arrive_call(
            opened["id"], "2026-08-05T13:30:00Z", technician["id"]
        )
        assert on_site["dispatch_status"] == "ON_SITE"
        assert on_site["billing_status"] == "UNBILLED"

        completed = fixtures.complete_call(
            opened["id"], "2026-08-05T14:00:00Z", 0.25, technician["id"]
        )
        assert completed["dispatch_status"] == "COMPLETED"
        assert completed["billing_status"] == "UNBILLED", (
            "reaching the end of the dispatch dimension bills nothing by itself"
        )
        assert completed.get("cross_location_invoice_id") is None

    def test_billing_dimension_advances_while_dispatch_stays_completed(self, api):
        """PRD §3.8: "Every claimed call cascades `INVOICED →
        BILLED_TO_NATIONAL`."
        PRD §3.8: "Every claimed call cascades `BILLED_TO_NATIONAL → UNBILLED` and
        has its `cross_location_invoice_id` cleared, releasing it to be picked up
        by a later invoice; the calls' `dispatch_status` remains `COMPLETED`
        throughout, since disputing a bill does not un-repair a truck."

        Design: Difficulty/non_linear_state_machine/road_service_call_parallel_dispatch_and_billing_dimensions
        """
        program = fixtures.setup_open_invoice(credit_grade="B")
        call_id = program["calls"][0]["id"]
        invoice_id = program["invoice"]["id"]

        claimed = fixtures.read_call(call_id)
        assert claimed["dispatch_status"] == "COMPLETED"
        assert claimed["billing_status"] == "INVOICED"
        assert claimed["cross_location_invoice_id"] == invoice_id

        fixtures.submit_invoice(invoice_id)
        billed = fixtures.read_call(call_id)
        assert billed["dispatch_status"] == "COMPLETED"
        assert billed["billing_status"] == "BILLED_TO_NATIONAL"

        fixtures.dispute_invoice(invoice_id)
        released = fixtures.read_call(call_id)
        assert released["dispatch_status"] == "COMPLETED", (
            "the dispatch dimension is frozen at its terminal value"
        )
        assert released["billing_status"] == "UNBILLED"
        assert released.get("cross_location_invoice_id") is None


class TestFailedCureFork:
    """One transition, three genuinely different outcomes."""

    def test_cure_defect_and_line_fault_diverge_only_on_the_line(self, api):
        """PRD §3.5: "When `failure_reason` is `CURE_DEFECT`, the casing reverts
        `IN_RETREAD → INSPECTED`, keeping both its grade and its accrued credit so
        it is immediately re-schedulable, and the line's `status` is untouched."
        PRD §3.5: "When `failure_reason` is `LINE_FAULT`, the casing likewise
        reverts `IN_RETREAD → INSPECTED` keeping grade and credit, **and in
        addition** the line is taken down, moving `AVAILABLE → DOWN`, because the
        fault was the plant's, not the carcass's."

        Design: Difficulty/non_linear_state_machine/retread_job_failed_cure_fork_diverges_by_reason
        """
        defect = fixtures.setup_failed_cure_job(failure_reason="CURE_DEFECT")
        fault = fixtures.setup_failed_cure_job(failure_reason="LINE_FAULT")

        for program in (defect, fault):
            assert program["job"]["status"] == "FAILED_CURE"
            casing = fixtures.read_casing(program["casing"]["id"])
            assert casing["status"] == "INSPECTED", "the carcass is re-schedulable"
            assert casing["inspection_grade"] == "B", "the grade survives the failure"
            assert casing["provisional_credit_cents"] == 8400, (
                "the accrued credit survives: 12000 default rate at grade B"
            )
            assert fixtures.read_line(program["line"]["id"])["booked_minutes"] == 0, (
                "the slot is released in all three branches"
            )

        assert fixtures.read_line(defect["line"]["id"])["status"] == "AVAILABLE"
        assert fixtures.read_line(fault["line"]["id"])["status"] == "DOWN", (
            "only the line-fault branch condemns the line"
        )

    def test_casing_failure_condemns_the_carcass_and_spares_the_line(self, api):
        """PRD §3.5: "When `failure_reason` is `CASING_FAILURE`, the carcass itself
        is condemned: the casing moves `IN_RETREAD → REJECTED` with its
        `rejection_reason` set to the fixed string `CASING_FAILURE_IN_PRODUCTION`,
        no ledger entry is posted — credit is written off only at certified
        destruction — and the line's `status` is untouched."
        PRD §3.5: "Recording a cure failure moves the job `IN_PRODUCTION →
        FAILED_CURE`, stores the `failure_reason`, accepts an optional free-text
        `note`, and releases the job's slot from the line's `booked_minutes` — that
        release happens in **all three** branches."

        Design: Difficulty/non_linear_state_machine/retread_job_failed_cure_fork_diverges_by_reason
        """
        program = fixtures.setup_failed_cure_job(failure_reason="CASING_FAILURE")

        assert program["job"]["status"] == "FAILED_CURE"
        assert program["job"]["failure_reason"] == "CASING_FAILURE"

        casing = fixtures.read_casing(program["casing"]["id"])
        assert casing["status"] == "REJECTED"
        assert casing["rejection_reason"] == "CASING_FAILURE_IN_PRODUCTION"
        assert casing["provisional_credit_cents"] == 8400, (
            "the credit is not written off here, only at certified destruction"
        )

        entries = fixtures.list_ledger(program["fleet"]["id"])
        assert len(entries_of_type(entries, "ACCRUAL")) == 1
        for written_off in ("ADJUSTMENT", "REVERSAL", "EXPIRY"):
            assert entries_of_type(entries, written_off) == [], (
                f"a condemned carcass posts no {written_off} entry"
            )

        line = fixtures.read_line(program["line"]["id"])
        assert line["status"] == "AVAILABLE", "the plant was not at fault"
        assert line["booked_minutes"] == 0

        _jobs, meta = validate_paginated(
            api.list_retread_jobs(
                fixtures.SCHEDULER, params={"status": "FAILED_CURE"}
            )
        )
        assert meta["total_count"] == 1
