"""Filing and reviewing seller documentation, the package's counter partition,
the case's documentation dimension, and the two hardship-score evaluations."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_hardship_package,
    assert_package_counter_partition,
    assert_seller_document,
    create_case,
    create_package,
    file_document,
    package_decision_payload,
    review_document,
    review_document_payload,
    set_clock,
    setup_accepted_package,
    setup_package_with_documents,
    setup_submitted_package,
    validate_error,
    validate_success,
)

NEG = TEST_USERS["negotiator_headers"]
ANALYST = TEST_USERS["servicer_analyst_headers"]

# The bank statement is issued far enough back that it is fresh when verified on
# 2026-08-05 (87 days old) and stale-dated when audited on 2026-08-10 (92 days old).
STALE_DATED_BANK_STATEMENT = {"BANK_STATEMENT": {"issued_on": "2026-05-10T00:00:00Z"}}


# ─── Document review lifecycle ────────────────────────

def test_revoking_a_pending_document_is_not_reviewable(api):
    """PRD §3.2: "No review of any kind is permitted while the owning package has been
    rejected outright; such an attempt is refused with `ERR_DOCUMENT_NOT_REVIEWABLE`, as
    is a verify or reject aimed at a document that is not currently `PENDING`, and as is
    a revoke aimed at a document that is not currently `VERIFIED`."
    PRD §3.2: "Filing a document records the owning package's identifier as the
    document's `package_id`, raises the package's `document_count` by one and its
    `pending_document_count` by one, and starts the document's `status` at `PENDING`."

    Design: Corner/state_machines/revoke_pending_document_returns_document_not_reviewable
    """
    set_clock("2026-08-05T00:00:00Z")
    case = create_case()
    package = create_package(case["id"])
    document = file_document(package["id"], "HARDSHIP_LETTER")
    assert document["status"] == "PENDING"

    validate_error(
        api.review_document(document["id"], review_document_payload("REVOKE"), ANALYST),
        ApiErrorId.ERR_DOCUMENT_NOT_REVIEWABLE.value,
    )

    stored = validate_success(api.get_hardship_package(package["id"], NEG), 200)
    assert stored["pending_document_count"] == 1
    assert stored["verified_document_count"] == 0
    assert_package_counter_partition(stored)

    documents = validate_success(api.list_package_documents(package["id"], NEG), 200)
    assert documents[0]["status"] == "PENDING"
    assert_seller_document(documents[0])


def test_verifying_a_document_older_than_ninety_days_is_refused(api):
    """PRD §3.2: "A document whose age at review exceeds **90 days** may not be verified;
    the review is refused with `ERR_DOCUMENT_EXPIRED`. A document exactly 90 days old is
    still fresh and passes."

    Design: Corner/validations/verify_document_older_than_ninety_days_rejected
    """
    set_clock("2026-08-05T00:00:00Z")
    case = create_case()
    package = create_package(case["id"])
    # 2026-05-01 to 2026-08-05 is 96 whole days.
    document = file_document(
        package["id"], "BANK_STATEMENT",
        issued_on="2026-05-01T00:00:00Z", reference_label="BS-OLD",
    )

    validate_error(
        api.review_document(document["id"], review_document_payload("VERIFY"), ANALYST),
        ApiErrorId.ERR_DOCUMENT_EXPIRED.value,
    )

    stored_package = validate_success(api.get_hardship_package(package["id"], NEG), 200)
    assert stored_package["verified_document_count"] == 0
    assert stored_package["pending_document_count"] == 1

    documents = validate_success(api.list_package_documents(package["id"], NEG), 200)
    assert documents[0]["status"] == "PENDING"

    case_after = validate_success(api.get_case(case["id"], NEG), 200)
    assert case_after["documentation_status"] == "DOC_PENDING"


def test_unrecognised_review_outcome_is_malformed(api):
    """PRD §3.2: "A `ServicerAnalyst` reviews a filed document by supplying an `outcome`
    — one of `VERIFY`, `REJECT` or `REVOKE` — and, optionally, a free-text `note`."
    PRD §2.6: "Required fields present, types correct, enum members recognised, numeric
    bounds honoured — otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/errors/invalid_request_unknown_review_outcome_returns_400
    """
    set_clock("2026-08-05T00:00:00Z")
    case = create_case()
    package = create_package(case["id"])
    document = file_document(package["id"], "HARDSHIP_LETTER")

    validate_error(
        api.review_document(document["id"], {"outcome": "APPROVE"}, ANALYST),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    documents = validate_success(api.list_package_documents(package["id"], NEG), 200)
    assert documents[0]["status"] == "PENDING"
    stored_package = validate_success(api.get_hardship_package(package["id"], NEG), 200)
    assert stored_package["pending_document_count"] == 1


# ─── VERIFY / REVOKE as a compensating pair ───────────

def test_revoke_restores_every_package_counter_to_its_pre_verify_value(api):
    """PRD §3.2: "A successful verification raises the package's
    `verified_document_count` by one and lowers its `pending_document_count` by one,
    leaving `document_count` untouched."
    PRD §3.2: "`REVOKE` is the deliberate compensating action for a verification: it
    moves a `VERIFIED` document back to `PENDING`, lowers `verified_document_count` by
    one and raises `pending_document_count` by one, restoring every package counter to
    precisely the value it held before the verification it undoes — `document_count`
    having never moved at all."

    Design: Difficulty/compensating_invariant/package_document_counter_partition_restored_by_revoke
    """
    case, package, documents = setup_package_with_documents(
        package_overrides={"hardship_reason": "DIVORCE"}, verify=False
    )
    for doc_type in ("HARDSHIP_LETTER", "FINANCIAL_WORKSHEET", "BANK_STATEMENT"):
        review_document(documents[doc_type]["id"], "VERIFY")

    before = validate_success(api.get_hardship_package(package["id"], NEG), 200)
    assert (before["verified_document_count"], before["pending_document_count"]) == (3, 1)

    verified = review_document(documents["AUTHORIZATION_FORM"]["id"], "VERIFY")
    assert verified["status"] == "VERIFIED"
    midpoint = validate_success(api.get_hardship_package(package["id"], NEG), 200)
    assert midpoint["verified_document_count"] == 4
    assert midpoint["pending_document_count"] == 0
    case_mid = validate_success(api.get_case(case["id"], NEG), 200)
    assert case_mid["documentation_status"] == "DOC_COMPLETE"

    revoked = validate_success(
        api.review_document(
            documents["AUTHORIZATION_FORM"]["id"],
            review_document_payload("REVOKE", note="Signature page unsigned"),
            ANALYST,
        ),
        200,
    )
    assert revoked["status"] == "PENDING"

    after = validate_success(api.get_hardship_package(package["id"], NEG), 200)
    assert after["verified_document_count"] == 3, "the revoke restores verified to 3"
    assert after["pending_document_count"] == 1, "the revoke restores pending to 1"
    assert after["rejected_document_count"] == 0
    assert after["document_count"] == 4, "document_count never moves"


def test_package_counter_partition_holds_across_the_verify_revoke_pair(api):
    """PRD §3.1: "Creation stamps `assembled_by_user_id` from the acting header, links
    the package to its case through the case's own identifier, and starts all four
    document counters — `document_count`, `pending_document_count`,
    `verified_document_count` and `rejected_document_count` — at 0."
    PRD §3.2: "`REVOKE` is the deliberate compensating action for a verification: it
    moves a `VERIFIED` document back to `PENDING`, lowers `verified_document_count` by
    one and raises `pending_document_count` by one, restoring every package counter to
    precisely the value it held before the verification it undoes — `document_count`
    having never moved at all."

    Design: Difficulty/compensating_invariant/package_document_counter_partition_restored_by_revoke
    """
    case, package, documents = setup_package_with_documents(
        package_overrides={"hardship_reason": "DIVORCE"}, verify=False
    )
    for doc_type in ("HARDSHIP_LETTER", "FINANCIAL_WORKSHEET", "BANK_STATEMENT"):
        review_document(documents[doc_type]["id"], "VERIFY")

    before = validate_success(api.get_hardship_package(package["id"], NEG), 200)
    assert_package_counter_partition(before)
    assert before["document_count"] == 4

    review_document(documents["AUTHORIZATION_FORM"]["id"], "VERIFY")
    midpoint = validate_success(api.get_hardship_package(package["id"], NEG), 200)
    assert_package_counter_partition(midpoint)
    assert midpoint["document_count"] == 4

    review_document(documents["AUTHORIZATION_FORM"]["id"], "REVOKE")
    after = validate_success(api.get_hardship_package(package["id"], NEG), 200)
    assert_package_counter_partition(after)
    assert after["document_count"] == 4
    assert (
        after["pending_document_count"],
        after["verified_document_count"],
        after["rejected_document_count"],
    ) == (
        before["pending_document_count"],
        before["verified_document_count"],
        before["rejected_document_count"],
    ), "each bucket returns to exactly its pre-verification value"
    assert_hardship_package(after)

    case_after = validate_success(api.get_case(case["id"], NEG), 200)
    assert case_after["documentation_status"] == "DOC_PENDING"


# ─── The case's two independent dimensions ────────────

def test_revoke_walks_the_documentation_dimension_back_alone(api):
    """PRD §3.2: "Revocation can also walk the documentation dimension backwards: if,
    after the revoke, at least one of the four required kinds no longer has any
    `VERIFIED` document on the package, `documentation_status` falls from `DOC_COMPLETE`
    back to `DOC_PENDING`."
    PRD §3.1: "The two dimensions never gate each other directly."

    Design: Difficulty/non_linear_state_machine/case_documentation_dimension_moves_while_negotiation_dimension_holds
    """
    case, package, documents = setup_accepted_package(
        package_overrides={"hardship_reason": "MEDICAL"}
    )
    assert case["negotiation_status"] == "MARKETED"
    assert case["documentation_status"] == "DOC_COMPLETE"

    revoked = validate_success(
        api.review_document(
            documents["BANK_STATEMENT"]["id"],
            review_document_payload("REVOKE", note="Statement page missing"),
            ANALYST,
        ),
        200,
    )
    assert revoked["status"] == "PENDING"

    case_after = validate_success(api.get_case(case["id"], NEG), 200)
    assert case_after["documentation_status"] == "DOC_PENDING", (
        "the documentation dimension retreats as soon as one required kind is uncovered"
    )
    assert case_after["negotiation_status"] == "MARKETED", (
        "the negotiation dimension is untouched by a document review"
    )


def test_documentation_retreat_leaves_the_package_lifecycle_untouched(api):
    """PRD §3.1: "`documentation_status` begins at `DOC_PENDING` and moves only between
    `DOC_PENDING`, `DOC_COMPLETE` and `DOC_STALE`; it has no terminal value at all."
    PRD §3.2: "`REVOKE` is the deliberate compensating action for a verification: it
    moves a `VERIFIED` document back to `PENDING`, lowers `verified_document_count` by
    one and raises `pending_document_count` by one, restoring every package counter to
    precisely the value it held before the verification it undoes — `document_count`
    having never moved at all."

    Design: Difficulty/non_linear_state_machine/case_documentation_dimension_moves_while_negotiation_dimension_holds
    """
    case, package, documents = setup_accepted_package(
        package_overrides={"hardship_reason": "MEDICAL"}
    )

    review_document(documents["BANK_STATEMENT"]["id"], "REVOKE")

    stored = validate_success(api.get_hardship_package(package["id"], NEG), 200)
    assert stored["status"] == "ACCEPTED", (
        "the package lifecycle does not move when a verification is revoked"
    )
    assert stored["verified_document_count"] == 3
    assert stored["pending_document_count"] == 1
    assert stored["document_count"] == 4
    assert_package_counter_partition(stored)


# ─── The two hardship-score evaluations ───────────────

def test_intake_score_counts_every_filed_required_kind(api):
    """PRD §3.3: "Under the **intake** evaluation performed at submission, a required
    kind qualifies when the package holds at least one document of that kind whose status
    is `PENDING` or `VERIFIED`, and document age is ignored entirely."
    PRD §3.3: "Every submission stamps `hardship_score_intake`. Every servicer decision
    stamps `hardship_score_audit`."

    Design: Difficulty/dual_variant_calc/hardship_score_intake_vs_audit_diverge_on_same_package
    """
    case, package, documents = setup_package_with_documents(
        doc_overrides=STALE_DATED_BANK_STATEMENT
    )
    assert package["verified_document_count"] == 4

    submitted = validate_success(api.submit_hardship_package(package["id"], NEG), 200)

    assert submitted["hardship_score_intake"] == pytest.approx(76.25), (
        "all four required kinds qualify under the intake evaluation"
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["hardship_score_audit"] is None, (
        "the audit score is not computed at submission"
    )


def test_audit_score_drops_the_stale_dated_bank_statement(api):
    """PRD §3.3: "Under the **servicer-audit** evaluation performed at decision time, a
    required kind qualifies only when the package holds at least one document of that
    kind that is `VERIFIED` *and* whose age at that moment — again the elapsed seconds
    since `issued_on` divided by 86,400 and truncated downward — is at most 90 days."
    PRD §3.3: "A successful `ACCEPT` moves the package to `ACCEPTED` and carries the
    case's negotiation dimension from `PACKAGE_REVIEW` to `MARKETED`."

    Design: Difficulty/dual_variant_calc/hardship_score_intake_vs_audit_diverge_on_same_package
    """
    case, package, documents = setup_package_with_documents(
        doc_overrides=STALE_DATED_BANK_STATEMENT
    )
    submitted = validate_success(api.submit_hardship_package(package["id"], NEG), 200)
    assert submitted["hardship_score_intake"] == pytest.approx(76.25)

    # The bank statement is 92 days old at this instant, so it drops out of the
    # audit's documentation-support term while remaining VERIFIED.
    set_clock("2026-08-10T00:00:00Z")
    decided = validate_success(
        api.decide_hardship_package(package["id"], package_decision_payload("ACCEPT"), ANALYST),
        200,
    )

    assert decided["hardship_score_audit"] == pytest.approx(73.75)
    assert decided["hardship_score_intake"] == pytest.approx(76.25), (
        "the intake score stamped at submission is not rewritten by the decision"
    )
    assert decided["status"] == "ACCEPTED"
    assert decided["verified_document_count"] == 4

    documents_after = validate_success(api.list_package_documents(package["id"], NEG), 200)
    bank_statement = [d for d in documents_after if d["doc_type"] == "BANK_STATEMENT"][0]
    assert bank_statement["status"] == "VERIFIED", (
        "the audit excludes the bank statement on age, not on status"
    )

    case_after = validate_success(api.get_case(case["id"], NEG), 200)
    assert case_after["negotiation_status"] == "MARKETED"


def test_audit_score_exactly_at_the_floor_is_accepted(api):
    """PRD §3.3: "An `ACCEPT` requires that audit score to be at least **55.00**; a
    package scoring below that floor cannot be accepted and the attempt is refused with
    `ERR_HARDSHIP_SCORE_BELOW_MINIMUM`. A score of exactly 55.00 passes."

    Design: Corner/calculations/hardship_score_exactly_at_minimum_is_accepted
    """
    case, package, _ = setup_submitted_package(
        package_overrides={
            "hardship_reason": "OTHER",
            "monthly_income_cents": 600_000,
            "monthly_expenses_cents": 1_100_000,
            "liquid_assets_cents": 3_300_000,
        }
    )
    assert package["hardship_score_intake"] == pytest.approx(55.00)

    decided = validate_success(
        api.decide_hardship_package(package["id"], package_decision_payload("ACCEPT"), ANALYST),
        200,
    )

    assert decided["hardship_score_audit"] == pytest.approx(55.00)
    assert decided["status"] == "ACCEPTED"

    case_after = validate_success(api.get_case(case["id"], NEG), 200)
    assert case_after["negotiation_status"] == "MARKETED"


def test_audit_score_just_below_the_floor_blocks_acceptance(api):
    """PRD §3.3: "An `ACCEPT` requires that audit score to be at least **55.00**; a
    package scoring below that floor cannot be accepted and the attempt is refused with
    `ERR_HARDSHIP_SCORE_BELOW_MINIMUM`. A score of exactly 55.00 passes."
    PRD §3.3: "The audit score is computed and stamped into `hardship_score_audit`
    **before** the outcome is evaluated, so it is persisted even when the decision that
    follows fails."

    Design: Corner/calculations/hardship_score_just_below_minimum_is_rejected
    """
    case, package, _ = setup_submitted_package(
        package_overrides={
            "hardship_reason": "OTHER",
            "monthly_income_cents": 600_000,
            "monthly_expenses_cents": 1_100_000,
            "liquid_assets_cents": 3_400_000,
        }
    )

    validate_error(
        api.decide_hardship_package(package["id"], package_decision_payload("ACCEPT"), ANALYST),
        ApiErrorId.ERR_HARDSHIP_SCORE_BELOW_MINIMUM.value,
    )

    stored = validate_success(api.get_hardship_package(package["id"], NEG), 200)
    assert stored["hardship_score_audit"] == pytest.approx(54.70), (
        "the audit score is stamped even though the ACCEPT that followed failed"
    )
    assert stored["status"] == "SUBMITTED"

    case_after = validate_success(api.get_case(case["id"], NEG), 200)
    assert case_after["negotiation_status"] == "PACKAGE_REVIEW"
