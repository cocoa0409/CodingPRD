"""Case finalization gates and record locking (PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    close_day_count,
    close_investigation,
    create_case,
    create_classified_case,
    create_corrective_action,
    finalize_case,
    fresh_case_version,
    get_case,
    open_investigation,
    set_clock,
    setup_closed_investigation,
    setup_org,
    submit_root_cause,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import OFFICER

_FINALIZE_GATES_QUOTE = (
    "A `SafetyOfficer` finalizes a `RECORDABLE` case — the request carrying "
    "`expected_case_version` per §2.8 — only when every gate passes: the "
    "case's investigation exists and is `CLOSED`, failing otherwise with "
    "`ERR_INVESTIGATION_OPEN`; `day_count_closed` is true, failing otherwise "
    "with `ERR_DAY_COUNT_OPEN`; every corrective action linked to the case "
    "sits in `VERIFIED` or `CANCELLED`, failing otherwise with "
    "`ERR_CORRECTIVE_ACTION_OPEN`; and a case whose `is_severe_event` is not "
    "`NONE` has its agency report on file, failing otherwise with "
    "`ERR_SEVERE_REPORT_REQUIRED`.")


def _recordable_case(fein, site_name, occurred="2026-08-01T10:00:00Z",
                     clock="2026-08-01T12:00:00Z", **flags):
    _, establishment, employee = setup_org(fein=fein, site_name=site_name)
    case = create_classified_case(establishment["id"], employee["id"],
                                  occurred, clock_iso=clock, **flags)
    return establishment, case


class TestFinalizeGates:
    def test_finalize_blocked_by_open_day_count(self, api):
        """PRD §3.9: "A `SafetyOfficer` finalizes a `RECORDABLE` case — the
        request carrying `expected_case_version` per §2.8 — only when every
        gate passes: the case's investigation exists and is `CLOSED`, failing
        otherwise with `ERR_INVESTIGATION_OPEN`; `day_count_closed` is true,
        failing otherwise with `ERR_DAY_COUNT_OPEN`; every corrective action
        linked to the case sits in `VERIFIED` or `CANCELLED`, failing
        otherwise with `ERR_CORRECTIVE_ACTION_OPEN`; and a case whose
        `is_severe_event` is not `NONE` has its agency report on file, failing
        otherwise with `ERR_SEVERE_REPORT_REQUIRED`."

        Design: Corner/errors/error_day_count_open_blocks_finalize
        """
        _, case = _recordable_case("12-0000031", "DC Site")
        setup_closed_investigation(case["id"], lead_id="sup-9",
                                   root_cause="TRAINING")

        resp = api.finalize_case(
            case["id"],
            {"expected_case_version": fresh_case_version(case["id"])},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_DAY_COUNT_OPEN)

    def test_finalize_blocked_by_open_corrective_action(self, api):
        """PRD §3.9: "A `SafetyOfficer` finalizes a `RECORDABLE` case — the
        request carrying `expected_case_version` per §2.8 — only when every
        gate passes: the case's investigation exists and is `CLOSED`, failing
        otherwise with `ERR_INVESTIGATION_OPEN`; `day_count_closed` is true,
        failing otherwise with `ERR_DAY_COUNT_OPEN`; every corrective action
        linked to the case sits in `VERIFIED` or `CANCELLED`, failing
        otherwise with `ERR_CORRECTIVE_ACTION_OPEN`; and a case whose
        `is_severe_event` is not `NONE` has its agency report on file, failing
        otherwise with `ERR_SEVERE_REPORT_REQUIRED`."

        Design: Corner/errors/error_corrective_action_open_blocks_finalize
        """
        establishment, case = _recordable_case("13-0000032", "CA Site")
        close_day_count(case["id"])
        setup_closed_investigation(case["id"], lead_id="sup-8")
        create_corrective_action(establishment["id"], case_id=case["id"],
                                 description="Replace guard",
                                 assigned_to="op-Z", priority="HIGH")

        resp = api.finalize_case(
            case["id"],
            {"expected_case_version": fresh_case_version(case["id"])},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_CORRECTIVE_ACTION_OPEN)


class TestFinalizeInvestigationDependency:
    def test_finalize_blocked_while_investigation_not_closed(self, api):
        """PRD §3.9: "A `SafetyOfficer` finalizes a `RECORDABLE` case — the
        request carrying `expected_case_version` per §2.8 — only when every
        gate passes: the case's investigation exists and is `CLOSED`, failing
        otherwise with `ERR_INVESTIGATION_OPEN`"
        PRD §3.4: "A successful closure stamps `closed_at`, lands the
        investigation in the terminal `CLOSED` state, and unblocks case
        finalization (§3.9)."

        Design: Difficulty/cross_entity_state_dependency/finalize_gated_by_investigation_state
        """
        _, case = _recordable_case("55-4445556", "Mill 7",
                                   occurred="2026-08-01T10:00:00Z",
                                   clock="2026-08-03T08:00:00Z")
        investigation = open_investigation(case["id"], "sup-100")
        submit_root_cause(investigation["id"], "sup-100",
                          root_cause="EQUIPMENT",
                          contributing_factors="Guard removed")
        close_day_count(case["id"])

        resp = api.finalize_case(
            case["id"],
            {"expected_case_version": fresh_case_version(case["id"])},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVESTIGATION_OPEN)
        assert get_case(case["id"])["status"] == "RECORDABLE"

    def test_finalize_succeeds_after_investigation_closes(self, api):
        """PRD §3.9: "A finalized case lands in the terminal `FINALIZED`
        state: no further day entries and no further reclassification are
        possible."
        PRD §3.4: "A successful closure stamps `closed_at`, lands the
        investigation in the terminal `CLOSED` state, and unblocks case
        finalization (§3.9)."

        Design: Difficulty/cross_entity_state_dependency/finalize_gated_by_investigation_state
        """
        _, case = _recordable_case("55-4445557", "Mill 8",
                                   occurred="2026-08-01T10:00:00Z",
                                   clock="2026-08-03T08:00:00Z")
        investigation = open_investigation(case["id"], "sup-100")
        submit_root_cause(investigation["id"], "sup-100",
                          root_cause="EQUIPMENT",
                          contributing_factors="Guard removed")
        close_day_count(case["id"])
        close_investigation(investigation["id"])

        finalized = finalize_case(case["id"])
        assert finalized["status"] == "FINALIZED"
        assert finalized["day_count_closed"] is True


class TestFinalizeValidationPriority:
    def test_finalize_from_pending_review_state_gate_wins(self, api):
        """PRD §2.9: "Fourth, state admissibility: the target resource must
        currently sit in a state from which the requested transition exists,
        failing with `ERR_INVALID_STATE`."
        PRD §2.9: "Business rules then run in their pinned order:
        severe-injury clock consistency (`ERR_SEVERE_REPORT_REQUIRED`); the
        temporal windows (`ERR_RECORDABILITY_WINDOW_PASSED`,
        `ERR_POSTING_WINDOW`, `ERR_CONTEST_WINDOW_PASSED`); referential
        integrity across entities (`ERR_CROSS_COMPANY_REFERENCE`,
        `ERR_LINKAGE_XOR`, `ERR_INVESTIGATION_OPEN`); uniqueness
        (`ERR_DUPLICATE`); segregation of duties (`ERR_DUTY_SEGREGATION`);
        day-interval validity (`ERR_DAY_INTERVAL_INVALID`); hour-log
        completeness (`ERR_HOURS_INCOMPLETE`); and penalty validity
        (`ERR_PENALTY_INVALID`)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_finalize
        """
        _, establishment, employee = setup_org(fein="55-3334445",
                                               site_name="Yard 8")
        case = create_case(establishment["id"], employee["id"],
                           "2026-07-28T10:00:00Z",
                           description="Hospitalized overnight",
                           body_part="head",
                           is_severe_event="INPATIENT_HOSPITALIZATION")
        resp = api.finalize_case(
            case["id"], {"expected_case_version": case["version"]}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_case(case["id"])["status"] == "PENDING_REVIEW"

    def test_finalize_severe_case_without_report_rejected(self, api):
        """PRD §3.9: "A `SafetyOfficer` finalizes a `RECORDABLE` case — the
        request carrying `expected_case_version` per §2.8 — only when every
        gate passes: the case's investigation exists and is `CLOSED`, failing
        otherwise with `ERR_INVESTIGATION_OPEN`; `day_count_closed` is true,
        failing otherwise with `ERR_DAY_COUNT_OPEN`; every corrective action
        linked to the case sits in `VERIFIED` or `CANCELLED`, failing
        otherwise with `ERR_CORRECTIVE_ACTION_OPEN`; and a case whose
        `is_severe_event` is not `NONE` has its agency report on file, failing
        otherwise with `ERR_SEVERE_REPORT_REQUIRED`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_finalize
        """
        _, case = _recordable_case(
            "55-3334446", "Yard 9",
            is_severe_event="INPATIENT_HOSPITALIZATION")
        setup_closed_investigation(case["id"], lead_id="sup-7")
        close_day_count(case["id"])

        resp = api.finalize_case(
            case["id"],
            {"expected_case_version": fresh_case_version(case["id"])},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_SEVERE_REPORT_REQUIRED)
