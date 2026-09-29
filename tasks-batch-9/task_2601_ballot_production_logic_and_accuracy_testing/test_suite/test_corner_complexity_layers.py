"""Layered interactions between the election's version counter and its derived counts.

Two threads run through these tests. The first is optimistic concurrency on the
accountability close-out: reconciliation may be repeated, so the only thing that
can be wrong with a replayed request is the version of the election it observed,
and a refused request must leave the counter and the snapshot alone. The second
is the re-derivation of the counters that describe a ballot face: the number of
certified contests, the number of certified candidates in a contest, and the
printed rank of the names that survive a disqualification.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_client import BallotProductionApiClient
from test_helpers.api_errors import ERR_STALE_ELECTION_VERSION
from test_helpers.assertions import (
    assert_accountability_worksheet,
    find_by,
)
from test_helpers.constants import (
    ACCOUNTABILITY_OUT_OF_BALANCE,
    BASIS_CERTIFIED,
    BASIS_PRELIMINARY,
    CANDIDATE_CERTIFIED,
    CANDIDATE_DISQUALIFIED,
    CONTEST_CERTIFIED,
    LOT_CODE_1,
    LOT_CODE_2,
    LOT_CODE_3,
    PHASE_RECONCILED,
    POLL_CLOSE_INSTANT,
    SEAL_1,
    SEAL_2,
    SEAL_3,
    SESSION_PASSED,
    SESSION_START,
)

ALVAREZ_FILING = "2026-06-01T09:00:00Z"
BROOKS_FILING = "2026-06-02T09:00:00Z"

# The worksheet the three lots below produce on the in-field basis, computed by hand
# from the declared steps: three lots in scope (two RETURNED, one still ISSUED),
# gross 3000 + 2000 + 1, the 15 basis point allowance for a gross above 5000, and
# accounted 2950 + 1939 + 0.
PRELIMINARY_WORKSHEET = {
    "basis": BASIS_PRELIMINARY,
    "lot_count": 3,
    "gross_issued": 5001,
    "allowance_bp": 15,
    "spoilage_credit": 7,
    "net_issued": 4994,
    "accounted": 4889,
    "gross_variance": 112,
    "net_variance": 105,
    "tolerance_bp": 200,
    "tolerance_ballots": 99,
    "ballot_accountability_status": ACCOUNTABILITY_OUT_OF_BALANCE,
}


def _two_candidate_locked_election(client: BallotProductionApiClient):
    """A locked election with one certified two-candidate contest on one style."""
    sc = fx.new_election(client)
    fx.add_contest(sc)
    alvarez = fx.add_candidate(sc, full_name="Ana Alvarez", ballot_name="Alvarez",
                               filing_received_at=ALVAREZ_FILING)
    brooks = fx.add_candidate(sc, full_name="Ben Brooks", ballot_name="Brooks",
                              filing_received_at=BROOKS_FILING)
    fx.certify_contest(sc)
    fx.add_style(sc)
    fx.add_precinct(sc, registered_voter_count=100)
    validate_success(sc.client.certify_ballot_order(sc.election_id, users.DIRECTOR))
    fx.certify_languages(sc)
    fx.approve_proof_cycle(sc)
    fx.assign_style(sc)
    validate_success(sc.client.lock_styles(sc.election_id, users.DIRECTOR))
    return sc, alvarez, brooks


def _closed_election_with_three_lots(client: BallotProductionApiClient):
    """A poll-closed election whose first two lots reported counts and whose third is
    still out in the field, so the in-field basis is legal and repeatable."""
    sc = fx.delivered_lot(
        client,
        lots=[f.manifest_line(LOT_CODE_1, 4001, SEAL_1),
              f.manifest_line(LOT_CODE_2, 4001, SEAL_2),
              f.manifest_line(LOT_CODE_3, 4498, SEAL_3)])
    lots = sc.lots_of_job()
    lot_1 = find_by(lots, "lot_code", LOT_CODE_1)["id"]
    lot_2 = find_by(lots, "lot_code", LOT_CODE_2)["id"]
    lot_3 = find_by(lots, "lot_code", LOT_CODE_3)["id"]

    fx.receive_lot(sc, lot_id=lot_1, seal_number=SEAL_1, quantity_received=4001)
    fx.issue_lot(sc, lot_id=lot_1, issue_quantity=3000)
    fx.receive_lot(sc, lot_id=lot_2, seal_number=SEAL_2, quantity_received=4001)
    fx.issue_lot(sc, lot_id=lot_2, issue_quantity=2000)
    fx.receive_lot(sc, lot_id=lot_3, seal_number=SEAL_3, quantity_received=4498)
    fx.issue_lot(sc, lot_id=lot_3, issue_quantity=1)

    fx.add_tabulator(sc)
    fx.program_unit(sc)
    fx.add_test_deck(sc, ballot_count=1, blank_count=1, overvote_count=0,
                     expected_marks=[])
    fx.schedule_session(sc)
    fx.sign_in_observers(sc)
    fx.set_clock(client, SESSION_START)
    fx.start_session(sc)
    session = fx.record_matching_results(sc, reported_marks=[], blank_count=1,
                                         overvote_count=0)
    assert session["status"] == SESSION_PASSED

    fx.deploy_unit(sc)
    validate_success(sc.client.deploy_election(sc.election_id, users.DIRECTOR))

    fx.return_lot_counts(sc, lot_id=lot_1, voted_quantity=2900,
                         spoiled_quantity=30, returned_unused_quantity=20)
    fx.return_lot_counts(sc, lot_id=lot_2, voted_quantity=1880,
                         spoiled_quantity=25, returned_unused_quantity=34)

    fx.set_clock(client, POLL_CLOSE_INSTANT)
    validate_success(sc.client.close_polls(sc.election_id, users.DIRECTOR))
    return sc


# ---- Repeating the accountability close-out under the version guard ----

def test_cl_replayed_reconciliation_is_stale_and_the_retry_with_the_new_version_wins(client):
    """A successful reconciliation bumps the election's version by one, the byte-identical
    replay is refused with 412 without writing anything, and the same request carrying the
    version the first reconciliation wrote succeeds again.

    PRD Section 3.9: "A reconciliation writes the worksheet's results onto the election: `total_ballots_issued` becomes `gross_issued`, `net_ballot_variance` becomes `net_variance`, `ballot_accountability_status` becomes the derived status, `reconciliation_basis` records the basis used, `last_reconciled_at` is stamped from the logical clock, `status` becomes `RECONCILED`, and `version` is bumped — which is why a client re-reconciling must read the election again to obtain a fresh `expected_election_version`."

    Design: Corner/complexity_layers/cl_election_version_increments_on_every_write_and_stale_reconcile_returns_412
    """
    sc = _closed_election_with_three_lots(client)

    before = validate_success(sc.client.get_election(sc.election_id, users.DIRECTOR))
    version_before = before["version"]

    first = validate_success(
        sc.client.reconcile(sc.election_id,
                            f.reconcile_payload(BASIS_PRELIMINARY, version_before),
                            users.DIRECTOR))
    assert first["status"] == PHASE_RECONCILED
    assert first["version"] == version_before + 1
    assert first["reconciliation_basis"] == BASIS_PRELIMINARY
    assert first["total_ballots_issued"] == 5001
    assert first["net_ballot_variance"] == 105
    assert first["ballot_accountability_status"] == ACCOUNTABILITY_OUT_OF_BALANCE
    assert_accountability_worksheet(
        validate_success(sc.client.get_accountability(
            sc.election_id, users.DIRECTOR,
            f.accountability_params(BASIS_PRELIMINARY))),
        PRELIMINARY_WORKSHEET)

    validate_error(
        sc.client.reconcile(sc.election_id,
                            f.reconcile_payload(BASIS_PRELIMINARY, version_before),
                            users.DIRECTOR),
        ERR_STALE_ELECTION_VERSION)

    after_rejection = validate_success(
        sc.client.get_election(sc.election_id, users.DIRECTOR))
    assert after_rejection["version"] == version_before + 1

    second = validate_success(
        sc.client.reconcile(sc.election_id,
                            f.reconcile_payload(BASIS_PRELIMINARY, version_before + 1),
                            users.DIRECTOR))
    assert second["status"] == PHASE_RECONCILED
    assert second["version"] == version_before + 2
    assert second["total_ballots_issued"] == 5001
    assert second["net_ballot_variance"] == 105

    final = validate_success(sc.client.get_election(sc.election_id, users.DIRECTOR))
    assert final["version"] == version_before + 2
    assert_accountability_worksheet(
        validate_success(sc.client.get_accountability(
            sc.election_id, users.DIRECTOR,
            f.accountability_params(BASIS_PRELIMINARY))),
        PRELIMINARY_WORKSHEET)


# ---- Counters and printed ranks re-derived from the surviving rows ----

def test_cl_certification_derives_both_counters_from_the_rows_it_certified(client):
    """Certifying a two-candidate contest counts the rows it promoted, not the payload:
    the contest reports 2 certified candidates ranked 0 and 1, the election reports 1.

    PRD Section 3.1: "Every candidate of the contest still in `FILED` is promoted `FILED → CERTIFIED`, while candidates already `DISQUALIFIED` are left exactly as they are; `certified_candidate_count` is set to the number of candidates just certified and `certified_at` is stamped with the logical clock"

    Design: Corner/complexity_layers/cl_derived_counts_reconcile_after_certification_and_after_disqualification
    """
    sc, alvarez, brooks = _two_candidate_locked_election(client)

    contest = validate_success(sc.client.get_contest(sc.contest_id, users.DIRECTOR))
    assert contest["certified_candidate_count"] == 2
    assert contest["status"] == CONTEST_CERTIFIED

    election = validate_success(sc.client.get_election(sc.election_id, users.DIRECTOR))
    assert election["certified_contest_count"] == 1

    rows, meta = validate_paginated(
        sc.client.list_candidates(sc.contest_id, users.DIRECTOR))
    assert meta["total_count"] == 2
    assert find_by(rows, "id", alvarez)["base_order_index"] == 0
    assert find_by(rows, "id", brooks)["base_order_index"] == 1
    assert find_by(rows, "id", alvarez)["status"] == CANDIDATE_CERTIFIED
    assert find_by(rows, "id", brooks)["status"] == CANDIDATE_CERTIFIED


def test_cl_disqualifications_recompact_ranks_and_empty_the_counter(client):
    """Disqualifying the first-ranked candidate clears its own rank and recompacts the
    survivor to rank 0, and disqualifying the survivor too leaves a certified contest
    with 0 certified candidates and a ballot face printing no names.

    PRD Section 3.2: "In the second hop, because the contest's certified roster has shrunk, every surviving `CERTIFIED` sibling has its `base_order_index` recompacted on the certified basis, so the rotation modulus falls by one and the printed order of the whole contest can shift; this recompaction runs only once the ordering has been frozen, that is when the election is no longer in `SETUP`."

    Design: Corner/complexity_layers/cl_derived_counts_reconcile_after_certification_and_after_disqualification
    """
    sc, alvarez, brooks = _two_candidate_locked_election(client)

    disqualified = validate_success(
        sc.client.disqualify_candidate(
            alvarez, f.disqualify_payload("Residency requirement not met"),
            users.DIRECTOR))
    assert disqualified["status"] == CANDIDATE_DISQUALIFIED
    assert disqualified["base_order_index"] is None

    contest = validate_success(sc.client.get_contest(sc.contest_id, users.DIRECTOR))
    assert contest["certified_candidate_count"] == 1
    assert contest["status"] == CONTEST_CERTIFIED

    survivors, survivor_meta = validate_paginated(
        sc.client.list_candidates(sc.contest_id, users.DIRECTOR,
                                  {"status": CANDIDATE_CERTIFIED}))
    assert survivor_meta["total_count"] == 1
    assert survivors[0]["id"] == brooks
    assert survivors[0]["ballot_name"] == "Brooks"
    assert survivors[0]["base_order_index"] == 0

    second = validate_success(
        sc.client.disqualify_candidate(
            brooks, f.disqualify_payload("Filing withdrawn"), users.DIRECTOR))
    assert second["status"] == CANDIDATE_DISQUALIFIED
    assert second["base_order_index"] is None

    emptied = validate_success(sc.client.get_contest(sc.contest_id, users.DIRECTOR))
    assert emptied["certified_candidate_count"] == 0
    assert emptied["status"] == CONTEST_CERTIFIED

    election = validate_success(sc.client.get_election(sc.election_id, users.DIRECTOR))
    assert election["certified_contest_count"] == 1

    layout = validate_success(
        sc.client.get_layout(sc.style_id, users.COORDINATOR,
                             f.layout_params(BASIS_CERTIFIED)))
    assert layout["contest_count"] == 1
    assert layout["candidate_count"] == 0
