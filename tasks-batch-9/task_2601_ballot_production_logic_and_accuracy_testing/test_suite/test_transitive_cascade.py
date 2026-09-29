"""Deep propagation chains: one call that walks several entity types.

Two chains are exercised here. Withdrawing a certified contest reverses the
whole production line — the contest, then the styles that printed it, then the
print jobs on those styles, then the ballot lots of those jobs, and finally the
precincts that held the paper and the election's readiness verdict. Recording a
failing logic-and-accuracy result reverses the equipment line — the session, the
tabulator's programming axis, the tabulator's physical custody axis and the seal
ledger, the precinct it was deployed to, and again the election's readiness.

Both chains are driven by a single request whose payload names none of the
downstream rows, and both are observed through the ordinary reads afterwards.
"""

from prd_bench_local_runner.testing import validate_success, validate_error

from test_helpers import assertions as asserts
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_client import BallotProductionApiClient
from test_helpers.api_errors import (
    ERR_DEPLOYMENT_NOT_READY,
    ERR_UNIT_STATE_INVALID,
)
from test_helpers.constants import (
    CONTEST_CERTIFIED,
    CONTEST_WITHDRAWN,
    CUSTODY_DEPLOYED,
    CUSTODY_IN_VAULT,
    DECK_CONSUMED,
    DECK_SEALED,
    DECK_VOIDED,
    EVENT_ISSUE,
    EVENT_RECEIPT,
    EVENT_SEAL_APPLIED,
    EVENT_SEAL_BROKEN,
    EVENT_TRANSFER_OUT,
    EVENT_VOID,
    FIRMWARE_VERSION_NEXT,
    FORMAT_PAPER_STANDARD,
    INVOICE_FINAL,
    JOB_DELIVERED,
    JOB_REJECTED,
    LANGUAGE_EN,
    LOT_ISSUED,
    LOT_VOIDED,
    PHASE_STYLES_LOCKED,
    READINESS_BLOCKED,
    READINESS_NOT_READY,
    READINESS_READY,
    SEAL_TAB_1,
    SESSION_FAILED,
    SESSION_IN_PROGRESS,
    SESSION_PASSED,
    STYLE_LOCKED,
    STYLE_PROOF_REJECTED,
    SUBJECT_BALLOT_LOT,
    SUBJECT_TABULATOR_UNIT,
    UNIT_LA_FAILED,
    UNIT_LA_PASSED,
    UNIT_PROGRAMMED,
)

# A second public test on the same unit, a full day clear of the first session's
# buffered interval so the calendar check cannot interfere.
SECOND_SESSION_START = "2026-09-02T14:00:00Z"
SECOND_SESSION_END = "2026-09-02T18:00:00Z"

# Figures the prepared world carries on entry, all derived by the declared
# workflow: a 12500-ballot order at 8450 cents per thousand bills a 105625-cent
# subtotal plus 45000 cents of freight, and the delivery of the single lot
# rewrites the invoice with a 1268-cent defect credit at 120 basis points.
COMMITTED_PRINT_CENTS_ON_ENTRY = 149357
RECEIVED_ON_ENTRY = 12500
ISSUED_ON_ENTRY = 3000


def _ready_election_with_deployed_unit(client: BallotProductionApiClient) -> fx.Scenario:
    """A locked election whose single precinct is READY and not yet declared deployed.

    One certified contest in D-12, one locked style, one precinct assigned to it,
    a delivered print job whose lot has been received and issued to the precinct,
    and one tabulator that has passed its public test and been sealed into place.
    """
    scenario = fx.la_passed_unit(client)
    fx.deploy_unit(scenario)
    return scenario


def _start_second_session(scenario: fx.Scenario) -> tuple:
    """Build a second deck, schedule a second public test on the same unit, open it."""
    deck_b = fx.add_test_deck(scenario, deck_code="DECK-B")
    session_2 = fx.schedule_session(
        scenario,
        deck_id=deck_b,
        scheduled_start=SECOND_SESSION_START,
        scheduled_end=SECOND_SESSION_END,
    )
    fx.sign_in_observers(scenario, session_2, names=["Obs Three", "Obs Four"])
    fx.set_clock(scenario.client, SECOND_SESSION_START)
    fx.start_session(scenario, session_2)
    return deck_b, session_2


# ---- Withdrawing a certified contest reverses the whole production line ----

def test_tc_withdrawal_hop1_clears_the_contest_and_the_certified_count(client):
    """Withdrawing a certified contest clears its printed order and the election's count.

    PRD Section 3.5: "The contest moves `CERTIFIED → WITHDRAWN`, its `ballot_order_index` is cleared to null, the supplied `withdrawn_reason` is stored, and the election's `certified_contest_count` is recomputed."

    Design: Difficulty/transitive_cascade/tc_contest_withdrawal_depth5_to_election_readiness
    """
    scenario = _ready_election_with_deployed_unit(client)

    contest_before = scenario.read_contest()
    asserts.assert_fields_equal(
        contest_before,
        {"status": CONTEST_CERTIFIED, "ballot_order_index": 1, "withdrawn_reason": None},
        "contest before the withdrawal",
    )
    election_before = scenario.read_election()
    asserts.assert_fields_equal(
        election_before,
        {"certified_contest_count": 1, "deployment_readiness": READINESS_READY},
        "election before the withdrawal",
    )

    reason = "Sole candidate died; the office moves to a special election"
    contest = validate_success(
        scenario.client.withdraw_contest(
            scenario.contest_id, f.withdraw_payload(reason), users.DIRECTOR))

    asserts.assert_fields_equal(
        contest,
        {"status": CONTEST_WITHDRAWN, "ballot_order_index": None, "withdrawn_reason": reason},
        "withdrawn contest",
    )
    assert scenario.read_election()["certified_contest_count"] == 0


def test_tc_withdrawal_hop2_rejects_the_locked_style_and_clears_its_coverage(client):
    """The style that printed the withdrawn contest falls back to PROOF_REJECTED with no coverage.

    PRD Section 3.5: "Because the contest is no longer certified, every ballot style of the election whose `district_codes` contains the withdrawn contest's `district_code` and whose status is `PROOFING`, `APPROVED` or `LOCKED` transitions to `PROOF_REJECTED`, has `contest_count` recomputed, and has `translated_languages` and `certified_formats` cleared to empty arrays."

    Design: Difficulty/transitive_cascade/tc_contest_withdrawal_depth5_to_election_readiness
    """
    scenario = _ready_election_with_deployed_unit(client)

    style_before = scenario.read_style()
    asserts.assert_fields_equal(
        style_before,
        {
            "status": STYLE_LOCKED,
            "contest_count": 1,
            "translated_languages": [LANGUAGE_EN],
            "certified_formats": [FORMAT_PAPER_STANDARD],
            "revision": 1,
            "proof_cycle_count": 1,
        },
        "style before the withdrawal",
    )

    validate_success(
        scenario.client.withdraw_contest(
            scenario.contest_id,
            f.withdraw_payload("Sole candidate died; the office moves to a special election"),
            users.DIRECTOR))

    style = scenario.read_style()
    asserts.assert_fields_equal(
        style,
        {
            "status": STYLE_PROOF_REJECTED,
            "contest_count": 0,
            "translated_languages": [],
            "certified_formats": [],
            "revision": 1,
            "proof_cycle_count": 1,
        },
        "style after the withdrawal",
    )


def test_tc_withdrawal_hop3_rejects_the_print_job_and_releases_the_committed_cents(client):
    """A delivered print job is rejected, its invoice zeroed and its whole commitment released.

    PRD Section 3.5: "Its press window is released, so its vendor's `active_job_count` is recomputed; `invoice_subtotal_cents`, `defect_credit_cents`, `freight_cents` and `invoice_total_cents` are all set to 0; and the election's `committed_print_cents` is reduced by exactly the amount that job had previously committed — the `ESTIMATE` total for a job that had only been approved, the `FINAL` total for a job that had already been delivered."

    Design: Difficulty/transitive_cascade/tc_contest_withdrawal_depth5_to_election_readiness
    """
    scenario = _ready_election_with_deployed_unit(client)

    job_before = scenario.read_job()
    asserts.assert_fields_equal(
        job_before,
        {
            "status": JOB_DELIVERED,
            "invoice_basis": INVOICE_FINAL,
            "invoice_subtotal_cents": 105625,
            "freight_cents": 45000,
            "defect_credit_cents": 1268,
            "invoice_total_cents": COMMITTED_PRINT_CENTS_ON_ENTRY,
            "delivered_quantity": RECEIVED_ON_ENTRY,
        },
        "print job before the withdrawal",
    )
    assert scenario.read_election()["committed_print_cents"] == COMMITTED_PRINT_CENTS_ON_ENTRY
    vendor_before = validate_success(
        scenario.client.get_print_vendor(scenario.vendor_id, users.DIRECTOR))
    assert vendor_before["active_job_count"] == 1

    validate_success(
        scenario.client.withdraw_contest(
            scenario.contest_id,
            f.withdraw_payload("Sole candidate died; the office moves to a special election"),
            users.DIRECTOR))

    job = scenario.read_job()
    assert job["status"] == JOB_REJECTED
    asserts.assert_invoice_zeroed(job)
    assert job["delivered_quantity"] == RECEIVED_ON_ENTRY
    assert scenario.read_election()["committed_print_cents"] == 0
    vendor = validate_success(
        scenario.client.get_print_vendor(scenario.vendor_id, users.DIRECTOR))
    assert vendor["active_job_count"] == 0


def test_tc_withdrawal_hop4_voids_the_issued_lot_and_zeroes_the_ballot_ledger(client):
    """The issued lot of a rejected job is voided, and the void is written to the ledger by the system.

    PRD Section 3.5: "Because those jobs are rejected, every ballot lot of a rejected job whose custody state is `IN_TRANSIT`, `RECEIVED` or `ISSUED` transitions to `VOIDED`, with `issued_quantity` cleared to 0, `unused_quantity` restored to `quantity_received` and `precinct_id` and `issued_by_user_id` cleared to null, and a custody event of type `VOID` appended for each."

    Design: Difficulty/transitive_cascade/tc_contest_withdrawal_depth5_to_election_readiness
    """
    scenario = _ready_election_with_deployed_unit(client)

    lot_before = scenario.read_lot()
    asserts.assert_fields_equal(
        lot_before,
        {
            "custody_state": LOT_ISSUED,
            "quantity_received": RECEIVED_ON_ENTRY,
            "issued_quantity": ISSUED_ON_ENTRY,
            "unused_quantity": RECEIVED_ON_ENTRY - ISSUED_ON_ENTRY,
            "precinct_id": scenario.precinct_id,
        },
        "lot before the withdrawal",
    )
    election_before = scenario.read_election()
    asserts.assert_fields_equal(
        election_before,
        {"total_ballots_received": RECEIVED_ON_ENTRY, "total_ballots_issued": ISSUED_ON_ENTRY},
        "election before the withdrawal",
    )

    validate_success(
        scenario.client.withdraw_contest(
            scenario.contest_id,
            f.withdraw_payload("Sole candidate died; the office moves to a special election"),
            users.DIRECTOR))

    lot = scenario.read_lot()
    asserts.assert_fields_equal(
        lot,
        {
            "custody_state": LOT_VOIDED,
            "quantity_received": RECEIVED_ON_ENTRY,
            "issued_quantity": 0,
            "unused_quantity": RECEIVED_ON_ENTRY,
            "precinct_id": None,
            "issued_by_user_id": None,
        },
        "voided lot",
    )
    election = scenario.read_election()
    asserts.assert_fields_equal(
        election,
        {"total_ballots_received": 0, "total_ballots_issued": 0},
        "election after the withdrawal",
    )

    lot_events = asserts.events_for_subject(scenario.custody_events(), scenario.lot_id)
    assert asserts.event_types(lot_events) == [
        EVENT_TRANSFER_OUT, EVENT_RECEIPT, EVENT_ISSUE, EVENT_VOID]
    asserts.assert_custody_event(
        lot_events[3], EVENT_VOID,
        subject_type=SUBJECT_BALLOT_LOT, subject_id=scenario.lot_id,
        from_state=LOT_ISSUED, to_state=LOT_VOIDED)
    asserts.assert_system_actor(lot_events[3])


def test_tc_withdrawal_hop5_blocks_readiness_and_the_deployment_gate(client):
    """Voiding the precinct's only lot drops it out of READY and blocks the deployment declaration.

    PRD Section 3.5: "Because those lots left `RECEIVED` and `ISSUED`, every precinct that had received ballots from them recomputes `ballots_received` — dropping to 0 when its only lots were voided — and therefore recomputes `deployment_status`, typically to `NOT_READY`; and because those precincts are no longer `READY`, the election's `deployment_readiness` is recomputed to `BLOCKED`."

    Design: Difficulty/transitive_cascade/tc_contest_withdrawal_depth5_to_election_readiness
    """
    scenario = _ready_election_with_deployed_unit(client)

    precinct_before = scenario.read_precinct()
    asserts.assert_fields_equal(
        precinct_before,
        {
            "required_ballot_quantity": 110,
            "ballots_received": ISSUED_ON_ENTRY,
            "deployment_status": READINESS_READY,
        },
        "precinct before the withdrawal",
    )
    assert scenario.read_election()["deployment_readiness"] == READINESS_READY

    validate_success(
        scenario.client.withdraw_contest(
            scenario.contest_id,
            f.withdraw_payload("Sole candidate died; the office moves to a special election"),
            users.DIRECTOR))

    precinct = scenario.read_precinct()
    asserts.assert_fields_equal(
        precinct,
        {"ballots_received": 0, "deployment_status": READINESS_NOT_READY},
        "precinct after the withdrawal",
    )
    election = scenario.read_election()
    asserts.assert_fields_equal(
        election,
        {"deployment_readiness": READINESS_BLOCKED, "status": PHASE_STYLES_LOCKED},
        "election after the withdrawal",
    )

    validate_error(
        scenario.client.deploy_election(scenario.election_id, users.DIRECTOR),
        ERR_DEPLOYMENT_NOT_READY)
    assert scenario.read_election()["status"] == PHASE_STYLES_LOCKED


def test_tc_withdrawal_leaves_the_sealed_unit_and_the_consumed_deck_untouched(client):
    """The cascade voids only DRAFT or SEALED decks and never touches the tabulator or its seal.

    PRD Section 3.5: "Every test deck of an affected style in `DRAFT` or `SEALED` is `VOIDED`."

    Design: Difficulty/transitive_cascade/tc_contest_withdrawal_depth5_to_election_readiness
    """
    scenario = _ready_election_with_deployed_unit(client)

    deck_before = validate_success(
        scenario.client.list_test_decks(scenario.style_id, users.DIRECTOR))
    assert asserts.find_by(deck_before, "id", scenario.deck_id)["status"] == DECK_CONSUMED

    validate_success(
        scenario.client.withdraw_contest(
            scenario.contest_id,
            f.withdraw_payload("Sole candidate died; the office moves to a special election"),
            users.DIRECTOR))

    decks = validate_success(
        scenario.client.list_test_decks(scenario.style_id, users.DIRECTOR))
    assert asserts.find_by(decks, "id", scenario.deck_id)["status"] == DECK_CONSUMED

    unit = scenario.read_tabulator()
    asserts.assert_fields_equal(
        unit,
        {
            "program_status": UNIT_LA_PASSED,
            "custody_status": CUSTODY_DEPLOYED,
            "precinct_id": scenario.precinct_id,
            "seal_number": SEAL_TAB_1,
        },
        "tabulator after the withdrawal",
    )
    assert scenario.read_election()["open_seal_count"] == 1

    unit_events = asserts.events_for_subject(
        scenario.custody_events(), scenario.tabulator_id)
    assert asserts.event_types(unit_events) == [EVENT_SEAL_APPLIED]


# ---- A failed public logic-and-accuracy test reverses the equipment line ----

def test_tc_la_failure_derives_the_absolute_deviation_discrepancy(client):
    """A single mark reported three times against an expectation of one scores a discrepancy of two.

    PRD Section 3.8: "Walking that key set in ascending `contest_id` then ascending `candidate_id` order, accumulate the absolute difference between the reported `mark_count` and the expected `mark_count` for each key, treating a key absent from either side as 0 on that side."

    Design: Difficulty/transitive_cascade/tc_la_failure_depth4_blocks_election_deploy
    """
    scenario = _ready_election_with_deployed_unit(client)
    _deck_b, session_2 = _start_second_session(scenario)

    unit_before = scenario.read_tabulator()
    asserts.assert_fields_equal(
        unit_before,
        {"program_status": UNIT_LA_PASSED, "custody_status": CUSTODY_DEPLOYED},
        "tabulator before the failing result",
    )

    session = validate_success(
        scenario.client.record_results(
            session_2,
            f.record_results_payload(
                [f.reported_mark(scenario.contest_id, scenario.candidate_id, 3)],
                reported_blank_count=1, reported_overvote_count=0),
            users.TECHNICIAN_2))

    asserts.assert_fields_equal(
        session,
        {
            "discrepancy_count": 2,
            "reported_blank_count": 1,
            "reported_overvote_count": 0,
            "status": SESSION_FAILED,
        },
        "recorded session",
    )
    asserts.assert_millisecond_timestamp(session.get("completed_at"), "session.completed_at")


def test_tc_la_failure_hop1_fails_the_session_and_voids_its_deck(client):
    """The failing result closes the session as FAILED and voids the deck it consumed.

    PRD Section 3.8: "Hop 1: the session moves `IN_PROGRESS → FAILED` and the deck moves `SEALED → VOIDED` — the deck must be rebuilt before the unit can be tested again."

    Design: Difficulty/transitive_cascade/tc_la_failure_depth4_blocks_election_deploy
    """
    scenario = _ready_election_with_deployed_unit(client)
    deck_b, session_2 = _start_second_session(scenario)

    decks_before = validate_success(
        scenario.client.list_test_decks(scenario.style_id, users.DIRECTOR))
    assert asserts.find_by(decks_before, "id", deck_b)["status"] == DECK_SEALED
    assert scenario.read_session(session_2)["status"] == SESSION_IN_PROGRESS

    session = validate_success(
        scenario.client.record_results(
            session_2,
            f.record_results_payload(
                [f.reported_mark(scenario.contest_id, scenario.candidate_id, 3)],
                reported_blank_count=1, reported_overvote_count=0),
            users.TECHNICIAN_2))

    assert session["status"] == SESSION_FAILED
    decks = validate_success(
        scenario.client.list_test_decks(scenario.style_id, users.DIRECTOR))
    assert asserts.find_by(decks, "id", deck_b)["status"] == DECK_VOIDED


def test_tc_la_failure_hop2_demotes_the_program_axis_and_breaks_the_deployment_seal(client):
    """A programming-axis failure forcibly breaks the physical seal on the custody axis.

    PRD Section 3.8: "Hop 2: the unit's `program_status` moves to `LA_FAILED`, and this happens whether the unit was `PROGRAMMED` or already `LA_PASSED`, so a post-election audit failure demotes a machine that had previously passed; additionally, if the unit's `custody_status` is `DEPLOYED`, the custody axis reverts `DEPLOYED → IN_VAULT` with `seal_number` and `precinct_id` cleared, a custody event of type `SEAL_BROKEN` appended with `actor_user_id` of `"system"`, and the election's `open_seal_count` decremented."

    Design: Difficulty/transitive_cascade/tc_la_failure_depth4_blocks_election_deploy
    """
    scenario = _ready_election_with_deployed_unit(client)
    _deck_b, session_2 = _start_second_session(scenario)

    assert scenario.read_election()["open_seal_count"] == 1

    validate_success(
        scenario.client.record_results(
            session_2,
            f.record_results_payload(
                [f.reported_mark(scenario.contest_id, scenario.candidate_id, 3)],
                reported_blank_count=1, reported_overvote_count=0),
            users.TECHNICIAN_2))

    unit = scenario.read_tabulator()
    asserts.assert_fields_equal(
        unit,
        {
            "program_status": UNIT_LA_FAILED,
            "custody_status": CUSTODY_IN_VAULT,
            "seal_number": None,
            "precinct_id": None,
        },
        "tabulator after the failing result",
    )
    assert scenario.read_election()["open_seal_count"] == 0

    unit_events = asserts.events_for_subject(
        scenario.custody_events(), scenario.tabulator_id)
    assert asserts.event_types(unit_events) == [EVENT_SEAL_APPLIED, EVENT_SEAL_BROKEN]
    asserts.assert_custody_event(
        unit_events[1], EVENT_SEAL_BROKEN,
        subject_type=SUBJECT_TABULATOR_UNIT, subject_id=scenario.tabulator_id,
        from_state=CUSTODY_DEPLOYED, to_state=CUSTODY_IN_VAULT)
    asserts.assert_system_actor(unit_events[1])


def test_tc_la_failure_hop3_and_hop4_block_the_precinct_and_the_election(client):
    """The precinct loses READY for want of a deployed unit, and the election's gate closes.

    PRD Section 3.8: "Hop 3: because the unit left `DEPLOYED`, the precinct it had been deployed to recomputes `deployment_status` and falls to `NOT_READY` — it no longer has a passed, deployed tabulator. Hop 4: because that precinct is no longer `READY`, the election's `deployment_readiness` is recomputed to `BLOCKED`, which in turn blocks the declaration of deployment with `ERR_DEPLOYMENT_NOT_READY`."

    Design: Difficulty/transitive_cascade/tc_la_failure_depth4_blocks_election_deploy
    """
    scenario = _ready_election_with_deployed_unit(client)
    _deck_b, session_2 = _start_second_session(scenario)

    precinct_before = scenario.read_precinct()
    asserts.assert_fields_equal(
        precinct_before,
        {"ballots_received": ISSUED_ON_ENTRY, "deployment_status": READINESS_READY},
        "precinct before the failing result",
    )
    assert scenario.read_election()["deployment_readiness"] == READINESS_READY

    validate_success(
        scenario.client.record_results(
            session_2,
            f.record_results_payload(
                [f.reported_mark(scenario.contest_id, scenario.candidate_id, 3)],
                reported_blank_count=1, reported_overvote_count=0),
            users.TECHNICIAN_2))

    precinct = scenario.read_precinct()
    asserts.assert_fields_equal(
        precinct,
        {"ballots_received": ISSUED_ON_ENTRY, "deployment_status": READINESS_NOT_READY},
        "precinct after the failing result",
    )
    election = scenario.read_election()
    asserts.assert_fields_equal(
        election,
        {"deployment_readiness": READINESS_BLOCKED, "status": PHASE_STYLES_LOCKED},
        "election after the failing result",
    )

    validate_error(
        scenario.client.deploy_election(scenario.election_id, users.DIRECTOR),
        ERR_DEPLOYMENT_NOT_READY)
    assert scenario.read_election()["status"] == PHASE_STYLES_LOCKED


def test_tc_la_failure_leaves_the_earlier_passed_session_and_the_paper_untouched(client):
    """The later failure does not rewrite the earlier passing session, its deck, or the issued paper.

    PRD Section 3.8: "The session moves `IN_PROGRESS → PASSED`, the deck moves `SEALED → CONSUMED`, the unit's `program_status` moves to `LA_PASSED`, `la_session_count` is recomputed as the number of sessions on that unit, and the readiness chain runs: the unit's precinct, if it has one, recomputes `deployment_status`, and the election recomputes `deployment_readiness`."

    Design: Difficulty/transitive_cascade/tc_la_failure_depth4_blocks_election_deploy
    """
    scenario = _ready_election_with_deployed_unit(client)
    _deck_b, session_2 = _start_second_session(scenario)

    validate_success(
        scenario.client.record_results(
            session_2,
            f.record_results_payload(
                [f.reported_mark(scenario.contest_id, scenario.candidate_id, 3)],
                reported_blank_count=1, reported_overvote_count=0),
            users.TECHNICIAN_2))

    first_session = scenario.read_session(scenario.session_ids[0])
    asserts.assert_fields_equal(
        first_session,
        {"status": SESSION_PASSED, "discrepancy_count": 0},
        "the earlier session",
    )
    decks = validate_success(
        scenario.client.list_test_decks(scenario.style_id, users.DIRECTOR))
    assert asserts.find_by(decks, "id", scenario.deck_ids[0])["status"] == DECK_CONSUMED

    lot = scenario.read_lot()
    asserts.assert_fields_equal(
        lot,
        {
            "custody_state": LOT_ISSUED,
            "issued_quantity": ISSUED_ON_ENTRY,
            "precinct_id": scenario.precinct_id,
        },
        "the issued lot",
    )
    assert scenario.read_election()["total_ballots_issued"] == ISSUED_ON_ENTRY


def test_tc_la_failure_returns_the_unit_to_the_reprogrammable_state_pair(client):
    """A failed unit lands back on exactly the state pair that programming accepts.

    PRD Section 3.8: "the unit's `program_status` must be `UNPROGRAMMED` or `LA_FAILED` **and** its `custody_status` must be `IN_VAULT`, or `ERR_UNIT_STATE_INVALID` — a deployed machine is not reprogrammed in the field."

    Design: Difficulty/transitive_cascade/tc_la_failure_depth4_blocks_election_deploy
    """
    scenario = _ready_election_with_deployed_unit(client)
    _deck_b, session_2 = _start_second_session(scenario)

    validate_error(
        scenario.client.program_tabulator(
            scenario.tabulator_id,
            f.program_payload(scenario.style_id, FIRMWARE_VERSION_NEXT),
            users.TECHNICIAN),
        ERR_UNIT_STATE_INVALID)

    validate_success(
        scenario.client.record_results(
            session_2,
            f.record_results_payload(
                [f.reported_mark(scenario.contest_id, scenario.candidate_id, 3)],
                reported_blank_count=1, reported_overvote_count=0),
            users.TECHNICIAN_2))

    reprogrammed = validate_success(
        scenario.client.program_tabulator(
            scenario.tabulator_id,
            f.program_payload(scenario.style_id, FIRMWARE_VERSION_NEXT),
            users.TECHNICIAN))
    asserts.assert_fields_equal(
        reprogrammed,
        {
            "program_status": UNIT_PROGRAMMED,
            "custody_status": CUSTODY_IN_VAULT,
            "firmware_version": FIRMWARE_VERSION_NEXT,
            "programmed_style_id": scenario.style_id,
        },
        "reprogrammed tabulator",
    )
