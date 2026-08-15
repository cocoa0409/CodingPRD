"""Gang runs: lock/unlock cycle, membership boundary, allocation remainder,
state gates, eligibility/due-window priority, quantity match, and OCC."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_estimate,
    add_gang_member,
    approve_proof,
    create_customer,
    create_estimate,
    create_gang_run,
    create_gang_with_members,
    create_plated_job,
    create_press,
    create_received_stock,
    create_stock,
    gang_member_payload,
    gang_pair_signatures,
    get_success_data,
    lock_gang,
    make_customer_headers,
    minimal_signature,
    quote_estimate,
    schedule_press_run,
    upload_proof,
    validate_error,
    validate_paginated,
    validate_success,
)

_SCH = TEST_USERS["scheduler_headers"]
_PM = TEST_USERS["plant_manager_headers"]


def _plated_job(cust, stock, quantity=1000, make_ready_cents=50000,
                due_date="2026-08-20T00:00:00Z", job_name="J",
                rate=30000, press_type="WEB", finishing=None):
    est = create_estimate(
        cust["id"], gang_pair_signatures(stock["id"], make_ready_cents)
        if rate == 37250 else minimal_signature(stock["id"], make_ready_cents=make_ready_cents,
                                                rate_per_thousand_cents=rate),
        quantity_ordered=quantity, due_date=due_date, job_name=job_name,
        press_type=press_type, finishing_options=finishing,
    )
    quote_estimate(est["id"])
    job = accept_estimate(est["id"], cust["id"])
    p = upload_proof(job["id"], f"s3://{job_name}.pdf")
    approve_proof(p["id"], cust["id"])
    return job


class TestGangLockUnlockCycle:
    def _gang_pair_locked(self):
        cust = create_customer(name="GC Cust")
        stock, _po = create_received_stock(name="80G", cost_per_sheet_cents=9, sheets=10000)
        j1 = _plated_job(cust, stock, quantity=4000, make_ready_cents=100000,
                         due_date="2026-08-20T00:00:00Z", job_name="G1", rate=37250,
                         finishing=["PERF"])
        j2 = _plated_job(cust, stock, quantity=6000, make_ready_cents=120000,
                         due_date="2026-08-21T00:00:00Z", job_name="G2", rate=37250,
                         finishing=["SCORE"])
        gang = create_gang_with_members(stock["id"], [j1["id"], j2["id"]])
        gang = lock_gang(gang["id"])
        return cust, j1, j2, gang

    def test_unlock_clears_allocations(self, api):
        """PRD §3.7: "A successful unlock moves the gang `LOCKED → FORMING`,
        clears every member's `allocated_make_ready_cents` back to null,
        clears the gang's `make_ready_total_cents` back to null."

        Design: Difficulty/non_linear_state_machine/gang_lock_unlock_cycle
        """
        _cust, j1, j2, gang = self._gang_pair_locked()
        resp = api.unlock_gang_run(gang["id"], _SCH)
        data = validate_success(resp, 200)
        assert data["status"] == "FORMING"
        assert data["make_ready_total_cents"] is None
        for m in data["members"]:
            assert m["allocated_make_ready_cents"] is None

    def test_relock_recomputes_same_allocations(self, api):
        """PRD §3.7: "On lock, the gang transitions `FORMING → LOCKED`, its
        `make_ready_total_cents` becomes the maximum of the members'
        individual `make_ready_total_cents` values, and each member's
        `allocated_make_ready_cents` is computed by a waterfall" — re-lock
        after unlock recomputes 48000/72000, proving the cycle restores a
        clean FORMING state.

        Design: Difficulty/non_linear_state_machine/gang_lock_unlock_cycle
        """
        _cust, j1, j2, gang = self._gang_pair_locked()
        api.unlock_gang_run(gang["id"], _SCH)
        relock = validate_success(api.lock_gang_run(gang["id"], _SCH), 200)
        assert relock["status"] == "LOCKED"
        allocs = {m["job_id"]: m["allocated_make_ready_cents"] for m in relock["members"]}
        assert allocs[j1["id"]] == 48000
        assert allocs[j2["id"]] == 72000
        job1 = get_success_data(api.get_job(j1["id"], _PM))
        assert job1["allocated_make_ready_cents"] == 48000


class TestGangMinimumMembershipBoundary:
    def _one_member_gang(self):
        cust = create_customer(name="GM Cust")
        stock, _po = create_received_stock(name="80G", cost_per_sheet_cents=9, sheets=10000)
        j1 = _plated_job(cust, stock, quantity=4000, make_ready_cents=100000,
                         due_date="2026-08-20T00:00:00Z", job_name="G1", rate=37250,
                         finishing=["PERF"])
        j2 = _plated_job(cust, stock, quantity=6000, make_ready_cents=120000,
                         due_date="2026-08-21T00:00:00Z", job_name="G2", rate=37250,
                         finishing=["SCORE"])
        gang = create_gang_run(stock["id"])
        gang = add_gang_member(gang, j1["id"])
        return cust, j1, j2, gang

    def test_lock_with_one_member_rejected(self, api):
        """PRD §3.7: "Locking requires at least 2 members (else
        `ERR_GANG_TOO_SMALL`)."

        Design: Difficulty/boundary_precision_check/gang_minimum_membership_boundary
        """
        _cust, _j1, _j2, gang = self._one_member_gang()
        resp = api.lock_gang_run(gang["id"], _SCH)
        validate_error(resp, ApiErrorId.ERR_GANG_TOO_SMALL)

    def test_lock_with_two_members_succeeds(self, api):
        """PRD §3.7: "Locking requires at least 2 members" — exactly 2 locks,
        and "`make_ready_total_cents` becomes the maximum of the members'
        individual `make_ready_total_cents` values" (max(100000, 120000) =
        120000).

        Design: Difficulty/boundary_precision_check/gang_minimum_membership_boundary
        """
        _cust, _j1, j2, gang = self._one_member_gang()
        gang = add_gang_member(gang, j2["id"])
        locked = validate_success(api.lock_gang_run(gang["id"], _SCH), 200)
        assert locked["status"] == "LOCKED"
        assert locked["make_ready_total_cents"] == 120000


class TestGangAllocationRemainder:
    def test_gang_allocation_remainder_to_earliest_member(self, api):
        """PRD §3.7: "each share is rounded half-up to a whole cent; the
        remainder — the gang make-ready total minus the sum of the rounded
        shares, which may be negative — is assigned to the member whose job
        has the earliest `created_at`... The conservation invariant holds
        exactly: the sum of `allocated_make_ready_cents` across members equals
        the gang's `make_ready_total_cents`." Three equal-impression members
        under max make-ready 100000: 33334/33333/33333.

        Design: Corner/calculations/gang_allocation_remainder_to_earliest_member
        """
        cust = create_customer(name="GR Cust")
        stock = create_stock(name="80G", cost_per_sheet_cents=9)
        jobs = []
        for name, mr in (("R1", 100000), ("R2", 90000), ("R3", 80000)):
            jobs.append(_plated_job(cust, stock, quantity=4000, make_ready_cents=mr,
                                    due_date="2026-08-20T00:00:00Z", job_name=name,
                                    rate=37250))
        gang = create_gang_with_members(stock["id"], [j["id"] for j in jobs])
        locked = lock_gang(gang["id"])
        assert locked["make_ready_total_cents"] == 100000
        allocs = {m["job_id"]: m["allocated_make_ready_cents"] for m in locked["members"]}
        # Earliest-created job (R1) receives the 1-cent remainder.
        assert allocs[jobs[0]["id"]] == 33334
        assert allocs[jobs[1]["id"]] == 33333
        assert allocs[jobs[2]["id"]] == 33333
        assert sum(allocs.values()) == 100000


class TestGangMembershipLocked:
    def test_gang_membership_mutation_when_locked_rejected(self, api):
        """PRD §3.7: "Membership mutations are permitted only while the gang
        is `FORMING`; attempting one against a `LOCKED` or `CONSUMED` gang is
        rejected with `ERR_GANG_NOT_FORMING`."

        Design: Corner/state_machines/gang_membership_mutation_when_locked_rejected
        """
        cust = create_customer(name="GL Cust")
        stock = create_stock(name="80G", cost_per_sheet_cents=9)
        j1 = _plated_job(cust, stock, quantity=4000, make_ready_cents=100000,
                         due_date="2026-08-20T00:00:00Z", job_name="G1", rate=37250,
                         finishing=["PERF"])
        j2 = _plated_job(cust, stock, quantity=6000, make_ready_cents=120000,
                         due_date="2026-08-21T00:00:00Z", job_name="G2", rate=37250,
                         finishing=["SCORE"])
        gang = create_gang_with_members(stock["id"], [j1["id"], j2["id"]])
        gang = lock_gang(gang["id"])
        resp = api.remove_gang_member(
            gang["id"], gang_member_payload(j2["id"], gang["version"]), _SCH)
        validate_error(resp, ApiErrorId.ERR_GANG_NOT_FORMING)
        after = get_success_data(api.get_gang_run(gang["id"], _SCH))
        assert len(after["members"]) == 2


class TestGangIneligibilityBeatsDueWindow:
    def _setup_mismatch_job(self):
        cust = create_customer(name="GW Cust")
        stock = create_stock(name="80G", cost_per_sheet_cents=9)
        # SHEETFED job (referential violation) due 2026-08-30 (+10 days: temporal violation)
        job = _plated_job(cust, stock, quantity=2000, make_ready_cents=80000,
                          due_date="2026-08-30T00:00:00Z", job_name="SheetJob",
                          rate=40000, press_type="SHEETFED")
        gang = create_gang_run(stock["id"], press_type="WEB",
                               anchor_due_date="2026-08-20T00:00:00Z")
        return cust, job, gang

    def test_gang_ineligibility_beats_due_window(self, api):
        """PRD §2.7: "Cross-entity referential consistency comes after that,
        then temporal rules (estimate expiry, gang due-date window, press
        window conflict)" — the referential check (press_type mismatch) is
        evaluated before the temporal check (due-date window), so the add
        fails with ERR_GANG_INELIGIBLE_JOB.

        Design: Difficulty/priority_pair_validation_conflict/gang_ineligibility_beats_due_window
        """
        _cust, job, gang = self._setup_mismatch_job()
        resp = api.add_gang_member(gang["id"], gang_member_payload(job["id"], gang["version"]), _SCH)
        validate_error(resp, ApiErrorId.ERR_GANG_INELIGIBLE_JOB)

    def test_ineligible_add_leaves_gang_unchanged(self, api):
        """PRD §3.7: "A job is eligible only if every signature of the job
        uses the gang's `paper_stock_id`, the job's `press_type` matches the
        gang's `press_type`, the job is not already a member of another gang,
        and the job's `production_status` is `PLATED` — any violation is
        rejected with `ERR_GANG_INELIGIBLE_JOB`." A rejected add must not
        append a member or bump the gang version.

        Design: Difficulty/priority_pair_validation_conflict/gang_ineligibility_beats_due_window
        """
        _cust, job, gang = self._setup_mismatch_job()
        api.add_gang_member(gang["id"], gang_member_payload(job["id"], gang["version"]), _SCH)
        after = get_success_data(api.get_gang_run(gang["id"], _SCH))
        assert len(after["members"]) == 0
        assert after["version"] == gang["version"]


class TestGangOperationErrors:
    def _locked_gang_with_press(self):
        cust = create_customer(name="GO Cust")
        stock, _po = create_received_stock(name="70U", grade="UNCOATED",
                                           cost_per_sheet_cents=5, sheets=5000)
        j1 = _plated_job(cust, stock, quantity=1000, make_ready_cents=50000,
                         due_date="2026-08-20T00:00:00Z", job_name="G1")
        j2 = _plated_job(cust, stock, quantity=1000, make_ready_cents=60000,
                         due_date="2026-08-21T00:00:00Z", job_name="G2")
        gang = create_gang_with_members(stock["id"], [j1["id"], j2["id"]])
        press = create_press(name="W1")
        return cust, stock, j1, j2, gang, press

    def test_gang_run_against_forming_gang_rejected(self, api):
        """PRD §3.7: "The gang must be `LOCKED` — scheduling against a
        non-locked gang is rejected with `ERR_GANG_NOT_LOCKED`."

        Design: Corner/errors/gang_operation_error_battery
        """
        _cust, _stock, _j1, _j2, gang, press = self._locked_gang_with_press()
        resp = api.create_press_run(
            {"press_id": press["id"], "gang_run_id": gang["id"], "run_quantity": 2000,
             "scheduled_start": "2026-08-10T08:00:00Z",
             "expected_press_version": press["version"]}, _SCH)
        validate_error(resp, ApiErrorId.ERR_GANG_NOT_LOCKED)

    def test_gang_run_quantity_must_equal_member_sum(self, api):
        """PRD §3.7: "The gang run's `run_quantity` must equal the sum of the
        member jobs' `quantity_ordered` values exactly, else
        `ERR_GANG_RUN_QUANTITY_MISMATCH`." 999 != 2000.

        Design: Corner/errors/gang_operation_error_battery
        """
        _cust, _stock, _j1, _j2, gang, press = self._locked_gang_with_press()
        lock_gang(gang["id"])
        resp = api.create_press_run(
            {"press_id": press["id"], "gang_run_id": gang["id"], "run_quantity": 999,
             "scheduled_start": "2026-08-10T08:00:00Z",
             "expected_press_version": press["version"]}, _SCH)
        validate_error(resp, ApiErrorId.ERR_GANG_RUN_QUANTITY_MISMATCH)

    def test_unlock_blocked_while_run_scheduled_then_succeeds_after_cancel(self, api):
        """PRD §3.7: "Unlocking is permitted while no `SCHEDULED` press run
        references the gang — attempting unlock with one present is rejected
        with `ERR_GANG_HAS_SCHEDULED_RUN`."

        Design: Corner/errors/gang_operation_error_battery
        """
        _cust, _stock, _j1, _j2, gang, press = self._locked_gang_with_press()
        lock_gang(gang["id"])
        run = schedule_press_run(press, gang_run_id=gang["id"], run_quantity=2000)
        r1 = api.unlock_gang_run(gang["id"], _SCH)
        validate_error(r1, ApiErrorId.ERR_GANG_HAS_SCHEDULED_RUN)
        api.cancel_press_run(run["id"], _SCH)
        r2 = api.unlock_gang_run(gang["id"], _SCH)
        data = validate_success(r2, 200)
        assert data["status"] == "FORMING"


class TestGangMembershipErrors:
    def _nine_jobs_and_two_gangs(self):
        cust = create_customer(name="GX Cust")
        stock = create_stock(name="70U", grade="UNCOATED", cost_per_sheet_cents=5)
        jobs = [_plated_job(cust, stock, quantity=100, make_ready_cents=1000,
                            job_name=f"J{i}", rate=1000) for i in range(1, 8)]
        jx = _plated_job(cust, stock, quantity=100, make_ready_cents=1000,
                         due_date="2026-08-24T00:00:00Z", job_name="JX", rate=1000)
        jy = _plated_job(cust, stock, quantity=100, make_ready_cents=1000,
                         due_date="2026-08-23T00:00:00Z", job_name="JY", rate=1000)
        ga = create_gang_run(stock["id"])
        gb = create_gang_with_members(stock["id"], [j["id"] for j in jobs[:6]])
        return jobs, jx, jy, ga, gb

    def test_seventh_member_rejected_gang_full(self, api):
        """PRD §3.7: "Locking requires at least 2 members (else
        `ERR_GANG_TOO_SMALL`) and at most 6 (else `ERR_GANG_FULL`)." The
        seventh member add is rejected.

        Design: Corner/errors/gang_membership_error_battery
        """
        jobs, _jx, _jy, _ga, gb = self._nine_jobs_and_two_gangs()
        resp = api.add_gang_member(gb["id"], gang_member_payload(jobs[6]["id"], gb["version"]), _SCH)
        validate_error(resp, ApiErrorId.ERR_GANG_FULL)

    def test_job_already_in_another_gang_ineligible(self, api):
        """PRD §3.7: "the job is not already a member of another gang" —
        violation is rejected with ERR_GANG_INELIGIBLE_JOB.

        Design: Corner/errors/gang_membership_error_battery
        """
        jobs, _jx, _jy, ga, gb = self._nine_jobs_and_two_gangs()
        resp = api.add_gang_member(ga["id"], gang_member_payload(jobs[0]["id"], ga["version"]), _SCH)
        validate_error(resp, ApiErrorId.ERR_GANG_INELIGIBLE_JOB)

    def test_due_window_plus_4_days_rejected(self, api):
        """PRD §3.7: "The job's `due_date` must also fall within three days of
        the gang's `anchor_due_date`, inclusive on both sides; a job outside
        that window is rejected with `ERR_GANG_DUE_WINDOW_EXCEEDED`."
        2026-08-24 is +4 days from the 2026-08-20 anchor.

        Design: Corner/errors/gang_membership_error_battery
        """
        _jobs, jx, _jy, ga, _gb = self._nine_jobs_and_two_gangs()
        resp = api.add_gang_member(ga["id"], gang_member_payload(jx["id"], ga["version"]), _SCH)
        validate_error(resp, ApiErrorId.ERR_GANG_DUE_WINDOW_EXCEEDED)

    def test_due_window_plus_3_days_inclusive_allowed(self, api):
        """PRD §3.7: "within three days of the gang's `anchor_due_date`,
        inclusive on both sides" — 2026-08-23 is exactly +3 days and is
        admitted.

        Design: Corner/errors/gang_membership_error_battery
        """
        _jobs, _jx, jy, ga, _gb = self._nine_jobs_and_two_gangs()
        resp = api.add_gang_member(ga["id"], gang_member_payload(jy["id"], ga["version"]), _SCH)
        data = validate_success(resp, 200)
        assert any(m["job_id"] == jy["id"] for m in data["members"])


class TestGangOCC:
    def test_occ_gang_member_add_stale_version(self, api):
        """PRD §2.4: "Adding a member job to a `FORMING` gang run must carry
        `expected_gang_run_version` matching the gang run's current
        `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        Each add bumps the gang version, so a second add carrying the
        creation-time version is rejected.

        Design: Corner/cross_cutting_layers/occ_gang_member_add_stale_version
        """
        cust = create_customer(name="OG Cust")
        stock = create_stock(name="70U", grade="UNCOATED", cost_per_sheet_cents=5)
        j1 = _plated_job(cust, stock, quantity=100, make_ready_cents=1000,
                         job_name="J1", rate=1000)
        j2 = _plated_job(cust, stock, quantity=100, make_ready_cents=1000,
                         job_name="J2", rate=1000)
        gang = create_gang_run(stock["id"])
        gv = gang["version"]
        r1 = api.add_gang_member(gang["id"], gang_member_payload(j1["id"], gv), _SCH)
        validate_success(r1, 200)
        r2 = api.add_gang_member(gang["id"], gang_member_payload(j2["id"], gv), _SCH)
        validate_error(r2, ApiErrorId.ERR_STALE_VERSION)
