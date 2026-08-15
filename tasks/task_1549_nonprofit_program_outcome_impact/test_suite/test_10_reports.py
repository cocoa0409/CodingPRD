"""Reports: the data-quality gate, the rework cycle, OCC on creation, and
funder/status preconditions."""
import pytest

from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_funder_viewer_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    create_active_program,
    create_cycle,
    create_funder,
    record_and_validate,
    record_observation,
    setup_cycle_under_review,
    setup_draft_report,
    setup_generated_report,
    setup_delivered_report,
    setup_program_with_approved_model,
    setup_active_cycle,
    setup_participant_with_consent,
    create_instrument,
    publish_instrument,
    create_certification,
    open_audit_for_cycle,
)
from test_helpers.test_users import DIRECTOR, LEAD


class TestDqGate:
    def test_dq_gate_exactly_80_passes(self, api):
        """PRD section 3.8: "For `FUNDER_STANDARD` and `FUNDER_CUSTOM`
        reports, the cycle's `latest_dq_score` must be present and at least
        80.00; when it is null or lower, generation is rejected with
        `ERR_DQ_GATE_NOT_MET` (HTTP 422)."
        PRD section 3.7: "Sixth, it is rounded half-up to two decimal places
        and written to the audit's `dq_score` and the cycle's
        `latest_dq_score`."

        Design: Difficulty/boundary_precision_check/dq_gate_exactly_80_passes
        """
        world = setup_cycle_under_review(
            program_name="Veterans", program_code="VET",
            indicator_specs=[
                {"code": "I1", "weight": 1.0,
                 "measurement_frequency": "END_OF_CYCLE"},
                {"code": "I2", "weight": 1.0,
                 "measurement_frequency": "END_OF_CYCLE"},
                {"code": "I3", "weight": 1.0,
                 "measurement_frequency": "END_OF_CYCLE"},
            ],
            validated_values=[("I1", 10)],
            pending_values=[("I2", 20), ("I3", 30)],
        )
        # C=100.00 (participant covers all 3), V=33.33 (1 of 3 validated),
        # K=100.00, F=0 -> raw = 50 + 9.999 + 20 = 79.999 -> rounds to 80.00.
        cycle = get_success_data(api.get_cycle(world["cycle"]["id"], DIRECTOR))
        assert cycle["latest_dq_score"] == pytest.approx(80.00, abs=0.001)

        draft = setup_draft_report(world, report_type="FUNDER_STANDARD")
        gen_resp = api.generate_report(draft["report"]["id"], LEAD)
        generated = validate_success(gen_resp, expected_status=200)
        assert generated["status"] == "GENERATED"
        assert generated["snapshot_dq_score"] == pytest.approx(80.00, abs=0.001)
        assert generated["snapshot_data_completeness_pct"] == pytest.approx(100.00, abs=0.01)
        # Only I1 has a VALIDATED observation -> attainment 10.00, weight
        # renormalized over eligible set (just I1) to 1.0.
        assert generated["snapshot_overall_impact_index"] == pytest.approx(10.00, abs=0.01)

    def test_dq_gate_boundary_inclusive(self, api):
        """PRD section 3.8: "the cycle's `latest_dq_score` must be present and
        at least 80.00; when it is null or lower, generation is rejected with
        `ERR_DQ_GATE_NOT_MET` (HTTP 422). `INTERNAL_DASHBOARD` reports are
        exempt from the gate."

        Design: Difficulty/boundary_precision_check/dq_gate_exactly_80_passes
        """
        # Companion scenario: dq 100.00 well above the gate also succeeds;
        # the point is to show the gate is not accidentally inverted.
        world = setup_cycle_under_review(
            program_name="Veterans2", program_code="VE2",
            indicator_specs=[{
                "code": "I1", "weight": 1.0,
                "measurement_frequency": "END_OF_CYCLE",
            }],
            validated_values=[("I1", 60)],
        )
        cycle = get_success_data(api.get_cycle(world["cycle"]["id"], DIRECTOR))
        assert cycle["latest_dq_score"] == pytest.approx(100.00, abs=0.01)

        draft = setup_draft_report(world, report_type="FUNDER_STANDARD")
        generated = validate_success(
            api.generate_report(draft["report"]["id"], LEAD))
        assert generated["status"] == "GENERATED"
        assert generated["snapshot_dq_score"] == pytest.approx(100.00, abs=0.01)

    def test_dq_gate_below_threshold_and_internal_exempt(self, api):
        """PRD section 3.8: "For `FUNDER_STANDARD` and `FUNDER_CUSTOM`
        reports, the cycle's `latest_dq_score` must be present and at least
        80.00; when it is null or lower, generation is rejected with
        `ERR_DQ_GATE_NOT_MET` (HTTP 422). `INTERNAL_DASHBOARD` reports are
        exempt from the gate."

        Design: Corner/calculations/dq_gate_below_threshold_and_internal_exempt
        """
        world = setup_cycle_under_review(
            program_name="Gate", program_code="GTE",
            indicator_specs=[{
                "code": "I1", "weight": 1.0,
                "measurement_frequency": "END_OF_CYCLE",
            }],
            validated_values=[],
            pending_values=[("I1", 42)],
        )
        # C=100.00 (PENDING obs still covers the indicator), V=0.00 (none
        # validated), K=100.00, F=0 -> 50 + 0 + 20 = 70.00.
        cycle = get_success_data(api.get_cycle(world["cycle"]["id"], DIRECTOR))
        assert cycle["latest_dq_score"] == pytest.approx(70.00, abs=0.01)

        funder = create_funder(name="Foundation K", code="FND-K")
        draft_funder = setup_draft_report(world, funder=funder,
                                          report_type="FUNDER_STANDARD")
        blocked = api.generate_report(draft_funder["report"]["id"], LEAD)
        validate_error(blocked, ApiErrorId.ERR_DQ_GATE_NOT_MET)

        draft_internal = setup_draft_report(world, funder=funder,
                                            report_type="INTERNAL_DASHBOARD")
        internal = validate_success(
            api.generate_report(draft_internal["report"]["id"], LEAD))
        assert internal["status"] == "GENERATED"
        assert internal["snapshot_dq_score"] == pytest.approx(70.00, abs=0.01)


class TestReportReworkCycle:
    def test_report_returned_rework_cycle(self, api):
        """PRD section 3.8: "A returned report enters the rework loop:
        regeneration (`RETURNED → GENERATED`) recomputes and re-pins all three
        snapshot fields at the new instant - the underlying data may have
        changed during rework - re-stamps `generated_at`, and re-applies the
        data-quality gate for the two funder report types."
        PRD section 3.8: "Acceptance (`DELIVERED → ACCEPTED`, terminal) and
        return (`DELIVERED → RETURNED`, carrying a `reason`) are
        `FunderViewer` operations restricted to the funder of record".

        Design: Difficulty/non_linear_state_machine/report_returned_rework_cycle
        """
        world = setup_cycle_under_review(
            program_name="Youth", program_code="YTH",
            indicator_specs=[{
                "code": "I1", "weight": 1.0,
                "measurement_frequency": "END_OF_CYCLE",
            }],
            validated_values=[("I1", 60)],
        )
        delivered = setup_delivered_report(world, report_type="FUNDER_STANDARD")
        report = delivered["report"]
        assert delivered["funder"] is not None

        returned = get_success_data(api.return_report(
            report["id"], {"reason": "needs cohort breakdown"},
            make_funder_viewer_headers(delivered["funder"]["id"])))
        assert returned["status"] == "RETURNED"

        regenerated = get_success_data(
            api.regenerate_report(report["id"], LEAD))
        assert regenerated["status"] == "GENERATED"
        assert regenerated["snapshot_dq_score"] == pytest.approx(100.00, abs=0.01)
        assert regenerated["snapshot_overall_impact_index"] == pytest.approx(60.00, abs=0.01)
        assert regenerated["snapshot_data_completeness_pct"] == pytest.approx(100.00, abs=0.01)
        assert regenerated["generated_at"] is not None

    def test_report_full_path_through_return_and_regenerate(self, api):
        """PRD section 3.8: "Delivery (`GENERATED → DELIVERED`) stamps
        `delivered_at`. ... return (`DELIVERED → RETURNED`, carrying a
        `reason`) ... regeneration (`RETURNED → GENERATED`) recomputes and
        re-pins all three snapshot fields at the new instant".

        Design: Difficulty/non_linear_state_machine/report_returned_rework_cycle
        """
        world = setup_cycle_under_review(
            program_name="Youth2", program_code="YT2",
            indicator_specs=[{
                "code": "I1", "weight": 1.0,
                "measurement_frequency": "END_OF_CYCLE",
            }],
            validated_values=[("I1", 60)],
        )
        draft = setup_draft_report(world, report_type="FUNDER_STANDARD")
        assert draft["report"]["status"] == "DRAFT"

        generated = get_success_data(
            api.generate_report(draft["report"]["id"], LEAD))
        assert generated["status"] == "GENERATED"

        delivered = get_success_data(
            api.deliver_report(draft["report"]["id"], LEAD))
        assert delivered["status"] == "DELIVERED"
        assert delivered["delivered_at"] is not None

        returned = get_success_data(api.return_report(
            draft["report"]["id"], {"reason": "needs cohort breakdown"},
            make_funder_viewer_headers(draft["funder"]["id"])))
        assert returned["status"] == "RETURNED"

        regenerated = get_success_data(
            api.regenerate_report(draft["report"]["id"], LEAD))
        assert regenerated["status"] == "GENERATED"


class TestMarkReportedGate:
    def test_mark_reported_blocked_by_delivered_report(self, api):
        """PRD section 3.4: "Marking the cycle reported (`UNDER_REVIEW →
        REPORTED`) is allowed only when no report of the cycle sits in
        `DRAFT`, `GENERATED`, `DELIVERED`, or `RETURNED` - every report must
        have reached a terminal or superseded state first."

        Design: Corner/state_machines/mark_reported_blocked_by_delivered_report
        """
        world = setup_cycle_under_review(
            program_name="Reporting", program_code="RPT",
            indicator_specs=[{
                "code": "I1", "weight": 1.0,
                "measurement_frequency": "END_OF_CYCLE",
            }],
            validated_values=[("I1", 60)],
        )
        delivered = setup_delivered_report(world, report_type="FUNDER_STANDARD")

        blocked = api.mark_reported(world["cycle"]["id"], DIRECTOR)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)

        get_success_data(api.accept_report(
            delivered["report"]["id"],
            make_funder_viewer_headers(delivered["funder"]["id"])))

        marked = get_success_data(
            api.mark_reported(world["cycle"]["id"], DIRECTOR))
        assert marked["status"] == "REPORTED"


class TestAcceptedTerminal:
    def test_accepted_report_terminal_deliver_rejected(self, api):
        """PRD section 3.8: "Acceptance (`DELIVERED → ACCEPTED`, terminal)".
        PRD section 3.4: "Every transition into or out of the wrong state is
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/accepted_report_terminal_deliver_rejected
        """
        world = setup_cycle_under_review(
            program_name="Terminal", program_code="TRR",
            indicator_specs=[{
                "code": "I1", "weight": 1.0,
                "measurement_frequency": "END_OF_CYCLE",
            }],
            validated_values=[("I1", 60)],
        )
        delivered = setup_delivered_report(world, report_type="FUNDER_STANDARD")
        get_success_data(api.accept_report(
            delivered["report"]["id"],
            make_funder_viewer_headers(delivered["funder"]["id"])))

        blocked = api.deliver_report(delivered["report"]["id"], LEAD)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)


class TestReportOcc:
    def test_occ_report_create_stale_and_supersede(self, api):
        """PRD section 2.8: "Creating a report under a cycle requires the
        request to carry `expected_program_cycle_version`, holding the
        `version` of the parent `ProgramCycle` the client last observed. If
        the cycle's current `version` differs - because the client is working
        from a read that no longer reflects the cycle - the creation is
        rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412). A new report
        legitimately supersedes an existing `DRAFT` or `GENERATED` report for
        the same cycle-funder-type triple".

        Design: Corner/cross_cutting_layers/occ_report_create_stale_and_supersede
        """
        program = create_active_program(name="OCC", code="OCC")
        base = setup_program_with_approved_model(program_name="OCC-base",
                                                 program_code="OCB")
        cycle = setup_active_cycle(base["program"])
        get_success_data(api.close_data(cycle["id"], DIRECTOR))
        get_success_data(api.begin_review(cycle["id"], DIRECTOR))
        funder = create_funder(name="Foundation M", code="FND-M")

        cycle_now = get_success_data(api.get_cycle(cycle["id"], LEAD))
        captured_version = cycle_now["version"]

        first = validate_success(api.create_report(
            cycle["id"],
            {"funder_id": funder["id"], "report_type": "FUNDER_STANDARD",
             "expected_program_cycle_version": captured_version},
            LEAD,
        ), expected_status=201)
        assert first["status"] == "DRAFT"

        stale_resp = api.create_report(
            cycle["id"],
            {"funder_id": funder["id"], "report_type": "FUNDER_STANDARD",
             "expected_program_cycle_version": captured_version},
            LEAD,
        )
        validate_error(stale_resp, ApiErrorId.ERR_STALE_CYCLE_VERSION)

        cycle_refreshed = get_success_data(api.get_cycle(cycle["id"], LEAD))
        second = validate_success(api.create_report(
            cycle["id"],
            {"funder_id": funder["id"], "report_type": "FUNDER_STANDARD",
             "expected_program_cycle_version": cycle_refreshed["version"]},
            LEAD,
        ), expected_status=201)

        first_after = get_success_data(api.get_report(first["id"], LEAD))
        assert first_after["status"] == "SUPERSEDED"
        assert second["status"] == "DRAFT"


class TestReportFunderPrecondition:
    def test_funder_inactive_report_rejected(self, api):
        """PRD section 3.1: "An `INACTIVE` funder cannot receive new reports
        - creating a report addressed to one is rejected with
        `ERR_FUNDER_INACTIVE` (HTTP 422)".

        Design: Corner/validations/funder_inactive_report_rejected
        """
        base = setup_program_with_approved_model(program_name="FundGate",
                                                 program_code="FGT")
        cycle = setup_active_cycle(base["program"])
        get_success_data(api.close_data(cycle["id"], DIRECTOR))
        get_success_data(api.begin_review(cycle["id"], DIRECTOR))

        funder = create_funder(name="Foundation L", code="FND-L")
        get_success_data(api.deactivate_funder(funder["id"], DIRECTOR))

        cycle_now = get_success_data(api.get_cycle(cycle["id"], LEAD))
        resp = api.create_report(
            cycle["id"],
            {"funder_id": funder["id"], "report_type": "FUNDER_STANDARD",
             "expected_program_cycle_version": cycle_now["version"]},
            LEAD,
        )
        validate_error(resp, ApiErrorId.ERR_FUNDER_INACTIVE)
