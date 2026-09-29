"""Scenario builders.

The harness restarts the API server before every test, so each test begins
against an empty database. Every precondition here is therefore constructed
from scratch through the endpoints the PRD declares — there is no seeded data
and no back door into storage.

Entity-backed identities are threaded per-row: an editor acts with
`make_handling_editor_headers(editor["id"])`, a reviewer with
`make_reviewer_headers(reviewer["id"])`, an author with
`make_author_headers(author["id"])`.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories as f
from .api_client import api_client
from .test_users import (
    PRODUCTION_STAFF_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    make_author_headers,
    make_editor_in_chief_headers,
    make_handling_editor_headers,
    make_reviewer_headers,
)

# --------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# --------------------------------------------------------------------------


def set_clock(current_utc):
    """Move the logical clock forward to `current_utc`."""
    return validate_success(
        api_client.set_clock(f.clock_payload(current_utc), SYSTEM_ADMIN_HEADERS)
    )


# --------------------------------------------------------------------------
# Registration (PRD §3.1)
# --------------------------------------------------------------------------


def create_journal(**overrides):
    return validate_success(
        api_client.create_journal(f.journal_payload(**overrides), SYSTEM_ADMIN_HEADERS),
        expected_status=201,
    )


def update_journal(journal_id, **overrides):
    """Patch a journal's configuration; only the supplied fields change."""
    return validate_success(
        api_client.update_journal(
            journal_id, f.journal_update_payload(**overrides), SYSTEM_ADMIN_HEADERS
        )
    )


def create_editor(journal_id, role_level="HANDLING", **overrides):
    return validate_success(
        api_client.create_editor(
            f.editor_payload(journal_id, role_level=role_level, **overrides),
            SYSTEM_ADMIN_HEADERS,
        ),
        expected_status=201,
    )


def create_chief(journal_id, **overrides):
    """Register a `CHIEF`-level editor and return (editor, headers)."""
    editor = create_editor(journal_id, role_level="CHIEF", **overrides)
    return editor, make_editor_in_chief_headers(editor["id"])


def create_handling_editor(journal_id, **overrides):
    """Register a `HANDLING`-level editor and return (editor, headers)."""
    editor = create_editor(journal_id, role_level="HANDLING", **overrides)
    return editor, make_handling_editor_headers(editor["id"])


def create_author(**overrides):
    """Register an author and return (author, headers)."""
    author = validate_success(
        api_client.create_author(f.author_payload(**overrides), SYSTEM_ADMIN_HEADERS),
        expected_status=201,
    )
    return author, make_author_headers(author["id"])


def create_reviewer(**overrides):
    """Register a reviewer and return (reviewer, headers)."""
    reviewer = validate_success(
        api_client.create_reviewer(
            f.reviewer_payload(**overrides), SYSTEM_ADMIN_HEADERS
        ),
        expected_status=201,
    )
    return reviewer, make_reviewer_headers(reviewer["id"])


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------


def get_journal(journal_id):
    return validate_success(api_client.get_journal(journal_id, SYSTEM_ADMIN_HEADERS))


def get_journal_metrics(journal_id):
    return validate_success(
        api_client.get_journal_metrics(journal_id, SYSTEM_ADMIN_HEADERS)
    )


def get_editor(editor_id):
    return validate_success(api_client.get_editor(editor_id, SYSTEM_ADMIN_HEADERS))


def get_reviewer(reviewer_id):
    return validate_success(api_client.get_reviewer(reviewer_id, SYSTEM_ADMIN_HEADERS))


def get_manuscript(manuscript_id):
    return validate_success(
        api_client.get_manuscript(manuscript_id, SYSTEM_ADMIN_HEADERS)
    )


def get_manuscript_version(manuscript_id):
    """The manuscript's current `version`, for the OCC-guarded writes of §2.5."""
    return get_manuscript(manuscript_id)["version"]


def get_assignment(assignment_id):
    return validate_success(
        api_client.get_editor_assignment(assignment_id, SYSTEM_ADMIN_HEADERS)
    )


def get_invitation(invitation_id):
    return validate_success(
        api_client.get_review_invitation(invitation_id, SYSTEM_ADMIN_HEADERS)
    )


def get_decision(decision_id):
    return validate_success(api_client.get_decision(decision_id, SYSTEM_ADMIN_HEADERS))


def get_appeal(appeal_id):
    return validate_success(api_client.get_appeal(appeal_id, SYSTEM_ADMIN_HEADERS))


def get_ethics_case(case_id):
    return validate_success(api_client.get_ethics_case(case_id, SYSTEM_ADMIN_HEADERS))


def get_invoice(invoice_id):
    return validate_success(api_client.get_apc_invoice(invoice_id, SYSTEM_ADMIN_HEADERS))


def get_production_job(job_id):
    return validate_success(
        api_client.get_production_job(job_id, SYSTEM_ADMIN_HEADERS)
    )


def list_production_jobs(manuscript_id):
    """A production job's only discovery channel (PRD §3.10)."""
    return get_success_data(
        api_client.list_manuscript_production_jobs(manuscript_id, SYSTEM_ADMIN_HEADERS)
    )


def get_only_production_job(manuscript_id):
    """The manuscript's single production job."""
    jobs = list_production_jobs(manuscript_id)
    assert len(jobs) == 1, f"Expected exactly one production job, got {len(jobs)}"
    return jobs[0]


def list_ethics_cases(manuscript_id):
    return get_success_data(
        api_client.list_manuscript_ethics_cases(manuscript_id, SYSTEM_ADMIN_HEADERS)
    )


def list_integrity_screenings(manuscript_id):
    return get_success_data(
        api_client.list_integrity_screenings(manuscript_id, SYSTEM_ADMIN_HEADERS)
    )


def list_invoices(manuscript_id):
    return get_success_data(
        api_client.list_manuscript_apc_invoices(manuscript_id, SYSTEM_ADMIN_HEADERS)
    )


def list_assignments(manuscript_id, state=None):
    """List a manuscript's editor assignments, optionally filtered by `state`."""
    params = {"manuscript_id": manuscript_id}
    if state is not None:
        params["state"] = state
    return get_success_data(
        api_client.list_editor_assignments(SYSTEM_ADMIN_HEADERS, params=params)
    )


# --------------------------------------------------------------------------
# Submission and screening (PRD §3.2, §3.3)
# --------------------------------------------------------------------------


def create_manuscript(journal_id, author, author_headers=None, **overrides):
    """Submit a manuscript; the acting `Author` is the corresponding author."""
    headers = author_headers or make_author_headers(author["id"])
    return validate_success(
        api_client.create_manuscript(
            f.manuscript_payload(journal_id, author["id"], **overrides), headers
        ),
        expected_status=201,
    )


def file_plagiarism_screening(manuscript_id, similarity_pct=5.0, headers=None):
    return validate_success(
        api_client.create_integrity_screening(
            manuscript_id,
            f.plagiarism_screening_payload(similarity_pct),
            headers or SYSTEM_ADMIN_HEADERS,
        ),
        expected_status=201,
    )


def file_image_forensics_screening(
    manuscript_id, manipulated_figure_count=0, headers=None
):
    return validate_success(
        api_client.create_integrity_screening(
            manuscript_id,
            f.image_forensics_screening_payload(manipulated_figure_count),
            headers or SYSTEM_ADMIN_HEADERS,
        ),
        expected_status=201,
    )


# --------------------------------------------------------------------------
# Assignment (PRD §3.4)
# --------------------------------------------------------------------------


def assign_editor(manuscript_id, chief_headers, editor_id=None, **overrides):
    """Create an editor assignment, reading the manuscript's live `version` first."""
    payload = f.editor_assignment_payload(
        manuscript_id, get_manuscript_version(manuscript_id), **overrides
    )
    if editor_id is not None:
        payload["editor_id"] = editor_id
    return validate_success(
        api_client.create_editor_assignment(payload, chief_headers), expected_status=201
    )


def declare_no_conflict(assignment_id, handling_headers):
    """A clean declaration moves the assignment `PROPOSED → ACTIVE`."""
    return validate_success(
        api_client.declare_conflict(
            assignment_id, f.conflict_declaration_payload(False), handling_headers
        )
    )


def declare_conflict(assignment_id, handling_headers, conflict_type="SAME_INSTITUTION"):
    return validate_success(
        api_client.declare_conflict(
            assignment_id,
            f.conflict_declaration_payload(True, conflict_type=conflict_type),
            handling_headers,
        )
    )


def advance_to_review(manuscript_id, handling_headers):
    return validate_success(
        api_client.screening_decision(
            manuscript_id,
            f.screening_decision_payload("ADVANCE_TO_REVIEW"),
            handling_headers,
        )
    )


def desk_reject(manuscript_id, handling_headers):
    return validate_success(
        api_client.screening_decision(
            manuscript_id, f.screening_decision_payload("DESK_REJECT"), handling_headers
        )
    )


# --------------------------------------------------------------------------
# Invitations and reviews (PRD §3.5, §3.6)
# --------------------------------------------------------------------------


def invite_reviewer(manuscript_id, handling_headers, reviewer_id=None, **overrides):
    payload = f.review_invitation_payload(manuscript_id, **overrides)
    if reviewer_id is not None:
        payload["reviewer_id"] = reviewer_id
    return validate_success(
        api_client.create_review_invitation(payload, handling_headers),
        expected_status=201,
    )


def accept_invitation(invitation_id, reviewer_headers):
    return validate_success(
        api_client.respond_to_invitation(
            invitation_id, f.invitation_response_payload("ACCEPT"), reviewer_headers
        )
    )


def decline_invitation(invitation_id, reviewer_headers, **overrides):
    return validate_success(
        api_client.respond_to_invitation(
            invitation_id,
            f.invitation_response_payload("DECLINE", **overrides),
            reviewer_headers,
        )
    )


def withdraw_invitation(invitation_id, handling_headers, **overrides):
    return validate_success(
        api_client.withdraw_invitation(
            invitation_id, f.withdraw_payload(**overrides), handling_headers
        )
    )


def submit_review(invitation_id, reviewer_headers, recommendation, **overrides):
    return validate_success(
        api_client.submit_review(
            invitation_id,
            f.review_payload(recommendation, **overrides),
            reviewer_headers,
        ),
        expected_status=201,
    )


def deliver_review(manuscript_id, handling_headers, reviewer, recommendation):
    """Invite a named reviewer, accept, and submit one review. Returns the review."""
    reviewer_headers = make_reviewer_headers(reviewer["id"])
    invitation = invite_reviewer(
        manuscript_id, handling_headers, reviewer_id=reviewer["id"]
    )
    accept_invitation(invitation["id"], reviewer_headers)
    return submit_review(invitation["id"], reviewer_headers, recommendation)


def run_reminder_sweep(journal_id):
    return validate_success(
        api_client.run_reminder_sweep(
            f.reminder_sweep_payload(journal_id), SYSTEM_ADMIN_HEADERS
        )
    )


# --------------------------------------------------------------------------
# Decisions, revisions, appeals (PRD §3.7)
# --------------------------------------------------------------------------


def issue_decision(manuscript_id, handling_headers, **overrides):
    return validate_success(
        api_client.create_decision(
            manuscript_id, f.decision_payload(**overrides), handling_headers
        ),
        expected_status=201,
    )


def submit_revision(manuscript_id, author_headers, **overrides):
    return validate_success(
        api_client.submit_revision(
            manuscript_id, f.revision_payload(**overrides), author_headers
        )
    )


def file_appeal(decision_id, author_headers, **overrides):
    return validate_success(
        api_client.create_appeal(f.appeal_payload(decision_id, **overrides), author_headers),
        expected_status=201,
    )


def adjudicate_appeal(appeal_id, chief_headers, outcome="UPHELD", **overrides):
    return validate_success(
        api_client.adjudicate_appeal(
            appeal_id, f.adjudication_payload(outcome, **overrides), chief_headers
        )
    )


# --------------------------------------------------------------------------
# Ethics cases (PRD §3.8)
# --------------------------------------------------------------------------


def open_ethics_case(manuscript_id, headers, **overrides):
    return validate_success(
        api_client.create_ethics_case(
            manuscript_id, f.ethics_case_payload(**overrides), headers
        ),
        expected_status=201,
    )


def advance_ethics_case(case_id, chief_headers, to_state):
    return validate_success(
        api_client.advance_ethics_case(
            case_id, f.ethics_case_advance_payload(to_state), chief_headers
        )
    )


def advance_case_to_committee_review(case_id, chief_headers):
    """Walk a case `OPEN → INVESTIGATION → COMMITTEE_REVIEW`."""
    advance_ethics_case(case_id, chief_headers, "INVESTIGATION")
    return advance_ethics_case(case_id, chief_headers, "COMMITTEE_REVIEW")


def resolve_ethics_case(case_id, chief_headers, resolution="NO_ACTION", **overrides):
    return validate_success(
        api_client.resolve_ethics_case(
            case_id,
            f.ethics_case_resolution_payload(resolution, **overrides),
            chief_headers,
        )
    )


# --------------------------------------------------------------------------
# Invoices (PRD §3.9)
# --------------------------------------------------------------------------


def issue_invoice(manuscript_id, headers=None, **overrides):
    """Issue an APC invoice, reading the manuscript's live `version` first."""
    return validate_success(
        api_client.create_apc_invoice(
            manuscript_id,
            f.apc_invoice_payload(get_manuscript_version(manuscript_id), **overrides),
            headers or PRODUCTION_STAFF_HEADERS,
        ),
        expected_status=201,
    )


def pay_invoice(invoice_id, amount_cents, headers=None):
    return validate_success(
        api_client.settle_apc_invoice(
            invoice_id,
            f.pay_settlement_payload(amount_cents),
            headers or PRODUCTION_STAFF_HEADERS,
        )
    )


def waive_invoice(invoice_id, headers=None, **overrides):
    return validate_success(
        api_client.settle_apc_invoice(
            invoice_id,
            f.waive_settlement_payload(**overrides),
            headers or SYSTEM_ADMIN_HEADERS,
        )
    )


def cancel_invoice(invoice_id, headers=None):
    return validate_success(
        api_client.settle_apc_invoice(
            invoice_id,
            f.cancel_settlement_payload(),
            headers or PRODUCTION_STAFF_HEADERS,
        )
    )


# --------------------------------------------------------------------------
# Production (PRD §3.10)
# --------------------------------------------------------------------------


def book_typeset_slot(job_id, slot_start, slot_end, headers=None, version=None):
    job_version = version if version is not None else get_production_job(job_id)["version"]
    return validate_success(
        api_client.book_typeset_slot(
            job_id,
            f.typeset_slot_payload(slot_start, slot_end, job_version),
            headers or PRODUCTION_STAFF_HEADERS,
        )
    )


def advance_content(job_id, to_stage, headers=None):
    return validate_success(
        api_client.advance_production_content(
            job_id, f.content_advance_payload(to_stage), headers or PRODUCTION_STAFF_HEADERS
        )
    )


def approve_proof(job_id, author_headers, approved=True, **overrides):
    return validate_success(
        api_client.approve_proof(
            job_id, f.proof_approval_payload(approved, **overrides), author_headers
        )
    )


def record_archival_deposit(job_id, headers=None, **overrides):
    return validate_success(
        api_client.record_archival_deposit(
            job_id,
            f.archival_deposit_payload(**overrides),
            headers or PRODUCTION_STAFF_HEADERS,
        )
    )


def publish_article(job_id, publication_date, headers=None, **overrides):
    return validate_success(
        api_client.publish_article(
            job_id,
            f.publication_payload(publication_date, **overrides),
            headers or PRODUCTION_STAFF_HEADERS,
        )
    )


# --------------------------------------------------------------------------
# Composite worlds
# --------------------------------------------------------------------------


def setup_world(journal_overrides=None, author_overrides=None, handling_editor_count=1):
    """A journal, one chief editor, N handling editors and one author."""
    journal = create_journal(**(journal_overrides or {}))
    chief, chief_headers = create_chief(journal["id"])
    handlings = []
    for _ in range(handling_editor_count):
        editor, headers = create_handling_editor(journal["id"])
        handlings.append({"editor": editor, "headers": headers})
    author, author_headers = create_author(**(author_overrides or {}))
    return {
        "journal": journal,
        "chief": chief,
        "chief_headers": chief_headers,
        "handlings": handlings,
        "handling": handlings[0]["editor"] if handlings else None,
        "handling_headers": handlings[0]["headers"] if handlings else None,
        "author": author,
        "author_headers": author_headers,
    }


def setup_submitted_manuscript(
    journal_overrides=None,
    author_overrides=None,
    manuscript_overrides=None,
    handling_editor_count=1,
):
    """A world plus one manuscript at `SUBMITTED`."""
    world = setup_world(
        journal_overrides=journal_overrides,
        author_overrides=author_overrides,
        handling_editor_count=handling_editor_count,
    )
    world["manuscript"] = create_manuscript(
        world["journal"]["id"],
        world["author"],
        world["author_headers"],
        **(manuscript_overrides or {}),
    )
    return world


def setup_active_assignment(
    journal_overrides=None,
    author_overrides=None,
    manuscript_overrides=None,
    similarity_pct=5.0,
    handling_editor_count=1,
):
    """A `SUBMITTED` manuscript with a screened round and an `ACTIVE` assignment."""
    world = setup_submitted_manuscript(
        journal_overrides=journal_overrides,
        author_overrides=author_overrides,
        manuscript_overrides=manuscript_overrides,
        handling_editor_count=handling_editor_count,
    )
    file_plagiarism_screening(world["manuscript"]["id"], similarity_pct)
    assignment = assign_editor(
        world["manuscript"]["id"],
        world["chief_headers"],
        editor_id=world["handling"]["id"],
    )
    declare_no_conflict(assignment["id"], world["handling_headers"])
    world["assignment"] = get_assignment(assignment["id"])
    return world


def setup_under_review_manuscript(**kwargs):
    """A manuscript advanced `SUBMITTED → UNDER_REVIEW` by the desk call."""
    world = setup_active_assignment(**kwargs)
    advance_to_review(world["manuscript"]["id"], world["handling_headers"])
    world["manuscript"] = get_manuscript(world["manuscript"]["id"])
    return world


def setup_decision_pending(recommendations=("MINOR_REVISION", "MINOR_REVISION"), **kwargs):
    """A manuscript at `DECISION_PENDING` with one submitted review per recommendation."""
    world = setup_under_review_manuscript(**kwargs)
    reviewers = []
    reviews = []
    for recommendation in recommendations:
        reviewer, reviewer_headers = create_reviewer()
        reviewers.append({"reviewer": reviewer, "headers": reviewer_headers})
        reviews.append(
            deliver_review(
                world["manuscript"]["id"],
                world["handling_headers"],
                reviewer,
                recommendation,
            )
        )
    world["reviewers"] = reviewers
    world["reviews"] = reviews
    world["manuscript"] = get_manuscript(world["manuscript"]["id"])
    return world


def setup_in_production(**kwargs):
    """An accepted manuscript at `IN_PRODUCTION` with its single production job."""
    world = setup_decision_pending(recommendations=("ACCEPT", "ACCEPT"), **kwargs)
    world["decision"] = issue_decision(
        world["manuscript"]["id"], world["handling_headers"]
    )
    world["manuscript"] = get_manuscript(world["manuscript"]["id"])
    world["job"] = get_only_production_job(world["manuscript"]["id"])
    return world


def setup_rejected_manuscript(**kwargs):
    """A manuscript at `REJECTED` with the rejecting decision."""
    world = setup_decision_pending(recommendations=("REJECT", "REJECT"), **kwargs)
    world["decision"] = issue_decision(
        world["manuscript"]["id"], world["handling_headers"]
    )
    world["manuscript"] = get_manuscript(world["manuscript"]["id"])
    return world


def setup_appeal_filed(**kwargs):
    """A rejected manuscript moved `REJECTED → UNDER_APPEAL` by a filed appeal."""
    world = setup_rejected_manuscript(**kwargs)
    world["appeal"] = file_appeal(
        world["decision"]["id"], world["author_headers"]
    )
    world["manuscript"] = get_manuscript(world["manuscript"]["id"])
    return world


def setup_ready_to_publish(
    slot_start="2026-09-01", slot_end="2026-09-05", page_charge_count=0,
    color_figure_count=0, **kwargs
):
    """A production job at `PROOF_APPROVED` / `DEPOSIT_CONFIRMED` with fees settled."""
    world = setup_in_production(**kwargs)
    job_id = world["job"]["id"]
    invoice = issue_invoice(
        world["manuscript"]["id"],
        page_charge_count=page_charge_count,
        color_figure_count=color_figure_count,
    )
    if invoice["total_due_cents"] > 0:
        pay_invoice(invoice["id"], invoice["total_due_cents"])
    else:
        # PRD 2.10 rule 28: publication requires the manuscript to carry no
        # invoice still at status `ISSUED`. A zero-total invoice clears the fee
        # dimension at issuance but still sits at `ISSUED`, and it cannot be
        # paid (`total_due_cents` must be greater than 0), so it is waived.
        waive_invoice(invoice["id"], waiver_reason="Nothing is billable on this article.")
    world["invoice"] = get_invoice(invoice["id"])
    book_typeset_slot(job_id, slot_start, slot_end)
    advance_content(job_id, "TYPESETTING")
    advance_content(job_id, "PROOF_SENT")
    approve_proof(job_id, world["author_headers"], True)
    record_archival_deposit(job_id)
    world["job"] = get_production_job(job_id)
    return world


def setup_published_manuscript(publication_date="2026-09-10", **kwargs):
    """A published article, with its job `INDEXED`."""
    world = setup_ready_to_publish(**kwargs)
    publish_article(world["job"]["id"], publication_date)
    world["manuscript"] = get_manuscript(world["manuscript"]["id"])
    world["job"] = get_production_job(world["job"]["id"])
    world["journal"] = get_journal(world["journal"]["id"])
    return world


# --------------------------------------------------------------------------
# Additional manuscripts inside an existing world
# --------------------------------------------------------------------------


def add_manuscript_under_review(world, similarity_pct=5.0, **manuscript_overrides):
    """Submit, screen, assign and desk-advance one more manuscript in `world`."""
    manuscript = create_manuscript(
        world["journal"]["id"],
        world["author"],
        world["author_headers"],
        **manuscript_overrides,
    )
    file_plagiarism_screening(manuscript["id"], similarity_pct)
    assignment = assign_editor(
        manuscript["id"], world["chief_headers"], editor_id=world["handling"]["id"]
    )
    declare_no_conflict(assignment["id"], world["handling_headers"])
    advance_to_review(manuscript["id"], world["handling_headers"])
    return get_manuscript(manuscript["id"])


def accept_manuscript_in_world(world, review_count=2, **manuscript_overrides):
    """Carry one more manuscript of `world` all the way to `IN_PRODUCTION`."""
    manuscript = add_manuscript_under_review(world, **manuscript_overrides)
    for _ in range(review_count):
        reviewer, _headers = create_reviewer()
        deliver_review(
            manuscript["id"], world["handling_headers"], reviewer, "ACCEPT"
        )
    decision = issue_decision(manuscript["id"], world["handling_headers"])
    return {
        "manuscript": get_manuscript(manuscript["id"]),
        "decision": decision,
        "job": get_only_production_job(manuscript["id"]),
    }


# --------------------------------------------------------------------------
# Reviewer-conduct scenarios
# --------------------------------------------------------------------------


def setup_rolling_vs_lifetime_reviewer():
    """One reviewer whose only decline falls outside the 180-day rolling window.

    The decline is created at the clock epoch; the clock then moves 213 days
    past it before a second invitation is accepted and answered on time.
    """
    world = setup_under_review_manuscript()
    manuscript_id = world["manuscript"]["id"]
    reviewer, reviewer_headers = create_reviewer()
    first = invite_reviewer(
        manuscript_id, world["handling_headers"], reviewer_id=reviewer["id"]
    )
    decline_invitation(
        first["id"], reviewer_headers, decline_reason="Competing commitments"
    )
    set_clock("2027-03-01T00:00:00Z")
    second = invite_reviewer(
        manuscript_id, world["handling_headers"], reviewer_id=reviewer["id"]
    )
    accept_invitation(second["id"], reviewer_headers)
    review = submit_review(
        second["id"],
        reviewer_headers,
        "ACCEPT",
        novelty_score=4,
        rigor_score=4,
        clarity_score=5,
        comments="Solid contribution",
    )
    world["reviewer"] = get_reviewer(reviewer["id"])
    world["reviewer_headers"] = reviewer_headers
    world["declined_invitation"] = get_invitation(first["id"])
    world["submitted_invitation"] = get_invitation(second["id"])
    world["review"] = review
    return world


def setup_open_invitation_for_withdrawal():
    """A fresh reviewer left holding exactly one `INVITED` invitation."""
    world = setup_under_review_manuscript()
    reviewer, reviewer_headers = create_reviewer()
    world["reviewer_before"] = get_reviewer(reviewer["id"])
    invitation = invite_reviewer(
        world["manuscript"]["id"],
        world["handling_headers"],
        reviewer_id=reviewer["id"],
    )
    world["reviewer"] = reviewer
    world["reviewer_headers"] = reviewer_headers
    world["invitation"] = invitation
    world["reviewer_while_open"] = get_reviewer(reviewer["id"])
    return world


def setup_consensus_variant_pair():
    """Two manuscripts scored by the same reviewer pair under both consensus modes.

    Manuscript `m1` is decided while the journal is `UNWEIGHTED`; the journal is
    then patched to `RELIABILITY_WEIGHTED` and `m2` collects the identical
    recommendation pair from the same two reviewers, whose frozen weights differ.
    """
    world = setup_under_review_manuscript()
    journal_id = world["journal"]["id"]
    handling_headers = world["handling_headers"]
    m1_id = world["manuscript"]["id"]

    strong, strong_headers = create_reviewer()
    weak, weak_headers = create_reviewer()

    inv_strong_1 = invite_reviewer(m1_id, handling_headers, reviewer_id=strong["id"])
    accept_invitation(inv_strong_1["id"], strong_headers)
    review_strong_1 = submit_review(
        inv_strong_1["id"],
        strong_headers,
        "ACCEPT",
        novelty_score=4,
        rigor_score=4,
        clarity_score=4,
        comments="Accept as is",
    )

    inv_weak_declined = invite_reviewer(m1_id, handling_headers, reviewer_id=weak["id"])
    decline_invitation(inv_weak_declined["id"], weak_headers, decline_reason="Too busy")
    inv_weak_1 = invite_reviewer(m1_id, handling_headers, reviewer_id=weak["id"])
    accept_invitation(inv_weak_1["id"], weak_headers)

    set_clock("2026-08-26T00:00:00Z")
    review_weak_1 = submit_review(
        inv_weak_1["id"],
        weak_headers,
        "MAJOR_REVISION",
        novelty_score=2,
        rigor_score=2,
        clarity_score=3,
        comments="Needs major work",
    )
    unweighted_decision = issue_decision(
        m1_id, handling_headers, editorial_note="Unweighted consensus decision"
    )

    update_journal(journal_id, consensus_mode="RELIABILITY_WEIGHTED")

    m2 = add_manuscript_under_review(
        world, similarity_pct=3.0, page_count=19, figure_count=4
    )
    inv_strong_2 = invite_reviewer(m2["id"], handling_headers, reviewer_id=strong["id"])
    accept_invitation(inv_strong_2["id"], strong_headers)
    review_strong_2 = submit_review(
        inv_strong_2["id"],
        strong_headers,
        "ACCEPT",
        novelty_score=4,
        rigor_score=4,
        clarity_score=4,
        comments="Accept as is",
    )
    inv_weak_2 = invite_reviewer(m2["id"], handling_headers, reviewer_id=weak["id"])
    accept_invitation(inv_weak_2["id"], weak_headers)

    set_clock("2026-09-20T00:00:00Z")
    review_weak_2 = submit_review(
        inv_weak_2["id"],
        weak_headers,
        "MAJOR_REVISION",
        novelty_score=2,
        rigor_score=2,
        clarity_score=3,
        comments="Needs major work",
    )

    world["strong_reviewer"] = strong
    world["weak_reviewer"] = weak
    world["m1"] = get_manuscript(m1_id)
    world["m2"] = get_manuscript(m2["id"])
    world["unweighted_decision"] = unweighted_decision
    world["review_strong_1"] = review_strong_1
    world["review_weak_1"] = review_weak_1
    world["review_strong_2"] = review_strong_2
    world["review_weak_2"] = review_weak_2
    return world


def setup_reject_cascade_world():
    """A `DECISION_PENDING` manuscript with two `REJECT` reviews and one live invitation.

    The third reviewer has two declines already recorded and still holds an
    `ACCEPTED` invitation, so the rejection cascade closes a third invitation.
    """
    world = setup_under_review_manuscript()
    manuscript_id = world["manuscript"]["id"]
    handling_headers = world["handling_headers"]

    cascaded, cascaded_headers = create_reviewer()
    first = invite_reviewer(manuscript_id, handling_headers, reviewer_id=cascaded["id"])
    decline_invitation(
        first["id"], cascaded_headers, decline_reason="Out of scope for me"
    )
    second = invite_reviewer(manuscript_id, handling_headers, reviewer_id=cascaded["id"])
    decline_invitation(
        second["id"], cascaded_headers, decline_reason="Still unavailable"
    )
    third = invite_reviewer(manuscript_id, handling_headers, reviewer_id=cascaded["id"])
    accept_invitation(third["id"], cascaded_headers)
    world["cascaded_reviewer_before"] = get_reviewer(cascaded["id"])

    rejecting = []
    for _ in range(2):
        reviewer, _headers = create_reviewer()
        rejecting.append(
            deliver_review(manuscript_id, handling_headers, reviewer, "REJECT")
        )

    world["cascaded_reviewer"] = cascaded
    world["cascaded_invitations"] = [first, second, third]
    world["open_invitation"] = third
    world["rejecting_reviews"] = rejecting
    world["manuscript"] = get_manuscript(manuscript_id)
    return world


# --------------------------------------------------------------------------
# Rejection-priority scenarios
# --------------------------------------------------------------------------


def setup_stage_gate_blocked_publication():
    """A job at `TYPESETTING`/`LICENSE_PENDING` that also carries an `ISSUED` invoice."""
    world = setup_in_production()
    job_id = world["job"]["id"]
    book_typeset_slot(job_id, "2026-09-01", "2026-09-05")
    advance_content(job_id, "TYPESETTING")
    world["invoice"] = issue_invoice(world["manuscript"]["id"])
    world["job"] = get_production_job(job_id)
    world["manuscript"] = get_manuscript(world["manuscript"]["id"])
    return world


def setup_blocked_and_non_compliant_manuscript():
    """A `SUBMITTED` manuscript that is simultaneously integrity-blocked and overlong."""
    world = setup_submitted_manuscript(manuscript_overrides={"page_count": 40})
    manuscript_id = world["manuscript"]["id"]
    world["screening"] = file_plagiarism_screening(manuscript_id, 55.0)
    assignment = assign_editor(
        manuscript_id, world["chief_headers"], editor_id=world["handling"]["id"]
    )
    declare_no_conflict(assignment["id"], world["handling_headers"])
    world["assignment"] = get_assignment(assignment["id"])
    world["manuscript"] = get_manuscript(manuscript_id)
    return world


# --------------------------------------------------------------------------
# Cross-entity gate scenarios
# --------------------------------------------------------------------------


def setup_second_issued_invoice_before_publication():
    """A publication-ready job whose manuscript carries a second, unsettled invoice."""
    world = setup_ready_to_publish()
    set_clock("2026-09-10T00:00:00Z")
    world["second_invoice"] = issue_invoice(world["manuscript"]["id"])
    world["job"] = get_production_job(world["job"]["id"])
    return world


def setup_ethics_hold_on_decision():
    """A decidable manuscript frozen by a `HIGH`-severity case, with a second chief."""
    world = setup_decision_pending()
    second_chief, second_chief_headers = create_chief(world["journal"]["id"])
    world["second_chief"] = second_chief
    world["second_chief_headers"] = second_chief_headers
    world["ethics_case"] = open_ethics_case(
        world["manuscript"]["id"],
        world["chief_headers"],
        case_type="AUTHORSHIP_DISPUTE",
        severity="HIGH",
        description="Omitted co-author claims authorship",
    )
    return world


# --------------------------------------------------------------------------
# Temporal-occupancy scenarios
# --------------------------------------------------------------------------


def setup_reviewer_window_pair():
    """Two manuscripts under review on a journal that allows one open window."""
    world = setup_under_review_manuscript(
        journal_overrides={"reviewer_concurrent_window_limit": 1}
    )
    world["m1"] = world["manuscript"]
    world["m2"] = add_manuscript_under_review(world, page_count=21)
    reviewer, reviewer_headers = create_reviewer()
    world["reviewer"] = reviewer
    world["reviewer_headers"] = reviewer_headers
    world["invitation"] = invite_reviewer(
        world["m1"]["id"], world["handling_headers"], reviewer_id=reviewer["id"]
    )
    return world


def setup_two_production_jobs(slot_start="2026-09-01", slot_end="2026-09-05"):
    """Two jobs of one journal, the first holding a booked slot."""
    world = setup_in_production()
    world["job_one"] = world["job"]
    book_typeset_slot(world["job_one"]["id"], slot_start, slot_end)
    world["job_one"] = get_production_job(world["job_one"]["id"])
    second = accept_manuscript_in_world(world, page_count=21)
    world["m2"] = second["manuscript"]
    world["job_two"] = second["job"]
    return world


# --------------------------------------------------------------------------
# Fee-arithmetic scenarios
# --------------------------------------------------------------------------


def setup_nested_rounding_invoice_world():
    """A non-round list price with both an income-band waiver and an institutional deal."""
    journal = create_journal(apc_base_cents=175033)
    author, author_headers = create_author(
        country_income_band="UPPER_MIDDLE", institutional_agreement=True
    )
    manuscript = create_manuscript(
        journal["id"],
        author,
        author_headers,
        oa_license="CC_BY_NC_ND",
        page_count=20,
        figure_count=5,
    )
    return {
        "journal": journal,
        "author": author,
        "author_headers": author_headers,
        "manuscript": manuscript,
    }


def setup_surcharge_bracket_invoice_world():
    """A list price and page charge that put the provisional total in the 10% bracket."""
    journal = create_journal(apc_base_cents=120000)
    author, author_headers = create_author()
    manuscript = create_manuscript(
        journal["id"], author, author_headers, page_count=28, figure_count=6
    )
    return {
        "journal": journal,
        "author": author,
        "author_headers": author_headers,
        "manuscript": manuscript,
    }


def setup_issued_invoice_without_production_job():
    """An `ISSUED` invoice on a `SUBMITTED` manuscript that has no production job."""
    journal = create_journal()
    author, author_headers = create_author()
    manuscript = create_manuscript(journal["id"], author, author_headers)
    journal_before = get_journal(journal["id"])
    invoice = issue_invoice(manuscript["id"])
    return {
        "journal": journal,
        "journal_before": journal_before,
        "journal_while_issued": get_journal(journal["id"]),
        "author": author,
        "author_headers": author_headers,
        "manuscript": manuscript,
        "invoice": invoice,
    }


# --------------------------------------------------------------------------
# Revision-cycle scenario
# --------------------------------------------------------------------------


def setup_revision_requested_manuscript():
    """A manuscript returned to the author by a `MINOR_REVISION` decision."""
    world = setup_decision_pending(
        manuscript_overrides={"page_count": 20, "figure_count": 5}
    )
    world["decision"] = issue_decision(
        world["manuscript"]["id"],
        world["handling_headers"],
        editorial_note="Minor revision requested",
    )
    world["manuscript"] = get_manuscript(world["manuscript"]["id"])
    return world
