"""Conserved quantities and the calls that compensate one another exactly.

Three ledgers are walked here. A ballot lot's accounting identity — received
equals issued plus unused — must hold after every issue and every recall, while
the chain of custody behind it only ever grows. The election's open-seal count
must always equal the seals applied plus the retention seals minus the seals
broken, so breaking a deployment seal returns the count to its pre-deployment
value while a poll-close recall, which keeps the seal intact, leaves it alone.
And the election's committed print total must return to exactly zero when the
commitment it recorded in two steps is withdrawn, with no rounding residue.

Every figure asserted below is pre-computed from the declared rules rather than
re-derived from the response being checked.
"""

from prd_bench_local_runner.testing import validate_success, validate_error

from test_helpers import assertions as asserts
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_client import BallotProductionApiClient
from test_helpers.api_errors import ERR_STYLE_STATE_INVALID
from test_helpers.constants import (
    ACCOUNTABILITY_BALANCED,
    ASSET_TAG_1,
    ASSET_TAG_2,
    BASIS_FINAL_CANVASS,
    CONTEST_WITHDRAWN,
    CUSTODY_DEPLOYED,
    CUSTODY_IN_VAULT,
    CUSTODY_RETURNED,
    CUSTODY_SEALED_RETENTION,
    EVENT_ISSUE,
    EVENT_RECALL,
    EVENT_RECEIPT,
    EVENT_RETENTION_SEAL,
    EVENT_RETURN,
    EVENT_SEAL_APPLIED,
    EVENT_SEAL_BROKEN,
    EVENT_TRANSFER_OUT,
    FREIGHT_TIER_1_CENTS,
    INVOICE_ESTIMATE,
    INVOICE_FINAL,
    JOB_PROOF_PENDING,
    JOB_REJECTED,
    LOT_CODE_1,
    LOT_CODE_2,
    LOT_IN_TRANSIT,
    LOT_ISSUED,
    LOT_RECEIVED,
    LOT_VOIDED,
    PHASE_DEPLOYED,
    PHASE_POLLS_CLOSED,
    PHASE_RECONCILED,
    POLLING_PLACE_2,
    POLL_CLOSE_INSTANT,
    PRECINCT_CODE_2,
    READINESS_BLOCKED,
    READINESS_NOT_READY,
    READINESS_READY,
    SEAL_1,
    SEAL_2,
    SEAL_RETENTION_1,
    SEAL_RETENTION_2,
    SEAL_TAB_1,
    SEAL_TAB_2,
    SESSION_START,
    SPOILAGE_ALLOWANCE_LARGE_BP,
    STYLE_PROOF_REJECTED,
    SUBJECT_BALLOT_LOT,
    SUBJECT_TABULATOR_UNIT,
    TOLERANCE_MEDIUM_BP,
    UNIT_LA_PASSED,
    USER_CUSTODIAN,
)

# The single-pallet world of the lot-conservation walk.
RECEIVED_QUANTITY = 12500
ISSUE_PART = 3000
ISSUE_WHOLE = 12500
ISSUE_AGAIN = 4000
REQUIRED_BALLOTS = 110

# The two-pallet, two-precinct world of the seal walk.
LOT_1_QUANTITY = 6000
LOT_2_QUANTITY = 6500
DELIVERED_QUANTITY = 12500

# The post-election counts of the two returned lots, each summing to exactly the
# quantity that lot received.
LOT_1_VOTED = 5800
LOT_2_VOTED = 6300
SPOILED_PER_LOT = 100
UNUSED_PER_LOT = 100

# The final-canvass worksheet of that world: a 12500-ballot gross at the 15
# basis point allowance credits 18 ballots, leaving a 12482 net whose 100 basis
# point tolerance is 124 ballots, against a variance of 0.
WORKSHEET_LOT_COUNT = 2
WORKSHEET_SPOILAGE_CREDIT = 18
WORKSHEET_NET_ISSUED = 12482
WORKSHEET_TOLERANCE_BALLOTS = 124

# Retention: the election date 2026-11-03 plus 22 days.
RETENTION_DAYS = 22
RETENTION_DAY = "2026-11-25"

# The money ledger of a 12500-ballot order at 8450 cents per thousand. The
# estimate bills 105625 of paper plus 45000 of freight; the delivery rewrites the
# same subtotal with a 1268-cent credit at the inspected rate of 120 basis
# points, so the committed total falls by 1268 rather than being added again.
SUBTOTAL_CENTS = 105625
DEFECT_RATE_BP = 120
DEFECT_CREDIT_CENTS = 1268
ESTIMATE_TOTAL_CENTS = 150625
FINAL_TOTAL_CENTS = 149357

OBSERVER_ROSTERS = (["Obs One", "Obs Two"], ["Obs Three", "Obs Four"])


def _received_lot(client: BallotProductionApiClient) -> fx.Scenario:
    """A locked election whose single 12500-ballot pallet has been counted in.

    One certified contest, one locked style, one precinct of 100 registered
    voters requiring 110 ballots, and one delivered lot received in full, so the
    lot opens the walk with nothing issued.
    """
    scenario = fx.delivered_lot(client)
    fx.receive_lot(scenario, quantity_received=RECEIVED_QUANTITY)
    return scenario


def _issue(scenario: fx.Scenario, quantity: int) -> dict:
    """Issue the scenario's only lot to its only precinct."""
    return validate_success(
        scenario.client.issue_lot(
            scenario.lot_id,
            f.issue_payload(scenario.precinct_id, quantity),
            users.CUSTODIAN))


def _recall(scenario: fx.Scenario) -> dict:
    """Pull the scenario's only lot back into the warehouse."""
    return validate_success(
        scenario.client.recall_lot(scenario.lot_id, users.CUSTODIAN, f.recall_payload()))


def _lot_accounting(scenario: fx.Scenario) -> tuple:
    """The lot's issued and unused figures, having checked the identity holds."""
    lot = scenario.read_lot()
    asserts.assert_lot_conservation(lot)
    assert lot["quantity_received"] == RECEIVED_QUANTITY, (
        f"the counted receipt must not move, got {lot['quantity_received']}"
    )
    return lot["issued_quantity"], lot["unused_quantity"]


def _seal_identity(scenario: fx.Scenario) -> int:
    """The open-seal figure implied by the election's ledger."""
    types = asserts.event_types(scenario.custody_events())
    return (types.count(EVENT_SEAL_APPLIED) + types.count(EVENT_RETENTION_SEAL)
            - types.count(EVENT_SEAL_BROKEN))


def _assert_open_seals(scenario: fx.Scenario, expected: int) -> None:
    """Assert the stored open-seal count and the ledger agree on ``expected``."""
    stored = scenario.read_election()["open_seal_count"]
    assert stored == expected, f"open_seal_count expected {expected}, got {stored}"
    implied = _seal_identity(scenario)
    assert implied == expected, (
        f"the custody ledger implies {implied} open seals, not the stored {expected}"
    )


def _two_precinct_two_unit_world(client: BallotProductionApiClient) -> fx.Scenario:
    """A locked election with two precincts, two pallets and two tested units.

    Both precincts point at the same locked style and each holds one issued
    pallet — 6000 ballots against 110 required, and 6500 against 110. Both units
    are programmed by one technician and passed by another, and no seal has been
    applied yet, so the election opens the walk with an open-seal count of 0.
    """
    scenario = fx.contests_certified(client)
    fx.add_precinct(scenario, precinct_code=PRECINCT_CODE_2,
                    polling_place=POLLING_PLACE_2)
    fx.certify_languages(scenario)
    fx.approve_proof_cycle(scenario)
    fx.assign_style(scenario, precinct_id=scenario.precinct_ids[0])
    fx.assign_style(scenario, precinct_id=scenario.precinct_ids[1])
    validate_success(scenario.client.lock_styles(scenario.election_id, users.DIRECTOR))

    fx.add_vendor(scenario)
    fx.add_print_job(scenario)
    fx.printed_job(scenario)
    fx.inspect_job(scenario)
    fx.deliver_job(scenario, lots=[
        f.manifest_line(LOT_CODE_1, LOT_1_QUANTITY, SEAL_1),
        f.manifest_line(LOT_CODE_2, LOT_2_QUANTITY, SEAL_2),
    ])
    fx.receive_lot(scenario, scenario.lot_ids[0], SEAL_1, LOT_1_QUANTITY)
    fx.issue_lot(scenario, scenario.lot_ids[0], scenario.precinct_ids[0], LOT_1_QUANTITY)
    fx.receive_lot(scenario, scenario.lot_ids[1], SEAL_2, LOT_2_QUANTITY)
    fx.issue_lot(scenario, scenario.lot_ids[1], scenario.precinct_ids[1], LOT_2_QUANTITY)

    fx.add_tabulator(scenario, asset_tag=ASSET_TAG_1)
    fx.add_tabulator(scenario, asset_tag=ASSET_TAG_2)
    fx.add_test_deck(scenario, deck_code="DECK-A")
    fx.add_test_deck(scenario, deck_code="DECK-B")
    for index in (0, 1):
        fx.program_unit(scenario, tabulator_id=scenario.tabulator_ids[index])
        fx.schedule_session(scenario, tabulator_id=scenario.tabulator_ids[index],
                            deck_id=scenario.deck_ids[index])
        fx.sign_in_observers(scenario, scenario.session_ids[index],
                             names=OBSERVER_ROSTERS[index])
    fx.set_clock(client, SESSION_START)
    for index in (0, 1):
        fx.start_session(scenario, scenario.session_ids[index])
        fx.record_matching_results(scenario, scenario.session_ids[index])
    return scenario


def _deploy_both_units(scenario: fx.Scenario) -> None:
    """Seal each tested unit into the precinct that already holds its paper."""
    fx.deploy_unit(scenario, scenario.tabulator_ids[0], scenario.precinct_ids[0], SEAL_TAB_1)
    fx.deploy_unit(scenario, scenario.tabulator_ids[1], scenario.precinct_ids[1], SEAL_TAB_2)


def _close_the_polls(scenario: fx.Scenario) -> dict:
    """Report both precinct boards' counts and close the polls at the close instant."""
    fx.return_lot_counts(scenario, scenario.lot_ids[0], LOT_1_VOTED,
                         SPOILED_PER_LOT, UNUSED_PER_LOT)
    fx.return_lot_counts(scenario, scenario.lot_ids[1], LOT_2_VOTED,
                         SPOILED_PER_LOT, UNUSED_PER_LOT)
    fx.set_clock(scenario.client, POLL_CLOSE_INSTANT)
    return validate_success(
        scenario.client.close_polls(scenario.election_id, users.DIRECTOR))


def _unit_events(scenario: fx.Scenario, tabulator_id: str) -> list:
    """The ledger lines of one unit, in the order the election ledger returns them."""
    return asserts.events_for_subject(scenario.custody_events(), tabulator_id)


# ---- A pallet issued and recalled: the counts compensate, the ledger does not ----

def test_ci_lot_conservation_holds_at_every_point_of_the_issue_recall_walk(client):
    """The received count equals issued plus unused after each of six movements.

    PRD Section 3.7: "Across an issue followed by a recall the conserved identity — received equals issued plus unused — is exactly restored."

    Design: Difficulty/compensating_invariant/ci_lot_receipt_conservation_across_issue_and_recall
    """
    scenario = _received_lot(client)

    assert _lot_accounting(scenario) == (0, 12500)
    _issue(scenario, ISSUE_PART)
    assert _lot_accounting(scenario) == (3000, 9500)
    _recall(scenario)
    assert _lot_accounting(scenario) == (0, 12500)
    _issue(scenario, ISSUE_WHOLE)
    assert _lot_accounting(scenario) == (12500, 0)
    _recall(scenario)
    assert _lot_accounting(scenario) == (0, 12500)
    _issue(scenario, ISSUE_AGAIN)
    assert _lot_accounting(scenario) == (4000, 8500)


def test_ci_issue_writes_the_precinct_and_the_election_ballot_ledgers(client):
    """Issuing 3000 of 12500 ballots names the custodian and moves both derived counts.

    PRD Section 3.7: "On success the lot moves `RECEIVED → ISSUED`, stores `precinct_id` and `issued_quantity`, sets `unused_quantity` to the received quantity minus the issued quantity, records `issued_by_user_id` as the custodian's `X-User-ID`, appends a custody event of type `ISSUE`, and triggers the readiness chain: the precinct recomputes `ballots_received` and `deployment_status`, and the election recomputes `total_ballots_issued` — the sum of `issued_quantity` over its lots in `ISSUED` or `RETURNED` — and `deployment_readiness`."

    Design: Difficulty/compensating_invariant/ci_lot_receipt_conservation_across_issue_and_recall
    """
    scenario = _received_lot(client)

    lot = _issue(scenario, ISSUE_PART)
    asserts.assert_fields_equal(
        lot,
        {
            "custody_state": LOT_ISSUED,
            "precinct_id": scenario.precinct_id,
            "issued_quantity": 3000,
            "unused_quantity": 9500,
            "issued_by_user_id": USER_CUSTODIAN,
        },
        "issued lot",
    )
    assert scenario.read_precinct()["ballots_received"] == 3000
    assert scenario.read_election()["total_ballots_issued"] == 3000


def test_ci_recall_restores_the_pre_issue_snapshot_exactly(client):
    """A recall puts the lot, the precinct and the election back where the issue found them.

    PRD Section 3.7: "The lot must be `ISSUED`; it moves `ISSUED → RECEIVED`, `issued_quantity` returns to 0, `unused_quantity` returns to the full `quantity_received`, `precinct_id` and `issued_by_user_id` are cleared to null, and a custody event of type `RECALL` is appended."

    Design: Difficulty/compensating_invariant/ci_lot_receipt_conservation_across_issue_and_recall
    """
    scenario = _received_lot(client)
    before = {
        "custody_state": LOT_RECEIVED,
        "quantity_received": 12500,
        "issued_quantity": 0,
        "unused_quantity": 12500,
        "precinct_id": None,
        "issued_by_user_id": None,
    }
    asserts.assert_fields_equal(scenario.read_lot(), before, "lot before the issue")

    _issue(scenario, ISSUE_PART)
    lot = _recall(scenario)

    asserts.assert_fields_equal(lot, before, "lot after the recall")
    assert scenario.read_precinct()["ballots_received"] == 0
    assert scenario.read_election()["total_ballots_issued"] == 0


def test_ci_issuing_the_whole_pallet_drives_unused_to_zero_and_back(client):
    """Issuing every received ballot leaves no unused ballots, and the recall restores them all.

    PRD Section 3.7: "On success the lot moves `RECEIVED → ISSUED`, stores `precinct_id` and `issued_quantity`, sets `unused_quantity` to the received quantity minus the issued quantity, records `issued_by_user_id` as the custodian's `X-User-ID`, appends a custody event of type `ISSUE`, and triggers the readiness chain: the precinct recomputes `ballots_received` and `deployment_status`, and the election recomputes `total_ballots_issued` — the sum of `issued_quantity` over its lots in `ISSUED` or `RETURNED` — and `deployment_readiness`."

    Design: Difficulty/compensating_invariant/ci_lot_receipt_conservation_across_issue_and_recall
    """
    scenario = _received_lot(client)
    _issue(scenario, ISSUE_PART)
    _recall(scenario)

    lot = _issue(scenario, ISSUE_WHOLE)
    asserts.assert_fields_equal(
        lot,
        {"issued_quantity": 12500, "unused_quantity": 0, "custody_state": LOT_ISSUED},
        "lot holding the whole pallet",
    )
    asserts.assert_lot_conservation(lot)
    assert scenario.read_precinct()["ballots_received"] == 12500
    assert scenario.read_election()["total_ballots_issued"] == 12500

    recalled = _recall(scenario)
    asserts.assert_fields_equal(
        recalled,
        {"issued_quantity": 0, "unused_quantity": 12500, "custody_state": LOT_RECEIVED},
        "lot after the whole pallet came back",
    )
    assert scenario.read_election()["total_ballots_issued"] == 0


def test_ci_recall_does_not_un_receive_the_ballots(client):
    """The election's received total stays at 12500 through every issue and recall.

    PRD Section 3.7: "On success the lot moves `IN_TRANSIT → RECEIVED`, stores the counted `quantity_received`, sets `unused_quantity` equal to it (nothing has been issued yet), appends a custody event of type `RECEIPT` recording `from_state` `IN_TRANSIT`, `to_state` `RECEIVED` and the lot's seal, and forces the election's `total_ballots_received` to be recomputed as the sum of `quantity_received` over the election's lots in `RECEIVED`, `ISSUED` or `RETURNED`."

    Design: Difficulty/compensating_invariant/ci_lot_receipt_conservation_across_issue_and_recall
    """
    scenario = _received_lot(client)
    assert scenario.read_election()["total_ballots_received"] == 12500

    for movement in (ISSUE_PART, None, ISSUE_WHOLE, None, ISSUE_AGAIN):
        if movement is None:
            _recall(scenario)
        else:
            _issue(scenario, movement)
        assert scenario.read_election()["total_ballots_received"] == 12500, (
            "a recall returns ballots to the warehouse; it does not un-receive them"
        )


def test_ci_the_issue_recall_walk_never_makes_the_precinct_ready(client):
    """Paper alone never makes a precinct ready, even 12500 ballots against 110 required.

    PRD Section 3.9: "A precinct's `deployment_status` is `READY` when **both** of two conditions hold: its `ballots_received` is greater than or equal to its `required_ballot_quantity`, and at least one tabulator exists whose `precinct_id` is that precinct with `program_status` `LA_PASSED` **and** `custody_status` `DEPLOYED`."

    Design: Difficulty/compensating_invariant/ci_lot_receipt_conservation_across_issue_and_recall
    """
    scenario = _received_lot(client)
    assert scenario.read_precinct()["required_ballot_quantity"] == REQUIRED_BALLOTS

    for movement in (ISSUE_PART, None, ISSUE_WHOLE, None, ISSUE_AGAIN):
        if movement is None:
            _recall(scenario)
        else:
            _issue(scenario, movement)
        assert scenario.read_precinct()["deployment_status"] == READINESS_NOT_READY
        assert scenario.read_election()["deployment_readiness"] == READINESS_BLOCKED


def test_ci_the_custody_chain_grows_by_one_row_per_movement(client):
    """The compensating movements are recorded, not erased: seven rows in sequence order.

    PRD Section 3.6: "A custody event of type `TRANSFER_OUT` with `to_state` `IN_TRANSIT` is appended for each created lot."

    Design: Difficulty/compensating_invariant/ci_lot_receipt_conservation_across_issue_and_recall
    """
    scenario = _received_lot(client)
    _issue(scenario, ISSUE_PART)
    _recall(scenario)
    _issue(scenario, ISSUE_WHOLE)
    _recall(scenario)
    _issue(scenario, ISSUE_AGAIN)

    events = asserts.events_for_subject(scenario.custody_events(), scenario.lot_id)
    assert asserts.event_types(events) == [
        EVENT_TRANSFER_OUT,
        EVENT_RECEIPT,
        EVENT_ISSUE,
        EVENT_RECALL,
        EVENT_ISSUE,
        EVENT_RECALL,
        EVENT_ISSUE,
    ]
    asserts.assert_sequence_indices_ascending(events)
    assert [event["sequence_index"] for event in events] == [1, 2, 3, 4, 5, 6, 7]

    asserts.assert_custody_event(events[0], EVENT_TRANSFER_OUT,
                                 subject_type=SUBJECT_BALLOT_LOT,
                                 subject_id=scenario.lot_id,
                                 to_state=LOT_IN_TRANSIT)
    asserts.assert_custody_event(events[1], EVENT_RECEIPT,
                                 subject_type=SUBJECT_BALLOT_LOT,
                                 subject_id=scenario.lot_id,
                                 from_state=LOT_IN_TRANSIT,
                                 to_state=LOT_RECEIVED,
                                 seal_number=SEAL_1)
    for index in (3, 5):
        asserts.assert_custody_event(events[index], EVENT_RECALL,
                                     subject_type=SUBJECT_BALLOT_LOT,
                                     subject_id=scenario.lot_id,
                                     from_state=LOT_ISSUED,
                                     to_state=LOT_RECEIVED,
                                     actor_user_id=USER_CUSTODIAN)


# ---- Seals applied, broken, retained and re-applied: a conserved count ----

BREAK_REASON = "Firmware seal re-verification before election day"


def _break_first_seal(scenario: fx.Scenario) -> dict:
    """Break the deployment seal of the first unit."""
    return validate_success(
        scenario.client.break_seal(scenario.tabulator_ids[0],
                                   f.break_seal_payload(BREAK_REASON),
                                   users.CUSTODIAN))


def _walk_through_deployment(scenario: fx.Scenario) -> None:
    """Deploy both units, compensate and re-apply the first seal, declare deployment."""
    _deploy_both_units(scenario)
    _break_first_seal(scenario)
    fx.deploy_unit(scenario, scenario.tabulator_ids[0], scenario.precinct_ids[0], SEAL_TAB_1)
    validate_success(scenario.client.deploy_election(scenario.election_id, users.DIRECTOR))


def _retain_both_seals(scenario: fx.Scenario) -> tuple:
    """Apply the two post-election retention seals."""
    first = validate_success(
        scenario.client.seal_retention(
            scenario.tabulator_ids[0],
            f.seal_retention_payload(SEAL_RETENTION_1, RETENTION_DAYS),
            users.CUSTODIAN))
    second = validate_success(
        scenario.client.seal_retention(
            scenario.tabulator_ids[1],
            f.seal_retention_payload(SEAL_RETENTION_2, RETENTION_DAYS),
            users.CUSTODIAN))
    return first, second


def test_ci_deploying_the_two_units_walks_the_open_seal_count_to_two(client):
    """Each deployment seal adds one to a count the ledger can always re-derive.

    PRD Section 2.11: "And the election's `open_seal_count` is a conserved quantity — the number of `SEAL_APPLIED` and `RETENTION_SEAL` lines for the election minus the number of `SEAL_BROKEN` lines — so every compensating action returns the count to the value it had before the action it compensates."

    Design: Difficulty/compensating_invariant/ci_open_seal_count_conservation_across_deploy_break_seal_and_retention
    """
    scenario = _two_precinct_two_unit_world(client)
    _assert_open_seals(scenario, 0)
    assert scenario.read_election()["deployment_readiness"] == READINESS_BLOCKED

    first = validate_success(
        scenario.client.deploy_tabulator(
            scenario.tabulator_ids[0],
            f.deploy_unit_payload(scenario.precinct_ids[0], SEAL_TAB_1),
            users.CUSTODIAN))
    asserts.assert_fields_equal(
        first,
        {
            "custody_status": CUSTODY_DEPLOYED,
            "program_status": UNIT_LA_PASSED,
            "seal_number": SEAL_TAB_1,
            "precinct_id": scenario.precinct_ids[0],
        },
        "first deployed unit",
    )
    _assert_open_seals(scenario, 1)
    assert scenario.read_precinct(scenario.precinct_ids[0])["deployment_status"] == READINESS_READY
    assert scenario.read_election()["deployment_readiness"] == READINESS_BLOCKED

    validate_success(
        scenario.client.deploy_tabulator(
            scenario.tabulator_ids[1],
            f.deploy_unit_payload(scenario.precinct_ids[1], SEAL_TAB_2),
            users.CUSTODIAN))
    _assert_open_seals(scenario, 2)
    assert scenario.read_precinct(scenario.precinct_ids[1])["deployment_status"] == READINESS_READY
    assert scenario.read_election()["deployment_readiness"] == READINESS_READY


def test_ci_breaking_a_seal_restores_the_pre_deployment_snapshot(client):
    """Breaking the seal reverses its own deployment and nothing else.

    PRD Section 3.9: "The unit moves `DEPLOYED → IN_VAULT`, `seal_number` and `precinct_id` are cleared to null, a custody event of type `SEAL_BROKEN` is appended recording the seal that was broken, and `open_seal_count` is decremented — returning to exactly its pre-deploy value."

    Design: Difficulty/compensating_invariant/ci_open_seal_count_conservation_across_deploy_break_seal_and_retention
    """
    scenario = _two_precinct_two_unit_world(client)
    before = {
        "custody_status": CUSTODY_IN_VAULT,
        "program_status": UNIT_LA_PASSED,
        "seal_number": None,
        "precinct_id": None,
    }
    asserts.assert_fields_equal(scenario.read_tabulator(scenario.tabulator_ids[0]),
                                before, "first unit before its deployment")

    _deploy_both_units(scenario)
    _assert_open_seals(scenario, 2)

    unit = _break_first_seal(scenario)
    asserts.assert_fields_equal(unit, before, "first unit after its seal was broken")
    _assert_open_seals(scenario, 1)
    assert scenario.read_precinct(scenario.precinct_ids[0])["deployment_status"] == READINESS_NOT_READY
    assert scenario.read_election()["deployment_readiness"] == READINESS_BLOCKED
    assert scenario.read_tabulator(scenario.tabulator_ids[1])["seal_number"] == SEAL_TAB_2


def test_ci_the_released_seal_can_be_applied_again_and_restores_readiness(client):
    """The broken seal number is free again, so re-deploying it carries the count back to two.

    PRD Section 3.9: "The election's `deployment_readiness` is `READY` when the election has at least one precinct **and** every one of its precincts is `READY`; otherwise `BLOCKED`."

    Design: Difficulty/compensating_invariant/ci_open_seal_count_conservation_across_deploy_break_seal_and_retention
    """
    scenario = _two_precinct_two_unit_world(client)
    _deploy_both_units(scenario)
    _break_first_seal(scenario)

    unit = validate_success(
        scenario.client.deploy_tabulator(
            scenario.tabulator_ids[0],
            f.deploy_unit_payload(scenario.precinct_ids[0], SEAL_TAB_1),
            users.CUSTODIAN))
    asserts.assert_fields_equal(
        unit,
        {
            "custody_status": CUSTODY_DEPLOYED,
            "seal_number": SEAL_TAB_1,
            "precinct_id": scenario.precinct_ids[0],
        },
        "re-deployed unit",
    )
    _assert_open_seals(scenario, 2)
    assert scenario.read_precinct(scenario.precinct_ids[0])["deployment_status"] == READINESS_READY
    assert scenario.read_election()["deployment_readiness"] == READINESS_READY

    election = validate_success(
        scenario.client.deploy_election(scenario.election_id, users.DIRECTOR))
    asserts.assert_fields_equal(
        election,
        {"status": PHASE_DEPLOYED, "deployment_readiness": READINESS_READY, "open_seal_count": 2},
        "declared election",
    )


def test_ci_closing_the_polls_returns_both_units_with_their_seals_intact(client):
    """A returned but still sealed unit is still an open seal, so the count does not move.

    PRD Section 3.9: "Every tabulator of the election whose `custody_status` is `DEPLOYED` transitions `DEPLOYED → RETURNED`, **retaining** its `seal_number` — the seal stays intact through transport, so `open_seal_count` does not change at poll close — and a custody event of type `RETURN` is appended for each with `actor_user_id` of `"system"`."

    Design: Difficulty/compensating_invariant/ci_open_seal_count_conservation_across_deploy_break_seal_and_retention
    """
    scenario = _two_precinct_two_unit_world(client)
    _walk_through_deployment(scenario)
    _assert_open_seals(scenario, 2)

    election = _close_the_polls(scenario)
    asserts.assert_fields_equal(
        election,
        {"status": PHASE_POLLS_CLOSED, "open_seal_count": 2,
         "deployment_readiness": READINESS_BLOCKED},
        "election at poll close",
    )
    _assert_open_seals(scenario, 2)

    for index, seal in ((0, SEAL_TAB_1), (1, SEAL_TAB_2)):
        unit = scenario.read_tabulator(scenario.tabulator_ids[index])
        asserts.assert_fields_equal(
            unit,
            {"custody_status": CUSTODY_RETURNED, "seal_number": seal,
             "program_status": UNIT_LA_PASSED},
            "returned unit",
        )
        returns = [event for event in _unit_events(scenario, scenario.tabulator_ids[index])
                   if event["event_type"] == EVENT_RETURN]
        assert len(returns) == 1
        asserts.assert_custody_event(returns[0], EVENT_RETURN,
                                     subject_type=SUBJECT_TABULATOR_UNIT,
                                     subject_id=scenario.tabulator_ids[index],
                                     from_state=CUSTODY_DEPLOYED,
                                     to_state=CUSTODY_RETURNED,
                                     seal_number=seal)
        asserts.assert_system_actor(returns[0])


def test_ci_the_retention_seals_carry_the_count_from_two_to_four(client):
    """Each retention seal is a new seal on the record and increments the count again.

    PRD Section 3.9: "On success the unit moves `RETURNED → SEALED_RETENTION`, its terminal custody state; `seal_number` is stored and `retention_until` is set to the election's `election_date` plus `retention_days` days; a custody event of type `RETENTION_SEAL` is appended; and the election's `open_seal_count` increases by one."

    Design: Difficulty/compensating_invariant/ci_open_seal_count_conservation_across_deploy_break_seal_and_retention
    """
    scenario = _two_precinct_two_unit_world(client)
    _walk_through_deployment(scenario)
    _close_the_polls(scenario)
    reconciled = fx.reconcile(scenario, BASIS_FINAL_CANVASS)
    assert reconciled["status"] == PHASE_RECONCILED
    _assert_open_seals(scenario, 2)

    first, second = _retain_both_seals(scenario)
    for unit, seal in ((first, SEAL_RETENTION_1), (second, SEAL_RETENTION_2)):
        asserts.assert_fields_equal(
            unit,
            {"custody_status": CUSTODY_SEALED_RETENTION, "seal_number": seal,
             "program_status": UNIT_LA_PASSED},
            "retention-sealed unit",
        )
        assert unit["retention_until"].startswith(RETENTION_DAY), (
            f"retention_until must fall on {RETENTION_DAY}, got {unit['retention_until']!r}"
        )
    _assert_open_seals(scenario, 4)


def test_ci_the_final_canvass_worksheet_balances_the_returned_paper(client):
    """The 12500 issued ballots come back fully accounted, inside a 124-ballot tolerance.

    PRD Section 3.9: "`ballot_accountability_status` is `BALANCED` when the absolute value of `net_variance` is less than or equal to `tolerance_ballots`, and `OUT_OF_BALANCE` otherwise."

    Design: Difficulty/compensating_invariant/ci_open_seal_count_conservation_across_deploy_break_seal_and_retention
    """
    scenario = _two_precinct_two_unit_world(client)
    _walk_through_deployment(scenario)
    _close_the_polls(scenario)

    election = fx.reconcile(scenario, BASIS_FINAL_CANVASS)
    asserts.assert_fields_equal(
        election,
        {
            "status": PHASE_RECONCILED,
            "ballot_accountability_status": ACCOUNTABILITY_BALANCED,
            "total_ballots_issued": DELIVERED_QUANTITY,
            "net_ballot_variance": 0,
            "reconciliation_basis": BASIS_FINAL_CANVASS,
            "open_seal_count": 2,
        },
        "reconciled election",
    )

    worksheet = validate_success(
        scenario.client.get_accountability(
            scenario.election_id, users.DIRECTOR,
            f.accountability_params(BASIS_FINAL_CANVASS)))
    asserts.assert_accountability_worksheet(
        worksheet,
        {
            "basis": BASIS_FINAL_CANVASS,
            "lot_count": WORKSHEET_LOT_COUNT,
            "gross_issued": DELIVERED_QUANTITY,
            "allowance_bp": SPOILAGE_ALLOWANCE_LARGE_BP,
            "spoilage_credit": WORKSHEET_SPOILAGE_CREDIT,
            "net_issued": WORKSHEET_NET_ISSUED,
            "accounted": DELIVERED_QUANTITY,
            "gross_variance": 0,
            "net_variance": 0,
            "tolerance_bp": TOLERANCE_MEDIUM_BP,
            "tolerance_ballots": WORKSHEET_TOLERANCE_BALLOTS,
            "ballot_accountability_status": ACCOUNTABILITY_BALANCED,
        },
    )


def test_ci_the_unit_ledgers_record_the_compensation_rather_than_erasing_it(client):
    """The re-sealed unit carries five ledger lines; its untouched twin carries three.

    PRD Section 3.9: "Note that a unit returned at poll close still carries its polling-place seal, and applying the retention seal overwrites `seal_number` while incrementing the open-seal count again — the retention seal is a new seal on the record, and the ledger holds both entries in `sequence_index` order."

    Design: Difficulty/compensating_invariant/ci_open_seal_count_conservation_across_deploy_break_seal_and_retention
    """
    scenario = _two_precinct_two_unit_world(client)
    _walk_through_deployment(scenario)
    _close_the_polls(scenario)
    fx.reconcile(scenario, BASIS_FINAL_CANVASS)
    _retain_both_seals(scenario)

    first_events = _unit_events(scenario, scenario.tabulator_ids[0])
    assert asserts.event_types(first_events) == [
        EVENT_SEAL_APPLIED,
        EVENT_SEAL_BROKEN,
        EVENT_SEAL_APPLIED,
        EVENT_RETURN,
        EVENT_RETENTION_SEAL,
    ]
    assert [event["sequence_index"] for event in first_events] == [1, 2, 3, 4, 5]
    asserts.assert_custody_event(first_events[1], EVENT_SEAL_BROKEN,
                                 subject_type=SUBJECT_TABULATOR_UNIT,
                                 from_state=CUSTODY_DEPLOYED,
                                 to_state=CUSTODY_IN_VAULT,
                                 seal_number=SEAL_TAB_1,
                                 actor_user_id=USER_CUSTODIAN)
    asserts.assert_custody_event(first_events[4], EVENT_RETENTION_SEAL,
                                 subject_type=SUBJECT_TABULATOR_UNIT,
                                 from_state=CUSTODY_RETURNED,
                                 to_state=CUSTODY_SEALED_RETENTION,
                                 seal_number=SEAL_RETENTION_1)

    second_events = _unit_events(scenario, scenario.tabulator_ids[1])
    assert asserts.event_types(second_events) == [
        EVENT_SEAL_APPLIED,
        EVENT_RETURN,
        EVENT_RETENTION_SEAL,
    ]
    assert [event["sequence_index"] for event in second_events] == [1, 2, 3]
    _assert_open_seals(scenario, 4)


# ---- The committed print total: written twice, released once, back to zero ----

SECOND_WINDOW_START = "2026-08-14T08:00:00Z"
SECOND_WINDOW_END = "2026-08-16T08:00:00Z"
THIRD_WINDOW_START = "2026-08-20T08:00:00Z"
THIRD_WINDOW_END = "2026-08-22T08:00:00Z"
WITHDRAWAL_REASON = "Court order removed the contest from the ballot"


def _job_placed(client: BallotProductionApiClient) -> fx.Scenario:
    """A locked election with one secure vendor and one 12500-ballot order placed."""
    scenario = fx.styles_locked(client)
    fx.add_vendor(scenario)
    fx.add_print_job(scenario)
    return scenario


def _second_order(scenario: fx.Scenario) -> str:
    """Place a second, never-approved order for the same style in a later window."""
    return fx.add_print_job(scenario, press_window_start=SECOND_WINDOW_START,
                            press_window_end=SECOND_WINDOW_END)


def _withdraw_the_contest(scenario: fx.Scenario) -> dict:
    """Withdraw the election's only certified contest."""
    return validate_success(
        scenario.client.withdraw_contest(scenario.contest_id,
                                         f.withdraw_payload(WITHDRAWAL_REASON),
                                         users.DIRECTOR))


def test_ci_an_unapproved_order_commits_nothing_to_the_print_ledger(client):
    """A second order sitting on the vendor's desk leaves the committed total untouched.

    PRD Section 3.6: "A created job starts in `PROOF_PENDING`, copies `election_id` from the referenced style, pins `style_version_at_creation` to the style's `version` as observed and accepted, and begins with `sample_size` 0, `defect_count` 0, `defect_rate_bp` 0, `inspection_count` 0, `delivered_quantity` 0, `approved_by_user_id` null, `invoice_basis` null and all four invoice money fields at 0."

    Design: Difficulty/compensating_invariant/ci_committed_print_cents_released_on_job_rejection
    """
    scenario = fx.issued_lot(client)
    assert scenario.read_election()["committed_print_cents"] == FINAL_TOTAL_CENTS

    second_job_id = _second_order(scenario)
    job = scenario.read_job(second_job_id)
    asserts.assert_fields_equal(
        job,
        {
            "status": JOB_PROOF_PENDING,
            "invoice_basis": None,
            "invoice_subtotal_cents": 0,
            "defect_credit_cents": 0,
            "freight_cents": 0,
            "invoice_total_cents": 0,
            "delivered_quantity": 0,
            "approved_by_user_id": None,
        },
        "second, unapproved order",
    )
    assert scenario.read_election()["committed_print_cents"] == FINAL_TOTAL_CENTS
    vendor = validate_success(
        scenario.client.get_print_vendor(scenario.vendor_id, users.DIRECTOR))
    assert vendor["active_job_count"] == 2


def test_ci_approving_the_press_proof_commits_the_estimate_total(client):
    """The first ledger write is the whole estimate: 105625 of paper plus 45000 of freight.

    PRD Section 3.6: "On success `approved_by_user_id` records the approving `X-User-ID`, `invoice_basis` is set to `ESTIMATE`, the estimate invoice is written, and the election's `committed_print_cents` increases by the job's new `invoice_total_cents`."

    Design: Difficulty/compensating_invariant/ci_committed_print_cents_released_on_job_rejection
    """
    scenario = _job_placed(client)
    assert scenario.read_election()["committed_print_cents"] == 0

    job = fx.printed_job(scenario)
    asserts.assert_fields_equal(
        job,
        {
            "invoice_basis": INVOICE_ESTIMATE,
            "invoice_subtotal_cents": SUBTOTAL_CENTS,
            "defect_credit_cents": 0,
            "freight_cents": FREIGHT_TIER_1_CENTS,
            "invoice_total_cents": ESTIMATE_TOTAL_CENTS,
            "delivered_quantity": 0,
        },
        "estimate invoice",
    )
    assert scenario.read_election()["committed_print_cents"] == ESTIMATE_TOTAL_CENTS


def test_ci_delivery_adjusts_the_committed_total_by_the_difference_only(client):
    """The delivery rewrites the invoice, so the ledger falls by 1268 rather than adding again.

    PRD Section 3.6: "Finally the election's `committed_print_cents` is adjusted by the difference between the new final total and the estimate total the job had previously contributed."

    Design: Difficulty/compensating_invariant/ci_committed_print_cents_released_on_job_rejection
    """
    scenario = _job_placed(client)
    fx.printed_job(scenario)
    assert scenario.read_election()["committed_print_cents"] == ESTIMATE_TOTAL_CENTS

    fx.inspect_job(scenario)
    assert scenario.read_job()["defect_rate_bp"] == DEFECT_RATE_BP

    job = fx.deliver_job(scenario)
    asserts.assert_fields_equal(
        job,
        {
            "invoice_basis": INVOICE_FINAL,
            "invoice_subtotal_cents": SUBTOTAL_CENTS,
            "defect_credit_cents": DEFECT_CREDIT_CENTS,
            "freight_cents": FREIGHT_TIER_1_CENTS,
            "invoice_total_cents": FINAL_TOTAL_CENTS,
            "delivered_quantity": DELIVERED_QUANTITY,
        },
        "final invoice",
    )
    assert scenario.read_election()["committed_print_cents"] == FINAL_TOTAL_CENTS


def test_ci_the_withdrawal_releases_the_final_total_and_zeroes_the_ledger(client):
    """Both orders are rejected and the committed total returns to exactly zero.

    PRD Section 3.5: "Its press window is released, so its vendor's `active_job_count` is recomputed; `invoice_subtotal_cents`, `defect_credit_cents`, `freight_cents` and `invoice_total_cents` are all set to 0; and the election's `committed_print_cents` is reduced by exactly the amount that job had previously committed — the `ESTIMATE` total for a job that had only been approved, the `FINAL` total for a job that had already been delivered."

    Design: Difficulty/compensating_invariant/ci_committed_print_cents_released_on_job_rejection
    """
    scenario = fx.issued_lot(client)
    second_job_id = _second_order(scenario)

    contest = _withdraw_the_contest(scenario)
    asserts.assert_fields_equal(
        contest,
        {"status": CONTEST_WITHDRAWN, "ballot_order_index": None},
        "withdrawn contest",
    )
    assert scenario.read_election()["committed_print_cents"] == 0

    delivered_job = scenario.read_job()
    assert delivered_job["status"] == JOB_REJECTED
    asserts.assert_invoice_zeroed(delivered_job)

    unapproved_job = scenario.read_job(second_job_id)
    assert unapproved_job["status"] == JOB_REJECTED
    asserts.assert_invoice_zeroed(unapproved_job)


def test_ci_the_money_ledger_and_the_ballot_ledger_reverse_independently(client):
    """The invoice is zeroed and the paper voided, but the delivered quantity stands.

    PRD Section 2.10: "Second, the money ledger and the ballot ledger are reversed independently: a rejected print job's invoice is zeroed and the election's committed print total reduced accordingly, while its `delivered_quantity` remains as shipped, because the pallets physically arrived."

    Design: Difficulty/compensating_invariant/ci_committed_print_cents_released_on_job_rejection
    """
    scenario = fx.issued_lot(client)
    _second_order(scenario)
    _withdraw_the_contest(scenario)

    assert scenario.read_job()["delivered_quantity"] == DELIVERED_QUANTITY
    vendor = validate_success(
        scenario.client.get_print_vendor(scenario.vendor_id, users.DIRECTOR))
    assert vendor["active_job_count"] == 0

    lot = scenario.read_lot()
    asserts.assert_fields_equal(
        lot,
        {
            "custody_state": LOT_VOIDED,
            "issued_quantity": 0,
            "unused_quantity": RECEIVED_QUANTITY,
            "precinct_id": None,
            "issued_by_user_id": None,
        },
        "voided lot",
    )
    asserts.assert_lot_conservation(lot)

    asserts.assert_fields_equal(
        scenario.read_election(),
        {"total_ballots_issued": 0, "total_ballots_received": 0,
         "committed_print_cents": 0},
        "election after the release",
    )
    assert scenario.read_precinct()["ballots_received"] == 0


def test_ci_a_rejected_style_cannot_re_commit_the_released_cents(client):
    """A fresh order against the rejected style is refused, so the ledger stays at zero.

    PRD Section 3.6: "Guards fire in ascending rank: the vendor and the style must resolve, and a style of another election is `ERR_BALLOT_STYLE_NOT_FOUND`; the presented style version must be current, or `ERR_STALE_BALLOT_STYLE_VERSION`; the election must be in `CONTESTS_CERTIFIED` or `STYLES_LOCKED`; the style must be `APPROVED` or `LOCKED`, or `ERR_STYLE_STATE_INVALID`; the vendor must be `ACTIVE` **and** have `certified_secure` true, or `ERR_VENDOR_NOT_SECURE` — ballots are never printed outside a certified secure facility; the vendor's press capacity must accommodate the window; and the ordered quantity must cover the requirement."

    Design: Difficulty/compensating_invariant/ci_committed_print_cents_released_on_job_rejection
    """
    scenario = fx.issued_lot(client)
    _second_order(scenario)
    _withdraw_the_contest(scenario)

    style = scenario.read_style()
    assert style["status"] == STYLE_PROOF_REJECTED

    payload = f.print_job_payload(
        scenario.vendor_id, scenario.style_id, style["version"],
        press_window_start=THIRD_WINDOW_START, press_window_end=THIRD_WINDOW_END)
    validate_error(scenario.client.create_print_job(payload, users.COORDINATOR),
                   ERR_STYLE_STATE_INVALID)

    assert scenario.read_election()["committed_print_cents"] == 0
