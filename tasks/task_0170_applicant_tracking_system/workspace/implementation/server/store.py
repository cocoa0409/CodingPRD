"""In-memory data store keyed by id. All mutations serialise on a single RLock."""
from __future__ import annotations

import threading
import uuid
from typing import Any


def gen_id() -> str:
    return str(uuid.uuid4())


class Store:
    """Tables keyed by id; lock guards every read-followed-by-write."""

    def __init__(self) -> None:
        self.lock = threading.RLock()

        # People
        self.recruiters: dict[str, dict[str, Any]] = {}
        self.hiring_managers: dict[str, dict[str, Any]] = {}
        self.interviewers: dict[str, dict[str, Any]] = {}
        self.candidates: dict[str, dict[str, Any]] = {}
        self.eeo_records: dict[str, dict[str, Any]] = {}  # keyed by EEORecord.id
        self.eeo_by_candidate: dict[str, str] = {}  # candidate_id -> eeo_record_id

        # Recruitment
        self.requisitions: dict[str, dict[str, Any]] = {}
        self.applications: dict[str, dict[str, Any]] = {}
        self.interviews: dict[str, dict[str, Any]] = {}
        self.interview_feedback: dict[str, dict[str, Any]] = {}

        # Offers / approvals
        self.offers: dict[str, dict[str, Any]] = {}
        self.offer_approval_steps: dict[str, dict[str, Any]] = {}  # keyed by step.id
        self.offers_created_by: dict[str, str] = {}  # offer_id -> creator recruiter_id

        # Vetting & payouts
        self.background_checks: dict[str, dict[str, Any]] = {}
        self.referral_bonuses: dict[str, dict[str, Any]] = {}

        # Goals
        self.diversity_goals: dict[str, dict[str, Any]] = {}
        # goal locks: id -> {locked_at}
        self.diversity_goal_locks: dict[str, dict[str, Any]] = {}


store = Store()
