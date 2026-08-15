"""Prior authorization workflows: decisions, appeals, coverage windows, clearance gating."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_case,
    create_patient,
    make_reviewer_headers,
    pledge_and_post_deposit,
    request_and_approve_authorization,
    request_authorization,
    set_clock,
    setup_accepted_insured_estimate,
    validate_error,
    validate_success,
)

COUNSELOR = TEST_USERS["counselor_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


def _case_with_requested_auth(mrn="MRN-SM-4", cpt_codes=("27447",)):
    set_clock("2026-08-03T09:00:00Z")
    patient = create_patient(mrn=mrn)
    case = create_case(patient["id"], service_date="2026-08-20")
    auth = request_authorization(case["id"], cpt_codes=cpt_codes,
                                 requester_id="ur-1")
    return patient, case, auth


class TestAppealCycle:
    def test_auth_appeal_cycle_denied_to_approved(self, api):
        """PRD §3.7: "The appeal cycle runs `DENIED` → `APPEALED` → a second
        decision. From `APPEALED`, an approval follows the same rules as a
        first-pass approval — necessity met, validity dates present,
        segregation of duties, `auth_number` minted, `auth_satisfied`
        recomputed — while a denial becomes `DENIED_FINAL`, which is terminal."
        PRD §3.7: "the request starts in `REQUESTED` status with
        `requested_by_user_id` set to the caller's `X-User-ID`."

        Design: Corner/state_machines/auth_appeal_cycle_denied_to_approved
        """
        _patient, _case, auth = _case_with_requested_auth()
        denied = validate_success(api.decide_authorization(
            auth["id"], {"decision": "DENIED", "medical_necessity_met": False},
            make_reviewer_headers("ur-2")), 200)
        assert denied["status"] == "DENIED"
        assert denied["decided_by_user_id"] == "ur-2"

        appealed = validate_success(
            api.appeal_authorization(auth["id"], make_reviewer_headers("ur-1")), 200)
        assert appealed["status"] == "APPEALED"

        approved = validate_success(api.decide_authorization(
            auth["id"],
            {"decision": "APPROVED", "medical_necessity_met": True,
             "valid_from": "2026-08-10", "valid_to": "2026-08-31"},
            make_reviewer_headers("ur-2")), 200)
        assert approved["status"] == "APPROVED"
        assert approved["auth_number"], "auth_number minted on APPROVED"
        assert approved["auth_number"].startswith("AUTH-")
        assert approved["requested_by_user_id"] == "ur-1"
        assert approved["decided_by_user_id"] == "ur-2", "segregation recorded"


class TestMedicalNecessityConsistency:
    def test_decide_denied_with_necessity_true_returns_422(self, api):
        """PRD §3.7: "Consistency between the decision and the
        medical-necessity flag is enforced: an approval requires
        `medical_necessity_met` true, and a denial requires it false; a
        mismatch is `ERR_MEDICAL_NECESSITY_CONFLICT` (HTTP 422)."

        Design: Corner/state_machines/decide_denied_with_necessity_true_returns_422
        """
        _patient, _case, auth = _case_with_requested_auth(mrn="MRN-SM-5")
        res = api.decide_authorization(
            auth["id"], {"decision": "DENIED", "medical_necessity_met": True},
            make_reviewer_headers("ur-2"))
        validate_error(res, ApiErrorId.ERR_MEDICAL_NECESSITY_CONFLICT)
        fetched = validate_success(
            api.list_case_authorizations(_case["id"], SUPERVISOR), 200)
        assert fetched[0]["status"] == "REQUESTED"


class TestClosedWindowContainment:
    """An APPROVED authorization whose closed window contains the service date
    blocks duplicate requests for the same CPT."""

    def _setup_covered_cases(self):
        set_clock("2026-08-03T09:00:00Z")
        patient = create_patient(mrn="MRN-O-1")
        case_a = create_case(patient["id"], service_date="2026-08-20",
                             service_description="Knee replacement")
        request_and_approve_authorization(case_a["id"], cpt_codes=("27447",),
                                          valid_from="2026-08-10",
                                          valid_to="2026-08-31")
        # Case B's service date is exactly the authorization window's end.
        case_b = create_case(patient["id"], service_date="2026-08-31",
                             service_description="Follow-up procedure")
        request_and_approve_authorization(case_b["id"], cpt_codes=("27447",),
                                          valid_from="2026-08-10",
                                          valid_to="2026-08-31")
        return patient, case_a, case_b

    def test_duplicate_covered_cpt_rejected_disjoint_allowed(self, api):
        """PRD §3.7: "if any requested CPT code intersects the codes of an
        existing `APPROVED`, non-expired authorization on the same case whose
        closed validity window contains the case's `service_date`, the request
        is rejected with `ERR_AUTH_ALREADY_COVERED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/authorization_closed_window_containment
        """
        _patient, case_a, _case_b = self._setup_covered_cases()
        res = api.create_authorization(
            case_a["id"], {"cpt_codes": ["27447"], "payer_code": "ACME"},
            make_reviewer_headers("ur-1"))
        validate_error(res, ApiErrorId.ERR_AUTH_ALREADY_COVERED)
        # A disjoint CPT is not covered and can be requested.
        new_auth = validate_success(api.create_authorization(
            case_a["id"], {"cpt_codes": ["29881"], "payer_code": "ACME"},
            make_reviewer_headers("ur-1")), 201)
        assert new_auth["status"] == "REQUESTED"

    def test_service_date_on_valid_to_boundary_is_still_covered(self, api):
        """PRD §3.3: "`auth_satisfied` is true when `auth_required` is false,
        or when an authorization on the case is `APPROVED`, has not since
        expired, and its closed validity window covers the case's
        `service_date` — that is, `valid_from` on or before the service date
        and `valid_to` on or after it."
        PRD §3.7: "if any requested CPT code intersects the codes of an
        existing `APPROVED`, non-expired authorization on the same case whose
        closed validity window contains the case's `service_date`, the request
        is rejected with `ERR_AUTH_ALREADY_COVERED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/authorization_closed_window_containment
        """
        _patient, _case_a, case_b = self._setup_covered_cases()
        res = api.create_authorization(
            case_b["id"], {"cpt_codes": ["27447"], "payer_code": "ACME"},
            make_reviewer_headers("ur-1"))
        validate_error(res, ApiErrorId.ERR_AUTH_ALREADY_COVERED,)


class TestClearRequiresAuthorization:
    def test_clear_without_authorization_rejected(self, api):
        """PRD §3.9: "The compliance gate comes first: if `auth_satisfied` is
        false, the clear is rejected with `ERR_AUTH_NOT_SATISFIED` (HTTP 409)."
        PRD §3.3: "`auth_satisfied` is true when `auth_required` is false, or
        when an authorization on the case is `APPROVED`, has not since expired,
        and its closed validity window covers the case's `service_date`".

        Design: Difficulty/cross_entity_state_dependency/case_clear_requires_approved_authorization
        """
        ctx = setup_accepted_insured_estimate(mrn="MRN-X-2",
                                              requires_auth_prior=True)
        assert ctx["case"]["auth_required"] is True
        pledge_and_post_deposit(ctx["case"]["id"], 125000)
        res = api.clear_case(ctx["case"]["id"], SUPERVISOR)
        validate_error(res, ApiErrorId.ERR_AUTH_NOT_SATISFIED)

    def test_clear_succeeds_after_covering_approval(self, api):
        """PRD §3.7: "From `REQUESTED`, a decision of `APPROVED` mints an
        `auth_number` (a sequential identifier of the form `AUTH-<number>`),
        records `decided_by_user_id`, and recomputes the case's
        `auth_satisfied`".
        PRD §3.9: "When all three gates pass, the case moves `IN_REVIEW` →
        `CLEARED`."

        Design: Difficulty/cross_entity_state_dependency/case_clear_requires_approved_authorization
        """
        ctx = setup_accepted_insured_estimate(mrn="MRN-X-3",
                                              requires_auth_prior=True)
        pledge_and_post_deposit(ctx["case"]["id"], 125000)
        auth = request_and_approve_authorization(
            ctx["case"]["id"], cpt_codes=("27447",),
            valid_from="2026-08-10", valid_to="2026-08-31")
        assert auth["auth_number"], "auth_number is non-null after approval"
        cleared = validate_success(api.clear_case(ctx["case"]["id"], SUPERVISOR), 200)
        assert cleared["status"] == "CLEARED"
        assert cleared["auth_satisfied"] is True
