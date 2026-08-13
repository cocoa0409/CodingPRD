"""Lien-waiver lifecycle (submission, phase-gated acceptance, resubmission) and the
closeout_ready -> FINAL_RELEASE_PENDING cascade."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    decide_waiver,
    get_project,
    get_trade,
    make_gc_inspector_headers,
    make_subcontractor_headers,
    new_project,
    new_trade,
    begin_punch,
    schedule_and_conduct_training,
    setup_closeout_project,
    setup_substantially_complete_project,
    submit_and_approve_all_docs,
    submit_waiver,
    mark_ready,
    validate_error,
    validate_success,
)

PM = TEST_USERS["gc_pm_headers"]
INSP = TEST_USERS["gc_inspector_headers"]


class TestWaiverPhaseGating:

    def test_waiver_unconditional_accept_too_early_returns_error(self):
        """PRD §3.5: "A `CONDITIONAL` waiver may be accepted once the project has reached `SUBSTANTIALLY_COMPLETE`, `CLOSEOUT_IN_PROGRESS`, or `FINAL_RELEASE_PENDING`; an `UNCONDITIONAL` waiver may be accepted only in `CLOSEOUT_IN_PROGRESS` or `FINAL_RELEASE_PENDING`; acceptance attempted in any other phase fails with `ERR_WAIVER_NOT_ACCEPTABLE_STATE`."

        Design: Corner/validations/waiver_unconditional_accept_too_early_returns_error
        """
        ctx = setup_substantially_complete_project(name="Proj")
        trade = ctx["trade"]
        submit_waiver(trade["id"], waiver_type="UNCONDITIONAL", amount_cents=500000)
        resp = api_client.decide_lien_waiver(trade["id"], {"decision": "ACCEPT"}, PM)
        validate_error(resp, ApiErrorId.ERR_WAIVER_NOT_ACCEPTABLE_STATE)
        assert get_trade(trade["id"])["lien_waiver_status"] == "SUBMITTED"


class TestWaiverResubmissionLoop:

    def test_waiver_reject_resubmit_cycle(self):
        """PRD §3.5: "Submission is accepted in any of the five working phases from `PUNCH_ACTIVE` through `FINAL_RELEASE_PENDING` (`ERR_INVALID_STATE` outside them), and after a rejection the same operation resubmits, moving `REJECTED` back to `SUBMITTED` and overwriting the stored waiver fields."
        PRD §3.5: "A `REJECT` decision requires a `rejection_reason` (`ERR_INVALID_REQUEST` without one) and lands the waiver in `REJECTED`, from which resubmission remains possible."

        Design: Corner/validations/waiver_reject_resubmit_cycle
        """
        project = new_project(name="Proj")
        trade = new_trade(project["id"])
        begin_punch(project["id"])
        submit_waiver(trade["id"], waiver_type="CONDITIONAL", amount_cents=100000, file_ref="wvr-1")

        rejected = validate_success(api_client.decide_lien_waiver(
            trade["id"], {"decision": "REJECT", "rejection_reason": "notarized copy required"}, PM,
        ), 200)
        assert rejected["lien_waiver_status"] == "REJECTED"

        resubmitted = validate_success(api_client.submit_lien_waiver(
            trade["id"],
            {"waiver_type": "CONDITIONAL", "amount_cents": 120000, "file_ref": "wvr-2"},
            make_subcontractor_headers(trade["id"]),
        ), 200)
        assert resubmitted["lien_waiver_status"] == "SUBMITTED"
        assert resubmitted["lien_waiver_amount_cents"] == 120000
        assert resubmitted["lien_waiver_file_ref"] == "wvr-2"

    def test_waiver_submit_after_accepted_returns_error(self):
        """PRD §3.5: "Acceptance, though, is absorbing: once `lien_waiver_status` stands at `ACCEPTED`, any further submission is rejected with `ERR_WAIVER_ALREADY_ACCEPTED`."

        Design: Corner/validations/waiver_submit_after_accepted_returns_error
        """
        ctx = setup_closeout_project(name="Proj")
        trade = ctx["trade"]
        submit_waiver(trade["id"], waiver_type="UNCONDITIONAL", amount_cents=500000)
        decide_waiver(trade["id"], "ACCEPT")
        assert get_trade(trade["id"])["lien_waiver_status"] == "ACCEPTED"

        resp = api_client.submit_lien_waiver(
            trade["id"],
            {"waiver_type": "UNCONDITIONAL", "amount_cents": 500000, "file_ref": "wvr-2"},
            make_subcontractor_headers(trade["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WAIVER_ALREADY_ACCEPTED)
        assert get_trade(trade["id"])["lien_waiver_status"] == "ACCEPTED"


class TestVerifyCascade:

    def test_verify_last_item_advances_project_to_final_release_pending(self):
        """PRD §2.8: "When the last unready trade's `closeout_ready` flips to true while the project is in `CLOSEOUT_IN_PROGRESS`, the server advances the project to `FINAL_RELEASE_PENDING` on its own — no explicit client request targets the project — and that automatic transition increments the project's `version` like any other."
        PRD §3.5: "Four operations can touch off that cascade — a document approval, a conducted training session, a waiver acceptance, and a punch-item verification."

        Design: Difficulty/transitive_cascade/verify_last_item_cascades_trade_ready_to_project_advance
        """
        ctx = setup_closeout_project(name="Proj C1", item_severities=("MINOR",))
        project, trade, item = ctx["project"], ctx["trade"], ctx["items"][0]
        submit_and_approve_all_docs(project["id"], trade["id"])
        submit_waiver(trade["id"])
        decide_waiver(trade["id"], "ACCEPT")
        schedule_and_conduct_training(project["id"], trade["id"])

        # One open item still blocks the package: no cascade has fired yet.
        pre = get_project(project["id"])
        assert pre["status"] == "CLOSEOUT_IN_PROGRESS"
        assert get_trade(trade["id"])["closeout_ready"] is False

        mark_ready(item["id"], trade["id"])
        verified = validate_success(api_client.verify_punch_item(
            item["id"], make_gc_inspector_headers("insp-9")
        ), 200)
        assert verified["status"] == "VERIFIED"

        trade_after = get_trade(trade["id"])
        assert trade_after["open_item_count"] == 0
        assert trade_after["closeout_ready"] is True
        assert get_project(project["id"])["status"] == "FINAL_RELEASE_PENDING"

    def test_project_waits_in_closeout_while_item_open(self):
        """PRD §3.5: "A trade's `closeout_ready` flag summarizes the package: it is true exactly when `open_item_count` is zero, `om_doc_approved` and `warranty_doc_approved` and `asbuilt_doc_approved` are all true, `has_conducted_training` is true, and the waiver stands `ACCEPTED` with type `UNCONDITIONAL`."

        Design: Difficulty/transitive_cascade/verify_last_item_cascades_trade_ready_to_project_advance
        """
        ctx = setup_closeout_project(name="Proj", item_severities=("MINOR",))
        project, trade, item = ctx["project"], ctx["trade"], ctx["items"][0]
        submit_and_approve_all_docs(project["id"], trade["id"])
        submit_waiver(trade["id"])
        decide_waiver(trade["id"], "ACCEPT")
        schedule_and_conduct_training(project["id"], trade["id"])

        trade_mid = get_trade(trade["id"])
        # Every other ingredient is satisfied; the single open item holds the flag down.
        assert trade_mid["om_doc_approved"] is True
        assert trade_mid["warranty_doc_approved"] is True
        assert trade_mid["asbuilt_doc_approved"] is True
        assert trade_mid["has_conducted_training"] is True
        assert trade_mid["lien_waiver_status"] == "ACCEPTED"
        assert trade_mid["open_item_count"] == 1
        assert trade_mid["closeout_ready"] is False
        assert get_project(project["id"])["status"] == "CLOSEOUT_IN_PROGRESS"


class TestWaiverCascade:

    def test_waiver_accept_advances_project_to_final_release_pending(self):
        """PRD §2.8: "When the last unready trade's `closeout_ready` flips to true while the project is in `CLOSEOUT_IN_PROGRESS`, the server advances the project to `FINAL_RELEASE_PENDING` on its own — no explicit client request targets the project — and that automatic transition increments the project's `version` like any other."
        PRD §3.5: "An acceptance recomputes `closeout_ready` — note that only an `UNCONDITIONAL` acceptance can complete that flag — and may thereby touch off the project cascade."

        Design: Difficulty/transitive_cascade/waiver_accept_cascades_trade_ready_to_project_advance
        """
        ctx = setup_closeout_project(name="Proj C2")
        project, trade = ctx["project"], ctx["trade"]
        submit_and_approve_all_docs(project["id"], trade["id"])
        schedule_and_conduct_training(project["id"], trade["id"])
        submit_waiver(trade["id"], waiver_type="UNCONDITIONAL", amount_cents=1_000_000)

        assert get_project(project["id"])["status"] == "CLOSEOUT_IN_PROGRESS"
        assert get_trade(trade["id"])["closeout_ready"] is False

        accepted = validate_success(api_client.decide_lien_waiver(
            trade["id"], {"decision": "ACCEPT"}, PM,
        ), 200)
        assert accepted["lien_waiver_status"] == "ACCEPTED"
        assert get_trade(trade["id"])["closeout_ready"] is True
        assert get_project(project["id"])["status"] == "FINAL_RELEASE_PENDING"

    def test_conditional_waiver_acceptance_cannot_complete_closeout(self):
        """PRD §3.5: "An acceptance recomputes `closeout_ready` — note that only an `UNCONDITIONAL` acceptance can complete that flag — and may thereby touch off the project cascade."
        PRD §3.5: "A trade's `closeout_ready` flag summarizes the package: it is true exactly when `open_item_count` is zero, `om_doc_approved` and `warranty_doc_approved` and `asbuilt_doc_approved` are all true, `has_conducted_training` is true, and the waiver stands `ACCEPTED` with type `UNCONDITIONAL`."

        Design: Difficulty/transitive_cascade/waiver_accept_cascades_trade_ready_to_project_advance
        """
        ctx = setup_closeout_project(name="Proj")
        project, trade = ctx["project"], ctx["trade"]
        submit_and_approve_all_docs(project["id"], trade["id"])
        schedule_and_conduct_training(project["id"], trade["id"])
        submit_waiver(trade["id"], waiver_type="CONDITIONAL", amount_cents=1_000_000)

        accepted = validate_success(api_client.decide_lien_waiver(
            trade["id"], {"decision": "ACCEPT"}, PM,
        ), 200)
        assert accepted["lien_waiver_status"] == "ACCEPTED"
        # CONDITIONAL acceptance is lawful in this phase but cannot complete the flag.
        assert get_trade(trade["id"])["closeout_ready"] is False
        assert get_project(project["id"])["status"] == "CLOSEOUT_IN_PROGRESS"
