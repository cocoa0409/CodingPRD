"""RBAC role denials, segregation of duties, and ownership discipline
(PRD §2.1, §2.9)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_counterparty,
    create_nda_payload,
    create_obligation_payload,
    create_registered_asset,
    create_measure_payload,
    create_employee_record,
    create_active_employee,
    create_grant_request,
    create_asset_payload,
    create_escalated_review_via_notice,
    create_demand_letter_payload,
    make_employee_headers,
    make_counterparty_rep_headers,
    make_ip_counsel_headers,
    make_senior_counsel_headers,
    get_pending_ack_id,
    TEST_USERS,
)

IP = TEST_USERS["ip_counsel_headers"]
HR = TEST_USERS["hr_partner_headers"]
SEC = TEST_USERS["security_officer_headers"]


class TestRoleDenial:
    def test_rbac_employee_cannot_create_asset(self, api):
        """PRD §2.1: "A request whose role is authenticated but not permitted
        for the target endpoint — or for the specific transition requested on
        that endpoint — is rejected with `ERR_UNAUTHORIZED_ROLE`."
        PRD §4: "POST `/api/assets` | Register a trade secret asset |
        IPCounsel".

        Design: Corner/rbac/rbac_employee_cannot_create_asset
        """
        emp = create_employee_record(
            full_name="Role Probe", email="role@x.com", department="ENG",
            role_title="SDE", access_clearance="STANDARD",
            hired_at="2026-05-01T00:00:00Z",
        )
        resp = api.create_asset(
            create_asset_payload(title="Forbidden", description="x",
                                 classification="INTERNAL", owner_department="ENG",
                                 exposure_estimate_cents=10),
            make_employee_headers(emp["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_rbac_hrpartner_cannot_approve_grant(self, api):
        """PRD §2.1: "A request whose role is authenticated but not permitted
        for the target endpoint — or for the specific transition requested on
        that endpoint — is rejected with `ERR_UNAUTHORIZED_ROLE`."
        PRD §4: "POST `/api/grants/{id}/state` | Access grant lifecycle
        transition | SecurityOfficer, IPCounsel".

        Design: Corner/rbac/rbac_hrpartner_cannot_approve_grant
        """
        emp = create_active_employee(
            complete_training=True, full_name="HR Probe", email="hrp@x.com",
            department="ENG", role_title="SDE", access_clearance="STANDARD",
            hired_at="2026-05-01T00:00:00Z",
        )
        asset = create_registered_asset(
            title="RBAC probe", description="x", classification="INTERNAL",
            owner_department="ENG", exposure_estimate_cents=10,
        )
        grant = create_grant_request(emp["id"], asset["id"], justification="j",
                                     expires_at="2026-12-01T00:00:00Z")
        resp = api.transition_grant(grant["id"], {"to_status": "APPROVED"}, HR)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        data = validate_success(api.get_grant(grant["id"], SEC))
        assert data["status"] == "REQUESTED"

    def test_rbac_security_officer_cannot_approve_crown_jewel(self, api):
        """PRD §3.4: "If the asset's classification is `CROWN_JEWEL`, only an
        `IPCounsel` may approve, otherwise `ERR_UNAUTHORIZED_ROLE`."

        Design: Corner/rbac/rbac_security_officer_cannot_approve_crown_jewel
        """
        emp = create_active_employee(
            complete_training=True, full_name="Privileged Pete", email="pete@x.com",
            department="AI", role_title="Scientist", access_clearance="PRIVILEGED",
            hired_at="2026-05-01T00:00:00Z",
        )
        asset = create_registered_asset(
            title="Crown probe", description="x", classification="CROWN_JEWEL",
            owner_department="AI", exposure_estimate_cents=10,
        )
        grant = create_grant_request(emp["id"], asset["id"], justification="j",
                                     expires_at="2026-12-01T00:00:00Z")
        resp = api.transition_grant(
            grant["id"], {"to_status": "APPROVED"},
            TEST_USERS["security_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        data = validate_success(api.get_grant(grant["id"], SEC))
        assert data["status"] == "REQUESTED"

    def test_rbac_counterparty_cannot_waive_obligation(self, api):
        """PRD §3.2: "Counsel may waive a `PENDING` or `OVERDUE` obligation."
        PRD §2.1: "A request whose role is authenticated but not permitted for
        the target endpoint — or for the specific transition requested on that
        endpoint — is rejected with `ERR_UNAUTHORIZED_ROLE`."

        Design: Corner/rbac/rbac_counterparty_cannot_waive_obligation
        """
        cp = create_counterparty(legal_name="Waiver Ltd", counterparty_type="VENDOR")
        nda = validate_success(api.create_nda(
            create_nda_payload(cp["id"], template_version="t22", governing_law="ID",
                               effective_date="2026-01-01T00:00:00Z",
                               expiry_date="2027-01-01T00:00:00Z",
                               survival_months=3, classification_ceiling="INTERNAL"), IP
        ), expected_status=201)
        ob = validate_success(api.create_obligation(
            create_obligation_payload(nda["id"], obligation_type="NON_USE"), IP
        ), expected_status=201)
        resp = api.transition_obligation(
            ob["id"], {"to_status": "WAIVED"}, make_counterparty_rep_headers(cp["id"])
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        data = validate_success(api.get_obligation(ob["id"], IP))
        assert data["status"] == "PENDING"


class TestSegregationOfDuties:
    def test_sod_measure_verifier_must_differ_from_implementer(self, api):
        """PRD §2.9: "A measure's implementer may not verify it."
        PRD §3.1: "Verification — `IMPLEMENTED → VERIFIED` — is counsel's step
        and enforces segregation of duties: the verifier's `X-User-ID` must
        differ from `implemented_by_user_id`, otherwise
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/sod_measure_verifier_must_differ_from_implementer
        """
        asset = validate_success(api.create_asset(
            create_asset_payload(title="SoD probe", description="x",
                                 classification="INTERNAL", owner_department="ENG",
                                 exposure_estimate_cents=10), IP
        ), expected_status=201)
        measure = validate_success(api.create_measure(
            create_measure_payload(asset["id"], measure_type="POLICY", title="p",
                                   evidence_uri="s3://ev/p.pdf"), IP
        ), expected_status=201)
        validate_success(api.transition_measure(
            measure["id"], {"to_status": "IMPLEMENTED"}, make_ip_counsel_headers("counsel_1")
        ))
        resp = api.transition_measure(
            measure["id"], {"to_status": "VERIFIED"}, make_ip_counsel_headers("counsel_1")
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        data = validate_success(api.transition_measure(
            measure["id"], {"to_status": "VERIFIED"}, make_ip_counsel_headers("counsel_2")
        ))
        assert data["status"] == "VERIFIED"

    def test_sod_letter_drafter_cannot_approve(self, api):
        """PRD §2.9: "a demand letter's drafter may not approve it."
        PRD §3.7: "Approval enforces segregation of duties: moving `DRAFTED →
        COUNSEL_APPROVED` is a `SeniorCounsel` step whose `X-User-ID` must
        differ from `drafted_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`,
        and it stamps `approved_by_user_id`."

        Design: Corner/rbac/sod_letter_drafter_cannot_approve
        """
        emp, review = create_escalated_review_via_notice(
            emp_overrides={
                "full_name": "Draft Probe", "email": "draft@x.com",
                "department": "ENG", "role_title": "SDE",
                "access_clearance": "STANDARD", "hired_at": "2026-05-01T00:00:00Z",
            },
            exfil_indicator_count=1,
        )
        asset = validate_success(api.create_asset(
            create_asset_payload(title="Letter probe", description="x",
                                 classification="INTERNAL", owner_department="ENG",
                                 exposure_estimate_cents=2000), IP
        ), expected_status=201)
        letter = validate_success(api.create_demand_letter(
            create_demand_letter_payload(
                review["id"],
                [{"asset_id": asset["id"], "claim_type": "CEASE_AND_DESIST"}],
                response_deadline_days=10,
            ),
            make_ip_counsel_headers("counsel_1"),
        ), expected_status=201)
        # Same user id as drafter, even in the SeniorCounsel role
        resp = api.transition_demand_letter(
            letter["id"], {"to_status": "COUNSEL_APPROVED"},
            make_senior_counsel_headers("counsel_1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        data = validate_success(api.transition_demand_letter(
            letter["id"], {"to_status": "COUNSEL_APPROVED"},
            make_senior_counsel_headers("senior_1"),
        ))
        assert data["status"] == "COUNSEL_APPROVED"


class TestOwnership:
    def test_ownership_employee_cannot_sign_others_ack(self, api):
        """PRD §2.9: "an employee signs only their own acknowledgment."
        PRD §3.3: "Signing belongs to the employee themself — `X-User-ID` must
        equal the acknowledgment's `employee_id`, otherwise
        `ERR_OWNERSHIP_REQUIRED`."

        Design: Corner/rbac/ownership_employee_cannot_sign_others_ack
        """
        emp_a = create_employee_record(
            full_name="Owner A", email="ownera@x.com", department="ENG",
            role_title="SDE", access_clearance="STANDARD",
            hired_at="2026-05-01T00:00:00Z",
        )
        emp_b = create_employee_record(
            full_name="Owner B", email="ownerb@x.com", department="ENG",
            role_title="SDE", access_clearance="STANDARD",
            hired_at="2026-05-01T00:00:00Z",
        )
        ack_b = get_pending_ack_id(emp_b["id"])
        resp = api.sign_acknowledgment(ack_b, make_employee_headers(emp_a["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_REQUIRED)
        data = validate_success(api.get_acknowledgment(ack_b, HR))
        assert data["status"] == "PENDING"

    def test_ownership_counterparty_cannot_fulfill_others_obligation(self, api):
        """PRD §2.9: "a counterparty representative executes NDAs and fulfills
        obligations only for their own organization."
        PRD §3.2: "Fulfillment belongs to the counterparty's representative —
        from `PENDING`, `OVERDUE`, or `ESCALATED` alike — with the same
        ownership rule as execution: `X-User-ID` must equal the parent NDA's
        `counterparty_id`, otherwise `ERR_OWNERSHIP_REQUIRED`."

        Design: Corner/rbac/ownership_counterparty_cannot_fulfill_others_obligation
        """
        cp_a = create_counterparty(legal_name="Cp A", counterparty_type="VENDOR")
        cp_b = create_counterparty(legal_name="Cp B", counterparty_type="VENDOR")
        nda_b = validate_success(api.create_nda(
            create_nda_payload(cp_b["id"], template_version="t23", governing_law="ID",
                               effective_date="2026-01-01T00:00:00Z",
                               expiry_date="2027-01-01T00:00:00Z",
                               survival_months=3, classification_ceiling="INTERNAL"), IP
        ), expected_status=201)
        ob_b = validate_success(api.create_obligation(
            create_obligation_payload(nda_b["id"], obligation_type="NON_USE"), IP
        ), expected_status=201)
        resp = api.transition_obligation(
            ob_b["id"], {"to_status": "FULFILLED"}, make_counterparty_rep_headers(cp_a["id"])
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_REQUIRED)
        data = validate_success(api.get_obligation(ob_b["id"], IP))
        assert data["status"] == "PENDING"
