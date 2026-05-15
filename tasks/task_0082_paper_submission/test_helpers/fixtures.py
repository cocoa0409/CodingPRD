"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() from the framework (lenient validator) so setup
failures produce clear "Setup failed" errors instead of confusing
assertion failures.

All fixtures honor PRD §2.1 identity rules:

- Entity-backed role headers (Author, EditorInChief, SectionEditor,
  AssociateEditor, Reviewer) are minted per-instance via
  make_<role>_headers(entity['id']) — never the shared TEST_USERS
  fallback constants, which would fail every ownership check and
  cascade 'Setup failed' into every downstream test.

- PlatformAdmin is opaque, so TEST_USERS['platform_admin_headers'] is
  canonical.

Fixture tiers (see prd-bench-unit-test-generator/SKILL.md):
  Tier 1 — single-entity state progression (DRAFT → SUBMITTED, etc.)
  Tier 2 — entity hierarchy assembly (author + reviewers + editors + manuscript)
  Tier 3 — full-lifecycle shortcuts (drive to UNDER_REVIEW, ACCEPTED, IN_PRODUCTION)
  Tier 4 — accumulation / threshold targeting (reviewer at load cap, editor window open)
  Tier 5 — terminal / finalization paths (PUBLISHED, RETRACTED)
"""
from __future__ import annotations
import datetime as _dt
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    EDITOR_ASSIGNMENT_WINDOW_DAYS,
    INVITATION_RESPONSE_DAYS,
    MAJOR_REVISION_DAYS,
    MINOR_REVISION_DAYS,
    REVIEW_DEADLINE_DAYS,
    SECONDS_PER_DAY,
    TEST_DEFAULTS,
)
from .factories import (
    assign_associate_payload,
    assign_section_editor_payload,
    clock_advance_payload,
    complete_review_patch_payload,
    create_author_payload,
    create_decision_payload,
    create_editor_payload,
    create_invitation_payload,
    create_manuscript_payload,
    create_publication_payload,
    create_reviewer_payload,
    desk_reject_payload,
    doi_mint_event_payload,
    finalize_decision_payload,
    orcid_verified_event_payload,
    plagiarism_result_event_payload,
    reinvite_reviewers_payload,
    submit_revision_payload,
)
from .test_users import (
    TEST_USERS,
    make_associate_editor_headers,
    make_author_headers,
    make_editor_in_chief_headers,
    make_reviewer_headers,
    make_section_editor_headers,
)


PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Time helpers — the platform exposes /_clock/advance which accepts a `to`
# instant (PRD §3.8: "moves the server's notion of 'now' forward to that
# value"). Tests advance the clock by reading the current server time off
# the most-recently-returned timestamp and adding seconds/days.
# ---------------------------------------------------------------------------
def _parse_iso(ts: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _format_iso(t: _dt.datetime) -> str:
    # PRD §2.4: ISO 8601 UTC, millisecond precision, Z-suffix
    return t.astimezone(_dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def advance_clock_to(to_iso: str) -> None:
    """PRD §3.8: '/_clock/advance ... accepts a `to` instant and moves the
    server's notion of "now" forward to that value.'"""
    res = api_client.advance_clock(
        clock_advance_payload(to_iso=to_iso), PLATFORM_ADMIN,
    )
    get_success_data(res)


def advance_clock_by_seconds(base_iso: str, seconds: int) -> str:
    """Advance to base_iso + seconds; return the new ISO string."""
    new_ts = _parse_iso(base_iso) + _dt.timedelta(seconds=seconds)
    new_iso = _format_iso(new_ts)
    advance_clock_to(new_iso)
    return new_iso


def advance_clock_by_days(base_iso: str, days: int) -> str:
    return advance_clock_by_seconds(base_iso, days * SECONDS_PER_DAY)


def iso_offset(anchor_iso: str, seconds: int) -> str:
    return _format_iso(_parse_iso(anchor_iso) + _dt.timedelta(seconds=seconds))


# ---------------------------------------------------------------------------
# Tier 1: State Progression — single-entity walk to a target state
# ---------------------------------------------------------------------------
def register_author(*, orcid_id: Optional[str] = None,
                    institution: Optional[str] = None,
                    recent_collaborator_ids: Optional[List[str]] = None,
                    verify_orcid: bool = True) -> Dict[str, Any]:
    """Register an Author and (optionally) flip orcid_verified=true.

    PRD §3.1: 'A freshly registered author always has orcid_verified set
    to false ... when the supplied orcid_id matches the stored value the
    system flips orcid_verified to true.'
    """
    payload = create_author_payload()
    if orcid_id is not None:
        payload["orcid_id"] = orcid_id
    elif verify_orcid:
        # We need an orcid_id to verify. Generate one.
        from .factories import _unique_orcid
        payload["orcid_id"] = _unique_orcid()
    if institution is not None:
        payload["institution"] = institution
    if recent_collaborator_ids is not None:
        payload["recent_collaborator_ids"] = list(recent_collaborator_ids)
    res = api_client.create_author(payload, PLATFORM_ADMIN)
    author = get_success_data(res)
    if verify_orcid and author.get("orcid_id"):
        ev_res = api_client.orcid_verified_event(
            orcid_verified_event_payload(
                author_id=author["id"], orcid_id=author["orcid_id"],
            ),
            PLATFORM_ADMIN,
        )
        author = get_success_data(ev_res)
    return author


def register_reviewer(*, expertise_tags: Optional[List[str]] = None,
                      institution: Optional[str] = None,
                      recent_collaborator_ids: Optional[List[str]] = None,
                      ) -> Dict[str, Any]:
    """Register a Reviewer in the pool."""
    payload = create_reviewer_payload()
    if expertise_tags is not None:
        payload["expertise_tags"] = list(expertise_tags)
    if institution is not None:
        payload["institution"] = institution
    if recent_collaborator_ids is not None:
        payload["recent_collaborator_ids"] = list(recent_collaborator_ids)
    res = api_client.create_reviewer(payload, PLATFORM_ADMIN)
    return get_success_data(res)


def register_editor(role: str, *,
                    topic_tags: Optional[List[str]] = None,
                    institution: Optional[str] = None,
                    recent_collaborator_ids: Optional[List[str]] = None,
                    ) -> Dict[str, Any]:
    """Register an Editor with the requested seat (EDITOR_IN_CHIEF,
    SECTION_EDITOR, or ASSOCIATE_EDITOR)."""
    payload = create_editor_payload(role=role, topic_tags=topic_tags)
    if institution is not None:
        payload["institution"] = institution
    if recent_collaborator_ids is not None:
        payload["recent_collaborator_ids"] = list(recent_collaborator_ids)
    res = api_client.create_editor(payload, PLATFORM_ADMIN)
    return get_success_data(res)


def create_manuscript_in_draft(author: Dict[str, Any],
                               *, co_author_ids: Optional[List[str]] = None,
                               topic_tag: Optional[str] = None,
                               suggested_reviewer_ids: Optional[List[str]] = None,
                               excluded_reviewer_ids: Optional[List[str]] = None,
                               **payload_overrides: Any,
                               ) -> Dict[str, Any]:
    """Create a Manuscript in DRAFT. The caller's headers MUST match
    author['id'] (Author identity per PRD §2.1)."""
    payload = create_manuscript_payload(
        corresponding_author_id=author["id"], **payload_overrides,
    )
    if co_author_ids is not None:
        payload["co_author_ids"] = list(co_author_ids)
    if topic_tag is not None:
        payload["topic_tag"] = topic_tag
    if suggested_reviewer_ids is not None:
        payload["suggested_reviewer_ids"] = list(suggested_reviewer_ids)
    if excluded_reviewer_ids is not None:
        payload["excluded_reviewer_ids"] = list(excluded_reviewer_ids)
    res = api_client.create_manuscript(
        payload, make_author_headers(author["id"]),
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 3: Lifecycle shortcuts — drive Manuscript through key states
# ---------------------------------------------------------------------------
def submit_manuscript_to_submitted(author: Dict[str, Any],
                                   manuscript: Dict[str, Any],
                                   *, plagiarism_similarity: float = 5.0,
                                   ) -> Dict[str, Any]:
    """Submit a DRAFT manuscript with empty co_author_ids and run a PASS
    plagiarism check. Returns the manuscript in SUBMITTED state.

    PRD §3.2 'When co_author_ids is empty, the manuscript transitions
    directly from DRAFT to SUBMITTED, a plagiarism check is requested ...'.
    """
    res = api_client.submit_manuscript(
        manuscript["id"], make_author_headers(author["id"]),
    )
    submitted = get_success_data(res)
    # Ingest plagiarism result so subsequent assign-associate can pass.
    plag_res = api_client.plagiarism_result_event(
        plagiarism_result_event_payload(
            manuscript_id=manuscript["id"],
            similarity_percent=plagiarism_similarity,
        ),
        PLATFORM_ADMIN,
    )
    get_success_data(plag_res)
    return submitted


def setup_submitted_manuscript(*, co_author_ids: Optional[List[str]] = None,
                               topic_tag: Optional[str] = None,
                               plagiarism_similarity: float = 5.0,
                               author_kwargs: Optional[dict] = None,
                               manuscript_overrides: Optional[dict] = None,
                               ) -> Dict[str, Any]:
    """Create Author (orcid_verified=true) + Manuscript and drive to
    SUBMITTED. Returns dict with keys: 'author', 'manuscript'.

    If co_author_ids is supplied, the manuscript first enters
    AWAITING_COAUTHOR (PRD §3.2). This helper accepts an empty/absent
    co_author_ids and submits directly to SUBMITTED.
    """
    author = register_author(**(author_kwargs or {}))
    manuscript = create_manuscript_in_draft(
        author,
        co_author_ids=co_author_ids or [],
        topic_tag=topic_tag,
        **(manuscript_overrides or {}),
    )
    submitted = submit_manuscript_to_submitted(
        author, manuscript, plagiarism_similarity=plagiarism_similarity,
    )
    return {"author": author, "manuscript": submitted}


def assign_section_then_associate(manuscript_id: str,
                                  *, section_editor: Optional[Dict[str, Any]] = None,
                                  associate_editor: Optional[Dict[str, Any]] = None,
                                  topic_tag: str = TEST_DEFAULTS["TOPIC_TAG"],
                                  ) -> Tuple[Dict[str, Any], Dict[str, Any],
                                             Dict[str, Any]]:
    """Bring a SUBMITTED manuscript to UNDER_REVIEW.

    PRD §3.4 chain: editor-in-chief assigns section editor →
    section editor assigns associate editor (manuscript → UNDER_REVIEW).
    Returns (manuscript_under_review, section_editor, associate_editor).
    """
    eic = register_editor("EDITOR_IN_CHIEF")
    if section_editor is None:
        section_editor = register_editor(
            "SECTION_EDITOR", topic_tags=[topic_tag],
        )
    if associate_editor is None:
        associate_editor = register_editor(
            "ASSOCIATE_EDITOR", topic_tags=[topic_tag],
        )

    res = api_client.assign_section_editor(
        manuscript_id,
        assign_section_editor_payload(section_editor_id=section_editor["id"]),
        make_editor_in_chief_headers(eic["id"]),
    )
    get_success_data(res)

    res = api_client.assign_associate(
        manuscript_id,
        assign_associate_payload(associate_editor_id=associate_editor["id"]),
        make_section_editor_headers(section_editor["id"]),
    )
    under_review = get_success_data(res)
    return under_review, section_editor, associate_editor


def setup_under_review_manuscript(*, co_author_ids: Optional[List[str]] = None,
                                  topic_tag: str = TEST_DEFAULTS["TOPIC_TAG"],
                                  plagiarism_similarity: float = 5.0,
                                  excluded_reviewer_ids: Optional[List[str]] = None,
                                  suggested_reviewer_ids: Optional[List[str]] = None,
                                  author_kwargs: Optional[dict] = None,
                                  associate_editor: Optional[Dict[str, Any]] = None,
                                  section_editor: Optional[Dict[str, Any]] = None,
                                  ) -> Dict[str, Any]:
    """End-to-end setup: Author + Manuscript → SUBMITTED → UNDER_REVIEW.

    Returns dict with keys 'author', 'manuscript', 'section_editor',
    'associate_editor'.
    """
    author = register_author(**(author_kwargs or {}))
    manuscript = create_manuscript_in_draft(
        author,
        co_author_ids=co_author_ids or [],
        topic_tag=topic_tag,
        excluded_reviewer_ids=excluded_reviewer_ids,
        suggested_reviewer_ids=suggested_reviewer_ids,
    )
    submit_manuscript_to_submitted(
        author, manuscript, plagiarism_similarity=plagiarism_similarity,
    )
    under_review, sec, assoc = assign_section_then_associate(
        manuscript["id"],
        section_editor=section_editor,
        associate_editor=associate_editor,
        topic_tag=topic_tag,
    )
    return {
        "author": author,
        "manuscript": under_review,
        "section_editor": sec,
        "associate_editor": assoc,
    }


# ---------------------------------------------------------------------------
# Tier 2: Reviewer panel and reviews
# ---------------------------------------------------------------------------
def invite_and_accept_reviewer(manuscript: Dict[str, Any],
                               associate_editor: Dict[str, Any],
                               reviewer: Dict[str, Any],
                               ) -> Dict[str, Any]:
    """Create invitation → reviewer accepts. Returns the ACCEPTED invitation
    payload (the dict returned by /accept). For convenience, callers may
    pass this dict to submit_review_for_invitation so that helper can pull
    a review_id off the response if the implementation surfaces one.
    """
    inv_res = api_client.create_invitation(
        manuscript["id"],
        create_invitation_payload(reviewer_id=reviewer["id"]),
        make_associate_editor_headers(associate_editor["id"]),
    )
    invitation = get_success_data(inv_res)
    acc_res = api_client.accept_invitation(
        manuscript["id"], invitation["id"],
        make_reviewer_headers(reviewer["id"]),
    )
    return get_success_data(acc_res)


def _discover_review_id_for_invitation(manuscript: Dict[str, Any],
                                       invitation: Dict[str, Any],
                                       reviewer: Dict[str, Any],
                                       accept_response: Optional[Dict[str, Any]] = None,
                                       ) -> Optional[str]:
    """Try multiple PRD-faithful paths to discover the Review.id that was
    created as a side effect of accepting ``invitation``.

    PRD §3.5: 'On a successful acceptance, the system creates a Review row
    in DRAFT ...'. The PRD does not pin where the new id is exposed, so we
    try the most common exposure points in order:

    1. The accept-invitation response data itself (some implementations
       include 'review_id' alongside the invitation).
    2. AuditLog entries with entity='Review' and details.invitation_id ==
       invitation.id, or the most recent Review-creation entry.
    3. The manuscript's invitation list (some implementations include
       'review_id' on the invitation row).
    """
    # (1) Response payload may carry it.
    if accept_response and isinstance(accept_response, dict):
        for key in ("review_id", "review", "draft_review_id"):
            v = accept_response.get(key)
            if isinstance(v, dict) and v.get("id"):
                return v["id"]
            if isinstance(v, str) and v:
                return v

    # (2) AuditLog scan.
    audit_res = api_client.list_audit_logs(
        TEST_USERS["platform_admin_headers"],
        params={"entity": "Review", "limit": 100},
    )
    if audit_res.status_code < 400:
        audit_data = audit_res.json().get("data", [])
        for entry in reversed(audit_data):
            details = entry.get("details") or {}
            if details.get("invitation_id") == invitation["id"]:
                return entry.get("entity_id")
        # Heuristic fallback: most-recent CREATE-like Review entry whose
        # to_state is DRAFT (matches PRD §3.5: review created in DRAFT).
        for entry in reversed(audit_data):
            if entry.get("to_state") == "DRAFT":
                return entry.get("entity_id")

    # (2b) Some implementations attach review_id to the
    # INVITATION_ACCEPTED audit row on the ReviewerInvitation. PRD §2.10
    # allows "free-form details object for any structured context".
    audit_inv_res = api_client.list_audit_logs(
        TEST_USERS["platform_admin_headers"],
        params={"entity": "ReviewerInvitation",
                "entity_id": invitation["id"], "limit": 100},
    )
    if audit_inv_res.status_code < 400:
        audit_data = audit_inv_res.json().get("data", [])
        for entry in reversed(audit_data):
            details = entry.get("details") or {}
            rid = details.get("review_id")
            if rid:
                return rid

    # (3) Invitation list with review_id linkage.
    inv_res = api_client.list_invitations(
        manuscript["id"],
        TEST_USERS["platform_admin_headers"],
    )
    if inv_res.status_code < 400:
        inv_data = inv_res.json().get("data", [])
        for inv in inv_data:
            if inv.get("id") == invitation["id"]:
                v = inv.get("review_id") or inv.get("draft_review_id")
                if v:
                    return v
    return None


def submit_review_for_invitation(manuscript: Dict[str, Any],
                                 invitation: Dict[str, Any],
                                 reviewer: Dict[str, Any],
                                 *,
                                 rating: int = 4,
                                 recommendation: str = "ACCEPT",
                                 comments_to_author: str = "good paper",
                                 comments_to_editor: str = "fine",
                                 review_id: Optional[str] = None,
                                 ) -> Dict[str, Any]:
    """Locate the DRAFT Review for ``invitation``, patch it with all four
    required fields (PRD §3.6), and submit it. Returns the SUBMITTED review.

    Callers may pass ``review_id`` directly when they already know it
    (e.g., captured from the accept response).
    """
    if review_id is None:
        review_id = _discover_review_id_for_invitation(
            manuscript, invitation, reviewer,
        )

    assert review_id is not None, (
        "Could not discover Review id for invitation "
        f"{invitation['id']}. The implementation must surface the new "
        "Review.id created on accept via the accept response, audit log, "
        "or the invitation row's review_id field."
    )

    headers = make_reviewer_headers(reviewer["id"])
    patch_res = api_client.patch_review(
        review_id,
        complete_review_patch_payload(
            rating=rating,
            recommendation=recommendation,
            comments_to_author=comments_to_author,
            comments_to_editor=comments_to_editor,
        ),
        headers,
    )
    get_success_data(patch_res)

    sub_res = api_client.submit_review(review_id, headers)
    return get_success_data(sub_res)


def setup_two_submitted_reviews(*, manuscript: Dict[str, Any],
                                associate_editor: Dict[str, Any],
                                reviewers: Optional[List[Dict[str, Any]]] = None,
                                ratings: Tuple[int, int] = (4, 4),
                                recommendations: Tuple[str, str] = (
                                    "ACCEPT", "MINOR_REVISION"),
                                ) -> Tuple[List[Dict[str, Any]],
                                           List[Dict[str, Any]]]:
    """Invite + accept + submit reviews for a manuscript in UNDER_REVIEW.

    PRD §3.7: a decision can only be recommended once 'at least two
    reviews are in SUBMITTED at the current revision_round'.

    Returns (reviewers, submitted_reviews) with length 2 each.
    """
    if reviewers is None:
        reviewers = [
            register_reviewer(expertise_tags=[manuscript["topic_tag"]])
            for _ in range(2)
        ]
    invitations = []
    for r in reviewers:
        inv = invite_and_accept_reviewer(manuscript, associate_editor, r)
        invitations.append(inv)
    submitted = []
    for inv, r, rating, rec in zip(invitations, reviewers,
                                   ratings, recommendations):
        review = submit_review_for_invitation(
            manuscript, inv, r,
            rating=rating, recommendation=rec,
        )
        submitted.append(review)
    return reviewers, submitted


# ---------------------------------------------------------------------------
# Tier 3: Decision lifecycle
# ---------------------------------------------------------------------------
def create_and_recommend_decision(manuscript: Dict[str, Any],
                                  associate_editor: Dict[str, Any],
                                  *, recommendation_from_associate: str = "ACCEPT",
                                  ) -> Dict[str, Any]:
    """POST /decisions then POST /recommend. Returns RECOMMENDED decision."""
    headers = make_associate_editor_headers(associate_editor["id"])
    create_res = api_client.create_decision(
        manuscript["id"],
        create_decision_payload(
            recommendation_from_associate=recommendation_from_associate,
        ),
        headers,
    )
    decision = get_success_data(create_res)
    rec_res = api_client.recommend_decision(
        manuscript["id"], decision["id"], headers,
    )
    return get_success_data(rec_res)


def finalize_decision(manuscript: Dict[str, Any],
                      decision: Dict[str, Any],
                      editor_in_chief: Dict[str, Any],
                      *, final_decision: str = "ACCEPT",
                      decision_letter_body: Optional[str] = None,
                      ) -> Dict[str, Any]:
    """POST /finalize with the editor-in-chief headers."""
    res = api_client.finalize_decision(
        manuscript["id"], decision["id"],
        finalize_decision_payload(
            final_decision=final_decision,
            decision_letter_body=decision_letter_body,
        ),
        make_editor_in_chief_headers(editor_in_chief["id"]),
    )
    return get_success_data(res)


def drive_manuscript_to_accepted(*, topic_tag: str = TEST_DEFAULTS["TOPIC_TAG"],
                                 ) -> Dict[str, Any]:
    """Walk a fresh manuscript all the way to ACCEPTED.

    Returns dict with keys: 'author', 'manuscript', 'section_editor',
    'associate_editor', 'editor_in_chief', 'reviewers', 'reviews',
    'decision'.
    """
    base = setup_under_review_manuscript(topic_tag=topic_tag)
    eic = register_editor("EDITOR_IN_CHIEF")
    reviewers, reviews = setup_two_submitted_reviews(
        manuscript=base["manuscript"],
        associate_editor=base["associate_editor"],
        recommendations=("ACCEPT", "ACCEPT"),
    )
    decision = create_and_recommend_decision(
        base["manuscript"], base["associate_editor"],
        recommendation_from_associate="ACCEPT",
    )
    finalized = finalize_decision(
        base["manuscript"], decision, eic, final_decision="ACCEPT",
    )
    # Re-fetch manuscript to capture cascaded ACCEPTED state.
    refetch = api_client.get_manuscript(
        base["manuscript"]["id"],
        TEST_USERS["platform_admin_headers"],
    )
    accepted_manuscript = get_success_data(refetch)
    return {
        "author": base["author"],
        "manuscript": accepted_manuscript,
        "section_editor": base["section_editor"],
        "associate_editor": base["associate_editor"],
        "editor_in_chief": eic,
        "reviewers": reviewers,
        "reviews": reviews,
        "decision": finalized,
    }


# ---------------------------------------------------------------------------
# Tier 4: Threshold / accumulation targeting
# ---------------------------------------------------------------------------
def setup_reviewer_at_load_cap(*, topic_tag: str = TEST_DEFAULTS["TOPIC_TAG"],
                               ) -> Dict[str, Any]:
    """Build state where a single Reviewer R has active_assignments == 3
    (the cap REVIEWER_MAX_CONCURRENT per PRD §3.5).

    Creates three distinct manuscripts each in UNDER_REVIEW, invites R on
    all three, accepts all three; each accept increments active_assignments.
    Returns dict with: 'reviewer', 'manuscripts' (length 3),
    'associate_editors' (length 3), 'invitations' (length 3).
    """
    reviewer = register_reviewer(expertise_tags=[topic_tag])
    manuscripts = []
    associate_editors = []
    invitations = []
    for _ in range(3):
        base = setup_under_review_manuscript(topic_tag=topic_tag)
        inv = invite_and_accept_reviewer(
            base["manuscript"], base["associate_editor"], reviewer,
        )
        manuscripts.append(base["manuscript"])
        associate_editors.append(base["associate_editor"])
        invitations.append(inv)
    return {
        "reviewer": reviewer,
        "manuscripts": manuscripts,
        "associate_editors": associate_editors,
        "invitations": invitations,
    }


def setup_associate_editor_with_open_window(
        *, topic_tag: str = TEST_DEFAULTS["TOPIC_TAG"],
) -> Dict[str, Any]:
    """Build state where AssociateEditor AE is already assigned to one
    manuscript M1 whose 5-day acceptance window is still open. Plus a
    second manuscript M2 is SUBMITTED with a section editor assigned and
    plagiarism PASS — ready for assign-associate.

    PRD §3.4: 'two manuscripts whose windows overlap on the same
    associate editor are rejected with ERR_EDITOR_WINDOW_OVERLAP.'
    """
    associate_editor = register_editor(
        "ASSOCIATE_EDITOR", topic_tags=[topic_tag],
    )

    # M1: drive to UNDER_REVIEW so AE owns an active window.
    m1_base = setup_under_review_manuscript(
        topic_tag=topic_tag, associate_editor=associate_editor,
    )

    # M2: SUBMITTED, section editor assigned, plagiarism PASS.
    author2 = register_author()
    m2 = create_manuscript_in_draft(author2, topic_tag=topic_tag)
    submit_manuscript_to_submitted(author2, m2, plagiarism_similarity=5.0)
    eic = register_editor("EDITOR_IN_CHIEF")
    section_editor = register_editor("SECTION_EDITOR", topic_tags=[topic_tag])
    res = api_client.assign_section_editor(
        m2["id"],
        assign_section_editor_payload(section_editor_id=section_editor["id"]),
        make_editor_in_chief_headers(eic["id"]),
    )
    get_success_data(res)

    return {
        "associate_editor": associate_editor,
        "section_editor_m1": m1_base["section_editor"],
        "section_editor_m2": section_editor,
        "editor_in_chief": eic,
        "manuscript_m1": m1_base["manuscript"],  # AE assigned, window open
        "manuscript_m2": m2,                     # SUBMITTED, awaiting associate
        "author_m1": m1_base["author"],
        "author_m2": author2,
    }


# ---------------------------------------------------------------------------
# Tier 5: Production and publication
# ---------------------------------------------------------------------------
def drive_publication_to_online_first(*, doi: str = TEST_DEFAULTS["DEFAULT_DOI"],
                                      ) -> Dict[str, Any]:
    """ACCEPTED manuscript → create Publication → send-proof → approve-proof
    → doi-mint. Returns dict with keys: all the keys from
    drive_manuscript_to_accepted, plus 'publication'.
    """
    base = drive_manuscript_to_accepted()
    pub_res = api_client.create_publication(
        base["manuscript"]["id"],
        create_publication_payload(indexing_targets=["PUBMED"]),
        PLATFORM_ADMIN,
    )
    publication = get_success_data(pub_res)

    send_res = api_client.send_proof(publication["id"], PLATFORM_ADMIN)
    get_success_data(send_res)

    approve_res = api_client.approve_proof(
        publication["id"], make_author_headers(base["author"]["id"]),
    )
    get_success_data(approve_res)

    mint_res = api_client.doi_mint_event(
        doi_mint_event_payload(publication_id=publication["id"], doi=doi),
        PLATFORM_ADMIN,
    )
    publication = get_success_data(mint_res)

    return {**base, "publication": publication}


def drive_publication_to_published(*, doi: str = TEST_DEFAULTS["DEFAULT_DOI"],
                                   ) -> Dict[str, Any]:
    """Full happy path to Manuscript=PUBLISHED, Publication=PUBLISHED."""
    base = drive_publication_to_online_first(doi=doi)
    pub_res = api_client.publish_issue(
        base["publication"]["id"], PLATFORM_ADMIN,
    )
    publication = get_success_data(pub_res)
    refetch = api_client.get_manuscript(
        base["manuscript"]["id"], PLATFORM_ADMIN,
    )
    manuscript = get_success_data(refetch)
    return {**base, "publication": publication, "manuscript": manuscript}


# ---------------------------------------------------------------------------
# Tier 4 helpers used by difficulty design instances
# ---------------------------------------------------------------------------
def setup_manuscript_with_coauthors(
        *, num_coauthors: int = 2,
        topic_tag: str = TEST_DEFAULTS["TOPIC_TAG"],
        author_kwargs: Optional[dict] = None,
) -> Dict[str, Any]:
    """Author + N other co-authors + Manuscript in DRAFT (not submitted).
    Returns dict with 'author', 'coauthors' (length num_coauthors),
    'manuscript'.
    """
    author = register_author(**(author_kwargs or {}))
    coauthors = [register_author() for _ in range(num_coauthors)]
    manuscript = create_manuscript_in_draft(
        author,
        co_author_ids=[c["id"] for c in coauthors],
        topic_tag=topic_tag,
    )
    return {"author": author, "coauthors": coauthors, "manuscript": manuscript}


def setup_manuscript_awaiting_coauthor(*, num_coauthors: int = 2,
                                       topic_tag: str = TEST_DEFAULTS["TOPIC_TAG"],
                                       ) -> Dict[str, Any]:
    """Author + N coauthors + Manuscript → submit → AWAITING_COAUTHOR.
    Returns dict with 'author', 'coauthors', 'manuscript' (AWAITING_COAUTHOR),
    'confirmations' (length num_coauthors, all PENDING).
    """
    base = setup_manuscript_with_coauthors(
        num_coauthors=num_coauthors, topic_tag=topic_tag,
    )
    res = api_client.submit_manuscript(
        base["manuscript"]["id"],
        make_author_headers(base["author"]["id"]),
    )
    submitted = get_success_data(res)
    conf_res = api_client.list_coauthor_confirmations(
        base["manuscript"]["id"], PLATFORM_ADMIN,
    )
    confirmations = conf_res.json().get("data", [])
    return {**base, "manuscript": submitted, "confirmations": confirmations}


def setup_revision_required_manuscript(
        *, final_decision: str = "MINOR_REVISION",
        topic_tag: str = TEST_DEFAULTS["TOPIC_TAG"],
) -> Dict[str, Any]:
    """Walk manuscript through to REVISION_REQUIRED with two SUBMITTED
    reviews already on the prior round."""
    base = setup_under_review_manuscript(topic_tag=topic_tag)
    eic = register_editor("EDITOR_IN_CHIEF")
    reviewers, reviews = setup_two_submitted_reviews(
        manuscript=base["manuscript"],
        associate_editor=base["associate_editor"],
        recommendations=("MAJOR_REVISION", "MAJOR_REVISION"),
    )
    decision = create_and_recommend_decision(
        base["manuscript"], base["associate_editor"],
        recommendation_from_associate=final_decision,
    )
    finalized = finalize_decision(
        base["manuscript"], decision, eic,
        final_decision=final_decision,
    )
    refetch = api_client.get_manuscript(
        base["manuscript"]["id"], PLATFORM_ADMIN,
    )
    revised_manuscript = get_success_data(refetch)
    return {
        "author": base["author"],
        "manuscript": revised_manuscript,
        "section_editor": base["section_editor"],
        "associate_editor": base["associate_editor"],
        "editor_in_chief": eic,
        "reviewers": reviewers,
        "reviews": reviews,
        "decision": finalized,
    }


# ---------------------------------------------------------------------------
# Audit-log query
# ---------------------------------------------------------------------------
def list_audit_for_entity(entity: str, entity_id: str) -> List[Dict[str, Any]]:
    """Convenience: list audit-log entries for one (entity, entity_id)."""
    res = api_client.list_audit_logs(
        PLATFORM_ADMIN,
        params={"entity": entity, "entity_id": entity_id, "limit": 100},
    )
    return res.json().get("data", [])


__all__ = [
    # time
    "advance_clock_to",
    "advance_clock_by_seconds",
    "advance_clock_by_days",
    "iso_offset",
    # tier 1
    "register_author",
    "register_reviewer",
    "register_editor",
    "create_manuscript_in_draft",
    # tier 3 lifecycle
    "submit_manuscript_to_submitted",
    "setup_submitted_manuscript",
    "assign_section_then_associate",
    "setup_under_review_manuscript",
    "invite_and_accept_reviewer",
    "submit_review_for_invitation",
    "setup_two_submitted_reviews",
    "create_and_recommend_decision",
    "finalize_decision",
    "drive_manuscript_to_accepted",
    # tier 4 threshold
    "setup_reviewer_at_load_cap",
    "setup_associate_editor_with_open_window",
    # tier 5 publication / revision
    "drive_publication_to_online_first",
    "drive_publication_to_published",
    "setup_manuscript_with_coauthors",
    "setup_manuscript_awaiting_coauthor",
    "setup_revision_required_manuscript",
    # audit
    "list_audit_for_entity",
]
