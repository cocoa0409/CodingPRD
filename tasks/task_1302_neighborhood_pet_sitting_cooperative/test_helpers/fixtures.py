"""Composite setup helpers for the pet-sitting cooperative test suite.

Most testable states (a VETTED member, an accepted claim, an IN_PROGRESS sit) take
5–25 API calls to reach; these helpers encapsulate those chains so tests focus on
assertions. All setup calls use get_success_data() so failures surface as clear
"Setup failed" errors.

Bootstrap note: the founders are vetted via a three-member mutual-vouch clique —
each pair of founders files references for each other and all six rows are
accepted before finalization, satisfying the reciprocity gate.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_member_payload, create_reference_payload, create_pet_profile_payload,
    create_holiday_window_payload, create_sitting_request_payload, create_claim_payload,
    create_accept_claim_payload, create_cancel_payload, create_entry_log_payload,
    create_incident_payload, create_resolve_incident_payload, create_dispute_payload,
    create_assign_mediator_payload, create_resolve_dispute_payload, create_escalate_payload,
)
from .test_users import TEST_USERS, make_member_headers

ADMIN = TEST_USERS["admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ─── Clock ─────────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Advance the server's logical clock (CoopAdmin-only, PRD §2.6)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ─── Members / vetting pipeline ────────────────────────

def create_applicant(display_name: str, email: str, phone: str, mediator_flag: bool = False) -> dict:
    """Submit a membership application as Anonymous. Returns the APPLIED member."""
    return get_success_data(api_client.create_member(
        create_member_payload(
            display_name=display_name, email=email, phone=phone, mediator_flag=mediator_flag,
        ),
        ANON,
    ))


def _vet_member_via_clique(member: dict, referees: list):
    """Walk an APPLIED member to VETTED with references from already-VETTED referees.

    Creates the two primary references (referees vouch for the applicant), the two
    reciprocal rows (the applicant vouches back for each referee), submits, accepts
    all four rows, accepts liability, and finalizes.
    """
    mid = member["id"]
    r1, r2 = referees[0], referees[1]
    ref_a = get_success_data(api_client.create_reference(
        mid, create_reference_payload(r1["id"]), ADMIN))
    ref_b = get_success_data(api_client.create_reference(
        mid, create_reference_payload(r2["id"]), ADMIN))
    # Reciprocal rows: applicant vouches back for each referee.
    rec_a = get_success_data(api_client.create_reference(
        r1["id"], create_reference_payload(
            mid, attestation_text="Applicant vouches back for the referee."), ADMIN))
    rec_b = get_success_data(api_client.create_reference(
        r2["id"], create_reference_payload(
            mid, attestation_text="Applicant vouches back for the referee."), ADMIN))
    get_success_data(api_client.accept_liability(mid, make_member_headers(mid)))
    get_success_data(api_client.submit_references(mid, ADMIN))
    for ref in (ref_a, ref_b, rec_a, rec_b):
        get_success_data(api_client.accept_reference(ref["id"], ADMIN))
    return get_success_data(api_client.finalize_vetting(mid, ADMIN))


def bootstrap_founders() -> dict:
    """Create and vet the three founding members via the mutual-vouch clique.

    Returns dict with keys f1, f2, f3 (Member dicts, all VETTED with the 10.0-hour
    joining grant and reliability 50); f3 carries mediator_flag=true.
    """
    f1 = create_applicant("Founder One", "f1@coop.test", "+15550101")
    f2 = create_applicant("Founder Two", "f2@coop.test", "+15550102")
    f3 = create_applicant("Founder Three", "f3@coop.test", "+15550103", mediator_flag=True)
    ids = {"f1": f1["id"], "f2": f2["id"], "f3": f3["id"]}

    refs = {}
    for subj, ref in (("f1", "f2"), ("f1", "f3"), ("f2", "f1"),
                      ("f2", "f3"), ("f3", "f1"), ("f3", "f2")):
        refs[(subj, ref)] = get_success_data(api_client.create_reference(
            ids[subj], create_reference_payload(ids[ref]), ADMIN))["id"]

    for mid in ids.values():
        get_success_data(api_client.accept_liability(mid, make_member_headers(mid)))
        get_success_data(api_client.submit_references(mid, ADMIN))
    for ref_id in refs.values():
        get_success_data(api_client.accept_reference(ref_id, ADMIN))
    for key in ("f1", "f2", "f3"):
        get_success_data(api_client.finalize_vetting(ids[key], ADMIN))

    return {
        "f1": get_success_data(api_client.get_member(ids["f1"], ADMIN)),
        "f2": get_success_data(api_client.get_member(ids["f2"], ADMIN)),
        "f3": get_success_data(api_client.get_member(ids["f3"], ADMIN)),
        "refs": refs,
    }


def create_vetted_member(display_name: str, email: str, phone: str, referees: list,
                         mediator_flag: bool = False) -> dict:
    """Create an applicant and walk them to VETTED using two VETTED referees."""
    member = create_applicant(display_name, email, phone, mediator_flag=mediator_flag)
    return _vet_member_via_clique(member, referees)


# ─── Pet profiles ──────────────────────────────────────

def create_pet(member: dict, **overrides) -> dict:
    """Create an active, waiver-accepted pet profile owned by the member."""
    return get_success_data(api_client.create_pet_profile(
        member["id"], create_pet_profile_payload(**overrides), make_member_headers(member["id"])))


# ─── Holiday windows ───────────────────────────────────

def create_window(**overrides) -> dict:
    return get_success_data(api_client.create_holiday_window(
        create_holiday_window_payload(**overrides), ADMIN))


# ─── Sitting marketplace chain ─────────────────────────

def post_request(owner: dict, pet: dict, start_at: str = None, end_at: str = None,
                 **overrides) -> dict:
    """Post an OPEN sitting request for the owner's pet."""
    payload = create_sitting_request_payload(pet["id"], **overrides)
    if start_at is not None:
        payload["start_at"] = start_at
    if end_at is not None:
        payload["end_at"] = end_at
    return get_success_data(api_client.create_sitting_request(payload, make_member_headers(owner["id"])))


def claim_request(request: dict, claimer: dict, message: str = "Happy to sit") -> dict:
    """File a PENDING claim on the request as the claimer."""
    return get_success_data(api_client.create_claim(
        request["id"], create_claim_payload(message=message), make_member_headers(claimer["id"])))


def accept_claim(request: dict, claim: dict, owner: dict, expected_version: int = None) -> dict:
    """Owner accepts a claim (OCC-guarded). Returns the ACCEPTED claim."""
    version = expected_version if expected_version is not None else request["version"]
    return get_success_data(api_client.accept_claim(
        request["id"], claim["id"], create_accept_claim_payload(version),
        make_member_headers(owner["id"])))


def get_assignment_for_request(request_id: str) -> dict:
    """Return the single assignment row for a request (fails setup if absent)."""
    data = get_success_data(api_client.get_request_assignment(request_id, ADMIN))
    assert isinstance(data, list) and len(data) == 1, f"Setup failed: expected 1 assignment for {request_id}"
    return data[0]


def get_handoff_for_assignment(assignment_id: str) -> dict:
    """Return the single handoff row for an assignment (fails setup if absent)."""
    data = get_success_data(api_client.get_assignment_handoff(assignment_id, ADMIN))
    assert isinstance(data, list) and len(data) == 1, f"Setup failed: expected 1 handoff for {assignment_id}"
    return data[0]


def setup_confirmed_sit(founders: dict = None, start_at: str = None, end_at: str = None,
                        sitter_key: str = "f2", owner_key: str = "f1",
                        owner: dict = None, pet: dict = None) -> dict:
    """Canonical sit through claim acceptance: assignment CONFIRMED, handoff PENDING.

    Returns dict: founders, owner, sitter, pet, request, claim, assignment, handoff.
    """
    if founders is None:
        founders = bootstrap_founders()
    owner = owner or founders[owner_key]
    sitter = founders[sitter_key]
    pet = pet or create_pet(owner)
    request = post_request(owner, pet, start_at=start_at, end_at=end_at)
    claim = claim_request(request, sitter)
    accepted = accept_claim(request, claim, owner)
    assignment = get_assignment_for_request(request["id"])
    handoff = get_handoff_for_assignment(assignment["id"])
    return {
        "founders": founders, "owner": owner, "sitter": sitter, "pet": pet,
        "request": get_success_data(api_client.get_sitting_request(request["id"], ADMIN)),
        "claim": accepted, "assignment": assignment, "handoff": handoff,
    }


def setup_in_progress_sit(founders: dict = None, start_at: str = None, end_at: str = None,
                          checkin_at: str = None, **kwargs) -> dict:
    """Walk the canonical sit to IN_PROGRESS: handoff confirmed, first CHECK_IN logged.

    Drives the logical clock to the sit window so the handoff gate is open.
    """
    sit = setup_confirmed_sit(founders=founders, start_at=start_at, end_at=end_at, **kwargs)
    start_at = start_at or TEST_DEFAULTS["SIT_START"]
    checkin_at = checkin_at or start_at
    day = start_at[:10]
    set_clock(f"{day}T08:30:00Z" if start_at == TEST_DEFAULTS["SIT_START"] else _two_hours_before(start_at))
    get_success_data(api_client.confirm_handoff(
        sit["handoff"]["id"], make_member_headers(sit["owner"]["id"])))
    set_clock(checkin_at)
    entry = get_success_data(api_client.create_entry_log(
        sit["assignment"]["id"],
        create_entry_log_payload("CHECK_IN", checkin_at),
        make_member_headers(sit["sitter"]["id"])))
    sit["checkin_entry"] = entry
    sit["assignment"] = get_success_data(api_client.get_assignment(sit["assignment"]["id"], ADMIN))
    return sit


def setup_completed_sit(founders: dict = None, checkout_clock: str = None, **kwargs) -> dict:
    """Walk the canonical sit through checkout: assignment COMPLETED_PENDING_REVIEW,
    request COMPLETED. checkout_clock sets the logical now for actual_end_at."""
    sit = setup_in_progress_sit(founders=founders, **kwargs)
    end_at = sit["assignment"]["scheduled_end_at"]
    set_clock(checkout_clock or end_at)
    sit["assignment"] = get_success_data(api_client.checkout_assignment(
        sit["assignment"]["id"], make_member_headers(sit["sitter"]["id"])))
    return sit


def setup_settled_sit(founders: dict = None, **kwargs) -> dict:
    """Full happy path through admin settlement: assignment SETTLED, ledger posted."""
    sit = setup_completed_sit(founders=founders, **kwargs)
    sit["assignment"] = get_success_data(api_client.settle_assignment(sit["assignment"]["id"], ADMIN))
    return sit


def _two_hours_before(start_at: str) -> str:
    """Compute start_at - 2h as an ISO instant (same-day hours only in our scenarios)."""
    from datetime import datetime, timedelta, timezone
    dt = datetime.fromisoformat(start_at.replace("Z", "+00:00"))
    return (dt - timedelta(hours=2)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── Incidents / disputes ──────────────────────────────

def file_incident(assignment_id: str, reporter: dict, **overrides) -> dict:
    return get_success_data(api_client.create_incident(
        assignment_id, create_incident_payload(**overrides), make_member_headers(reporter["id"])))


def resolve_incident_at_fault(incident_id: str, at_fault_member_id: str) -> dict:
    """begin-review then resolve AT_FAULT against the given member."""
    get_success_data(api_client.begin_review_incident(incident_id, ADMIN))
    return get_success_data(api_client.resolve_incident(
        incident_id, create_resolve_incident_payload("AT_FAULT", at_fault_member_id=at_fault_member_id), ADMIN))


def open_dispute(initiator: dict, respondent: dict, **overrides) -> dict:
    return get_success_data(api_client.create_dispute(
        create_dispute_payload(respondent["id"], **overrides), make_member_headers(initiator["id"])))


def setup_dispute_in_mediation(founders: dict, initiator_key: str = "f1",
                               respondent_key: str = "f2", **overrides) -> dict:
    """Open a dispute and assign founder f3 as mediator. Returns the MEDIATION dispute."""
    dispute = open_dispute(founders[initiator_key], founders[respondent_key], **overrides)
    return get_success_data(api_client.assign_mediator(
        dispute["id"], create_assign_mediator_payload(founders["f3"]["id"]), ADMIN))


def escalate_dispute(dispute: dict, mediator: dict) -> dict:
    return get_success_data(api_client.escalate_dispute(
        dispute["id"], create_escalate_payload(), make_member_headers(mediator["id"])))


def resolve_dispute(dispute: dict, mediator: dict, outcome: str, **overrides) -> dict:
    return get_success_data(api_client.resolve_dispute(
        dispute["id"], create_resolve_dispute_payload(outcome, **overrides),
        make_member_headers(mediator["id"])))


# ─── Ledger helpers ────────────────────────────────────

def list_ledger(member_id: str, params: dict = None) -> list:
    return get_success_data(api_client.list_credit_ledger(member_id, ADMIN, params=params))


def get_member(member_id: str) -> dict:
    return get_success_data(api_client.get_member(member_id, ADMIN))
