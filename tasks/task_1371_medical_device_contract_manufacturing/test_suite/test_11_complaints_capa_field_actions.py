"""Complaints, CAPA loop, and field actions — rates, cascades, and linkages."""
import pytest

from test_helpers import (
    QE_ALICE,
    QM_BOB,
    RA_1,
    ApiErrorId,
    add_component,
    complete_lot,
    create_capa,
    create_capa_payload,
    create_complaint,
    create_complaint_payload,
    create_field_action,
    create_field_action_payload,
    create_lot,
    create_ncr,
    create_part,
    create_qualified_supplier,
    create_releasable_lot,
    create_released_lot,
    create_validated_stack,
    contain_ncr,
    disposition_ncr,
    close_ncr,
    find_capa_by_source_complaint,
    get_lot,
    investigate_complaint,
    make_quality_manager_headers,
    qe,
    qm,
    ra,
    validate_error,
    validate_success,
    validate_paginated,
    verify_capa,
    walk_capa_to_effectiveness_check,
    api_client,
)


def _complaint_stack(prefix, receive_qty=100):
    stack = create_validated_stack(prefix)
    qs = create_qualified_supplier(f"SUP-{prefix.removeprefix('DEV-')}", f"{prefix} Co")
    part = create_part(
        qs["supplier"]["id"], f"PN-{prefix.removeprefix('DEV-')}", receive_qty=receive_qty
    )
    return stack, qs, part


class TestComplaintRateBoundary:
    def _rate_setup(self, prefix, big_qty, big_mfg="2026-08-05T00:00:00Z"):
        """Three 10-unit priming lots (100% sampled) plus one big lot, all
        RELEASED; returns (stack, big_lot_bundle)."""
        stack, _qs, part = _complaint_stack(prefix, receive_qty=30000)
        for i in (1, 2, 3):
            create_released_lot(
                stack, part,
                lot_number=f"{prefix}-LT{i}", quantity=10,
                manufactured_at=f"2026-08-0{i + 1}T00:00:00Z",
                supplier_lot_number=f"SL-{prefix}-{i}",
            )
        big = create_released_lot(
            stack, part,
            lot_number=f"{prefix}-LT4", quantity=big_qty,
            manufactured_at=big_mfg,
            supplier_lot_number=f"SL-{prefix}-4",
        )
        return stack, part, big

    def test_rate_zero_before_and_exactly_5_after_confirmation(self, api):
        """PRD section 3.7: "then computes the rate as zero when the denominator
        is zero, otherwise the numerator divided by the denominator, multiplied
        by one hundred thousand, and rounded half-up to four decimal places; and
        finally stores `complaint_rate_per_100k` and sets
        `field_action_review_required` true exactly when the rate is at least
        5.0." — 1 confirmed complaint over 20000 releasable units is exactly 5.0.

        Design: Difficulty/boundary_precision_check/complaint_rate_exactly_5_sets_flag
        """
        stack, _part, big = self._rate_setup("DEV-R5", 20125)
        assert big["lot"]["releasable_qty"] == 20000

        dmr_before = validate_success(api.get_dmr(stack["dmr"]["id"], ra()))
        assert dmr_before["complaint_rate_per_100k"] == 0
        assert dmr_before["field_action_review_required"] is False

        complaint = create_complaint("CMP-R1", big["lot"]["id"], severity="SERIOUS_INJURY")
        investigate_complaint(complaint["id"], confirmed=True)

        dmr_after = validate_success(api.get_dmr(stack["dmr"]["id"], ra()))
        assert dmr_after["complaint_rate_per_100k"] == pytest.approx(5.0, abs=1e-9)

    def test_flag_flips_true_at_inclusive_threshold(self, api):
        """PRD section 3.7: "and finally stores `complaint_rate_per_100k` and
        sets `field_action_review_required` true exactly when the rate is at
        least 5.0." — the threshold is inclusive: at exactly 5.0 the flag is
        true, while it is false beforehand.

        Design: Difficulty/boundary_precision_check/complaint_rate_exactly_5_sets_flag
        """
        stack, _part, big = self._rate_setup("DEV-R5", 20125)
        dmr_before = validate_success(api.get_dmr(stack["dmr"]["id"], ra()))
        assert dmr_before["field_action_review_required"] is False

        complaint = create_complaint("CMP-R1", big["lot"]["id"], severity="SERIOUS_INJURY")
        investigate_complaint(complaint["id"], confirmed=True)

        dmr_after = validate_success(api.get_dmr(stack["dmr"]["id"], ra()))
        assert dmr_after["complaint_rate_per_100k"] == pytest.approx(5.0, abs=1e-9)
        assert dmr_after["field_action_review_required"] is True, (
            "rate of exactly 5.0 satisfies the inclusive at-least-5.0 rule"
        )

    def test_rounding_below_threshold_keeps_flag_false(self, api):
        """PRD section 3.7: "rounded half-up to four decimal places; and finally
        stores `complaint_rate_per_100k` and sets `field_action_review_required`
        true exactly when the rate is at least 5.0." — 1 over 20001 rounds to
        4.9998, strictly below 5.0. PRD section 3.7: "When the complaint is
        confirmed with severity `SERIOUS_INJURY` or `DEATH`, two cascades fire
        together: a CAPA is auto-created ..." — a `MINOR` complaint spawns none.

        Design: Corner/calculations/complaint_rate_rounding_stays_below_threshold
        """
        stack, _part, big = self._rate_setup("DEV-RB", 20126)
        assert big["lot"]["releasable_qty"] == 20001

        complaint = create_complaint("CMP-RB", big["lot"]["id"], severity="MINOR")
        investigate_complaint(complaint["id"], confirmed=True)

        dmr = validate_success(api.get_dmr(stack["dmr"]["id"], ra()))
        assert dmr["complaint_rate_per_100k"] == pytest.approx(4.9998, abs=1e-9)
        assert dmr["field_action_review_required"] is False

        page, _meta = validate_paginated(
            api.list_capas(qe(), params={"source_complaint_id": complaint["id"]})
        )
        assert page == [], "a confirmed MINOR complaint must not spawn a CAPA"


class TestComplaintRateFeedbackEvaluationOrder:
    def test_confirmation_sets_rate_and_flag_at_threshold(self, api):
        """PRD section 3.7: "the system first applies all entity mutations of the
        triggering action; then sums the denominator as the total
        `releasable_qty` across the DMR's lots in `RELEASED`; then counts the
        numerator as the confirmed complaints in `INVESTIGATED` or `CLOSED` whose
        lot belongs to the DMR" and "finally stores `complaint_rate_per_100k`
        and sets `field_action_review_required` true exactly when the rate is at
        least 5.0."

        Design: Difficulty/combinatorial_formula/complaint_rate_feedback_evaluation_order
        """
        stack, _qs, part = _complaint_stack("DEV-C", receive_qty=30000)
        for i in (1, 2, 3):
            create_released_lot(
                stack, part,
                lot_number=f"LT-C{i}", quantity=10,
                manufactured_at=f"2026-08-0{i + 1}T00:00:00Z",
                supplier_lot_number=f"SL-C{i}",
            )
        big = create_released_lot(
            stack, part, lot_number="LT-C4", quantity=20125,
            manufactured_at="2026-08-05T00:00:00Z", supplier_lot_number="SL-C4",
        )
        assert big["lot"]["releasable_qty"] == 20000

        complaint = create_complaint(
            "CMP-C1", big["lot"]["id"], severity="SERIOUS_INJURY",
            description="catheter fracture",
        )
        investigate_complaint(complaint["id"], confirmed=True)

        dmr = validate_success(api.get_dmr(stack["dmr"]["id"], ra()))
        assert dmr["complaint_rate_per_100k"] == pytest.approx(5.0, abs=1e-9)
        assert dmr["field_action_review_required"] is True

    def test_recall_of_all_released_lots_zeroes_rate_and_clears_flag(self, api):
        """PRD section 3.7: "Issuing stamps `issued_at`, recalls every `RELEASED`
        lot of the DMR whose `manufactured_at` falls within the closed scope
        interval ... and records how many lots transitioned as
        `recalled_lot_count`." and PRD section 3.6: "Recall voids the lot's
        `APPROVED` and `PRINTED` labels (`LOT_RECALLED`) and recomputes the DMR's
        complaint rate with this lot's `releasable_qty` leaving the denominator"
        — with the denominator at zero, "the rate as zero when the denominator
        is zero".

        Design: Difficulty/combinatorial_formula/complaint_rate_feedback_evaluation_order
        """
        stack, _qs, part = _complaint_stack("DEV-C", receive_qty=30000)
        for i in (1, 2, 3):
            create_released_lot(
                stack, part,
                lot_number=f"LT-C{i}", quantity=10,
                manufactured_at=f"2026-08-0{i + 1}T00:00:00Z",
                supplier_lot_number=f"SL-C{i}",
            )
        big = create_released_lot(
            stack, part, lot_number="LT-C4", quantity=20125,
            manufactured_at="2026-08-05T00:00:00Z", supplier_lot_number="SL-C4",
        )
        complaint = create_complaint(
            "CMP-C1", big["lot"]["id"], severity="SERIOUS_INJURY",
            description="catheter fracture",
        )
        investigate_complaint(complaint["id"], confirmed=True)

        fa = create_field_action("FA-C1", stack["dmr"]["id"], complaint["id"])
        issued = validate_success(api.issue_field_action(fa["id"], ra()))
        assert issued["status"] == "ISSUED"
        assert issued["recalled_lot_count"] == 4

        dmr = validate_success(api.get_dmr(stack["dmr"]["id"], ra()))
        assert dmr["complaint_rate_per_100k"] == 0
        assert dmr["field_action_review_required"] is False

        recalled = get_lot(big["lot"]["id"])
        assert recalled["disposition_status"] == "RECALLED"
        label = validate_success(api.get_label(big["label"]["id"], ra()))
        assert label["status"] == "VOID"
        assert label["void_reason"] == "LOT_RECALLED"


class TestComplaintCloseRequiresCapaClosed:
    def _setup_confirmed_serious_complaint(self):
        stack, _qs, part = _complaint_stack("DEV-X3")
        bundle = create_released_lot(
            stack, part, lot_number="LT-X3", supplier_lot_number="SL-X3"
        )
        complaint = create_complaint(
            "CMP-X3", bundle["lot"]["id"], severity="SERIOUS_INJURY",
            description="fracture in field",
        )
        investigate_complaint(complaint["id"], confirmed=True)
        capa = find_capa_by_source_complaint(complaint["id"])
        return stack, complaint, capa

    def test_close_blocked_while_spawned_capa_open(self, api):
        """PRD section 3.7: "Closing a complaint requires every CAPA spawned from
        it to be `CLOSED` (`ERR_CAPA_NOT_CLOSED`)." and "a CAPA is auto-created
        in `INITIATED` with `source_type` `COMPLAINT`, `source_complaint_id`
        pointing at this complaint, `dmr_id` taken from the complained lot's DMR,
        `initiator_user_id` set to the investigator, and `process_change` false".

        Design: Difficulty/cross_entity_state_dependency/complaint_close_requires_capa_closed
        """
        stack, complaint, capa = self._setup_confirmed_serious_complaint()
        assert capa["status"] == "INITIATED"
        assert capa["source_type"] == "COMPLAINT"
        assert capa["source_complaint_id"] == complaint["id"]
        assert capa["dmr_id"] == stack["dmr"]["id"]

        resp = api.close_complaint(complaint["id"], ra())
        validate_error(resp, ApiErrorId.ERR_CAPA_NOT_CLOSED)

    def test_close_succeeds_after_spawned_capa_closed(self, api):
        """PRD section 3.7: "Closing a complaint requires every CAPA spawned from
        it to be `CLOSED` (`ERR_CAPA_NOT_CLOSED`)." — once the CAPA is verified
        effective by a quality manager who is not its initiator, the complaint
        closes.

        Design: Difficulty/cross_entity_state_dependency/complaint_close_requires_capa_closed
        """
        _stack, complaint, capa = self._setup_confirmed_serious_complaint()
        # CAPA initiator is the complaint investigator (ra-1); the QM verifier differs.
        walk_capa_to_effectiveness_check(capa["id"], action_summary="redesign joint")
        closed_capa = verify_capa(capa["id"], effective=True, verifier=QM_BOB)
        assert closed_capa["status"] == "CLOSED"

        closed = validate_success(api.close_complaint(complaint["id"], ra()))
        assert closed["status"] == "CLOSED"


class TestComplaintLifecycle:
    def test_complaint_on_unreleased_lot_rejected(self, api):
        """PRD section 3.7: "Intake requires a unique `complaint_code`, the
        `lot_id` of the complained unit — and that lot must be `RELEASED` or
        `RECALLED` (`ERR_LOT_NOT_RELEASED`)"."

        Design: Corner/endpoints/complaint_on_unreleased_lot_rejected
        """
        stack = create_validated_stack("DEV-CU")
        lot = create_lot("LT-CU", stack["dmr"]["id"], stack["protocol"]["id"])
        resp = api.create_complaint(
            create_complaint_payload(
                lot["id"], complaint_code="CMP-CU", severity="MINOR",
                description="early report",
            ),
            ra(),
        )
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_RELEASED)

    def test_complaint_closed_terminal_lockdown(self, api):
        """PRD section 3.7: "Reopening an `INVESTIGATED` complaint returns it to
        `UNDER_INVESTIGATION`" — from `CLOSED` no reopen transition is declared,
        and PRD section 2.10 step 7 rejects it (`ERR_INVALID_STATE_TRANSITION`).

        Design: Corner/state_machines/complaint_closed_terminal_lockdown
        """
        stack, _qs, part = _complaint_stack("DEV-CT")
        bundle = create_released_lot(stack, part, lot_number="LT-CT", supplier_lot_number="SL-CT")
        complaint = create_complaint("CMP-CT", bundle["lot"]["id"], severity="MINOR")
        investigate_complaint(complaint["id"], confirmed=False)
        closed = validate_success(api.close_complaint(complaint["id"], ra()))
        assert closed["status"] == "CLOSED"

        resp = api.reopen_complaint(complaint["id"], ra())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_complaint_reopen_resets_confirmation(self, api):
        """PRD section 3.7: "Reopening an `INVESTIGATED` complaint returns it to
        `UNDER_INVESTIGATION`, resets `confirmed` to false, and recomputes the
        rate with this complaint dropped from the numerator."

        Design: Corner/state_machines/complaint_reopen_resets_confirmation
        """
        stack, _qs, part = _complaint_stack("DEV-CR")
        bundle = create_released_lot(stack, part, lot_number="LT-CR", supplier_lot_number="SL-CR")
        complaint = create_complaint("CMP-CR", bundle["lot"]["id"], severity="MINOR")
        investigate_complaint(complaint["id"], confirmed=True)

        reopened = validate_success(api.reopen_complaint(complaint["id"], ra()))
        assert reopened["status"] == "UNDER_INVESTIGATION"
        assert reopened["confirmed"] is False

        dmr = validate_success(api.get_dmr(stack["dmr"]["id"], ra()))
        assert dmr["complaint_rate_per_100k"] == 0


class TestCapaWorkflow:
    def test_capa_ineffective_loop_cycles(self, api):
        """PRD section 3.7: "`effective` false moves it to `INEFFECTIVE`, from
        which restarting investigation returns it to `INVESTIGATING` and
        increments `effectiveness_cycles` by one."

        Design: Corner/state_machines/capa_ineffective_loop_cycles
        """
        stack = create_validated_stack("DEV-CL")
        capa = create_capa("CAPA-CL", stack["dmr"]["id"], source_type="MANUAL",
                           process_change=False)
        walk_capa_to_effectiveness_check(capa["id"], action_summary="retrain line")

        ineffective = verify_capa(capa["id"], effective=False)
        assert ineffective["status"] == "INEFFECTIVE"

        restarted = validate_success(api.restart_capa_investigation(capa["id"], qe()))
        assert restarted["status"] == "INVESTIGATING"
        assert restarted["effectiveness_cycles"] == 1

        validate_success(api.plan_capa_actions(capa["id"], {"action_summary": "second plan"}, qe()))
        validate_success(api.implement_capa(capa["id"], qe()))
        validate_success(api.complete_capa_implementation(capa["id"], qe()))
        closed = verify_capa(capa["id"], effective=True)
        assert closed["status"] == "CLOSED"
        assert closed["effectiveness_cycles"] == 1

    def test_capa_verify_segregation_of_duties(self, api):
        """PRD section 2.6: "The operator verifying CAPA effectiveness must not
        be the CAPA's `initiator_user_id`." and PRD section 3.7: "Verification
        belongs to a `QualityManager` who is not the CAPA's initiator ... :
        `effective` true closes the CAPA (`closer_user_id` recorded)".

        Design: Corner/state_machines/capa_verify_segregation_of_duties
        """
        stack = create_validated_stack("DEV-CV")
        capa = create_capa("CAPA-CV", stack["dmr"]["id"], source_type="MANUAL",
                           process_change=False, initiator=QE_ALICE)
        walk_capa_to_effectiveness_check(capa["id"], action_summary="plan")

        resp = api.verify_capa_effectiveness(
            capa["id"], {"effective": True}, make_quality_manager_headers(QE_ALICE)
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        current = validate_success(api.get_capa(capa["id"], qm()))
        assert current["status"] == "EFFECTIVENESS_CHECK"

        closed = verify_capa(capa["id"], effective=True, verifier=QM_BOB)
        assert closed["status"] == "CLOSED"
        assert closed["closer_user_id"] == QM_BOB

    def test_capa_source_linkage_mismatch(self, api):
        """PRD section 3.7: "Source linkage must match the type: `COMPLAINT`
        requires `source_complaint_id`, `NCR` requires `source_ncr_id`, and
        `AUDIT` and `MANUAL` take neither; for a complaint source, the
        complaint's lot must belong to the CAPA's DMR — any violation is
        `ERR_SOURCE_MISMATCH`."

        Design: Corner/endpoints/capa_source_linkage_mismatch
        """
        from test_helpers import create_approved_dmr

        dmr = create_approved_dmr(device_code="DEV-SM")
        resp = api.create_capa(
            create_capa_payload(
                dmr["id"], capa_code="CAPA-SM", source_type="COMPLAINT", process_change=False
            ),
            qe(),
        )
        validate_error(resp, ApiErrorId.ERR_SOURCE_MISMATCH)

    def test_capa_close_blocked_by_open_source_ncr(self, api):
        """PRD section 3.7: "`effective` true closes the CAPA (`closer_user_id`
        recorded), but only when a linked source NCR is itself `CLOSED`
        (`ERR_SOURCE_NOT_CLOSED`)".

        Design: Corner/endpoints/capa_close_blocked_by_open_source_ncr
        """
        from test_helpers import create_approved_dmr, create_supplier

        sup = create_supplier("SUP-CN", "CN Co")
        part = create_part(sup["id"], "PN-CN", description="wire")
        ncr = create_ncr(
            ncr_code="NCR-CN", severity="MAJOR", description="insulation nick",
            supplier_part_id=part["id"],
        )
        contain_ncr(ncr["id"])
        disposition_ncr(ncr["id"], "REWORK", "INTERNAL")

        dmr = create_approved_dmr(device_code="DEV-CN")
        capa = create_capa(
            "CAPA-CN", dmr["id"], source_type="NCR", process_change=False,
            source_ncr_id=ncr["id"],
        )
        walk_capa_to_effectiveness_check(capa["id"], action_summary="rework instructions")

        resp = api.verify_capa_effectiveness(capa["id"], {"effective": True}, qm())
        validate_error(resp, ApiErrorId.ERR_SOURCE_NOT_CLOSED)
        current = validate_success(api.get_capa(capa["id"], qm()))
        assert current["status"] == "EFFECTIVENESS_CHECK"

        close_ncr(ncr["id"])
        closed = verify_capa(capa["id"], effective=True, verifier=QM_BOB)
        assert closed["status"] == "CLOSED"


class TestCapaProcessChangeRevalidationChain:
    def _setup(self, api):
        stack, _qs, part = _complaint_stack("DEV-K")
        lot1 = create_lot("LT-K1", stack["dmr"]["id"], stack["protocol"]["id"])
        add_component(lot1["id"], part["id"], quantity_used=10, supplier_lot_number="SL-K1")
        complete_lot(lot1["id"])
        bundle2 = create_released_lot(
            stack, part, lot_number="LT-K2", supplier_lot_number="SL-K2"
        )
        capa = create_capa("CAPA-K", stack["dmr"]["id"], source_type="MANUAL",
                           process_change=True)
        validate_success(api.begin_capa_investigation(capa["id"], qe()))
        validate_success(
            api.plan_capa_actions(capa["id"], {"action_summary": "rework sealing process"}, qe())
        )
        return stack, capa, lot1, bundle2

    def test_implement_flips_validated_protocol_to_revalidation(self, api):
        """PRD section 3.7: "implementing moves to `IMPLEMENTING` — and when
        `process_change` is true, every validation protocol of the CAPA's DMR
        currently `VALIDATED` transitions to `REVALIDATION_REQUIRED` with
        `revalidation_reason` `CAPA_PROCESS_CHANGE`, each holding its in-flight
        lots `REVALIDATION`".

        Design: Difficulty/transitive_cascade/capa_process_change_revalidation_chain
        """
        stack, capa, lot1, _bundle2 = self._setup(api)
        implementing = validate_success(api.implement_capa(capa["id"], qe()))
        assert implementing["status"] == "IMPLEMENTING"

        protocol = validate_success(api.get_protocol(stack["protocol"]["id"], qm()))
        assert protocol["status"] == "REVALIDATION_REQUIRED"
        assert protocol["revalidation_reason"] == "CAPA_PROCESS_CHANGE"

        held = get_lot(lot1["id"])
        assert held["hold_status"] == "ON_HOLD"
        assert held["hold_reason"] == "REVALIDATION"

    def test_revalidation_cascade_leaves_released_lots_untouched(self, api):
        """PRD section 3.3: "every lot produced under the protocol that is still
        `IN_PRODUCTION` or `COMPLETED` is placed `ON_HOLD` with `hold_reason`
        `REVALIDATION`" — a `RELEASED` lot is outside the cascade's scope.

        Design: Difficulty/transitive_cascade/capa_process_change_revalidation_chain
        """
        _stack, capa, _lot1, bundle2 = self._setup(api)
        validate_success(api.implement_capa(capa["id"], qe()))

        released = get_lot(bundle2["lot"]["id"])
        assert released["disposition_status"] == "RELEASED"
        assert released["hold_status"] == "CLEAR"


class TestFieldActions:
    def test_field_action_unconfirmed_complaint_rejected(self, api):
        """PRD section 3.7: "The reason complaint must be confirmed, of severity
        `SERIOUS_INJURY` or `DEATH`, and tied to a lot of the same DMR
        (`ERR_COMPLAINT_NOT_ACTIONABLE`)."

        Design: Corner/endpoints/field_action_unconfirmed_complaint_rejected
        """
        stack, _qs, part = _complaint_stack("DEV-FU")
        bundle = create_released_lot(stack, part, lot_number="LT-FU", supplier_lot_number="SL-FU")
        complaint = create_complaint("CMP-FU", bundle["lot"]["id"], severity="MINOR")
        investigate_complaint(complaint["id"], confirmed=False)

        resp = api.create_field_action(
            create_field_action_payload(
                stack["dmr"]["id"], complaint["id"], action_code="FA-FU",
                action_type="REMOVAL",
                scope_mfg_start="2026-08-01T00:00:00Z",
                scope_mfg_end="2026-08-31T00:00:00Z",
            ),
            ra(),
        )
        validate_error(resp, ApiErrorId.ERR_COMPLAINT_NOT_ACTIONABLE)

    def test_field_action_scope_recalls_only_in_scope_lots(self, api):
        """PRD section 3.7: "Issuing stamps `issued_at`, recalls every `RELEASED`
        lot of the DMR whose `manufactured_at` falls within the closed scope
        interval — on or after `scope_mfg_start` and on or before
        `scope_mfg_end` — with each recalled lot's label-void and rate-recompute
        cascade per §3.6, and records how many lots transitioned as
        `recalled_lot_count`."

        Design: Corner/endpoints/field_action_scope_recalls_only_in_scope_lots
        """
        stack, _qs, part = _complaint_stack("DEV-FS")
        lot_a = create_released_lot(
            stack, part, lot_number="LT-FSA",
            manufactured_at="2026-08-02T00:00:00Z", supplier_lot_number="SL-FSA",
        )
        lot_b = create_released_lot(
            stack, part, lot_number="LT-FSB",
            manufactured_at="2026-08-20T00:00:00Z", supplier_lot_number="SL-FSB",
        )
        complaint = create_complaint(
            "CMP-FS", lot_a["lot"]["id"], severity="SERIOUS_INJURY", description="fracture"
        )
        investigate_complaint(complaint["id"], confirmed=True)
        fa = create_field_action(
            "FA-FS", stack["dmr"]["id"], complaint["id"],
            scope_mfg_start="2026-08-01T00:00:00Z",
            scope_mfg_end="2026-08-10T00:00:00Z",
        )
        issued = validate_success(api.issue_field_action(fa["id"], ra()))
        assert issued["status"] == "ISSUED"
        assert issued["recalled_lot_count"] == 1

        assert get_lot(lot_a["lot"]["id"])["disposition_status"] == "RECALLED"
        label_a = validate_success(api.get_label(lot_a["label"]["id"], ra()))
        assert label_a["status"] == "VOID"
        assert label_a["void_reason"] == "LOT_RECALLED"
        assert get_lot(lot_b["lot"]["id"])["disposition_status"] == "RELEASED"
