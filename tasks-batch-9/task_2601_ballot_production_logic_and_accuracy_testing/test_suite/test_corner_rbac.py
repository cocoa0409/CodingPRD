"""Who may act, and when holding the right role is still not enough.

The role model is flat: the elections director cannot borrow the ballot
coordinator's endpoints, and the warehouse custodian cannot borrow the vendor's.
Two operations go further and bind to a person rather than to a role — proof
sign-off and logic-and-accuracy results entry — while a print vendor's
representative is the one identity that must resolve to a stored vendor row.
"""

from typing import Tuple

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as errs
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_client import BallotProductionApiClient

_NOT_A_VENDOR = "user-not-a-vendor"


def _printing_job(client: BallotProductionApiClient) -> Tuple[fx.Scenario, str]:
    """A locked election whose single print job is on press, so only roles are wrong."""
    sc = fx.styles_locked(client)
    vendor_id = fx.add_vendor(sc)
    fx.add_print_job(sc)
    fx.printed_job(sc)
    return sc, vendor_id


def _qc_passed_job_and_second_vendor(
        client: BallotProductionApiClient) -> Tuple[fx.Scenario, str]:
    """A shippable job owned by one vendor, beside a second equally certified vendor."""
    sc = fx.styles_locked(client)
    fx.add_vendor(sc)
    fx.add_print_job(sc)
    fx.printed_job(sc)
    fx.inspect_job(sc)
    other_vendor = validate_success(
        client.create_print_vendor(
            f.print_vendor_payload(name="Harbor Press", press_line_count=3),
            users.DIRECTOR),
        expected_status=201)["id"]
    return sc, other_vendor


def _open_public_session(client: BallotProductionApiClient) -> fx.Scenario:
    """A public test session opened by the second technician, awaiting its results."""
    sc = fx.styles_locked(client)
    fx.add_tabulator(sc)
    fx.program_unit(sc)
    fx.add_test_deck(sc, ballot_count=1, blank_count=1, expected_marks=[])
    fx.schedule_session(sc)
    fx.sign_in_observers(sc)
    fx.set_clock(client, c.SESSION_START)
    fx.start_session(sc)
    return sc


def _style_in_proofing(client: BallotProductionApiClient) -> fx.Scenario:
    """A style out for proof, requested by the first ballot coordinator."""
    sc = fx.contests_certified(client)
    fx.certify_languages(sc)
    validate_success(client.request_proof(sc.style_id, users.COORDINATOR))
    return sc


# ---- Exclusive operations admit exactly one role ----

def test_rbac_exclusive_operations_refuse_every_other_role(client):
    """Seven operations refuse the wrong role with one identifier, and the same call from the right role succeeds.

    PRD Section 2.1: "If it names a recognized role that the target operation does not admit, the request is rejected with `ERR_UNAUTHORIZED`."

    PRD Section 2.1: "Authorization is checked before anything else about the request is examined — before the payload schema, before the addressed resource is looked up."

    PRD Section 3.7: "A `VotingSystemTechnician` intakes a unit into the vault while the election is in `SETUP`, `CONTESTS_CERTIFIED` or `STYLES_LOCKED`, supplying the `asset_tag` stencilled on the machine (unique within the election) and optionally the `firmware_version` observed at intake."

    PRD Section 3.5: "Quality inspection belongs to the `WarehouseCustodian`, is not gated on the election phase, and requires the job to be `PRINTING` or `QC_HOLD` — inspecting a `PROOF_PENDING`, `QC_PASSED`, `DELIVERED` or `REJECTED` job is `ERR_JOB_STATE_INVALID`."

    Design: Corner/rbac/rbac_exclusive_operations_reject_every_other_role_returns_403
    """
    sc, vendor_id = _printing_job(client)
    style_version = sc.style_version()

    refusals = [
        client.lock_styles(sc.election_id, users.COORDINATOR),
        client.create_ballot_style(
            sc.election_id, f.ballot_style_payload(style_code=c.STYLE_CODE_ALT),
            users.DIRECTOR),
        client.create_language_certifications(
            sc.style_id, f.language_certification_payload(), users.COORDINATOR),
        client.create_print_job(
            f.print_job_payload(vendor_id, sc.style_id, style_version,
                                quantity_ordered=500),
            users.DIRECTOR),
        client.create_tabulator(
            sc.election_id, f.tabulator_payload(asset_tag=c.ASSET_TAG_2),
            users.CUSTODIAN),
        client.inspect_print_job(sc.job_id, f.inspect_payload(),
                                 users.vendor_rep(vendor_id)),
        client.deliver_print_job(sc.job_id, f.deliver_payload(), users.CUSTODIAN),
    ]
    for response in refusals:
        assert response.status_code == 403, response.text
        validate_error(response, errs.ERR_UNAUTHORIZED)

    inspected = validate_success(
        client.inspect_print_job(sc.job_id, f.inspect_payload(), users.CUSTODIAN))
    assert inspected["status"] == c.JOB_QC_PASSED
    assert inspected["defect_rate_bp"] == 120

    assert sc.read_election()["status"] == c.PHASE_STYLES_LOCKED
    _, styles_meta = validate_paginated(
        client.list_ballot_styles(users.DIRECTOR, {"election_id": sc.election_id}))
    assert styles_meta["total_count"] == 1
    _, jobs_meta = validate_paginated(
        client.list_print_jobs(users.DIRECTOR, {"election_id": sc.election_id}))
    assert jobs_meta["total_count"] == 1
    _, units_meta = validate_paginated(
        client.list_tabulators(users.TECHNICIAN, {"election_id": sc.election_id}))
    assert units_meta["total_count"] == 0


# ---- Shared creation and shared reads ----

def test_rbac_filings_are_accepted_from_either_office_role(client):
    """Contests, candidates and precincts may be filed by the director or the coordinator, with identical results.

    PRD Section 3.1: "Contests are filed while the election is still in `SETUP`, by either an `ElectionsDirector` or a `BallotCoordinator`."

    PRD Section 3.3: "Precincts are registered by an `ElectionsDirector` or a `BallotCoordinator` while the election is in `SETUP` or `CONTESTS_CERTIFIED`."

    PRD Section 3.3: "Registration derives the precinct's statutory print requirement immediately: `required_ballot_quantity` is the registered voter count multiplied by 11 and divided by 10 — the statutory 110 percent floor — rounded **up** to the next whole ballot, so the floor is never undershot."

    Design: Corner/rbac/rbac_shared_creation_operations_accepted_for_both_declared_roles
    """
    sc = fx.new_election(client)

    by_director = validate_success(
        client.create_contest(
            sc.election_id,
            f.contest_payload(title="County Sheriff", district_code=c.DISTRICT_D12,
                              seats_open=1),
            users.DIRECTOR),
        expected_status=201)
    by_coordinator = validate_success(
        client.create_contest(
            sc.election_id,
            f.contest_payload(title="Bond Measure A",
                              contest_type=c.CONTEST_TYPE_MEASURE,
                              district_code=c.DISTRICT_D07, seats_open=1),
            users.COORDINATOR),
        expected_status=201)
    assert by_director["status"] == c.CONTEST_DRAFT
    assert by_coordinator["status"] == c.CONTEST_DRAFT
    for contest in (by_director, by_coordinator):
        assert contest["ballot_order_index"] is None
        assert contest["certified_candidate_count"] == 0
    assert set(by_director.keys()) == set(by_coordinator.keys())

    filed_by_director = validate_success(
        client.create_candidate(by_director["id"], f.candidate_payload(), users.DIRECTOR),
        expected_status=201)
    filed_by_coordinator = validate_success(
        client.create_candidate(
            by_director["id"],
            f.candidate_payload(full_name="Ben Brooks", ballot_name="Brooks",
                                filing_received_at="2026-06-02T09:00:00Z",
                                party_code="GRN"),
            users.COORDINATOR),
        expected_status=201)
    assert filed_by_director["status"] == c.CANDIDATE_FILED
    assert filed_by_coordinator["status"] == c.CANDIDATE_FILED

    precinct_by_director = validate_success(
        client.create_precinct(
            sc.election_id,
            f.precinct_payload(c.PRECINCT_CODE_1, [c.DISTRICT_D12], 100),
            users.DIRECTOR),
        expected_status=201)
    precinct_by_coordinator = validate_success(
        client.create_precinct(
            sc.election_id,
            f.precinct_payload(c.PRECINCT_CODE_2, [c.DISTRICT_D07], 100),
            users.COORDINATOR),
        expected_status=201)
    assert precinct_by_director["required_ballot_quantity"] == 110
    assert precinct_by_coordinator["required_ballot_quantity"] == 110


def test_rbac_reads_are_open_to_the_roles_that_never_write(client):
    """The language coordinator, the public observer and a vendor's representative read what the director reads.

    PRD Section 2.1: "A `PublicObserver` may sign in to a scheduled logic-and-accuracy session and read anything; it may mutate nothing else."

    PRD Section 2.1: "When `X-User-Role` is `PrintVendorRep`, `X-User-ID` is the `id` of the acting `PrintVendor`; ownership checks compare the addressed print job's `vendor_id` to `X-User-ID`, and a representative of a different vendor recording a delivery is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/rbac_shared_creation_operations_accepted_for_both_declared_roles
    """
    sc = fx.new_election(client)
    sheriff = fx.add_contest(sc, title="County Sheriff", district_code=c.DISTRICT_D12,
                             seats_open=1)
    measure = fx.add_contest(sc, title="Bond Measure A",
                             contest_type=c.CONTEST_TYPE_MEASURE,
                             district_code=c.DISTRICT_D07, seats_open=1)
    vendor_id = fx.add_vendor(sc)

    seen_by_language = validate_success(
        client.get_election(sc.election_id, users.LANGUAGE_COORDINATOR))
    seen_by_observer = validate_success(
        client.get_election(sc.election_id, users.OBSERVER))
    assert seen_by_language["status"] == c.PHASE_SETUP
    assert seen_by_observer["status"] == c.PHASE_SETUP
    assert seen_by_observer["certified_contest_count"] == 0

    rows, meta = validate_paginated(
        client.list_contests(sc.election_id, users.vendor_rep(vendor_id)))
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {sheriff, measure}


# ---- Deck building and observer sign-in are shared by two roles each ----

def test_rbac_deck_building_is_shared_and_still_records_the_builder(client):
    """Either the technician or the coordinator may build a deck, and each deck remembers who built it.

    PRD Section 3.8: "A `VotingSystemTechnician` or `BallotCoordinator` builds a deck against an `APPROVED` or `LOCKED` style while the election is `CONTESTS_CERTIFIED` or `STYLES_LOCKED`, supplying a `deck_code` unique within the style, a `ballot_count`, a `blank_count`, an `overvote_count`, and `expected_marks` — an array of objects each naming a `contest_id`, a `candidate_id` and an integer `mark_count` of at least 1."

    PRD Section 3.8: "An accepted deck is created in `DRAFT` with the derived `expected_total_marks` and `created_by_user_id` set to the builder's `X-User-ID`."

    Design: Corner/rbac/rbac_test_deck_creation_shared_by_technician_and_coordinator
    """
    sc = fx.styles_locked(client)
    fx.add_tabulator(sc)
    fx.program_unit(sc)
    fx.add_test_deck(sc, deck_code="DECK-A", ballot_count=1, blank_count=1,
                     expected_marks=[])

    by_coordinator = validate_success(
        client.create_test_deck(
            sc.style_id,
            f.test_deck_payload([], deck_code="DECK-B", ballot_count=1, blank_count=1),
            users.COORDINATOR),
        expected_status=201)
    by_technician = validate_success(
        client.create_test_deck(
            sc.style_id,
            f.test_deck_payload([], deck_code="DECK-C", ballot_count=1, blank_count=1),
            users.TECHNICIAN),
        expected_status=201)

    assert by_coordinator["status"] == c.DECK_DRAFT
    assert by_technician["status"] == c.DECK_DRAFT
    assert by_coordinator["expected_total_marks"] == 0
    assert by_technician["expected_total_marks"] == 0
    assert by_coordinator["created_by_user_id"] == c.USER_COORD
    assert by_technician["created_by_user_id"] == c.USER_TECH_1

    rows, meta = validate_paginated(
        client.list_test_decks(sc.style_id, users.OBSERVER, {"status": c.DECK_DRAFT}))
    assert meta["total_count"] == 3
    assert {row["deck_code"] for row in rows} == {"DECK-A", "DECK-B", "DECK-C"}


def test_rbac_observer_sign_in_is_shared_by_the_technician_and_the_observer(client):
    """A member of the public may be signed in either by a technician or by an observer, and both count.

    PRD Section 3.8: "Either a `VotingSystemTechnician` or a `PublicObserver` may register a person, supplying an `observer_name`; the session must still be `SCHEDULED`, or `ERR_SESSION_STATE_INVALID`."

    PRD Section 3.8: "The name is appended to `observer_names` in registration order and `observer_count` is recomputed as that array's length."

    Design: Corner/rbac/rbac_test_deck_creation_shared_by_technician_and_coordinator
    """
    sc = fx.styles_locked(client)
    fx.add_tabulator(sc)
    fx.program_unit(sc)
    fx.add_test_deck(sc, ballot_count=1, blank_count=1, expected_marks=[])
    session_id = fx.schedule_session(sc)

    first = validate_success(
        client.add_observer(session_id, f.observer_payload("Zeta Watkins"),
                            users.OBSERVER))
    second = validate_success(
        client.add_observer(session_id, f.observer_payload("Ivo Marsh"),
                            users.TECHNICIAN_2))

    assert first["observer_count"] == 1
    assert second["observer_count"] == 2
    assert second["observer_names"] == ["Zeta Watkins", "Ivo Marsh"]


# ---- A vendor's representative is an entity-backed identity ----

def test_rbac_a_foreign_vendor_representative_cannot_record_the_delivery(client):
    """A second certified vendor's representative, and a user id that is no vendor at all, are both refused.

    PRD Section 3.6: "Delivery is recorded by the `PrintVendorRep` whose `X-User-ID` equals the job's `vendor_id` — any other vendor's representative is refused with `ERR_UNAUTHORIZED`."

    PRD Section 2.1: "When `X-User-Role` is `PrintVendorRep`, `X-User-ID` is the `id` of the acting `PrintVendor`; ownership checks compare the addressed print job's `vendor_id` to `X-User-ID`, and a representative of a different vendor recording a delivery is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/rbac_vendor_rep_of_another_vendor_cannot_deliver
    """
    sc, other_vendor = _qc_passed_job_and_second_vendor(client)
    manifest = f.deliver_payload([f.manifest_line(c.LOT_CODE_1, 12500, c.SEAL_1)])

    validate_error(
        client.deliver_print_job(sc.job_id, manifest, users.vendor_rep(other_vendor)),
        errs.ERR_UNAUTHORIZED)
    validate_error(
        client.deliver_print_job(sc.job_id, manifest, users.vendor_rep(_NOT_A_VENDOR)),
        errs.ERR_UNAUTHORIZED)

    rows, meta = validate_paginated(
        client.list_ballot_lots(users.CUSTODIAN, {"print_job_id": sc.job_id}))
    assert rows == []
    assert meta["total_count"] == 0
    job = sc.read_job()
    assert job["status"] == c.JOB_QC_PASSED
    assert job["invoice_basis"] == c.INVOICE_ESTIMATE


def test_rbac_the_owning_representative_delivers_and_then_the_state_gate_takes_over(client):
    """The owning vendor's representative delivers the identical manifest, and a repeat is a state error rather than a role error.

    PRD Section 3.6: "Delivery is recorded by the `PrintVendorRep` whose `X-User-ID` equals the job's `vendor_id` — any other vendor's representative is refused with `ERR_UNAUTHORIZED`."

    PRD Section 3.6: "The job must be `QC_PASSED`, or `ERR_JOB_STATE_INVALID`."

    Design: Corner/rbac/rbac_vendor_rep_of_another_vendor_cannot_deliver
    """
    sc, _ = _qc_passed_job_and_second_vendor(client)
    manifest = f.deliver_payload([f.manifest_line(c.LOT_CODE_1, 12500, c.SEAL_1)])

    delivered = validate_success(
        client.deliver_print_job(sc.job_id, manifest, sc.vendor_headers))
    assert delivered["status"] == c.JOB_DELIVERED
    assert delivered["invoice_basis"] == c.INVOICE_FINAL

    validate_error(
        client.deliver_print_job(
            sc.job_id,
            f.deliver_payload([f.manifest_line("L-009", 100, "SEAL-1009")]),
            sc.vendor_headers),
        errs.ERR_JOB_STATE_INVALID)

    rows, meta = validate_paginated(
        client.list_ballot_lots(users.CUSTODIAN, {"print_job_id": sc.job_id}))
    assert meta["total_count"] == 1
    assert rows[0]["lot_code"] == c.LOT_CODE_1
    assert rows[0]["quantity_shipped"] == 12500
    assert rows[0]["seal_number"] == c.SEAL_1


# ---- Results are entered by the technician who ran the test ----

def test_rbac_only_the_conducting_technician_may_record_the_results(client):
    """A second technician is refused on duties, the custodian is refused on role, and the conductor's identical payload passes.

    PRD Section 3.8: "The recording `X-User-ID` must **equal** the session's `conducted_by_user_id`, or `ERR_SEGREGATION_OF_DUTIES` — results are entered by the technician who actually ran the test, not by a third party."

    PRD Section 2.1: "If it names a recognized role that the target operation does not admit, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/rbac_results_recorded_only_by_the_conducting_technician
    """
    sc = _open_public_session(client)
    results = f.record_results_payload([], reported_blank_count=1,
                                      reported_overvote_count=0)

    validate_error(
        client.record_results(sc.session_id, results, users.TECHNICIAN),
        errs.ERR_SEGREGATION_OF_DUTIES)
    validate_error(
        client.record_results(sc.session_id, results, users.CUSTODIAN),
        errs.ERR_UNAUTHORIZED)

    recorded = validate_success(
        client.record_results(sc.session_id, results, users.TECHNICIAN_2))
    assert recorded["status"] == c.SESSION_PASSED
    assert recorded["discrepancy_count"] == 0

    unit = validate_success(client.get_tabulator(sc.tabulator_id, users.OBSERVER))
    assert unit["program_status"] == c.UNIT_LA_PASSED
    assert unit["la_session_count"] == 1


# ---- Proof sign-off needs a second pair of eyes ----

def test_rbac_the_proof_requester_cannot_decide_their_own_proof(client):
    """The wrong role is refused on role, the requester is refused on duties, and a second coordinator signs the proof off.

    PRD Section 3.4: "Deciding a proof is open to either an `ElectionsDirector` or a `BallotCoordinator`, requires the style to be `PROOFING` (otherwise `ERR_STYLE_STATE_INVALID`), and requires the election to be in `CONTESTS_CERTIFIED`."

    PRD Section 3.4: "The deciding user's `X-User-ID` must differ from the style's `proof_requested_by_user_id`, or the decision is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/rbac_proof_requester_cannot_decide_their_own_proof
    """
    sc = _style_in_proofing(client)

    validate_error(
        client.proof_decision(
            sc.style_id, f.proof_decision_payload(decision_note="Looks fine to me"),
            users.LANGUAGE_COORDINATOR),
        errs.ERR_UNAUTHORIZED)
    validate_error(
        client.proof_decision(
            sc.style_id,
            f.proof_decision_payload(decision_note="Approving my own request"),
            users.COORDINATOR),
        errs.ERR_SEGREGATION_OF_DUTIES)

    approved = validate_success(
        client.proof_decision(
            sc.style_id,
            f.proof_decision_payload(decision_note="Second-pair-of-eyes approval"),
            users.COORDINATOR_2))
    assert approved["status"] == c.STYLE_APPROVED
    assert approved["proof_decided_by_user_id"] == c.USER_COORD_2
    assert approved["revision"] == 1


def test_rbac_a_decided_proof_answers_on_state_rather_than_on_duties(client):
    """Once the style has left proofing, even the requester's own second attempt is a state refusal.

    PRD Section 3.4: "Deciding a proof is open to either an `ElectionsDirector` or a `BallotCoordinator`, requires the style to be `PROOFING` (otherwise `ERR_STYLE_STATE_INVALID`), and requires the election to be in `CONTESTS_CERTIFIED`."

    Design: Corner/rbac/rbac_proof_requester_cannot_decide_their_own_proof
    """
    sc = _style_in_proofing(client)
    validate_success(
        client.proof_decision(
            sc.style_id,
            f.proof_decision_payload(decision_note="Second-pair-of-eyes approval"),
            users.COORDINATOR_2))

    validate_error(
        client.proof_decision(
            sc.style_id,
            f.proof_decision_payload(decision="REJECT",
                                     decision_note="Changed my mind"),
            users.COORDINATOR),
        errs.ERR_STYLE_STATE_INVALID)

    style = sc.read_style()
    assert style["status"] == c.STYLE_APPROVED
    assert style["revision"] == 1
    assert style["proof_decided_by_user_id"] == c.USER_COORD_2
