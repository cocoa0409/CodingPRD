"""Payload factories — one per entity, input fields only.

Each factory builds only the caller-supplied (source: input) fields named in the PRD.
System and computed fields are never included.
"""
import itertools

_counter = itertools.count(1)


def unique_email(prefix="user"):
    """Generate a process-unique email so uniqueness constraints never collide."""
    return f"{prefix}{next(_counter)}@example.com"


def create_client_payload(**overrides) -> dict:
    """POST /clients — display_name, email."""
    defaults = {
        "display_name": "Test Client",
        "email": unique_email("client"),
    }
    defaults.update(overrides)
    return defaults


def create_freelancer_payload(**overrides) -> dict:
    """POST /freelancers — display_name, email, skills, tax_id_on_file?."""
    defaults = {
        "display_name": "Test Freelancer",
        "email": unique_email("freelancer"),
        "skills": ["python"],
    }
    defaults.update(overrides)
    return defaults


def deposit_payload(amount_cents: int, **overrides) -> dict:
    """POST /clients/{id}/wallet/deposit — amount_cents."""
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_job_posting_payload(client_id: str, **overrides) -> dict:
    """POST /job-postings — client_id, title, billing_type, budget_cents, required_skills."""
    defaults = {
        "client_id": client_id,
        "title": "Test Job",
        "billing_type": "FIXED",
        "budget_cents": 30000,
        "required_skills": ["python"],
    }
    defaults.update(overrides)
    return defaults


def create_proposal_payload(job_posting_id: str, freelancer_id: str, **overrides) -> dict:
    """POST /proposals — job_posting_id, freelancer_id, bid_amount_cents, cover_letter."""
    defaults = {
        "job_posting_id": job_posting_id,
        "freelancer_id": freelancer_id,
        "bid_amount_cents": 20000,
        "cover_letter": "I can do this work.",
    }
    defaults.update(overrides)
    return defaults


def counter_payload(actor_role: str, bid_amount_cents: int, **overrides) -> dict:
    """POST /proposals/{id}/counter — actor_role, bid_amount_cents."""
    defaults = {"actor_role": actor_role, "bid_amount_cents": bid_amount_cents}
    defaults.update(overrides)
    return defaults


def accept_payload(actor_role: str, **overrides) -> dict:
    """POST /proposals/{id}/accept — actor_role."""
    defaults = {"actor_role": actor_role}
    defaults.update(overrides)
    return defaults


def activate_contract_payload(sow_text="Statement of work.", **overrides) -> dict:
    """POST /contracts/{id}/activate — sow_text, hourly_cap_hours?."""
    defaults = {"sow_text": sow_text}
    defaults.update(overrides)
    return defaults


def create_milestone_payload(title="Milestone", amount_cents=20000, ordinal=1, **overrides) -> dict:
    """POST /contracts/{id}/milestones — title, amount_cents, ordinal."""
    defaults = {"title": title, "amount_cents": amount_cents, "ordinal": ordinal}
    defaults.update(overrides)
    return defaults


def fund_payload(expected_contract_version: int, **overrides) -> dict:
    """POST .../fund — expected_contract_version."""
    defaults = {"expected_contract_version": expected_contract_version}
    defaults.update(overrides)
    return defaults


def release_payload(expected_contract_version: int, **overrides) -> dict:
    """POST .../release — expected_contract_version."""
    defaults = {"expected_contract_version": expected_contract_version}
    defaults.update(overrides)
    return defaults


def create_timelog_payload(milestone_id: str, work_date: str, start_minute: int,
                           end_minute: int, memo="work", **overrides) -> dict:
    """POST /contracts/{id}/timelogs — milestone_id, work_date, start_minute, end_minute, memo."""
    defaults = {
        "milestone_id": milestone_id,
        "work_date": work_date,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "memo": memo,
    }
    defaults.update(overrides)
    return defaults


def dispute_payload(raised_by: str, claimed_release_cents: int, reason="disagreement", **overrides) -> dict:
    """POST .../dispute — raised_by, reason, claimed_release_cents."""
    defaults = {
        "raised_by": raised_by,
        "reason": reason,
        "claimed_release_cents": claimed_release_cents,
    }
    defaults.update(overrides)
    return defaults


def resolve_payload(arbitrator_award_cents: int, **overrides) -> dict:
    """POST /disputes/{id}/resolve — arbitrator_award_cents."""
    defaults = {"arbitrator_award_cents": arbitrator_award_cents}
    defaults.update(overrides)
    return defaults


def withdraw_dispute_payload(actor_role: str, **overrides) -> dict:
    """POST /disputes/{id}/withdraw — actor_role."""
    defaults = {"actor_role": actor_role}
    defaults.update(overrides)
    return defaults


def create_review_payload(contract_id: str, author_role: str, rating=5, comment="great", **overrides) -> dict:
    """POST /reviews — contract_id, author_role, rating, comment."""
    defaults = {
        "contract_id": contract_id,
        "author_role": author_role,
        "rating": rating,
        "comment": comment,
    }
    defaults.update(overrides)
    return defaults


def create_tax_record_payload(freelancer_id: str, tax_year: int, basis=None, **overrides) -> dict:
    """POST /tax-records — freelancer_id, tax_year, basis?."""
    defaults = {"freelancer_id": freelancer_id, "tax_year": tax_year}
    if basis is not None:
        defaults["basis"] = basis
    defaults.update(overrides)
    return defaults
