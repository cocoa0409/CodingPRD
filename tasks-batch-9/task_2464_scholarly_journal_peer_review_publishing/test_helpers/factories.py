"""Request-payload builders.

Each builder returns the minimal valid body for one write endpoint and accepts
`**overrides` so a test can pin exactly the fields its scenario is about.
Unique keys the PRD declares — a journal's `name`, an editor's `email` within a
journal, a reviewer's `email`, an author's `email` — are suffixed so that
independent builder calls never collide with `ERR_DUPLICATE_KEY`.
"""

import itertools

_counter = itertools.count(1)


def unique_suffix():
    """A per-process monotonically increasing suffix for unique-key fields."""
    return next(_counter)


# --------------------------------------------------------------------------
# Journals (PRD §3.1)
# --------------------------------------------------------------------------


def journal_payload(**overrides):
    n = unique_suffix()
    payload = {
        "name": f"Journal of Applied Contract Testing {n}",
        "subject_areas": ["BIOCHEMISTRY"],
    }
    payload.update(overrides)
    return payload


def journal_update_payload(**overrides):
    payload = {}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# People (PRD §3.1)
# --------------------------------------------------------------------------


def editor_payload(journal_id, role_level="HANDLING", **overrides):
    n = unique_suffix()
    payload = {
        "journal_id": journal_id,
        "email": f"editor{n}@example.org",
        "full_name": f"Editor {n}",
        "affiliation": f"Editorial Institute {n}",
        "subject_areas": ["BIOCHEMISTRY"],
        "role_level": role_level,
    }
    payload.update(overrides)
    return payload


def author_payload(**overrides):
    n = unique_suffix()
    payload = {
        "email": f"author{n}@example.org",
        "full_name": f"Author {n}",
        "affiliation": f"Author University {n}",
    }
    payload.update(overrides)
    return payload


def reviewer_payload(**overrides):
    n = unique_suffix()
    payload = {
        "email": f"reviewer{n}@example.org",
        "full_name": f"Reviewer {n}",
        "affiliation": f"Reviewer College {n}",
        "subject_areas": ["BIOCHEMISTRY"],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Manuscripts (PRD §3.2)
# --------------------------------------------------------------------------


def manuscript_payload(journal_id, corresponding_author_id, **overrides):
    n = unique_suffix()
    payload = {
        "journal_id": journal_id,
        "corresponding_author_id": corresponding_author_id,
        "title": f"On the Determinism of Editorial Arithmetic {n}",
        "subject_area": "BIOCHEMISTRY",
        "oa_license": "CC_BY",
        "page_count": 12,
        "figure_count": 3,
        "data_availability_statement": "Data are available in the supplementary archive.",
    }
    payload.update(overrides)
    return payload


def plagiarism_screening_payload(similarity_pct, **overrides):
    payload = {"scan_type": "PLAGIARISM", "similarity_pct": similarity_pct}
    payload.update(overrides)
    return payload


def image_forensics_screening_payload(manipulated_figure_count, **overrides):
    payload = {
        "scan_type": "IMAGE_FORENSICS",
        "manipulated_figure_count": manipulated_figure_count,
    }
    payload.update(overrides)
    return payload


def licensing_payload(oa_license, **overrides):
    payload = {"oa_license": oa_license}
    payload.update(overrides)
    return payload


def screening_decision_payload(action="ADVANCE_TO_REVIEW", **overrides):
    payload = {"action": action}
    payload.update(overrides)
    return payload


def revision_payload(page_count=12, figure_count=3, **overrides):
    payload = {
        "page_count": page_count,
        "figure_count": figure_count,
        "response_letter": "All reviewer comments have been addressed point by point.",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Editor assignments (PRD §3.4)
# --------------------------------------------------------------------------


def editor_assignment_payload(manuscript_id, expected_manuscript_version, **overrides):
    payload = {
        "manuscript_id": manuscript_id,
        "expected_manuscript_version": expected_manuscript_version,
    }
    payload.update(overrides)
    return payload


def conflict_declaration_payload(declared_conflict=False, **overrides):
    payload = {"declared_conflict": declared_conflict}
    payload.update(overrides)
    return payload


def recusal_payload(**overrides):
    payload = {}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Review invitations and reviews (PRD §3.5, §3.6)
# --------------------------------------------------------------------------


def review_invitation_payload(manuscript_id, **overrides):
    payload = {"manuscript_id": manuscript_id}
    payload.update(overrides)
    return payload


def invitation_response_payload(response="ACCEPT", **overrides):
    payload = {"response": response}
    payload.update(overrides)
    return payload


def review_payload(recommendation="MINOR_REVISION", **overrides):
    payload = {
        "recommendation": recommendation,
        "novelty_score": 3,
        "rigor_score": 3,
        "clarity_score": 3,
    }
    payload.update(overrides)
    return payload


def withdraw_payload(**overrides):
    payload = {}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Decisions and appeals (PRD §3.7)
# --------------------------------------------------------------------------


def decision_payload(**overrides):
    payload = {"editorial_note": "The editorial board has reached a decision."}
    payload.update(overrides)
    return payload


def appeal_payload(decision_id, **overrides):
    payload = {
        "decision_id": decision_id,
        "grounds": "The reviewers misread the central experiment.",
    }
    payload.update(overrides)
    return payload


def adjudication_payload(outcome="UPHELD", **overrides):
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Ethics cases (PRD §3.8)
# --------------------------------------------------------------------------


def ethics_case_payload(case_type="PLAGIARISM", severity="HIGH", **overrides):
    payload = {
        "case_type": case_type,
        "severity": severity,
        "description": "An allegation was received from a reader.",
    }
    payload.update(overrides)
    return payload


def ethics_case_advance_payload(to_state, **overrides):
    payload = {"to_state": to_state}
    payload.update(overrides)
    return payload


def ethics_case_resolution_payload(resolution="NO_ACTION", **overrides):
    payload = {
        "resolution": resolution,
        "resolution_statement": "The committee published its findings.",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# APC invoices (PRD §3.9)
# --------------------------------------------------------------------------


def apc_invoice_payload(expected_manuscript_version, **overrides):
    payload = {"expected_manuscript_version": expected_manuscript_version}
    payload.update(overrides)
    return payload


def pay_settlement_payload(amount_cents, **overrides):
    payload = {"action": "PAY", "amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def waive_settlement_payload(waiver_reason="Editorial discretion.", **overrides):
    payload = {"action": "WAIVE", "waiver_reason": waiver_reason}
    payload.update(overrides)
    return payload


def cancel_settlement_payload(**overrides):
    payload = {"action": "CANCEL"}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Production jobs (PRD §3.10)
# --------------------------------------------------------------------------


def typeset_slot_payload(slot_start, slot_end, expected_production_job_version, **overrides):
    payload = {
        "slot_start": slot_start,
        "slot_end": slot_end,
        "expected_production_job_version": expected_production_job_version,
    }
    payload.update(overrides)
    return payload


def content_advance_payload(to_stage, **overrides):
    payload = {"to_stage": to_stage}
    payload.update(overrides)
    return payload


def proof_approval_payload(approved=True, **overrides):
    payload = {"approved": approved}
    payload.update(overrides)
    return payload


def archival_deposit_payload(archival_repository="CLOCKSS", **overrides):
    payload = {
        "archival_repository": archival_repository,
        "deposit_reference": "CLOCKSS-RECEIPT-0001",
    }
    payload.update(overrides)
    return payload


def publication_payload(publication_date, **overrides):
    payload = {"publication_date": publication_date}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Operational endpoints (PRD §2.4, §3.5)
# --------------------------------------------------------------------------


def clock_payload(current_utc, **overrides):
    payload = {"current_utc": current_utc}
    payload.update(overrides)
    return payload


def reminder_sweep_payload(journal_id, **overrides):
    payload = {"journal_id": journal_id}
    payload.update(overrides)
    return payload
