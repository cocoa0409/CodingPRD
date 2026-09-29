"""State machines of the ballot production service.

These tests pin down, for every row the service creates, the state it is born
in; for every legal edge, the side effects the edge is required to write —
custody ledger lines, recomputed election ledgers, demoted readiness; and for
every illegal edge, the exact typed state-guard error the service must answer
with, together with the requirement that a refused call leaves the world byte
for byte as it found it.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers import test_users as users
from test_helpers.api_errors import (
    ERR_CONTEST_STATE_INVALID,
    ERR_ELECTION_PHASE_INVALID,
    ERR_LOT_STATE_INVALID,
    ERR_UNIT_STATE_INVALID,
)
from test_helpers.assertions import (
    assert_custody_event,
    assert_fields_equal,
    assert_iso_timestamp,
    assert_lot_conservation,
    assert_sequence_indices_ascending,
    assert_system_actor,
    event_types,
    find_by,
)
from test_helpers.constants import (
    ACCOUNTABILITY_OUT_OF_BALANCE,
    ACCOUNTABILITY_PENDING,
    BASIS_PRELIMINARY,
    CANDIDATE_CERTIFIED,
    CANDIDATE_DISQUALIFIED,
    CANDIDATE_FILED,
    CONTEST_CERTIFIED,
    CONTEST_DRAFT,
    CONTEST_WITHDRAWN,
    CUSTODY_DEPLOYED,
    CUSTODY_IN_VAULT,
    CUSTODY_RETURNED,
    DECK_CONSUMED,
    DECK_DRAFT,
    DECK_VOIDED,
    DISTRICT_D12,
    EVENT_RECEIPT,
    EVENT_RETURN,
    EVENT_SEAL_APPLIED,
    EVENT_TRANSFER_OUT,
    FORMAT_PAPER_STANDARD,
    JOB_PROOF_PENDING,
    LANGUAGE_EN,
    LOT_CODE_1,
    LOT_CODE_2,
    LOT_CODE_3,
    LOT_IN_TRANSIT,
    LOT_ISSUED,
    LOT_RECEIVED,
    PHASE_POLLS_CLOSED,
    PHASE_RECONCILED,
    PHASE_SETUP,
    PHASE_STYLES_LOCKED,
    READINESS_BLOCKED,
    READINESS_NOT_READY,
    READINESS_READY,
    SEAL_1,
    SEAL_2,
    SEAL_3,
    SEAL_TAB_1,
    SESSION_PASSED,
    SESSION_SCHEDULED,
    SESSION_START,
    STYLE_APPROVED,
    STYLE_CODE_ALT,
    STYLE_DRAFT,
    STYLE_LOCKED,
    SUBJECT_BALLOT_LOT,
    SUBJECT_TABULATOR_UNIT,
    UNIT_LA_PASSED,
    UNIT_PROGRAMMED,
    UNIT_UNPROGRAMMED,
    USER_TECH_1,
)

THREE_PALLET_MANIFEST = [
    (LOT_CODE_1, 4001, SEAL_1),
    (LOT_CODE_2, 4001, SEAL_2),
    (LOT_CODE_3, 4498, SEAL_3),
]


def _three_pallet_delivery(client):
    """A locked election whose only print job shipped three sealed pallets."""
    return fixtures.delivered_lot(
        client,
        lots=[f.manifest_line(code, quantity, seal)
              for code, quantity, seal in THREE_PALLET_MANIFEST],
    )


def _issue_three_pallets(sc):
    """Receive all three pallets and issue 3000 / 2000 / 1 ballots to the precinct."""
    for (code, quantity, seal), lot_id, issued in zip(
            THREE_PALLET_MANIFEST, sc.lot_ids, (3000, 2000, 1)):
        fixtures.receive_lot(sc, lot_id, seal_number=seal, quantity_received=quantity)
        fixtures.issue_lot(sc, lot_id, issue_quantity=issued)


def _pass_public_test(sc):
    """Programme the vault unit and take it through a passing public test."""
    fixtures.add_tabulator(sc)
    fixtures.program_unit(sc)
    fixtures.add_test_deck(sc)
    fixtures.schedule_session(sc)
    fixtures.sign_in_observers(sc)
    fixtures.set_clock(sc.client, SESSION_START)
    fixtures.start_session(sc)
    return fixtures.record_matching_results(sc)


def _three_pallet_polls_closed(client):
    """A fully run election whose polls have closed, ready to be reconciled.

    Two of its three pallets have reported their board counts; the third is
    still in the field, which is what keeps the in-field basis interesting.
    """
    sc = _three_pallet_delivery(client)
    _issue_three_pallets(sc)
    _pass_public_test(sc)
    fixtures.deploy_unit(sc)
    fixtures.set_clock(client, SESSION_START)
    validate_success(sc.client.deploy_election(sc.election_id, users.DIRECTOR))
    fixtures.return_lot_counts(sc, sc.lot_ids[0], voted_quantity=2900,
                               spoiled_quantity=30, returned_unused_quantity=20)
    fixtures.return_lot_counts(sc, sc.lot_ids[1], voted_quantity=1880,
                               spoiled_quantity=25, returned_unused_quantity=34)
    validate_success(sc.client.close_polls(sc.election_id, users.DIRECTOR))
    return sc


# ---- Rows created during slate and equipment setup ----

def test_sm_slate_rows_land_in_their_declared_initial_states(client, clock_at_start):
    """A newly registered election, a newly filed contest and a newly filed candidate
    each land on their declared initial state with every derived figure at rest.

    PRD Section 3.1: "A new election lands in `SETUP` with every derived figure at rest: `certified_contest_count` 0, `committed_print_cents` 0, `deployment_readiness` `BLOCKED`, `open_seal_count` 0, `total_ballots_received` 0, `total_ballots_issued` 0, `ballot_accountability_status` `PENDING`, `net_ballot_variance` 0, and both `reconciliation_basis` and `last_reconciled_at` null."

    PRD Section 3.1: "A newly filed contest is `DRAFT`, with `ballot_order_index` null, `certified_candidate_count` 0, and `certified_at` and `withdrawn_reason` both null."

    PRD Section 3.1: "A filed candidate starts in `FILED`, with `base_order_index` and `disqualified_reason` null."

    Design: Corner/state_machines/sm_new_rows_start_in_declared_initial_states
    """
    election = validate_success(
        client.create_election(f.election_payload(), users.DIRECTOR), 201)
    assert election["status"] == PHASE_SETUP
    assert_fields_equal(election, {
        "certified_contest_count": 0,
        "committed_print_cents": 0,
        "deployment_readiness": READINESS_BLOCKED,
        "open_seal_count": 0,
        "total_ballots_received": 0,
        "total_ballots_issued": 0,
        "ballot_accountability_status": ACCOUNTABILITY_PENDING,
        "net_ballot_variance": 0,
        "reconciliation_basis": None,
        "last_reconciled_at": None,
    }, "new election")

    contest = validate_success(
        client.create_contest(election["id"], f.contest_payload(), users.COORDINATOR), 201)
    assert contest["status"] == CONTEST_DRAFT
    assert_fields_equal(contest, {
        "ballot_order_index": None,
        "certified_candidate_count": 0,
        "certified_at": None,
        "withdrawn_reason": None,
    }, "new contest")

    candidate = validate_success(
        client.create_candidate(contest["id"], f.candidate_payload(), users.COORDINATOR), 201)
    assert candidate["status"] == CANDIDATE_FILED
    assert_fields_equal(candidate, {
        "base_order_index": None,
        "disqualified_reason": None,
    }, "new candidate")


def test_sm_geography_and_equipment_rows_land_in_their_declared_initial_states(client,
                                                                              clock_at_start):
    """A new ballot style, a new precinct and a newly intaken tabulator each land on
    their declared initial state, the unit on both of its independent axes at once.

    PRD Section 3.4: "A new style is born in `DRAFT` with `revision` 1, `proof_cycle_count` 0, empty `translated_languages` and `certified_formats` arrays, `precinct_count` 0, both `proof_requested_by_user_id` and `proof_decided_by_user_id` null, and `contest_count` derived from the count of the election's `CERTIFIED` contests whose `district_code` falls inside the new style's district set."

    PRD Section 3.3: "A newly registered precinct has `assigned_style_id` null, `ballots_received` 0 and `deployment_status` `NOT_READY`, and its arrival forces a recomputation of the election's `deployment_readiness`, which a fresh `NOT_READY` precinct can only block."

    PRD Section 3.8: "The unit is created `UNPROGRAMMED` and `IN_VAULT`, with `precinct_id`, `programmed_style_id`, `seal_number` and `retention_until` null and `la_session_count` 0."

    Design: Corner/state_machines/sm_new_rows_start_in_declared_initial_states
    """
    sc = fixtures.new_election(client)

    style = validate_success(
        client.create_ballot_style(sc.election_id, f.ballot_style_payload(),
                                  users.COORDINATOR), 201)
    assert style["status"] == STYLE_DRAFT
    assert_fields_equal(style, {
        "revision": 1,
        "proof_cycle_count": 0,
        "translated_languages": [],
        "certified_formats": [],
        "precinct_count": 0,
        "proof_requested_by_user_id": None,
        "proof_decided_by_user_id": None,
        "contest_count": 0,
    }, "new ballot style")

    precinct = validate_success(
        client.create_precinct(sc.election_id, f.precinct_payload(), users.COORDINATOR), 201)
    assert_fields_equal(precinct, {
        "assigned_style_id": None,
        "ballots_received": 0,
        "deployment_status": READINESS_NOT_READY,
    }, "new precinct")
    assert sc.read_election()["deployment_readiness"] == READINESS_BLOCKED

    unit = validate_success(
        client.create_tabulator(sc.election_id, f.tabulator_payload(), users.TECHNICIAN), 201)
    assert_fields_equal(unit, {
        "program_status": UNIT_UNPROGRAMMED,
        "custody_status": CUSTODY_IN_VAULT,
        "precinct_id": None,
        "programmed_style_id": None,
        "seal_number": None,
        "retention_until": None,
        "la_session_count": 0,
    }, "new tabulator")


# ---- Rows created along the print and testing pipeline ----

def test_sm_print_job_and_shipped_lot_start_with_every_figure_at_rest(client):
    """A created print job starts in its proofing state with a null invoice basis, and the
    lots its delivery manifest creates start in transit with every accounting figure zero.

    PRD Section 3.6: "A created job starts in `PROOF_PENDING`, copies `election_id` from the referenced style, pins `style_version_at_creation` to the style's `version` as observed and accepted, and begins with `sample_size` 0, `defect_count` 0, `defect_rate_bp` 0, `inspection_count` 0, `delivered_quantity` 0, `approved_by_user_id` null, `invoice_basis` null and all four invoice money fields at 0."

    PRD Section 3.6: "An accepted manifest moves the job `QC_PASSED → DELIVERED` and creates one ballot lot per line, each in `IN_TRANSIT` with `lot_code`, `quantity_shipped` and `seal_number` copied from the line, `election_id` copied from the job, and every accounting figure at rest: `quantity_received` 0, `issued_quantity` 0, `unused_quantity` 0, `voted_quantity` 0, `spoiled_quantity` 0, `returned_unused_quantity` 0, `accounted_quantity` 0, `lot_variance` 0, and `precinct_id` and `issued_by_user_id` null."

    Design: Corner/state_machines/sm_print_pipeline_rows_start_in_declared_initial_states
    """
    sc = fixtures.styles_locked(client)
    fixtures.add_vendor(sc)
    accepted_style_version = sc.style_version()

    job = validate_success(
        client.create_print_job(
            f.print_job_payload(sc.vendor_id, sc.style_id, accepted_style_version,
                                quantity_ordered=12500),
            users.COORDINATOR), 201)
    assert job["status"] == JOB_PROOF_PENDING
    assert_fields_equal(job, {
        "election_id": sc.election_id,
        "style_version_at_creation": accepted_style_version,
        "sample_size": 0,
        "defect_count": 0,
        "defect_rate_bp": 0,
        "inspection_count": 0,
        "delivered_quantity": 0,
        "approved_by_user_id": None,
        "invoice_basis": None,
        "invoice_subtotal_cents": 0,
        "defect_credit_cents": 0,
        "freight_cents": 0,
        "invoice_total_cents": 0,
    }, "new print job")

    sc.job_ids.append(job["id"])
    fixtures.printed_job(sc)
    fixtures.inspect_job(sc)
    fixtures.deliver_job(sc)

    lot = sc.read_lot()
    assert lot["custody_state"] == LOT_IN_TRANSIT
    assert_fields_equal(lot, {
        "election_id": sc.election_id,
        "lot_code": LOT_CODE_1,
        "quantity_shipped": 12500,
        "seal_number": SEAL_1,
        "quantity_received": 0,
        "issued_quantity": 0,
        "unused_quantity": 0,
        "voted_quantity": 0,
        "spoiled_quantity": 0,
        "returned_unused_quantity": 0,
        "accounted_quantity": 0,
        "precinct_id": None,
        "issued_by_user_id": None,
    }, "shipped ballot lot")


def test_sm_test_deck_and_session_start_in_declared_initial_states(client):
    """A newly built test deck starts as a draft owned by its builder, and a newly
    scheduled public test starts with no observers, no reported tallies and the
    notice lead it derived once at creation.

    PRD Section 3.8: "An accepted deck is created in `DRAFT` with the derived `expected_total_marks` and `created_by_user_id` set to the builder's `X-User-ID`."

    PRD Section 3.8: "An accepted session is created `SCHEDULED` with `observer_count` 0, an empty `observer_names` array, an empty `reported_marks` array, and `reported_blank_count`, `reported_overvote_count`, `discrepancy_count`, `conducted_by_user_id`, `started_at` and `completed_at` all null."

    PRD Section 3.8: "`notice_lead_minutes` is derived once, at creation, as the whole minutes from `public_notice_posted_at` to `scheduled_start`, rounded down; a notice posted *after* the scheduled start yields a negative lead, which is retained as computed rather than clamped."

    Design: Corner/state_machines/sm_print_pipeline_rows_start_in_declared_initial_states
    """
    sc = fixtures.styles_locked(client)
    unit = fixtures.add_tabulator(sc)
    fixtures.program_unit(sc)

    deck = validate_success(
        client.create_test_deck(
            sc.style_id,
            f.test_deck_payload([], deck_code="DECK-A", ballot_count=1, blank_count=1,
                                overvote_count=0),
            users.TECHNICIAN), 201)
    assert deck["status"] == DECK_DRAFT
    assert_fields_equal(deck, {
        "expected_total_marks": 0,
        "created_by_user_id": USER_TECH_1,
    }, "new test deck")

    session = validate_success(
        client.create_la_session(
            f.la_session_payload(unit, deck["id"],
                                 public_notice_posted_at="2026-08-01T00:00:00Z",
                                 scheduled_start=SESSION_START),
            users.TECHNICIAN_2), 201)
    assert session["status"] == SESSION_SCHEDULED
    assert_fields_equal(session, {
        "observer_count": 0,
        "observer_names": [],
        "reported_marks": [],
        "reported_blank_count": None,
        "reported_overvote_count": None,
        "discrepancy_count": None,
        "conducted_by_user_id": None,
        "started_at": None,
        "completed_at": None,
        "notice_lead_minutes": 45480,
    }, "new public test session")


# ---- Receiving a pallet: the legal transition and its ledger line ----

def test_sm_lot_receipt_moves_the_lot_and_recomputes_the_election_receipt_total(client):
    """Counting a pallet in moves the lot out of transit, seeds its unused quantity from
    the counted figure, and forces the election's received total to be recomputed.

    PRD Section 3.7: "On success the lot moves `IN_TRANSIT → RECEIVED`, stores the counted `quantity_received`, sets `unused_quantity` equal to it (nothing has been issued yet), appends a custody event of type `RECEIPT` recording `from_state` `IN_TRANSIT`, `to_state` `RECEIVED` and the lot's seal, and forces the election's `total_ballots_received` to be recomputed as the sum of `quantity_received` over the election's lots in `RECEIVED`, `ISSUED` or `RETURNED`."

    Design: Corner/state_machines/sm_lot_receive_valid_transition_appends_receipt_custody_event
    """
    sc = fixtures.delivered_lot(client)
    assert sc.read_election()["total_ballots_received"] == 0

    lot = validate_success(
        client.receive_lot(sc.lot_id, f.receive_payload(SEAL_1, 12500), users.CUSTODIAN))
    assert lot["custody_state"] == LOT_RECEIVED
    assert_fields_equal(lot, {
        "quantity_received": 12500,
        "unused_quantity": 12500,
        "issued_quantity": 0,
        "seal_number": SEAL_1,
        "precinct_id": None,
        "issued_by_user_id": None,
    }, "received ballot lot")
    assert_lot_conservation(lot)

    assert sc.read_election()["total_ballots_received"] == 12500


def test_sm_lot_receipt_appends_a_receipt_line_after_the_shipping_line(client):
    """The receipt appends a second ledger line for the pallet, typed RECEIPT and
    recording the transition out of transit together with the seal on the pallet.

    PRD Section 3.7: "On success the lot moves `IN_TRANSIT → RECEIVED`, stores the counted `quantity_received`, sets `unused_quantity` equal to it (nothing has been issued yet), appends a custody event of type `RECEIPT` recording `from_state` `IN_TRANSIT`, `to_state` `RECEIVED` and the lot's seal, and forces the election's `total_ballots_received` to be recomputed as the sum of `quantity_received` over the election's lots in `RECEIVED`, `ISSUED` or `RETURNED`."

    PRD Section 3.6: "A custody event of type `TRANSFER_OUT` with `to_state` `IN_TRANSIT` is appended for each created lot."

    Design: Corner/state_machines/sm_lot_receive_valid_transition_appends_receipt_custody_event
    """
    sc = fixtures.delivered_lot(client)
    fixtures.receive_lot(sc, quantity_received=12500)

    rows, _ = validate_paginated(
        client.list_custody_events(sc.election_id, users.DIRECTOR,
                                   {"subject_id": sc.lot_id, "limit": 100}))
    assert event_types(rows) == [EVENT_TRANSFER_OUT, EVENT_RECEIPT]
    assert_sequence_indices_ascending(rows)
    assert [row["sequence_index"] for row in rows] == [1, 2]
    assert_custody_event(rows[1], EVENT_RECEIPT,
                         subject_type=SUBJECT_BALLOT_LOT,
                         subject_id=sc.lot_id,
                         from_state=LOT_IN_TRANSIT,
                         to_state=LOT_RECEIVED,
                         seal_number=SEAL_1)


# ---- An untested machine may not leave the vault ----

def test_sm_deploying_a_merely_programmed_unit_is_refused(client):
    """A unit that has been programmed but has not passed its public test cannot be
    deployed: the request is refused with the unit-state guard and nothing is written.

    PRD Section 3.9: "Its guards, in ascending rank, are: the unit must resolve, or `ERR_TABULATOR_NOT_FOUND`; the precinct must exist in the same election, or `ERR_PRECINCT_NOT_FOUND`; the unit's `program_status` must be `LA_PASSED` **and** its `custody_status` must be `IN_VAULT`, or `ERR_UNIT_STATE_INVALID` — an untested machine never leaves the vault; at least one ballot lot with that `precinct_id` must be in `ISSUED`, or `ERR_LOT_STATE_INVALID` — the machine does not travel ahead of the paper; the unit's `programmed_style_id` must equal the precinct's `assigned_style_id`, or `ERR_UNIT_STYLE_MISMATCH` — a machine programmed for one district combination cannot read another's ballots; and the `seal_number` must not already be held by any other ballot lot or tabulator of the election, or `ERR_SEAL_NUMBER_DUPLICATE`."

    Design: Corner/state_machines/sm_deploy_unit_without_la_pass_returns_unit_state_invalid
    """
    sc = fixtures.issued_lot(client)
    unit_id = fixtures.add_tabulator(sc)
    fixtures.program_unit(sc)

    validate_error(
        client.deploy_tabulator(unit_id, f.deploy_unit_payload(sc.precinct_id, SEAL_TAB_1),
                                users.CUSTODIAN),
        ERR_UNIT_STATE_INVALID)

    unit = sc.read_tabulator()
    assert_fields_equal(unit, {
        "program_status": UNIT_PROGRAMMED,
        "custody_status": CUSTODY_IN_VAULT,
        "precinct_id": None,
        "seal_number": None,
    }, "refused tabulator")
    assert sc.read_election()["open_seal_count"] == 0

    rows, _ = validate_paginated(
        client.list_custody_events(sc.election_id, users.DIRECTOR,
                                   {"subject_id": unit_id, "event_type": EVENT_SEAL_APPLIED,
                                    "limit": 100}))
    assert rows == []


def test_sm_the_same_deployment_succeeds_once_the_unit_has_passed_its_test(client):
    """Once the unit has passed its public test the identical deployment request
    succeeds, seals the machine to its precinct and lifts the readiness chain.

    PRD Section 3.8: "The session moves `IN_PROGRESS → PASSED`, the deck moves `SEALED → CONSUMED`, the unit's `program_status` moves to `LA_PASSED`, `la_session_count` is recomputed as the number of sessions on that unit, and the readiness chain runs: the unit's precinct, if it has one, recomputes `deployment_status`, and the election recomputes `deployment_readiness`."

    PRD Section 3.9: "On success the unit moves `IN_VAULT → DEPLOYED`, stores `precinct_id` and `seal_number`, appends a custody event of type `SEAL_APPLIED` with `from_state` `IN_VAULT` and `to_state` `DEPLOYED`, increments the election's `open_seal_count` by one, and re-derives the precinct's `deployment_status` and the election's `deployment_readiness`."

    PRD Section 3.9: "A precinct's `deployment_status` is `READY` when **both** of two conditions hold: its `ballots_received` is greater than or equal to its `required_ballot_quantity`, and at least one tabulator exists whose `precinct_id` is that precinct with `program_status` `LA_PASSED` **and** `custody_status` `DEPLOYED`."

    Design: Corner/state_machines/sm_deploy_unit_without_la_pass_returns_unit_state_invalid
    """
    sc = fixtures.la_passed_unit(client)

    session = sc.read_session()
    assert session["status"] == SESSION_PASSED
    assert session["discrepancy_count"] == 0
    unit = sc.read_tabulator()
    assert unit["program_status"] == UNIT_LA_PASSED
    assert unit["custody_status"] == CUSTODY_IN_VAULT
    decks, _ = validate_paginated(
        client.list_test_decks(sc.style_id, users.TECHNICIAN, {"limit": 100}))
    assert find_by(decks, "id", sc.deck_id)["status"] == DECK_CONSUMED

    deployed = validate_success(
        client.deploy_tabulator(sc.tabulator_id,
                                f.deploy_unit_payload(sc.precinct_id, SEAL_TAB_1),
                                users.CUSTODIAN))
    assert_fields_equal(deployed, {
        "program_status": UNIT_LA_PASSED,
        "custody_status": CUSTODY_DEPLOYED,
        "precinct_id": sc.precinct_id,
        "seal_number": SEAL_TAB_1,
    }, "deployed tabulator")

    rows, _ = validate_paginated(
        client.list_custody_events(sc.election_id, users.DIRECTOR,
                                   {"subject_id": sc.tabulator_id,
                                    "event_type": EVENT_SEAL_APPLIED, "limit": 100}))
    assert len(rows) == 1
    assert_custody_event(rows[0], EVENT_SEAL_APPLIED,
                         subject_type=SUBJECT_TABULATOR_UNIT,
                         subject_id=sc.tabulator_id,
                         from_state=CUSTODY_IN_VAULT,
                         to_state=CUSTODY_DEPLOYED,
                         seal_number=SEAL_TAB_1)

    assert sc.read_election()["open_seal_count"] == 1
    assert sc.read_precinct()["deployment_status"] == READINESS_READY
    assert sc.read_election()["deployment_readiness"] == READINESS_READY


# ---- A receipt is not replayable ----

def test_sm_receiving_the_same_lot_twice_is_refused_and_double_counts_nothing(client):
    """A pallet already counted in is no longer in transit, so a replayed receipt is
    refused with the lot-state guard and the counted quantity is not doubled.

    PRD Section 3.7: "The lot must be `IN_TRANSIT`, or `ERR_LOT_STATE_INVALID`; the payload's `seal_number` must equal the `seal_number` the vendor declared for that lot in the manifest, or the receipt is refused with `ERR_SEAL_MISMATCH` — the seal on the pallet is not the seal that was shipped; and `quantity_received` must be at least 1."

    Design: Corner/state_machines/sm_receive_lot_twice_second_call_rejected
    """
    sc = fixtures.delivered_lot(client)
    fixtures.receive_lot(sc, quantity_received=12500)

    validate_error(
        client.receive_lot(sc.lot_id, f.receive_payload(SEAL_1, 12500), users.CUSTODIAN),
        ERR_LOT_STATE_INVALID)

    lot = sc.read_lot()
    assert lot["custody_state"] == LOT_RECEIVED
    assert_fields_equal(lot, {
        "quantity_received": 12500,
        "unused_quantity": 12500,
        "issued_quantity": 0,
    }, "singly received ballot lot")
    assert sc.read_election()["total_ballots_received"] == 12500

    rows, _ = validate_paginated(
        client.list_custody_events(sc.election_id, users.DIRECTOR,
                                   {"subject_id": sc.lot_id, "event_type": EVENT_RECEIPT,
                                    "limit": 100}))
    assert len(rows) == 1


# ---- Only a certified contest can be withdrawn, and only once ----

def test_sm_withdrawing_a_draft_contest_is_refused(client):
    """A contest that has never been certified cannot be withdrawn: the request is
    refused with the contest-state guard and the contest keeps its draft state.

    PRD Section 3.5: "The contest must be `CERTIFIED`; withdrawing a `DRAFT` or already-`WITHDRAWN` contest is `ERR_CONTEST_STATE_INVALID`."

    Design: Corner/state_machines/sm_withdraw_draft_contest_returns_409_contest_state_invalid
    """
    sc = fixtures.new_election(client)
    contest_id = fixtures.add_contest(sc)
    fixtures.add_candidate(sc)

    validate_error(
        client.withdraw_contest(contest_id, f.withdraw_payload("Filed in the wrong district"),
                                users.DIRECTOR),
        ERR_CONTEST_STATE_INVALID)

    contest = sc.read_contest()
    assert contest["status"] == CONTEST_DRAFT
    assert_fields_equal(contest, {
        "ballot_order_index": None,
        "withdrawn_reason": None,
    }, "refused contest")
    assert sc.read_election()["certified_contest_count"] == 0


def test_sm_a_withdrawn_contest_cannot_be_withdrawn_again(client):
    """Certification opens the withdrawal path, the withdrawal closes it again: the
    second withdrawal is refused and the stored reason is not overwritten.

    PRD Section 3.1: "Certification of a contest is an `ElectionsDirector` action that moves it `DRAFT → CERTIFIED`, and it enforces four guards in this order."

    PRD Section 3.5: "**Hop 1 — the contest.** The contest moves `CERTIFIED → WITHDRAWN`, its `ballot_order_index` is cleared to null, the supplied `withdrawn_reason` is stored, and the election's `certified_contest_count` is recomputed."

    PRD Section 3.5: "The contest must be `CERTIFIED`; withdrawing a `DRAFT` or already-`WITHDRAWN` contest is `ERR_CONTEST_STATE_INVALID`."

    Design: Corner/state_machines/sm_withdraw_draft_contest_returns_409_contest_state_invalid
    """
    sc = fixtures.new_election(client)
    contest_id = fixtures.add_contest(sc)
    candidate_id = fixtures.add_candidate(sc)

    certified = validate_success(client.certify_contest(contest_id, users.DIRECTOR))
    assert certified["status"] == CONTEST_CERTIFIED
    assert certified["certified_candidate_count"] == 1
    assert_iso_timestamp(certified["certified_at"], "contest.certified_at")
    assert find_by(sc.candidates_of(), "id", candidate_id)["status"] == CANDIDATE_CERTIFIED
    assert sc.read_election()["certified_contest_count"] == 1

    withdrawn = validate_success(
        client.withdraw_contest(contest_id, f.withdraw_payload("Court order 2026-08-01"),
                                users.DIRECTOR))
    assert withdrawn["status"] == CONTEST_WITHDRAWN
    assert_fields_equal(withdrawn, {
        "ballot_order_index": None,
        "withdrawn_reason": "Court order 2026-08-01",
    }, "withdrawn contest")
    assert sc.read_election()["certified_contest_count"] == 0

    validate_error(
        client.withdraw_contest(contest_id, f.withdraw_payload("Second attempt"),
                                users.DIRECTOR),
        ERR_CONTEST_STATE_INVALID)

    contest = sc.read_contest()
    assert contest["status"] == CONTEST_WITHDRAWN
    assert contest["withdrawn_reason"] == "Court order 2026-08-01"


# ---- The reconciled phase refuses every write except another reconciliation ----

def test_sm_a_reconciled_election_refuses_the_earlier_phase_writes(client):
    """Once an election has been reconciled, closing the polls, declaring deployment,
    locking styles, freezing the ballot order and filing a contest are all refused on
    the phase gate, and the election is left untouched.

    PRD Section 2.5: "Nearly every write is legal only in specific phases; attempting one outside its permitted set is rejected with `ERR_ELECTION_PHASE_INVALID`."

    PRD Section 3.9: "Closing the polls is an `ElectionsDirector` action legal only from `DEPLOYED`."

    PRD Section 3.1: "Freezing the ballot order is the `ElectionsDirector` action that advances the election `SETUP → CONTESTS_CERTIFIED`."

    Design: Corner/state_machines/sm_reconciled_election_rejects_close_polls_and_deploy
    """
    sc = _three_pallet_polls_closed(client)
    fixtures.reconcile(sc, BASIS_PRELIMINARY)
    version_after_reconciliation = sc.election_version()

    validate_error(client.close_polls(sc.election_id, users.DIRECTOR),
                   ERR_ELECTION_PHASE_INVALID)
    validate_error(client.deploy_election(sc.election_id, users.DIRECTOR),
                   ERR_ELECTION_PHASE_INVALID)
    validate_error(client.lock_styles(sc.election_id, users.DIRECTOR),
                   ERR_ELECTION_PHASE_INVALID)
    validate_error(client.certify_ballot_order(sc.election_id, users.DIRECTOR),
                   ERR_ELECTION_PHASE_INVALID)
    validate_error(
        client.create_contest(sc.election_id, f.contest_payload("Late Filing"),
                              users.COORDINATOR),
        ERR_ELECTION_PHASE_INVALID)

    election = sc.read_election()
    assert election["status"] == PHASE_RECONCILED
    assert election["version"] == version_after_reconciliation

    contests, _ = validate_paginated(
        client.list_contests(sc.election_id, users.DIRECTOR, {"limit": 100}))
    assert [contest["title"] for contest in contests] == ["County Sheriff"]


def test_sm_a_reconciled_election_can_be_reconciled_again(client):
    """Reconciliation is legal from the reconciled phase itself, so a second pass on a
    freshly read version rewrites the accountability figures and bumps the version
    without moving the election out of its terminal phase.

    PRD Section 3.9: "Reconciliation is the accountability close-out: an `ElectionsDirector` action legal from `POLLS_CLOSED` or from `RECONCILED`, so an election can be reconciled again on a firmer basis without leaving its terminal phase."

    PRD Section 3.9: "A reconciliation writes the worksheet's results onto the election: `total_ballots_issued` becomes `gross_issued`, `net_ballot_variance` becomes `net_variance`, `ballot_accountability_status` becomes the derived status, `reconciliation_basis` records the basis used, `last_reconciled_at` is stamped from the logical clock, `status` becomes `RECONCILED`, and `version` is bumped — which is why a client re-reconciling must read the election again to obtain a fresh `expected_election_version`."

    Design: Corner/state_machines/sm_reconciled_election_rejects_close_polls_and_deploy
    """
    sc = _three_pallet_polls_closed(client)
    first = fixtures.reconcile(sc, BASIS_PRELIMINARY)
    assert first["status"] == PHASE_RECONCILED

    second = validate_success(
        client.reconcile(sc.election_id,
                         f.reconcile_payload(BASIS_PRELIMINARY, first["version"]),
                         users.DIRECTOR))
    assert second["status"] == PHASE_RECONCILED
    assert second["version"] == first["version"] + 1
    assert_fields_equal(second, {
        "reconciliation_basis": BASIS_PRELIMINARY,
        "total_ballots_issued": 5001,
        "net_ballot_variance": 105,
        "ballot_accountability_status": ACCOUNTABILITY_OUT_OF_BALANCE,
    }, "re-reconciled election")
    assert_iso_timestamp(second["last_reconciled_at"], "election.last_reconciled_at")


# ---- The style lock touches only the styles a precinct points at ----

def test_sm_locking_styles_leaves_an_unreferenced_approved_style_untouched(client):
    """Locking the styles promotes only the approved style some precinct points at; an
    approved style no precinct points at keeps its state and its version exactly.

    PRD Section 3.4: "Each such style then transitions `APPROVED → LOCKED` and has its `version` bumped."

    PRD Section 3.4: "Styles that no precinct points at, and styles in `DRAFT`, `PROOFING` or `PROOF_REJECTED`, are left entirely untouched and their `version` does not move."

    Design: Corner/state_machines/sm_lock_styles_locks_only_precinct_referenced_styles
    """
    sc = fixtures.contests_certified(client)
    fixtures.certify_languages(sc)
    fixtures.approve_proof_cycle(sc)
    fixtures.assign_style(sc)

    unreferenced_id = fixtures.add_style(sc, style_code=STYLE_CODE_ALT)
    fixtures.certify_languages(sc, style_id=unreferenced_id)
    fixtures.approve_proof_cycle(sc, style_id=unreferenced_id)
    before = sc.read_style(unreferenced_id)
    assert before["status"] == STYLE_APPROVED

    election = validate_success(client.lock_styles(sc.election_id, users.DIRECTOR))
    assert election["status"] == PHASE_STYLES_LOCKED

    referenced = sc.read_style()
    assert referenced["status"] == STYLE_LOCKED
    assert referenced["precinct_count"] == 1

    unreferenced = sc.read_style(unreferenced_id)
    assert unreferenced["status"] == STYLE_APPROVED
    assert unreferenced["version"] == before["version"]
    assert_fields_equal(unreferenced, {
        "precinct_count": 0,
        "revision": 1,
        "translated_languages": [LANGUAGE_EN],
        "certified_formats": [FORMAT_PAPER_STANDARD],
        "updated_at": before["updated_at"],
    }, "unreferenced ballot style")


# ---- Closing the polls recalls the machines and demotes readiness ----

def test_sm_closing_the_polls_returns_the_deployed_unit_with_its_seal_intact(client):
    """Closing the polls recalls every deployed machine to returned custody, keeps its
    seal number and the election's open-seal count, and appends a system-written
    RETURN line for each recalled machine.

    PRD Section 3.9: "Every tabulator of the election whose `custody_status` is `DEPLOYED` transitions `DEPLOYED → RETURNED`, **retaining** its `seal_number` — the seal stays intact through transport, so `open_seal_count` does not change at poll close — and a custody event of type `RETURN` is appended for each with `actor_user_id` of `"system"`."

    PRD Section 3.9: "The election's `status` becomes `POLLS_CLOSED`."

    Design: Corner/state_machines/sm_close_polls_returns_units_and_demotes_precinct_readiness
    """
    sc = fixtures.deployed_election(client)
    assert sc.read_tabulator()["custody_status"] == CUSTODY_DEPLOYED
    assert sc.read_election()["open_seal_count"] == 1

    election = validate_success(client.close_polls(sc.election_id, users.DIRECTOR))
    assert election["status"] == PHASE_POLLS_CLOSED
    assert election["open_seal_count"] == 1

    unit = sc.read_tabulator()
    assert_fields_equal(unit, {
        "custody_status": CUSTODY_RETURNED,
        "seal_number": SEAL_TAB_1,
        "program_status": UNIT_LA_PASSED,
        "precinct_id": sc.precinct_id,
    }, "recalled tabulator")

    rows, _ = validate_paginated(
        client.list_custody_events(sc.election_id, users.DIRECTOR,
                                   {"subject_id": sc.tabulator_id,
                                    "event_type": EVENT_RETURN, "limit": 100}))
    assert len(rows) == 1
    assert_custody_event(rows[0], EVENT_RETURN,
                         subject_type=SUBJECT_TABULATOR_UNIT,
                         subject_id=sc.tabulator_id,
                         from_state=CUSTODY_DEPLOYED,
                         to_state=CUSTODY_RETURNED,
                         seal_number=SEAL_TAB_1)
    assert_system_actor(rows[0])


def test_sm_closing_the_polls_demotes_precinct_and_election_readiness(client):
    """With no machine deployed any longer, the precinct falls out of readiness and the
    election's readiness is blocked, while the paper accounting is left alone.

    PRD Section 3.9: "Each affected precinct recomputes `deployment_status`, which necessarily falls to `NOT_READY` since no unit is deployed any longer, and the election recomputes `deployment_readiness`, which necessarily becomes `BLOCKED`."

    PRD Section 3.9: "The election's `status` becomes `POLLS_CLOSED`."

    Design: Corner/state_machines/sm_close_polls_returns_units_and_demotes_precinct_readiness
    """
    sc = fixtures.deployed_election(client)
    assert sc.read_precinct()["deployment_status"] == READINESS_READY
    assert sc.read_election()["deployment_readiness"] == READINESS_READY

    election = validate_success(client.close_polls(sc.election_id, users.DIRECTOR))
    assert election["status"] == PHASE_POLLS_CLOSED
    assert election["deployment_readiness"] == READINESS_BLOCKED
    assert sc.read_precinct()["deployment_status"] == READINESS_NOT_READY

    lot = sc.read_lot()
    assert lot["custody_state"] == LOT_ISSUED
    assert_fields_equal(lot, {
        "quantity_received": 12500,
        "issued_quantity": 3000,
        "precinct_id": sc.precinct_id,
    }, "ballot lot at poll close")


# ---- Disqualifying a certified candidate recompacts the order and voids decks ----

def test_sm_disqualification_recompacts_the_surviving_certified_siblings(client):
    """Disqualifying a certified candidate clears its own certified position, recompacts
    the surviving siblings onto contiguous zero-based ranks and recomputes the
    contest's certified candidate count.

    PRD Section 3.2: "In the first hop the candidate's `disqualified_reason` is stored, its `base_order_index` is cleared to null — a disqualified candidate holds no certified position — and the contest's `certified_candidate_count` is recomputed."

    PRD Section 3.2: "In the second hop, because the contest's certified roster has shrunk, every surviving `CERTIFIED` sibling has its `base_order_index` recompacted on the certified basis, so the rotation modulus falls by one and the printed order of the whole contest can shift; this recompaction runs only once the ordering has been frozen, that is when the election is no longer in `SETUP`."

    PRD Section 3.2: "Each candidate's `base_order_index` is its zero-based rank in that order."

    Design: Corner/state_machines/sm_candidate_disqualification_recompacts_order_and_voids_decks
    """
    sc = fixtures.new_election(client)
    contest_id = fixtures.add_contest(sc)
    first_id = fixtures.add_candidate(sc)
    middle_id = fixtures.add_candidate(sc, full_name="Ben Brooks", ballot_name="Brooks",
                                       filing_received_at="2026-06-02T09:00:00Z")
    last_id = fixtures.add_candidate(sc, full_name="Cai Chen", ballot_name="Chen",
                                     filing_received_at="2026-06-03T09:00:00Z")
    fixtures.certify_contest(sc)
    fixtures.add_style(sc)
    fixtures.add_precinct(sc)
    validate_success(client.certify_ballot_order(sc.election_id, users.DIRECTOR))

    roster = sc.candidates_of(contest_id)
    assert find_by(roster, "id", first_id)["base_order_index"] == 0
    assert find_by(roster, "id", middle_id)["base_order_index"] == 1
    assert find_by(roster, "id", last_id)["base_order_index"] == 2

    disqualified = validate_success(
        client.disqualify_candidate(
            middle_id, f.disqualify_payload("Residency requirement not met"), users.DIRECTOR))
    assert disqualified["status"] == CANDIDATE_DISQUALIFIED
    assert_fields_equal(disqualified, {
        "base_order_index": None,
        "disqualified_reason": "Residency requirement not met",
    }, "disqualified candidate")

    roster = sc.candidates_of(contest_id)
    assert find_by(roster, "id", first_id)["base_order_index"] == 0
    assert find_by(roster, "id", last_id)["base_order_index"] == 1
    assert find_by(roster, "id", middle_id)["base_order_index"] is None

    contest = sc.read_contest(contest_id)
    assert contest["status"] == CONTEST_CERTIFIED
    assert contest["certified_candidate_count"] == 2


def test_sm_disqualification_voids_the_draft_deck_that_names_the_candidate(client):
    """Because the certified positions moved, a draft test deck whose expected marks
    name the disqualified candidate is voided, while its declared mark total, its
    contest and its ballot style are all left as they were.

    PRD Section 3.2: "In the third hop, because those indices moved, every test deck in `DRAFT` or `SEALED` whose expected marks reference the disqualified candidate, or whose ballot style covers this contest's district, transitions to `VOIDED` — its expectations no longer match the printed layout."

    PRD Section 3.8: "`expected_total_marks` is derived as the sum of `mark_count` across `expected_marks`."

    Design: Corner/state_machines/sm_candidate_disqualification_recompacts_order_and_voids_decks
    """
    sc = fixtures.new_election(client)
    contest_id = fixtures.add_contest(sc)
    fixtures.add_candidate(sc)
    marked_id = fixtures.add_candidate(sc, full_name="Ben Brooks", ballot_name="Brooks",
                                       filing_received_at="2026-06-02T09:00:00Z")
    fixtures.add_candidate(sc, full_name="Cai Chen", ballot_name="Chen",
                           filing_received_at="2026-06-03T09:00:00Z")
    fixtures.certify_contest(sc)
    style_id = fixtures.add_style(sc, district_codes=[DISTRICT_D12])
    fixtures.add_precinct(sc)
    validate_success(client.certify_ballot_order(sc.election_id, users.DIRECTOR))
    fixtures.certify_languages(sc)
    fixtures.approve_proof_cycle(sc)

    deck_id = fixtures.add_test_deck(sc, contest_id=contest_id, candidate_id=marked_id,
                                     ballot_count=1, blank_count=0, overvote_count=0,
                                     mark_count=10)
    decks, _ = validate_paginated(
        client.list_test_decks(style_id, users.TECHNICIAN, {"limit": 100}))
    assert find_by(decks, "id", deck_id)["status"] == DECK_DRAFT

    validate_success(
        client.disqualify_candidate(
            marked_id, f.disqualify_payload("Residency requirement not met"), users.DIRECTOR))

    decks, _ = validate_paginated(
        client.list_test_decks(style_id, users.TECHNICIAN, {"limit": 100}))
    voided = find_by(decks, "id", deck_id)
    assert voided["status"] == DECK_VOIDED
    assert voided["expected_total_marks"] == 10

    assert sc.read_contest(contest_id)["status"] == CONTEST_CERTIFIED
    assert sc.read_style(style_id)["status"] == STYLE_APPROVED
