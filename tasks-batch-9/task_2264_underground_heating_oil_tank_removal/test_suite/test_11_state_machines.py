"""Initial states, undeclared transitions, terminal lock-outs and side-effect writes."""
import pytest

from test_helpers import fixtures as fx, parse_instant, validate_error
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    claim_decision_payload,
    custody_event_payload,
    disclosure_response_payload,
    field_event_payload,
    permit_decision_payload,
    rescind_payload,
    result_payload,
    sweep_survey_payload,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    FIELD_TECHNICIAN,
    LSP_DRAFTER,
    make_homeowner_headers,
    make_lab_analyst_headers,
)


class TestInitialStates:
    def test_a_fresh_project_begins_in_intake(self, api):
        """PRD §3.1: "A fresh project begins in `INTAKE` with `sampling_round` at 0, `contamination_class` at `UNCLASSIFIED`, `approved_scope_cubic_yards` equal to `baseline_scope_cubic_yards`, `remediation_cost_cents` at 0, and a blocker list that already names two obstacles — field work has not happened and contamination has not been cleared."
        PRD §3.1: "Locating the tank is the first substantive act, shared between the `ProjectCoordinator` and the `FieldTechnician`."

        Design: Corner/state_machines/tank_project_starts_in_intake_initial_state
        """
        ctx = fx.project_at_intake()

        project = ctx["project"]
        assert project["status"] == "INTAKE", (
            f"nothing has been surveyed yet, got {project['status']}"
        )
        assert project["approved_scope_cubic_yards"] == pytest.approx(
            project["baseline_scope_cubic_yards"], abs=0.01
        ), (
            "with no change order the approved scope equals the baseline, got "
            f"{project['approved_scope_cubic_yards']}"
        )
        assert project["survey_completed_at"] is None, (
            f"no survey has been recorded, got {project['survey_completed_at']}"
        )
        assert project["recommended_method"] is None, (
            f"no recommendation has been derived, got {project['recommended_method']}"
        )


class TestUndeclaredTransitions:
    def test_a_second_sweep_survey_is_refused_and_the_first_result_stands(self, api):
        """PRD §3.1: "The sweep survey advances the project `INTAKE → SURVEYED` and records the `survey_method` used — `GPR` for ground-penetrating radar, `MAGNETOMETER`, or `PROBE_ROD` — together with `tanks_detected_count` and, stamped from the logical clock, `survey_completed_at`."
        PRD §2.11: "9. **State legality** — the target resource, and the project behind it, must be in a state from which the requested operation is declared. For project-targeted operations the code is `ERR_PROJECT_STATE_INVALID` (409); for other targets the entity-specific state code is used — `ERR_DISCLOSURE_STATE_INVALID`, `ERR_PERMIT_STATE_INVALID`, `ERR_WORK_ORDER_STATE_INVALID`, `ERR_SAMPLE_STATE_INVALID`, `ERR_CHANGE_ORDER_STATE_INVALID`, `ERR_CLAIM_STATE_INVALID` or `ERR_NFA_STATE_INVALID`, each HTTP 409. Applies to every action endpoint."

        Design: Corner/state_machines/sweep_survey_recorded_twice_is_rejected_on_the_second_attempt
        """
        ctx = fx.project_at_surveyed()

        response = api.record_sweep_survey(
            ctx["project"]["id"],
            sweep_survey_payload(survey_method="PROBE_ROD", tanks_detected_count=2),
            FIELD_TECHNICIAN,
        )
        validate_error(response, ApiErrorId.ERR_PROJECT_STATE_INVALID.value, 409)

        project = fx.read_project(ctx["project"]["id"])
        assert project["status"] == "SURVEYED", (
            f"the project stays where the first survey left it, got {project['status']}"
        )
        assert project["survey_method"] == "GPR", (
            f"the first survey's method stands, got {project['survey_method']}"
        )
        assert project["tanks_detected_count"] == 1, (
            f"the refused count is not written, got {project['tanks_detected_count']}"
        )
        assert project["method_score"] == pytest.approx(36.00, abs=0.01), (
            f"the first survey's score stands, got {project['method_score']}"
        )

    def test_a_second_response_to_an_answered_notice_is_refused(self, api):
        """PRD §3.2: "A response to a notice that is no longer `PENDING` is refused with `ERR_DISCLOSURE_STATE_INVALID`."
        PRD §3.2: "A disclosure notice never leaves `ACKNOWLEDGED`, `DECLINED` or `EXPIRED` once it arrives there; all three are terminal, and a project needing a fresh answer needs a fresh notice."

        Design: Corner/state_machines/disclosure_responded_twice_is_rejected_on_the_second_attempt
        """
        ctx = fx.project_at_disclosed()

        response = api.respond_to_disclosure(
            ctx["sweep_disclosure"]["id"],
            disclosure_response_payload(response="DECLINED", response_channel="EMAIL"),
            make_homeowner_headers(ctx["property"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_DISCLOSURE_STATE_INVALID.value, 409)

        notice = fx.read_disclosure(ctx["sweep_disclosure"]["id"])
        assert notice["status"] == "ACKNOWLEDGED", (
            f"the first answer is final, got {notice['status']}"
        )
        assert notice["response_channel"] == "PORTAL", (
            "the refused second answer must not overwrite the channel, got "
            f"{notice['response_channel']}"
        )
        assert fx.read_project(ctx["project"]["id"])["status"] == "DISCLOSED", (
            "the project stays past the disclosure gate"
        )

    def test_starting_field_work_without_mobilizing_first_is_refused(self, api):
        """PRD §3.4: "The dimension runs `SCHEDULED → MOBILIZED → IN_PROGRESS → FIELD_COMPLETE`, with `ABORTED` reachable from any of the first three; `FIELD_COMPLETE` and `ABORTED` are terminal. An event requested from a state that does not allow it is refused with `ERR_WORK_ORDER_STATE_INVALID`."
        PRD §3.4: "`START` moves the field dimension `MOBILIZED → IN_PROGRESS` and requires the project to be in `PERMITTED`."

        Design: Corner/state_machines/work_order_start_without_a_prior_mobilize_is_rejected
        """
        ctx = fx.project_with_booked_work_order()
        fx.set_clock("2026-08-06T13:00:00Z")

        response = api.create_field_event(
            ctx["work_order"]["id"], field_event_payload("START"), FIELD_TECHNICIAN
        )
        validate_error(response, ApiErrorId.ERR_WORK_ORDER_STATE_INVALID.value, 409)

        work_order = fx.read_work_order(ctx["work_order"]["id"])
        assert work_order["field_status"] == "SCHEDULED", (
            f"the crew has not arrived yet, got {work_order['field_status']}"
        )
        assert fx.read_project(ctx["project"]["id"])["status"] == "PERMITTED", (
            "only a lawful START turns the project's own lifecycle over"
        )

    def test_a_decision_on_a_denied_permit_is_locked_out(self, api):
        """PRD §3.3: "A permit decision requested from a state that does not permit it — asking for `ISSUED` twice, or asking for `REVOKED` on a permit still in `SUBMITTED` — is refused with `ERR_PERMIT_STATE_INVALID`."
        PRD §3.3: "**The `DENIED` branch** requires the permit to be in `SUBMITTED` and requires `denial_reason` to accompany the decision."

        Design: Corner/state_machines/permit_decision_on_a_denied_permit_is_locked_out
        """
        ctx = fx.project_at_disclosed()
        permit = fx.create_permit(ctx["project"]["id"], "MUNICIPAL_DECOMMISSION")
        fx.decide_permit(
            permit["id"], "DENIED", denial_reason="site plan omitted the tank location"
        )

        response = api.decide_permit(
            permit["id"], permit_decision_payload("ISSUED"), COMPLIANCE_OFFICER
        )
        validate_error(response, ApiErrorId.ERR_PERMIT_STATE_INVALID.value, 409)

        stored = fx.read_permit(permit["id"])
        assert stored["status"] == "DENIED", (
            f"a denial is a dead end for the row, got {stored['status']}"
        )
        assert stored["issued_at"] is None, (
            f"the refused issuance stamps nothing, got {stored['issued_at']}"
        )
        assert fx.read_project(ctx["project"]["id"])["status"] == "DISCLOSED", (
            "no municipal authorisation was ever issued, so the project waits"
        )

    def test_reporting_a_result_on_an_aliquot_still_in_transit_is_refused(self, api):
        """PRD §3.6: "`RECEIVE` is a `LabAnalyst` act, permitted only to the lab named as the sample's `laboratory_id`, and moves the sample `IN_TRANSIT → AT_LAB`. A custody event requested from a state that does not allow it is refused with `ERR_SAMPLE_STATE_INVALID`."
        PRD §3.6: "`SAMPLES_PENDING` is present whenever the project has at least one sample in the current `sampling_round` whose `status` is `COLLECTED`, `IN_TRANSIT` or `AT_LAB`."

        Design: Corner/state_machines/sample_result_reported_while_still_in_transit_is_rejected
        """
        ctx = fx.project_at_sampling()
        sample = fx.create_sample(
            ctx["project"]["id"],
            ctx["work_order"]["id"],
            ctx["laboratory"]["id"],
            sample_point="TANK_BOTTOM",
            depth_inches=96,
        )
        fx.dispatch_sample(sample["id"])

        response = api.report_result(
            sample["id"],
            result_payload(120.0, 0.05),
            make_lab_analyst_headers(ctx["laboratory"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_SAMPLE_STATE_INVALID.value, 409)

        stored = fx.read_sample(sample["id"])
        assert stored["status"] == "IN_TRANSIT", (
            f"the aliquot is still with the courier, got {stored['status']}"
        )
        assert stored["tph_mg_kg"] is None, (
            f"no figure may be recorded, got {stored['tph_mg_kg']}"
        )
        assert fx.read_project(ctx["project"]["id"])["status"] == "SAMPLING", (
            "the round cannot close while an aliquot is unresulted"
        )


class TestTerminalStateLockdown:
    def test_dispatching_a_voided_aliquot_is_locked_out(self, api):
        """PRD §3.6: "`VOID` is also a technician act, accepted while the sample is in `COLLECTED` or `IN_TRANSIT`, and moves it to `VOIDED`; a voided sample stops counting toward round completeness and toward the closure blockers entirely."
        PRD §3.6: "Both `INVALIDATED` and `VOIDED` are terminal for a sample — a discredited aliquot is never rehabilitated, and the only remedy is a fresh sample naming it through `retest_of_sample_id`."

        Design: Corner/state_machines/soil_sample_voided_then_dispatched_is_locked_out
        """
        ctx = fx.project_at_sampling()
        sample = fx.create_sample(
            ctx["project"]["id"],
            ctx["work_order"]["id"],
            ctx["laboratory"]["id"],
            sample_point="TANK_BOTTOM",
            depth_inches=96,
        )
        fx.void_sample(sample["id"])

        response = api.create_custody_event(
            sample["id"], custody_event_payload("DISPATCH"), FIELD_TECHNICIAN
        )
        validate_error(response, ApiErrorId.ERR_SAMPLE_STATE_INVALID.value, 409)

        stored = fx.read_sample(sample["id"])
        assert stored["status"] == "VOIDED", (
            f"a voided aliquot is never rehabilitated, got {stored['status']}"
        )
        assert stored["dispatched_at"] is None, (
            f"the refused dispatch stamps nothing, got {stored['dispatched_at']}"
        )
        blockers = fx.read_project(ctx["project"]["id"])["nfa_blockers"]
        assert "SAMPLES_PENDING" not in blockers, (
            "a voided aliquot stops counting toward the blockers entirely, got "
            f"{blockers}"
        )

    def test_submitting_an_already_submitted_change_order_is_refused(self, api):
        """PRD §3.7: "Submission is the author's own act: the same `LicensedSiteProfessional` whose identifier is recorded as `requested_by_user_id` moves the row `DRAFT → SUBMITTED`, and only while the project stands at `REMEDIATION_ACTIVE`. The blocker list is recomputed, and `OPEN_CHANGE_ORDER` remains present for as long as any row on the project sits in `DRAFT` or `SUBMITTED`. Submit or decision requested from a state that does not allow it is refused with `ERR_CHANGE_ORDER_STATE_INVALID`."
        PRD §3.7: "The project's `approved_scope_cubic_yards` is always its `baseline_scope_cubic_yards` plus the sum of `additional_cubic_yards` over the project's change orders whose `status` is `APPROVED`. Rows in `DRAFT`, `SUBMITTED`, `REJECTED` or `SUPERSEDED` contribute nothing."

        Design: Corner/state_machines/change_order_submitted_twice_is_rejected_on_the_second_attempt
        """
        ctx = fx.project_remediation_active_gross()
        order = fx.submitted_change_order(ctx, 2.0, 1200)

        response = api.submit_change_order(order["id"], LSP_DRAFTER)
        validate_error(response, ApiErrorId.ERR_CHANGE_ORDER_STATE_INVALID.value, 409)

        stored = fx.read_change_order(order["id"])
        assert stored["status"] == "SUBMITTED", (
            f"the row is already awaiting a decision, got {stored['status']}"
        )
        assert stored["line_amount_cents"] is None, (
            "the line amount is computed only on approval, got "
            f"{stored['line_amount_cents']}"
        )

        project = fx.read_project(ctx["project"]["id"])
        assert project["approved_scope_cubic_yards"] == pytest.approx(8.0, abs=0.01), (
            "a submitted row contributes nothing to the approved scope, got "
            f"{project['approved_scope_cubic_yards']}"
        )
        assert "OPEN_CHANGE_ORDER" in project["nfa_blockers"], (
            f"the unresolved row blocks closure, got {project['nfa_blockers']}"
        )

    def test_approving_a_claim_straight_from_submitted_is_refused(self, api):
        """PRD §3.9: "`APPROVED` is accepted from `UNDER_REVIEW`, requires `eligible_amount_cents` to be strictly greater than zero — otherwise `ERR_CLAIM_NOT_ELIGIBLE` — and stamps `decided_at` from the logical clock."
        PRD §3.9: "`UNDER_REVIEW` is accepted from `SUBMITTED` and simply opens the review."

        Design: Corner/state_machines/claim_approved_directly_from_submitted_is_rejected
        """
        ctx = fx.project_cleared()
        claim = fx.create_claim(ctx["project"]["id"], claimed_costs_cents=900000)
        assert claim["eligible_amount_cents"] == 818500, (
            "900,000 gross under the 4,000,000-cent tier less the 50,000-cent "
            "deductible less the 31,500-cent fee is 818,500 cents, got "
            f"{claim['eligible_amount_cents']}"
        )
        fx.submit_claim(claim["id"])

        response = api.decide_trust_fund_claim(
            claim["id"], claim_decision_payload("APPROVED"), COMPLIANCE_OFFICER
        )
        validate_error(response, ApiErrorId.ERR_CLAIM_STATE_INVALID.value, 409)

        stored = fx.read_claim(claim["id"])
        assert stored["status"] == "SUBMITTED", (
            f"the review was never opened, got {stored['status']}"
        )
        assert stored["decided_at"] is None, (
            f"no decision instant is stamped, got {stored['decided_at']}"
        )
        assert stored["info_request_count"] == 0, (
            f"no questions were asked, got {stored['info_request_count']}"
        )

    def test_rescinding_a_letter_still_in_draft_is_refused(self, api):
        """PRD §3.9: "A `ComplianceOfficer` rescinds an issued letter by supplying a `rescission_reason`, which is required; the letter must be in `ISSUED` and the project in `CLOSED_NFA`."
        PRD §3.9: "Issue or rescind requested from a letter state that does not allow it is refused with `ERR_NFA_STATE_INVALID`."

        Design: Corner/state_machines/nfa_letter_rescinded_while_still_draft_is_rejected
        """
        ctx = fx.project_cleared()
        letter = fx.draft_nfa_letter(
            ctx["project"]["id"], closing_date="2026-09-15T00:00:00Z"
        )

        response = api.rescind_nfa_letter(
            letter["id"], rescind_payload(), COMPLIANCE_OFFICER
        )
        validate_error(response, ApiErrorId.ERR_NFA_STATE_INVALID.value, 409)

        stored = fx.read_nfa_letter(letter["id"])
        assert stored["status"] == "DRAFT", (
            f"an unsigned letter cannot be rescinded, got {stored['status']}"
        )
        assert stored["rescinded_at"] is None, (
            f"no rescission instant is stamped, got {stored['rescinded_at']}"
        )
        assert stored["issued_by_user_id"] is None, (
            f"nobody has signed the letter, got {stored['issued_by_user_id']}"
        )
        assert fx.read_project(ctx["project"]["id"])["status"] == "CLEARED", (
            "the project is not closed, so nothing can be walked back"
        )


class TestSideEffectWrites:
    def test_a_declined_sweep_notice_voids_the_project_and_aborts_its_field_work(
        self, api
    ):
        """PRD §3.2: "A decline is far more consequential. The notice transitions `PENDING → DECLINED` with `responded_at` stamped, and when the declined notice was a `SWEEP_FINDINGS` notice on a project in `SURVEYED`, the project is voided outright: `SURVEYED → VOID`."
        PRD §3.2: "Every `DecommissionWorkOrder` on the project whose `field_status` is `SCHEDULED`, `MOBILIZED` or `IN_PROGRESS` is transitioned to `ABORTED` with `abort_reason` set to `PROJECT_VOIDED`, and its `billing_status` is transitioned to `WRITTEN_OFF`."

        Design: Corner/state_machines/disclosure_declined_voids_the_project_and_aborts_its_open_work_order
        """
        ctx = fx.project_at_surveyed()
        crew = fx.create_crew()
        work_order = fx.create_work_order(ctx["project"]["id"], crew["id"])
        notice = fx.create_disclosure(
            ctx["project"]["id"], disclosure_kind="SWEEP_FINDINGS"
        )

        declined = fx.respond_to_disclosure(
            notice["id"],
            ctx["property"]["id"],
            response="DECLINED",
            response_channel="WET_SIGNATURE",
        )
        assert declined["status"] == "DECLINED", (
            f"the notice must record the refusal, got {declined['status']}"
        )
        assert parse_instant(declined["responded_at"]) == parse_instant(
            "2026-08-03T08:00:00Z"
        ), (
            "the response instant is stamped from the logical clock, got "
            f"{declined['responded_at']}"
        )
        assert declined["response_channel"] == "WET_SIGNATURE", (
            f"the channel must be stored, got {declined['response_channel']}"
        )

        assert fx.read_project(ctx["project"]["id"])["status"] == "VOID", (
            "a declined sweep notice voids the project outright"
        )
        aborted = fx.read_work_order(work_order["id"])
        assert aborted["field_status"] == "ABORTED", (
            f"the booking dies with the project, got {aborted['field_status']}"
        )
        assert aborted["abort_reason"] == "PROJECT_VOIDED", (
            f"the cascade records why, got {aborted['abort_reason']}"
        )
        assert aborted["billing_status"] == "WRITTEN_OFF", (
            f"the abort writes the billing off, got {aborted['billing_status']}"
        )

    def test_field_completion_opens_sampling_and_the_billing_dimension(self, api):
        """PRD §3.4: "On success both values are stored on the work order and copied onto the project, the billing dimension advances `UNBILLED → BILLABLE`, the project's `sampling_round` moves from 0 to 1, and the project advances `DECOMMISSIONING → SAMPLING`."
        PRD §3.5: "`UNBILLED → BILLABLE` is written by the system as a side effect of a successful field `COMPLETE`, and it fires only when the billing dimension is standing at `UNBILLED` — the billing dimension advances from `UNBILLED` by that route alone."

        Design: Corner/state_machines/field_complete_bubbles_the_project_to_sampling_and_opens_billing
        """
        ctx = fx.project_at_sampling()

        work_order = fx.read_work_order(ctx["work_order"]["id"])
        assert work_order["field_status"] == "FIELD_COMPLETE", (
            f"the crew finished, got {work_order['field_status']}"
        )
        assert work_order["billing_status"] == "BILLABLE", (
            "completion is the only route out of UNBILLED, got "
            f"{work_order['billing_status']}"
        )

        project = fx.read_project(ctx["project"]["id"])
        assert project["status"] == "SAMPLING", (
            f"confirmation sampling has opened, got {project['status']}"
        )
        assert project["sampling_round"] == 1, (
            f"the first confirmation round is open, got {project['sampling_round']}"
        )
        assert project["actual_excavated_cubic_yards"] == pytest.approx(9.5, abs=0.01), (
            "the crew's dug volume is copied onto the project, got "
            f"{project['actual_excavated_cubic_yards']}"
        )
        assert project["hauled_tons"] == pytest.approx(12.4, abs=0.01), (
            f"the weigh-ticket tonnage is copied too, got {project['hauled_tons']}"
        )
        assert project["decommission_method"] == "REMOVAL", (
            "the executed method was frozen at START, got "
            f"{project['decommission_method']}"
        )
        assert "FIELD_WORK_INCOMPLETE" not in project["nfa_blockers"], (
            f"the field-work obstacle is cleared, got {project['nfa_blockers']}"
        )
