"""Application review cycle and preference claims: info loop, decisions,
appeals, evidence and category constraints, and withdrawal lockdown."""
from test_helpers import (
    ApiErrorId, assert_preference_claim, fixtures, get_success_data,
    make_applicant_headers, validate_error, validate_success,
)

CLERK = fixtures.CLERK


def _open_campaign_with_application(api, full_name="Yara Y",
                                    email="y@x.com"):
    prop = fixtures.new_property(api)
    campaign = fixtures.new_open_campaign(api, prop["id"])
    applicant = fixtures.new_applicant(api, full_name=full_name, email=email)
    application = fixtures.submit_application(api, campaign["id"],
                                              applicant["id"])
    return campaign, applicant, application


def test_review_info_cycle_twice_statuses(api):
    """PRD §3.3: "An `ApplicationClerk` begins review, moving the application
    from `SUBMITTED` to `UNDER_REVIEW`; requests more information, moving it
    from `UNDER_REVIEW` to `NEEDS_INFO` (the request may carry an optional
    free-text `note`); and the owning applicant answers, moving it from
    `NEEDS_INFO` back to `UNDER_REVIEW`".

    Design: Difficulty/non_linear_state_machine/application_review_info_cycle_twice
    """
    _, applicant, application = _open_campaign_with_application(
        api, full_name="Eve E", email="e@x.com")
    app_id = application["id"]
    owner = make_applicant_headers(applicant["id"])

    fixtures.review_action(api, app_id, "BEGIN_REVIEW", CLERK)
    first = fixtures.review_action(api, app_id, "REQUEST_INFO", CLERK,
                                   note="need id")
    assert first["status"] == "NEEDS_INFO"
    second = fixtures.review_action(api, app_id, "SUBMIT_INFO", owner,
                                    note="id attached")
    assert second["status"] == "UNDER_REVIEW", "first cycle closes A->B->A"
    third = fixtures.review_action(api, app_id, "REQUEST_INFO", CLERK,
                                   note="need paystub")
    assert third["status"] == "NEEDS_INFO"
    fourth = fixtures.review_action(api, app_id, "SUBMIT_INFO", owner,
                                    note="paystub attached")
    assert fourth["status"] == "UNDER_REVIEW", (
        "the loop is repeatable, not one-shot — the second full traversal "
        "lands back in UNDER_REVIEW"
    )


def test_review_info_cycle_twice_version_increments(api):
    """PRD §2.4: "`version` (integer): a system-managed integer that
    increments by exactly 1 on every mutation of the resource."

    Design: Difficulty/non_linear_state_machine/application_review_info_cycle_twice
    """
    _, applicant, application = _open_campaign_with_application(
        api, full_name="Eve E", email="e@x.com")
    app_id = application["id"]
    owner = make_applicant_headers(applicant["id"])
    v0 = application["version"]

    fixtures.review_action(api, app_id, "BEGIN_REVIEW", CLERK)
    for note in ("need id", "need paystub"):
        fixtures.review_action(api, app_id, "REQUEST_INFO", CLERK, note=note)
        fixtures.review_action(api, app_id, "SUBMIT_INFO", owner,
                               note="attached")
    final = get_success_data(api.get_application(app_id, CLERK))
    assert final["version"] == v0 + 5, (
        "create plus five review transitions, each incrementing by exactly 1"
    )


def test_claim_appeal_returns_to_pending_with_new_evidence(api):
    """PRD §3.3: "the owning applicant may appeal a `DENIED` claim back to
    `PENDING` by supplying a `new_evidence_ref`, which replaces the stored
    `evidence_ref` and clears the `denial_reason`".

    Design: Corner/state_machines/claim_appeal_returns_to_pending_with_new_evidence
    """
    _, applicant, application = _open_campaign_with_application(
        api, full_name="Xan X", email="x2@x.com")
    claim = fixtures.file_claim(api, application["id"], applicant["id"],
                                "LOCAL_RESIDENT", "old-lease")
    fixtures.decide_claim(api, claim["id"], "DENY",
                          denial_reason="lease older than 12 months")

    appealed = validate_success(api.transition_preference_claim(
        claim["id"],
        {"action": "APPEAL", "new_evidence_ref": "current-utility-bill"},
        make_applicant_headers(applicant["id"])))
    assert_preference_claim(appealed)
    assert appealed["status"] == "PENDING"
    assert appealed["evidence_ref"] == "current-utility-bill"
    assert appealed["denial_reason"] is None


def test_complete_verification_with_pending_claim_returns_claims_pending(api):
    """PRD §3.3: "Completion requires that no preference claim of the
    application still sits in `PENDING` — one that does triggers
    `ERR_PREFERENCE_CLAIMS_PENDING` — and stamps `verified_at` while
    recomputing `verified_preference_categories` from the application's
    verified claims, leaving the application `VERIFIED`."

    Design: Corner/state_machines/complete_verification_with_pending_claim_returns_claims_pending
    """
    _, applicant, application = _open_campaign_with_application(
        api, full_name="Yara Y", email="y@x.com")
    claim = fixtures.file_claim(api, application["id"], applicant["id"],
                                "VETERAN", "dd214")
    fixtures.review_action(api, application["id"], "BEGIN_REVIEW", CLERK)

    resp = api.review_application(application["id"],
                                  {"action": "COMPLETE_VERIFICATION"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_PREFERENCE_CLAIMS_PENDING)

    fixtures.decide_claim(api, claim["id"], "VERIFY")
    verified = validate_success(api.review_application(
        application["id"], {"action": "COMPLETE_VERIFICATION"}, CLERK))
    assert verified["status"] == "VERIFIED"
    assert verified["verified_preference_categories"] == ["VETERAN"]


def test_withdraw_twice_returns_invalid_state(api):
    """PRD §3.3: "from `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_INFO` the owning
    applicant may withdraw, moving the application to terminal `WITHDRAWN`."
    PRD §2.10: "all other state violations yield the generic
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/withdraw_twice_returns_invalid_state
    """
    _, applicant, application = _open_campaign_with_application(
        api, full_name="Zed Z", email="z2@x.com")
    owner = make_applicant_headers(applicant["id"])
    withdrawn = validate_success(
        api.withdraw_application(application["id"], owner))
    assert withdrawn["status"] == "WITHDRAWN"
    resp = api.withdraw_application(application["id"], owner)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    final = get_success_data(api.get_application(application["id"], CLERK))
    assert final["status"] == "WITHDRAWN"


def test_claim_without_evidence_returns_evidence_required(api):
    """PRD §3.3: "The owning applicant files a claim against an
    `application_id`, naming a `category` of `LOCAL_RESIDENT`, `VETERAN`, or
    `ACCESSIBILITY` and supplying an `evidence_ref` document reference; an
    empty or missing reference is rejected with
    `ERR_PREFERENCE_EVIDENCE_REQUIRED`".

    Design: Corner/validations/claim_without_evidence_returns_evidence_required
    """
    _, applicant, application = _open_campaign_with_application(
        api, full_name="Val V", email="v9@x.com")
    resp = api.create_preference_claim(
        fixtures.create_preference_claim_payload(application["id"],
                                                 category="VETERAN",
                                                 evidence_ref=""),
        make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_PREFERENCE_EVIDENCE_REQUIRED)

    ok = validate_success(api.create_preference_claim(
        fixtures.create_preference_claim_payload(application["id"],
                                                 category="VETERAN",
                                                 evidence_ref="dd214-scan"),
        make_applicant_headers(applicant["id"])), expected_status=201)
    assert ok["status"] == "PENDING"


def test_duplicate_claim_category_rejected(api):
    """PRD §3.3: "an empty or missing reference is rejected with
    `ERR_PREFERENCE_EVIDENCE_REQUIRED`, and a second claim of the same
    category on the same application with `ERR_DUPLICATE_CLAIM`."

    Design: Corner/validations/duplicate_claim_category_rejected
    """
    _, applicant, application = _open_campaign_with_application(
        api, full_name="Wyn W", email="w9@x.com")
    fixtures.file_claim(api, application["id"], applicant["id"],
                        "LOCAL_RESIDENT", "lease")

    resp = api.create_preference_claim(
        fixtures.create_preference_claim_payload(application["id"],
                                                 category="LOCAL_RESIDENT",
                                                 evidence_ref="utility-bill"),
        make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLAIM)

    other = validate_success(api.create_preference_claim(
        fixtures.create_preference_claim_payload(application["id"],
                                                 category="ACCESSIBILITY",
                                                 evidence_ref="mobility-cert"),
        make_applicant_headers(applicant["id"])), expected_status=201)
    assert other["category"] == "ACCESSIBILITY"
