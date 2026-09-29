"""Staged scenario builders.

Each test starts against an empty service, so every scenario is assembled from
scratch through the declared endpoints only — no seeded rows, no direct writes.
The builders are layered: each one calls the previous layer and then advances
the election one step, so a test can stop at exactly the stage its rule needs.

All builders use the lenient success reader, because a fixture only needs the
resource it just created; the assertions that matter belong in the tests.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from . import test_users as users
from .api_client import BallotProductionApiClient
from .constants import (
    ASSET_TAG_1,
    BASIS_FINAL_CANVASS,
    CLOCK_START,
    FIRMWARE_VERSION,
    POLL_CLOSE_INSTANT,
    PRECINCT_CODE_1,
    SEAL_1,
    SEAL_TAB_1,
    SESSION_START,
    STYLE_CODE_MAIN,
)


@dataclass
class Scenario:
    """Mutable handle on everything a builder has created so far."""

    client: BallotProductionApiClient
    election_id: str = ""
    election: Dict[str, Any] = field(default_factory=dict)
    contest_ids: List[str] = field(default_factory=list)
    candidate_ids: List[str] = field(default_factory=list)
    precinct_ids: List[str] = field(default_factory=list)
    style_ids: List[str] = field(default_factory=list)
    vendor_id: str = ""
    job_ids: List[str] = field(default_factory=list)
    lot_ids: List[str] = field(default_factory=list)
    tabulator_ids: List[str] = field(default_factory=list)
    deck_ids: List[str] = field(default_factory=list)
    session_ids: List[str] = field(default_factory=list)

    # ─── Convenience accessors for the single-of-each happy path ─────────────

    @property
    def contest_id(self) -> str:
        return self.contest_ids[0]

    @property
    def candidate_id(self) -> str:
        return self.candidate_ids[0]

    @property
    def precinct_id(self) -> str:
        return self.precinct_ids[0]

    @property
    def style_id(self) -> str:
        return self.style_ids[0]

    @property
    def job_id(self) -> str:
        return self.job_ids[0]

    @property
    def lot_id(self) -> str:
        return self.lot_ids[0]

    @property
    def tabulator_id(self) -> str:
        return self.tabulator_ids[0]

    @property
    def deck_id(self) -> str:
        return self.deck_ids[0]

    @property
    def session_id(self) -> str:
        return self.session_ids[0]

    @property
    def vendor_headers(self) -> Dict[str, str]:
        return users.vendor_rep(self.vendor_id)

    # ─── Live reads ─────────────────────────────────────────────────────────

    def read_election(self) -> Dict[str, Any]:
        return get_success_data(self.client.get_election(self.election_id, users.DIRECTOR))

    def election_version(self) -> int:
        return self.read_election()["version"]

    def read_style(self, style_id: Optional[str] = None) -> Dict[str, Any]:
        return get_success_data(
            self.client.get_ballot_style(style_id or self.style_id, users.DIRECTOR))

    def style_version(self, style_id: Optional[str] = None) -> int:
        return self.read_style(style_id)["version"]

    def read_precinct(self, precinct_id: Optional[str] = None) -> Dict[str, Any]:
        return get_success_data(
            self.client.get_precinct(precinct_id or self.precinct_id, users.DIRECTOR))

    def read_job(self, job_id: Optional[str] = None) -> Dict[str, Any]:
        return get_success_data(
            self.client.get_print_job(job_id or self.job_id, users.DIRECTOR))

    def read_lot(self, lot_id: Optional[str] = None) -> Dict[str, Any]:
        return get_success_data(
            self.client.get_ballot_lot(lot_id or self.lot_id, users.DIRECTOR))

    def read_tabulator(self, tabulator_id: Optional[str] = None) -> Dict[str, Any]:
        return get_success_data(
            self.client.get_tabulator(tabulator_id or self.tabulator_id, users.DIRECTOR))

    def read_session(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        return get_success_data(
            self.client.get_la_session(session_id or self.session_id, users.DIRECTOR))

    def read_contest(self, contest_id: Optional[str] = None) -> Dict[str, Any]:
        return get_success_data(
            self.client.get_contest(contest_id or self.contest_id, users.DIRECTOR))

    def custody_events(self) -> List[Dict[str, Any]]:
        response = self.client.list_custody_events(
            self.election_id, users.DIRECTOR, {"limit": 100})
        return response.json()["data"]

    def lots_of_job(self, job_id: Optional[str] = None) -> List[Dict[str, Any]]:
        response = self.client.list_ballot_lots(
            users.DIRECTOR, {"print_job_id": job_id or self.job_id, "limit": 100})
        return response.json()["data"]

    def candidates_of(self, contest_id: Optional[str] = None) -> List[Dict[str, Any]]:
        response = self.client.list_candidates(
            contest_id or self.contest_id, users.DIRECTOR, {"limit": 100})
        return response.json()["data"]


# ─── Clock ───────────────────────────────────────────────────────────────────

def set_clock(client: BallotProductionApiClient, instant: str) -> None:
    """Move the server logical clock to ``instant``."""
    response = client.set_clock(instant, users.DIRECTOR)
    assert response.status_code == 200, (
        f"setting the logical clock to {instant} failed with {response.status_code}: "
        f"{response.text}"
    )


# ─── Stage 1: a registered election ──────────────────────────────────────────

def new_election(client: BallotProductionApiClient, clock: str = CLOCK_START,
                 **overrides: Any) -> Scenario:
    """Register an election in its initial phase with the clock at ``clock``."""
    set_clock(client, clock)
    data = get_success_data(
        client.create_election(f.election_payload(**overrides), users.DIRECTOR))
    return Scenario(client=client, election_id=data["id"], election=data)


# ─── Stage 2: contests and candidates ────────────────────────────────────────

def add_contest(sc: Scenario, title: str = "County Sheriff", **overrides: Any) -> str:
    data = get_success_data(
        sc.client.create_contest(sc.election_id, f.contest_payload(title, **overrides),
                                 users.COORDINATOR))
    sc.contest_ids.append(data["id"])
    return data["id"]


def add_candidate(sc: Scenario, contest_id: Optional[str] = None,
                  full_name: str = "Ana Alvarez", ballot_name: str = "Alvarez",
                  filing_received_at: str = "2026-06-01T09:00:00Z",
                  **overrides: Any) -> str:
    data = get_success_data(
        sc.client.create_candidate(
            contest_id or sc.contest_id,
            f.candidate_payload(full_name, ballot_name, filing_received_at, **overrides),
            users.COORDINATOR))
    sc.candidate_ids.append(data["id"])
    return data["id"]


def certify_contest(sc: Scenario, contest_id: Optional[str] = None) -> Dict[str, Any]:
    return get_success_data(
        sc.client.certify_contest(contest_id or sc.contest_id, users.DIRECTOR))


def add_style(sc: Scenario, style_code: str = STYLE_CODE_MAIN,
              district_codes: Optional[List[str]] = None, **overrides: Any) -> str:
    data = get_success_data(
        sc.client.create_ballot_style(
            sc.election_id,
            f.ballot_style_payload(style_code, district_codes, **overrides),
            users.COORDINATOR))
    sc.style_ids.append(data["id"])
    return data["id"]


def add_precinct(sc: Scenario, precinct_code: str = PRECINCT_CODE_1,
                 district_codes: Optional[List[str]] = None,
                 registered_voter_count: int = 100, **overrides: Any) -> str:
    data = get_success_data(
        sc.client.create_precinct(
            sc.election_id,
            f.precinct_payload(precinct_code, district_codes, registered_voter_count,
                               **overrides),
            users.COORDINATOR))
    sc.precinct_ids.append(data["id"])
    return data["id"]


def contests_certified(client: BallotProductionApiClient, clock: str = CLOCK_START,
                       election_overrides: Optional[Dict[str, Any]] = None,
                       registered_voter_count: int = 100) -> Scenario:
    """Election with one certified single-candidate contest, one style, one precinct,
    and the ballot order frozen."""
    sc = new_election(client, clock, **(election_overrides or {}))
    add_contest(sc)
    add_candidate(sc)
    certify_contest(sc)
    add_style(sc)
    add_precinct(sc, registered_voter_count=registered_voter_count)
    get_success_data(sc.client.certify_ballot_order(sc.election_id, users.DIRECTOR))
    return sc


# ─── Stage 3: proofing, assignment and the style lock ────────────────────────

def certify_languages(sc: Scenario, style_id: Optional[str] = None,
                      **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        sc.client.create_language_certifications(
            style_id or sc.style_id,
            f.language_certification_payload(**overrides),
            users.LANGUAGE_COORDINATOR))


def approve_proof_cycle(sc: Scenario, style_id: Optional[str] = None,
                        decision: str = "APPROVE") -> Dict[str, Any]:
    """Send the style out for proofing and have a second user decide it."""
    target = style_id or sc.style_id
    get_success_data(sc.client.request_proof(target, users.COORDINATOR))
    return get_success_data(
        sc.client.proof_decision(target, f.proof_decision_payload(decision), users.DIRECTOR))


def assign_style(sc: Scenario, precinct_id: Optional[str] = None,
                 style_id: Optional[str] = None) -> Dict[str, Any]:
    return get_success_data(
        sc.client.assign_style(precinct_id or sc.precinct_id,
                               f.assign_style_payload(style_id or sc.style_id),
                               users.COORDINATOR))


def styles_locked(client: BallotProductionApiClient, clock: str = CLOCK_START,
                  election_overrides: Optional[Dict[str, Any]] = None,
                  registered_voter_count: int = 100) -> Scenario:
    """Election advanced through proofing and style assignment to the locked phase."""
    sc = contests_certified(client, clock, election_overrides, registered_voter_count)
    certify_languages(sc)
    approve_proof_cycle(sc)
    assign_style(sc)
    get_success_data(sc.client.lock_styles(sc.election_id, users.DIRECTOR))
    return sc


# ─── Stage 4: the print run ──────────────────────────────────────────────────

def add_vendor(sc: Scenario, **overrides: Any) -> str:
    data = get_success_data(
        sc.client.create_print_vendor(f.print_vendor_payload(**overrides), users.DIRECTOR))
    sc.vendor_id = data["id"]
    return data["id"]


def add_print_job(sc: Scenario, style_id: Optional[str] = None,
                  vendor_id: Optional[str] = None, quantity_ordered: int = 12500,
                  **overrides: Any) -> str:
    target_style = style_id or sc.style_id
    payload = f.print_job_payload(
        vendor_id or sc.vendor_id, target_style, sc.style_version(target_style),
        quantity_ordered=quantity_ordered, **overrides)
    data = get_success_data(sc.client.create_print_job(payload, users.COORDINATOR))
    sc.job_ids.append(data["id"])
    return data["id"]


def printed_job(sc: Scenario, job_id: Optional[str] = None) -> Dict[str, Any]:
    """Approve the press proof so the job is on press with its estimate invoice."""
    return get_success_data(
        sc.client.approve_press_proof(job_id or sc.job_id, users.DIRECTOR))


def inspect_job(sc: Scenario, sample_size: int = 500, defect_count: int = 6,
                job_id: Optional[str] = None) -> Dict[str, Any]:
    return get_success_data(
        sc.client.inspect_print_job(job_id or sc.job_id,
                                    f.inspect_payload(sample_size, defect_count),
                                    users.CUSTODIAN))


def deliver_job(sc: Scenario, lots: Optional[List[Dict[str, Any]]] = None,
                job_id: Optional[str] = None) -> Dict[str, Any]:
    """Record the vendor delivery and remember the created lot ids in manifest order."""
    target = job_id or sc.job_id
    result = get_success_data(
        sc.client.deliver_print_job(target, f.deliver_payload(lots), sc.vendor_headers))
    for lot in sc.lots_of_job(target):
        if lot["id"] not in sc.lot_ids:
            sc.lot_ids.append(lot["id"])
    return result


def delivered_lot(client: BallotProductionApiClient, clock: str = CLOCK_START,
                  election_overrides: Optional[Dict[str, Any]] = None,
                  registered_voter_count: int = 100,
                  quantity_ordered: int = 12500,
                  lots: Optional[List[Dict[str, Any]]] = None) -> Scenario:
    """Locked election with one delivered print job and its ballot lots in transit."""
    sc = styles_locked(client, clock, election_overrides, registered_voter_count)
    add_vendor(sc)
    add_print_job(sc, quantity_ordered=quantity_ordered)
    printed_job(sc)
    inspect_job(sc)
    deliver_job(sc, lots)
    return sc


def receive_lot(sc: Scenario, lot_id: Optional[str] = None,
                seal_number: str = SEAL_1,
                quantity_received: int = 12500) -> Dict[str, Any]:
    return get_success_data(
        sc.client.receive_lot(lot_id or sc.lot_id,
                              f.receive_payload(seal_number, quantity_received),
                              users.CUSTODIAN))


def issue_lot(sc: Scenario, lot_id: Optional[str] = None,
              precinct_id: Optional[str] = None,
              issue_quantity: int = 3000) -> Dict[str, Any]:
    return get_success_data(
        sc.client.issue_lot(lot_id or sc.lot_id,
                            f.issue_payload(precinct_id or sc.precinct_id, issue_quantity),
                            users.CUSTODIAN))


def issued_lot(client: BallotProductionApiClient, clock: str = CLOCK_START,
               registered_voter_count: int = 100,
               issue_quantity: int = 3000,
               election_overrides: Optional[Dict[str, Any]] = None) -> Scenario:
    """Delivered election whose single lot has been received and issued to the precinct."""
    sc = delivered_lot(client, clock, election_overrides, registered_voter_count)
    receive_lot(sc)
    issue_lot(sc, issue_quantity=issue_quantity)
    return sc


# ─── Stage 5: tabulators, decks and the public logic-and-accuracy test ───────

def add_tabulator(sc: Scenario, asset_tag: str = ASSET_TAG_1,
                  firmware_version: str = FIRMWARE_VERSION, **overrides: Any) -> str:
    data = get_success_data(
        sc.client.create_tabulator(sc.election_id,
                                   f.tabulator_payload(asset_tag, firmware_version, **overrides),
                                   users.TECHNICIAN))
    sc.tabulator_ids.append(data["id"])
    return data["id"]


def program_unit(sc: Scenario, tabulator_id: Optional[str] = None,
                 style_id: Optional[str] = None,
                 firmware_version: str = FIRMWARE_VERSION,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Program a unit for a style. The programming technician is deliberately a
    different person from the one who conducts the public test."""
    return get_success_data(
        sc.client.program_tabulator(
            tabulator_id or sc.tabulator_id,
            f.program_payload(style_id or sc.style_id, firmware_version),
            headers or users.TECHNICIAN))


def add_test_deck(sc: Scenario, style_id: Optional[str] = None,
                  contest_id: Optional[str] = None,
                  candidate_id: Optional[str] = None,
                  deck_code: str = "DECK-A", ballot_count: int = 2,
                  blank_count: int = 1, overvote_count: int = 0,
                  mark_count: int = 1,
                  expected_marks: Optional[List[Dict[str, Any]]] = None,
                  headers: Optional[Dict[str, str]] = None) -> str:
    marks = expected_marks if expected_marks is not None else [
        f.expected_mark(contest_id or sc.contest_id, candidate_id or sc.candidate_id, mark_count)
    ]
    data = get_success_data(
        sc.client.create_test_deck(
            style_id or sc.style_id,
            f.test_deck_payload(marks, deck_code, ballot_count, blank_count, overvote_count),
            headers or users.TECHNICIAN))
    sc.deck_ids.append(data["id"])
    return data["id"]


def schedule_session(sc: Scenario, tabulator_id: Optional[str] = None,
                     deck_id: Optional[str] = None,
                     scheduled_start: str = SESSION_START,
                     headers: Optional[Dict[str, str]] = None,
                     **overrides: Any) -> str:
    data = get_success_data(
        sc.client.create_la_session(
            f.la_session_payload(tabulator_id or sc.tabulator_id, deck_id or sc.deck_id,
                                 scheduled_start=scheduled_start, **overrides),
            headers or users.TECHNICIAN_2))
    sc.session_ids.append(data["id"])
    return data["id"]


def sign_in_observers(sc: Scenario, session_id: Optional[str] = None,
                      names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    target = session_id or sc.session_id
    roster = names if names is not None else ["Iris Nolan", "Omar Pratt"]
    return [
        get_success_data(
            sc.client.add_observer(target, f.observer_payload(name), users.OBSERVER))
        for name in roster
    ]


def start_session(sc: Scenario, session_id: Optional[str] = None,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        sc.client.start_session(session_id or sc.session_id, headers or users.TECHNICIAN_2))


def record_matching_results(sc: Scenario, session_id: Optional[str] = None,
                            contest_id: Optional[str] = None,
                            candidate_id: Optional[str] = None,
                            mark_count: int = 1, blank_count: int = 1,
                            overvote_count: int = 0,
                            reported_marks: Optional[List[Dict[str, Any]]] = None,
                            headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Report tallies that match the deck exactly, so the session passes."""
    marks = reported_marks if reported_marks is not None else [
        f.reported_mark(contest_id or sc.contest_id, candidate_id or sc.candidate_id, mark_count)
    ]
    return get_success_data(
        sc.client.record_results(
            session_id or sc.session_id,
            f.record_results_payload(marks, blank_count, overvote_count),
            headers or users.TECHNICIAN_2))


def la_passed_unit(client: BallotProductionApiClient, clock: str = CLOCK_START,
                   registered_voter_count: int = 100,
                   issue_quantity: int = 3000,
                   session_start: str = SESSION_START,
                   election_overrides: Optional[Dict[str, Any]] = None) -> Scenario:
    """Issued-paper election with one programmed unit that has passed its public test.

    The clock is left at the session start instant, inside the test window.
    """
    sc = issued_lot(client, clock, registered_voter_count, issue_quantity, election_overrides)
    add_tabulator(sc)
    program_unit(sc)
    add_test_deck(sc)
    schedule_session(sc, scheduled_start=session_start)
    sign_in_observers(sc)
    set_clock(client, session_start)
    start_session(sc)
    record_matching_results(sc)
    return sc


# ─── Stage 6: deployment, poll close and reconciliation ─────────────────────

def deploy_unit(sc: Scenario, tabulator_id: Optional[str] = None,
                precinct_id: Optional[str] = None,
                seal_number: str = SEAL_TAB_1) -> Dict[str, Any]:
    return get_success_data(
        sc.client.deploy_tabulator(
            tabulator_id or sc.tabulator_id,
            f.deploy_unit_payload(precinct_id or sc.precinct_id, seal_number),
            users.CUSTODIAN))


def deployed_election(client: BallotProductionApiClient, clock: str = CLOCK_START,
                      registered_voter_count: int = 100,
                      issue_quantity: int = 3000,
                      session_start: str = SESSION_START,
                      election_overrides: Optional[Dict[str, Any]] = None) -> Scenario:
    """Election whose only precinct is ready and which has been declared deployed."""
    sc = la_passed_unit(client, clock, registered_voter_count, issue_quantity,
                        session_start, election_overrides)
    deploy_unit(sc)
    get_success_data(sc.client.deploy_election(sc.election_id, users.DIRECTOR))
    return sc


def polls_closed_election(client: BallotProductionApiClient, clock: str = CLOCK_START,
                          registered_voter_count: int = 100,
                          issue_quantity: int = 3000,
                          session_start: str = SESSION_START,
                          close_instant: str = POLL_CLOSE_INSTANT,
                          election_overrides: Optional[Dict[str, Any]] = None) -> Scenario:
    """Deployed election advanced to the poll-close phase with the clock at close."""
    sc = deployed_election(client, clock, registered_voter_count, issue_quantity,
                           session_start, election_overrides)
    set_clock(client, close_instant)
    get_success_data(sc.client.close_polls(sc.election_id, users.DIRECTOR))
    return sc


def return_lot_counts(sc: Scenario, lot_id: Optional[str] = None,
                      voted_quantity: int = 2900, spoiled_quantity: int = 30,
                      returned_unused_quantity: int = 70) -> Dict[str, Any]:
    return get_success_data(
        sc.client.return_counts(
            lot_id or sc.lot_id,
            f.return_counts_payload(voted_quantity, spoiled_quantity,
                                    returned_unused_quantity),
            users.CUSTODIAN))


def reconcile(sc: Scenario, basis: str = BASIS_FINAL_CANVASS) -> Dict[str, Any]:
    """Reconcile on a freshly read election version."""
    return get_success_data(
        sc.client.reconcile(sc.election_id,
                            f.reconcile_payload(basis, sc.election_version()),
                            users.DIRECTOR))


def reconciled_election(client: BallotProductionApiClient, clock: str = CLOCK_START,
                        registered_voter_count: int = 100,
                        issue_quantity: int = 3000,
                        basis: str = BASIS_FINAL_CANVASS,
                        election_overrides: Optional[Dict[str, Any]] = None) -> Scenario:
    """Poll-closed election whose lot has reported its counts and been reconciled."""
    sc = polls_closed_election(client, clock, registered_voter_count, issue_quantity,
                               election_overrides=election_overrides)
    lot = sc.read_lot()
    issued = lot["issued_quantity"]
    voted = issued - 30 - 20 if issued > 50 else 0
    return_lot_counts(sc, voted_quantity=voted, spoiled_quantity=30,
                      returned_unused_quantity=20)
    reconcile(sc, basis)
    return sc


__all__ = [
    "Scenario",
    "set_clock",
    "new_election",
    "add_contest",
    "add_candidate",
    "certify_contest",
    "add_style",
    "add_precinct",
    "contests_certified",
    "certify_languages",
    "approve_proof_cycle",
    "assign_style",
    "styles_locked",
    "add_vendor",
    "add_print_job",
    "printed_job",
    "inspect_job",
    "deliver_job",
    "delivered_lot",
    "receive_lot",
    "issue_lot",
    "issued_lot",
    "add_tabulator",
    "program_unit",
    "add_test_deck",
    "schedule_session",
    "sign_in_observers",
    "start_session",
    "record_matching_results",
    "la_passed_unit",
    "deploy_unit",
    "deployed_election",
    "polls_closed_election",
    "return_lot_counts",
    "reconcile",
    "reconciled_election",
]
