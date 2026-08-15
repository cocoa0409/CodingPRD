"""Corner queue: validation rules (PRD §2.1, §2.8, §2.10, §3.2, §3.3, §3.4,
§3.7).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    NON_EXISTENT_UUID, CLOCK_DEFAULT_ISO,
    TEST_USERS, make_intake_specialist_headers, make_medical_director_headers,
    make_case_analyst_headers,
    create_member, create_provider, create_policy, set_clock,
    intake_case, triage_case, begin_review, create_in_review_case,
    request_clinical_review, walk_review_to_determined,
    decide_grievance_from_in_review, get_case_effectuation,
    create_clinical_factors_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
ANALYST = TEST_USERS["case_analyst_headers"]
MD = TEST_USERS["medical_director_headers"]
MSR = TEST_USERS["member_services_rep_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
CLAIMS = TEST_USERS["claims_processor_headers"]


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "A request whose headers are missing or whose role is not one of these
    seven is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unauthenticated_missing_headers
    """
    validate_error(api.get_member(NON_EXISTENT_UUID, headers={}),
                   ApiErrorId.ERR_UNAUTHENTICATED)


def test_expedited_grievance_intake_rejected(api):
    """PRD §3.2: "And because grievances have no expedited track, an intake that sets
    `expedited_requested` on a `GRIEVANCE` is rejected with
    `ERR_EXPEDITED_NOT_ALLOWED`."

    Design: Corner/validations/expedited_grievance_intake_rejected
    """
    member = create_member("MBR-VA2", full_name="Exp Grv", program="MEDICARE")
    set_clock(CLOCK_DEFAULT_ISO)
    validate_error(
        api.create_case({"member_id": member["id"], "case_kind": "GRIEVANCE",
                         "expedited_requested": True,
                         "expedited_justification": "urgent"}, INTAKE),
        ApiErrorId.ERR_EXPEDITED_NOT_ALLOWED)


def test_triage_without_configured_policy_rejected(api):
    """PRD §2.9: "Triage and priority upgrades both require exactly one active policy for
    the case's triple; its absence is rejected with
    `ERR_POLICY_NOT_CONFIGURED`."

    Design: Corner/validations/policy_not_configured_at_triage
    """
    member = create_member("MBR-VA3", full_name="No Policy", program="MEDICARE")
    provider = create_provider("2233445566", legal_name="NoPolicy Clinic",
                               w9_on_file=True)
    # Only a GRIEVANCE policy exists; the ORG_DETERMINATION triple is bare.
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock(CLOCK_DEFAULT_ISO)
    case = intake_case(member["id"], case_kind="ORG_DETERMINATION",
                       provider_id=provider["id"])
    validate_error(api.triage_case(case["id"], INTAKE),
                   ApiErrorId.ERR_POLICY_NOT_CONFIGURED)


def test_ack_window_boundary_exactly_24h_ok_25h_fails(api):
    """PRD §3.3: "And the acknowledgement window is enforced: triage attempted more than 24
    hours after `received_at` is rejected with `ERR_ACK_WINDOW_MISSED`."

    Design: Corner/validations/ack_window_missed_at_triage
    """
    member = create_member("MBR-VA4", full_name="Ack Win", program="MEDICARE")
    # Case B rides on a second member: an identical intake (same
    # member/kind/provider) within one hour is a duplicate (PRD §3.2), and
    # both intakes must stamp received_at at the same instant.
    member_b = create_member("MBR-VA4B", full_name="Ack Win B",
                             program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock("2026-08-01T00:00:00Z")
    case_a = intake_case(member["id"], case_kind="GRIEVANCE")
    case_b = intake_case(member_b["id"], case_kind="GRIEVANCE")
    # Exactly +24h is not "more than 24 hours": the triage succeeds.
    set_clock("2026-08-02T00:00:00Z")
    ok = validate_success(api.triage_case(case_a["id"], INTAKE))
    assert ok["status"] == "TRIAGED"
    # +25h is more than 24 hours after received_at.
    set_clock("2026-08-02T01:00:01Z")
    validate_error(api.triage_case(case_b["id"], INTAKE),
                   ApiErrorId.ERR_ACK_WINDOW_MISSED)


def test_second_clinical_review_while_live_rejected(api):
    """PRD §3.4: "A replacement review may also be requested while the case is already in
    `PENDING_CLINICAL` — for example after a prior review reached a
    terminal state — but only one live review may exist per case at any
    moment: if any review for the case currently sits in `REQUESTED`,
    `ASSIGNED`, or `DETERMINATION_DRAFT`, the request is rejected with
    `ERR_REVIEW_IN_FLIGHT` (HTTP 409)."

    Design: Corner/validations/review_in_flight_second_request_rejected
    """
    member = create_member("MBR-VA5", full_name="In Flight", program="MEDICARE")
    provider = create_provider("3344556677", legal_name="InFlight Clinic",
                               w9_on_file=True)
    create_policy("MEDICARE", "APPEAL", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock(CLOCK_DEFAULT_ISO)
    case = create_in_review_case(member["id"], case_kind="APPEAL",
                                 provider_id=provider["id"])
    request_clinical_review(case["id"])
    validate_error(api.request_clinical_review(case["id"], ANALYST),
                   ApiErrorId.ERR_REVIEW_IN_FLIGHT)


def test_duty_segregation_triager_cannot_decide(api):
    """PRD §2.10: "The `MedicalDirector` who records the decision on a case sitting in
    `PENDING_CLINICAL` must not be the same operator — compared by
    `X-User-ID` — as the `IntakeSpecialist` who triaged that case."
PRD §2.10: "Either violation is rejected with `ERR_DUTY_SEGREGATION` (HTTP 422)."

    Design: Corner/validations/duty_segregation_triager_cannot_decide
    """
    member = create_member("MBR-VA6", full_name="Duty Seg", program="MEDICARE")
    provider = create_provider("4455667788", legal_name="Duty Clinic",
                               w9_on_file=True)
    create_policy("MEDICARE", "APPEAL", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock(CLOCK_DEFAULT_ISO)
    case = intake_case(member["id"], case_kind="APPEAL",
                       provider_id=provider["id"])
    triage_case(case["id"],
                headers=make_intake_specialist_headers("shared-1"))
    begin_review(case["id"])
    review = request_clinical_review(case["id"])
    walk_review_to_determined(review["id"], "md-901",
                              determination="UPHOLD_SERVICE")
    # The decider's X-User-ID equals the triager's: segregation of duties.
    validate_error(
        api.decide_case(case["id"], {"decision_outcome": "UNFAVORABLE"},
                        make_medical_director_headers("shared-1")),
        ApiErrorId.ERR_DUTY_SEGREGATION)


def test_waive_positive_payment_effectuation_rejected(api):
    """PRD §3.7: "A `ComplianceOfficer` may waive an effectuation outright, but only a
    service-only one: the waiver moves `PENDING` → `WAIVED` and requires
    `payment_amount_cents` to be exactly zero, else
    `ERR_WAIVER_NOT_ALLOWED`."

    Design: Corner/validations/waiver_rejected_for_positive_payment
    """
    member = create_member("MBR-VA7", full_name="Waive No", program="MEDICARE")
    provider = create_provider("5566778899", legal_name="Waive Clinic",
                               w9_on_file=True)
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock(CLOCK_DEFAULT_ISO)
    case = decide_grievance_from_in_review(
        create_in_review_case(member["id"], case_kind="GRIEVANCE",
                              provider_id=provider["id"])["id"],
        decision_outcome="FULLY_FAVORABLE", payment_amount_cents=9000)
    eff = get_case_effectuation(case["id"])
    validate_error(api.waive_effectuation(eff["id"], COMPLIANCE),
                   ApiErrorId.ERR_WAIVER_NOT_ALLOWED)


def test_existence_checked_before_state(api):
    """PRD §2.8: "Third, path-identifier existence, validated left to right along the URL:
    the first identifier that does not correspond to an existing row —
    whether case, notification, clinical review, IRE referral,
    effectuation, reopening, member, or provider — is rejected with
    `ERR_NOT_FOUND` (HTTP 404) before any deeper identifier is examined."

    Design: Corner/validations/existence_checked_before_state
    """
    validate_error(api.triage_case(NON_EXISTENT_UUID, INTAKE),
                   ApiErrorId.ERR_NOT_FOUND)


def test_authorization_checked_before_existence(api):
    """PRD §2.8: "Every request is checked against a fixed, prioritized validation sequence,
    and an earlier failure masks every later one."
    Authorization (second) precedes path existence (third); a ClaimsProcessor
    on a nonexistent id must see ERR_UNAUTHORIZED.

    Design: Corner/validations/authz_checked_before_existence
    """
    # close is ComplianceOfficer-only; a ClaimsProcessor on a nonexistent id
    # must see the authorization failure, not the 404.
    validate_error(api.close_case(NON_EXISTENT_UUID, CLAIMS),
                   ApiErrorId.ERR_UNAUTHORIZED)
