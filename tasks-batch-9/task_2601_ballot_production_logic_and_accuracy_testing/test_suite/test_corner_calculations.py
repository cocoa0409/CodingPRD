"""Numeric derivations of the ballot production service.

These tests pin the arithmetic the office is audited on: the printed order of
contests and candidates, the statutory 110 percent precinct ballot requirement,
the estimate invoice with its flat freight tiers, test-deck mark capacity, the
absolute-deviation discrepancy total of a public logic-and-accuracy test, the
ballots a precinct is credited with holding, and the ballot-accountability
worksheet when nothing is in scope at all.
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
from test_helpers.api_errors import (
    ERR_DECK_MARKS_EXCEED_CAPACITY,
    ERR_DECK_MARK_OFF_STYLE,
    ERR_DEPLOYMENT_NOT_READY,
    ERR_EMPTY_TEST_DECK,
)
from test_helpers.assertions import (
    assert_accountability_worksheet,
    find_by,
)
from test_helpers.constants import (
    ACCOUNTABILITY_BALANCED,
    ACCOUNTABILITY_PENDING,
    BASIS_FINAL_CANVASS,
    BASIS_PRELIMINARY,
    CANDIDATE_CERTIFIED,
    CONTEST_CERTIFIED,
    CONTEST_DRAFT,
    CONTEST_TYPE_CANDIDATE,
    CONTEST_TYPE_MEASURE,
    CONTEST_WITHDRAWN,
    CUSTODY_IN_VAULT,
    DECK_DRAFT,
    DECK_VOIDED,
    DISTRICT_D07,
    DISTRICT_D12,
    JOB_PRINTING,
    INVOICE_ESTIMATE,
    LOT_RECEIVED,
    PHASE_CONTESTS_CERTIFIED,
    PHASE_STYLES_LOCKED,
    READINESS_BLOCKED,
    READINESS_NOT_READY,
    SESSION_FAILED,
    SESSION_START,
    SPOILAGE_ALLOWANCE_SMALL_BP,
    TOLERANCE_SMALL_BP,
    UNIT_LA_FAILED,
)

ALVAREZ_FILING = "2026-06-01T09:00:00Z"
BROOKS_FILING = "2026-06-02T09:00:00Z"


def _three_contest_election(client: BallotProductionApiClient):
    """An election whose three certified contests were filed out of printed order."""
    sc = fx.new_election(client)
    measure = fx.add_contest(sc, title="Bond Measure A",
                             contest_type=CONTEST_TYPE_MEASURE,
                             district_code=DISTRICT_D07)
    sheriff = fx.add_contest(sc, title="County Sheriff",
                             contest_type=CONTEST_TYPE_CANDIDATE,
                             district_code=DISTRICT_D12)
    board = fx.add_contest(sc, title="Board of Supervisors",
                           contest_type=CONTEST_TYPE_CANDIDATE,
                           district_code=DISTRICT_D07)
    alvarez = fx.add_candidate(sc, contest_id=sheriff, full_name="Ana Alvarez",
                               ballot_name="Alvarez", filing_received_at=ALVAREZ_FILING)
    brooks = fx.add_candidate(sc, contest_id=board, full_name="Ben Brooks",
                              ballot_name="Brooks", filing_received_at=BROOKS_FILING)
    fx.certify_contest(sc, measure)
    fx.certify_contest(sc, sheriff)
    fx.certify_contest(sc, board)
    return sc, {"measure": measure, "sheriff": sheriff, "board": board,
                "alvarez": alvarez, "brooks": brooks}


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


# ---- The printed order of contests on the ballot face ----

def test_calc_contest_order_indices_follow_the_published_sort_not_creation_order(client):
    """Freezing the ballot order numbers the certified contests 1, 2, 3 by type then
    district then title, so the contest filed first ends up printed last.

    PRD Section 3.1: "Those certified contests are sorted by four keys in order: first by contest type, with `CANDIDATE` contests ahead of `MEASURE` contests; then by `district_code` ascending as a byte-wise string comparison; then by `title` ascending, likewise byte-wise; and finally by `created_at` ascending as the deterministic tiebreak."

    Design: Corner/calculations/calc_contest_ordering_assigns_contiguous_indices_in_published_sort_order
    """
    sc, ids = _three_contest_election(client)

    frozen = validate_success(sc.client.certify_ballot_order(sc.election_id, users.DIRECTOR))
    assert frozen["status"] == PHASE_CONTESTS_CERTIFIED
    assert frozen["certified_contest_count"] == 3

    board = validate_success(sc.client.get_contest(ids["board"], users.COORDINATOR))
    sheriff = validate_success(sc.client.get_contest(ids["sheriff"], users.COORDINATOR))
    measure = validate_success(sc.client.get_contest(ids["measure"], users.COORDINATOR))

    # CANDIDATE ahead of MEASURE, then D-07 ahead of D-12: Board 1, Sheriff 2, Measure 3.
    assert board["ballot_order_index"] == 1
    assert sheriff["ballot_order_index"] == 2
    assert measure["ballot_order_index"] == 3
    for contest in (board, sheriff, measure):
        assert contest["status"] == CONTEST_CERTIFIED
    assert sorted([board["ballot_order_index"], sheriff["ballot_order_index"],
                   measure["ballot_order_index"]]) == [1, 2, 3]


def test_calc_contest_order_assigns_zero_based_candidate_indices(client):
    """The same pass writes each certified candidate's zero-based rank within its own
    contest, so the sole candidate of a contest holds index 0.

    PRD Section 3.2: "Each candidate's `base_order_index` is its zero-based rank in that order."

    Design: Corner/calculations/calc_contest_ordering_assigns_contiguous_indices_in_published_sort_order
    """
    sc, ids = _three_contest_election(client)

    validate_success(sc.client.certify_ballot_order(sc.election_id, users.DIRECTOR))

    sheriff_rows, _ = validate_paginated(
        sc.client.list_candidates(ids["sheriff"], users.COORDINATOR))
    board_rows, _ = validate_paginated(
        sc.client.list_candidates(ids["board"], users.COORDINATOR))

    alvarez = find_by(sheriff_rows, "id", ids["alvarez"])
    brooks = find_by(board_rows, "id", ids["brooks"])
    assert alvarez["base_order_index"] == 0
    assert brooks["base_order_index"] == 0
    assert alvarez["status"] == CANDIDATE_CERTIFIED
    assert brooks["status"] == CANDIDATE_CERTIFIED


def test_calc_contest_order_excludes_a_draft_contest_from_the_index_set(client):
    """A draft contest that would sort ahead of every certified contest neither takes
    index 1 nor shifts the certified indices, and keeps a null index of its own.

    PRD Section 3.1: "The pass considers only contests of the election whose status is `CERTIFIED`; contests in `DRAFT` or `WITHDRAWN` are excluded and keep `ballot_order_index` null."

    Design: Corner/calculations/calc_contest_ordering_excludes_draft_and_withdrawn_contests
    """
    sc, ids = _three_contest_election(client)
    draft_id = fx.add_contest(sc, title="Aardvark Advisory Board",
                              contest_type=CONTEST_TYPE_CANDIDATE,
                              district_code="D-01")

    validate_success(sc.client.certify_ballot_order(sc.election_id, users.DIRECTOR))

    draft = validate_success(sc.client.get_contest(draft_id, users.COORDINATOR))
    assert draft["status"] == CONTEST_DRAFT
    assert draft["ballot_order_index"] is None

    rows, meta = validate_paginated(sc.client.list_contests(sc.election_id, users.COORDINATOR))
    assert meta["total_count"] == 4
    assert find_by(rows, "id", ids["board"])["ballot_order_index"] == 1
    assert find_by(rows, "id", ids["sheriff"])["ballot_order_index"] == 2
    assert find_by(rows, "id", ids["measure"])["ballot_order_index"] == 3


def test_calc_withdrawn_contest_leaves_a_permanent_gap_in_the_index_set(client):
    """Withdrawing the contest printed first clears its index to null and leaves the
    survivors on 2 and 3, so index 1 stays permanently vacant.

    PRD Section 3.1: "A contest withdrawn after the order was frozen has its `ballot_order_index` reset to null, and the surviving contests are **not** renumbered: the gap stays visible in the printed order of record, and every test deck already built against the affected styles is voided instead."

    Design: Corner/calculations/calc_contest_ordering_excludes_draft_and_withdrawn_contests
    """
    sc, ids = _three_contest_election(client)
    validate_success(sc.client.certify_ballot_order(sc.election_id, users.DIRECTOR))

    withdrawn = validate_success(
        sc.client.withdraw_contest(ids["board"],
                                   f.withdraw_payload("District boundary litigation"),
                                   users.DIRECTOR))
    assert withdrawn["status"] == CONTEST_WITHDRAWN
    assert withdrawn["ballot_order_index"] is None

    sheriff = validate_success(sc.client.get_contest(ids["sheriff"], users.COORDINATOR))
    measure = validate_success(sc.client.get_contest(ids["measure"], users.COORDINATOR))
    assert sheriff["ballot_order_index"] == 2
    assert measure["ballot_order_index"] == 3

    election = validate_success(sc.client.get_election(sc.election_id, users.DIRECTOR))
    assert election["certified_contest_count"] == 2


# ---- The statutory precinct ballot requirement ----

def test_calc_precinct_requirement_rounds_the_statutory_overage_up(client):
    """Each precinct's requirement is its registered voter count times 11 over 10 rounded
    up, so 1751 voters require 1927 ballots and a single voter requires 2.

    PRD Section 3.3: "Registration derives the precinct's statutory print requirement immediately: `required_ballot_quantity` is the registered voter count multiplied by 11 and divided by 10 — the statutory 110 percent floor — rounded **up** to the next whole ballot, so the floor is never undershot."

    Design: Corner/calculations/calc_precinct_requirement_ceiling_uses_declared_overage_constants
    """
    sc = fx.new_election(client)

    def register(precinct_code, registered_voter_count, polling_place):
        return validate_success(
            sc.client.create_precinct(
                sc.election_id,
                f.precinct_payload(precinct_code, [DISTRICT_D12],
                                   registered_voter_count, polling_place),
                users.COORDINATOR),
            expected_status=201)

    big = register("P-101", 1751, "Northside Armory")
    one = register("P-102", 1, "Lighthouse Keeper Cottage")
    ten = register("P-103", 10, "Riverside Depot")
    five = register("P-104", 5, "Old Schoolhouse")

    assert big["required_ballot_quantity"] == 1927
    assert one["required_ballot_quantity"] == 2
    assert ten["required_ballot_quantity"] == 11
    assert five["required_ballot_quantity"] == 6

    for precinct in (big, one, ten, five):
        assert precinct["ballots_received"] == 0
        assert precinct["deployment_status"] == READINESS_NOT_READY


# ---- The estimate invoice, its per-thousand rate and its flat freight tiers ----

def test_calc_estimate_invoice_freight_tier_boundary_and_per_thousand_rounding(client):
    """An order of exactly 50000 ballots stays in the first freight tier at 45000 cents
    while 50001 pays the whole second-tier fee of 90000 cents, and the odd quantity's
    subtotal rounds half up to 422508 cents.

    PRD Section 3.6: "A billing quantity of 50 000 ballots or fewer carries 45 000 cents; a billing quantity above 50 000 but no more than 200 000 carries 90 000 cents; anything above 200 000 carries 150 000 cents."

    Design: Corner/calculations/calc_freight_tier_boundary_and_per_thousand_rounding
    """
    sc = fx.styles_locked(client)
    fx.add_vendor(sc)

    job_a = validate_success(
        sc.client.create_print_job(
            f.print_job_payload(sc.vendor_id, sc.style_id, sc.style_version(),
                                quantity_ordered=50000,
                                press_window_start="2026-08-10T08:00:00Z",
                                press_window_end="2026-08-12T08:00:00Z"),
            users.COORDINATOR),
        expected_status=201)
    invoice_a = validate_success(
        sc.client.approve_press_proof(job_a["id"], users.DIRECTOR))

    # 50000 * 8450 / 1000 = 422500 exactly; 50000 is the top of the first freight tier.
    assert invoice_a["invoice_subtotal_cents"] == 422500
    assert invoice_a["freight_cents"] == 45000
    assert invoice_a["defect_credit_cents"] == 0
    assert invoice_a["invoice_total_cents"] == 467500
    assert invoice_a["invoice_basis"] == INVOICE_ESTIMATE
    assert invoice_a["delivered_quantity"] == 0
    assert invoice_a["status"] == JOB_PRINTING

    job_b = validate_success(
        sc.client.create_print_job(
            f.print_job_payload(sc.vendor_id, sc.style_id, sc.style_version(),
                                quantity_ordered=50001,
                                press_window_start="2026-08-13T08:00:00Z",
                                press_window_end="2026-08-15T08:00:00Z"),
            users.COORDINATOR),
        expected_status=201)
    invoice_b = validate_success(
        sc.client.approve_press_proof(job_b["id"], users.DIRECTOR))

    # 50001 * 8450 / 1000 = 422508.45, which rounds half up to 422508 whole cents.
    assert invoice_b["invoice_subtotal_cents"] == 422508
    assert invoice_b["freight_cents"] == 90000
    assert invoice_b["defect_credit_cents"] == 0
    assert invoice_b["invoice_total_cents"] == 512508
    assert invoice_b["invoice_basis"] == INVOICE_ESTIMATE
    assert invoice_b["delivered_quantity"] == 0
    assert invoice_b["status"] == JOB_PRINTING

    election = validate_success(sc.client.get_election(sc.election_id, users.DIRECTOR))
    assert election["committed_print_cents"] == 980008

    vendor = validate_success(sc.client.get_print_vendor(sc.vendor_id, users.DIRECTOR))
    assert vendor["active_job_count"] == 2


# ---- The accountability worksheet when no paper is in scope ----

def test_calc_accountability_with_no_lots_is_vacuously_balanced_on_both_bases(client):
    """With no ballot lots at all every worksheet figure is 0, the tier lookups still
    report 25 and 200 basis points, and the verdict is BALANCED on either basis.

    PRD Section 3.9: "Reconciling an election with nothing in scope is vacuously balanced: every figure is 0, and 0 is within a tolerance of 0."

    Design: Corner/calculations/calc_accountability_zero_lots_is_vacuously_balanced
    """
    sc = fx.new_election(client)
    fx.add_precinct(sc, registered_voter_count=100)

    preliminary = validate_success(
        sc.client.get_accountability(sc.election_id, users.DIRECTOR,
                                     f.accountability_params(BASIS_PRELIMINARY)))
    assert_accountability_worksheet(preliminary, {
        "basis": BASIS_PRELIMINARY,
        "lot_count": 0,
        "gross_issued": 0,
        "allowance_bp": SPOILAGE_ALLOWANCE_SMALL_BP,
        "spoilage_credit": 0,
        "net_issued": 0,
        "accounted": 0,
        "gross_variance": 0,
        "net_variance": 0,
        "tolerance_bp": TOLERANCE_SMALL_BP,
        "tolerance_ballots": 0,
        "ballot_accountability_status": ACCOUNTABILITY_BALANCED,
    })

    final = validate_success(
        sc.client.get_accountability(sc.election_id, users.DIRECTOR,
                                     f.accountability_params(BASIS_FINAL_CANVASS)))
    assert_accountability_worksheet(final, {
        "basis": BASIS_FINAL_CANVASS,
        "lot_count": 0,
        "gross_issued": 0,
        "allowance_bp": SPOILAGE_ALLOWANCE_SMALL_BP,
        "spoilage_credit": 0,
        "net_issued": 0,
        "accounted": 0,
        "gross_variance": 0,
        "net_variance": 0,
        "tolerance_bp": TOLERANCE_SMALL_BP,
        "tolerance_ballots": 0,
        "ballot_accountability_status": ACCOUNTABILITY_BALANCED,
    })


def test_calc_accountability_read_defaults_to_preliminary_and_writes_nothing(client):
    """Omitting the basis reads the PRELIMINARY worksheet, any role may read it, and the
    read leaves the election's own stored accountability verdict at PENDING.

    PRD Section 3.9: "Its `basis` query parameter is optional and defaults to `PRELIMINARY`, the in-field view; an unrecognised basis is `ERR_INVALID_REQUEST`."

    Design: Corner/calculations/calc_accountability_zero_lots_is_vacuously_balanced
    """
    sc = fx.new_election(client)
    fx.add_precinct(sc, registered_voter_count=100)

    defaulted = validate_success(
        sc.client.get_accountability(sc.election_id, users.OBSERVER,
                                     f.accountability_params(None)))
    assert defaulted["basis"] == BASIS_PRELIMINARY
    assert defaulted["lot_count"] == 0
    assert defaulted["ballot_accountability_status"] == ACCOUNTABILITY_BALANCED

    election = validate_success(sc.client.get_election(sc.election_id, users.DIRECTOR))
    assert election["ballot_accountability_status"] == ACCOUNTABILITY_PENDING
    assert election["reconciliation_basis"] is None
    assert election["last_reconciled_at"] is None
    assert election["net_ballot_variance"] == 0
    assert election["total_ballots_issued"] == 0


# ---- The absolute-deviation discrepancy total of a public accuracy test ----

def _failing_la_session(client: BallotProductionApiClient):
    """Run a public test whose reported tallies are right in total but wrong per name."""
    sc, alvarez, brooks = _two_candidate_locked_election(client)
    fx.add_tabulator(sc)
    fx.program_unit(sc)
    deck_id = fx.add_test_deck(
        sc, ballot_count=2, blank_count=2, overvote_count=1,
        expected_marks=[f.expected_mark(sc.contest_id, alvarez, 20),
                        f.expected_mark(sc.contest_id, brooks, 20)])
    fx.schedule_session(sc)
    fx.sign_in_observers(sc)
    fx.set_clock(client, SESSION_START)
    fx.start_session(sc)
    recorded = validate_success(
        sc.client.record_results(
            sc.session_id,
            f.record_results_payload(
                [f.reported_mark(sc.contest_id, alvarez, 23),
                 f.reported_mark(sc.contest_id, brooks, 17)],
                reported_blank_count=2, reported_overvote_count=1),
            users.TECHNICIAN_2))
    return sc, deck_id, recorded


def test_calc_la_discrepancy_sums_offsetting_deltas_instead_of_cancelling_them(client):
    """A machine reporting 23 and 17 against an expected 20 and 20 scores a discrepancy
    of 6 and fails, even though its grand total of 40 marks is exactly right.

    PRD Section 3.8: "Two offsetting errors do **not** cancel — one candidate over by 3 and another under by 3 gives 6, not 0, because absolute values are summed before totalling."

    Design: Corner/calculations/calc_la_discrepancy_sums_absolute_offsetting_deltas
    """
    sc, deck_id, recorded = _failing_la_session(client)

    # abs(23 - 20) + abs(17 - 20) + abs(2 - 2) + abs(1 - 1) == 3 + 3 + 0 + 0.
    assert recorded["discrepancy_count"] == 6
    assert recorded["status"] == SESSION_FAILED
    assert recorded["reported_blank_count"] == 2
    assert recorded["reported_overvote_count"] == 1
    assert len(recorded["reported_marks"]) == 2
    assert recorded["completed_at"] is not None

    deck = find_by(validate_paginated(
        sc.client.list_test_decks(sc.style_id, users.TECHNICIAN))[0], "id", deck_id)
    assert deck["expected_total_marks"] == 40


def test_calc_la_discrepancy_of_six_drives_the_whole_failure_cascade(client):
    """The discrepancy of 6 voids the deck, demotes the tabulator to LA_FAILED in the
    vault, and leaves the election blocked with no seal ever broken.

    PRD Section 3.8: "Hop 1: the session moves `IN_PROGRESS → FAILED` and the deck moves `SEALED → VOIDED` — the deck must be rebuilt before the unit can be tested again."

    Design: Corner/calculations/calc_la_discrepancy_sums_absolute_offsetting_deltas
    """
    sc, deck_id, recorded = _failing_la_session(client)
    assert recorded["discrepancy_count"] == 6

    deck = find_by(validate_paginated(
        sc.client.list_test_decks(sc.style_id, users.TECHNICIAN))[0], "id", deck_id)
    assert deck["status"] == DECK_VOIDED
    assert deck["expected_total_marks"] == 40

    unit = validate_success(sc.client.get_tabulator(sc.tabulator_id, users.TECHNICIAN))
    assert unit["program_status"] == UNIT_LA_FAILED
    assert unit["custody_status"] == CUSTODY_IN_VAULT
    assert unit["precinct_id"] is None

    election = validate_success(sc.client.get_election(sc.election_id, users.DIRECTOR))
    assert election["deployment_readiness"] == READINESS_BLOCKED
    assert election["open_seal_count"] == 0

    precinct = validate_success(sc.client.get_precinct(sc.precinct_id, users.CUSTODIAN))
    assert precinct["deployment_status"] == READINESS_NOT_READY


# ---- Test-deck mark capacity and the printable-pair rule ----

def test_calc_test_deck_rejects_zero_ballots_off_style_marks_and_forty_one_marks(client):
    """A zero-ballot deck, a deck marking a disqualified name, and a one-ballot deck
    declaring 41 marks are each refused, and none of them leaves a row behind.

    PRD Section 3.8: "`ballot_count` below 1 is refused with `ERR_EMPTY_TEST_DECK`."

    Design: Corner/calculations/calc_test_deck_capacity_and_off_style_marks_rejected
    """
    sc, alvarez, brooks = _two_candidate_locked_election(client)
    validate_success(
        sc.client.disqualify_candidate(brooks, f.disqualify_payload("Withdrew from the race"),
                                       users.DIRECTOR))

    validate_error(
        sc.client.create_test_deck(
            sc.style_id,
            f.test_deck_payload([], deck_code="DECK-EMPTY", ballot_count=0,
                                blank_count=0, overvote_count=0),
            users.TECHNICIAN),
        ERR_EMPTY_TEST_DECK)

    validate_error(
        sc.client.create_test_deck(
            sc.style_id,
            f.test_deck_payload([f.expected_mark(sc.contest_id, brooks, 5)],
                                deck_code="DECK-OFF", ballot_count=1,
                                blank_count=0, overvote_count=0),
            users.TECHNICIAN),
        ERR_DECK_MARK_OFF_STYLE)

    validate_error(
        sc.client.create_test_deck(
            sc.style_id,
            f.test_deck_payload([f.expected_mark(sc.contest_id, alvarez, 41)],
                                deck_code="DECK-41", ballot_count=1,
                                blank_count=0, overvote_count=0),
            users.TECHNICIAN),
        ERR_DECK_MARKS_EXCEED_CAPACITY)

    rows, meta = validate_paginated(sc.client.list_test_decks(sc.style_id, users.TECHNICIAN))
    assert meta["total_count"] == 0
    assert rows == []


def test_calc_test_deck_accepts_exactly_forty_marks_on_one_ballot(client):
    """One ballot carries exactly 40 mark lines, so a deck declaring 40 marks is created
    as a draft with 7 blanks and 3 overvotes charged against nothing.

    PRD Section 3.8: "The comparison is strict: a one-ballot deck declaring exactly 40 marks is accepted, and 41 is refused."

    Design: Corner/calculations/calc_test_deck_capacity_and_off_style_marks_rejected
    """
    sc, alvarez, brooks = _two_candidate_locked_election(client)
    validate_success(
        sc.client.disqualify_candidate(brooks, f.disqualify_payload("Withdrew from the race"),
                                       users.DIRECTOR))

    deck = validate_success(
        sc.client.create_test_deck(
            sc.style_id,
            f.test_deck_payload([f.expected_mark(sc.contest_id, alvarez, 40)],
                                deck_code="DECK-40", ballot_count=1,
                                blank_count=7, overvote_count=3),
            users.TECHNICIAN),
        expected_status=201)

    assert deck["expected_total_marks"] == 40
    assert deck["status"] == DECK_DRAFT
    assert deck["ballot_count"] == 1
    assert deck["blank_count"] == 7
    assert deck["overvote_count"] == 3

    rows, meta = validate_paginated(sc.client.list_test_decks(sc.style_id, users.TECHNICIAN))
    assert meta["total_count"] == 1
    assert find_by(rows, "id", deck["id"])["expected_total_marks"] == 40


# ---- An election with no polling places at all ----

def test_calc_zero_precinct_election_locks_its_styles_vacuously(client):
    """With no precincts both lock-styles preconditions quantify over an empty set, so
    the election reaches STYLES_LOCKED while its readiness stays BLOCKED.

    PRD Section 3.4: "Two preconditions apply: every precinct of the election must carry an `assigned_style_id`, or the request fails with `ERR_ELECTION_PHASE_INVALID`; and every style that some precinct points at must be `APPROVED`, or the request fails with `ERR_STYLE_STATE_INVALID`."

    Design: Corner/calculations/calc_zero_precinct_election_is_lockable_but_never_deployable
    """
    sc = fx.new_election(client)
    fx.add_contest(sc)
    fx.add_candidate(sc, full_name="Ana Alvarez", ballot_name="Alvarez",
                     filing_received_at=ALVAREZ_FILING)
    fx.certify_contest(sc)

    certified = validate_success(
        sc.client.certify_ballot_order(sc.election_id, users.DIRECTOR))
    assert certified["status"] == PHASE_CONTESTS_CERTIFIED
    assert certified["deployment_readiness"] == READINESS_BLOCKED

    locked = validate_success(sc.client.lock_styles(sc.election_id, users.DIRECTOR))
    assert locked["status"] == PHASE_STYLES_LOCKED
    assert locked["deployment_readiness"] == READINESS_BLOCKED


def test_calc_zero_precinct_election_is_never_deployable(client):
    """The empty precinct set is deliberately not a satisfied conjunction for readiness,
    so deploying a locked election with no polling places is refused.

    PRD Section 3.9: "An election with zero precincts is `BLOCKED`, not `READY` — the empty conjunction is deliberately not treated as satisfied, because an election with no polling places is not prepared."

    Design: Corner/calculations/calc_zero_precinct_election_is_lockable_but_never_deployable
    """
    sc = fx.new_election(client)
    fx.add_contest(sc)
    fx.add_candidate(sc, full_name="Ana Alvarez", ballot_name="Alvarez",
                     filing_received_at=ALVAREZ_FILING)
    fx.certify_contest(sc)
    validate_success(sc.client.certify_ballot_order(sc.election_id, users.DIRECTOR))
    validate_success(sc.client.lock_styles(sc.election_id, users.DIRECTOR))

    validate_error(sc.client.deploy_election(sc.election_id, users.DIRECTOR),
                   ERR_DEPLOYMENT_NOT_READY)

    election = validate_success(sc.client.get_election(sc.election_id, users.DIRECTOR))
    assert election["status"] == PHASE_STYLES_LOCKED
    assert election["deployment_readiness"] == READINESS_BLOCKED


# ---- The ballots a precinct is credited with holding ----

def test_calc_precinct_ballots_received_ignores_paper_still_in_the_warehouse(client):
    """A received lot of 12500 in the warehouse credits the precinct with 0 ballots, and
    issuing 109 of the 110 required leaves it one ballot short.

    PRD Section 3.3: "A precinct's `ballots_received` is the sum of the issued quantities of the ballot lots currently pointing at it whose custody state is `ISSUED` or `RETURNED`."

    Design: Corner/calculations/calc_precinct_ballots_received_excludes_warehouse_lots
    """
    sc = fx.delivered_lot(client, registered_voter_count=100)
    fx.receive_lot(sc)

    in_warehouse = validate_success(
        sc.client.get_precinct(sc.precinct_id, users.CUSTODIAN))
    assert in_warehouse["required_ballot_quantity"] == 110
    assert in_warehouse["ballots_received"] == 0
    assert in_warehouse["deployment_status"] == READINESS_NOT_READY

    validate_success(
        sc.client.issue_lot(sc.lot_id, f.issue_payload(sc.precinct_id, 109),
                            users.CUSTODIAN))
    one_short = validate_success(sc.client.get_precinct(sc.precinct_id, users.CUSTODIAN))
    assert one_short["ballots_received"] == 109
    assert one_short["deployment_status"] == READINESS_NOT_READY


def test_calc_precinct_ballots_received_falls_back_to_zero_after_a_recall(client):
    """Recalling an issued lot drops the precinct's credit back to 0, and re-issuing the
    full 110 satisfies the inclusive paper clause while readiness still needs a machine.

    PRD Section 3.5: "The lot must be `ISSUED`; it moves `ISSUED → RECEIVED`, `issued_quantity` returns to 0, `unused_quantity` returns to the full `quantity_received`, `precinct_id` and `issued_by_user_id` are cleared to null, and a custody event of type `RECALL` is appended."

    Design: Corner/calculations/calc_precinct_ballots_received_excludes_warehouse_lots
    """
    sc = fx.delivered_lot(client, registered_voter_count=100)
    fx.receive_lot(sc)
    validate_success(
        sc.client.issue_lot(sc.lot_id, f.issue_payload(sc.precinct_id, 109),
                            users.CUSTODIAN))

    recalled = validate_success(
        sc.client.recall_lot(sc.lot_id, users.CUSTODIAN,
                             f.recall_payload("Miscount at the loading dock")))
    assert recalled["custody_state"] == LOT_RECEIVED
    assert recalled["issued_quantity"] == 0
    assert recalled["precinct_id"] is None
    assert validate_success(
        sc.client.get_precinct(sc.precinct_id, users.CUSTODIAN))["ballots_received"] == 0

    validate_success(
        sc.client.issue_lot(sc.lot_id, f.issue_payload(sc.precinct_id, 110),
                            users.CUSTODIAN))
    at_requirement = validate_success(
        sc.client.get_precinct(sc.precinct_id, users.CUSTODIAN))
    assert at_requirement["ballots_received"] == 110
    assert at_requirement["deployment_status"] == READINESS_NOT_READY

    election = validate_success(sc.client.get_election(sc.election_id, users.DIRECTOR))
    assert election["total_ballots_issued"] == 110
    assert election["deployment_readiness"] == READINESS_BLOCKED
