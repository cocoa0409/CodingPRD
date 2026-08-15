"""Purchase application pipeline: submission gates, ownership, segregation of
duties, the UNDER_REVIEW / INFO_REQUESTED review cycle, interview-gated
approval, and validation priority on record-transfer."""
from test_helpers import (
    AGENT,
    OFFICER,
    ApiErrorId,
    assert_purchase_application,
    complete_interview,
    create_purchase_app,
    fresh_coop_version,
    make_shareholder_headers,
    open_resolution,
    pass_resolution,
    setup_application_interview_scheduled,
    setup_application_under_review,
    setup_coop_with_owner,
    submit_purchase_app,
    validate_error,
    validate_success,
)


def _get_app(api, coop_id, app_id):
    return validate_success(api.get_purchase_application(coop_id, app_id, OFFICER))


class TestSubmissionGates:
    def test_submit_already_submitted_returns_invalid_state(self, api):
        """PRD §2.9: "the target resource is in a state from which the
        requested transition exists; failure yields `ERR_INVALID_STATE`
        (HTTP 409)".
        PRD §3.5: "A valid submission moves the application from `DRAFT`
        to `SUBMITTED` and stamps `submitted_at`."

        Design: Corner/state_machines/purchase_submit_from_submitted_returns_invalid_state
        """
        env = setup_coop_with_owner()
        app = create_purchase_app(env["coop"]["id"], env["unit"]["id"],
                                  env["owner"]["id"])
        submitted = submit_purchase_app(env["coop"]["id"], app["id"],
                                        env["owner"]["id"])
        assert submitted["application_status"] == "SUBMITTED"
        resp = api.submit_purchase_application(
            env["coop"]["id"], app["id"], make_shareholder_headers(env["owner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_withdrawn_application_admits_no_further_transitions(self, api):
        """PRD §3.5: "Once an application has reached a terminal state
        (`REJECTED`, `WITHDRAWN`, or `TRANSFERRED`), further transitions are
        rejected with `ERR_ALREADY_TERMINAL`."
        PRD §3.5: "The seller may withdraw the application from any
        non-terminal status — `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`,
        `INFO_REQUESTED`, `INTERVIEW_SCHEDULED`, or `APPROVED` — moving it to
        `WITHDRAWN`".

        Design: Corner/state_machines/purchase_application_terminal_state_lockdown
        """
        env = setup_coop_with_owner()
        app = create_purchase_app(env["coop"]["id"], env["unit"]["id"],
                                  env["owner"]["id"])
        withdrawn = validate_success(api.withdraw_purchase_application(
            env["coop"]["id"], app["id"],
            make_shareholder_headers(env["owner"]["id"])), 200)
        assert withdrawn["application_status"] == "WITHDRAWN"
        resp = api.certify_purchase_application(env["coop"]["id"], app["id"], AGENT)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL, expected_status=409)

    def test_financing_above_house_cap_rejected(self, api):
        """PRD §3.5: "the buyer's financing may not exceed the house cap
        of 8000 basis points — eighty percent of the price — with breaches
        rejected as `ERR_BUSINESS_CONSTRAINT`".

        Design: Corner/validations/purchase_financing_cap_violation
        """
        env = setup_coop_with_owner()
        app = create_purchase_app(env["coop"]["id"], env["unit"]["id"],
                                  env["owner"]["id"], financing_percent_bps=9000)
        resp = api.submit_purchase_application(
            env["coop"]["id"], app["id"], make_shareholder_headers(env["owner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_BUSINESS_CONSTRAINT, expected_status=422)

    def test_submit_by_non_seller_rejected_as_not_owner(self, api):
        """PRD §3.5: "Submitting the application is the seller's own act
        — the caller's `X-User-ID` must equal the `seller_shareholder_id`, else
        `ERR_NOT_RESOURCE_OWNER`".

        Design: Corner/validations/ownership_check_shareholder_cannot_submit_for_another
        """
        env = setup_coop_with_owner()
        other = validate_success(api.create_shareholder(
            env["coop"]["id"], {"full_name": "Other Owner",
                                "email": "other@example.com"}, OFFICER), 201)
        app = create_purchase_app(env["coop"]["id"], env["unit"]["id"],
                                  env["owner"]["id"])
        resp = api.submit_purchase_application(
            env["coop"]["id"], app["id"], make_shareholder_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)

    def test_panel_may_not_include_certifying_agent(self, api):
        """PRD §3.5: "The panel must contain at least two distinct
        `BoardMember` user ids — too few is rejected with
        `ERR_BUSINESS_CONSTRAINT` — and segregation of duties forbids any panel
        entry from equal­ing the `X-User-ID` of the managing agent who certified
        the package, a violation rejected with `ERR_SEPARATION_OF_DUTIES`
        (HTTP 422)."

        Design: Corner/validations/interview_segregation_of_duties
        """
        env = setup_application_under_review()
        resp = api.schedule_interview(
            env["coop"]["id"], env["app"]["id"],
            {"scheduled_at": "2026-08-15T14:00:00Z",
             "panel_member_user_ids": ["ma-certifier-1", "bm-panel-2"]},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_SEPARATION_OF_DUTIES, expected_status=422)


class TestReviewCycle:
    def test_info_request_cycle_returns_to_under_review(self, api):
        """PRD §3.5: "A `BoardOfficer` may bounce the package back by
        requesting more information — optionally annotating the request with
        `info_request_notes` — moving the application from `UNDER_REVIEW` to
        `INFO_REQUESTED`; the seller answers by submitting the requested
        material, optionally attaching `info_payload`, which returns the
        application to `UNDER_REVIEW`."

        Design: Difficulty/non_linear_state_machine/purchase_application_review_cycle
        """
        env = setup_application_under_review()
        coop_id, app_id = env["coop"]["id"], env["app"]["id"]

        requested = validate_success(api.request_info(
            coop_id, app_id, {"info_request_notes": "Need tax returns"}, OFFICER), 200)
        assert requested["application_status"] == "INFO_REQUESTED"

        answered = validate_success(api.submit_info(
            coop_id, app_id, {"info_payload": "Tax returns attached"},
            make_shareholder_headers(env["owner"]["id"])), 200)
        assert answered["application_status"] == "UNDER_REVIEW"
        assert_purchase_application(answered)

    def test_info_request_cycle_may_repeat_any_number_of_times(self, api):
        """PRD §3.5: "This request-and-answer cycle between
        `UNDER_REVIEW` and `INFO_REQUESTED` may repeat any number of times."

        Design: Difficulty/non_linear_state_machine/purchase_application_review_cycle
        """
        env = setup_application_under_review()
        coop_id, app_id = env["coop"]["id"], env["app"]["id"]
        seller_headers = make_shareholder_headers(env["owner"]["id"])

        for notes, payload in (("Need tax returns", "Tax returns attached"),
                               ("Need reference letters", "References attached")):
            requested = validate_success(
                api.request_info(coop_id, app_id, {"info_request_notes": notes},
                                 OFFICER), 200)
            assert requested["application_status"] == "INFO_REQUESTED"
            answered = validate_success(
                api.submit_info(coop_id, app_id, {"info_payload": payload},
                                seller_headers), 200)
            assert answered["application_status"] == "UNDER_REVIEW"

        final = _get_app(api, coop_id, app_id)
        assert final["application_status"] == "UNDER_REVIEW", \
            "two full cycles leave the application back in UNDER_REVIEW"


class TestInterviewGatedApproval:
    def test_unfavorable_interview_blocks_approval_despite_passed_resolution(self, api):
        """PRD §3.6: "Approval requires a resolution of kind
        `APPROVE_PURCHASE` naming the application to reach `PASSED`, and even a
        passed resolution does not approve an unqualified buyer: the
        application's interview must be `COMPLETED` with a `FAVORABLE` outcome".
        PRD §3.5: "Completion stamps `completed_at`, moves the interview
        from `SCHEDULED` to `COMPLETED`, and, when the outcome is `UNFAVORABLE`,
        sends the application back to `UNDER_REVIEW` for re-review."

        Design: Difficulty/cross_entity_state_dependency/purchase_approval_requires_interview_favorable
        """
        env = setup_application_interview_scheduled()
        coop_id, app_id = env["coop"]["id"], env["app"]["id"]

        interview = complete_interview(coop_id, env["interview"]["id"],
                                       outcome="UNFAVORABLE")
        assert interview["interview_status"] == "COMPLETED"
        assert interview["interview_outcome"] == "UNFAVORABLE"
        assert _get_app(api, coop_id, app_id)["application_status"] == "UNDER_REVIEW"

        resolution = open_resolution(coop_id, "APPROVE_PURCHASE",
                                     "PurchaseApplication", app_id)
        resolution = pass_resolution(coop_id, resolution["id"])
        assert resolution["resolution_status"] == "PASSED"
        final = _get_app(api, coop_id, app_id)
        assert final["application_status"] == "UNDER_REVIEW", (
            "no FAVORABLE completed interview -> approval cannot fire from "
            f"UNDER_REVIEW, got {final['application_status']}")

    def test_favorable_interview_and_passed_resolution_approves(self, api):
        """PRD §3.6: "Approval moves the application from
        `INTERVIEW_SCHEDULED` to `APPROVED` and stamps `deciding_resolution_id`".
        PRD §3.6: "First, the declared `debt_to_income_bps` may not
        exceed 2800 basis points — twenty-eight percent. Second, the declared
        `post_closing_liquidity_cents` must cover twelve months of carrying
        costs".

        Design: Difficulty/cross_entity_state_dependency/purchase_approval_requires_interview_favorable
        """
        env = setup_application_interview_scheduled()
        coop_id, app_id = env["coop"]["id"], env["app"]["id"]

        interview = complete_interview(coop_id, env["interview"]["id"],
                                       outcome="FAVORABLE")
        assert interview["interview_outcome"] == "FAVORABLE"

        resolution = open_resolution(coop_id, "APPROVE_PURCHASE",
                                     "PurchaseApplication", app_id)
        resolution = pass_resolution(coop_id, resolution["id"])
        assert resolution["resolution_status"] == "PASSED"

        final = _get_app(api, coop_id, app_id)
        assert final["application_status"] == "APPROVED"
        assert final["deciding_resolution_id"] == resolution["id"]


class TestRecordTransferValidationPriority:
    def test_record_transfer_on_draft_reports_state_not_fiscal(self, api):
        """PRD §2.9: "When several checks could fail on the same request,
        the server reports only the earliest failure, evaluating checks in this
        fixed priority order" — state-transition legality (priority 5, yielding
        `ERR_INVALID_STATE` (HTTP 409)) precedes fiscal thresholds (priority 10,
        yielding `ERR_FISCAL_THRESHOLD_VIOLATION` (HTTP 422)).
        PRD §3.6: "A valid recording moves the application from
        `APPROVED` to `TRANSFERRED`".

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_vs_fiscal_threshold_on_record_transfer
        """
        env = setup_coop_with_owner()
        # DRAFT application (never submitted) whose buyer also breaches the
        # 2800 bps debt-to-income cap: state and fiscal both fail.
        app = create_purchase_app(env["coop"]["id"], env["unit"]["id"],
                                  env["owner"]["id"], debt_to_income_bps=5000)
        version = fresh_coop_version(env["coop"]["id"])
        resp = api.record_transfer(env["coop"]["id"], app["id"],
                                   {"expected_cooperative_version": version}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_record_transfer_requires_approved_state(self, api):
        """PRD §3.6: "A valid recording moves the application from
        `APPROVED` to `TRANSFERRED`, stamps `transferred_at`, computes and
        stores `flip_tax_cents`, and increments the cooperative's `version`."
        PRD §2.9: "the target resource is in a state from which the
        requested transition exists; failure yields `ERR_INVALID_STATE`
        (HTTP 409)".

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_vs_fiscal_threshold_on_record_transfer
        """
        env = setup_application_under_review()
        coop_id, app_id = env["coop"]["id"], env["app"]["id"]
        assert _get_app(api, coop_id, app_id)["application_status"] == "UNDER_REVIEW"
        version = fresh_coop_version(coop_id)
        resp = api.record_transfer(coop_id, app_id,
                                   {"expected_cooperative_version": version}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert _get_app(api, coop_id, app_id)["application_status"] == "UNDER_REVIEW"
