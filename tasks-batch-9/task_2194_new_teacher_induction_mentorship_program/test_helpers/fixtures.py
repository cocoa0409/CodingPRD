"""Composite setup helpers and pytest fixtures.

The API server is restarted before every individual test, so each test starts
against an empty district.  Every precondition below is therefore built from
scratch through the documented endpoints — nothing is seeded out of band.
"""

from typing import Any, Callable, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import InductionApiClient
from .test_users import (
    ADMIN,
    APPROVER,
    PREPARER,
    make_mentor_headers,
    make_site_lead_headers,
)

# ----------------------------------------------------------------------
# Primitive setup steps
# ----------------------------------------------------------------------


def set_clock(api: InductionApiClient, current_utc: str, headers: Dict[str, str] = ADMIN) -> Dict[str, Any]:
    """Move the server's logical UTC clock."""
    return get_success_data(api.set_clock(current_utc, headers))


def create_site(api: InductionApiClient, headers: Dict[str, str] = ADMIN, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_site(f.site_payload(**overrides), headers))


def create_cohort(api: InductionApiClient, headers: Dict[str, str] = ADMIN, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_cohort(f.cohort_payload(**overrides), headers))


def create_mentor(
    api: InductionApiClient, site_id: str, headers: Dict[str, str] = ADMIN, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(api.create_mentor(f.mentor_payload(site_id, **overrides), headers))


def post_certify_training(api: InductionApiClient, mentor_id: str) -> Dict[str, Any]:
    """Post the hours and the three initial modules a CERTIFY action requires."""
    get_success_data(
        api.post_training_credit(
            mentor_id,
            f.training_credit_payload("FOUNDATIONS", 8.00, completed_on="2026-07-10"),
            ADMIN,
        )
    )
    get_success_data(
        api.post_training_credit(
            mentor_id,
            f.training_credit_payload("OBSERVATION_PROTOCOL", 6.00, completed_on="2026-07-11"),
            ADMIN,
        )
    )
    return get_success_data(
        api.post_training_credit(
            mentor_id,
            f.training_credit_payload("EQUITY", 4.00, completed_on="2026-07-12"),
            ADMIN,
        )
    )


def certify_mentor(api: InductionApiClient, mentor_id: str) -> Dict[str, Any]:
    """Train and certify a mentor; returns the updated mentor row."""
    post_certify_training(api, mentor_id)
    return get_success_data(api.certification_action(mentor_id, f.certification_payload("CERTIFY"), ADMIN))


def create_certified_mentor(
    api: InductionApiClient, site_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Register a mentor and drive it to CERTIFIED in one step."""
    mentor = create_mentor(api, site_id, **overrides)
    return certify_mentor(api, mentor["id"])


def create_novice(
    api: InductionApiClient,
    site_id: str,
    cohort_id: str,
    headers: Dict[str, str] = ADMIN,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_novice(f.novice_payload(site_id, cohort_id, **overrides), headers)
    )


def propose_match(
    api: InductionApiClient,
    novice_id: str,
    expected_mentor_version: int,
    mentor_id: Optional[str] = None,
    headers: Dict[str, str] = ADMIN,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_match(
            f.match_payload(novice_id, expected_mentor_version, mentor_id, **overrides), headers
        )
    )


def activate_match(
    api: InductionApiClient, match_id: str, headers: Dict[str, str] = ADMIN
) -> Dict[str, Any]:
    return get_success_data(api.dispose_match(match_id, f.disposition_payload("ACTIVATE"), headers))


def submit_contact_log(
    api: InductionApiClient,
    match_id: str,
    contact_date: str,
    minutes: int = 60,
    contact_type: str = "ONE_ON_ONE",
    headers: Optional[Dict[str, str]] = None,
    mentor_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Submit a contact log as the mentor on the match unless told otherwise."""
    if headers is None:
        assert mentor_id is not None, "submit_contact_log needs mentor_id or explicit headers"
        headers = make_mentor_headers(mentor_id)
    return get_success_data(
        api.create_contact_log(
            f.contact_log_payload(match_id, contact_date, minutes, contact_type, **overrides),
            headers,
        )
    )


def verify_contact_log(
    api: InductionApiClient, log_id: str, headers: Dict[str, str] = ADMIN, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.review_contact_log(log_id, f.review_payload("VERIFY", **overrides), headers)
    )


def submit_and_verify_contact_log(
    api: InductionApiClient,
    match_id: str,
    mentor_id: str,
    contact_date: str,
    minutes: int = 60,
    contact_type: str = "ONE_ON_ONE",
    verifier: Dict[str, str] = ADMIN,
    **overrides: Any,
) -> Dict[str, Any]:
    """Submit a log as the mentor and verify it as somebody else."""
    log = submit_contact_log(
        api, match_id, contact_date, minutes, contact_type, mentor_id=mentor_id, **overrides
    )
    return verify_contact_log(api, log["id"], verifier)


def open_observation_cycle(
    api: InductionApiClient,
    match_id: str,
    mentor_id: str,
    cycle_index: int,
    window_start: str,
    window_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_observation_cycle(
            f.observation_cycle_payload(
                match_id, cycle_index, window_start, window_end, **overrides
            ),
            make_mentor_headers(mentor_id),
        )
    )


def document_observation_cycle(
    api: InductionApiClient,
    cycle_id: str,
    mentor_id: str,
    site_id: str,
    rubric_scores: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Drive a cycle whose window has closed all the way to DOCUMENTED."""
    mentor_headers = make_mentor_headers(mentor_id)
    get_success_data(api.advance_cycle(cycle_id, f.advance_payload("OBSERVED"), mentor_headers))
    get_success_data(
        api.advance_cycle(cycle_id, f.advance_payload("POST_CONFERENCE"), mentor_headers)
    )
    get_success_data(
        api.write_feedback(
            cycle_id, f.feedback_payload(submit=True, rubric_scores=rubric_scores), mentor_headers
        )
    )
    get_success_data(
        api.review_feedback(
            cycle_id, f.feedback_review_payload("ACCEPT"), make_site_lead_headers(site_id)
        )
    )
    return get_success_data(
        api.advance_cycle(cycle_id, f.advance_payload("DOCUMENTED"), mentor_headers)
    )


def schedule_seminar_session(
    api: InductionApiClient,
    cohort_id: str,
    session_index: int,
    scheduled_start: str,
    scheduled_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_seminar_session(
            f.seminar_session_payload(
                cohort_id, session_index, scheduled_start, scheduled_end, **overrides
            ),
            ADMIN,
        )
    )


def record_attendance(
    api: InductionApiClient,
    session_id: str,
    novice_id: str,
    attendance_status: str = "PRESENT",
    minutes_attended: int = 120,
    headers: Dict[str, str] = ADMIN,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_attendance(
            f.attendance_payload(
                session_id, novice_id, attendance_status, minutes_attended, **overrides
            ),
            headers,
        )
    )


def hold_session(api: InductionApiClient, session_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.set_session_status(session_id, f.session_status_payload("HELD"), ADMIN)
    )


def define_milestone(
    api: InductionApiClient, code: str, sequence_index: int, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_milestone(f.milestone_payload(code, sequence_index, **overrides), ADMIN)
    )


def attainment_for(
    api: InductionApiClient, novice_id: str, milestone_id: str
) -> Dict[str, Any]:
    """Return the novice's attainment row for one milestone.

    Enrolment seeds "one attainment row for every milestone definition currently
    in the catalogue", so a milestone defined *before* the novice was enrolled
    already has its row.  A milestone defined afterwards has none, and the PRD's
    own answer for that case is the explicit creation endpoint: "Explicit
    creation exists only for milestones introduced after a cohort is already
    under way; it takes ``novice_id``, ``milestone_id`` and an optional
    ``evidence_note``."  This helper therefore reads the seeded row when one
    exists and opens the row through that documented endpoint when it does not.
    """
    rows, _ = _list(api.list_attainments(ADMIN, {"novice_id": novice_id, "limit": 100}))
    for row in rows:
        if row["milestone_id"] == milestone_id:
            return row
    return get_success_data(
        api.create_attainment(f.attainment_payload(novice_id, milestone_id), ADMIN),
        201,
    )


#: The PRD names the milestone-attainment decisions in prose ("Attest, revoke or
#: reopen a milestone attainment") rather than as literal enum members, so the
#: attestation verb has two defensible spellings.  Requests below try one and
#: fall back to the other when the first is refused as an unknown enum member;
#: an unknown enum member is a 400 and mutates nothing, so the fallback is safe.
_ATTEST_SPELLINGS = ("ATTEST", "ATTAIN")


def attainment_decision_request(
    api: InductionApiClient,
    attainment_id: str,
    decision: str,
    headers: Dict[str, str] = ADMIN,
    **overrides: Any,
):
    """POST an attainment decision, tolerating either spelling of the attest verb."""
    spellings = _ATTEST_SPELLINGS if decision in _ATTEST_SPELLINGS else (decision,)
    response = None
    for spelling in spellings:
        response = api.attainment_decision(
            attainment_id, f.attainment_decision_payload(spelling, **overrides), headers
        )
        if not (response.status_code == 400):
            return response
    return response


def attest_attainment(
    api: InductionApiClient,
    attainment_id: str,
    headers: Dict[str, str] = ADMIN,
    **overrides: Any,
) -> Dict[str, Any]:
    """Drive an IN_PROGRESS attainment row to ATTAINED."""
    return get_success_data(
        attainment_decision_request(api, attainment_id, "ATTEST", headers, **overrides)
    )


def revoke_attainment(
    api: InductionApiClient,
    attainment_id: str,
    headers: Dict[str, str] = ADMIN,
    **overrides: Any,
) -> Dict[str, Any]:
    """Drive an ATTAINED attainment row to REVOKED."""
    return get_success_data(
        attainment_decision_request(api, attainment_id, "REVOKE", headers, **overrides)
    )


def _list(response) -> tuple:
    body = get_success_data(response)
    return body, response.json()["meta"]


def draft_disbursement(
    api: InductionApiClient,
    mentor_id: str,
    expected_mentor_version: int,
    headers: Dict[str, str] = PREPARER,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_disbursement(
            f.disbursement_payload(mentor_id, expected_mentor_version, **overrides), headers
        )
    )


def approve_disbursement(
    api: InductionApiClient, disbursement_id: str, headers: Dict[str, str] = APPROVER
) -> Dict[str, Any]:
    return get_success_data(
        api.set_disbursement_status(
            disbursement_id, f.disbursement_status_payload("APPROVED"), headers
        )
    )


def pay_disbursement(
    api: InductionApiClient,
    disbursement_id: str,
    headers: Dict[str, str] = APPROVER,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.set_disbursement_status(
            disbursement_id, f.disbursement_status_payload("PAID", **overrides), headers
        )
    )


def assemble_packet(
    api: InductionApiClient,
    novice_id: str,
    expected_novice_version: int,
    headers: Dict[str, str] = ADMIN,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_packet(
            f.packet_payload(novice_id, expected_novice_version, **overrides), headers
        )
    )


# ----------------------------------------------------------------------
# Fresh reads
# ----------------------------------------------------------------------


def read_site(api: InductionApiClient, site_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_site(site_id, ADMIN))


def read_mentor(api: InductionApiClient, mentor_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_mentor(mentor_id, ADMIN))


def read_cohort(api: InductionApiClient, cohort_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_cohort(cohort_id, ADMIN))


def read_novice(api: InductionApiClient, novice_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_novice(novice_id, ADMIN))


def read_readiness(api: InductionApiClient, novice_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_readiness(novice_id, ADMIN))


def read_match(api: InductionApiClient, match_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_match(match_id, ADMIN))


def read_contact_log(api: InductionApiClient, log_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_contact_log(log_id, ADMIN))


def read_cycle(api: InductionApiClient, cycle_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_observation_cycle(cycle_id, ADMIN))


def read_session(api: InductionApiClient, session_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_seminar_session(session_id, ADMIN))


def read_attainment(api: InductionApiClient, attainment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_attainment(attainment_id, ADMIN))


def read_disbursement(api: InductionApiClient, disbursement_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_disbursement(disbursement_id, ADMIN))


def read_packet(api: InductionApiClient, packet_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_packet(packet_id, ADMIN))


# ----------------------------------------------------------------------
# Tier-2 composite: the canonical mentoring relationship
# ----------------------------------------------------------------------


def build_program(
    api: InductionApiClient,
    site_overrides: Optional[Dict[str, Any]] = None,
    cohort_overrides: Optional[Dict[str, Any]] = None,
    mentor_overrides: Optional[Dict[str, Any]] = None,
    novice_overrides: Optional[Dict[str, Any]] = None,
    activate: bool = True,
) -> Dict[str, Any]:
    """Site, cohort, certified mentor, enrolled novice and their match.

    Returns a dict carrying every created row plus the mentor version observed
    at proposal time, which is what the match proposal had to prove it read.
    """
    site = create_site(api, **(site_overrides or {}))
    cohort = create_cohort(api, **(cohort_overrides or {}))
    mentor = create_certified_mentor(api, site["id"], **(mentor_overrides or {}))
    novice = create_novice(api, site["id"], cohort["id"], **(novice_overrides or {}))
    match = propose_match(api, novice["id"], mentor["version"], mentor["id"])
    if activate:
        match = activate_match(api, match["id"])
    return {
        "site": site,
        "site_id": site["id"],
        "cohort": cohort,
        "cohort_id": cohort["id"],
        "mentor": mentor,
        "mentor_id": mentor["id"],
        "mentor_version_at_proposal": mentor["version"],
        "novice": novice,
        "novice_id": novice["id"],
        "match": match,
        "match_id": match["id"],
    }


# ----------------------------------------------------------------------
# Pytest fixtures
# ----------------------------------------------------------------------


@pytest.fixture
def api() -> InductionApiClient:
    """A client pointed at the API under test."""
    return InductionApiClient()


@pytest.fixture
def program(api: InductionApiClient) -> Dict[str, Any]:
    """The canonical active mentoring relationship at a single site."""
    return build_program(api)


@pytest.fixture
def proposed_program(api: InductionApiClient) -> Dict[str, Any]:
    """The same relationship left in PROPOSED rather than activated."""
    return build_program(api, activate=False)


@pytest.fixture
def program_factory(api: InductionApiClient) -> Callable[..., Dict[str, Any]]:
    """A builder for variant programs (caps, subjects, activation)."""

    def _build(**kwargs: Any) -> Dict[str, Any]:
        return build_program(api, **kwargs)

    return _build


@pytest.fixture
def site(api: InductionApiClient) -> Dict[str, Any]:
    """A single open site."""
    return create_site(api)


@pytest.fixture
def cohort(api: InductionApiClient) -> Dict[str, Any]:
    """A single forming cohort."""
    return create_cohort(api)


def all_rows(api: InductionApiClient, lister: Callable, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Read a filtered collection with the maximum page size."""
    merged = dict(params)
    merged.setdefault("limit", 100)
    return get_success_data(lister(ADMIN, merged))
