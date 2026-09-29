"""Composite fixtures for the managed document review staffing API.

Setup here uses ``get_success_data`` rather than a strict validator, so that a
broken setup step fails loudly as a setup problem rather than masquerading as
the behaviour under test.

The ladder below mirrors the real engagement sequence: register a client, open
a matter, mint and approve a protocol, source and onboard a reviewer, open a
secure session, carve a batch, assign it, code it, submit it, sample it,
validate the privilege log, release the batch and close the matter. Fixtures
stop the ladder at whichever rung a test needs.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import CLOCK_START_UTC
from . import factories as f
from .test_users import (
    ENGAGEMENT_MANAGER,
    QC_LEAD,
    STAFFING_COORDINATOR,
    make_client_counsel_headers,
    make_reviewer_headers,
)

# ---------------------------------------------------------------------------
# Reviewer payload catalogue
# ---------------------------------------------------------------------------
# Ada is the workhorse first-pass reviewer for the core engagement: she matches
# both required languages, so her effective per-document rate carries the
# language premium.
REVIEWER_ADA = dict(
    full_name="Ada Ishikawa",
    bar_admissions=["NY"],
    languages=["EN", "JA"],
    subject_matter_tags=["ANTITRUST"],
    tier="FIRST_PASS",
    hourly_cost_cents=5200,
    max_concurrent_batches=2,
    remote_work_authorized=False,
)

# Ben is the second-level reviewer and the only person authorised to work
# remotely.
REVIEWER_BEN = dict(
    full_name="Ben Calder",
    bar_admissions=["NY"],
    languages=["EN", "JA"],
    subject_matter_tags=["ANTITRUST"],
    tier="SECOND_LEVEL",
    hourly_cost_cents=7400,
    max_concurrent_batches=2,
    remote_work_authorized=True,
)

# Cleo scores other people's work and is deliberately never staffed onto a
# batch, so she can validate a sample without a segregation-of-duties clash.
REVIEWER_CLEO = dict(
    full_name="Cleo Marchetti",
    bar_admissions=["NY"],
    languages=["EN"],
    subject_matter_tags=["QC"],
    tier="SECOND_LEVEL",
    hourly_cost_cents=8800,
    max_concurrent_batches=1,
    remote_work_authorized=False,
)

# Dana is Ada's twin on every scored dimension but costs more per hour, which
# is what makes her useful for exercising the tie-break chain.
REVIEWER_DANA = dict(
    full_name="Dana Okafor",
    bar_admissions=["NY"],
    languages=["EN", "JA"],
    subject_matter_tags=["ANTITRUST"],
    tier="FIRST_PASS",
    hourly_cost_cents=7400,
    max_concurrent_batches=2,
    remote_work_authorized=False,
)

# Dara matches the languages but not the subject tags, so she scores lower
# than Ada without being excluded from the pool.
REVIEWER_DARA = dict(
    full_name="Dara Okonkwo",
    bar_admissions=["NY"],
    languages=["EN", "JA"],
    subject_matter_tags=["SECURITIES"],
    tier="FIRST_PASS",
    hourly_cost_cents=6100,
    max_concurrent_batches=2,
    remote_work_authorized=False,
)

# Elena is a third fully onboarded first-pass reviewer, used when two onsite
# seats are already occupied.
REVIEWER_ELENA = dict(
    full_name="Elena Vasquez",
    bar_admissions=["NY"],
    languages=["EN", "JA"],
    subject_matter_tags=["ANTITRUST"],
    tier="FIRST_PASS",
    hourly_cost_cents=6000,
    max_concurrent_batches=2,
    remote_work_authorized=False,
)


# ---------------------------------------------------------------------------
# The ladder
# ---------------------------------------------------------------------------
class ReviewLadder:
    """Sequenced setup helper. Every method returns the created row."""

    def __init__(self, api: ApiClient):
        self.api = api
        self.client_id: str | None = None
        self.matter_id: str | None = None
        self.protocol_id: str | None = None

    # -- clock ---------------------------------------------------------
    def set_clock(self, to_iso8601: str = CLOCK_START_UTC) -> dict:
        return get_success_data(self.api.set_clock(to_iso8601))

    # -- client and matter --------------------------------------------
    def register_client(self, **overrides) -> dict:
        row = get_success_data(
            self.api.create_client(f.client_payload(**overrides), ENGAGEMENT_MANAGER)
        )
        self.client_id = row["id"]
        return row

    def open_matter(self, client_id: str | None = None, **overrides) -> dict:
        row = get_success_data(
            self.api.create_matter(
                f.matter_payload(client_id or self.client_id, **overrides),
                ENGAGEMENT_MANAGER,
            )
        )
        self.matter_id = row["id"]
        return row

    def read_matter(self, matter_id: str | None = None) -> dict:
        return get_success_data(
            self.api.get_matter(matter_id or self.matter_id, ENGAGEMENT_MANAGER)
        )

    def matter_version(self, matter_id: str | None = None) -> int:
        return self.read_matter(matter_id)["version"]

    def suspend_matter(
        self, reason: str, matter_id: str | None = None
    ) -> dict:
        return get_success_data(
            self.api.set_matter_suspension(
                matter_id or self.matter_id,
                f.suspension_payload(True, suspension_reason=reason),
                ENGAGEMENT_MANAGER,
            )
        )

    def resume_matter(self, matter_id: str | None = None) -> dict:
        return get_success_data(
            self.api.set_matter_suspension(
                matter_id or self.matter_id,
                f.suspension_payload(False),
                ENGAGEMENT_MANAGER,
            )
        )

    def close_matter(self, matter_id: str | None = None) -> dict:
        return get_success_data(
            self.api.close_matter(matter_id or self.matter_id, ENGAGEMENT_MANAGER)
        )

    # -- protocol ------------------------------------------------------
    def mint_protocol(
        self,
        matter_id: str | None = None,
        expected_matter_version: int | None = None,
        **overrides,
    ) -> dict:
        target = matter_id or self.matter_id
        version = (
            expected_matter_version
            if expected_matter_version is not None
            else self.matter_version(target)
        )
        row = get_success_data(
            self.api.create_protocol(
                target, f.protocol_payload(version, **overrides), ENGAGEMENT_MANAGER
            )
        )
        self.protocol_id = row["id"]
        return row

    def submit_protocol(self, protocol_id: str | None = None) -> dict:
        return get_success_data(
            self.api.submit_protocol(
                protocol_id or self.protocol_id, ENGAGEMENT_MANAGER
            )
        )

    def approve_protocol(
        self, protocol_id: str | None = None, client_id: str | None = None
    ) -> dict:
        return get_success_data(
            self.api.decide_protocol(
                protocol_id or self.protocol_id,
                f.protocol_decision_payload("APPROVE"),
                make_client_counsel_headers(client_id or self.client_id),
            )
        )

    def request_protocol_changes(
        self,
        notes: str,
        protocol_id: str | None = None,
        client_id: str | None = None,
    ) -> dict:
        return get_success_data(
            self.api.decide_protocol(
                protocol_id or self.protocol_id,
                f.protocol_decision_payload("REQUEST_CHANGES", change_notes=notes),
                make_client_counsel_headers(client_id or self.client_id),
            )
        )

    def approved_protocol(self, **overrides) -> dict:
        """Mint, submit and approve one protocol revision in one step."""
        protocol = self.mint_protocol(**overrides)
        self.submit_protocol(protocol["id"])
        return self.approve_protocol(protocol["id"])

    # -- reviewers -----------------------------------------------------
    def source_reviewer(self, spec: dict | None = None, **overrides) -> dict:
        payload = dict(spec or REVIEWER_ADA)
        payload.update(overrides)
        return get_success_data(
            self.api.create_reviewer(
                f.reviewer_payload(**payload), STAFFING_COORDINATOR
            )
        )

    def verify_credential(
        self, reviewer_id: str, bar_admissions: list[str] | None = None
    ) -> dict:
        return get_success_data(
            self.api.set_credential_status(
                reviewer_id,
                f.credential_status_payload(
                    "VERIFIED", bar_admissions=bar_admissions or ["NY"]
                ),
                STAFFING_COORDINATOR,
            )
        )

    def lapse_credential(self, reviewer_id: str) -> dict:
        return get_success_data(
            self.api.set_credential_status(
                reviewer_id,
                f.credential_status_payload("LAPSED"),
                STAFFING_COORDINATOR,
            )
        )

    def read_reviewer(self, reviewer_id: str) -> dict:
        return get_success_data(
            self.api.get_reviewer(reviewer_id, STAFFING_COORDINATOR)
        )

    def scorecard(self, reviewer_id: str, weighting: str | None = None) -> dict:
        return get_success_data(
            self.api.get_scorecard(reviewer_id, QC_LEAD, weighting=weighting)
        )

    def scorecard_events(self, reviewer_id: str, event_type: str | None = None):
        response = self.api.list_scorecard_events(
            reviewer_id, QC_LEAD, event_type=event_type, limit=100
        )
        return get_success_data(response)

    # -- screening -----------------------------------------------------
    def open_screening(
        self, reviewer_id: str, matter_id: str | None = None, **overrides
    ) -> dict:
        return get_success_data(
            self.api.create_screening(
                f.screening_payload(
                    reviewer_id, matter_id or self.matter_id, **overrides
                ),
                STAFFING_COORDINATOR,
            )
        )

    def decide_screening(
        self, screening_id: str, outcome: str, note: str = "no adverse party overlap"
    ) -> dict:
        return get_success_data(
            self.api.decide_screening(
                screening_id,
                f.screening_decision_payload(outcome, decision_note=note),
                STAFFING_COORDINATOR,
            )
        )

    # -- agreements ----------------------------------------------------
    def issue_agreement(
        self, reviewer_id: str, matter_id: str | None = None, **overrides
    ) -> dict:
        return get_success_data(
            self.api.create_agreement(
                f.agreement_payload(
                    reviewer_id, matter_id or self.matter_id, **overrides
                ),
                STAFFING_COORDINATOR,
            )
        )

    def execute_agreement(
        self, agreement_id: str, reviewer_id: str, signature_name: str
    ) -> dict:
        return get_success_data(
            self.api.execute_agreement(
                agreement_id,
                f.execute_payload(signature_name),
                make_reviewer_headers(reviewer_id),
            )
        )

    # -- full onboarding ----------------------------------------------
    def onboard(
        self,
        spec: dict | None = None,
        matter_id: str | None = None,
        remote_work_addendum: bool = False,
        coverage_start_utc: str = CLOCK_START_UTC,
        coverage_end_utc: str = "2026-10-31T00:00:00Z",
        **reviewer_overrides,
    ) -> dict:
        """Source, verify, clear, cover and sign one reviewer onto a matter.

        Returns a dict of the reviewer, screening and agreement rows plus the
        reviewer's own request headers.
        """
        spec = dict(spec or REVIEWER_ADA)
        spec.update(reviewer_overrides)
        reviewer = self.source_reviewer(spec)
        self.verify_credential(reviewer["id"], spec.get("bar_admissions", ["NY"]))
        screening = self.open_screening(reviewer["id"], matter_id)
        self.decide_screening(screening["id"], "CLEARED")
        agreement = self.issue_agreement(
            reviewer["id"],
            matter_id,
            remote_work_addendum=remote_work_addendum,
            coverage_start_utc=coverage_start_utc,
            coverage_end_utc=coverage_end_utc,
        )
        self.execute_agreement(
            agreement["id"], reviewer["id"], spec["full_name"]
        )
        return {
            "reviewer": reviewer,
            "reviewer_id": reviewer["id"],
            "headers": make_reviewer_headers(reviewer["id"]),
            "screening": screening,
            "screening_id": screening["id"],
            "agreement": agreement,
            "agreement_id": agreement["id"],
            "full_name": spec["full_name"],
        }

    # -- sessions ------------------------------------------------------
    def schedule_session(
        self, reviewer_id: str, matter_id: str | None = None, **overrides
    ) -> dict:
        return get_success_data(
            self.api.create_session(
                f.session_payload(
                    reviewer_id, matter_id or self.matter_id, **overrides
                ),
                make_reviewer_headers(reviewer_id),
            )
        )

    def activate_session(self, session_id: str, reviewer_id: str) -> dict:
        return get_success_data(
            self.api.set_session_lifecycle(
                session_id,
                f.session_lifecycle_payload("ACTIVE"),
                make_reviewer_headers(reviewer_id),
            )
        )

    def active_session(
        self, reviewer_id: str, matter_id: str | None = None, **overrides
    ) -> dict:
        session = self.schedule_session(reviewer_id, matter_id, **overrides)
        return self.activate_session(session["id"], reviewer_id)

    # -- batches -------------------------------------------------------
    def carve_batch(
        self, document_count: int, matter_id: str | None = None, **overrides
    ) -> dict:
        return get_success_data(
            self.api.create_batch(
                matter_id or self.matter_id,
                f.batch_payload(document_count, **overrides),
                ENGAGEMENT_MANAGER,
            )
        )

    def read_batch(self, batch_id: str) -> dict:
        return get_success_data(self.api.get_batch(batch_id, ENGAGEMENT_MANAGER))

    def batch_version(self, batch_id: str) -> int:
        return self.read_batch(batch_id)["version"]

    def dissolve_batch(self, batch_id: str) -> dict:
        return get_success_data(
            self.api.dissolve_batch(batch_id, ENGAGEMENT_MANAGER)
        )

    def release_batch(self, batch_id: str) -> dict:
        return get_success_data(self.api.release_batch(batch_id, QC_LEAD))

    # -- assignments ---------------------------------------------------
    def assign(
        self,
        batch_id: str,
        reviewer_id: str,
        pass_type: str = "FIRST_PASS",
        expected_batch_version: int | None = None,
    ) -> dict:
        version = (
            expected_batch_version
            if expected_batch_version is not None
            else self.batch_version(batch_id)
        )
        return get_success_data(
            self.api.create_assignment(
                batch_id,
                f.assignment_payload(version, reviewer_id, pass_type),
                STAFFING_COORDINATOR,
            )
        )

    def auto_assign(
        self,
        batch_id: str,
        pass_type: str = "FIRST_PASS",
        expected_batch_version: int | None = None,
    ) -> dict:
        version = (
            expected_batch_version
            if expected_batch_version is not None
            else self.batch_version(batch_id)
        )
        return get_success_data(
            self.api.auto_assign(
                batch_id,
                f.auto_assign_payload(version, pass_type),
                STAFFING_COORDINATOR,
            )
        )

    def read_assignment(self, assignment_id: str) -> dict:
        return get_success_data(
            self.api.get_assignment(assignment_id, STAFFING_COORDINATOR)
        )

    def start(self, assignment_id: str, reviewer_id: str) -> dict:
        return get_success_data(
            self.api.start_assignment(
                assignment_id, make_reviewer_headers(reviewer_id)
            )
        )

    def progress(
        self,
        assignment_id: str,
        reviewer_id: str,
        documents_coded: int,
        minutes_logged: int,
        privilege_hits_logged: int = 0,
    ) -> dict:
        return get_success_data(
            self.api.record_progress(
                assignment_id,
                f.progress_payload(
                    documents_coded,
                    minutes_logged,
                    privilege_hits_logged=privilege_hits_logged,
                ),
                make_reviewer_headers(reviewer_id),
            )
        )

    def submit(self, assignment_id: str, reviewer_id: str) -> dict:
        return get_success_data(
            self.api.submit_assignment(
                assignment_id, make_reviewer_headers(reviewer_id)
            )
        )

    def void(self, assignment_id: str, void_reason: str) -> dict:
        return get_success_data(
            self.api.void_assignment(
                assignment_id, f.void_payload(void_reason), STAFFING_COORDINATOR
            )
        )

    def matter_ledger(
        self, matter_id: str | None = None, entry_type: str | None = None
    ) -> list[dict]:
        return get_success_data(
            self.api.list_matter_budget_ledger(
                matter_id or self.matter_id,
                ENGAGEMENT_MANAGER,
                entry_type=entry_type,
                limit=100,
            )
        )

    def assignment_ledger(
        self, assignment_id: str, entry_type: str | None = None
    ) -> list[dict]:
        return get_success_data(
            self.api.list_assignment_budget_ledger(
                assignment_id,
                ENGAGEMENT_MANAGER,
                entry_type=entry_type,
                limit=100,
            )
        )

    def spend_projection(
        self, matter_id: str | None = None, basis: str | None = None
    ) -> dict:
        return get_success_data(
            self.api.get_spend_projection(
                matter_id or self.matter_id, ENGAGEMENT_MANAGER, basis=basis
            )
        )

    # -- quality control ----------------------------------------------
    def draw_sample(self, batch_id: str, validator_id: str) -> dict:
        return get_success_data(
            self.api.create_qc_sample(
                batch_id, f.qc_sample_payload(validator_id), QC_LEAD
            )
        )

    def validate_sample(
        self,
        sample_id: str,
        coding_error_count: int,
        privilege_error_count: int = 0,
    ) -> dict:
        return get_success_data(
            self.api.validate_qc_sample(
                sample_id,
                f.qc_validate_payload(coding_error_count, privilege_error_count),
                QC_LEAD,
            )
        )

    # -- privilege log -------------------------------------------------
    def log_privilege(
        self,
        batch_id: str,
        reviewer_id: str,
        document_ref: str,
        privilege_basis: str = "ATTORNEY_CLIENT",
        disposition: str = "WITHHELD",
    ) -> dict:
        return get_success_data(
            self.api.create_privilege_entry(
                batch_id,
                f.privilege_entry_payload(
                    document_ref, privilege_basis, disposition
                ),
                make_reviewer_headers(reviewer_id),
            )
        )

    def accept_privilege(self, entry_id: str) -> dict:
        return get_success_data(
            self.api.validate_privilege_entry(
                entry_id, f.privilege_validate_payload(True), QC_LEAD
            )
        )

    def challenge_privilege(self, entry_id: str, note: str) -> dict:
        return get_success_data(
            self.api.validate_privilege_entry(
                entry_id,
                f.privilege_validate_payload(False, challenge_note=note),
                QC_LEAD,
            )
        )

    def amend_privilege(
        self,
        entry_id: str,
        reviewer_id: str,
        privilege_basis: str,
        disposition: str,
    ) -> dict:
        return get_success_data(
            self.api.amend_privilege_entry(
                entry_id,
                f.privilege_amend_payload(privilege_basis, disposition),
                make_reviewer_headers(reviewer_id),
            )
        )


# ---------------------------------------------------------------------------
# Tier 1 — the bare API surface and the clock
# ---------------------------------------------------------------------------
@pytest.fixture
def api() -> ApiClient:
    """A client bound to the server under test."""
    return ApiClient()


@pytest.fixture
def ladder(api: ApiClient) -> ReviewLadder:
    """A setup ladder with the logical clock pinned at its startup default."""
    rungs = ReviewLadder(api)
    rungs.set_clock(CLOCK_START_UTC)
    return rungs


# ---------------------------------------------------------------------------
# Tier 2 — client and matter
# ---------------------------------------------------------------------------
@pytest.fixture
def registered_client(ladder: ReviewLadder) -> dict:
    """One instructing client and nothing else."""
    client = ladder.register_client()
    return {"ladder": ladder, "client": client, "client_id": client["id"]}


@pytest.fixture
def matter_in_intake(registered_client: dict) -> dict:
    """A 600-document matter sitting in INTAKE with no protocol yet."""
    ladder: ReviewLadder = registered_client["ladder"]
    matter = ladder.open_matter()
    return {
        **registered_client,
        "matter": matter,
        "matter_id": matter["id"],
        "matter_version": matter["version"],
    }


@pytest.fixture
def matter_with_draft_protocol(matter_in_intake: dict) -> dict:
    """Revision one minted but not yet sent to the client."""
    ladder: ReviewLadder = matter_in_intake["ladder"]
    protocol = ladder.mint_protocol()
    return {
        **matter_in_intake,
        "protocol": protocol,
        "protocol_id": protocol["id"],
    }


@pytest.fixture
def matter_in_staffing(matter_in_intake: dict) -> dict:
    """Revision one approved, so the matter has opened staffing."""
    ladder: ReviewLadder = matter_in_intake["ladder"]
    protocol = ladder.mint_protocol()
    ladder.submit_protocol(protocol["id"])
    approved = ladder.approve_protocol(protocol["id"])
    return {
        **matter_in_intake,
        "protocol": approved,
        "protocol_id": protocol["id"],
    }


# ---------------------------------------------------------------------------
# Tier 3 — staffed engagement shortcuts
# ---------------------------------------------------------------------------
@pytest.fixture
def staffed_matter(matter_in_staffing: dict) -> dict:
    """Ada fully onboarded with an active onsite session; the matter is IN_REVIEW."""
    ladder: ReviewLadder = matter_in_staffing["ladder"]
    ada = ladder.onboard(REVIEWER_ADA)
    session = ladder.active_session(ada["reviewer_id"])
    return {
        **matter_in_staffing,
        "ada": ada,
        "ada_id": ada["reviewer_id"],
        "ada_headers": ada["headers"],
        "ada_session": session,
        "ada_session_id": session["id"],
    }


@pytest.fixture
def batched_matter(staffed_matter: dict) -> dict:
    """A 400-document batch carved out of the staffed matter, still CREATED."""
    ladder: ReviewLadder = staffed_matter["ladder"]
    batch = ladder.carve_batch(400)
    return {
        **staffed_matter,
        "batch": batch,
        "batch_id": batch["id"],
        "batch_version": batch["version"],
    }


@pytest.fixture
def assigned_batch(batched_matter: dict) -> dict:
    """Ada assigned to the 400-document batch on the first pass."""
    ladder: ReviewLadder = batched_matter["ladder"]
    assignment = ladder.assign(
        batched_matter["batch_id"],
        batched_matter["ada_id"],
        "FIRST_PASS",
        batched_matter["batch_version"],
    )
    return {
        **batched_matter,
        "assignment": assignment,
        "assignment_id": assignment["id"],
    }


@pytest.fixture
def started_assignment(assigned_batch: dict) -> dict:
    """Ada has begun coding; the batch is IN_PROGRESS."""
    ladder: ReviewLadder = assigned_batch["ladder"]
    started = ladder.start(assigned_batch["assignment_id"], assigned_batch["ada_id"])
    return {**assigned_batch, "assignment": started}


@pytest.fixture
def submitted_assignment(started_assignment: dict) -> dict:
    """All 400 documents coded in 420 minutes and submitted, so billing has run."""
    ladder: ReviewLadder = started_assignment["ladder"]
    ladder.progress(
        started_assignment["assignment_id"], started_assignment["ada_id"], 400, 420
    )
    submitted = ladder.submit(
        started_assignment["assignment_id"], started_assignment["ada_id"]
    )
    return {**started_assignment, "assignment": submitted}


@pytest.fixture
def qc_validator(submitted_assignment: dict) -> dict:
    """Cleo sourced as a validator who holds no assignment on the batch."""
    ladder: ReviewLadder = submitted_assignment["ladder"]
    cleo = ladder.source_reviewer(REVIEWER_CLEO)
    return {**submitted_assignment, "cleo": cleo, "cleo_id": cleo["id"]}


@pytest.fixture
def drawn_sample(qc_validator: dict) -> dict:
    """A pending 40-document sample drawn on the submitted batch."""
    ladder: ReviewLadder = qc_validator["ladder"]
    sample = ladder.draw_sample(qc_validator["batch_id"], qc_validator["cleo_id"])
    return {**qc_validator, "sample": sample, "sample_id": sample["id"]}


@pytest.fixture
def failed_sample(drawn_sample: dict) -> dict:
    """The sample failed on three coding errors, reopening Ada's assignment."""
    ladder: ReviewLadder = drawn_sample["ladder"]
    validated = ladder.validate_sample(drawn_sample["sample_id"], 3, 0)
    return {**drawn_sample, "sample": validated}


@pytest.fixture
def passed_sample(drawn_sample: dict) -> dict:
    """The sample passed on a single coding error, carrying the batch to QC_PASSED."""
    ladder: ReviewLadder = drawn_sample["ladder"]
    validated = ladder.validate_sample(drawn_sample["sample_id"], 1, 0)
    return {**drawn_sample, "sample": validated}


# ---------------------------------------------------------------------------
# Tier 4 — accumulation and threshold targeting
# ---------------------------------------------------------------------------
@pytest.fixture
def two_reviewer_matter(matter_in_staffing: dict) -> dict:
    """Ada and Ben both onboarded; Ben carries the remote-work addendum."""
    ladder: ReviewLadder = matter_in_staffing["ladder"]
    ada = ladder.onboard(REVIEWER_ADA)
    ben = ladder.onboard(REVIEWER_BEN, remote_work_addendum=True)
    return {
        **matter_in_staffing,
        "ada": ada,
        "ada_id": ada["reviewer_id"],
        "ada_headers": ada["headers"],
        "ben": ben,
        "ben_id": ben["reviewer_id"],
        "ben_headers": ben["headers"],
    }


@pytest.fixture
def tie_break_pool(matter_in_staffing: dict) -> dict:
    """Ada and Dana onboarded: identical scores, different hourly cost."""
    ladder: ReviewLadder = matter_in_staffing["ladder"]
    ada = ladder.onboard(REVIEWER_ADA)
    dana = ladder.onboard(REVIEWER_DANA)
    batch = ladder.carve_batch(400)
    return {
        **matter_in_staffing,
        "ada": ada,
        "ada_id": ada["reviewer_id"],
        "dana": dana,
        "dana_id": dana["reviewer_id"],
        "batch": batch,
        "batch_id": batch["id"],
        "batch_version": batch["version"],
    }


@pytest.fixture
def score_gap_pool(matter_in_staffing: dict) -> dict:
    """Ada and Dara onboarded: Dara misses the subject tag, so she scores lower."""
    ladder: ReviewLadder = matter_in_staffing["ladder"]
    ada = ladder.onboard(REVIEWER_ADA)
    dara = ladder.onboard(REVIEWER_DARA)
    batch = ladder.carve_batch(400)
    return {
        **matter_in_staffing,
        "ada": ada,
        "ada_id": ada["reviewer_id"],
        "dara": dara,
        "dara_id": dara["reviewer_id"],
        "batch": batch,
        "batch_id": batch["id"],
        "batch_version": batch["version"],
    }


@pytest.fixture
def two_batch_engagement(staffed_matter: dict) -> dict:
    """A 400-document batch and a 200-document batch, both assigned to Ada."""
    ladder: ReviewLadder = staffed_matter["ladder"]
    batch_one = ladder.carve_batch(400)
    first = ladder.assign(
        batch_one["id"], staffed_matter["ada_id"], "FIRST_PASS", batch_one["version"]
    )
    batch_two = ladder.carve_batch(200)
    second = ladder.assign(
        batch_two["id"], staffed_matter["ada_id"], "FIRST_PASS", batch_two["version"]
    )
    return {
        **staffed_matter,
        "batch_one": batch_one,
        "batch_one_id": batch_one["id"],
        "assignment_one": first,
        "assignment_one_id": first["id"],
        "batch_two": batch_two,
        "batch_two_id": batch_two["id"],
        "assignment_two": second,
        "assignment_two_id": second["id"],
    }


@pytest.fixture
def hourly_matter(registered_client: dict) -> dict:
    """An hourly-priced matter with Ada onboarded and two 100-document batches."""
    ladder: ReviewLadder = registered_client["ladder"]
    matter = ladder.open_matter(
        name="Northwind v. Calder — Hourly Tranche", pricing_model="HOURLY"
    )
    ladder.approved_protocol()
    ada = ladder.onboard(REVIEWER_ADA)
    ladder.active_session(ada["reviewer_id"])
    batch_one = ladder.carve_batch(100)
    first = ladder.assign(
        batch_one["id"], ada["reviewer_id"], "FIRST_PASS", batch_one["version"]
    )
    batch_two = ladder.carve_batch(100)
    second = ladder.assign(
        batch_two["id"], ada["reviewer_id"], "FIRST_PASS", batch_two["version"]
    )
    return {
        **registered_client,
        "matter": matter,
        "matter_id": matter["id"],
        "ada": ada,
        "ada_id": ada["reviewer_id"],
        "batch_one_id": batch_one["id"],
        "assignment_one_id": first["id"],
        "batch_two_id": batch_two["id"],
        "assignment_two_id": second["id"],
    }


@pytest.fixture
def capped_matter(registered_client: dict) -> dict:
    """A matter whose budget cap equals exactly one 400-document commitment."""
    ladder: ReviewLadder = registered_client["ladder"]
    matter = ladder.open_matter(
        name="Northwind v. Calder — Fixed-Fee Tranche", budget_cap_cents=85200
    )
    ladder.approved_protocol()
    ada = ladder.onboard(REVIEWER_ADA)
    batch_one = ladder.carve_batch(400)
    batch_two = ladder.carve_batch(100)
    return {
        **registered_client,
        "matter": matter,
        "matter_id": matter["id"],
        "ada": ada,
        "ada_id": ada["reviewer_id"],
        "batch_one": batch_one,
        "batch_one_id": batch_one["id"],
        "batch_one_version": batch_one["version"],
        "batch_two": batch_two,
        "batch_two_id": batch_two["id"],
        "batch_two_version": batch_two["version"],
    }


@pytest.fixture
def tightly_capped_matter(registered_client: dict) -> dict:
    """A matter capped far below one commitment, with a superseded protocol."""
    ladder: ReviewLadder = registered_client["ladder"]
    matter = ladder.open_matter(
        name="Northwind v. Calder — Capped Tranche", budget_cap_cents=50000
    )
    first_protocol = ladder.mint_protocol()
    ladder.submit_protocol(first_protocol["id"])
    ladder.approve_protocol(first_protocol["id"])
    ada = ladder.onboard(REVIEWER_ADA)
    batch = ladder.carve_batch(400)
    return {
        **registered_client,
        "matter": matter,
        "matter_id": matter["id"],
        "first_protocol": first_protocol,
        "first_protocol_id": first_protocol["id"],
        "ada": ada,
        "ada_id": ada["reviewer_id"],
        "batch": batch,
        "batch_id": batch["id"],
        "batch_version": batch["version"],
    }


@pytest.fixture
def standard_tier_matter(registered_client: dict) -> dict:
    """A 100-document standard-tier matter, useful for the small-batch floors."""
    ladder: ReviewLadder = registered_client["ladder"]
    matter = ladder.open_matter(
        name="Northwind v. Calder — Standard Tranche",
        document_count=100,
        complexity_tier="STANDARD",
        budget_cap_cents=400000,
    )
    ladder.approved_protocol()
    ada = ladder.onboard(REVIEWER_ADA)
    ladder.active_session(ada["reviewer_id"])
    return {
        **registered_client,
        "matter": matter,
        "matter_id": matter["id"],
        "ada": ada,
        "ada_id": ada["reviewer_id"],
    }


@pytest.fixture
def second_level_matter(registered_client: dict) -> dict:
    """A matter whose protocol demands a second-level pass, with Ada and Ben."""
    ladder: ReviewLadder = registered_client["ladder"]
    matter = ladder.open_matter(name="Northwind v. Calder — Two-Pass Tranche")
    ladder.approved_protocol(second_level_required=True)
    ada = ladder.onboard(REVIEWER_ADA)
    ben = ladder.onboard(REVIEWER_BEN, remote_work_addendum=True)
    ladder.active_session(ada["reviewer_id"])
    batch = ladder.carve_batch(400)
    return {
        **registered_client,
        "matter": matter,
        "matter_id": matter["id"],
        "ada": ada,
        "ada_id": ada["reviewer_id"],
        "ben": ben,
        "ben_id": ben["reviewer_id"],
        "batch": batch,
        "batch_id": batch["id"],
        "batch_version": batch["version"],
    }


# ---------------------------------------------------------------------------
# Tier 5 — finalisation and terminal state
# ---------------------------------------------------------------------------
@pytest.fixture
def released_batch(staffed_matter: dict) -> dict:
    """The whole 600 documents coded, sampled clean, privilege-validated, released.

    Because every document is batched and the single batch is RELEASED, the
    matter itself has bubbled to QC_CLOSEOUT.
    """
    ladder: ReviewLadder = staffed_matter["ladder"]
    ada_id = staffed_matter["ada_id"]
    batch = ladder.carve_batch(600)
    assignment = ladder.assign(batch["id"], ada_id, "FIRST_PASS", batch["version"])
    ladder.start(assignment["id"], ada_id)
    first_entry = ladder.log_privilege(batch["id"], ada_id, "DOC-000101")
    second_entry = ladder.log_privilege(
        batch["id"], ada_id, "DOC-000207", "WORK_PRODUCT", "REDACTED"
    )
    ladder.progress(assignment["id"], ada_id, 600, 650, privilege_hits_logged=2)
    ladder.submit(assignment["id"], ada_id)
    cleo = ladder.source_reviewer(REVIEWER_CLEO)
    sample = ladder.draw_sample(batch["id"], cleo["id"])
    ladder.validate_sample(sample["id"], 0, 0)
    ladder.accept_privilege(first_entry["id"])
    ladder.accept_privilege(second_entry["id"])
    released = ladder.release_batch(batch["id"])
    return {
        **staffed_matter,
        "batch": released,
        "batch_id": batch["id"],
        "assignment": assignment,
        "assignment_id": assignment["id"],
        "cleo": cleo,
        "cleo_id": cleo["id"],
        "sample_id": sample["id"],
        "first_entry_id": first_entry["id"],
        "second_entry_id": second_entry["id"],
    }


@pytest.fixture
def closed_matter(released_batch: dict) -> dict:
    """The matter closed out of QC_CLOSEOUT; CLOSED is terminal."""
    ladder: ReviewLadder = released_batch["ladder"]
    closed = ladder.close_matter()
    return {**released_batch, "matter": closed}


@pytest.fixture
def partially_batched_closeout(staffed_matter: dict) -> dict:
    """599 of 600 documents released, leaving one document unbatched.

    The single stranded document blocks both the automatic bubble to closeout
    and any attempt to close the matter.
    """
    ladder: ReviewLadder = staffed_matter["ladder"]
    ada_id = staffed_matter["ada_id"]
    batch = ladder.carve_batch(599)
    assignment = ladder.assign(batch["id"], ada_id, "FIRST_PASS", batch["version"])
    ladder.start(assignment["id"], ada_id)
    first_entry = ladder.log_privilege(batch["id"], ada_id, "DOC-000101")
    second_entry = ladder.log_privilege(
        batch["id"], ada_id, "DOC-000207", "WORK_PRODUCT", "REDACTED"
    )
    ladder.progress(assignment["id"], ada_id, 599, 650, privilege_hits_logged=2)
    ladder.submit(assignment["id"], ada_id)
    cleo = ladder.source_reviewer(REVIEWER_CLEO)
    sample = ladder.draw_sample(batch["id"], cleo["id"])
    ladder.validate_sample(sample["id"], 0, 0)
    ladder.accept_privilege(first_entry["id"])
    ladder.accept_privilege(second_entry["id"])
    released = ladder.release_batch(batch["id"])
    return {
        **staffed_matter,
        "batch": released,
        "batch_id": batch["id"],
        "assignment_id": assignment["id"],
        "cleo_id": cleo["id"],
        "first_entry_id": first_entry["id"],
        "second_entry_id": second_entry["id"],
    }
