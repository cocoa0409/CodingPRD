"""Operations gated on the state of a sibling row rather than on their own target."""
import pytest

from test_helpers import fixtures as fx, parse_instant, validate_error
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import custody_event_payload, field_event_payload
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    FIELD_TECHNICIAN,
    make_lab_analyst_headers,
)


class TestMobilizeRequiresEffectiveFireMarshalNotice:
    #: The booking sits a full day before the fire marshal's notice takes effect.
    ARRIVAL_INSTANT = "2026-08-04T13:00:00Z"
    NOTICE_EFFECTIVE_AT = "2026-08-05T08:00:00Z"

    def _crew_arriving_before_the_notice_takes_effect(self):
        ctx = fx.project_with_booked_work_order(
            work_order_overrides={
                "scheduled_start_at": self.ARRIVAL_INSTANT,
                "scheduled_end_at": "2026-08-04T21:00:00Z",
            }
        )
        fx.set_clock(self.ARRIVAL_INSTANT)
        return ctx

    def test_arrival_before_the_notice_takes_effect_is_refused(self, api):
        """PRD §3.4: "It requires that the project carry a `FIRE_MARSHAL_NOTIFICATION` permit in `ISSUED` whose `notice_effective_at` is at or before the current logical instant — absence of such a notice, or arrival before its notice has taken effect, is refused with `ERR_FIRE_MARSHAL_NOTICE_NOT_EFFECTIVE`."
        PRD §3.3: "The `notice_effective_at` field is where the two types diverge: for a `FIRE_MARSHAL_NOTIFICATION` it is 48 hours after `issued_at`, encoding the two-day statutory wait before ground may be broken, while for a `MUNICIPAL_DECOMMISSION` it is simply equal to `issued_at`."

        Design: Difficulty/cross_entity_state_dependency/work_order_mobilize_requires_effective_fire_marshal_notice
        """
        ctx = self._crew_arriving_before_the_notice_takes_effect()

        notice = fx.read_permit(ctx["fire_permit"]["id"])
        assert notice["status"] == "ISSUED", (
            f"the notice itself is in force, got {notice['status']}"
        )
        assert parse_instant(notice["notice_effective_at"]) == parse_instant(
            self.NOTICE_EFFECTIVE_AT
        ), (
            "48 hours after issuance at 2026-08-03T08:00:00Z is "
            f"2026-08-05T08:00:00Z, got {notice['notice_effective_at']}"
        )

        response = api.create_field_event(
            ctx["work_order"]["id"], field_event_payload("MOBILIZE"), FIELD_TECHNICIAN
        )
        validate_error(
            response, ApiErrorId.ERR_FIRE_MARSHAL_NOTICE_NOT_EFFECTIVE.value, 409
        )

    def test_refused_mobilization_leaves_both_work_order_dimensions_where_they_were(
        self, api
    ):
        """PRD §3.4: "`MOBILIZE` moves `SCHEDULED → MOBILIZED` and is the most heavily gated event in the system, because it is the moment a crew physically arrives on a residential site."
        PRD §3.4: "`START` moves the field dimension `MOBILIZED → IN_PROGRESS` and requires the project to be in `PERMITTED`. It is also the moment the project's own lifecycle turns over: the project advances `PERMITTED → DECOMMISSIONING`, entering the `DECOMMISSIONING` state in which the tank is physically being pulled or filled, and the work order's `method` is copied onto the project as `decommission_method`, freezing what was actually executed independently of what had been recommended."

        Design: Difficulty/cross_entity_state_dependency/work_order_mobilize_requires_effective_fire_marshal_notice
        """
        ctx = self._crew_arriving_before_the_notice_takes_effect()
        api.create_field_event(
            ctx["work_order"]["id"], field_event_payload("MOBILIZE"), FIELD_TECHNICIAN
        )

        work_order = fx.read_work_order(ctx["work_order"]["id"])
        assert work_order["field_status"] == "SCHEDULED", (
            f"the crew never lawfully arrived, got {work_order['field_status']}"
        )
        assert work_order["billing_status"] == "UNBILLED", (
            "the billing dimension is untouched by a refused field event, got "
            f"{work_order['billing_status']}"
        )

        project = fx.read_project(ctx["project"]["id"])
        assert project["status"] == "PERMITTED", (
            f"the project waits in PERMITTED, got {project['status']}"
        )
        assert project["decommission_method"] is None, (
            "the executed method is frozen only when work actually starts, got "
            f"{project['decommission_method']}"
        )


class TestSampleReceiptRequiresAccreditedLaboratory:
    def _aliquot_in_transit_to_an_unaccredited_lab(self):
        ctx = fx.project_at_sampling(laboratory_overrides={"accredited": False})
        ctx["sample"] = fx.create_sample(
            ctx["project"]["id"],
            ctx["work_order"]["id"],
            ctx["laboratory"]["id"],
            sample_point="TANK_BOTTOM",
            depth_inches=96,
        )
        fx.dispatch_sample(ctx["sample"]["id"])
        return ctx

    def test_receipt_by_an_unaccredited_laboratory_is_refused(self, api):
        """PRD §3.6: "Receipt carries three gates, evaluated in order. First, the receiving lab's `accredited` flag must be true, or the receipt is refused with `ERR_LAB_NOT_ACCREDITED`."
        PRD §3.6: "`accredited` defaults to true and records whether the lab holds state accreditation; an unaccredited lab may not take custody of samples at all."

        Design: Difficulty/cross_entity_state_dependency/soil_sample_receive_requires_accredited_laboratory
        """
        ctx = self._aliquot_in_transit_to_an_unaccredited_lab()

        assert fx.read_laboratory(ctx["laboratory"]["id"])["accredited"] is False, (
            "the laboratory under test must be the unaccredited one"
        )

        response = api.create_custody_event(
            ctx["sample"]["id"],
            custody_event_payload("RECEIVE"),
            make_lab_analyst_headers(ctx["laboratory"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_LAB_NOT_ACCREDITED.value, 409)

    def test_refused_receipt_leaves_the_aliquot_in_transit_and_the_project_blocked(
        self, api
    ):
        """PRD §3.6: "`RECEIVE` is a `LabAnalyst` act, permitted only to the lab named as the sample's `laboratory_id`, and moves the sample `IN_TRANSIT → AT_LAB`."
        PRD §3.9: "`SAMPLES_PENDING` is present whenever the project has at least one sample in the current `sampling_round` whose `status` is `COLLECTED`, `IN_TRANSIT` or `AT_LAB`."
        PRD §3.6: "On success `received_at` is stamped from the logical clock, starting this sample's own analysis window."

        Design: Difficulty/cross_entity_state_dependency/soil_sample_receive_requires_accredited_laboratory
        """
        ctx = self._aliquot_in_transit_to_an_unaccredited_lab()
        api.create_custody_event(
            ctx["sample"]["id"],
            custody_event_payload("RECEIVE"),
            make_lab_analyst_headers(ctx["laboratory"]["id"]),
        )

        sample = fx.read_sample(ctx["sample"]["id"])
        assert sample["status"] == "IN_TRANSIT", (
            "the aliquot never changed hands, got "
            f"{sample['status']}"
        )
        assert sample["received_at"] is None, (
            f"no receipt instant is stamped, got {sample['received_at']}"
        )
        assert sample["qc_flag"] == "NONE", (
            "an accreditation refusal is not a quality defect of the aliquot, got "
            f"{sample['qc_flag']}"
        )

        project = fx.read_project(ctx["project"]["id"])
        assert project["status"] == "SAMPLING", (
            f"the confirmation round is still open, got {project['status']}"
        )
        assert "SAMPLES_PENDING" in project["nfa_blockers"], (
            "the aliquot in transit still counts as pending, got "
            f"{project['nfa_blockers']}"
        )


class TestClaimSubmitRequiresAcknowledgedContaminationDisclosure:
    #: New Jersey gross costs of 900,000 cents yield an eligible amount of 818,500.
    CLAIMED_CENTS = 900000

    def _claim_behind_an_unanswered_contamination_notice(self):
        ctx = fx.project_remediation_active_gross()
        ctx["contamination_disclosure"] = fx.create_disclosure(
            ctx["project"]["id"], disclosure_kind="CONTAMINATION_FINDINGS"
        )
        ctx["claim"] = fx.create_claim(
            ctx["project"]["id"], claimed_costs_cents=self.CLAIMED_CENTS
        )
        return ctx

    def test_submission_is_refused_while_the_contamination_notice_is_unanswered(
        self, api
    ):
        """PRD §3.9: "Submission from `DRAFT` requires the project to be in `ASSESSED`, `REMEDIATION_ACTIVE`, `CLEARED` or `CLOSED_NFA`, requires `eligible_amount_cents` to be strictly greater than zero — a zero-value claim is refused with `ERR_CLAIM_NOT_ELIGIBLE` — and, when the project's `contamination_disclosure_required` latch is true, requires that a `CONTAMINATION_FINDINGS` disclosure on the project already stand at `ACKNOWLEDGED`; a missing acknowledgement is refused with `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`."
        PRD §3.2: "The notice is created in `PENDING` with `sent_at` stamped from the logical clock and `expires_at` derived as three days later — the response window is 72 hours."

        Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_acknowledged_contamination_disclosure
        """
        ctx = self._claim_behind_an_unanswered_contamination_notice()

        assert ctx["claim"]["eligible_amount_cents"] == 818500, (
            "900,000 gross under the 4,000,000-cent tier less the 50,000-cent "
            "deductible less the 31,500-cent fee is 818,500 cents, got "
            f"{ctx['claim']['eligible_amount_cents']}"
        )

        response = api.submit_trust_fund_claim(
            ctx["claim"]["id"], COMPLIANCE_OFFICER
        )
        validate_error(response, ApiErrorId.ERR_DISCLOSURE_NOT_ACKNOWLEDGED.value, 409)

    def test_refused_submission_leaves_the_claim_in_draft_and_the_blocker_standing(
        self, api
    ):
        """PRD §2.7: "Second, project-level flags that record that something *has happened* are latches: `remediation_started` is set true the first time a project enters `REMEDIATION_ACTIVE` and is never reset, and `contamination_disclosure_required` is set true the first time the project's `contamination_class` becomes `ELEVATED` or `GROSS` and is likewise never reset, even when a later round classifies `CLEAN`."
        PRD §3.9: "`CONTAMINATION_DISCLOSURE_NOT_ACKNOWLEDGED` is present whenever the project's `contamination_disclosure_required` latch is true and the project has no `CONTAMINATION_FINDINGS` disclosure standing at `ACKNOWLEDGED`."

        Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_acknowledged_contamination_disclosure
        """
        ctx = self._claim_behind_an_unanswered_contamination_notice()
        api.submit_trust_fund_claim(ctx["claim"]["id"], COMPLIANCE_OFFICER)

        claim = fx.read_claim(ctx["claim"]["id"])
        assert claim["status"] == "DRAFT", (
            f"a refused submission leaves the claim in DRAFT, got {claim['status']}"
        )
        assert claim["submitted_at"] is None, (
            f"no submission instant is stamped, got {claim['submitted_at']}"
        )
        assert claim["unreimbursed_balance_cents"] == pytest.approx(818500, abs=0.01), (
            "with nothing disbursed the balance is the whole eligible amount, got "
            f"{claim['unreimbursed_balance_cents']}"
        )

        notice = fx.read_disclosure(ctx["contamination_disclosure"]["id"])
        assert notice["status"] == "PENDING", (
            f"the homeowner has not answered yet, got {notice['status']}"
        )

        project = fx.read_project(ctx["project"]["id"])
        assert project["contamination_disclosure_required"] is True, (
            "the gross classification latched the disclosure requirement"
        )
        assert "CONTAMINATION_DISCLOSURE_NOT_ACKNOWLEDGED" in project["nfa_blockers"], (
            "the unanswered notice must also block closure, got "
            f"{project['nfa_blockers']}"
        )
