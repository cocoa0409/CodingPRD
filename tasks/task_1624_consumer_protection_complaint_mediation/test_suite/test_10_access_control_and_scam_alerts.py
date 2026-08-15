"""Access control (authentication, roles, ownership) and scam-alert publication."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    draft_scam_alert,
    file_complaint,
    make_business_headers,
    make_consumer_headers,
    make_mediator_headers,
    notify_business,
    register_business,
    register_consumer,
    register_mediator,
    review_response,
    screen_accept,
    submit_response,
    validate_error,
    validate_success,
)

ANON = TEST_USERS["anonymous_headers"]
OFFICER_1 = TEST_USERS["intake_officer_headers"]
DIRECTOR_1 = TEST_USERS["unit_director_headers"]
DIRECTOR_2 = TEST_USERS["unit_director_2_headers"]
DIRECTOR_3 = TEST_USERS["unit_director_3_headers"]


def _one_complaint(api, suffix=""):
    consumer = register_consumer(full_name="AU", email=f"au{suffix}@x.com", state_code="OR")
    business = register_business(legal_name=f"AuCo{suffix}", home_state="OR",
                                 operates_in_states=["OR"])
    complaint = file_complaint(consumer, business, category="OTHER", description="au")
    return consumer, business, complaint


class TestAuthenticationAndRoles:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role outside this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.12: "1. Authentication: the headers are present and the role is recognized, else `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/c_val_missing_auth_unauthenticated
        """
        _, _, complaint = _one_complaint(api)
        resp = api.screen_complaint(complaint["id"], {"decision": "ACCEPT"}, headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_consumer_cannot_screen_complaint(self, api):
        """PRD §2.1: "When the role is recognized but does not appear among the roles authorized for the target operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "| POST | `/consumer-protection/complaints/{complaintId}/screen` | Screen for jurisdiction: accept or decline | IntakeOfficer |"

        Design: Corner/validations/c_val_role_forbidden_for_consumer_screen
        """
        consumer, _, complaint = _one_complaint(api, "rb")
        # Even the owning consumer is refused: the role itself is not authorized.
        resp = api.screen_complaint(
            complaint["id"], {"decision": "ACCEPT"}, make_consumer_headers(consumer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_consumer_cannot_read_another_consumers_complaint(self, api):
        """PRD §2.1: "When `X-User-Role` is `Consumer`, `X-User-ID` is the `id` of the acting `Consumer` record; ownership checks on any resource that references a consumer compare the resource's `consumer_id` to `X-User-ID`."
        PRD §2.1: "An entity-backed caller acting outside its own scope — a consumer touching another consumer's complaint, a business answering a complaint filed against someone else, a mediator completing a colleague's session — is refused with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/validations/c_val_cross_consumer_access_forbidden
        """
        consumer1, _, complaint = _one_complaint(api, "own")
        consumer2 = register_consumer(full_name="C Two", email="own2@x.com", state_code="OR")
        resp = api.get_complaint(complaint["id"], make_consumer_headers(consumer2["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

    def test_existence_checked_before_state(self, api):
        """PRD §2.12: "Checks on any request run in a fixed order, and a failure at an earlier step masks every later one"
        PRD §2.12: "4. Existence: path identifiers resolve left to right, and foreign keys in the body resolve, else the appropriate not-found error of §2.5."
        PRD §2.5: "the same pattern gives `ERR_COMPLAINT_NOT_FOUND` for `{complaintId}`"

        Design: Corner/validations/c_val_existence_before_state_not_found
        """
        resp = api.screen_complaint(NON_EXISTENT_UUID, {"decision": "ACCEPT"}, OFFICER_1)
        validate_error(resp, ApiErrorId.ERR_COMPLAINT_NOT_FOUND)

    def test_anonymous_cannot_read_complaint_detail(self, api):
        """PRD §2.1: "When the role is recognized but does not appear among the roles authorized for the target operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "| GET | `/consumer-protection/complaints/{complaintId}` | Get a complaint; party callers must own it | Consumer, Business, IntakeOfficer, Mediator, EnforcementAttorney, UnitDirector |"

        Design: Corner/rbac/c_rbac_anonymous_complaint_read_forbidden
        """
        _, _, complaint = _one_complaint(api, "an")
        resp = api.get_complaint(complaint["id"], ANON)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestRoleExclusiveEndpoints:
    def test_business_cannot_review_own_response(self, api):
        """PRD §2.1: "When the role is recognized but does not appear among the roles authorized for the target operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "| POST | `/consumer-protection/business-responses/{responseId}/review` | Review a response: sufficient or insufficient-returned | IntakeOfficer |"

        Design: Corner/rbac/c_rbac_business_cannot_review_response
        """
        consumer, business, complaint = _one_complaint(api, "fx")
        screen_accept(complaint["id"], OFFICER_1)
        notify_business(complaint["id"], OFFICER_1)
        response = submit_response(complaint["id"], business)

        resp = api.review_business_response(
            response["id"], {"verdict": "SUFFICIENT"}, make_business_headers(business["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_mediator_cannot_publish_scam_alert(self, api):
        """PRD §2.1: "When the role is recognized but does not appear among the roles authorized for the target operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "| POST | `/consumer-protection/scam-alerts/{alertId}/publish` | Publish a draft alert (publisher differs from drafter) | UnitDirector |"

        Design: Corner/rbac/c_rbac_mediator_cannot_publish_alert
        """
        mediator = register_mediator(full_name="Med RB", employee_ref="EMP-33")
        alert = draft_scam_alert(
            DIRECTOR_1, title="Fake Charity Wave", scam_category="FAKE_CHARITY", severity="LOW"
        )
        resp = api.publish_scam_alert(alert["id"], make_mediator_headers(mediator["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestScamAlertPublicationOrder:
    def _setup_duplicate_alerts(self, api):
        """alert1 (title T, related business B) drafted by dir-1 and published by
        dir-2; alert2 with the identical (title, related_business_id) drafted by
        dir-2, still DRAFT."""
        business = register_business(legal_name="AlertCo", home_state="OR",
                                     operates_in_states=["OR"])
        alert1 = draft_scam_alert(
            DIRECTOR_1, title="Tech Support Refund Scam", scam_category="TECH_SUPPORT",
            severity="HIGH", related_business_id=business["id"],
        )
        validate_success(api.publish_scam_alert(alert1["id"], DIRECTOR_2))
        alert2 = draft_scam_alert(
            DIRECTOR_2, title="Tech Support Refund Scam", scam_category="TECH_SUPPORT",
            severity="ELEVATED", related_business_id=business["id"],
        )
        return alert2

    def test_drafter_self_publish_rejected_before_duplicate_check(self, api):
        """PRD §2.12: "Checks on any request run in a fixed order, and a failure at an earlier step masks every later one"
        PRD §2.12: "7. Regulatory gates: the filing window at complaint creation, jurisdiction at screening, the segregation-of-duties pairs, the `FLAGGED` bar on mediation offers, and mediator conflict-of-interest screening"
        PRD §3.9: "Publication is a `UnitDirector` act with two guards: the publisher must differ from the drafter (`ERR_SEGREGATION_OF_DUTIES`), and no other alert with the same `title` and `related_business_id` may already stand in `DRAFT` or `PUBLISHED` (`ERR_DUPLICATE_ACTIVE_ALERT`)."

        Design: Difficulty/priority_pair_validation_conflict/d_priority_safety_beats_constraint
        """
        alert2 = self._setup_duplicate_alerts(api)
        # dir-2 drafted alert2 and a duplicate active alert exists: the regulatory
        # gate (step 7) masks the uniqueness/duplicate constraint (step 8).
        resp = api.publish_scam_alert(alert2["id"], DIRECTOR_2)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_duplicate_active_alert_surfaces_for_third_publisher(self, api):
        """PRD §3.9: "no other alert with the same `title` and `related_business_id` may already stand in `DRAFT` or `PUBLISHED` (`ERR_DUPLICATE_ACTIVE_ALERT`)"
        PRD §2.12: "8. Uniqueness and capacity: duplicate-complaint detection, registration uniqueness, the stale-version guard, mediator and room calendar conflicts, the caseload cap, duplicate active alerts, the resubmission cap, and the single-use appeal"

        Design: Difficulty/priority_pair_validation_conflict/d_priority_safety_beats_constraint
        """
        alert2 = self._setup_duplicate_alerts(api)
        # With segregation satisfied (dir-3 did not draft alert2), the constraint surfaces.
        resp = api.publish_scam_alert(alert2["id"], DIRECTOR_3)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_ALERT)

        alert_after = validate_success(api.get_scam_alert(alert2["id"], ANON))
        assert alert_after["alert_status"] == "DRAFT", "both rejections leave state untouched"
