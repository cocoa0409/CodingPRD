"""Adjustment branching, the passed-adjustment schedule, and materiality."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_adjustment,
    complete_fieldwork,
    create_adjustment,
    create_adjustment_payload,
    create_fieldwork_engagement,
    disposition_adjustment,
    get_adjustment,
    get_engagement,
    issue_report,
    pass_adjustment,
    setup_pending_rep_letter,
    setup_signed_engagement,
    sign_rep_letter,
    validate_error,
    validate_paginated,
    validate_success,
)

CONTROLLER = TEST_USERS["controller_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestAdjustmentBranchingFork:

    def test_three_branches_only_pass_increments_total(self):
        """PRD §3.6: "`PASS` carries one further consequence: it records that
        the client refused to book the item, moving it to the
        passed-adjustment schedule and incrementing the engagement's
        `passed_adjustment_total_cents` by the adjustment's `amount_cents`.
        `ACCEPTED`, `REJECTED`, and `PASSED` are all terminal."

        Design: Difficulty/non_linear_state_machine/audit_adjustment_branching_fork
        """
        eng, _loc = create_fieldwork_engagement(client_name="ZetaCorp")
        adj_a = create_adjustment(eng["id"], 10_000, description="AdjA",
                                  direction="DEBIT")
        adj_b = create_adjustment(eng["id"], 20_000, description="AdjB",
                                  direction="DEBIT")
        adj_c = create_adjustment(eng["id"], 30_000, description="AdjC",
                                  direction="CREDIT")
        a = disposition_adjustment(adj_a["id"], "ACCEPT")
        b = disposition_adjustment(adj_b["id"], "PASS",
                                   rationale="Client refuses — booked next year")
        c = disposition_adjustment(adj_c["id"], "REJECT",
                                   rationale="Auditor agreed to withdraw")
        assert a["disposition"] == "ACCEPTED"
        assert b["disposition"] == "PASSED"
        assert c["disposition"] == "REJECTED"
        final = get_engagement(eng["id"])
        assert final["passed_adjustment_total_cents"] == 20_000, (
            f"only PASSED increments the total: expected 20000, got "
            f"{final['passed_adjustment_total_cents']}"
        )

    def test_accept_without_rationale_records_null_rationale(self):
        """PRD §3.6: "`ACCEPT` treats `rationale` as optional — the recorded
        `disposition_rationale` is the payload value when provided and null
        otherwise."
        PRD §3.6: "All three branches record the acting `Controller`'s
        `X-User-ID` as `disposition_by_user_id`."

        Design: Difficulty/non_linear_state_machine/audit_adjustment_branching_fork
        """
        eng, _loc = create_fieldwork_engagement(client_name="ZetaCorp")
        adj = create_adjustment(eng["id"], 10_000, description="AdjA")
        data = disposition_adjustment(adj["id"], "ACCEPT",
                                      controller_user="ctrl-99")
        assert data["disposition"] == "ACCEPTED"
        assert data["disposition_rationale"] is None, (
            f"ACCEPT without rationale records null, got "
            f"{data['disposition_rationale']!r}"
        )
        assert data["disposition_by_user_id"] == "ctrl-99"
        assert get_engagement(eng["id"])["passed_adjustment_total_cents"] == 0


class TestMaterialityStrictLessThan:

    def test_passed_total_one_cent_below_materiality_allows_issue(self):
        """PRD §3.8: "the passed-adjustment total must clear materiality —
        `passed_adjustment_total_cents`, the sum of `amount_cents` over the
        engagement's `PASSED` adjustments, must be strictly less than the
        engagement's `materiality_cents`."
        PRD §3.8: "Issuance recomputes `posture` to `LOCKED` and leaves the
        engagement in its terminal `REPORT_ISSUED` state."

        Design: Difficulty/boundary_precision_check/materiality_threshold_strict_less_than
        """
        eng, _loc = create_fieldwork_engagement(
            client_name="LambdaLtd", materiality_cents=100_000)
        adj = create_adjustment(eng["id"], 99_999, description="Cutoff")
        pass_adjustment(adj["id"], rationale="Refused")
        complete_fieldwork(eng["id"])
        letter = setup_pending_rep_letter(eng["id"], preparer_user="prep_a")
        sign_rep_letter(letter["id"], eng["id"], signer_user="ctrl_b")
        assert get_engagement(eng["id"])["passed_adjustment_total_cents"] \
            == 99_999
        issued = issue_report(eng["id"])
        assert issued["status"] == "REPORT_ISSUED", \
            "99999 < 100000 must clear the materiality gate"
        assert issued["posture"] == "LOCKED"

    def test_passed_total_equal_materiality_rejects_issue(self):
        """PRD §3.8: "Equality does not pass: a total exactly equal to
        materiality is rejected with
        `ERR_PASSED_ADJUSTMENTS_EXCEED_MATERIALITY` just as an overage is."

        Design: Difficulty/boundary_precision_check/materiality_threshold_strict_less_than
        """
        eng, _loc = create_fieldwork_engagement(
            client_name="LambdaLtd", materiality_cents=100_000)
        adj = create_adjustment(eng["id"], 100_000, description="Cutoff")
        pass_adjustment(adj["id"], rationale="Refused")
        complete_fieldwork(eng["id"])
        letter = setup_pending_rep_letter(eng["id"], preparer_user="prep_a")
        sign_rep_letter(letter["id"], eng["id"], signer_user="ctrl_b")
        resp = api_client.issue_report(eng["id"], AUDITOR)
        validate_error(
            resp, ApiErrorId.ERR_PASSED_ADJUSTMENTS_EXCEED_MATERIALITY)
        after = get_engagement(eng["id"])
        assert after["status"] == "FIELDWORK_COMPLETE", \
            "rejected issuance leaves the engagement in FIELDWORK_COMPLETE"


class TestMaterialityEngagementGate:

    def test_issue_report_rejected_when_passed_total_equals_materiality(self):
        """PRD §3.8: "the passed-adjustment total must clear materiality —
        `passed_adjustment_total_cents`, the sum of `amount_cents` over the
        engagement's `PASSED` adjustments, must be strictly less than the
        engagement's `materiality_cents`. Equality does not pass: a total
        exactly equal to materiality is rejected with
        `ERR_PASSED_ADJUSTMENTS_EXCEED_MATERIALITY` just as an overage is."

        Design: Difficulty/dual_variant_calc/passed_adjustment_materiality_per_engagement_vs_per_location
        """
        eng, _loc = create_fieldwork_engagement(
            client_name="BetaCo", materiality_cents=100_000)
        adj1 = create_adjustment(eng["id"], 60_000,
                                 description="Revenue cutoff")
        adj2 = create_adjustment(eng["id"], 40_000, description="Accrual miss")
        pass_adjustment(adj1["id"], rationale="Client refuses")
        pass_adjustment(adj2["id"], rationale="Client refuses")
        assert get_engagement(eng["id"])["passed_adjustment_total_cents"] \
            == 100_000
        complete_fieldwork(eng["id"])
        letter = setup_pending_rep_letter(eng["id"], preparer_user="prep_a")
        sign_rep_letter(letter["id"], eng["id"], signer_user="ctrl_b")
        resp = api_client.issue_report(eng["id"], AUDITOR)
        validate_error(
            resp, ApiErrorId.ERR_PASSED_ADJUSTMENTS_EXCEED_MATERIALITY,
        )
        assert get_engagement(eng["id"])["passed_adjustment_total_cents"] \
            == 100_000

    def test_issue_report_rejected_when_passed_total_exceeds_materiality(self):
        """PRD §3.8: "Equality does not pass: a total exactly equal to
        materiality is rejected with
        `ERR_PASSED_ADJUSTMENTS_EXCEED_MATERIALITY` just as an overage is."

        Design: Difficulty/dual_variant_calc/passed_adjustment_materiality_per_engagement_vs_per_location
        """
        eng, _loc = create_fieldwork_engagement(
            client_name="BetaCo", materiality_cents=100_000)
        adj = create_adjustment(eng["id"], 100_001, description="Overage")
        pass_adjustment(adj["id"], rationale="Client refuses")
        assert get_engagement(eng["id"])["passed_adjustment_total_cents"] \
            == 100_001
        complete_fieldwork(eng["id"])
        letter = setup_pending_rep_letter(eng["id"], preparer_user="prep_a")
        sign_rep_letter(letter["id"], eng["id"], signer_user="ctrl_b")
        resp = api_client.issue_report(eng["id"], AUDITOR)
        validate_error(
            resp, ApiErrorId.ERR_PASSED_ADJUSTMENTS_EXCEED_MATERIALITY)


class TestDispositionPostureLocked:

    def test_disposition_rejected_after_report_issued(self):
        """PRD §3.6: "The adjustment must be in `PROPOSED`
        (`ERR_ADJUSTMENT_NOT_PROPOSED`) and the engagement posture must not be
        `LOCKED` (`ERR_ENGAGEMENT_POSTURE_LOCKED`, per §2.6)."
        PRD §2.6: "While an engagement is `LOCKED`, every state-mutating
        operation other than report issuance and reads is rejected with
        `ERR_ENGAGEMENT_POSTURE_LOCKED`".

        Design: Difficulty/cross_entity_state_dependency/adjustment_disposition_blocked_when_posture_locked
        """
        eng, _loc = create_fieldwork_engagement(
            client_name="XiCo", materiality_cents=100_000)
        adj = create_adjustment(eng["id"], 5_000, description="AdjA")
        complete_fieldwork(eng["id"])
        letter = setup_pending_rep_letter(eng["id"], preparer_user="prep_a")
        sign_rep_letter(letter["id"], eng["id"], signer_user="ctrl_b")
        issue_report(eng["id"])
        assert get_engagement(eng["id"])["posture"] == "LOCKED"
        resp = api_client.disposition_adjustment(
            adj["id"], {"disposition": "ACCEPT"}, CONTROLLER)
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_POSTURE_LOCKED)
        assert get_adjustment(adj["id"])["disposition"] == "PROPOSED", \
            "rejected disposition leaves the adjustment PROPOSED"

    def test_disposition_rejected_after_rep_letter_signed(self):
        """PRD §2.6: "The posture is `LOCKED` whenever the engagement's
        representation letter has reached `SIGNED`".
        PRD §2.6: "While an engagement is `LOCKED`, every state-mutating
        operation other than report issuance and reads is rejected with
        `ERR_ENGAGEMENT_POSTURE_LOCKED`: creating PBC requests, uploading
        evidence, submitting a PBC request for review, recording an auditor
        review decision, raising queries, creating sampling requests,
        scheduling fieldwork visits, proposing adjustments, dispositioning
        adjustments, proposing fee change requests, creating a representation
        letter draft, and submitting a representation letter for signature are
        all forbidden."

        Design: Difficulty/cross_entity_state_dependency/adjustment_disposition_blocked_when_posture_locked
        """
        eng, _loc = create_fieldwork_engagement(
            client_name="XiCo", materiality_cents=100_000)
        adj = create_adjustment(eng["id"], 5_000, description="AdjA")
        complete_fieldwork(eng["id"])
        letter = setup_pending_rep_letter(eng["id"], preparer_user="prep_a")
        sign_rep_letter(letter["id"], eng["id"], signer_user="ctrl_b")
        assert get_engagement(eng["id"])["posture"] == "LOCKED"
        resp = api_client.disposition_adjustment(
            adj["id"], {"disposition": "ACCEPT"}, CONTROLLER)
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_POSTURE_LOCKED)
        assert get_adjustment(adj["id"])["disposition"] == "PROPOSED"


class TestAdjustmentTerminalAndShape:

    def test_disposition_after_accepted_rejected(self):
        """PRD §3.6: "The adjustment must be in `PROPOSED`
        (`ERR_ADJUSTMENT_NOT_PROPOSED`) and the engagement posture must not be
        `LOCKED` (`ERR_ENGAGEMENT_POSTURE_LOCKED`, per §2.6)."
        PRD §3.6: "`ACCEPTED`, `REJECTED`, and `PASSED` are all terminal."

        Design: Corner/state_machines/adjustment_disposition_terminal_lockdown
        """
        eng, _loc = create_fieldwork_engagement(client_name="C")
        adj = create_adjustment(eng["id"], 5_000, description="A")
        disposition_adjustment(adj["id"], "ACCEPT")
        resp = api_client.disposition_adjustment(
            adj["id"],
            {"disposition": "REJECT", "rationale": "Second thoughts"},
            CONTROLLER)
        validate_error(resp, ApiErrorId.ERR_ADJUSTMENT_NOT_PROPOSED)
        assert get_adjustment(adj["id"])["disposition"] == "ACCEPTED", \
            "rejected second disposition leaves the adjustment ACCEPTED"

    def test_zero_amount_rejected(self):
        """PRD §3.6: "an `amount_cents` holding the absolute value in cents
        (which must be greater than zero, else
        `ERR_INVALID_ADJUSTMENT_AMOUNT`)".

        Design: Corner/errors/error_invalid_adjustment_amount
        """
        eng, _loc = create_fieldwork_engagement(client_name="C")
        resp = api_client.create_adjustment(
            create_adjustment_payload(eng["id"], description="zero",
                                      amount_cents=0, direction="DEBIT"),
            AUDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ADJUSTMENT_AMOUNT)


class TestAdjustmentListing:

    def test_adjustments_list_filter_by_disposition(self):
        """PRD §3.6: "The adjustment list — which doubles as the
        passed-adjustment schedule — filters by `engagement_id` and by
        `disposition`."

        Design: Corner/endpoints/adjustments_list_filter_by_disposition
        """
        eng, _loc = create_fieldwork_engagement(
            client_name="C", materiality_cents=100_000)
        adj_a = create_adjustment(eng["id"], 5_000, description="A",
                                  direction="DEBIT")
        adj_b = create_adjustment(eng["id"], 3_000, description="B",
                                  direction="CREDIT")
        disposition_adjustment(adj_a["id"], "ACCEPT")
        pass_adjustment(adj_b["id"], rationale="Client refuses")

        passed, meta_passed = validate_paginated(
            api_client.list_adjustments(
                CONTROLLER,
                params={"engagement_id": eng["id"], "disposition": "PASSED"}))
        assert [a["id"] for a in passed] == [adj_b["id"]], \
            "disposition=PASSED is the passed-adjustment schedule view"
        assert meta_passed["total_count"] == 1

        accepted, meta_acc = validate_paginated(
            api_client.list_adjustments(
                CONTROLLER,
                params={"engagement_id": eng["id"],
                        "disposition": "ACCEPTED"}))
        assert [a["id"] for a in accepted] == [adj_a["id"]]
        assert meta_acc["total_count"] == 1

        all_rows, meta_all = validate_paginated(
            api_client.list_adjustments(
                CONTROLLER, params={"engagement_id": eng["id"]}))
        assert {a["id"] for a in all_rows} == {adj_a["id"], adj_b["id"]}
        for row in all_rows:
            assert_adjustment(row)
