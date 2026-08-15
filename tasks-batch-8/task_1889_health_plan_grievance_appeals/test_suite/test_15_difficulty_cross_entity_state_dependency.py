"""Difficulty queue: cross-entity state dependencies (PRD §2.10, §3.5, §3.7, §3.8)."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, api_client,
    TEST_USERS, make_intake_specialist_headers, make_medical_director_headers,
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


def _setup_appeal_review_in_draft():
    """APPEAL in PENDING_CLINICAL with the review in DETERMINATION_DRAFT."""
    member = create_member("MBR-CE1", full_name="Drew Han", program="MEDICARE")
    provider = create_provider("8765432109", legal_name="Han Partners",
                               w9_on_file=True)
    create_policy("MEDICARE", "APPEAL", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock("2026-08-01T00:00:00Z")
    case = intake_case(member["id"], case_kind="APPEAL",
                       provider_id=provider["id"])
    triage_case(case["id"],
                headers=make_intake_specialist_headers("intake-ce1"))
    begin_review(case["id"])
    review = request_clinical_review(case["id"])
    get_success_data(api_client.assign_clinical_review(
        review["id"], {"reviewer_physician_id": "md-701"},
        make_medical_director_headers("md-admin")))
    get_success_data(api_client.draft_determination(
        review["id"], create_clinical_factors_payload(
            severity=7, acuity=7, guideline_match=7, comorbidity=7,
            functional_impairment=7),
        make_medical_director_headers("md-701")))
    return case, review


def test_decide_blocked_until_sibling_review_determined(api):
    """PRD §3.5: "The clinical door: a `MedicalDirector` decides a case in
    `PENDING_CLINICAL`, which requires a Clinical Review for the case to
    already sit in `DETERMINED` status and requires, per §2.10, that the
    deciding physician not be the intake specialist who triaged the case."
PRD §2.8: "Only after those six generic gates do endpoint-specific business rules
    apply, and they too have a fixed relative order: segregation of duties
    (`ERR_DUTY_SEGREGATION`); clinical routing
    (`ERR_CLINICAL_REVIEW_REQUIRED`); the three temporal windows —
    acknowledgement (`ERR_ACK_WINDOW_MISSED`), IRE forwarding
    (`ERR_IRE_WINDOW_MISSED`), and reopening (`ERR_REOPEN_WINDOW_MISSED`);
    the one-live-clinical-review constraint (`ERR_REVIEW_IN_FLIGHT`); the
    single-extension constraint (`ERR_EXTENSION_CONSUMED`); expedited
    eligibility (`ERR_EXPEDITED_NOT_ALLOWED`); policy configuration
    (`ERR_POLICY_NOT_CONFIGURED`); notification completeness
    (`ERR_NOTIFICATION_INCOMPLETE`); the W-9 payment gate
    (`ERR_W9_REQUIRED`); the waiver gate (`ERR_WAIVER_NOT_ALLOWED`); the
    payment allowance rule (`ERR_PAYMENT_NOT_ALLOWED`); and finally the
    duplicate-intake guard (`ERR_DUPLICATE_CASE`)."

    Design: Difficulty/cross_entity_state_dependency/case_decide_depends_on_clinical_review_determined
    """
    case, review = _setup_appeal_review_in_draft()
    # Review is DETERMINATION_DRAFT, not DETERMINED: the decide must be
    # rejected by the clinical-routing rule.
    validate_error(
        api.decide_case(case["id"], {"decision_outcome": "UNFAVORABLE"},
                        make_medical_director_headers("md-702")),
        ApiErrorId.ERR_CLINICAL_REVIEW_REQUIRED)


def test_decide_succeeds_after_review_reaches_determined(api):
    """PRD §3.5: "Recording the decision sets `decision_outcome`, stamps `decided_at`, moves
    the case to `DECIDED`, appends a `DECISION_RECORDED` event, and
    increments the case's `version`."

    Design: Difficulty/cross_entity_state_dependency/case_decide_depends_on_clinical_review_determined
    """
    case, review = _setup_appeal_review_in_draft()
    get_success_data(api.finalize_determination(
        review["id"], {"determination": "UPHOLD_SERVICE"},
        make_medical_director_headers("md-701")))
    data = validate_success(api.decide_case(
        case["id"], {"decision_outcome": "UNFAVORABLE"},
        make_medical_director_headers("md-702")))
    assert data["status"] == "DECIDED"
    assert data["decision_outcome"] == "UNFAVORABLE"


def _setup_payment_effectuation_without_w9():
    """GRIEVANCE decided FULLY_FAVORABLE with payment 25000 against a provider
    whose w9_on_file is false. Returns (member, provider, case, effectuation)."""
    member = create_member("MBR-CE2", full_name="Eli Poe", program="MEDICARE")
    provider = create_provider("7654321098", legal_name="Poe Associates",
                               w9_on_file=False)
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock("2026-08-01T00:00:00Z")
    case = create_in_review_case(member["id"], case_kind="GRIEVANCE",
                                 provider_id=provider["id"])
    case = decide_grievance_from_in_review(
        case["id"], decision_outcome="FULLY_FAVORABLE",
        payment_amount_cents=25000)
    return member, provider, case, get_case_effectuation(case["id"])


def test_effectuation_start_blocked_by_provider_w9(api):
    """PRD §3.7: "The W-9 gate stands in front of any monetary release: when
    `payment_amount_cents` is greater than zero and the case's
    `provider_id` references a Provider, that provider's `w9_on_file` must
    be `true`, or the start is rejected with `ERR_W9_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/effectuation_start_depends_on_provider_w9
    """
    _m, _p, _c, eff = _setup_payment_effectuation_without_w9()
    validate_error(api.start_effectuation(eff["id"], CLAIMS),
                   ApiErrorId.ERR_W9_REQUIRED)
    after = get_success_data(api.get_effectuation(eff["id"], CLAIMS))
    assert after["status"] == "PENDING"


def test_effectuation_start_succeeds_after_w9_filed(api):
    """PRD §3.1: "A `PlatformAdmin` may later patch a provider's `w9_on_file` and
    `contract_status`; each patch increments the provider's `version`."
PRD §3.7: "A `ClaimsProcessor` starts a `PENDING` effectuation, moving it to
    `IN_PROGRESS` and appending an `EFFECTUATION_STARTED` event on the
    parent case."

    Design: Difficulty/cross_entity_state_dependency/effectuation_start_depends_on_provider_w9
    """
    _m, provider, _c, eff = _setup_payment_effectuation_without_w9()
    validate_error(api.start_effectuation(eff["id"], CLAIMS),
                   ApiErrorId.ERR_W9_REQUIRED)
    patched = validate_success(api.patch_provider(
        provider["id"], {"w9_on_file": True}, ADMIN))
    assert patched["w9_on_file"] is True
    data = validate_success(api.start_effectuation(eff["id"], CLAIMS))
    assert data["status"] == "IN_PROGRESS"


def test_reopening_rejected_when_source_case_not_closed(api):
    """PRD §3.8: "A `ComplianceOfficer` or a `MemberServicesRep` may request a reopening
    against a `CLOSED` case by supplying the `case_id` and a
    `request_reason` of `NEW_EVIDENCE`, `CLERICAL_ERROR`, or
    `FRAUD_OR_SIMILAR_FAULT`; the request stamps `requested_at` and
    appends a `REOPEN_REQUESTED` event on the source case."
PRD §2.8: "Fifth, transition validity: if the requested action is not declared from
    the resource's current state, the request is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/reopening_grant_depends_on_source_case_closed
    """
    member = create_member("MBR-CE3", full_name="Fay Zhu", program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock("2026-08-01T00:00:00Z")
    case = create_in_review_case(member["id"], case_kind="GRIEVANCE")
    validate_error(
        api.create_reopening({"case_id": case["id"],
                              "request_reason": "NEW_EVIDENCE"}, COMPLIANCE),
        ApiErrorId.ERR_INVALID_STATE)


def test_reopening_rejection_creates_no_reopening_row(api):
    """PRD §3.8: "Reopenings against a case are listable with a `status` filter."

    Design: Difficulty/cross_entity_state_dependency/reopening_grant_depends_on_source_case_closed
    """
    member = create_member("MBR-CE3B", full_name="Fay Zhu B",
                           program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock("2026-08-01T00:00:00Z")
    case = create_in_review_case(member["id"], case_kind="GRIEVANCE")
    validate_error(
        api.create_reopening({"case_id": case["id"],
                              "request_reason": "NEW_EVIDENCE"}, COMPLIANCE),
        ApiErrorId.ERR_INVALID_STATE)
    rows = get_success_data(api.list_case_reopenings(case["id"], COMPLIANCE))
    assert rows == [], f"No Reopening row may exist for a rejected request; got {rows}"
