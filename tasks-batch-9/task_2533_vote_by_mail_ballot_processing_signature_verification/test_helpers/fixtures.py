"""Composite setup helpers.

Every helper drives the public API only, so each test builds the state it needs
from an empty database. Setup calls use the lenient validator so a broken
precondition surfaces as a setup failure rather than a confusing assertion.

Naming: `create_*` performs one write; `setup_*` walks a multi-step chain and
returns a bundle dict whose keys name the entities it produced.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_ELECTION
from .factories import (
    address_result_payload,
    ballot_request_payload,
    challenge_adjudication_payload,
    challenge_payload,
    cure_adjudication_payload,
    cure_evidence_payload,
    election_payload,
    mailing_batch_payload,
    observer_session_payload,
    packet_payload,
    remake_payload,
    return_envelope_payload,
    reviewer_payload,
    separation_run_payload,
    signature_decision_payload,
    voter_payload,
)
from .test_users import (
    TEST_USERS,
    make_observer_headers,
    make_signature_reviewer_headers,
)

ADMIN = TEST_USERS["elections_admin_headers"]
CLERK = TEST_USERS["elections_clerk_headers"]
SUPERVISOR = TEST_USERS["canvass_supervisor_headers"]
OBSERVER = TEST_USERS["observer_headers"]

POSTURE_ORDER = ["PRE_MAIL", "MAILING", "RECEIVING", "CANVASS_LOCKED", "CERTIFIED"]


# --- Logical clock -------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock forward to a named instant."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# --- Elections -----------------------------------------------------------------

def create_election(**overrides) -> dict:
    """Register one election. Accepts any registration field as an override."""
    return get_success_data(api_client.create_election(election_payload(**overrides), ADMIN))


def advance_posture(election_id: str, target_posture: str) -> dict:
    """Advance one election to the named posture."""
    return get_success_data(
        api_client.advance_posture(election_id, {"target_posture": target_posture}, ADMIN))


def advance_posture_to(election_id: str, target_posture: str) -> dict:
    """Walk the posture ladder one step at a time until the election reaches
    target_posture. Returns the election as reported by the final advance."""
    election = get_success_data(api_client.get_election(election_id, ADMIN))
    current = POSTURE_ORDER.index(election["posture"])
    goal = POSTURE_ORDER.index(target_posture)
    for step in range(current + 1, goal + 1):
        election = advance_posture(election_id, POSTURE_ORDER[step])
    return election


def setup_election(posture: str = "PRE_MAIL", clock: str = "2026-09-10T00:00:00Z",
                   **overrides) -> dict:
    """Set the clock, register an election, and walk it to `posture`."""
    if clock:
        set_clock(clock)
    election = create_election(**overrides)
    if posture != "PRE_MAIL":
        advance_posture_to(election["id"], posture)
        election = get_success_data(api_client.get_election(election["id"], ADMIN))
    return election


def get_election(election_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_election(election_id, headers or ADMIN))


def get_accountability(election_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_accountability(election_id, headers or ADMIN))


def run_canvass_sweep(election_id: str, headers=None) -> dict:
    """Take one canvass checkpoint. The checkpoint is an ElectionsAdmin act."""
    return get_success_data(api_client.run_canvass_sweep(election_id, {},
                                                         headers or ADMIN))


# --- Voters, reviewers, enrollments -------------------------------------------

def create_voter(**overrides) -> dict:
    """Register one voter. Defaults are a domestic, active, one-signature voter."""
    return get_success_data(api_client.create_voter(voter_payload(**overrides), CLERK))


def create_voters(count: int, **overrides) -> list:
    """Register `count` voters with distinct names and residence addresses."""
    voters = []
    for index in range(count):
        fields = dict(overrides)
        fields.setdefault("full_name", f"Voter {index + 1:02d}")
        fields.setdefault("residence_address", f"{100 + index} Sycamore Ave")
        voters.append(create_voter(**fields))
    return voters


def create_reviewer(**overrides) -> dict:
    """Register one reviewer. Defaults are TRAINED with training completed 2026-08-01."""
    return get_success_data(api_client.create_reviewer(reviewer_payload(**overrides), ADMIN))


def create_trained_reviewer(party_affiliation: str = "NPP", full_name: str = "Tess Ward",
                            training_completed_at: str = "2026-08-01T00:00:00Z",
                            **overrides) -> dict:
    return create_reviewer(full_name=full_name, party_affiliation=party_affiliation,
                           training_status="TRAINED",
                           training_completed_at=training_completed_at, **overrides)


def create_lead_reviewer(party_affiliation: str = "DEM", full_name: str = "Lena Ford",
                         training_completed_at: str = "2026-08-01T00:00:00Z",
                         **overrides) -> dict:
    return create_reviewer(full_name=full_name, party_affiliation=party_affiliation,
                           training_status="CERTIFIED_LEAD",
                           training_completed_at=training_completed_at, **overrides)


def create_enrollment(voter_id: str, headers=None) -> dict:
    """Open a permanent absentee enrollment for one voter."""
    return get_success_data(api_client.create_enrollment(voter_id, {}, headers or CLERK))


# --- Ballot requests and address verification ---------------------------------

def create_ballot_request(voter: dict, election: dict, **overrides) -> dict:
    """Open a ballot request, threading the voter's current version."""
    payload = ballot_request_payload(voter["id"], election["id"], voter["version"],
                                     **overrides)
    return get_success_data(api_client.create_ballot_request(payload, CLERK))


def get_address_verification_for(ballot_request_id: str) -> dict:
    """Read back the address verification the ballot request opened."""
    data = get_success_data(
        api_client.list_address_verifications(CLERK,
                                             params={"ballot_request_id": ballot_request_id}))
    rows = data if isinstance(data, list) else data.get("data", [])
    assert rows, f"expected an address verification for request {ballot_request_id}"
    return rows[0]


def submit_address_result(verification_id: str, ncoa_result: str = "MATCH_SAME",
                          **overrides) -> dict:
    return get_success_data(
        api_client.submit_address_result(verification_id,
                                        address_result_payload(ncoa_result, **overrides),
                                        CLERK))


def resolve_address(ballot_request_id: str, ncoa_result: str = "MATCH_SAME",
                    **overrides) -> dict:
    """Locate the request's address verification and record one NCOA result."""
    verification = get_address_verification_for(ballot_request_id)
    return submit_address_result(verification["id"], ncoa_result, **overrides)


def approve_request(ballot_request_id: str, headers=None) -> dict:
    return get_success_data(api_client.approve_ballot_request(ballot_request_id,
                                                             headers or CLERK))


def setup_approved_request(election: dict, voter: dict = None,
                           ncoa_result: str = "MATCH_SAME", **request_overrides) -> dict:
    """Voter, ballot request, cleared address verification, approval.
    Returns {"voter", "request", "verification"}."""
    voter = voter or create_voter()
    request = create_ballot_request(voter, election, **request_overrides)
    verification = resolve_address(request["id"], ncoa_result)
    approved = approve_request(request["id"])
    return {"voter": voter, "request": approved, "verification": verification}


# --- Mailing batches and packets ----------------------------------------------

def create_batch(election: dict, **overrides) -> dict:
    """Open a DRAFT mailing batch for one election."""
    return get_success_data(
        api_client.create_mailing_batch(mailing_batch_payload(election["id"], **overrides),
                                        CLERK))


def add_packet(batch_id: str, ballot_request_id: str, packet_weight_grams: int = 28) -> dict:
    return get_success_data(
        api_client.add_packet(batch_id,
                             packet_payload(ballot_request_id, packet_weight_grams),
                             CLERK))


def seal_batch(batch_id: str, headers=None) -> dict:
    return get_success_data(api_client.seal_batch(batch_id, headers or CLERK))


def dispatch_batch(batch_id: str, headers=None) -> dict:
    return get_success_data(api_client.dispatch_batch(batch_id, headers or CLERK))


def cancel_batch(batch_id: str, cancellation_reason_code: str = "PRINT_DEFECT",
                 headers=None) -> dict:
    return get_success_data(
        api_client.cancel_batch(batch_id,
                               {"cancellation_reason_code": cancellation_reason_code},
                               headers or CLERK))


def setup_sealed_batch(election: dict, weights=(28,), batch_type: str = "DOMESTIC_INITIAL",
                       scheduled_send_date: str = "2026-09-15",
                       voter_overrides: dict = None, ncoa_result: str = "MATCH_SAME",
                       request_overrides: dict = None) -> dict:
    """One batch holding one packet per entry in `weights`, sealed so its estimate
    is frozen. Returns {"election", "batch", "voters", "requests", "packets"}."""
    voter_overrides = voter_overrides or {}
    request_overrides = request_overrides or {}
    batch = create_batch(election, batch_type=batch_type,
                         scheduled_send_date=scheduled_send_date)
    voters, requests, packets = [], [], []
    for index, grams in enumerate(weights):
        fields = dict(voter_overrides)
        fields.setdefault("full_name", f"Voter {index + 1:02d}")
        fields.setdefault("residence_address", f"{200 + index} Linden Way")
        voter = create_voter(**fields)
        approved = setup_approved_request(election, voter, ncoa_result, **request_overrides)
        packets.append(add_packet(batch["id"], approved["request"]["id"], grams))
        voters.append(voter)
        requests.append(approved["request"])
    sealed = seal_batch(batch["id"])
    return {"election": election, "batch": sealed, "voters": voters,
            "requests": requests, "packets": packets}


def setup_dispatched_batch(election: dict, weights=(28,), **kwargs) -> dict:
    """Same as setup_sealed_batch, then dispatched so every packet is MAILED."""
    bundle = setup_sealed_batch(election, weights=weights, **kwargs)
    bundle["batch"] = dispatch_batch(bundle["batch"]["id"])
    bundle["packets"] = [
        get_success_data(api_client.get_ballot_packet(packet["id"], CLERK))
        for packet in bundle["packets"]
    ]
    return bundle


def setup_mailed_packets(count: int = 1, weights=None, posture: str = "RECEIVING",
                         clock: str = "2026-09-10T00:00:00Z",
                         election: dict = None, election_overrides: dict = None,
                         **kwargs) -> dict:
    """Full mailing chain from an empty database: election in `posture`, one
    dispatched batch, `count` MAILED packets. Returns the dispatched-batch bundle."""
    if election is None:
        election = setup_election(posture="MAILING", clock=clock,
                                  **(election_overrides or {}))
    weights = weights or tuple([28] * count)
    bundle = setup_dispatched_batch(election, weights=weights, **kwargs)
    if posture and posture != "MAILING":
        advance_posture_to(election["id"], posture)
    bundle["election"] = get_election(election["id"])
    return bundle


def mark_packet_undeliverable(packet_id: str,
                              undeliverable_reason_code: str = "NO_SUCH_ADDRESS",
                              headers=None) -> dict:
    return get_success_data(
        api_client.mark_packet_undeliverable(
            packet_id, {"undeliverable_reason_code": undeliverable_reason_code},
            headers or CLERK))


# --- Return envelope intake ----------------------------------------------------

def intake_envelope(packet_id: str, intake_channel: str = "DROPBOX", **overrides) -> dict:
    """Book one return envelope in against a mailed packet."""
    return get_success_data(
        api_client.create_return_envelope(
            return_envelope_payload(packet_id, intake_channel, **overrides), CLERK))


def get_envelope(envelope_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_return_envelope(envelope_id, headers or CLERK))


def setup_received_envelopes(count: int = 1, intake_at: str = "2026-11-03T12:00:00Z",
                             intake_channel: str = "DROPBOX",
                             envelope_overrides: dict = None, **kwargs) -> dict:
    """Mailing chain, then the clock moved to `intake_at`, then one envelope per
    packet. Returns the mailing bundle plus {"envelopes": [...]}."""
    bundle = setup_mailed_packets(count=count, **kwargs)
    if intake_at:
        set_clock(intake_at)
    envelope_overrides = envelope_overrides or {}
    bundle["envelopes"] = [
        intake_envelope(packet["id"], intake_channel, **envelope_overrides)
        for packet in bundle["packets"]
    ]
    bundle["election"] = get_election(bundle["election"]["id"])
    return bundle


# --- Signature review ----------------------------------------------------------

def open_review(envelope_id: str, headers=None) -> dict:
    """Open the next signature review round on one envelope; the API selects
    the reviewer, so the returned row names the assignee."""
    return get_success_data(api_client.open_signature_review(envelope_id, headers or CLERK))


def submit_decision(review: dict, decision: str = "MATCH", similarity_score: int = 90,
                    **overrides) -> dict:
    """Submit a decision as the reviewer the round was actually assigned to."""
    headers = make_signature_reviewer_headers(review["reviewer_id"])
    payload = signature_decision_payload(decision, similarity_score, **overrides)
    return get_success_data(
        api_client.submit_signature_decision(review["id"], payload, headers))


def review_and_decide(envelope_id: str, decision: str = "MATCH",
                      similarity_score: int = 90, **overrides) -> dict:
    """Open one round and immediately submit its decision. Returns the submitted review."""
    review = open_review(envelope_id)
    return submit_decision(review, decision, similarity_score, **overrides)


def setup_envelope_with_open_review(reviewers: list = None, **kwargs) -> dict:
    """A received envelope with one round-1 review assigned. Creates a single
    TRAINED reviewer unless `reviewers` is supplied, so selection is unambiguous.
    Returns the intake bundle plus {"reviewers", "envelope", "review"}."""
    reviewers = reviewers if reviewers is not None else [create_trained_reviewer()]
    bundle = setup_received_envelopes(count=1, **kwargs)
    bundle["reviewers"] = reviewers
    bundle["envelope"] = bundle["envelopes"][0]
    bundle["review"] = open_review(bundle["envelope"]["id"])
    return bundle


def setup_accepted_envelope(similarity_score: int = 95, **kwargs) -> dict:
    """A received envelope carried to ACCEPTED by one confident round-1 match."""
    bundle = setup_envelope_with_open_review(**kwargs)
    bundle["review"] = submit_decision(bundle["review"], "MATCH", similarity_score)
    bundle["envelope"] = get_envelope(bundle["envelope"]["id"])
    return bundle


def setup_escalated_envelope(similarity_score: int = 71, **kwargs) -> dict:
    """A received envelope escalated by a round-1 score below the auto-accept
    threshold. The escalated round 2 is not yet opened."""
    bundle = setup_envelope_with_open_review(**kwargs)
    bundle["review"] = submit_decision(bundle["review"], "MATCH", similarity_score)
    bundle["envelope"] = get_envelope(bundle["envelope"]["id"])
    return bundle


def setup_cure_required_envelope(reviewers: list = None, **kwargs) -> dict:
    """Two no-match rounds carry one envelope to CURE_REQUIRED. Two reviewers are
    created because no reviewer may take two rounds on the same envelope.
    Returns the bundle plus {"reviews": [round1, round2]}."""
    if reviewers is None:
        reviewers = [
            create_trained_reviewer(full_name="Tess Ward", party_affiliation="NPP"),
            create_trained_reviewer(full_name="Ivan Ruiz", party_affiliation="REP"),
        ]
    bundle = setup_envelope_with_open_review(reviewers=reviewers, **kwargs)
    round_one = submit_decision(bundle["review"], "NO_MATCH", 40)
    round_two_open = open_review(bundle["envelope"]["id"])
    round_two = submit_decision(round_two_open, "NO_MATCH", 40)
    bundle["reviews"] = [round_one, round_two]
    bundle["review"] = round_two
    bundle["envelope"] = get_envelope(bundle["envelope"]["id"])
    return bundle


# --- Cure notices and evidence -------------------------------------------------

def issue_cure_notice(envelope_id: str, headers=None) -> dict:
    return get_success_data(api_client.create_cure_notice(envelope_id, headers or CLERK))


def submit_cure_evidence(notice_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.submit_cure_evidence(notice_id, cure_evidence_payload(**overrides),
                                       headers or CLERK))


def adjudicate_cure_notice(notice_id: str, outcome: str = "CURE", headers=None,
                           **overrides) -> dict:
    return get_success_data(
        api_client.adjudicate_cure_notice(notice_id,
                                        cure_adjudication_payload(outcome, **overrides),
                                        headers or SUPERVISOR))


def get_cure_notice(notice_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_cure_notice(notice_id, headers or CLERK))


def setup_issued_cure_notice(**kwargs) -> dict:
    """An envelope in CURE_REQUIRED with one ISSUED cure notice.
    Returns the bundle plus {"cure_notice"}."""
    bundle = setup_cure_required_envelope(**kwargs)
    bundle["cure_notice"] = issue_cure_notice(bundle["envelope"]["id"])
    bundle["envelope"] = get_envelope(bundle["envelope"]["id"])
    return bundle


def setup_cure_notice_under_evidence_review(**kwargs) -> dict:
    """An ISSUED cure notice moved to UNDER_EVIDENCE_REVIEW by one submission."""
    bundle = setup_issued_cure_notice(**kwargs)
    bundle["evidence"] = submit_cure_evidence(bundle["cure_notice"]["id"])
    bundle["cure_notice"] = get_cure_notice(bundle["cure_notice"]["id"])
    return bundle


# --- Remakes -------------------------------------------------------------------

def create_bipartisan_team(party_a: str = "DEM", party_b: str = "REP") -> tuple:
    """Two TRAINED reviewers of different parties, eligible as a remake team."""
    member_a = create_trained_reviewer(full_name="Dana Moss", party_affiliation=party_a)
    member_b = create_trained_reviewer(full_name="Reid Vance", party_affiliation=party_b)
    return member_a, member_b


def open_remake(envelope: dict, member_a: dict, member_b: dict, headers=None,
                **overrides) -> dict:
    """Open a remake session on one envelope, threading its current version."""
    payload = remake_payload(member_a["id"], member_b["id"], envelope["version"],
                             **overrides)
    return get_success_data(
        api_client.create_remake(envelope["id"], payload, headers or SUPERVISOR))


def complete_remake(remake_id: str, remade_serial: str = "RM-0001", headers=None) -> dict:
    return get_success_data(
        api_client.complete_remake(remake_id, {"remade_serial": remade_serial},
                                  headers or SUPERVISOR))


def void_remake(remake_id: str, voided_reason_code: str = "TEAM_ERROR",
                headers=None) -> dict:
    return get_success_data(
        api_client.void_remake(remake_id, {"voided_reason_code": voided_reason_code},
                              headers or SUPERVISOR))


def setup_open_remake(envelope_bundle: dict = None, party_a: str = "DEM",
                      party_b: str = "REP", **kwargs) -> dict:
    """An envelope with an OPEN remake session held by a bipartisan team.
    Pass `envelope_bundle` to remake an envelope an earlier fixture produced,
    otherwise a fresh received envelope is built. Returns the bundle plus
    {"team": (a, b), "remake"}."""
    bundle = envelope_bundle or setup_received_envelopes(count=1, **kwargs)
    bundle.setdefault("envelope", bundle["envelopes"][0])
    member_a, member_b = create_bipartisan_team(party_a, party_b)
    envelope = get_envelope(bundle["envelope"]["id"])
    bundle["team"] = (member_a, member_b)
    bundle["remake"] = open_remake(envelope, member_a, member_b)
    bundle["envelope"] = get_envelope(envelope["id"])
    return bundle


def setup_completed_remake(remade_serial: str = "RM-0001", **kwargs) -> dict:
    """An OPEN remake carried through completion, so a replacement envelope exists."""
    bundle = setup_open_remake(**kwargs)
    bundle["remake"] = complete_remake(bundle["remake"]["id"], remade_serial)
    bundle["envelope"] = get_envelope(bundle["envelope"]["id"])
    bundle["replacement"] = get_envelope(bundle["remake"]["remade_envelope_id"])
    return bundle


# --- Observer access -----------------------------------------------------------

def schedule_observer_session(election_id: str, observer_user_id: str = "obs-1",
                              headers=None, **overrides) -> dict:
    """Book an observer access window. Booking is a clerk or observer act."""
    return get_success_data(
        api_client.create_observer_session(
            election_id, observer_session_payload(observer_user_id, **overrides),
            headers or CLERK))


def check_in_observer(session: dict) -> dict:
    """Check in as the observer the session was scheduled for."""
    headers = make_observer_headers(session["observer_user_id"])
    return get_success_data(api_client.check_in_observer(session["id"], headers))


def revoke_observer_session(session_id: str, revocation_reason_code: str = "MISCONDUCT",
                            headers=None) -> dict:
    return get_success_data(
        api_client.revoke_observer_session(
            session_id, {"revocation_reason_code": revocation_reason_code},
            headers or ADMIN))


def setup_checked_in_observer(election: dict, observer_user_id: str = "obs-1",
                              now: str = None, station_area: str = "SIGNATURE_REVIEW",
                              window_start_at: str = "2026-11-03T09:00:00Z",
                              window_end_at: str = "2026-11-03T18:00:00Z",
                              **overrides) -> dict:
    """A scheduled session checked in inside its window. `now` moves the clock into
    the window first. Returns {"session", "headers"}."""
    session = schedule_observer_session(election["id"], observer_user_id,
                                       station_area=station_area,
                                       window_start_at=window_start_at,
                                       window_end_at=window_end_at, **overrides)
    if now:
        set_clock(now)
    session = check_in_observer(session)
    return {"session": session, "headers": make_observer_headers(observer_user_id)}


def file_challenge(envelope_id: str, headers, challenge_reason_code: str = "SIGNATURE_DISPUTE",
                   **overrides) -> dict:
    """File an observer challenge. `headers` must belong to a checked-in observer."""
    return get_success_data(
        api_client.file_challenge(envelope_id,
                                challenge_payload(challenge_reason_code, **overrides),
                                headers))


def adjudicate_challenge(envelope_id: str, outcome: str = "OVERRULE", headers=None,
                         **overrides) -> dict:
    return get_success_data(
        api_client.adjudicate_challenge(envelope_id,
                                      challenge_adjudication_payload(outcome, **overrides),
                                      headers or SUPERVISOR))


# --- Separation, counting, sweeps ----------------------------------------------

def run_separation(election_id: str, envelope_ids, headers=None) -> dict:
    return get_success_data(
        api_client.create_separation_run(election_id,
                                       separation_run_payload(envelope_ids),
                                       headers or SUPERVISOR))


def count_envelope(envelope_id: str, headers=None) -> dict:
    return get_success_data(api_client.count_envelope(envelope_id, headers or SUPERVISOR))


def setup_accepted_envelope_pool(count: int = 3, similarity_score: int = 95,
                                 intake_at: str = "2026-11-03T12:00:00Z",
                                 intake_channel: str = "DROPBOX",
                                 reviewers: list = None,
                                 envelope_overrides: dict = None, **kwargs) -> dict:
    """`count` received envelopes, each carried to ACCEPTED by a confident round-1
    match. One reviewer per envelope is created, because no reviewer may take two
    rounds on the same envelope and a single reviewer would still be eligible here.
    Returns the intake bundle plus {"reviews": [...]} with envelopes refreshed."""
    if reviewers is None:
        reviewers = [
            create_trained_reviewer(full_name=f"Reviewer {index + 1:02d}",
                                    party_affiliation="NPP")
            for index in range(count)
        ]
    bundle = setup_received_envelopes(count=count, intake_at=intake_at,
                                     intake_channel=intake_channel,
                                     envelope_overrides=envelope_overrides, **kwargs)
    bundle["reviewers"] = reviewers
    bundle["reviews"] = [
        review_and_decide(envelope["id"], "MATCH", similarity_score)
        for envelope in bundle["envelopes"]
    ]
    bundle["envelopes"] = [get_envelope(envelope["id"]) for envelope in bundle["envelopes"]]
    bundle["election"] = get_election(bundle["election"]["id"])
    return bundle


def setup_separated_envelope_pool(count: int = 3, **kwargs) -> dict:
    """An accepted pool of `count` envelopes carried through one separation run,
    so every envelope is SEPARATED. Returns the pool bundle plus {"separation_run"}."""
    bundle = setup_accepted_envelope_pool(count=count, **kwargs)
    bundle["separation_run"] = run_separation(
        bundle["election"]["id"], [envelope["id"] for envelope in bundle["envelopes"]])
    bundle["envelopes"] = [get_envelope(envelope["id"]) for envelope in bundle["envelopes"]]
    bundle["election"] = get_election(bundle["election"]["id"])
    return bundle


# --- Transparency log ----------------------------------------------------------

def list_transparency_log(election_id: str, headers=None, **params) -> list:
    query = {"election_id": election_id}
    query.update(params)
    data = get_success_data(api_client.list_transparency_log(headers or ADMIN, params=query))
    return data if isinstance(data, list) else data.get("data", [])


def transparency_event_types(election_id: str, headers=None) -> list:
    """Event types recorded for one election, in sequence order."""
    return [entry["event_type"] for entry in list_transparency_log(election_id, headers)]
