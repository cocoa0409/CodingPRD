"""Composite setup helpers for the peer-review test suite.

Every helper builds its preconditions from scratch through PRD-declared
endpoints (the server restarts with an empty database before each test).
Setup calls use the lenient get_success_data() so a setup failure surfaces as
a clear error rather than a confusing assertion failure deep in a test.

Version handling: the two OCC-guarded writes (assignment create, score
submit) always re-read the case immediately before writing, so callers never
thread stale versions through multi-step setups.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import AFTER_DEADLINE, DEFAULT_REFERRED_AT
from .factories import (
    add_focus_group_member_payload,
    close_focused_review_payload,
    create_case_payload,
    create_committee_member_payload,
    create_focus_group_payload,
    create_focused_review_payload,
    create_provider_payload,
    create_response_payload,
    set_clock_payload,
    submit_assignment_payload,
)
from .test_users import (
    TEST_USERS,
    make_committee_member_headers,
    make_provider_headers,
)

QD = TEST_USERS["quality_director_headers"]
PRC = TEST_USERS["peer_review_coordinator_headers"]


# ---------------------------------------------------------------------------
# Tier 0: atomic building blocks
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Move the server's logical clock (QualityDirector-only capability)."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), QD))


def create_provider(full_name="Dr. Fixture Provider", specialty="SURGERY") -> dict:
    return get_success_data(
        api_client.create_provider(
            create_provider_payload(full_name=full_name, specialty=specialty), QD))


def seat_member(provider_id, member_role="MEMBER") -> dict:
    return get_success_data(
        api_client.create_committee_member(
            create_committee_member_payload(provider_id=provider_id, member_role=member_role),
            QD))


def create_case(subject_provider_id, referral_source="OTHER",
                referred_at=DEFAULT_REFERRED_AT, description="Review case") -> dict:
    return get_success_data(
        api_client.create_case(
            create_case_payload(
                subject_provider_id=subject_provider_id,
                referral_source=referral_source,
                referred_at=referred_at,
                description=description,
            ),
            PRC))


def get_case(case_id) -> dict:
    return get_success_data(api_client.get_case(case_id, QD))


def get_member(member_id) -> dict:
    return get_success_data(api_client.get_committee_member(member_id, QD))


def get_assignment(assignment_id) -> dict:
    return get_success_data(api_client.get_assignment(assignment_id, QD))


def screen_case_in(case_id) -> dict:
    return get_success_data(
        api_client.screen_case(case_id, {"decision": "SCREEN_IN"}, QD))


def assign_reviewer(case_id, member_id) -> dict:
    """Create a PENDING assignment; re-reads the case version first (OCC)."""
    version = get_case(case_id)["version"]
    return get_success_data(
        api_client.create_assignment(
            case_id,
            {"reviewer_id": member_id, "expected_case_version": version},
            PRC))


def submit_scores(assignment_id, member_id, case_id, care, ofi=None) -> dict:
    """Submit scores as the assigned member; re-reads the case version first."""
    version = get_case(case_id)["version"]
    return get_success_data(
        api_client.submit_assignment(
            assignment_id,
            submit_assignment_payload(care, version, ofi_score=ofi),
            make_committee_member_headers(member_id)))


def finalize_deliberation(case_id, chair_id, rationale_note=None) -> dict:
    payload = {} if rationale_note is None else {"rationale_note": rationale_note}
    return get_success_data(
        api_client.finalize_deliberation(case_id, payload,
                                         make_committee_member_headers(chair_id)))


def respond_to_case(case_id, subject_provider_id, response_text="Provider response") -> dict:
    return get_success_data(
        api_client.create_case_response(
            case_id,
            create_response_payload(response_text=response_text),
            make_provider_headers(subject_provider_id)))


def committee_review(case_id, chair_id) -> dict:
    return get_success_data(
        api_client.committee_review(case_id, {}, make_committee_member_headers(chair_id)))


def finalize_after_response(case_id, chair_id, reconsideration_note=None) -> dict:
    payload = {} if reconsideration_note is None else {"reconsideration_note": reconsideration_note}
    return get_success_data(
        api_client.finalize_after_response(case_id, payload,
                                           make_committee_member_headers(chair_id)))


def close_case_no_response(case_id) -> dict:
    return get_success_data(api_client.close_no_response(case_id, QD))


def create_focused_review(provider_id, basis="Focused review basis") -> dict:
    return get_success_data(
        api_client.create_focused_review(
            create_focused_review_payload(provider_id=provider_id, basis=basis), QD))


def close_focused_review(focus_id, resolution_note="Resolved") -> dict:
    return get_success_data(
        api_client.close_focused_review(
            focus_id, close_focused_review_payload(resolution_note=resolution_note), QD))


def create_focus_group(focus_id, name="panel-1") -> dict:
    return get_success_data(
        api_client.create_focus_group(focus_id, create_focus_group_payload(name=name), QD))


def add_focus_group_member(group_id, member_id) -> dict:
    return get_success_data(
        api_client.add_focus_group_member(
            group_id, add_focus_group_member_payload(member_id=member_id), QD))


def list_case_assignments(case_id, params=None) -> list:
    return get_success_data(api_client.list_case_assignments(case_id, QD, params=params))


def get_case_deliberation(case_id) -> list:
    return get_success_data(api_client.get_case_deliberation(case_id, QD))


def get_quality_trend(provider_id) -> dict:
    return get_success_data(api_client.get_provider_quality_trend(provider_id, QD))


# ---------------------------------------------------------------------------
# Tier 1/2: committee roster and case progression
# ---------------------------------------------------------------------------

def setup_committee(subject_specialty="SURGERY",
                    chair_specialty="INTERNAL_MEDICINE",
                    member_specialties=("SURGERY", "CARDIOLOGY", "PEDIATRICS"),
                    num_members=3) -> dict:
    """Subject provider + one CHAIR member + N MEMBER members (each backed by
    its own provider row). Returns a context dict used by all later tiers."""
    subject = create_provider("Subject Under Review", subject_specialty)
    chair_provider = create_provider("Committee Chair", chair_specialty)
    chair = seat_member(chair_provider["id"], "CHAIR")
    members = []
    member_providers = []
    specialties = list(member_specialties)
    while len(specialties) < num_members:
        specialties.append("EMERGENCY_MEDICINE")
    for i in range(num_members):
        p = create_provider(f"Reviewer {i + 1}", specialties[i])
        members.append(seat_member(p["id"], "MEMBER"))
        member_providers.append(p)
    return {
        "subject": subject,
        "chair": chair,
        "chair_provider": chair_provider,
        "members": members,
        "member_providers": member_providers,
    }


def drive_case_to_deliberation(ctx, scores=((4, None), (4, None), (4, None)),
                               referral_source="OTHER", description="Review case",
                               referred_at=DEFAULT_REFERRED_AT):
    """Create a case for ctx's subject, screen it in, assign ctx's members in
    order, and submit the given (care, ofi) scores. Ends in DELIBERATION when
    three scores are submitted. Returns (case, assignments)."""
    case = create_case(ctx["subject"]["id"], referral_source=referral_source,
                       referred_at=referred_at, description=description)
    screen_case_in(case["id"])
    assignments = [assign_reviewer(case["id"], m["id"]) for m in ctx["members"]]
    for assignment, member, (care, ofi) in zip(assignments, ctx["members"], scores):
        submit_scores(assignment["id"], member["id"], case["id"], care, ofi)
    return get_case(case["id"]), assignments


def drive_case_to_notified(ctx, scores=((4, None), (4, None), (4, None)),
                           rationale_note="Committee rationale", **case_kwargs):
    """Full progression to NOTIFIED: deliberation plus chair finalization.
    Returns (case, assignments, deliberation)."""
    case, assignments = drive_case_to_deliberation(ctx, scores=scores, **case_kwargs)
    deliberation = finalize_deliberation(case["id"], ctx["chair"]["id"], rationale_note)
    return get_case(case["id"]), assignments, deliberation


def setup_case_in_deliberation(scores=((4, None), (4, None), (4, None)), **committee_kwargs) -> dict:
    """Tier 2: committee + one case driven to DELIBERATION."""
    ctx = setup_committee(**committee_kwargs)
    case, assignments = drive_case_to_deliberation(ctx, scores=scores)
    ctx["case"] = case
    ctx["assignments"] = assignments
    return ctx


def setup_case_notified(scores=((4, None), (4, None), (4, None)), **committee_kwargs) -> dict:
    """Tier 3: committee + one case driven through finalize to NOTIFIED, with
    the notification row created (deadline = sent_at + 14 days)."""
    ctx = setup_committee(**committee_kwargs)
    case, assignments, deliberation = drive_case_to_notified(ctx, scores=scores)
    ctx["case"] = case
    ctx["assignments"] = assignments
    ctx["deliberation"] = deliberation
    return ctx


def setup_case_in_committee_review(scores=((4, None), (4, None), (4, None)),
                                   **committee_kwargs) -> dict:
    """Tier 3: case driven through the provider response loop into
    COMMITTEE_REVIEW (the score-revision window)."""
    ctx = setup_case_notified(scores=scores, **committee_kwargs)
    respond_to_case(ctx["case"]["id"], ctx["subject"]["id"])
    committee_review(ctx["case"]["id"], ctx["chair"]["id"])
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


def setup_case_closed_no_response(scores=((4, None), (4, None), (4, None)),
                                  close_at=AFTER_DEADLINE, **committee_kwargs) -> dict:
    """Tier 5: case in NOTIFIED, clock moved past the response deadline, then
    closed by the QualityDirector (closure_basis NO_RESPONSE)."""
    ctx = setup_case_notified(scores=scores, **committee_kwargs)
    set_clock(close_at)
    ctx["case"] = close_case_no_response(ctx["case"]["id"])
    return ctx
