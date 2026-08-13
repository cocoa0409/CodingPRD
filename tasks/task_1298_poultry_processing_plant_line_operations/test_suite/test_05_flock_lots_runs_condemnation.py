"""Flock lot booking/receiving, evisceration run gates, condemnation coding
and certification, and the yield variants."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    assert_bird_accountability,
    create_flock_lot_payload, receive_flock_lot_payload, create_line_run_payload,
    create_condemnation_record_payload, create_shift_payload,
    make_line, make_shift, fully_staffed_shift, book_and_receive_lot, queue_run,
    open_shift, create_passed_preop,
    setup_running_shift_with_run, setup_completed_run, setup_chilled_lot,
    setup_settled_lot, set_clock,
    make_qa_technician_headers, make_usda_inspector_headers,
    TEST_USERS,
)

PM = TEST_USERS["plant_manager_headers"]
SUP = TEST_USERS["shift_supervisor_headers"]
RCV = TEST_USERS["receiving_clerk_headers"]
OP = TEST_USERS["line_operator_headers"]
QA = TEST_USERS["qa_technician_headers"]


class TestBookingAndReceiving:

    def test_flock_booking_shift_aggregate_capacity(self, api):
        """PRD §3.3: "Booking enforces the shift's shackle capacity: the sum of
        `booked_head_count` across all lots of the shift, plus the new lot's
        booking, must not exceed the shift's `shackle_capacity_birds`; a total
        exactly equal to capacity is allowed, while a total strictly above it
        is rejected with `ERR_SHIFT_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/flock_booking_shift_aggregate_capacity
        """
        shift = make_shift(shift_code="NIGHT", shackle_capacity_birds=20000,
                           labor_hours_budget=50.0)
        a = validate_success(api.create_flock_lot(
            create_flock_lot_payload(shift["id"], lot_code="FL-A"), RCV), expected_status=201)
        b = validate_success(api.create_flock_lot(
            create_flock_lot_payload(shift["id"], lot_code="FL-B", grower_name="GrowerB"),
            RCV), expected_status=201)
        # Cumulative exactly at capacity (10000 + 10000 == 20000) was allowed above.
        resp = api.create_flock_lot(
            create_flock_lot_payload(shift["id"], lot_code="FL-C", grower_name="GrowerC",
                                     booked_head_count=1), RCV)
        validate_error(resp, ApiErrorId.ERR_SHIFT_CAPACITY_EXCEEDED)
        lots, meta = validate_paginated(api.list_shift_flock_lots(shift["id"], RCV))
        assert len(lots) == 2

    def test_receive_already_received_lot_rejected(self, api):
        """PRD §3.3: "A receive attempted on a lot no longer in `BOOKED` is
        rejected with `ERR_FLOCK_LOT_NOT_RECEIVABLE`."

        Design: Corner/validations/receive_already_received_lot_rejected
        """
        lot = book_and_receive_lot(make_shift()["id"])
        assert lot["status"] == "RECEIVED"
        resp = api.receive_flock_lot(
            lot["id"], receive_flock_lot_payload(head_count_received=9999, doa_count=51,
                                                 total_live_weight_lb=49999.0), RCV)
        validate_error(resp, ApiErrorId.ERR_FLOCK_LOT_NOT_RECEIVABLE)
        after = get_success_data(api.get_flock_lot(lot["id"], RCV))
        assert after["head_count_received"] == 10000  # first receipt preserved

    def test_flock_settle_reopen_resettle_cycle(self, api):
        """PRD §3.8: "Settlement is the flock lot's financial-grade close,
        performed by a `ShiftSupervisor` advancing the lot to `SETTLED` from
        `CHILLED` or `REOPENED` (any other origin state is
        `ERR_INVALID_STATE_TRANSITION`)."
        PRD §3.8: "Regrade is the regulator's prerogative: a `USDAInspector`
        may advance a `SETTLED` lot to `REOPENED` — from any other state,
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/flock_settle_reopen_resettle_cycle
        """
        env = setup_chilled_lot()
        lid = env["lot"]["id"]
        s1 = validate_success(api.advance_flock_lot(lid, {"to_status": "SETTLED"}, SUP))
        assert s1["status"] == "SETTLED"
        assert s1["certified_yield_pct"] == pytest.approx(72.0)

        s2 = validate_success(api.advance_flock_lot(
            lid, {"to_status": "REOPENED"}, make_usda_inspector_headers("usda-1")))
        assert s2["status"] == "REOPENED"

        s3 = validate_success(api.advance_flock_lot(lid, {"to_status": "SETTLED"}, SUP))
        assert s3["status"] == "SETTLED"
        assert s3["certified_yield_pct"] == pytest.approx(72.0)


class TestRunGates:

    def test_line_run_start_requires_shift_running(self, api):
        """PRD §3.4: "A `LineOperator` starts a queued run, moving it `QUEUED`
        → `RUNNING`, under four preconditions: the enclosing shift must be
        `RUNNING` (else `ERR_SHIFT_NOT_RUNNING`)".

        Design: Difficulty/cross_entity_state_dependency/line_run_start_requires_shift_running
        """
        line = make_line()
        shift = make_shift()
        lot = get_success_data(api.create_flock_lot(
            create_flock_lot_payload(shift["id"]), RCV))
        run = queue_run(shift["id"], line["id"], lot["id"])
        resp = api.advance_line_run(run["id"], {"to_status": "RUNNING"}, OP)
        validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_RUNNING)
        after = get_success_data(api.get_line_run(run["id"], OP))
        assert after["status"] == "QUEUED"

    def test_run_start_with_unreceived_lot_rejected(self, api):
        """PRD §3.4: "the flock lot must be `RECEIVED` or `ON_LINE` (else
        `ERR_RUN_NOT_STARTABLE`)".

        Design: Corner/validations/run_start_with_unreceived_lot_rejected
        """
        line = make_line()
        shift = make_shift()
        create_passed_preop(shift["id"], line["id"])
        lot = get_success_data(api.create_flock_lot(
            create_flock_lot_payload(shift["id"]), RCV))  # BOOKED, never received
        run = queue_run(shift["id"], line["id"], lot["id"])
        open_shift(shift["id"])
        resp = api.advance_line_run(run["id"], {"to_status": "RUNNING"}, OP)
        validate_error(resp, ApiErrorId.ERR_RUN_NOT_STARTABLE)
        after = get_success_data(api.get_line_run(run["id"], OP))
        assert after["status"] == "QUEUED"

    def test_run_complete_from_queued_rejected(self, api):
        """PRD §3.4: "a completion attempted from any state other than
        `RUNNING` is `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/validations/run_complete_from_queued_rejected
        """
        line = make_line()
        shift = make_shift()
        lot = get_success_data(api.create_flock_lot(
            create_flock_lot_payload(shift["id"]), RCV))
        run = queue_run(shift["id"], line["id"], lot["id"])
        resp = api.advance_line_run(
            run["id"], {"to_status": "COMPLETED", "birds_hung": 100,
                        "carcass_weight_lb": 360.0}, OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_success_data(api.get_line_run(run["id"], OP))
        assert after["status"] == "QUEUED"

    def test_run_create_lot_shift_mismatch(self, api):
        """PRD §3.4: "the lot's `receiving_shift_id` must equal the run's
        `shift_id`, else `ERR_LOT_SHIFT_MISMATCH`."

        Design: Corner/validations/run_create_lot_shift_mismatch
        """
        line = make_line()
        s1 = make_shift()
        s2 = make_shift(shift_code="NIGHT")
        lot = get_success_data(api.create_flock_lot(
            create_flock_lot_payload(s2["id"]), RCV))
        resp = api.create_line_run(
            create_line_run_payload(s1["id"], line["id"], lot["id"]), SUP)
        validate_error(resp, ApiErrorId.ERR_LOT_SHIFT_MISMATCH)

    def test_run_on_deboning_line_rejected(self, api):
        """PRD §3.4: "the line must be an `EVISCERATION` line — queuing onto a
        `DEBONING` line is rejected with `ERR_LINE_TYPE_MISMATCH`".

        Design: Corner/validations/run_on_deboning_line_rejected
        """
        db_line = make_line(line_code="DB-1", line_type="DEBONING", rated_speed_bpm=50)
        shift = make_shift()
        lot = get_success_data(api.create_flock_lot(
            create_flock_lot_payload(shift["id"]), RCV))
        resp = api.create_line_run(
            create_line_run_payload(shift["id"], db_line["id"], lot["id"],
                                    planned_speed_bpm=45), SUP)
        validate_error(resp, ApiErrorId.ERR_LINE_TYPE_MISMATCH)


class TestCondemnationAccounting:

    def test_run_auto_reconciles_when_last_record_certified(self, api):
        """PRD §3.4: "Second, if every condemnation record of the run is now
        `CERTIFIED`, the run moves automatically from `COMPLETED` to
        `RECONCILED`, rolling its totals into the lot's certified aggregates."

        Design: Corner/state_machines/run_auto_reconciles_when_last_record_certified
        """
        env = setup_completed_run(completion_clock=None, condemnation=40,
                                  condemn_user_id="qa-1")
        record = env["record"]
        get_success_data(api.advance_condemnation_record(
            record["id"], {"to_status": "CERTIFIED"}, make_usda_inspector_headers("usda-1")))
        run = get_success_data(api.get_line_run(env["run"]["id"], OP))
        assert run["status"] == "RECONCILED"

    def test_condemnation_certified_disputed_recertified_cycle(self, api):
        """PRD §3.4: "The regrade cycle runs through dispute and
        recertification. A `PlantManager` may advance a `CERTIFIED` record to
        `DISPUTED`, supplying a `reason` (absent, `ERR_INVALID_REQUEST`).
        Dispute is compensating bookkeeping: `DISPUTED` records are excluded
        from `condemned_accounted`".
        PRD §3.4: "A `USDAInspector` recertifies a `DISPUTED` record back to
        `CERTIFIED`, optionally supplying an `amended_carcass_count` greater
        than zero".
        PRD §3.4: "its `effective_count` is its `amended_carcass_count` when
        one has been supplied, otherwise its `carcass_count`."

        Design: Difficulty/non_linear_state_machine/condemnation_certified_disputed_recertified_cycle
        """
        env = setup_completed_run(completion_clock=None, condemnation=100,
                                  condemn_user_id="qa-1")
        cid = env["record"]["id"]
        usda = make_usda_inspector_headers("usda-1")

        c = validate_success(api.advance_condemnation_record(cid, {"to_status": "CERTIFIED"}, usda))
        assert c["status"] == "CERTIFIED"

        d = validate_success(api.advance_condemnation_record(
            cid, {"to_status": "DISPUTED", "reason": "regrade requested by plant"}, PM))
        assert d["status"] == "DISPUTED"
        lot = get_success_data(api.get_flock_lot(env["lot"]["id"], PM))
        assert lot["condemned_accounted"] == 0  # DISPUTED excluded

        r = validate_success(api.advance_condemnation_record(
            cid, {"to_status": "CERTIFIED", "amended_carcass_count": 120}, usda))
        assert r["status"] == "CERTIFIED"
        assert r["effective_count"] == 120
        lot = get_success_data(api.get_flock_lot(env["lot"]["id"], PM))
        assert lot["condemned_accounted"] == 120

    def test_bird_accountability_conserved_on_certify_dispute(self, api):
        """PRD §3.4: "The conservation invariant underneath all of this is bird
        accountability: at all times a run's `birds_hung` equals its condemned
        birds (the sum of `effective_count` over records in `DRAFT` or
        `CERTIFIED`) plus its `carcasses_to_chill`, and certifying then
        disputing the same record leaves `carcasses_to_chill` exactly
        unchanged."

        Design: Difficulty/compensating_invariant/bird_accountability_conserved_on_certify_dispute
        """
        env = setup_completed_run(completion_clock=None, condemnation=100,
                                  condemn_user_id="qa-1")
        cid = env["record"]["id"]
        lot_id = env["lot"]["id"]

        get_success_data(api.advance_condemnation_record(
            cid, {"to_status": "CERTIFIED"}, make_usda_inspector_headers("usda-1")))
        lot = get_success_data(api.get_flock_lot(lot_id, PM))
        assert lot["condemned_accounted"] == 100
        assert lot["carcasses_to_chill"] == 9850
        assert_bird_accountability(lot)

        get_success_data(api.advance_condemnation_record(
            cid, {"to_status": "DISPUTED", "reason": "retain for regrade"}, PM))
        lot = get_success_data(api.get_flock_lot(lot_id, PM))
        assert lot["condemned_accounted"] == 0
        assert lot["carcasses_to_chill"] == 9950  # restored by the compensating dispute
        assert_bird_accountability(lot)

    def test_sod_condemnation_self_certify_rejected(self, api):
        """PRD §3.4: "Certification belongs to the `USDAInspector`, under
        segregation of duties: the certifier's `X-User-ID` must differ from the
        record's `recorded_by_user_id` — a recorder may never certify their own
        record, rejected with `ERR_SOD_CONDEMNATION_SELF_CERTIFY`."

        Design: Corner/validations/sod_condemnation_self_certify_rejected
        """
        env = setup_completed_run(completion_clock=None, condemnation=25,
                                  condemn_user_id="insp-1")
        cid = env["record"]["id"]
        # Same operator id that recorded the record, now holding USDAInspector role
        resp = api.advance_condemnation_record(
            cid, {"to_status": "CERTIFIED"}, make_usda_inspector_headers("insp-1"))
        validate_error(resp, ApiErrorId.ERR_SOD_CONDEMNATION_SELF_CERTIFY)
        after = get_success_data(api.get_condemnation_record(cid, QA))
        assert after["status"] == "DRAFT"

    def test_line_operator_cannot_certify_condemnation(self, api):
        """PRD §3.4: "Certification belongs to the `USDAInspector`".
        PRD §2.1: "An authenticated operator who attempts an operation outside
        their role's mandate is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)".

        Design: Corner/rbac/line_operator_cannot_certify_condemnation
        """
        env = setup_completed_run(completion_clock=None, condemnation=10,
                                  condemn_user_id="qa-1")
        resp = api.advance_condemnation_record(
            env["record"]["id"], {"to_status": "CERTIFIED"}, OP)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        after = get_success_data(api.get_condemnation_record(env["record"]["id"], QA))
        assert after["status"] == "DRAFT"

    def test_condemnation_total_cannot_exceed_birds_hung(self, api):
        """PRD §3.4: "Certification also passes a numerical gate: the sum of
        `effective_count` over the run's already-`CERTIFIED` records, plus the
        `effective_count` of the record being certified, must be no greater
        than the run's `birds_hung` — equality allowed — with `DRAFT` and
        `DISPUTED` records not participating in the gate; a violation is
        `ERR_CONDEMNATION_COUNT_EXCEEDS_HUNG`."

        Design: Corner/validations/condemnation_total_cannot_exceed_birds_hung
        """
        env = setup_completed_run(completion_clock=None)
        rid = env["run"]["id"]
        qa_recorder = make_qa_technician_headers("qa-1")
        usda = make_usda_inspector_headers("usda-1")

        rec_a = get_success_data(api.create_condemnation_record(
            create_condemnation_record_payload(rid, carcass_count=9900), qa_recorder))
        get_success_data(api.advance_condemnation_record(
            rec_a["id"], {"to_status": "CERTIFIED"}, usda))

        # 9900 CERTIFIED + 100 would total 10000 > 9950 birds_hung -> rejected
        rec_b = get_success_data(api.create_condemnation_record(
            create_condemnation_record_payload(rid, condemnation_code="BRUISING",
                                               carcass_count=100), qa_recorder))
        resp = api.advance_condemnation_record(rec_b["id"], {"to_status": "CERTIFIED"}, usda)
        validate_error(resp, ApiErrorId.ERR_CONDEMNATION_COUNT_EXCEEDS_HUNG)
        b_after = get_success_data(api.get_condemnation_record(rec_b["id"], QA))
        assert b_after["status"] == "DRAFT"

        # 9900 + 50 == 9950 -> equality allowed
        rec_c = get_success_data(api.create_condemnation_record(
            create_condemnation_record_payload(rid, condemnation_code="CONTAMINATION",
                                               carcass_count=50), qa_recorder))
        certified = validate_success(api.advance_condemnation_record(
            rec_c["id"], {"to_status": "CERTIFIED"}, usda))
        assert certified["status"] == "CERTIFIED"


class TestYieldVariants:

    def test_provisional_yield_literal_after_completion(self, api):
        """PRD §3.4: "It is an eviscerated-basis estimate: take the lot's
        `birds_hung_total` minus the provisional condemnation count (the sum of
        `effective_count` over records in `DRAFT` or `DISPUTED`), multiply by
        the eviscerated-basis allowance — 0.88 times the average live weight
        per bird, where the average live weight is the lot's
        `total_live_weight_lb` divided by its `head_count_received` — divide by
        `total_live_weight_lb`, multiply by 100 to express a percentage, and
        round half-up to two decimal places."

        Design: Corner/calculations/provisional_yield_literal_after_completion
        """
        env = setup_completed_run(completion_clock=None)
        lot = get_success_data(api.get_flock_lot(env["lot"]["id"], PM))
        # 9950 * (5.0 * 0.88) / 50000 * 100 = 87.56
        assert lot["provisional_yield_pct"] == pytest.approx(87.56)
        assert lot["birds_hung_total"] == 9950
        assert lot["carcasses_to_chill"] == 9950

    def test_flock_yield_provisional_vs_certified_diverge(self, api):
        """PRD §3.8: "Because the provisional variant uses the eviscerated
        basis with its 0.88 allowance and provisional condemnation counts while
        the certified variant uses measured carcass weight and certified counts
        only, the same data yields two different numbers by design."
        PRD §3.8: "The certified yield is the live-basis counterpart of the
        provisional figure of §3.4, computed over the same recorded data but
        through a different lens: from the lot's `carcass_weight_total_lb`,
        subtract the certified condemnation count — the sum of `effective_count`
        over records in `CERTIFIED` — multiplied by the average carcass weight".

        Design: Difficulty/dual_variant_calc/flock_yield_provisional_vs_certified_diverge
        """
        env = setup_completed_run(completion_clock="2026-08-01T06:00:00Z",
                                  condemnation=100, condemn_user_id="qa-1")
        lot = get_success_data(api.get_flock_lot(env["lot"]["id"], QA))
        # Provisional: (9950 - 100) * (5.0 * 0.88) / 50000 * 100 = 86.68
        assert lot["provisional_yield_pct"] == pytest.approx(86.68)

        get_success_data(api.advance_condemnation_record(
            env["record"]["id"], {"to_status": "CERTIFIED"},
            make_usda_inspector_headers("usda-1")))
        set_clock("2026-08-01T10:00:00Z")
        settled = validate_success(api.advance_flock_lot(
            env["lot"]["id"], {"to_status": "SETTLED"}, SUP))
        assert settled["status"] == "SETTLED"
        # Certified: (36000 - 100 * (36000/9950)) / 50000 * 100 = 71.28
        assert settled["certified_yield_pct"] == pytest.approx(71.28)
        # Both variants coexist on the same lot and differ
        assert settled["provisional_yield_pct"] == pytest.approx(86.68)

    def test_settle_with_draft_record_rejected(self, api):
        """PRD §3.8: "Settlement requires every condemnation record on the
        lot's runs to be `CERTIFIED` and at least one run of the lot to be
        `RECONCILED`, else `ERR_LOT_NOT_SETTLABLE`."

        Design: Corner/validations/settle_with_draft_record_rejected
        """
        env = setup_chilled_lot(condemnation=30, condemn_user_id="qa-1")
        assert env["lot"]["status"] == "CHILLED"
        resp = api.advance_flock_lot(env["lot"]["id"], {"to_status": "SETTLED"}, SUP)
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_SETTLABLE)
        after = get_success_data(api.get_flock_lot(env["lot"]["id"], PM))
        assert after["status"] == "CHILLED"
