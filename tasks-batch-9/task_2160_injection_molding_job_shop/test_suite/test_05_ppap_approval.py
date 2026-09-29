"""First-article evidence, internal review and the customer's PPAP verdict."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_ppap_submission,
    create_customer,
    create_mold,
    create_ppap,
    create_press,
    create_quote,
    endorse_ppap,
    file_ppap,
    make_customer_rep_headers,
    mold_version,
    read_mold,
    read_ppap,
    set_clock,
    setup_ppap_under_review,
    setup_sampling_tool,
    validate_error,
    validate_success,
)

PA = TEST_USERS["plant_admin_headers"]
QE_ALICE = TEST_USERS["quality_engineer_headers"]
QE_BOB = TEST_USERS["quality_reviewer_headers"]


def test_filing_a_package_needs_a_passing_verdict_and_thirty_sample_shots(api):
    """PRD §3.4: "Filing requires that the tool's lifecycle status is `SAMPLING` —
    otherwise `ERR_MOLD_NOT_PPAP_APPROVED` — and that the first-article evidence is
    adequate: the dimensional verdict must be true, and the sample must have been
    drawn from a run of at least 30 shots. A false verdict or a sample below 30
    shots is rejected with `ERR_FAI_NOT_PASSED`. On success both values are stored,
    the acting `X-User-ID` is recorded as `submitted_by_user_id`, and the package
    moves `DRAFT → SUBMITTED`."

    Design: Corner/state_machines/ppap_submit_with_failed_first_article_returns_fai_not_passed
    """
    shop = setup_sampling_tool()
    submission = create_ppap(shop["mold"]["id"], shop["quote"]["id"])

    failed_verdict = api.submit_ppap(
        submission["id"], {"fai_dimensional_pass": False, "fai_sample_shots": 60}, QE_ALICE
    )
    assert failed_verdict.status_code == 422, f"Expected 422, got {failed_verdict.status_code}"
    validate_error(failed_verdict, ApiErrorId.ERR_FAI_NOT_PASSED.value)

    short_sample = api.submit_ppap(
        submission["id"], {"fai_dimensional_pass": True, "fai_sample_shots": 29}, QE_ALICE
    )
    assert short_sample.status_code == 422, f"Expected 422, got {short_sample.status_code}"
    validate_error(short_sample, ApiErrorId.ERR_FAI_NOT_PASSED.value)

    still_draft = read_ppap(submission["id"])
    assert still_draft["status"] == "DRAFT"
    assert still_draft.get("submitted_by_user_id") is None

    accepted = validate_success(
        api.submit_ppap(
            submission["id"], {"fai_dimensional_pass": True, "fai_sample_shots": 30}, QE_ALICE
        )
    )
    assert_ppap_submission(accepted)
    assert accepted["status"] == "SUBMITTED"
    assert accepted["fai_sample_shots"] == 30


def test_a_package_cannot_be_filed_while_the_tool_is_still_new(api):
    """PRD §3.4: "Opening a package is deliberately ungated: it starts in `DRAFT`
    with `revision_no` at 1, and the tool-status gate bites at filing time, not at
    creation time."
    PRD §3.4: "Filing requires that the tool's lifecycle status is `SAMPLING` —
    otherwise `ERR_MOLD_NOT_PPAP_APPROVED` — and that the first-article evidence is
    adequate: the dimensional verdict must be true, and the sample must have been
    drawn from a run of at least 30 shots."

    Design: Corner/errors/ppap_submit_while_mold_is_not_sampling_returns_mold_not_ppap_approved
    """
    set_clock()
    customer = create_customer()
    create_press()
    mold = create_mold(customer["id"])
    quote = create_quote(customer["id"], mold["id"])
    submission = create_ppap(mold["id"], quote["id"])
    assert submission["status"] == "DRAFT"
    assert submission["revision_no"] == 1

    response = api.submit_ppap(
        submission["id"], {"fai_dimensional_pass": True, "fai_sample_shots": 40}, QE_ALICE
    )

    assert response.status_code == 409, f"Expected 409, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_MOLD_NOT_PPAP_APPROVED.value)
    still_draft = read_ppap(submission["id"])
    assert still_draft["status"] == "DRAFT"
    assert still_draft.get("submitted_by_user_id") is None
    assert read_mold(mold["id"])["status"] == "NEW"


def test_the_submitter_may_not_endorse_their_own_package(api):
    """PRD §3.4: "A `QualityEngineer` or a `PlantAdmin` supplies a `decision` of
    `ENDORSE` or `REJECT` and an optional `note`, and in either case the acting
    `X-User-ID` is recorded as `internal_reviewed_by_user_id`. The reviewer's
    `X-User-ID` must differ from the `submitted_by_user_id` already stored on the
    package; when they are the same principal the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES`. An endorsement moves the package `SUBMITTED →
    UNDER_REVIEW` and puts it in front of the customer."

    Design: Corner/rbac/ppap_submitter_cannot_endorse_their_own_package
    """
    shop = setup_sampling_tool()
    submission = create_ppap(shop["mold"]["id"], shop["quote"]["id"])
    file_ppap(submission["id"])

    self_review = api.ppap_internal_review(
        submission["id"], {"decision": "ENDORSE", "note": "self review attempt"}, QE_ALICE
    )
    assert self_review.status_code == 403, f"Expected 403, got {self_review.status_code}"
    validate_error(self_review, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    unchanged = read_ppap(submission["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged.get("internal_reviewed_by_user_id") is None

    endorsed = validate_success(
        api.ppap_internal_review(submission["id"], {"decision": "ENDORSE"}, QE_BOB)
    )
    assert endorsed["status"] == "UNDER_REVIEW"
    assert endorsed["internal_reviewed_by_user_id"] == "qe-bob"


def test_a_customer_rejection_leaves_the_tool_untouched_and_revision_clears_the_round(api):
    """PRD §3.4: "**`REJECT`** carries no tool-status requirement beyond the package
    being `UNDER_REVIEW`. The package moves `UNDER_REVIEW → REJECTED`, and the tool
    is not mutated: its status, its `approved_max_regrind_bp`, its
    `interim_expiry_shots` and its `version` are all unchanged."
    PRD §3.4: "A `QualityEngineer` may send it back for another round, optionally
    supplying a replacement `max_regrind_bp`, which moves it `REJECTED → DRAFT`,
    increments `revision_no` by 1, and clears `fai_dimensional_pass`,
    `fai_sample_shots`, `submitted_by_user_id`, `internal_reviewed_by_user_id` and
    `customer_decided_by_user_id` all back to unset, so the next round re-earns
    every one of them."

    Design: Difficulty/non_linear_state_machine/ppap_reject_revise_resubmit_cycle
    """
    shop = setup_ppap_under_review()
    submission_id = shop["ppap"]["id"]

    rejected = validate_success(
        api.ppap_customer_decision(
            submission_id,
            {
                "decision": "REJECT",
                "expected_mold_version": mold_version(shop["mold"]["id"]),
                "reason": "gate vestige exceeds print callout",
            },
            make_customer_rep_headers(shop["customer"]["id"]),
        )
    )
    assert rejected["status"] == "REJECTED"
    assert read_mold(shop["mold"]["id"])["status"] == "SAMPLING"

    revised = validate_success(
        api.revise_ppap(submission_id, {"max_regrind_bp": 2000}, QE_ALICE)
    )
    assert revised["status"] == "DRAFT"
    assert revised["revision_no"] == 2
    assert revised.get("fai_dimensional_pass") is None
    assert revised.get("fai_sample_shots") is None
    assert revised.get("submitted_by_user_id") is None
    assert revised.get("internal_reviewed_by_user_id") is None
    assert revised.get("customer_decided_by_user_id") is None


def test_the_revised_package_re_earns_every_actor_and_reaches_approved(api):
    """PRD §3.4: "On success both values are stored, the acting `X-User-ID` is
    recorded as `submitted_by_user_id`, and the package moves `DRAFT → SUBMITTED`."
    PRD §3.4: "**`APPROVE`** additionally requires the tool's lifecycle status to be
    `SAMPLING`. The package moves `UNDER_REVIEW → APPROVED`. The tool moves
    `SAMPLING → PPAP_APPROVED`, its `approved_max_regrind_bp` is set to the
    package's `max_regrind_bp`, its `interim_expiry_shots` is cleared to unset, and
    its `version` is incremented by 1."

    Design: Difficulty/non_linear_state_machine/ppap_reject_revise_resubmit_cycle
    """
    shop = setup_ppap_under_review()
    submission_id = shop["ppap"]["id"]
    customer_headers = make_customer_rep_headers(shop["customer"]["id"])

    validate_success(
        api.ppap_customer_decision(
            submission_id,
            {
                "decision": "REJECT",
                "expected_mold_version": mold_version(shop["mold"]["id"]),
                "reason": "gate vestige exceeds print callout",
            },
            customer_headers,
        )
    )
    validate_success(api.revise_ppap(submission_id, {"max_regrind_bp": 2000}, QE_ALICE))

    resubmitted = validate_success(
        api.submit_ppap(
            submission_id, {"fai_dimensional_pass": True, "fai_sample_shots": 45}, QE_ALICE
        )
    )
    assert resubmitted["fai_sample_shots"] == 45
    assert resubmitted["submitted_by_user_id"] == "qe-alice"

    endorse_ppap(submission_id)
    approved = validate_success(
        api.ppap_customer_decision(
            submission_id,
            {
                "decision": "APPROVE",
                "expected_mold_version": mold_version(shop["mold"]["id"]),
            },
            customer_headers,
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["revision_no"] == 2
    mold = read_mold(shop["mold"]["id"])
    assert mold["status"] == "PPAP_APPROVED"
    assert mold["approved_max_regrind_bp"] == 2000


def test_a_quarantined_tool_blocks_the_customers_approval(api):
    """PRD §3.4: "Quarantining a tool that is still `SAMPLING` fires no cascade at
    all — a sampling tool has no production jobs, by construction — but it does mean
    any package sitting in `UNDER_REVIEW` can no longer be approved until the tool
    is released."
    PRD §3.4: "An operation aimed at a tool that is currently `QUARANTINED` is
    rejected with `ERR_MOLD_QUARANTINED`."

    Design: Difficulty/cross_entity_state_dependency/ppap_customer_approval_gated_on_mold_status
    """
    shop = setup_ppap_under_review()
    validate_success(
        api.mold_quality_hold(
            shop["mold"]["id"],
            {"action": "QUARANTINE", "reason": "dimensional drift found on cavity 3"},
            QE_ALICE,
        )
    )

    response = api.ppap_customer_decision(
        shop["ppap"]["id"],
        {"decision": "APPROVE", "expected_mold_version": mold_version(shop["mold"]["id"])},
        make_customer_rep_headers(shop["customer"]["id"]),
    )

    assert response.status_code == 409, f"Expected 409, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_MOLD_QUARANTINED.value)
    assert read_ppap(shop["ppap"]["id"])["status"] == "UNDER_REVIEW"
    assert read_mold(shop["mold"]["id"])["status"] == "QUARANTINED"


def test_releasing_the_tool_back_to_sampling_makes_the_package_decidable_again(api):
    """PRD §3.4: "If `approved_max_regrind_bp` is still unset, the tool was
    quarantined while it was still sampling and it returns to `SAMPLING`, where its
    pending package becomes decidable again."
    PRD §3.4: "**`APPROVE`** additionally requires the tool's lifecycle status to be
    `SAMPLING`. The package moves `UNDER_REVIEW → APPROVED`. The tool moves
    `SAMPLING → PPAP_APPROVED`, its `approved_max_regrind_bp` is set to the
    package's `max_regrind_bp`, its `interim_expiry_shots` is cleared to unset, and
    its `version` is incremented by 1."

    Design: Difficulty/cross_entity_state_dependency/ppap_customer_approval_gated_on_mold_status
    """
    shop = setup_ppap_under_review()
    validate_success(
        api.mold_quality_hold(
            shop["mold"]["id"],
            {"action": "QUARANTINE", "reason": "dimensional drift found on cavity 3"},
            QE_ALICE,
        )
    )

    released = validate_success(
        api.mold_quality_hold(
            shop["mold"]["id"],
            {"action": "RELEASE", "reason": "parting line stoned and re-sampled"},
            QE_ALICE,
        )
    )
    assert released["status"] == "SAMPLING", (
        "approved_max_regrind_bp was still unset, so the tool returns to SAMPLING"
    )

    approved = validate_success(
        api.ppap_customer_decision(
            shop["ppap"]["id"],
            {
                "decision": "APPROVE",
                "expected_mold_version": mold_version(shop["mold"]["id"]),
            },
            make_customer_rep_headers(shop["customer"]["id"]),
        )
    )
    assert approved["status"] == "APPROVED"
    mold = read_mold(shop["mold"]["id"])
    assert mold["status"] == "PPAP_APPROVED"
    assert mold["approved_max_regrind_bp"] == 2000
