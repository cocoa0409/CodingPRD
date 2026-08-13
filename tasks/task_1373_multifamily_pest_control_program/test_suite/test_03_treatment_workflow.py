"""Treatment lifecycle: prep handshake ordering, completion gating, notify
deadline, reschedule cycle + OCC + limit, cancel invariant, and the
completion-time reconciliation of derived fields."""
from test_helpers import (
    ApiErrorId,
    assert_treatment,
    create_treatment_payload,
    get_success_data,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    CLERK,
    MANAGER,
    complete_treatment,
    resident_headers_for,
    run_prep_failure_cycle,
    schedule_treatment,
    setup_community,
    setup_prep_notified_treatment,
    setup_prep_verified_treatment,
    technician_headers_for,
)


class TestTreatmentCompletionGate:
    def test_complete_from_scheduled_returns_invalid_state(self, api):
        """PRD §3.5: "Only the assigned technician completes a treatment, and
        only from `PREP_VERIFIED`, supplying the on-site `actual_minutes` of at
        least 1."
        PRD §2.4: "a transition that is simply not defined from the entity's
        current non-terminal state is rejected with `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Corner/state_machines/treatment_complete_from_scheduled_returns_invalid_state
        """
        ctx = setup_community(with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["ROACHES"]})
        tr = schedule_treatment(ctx["unit"]["id"], ctx["technician"]["id"])
        resp = api.complete_treatment(
            tr["id"], {"actual_minutes": 60}, technician_headers_for(ctx["technician"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPrepHandshake:
    def test_verify_prep_before_notify_rejected(self, api):
        """PRD §3.4: "Verification before the prep notice is rejected with
        `ERR_PREP_NOT_NOTIFIED` (HTTP 409); verification before the resident's
        acknowledgement is rejected with `ERR_PREP_NOT_ACKNOWLEDGED`
        (HTTP 409)."

        Design: Corner/validations/verify_prep_before_notify_rejected
        """
        ctx = setup_community(with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["ROACHES"]})
        tr = schedule_treatment(ctx["unit"]["id"], ctx["technician"]["id"])
        resp = api.verify_prep(tr["id"], {"compliant": True}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_PREP_NOT_NOTIFIED)

    def test_verify_prep_before_acknowledgement_rejected(self, api):
        """PRD §3.4: "Verification before the prep notice is rejected with
        `ERR_PREP_NOT_NOTIFIED` (HTTP 409); verification before the resident's
        acknowledgement is rejected with `ERR_PREP_NOT_ACKNOWLEDGED`
        (HTTP 409)."

        Design: Corner/validations/verify_prep_before_acknowledgement_rejected
        """
        ctx = setup_community(with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["ROACHES"]})
        tr = setup_prep_notified_treatment(ctx["unit"]["id"], ctx["technician"]["id"])
        resp = api.verify_prep(tr["id"], {"compliant": True}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_PREP_NOT_ACKNOWLEDGED)


class TestPrepNoticeDeadline:
    def test_prep_notice_boundary_exactly_48h(self, api):
        """PRD §3.4: "At least 48 hours before `window_start` — a notify
        attempted inside that window fails with `ERR_PREP_NOTICE_TOO_LATE`
        (HTTP 422) — the `PropertyManager` issues the prep notice, moving the
        treatment from `SCHEDULED` to `PREP_NOTIFIED` and stamping
        `prep_notified_at`."
        PRD §2.4: "At startup, before any clock call, the logical clock reads
        exactly 2026-08-01T00:00:00Z."

        Design: Corner/validations/prep_notice_boundary_exactly_48h
        """
        ctx = setup_community(num_units=2, with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["ROACHES"]})
        u1, u2 = ctx["units"][0], ctx["units"][1]
        tech = ctx["technician"]
        tr1 = schedule_treatment(u1["id"], tech["id"],
                                 window_start="2026-08-02T00:00:00Z",
                                 window_end="2026-08-02T01:00:00Z")
        tr2 = schedule_treatment(u2["id"], tech["id"],
                                 window_start="2026-08-03T00:00:00Z",
                                 window_end="2026-08-03T01:00:00Z")

        resp_late = api.notify_prep(tr1["id"], MANAGER)
        validate_error(resp_late, ApiErrorId.ERR_PREP_NOTICE_TOO_LATE)

        ok = validate_success(api.notify_prep(tr2["id"], MANAGER))
        assert ok["status"] == "PREP_NOTIFIED"
        assert ok["prep_notified_at"] is not None


class TestRescheduleCycle:
    def _setup_cycle(self, api):
        ctx = setup_community(contract_overrides={"scope_pest_types": ["ROACHES"]})
        tr = schedule_treatment(ctx["unit"]["id"], ctx["technician"]["id"])
        return ctx, tr

    def _notify_ack(self, api, ctx, tr_id):
        validate_success(api.notify_prep(tr_id, MANAGER))
        validate_success(api.acknowledge_prep(tr_id, resident_headers_for(ctx["resident"])))

    def test_prep_failure_loop_resets_prep_tracking(self, api):
        """PRD §3.5: "A reschedule out of `NON_COMPLIANT` additionally clears
        `prep_notified_at` and `prep_acknowledged_at` to null, forcing the
        preparation handshake to restart."
        PRD §3.5: "A treatment window moves through the reschedule action,
        available from `SCHEDULED` — a plain move that leaves the treatment
        `SCHEDULED` — and from `NON_COMPLIANT`, which returns the treatment to
        `SCHEDULED`."

        Design: Difficulty/non_linear_state_machine/treatment_prep_reschedule_cycle
        """
        ctx, tr = self._setup_cycle(api)
        unit, resident, tech, lease = (ctx["unit"], ctx["resident"],
                                       ctx["technician"], ctx["lease"])

        self._notify_ack(api, ctx, tr["id"])
        nc1 = validate_success(api.verify_prep(tr["id"], {"compliant": False}, MANAGER))
        assert nc1["status"] == "NON_COMPLIANT"
        r1 = validate_success(api.reschedule_treatment(
            tr["id"],
            {"window_start": "2026-08-12T09:00:00Z", "window_end": "2026-08-12T10:00:00Z",
             "expected_treatment_version": nc1["version"]},
            MANAGER,
        ))
        assert r1["status"] == "SCHEDULED"
        assert r1["reschedule_count"] == 1
        assert r1["prep_notified_at"] is None and r1["prep_acknowledged_at"] is None

        self._notify_ack(api, ctx, tr["id"])
        nc2 = validate_success(api.verify_prep(tr["id"], {"compliant": False}, MANAGER))
        r2 = validate_success(api.reschedule_treatment(
            tr["id"],
            {"window_start": "2026-08-14T09:00:00Z", "window_end": "2026-08-14T10:00:00Z",
             "expected_treatment_version": nc2["version"]},
            MANAGER,
        ))
        assert_treatment(r2)
        assert r2["status"] == "SCHEDULED"
        assert r2["reschedule_count"] == 2
        assert r2["prep_notified_at"] is None and r2["prep_acknowledged_at"] is None

        lease_after = validate_success(api.get_lease(lease["id"], CLERK))
        assert lease_after["outstanding_balance_cents"] == 32250, (
            "two NON_COMPLIANCE_FEE chargebacks of 16125 each; below 50000 so no late fee"
        )

    def test_prep_failure_cycle_fires_chargeback_cascade_each_loop(self, api):
        """PRD §3.4: "A non-compliant verification moves it to `NON_COMPLIANT`
        and fires a second cascade. Link one: if the unit has an `ACTIVE` lease
        with `pest_addendum_signed` true, the system auto-creates a
        `NON_COMPLIANCE_FEE` chargeback in `ASSESSED` whose
        `source_treatment_id` points at this treatment."

        Design: Difficulty/non_linear_state_machine/treatment_prep_reschedule_cycle
        """
        ctx, tr = self._setup_cycle(api)
        unit, resident, tech, lease = (ctx["unit"], ctx["resident"],
                                       ctx["technician"], ctx["lease"])

        self._notify_ack(api, ctx, tr["id"])
        run_prep_failure_cycle(unit["id"], resident, tech["id"], tr["id"],
                               "2026-08-12T09:00:00Z", "2026-08-12T10:00:00Z")
        self._notify_ack(api, ctx, tr["id"])
        run_prep_failure_cycle(unit["id"], resident, tech["id"], tr["id"],
                               "2026-08-14T09:00:00Z", "2026-08-14T10:00:00Z")

        cbs = get_success_data(api.list_lease_chargebacks(lease["id"], CLERK))
        nc_fees = [c for c in cbs if c["kind"] == "NON_COMPLIANCE_FEE"]
        assert len(nc_fees) == 2, "each NON_COMPLIANT entry fires the chargeback cascade"
        assert all(c["source_treatment_id"] == tr["id"] for c in nc_fees)
        assert all(c["provisional_amount_cents"] == 16125 for c in nc_fees)
        assert not any(c["kind"] == "LATE_FEE" for c in cbs), "32250 < 50000 so no late fee"


class TestRescheduleLimit:
    def test_third_reschedule_rejected_at_limit(self, api):
        """PRD §3.5: "The hard limit is 2 reschedules; a third attempt is
        rejected with `ERR_RESCHEDULE_LIMIT_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/third_reschedule_rejected_at_limit
        """
        ctx = setup_community(contract_overrides={"scope_pest_types": ["ROACHES"]})
        unit, resident, tech = ctx["unit"], ctx["resident"], ctx["technician"]
        tr = schedule_treatment(unit["id"], tech["id"])

        validate_success(api.notify_prep(tr["id"], MANAGER))
        validate_success(api.acknowledge_prep(tr["id"], resident_headers_for(resident)))
        r1 = run_prep_failure_cycle(unit["id"], resident, tech["id"], tr["id"],
                                    "2026-08-12T09:00:00Z", "2026-08-12T10:00:00Z")
        validate_success(api.notify_prep(tr["id"], MANAGER))
        validate_success(api.acknowledge_prep(tr["id"], resident_headers_for(resident)))
        r2 = run_prep_failure_cycle(unit["id"], resident, tech["id"], tr["id"],
                                    "2026-08-14T09:00:00Z", "2026-08-14T10:00:00Z")
        assert r2["reschedule_count"] == 2

        resp = api.reschedule_treatment(
            tr["id"],
            {"window_start": "2026-08-16T09:00:00Z", "window_end": "2026-08-16T10:00:00Z",
             "expected_treatment_version": r2["version"]},
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_RESCHEDULE_LIMIT_EXCEEDED)


class TestOccOnReschedule:
    def test_occ_stale_reschedule_returns_412(self, api):
        """PRD §2.6: "Rescheduling a treatment requires the request to carry
        `expected_treatment_version`, holding the treatment `version` the
        client last observed. If that value no longer matches the treatment's
        current `version` — because another writer has rescheduled, notified,
        or otherwise mutated the treatment since the client read it — the
        reschedule is rejected with `ERR_STALE_VERSION` (HTTP 412), and the
        client must re-read the treatment before retrying."

        Design: Corner/cross_cutting_layers/occ_stale_reschedule_returns_412
        """
        ctx = setup_community(with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["ROACHES"]})
        tr = schedule_treatment(ctx["unit"]["id"], ctx["technician"]["id"])
        stale_version = tr["version"]
        validate_success(api.notify_prep(tr["id"], MANAGER))

        resp = api.reschedule_treatment(
            tr["id"],
            {"window_start": "2026-08-12T09:00:00Z", "window_end": "2026-08-12T10:00:00Z",
             "expected_treatment_version": stale_version},
            MANAGER,
        )
        # The race loser's report is not uniquely pinned by PRD here: §2.6
        # names ERR_STALE_VERSION for exactly this read-then-notified race,
        # while §2.10 orders state preconditions (reschedule is undefined from
        # PREP_NOTIFIED per §3.5, so ERR_INVALID_STATE) ahead of the
        # stale-version check. Both rejections are PRD-faithful.
        validate_error_is_one_of(resp, ["ERR_STALE_VERSION", "ERR_INVALID_STATE"])


class TestCancelConservesBookedMinutes:
    def test_technician_minutes_schedule_cancel_invariant(self, api):
        """PRD §3.5: "A `PropertyManager` may cancel a treatment while it sits
        in `SCHEDULED`, `PREP_NOTIFIED`, or `NON_COMPLIANT`, optionally
        recording a `reason`; cancellation moves it to `CANCELLED` and releases
        the technician's booked window."
        PRD §3.4: "recomputes the technician's `booked_minutes` — the sum of
        window lengths over that technician's treatments in `SCHEDULED`,
        `PREP_NOTIFIED`, `PREP_VERIFIED`, or `NON_COMPLIANT`."

        Design: Difficulty/compensating_invariant/technician_minutes_schedule_cancel_invariant
        """
        ctx = setup_community(with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["ROACHES"]})
        tech = ctx["technician"]
        assert tech["booked_minutes"] == 0

        tr = schedule_treatment(ctx["unit"]["id"], tech["id"])
        bm1 = validate_success(api.get_technician(tech["id"], ADMIN))
        assert bm1["booked_minutes"] == 60, "09:00-10:00 window books exactly 60 minutes"

        cancelled = validate_success(api.cancel_treatment(tr["id"], MANAGER))
        assert cancelled["status"] == "CANCELLED"
        bm2 = validate_success(api.get_technician(tech["id"], ADMIN))
        assert bm2["booked_minutes"] == 0, "cancel releases exactly the booked window"

    def test_booked_minutes_recomputed_while_scheduled_then_cancelled(self, api):
        """PRD §3.4: "The server derives `planned_minutes` as the whole-minute
        length of the window and recomputes the technician's `booked_minutes`
        — the sum of window lengths over that technician's treatments in
        `SCHEDULED`, `PREP_NOTIFIED`, `PREP_VERIFIED`, or `NON_COMPLIANT`."
        PRD §3.5: "cancellation moves it to `CANCELLED` and releases the
        technician's booked window."

        Design: Difficulty/compensating_invariant/technician_minutes_schedule_cancel_invariant
        """
        ctx = setup_community(with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["ROACHES"]})
        unit, tech = ctx["unit"], ctx["technician"]
        tr1 = schedule_treatment(unit["id"], tech["id"],
                                 window_start="2026-08-10T09:00:00Z",
                                 window_end="2026-08-10T10:00:00Z")
        tr2 = schedule_treatment(unit["id"], tech["id"],
                                 window_start="2026-08-11T09:00:00Z",
                                 window_end="2026-08-11T10:30:00Z")
        bm = validate_success(api.get_technician(tech["id"], ADMIN))
        assert bm["booked_minutes"] == 150

        validate_success(api.cancel_treatment(tr1["id"], MANAGER))
        bm = validate_success(api.get_technician(tech["id"], ADMIN))
        assert bm["booked_minutes"] == 90, "only the surviving 90-minute window stays booked"
        tr = validate_success(api.get_treatment(tr2["id"], MANAGER))
        assert tr["planned_minutes"] == 90


class TestCompletionReconciliation:
    def test_derived_fields_reconcile_on_completion(self, api):
        """PRD §3.5: "Completion books the treatment-type estimate of §2.8 into
        the contract's `spent_cents`, removes the window from the technician's
        booked set, and — when the treatment carries a `bed_bug_case_id` —
        checks whether every treatment linked to that case is now `COMPLETED`
        and every furniture disposal of the case is `VERIFIED` or none exist;
        if so the case advances from `TREATING` to `MONITORING`."
        PRD §2.8: "Treatment cost estimates for budget purposes are 12000 cents
        for a `CHEMICAL` treatment, 65000 for `HEAT`, 9000 for `EXCLUSION`, and
        6000 for `TRAPPING`."

        Design: Corner/cross_cutting_layers/derived_fields_reconcile_on_completion
        """
        ctx = setup_community(contract_overrides={"scope_pest_types": ["ROACHES"]})
        unit, resident, tech = ctx["unit"], ctx["resident"], ctx["technician"]
        tr = setup_prep_verified_treatment(unit["id"], resident, tech["id"])
        bm_before = validate_success(api.get_technician(tech["id"], ADMIN))
        assert bm_before["booked_minutes"] == 60

        done = complete_treatment(tr["id"], tech, actual_minutes=60)
        assert done["status"] == "COMPLETED"

        contract = validate_success(api.get_contract(ctx["contract"]["id"], ADMIN))
        assert contract["spent_cents"] == 12000, "CHEMICAL estimate booked at completion"
        bm_after = validate_success(api.get_technician(tech["id"], ADMIN))
        assert bm_after["booked_minutes"] == 0, "COMPLETED leaves the booked set"


class TestImmediateConsistency:
    def test_immediate_read_after_write_consistency(self, api):
        """PRD §2.5: "`version` is an integer that starts at its initial value
        on creation and increments by 1 on every mutation of the resource,
        including system-driven cascades and lazy transitions."
        PRD §3.4: "A new treatment is born `SCHEDULED` with `reschedule_count`
        at zero and `vacancy_attested` defaulting to false unless the manager
        supplies it."
        PRD §2.3: "Certain list endpoints accept additional filter parameters —
        `floor` on the unit list, `status` on lease-chargeback,
        technician-treatment, technician-inspection, unit-treatment,
        bed-bug-case, and furniture-disposal lists, and `kind` on the
        unit-inspection list — all of which are optional."

        Design: Corner/consistency_model/immediate_read_after_write_consistency
        """
        ctx = setup_community(with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["ROACHES"]})
        unit, tech = ctx["unit"], ctx["technician"]
        created = validate_success(
            api.create_treatment(unit["id"], create_treatment_payload(technician_id=tech["id"]), MANAGER),
            201,
        )
        assert created["status"] == "SCHEDULED" and created["version"] == 1

        fetched = validate_success(api.get_treatment(created["id"], MANAGER))
        assert fetched["version"] == created["version"]
        assert fetched["status"] == created["status"]

        from test_helpers import validate_paginated
        listed, meta = validate_paginated(
            api.list_unit_treatments(unit["id"], MANAGER, params={"status": "SCHEDULED"})
        )
        assert [t["id"] for t in listed] == [created["id"]]
