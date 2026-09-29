"""State machines that are not a single line: parallel dimensions, bounded cycles, forks."""
from test_helpers import fixtures as fx, parse_instant, validate_error
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import claim_decision_payload
from test_helpers.test_users import COMPLIANCE_OFFICER


class TestParallelWorkOrderDimensions:
    def test_invoicing_advances_billing_without_touching_field_progress(self, api):
        """PRD §3.5: "A work order carries a second, **independent** state dimension. `billing_status` evolves on its own timeline and is never inferred from `field_status`: a work order can sit at `INVOICED` while its project has already moved on to `SAMPLING` or `REMEDIATION_ACTIVE`."
        PRD §3.5: "`INVOICE` moves `BILLABLE → INVOICED` and requires nothing beyond the billing dimension standing at `BILLABLE`; field progress is irrelevant to it."

        Design: Difficulty/non_linear_state_machine/work_order_field_and_billing_dimensions_evolve_independently
        """
        ctx = fx.project_remediation_active_gross()

        invoiced = fx.billing_event(ctx["work_order"]["id"], "INVOICE")
        assert invoiced["billing_status"] == "INVOICED", (
            f"the billing dimension must reach INVOICED, got {invoiced['billing_status']}"
        )
        assert invoiced["field_status"] == "FIELD_COMPLETE", (
            "the field dimension is untouched by a billing event, got "
            f"{invoiced['field_status']}"
        )
        assert fx.read_project(ctx["project"]["id"])["status"] == "REMEDIATION_ACTIVE", (
            "the project's own lifecycle is independent of the billing dimension"
        )

    def test_write_off_from_invoiced_leaves_field_complete_and_records_no_abort(
        self, api
    ):
        """PRD §3.5: "`WRITE_OFF` is accepted while `billing_status` stands at `UNBILLED`, `BILLABLE` or `INVOICED`, and moves the dimension to `WRITTEN_OFF`."
        PRD §3.4: "The dimension runs `SCHEDULED → MOBILIZED → IN_PROGRESS → FIELD_COMPLETE`, with `ABORTED` reachable from any of the first three; `FIELD_COMPLETE` and `ABORTED` are terminal."
        PRD §3.4: "The work order transitions to `ABORTED` with that reason recorded, its `billing_status` is transitioned to `WRITTEN_OFF` whenever it currently stands at `UNBILLED`, `BILLABLE` or `INVOICED`, and the crew's booking interval is released so the crew's calendar no longer collides with future bookings."

        Design: Difficulty/non_linear_state_machine/work_order_field_and_billing_dimensions_evolve_independently
        """
        ctx = fx.project_remediation_active_gross()
        fx.billing_event(ctx["work_order"]["id"], "INVOICE")

        written_off = fx.billing_event(ctx["work_order"]["id"], "WRITE_OFF")
        assert written_off["billing_status"] == "WRITTEN_OFF", (
            "the escape from INVOICED must land on WRITTEN_OFF, got "
            f"{written_off['billing_status']}"
        )
        assert written_off["field_status"] == "FIELD_COMPLETE", (
            "writing off the invoice is not an abort of the field work, got "
            f"{written_off['field_status']}"
        )
        assert written_off["abort_reason"] is None, (
            "no abort happened, so no reason may be recorded, got "
            f"{written_off['abort_reason']}"
        )
        assert fx.read_project(ctx["project"]["id"])["status"] == "REMEDIATION_ACTIVE", (
            "the project stays where the contamination cascade left it"
        )


class TestClaimReviewCycleCeiling:
    #: New Jersey gross costs of 900,000 cents yield an eligible amount of 818,500.
    CLAIMED_CENTS = 900000

    def test_review_cycle_runs_twice_incrementing_the_information_request_count(
        self, api
    ):
        """PRD §3.9: "`INFO_REQUESTED` is accepted from `UNDER_REVIEW` and increments `info_request_count` by 1; because the fund permits at most two rounds of questions, the decision is available only while `info_request_count` is strictly below 2, and a third attempt is refused with `ERR_INFO_REQUEST_LIMIT_REACHED`."
        PRD §3.9: "Re-submission from `INFO_REQUESTED` requires the same set of project states but not the eligibility or disclosure re-checks."

        Design: Difficulty/non_linear_state_machine/trust_fund_claim_review_cycle_bounded_by_info_request_limit
        """
        ctx = fx.project_cleared()
        claim = fx.create_claim(
            ctx["project"]["id"], claimed_costs_cents=self.CLAIMED_CENTS
        )
        assert claim["eligible_amount_cents"] == 818500, (
            "900,000 gross under the 4,000,000-cent tier less the 50,000-cent "
            "deductible less the 31,500-cent fee is 818,500 cents, got "
            f"{claim['eligible_amount_cents']}"
        )

        fx.submit_claim(claim["id"])
        fx.decide_claim(claim["id"], "UNDER_REVIEW")
        first = fx.decide_claim(claim["id"], "INFO_REQUESTED")
        assert first["info_request_count"] == 1, (
            f"the first round of questions counts 1, got {first['info_request_count']}"
        )

        fx.submit_claim(claim["id"])
        fx.decide_claim(claim["id"], "UNDER_REVIEW")
        second = fx.decide_claim(claim["id"], "INFO_REQUESTED")
        assert second["info_request_count"] == 2, (
            f"the second round of questions counts 2, got {second['info_request_count']}"
        )

    def test_third_information_request_is_refused_and_leaves_the_claim_under_review(
        self, api
    ):
        """PRD §3.9: "The cycle `SUBMITTED → UNDER_REVIEW → INFO_REQUESTED → SUBMITTED` may therefore run twice at most."
        PRD §2.11: "**Uniqueness and quota constraints**, in this internal order: `ERR_DUPLICATE_DISCLOSURE` (409), `ERR_WORK_ORDER_ALREADY_OPEN` (409), `ERR_DUPLICATE_FINAL_CLAIM` (409), then `ERR_INFO_REQUEST_LIMIT_REACHED` (409)."

        Design: Difficulty/non_linear_state_machine/trust_fund_claim_review_cycle_bounded_by_info_request_limit
        """
        ctx = fx.project_cleared()
        claim = fx.create_claim(
            ctx["project"]["id"], claimed_costs_cents=self.CLAIMED_CENTS
        )
        for _ in range(2):
            fx.submit_claim(claim["id"])
            fx.decide_claim(claim["id"], "UNDER_REVIEW")
            fx.decide_claim(claim["id"], "INFO_REQUESTED")
        fx.submit_claim(claim["id"])
        fx.decide_claim(claim["id"], "UNDER_REVIEW")

        response = api.decide_trust_fund_claim(
            claim["id"], claim_decision_payload("INFO_REQUESTED"), COMPLIANCE_OFFICER
        )
        validate_error(
            response, ApiErrorId.ERR_INFO_REQUEST_LIMIT_REACHED.value, 409
        )

        settled = fx.read_claim(claim["id"])
        assert settled["info_request_count"] == 2, (
            "the refused third request must not increment the counter, got "
            f"{settled['info_request_count']}"
        )
        assert settled["status"] == "UNDER_REVIEW", (
            "the claim stays where the last accepted decision left it, got "
            f"{settled['status']}"
        )


class TestPermitDecisionFork:
    def test_denied_branch_stores_the_reason_and_changes_nothing_else(self, api):
        """PRD §3.3: "**The `DENIED` branch** requires the permit to be in `SUBMITTED` and requires `denial_reason` to accompany the decision."
        PRD §3.3: "Nothing else happens: the project's `status` is unchanged and remains `DISCLOSED`, no work order is touched, and no blocker is added."

        Design: Difficulty/non_linear_state_machine/permit_decision_fork_branches_carry_disjoint_side_effect_sets
        """
        ctx = fx.project_at_disclosed()
        permit = fx.create_permit(ctx["project"]["id"], "FIRE_MARSHAL_NOTIFICATION")
        denied = fx.decide_permit(
            permit["id"],
            "DENIED",
            denial_reason="application missing the tank tightness report",
        )

        assert denied["status"] == "DENIED", (
            f"the decision must land the permit in DENIED, got {denied['status']}"
        )
        assert denied["issued_at"] is None, (
            f"a denial stamps no issuance instant, got {denied['issued_at']}"
        )
        assert denied["notice_effective_at"] is None, (
            "the statutory wait is derived only on issuance, got "
            f"{denied['notice_effective_at']}"
        )
        assert fx.read_project(ctx["project"]["id"])["status"] == "DISCLOSED", (
            "a denial is a dead end for the permit row, not for the project"
        )

    def test_issued_municipal_branch_derives_validity_and_advances_the_project(
        self, api
    ):
        """PRD §3.3: "On success the permit transitions `SUBMITTED → ISSUED`, `issued_at` is stamped from the logical clock, and `expires_at` is derived as exactly 180 days after issuance, after which the permit lapses."
        PRD §3.3: "The `notice_effective_at` field is where the two types diverge: for a `FIRE_MARSHAL_NOTIFICATION` it is 48 hours after `issued_at`, encoding the two-day statutory wait before ground may be broken, while for a `MUNICIPAL_DECOMMISSION` it is simply equal to `issued_at`."
        PRD §3.3: "Finally, and only for a `MUNICIPAL_DECOMMISSION` permit, the project advances `DISCLOSED → PERMITTED`."

        Design: Difficulty/non_linear_state_machine/permit_decision_fork_branches_carry_disjoint_side_effect_sets
        """
        ctx = fx.project_at_disclosed(clock="2026-08-03T08:00:00Z")
        permit = fx.create_permit(ctx["project"]["id"], "MUNICIPAL_DECOMMISSION")
        issued = fx.decide_permit(permit["id"], "ISSUED")

        assert issued["status"] == "ISSUED", (
            f"the authorisation must land in ISSUED, got {issued['status']}"
        )
        assert parse_instant(issued["notice_effective_at"]) == parse_instant(
            "2026-08-03T08:00:00Z"
        ), (
            "a municipal permit's notice takes effect at issuance itself, got "
            f"{issued['notice_effective_at']}"
        )
        assert parse_instant(issued["expires_at"]) == parse_instant(
            "2027-01-30T08:00:00Z"
        ), (
            "180 days after 2026-08-03T08:00:00Z is 2027-01-30T08:00:00Z, got "
            f"{issued['expires_at']}"
        )
        assert fx.read_project(ctx["project"]["id"])["status"] == "PERMITTED", (
            "only the municipal authorisation advances the project"
        )

    def test_revoked_branch_aborts_live_field_work_and_adds_a_closure_blocker(
        self, api
    ):
        """PRD §3.3: "Every `DecommissionWorkOrder` on the project whose `field_status` is `SCHEDULED`, `MOBILIZED` or `IN_PROGRESS` is transitioned to `ABORTED` with `abort_reason` set to `PERMIT_REVOKED`, and its `billing_status` is transitioned to `WRITTEN_OFF`."
        PRD §3.9: "`PERMIT_REVOKED` is present whenever the project has at least one `MUNICIPAL_DECOMMISSION` permit whose `status` is `REVOKED` or `EXPIRED`."

        Design: Difficulty/non_linear_state_machine/permit_decision_fork_branches_carry_disjoint_side_effect_sets
        """
        ctx = fx.project_with_booked_work_order()
        fx.decide_permit(
            ctx["municipal_permit"]["id"],
            "REVOKED",
            revocation_reason="municipal engineer pulled the authorisation",
        )

        work_order = fx.read_work_order(ctx["work_order"]["id"])
        assert work_order["field_status"] == "ABORTED", (
            f"the live booking must be aborted, got {work_order['field_status']}"
        )
        assert work_order["billing_status"] == "WRITTEN_OFF", (
            f"the abort writes the billing off, got {work_order['billing_status']}"
        )
        assert work_order["abort_reason"] == "PERMIT_REVOKED", (
            "the cascade records why the booking died, got "
            f"{work_order['abort_reason']}"
        )

        project = fx.read_project(ctx["project"]["id"])
        assert "PERMIT_REVOKED" in project["nfa_blockers"], (
            f"the revocation must name a closure blocker, got {project['nfa_blockers']}"
        )
        assert project["status"] == "PERMITTED", (
            "a revocation does not itself move the project's own status, got "
            f"{project['status']}"
        )
