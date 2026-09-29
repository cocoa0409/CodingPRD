"""Composite state builders.

Almost every rule in this PRD sits behind a chain of prerequisites: a credential
only exists after a programme has been created and activated, an item authored,
submitted and twice approved, statistics ingested, a form assembled, rated,
cut-scored and published, a candidate created, an application filed and both
dimensions verified, a session created, a seat reserved, a sitting checked in,
responses submitted and a score reported. The builders below construct exactly
those chains, in progressive prefixes, so a test states only the step it is
actually about.

Every builder threads identities correctly: continuing-education claims and
cycle transitions are performed as the acting ``Candidate`` behind the
credential, because ownership is decided by comparing the addressed
certificant's ``candidate_id`` to ``X-User-ID``.

The harness restarts the server and empties the store before each test, so each
builder starts from nothing and never assumes a leftover row.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import DEFAULT_CLOCK
from .test_users import (
    ELIGIBILITY_REVIEWER_1_ID,
    ELIGIBILITY_REVIEWER_2_ID,
    ELIGIBILITY_REVIEWER_3_ID,
    ETHICS_OFFICER_1_ID,
    ITEM_AUTHOR_ID,
    ITEM_REVIEWER_1_ID,
    ITEM_REVIEWER_2_ID,
    PANELIST_IDS,
    PSYCHOMETRICIAN_ID,
    TEST_USERS,
    make_certificant_headers,
    make_eligibility_reviewer_headers,
    make_ethics_officer_headers,
    make_item_specialist_headers,
    make_panelist_headers,
    make_psychometrician_headers,
)

PROGRAM_ADMIN = TEST_USERS["program_admin_headers"]
ITEM_AUTHOR = TEST_USERS["item_author_headers"]
PSYCHOMETRICIAN = TEST_USERS["psychometrician_headers"]
EXAM_OPERATIONS = TEST_USERS["exam_operations_headers"]
ELIGIBILITY_REVIEWER_1 = TEST_USERS["eligibility_reviewer_1_headers"]
ELIGIBILITY_REVIEWER_2 = TEST_USERS["eligibility_reviewer_2_headers"]
ELIGIBILITY_REVIEWER_3 = TEST_USERS["eligibility_reviewer_3_headers"]


# ---------------------------------------------------------------------------
# The state carried between steps
# ---------------------------------------------------------------------------


@dataclass
class Pipeline:
    """Identifiers and version tokens produced by the delivery chain."""

    program_id: Optional[str] = None
    item_id: Optional[str] = None
    item_ids: List[str] = field(default_factory=list)
    form_id: Optional[str] = None
    form_version: Optional[int] = None
    candidate_id: Optional[str] = None
    application_id: Optional[str] = None
    session_id: Optional[str] = None
    session_version: Optional[int] = None
    registration_id: Optional[str] = None
    certificant_id: Optional[str] = None
    certificant_version: Optional[int] = None
    certificate_number: Optional[str] = None
    cycle_id: Optional[str] = None

    @property
    def owner_headers(self) -> Dict[str, str]:
        """Headers for the credential holder: the ``Certificant`` role carrying
        the acting ``Candidate``'s identifier.
        """
        assert self.candidate_id is not None, "no candidate has been created yet"
        return make_certificant_headers(self.candidate_id)


# ---------------------------------------------------------------------------
# Tier 1 — single-entity builders
# ---------------------------------------------------------------------------


def set_clock(client: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock. Setting the clock never mutates a stored record."""
    return get_success_data(
        client.set_clock(f.set_clock_payload(current_utc), EXAM_OPERATIONS))


def reset_clock(client: ApiClient) -> Dict[str, Any]:
    return set_clock(client, DEFAULT_CLOCK)


def create_program(client: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        client.create_program(f.create_program_payload(**overrides), PROGRAM_ADMIN))


def active_program(client: ApiClient, **overrides) -> Dict[str, Any]:
    """A programme in ``ACTIVE`` status — the precondition for accepting
    applications and publishing forms.
    """
    program = create_program(client, **overrides)
    get_success_data(
        client.activate_program(program["id"], f.activate_program_payload(), PROGRAM_ADMIN))
    return get_success_data(client.get_program(program["id"], PROGRAM_ADMIN))


def create_candidate(client: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        client.create_candidate(f.create_candidate_payload(**overrides), EXAM_OPERATIONS))


def create_test_center_session(client: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        client.create_exam_session(
            f.create_test_center_session_payload(**overrides), EXAM_OPERATIONS))


def create_online_session(client: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        client.create_exam_session(
            f.create_online_session_payload(**overrides), EXAM_OPERATIONS))


# ---------------------------------------------------------------------------
# Tier 2 — item authoring and statistics
# ---------------------------------------------------------------------------


def draft_item(client: ApiClient, program_id: str, author_user_id: str = ITEM_AUTHOR_ID,
               **overrides) -> Dict[str, Any]:
    """A newly authored item: ``DRAFT``, every accumulator zero."""
    return get_success_data(
        client.create_item(f.create_item_payload(program_id, **overrides),
                           make_item_specialist_headers(author_user_id)))


def item_in_review(client: ApiClient, program_id: str, author_user_id: str = ITEM_AUTHOR_ID,
                   **overrides) -> Dict[str, Any]:
    item = draft_item(client, program_id, author_user_id, **overrides)
    return get_success_data(
        client.submit_item_for_review(item["id"], f.submit_item_payload(),
                                      make_item_specialist_headers(author_user_id)))


def approved_item(client: ApiClient, program_id: str, author_user_id: str = ITEM_AUTHOR_ID,
                  reviewer_user_ids: Optional[List[str]] = None, **overrides) -> Dict[str, Any]:
    """An item promoted to ``APPROVED`` by two distinct non-author approvals."""
    reviewers = reviewer_user_ids or [ITEM_REVIEWER_1_ID, ITEM_REVIEWER_2_ID]
    item = item_in_review(client, program_id, author_user_id, **overrides)
    result = item
    for reviewer in reviewers:
        result = get_success_data(
            client.review_item(item["id"], f.review_item_payload("APPROVE"),
                               make_item_specialist_headers(reviewer)))
    return result


def operational_item(client: ApiClient, program_id: str,
                     batch: Optional[Dict[str, Any]] = None,
                     author_user_id: str = ITEM_AUTHOR_ID,
                     **overrides) -> Dict[str, Any]:
    """An item carrying enough responses to compute statistics and clear the
    flagging thresholds, which promotes it to ``OPERATIONAL``.
    """
    item = approved_item(client, program_id, author_user_id, **overrides)
    payload = batch if batch is not None else f.response_batch_payload()
    return get_success_data(
        client.ingest_response_batch(item["id"], payload, PSYCHOMETRICIAN))


def ingest_batch(client: ApiClient, item_id: str, psychometrician_user_id: str = PSYCHOMETRICIAN_ID,
                 **batch_overrides) -> Dict[str, Any]:
    return get_success_data(
        client.ingest_response_batch(item_id, f.response_batch_payload(**batch_overrides),
                                     make_psychometrician_headers(psychometrician_user_id)))


# ---------------------------------------------------------------------------
# Tier 3 — form assembly, standard setting and publication
# ---------------------------------------------------------------------------


def assembled_form(client: ApiClient, program_id: str, item_ids: List[str],
                   panelist_user_ids: Optional[List[str]] = None, **overrides) -> Dict[str, Any]:
    return get_success_data(
        client.create_form(
            f.create_form_payload(program_id, item_ids, panelist_user_ids, **overrides),
            PSYCHOMETRICIAN))


def submit_ratings(client: ApiClient, form_id: str,
                   ratings: List[Any]) -> Dict[str, Any]:
    """Submit one rating per entry.

    ``ratings`` entries are either a bare rate (assigned to ``pan-1``, ``pan-2``,
    … in order) or an explicit ``(panelist_user_id, rate)`` pair.
    """
    result: Dict[str, Any] = {}
    for index, entry in enumerate(ratings):
        if isinstance(entry, (tuple, list)):
            panelist_user_id, rate = entry
        else:
            panelist_user_id, rate = PANELIST_IDS[index], entry
        result = get_success_data(
            client.submit_panel_rating(
                form_id, f.panel_rating_payload(panelist_user_id, rate),
                make_panelist_headers(panelist_user_id)))
    return result


def rated_form(client: ApiClient, program_id: str, item_ids: List[str],
               ratings: Optional[List[Any]] = None,
               panelist_user_ids: Optional[List[str]] = None,
               **overrides) -> Dict[str, Any]:
    """A form whose panel has finished rating; the returned body carries the
    version token that adopting the cut score will demand.
    """
    form = assembled_form(client, program_id, item_ids, panelist_user_ids, **overrides)
    return submit_ratings(client, form["id"], ratings if ratings is not None else [0.6])


def cut_score_form(client: ApiClient, form_id: str, expected_form_version: int,
                   adopter_user_id: str = PSYCHOMETRICIAN_ID) -> Dict[str, Any]:
    return get_success_data(
        client.adopt_cut_score(form_id, f.adopt_cut_score_payload(expected_form_version),
                               make_psychometrician_headers(adopter_user_id)))


def published_form(client: ApiClient, program_id: str, item_ids: List[str],
                   ratings: Optional[List[Any]] = None,
                   panelist_user_ids: Optional[List[str]] = None,
                   **overrides) -> Dict[str, Any]:
    """A form in ``PUBLISHED`` status — the only kind a registration accepts."""
    rated = rated_form(client, program_id, item_ids, ratings, panelist_user_ids, **overrides)
    cut_score_form(client, rated["id"], rated["version"])
    return get_success_data(
        client.publish_form(rated["id"], f.publish_form_payload(), PROGRAM_ADMIN))


# ---------------------------------------------------------------------------
# Tier 3 — eligibility
# ---------------------------------------------------------------------------


def submitted_application(client: ApiClient, candidate_id: str, program_id: str,
                          reviewer_user_id: str = ELIGIBILITY_REVIEWER_1_ID,
                          **overrides) -> Dict[str, Any]:
    return get_success_data(
        client.create_application(
            f.create_application_payload(candidate_id, program_id, **overrides),
            make_eligibility_reviewer_headers(reviewer_user_id)))


def approved_application(client: ApiClient, candidate_id: str, program_id: str,
                         education_reviewer_user_id: str = ELIGIBILITY_REVIEWER_1_ID,
                         experience_reviewer_user_id: str = ELIGIBILITY_REVIEWER_2_ID,
                         **overrides) -> Dict[str, Any]:
    """An application whose education and experience dimensions have both been
    verified, which — with the attestation signed on submission — approves it.
    """
    application = submitted_application(client, candidate_id, program_id,
                                        education_reviewer_user_id, **overrides)
    get_success_data(
        client.verify_application_dimension(
            application["id"], f.verify_dimension_payload("EDUCATION", "PASS"),
            make_eligibility_reviewer_headers(education_reviewer_user_id)))
    return get_success_data(
        client.verify_application_dimension(
            application["id"], f.verify_dimension_payload("EXPERIENCE", "PASS"),
            make_eligibility_reviewer_headers(experience_reviewer_user_id)))


# ---------------------------------------------------------------------------
# Tier 4 — registration, seating and delivery
# ---------------------------------------------------------------------------


def create_registration(client: ApiClient, application_id: str, form_id: str,
                        fee_paid_cents: int = 45000, **overrides) -> Dict[str, Any]:
    return get_success_data(
        client.create_exam_registration(
            f.create_registration_payload(application_id, form_id, fee_paid_cents, **overrides),
            EXAM_OPERATIONS))


def schedule_seat(client: ApiClient, registration_id: str, session_id: str,
                  expected_session_version: int) -> Dict[str, Any]:
    return get_success_data(
        client.schedule_seat(
            registration_id, f.schedule_seat_payload(session_id, expected_session_version),
            EXAM_OPERATIONS))


def check_in(client: ApiClient, registration_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.check_in(registration_id, f.check_in_payload(), EXAM_OPERATIONS))


def submit_responses(client: ApiClient, registration_id: str, raw_score: int) -> Dict[str, Any]:
    return get_success_data(
        client.submit_responses(registration_id, f.submit_responses_payload(raw_score),
                                EXAM_OPERATIONS))


def report_score(client: ApiClient, registration_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.report_score(registration_id, f.report_score_payload(), EXAM_OPERATIONS))


# ---------------------------------------------------------------------------
# The delivery chain, in progressive prefixes
# ---------------------------------------------------------------------------


def pipeline_through_ratings(client: ApiClient,
                             program_overrides: Optional[Dict[str, Any]] = None,
                             item_overrides: Optional[Dict[str, Any]] = None,
                             batch: Optional[Dict[str, Any]] = None,
                             form_overrides: Optional[Dict[str, Any]] = None,
                             ratings: Optional[List[Any]] = None,
                             panelist_user_ids: Optional[List[str]] = None) -> Pipeline:
    """Active programme, one operational item, an assembled form whose panel has
    rated it. Stops short of adopting the cut score.
    """
    program = active_program(client, **(program_overrides or {}))
    item = operational_item(client, program["id"], batch=batch, **(item_overrides or {}))
    form = rated_form(client, program["id"], [item["id"]], ratings, panelist_user_ids,
                      **(form_overrides or {}))
    return Pipeline(program_id=program["id"], item_id=item["id"], item_ids=[item["id"]],
                    form_id=form["id"], form_version=form["version"])


def pipeline_through_published_form(client: ApiClient,
                                    program_overrides: Optional[Dict[str, Any]] = None,
                                    item_overrides: Optional[Dict[str, Any]] = None,
                                    batch: Optional[Dict[str, Any]] = None,
                                    form_overrides: Optional[Dict[str, Any]] = None,
                                    ratings: Optional[List[Any]] = None,
                                    panelist_user_ids: Optional[List[str]] = None) -> Pipeline:
    """Everything a registration needs on the psychometric side: an active
    programme, an operational item and a published form with an adopted cut.
    """
    state = pipeline_through_ratings(client, program_overrides, item_overrides, batch,
                                     form_overrides, ratings, panelist_user_ids)
    cut_score_form(client, state.form_id, state.form_version)
    form = get_success_data(
        client.publish_form(state.form_id, f.publish_form_payload(), PROGRAM_ADMIN))
    state.form_version = form["version"]
    return state


def pipeline_through_approved_application(
        client: ApiClient,
        program_overrides: Optional[Dict[str, Any]] = None,
        item_overrides: Optional[Dict[str, Any]] = None,
        batch: Optional[Dict[str, Any]] = None,
        form_overrides: Optional[Dict[str, Any]] = None,
        ratings: Optional[List[Any]] = None,
        panelist_user_ids: Optional[List[str]] = None,
        candidate_overrides: Optional[Dict[str, Any]] = None,
        application_overrides: Optional[Dict[str, Any]] = None) -> Pipeline:
    """A published form plus a candidate whose application is ``APPROVED``."""
    state = pipeline_through_published_form(client, program_overrides, item_overrides, batch,
                                            form_overrides, ratings, panelist_user_ids)
    candidate = create_candidate(client, **(candidate_overrides or {}))
    application = approved_application(client, candidate["id"], state.program_id,
                                       **(application_overrides or {}))
    state.candidate_id = candidate["id"]
    state.application_id = application["id"]
    return state


def pipeline_through_scheduled_seat(
        client: ApiClient,
        program_overrides: Optional[Dict[str, Any]] = None,
        item_overrides: Optional[Dict[str, Any]] = None,
        batch: Optional[Dict[str, Any]] = None,
        form_overrides: Optional[Dict[str, Any]] = None,
        ratings: Optional[List[Any]] = None,
        panelist_user_ids: Optional[List[str]] = None,
        candidate_overrides: Optional[Dict[str, Any]] = None,
        application_overrides: Optional[Dict[str, Any]] = None,
        session_overrides: Optional[Dict[str, Any]] = None,
        fee_paid_cents: int = 45000) -> Pipeline:
    """An approved candidate holding a reserved seat in a future session."""
    state = pipeline_through_approved_application(
        client, program_overrides, item_overrides, batch, form_overrides, ratings,
        panelist_user_ids, candidate_overrides, application_overrides)
    session = create_test_center_session(client, **(session_overrides or {}))
    registration = create_registration(client, state.application_id, state.form_id,
                                       fee_paid_cents)
    scheduled = schedule_seat(client, registration["id"], session["id"], session["version"])
    state.session_id = session["id"]
    state.registration_id = registration["id"]
    state.session_version = get_success_data(
        client.get_exam_session(session["id"], EXAM_OPERATIONS))["version"]
    assert scheduled["seat_status"] == "SCHEDULED"
    return state


def pipeline_at_session_open(client: ApiClient, session_start: str = "2026-08-10T00:00:00Z",
                             **kwargs) -> Pipeline:
    """A reserved seat with the clock advanced into the check-in window."""
    state = pipeline_through_scheduled_seat(client, **kwargs)
    set_clock(client, session_start)
    return state


def pipeline_through_check_in(client: ApiClient, session_start: str = "2026-08-10T00:00:00Z",
                             **kwargs) -> Pipeline:
    """A candidate seated in the session, awaiting responses."""
    state = pipeline_at_session_open(client, session_start, **kwargs)
    check_in(client, state.registration_id)
    return state


def pipeline_through_responses(client: ApiClient, raw_score: int = 1,
                               session_start: str = "2026-08-10T00:00:00Z",
                               **kwargs) -> Pipeline:
    """Responses submitted and scored, but the result not yet released."""
    state = pipeline_through_check_in(client, session_start, **kwargs)
    submit_responses(client, state.registration_id, raw_score)
    return state


def pipeline_through_certificant(client: ApiClient, raw_score: int = 1,
                                 session_start: str = "2026-08-10T00:00:00Z",
                                 **kwargs) -> Pipeline:
    """The full delivery chain: a passing result reported, which mints the
    credential and opens its first recertification cycle.
    """
    state = pipeline_through_responses(client, raw_score, session_start, **kwargs)
    report_score(client, state.registration_id)
    certificants = get_success_data(
        client.list_certificants(PROGRAM_ADMIN, {"candidate_id": state.candidate_id}))
    assert len(certificants) == 1, f"expected exactly one credential, got {len(certificants)}"
    certificant = certificants[0]
    cycles = get_success_data(
        client.list_recertification_cycles(PROGRAM_ADMIN,
                                          {"certificant_id": certificant["id"]}))
    assert len(cycles) == 1, f"expected exactly one open cycle, got {len(cycles)}"
    state.certificant_id = certificant["id"]
    state.certificant_version = certificant["version"]
    state.certificate_number = certificant["certificate_number"]
    state.cycle_id = cycles[0]["id"]
    return state


# ---------------------------------------------------------------------------
# Tier 5 — a second candidate on the same programme
# ---------------------------------------------------------------------------


def second_candidate_application(client: ApiClient, state: Pipeline,
                                 email: str = "cand.b@example.com",
                                 full_name: str = "Cand B",
                                 education_reviewer_user_id: str = ELIGIBILITY_REVIEWER_1_ID,
                                 experience_reviewer_user_id: str = ELIGIBILITY_REVIEWER_2_ID,
                                 **application_overrides) -> Dict[str, Any]:
    """A second approved applicant on the same programme, for rivalry over a
    seat or a room. Returns ``{"candidate": ..., "application": ...}``.
    """
    candidate = create_candidate(client, email=email, full_name=full_name)
    application = approved_application(client, candidate["id"], state.program_id,
                                       education_reviewer_user_id,
                                       experience_reviewer_user_id, **application_overrides)
    return {"candidate": candidate, "application": application}


# ---------------------------------------------------------------------------
# Tier 5 — continuing education
# ---------------------------------------------------------------------------


def claim_ceu(client: ApiClient, state: Pipeline, cycle_id: Optional[str] = None,
              **overrides) -> Dict[str, Any]:
    """Claim an activity as the credential holder."""
    return get_success_data(
        client.claim_ceu_activity(cycle_id or state.cycle_id, f.claim_ceu_payload(**overrides),
                                  state.owner_headers))


def approved_ceu(client: ApiClient, state: Pipeline, cycle_id: Optional[str] = None,
                 reviewer_user_id: str = ELIGIBILITY_REVIEWER_3_ID, **overrides) -> Dict[str, Any]:
    """Claim an activity and have a reviewer approve it, so its credits count."""
    activity = claim_ceu(client, state, cycle_id, **overrides)
    return get_success_data(
        client.review_ceu_activity(activity["id"], f.review_ceu_payload("APPROVE"),
                                   make_eligibility_reviewer_headers(reviewer_user_id)))


def satisfied_cycle(client: ApiClient, state: Pipeline, contact_hours: float = 12.0,
                    activity_date: str = "2026-09-15T00:00:00Z") -> Dict[str, Any]:
    """Bring the open cycle's applied credits up to its requirement."""
    approved_ceu(client, state, contact_hours=contact_hours, activity_date=activity_date)
    return get_success_data(client.get_recertification_cycle(state.cycle_id, PROGRAM_ADMIN))


# ---------------------------------------------------------------------------
# Tier 5 — security incidents
# ---------------------------------------------------------------------------


def raise_incident(client: ApiClient, registration_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        client.raise_security_incident(registration_id, f.create_incident_payload(**overrides),
                                       EXAM_OPERATIONS))


def adjudicate_incident(client: ApiClient, incident_id: str,
                        outcome: str = "SUBSTANTIATE") -> Dict[str, Any]:
    """Adjudication is reserved to ``ExamOperations``."""
    return get_success_data(
        client.adjudicate_security_incident(incident_id, f.adjudicate_incident_payload(outcome),
                                            EXAM_OPERATIONS))


# ---------------------------------------------------------------------------
# Tier 5 — discipline
# ---------------------------------------------------------------------------


def case_awaiting_decision(client: ApiClient, state: Pipeline,
                           opener_user_id: str = ETHICS_OFFICER_1_ID,
                           **case_overrides) -> Dict[str, Any]:
    """A case that has completed due process: opened, a response requested, and
    the respondent's own answer on the record.
    """
    case = get_success_data(
        client.open_disciplinary_case(
            f.open_case_payload(state.certificant_id, **case_overrides),
            make_ethics_officer_headers(opener_user_id)))
    get_success_data(
        client.request_case_response(case["id"], f.request_response_payload(),
                                     make_ethics_officer_headers(opener_user_id)))
    return get_success_data(
        client.respond_to_case(case["id"], f.respond_to_case_payload(), state.owner_headers))


# ---------------------------------------------------------------------------
# Tier 5 — the maintenance run
# ---------------------------------------------------------------------------


def run_maintenance(client: ApiClient, dry_run: bool = False) -> Dict[str, Any]:
    return get_success_data(
        client.run_maintenance(f.maintenance_run_payload(dry_run), PROGRAM_ADMIN))


# ---------------------------------------------------------------------------
# Convenience re-reads
# ---------------------------------------------------------------------------


def read_program(client: ApiClient, program_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_program(program_id, PROGRAM_ADMIN))


def read_item(client: ApiClient, item_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_item(item_id, PSYCHOMETRICIAN))


def read_form(client: ApiClient, form_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_form(form_id, PSYCHOMETRICIAN))


def read_candidate(client: ApiClient, candidate_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_candidate(candidate_id, EXAM_OPERATIONS))


def read_application(client: ApiClient, application_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_application(application_id, ELIGIBILITY_REVIEWER_1))


def read_session(client: ApiClient, session_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_exam_session(session_id, EXAM_OPERATIONS))


def read_registration(client: ApiClient, registration_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_exam_registration(registration_id, EXAM_OPERATIONS))


def read_incident(client: ApiClient, incident_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_security_incident(incident_id, EXAM_OPERATIONS))


def read_certificant(client: ApiClient, certificant_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_certificant(certificant_id, PROGRAM_ADMIN))


def read_cycle(client: ApiClient, cycle_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_recertification_cycle(cycle_id, PROGRAM_ADMIN))


def read_activity(client: ApiClient, activity_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_ceu_activity(activity_id, ELIGIBILITY_REVIEWER_3))


def read_case(client: ApiClient, case_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.get_disciplinary_case(case_id, make_ethics_officer_headers(ETHICS_OFFICER_1_ID)))


def read_cycles_of(client: ApiClient, certificant_id: str) -> List[Dict[str, Any]]:
    return get_success_data(
        client.list_certificant_recertification_cycles(certificant_id, PROGRAM_ADMIN))


def read_activities_of(client: ApiClient, cycle_id: str) -> List[Dict[str, Any]]:
    return get_success_data(client.list_cycle_ceu_activities(cycle_id, PROGRAM_ADMIN))
