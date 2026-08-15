"""Warranty claims, no-cost retreats, and joint-use attachment audits
(PRD §3.6, §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    adjudicate_claim,
    apply_treatment,
    assert_attachment_audit,
    assert_instant_equals,
    assert_treatment_work_order,
    assert_warranty_claim,
    create_budget,
    create_crew,
    create_pole,
    create_treatment_order,
    create_verified_treatment,
    create_warranty_claim_payload,
    file_claim,
    get_cycle,
    get_pole,
    get_treatment,
    qa_review_treatment,
    reconcile_cycle,
    schedule_treatment,
    set_clock,
    setup_notified_audit,
    setup_submitted_joint_use_task,
    setup_verified_order_with_claim,
    validate_error,
    validate_paginated,
    validate_success,
)

_PM = TEST_USERS["program_manager_headers"]


class TestClaimCollection:
    def test_fk_reverse_reachability_claims_under_order(self, api, program_manager_headers):
        """PRD §3.6: "All claims against an order can be listed through the order's
        claim collection, which may hold zero or more claims over the order's life."

        Design: Corner/entities/fk_reverse_reachability_claims_under_order
        """
        pole = create_pole(pole_number="P-FK")
        crew = create_crew(crew_code="CR-FK")
        order = create_verified_treatment(pole["id"], crew["id"],
                                          product_code="PENTA_GEL", cost_cents=21000)
        before, _ = validate_paginated(
            api.list_warranty_claims_for_order(order["id"], program_manager_headers)
        )
        assert before == [], "no claims before any filing"

        file_claim(order["id"], claim_reason="PRODUCT_FAILURE")
        after, _ = validate_paginated(
            api.list_warranty_claims_for_order(order["id"], program_manager_headers)
        )
        assert len(after) == 1
        assert_warranty_claim(after[0])
        assert after[0]["status"] == "FILED"
        assert after[0]["treatment_order_id"] == order["id"]


class TestClaimPreconditions:
    def _setup_applied_unverified(self, api):
        pole = create_pole(pole_number="P-CL")
        crew = create_crew(crew_code="CR-C")
        order = create_treatment_order(pole["id"], product_code="PENTA_GEL",
                                       cost_cents=21000)
        schedule_treatment(order["id"], crew["id"],
                           work_start_date="2026-08-10", work_end_date="2026-08-12")
        apply_treatment(order["id"], crew["id"])
        return pole, crew, order

    def test_claim_on_unverified_order_rejected(self, api, program_manager_headers):
        """PRD §3.6: "The target order must have reached `VERIFIED`; a claim against an
        order in any other status is rejected as an invalid-state error
        (`ERR_INVALID_STATE`)."

        Design: Difficulty/cross_entity_state_dependency/claim_requires_verified_order_and_live_warranty
        """
        _, _, order = self._setup_applied_unverified(api)
        resp = api.create_warranty_claim(
            create_warranty_claim_payload(order["id"],
                                          claim_reason="DECAY_RECURRENCE"),
            program_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_claim_on_verified_order_within_warranty_succeeds(
            self, api, program_manager_headers):
        """PRD §3.5: "`warranty_years` is drawn from the product — ten years for
        `CCA_WRAP`, eight for `PENTA_GEL`, five for `COPPER_NAPHTHENATE` — and
        `warranty_end_date` is `applied_at` advanced by that many years, keeping the
        same month and day".
        PRD §3.5: "A claim is within warranty when its filing time falls on or before
        `warranty_end_date`; the boundary is inclusive."

        Design: Difficulty/cross_entity_state_dependency/claim_requires_verified_order_and_live_warranty
        """
        _, _, order = self._setup_applied_unverified(api)
        qa_review_treatment(order["id"], "PASS")
        verified = get_treatment(order["id"])
        assert verified["status"] == "VERIFIED"
        # PENTA_GEL: eight years from the 2026-08-01 application.
        assert_instant_equals(verified["warranty_end_date"], "2034-08-01T00:00:00Z",
                              "warranty_end_date")
        assert verified["warranty_years"] == 8

        resp = api.create_warranty_claim(
            create_warranty_claim_payload(order["id"],
                                          claim_reason="DECAY_RECURRENCE"),
            program_manager_headers,
        )
        claim = validate_success(resp, expected_status=201)
        assert_warranty_claim(claim)
        assert claim["status"] == "FILED"
        assert_instant_equals(claim["filed_at"], "2026-08-01T00:00:00Z", "filed_at")

    def test_claim_already_open_rejected(self, api, program_manager_headers):
        """PRD §3.6: "only one open claim may exist per treatment order, so filing
        while another claim for the same order is still `FILED` is rejected with
        `ERR_CLAIM_ALREADY_OPEN`".

        Design: Corner/validations/claim_already_open_rejected
        """
        _, _, order, _ = setup_verified_order_with_claim(
            product_code="CCA_WRAP", cost_cents=17500, claim_reason="PRODUCT_FAILURE"
        )
        resp = api.create_warranty_claim(
            create_warranty_claim_payload(order["id"],
                                          claim_reason="DECAY_RECURRENCE"),
            program_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_ALREADY_OPEN)

    def test_warranty_expired_after_end_date(self, api, program_manager_headers):
        """PRD §3.6: "the claim's filing must fall within the warranty window —
        `filed_at` on or before the order's `warranty_end_date`, inclusively —
        otherwise the filing is rejected with `ERR_WARRANTY_EXPIRED`."

        Design: Corner/validations/warranty_expired_after_end_date
        """
        p1 = create_pole(pole_number="P-WX1")
        p2 = create_pole(pole_number="P-WX2")
        crew = create_crew(crew_code="CR-WX")
        o1 = create_verified_treatment(p1["id"], crew["id"],
                                       product_code="COPPER_NAPHTHENATE",
                                       cost_cents=14500,
                                       work_start_date="2026-08-10",
                                       work_end_date="2026-08-12")
        o2 = create_verified_treatment(p2["id"], crew["id"],
                                       product_code="COPPER_NAPHTHENATE",
                                       cost_cents=14500,
                                       work_start_date="2026-08-12",
                                       work_end_date="2026-08-14")
        # COPPER_NAPHTHENATE: five years from 2026-08-01 -> warranty_end 2031-08-01.
        set_clock("2031-08-01T00:00:00Z")
        resp = api.create_warranty_claim(
            create_warranty_claim_payload(o1["id"]), program_manager_headers
        )
        claim = validate_success(resp, expected_status=201)
        assert claim["status"] == "FILED", (
            "filing exactly at warranty_end_date succeeds (inclusive boundary)"
        )

        set_clock("2031-08-02T00:00:00Z")
        resp = api.create_warranty_claim(
            create_warranty_claim_payload(o2["id"]), program_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED)


class TestAdjudication:
    def test_adjudicate_claim_twice_rejected(self, api, program_manager_headers):
        """PRD §3.6: "Adjudication is a `ProgramManager` decision on a `FILED` claim,
        carrying an `outcome` and an optional free-text `adjudication_note`."
        PRD §3.6: "An outcome of `DENY` moves the claim to the terminal `DENIED` state
        and stamps the `adjudication_note`."

        Design: Corner/state_machines/adjudicate_claim_twice_rejected
        """
        _, _, order, claim = setup_verified_order_with_claim(
            product_code="CCA_WRAP", cost_cents=17500, claim_reason="PRODUCT_FAILURE"
        )
        denied = adjudicate_claim(claim["id"], "DENY",
                                  adjudication_note="wear is normal")
        assert denied["status"] == "DENIED"
        assert denied["adjudication_note"] == "wear is normal"

        resp = api.adjudicate_warranty_claim(
            claim["id"], {"outcome": "HONOR"}, program_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        retreats, _ = validate_paginated(
            api.list_treatment_work_orders(program_manager_headers,
                                           params={"source_claim_id": claim["id"]})
        )
        assert retreats == [], "DENY creates no retreat order"


class TestWarrantyHonorRetreatChain:
    def _setup_honored(self, api, program_manager_headers):
        pole, crew, order, claim = setup_verified_order_with_claim(
            product_code="PENTA_GEL", cost_cents=21000,
            claim_reason="DECAY_RECURRENCE"
        )
        resp = api.adjudicate_warranty_claim(
            claim["id"],
            {"outcome": "HONOR", "adjudication_note": "decay under wrap"},
            program_manager_headers,
        )
        honored = validate_success(resp, expected_status=200)
        return pole, order, honored

    def test_warranty_honor_creates_retreat_order(self, api, program_manager_headers):
        """PRD §3.6: "An outcome of `HONOR` moves the claim to the terminal `HONORED`
        state and auto-creates a retreat `TreatmentWorkOrder`: the new order carries
        `is_warranty_retreat` set to true, a `cost_cents` of zero, a `source_claim_id`
        pointing back to the claim, and the same `pole_id` and `product_code` as the
        original order."

        Design: Difficulty/transitive_cascade/warranty_honor_retreat_chain_depth2
        """
        pole, order, honored = self._setup_honored(api, program_manager_headers)
        assert honored["status"] == "HONORED"
        retreats, _ = validate_paginated(
            api.list_treatment_work_orders(program_manager_headers,
                                           params={"source_claim_id": honored["id"]})
        )
        assert len(retreats) == 1, "HONOR auto-creates exactly one retreat order"
        retreat = retreats[0]
        assert_treatment_work_order(retreat)
        assert retreat["is_warranty_retreat"] is True
        assert retreat["cost_cents"] == 0
        assert retreat["source_claim_id"] == honored["id"]
        assert retreat["pole_id"] == pole["id"]
        assert retreat["product_code"] == "PENTA_GEL"
        assert retreat["status"] == "CREATED"

    def test_warranty_honor_increments_open_treatment_count(
            self, api, program_manager_headers):
        """PRD §3.6: "Like any order creation, the retreat increments the pole's
        `open_treatment_count`, and it flows through the ordinary scheduling,
        application, and quality-review lifecycle of §3.5."
        PRD §3.5: "The order starts in `CREATED`, and its creation increments the
        pole's `open_treatment_count` — the running count of orders for the pole in
        `CREATED`, `SCHEDULED`, `APPLIED`, or `FAILED_QA`."

        Design: Difficulty/transitive_cascade/warranty_honor_retreat_chain_depth2
        """
        pole, _, _ = self._setup_honored(api, program_manager_headers)
        after = get_pole(pole["id"])
        # The original order's VERIFIED transition decremented the count to 0; the
        # retreat order (CREATED) brings it back to 1.
        assert after["open_treatment_count"] == 1


class TestAuditParallelDimensions:
    def _setup_audit(self, api, program_manager_headers):
        pole, cycle, task, audit = setup_submitted_joint_use_task(
            found_attachment_count=5, declared=2,
            pole_overrides={"pole_number": "P-JU"},
        )
        return pole, audit

    def test_audit_adjudicate_walks_violation_to_notified(
            self, api, program_manager_headers):
        """PRD §3.7: "The audit's computed `unauthorized_count` is the found count
        minus the pole's `attachment_count_declared`, floored at zero."
        PRD §3.7: "when `unauthorized_count` is greater than zero, `violation_status`
        advances from `NONE` to `DETECTED` and immediately on to `NOTIFIED` — the
        notice is issued as part of the adjudication — and the `cure_deadline` is set
        to `adjudicated_at` plus 45 days."

        Design: Difficulty/non_linear_state_machine/audit_parallel_dimensions_evolve_independently
        """
        _, audit = self._setup_audit(api, program_manager_headers)
        assert audit["audit_status"] == "SUBMITTED"
        assert audit["violation_status"] == "NONE"
        resp = api.adjudicate_attachment_audit(audit["id"], program_manager_headers)
        adjudicated = validate_success(resp, expected_status=200)
        assert_attachment_audit(adjudicated)
        assert adjudicated["audit_status"] == "ADJUDICATED"
        assert adjudicated["violation_status"] == "NOTIFIED"
        assert adjudicated["unauthorized_count"] == 3
        assert_instant_equals(adjudicated["adjudicated_at"], "2026-08-01T00:00:00Z",
                              "adjudicated_at")
        assert_instant_equals(adjudicated["cure_deadline"], "2026-09-15T00:00:00Z",
                              "cure_deadline (adjudicated_at + 45 days)")

    def test_audit_mark_cured_leaves_audit_status(self, api, attacher_rep_headers):
        """PRD §3.7: "Marking cured stamps `cured_at` and moves the violation dimension
        to `CURED`; it does not alter `audit_status`, which remains `ADJUDICATED`."

        Design: Difficulty/non_linear_state_machine/audit_parallel_dimensions_evolve_independently
        """
        _, audit = self._setup_audit(api, attacher_rep_headers)
        # Adjudication is a ProgramManager act (PRD §3.7); curing is the AttacherRep's.
        validate_success(
            api.adjudicate_attachment_audit(audit["id"], _PM), expected_status=200
        )
        resp = api.mark_cured_attachment_audit(audit["id"], attacher_rep_headers)
        cured = validate_success(resp, expected_status=200)
        assert cured["violation_status"] == "CURED"
        assert cured["audit_status"] == "ADJUDICATED", (
            "mark-cured moves only the violation dimension"
        )
        assert_instant_equals(cured["cured_at"], "2026-08-01T00:00:00Z", "cured_at")


class TestAuditDeadlineEnforcement:
    def test_audit_auto_escalates_at_reconcile_past_deadline(
            self, api, program_manager_headers):
        """PRD §3.9: "Step two escalates overdue violations: every `AttachmentAudit`
        whose `violation_status` is `NOTIFIED` and whose `cure_deadline` has passed
        relative to the current logical time moves to `ESCALATED`."
        PRD §3.7: "If the deadline passes with the violation still `NOTIFIED`, the
        violation does not drift on its own — it is escalated by the cycle reconcile
        of §3.9, which moves every overdue `NOTIFIED` violation to `ESCALATED`."

        Design: Corner/state_machines/audit_auto_escalates_at_reconcile_past_deadline
        """
        budget = create_budget(fiscal_year=2026, total_cents=1000)
        pole, cycle, task, audit = setup_notified_audit(found_attachment_count=3,
                                                        declared=1)
        set_clock("2026-09-20T00:00:00Z")
        reconcile_cycle(cycle["id"], budget["id"])
        after = validate_success(
            api.get_attachment_audit(audit["id"], program_manager_headers)
        )
        assert after["violation_status"] == "ESCALATED", (
            "cure_deadline 2026-09-15 < now 2026-09-20 must escalate at reconcile"
        )
        assert after["audit_status"] == "ADJUDICATED"
        assert get_cycle(cycle["id"])["status"] == "RECONCILED"

    def test_mark_cured_after_deadline_rejected(self, api, attacher_rep_headers):
        """PRD §3.7: "An `AttacherRep` marks the violation cured, which requires
        `violation_status` to be `NOTIFIED` and the current logical time to be on or
        before `cure_deadline`; a late attempt is rejected with
        `ERR_CURE_DEADLINE_PASSED`."

        Design: Corner/state_machines/mark_cured_after_deadline_rejected
        """
        _, _, _, audit = setup_notified_audit(found_attachment_count=2, declared=1)
        set_clock("2026-09-16T00:00:00Z")
        resp = api.mark_cured_attachment_audit(audit["id"], attacher_rep_headers)
        validate_error(resp, ApiErrorId.ERR_CURE_DEADLINE_PASSED)
        after = validate_success(api.get_attachment_audit(audit["id"], _PM))
        assert after["violation_status"] == "NOTIFIED"
