"""Underwriting workflow, issuance, and validation-priority claims."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_days,
    assert_policy,
    build_user_headers,
    create_application,
    create_issued_policy,
    create_insured,
    create_template,
    get_success_data,
    set_clock,
    validate_error,
    validate_success,
)

U1 = "underwriter-u1"


def _submitted_application(**cfg):
    """Clock pinned + insured + template + SUBMITTED application."""
    set_clock("2026-05-01T00:00:00Z")
    insured = create_insured(date_of_birth=cfg.pop("date_of_birth",
                                                   "1990-01-01"),
                             tobacco_user=cfg.pop("tobacco_user", False))
    template = create_template(**cfg.pop("template_overrides", {}))
    app = create_application(insured["id"], template["id"], **cfg)
    return insured, template, app


class TestApplicationStateMachine:
    def test_approve_from_submitted_rejected(self, api):
        """PRD §3.2: "The underwriter approves an application in `UNDER_REVIEW` by assigning an
        `underwriting_class` in the request payload".
        PRD §2.12: "**fourth**, whether the target resource's current state permits the operation
        (`ERR_INVALID_STATE`, or `ERR_ALREADY_TERMINAL` where the resource
        sits in a terminal state)".

        Design: Corner/state_machines/approve_submitted_application_returns_invalid_state
        """
        _ip, _tpl, app = _submitted_application()
        resp = api.approve_application(app["id"], "STANDARD_NON_TOBACCO",
                                       build_user_headers(U1, "Underwriter"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_decline_issued_application_rejected(self, api):
        """PRD §3.2: "the underwriter may decline the file outright, moving it from `UNDER_REVIEW`
        to the terminal `DECLINED` state."
        PRD §2.12: "**fourth**, whether the target resource's current state permits the operation
        (`ERR_INVALID_STATE`, or `ERR_ALREADY_TERMINAL` where the resource
        sits in a terminal state)".

        Design: Corner/state_machines/decline_issued_application_returns_invalid_state
        """
        bundle = create_issued_policy()
        resp = api.decline_application(bundle["application"]["id"],
                                       build_user_headers(U1, "Underwriter"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_policy_issued_with_current_and_in_force(self, api):
        """PRD §3.3: "the policy begins with `form_status` of `IN_FORCE` and
        `premium_payment_status` of `CURRENT`".

        Design: Corner/state_machines/policy_initial_state_is_current_in_force
        """
        bundle = create_issued_policy()
        policy = bundle["policy"]
        assert_policy(policy)
        assert policy["premium_payment_status"] == "CURRENT"
        assert policy["form_status"] == "IN_FORCE"


class TestIssueStatePriority:
    def test_issue_from_submitted_surfaces_invalid_state(self, api):
        """PRD §2.12: "**fourth**, whether the target resource's current state permits the operation
        (`ERR_INVALID_STATE`, or `ERR_ALREADY_TERMINAL` where the resource
        sits in a terminal state); **fifth**, segregation of duties on the
        three two-person chains of §2.11".
        PRD §3.3: "Issuance is permitted only when two preconditions hold: the first billing
        cycle's premium has been fully received, meaning the first cycle
        stands in `PAID` or `WAIVED` status, and the product template
        referenced by the application is still valid."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_segregation
        """
        _ip, _tpl, app = _submitted_application()
        # Application still SUBMITTED: the state check fires before any
        # segregation-of-duties consideration in the fixed evaluation order.
        resp = api.issue_application(app["id"],
                                     build_user_headers("issuer-x", "PolicyIssuer"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_second_issue_on_issued_application_rejected(self, api):
        """PRD §3.3: "The application's status advances to ISSUED".
        PRD §2.12: "**fourth**, whether the target resource's current state permits the operation
        (`ERR_INVALID_STATE`, or `ERR_ALREADY_TERMINAL` where the resource
        sits in a terminal state)".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_segregation
        """
        bundle = create_issued_policy()
        resp = api.issue_application(bundle["application"]["id"],
                                     build_user_headers("issuer-2", "PolicyIssuer"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSegregationOfDutiesAtIssue:
    def test_issuer_sharing_approver_id_rejected(self, api):
        """PRD §2.11: "At policy issuance, the issuing `PolicyIssuer`'s `X-User-ID` must differ from
        the approving underwriter's `X-User-ID`."
        PRD §2.11: "A violation on any of these three operations is rejected with
        `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403)."

        Design: Corner/validations/segregation_of_duties_issue_after_own_approval
        """
        _ip, _tpl, app = _submitted_application()
        uw = build_user_headers(U1, "Underwriter")
        get_success_data(api.begin_review(app["id"], uw))
        get_success_data(api.approve_application(app["id"], "STANDARD_NON_TOBACCO", uw))
        # The issuer presents the SAME X-User-ID the approver used.
        resp = api.issue_application(app["id"], build_user_headers(U1, "PolicyIssuer"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)

    def test_distinct_issuer_succeeds(self, api):
        """PRD §2.11: "At policy issuance, the issuing `PolicyIssuer`'s `X-User-ID` must differ from
        the approving underwriter's `X-User-ID`."
        PRD §3.3: "The new policy resource is returned with a `201 Created` status."

        Design: Corner/validations/segregation_of_duties_issue_after_own_approval
        """
        _ip, _tpl, app = _submitted_application()
        uw = build_user_headers(U1, "Underwriter")
        get_success_data(api.begin_review(app["id"], uw))
        get_success_data(api.approve_application(app["id"], "STANDARD_NON_TOBACCO", uw))
        resp = api.issue_application(app["id"],
                                     build_user_headers("issuer-distinct", "PolicyIssuer"))
        policy = validate_success(resp, expected_status=201)
        assert_policy(policy)
        assert policy["form_status"] == "IN_FORCE"


class TestUnderwritingClassConsistency:
    def test_tobacco_class_on_non_tobacco_insured_rejected(self, api):
        """PRD §3.2: "The assigned class must be consistent with the insured's `tobacco_user` flag:
        `PREFERRED_NON_TOBACCO` and `STANDARD_NON_TOBACCO` require a
        non-tobacco insured, while `PREFERRED_TOBACCO` and `STANDARD_TOBACCO`
        require a tobacco user; an inconsistent assignment is rejected with
        `ERR_CLASS_TOBACCO_MISMATCH` (HTTP 422)."

        Design: Corner/validations/class_tobacco_mismatch
        """
        _ip, _tpl, app = _submitted_application(tobacco_user=False)
        uw = build_user_headers(U1, "Underwriter")
        get_success_data(api.begin_review(app["id"], uw))
        resp = api.approve_application(app["id"], "PREFERRED_TOBACCO", uw)
        validate_error(resp, ApiErrorId.ERR_CLASS_TOBACCO_MISMATCH)

    def test_face_amount_below_template_minimum_rejected(self, api):
        """PRD §3.2: "The requested face amount must fall within the template's
        `min_face_amount_cents` and `max_face_amount_cents`; a request outside
        that band, an unrecognized mode, or any other malformed field is
        rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/face_amount_below_template_min
        """
        set_clock("2026-05-01T00:00:00Z")
        insured = create_insured()
        template = create_template(min_face_amount_cents=500_000,
                                   max_face_amount_cents=100_000_000)
        resp = api.create_application(
            {"insured_person_id": insured["id"],
             "product_template_id": template["id"],
             "requested_face_amount_cents": 100,
             "premium_mode": "MONTHLY"},
            build_user_headers("agent-1", "Agent"))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
