"""Peer review: file lifecycle, voting guards, quorum, outcome match, OCC, and the
fork-join finalize branches.

Covers difficulty-design rules `non_linear_state_machine` (fork-join deny),
`priority_pair_validation_conflict` (cast-vote referential beats safety), plus
corner-design `state_machines`, `calculations`, `cross_cutting_complexity_layers`,
and `errors` instances on the committee path.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error,
    make_system_admin_headers, make_specialist_headers,
    make_medical_director_headers, make_peer_reviewer_headers,
    make_enrollment_coordinator_headers, make_compliance_officer_headers,
    ApiErrorId,
    create_org_payload, create_provider_payload,
    create_peer_reviewer_payload, cast_vote_payload, finalize_payload,
    create_enrollment_payload,
)
import test_helpers.fixtures as fx

ADMIN = make_system_admin_headers("admin-1")
SPEC = make_specialist_headers("spec-1")
# The initiating specialist's opaque X-User-ID ("spec-1") acting in a *voting*
# capacity. PRD §2.1: a reviewer registers "the `X-User-ID` value that this
# reviewer, acting as `MedicalDirector` or `PeerReviewer`, will present"; PRD §2.6
# evaluates role authorization (step 2) before the segregation/referential checks
# (step 8), so the segregation-of-duties anchor is only reachable when spec-1 casts
# under a voting role, not as a CredentialingSpecialist (which the cast-vote
# endpoint does not authorize at all -> ERR_INSUFFICIENT_PERMISSIONS).
SPEC_AS_REVIEWER = make_peer_reviewer_headers("spec-1")
MD = make_medical_director_headers("md-1")
REV2 = make_peer_reviewer_headers("rev-2")
REV3 = make_peer_reviewer_headers("rev-3")
ENR = make_enrollment_coordinator_headers("enr-1")
COMP = make_compliance_officer_headers("comp-1")


def _file_version(file_id):
    f = validate_success(api_client.get_credentialing_file(file_id, MD), 200)
    return f["version"]


# =========================================================================
# open-review preconditions
# =========================================================================
def test_open_review_already_under_review_returns_not_assembling():
    """PRD §3.5: "This is permitted only when the file is currently `ASSEMBLING`
    (otherwise `ERR_FILE_NOT_ASSEMBLING`)".

    Design: Corner/state_machines/open_review_already_under_review_returns_not_assembling
    """
    ctx = fx.setup_file_under_review()  # already opened to UNDER_REVIEW
    resp = api_client.open_review(ctx["file"]["id"], MD)
    validate_error(resp, ApiErrorId.ERR_FILE_NOT_ASSEMBLING.value)


def test_provider_excluded_blocks_open_review():
    """PRD §3.5: "and when the provider's `credentialing_status` is not
    `EXCLUDED` (otherwise `ERR_PROVIDER_EXCLUDED`, HTTP 403). A provider with any
    open OIG/SAM hit — that is, a `sanction_score` above zero — is in the
    `EXCLUDED` posture and cannot have a review opened."

    Design: Corner/state_machines/provider_excluded_blocks_open_review
    """
    org_id, provider, item = fx.setup_provider_ready_for_review()
    source = fx.create_sanctions_source(org_id, source_code="SAM_EXCLUSIONS", severity_weight=5)
    validate_success(api_client.create_sanctions_screening(
        provider["id"],
        {"sanctions_source_id": source["id"], "result": "HIT"},
        COMP), 201)
    file = validate_success(api_client.create_credentialing_file(provider["id"], SPEC), 201)
    resp = api_client.open_review(file["id"], MD)
    validate_error(resp, ApiErrorId.ERR_PROVIDER_EXCLUDED.value)


# =========================================================================
# Voting guards
# =========================================================================
def test_duplicate_vote_returns_error():
    """PRD §3.5: "A reviewer may cast at most one vote on any given file; a second
    cast by the same reviewer on the same file is rejected with
    `ERR_DUPLICATE_VOTE` (HTTP 409)."

    Design: Corner/validations/duplicate_vote_returns_error
    """
    ctx = fx.setup_file_under_review()
    validate_success(api_client.cast_vote(
        ctx["file"]["id"], cast_vote_payload(ctx["rev2"]["id"], "YES"), REV2), 201)
    resp = api_client.cast_vote(
        ctx["file"]["id"], cast_vote_payload(ctx["rev2"]["id"], "NO"), REV2)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_VOTE.value)


def test_segregation_of_duties_blocks_initiating_specialist_vote():
    """PRD §3.5: "Segregation of duties forbids the casting user from being the
    provider's `initiated_by_user_id`: the specialist who submitted the
    application may not vote on that provider's review, and a violating cast is
    rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/errors/error_segregation_of_duties_isolated
    """
    org_id, provider, item = fx.setup_provider_ready_for_review()
    # A SAME-ORG reviewer registered under the initiating specialist's user_id.
    conflicted = fx.create_reviewer(org_id, "spec-1", full_name="Conflicted reviewer")
    file = validate_success(api_client.create_credentialing_file(provider["id"], SPEC), 201)
    validate_success(api_client.open_review(file["id"], MD), 200)
    # spec-1 (the initiated_by_user_id) attempts to cast a vote — acting as a
    # PeerReviewer so role authorization (PRD §2.6 step 2) is satisfied — using the
    # same-org reviewer, so the segregation-of-duties anchor is the deciding check.
    resp = api_client.cast_vote(file["id"], cast_vote_payload(conflicted["id"], "YES"), SPEC_AS_REVIEWER)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_cast_vote_referential_beats_segregation_of_duties():
    """PRD §2.6: "When several checks could reject the same request, they are
    evaluated in a fixed precedence so that the returned error is deterministic."
    PRD §3.5: "The reviewer named by `reviewer_id` must belong to the same
    organization as the file's provider; otherwise the cast is rejected with
    `ERR_REVIEWER_ORG_MISMATCH` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/cast_vote_referential_beats_safety
    """
    org1 = validate_success(api_client.create_org(create_org_payload(name="CVO-1"), ADMIN), 201)
    # The cross-org reviewer lives in a *different* org under user_id 'spec-1'.
    org2 = validate_success(api_client.create_org(create_org_payload(name="CVO-2"), ADMIN), 201)
    org_id, provider, item = fx.setup_provider_ready_for_review(org_id=org1["id"])
    cross_reviewer = fx.create_reviewer(org2["id"], "spec-1", full_name="Cross-org reviewer")
    file = validate_success(api_client.create_credentialing_file(provider["id"], SPEC), 201)
    validate_success(api_client.open_review(file["id"], MD), 200)
    # spec-1 (segregation violation, casting as a PeerReviewer so role auth passes)
    # using an org-2 reviewer (referential violation): the higher-priority
    # referential error must win.
    resp = api_client.cast_vote(file["id"], cast_vote_payload(cross_reviewer["id"], "YES"), SPEC_AS_REVIEWER)
    validate_error(resp, ApiErrorId.ERR_REVIEWER_ORG_MISMATCH.value)


# =========================================================================
# Finalize: quorum, outcome match, OCC, branches
# =========================================================================
def test_quorum_not_met_with_two_votes():
    """PRD §3.5: "the file must have at least three peer-review votes whose ballot
    is `YES` or `NO` — abstentions do not count toward quorum — or the finalize
    is rejected with `ERR_QUORUM_NOT_MET` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/quorum_count_boundary_on_finalize
    """
    ctx = fx.setup_file_under_review()
    file_id = ctx["file"]["id"]
    validate_success(api_client.cast_vote(file_id, cast_vote_payload(ctx["rev2"]["id"], "YES"), REV2), 201)
    validate_success(api_client.cast_vote(file_id, cast_vote_payload(ctx["chair"]["id"], "YES"), MD), 201)
    version = _file_version(file_id)
    resp = api_client.finalize_file(file_id, finalize_payload("APPROVE", version), MD)
    validate_error(resp, ApiErrorId.ERR_QUORUM_NOT_MET.value)


def test_quorum_boundary_third_vote_satisfies():
    """PRD §3.5: "the file must have at least three peer-review votes whose ballot
    is `YES` or `NO` — abstentions do not count toward quorum — or the finalize
    is rejected with `ERR_QUORUM_NOT_MET` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/quorum_count_boundary_on_finalize
    """
    ctx = fx.setup_file_under_review()
    file_id = ctx["file"]["id"]
    # The third (chair) vote pushes the non-ABSTAIN count to exactly 3.
    fx.cast_three_yes_votes(file_id, ctx["chair"], ctx["rev2"], ctx["rev3"])
    version = _file_version(file_id)
    finalized = validate_success(api_client.finalize_file(
        file_id, finalize_payload("APPROVE", version), MD), 200)
    assert finalized["review_status"] == "APPROVED"


def test_finalize_outcome_mismatch_returns_error():
    """PRD §3.5: "The supplied decision must match the committee outcome: an
    `APPROVE` requires the tally to resolve to a `YES` outcome, and a `DENY`
    requires it to resolve to a `NO` outcome; a decision that contradicts the
    outcome is rejected with `ERR_REVIEW_OUTCOME_MISMATCH` (HTTP 409)."

    Design: Corner/calculations/finalize_outcome_mismatch_returns_error
    """
    ctx = fx.setup_file_under_review()
    file_id = ctx["file"]["id"]
    fx.cast_three_yes_votes(file_id, ctx["chair"], ctx["rev2"], ctx["rev3"])  # YES outcome
    version = _file_version(file_id)
    resp = api_client.finalize_file(file_id, finalize_payload("DENY", version), MD)
    validate_error(resp, ApiErrorId.ERR_REVIEW_OUTCOME_MISMATCH.value)


def test_finalize_stale_version_returns_stale_version():
    """PRD §2.10: "Before any quorum, outcome, or state check runs, the server
    compares `expected_credentialing_file_version` against the file's current
    `version`. If they do not match, the finalize is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.10: "each cast vote recomputes the weighted tally and writes the new
    `tally_yes` and `tally_no` back onto the file, which increments the file's
    `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_finalize_stale_version_conflict
    """
    ctx = fx.setup_file_under_review()
    file_id = ctx["file"]["id"]
    validate_success(api_client.cast_vote(file_id, cast_vote_payload(ctx["rev2"]["id"], "YES"), REV2), 201)
    validate_success(api_client.cast_vote(file_id, cast_vote_payload(ctx["rev3"]["id"], "YES"), REV3), 201)
    stale_version = _file_version(file_id)  # captured after the 2nd vote
    # A third vote advances the file's version, making stale_version out of date.
    validate_success(api_client.cast_vote(file_id, cast_vote_payload(ctx["chair"]["id"], "YES"), MD), 201)
    resp = api_client.finalize_file(file_id, finalize_payload("APPROVE", stale_version), MD)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_finalize_deny_branch_demotes_provider_conditional():
    """PRD §3.5: "On a `DENY`, the file moves to `DENIED`, the provider's
    `credentialing_status` becomes `CONDITIONAL`, and every payer enrollment for
    that provider currently in `REQUESTED` or `SUBMITTED` is cascaded to
    `REJECTED`."

    Design: Difficulty/non_linear_state_machine/credentialing_file_fork_join_deny_branch
    """
    ctx = fx.setup_file_under_review()
    file_id = ctx["file"]["id"]
    # Three NO votes -> NO outcome.
    validate_success(api_client.cast_vote(file_id, cast_vote_payload(ctx["rev2"]["id"], "NO"), REV2), 201)
    validate_success(api_client.cast_vote(file_id, cast_vote_payload(ctx["rev3"]["id"], "NO"), REV3), 201)
    validate_success(api_client.cast_vote(file_id, cast_vote_payload(ctx["chair"]["id"], "NO"), MD), 201)
    version = _file_version(file_id)
    finalized = validate_success(api_client.finalize_file(
        file_id, finalize_payload("DENY", version, decision_reason="insufficient"), MD), 200)
    assert finalized["review_status"] == "DENIED"
    provider = validate_success(api_client.get_provider(ctx["provider"]["id"], SPEC), 200)
    assert provider["credentialing_status"] == "CONDITIONAL"


def test_finalize_approve_cascade_clears_provider_immediately():
    """PRD §3.5: "On an `APPROVE`, the file moves to `APPROVED`, and the provider
    is cleared: the provider's `credentialing_status` becomes `CLEARED`, its
    re-credentialing loop advances to `CURRENT`".

    Design: Corner/consistency_model/finalize_approve_cascade_visible_same_request
    """
    ctx = fx.setup_file_under_review()
    file_id = ctx["file"]["id"]
    fx.cast_three_yes_votes(file_id, ctx["chair"], ctx["rev2"], ctx["rev3"])
    version = _file_version(file_id)
    validate_success(api_client.finalize_file(file_id, finalize_payload("APPROVE", version), MD), 200)
    provider = validate_success(api_client.get_provider(ctx["provider"]["id"], SPEC), 200)
    assert provider["credentialing_status"] == "CLEARED"
    assert provider["recred_state"] == "CURRENT"
