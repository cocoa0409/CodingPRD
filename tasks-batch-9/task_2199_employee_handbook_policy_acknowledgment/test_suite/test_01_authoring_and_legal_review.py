"""Authoring, the jurisdiction legal review cycle and version approval."""
from test_helpers import (
    ApiErrorId,
    add_addendum,
    api_client,
    approve_addendum,
    assert_same_instant,
    decide_review_as,
    drive_version_to_in_legal_review,
    make_admin_headers,
    make_author_headers,
    mint_version,
    new_document,
    new_jurisdiction,
    new_reviewer,
    refresh_addendum,
    refresh_review,
    refresh_reviewer,
    refresh_version,
    request_review,
    set_clock,
    start_review_as,
    submit_for_review,
    validate_error,
    validate_success,
)


def _version_in_changes_requested(min_legal_review_days=10):
    """CA jurisdiction, one reviewer, a version driven to IN_LEGAL_REVIEW whose
    single CA review has just come back with REQUEST_CHANGES."""
    j = new_jurisdiction(min_legal_review_days=min_legal_review_days)
    r = new_reviewer(j["id"])
    d = new_document()
    v = mint_version(d, [j["id"]])
    v, addenda, reviews = drive_version_to_in_legal_review(v, [(j["id"], r["id"])])
    review = reviews[j["id"]]
    start_review_as(review["id"], r["id"])
    decide_review_as(review["id"], r["id"], "REQUEST_CHANGES", comment="Fix section 2.")
    return j, r, d, v, addenda[j["id"]], review


def test_re_request_returns_review_to_requested_with_incremented_round_no():
    """PRD §3.3: "The cycle closes when the author re-raises a review that asked
    for changes, supplying a fresh `due_at`. That moves the review
    `CHANGES_REQUESTED → REQUESTED`, requires the owning version to be back in
    `DRAFT`, increases `round_no` by 1, clears `decided_at` to null, restamps
    `assigned_at` from the logical clock, adopts the supplied `due_at`, and
    increments the reviewer's `open_review_count` by 1."

    Design: Difficulty/non_linear_state_machine/legal_review_revisits_requested_with_monotonic_round_no
    """
    j, r, d, v, addendum, review = _version_in_changes_requested()

    from test_helpers import make_author_headers

    data = validate_success(
        api_client.re_request_legal_review(
            review["id"], {"due_at": "2026-08-25T00:00:00Z"}, make_author_headers()
        )
    )
    assert data["status"] == "REQUESTED", (
        f"CHANGES_REQUESTED -> REQUESTED expected, got {data['status']}"
    )
    assert data["round_no"] == 2, f"round_no must reach 2, got {data['round_no']}"
    assert data["decided_at"] is None, (
        f"decided_at must be cleared on the revisit, got {data['decided_at']}"
    )
    assert_same_instant(data["due_at"], "2026-08-25T00:00:00Z", "due_at")

    version = refresh_version(v["id"])
    assert version["status"] == "DRAFT", (
        f"version must sit in DRAFT for the revisit, got {version['status']}"
    )
    assert version["revision_round"] == 1, (
        f"revision_round must be 1 after one revert, got {version['revision_round']}"
    )
    assert refresh_addendum(addendum["id"])["status"] == "DRAFT"


def test_re_request_restamps_assigned_at_and_reopens_reviewer_capacity():
    """PRD §3.3: "The cycle closes when the author re-raises a review that asked
    for changes, supplying a fresh `due_at`. That moves the review
    `CHANGES_REQUESTED → REQUESTED`, requires the owning version to be back in
    `DRAFT`, increases `round_no` by 1, clears `decided_at` to null, restamps
    `assigned_at` from the logical clock, adopts the supplied `due_at`, and
    increments the reviewer's `open_review_count` by 1."

    Design: Difficulty/non_linear_state_machine/legal_review_revisits_requested_with_monotonic_round_no
    """
    from test_helpers import make_author_headers

    j, r, d, v, addendum, review = _version_in_changes_requested()
    assert refresh_reviewer(r["id"])["open_review_count"] == 0, (
        "a CHANGES_REQUESTED review must not occupy reviewer capacity"
    )

    set_clock("2026-08-10T00:00:00Z")
    data = validate_success(
        api_client.re_request_legal_review(
            review["id"], {"due_at": "2026-08-25T00:00:00Z"}, make_author_headers()
        )
    )
    assert_same_instant(data["assigned_at"], "2026-08-10T00:00:00Z", "assigned_at")
    assert data["round_no"] == 2
    assert refresh_reviewer(r["id"])["open_review_count"] == 1, (
        "re-raising the review must re-occupy one unit of reviewer capacity"
    )


def test_request_changes_withdraws_siblings_frees_counters_and_unapproves_addenda():
    """PRD §3.3: "Hop 1: the version moves `IN_LEGAL_REVIEW → DRAFT` and its
    `revision_round` increases by 1. Hop 2: because the version has left review,
    every **sibling** review on that version whose `status` is `REQUESTED` or
    `IN_PROGRESS` is set to `WITHDRAWN` with `decided_at` stamped from the
    logical clock ... Hop 3: because those reviews became `WITHDRAWN`, each
    affected reviewer's `open_review_count` is decremented by 1. Hop 4: because
    at least one reviewer's open count changed, every addendum on that version
    whose `status` is `APPROVED` is reset to `DRAFT` with
    `approved_by_reviewer_id` cleared to null."

    Design: Difficulty/transitive_cascade/request_changes_unwinds_version_siblings_reviewer_counter_and_addenda
    """
    ca = new_jurisdiction()
    ny = new_jurisdiction()
    r_ca = new_reviewer(ca["id"])
    r_ny = new_reviewer(ny["id"])
    document = new_document()
    version = mint_version(document, [ca["id"], ny["id"]])
    version, addenda, reviews = drive_version_to_in_legal_review(
        version, [(ca["id"], r_ca["id"]), (ny["id"], r_ny["id"])]
    )
    assert refresh_reviewer(r_ca["id"])["open_review_count"] == 1
    assert refresh_reviewer(r_ny["id"])["open_review_count"] == 1

    start_review_as(reviews[ca["id"]]["id"], r_ca["id"])
    decided = decide_review_as(
        reviews[ca["id"]]["id"], r_ca["id"], "REQUEST_CHANGES", comment="Rework §2."
    )
    assert decided["status"] == "CHANGES_REQUESTED", (
        f"deciding review must land in CHANGES_REQUESTED, got {decided['status']}"
    )

    reverted = refresh_version(version["id"])
    assert reverted["status"] == "DRAFT", (
        f"hop 1 must revert the version to DRAFT, got {reverted['status']}"
    )
    assert reverted["revision_round"] == 1, (
        f"hop 1 must raise revision_round to 1, got {reverted['revision_round']}"
    )

    sibling = refresh_review(reviews[ny["id"]]["id"])
    assert sibling["status"] == "WITHDRAWN", (
        f"hop 2 must withdraw the REQUESTED sibling review, got {sibling['status']}"
    )
    assert sibling["decided_at"] is not None, (
        "hop 2 must stamp decided_at on the withdrawn sibling"
    )

    assert refresh_reviewer(r_ca["id"])["open_review_count"] == 0, (
        "the deciding reviewer's open_review_count must return to 0"
    )
    assert refresh_reviewer(r_ny["id"])["open_review_count"] == 0, (
        "hop 3 must release the withdrawn sibling reviewer's capacity"
    )

    for jurisdiction in (ca, ny):
        addendum = refresh_addendum(addenda[jurisdiction["id"]]["id"])
        assert addendum["status"] == "DRAFT", (
            f"hop 4 must reset the APPROVED addendum to DRAFT, got {addendum['status']}"
        )
        assert addendum["approved_by_reviewer_id"] is None, (
            "hop 4 must clear approved_by_reviewer_id on the reset addendum"
        )


def test_request_changes_hop_four_touches_only_the_approved_addenda():
    """PRD §3.3: "Hop 4: because at least one reviewer's open count changed,
    every addendum on that version whose `status` is `APPROVED` is reset to
    `DRAFT` with `approved_by_reviewer_id` cleared to null." PRD §2: "Every
    mutating hop that touches a versioned row refreshes that row's `updated_at`
    and increments its `version` by 1."

    Design: Difficulty/transitive_cascade/request_changes_unwinds_version_siblings_reviewer_counter_and_addenda
    """
    ca = new_jurisdiction()
    ny = new_jurisdiction()
    tx = new_jurisdiction()
    r_ca = new_reviewer(ca["id"])
    r_ny = new_reviewer(ny["id"])
    r_tx = new_reviewer(tx["id"])
    document = new_document()
    version = mint_version(document, [ca["id"], ny["id"], tx["id"]])

    approved = {}
    for jurisdiction, reviewer in ((ca, r_ca), (ny, r_ny)):
        addendum = add_addendum(version["id"], jurisdiction["id"])
        approved[jurisdiction["id"]] = approve_addendum(addendum["id"], reviewer["id"])
    tx_addendum = add_addendum(version["id"], tx["id"])
    assert tx_addendum["status"] == "DRAFT"
    assert tx_addendum["version"] == 1

    reviews = {}
    for jurisdiction, reviewer in ((ca, r_ca), (ny, r_ny), (tx, r_tx)):
        reviews[jurisdiction["id"]] = request_review(
            version["id"], jurisdiction["id"], reviewer["id"]
        )
    submit_for_review(version["id"])

    start_review_as(reviews[ca["id"]]["id"], r_ca["id"])
    decide_review_as(
        reviews[ca["id"]]["id"], r_ca["id"], "REQUEST_CHANGES", comment="Needs rework."
    )

    for jurisdiction in (ca, ny):
        addendum = refresh_addendum(approved[jurisdiction["id"]]["id"])
        assert addendum["status"] == "DRAFT", (
            f"hop 4 must reset an APPROVED addendum, got {addendum['status']}"
        )
        assert addendum["approved_by_reviewer_id"] is None
        assert addendum["version"] == 3, (
            "an addendum created, approved and then reset must be at version 3, "
            f"got {addendum['version']}"
        )

    untouched = refresh_addendum(tx_addendum["id"])
    assert untouched["status"] == "DRAFT", (
        f"an already-DRAFT addendum must stay DRAFT, got {untouched['status']}"
    )
    assert untouched["version"] == 1, (
        "hop 4 must not touch an addendum that was never APPROVED, so its version "
        f"must remain 1, got {untouched['version']}"
    )

    for jurisdiction in (ny, tx):
        assert refresh_review(reviews[jurisdiction["id"]]["id"])["status"] == "WITHDRAWN"
    for reviewer in (r_ca, r_ny, r_tx):
        assert refresh_reviewer(reviewer["id"])["open_review_count"] == 0, (
            "hop 3 must release every affected reviewer's capacity"
        )
    assert refresh_version(version["id"])["revision_round"] == 1


def _in_legal_review_with_draft_addendum():
    """A version in IN_LEGAL_REVIEW whose single required jurisdiction has a
    REQUESTED review and an addendum still parked in DRAFT."""
    jurisdiction = new_jurisdiction()
    reviewer = new_reviewer(jurisdiction["id"])
    document = new_document()
    version = mint_version(document, [jurisdiction["id"]])
    addendum = add_addendum(version["id"], jurisdiction["id"])
    review = request_review(version["id"], jurisdiction["id"], reviewer["id"])
    version = submit_for_review(version["id"])
    assert version["status"] == "IN_LEGAL_REVIEW"
    return jurisdiction, reviewer, document, version, addendum, review


def test_incomplete_legal_review_is_reported_before_the_unapproved_addendum():
    """PRD §3.4: "Only after the review sweep passes does the addendum sweep run
    ... The ordering matters — a version missing both an approved review and an
    approved addendum for the same state reports the incomplete review, not the
    unapproved addendum."

    Design: Difficulty/priority_pair_validation_conflict/legal_review_completeness_outranks_addendum_approval
    """
    jurisdiction, reviewer, document, version, addendum, review = (
        _in_legal_review_with_draft_addendum()
    )
    started = start_review_as(review["id"], reviewer["id"])
    assert started["status"] == "IN_PROGRESS"
    assert refresh_addendum(addendum["id"])["status"] == "DRAFT"

    validate_error(
        api_client.approve_policy_version(version["id"], make_admin_headers()),
        ApiErrorId.ERR_LEGAL_REVIEW_INCOMPLETE,
    )

    unchanged = refresh_version(version["id"])
    assert unchanged["status"] == "IN_LEGAL_REVIEW", (
        f"a refused approval must not move the version, got {unchanged['status']}"
    )
    assert unchanged["approved_at"] is None, (
        f"approved_at must stay null, got {unchanged['approved_at']}"
    )


def test_addendum_approval_is_reported_once_the_review_sweep_passes():
    """PRD §3.4: "for every jurisdiction named in `required_jurisdiction_ids`,
    there must be a review on this version for that jurisdiction whose `status`
    is `APPROVED`; a gap here is refused with `ERR_LEGAL_REVIEW_INCOMPLETE`
    (409). Only after the review sweep passes does the addendum sweep run: for
    every jurisdiction in `required_jurisdiction_ids` there must be an addendum
    on this version whose `status` is `APPROVED`, and a gap is refused with
    `ERR_ADDENDUM_NOT_APPROVED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/legal_review_completeness_outranks_addendum_approval
    """
    jurisdiction, reviewer, document, version, addendum, review = (
        _in_legal_review_with_draft_addendum()
    )
    start_review_as(review["id"], reviewer["id"])
    decided = decide_review_as(review["id"], reviewer["id"], "APPROVE")
    assert decided["status"] == "APPROVED"
    assert refresh_addendum(addendum["id"])["status"] == "DRAFT"

    validate_error(
        api_client.approve_policy_version(version["id"], make_admin_headers()),
        ApiErrorId.ERR_ADDENDUM_NOT_APPROVED,
    )

    unchanged = refresh_version(version["id"])
    assert unchanged["status"] == "IN_LEGAL_REVIEW", (
        f"a refused approval must not move the version, got {unchanged['status']}"
    )
    assert unchanged["approved_at"] is None

    approve_addendum(addendum["id"], reviewer["id"])
    approved = validate_success(
        api_client.approve_policy_version(version["id"], make_admin_headers())
    )
    assert approved["status"] == "APPROVED", (
        "once both sweeps pass the version must reach APPROVED, got "
        f"{approved['status']}"
    )
    assert approved["pinned_addendum_ids"] == [addendum["id"]], (
        "approval must pin the APPROVED addendum, got "
        f"{approved['pinned_addendum_ids']}"
    )
