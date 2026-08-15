"""Excavation gates: permit, easements, permit-window coverage, precedence,
change-order freeze, reopen cycle, and restoration-blocked closure.

PRD §3.3 (five excavation gates, reopen, closure), §2.7 (posture/freeze),
§2.10 (referential before temporal).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_change_order_payload,
    create_easement_payload,
    create_restoration_task_payload,
    schedule_segment_payload,
    setup_mobilized_project,
    create_scheduled_segment,
    create_issued_permit,
    lifecycle,
    transition_segment,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["pm_headers"]
ROW = TEST_USERS["row_headers"]
CONTRACTOR = TEST_USERS["contractor_headers"]


def _trenching_base(api, name, easement="recorded", permit=None):
    """Mobilized 2-party project driven to TRENCHING with a scheduled segment.

    easement: "recorded" | "signed" | "refused"
    permit: None (no permit) | "issued" | ("issued", valid_from, valid_to)
    Returns (project, parts, parcel, segment).
    """
    project, parts = setup_mobilized_project(
        [
            {"utility_name": "U1", "utility_type": "ELECTRIC", "cost_share_bp": 7000, "sequence_order": 1},
            {"utility_name": "U2", "utility_type": "TELECOM", "cost_share_bp": 3000, "sequence_order": 2},
        ],
        name=name, rule20_credit_cents=0, estimated_total_cost_cents=1000000,
        target_cutover_on="2026-12-31T00:00:00Z", contingency_days=0,
    )
    parcel = validate_success(api.create_parcel(
        {"project_id": project["id"], "address": "9 Ash St", "owner_name": "Owner Nine",
         "existing_panel_amps": 200, "load_calc_amps": 100}, ROW), 201)
    es = validate_success(api.create_easement(
        create_easement_payload(parcel["id"], easement_type="TRENCH"), ROW), 201)
    es = validate_success(api.transition_easement(es["id"], {"to": "REQUESTED"}, ROW), 200)
    if easement == "recorded":
        es = validate_success(api.transition_easement(es["id"], {"to": "SIGNED"}, ROW), 200)
        es = validate_success(api.transition_easement(es["id"], {"to": "RECORDED"}, ROW), 200)
    elif easement == "signed":
        es = validate_success(api.transition_easement(es["id"], {"to": "SIGNED"}, ROW), 200)
    elif easement == "refused":
        es = validate_success(api.transition_easement(es["id"], {"to": "REFUSED"}, ROW), 200)

    if permit == "issued":
        create_issued_permit(project["id"])
    elif isinstance(permit, tuple):
        _tag, valid_from, valid_to = permit
        create_issued_permit(project["id"], valid_from=valid_from, valid_to=valid_to)

    seg = create_scheduled_segment(project["id"], parcel_ids=[parcel["id"]])
    lifecycle(project["id"], "START_TRENCHING")
    return project, parts, parcel, seg


class TestExcavationPermitGate:
    def test_excavation_blocked_without_issued_permit(self, api):
        """PRD §3.3: "Moving `SCHEDULED → EXCAVATING` enforces five gates: the
        project must be `TRENCHING`; the segment must not be frozen
        (`ERR_CHANGE_ORDER_FREEZE`); no parcel in `parcel_ids` may hold a
        `TRENCH` easement in `REFUSED` (`ERR_EASEMENT_REFUSED_BLOCKING`);
        every parcel in `parcel_ids` must hold a `TRENCH` easement in
        `RECORDED` (`ERR_EASEMENT_NOT_RECORDED`); an `ENCROACHMENT` permit in
        `ISSUED` status must exist for the project (`ERR_PERMIT_NOT_ISSUED`);
        and that permit's validity window must cover the whole excavation
        window, both endpoints inclusive (`ERR_PERMIT_WINDOW_VIOLATION`)."

        Design: Difficulty/cross_entity_state_dependency/excavation_requires_issued_permit
        """
        _project, _parts, _parcel, seg = _trenching_base(api, "Gate Project", permit=None)
        resp = api.transition_trench_segment(seg["id"], {"to": "EXCAVATING"}, PM)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ISSUED)

    def test_excavation_succeeds_once_permit_issued(self, api):
        """PRD §3.3: "an `ENCROACHMENT` permit in `ISSUED` status must exist
        for the project (`ERR_PERMIT_NOT_ISSUED`); and that permit's validity
        window must cover the whole excavation window, both endpoints inclusive
        (`ERR_PERMIT_WINDOW_VIOLATION`)."

        Design: Difficulty/cross_entity_state_dependency/excavation_requires_issued_permit
        """
        _project, _parts, _parcel, seg = _trenching_base(api, "Gate Project", permit=None)
        validate_error(
            api.transition_trench_segment(seg["id"], {"to": "EXCAVATING"}, PM),
            ApiErrorId.ERR_PERMIT_NOT_ISSUED,
        )
        create_issued_permit(_project["id"])
        resp = api.transition_trench_segment(seg["id"], {"to": "EXCAVATING"}, PM)
        data = validate_success(resp, 200)
        assert data["status"] == "EXCAVATING"


class TestEasementGate:
    def test_easement_signed_but_not_recorded_blocks_excavation(self, api):
        """PRD §3.3: "every parcel in `parcel_ids` must hold a `TRENCH`
        easement in `RECORDED` (`ERR_EASEMENT_NOT_RECORDED`)".

        Design: Corner/validations/easement_signed_but_not_recorded_blocks_excavation
        """
        _project, _parts, _parcel, seg = _trenching_base(
            api, "V11", easement="signed", permit="issued")
        resp = api.transition_trench_segment(seg["id"], {"to": "EXCAVATING"}, PM)
        validate_error(resp, ApiErrorId.ERR_EASEMENT_NOT_RECORDED)


class TestPermitWindowGate:
    def test_permit_window_must_cover_excavation(self, api):
        """PRD §3.3: "and that permit's validity window must cover the whole
        excavation window, both endpoints inclusive
        (`ERR_PERMIT_WINDOW_VIOLATION`)."

        Design: Corner/validations/permit_window_must_cover_excavation
        """
        _project, _parts, _parcel, seg = _trenching_base(
            api, "V12", easement="recorded",
            permit=("issued", "2026-08-01T00:00:00Z", "2026-09-05T00:00:00Z"))
        resp = api.transition_trench_segment(seg["id"], {"to": "EXCAVATING"}, PM)
        validate_error(resp, ApiErrorId.ERR_PERMIT_WINDOW_VIOLATION)


class TestReferentialPreemptsTemporal:
    def test_refused_easement_preempts_permit_window_violation(self, api):
        """PRD §2.10: "Only then does the server evaluate, in order: optimistic
        concurrency mismatches (`ERR_STALE_VERSION`); state-machine legality,
        including terminal-state lockdown (`ERR_INVALID_STATE`, HTTP 409);
        posture and freeze gates (`ERR_POSTURE_FROZEN`, `ERR_CHANGE_ORDER_FREEZE`);
        business safety rules such as trench geometry and outage coverage;
        referential gates such as easements and permits; temporal gates such as
        permit windows, slot windows, notification lead time, and warranty
        deadlines; capacity and constraint checks such as slot conflicts, crew
        capacity, and panel sizing; and finally the fiscal rules — share sums,
        exact payment amounts, and segregation of duties."
        With a REFUSED TRENCH easement and a too-short permit window both
        present, the referential easement error is the one reported.

        Design: Difficulty/priority_pair_validation_conflict/referential_preempts_temporal_on_excavation
        """
        _project, _parts, _parcel, seg = _trenching_base(
            api, "Prio2 Project", easement="refused",
            permit=("issued", "2026-08-01T00:00:00Z", "2026-09-05T00:00:00Z"))
        resp = api.transition_trench_segment(seg["id"], {"to": "EXCAVATING"}, PM)
        validate_error(resp, ApiErrorId.ERR_EASEMENT_REFUSED_BLOCKING)

    def test_permit_window_violation_once_easements_recorded(self, api):
        """PRD §3.3: "and that permit's validity window must cover the whole
        excavation window, both endpoints inclusive
        (`ERR_PERMIT_WINDOW_VIOLATION`)."
        Companion half of the pair: with the easement gate satisfied, the
        temporal permit-window gate is the surviving failure.

        Design: Difficulty/priority_pair_validation_conflict/referential_preempts_temporal_on_excavation
        """
        _project, _parts, _parcel, seg = _trenching_base(
            api, "Prio2 Iso", easement="recorded",
            permit=("issued", "2026-08-01T00:00:00Z", "2026-09-05T00:00:00Z"))
        resp = api.transition_trench_segment(seg["id"], {"to": "EXCAVATING"}, PM)
        validate_error(resp, ApiErrorId.ERR_PERMIT_WINDOW_VIOLATION)


class TestChangeOrderFreeze:
    def test_approved_change_order_freezes_segment_and_posture(self, api):
        """PRD §2.7: "At the project level, advancing from `MOBILIZED` to
        `TRENCHING` is rejected with `ERR_POSTURE_FROZEN` (HTTP 409) while the
        posture is `FROZEN`. At the segment level, each trench segment carries
        a computed boolean `frozen`, true while an `APPROVED` change order
        references that segment — or references no segments at all, which marks
        the change order project-wide and freezes every segment. A frozen
        segment refuses scheduling and rescheduling, new occupancy-slot
        reservations, and state-transition requests with
        `ERR_CHANGE_ORDER_FREEZE` (HTTP 409); the freeze lifts when the change
        order is incorporated (or otherwise leaves `APPROVED`)."

        Design: Corner/validations/approved_co_freezes_segment_schedule
        """
        project, _parts = setup_mobilized_project(
            [
                {"utility_name": "U1", "utility_type": "ELECTRIC", "cost_share_bp": 9999, "sequence_order": 1},
                {"utility_name": "U2", "utility_type": "TELECOM", "cost_share_bp": 1, "sequence_order": 2},
            ],
            name="V13", rule20_credit_cents=0, estimated_total_cost_cents=1000000,
            target_cutover_on="2026-12-31T00:00:00Z", contingency_days=0,
        )
        seg = create_scheduled_segment(project["id"])
        co = validate_success(api.create_change_order(
            create_change_order_payload(project["id"], description="freeze seg",
                                        segment_ids=[seg["id"]]), PM), 201)
        validate_success(api.transition_change_order(
            co["id"], {"to": "PRICED", "delta_cost_cents": 5000,
                       "delta_delay_days": 3, "delay_cause": "MIXED"}, PM), 200)
        validate_success(api.transition_change_order(co["id"], {"to": "APPROVED"}, PM), 200)

        resp = api.schedule_trench_segment(
            seg["id"],
            schedule_segment_payload(
                excavation_start_on="2026-09-02T00:00:00Z",
                excavation_end_on="2026-09-11T00:00:00Z",
                expected_trench_segment_version=seg["version"],
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_CHANGE_ORDER_FREEZE)

        resp = api.project_lifecycle(project["id"], {"action": "START_TRENCHING"}, PM)
        validate_error(resp, ApiErrorId.ERR_POSTURE_FROZEN)

        proj = validate_success(api.get_project(project["id"], PM), 200)
        assert proj["posture"] == "FROZEN"
        seg_after = validate_success(api.get_trench_segment(seg["id"], PM), 200)
        assert seg_after["frozen"] is True


class TestSegmentReopenAndClose:
    def test_segment_reopen_cycle_backfilled_to_excavating(self, api):
        """PRD §3.3: "A segment that discovers a defect may be reopened —
        `BACKFILLED → EXCAVATING` — under exactly the same freeze, easement,
        and permit gates as the original excavation entry."

        Design: Corner/state_machines/segment_reopen_cycle_backfilled_to_excavating
        """
        _project, _parts, _parcel, seg = _trenching_base(
            api, "SM4", easement="recorded", permit="issued")
        transition_segment(seg["id"], "EXCAVATING")
        transition_segment(seg["id"], "BACKFILLING")
        transition_segment(seg["id"], "BACKFILLED")
        resp = api.transition_trench_segment(seg["id"], {"to": "EXCAVATING"}, PM)
        data = validate_success(resp, 200)
        assert data["status"] == "EXCAVATING", (
            f"reopen cycle succeeds while the gates still hold, got {data['status']}"
        )

    def test_restoration_open_blocks_segment_close(self, api):
        """PRD §3.3: "Finally, `BACKFILLED → CLOSED` requires every restoration
        task on the segment to be `ACCEPTED`
        (`ERR_RESTORATION_OPEN_BLOCKING`), which ties the surface-restoration
        workflow of §3.8 into segment closure."

        Design: Corner/errors/restoration_open_blocks_segment_close
        """
        _project, _parts, parcel, seg = _trenching_base(
            api, "E1", easement="recorded", permit="issued")
        transition_segment(seg["id"], "EXCAVATING")
        transition_segment(seg["id"], "BACKFILLING")
        transition_segment(seg["id"], "BACKFILLED")

        rt = validate_success(api.create_restoration_task(
            create_restoration_task_payload(seg["id"], parcel["id"], task_type="LANDSCAPE"),
            CONTRACTOR), 201)

        resp = api.transition_trench_segment(seg["id"], {"to": "CLOSED"}, PM)
        validate_error(resp, ApiErrorId.ERR_RESTORATION_OPEN_BLOCKING)

        validate_success(api.transition_restoration_task(rt["id"], {"to": "IN_WORK"}, CONTRACTOR), 200)
        validate_success(api.transition_restoration_task(rt["id"], {"to": "COMPLETE"}, CONTRACTOR), 200)
        validate_success(api.transition_restoration_task(rt["id"], {"to": "ACCEPTED"}, PM), 200)

        resp = api.transition_trench_segment(seg["id"], {"to": "CLOSED"}, PM)
        data = validate_success(resp, 200)
        assert data["status"] == "CLOSED", (
            "closure succeeds once every restoration task on the segment is ACCEPTED"
        )
