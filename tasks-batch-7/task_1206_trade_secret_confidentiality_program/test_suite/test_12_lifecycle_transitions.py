"""Lifecycle transitions: NDA happy path, terminal lockdowns, retire cascade,
exit-interview loops and gates, review kickback cycle, letter issue gate
(PRD §3.2, §3.1, §3.6, §3.7, §3.4, §3.5)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    assert_same_instant,
    ApiErrorId,
    create_counterparty,
    create_active_nda,
    create_nda_payload,
    create_obligation_payload,
    create_registered_asset,
    add_verified_measure,
    create_measure_payload,
    create_employee_record,
    create_active_employee,
    create_grant_request,
    create_exit_interview_payload,
    create_draft_disclosure,
    create_escalated_review_via_notice,
    create_asset_payload,
    create_demand_letter_payload,
    make_employee_headers,
    make_counterparty_rep_headers,
    make_ip_counsel_headers,
    TEST_USERS,
)

IP = TEST_USERS["ip_counsel_headers"]
HR = TEST_USERS["hr_partner_headers"]
SEC = TEST_USERS["security_officer_headers"]


class TestNdaFullHappyPath:
    def test_nda_full_happy_path(self, api):
        """PRD §3.2: "The NDA lifecycle runs `DRAFT → SENT → EXECUTED →
        ACTIVE`."
        PRD §3.2: "The computed `confidentiality_end` — `expiry_date` plus
        `survival_months` calendar months — records how long confidentiality
        outlives the agreement."

        Design: Corner/state_machines/nda_full_happy_path
        """
        cp = create_counterparty(legal_name="Nu Freight", counterparty_type="VENDOR")
        resp = api.create_nda(
            create_nda_payload(
                cp["id"], template_version="t13", governing_law="AZ",
                effective_date="2026-01-01T00:00:00Z", expiry_date="2026-12-31T00:00:00Z",
                survival_months=6, classification_ceiling="INTERNAL",
            ), IP
        )
        nda = validate_success(resp, expected_status=201)
        assert nda["status"] == "DRAFT"
        validate_success(api.transition_nda(nda["id"], {"to_status": "SENT"}, IP))
        validate_success(api.transition_nda(
            nda["id"], {"to_status": "EXECUTED"}, make_counterparty_rep_headers(cp["id"])
        ))
        data = validate_success(api.transition_nda(nda["id"], {"to_status": "ACTIVE"}, IP))
        assert data["status"] == "ACTIVE"
        assert_same_instant(
            data["confidentiality_end"], "2027-06-30T00:00:00Z",
            label=f"2026-12-31 + 6 months = 2027-06-30, got {data['confidentiality_end']}")


class TestObligationFulfillTwiceRejected:
    def test_obligation_fulfill_twice_rejected(self, api):
        """PRD §3.2: "Counsel may waive a `PENDING` or `OVERDUE` obligation,
        which recomputes the NDA's counters; `FULFILLED` and `WAIVED` are
        terminal."
        PRD §2.12: "Sixth (6) state-machine preconditions: the transition must
        be defined from the current state and entity-level state gates must
        hold, else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/obligation_fulfill_twice_rejected
        """
        cp = create_counterparty(legal_name="Xi Print", counterparty_type="VENDOR")
        resp = api.create_nda(
            create_nda_payload(
                cp["id"], template_version="t14", governing_law="AZ",
                effective_date="2026-01-01T00:00:00Z", expiry_date="2027-01-01T00:00:00Z",
                survival_months=3, classification_ceiling="INTERNAL",
            ), IP
        )
        nda = validate_success(resp, expected_status=201)
        resp = api.create_obligation(
            create_obligation_payload(nda["id"], obligation_type="NON_USE"), IP
        )
        ob = validate_success(resp, expected_status=201)
        validate_success(api.transition_obligation(
            ob["id"], {"to_status": "FULFILLED"}, make_counterparty_rep_headers(cp["id"])
        ))
        resp = api.transition_obligation(
            ob["id"], {"to_status": "FULFILLED"}, make_counterparty_rep_headers(cp["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        nda_now = validate_success(api.get_nda(nda["id"], IP))
        assert nda_now["obligations_fulfilled_count"] == 1, "no double count"


class TestAssetRetirement:
    def test_asset_retired_terminal_lockdown(self, api):
        """PRD §3.1: "`RETIRED` is terminal."
        PRD §2.12: "Sixth (6) state-machine preconditions: the transition must
        be defined from the current state and entity-level state gates must
        hold, else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/asset_retired_terminal_lockdown
        """
        asset = create_registered_asset(
            title="Old formula", description="x", classification="INTERNAL",
            owner_department="RND", exposure_estimate_cents=10,
        )
        validate_success(api.transition_asset(asset["id"], {"to_status": "RETIRED"}, IP))
        resp = api.transition_asset(asset["id"], {"to_status": "SUSPENDED"}, IP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        data = validate_success(api.get_asset(asset["id"], IP))
        assert data["status"] == "RETIRED"

    def test_asset_retire_cascades_measures_abandoned(self, api):
        """PRD §3.1: "Retiring cascades: every measure of the asset in
        `PLANNED`, `IMPLEMENTED`, `VERIFIED`, or `LAPSED` moves to `ABANDONED`
        in `created_at` ascending order, and both score variants are recomputed
        to zero along with the posture."

        Design: Corner/state_machines/asset_retire_cascades_measures_abandoned
        """
        asset = create_registered_asset(
            title="Legacy coater", description="x", classification="CONFIDENTIAL",
            owner_department="FAB", exposure_estimate_cents=60000,
        )
        m1 = add_verified_measure(asset["id"], "TECHNICAL", title="Interlock",
                                  evidence_uri="s3://ev/i.pdf")
        resp = api.create_measure(
            create_measure_payload(asset["id"], measure_type="POLICY",
                                   title="Draft policy", evidence_uri=""), SEC
        )
        m2 = validate_success(resp, expected_status=201)
        validate_success(api.transition_asset(asset["id"], {"to_status": "RETIRED"}, IP))
        assert validate_success(api.get_measure(m1["id"], IP))["status"] == "ABANDONED"
        assert validate_success(api.get_measure(m2["id"], IP))["status"] == "ABANDONED"
        asset_now = validate_success(api.get_asset(asset["id"], IP))
        assert asset_now["score_operational"] == 0
        assert asset_now["protection_posture"] == "DEFICIENT"


def _setup_notice_employee(api, full_name, email):
    """ACTIVE employee moved to NOTICE (voluntary). Returns employee dict."""
    emp = create_active_employee(
        complete_training=False, full_name=full_name, email=email,
        department="SALES", role_title="AE", access_clearance="STANDARD",
        hired_at="2026-05-01T00:00:00Z",
    )
    resp = api.transition_employee(
        emp["id"], {"to_status": "NOTICE", "departure_type": "VOLUNTARY"}, HR
    )
    return validate_success(resp)


class TestExitInterviewNoShowLoop:
    def test_exit_interview_no_show_loop_then_escalate(self, api):
        """PRD §3.6: "A no-show — `SCHEDULED → NO_SHOW` — increments
        `no_show_count`, which starts at zero, by one, and from `NO_SHOW` the
        interview can be rescheduled back to `SCHEDULED` with a fresh window
        (subject to the same overlap check against the employee's other
        `SCHEDULED` or `CONDUCTED` interviews), or escalated once
        `no_show_count` reaches at least two, otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/exit_interview_no_show_loop_then_escalate
        """
        emp = _setup_notice_employee(api, "Wes NoShow", "wes@x.com")
        resp = api.create_exit_interview(
            create_exit_interview_payload(
                emp["id"],
                scheduled_start="2026-05-10T10:00:00Z",
                scheduled_end="2026-05-10T11:00:00Z",
            ), HR
        )
        ei = validate_success(resp, expected_status=201)
        validate_success(api.transition_exit_interview(ei["id"], {"to_status": "NO_SHOW"}, HR))
        validate_success(api.transition_exit_interview(
            ei["id"],
            {"to_status": "SCHEDULED", "scheduled_start": "2026-05-12T10:00:00Z",
             "scheduled_end": "2026-05-12T11:00:00Z"},
            HR,
        ))
        validate_success(api.transition_exit_interview(ei["id"], {"to_status": "NO_SHOW"}, HR))
        data = validate_success(api.transition_exit_interview(ei["id"], {"to_status": "ESCALATED"}, HR))
        assert data["no_show_count"] == 2
        assert data["status"] == "ESCALATED"

    def test_interview_escalate_before_two_no_shows_rejected(self, api):
        """PRD §3.6: "or escalated once `no_show_count` reaches at least two,
        otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/interview_escalate_before_two_no_shows_rejected
        """
        emp = create_active_employee(
            complete_training=False, full_name="Xena Late", email="xena@x.com",
            department="SALES", role_title="AE", access_clearance="STANDARD",
            hired_at="2026-05-01T00:00:00Z",
        )
        resp = api.create_exit_interview(
            create_exit_interview_payload(emp["id"]), HR
        )
        ei = validate_success(resp, expected_status=201)
        validate_success(api.transition_exit_interview(ei["id"], {"to_status": "NO_SHOW"}, HR))
        resp = api.transition_exit_interview(ei["id"], {"to_status": "ESCALATED"}, HR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        data = validate_success(api.get_exit_interview(ei["id"], HR))
        assert data["status"] == "NO_SHOW"

    def test_interview_certify_requires_both_flags(self, api):
        """PRD §3.6: "Certification — `CONDUCTED → CERTIFIED` — requires both
        flags true, otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/state_machines/interview_certify_requires_both_flags
        """
        emp = create_active_employee(
            complete_training=False, full_name="Yara Exit", email="yara@x.com",
            department="FIN", role_title="Analyst", access_clearance="STANDARD",
            hired_at="2026-05-01T00:00:00Z",
        )
        resp = api.create_exit_interview(
            create_exit_interview_payload(emp["id"]), HR
        )
        ei = validate_success(resp, expected_status=201)
        validate_success(api.transition_exit_interview(ei["id"], {"to_status": "CONDUCTED"}, HR))
        validate_success(api.patch_exit_interview(
            ei["id"], {"return_certification": True}, HR
        ))
        resp = api.transition_exit_interview(ei["id"], {"to_status": "CERTIFIED"}, HR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        data = validate_success(api.get_exit_interview(ei["id"], HR))
        assert data["status"] == "CONDUCTED"

    def test_interview_adjacent_windows_allowed_half_open(self, api):
        """PRD §3.6: "Windows are half-open intervals for overlap purposes: a
        new interview whose window overlaps another `SCHEDULED` or `CONDUCTED`
        interview of the same employee is rejected with `ERR_INTERVIEW_OVERLAP`,
        while one starting exactly when another ends is permitted."

        Design: Corner/state_machines/interview_adjacent_windows_allowed_half_open
        """
        emp = create_active_employee(
            complete_training=False, full_name="Zack Double", email="zack@x.com",
            department="ENG", role_title="SDE", access_clearance="STANDARD",
            hired_at="2026-05-01T00:00:00Z",
        )
        validate_success(api.create_exit_interview(
            create_exit_interview_payload(
                emp["id"],
                scheduled_start="2026-05-10T10:00:00Z",
                scheduled_end="2026-05-10T11:00:00Z",
            ), HR
        ), expected_status=201)
        resp = api.create_exit_interview(
            create_exit_interview_payload(
                emp["id"],
                scheduled_start="2026-05-10T10:30:00Z",
                scheduled_end="2026-05-10T11:30:00Z",
            ), HR
        )
        validate_error(resp, ApiErrorId.ERR_INTERVIEW_OVERLAP)
        resp = api.create_exit_interview(
            create_exit_interview_payload(
                emp["id"],
                scheduled_start="2026-05-10T11:00:00Z",
                scheduled_end="2026-05-10T12:00:00Z",
            ), HR
        )
        validate_success(resp, expected_status=201)


class TestForensicReviewKickbackCycle:
    def test_review_kickback_cycle_and_escalation_gate(self, api):
        """PRD §3.6: "Counsel then takes over: `FINDINGS_DRAFTED →
        COUNSEL_REVIEW` stamps `reviewed_by_counsel_id` with the counsel's
        `X-User-ID`, and counsel may kick the review back to
        `FINDINGS_DRAFTED` — the `FINDINGS_DRAFTED ↔ COUNSEL_REVIEW` loop — or
        close it."
        PRD §3.6: "escalating (`COUNSEL_REVIEW → ESCALATED`) requires at least
        one exfiltration indicator on record, otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/review_kickback_cycle_and_escalation_gate
        """
        emp = create_active_employee(
            complete_training=False, full_name="Amy Watch", email="amy@x.com",
            department="ENG", role_title="SDE", access_clearance="STANDARD",
            hired_at="2026-05-01T00:00:00Z",
        )
        resp = api.create_forensic_review(
            {"employee_id": emp["id"], "trigger_reason": "POLICY"}, IP
        )
        review = validate_success(resp, expected_status=201)
        validate_success(api.transition_forensic_review(review["id"], {"to_status": "IMAGING"}, SEC))
        validate_success(api.create_evidence_item(
            {"review_id": review["id"], "source": "DEVICE_IMAGE",
             "sha256": "e" * 64, "byte_size": 4096}, SEC
        ), expected_status=201)
        validate_success(api.transition_forensic_review(
            review["id"], {"to_status": "FINDINGS_DRAFTED"}, SEC
        ))
        validate_success(api.transition_forensic_review(
            review["id"], {"to_status": "COUNSEL_REVIEW"}, IP
        ))
        # Escalation with zero indicators is rejected
        resp = api.transition_forensic_review(review["id"], {"to_status": "ESCALATED"}, IP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        # Kickback cycle
        validate_success(api.transition_forensic_review(
            review["id"], {"to_status": "FINDINGS_DRAFTED"}, IP
        ))
        validate_success(api.patch_forensic_review(
            review["id"], {"exfil_indicator_count": 3}, SEC
        ))
        validate_success(api.transition_forensic_review(
            review["id"], {"to_status": "COUNSEL_REVIEW"}, IP
        ))
        data = validate_success(api.transition_forensic_review(
            review["id"], {"to_status": "ESCALATED"}, IP
        ))
        assert data["status"] == "ESCALATED"


class TestLetterIssueGate:
    def test_letter_issue_before_approval_rejected(self, api):
        """PRD §3.7: "Issuing — `COUNSEL_APPROVED → ISSUED`, again senior
        counsel — stamps `issued_at` at the current clock and computes
        `response_deadline` as `issued_at` plus `response_deadline_days` days."
        PRD §2.12: "Sixth (6) state-machine preconditions: the transition must
        be defined from the current state and entity-level state gates must
        hold, else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/letter_issue_before_approval_rejected
        """
        emp, review = create_escalated_review_via_notice(
            emp_overrides={
                "full_name": "Bob Ex", "email": "bob@x.com", "department": "ENG",
                "role_title": "SDE", "access_clearance": "STANDARD",
                "hired_at": "2026-05-01T00:00:00Z",
            },
            exfil_indicator_count=1,
        )
        resp = api.create_asset(
            create_asset_payload(
                title="roadmap", description="x", classification="INTERNAL",
                owner_department="ENG", exposure_estimate_cents=5000,
            ), IP
        )
        asset = validate_success(resp, expected_status=201)
        resp = api.create_demand_letter(
            create_demand_letter_payload(
                review["id"],
                [{"asset_id": asset["id"], "claim_type": "PRESERVATION"}],
                response_deadline_days=10,
            ),
            make_ip_counsel_headers("counsel_1"),
        )
        letter = validate_success(resp, expected_status=201)
        resp = api.transition_demand_letter(
            letter["id"], {"to_status": "ISSUED"},
            TEST_USERS["senior_counsel_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        data = validate_success(api.get_demand_letter(letter["id"], IP))
        assert data["status"] == "DRAFTED"


class TestGrantAndDisclosureTerminalLockdown:
    def test_grant_denied_terminal_lockdown(self, api):
        """PRD §3.4: "Denial — `REQUESTED → DENIED` — is unconditional and
        terminal."
        PRD §2.12: "Sixth (6) state-machine preconditions: the transition must
        be defined from the current state and entity-level state gates must
        hold, else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/grant_denied_terminal_lockdown
        """
        emp = create_active_employee(
            complete_training=False, full_name="Cleo Deny", email="cleo@x.com",
            department="OPS", role_title="Tech", access_clearance="STANDARD",
            hired_at="2026-05-01T00:00:00Z",
        )
        asset = create_registered_asset(
            title="Shift matrix", description="x", classification="INTERNAL",
            owner_department="OPS", exposure_estimate_cents=9000,
        )
        grant = create_grant_request(emp["id"], asset["id"], justification="j",
                                     expires_at="2026-12-01T00:00:00Z")
        validate_success(api.transition_grant(grant["id"], {"to_status": "DENIED"}, SEC))
        resp = api.transition_grant(grant["id"], {"to_status": "APPROVED"}, IP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        data = validate_success(api.get_grant(grant["id"], SEC))
        assert data["status"] == "DENIED"

    def test_disclosure_withdrawn_terminal_lockdown(self, api):
        """PRD §3.5: "The requester may also withdraw from `DRAFT`, `SUBMITTED`,
        or `RETURNED`; `WITHDRAWN` is terminal."
        PRD §2.12: "Sixth (6) state-machine preconditions: the transition must
        be defined from the current state and entity-level state gates must
        hold, else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/disclosure_withdrawn_terminal_lockdown
        """
        cp = create_counterparty(legal_name="Rho Design", counterparty_type="CUSTOMER")
        resp = api.create_nda(
            create_nda_payload(
                cp["id"], template_version="t15", governing_law="AZ",
                effective_date="2026-01-01T00:00:00Z", expiry_date="2027-01-01T00:00:00Z",
                survival_months=3, classification_ceiling="INTERNAL",
            ), IP
        )
        nda = validate_success(resp, expected_status=201)
        asset = create_registered_asset(
            title="Font metrics", description="x", classification="INTERNAL",
            owner_department="MKT", exposure_estimate_cents=500,
        )
        emp = create_employee_record(
            full_name="Dee Market", email="dee@x.com", department="MKT",
            role_title="Designer", access_clearance="STANDARD",
            hired_at="2026-05-01T00:00:00Z",
        )
        disc = create_draft_disclosure(
            emp["id"], asset["id"], nda["id"],
            purpose="p", marking_protocol="ORAL_WITH_FOLLOWUP",
            planned_disclosure_date="2026-08-01T00:00:00Z",
        )
        validate_success(api.transition_disclosure(
            disc["id"], {"to_status": "WITHDRAWN"}, make_employee_headers(emp["id"])
        ))
        resp = api.transition_disclosure(
            disc["id"], {"to_status": "SUBMITTED"}, make_employee_headers(emp["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        data = validate_success(api.get_disclosure(disc["id"], IP))
        assert data["status"] == "WITHDRAWN"
