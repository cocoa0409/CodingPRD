"""Composite setup helpers for multi-step test prerequisites.

Every test starts against an empty database (the runner restarts the server
before each test), so all preconditions are built from scratch here via
PRD-declared endpoints. Setup calls use get_success_data() so failures surface
as clear "Setup failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    T_JUNE_01, T_JUNE_03_LATE, WINDOW_START, WINDOW_END,
)
from .factories import (
    create_specialty_track_payload, create_referring_provider_payload,
    create_specialist_payload, create_panel_membership_payload,
    create_availability_window_payload, create_consult_request_payload,
    create_response_payload, create_documentation_payload, create_revise_payload,
    create_quality_review_payload, create_complete_review_payload,
)
from .test_users import (
    TEST_USERS, make_provider_headers, make_specialist_headers,
    make_reviewer_headers,
)

COORD = TEST_USERS["coordinator_headers"]
BILLING = TEST_USERS["billing_headers"]


# ─── Tier 0: atomic building blocks ─────────────────────────────────

def set_clock(iso: str = T_JUNE_01):
    """Advance the logical clock (also runs the expiry sweep)."""
    res = api_client.set_clock({"to_iso8601": iso}, COORD)
    assert res.status_code == 200, f"Setup failed: set_clock -> {res.status_code} {res.text}"
    return res


def create_track(specialty_code: str = "CARDIOLOGY", **overrides):
    payload = create_specialty_track_payload(specialty_code=specialty_code, **overrides)
    return get_success_data(api_client.create_specialty_track(payload, COORD))


def create_provider(npi: str = "1000000001", **overrides):
    payload = create_referring_provider_payload(npi=npi, **overrides)
    return get_success_data(api_client.create_referring_provider(payload, COORD))


def create_specialist(npi: str = "2000000001", **overrides):
    payload = create_specialist_payload(npi=npi, **overrides)
    return get_success_data(api_client.create_specialist(payload, COORD))


def create_membership(specialist_id: str, track_id: str, **overrides):
    payload = create_panel_membership_payload(specialist_id, track_id, **overrides)
    return get_success_data(api_client.create_panel_membership(payload, COORD))


def create_window(membership_id: str, specialist_id: str,
                  window_start: str = WINDOW_START, window_end: str = WINDOW_END):
    """Create an ACTIVE availability window as the owning specialist."""
    payload = create_availability_window_payload(membership_id, window_start, window_end)
    return get_success_data(
        api_client.create_availability_window(payload, make_specialist_headers(specialist_id))
    )


def create_consult(track_id: str, provider_id: str, patient_ref: str = "PAT-0001",
                   **overrides):
    payload = create_consult_request_payload(track_id, patient_ref=patient_ref, **overrides)
    return get_success_data(
        api_client.create_consult_request(payload, make_provider_headers(provider_id))
    )


def submit_response(consult_id: str, specialist_id: str,
                    disposition: str = "MANAGE_IN_PRIMARY_CARE", **overrides):
    payload = create_response_payload(disposition=disposition, **overrides)
    return get_success_data(
        api_client.create_response(consult_id, payload, make_specialist_headers(specialist_id))
    )


def document_response(response_id: str, provider_id: str, specialist_id: str):
    """Mark both sides of the dual-record documentation (PCP + specialist)."""
    get_success_data(api_client.mark_documentation(
        response_id, create_documentation_payload("PCP_NOTE"),
        make_provider_headers(provider_id),
    ))
    return get_success_data(api_client.mark_documentation(
        response_id, create_documentation_payload("SPECIALIST_NOTE"),
        make_specialist_headers(specialist_id),
    ))


def open_review(response_id: str, reviewer_id: str):
    payload = create_quality_review_payload(response_id)
    return get_success_data(
        api_client.create_quality_review(payload, make_reviewer_headers(reviewer_id))
    )


def complete_review(review_id: str, reviewer_id: str, timeliness_score: int = 5,
                    appropriateness_score: int = 5, clarity_score: int = 5,
                    verdict: str = "PASS"):
    payload = create_complete_review_payload(
        timeliness_score=timeliness_score,
        appropriateness_score=appropriateness_score,
        clarity_score=clarity_score,
        verdict=verdict,
    )
    return get_success_data(
        api_client.complete_quality_review(review_id, payload,
                                           make_reviewer_headers(reviewer_id))
    )


def finalize_response(response_id: str, specialist_id: str):
    return get_success_data(
        api_client.finalize_response(response_id, make_specialist_headers(specialist_id))
    )


def revise_response(response_id: str, specialist_id: str, **overrides):
    payload = create_revise_payload(**overrides)
    return get_success_data(
        api_client.revise_response(response_id, payload, make_specialist_headers(specialist_id))
    )


def close_consult(consult_id: str, provider_id: str):
    return get_success_data(
        api_client.close_consult(consult_id, make_provider_headers(provider_id))
    )


def get_membership(membership_id: str):
    return get_success_data(api_client.get_panel_membership(membership_id, COORD))


def get_consult(consult_id: str):
    return get_success_data(api_client.get_consult_request(consult_id, COORD))


def get_response(response_id: str):
    return get_success_data(api_client.get_consult_response(response_id, COORD))


def get_summary(membership_id: str):
    return get_success_data(api_client.get_compensation_summary(membership_id, COORD))


# ─── Tier 1/2: scenario assembly ────────────────────────────────────

def setup_panel_scenario(track_overrides=None, specialty_code: str = "CARDIOLOGY",
                         provider_npi: str = "1000000001",
                         specialist_npi: str = "2000000001",
                         reviewer_npi: str = "2000000002",
                         with_reviewer: bool = False,
                         clock: str = T_JUNE_01):
    """Clock set + track + provider + specialist + membership + covering window.

    Returns a dict with keys: track, provider, specialist, membership, window
    (and reviewer when with_reviewer=True).
    """
    set_clock(clock)
    track_overrides = dict(track_overrides or {})
    # An override may legitimately re-target the specialty code itself; pop it
    # so the explicit kwarg and the override dict never collide at call time.
    code = track_overrides.pop("specialty_code", specialty_code)
    track = create_track(specialty_code=code, **track_overrides)
    provider = create_provider(npi=provider_npi)
    specialist = create_specialist(npi=specialist_npi)
    membership = create_membership(specialist["id"], track["id"])
    window = create_window(membership["id"], specialist["id"])
    scenario = {
        "track": track,
        "provider": provider,
        "specialist": specialist,
        "membership": membership,
        "window": window,
    }
    if with_reviewer:
        scenario["reviewer"] = create_specialist(npi=reviewer_npi)
    return scenario


def setup_assigned_consult(patient_ref: str = "PAT-0001", consult_overrides=None,
                           **scenario_kwargs):
    """Panel scenario + one consult routed ASSIGNED to the membership."""
    scenario = setup_panel_scenario(**scenario_kwargs)
    consult = create_consult(
        scenario["track"]["id"], scenario["provider"]["id"],
        patient_ref=patient_ref, **(consult_overrides or {}),
    )
    assert consult["status"] == "ASSIGNED", (
        f"Setup failed: consult landed in {consult['status']}, expected ASSIGNED"
    )
    scenario["consult"] = consult
    return scenario


def setup_answered_consult(patient_ref: str = "PAT-0001",
                           disposition: str = "MANAGE_IN_PRIMARY_CARE",
                           consult_overrides=None, response_overrides=None,
                           **scenario_kwargs):
    """Assigned consult + specialist response submitted (consult ANSWERED)."""
    scenario = setup_assigned_consult(
        patient_ref=patient_ref, consult_overrides=consult_overrides, **scenario_kwargs
    )
    response = submit_response(
        scenario["consult"]["id"], scenario["specialist"]["id"],
        disposition=disposition, **(response_overrides or {}),
    )
    scenario["response"] = response
    return scenario


def setup_finalized_consult(patient_ref: str = "PAT-0001",
                            disposition: str = "MANAGE_IN_PRIMARY_CARE",
                            **scenario_kwargs):
    """Answered + fully documented + finalized consult (billing CHARGEABLE)."""
    scenario = setup_answered_consult(
        patient_ref=patient_ref, disposition=disposition, **scenario_kwargs
    )
    document_response(
        scenario["response"]["id"], scenario["provider"]["id"], scenario["specialist"]["id"]
    )
    scenario["response"] = finalize_response(
        scenario["response"]["id"], scenario["specialist"]["id"]
    )
    return scenario


def setup_queued_consult_scenario(specialty_code: str = "NEUROLOGY",
                                  provider_npi: str = "1000000003",
                                  patient_ref: str = "PAT-Q1",
                                  consult_overrides=None,
                                  clock: str = T_JUNE_01):
    """Track with NO panel: consult lands QUEUED with an empty-pool decision."""
    set_clock(clock)
    track = create_track(specialty_code=specialty_code)
    provider = create_provider(npi=provider_npi)
    consult = create_consult(track["id"], provider["id"], patient_ref=patient_ref,
                             **(consult_overrides or {}))
    return {"track": track, "provider": provider, "consult": consult}


def setup_late_answered_consult(patient_ref: str = "PAT-L1",
                                disposition: str = "MANAGE_IN_PRIMARY_CARE",
                                response_clock: str = T_JUNE_03_LATE,
                                with_reviewer: bool = True,
                                **scenario_kwargs):
    """Consult created at T_JUNE_01 (48h routine SLA); clock advanced 1h past
    the deadline; response submitted late (on_time False, review_required True)."""
    scenario = setup_assigned_consult(
        patient_ref=patient_ref, with_reviewer=with_reviewer, **scenario_kwargs
    )
    set_clock(response_clock)
    response = submit_response(
        scenario["consult"]["id"], scenario["specialist"]["id"], disposition=disposition
    )
    scenario["response"] = response
    return scenario


def setup_rebuked_response(patient_ref: str = "PAT-RB1", late: bool = False,
                           review_scores=(2, 1, 4)):
    """Answered consult + completed REBUKE review (composite 4000 for 2/1/4).

    Returns scenario with response in REBUKED status. review_scores are
    (timeliness, appropriateness, clarity).
    """
    if late:
        scenario = setup_late_answered_consult(patient_ref=patient_ref)
    else:
        scenario = setup_answered_consult(patient_ref=patient_ref, with_reviewer=True)
    t, a, c = review_scores
    review = open_review(scenario["response"]["id"], scenario["reviewer"]["id"])
    complete_review(review["id"], scenario["reviewer"]["id"],
                    timeliness_score=t, appropriateness_score=a, clarity_score=c,
                    verdict="REBUKE")
    scenario["review"] = review
    scenario["response"] = get_response(scenario["response"]["id"])
    return scenario
