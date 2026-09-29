"""The boundaries between the offices that share this system.

Each group pairs a refusal with the same call made by the office that owns the
capability, so the refusal is shown to be about the caller and not about the
request.  The two segregation-of-duties rules are exercised the same way: the
identity that acted first is the only one refused the second time.
"""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import one_entry
from test_helpers.test_users import (
    COMPLIANCE,
    COMPLIANCE_COUNTERSIGNER,
    FINANCE_APPROVER,
    FINANCE_PAYER,
    OFFICER,
    REGISTRAR,
    TEST_USERS,
)

DUAL_HAT_OFFICER = TEST_USERS["dual_hat_officer"]
DUAL_HAT_COMPLIANCE = TEST_USERS["dual_hat_compliance"]


class TestScorecardsBelongToTheRecruitmentOffice:
    def test_the_registrar_cannot_score_an_agency_that_the_officer_can(self, client):
        """The identical body is refused for one office and accepted for the other.

        "**`Registrar`** — the registrar office, which records enrollment facts:
        milestone registrations and withdrawals."

        "Onboards agencies, creates programs, drafts contracts, assigns territories
        and rate cards, issues disclosures, decides admissions, and runs performance
        scorecards."

        "If the headers are well formed but the declared role is not permitted for the
        endpoint — or not permitted for the particular action variant being requested
        — the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/registrar_cannot_run_scorecards
        """
        agency = fx.register_agency(client, legal_name="Scorecard Role Agency")
        fx.clear_agency(client, agency["id"])
        payload = F.scorecard_payload("2026-08-01", "2026-08-01")

        refused = client.run_scorecard(agency["id"], payload, REGISTRAR)
        validate_error(refused, E.ERR_UNAUTHORIZED, 403)
        assert fx.read_scorecards(client, agency["id"]) == []

        accepted = validate_success(
            client.run_scorecard(agency["id"], payload, OFFICER), 201
        )
        assert accepted["agency_id"] == agency["id"]
        assert len(fx.read_scorecards(client, agency["id"])) == 1

    def test_only_the_accepted_run_moves_the_agencys_tier(self, client):
        """An empty cohort still writes a scorecard, and that write sets the tier.

        "except that an empty cohort forces `UNRATED` regardless of any score"

        "Writing a scorecard also refreshes the agency's `current_tier`, which is the
        `tier` of that agency's scorecard with the greatest `period_end_date`"

        Design: Corner/rbac/registrar_cannot_run_scorecards
        """
        agency = fx.register_agency(client, legal_name="Scorecard Role Agency")
        fx.clear_agency(client, agency["id"])
        payload = F.scorecard_payload("2026-08-01", "2026-08-01")

        client.run_scorecard(agency["id"], payload, REGISTRAR)
        assert fx.read_agency(client, agency["id"])["current_tier"] == C.TIER_UNRATED

        scorecard = validate_success(
            client.run_scorecard(agency["id"], payload, OFFICER), 201
        )
        assert scorecard["tier"] == C.TIER_UNRATED
        assert scorecard["posture_action_applied"] == C.POSTURE_ACTION_NONE
        assert fx.read_agency(client, agency["id"])["current_tier"] == C.TIER_UNRATED


class TestAgencyOwnerScopeStopsAtItsOwnFiles:
    @pytest.fixture()
    def two_agencies_one_file(self, client):
        """A draft file owned by the first agency, and a second agency's credentials."""
        first = fx.register_agency(
            client, legal_name="Scope Agency One", home_country_code="IN"
        )
        fx.clear_agency(client, first["id"])
        second = fx.register_agency(
            client, legal_name="Scope Agency Two", home_country_code="VN"
        )
        fx.clear_agency(client, second["id"])

        program = fx.create_program(client, annual_tuition_cents=2000000)
        application = fx.create_application(
            client, first["id"], program["id"], student_ref="STU-001"
        )

        return {
            "owner_id": first["id"],
            "outsider_headers": fx.make_agency_owner_headers(second["id"]),
            "owner_headers": fx.make_agency_owner_headers(first["id"]),
            "application_id": application["id"],
        }

    def test_a_stranger_agency_can_neither_submit_nor_read_the_file(
        self, client, two_agencies_one_file
    ):
        """The scope check answers before any submission gate is consulted.

        "the comparison target is the `Agency` reachable from the target resource:
        the agency's own `id` for agency-scoped endpoints, `agency_id` on an
        `AgentContract`, `agency_id` on a `StudentApplication`"

        "A mismatch is rejected with `ERR_AGENCY_SCOPE_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/agency_owner_cannot_touch_another_agencys_application
        """
        env = two_agencies_one_file

        blocked_submit = client.submit_application(
            env["application_id"], env["outsider_headers"]
        )
        body = validate_error(blocked_submit, E.ERR_AGENCY_SCOPE_VIOLATION, 403)
        assert body["error_id"] != E.ERR_UNAUTHORIZED
        assert body["error_id"] != E.ERR_DISCLOSURE_NOT_ACKNOWLEDGED

        blocked_read = client.get_application(
            env["application_id"], env["outsider_headers"]
        )
        validate_error(blocked_read, E.ERR_AGENCY_SCOPE_VIOLATION, 403)

    def test_the_refusals_change_nothing_and_the_true_owner_still_reads_its_file(
        self, client, two_agencies_one_file
    ):
        """Only the agency named on the file may see it.

        "`agency_id` is immutable: it is the recruiting agency of record and drives
        commission attribution forever"

        Design: Corner/rbac/agency_owner_cannot_touch_another_agencys_application
        """
        env = two_agencies_one_file
        client.submit_application(env["application_id"], env["outsider_headers"])

        mine = validate_success(
            client.get_application(env["application_id"], env["owner_headers"])
        )
        assert mine["status"] == C.APPLICATION_DRAFT
        assert mine["agency_id"] == env["owner_id"]


class TestApplicantHasNoReadAccess:
    @pytest.fixture()
    def issued_disclosure(self, client):
        """A student file whose disclosure has been issued but not yet acknowledged."""
        agency = fx.register_agency(client, legal_name="Applicant Read Agency")
        fx.clear_agency(client, agency["id"])
        contract = fx.draft_contract(client, agency["id"], contract_ref="CTR-001")
        fx.append_schedule(client, contract["id"], contract["version"])
        fx.send_contract_for_signature(client, contract["id"])

        program = fx.create_program(client)
        application = fx.create_application(
            client, agency["id"], program["id"], student_ref="STU-001"
        )
        issued = fx.issue_disclosure(client, agency["id"], application["id"])

        return {
            "application_id": application["id"],
            "ack_token": issued["disclosure_ack_token"],
            "applicant_headers": fx.make_applicant_headers("applicant-001"),
        }

    def test_the_acknowledgement_is_the_applicants_single_capability(
        self, client, issued_disclosure
    ):
        """The student may finish the acknowledgement and nothing else.

        "with an `action` of `ACKNOWLEDGE`, the student presents `ack_token`, which
        must equal the application's current `disclosure_ack_token`, and the
        application moves `ISSUED → ACKNOWLEDGED` with `disclosure_acknowledged_at`
        stamped from the logical-clock instant"

        "the prospective student. Holds no read access whatsoever; the
        acknowledgement token issued with the agent-relationship disclosure is this
        role's only capability."

        Design: Corner/rbac/applicant_cannot_read_the_application_it_acknowledged
        """
        env = issued_disclosure

        acknowledged = validate_success(
            client.application_disclosure(
                env["application_id"],
                F.disclosure_acknowledge_payload(env["ack_token"]),
                env["applicant_headers"],
            )
        )
        assert acknowledged["disclosure_state"] == C.DISCLOSURE_ACKNOWLEDGED

        blocked_read = client.get_application(
            env["application_id"], env["applicant_headers"]
        )
        validate_error(blocked_read, E.ERR_UNAUTHORIZED, 403)

    def test_the_applicant_may_not_issue_the_disclosure_it_may_acknowledge(
        self, client, issued_disclosure
    ):
        """The same endpoint splits its permissions by action.

        "issuing an agent-relationship disclosure requires `RecruitmentOfficer` or
        `AgencyOwner`, while acknowledging it requires `Applicant`"

        "A role that is permitted on the endpoint but not on the requested action
        still receives `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/applicant_cannot_read_the_application_it_acknowledged
        """
        env = issued_disclosure

        blocked_issue = client.application_disclosure(
            env["application_id"],
            F.disclosure_issue_payload(),
            env["applicant_headers"],
        )
        validate_error(blocked_issue, E.ERR_UNAUTHORIZED, 403)


class TestMilestonesBelongToTheRegistrar:
    @pytest.fixture()
    def admitted_file(self, client):
        """An admitted file whose next milestone is the deposit."""
        partner = fx.build_active_partner(client, legal_name="Finance Role Agency")
        admitted = fx.build_admitted_application(
            client,
            partner,
            student_ref="STU-001",
            passport_hash="hash-fr-001",
            applicant_user_id="applicant-001",
        )
        return {
            "application_id": admitted["application_id"],
            "version": admitted["version"],
        }

    def test_the_finance_office_cannot_register_an_enrollment_fact(
        self, client, admitted_file
    ):
        """Money is the finance office's business; facts are the registrar's.

        "Milestone registration is exclusive to the `Registrar` and takes a
        `milestone`, the `event_date` on which the fact occurred, and the concurrency
        field `expected_application_version` described in §2.9."

        "**`FinanceOfficer`** — the commission disbursement authority, which
        approves, pays and voids ledger entries."

        Design: Corner/rbac/finance_officer_cannot_register_milestones
        """
        env = admitted_file

        refused = client.register_milestone(
            env["application_id"],
            F.milestone_payload(
                C.MILESTONE_DEPOSIT_PAID, C.DEFAULT_CLOCK_DATE, env["version"]
            ),
            FINANCE_APPROVER,
        )
        validate_error(refused, E.ERR_UNAUTHORIZED, 403)

        assert fx.application_version(client, env["application_id"]) == env["version"]
        assert fx.read_entries(client, application_id=env["application_id"]) == []

    def test_the_refused_call_never_consumed_the_version_it_quoted(
        self, client, admitted_file
    ):
        """The registrar replays the identical body, stale version and all.

        "Role permitted for the endpoint and for the requested action variant —
        `ERR_UNAUTHORIZED`."

        "Optimistic concurrency checks — `ERR_STALE_CONTRACT_VERSION` or
        `ERR_STALE_APPLICATION_VERSION`."

        Design: Corner/rbac/finance_officer_cannot_register_milestones
        """
        env = admitted_file
        payload = F.milestone_payload(
            C.MILESTONE_DEPOSIT_PAID, C.DEFAULT_CLOCK_DATE, env["version"]
        )

        client.register_milestone(env["application_id"], payload, FINANCE_APPROVER)
        accepted = validate_success(
            client.register_milestone(env["application_id"], payload, REGISTRAR)
        )
        assert accepted["status"] == C.APPLICATION_DEPOSIT_PAID

        entries = fx.read_entries(client, application_id=env["application_id"])
        assert len(entries) == 1
        one_entry(entries, C.ENTRY_KIND_ACCRUAL, C.MILESTONE_DEPOSIT_PAID)


class TestTrainingIsWritableByBothOffices:
    @pytest.fixture()
    def certified_agency(self, client):
        """One module recorded by each of the two offices that may record them."""
        agency = fx.register_agency(client, legal_name="Shared Write Agency")
        fx.clear_agency(client, agency["id"])

        program_accuracy = validate_success(
            client.record_certification(
                agency["id"],
                F.certification_payload(
                    module_code=C.MODULE_PROGRAM_ACCURACY,
                    score=92,
                    issued_on=C.DEFAULT_CLOCK_DATE,
                ),
                OFFICER,
            ),
            201,
        )
        prohibited_claims = validate_success(
            client.record_certification(
                agency["id"],
                F.certification_payload(
                    module_code=C.MODULE_PROHIBITED_CLAIMS,
                    score=88,
                    issued_on=C.DEFAULT_CLOCK_DATE,
                ),
                COMPLIANCE,
            ),
            201,
        )
        return {
            "agency_id": agency["id"],
            "program_accuracy": program_accuracy,
            "prohibited_claims": prohibited_claims,
        }

    def test_both_offices_write_a_valid_record_with_a_derived_expiry(
        self, client, certified_agency
    ):
        """The two modules expire on different days from the same issue date.

        "A `RecruitmentOfficer` or `ComplianceOfficer` records a completed module by
        supplying the `module_code`"

        "`expires_on` is `issued_on` advanced by the module's validity period: one
        full year for `PROGRAM_ACCURACY`, half a year — 180 days — for
        `PROHIBITED_CLAIMS`, and one full year for `VISA_INTEGRITY`, where a full
        year is 365 days."

        Design: Corner/rbac/training_certifications_are_writable_by_both_offices
        """
        env = certified_agency

        assert env["program_accuracy"]["status"] == C.CERT_VALID
        assert env["program_accuracy"]["expires_on"] == "2027-08-01"
        assert env["prohibited_claims"]["status"] == C.CERT_VALID
        assert env["prohibited_claims"]["expires_on"] == "2027-01-28"

    def test_the_agency_sees_both_live_records_through_the_status_filter(
        self, client, certified_agency
    ):
        """Whoever wrote the record, the agency reads the same two rows.

        "Certifications can be listed for an agency and filtered by `module_code` and
        by `status`."

        Design: Corner/rbac/training_certifications_are_writable_by_both_offices
        """
        agency_id = certified_agency["agency_id"]

        rows, meta = validate_paginated(
            client.list_certifications(
                agency_id,
                fx.make_agency_owner_headers(agency_id),
                {"status": C.CERT_VALID},
            )
        )
        assert meta["total_count"] == 2
        assert sorted(row["module_code"] for row in rows) == [
            C.MODULE_PROGRAM_ACCURACY,
            C.MODULE_PROHIBITED_CLAIMS,
        ]


class TestContractDrafterCannotCountersign:
    @pytest.fixture()
    def signed_contract_drafted_by_dual_hat(self, client):
        """A contract drafted and sent by one identity, awaiting compliance review."""
        agency = fx.register_agency(client, legal_name="Dual Hat Agency")
        fx.clear_agency(client, agency["id"])

        contract = fx.draft_contract(
            client, agency["id"], headers=DUAL_HAT_OFFICER, contract_ref="CTR-001"
        )
        fx.append_schedule(
            client, contract["id"], contract["version"], headers=DUAL_HAT_OFFICER
        )
        fx.send_contract_for_signature(
            client, contract["id"], headers=DUAL_HAT_OFFICER
        )
        fx.agency_sign_contract(client, agency["id"], contract["id"])

        return {"contract_id": contract["id"], "contract": contract}

    def test_the_drafting_identity_is_recorded_and_then_refused(
        self, client, signed_contract_drafted_by_dual_hat
    ):
        """The same person wearing a compliance hat is still the drafter.

        "`created_by_user_id` set to the drafting officer's `X-User-ID`"

        "A contract's countersignature is barred to its drafter: when a
        `ComplianceOfficer` approves a contract that is awaiting compliance review,
        the acting `X-User-ID` must differ from the contract's `created_by_user_id`."

        Design: Corner/rbac/contract_drafter_cannot_countersign_its_own_contract
        """
        env = signed_contract_drafted_by_dual_hat
        assert env["contract"]["created_by_user_id"] == "dual-hat-1"

        refused = client.contract_lifecycle_action(
            env["contract_id"],
            F.lifecycle_payload(C.LIFECYCLE_COMPLIANCE_APPROVE),
            DUAL_HAT_COMPLIANCE,
        )
        validate_error(refused, E.ERR_SEGREGATION_OF_DUTIES, 403)

        assert (
            fx.read_contract(client, env["contract_id"])["status"]
            == C.CONTRACT_PENDING_COMPLIANCE_REVIEW
        )

    def test_a_second_compliance_identity_completes_the_countersignature(
        self, client, signed_contract_drafted_by_dual_hat
    ):
        """Only the separation of the two identities was missing.

        "`COMPLIANCE_APPROVE` moves `PENDING_COMPLIANCE_REVIEW → ACTIVE` and is the
        countersignature."

        "The approving identity is stamped into `compliance_approved_by_user_id`."

        Design: Corner/rbac/contract_drafter_cannot_countersign_its_own_contract
        """
        env = signed_contract_drafted_by_dual_hat

        activated = validate_success(
            client.contract_lifecycle_action(
                env["contract_id"],
                F.lifecycle_payload(C.LIFECYCLE_COMPLIANCE_APPROVE),
                COMPLIANCE_COUNTERSIGNER,
            )
        )
        assert activated["status"] == C.CONTRACT_ACTIVE
        assert activated["compliance_approved_by_user_id"] == "compliance-2"


class TestEntryApproverCannotPayIt:
    @pytest.fixture()
    def approved_entry(self, client):
        """One deposit accrual, approved by the first finance identity."""
        partner = fx.build_active_partner(client, legal_name="SoD Finance Agency")
        admitted = fx.build_admitted_application(
            client,
            partner,
            student_ref="STU-001",
            passport_hash="hash-sod-001",
            applicant_user_id="applicant-001",
        )
        fx.register_milestone(
            client,
            admitted["application_id"],
            C.MILESTONE_DEPOSIT_PAID,
            C.DEFAULT_CLOCK_DATE,
            admitted["version"],
        )
        entries = fx.read_entries(client, application_id=admitted["application_id"])
        entry = one_entry(entries, C.ENTRY_KIND_ACCRUAL, C.MILESTONE_DEPOSIT_PAID)

        approved = validate_success(
            client.entry_disposition(
                entry["id"],
                F.disposition_payload(C.DISPOSITION_APPROVE),
                FINANCE_APPROVER,
            )
        )
        return {"entry_id": entry["id"], "approved": approved}

    def test_the_approving_identity_cannot_release_the_money_it_approved(
        self, client, approved_entry
    ):
        """The refusal is about who is asking, not about the entry's state.

        "An `action` of `APPROVE` moves `ACCRUED → APPROVED` and stamps
        `approved_by_user_id`."

        "A commission payment is barred to its approver: when a `FinanceOfficer` pays
        an entry, the acting `X-User-ID` must differ from that entry's
        `approved_by_user_id`. Both failures return `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 403)."

        Design: Corner/rbac/entry_approver_cannot_also_pay_the_entry
        """
        env = approved_entry
        assert env["approved"]["state"] == C.ENTRY_APPROVED
        assert env["approved"]["approved_by_user_id"] == "finance-1"

        refused = client.entry_disposition(
            env["entry_id"], F.disposition_payload(C.DISPOSITION_PAY), FINANCE_APPROVER
        )
        body = validate_error(refused, E.ERR_SEGREGATION_OF_DUTIES, 403)
        assert body["error_id"] != E.ERR_INVALID_ENTRY_STATE

        held = validate_success(
            client.get_commission_entry(env["entry_id"], FINANCE_APPROVER)
        )
        assert held["state"] == C.ENTRY_APPROVED
        assert held["paid_by_user_id"] is None

    def test_a_second_finance_identity_pays_the_same_entry(self, client, approved_entry):
        """The payment stamp names the identity that actually released the money.

        "An `action` of `PAY` moves `APPROVED → PAID` and stamps `paid_by_user_id`."

        Design: Corner/rbac/entry_approver_cannot_also_pay_the_entry
        """
        env = approved_entry

        paid = validate_success(
            client.entry_disposition(
                env["entry_id"], F.disposition_payload(C.DISPOSITION_PAY), FINANCE_PAYER
            )
        )
        assert paid["state"] == C.ENTRY_PAID
        assert paid["paid_by_user_id"] == "finance-2"
