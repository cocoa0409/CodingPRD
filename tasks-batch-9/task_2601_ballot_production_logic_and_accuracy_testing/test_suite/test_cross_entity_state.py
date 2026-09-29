"""Operations whose legality is decided by the state of rows other than the target.

Placing and approving a print order is judged against the ballot style's status and
its current revision, and deploying a tabulator is judged against the paper standing
at the precinct, the precinct's own style assignment and the election-wide seal
namespace. Each test here changes only those other rows and watches the same call
flip.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_errors import (
    ERR_LOT_STATE_INVALID,
    ERR_PROOF_VERSION_STALE,
    ERR_SEAL_NUMBER_DUPLICATE,
    ERR_STALE_BALLOT_STYLE_VERSION,
    ERR_STYLE_STATE_INVALID,
    ERR_UNIT_STATE_INVALID,
    ERR_UNIT_STYLE_MISMATCH,
)
from test_helpers.assertions import assert_custody_event, events_for_subject, find_by
from test_helpers.constants import (
    ASSET_TAG_1,
    ASSET_TAG_2,
    CUSTODY_DEPLOYED,
    CUSTODY_IN_VAULT,
    DISTRICT_D12,
    EVENT_SEAL_APPLIED,
    INVOICE_ESTIMATE,
    JOB_PRINTING,
    JOB_PROOF_PENDING,
    LOT_CODE_1,
    LOT_CODE_2,
    LOT_ISSUED,
    LOT_RECEIVED,
    PHASE_STYLES_LOCKED,
    POLLING_PLACE_2,
    PRECINCT_CODE_1,
    PRECINCT_CODE_2,
    READINESS_BLOCKED,
    READINESS_NOT_READY,
    READINESS_READY,
    SEAL_1,
    SEAL_2,
    SEAL_TAB_1,
    SESSION_START,
    STYLE_APPROVED,
    STYLE_CODE_ALT,
    STYLE_CODE_MAIN,
    STYLE_DRAFT,
    STYLE_LOCKED,
    SUBJECT_TABULATOR_UNIT,
    UNIT_LA_PASSED,
)

ESTIMATE_TOTAL_CENTS = 150625
SECOND_WINDOW_START = "2026-08-11T08:00:00Z"
SECOND_WINDOW_END = "2026-08-13T08:00:00Z"
FREE_WINDOW_START = "2026-08-14T08:00:00Z"
FREE_WINDOW_END = "2026-08-16T08:00:00Z"


def _approved_style_with_pending_order(client):
    """CONTESTS_CERTIFIED election: S-100 APPROVED and ordered, S-200 still DRAFT."""
    sc = fx.contests_certified(client)
    fx.add_style(sc, STYLE_CODE_ALT, [DISTRICT_D12])
    fx.certify_languages(sc, style_id=sc.style_ids[0])
    fx.approve_proof_cycle(sc, style_id=sc.style_ids[0])
    fx.assign_style(sc, precinct_id=sc.precinct_ids[0], style_id=sc.style_ids[0])
    fx.add_vendor(sc)
    fx.add_print_job(sc, style_id=sc.style_ids[0])
    return sc


def _order_payload(sc, style_id, expected_version, window_start, window_end):
    return f.print_job_payload(sc.vendor_id, style_id, expected_version,
                               quantity_ordered=12500,
                               press_window_start=window_start,
                               press_window_end=window_end)


# ---- A print order lives or dies by the ballot style beside it ----

def test_ce_order_against_a_draft_style_is_refused(client):
    """A flawless order payload is still refused while the style it names has not been proofed.

    PRD Section 3.6: "Guards fire in ascending rank: the vendor and the style must resolve, and a style of another election is `ERR_BALLOT_STYLE_NOT_FOUND`; the presented style version must be current, or `ERR_STALE_BALLOT_STYLE_VERSION`; the election must be in `CONTESTS_CERTIFIED` or `STYLES_LOCKED`; the style must be `APPROVED` or `LOCKED`, or `ERR_STYLE_STATE_INVALID`; the vendor must be `ACTIVE` **and** have `certified_secure` true, or `ERR_VENDOR_NOT_SECURE` — ballots are never printed outside a certified secure facility; the vendor's press capacity must accommodate the window; and the ordered quantity must cover the requirement."

    Design: Difficulty/cross_entity_state_dependency/ce_print_job_legality_depends_on_style_state_and_pinned_revision
    """
    sc = _approved_style_with_pending_order(client)
    draft_style_id = sc.style_ids[1]
    assert sc.read_style(draft_style_id)["status"] == STYLE_DRAFT

    validate_error(
        client.create_print_job(
            _order_payload(sc, draft_style_id, sc.style_version(draft_style_id),
                           FREE_WINDOW_START, FREE_WINDOW_END),
            users.COORDINATOR),
        ERR_STYLE_STATE_INVALID)

    rows, meta = validate_paginated(
        client.list_print_jobs(users.COORDINATOR, {"style_id": draft_style_id}))
    assert meta["total_count"] == 0
    assert rows == []
    assert validate_success(
        client.get_print_vendor(sc.vendor_id, users.DIRECTOR))["active_job_count"] == 1


def test_ce_locking_the_styles_strands_the_pinned_press_proof(client):
    """Locking the style bumps its revision, and the untouched order can no longer be approved.

    PRD Section 3.4: "Each such style then transitions `APPROVED → LOCKED` and has its `version` bumped. Styles that no precinct points at, and styles in `DRAFT`, `PROOFING` or `PROOF_REJECTED`, are left entirely untouched and their `version` does not move."

    PRD Section 3.6: "The job must be `PROOF_PENDING`, or `ERR_JOB_STATE_INVALID`; the election must be in `CONTESTS_CERTIFIED` or `STYLES_LOCKED`; the style must still be `APPROVED` or `LOCKED`, or `ERR_STYLE_STATE_INVALID`; the vendor must still be `ACTIVE` with `certified_secure` true, or `ERR_VENDOR_NOT_SECURE`; and the style's current `version` must still equal the job's pinned `style_version_at_creation`, or the approval fails with `ERR_PROOF_VERSION_STALE`, because the artwork moved after the job was placed and the proof on the vendor's press is no longer the artwork of record."

    Design: Difficulty/cross_entity_state_dependency/ce_print_job_legality_depends_on_style_state_and_pinned_revision
    """
    sc = _approved_style_with_pending_order(client)
    style_id = sc.style_ids[0]
    version_at_order = sc.style_version(style_id)
    assert sc.read_style(style_id)["status"] == STYLE_APPROVED

    validate_success(client.lock_styles(sc.election_id, users.DIRECTOR))

    assert sc.read_style(style_id)["status"] == STYLE_LOCKED
    assert sc.read_style(style_id)["version"] > version_at_order
    assert sc.read_style(sc.style_ids[1])["status"] == STYLE_DRAFT
    assert sc.read_election()["status"] == PHASE_STYLES_LOCKED

    validate_error(client.approve_press_proof(sc.job_id, users.DIRECTOR),
                   ERR_PROOF_VERSION_STALE)

    job = sc.read_job()
    assert job["status"] == JOB_PROOF_PENDING
    assert job["style_version_at_creation"] == version_at_order
    assert job["invoice_basis"] is None
    assert sc.read_election()["committed_print_cents"] == 0


def test_ce_reordering_with_the_pre_lock_revision_is_a_stale_version(client):
    """The same pre-lock revision number that stalls an approval is a concurrency failure on creation.

    PRD Section 2.8: "If it does not equal the style's current `version`, the order is rejected with `ERR_STALE_BALLOT_STYLE_VERSION` and HTTP 412."

    Design: Difficulty/cross_entity_state_dependency/ce_print_job_legality_depends_on_style_state_and_pinned_revision
    """
    sc = _approved_style_with_pending_order(client)
    style_id = sc.style_ids[0]
    version_at_order = sc.style_version(style_id)
    validate_success(client.lock_styles(sc.election_id, users.DIRECTOR))

    validate_error(
        client.create_print_job(
            _order_payload(sc, style_id, version_at_order,
                           SECOND_WINDOW_START, SECOND_WINDOW_END),
            users.COORDINATOR),
        ERR_STALE_BALLOT_STYLE_VERSION)

    rows, meta = validate_paginated(
        client.list_print_jobs(users.COORDINATOR, {"style_id": style_id}))
    assert meta["total_count"] == 1
    assert find_by(rows, "id", sc.job_id)["status"] == JOB_PROOF_PENDING


def test_ce_reordering_with_the_locked_revision_pins_the_new_number(client):
    """A re-order presenting the post-lock revision is accepted and pins that revision.

    PRD Section 3.6: "A created job starts in `PROOF_PENDING`, copies `election_id` from the referenced style, pins `style_version_at_creation` to the style's `version` as observed and accepted, and begins with `sample_size` 0, `defect_count` 0, `defect_rate_bp` 0, `inspection_count` 0, `delivered_quantity` 0, `approved_by_user_id` null, `invoice_basis` null and all four invoice money fields at 0."

    Design: Difficulty/cross_entity_state_dependency/ce_print_job_legality_depends_on_style_state_and_pinned_revision
    """
    sc = _approved_style_with_pending_order(client)
    style_id = sc.style_ids[0]
    validate_success(client.lock_styles(sc.election_id, users.DIRECTOR))
    locked_version = sc.style_version(style_id)

    job = validate_success(
        client.create_print_job(
            _order_payload(sc, style_id, locked_version,
                           SECOND_WINDOW_START, SECOND_WINDOW_END),
            users.COORDINATOR),
        expected_status=201)

    assert job["status"] == JOB_PROOF_PENDING
    assert job["style_version_at_creation"] == locked_version
    assert job["invoice_basis"] is None
    assert job["invoice_total_cents"] == 0
    assert validate_success(
        client.get_print_vendor(sc.vendor_id, users.DIRECTOR))["active_job_count"] == 2


def test_ce_approving_the_repinned_order_writes_the_estimate_invoice(client):
    """The re-pinned order approves cleanly and is the only one that reaches the money ledger.

    PRD Section 3.6: "On success `approved_by_user_id` records the approving `X-User-ID`, `invoice_basis` is set to `ESTIMATE`, the estimate invoice is written, and the election's `committed_print_cents` increases by the job's new `invoice_total_cents`."

    Design: Difficulty/cross_entity_state_dependency/ce_print_job_legality_depends_on_style_state_and_pinned_revision
    """
    sc = _approved_style_with_pending_order(client)
    style_id = sc.style_ids[0]
    validate_success(client.lock_styles(sc.election_id, users.DIRECTOR))
    locked_version = sc.style_version(style_id)
    second_job_id = fx.add_print_job(sc, style_id=style_id,
                                     press_window_start=SECOND_WINDOW_START,
                                     press_window_end=SECOND_WINDOW_END)
    validate_error(client.approve_press_proof(sc.job_ids[0], users.DIRECTOR),
                   ERR_PROOF_VERSION_STALE)

    job = validate_success(client.approve_press_proof(second_job_id, users.DIRECTOR))

    assert job["status"] == JOB_PRINTING
    assert job["invoice_basis"] == INVOICE_ESTIMATE
    assert job["invoice_total_cents"] == ESTIMATE_TOTAL_CENTS
    assert sc.read_election()["committed_print_cents"] == ESTIMATE_TOTAL_CENTS
    assert sc.read_style(style_id)["version"] == locked_version


# ---- A tabulator deploys only when the paper, the precinct and the seals agree ----

def _two_precinct_election_with_one_tested_unit(client):
    """STYLES_LOCKED election: P-001 holds S-100 paper, P-002 holds S-200 paper.

    TAB-001 is programmed for S-100 and has passed its public test; TAB-002 is
    programmed for the same style but has never been tested.
    """
    sc = fx.new_election(client)
    fx.add_contest(sc, district_code=DISTRICT_D12)
    fx.add_candidate(sc)
    fx.certify_contest(sc)
    fx.add_style(sc, STYLE_CODE_MAIN, [DISTRICT_D12])
    fx.add_style(sc, STYLE_CODE_ALT, [DISTRICT_D12])
    fx.add_precinct(sc, PRECINCT_CODE_1, [DISTRICT_D12], 100)
    fx.add_precinct(sc, PRECINCT_CODE_2, [DISTRICT_D12], 100,
                    polling_place=POLLING_PLACE_2)
    validate_success(client.certify_ballot_order(sc.election_id, users.DIRECTOR))
    for style_id in sc.style_ids:
        fx.certify_languages(sc, style_id=style_id)
        fx.approve_proof_cycle(sc, style_id=style_id)
    fx.assign_style(sc, precinct_id=sc.precinct_ids[0], style_id=sc.style_ids[0])
    fx.assign_style(sc, precinct_id=sc.precinct_ids[1], style_id=sc.style_ids[1])
    validate_success(client.lock_styles(sc.election_id, users.DIRECTOR))
    fx.add_vendor(sc)
    fx.add_print_job(sc, style_id=sc.style_ids[0])
    fx.printed_job(sc, job_id=sc.job_ids[0])
    fx.inspect_job(sc, job_id=sc.job_ids[0])
    fx.deliver_job(sc, lots=[f.manifest_line(LOT_CODE_1, 12500, SEAL_1)],
                   job_id=sc.job_ids[0])
    fx.add_print_job(sc, style_id=sc.style_ids[1],
                     press_window_start=SECOND_WINDOW_START,
                     press_window_end=SECOND_WINDOW_END)
    fx.printed_job(sc, job_id=sc.job_ids[1])
    fx.inspect_job(sc, job_id=sc.job_ids[1])
    fx.deliver_job(sc, lots=[f.manifest_line(LOT_CODE_2, 12500, SEAL_2)],
                   job_id=sc.job_ids[1])
    fx.receive_lot(sc, lot_id=sc.lot_ids[0], seal_number=SEAL_1, quantity_received=12500)
    fx.receive_lot(sc, lot_id=sc.lot_ids[1], seal_number=SEAL_2, quantity_received=12500)
    fx.issue_lot(sc, lot_id=sc.lot_ids[0], precinct_id=sc.precinct_ids[0],
                 issue_quantity=12500)
    fx.issue_lot(sc, lot_id=sc.lot_ids[1], precinct_id=sc.precinct_ids[1],
                 issue_quantity=12500)
    fx.add_tabulator(sc, asset_tag=ASSET_TAG_1)
    fx.add_tabulator(sc, asset_tag=ASSET_TAG_2)
    fx.program_unit(sc, tabulator_id=sc.tabulator_ids[0], style_id=sc.style_ids[0],
                    headers=users.TECHNICIAN)
    fx.program_unit(sc, tabulator_id=sc.tabulator_ids[1], style_id=sc.style_ids[0],
                    headers=users.TECHNICIAN)
    fx.add_test_deck(sc, style_id=sc.style_ids[0], deck_code="DECK-A")
    fx.schedule_session(sc, tabulator_id=sc.tabulator_ids[0], deck_id=sc.deck_ids[0],
                        headers=users.TECHNICIAN_2)
    fx.sign_in_observers(sc)
    fx.set_clock(client, SESSION_START)
    fx.start_session(sc, headers=users.TECHNICIAN_2)
    fx.record_matching_results(sc, headers=users.TECHNICIAN_2)
    assert sc.read_tabulator(sc.tabulator_ids[0])["program_status"] == UNIT_LA_PASSED
    return sc


def test_ce_deploy_to_a_precinct_holding_another_style_is_a_mismatch(client):
    """A tested unit is refused at a precinct whose assigned style is not the one it holds.

    PRD Section 3.8: "Its guards, in ascending rank, are: the unit must resolve, or `ERR_TABULATOR_NOT_FOUND`; the precinct must exist in the same election, or `ERR_PRECINCT_NOT_FOUND`; the unit's `program_status` must be `LA_PASSED` **and** its `custody_status` must be `IN_VAULT`, or `ERR_UNIT_STATE_INVALID` — an untested machine never leaves the vault; at least one ballot lot with that `precinct_id` must be in `ISSUED`, or `ERR_LOT_STATE_INVALID` — the machine does not travel ahead of the paper; the unit's `programmed_style_id` must equal the precinct's `assigned_style_id`, or `ERR_UNIT_STYLE_MISMATCH` — a machine programmed for one district combination cannot read another's ballots; and the `seal_number` must not already be held by any other ballot lot or tabulator of the election, or `ERR_SEAL_NUMBER_DUPLICATE`."

    Design: Difficulty/cross_entity_state_dependency/ce_tabulator_deploy_depends_on_lot_custody_and_precinct_style
    """
    sc = _two_precinct_election_with_one_tested_unit(client)
    assert sc.read_lot(sc.lot_ids[1])["custody_state"] == LOT_ISSUED

    validate_error(
        client.deploy_tabulator(
            sc.tabulator_ids[0],
            f.deploy_unit_payload(sc.precinct_ids[1], SEAL_TAB_1),
            users.CUSTODIAN),
        ERR_UNIT_STYLE_MISMATCH)

    assert sc.read_tabulator(sc.tabulator_ids[0])["custody_status"] == CUSTODY_IN_VAULT
    assert sc.read_election()["open_seal_count"] == 0


def test_ce_deploy_of_an_untested_unit_is_a_unit_state_failure(client):
    """The unit's own program axis is read before the paper and the style match.

    PRD Section 3.8: "Its guards, in ascending rank, are: the unit must resolve, or `ERR_TABULATOR_NOT_FOUND`; the precinct must exist in the same election, or `ERR_PRECINCT_NOT_FOUND`; the unit's `program_status` must be `LA_PASSED` **and** its `custody_status` must be `IN_VAULT`, or `ERR_UNIT_STATE_INVALID` — an untested machine never leaves the vault; at least one ballot lot with that `precinct_id` must be in `ISSUED`, or `ERR_LOT_STATE_INVALID` — the machine does not travel ahead of the paper; the unit's `programmed_style_id` must equal the precinct's `assigned_style_id`, or `ERR_UNIT_STYLE_MISMATCH` — a machine programmed for one district combination cannot read another's ballots; and the `seal_number` must not already be held by any other ballot lot or tabulator of the election, or `ERR_SEAL_NUMBER_DUPLICATE`."

    Design: Difficulty/cross_entity_state_dependency/ce_tabulator_deploy_depends_on_lot_custody_and_precinct_style
    """
    sc = _two_precinct_election_with_one_tested_unit(client)

    validate_error(
        client.deploy_tabulator(
            sc.tabulator_ids[1],
            f.deploy_unit_payload(sc.precinct_ids[0], SEAL_TAB_1),
            users.CUSTODIAN),
        ERR_UNIT_STATE_INVALID)

    assert sc.read_tabulator(sc.tabulator_ids[1])["custody_status"] == CUSTODY_IN_VAULT
    assert sc.read_precinct(sc.precinct_ids[0])["deployment_status"] == READINESS_NOT_READY


def test_ce_deploy_with_a_seal_already_on_a_lot_is_a_duplicate(client):
    """The seal namespace spans lots and units, so a pallet seal cannot be reused on a machine.

    PRD Section 2.11: "Seal numbers are unique within an election while they are open: writing a `seal_number` that some other ballot lot or tabulator of the same election already holds is rejected with `ERR_SEAL_NUMBER_DUPLICATE`."

    Design: Difficulty/cross_entity_state_dependency/ce_tabulator_deploy_depends_on_lot_custody_and_precinct_style
    """
    sc = _two_precinct_election_with_one_tested_unit(client)

    validate_error(
        client.deploy_tabulator(
            sc.tabulator_ids[0],
            f.deploy_unit_payload(sc.precinct_ids[0], SEAL_1),
            users.CUSTODIAN),
        ERR_SEAL_NUMBER_DUPLICATE)

    unit = sc.read_tabulator(sc.tabulator_ids[0])
    assert unit["custody_status"] == CUSTODY_IN_VAULT
    assert unit["seal_number"] is None
    assert sc.read_election()["open_seal_count"] == 0


def test_ce_recalling_the_precinct_paper_blocks_the_deploy(client):
    """Pulling the precinct's lot back to the warehouse makes the machine's deployment illegal.

    PRD Section 3.7: "Recall is the compensating action for issue, optionally carrying a `recall_reason`. The lot must be `ISSUED`; it moves `ISSUED → RECEIVED`, `issued_quantity` returns to 0, `unused_quantity` returns to the full `quantity_received`, `precinct_id` and `issued_by_user_id` are cleared to null, and a custody event of type `RECALL` is appended."

    Design: Difficulty/cross_entity_state_dependency/ce_tabulator_deploy_depends_on_lot_custody_and_precinct_style
    """
    sc = _two_precinct_election_with_one_tested_unit(client)

    lot = validate_success(client.recall_lot(sc.lot_ids[0], users.CUSTODIAN,
                                            f.recall_payload()))
    assert lot["custody_state"] == LOT_RECEIVED
    assert lot["issued_quantity"] == 0
    assert lot["unused_quantity"] == 12500
    assert lot["precinct_id"] is None
    assert sc.read_precinct(sc.precinct_ids[0])["ballots_received"] == 0

    validate_error(
        client.deploy_tabulator(
            sc.tabulator_ids[0],
            f.deploy_unit_payload(sc.precinct_ids[0], SEAL_TAB_1),
            users.CUSTODIAN),
        ERR_LOT_STATE_INVALID)

    assert sc.read_tabulator(sc.tabulator_ids[0])["program_status"] == UNIT_LA_PASSED
    assert sc.read_tabulator(sc.tabulator_ids[0])["custody_status"] == CUSTODY_IN_VAULT
    assert sc.read_election()["open_seal_count"] == 0


def test_ce_reissuing_the_paper_lets_the_identical_deploy_succeed(client):
    """The same deploy request that failed succeeds once the lot stands ISSUED at the precinct again.

    PRD Section 3.8: "On success the unit moves `IN_VAULT → DEPLOYED`, stores `precinct_id` and `seal_number`, appends a custody event of type `SEAL_APPLIED` with `from_state` `IN_VAULT` and `to_state` `DEPLOYED`, increments the election's `open_seal_count` by one, and re-derives the precinct's `deployment_status` and the election's `deployment_readiness`."

    Design: Difficulty/cross_entity_state_dependency/ce_tabulator_deploy_depends_on_lot_custody_and_precinct_style
    """
    sc = _two_precinct_election_with_one_tested_unit(client)
    validate_success(client.recall_lot(sc.lot_ids[0], users.CUSTODIAN, f.recall_payload()))
    validate_error(
        client.deploy_tabulator(
            sc.tabulator_ids[0],
            f.deploy_unit_payload(sc.precinct_ids[0], SEAL_TAB_1),
            users.CUSTODIAN),
        ERR_LOT_STATE_INVALID)
    lot = validate_success(
        client.issue_lot(sc.lot_ids[0],
                         f.issue_payload(sc.precinct_ids[0], 12500),
                         users.CUSTODIAN))
    assert lot["custody_state"] == LOT_ISSUED
    assert sc.read_precinct(sc.precinct_ids[0])["ballots_received"] == 12500

    unit = validate_success(
        client.deploy_tabulator(
            sc.tabulator_ids[0],
            f.deploy_unit_payload(sc.precinct_ids[0], SEAL_TAB_1),
            users.CUSTODIAN))

    assert unit["custody_status"] == CUSTODY_DEPLOYED
    assert unit["precinct_id"] == sc.precinct_ids[0]
    assert unit["seal_number"] == SEAL_TAB_1
    assert sc.read_election()["open_seal_count"] == 1
    seal_events = [event for event in events_for_subject(sc.custody_events(),
                                                        sc.tabulator_ids[0])
                   if event["event_type"] == EVENT_SEAL_APPLIED]
    assert len(seal_events) == 1
    assert_custody_event(seal_events[0], EVENT_SEAL_APPLIED,
                         subject_type=SUBJECT_TABULATOR_UNIT,
                         subject_id=sc.tabulator_ids[0],
                         from_state=CUSTODY_IN_VAULT, to_state=CUSTODY_DEPLOYED,
                         seal_number=SEAL_TAB_1)
    assert sc.read_precinct(sc.precinct_ids[0])["deployment_status"] == READINESS_READY
    assert sc.read_precinct(sc.precinct_ids[1])["deployment_status"] == READINESS_NOT_READY
    assert sc.read_election()["deployment_readiness"] == READINESS_BLOCKED
    assert sc.read_tabulator(sc.tabulator_ids[1])["custody_status"] == CUSTODY_IN_VAULT
