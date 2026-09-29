"""Guard ordering and the shape of rejection on the ballot production service.

Every test in this file puts a request in a state where more than one rule is
genuinely broken at the same time, proves which rejection the service is
obliged to answer with, and then repairs that one violation so the next rule
down becomes observable. The families covered are the reconciliation
concurrency guard against the final-canvass completeness rule, the payload
schema gate against path existence, path existence against payload foreign
keys, authentication against authorization, the fiscal floor on a print order,
the secure-facility rule on a print vendor, seal verification at warehouse
receipt, the ceiling on a lot's return accounting, the retention seal's
dependence on a reconciled election, and the observer minimum that varies with
the kind of logic-and-accuracy session being opened.
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
    ERR_BALLOT_STYLE_NOT_FOUND,
    ERR_ELECTION_NOT_FOUND,
    ERR_INSUFFICIENT_OBSERVERS,
    ERR_INVALID_REQUEST,
    ERR_LOTS_NOT_RETURNED,
    ERR_LOT_ACCOUNTING_EXCEEDS_RECEIPT,
    ERR_LOT_STATE_INVALID,
    ERR_PRECINCT_NOT_FOUND,
    ERR_QUANTITY_BELOW_REQUIREMENT,
    ERR_RETENTION_BEFORE_RECONCILIATION,
    ERR_SEAL_MISMATCH,
    ERR_SEAL_NUMBER_DUPLICATE,
    ERR_STALE_ELECTION_VERSION,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    ERR_VENDOR_NOT_SECURE,
)
from test_helpers.assertions import assert_custody_event, assert_iso_timestamp, find_by
from test_helpers.constants import (
    BASIS_FINAL_CANVASS,
    BASIS_PRELIMINARY,
    CONTEST_DRAFT,
    CUSTODY_RETURNED,
    CUSTODY_SEALED_RETENTION,
    DECK_DRAFT,
    DECK_SEALED,
    EVENT_RECEIPT,
    EVENT_RETENTION_SEAL,
    FREIGHT_TIER_1_CENTS,
    INVOICE_ESTIMATE,
    JOB_PROOF_PENDING,
    LOT_CODE_1,
    LOT_CODE_2,
    LOT_CODE_3,
    LOT_ISSUED,
    LOT_IN_TRANSIT,
    LOT_RECEIVED,
    LOT_RETURNED,
    MIN_PUBLIC_OBSERVERS,
    PHASE_RECONCILED,
    READINESS_NOT_READY,
    SEAL_1,
    SEAL_2,
    SEAL_3,
    SEAL_RETENTION_1,
    SESSION_IN_PROGRESS,
    SESSION_PASSED,
    SESSION_SCHEDULED,
    SESSION_START,
    STYLE_CODE_ALT,
    SUBJECT_BALLOT_LOT,
    SUBJECT_TABULATOR_UNIT,
    UNIT_LA_PASSED,
    USER_TECH_2,
    VENDOR_SUSPENDED,
)

# Literals this file needs that the shared constants module does not carry: the
# audit flavour of a logic-and-accuracy session, its observer floor, the evening
# window that audit session occupies, and two syntactically valid identifiers
# that belong to no stored row.
SESSION_TYPE_AUDIT = "POST_ELECTION_AUDIT"
MIN_AUDIT_OBSERVERS = 1
AUDIT_SESSION_START = "2026-09-01T20:00:00Z"
AUDIT_SESSION_END = "2026-09-01T22:00:00Z"
ABSENT_ID_A = "00000000-0000-0000-0000-0000000000ff"
ABSENT_ID_B = "00000000-0000-0000-0000-0000000000fe"


# ---- The reconciliation version guard against the final-canvass completeness rule ----

def test_val_stale_election_version_outranks_final_canvass_completeness(client):
    """A stale expected_election_version is answered before the final-canvass
    completeness rule, and refreshing it exposes the still-issued lot.

    PRD Section 3.9: "Guards run in ascending rank: schema first, then existence, then the version check answering `ERR_STALE_ELECTION_VERSION`, then the phase check, and finally, only for a `FINAL_CANVASS` request, the completeness check: if any ballot lot of the election is still in `ISSUED`, the reconciliation is refused with `ERR_LOTS_NOT_RETURNED`."

    Design: Corner/validations/val_stale_election_version_beats_lots_not_returned_returns_412
    """
    sc = fixtures.polls_closed_election(client)
    captured_version = sc.election_version()

    # A preliminary reconciliation is legal with paper still in the field, and
    # it bumps the election version the client is holding.
    preliminary = validate_success(
        client.reconcile(sc.election_id,
                         f.reconcile_payload(BASIS_PRELIMINARY, captured_version),
                         users.DIRECTOR))
    assert preliminary["status"] == PHASE_RECONCILED
    assert preliminary["reconciliation_basis"] == BASIS_PRELIMINARY
    assert preliminary["version"] == captured_version + 1

    # The lot is still ISSUED, so a FINAL_CANVASS request breaks two rules at
    # once: the version it presents is one behind, and paper is in the field.
    assert sc.read_lot()["custody_state"] == LOT_ISSUED
    stale = client.reconcile(sc.election_id,
                             f.reconcile_payload(BASIS_FINAL_CANVASS, captured_version),
                             users.DIRECTOR)
    validate_error(stale, ERR_STALE_ELECTION_VERSION, expected_status=412)

    # The rejected call wrote nothing: the stored basis and version stand.
    midpoint = sc.read_election()
    assert midpoint["version"] == captured_version + 1
    assert midpoint["reconciliation_basis"] == BASIS_PRELIMINARY

    # Repairing only the version exposes the business rule underneath it.
    completeness = client.reconcile(
        sc.election_id,
        f.reconcile_payload(BASIS_FINAL_CANVASS, midpoint["version"]),
        users.DIRECTOR)
    validate_error(completeness, ERR_LOTS_NOT_RETURNED, expected_status=409)

    after = sc.read_election()
    assert after["reconciliation_basis"] == BASIS_PRELIMINARY
    assert after["version"] == captured_version + 1
    assert sc.read_lot()["custody_state"] == LOT_ISSUED


# ---- A malformed body is answered before the addressed election is looked up ----

def test_val_schema_fault_outranks_missing_election_on_contest_filing(client):
    """Three different schema faults answer before the path election id is
    resolved, and only a clean body reaches the not-found gate.

    PRD Section 2.6: "The returned `error_id` is always the one belonging to the lowest-numbered rank below; ranks are evaluated in ascending order and the first violated rank decides the response."

    Design: Corner/validations/val_schema_check_precedes_path_existence_returns_invalid_request
    """
    sc = fixtures.new_election(client)
    absent_path = f"/elections/{ABSENT_ID_A}/contests"

    missing_title = f.contest_payload()
    del missing_title["title"]
    validate_error(
        client.raw("POST", absent_path, missing_title, users.COORDINATOR),
        ERR_INVALID_REQUEST, expected_status=400)

    below_minimum = f.contest_payload(seats_open=0)
    validate_error(
        client.raw("POST", absent_path, below_minimum, users.COORDINATOR),
        ERR_INVALID_REQUEST, expected_status=400)

    unknown_enum = f.contest_payload(contest_type="REFERENDUM")
    validate_error(
        client.raw("POST", absent_path, unknown_enum, users.COORDINATOR),
        ERR_INVALID_REQUEST, expected_status=400)

    # With the body repaired, the same unresolvable election id now reports.
    validate_error(
        client.raw("POST", absent_path, f.contest_payload(), users.COORDINATOR),
        ERR_ELECTION_NOT_FOUND, expected_status=404)

    # The same clean body against the election that does exist is accepted.
    filed = validate_success(
        client.create_contest(sc.election_id, f.contest_payload(), users.COORDINATOR),
        expected_status=201)
    assert filed["status"] == CONTEST_DRAFT
    assert filed["rotation_required"] is False
    assert filed["ballot_order_index"] is None
    assert sc.read_election()["certified_contest_count"] == 0

    rows, meta = validate_paginated(
        client.list_contests(sc.election_id, users.DIRECTOR, {"limit": 100}))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [filed["id"]]


# ---- The precinct in the path is resolved before the style id in the body ----

def test_val_precinct_path_id_outranks_payload_style_id(client):
    """When neither the addressed precinct nor the referenced style resolves, the
    path identifier is the one reported.

    PRD Section 2.7: "Rank 50 extends the same discipline to foreign keys carried inside a payload, on six operations: assigning a style to a precinct, placing a print order, issuing a lot to a precinct, programming a tabulator, deploying a tabulator and scheduling a logic-and-accuracy session."

    Design: Corner/validations/val_path_existence_precedes_referenced_existence_returns_not_found
    """
    sc = fixtures.contests_certified(client)
    fixtures.certify_languages(sc)
    fixtures.approve_proof_cycle(sc)

    # Both identifiers are unresolvable; the path one answers.
    both_absent = client.assign_style(ABSENT_ID_A,
                                      f.assign_style_payload(ABSENT_ID_B),
                                      users.COORDINATOR)
    validate_error(both_absent, ERR_PRECINCT_NOT_FOUND, expected_status=404)

    # With a real precinct in the path, the payload foreign key finally reports.
    style_absent = client.assign_style(sc.precinct_id,
                                       f.assign_style_payload(ABSENT_ID_B),
                                       users.COORDINATOR)
    validate_error(style_absent, ERR_BALLOT_STYLE_NOT_FOUND, expected_status=404)

    # Neither rejection wrote the foreign key.
    before = sc.read_precinct()
    assert before["assigned_style_id"] is None
    assert before["deployment_status"] == READINESS_NOT_READY

    assigned = validate_success(
        client.assign_style(sc.precinct_id,
                            f.assign_style_payload(sc.style_id),
                            users.COORDINATOR))
    assert assigned["assigned_style_id"] == sc.style_id
    assert assigned["deployment_status"] == READINESS_NOT_READY


def test_val_cross_election_style_reference_reports_not_found(client):
    """A style that exists but belongs to another election is reported as absent
    rather than as a mismatch.

    PRD Section 2.7: "A payload foreign key that does not resolve, **or that resolves to a row belonging to a different election than the addressed resource**, is reported as that entity's not-found error rather than as a business error — a deliberate choice, so that one election's rows are never disclosed through the error channel of another."

    Design: Corner/validations/val_path_existence_precedes_referenced_existence_returns_not_found
    """
    sc = fixtures.contests_certified(client)
    fixtures.certify_languages(sc)
    fixtures.approve_proof_cycle(sc)

    # A second, unrelated election owns a style of its own.
    other = fixtures.new_election(client, name="March 2027 Special",
                                  election_date="2027-03-02T00:00:00Z")
    foreign_style = fixtures.add_style(other, style_code=STYLE_CODE_ALT)
    assert foreign_style != sc.style_id

    leaked = client.assign_style(sc.precinct_id,
                                f.assign_style_payload(foreign_style),
                                users.COORDINATOR)
    validate_error(leaked, ERR_BALLOT_STYLE_NOT_FOUND, expected_status=404)
    assert sc.read_precinct()["assigned_style_id"] is None

    assigned = validate_success(
        client.assign_style(sc.precinct_id,
                            f.assign_style_payload(sc.style_id),
                            users.COORDINATOR))
    assert assigned["assigned_style_id"] == sc.style_id


# ---- The role header is examined before the body and before the path ----

def test_val_missing_or_unknown_role_outranks_schema_and_path_gates(client):
    """An absent role header and an unrecognised role string are both
    authentication failures, reported ahead of the schema and path gates.

    PRD Section 2.1: "If the role header is absent, empty, or does not name one of the seven roles below, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/val_authentication_precedes_authorization_returns_unauthenticated
    """
    sc = fixtures.new_election(client)

    # No role header at all, on a request that is otherwise perfectly legal.
    validate_error(
        client.raw("POST", f"/elections/{sc.election_id}/contests",
                   f.contest_payload(), users.headers_without_role()),
        ERR_UNAUTHENTICATED, expected_status=401)

    # The same missing header wins over a malformed body addressed to an
    # election that does not exist.
    broken = f.contest_payload(contest_type="REFERENDUM", seats_open=0)
    del broken["title"]
    validate_error(
        client.raw("POST", f"/elections/{ABSENT_ID_A}/contests", broken,
                   users.headers_without_role()),
        ERR_UNAUTHENTICATED, expected_status=401)

    # A role string outside the seven declared roles is the same fault.
    validate_error(
        client.raw("POST", f"/elections/{sc.election_id}/contests",
                   f.contest_payload(),
                   users.headers_with_unknown_role(role="BallotAuditor")),
        ERR_UNAUTHENTICATED, expected_status=401)

    # Nothing was written by any of the three rejections.
    rows, meta = validate_paginated(
        client.list_contests(sc.election_id, users.DIRECTOR, {"limit": 100}))
    assert meta["total_count"] == 0
    assert rows == []


def test_val_declared_role_reaches_the_authorization_gate(client):
    """A header naming a declared role authenticates and is then measured
    against the endpoint's own roles list.

    PRD Section 2.1: "If it names a recognized role that the target operation does not admit, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/validations/val_authentication_precedes_authorization_returns_unauthenticated
    """
    sc = fixtures.new_election(client)

    refused = client.create_contest(sc.election_id, f.contest_payload(),
                                    users.OBSERVER)
    validate_error(refused, ERR_UNAUTHORIZED, expected_status=403)

    filed = validate_success(
        client.create_contest(sc.election_id, f.contest_payload(),
                              users.COORDINATOR),
        expected_status=201)
    assert filed["status"] == CONTEST_DRAFT

    rows, meta = validate_paginated(
        client.list_contests(sc.election_id, users.DIRECTOR, {"limit": 100}))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [filed["id"]]


# ---- The fiscal floor on a print order is the precinct requirement ----

def test_val_order_quantity_floor_is_precinct_requirement_not_voter_count(client):
    """An order one ballot below the assigned precincts' statutory requirement is
    refused, and the boundary quantity itself is accepted.

    PRD Section 3.6: "The quantity rule is fiscal and sits at the very end of the order: `quantity_ordered` must be at least the sum of `required_ballot_quantity` across every precinct whose `assigned_style_id` is the ordered style, or the order is refused with `ERR_QUANTITY_BELOW_REQUIREMENT`."

    Design: Corner/validations/val_print_quantity_below_precinct_requirement_returns_409_then_passes
    """
    sc = fixtures.styles_locked(client)
    vendor_id = fixtures.add_vendor(sc)
    style_version = sc.style_version()

    # 100 registered voters carry a 110-ballot statutory requirement.
    assert sc.read_precinct()["required_ballot_quantity"] == 110

    short = client.create_print_job(
        f.print_job_payload(vendor_id, sc.style_id, style_version,
                            quantity_ordered=109),
        users.COORDINATOR)
    validate_error(short, ERR_QUANTITY_BELOW_REQUIREMENT, expected_status=409)

    # No job row, so no vendor-side counter moved.
    assert validate_success(
        client.get_print_vendor(vendor_id, users.DIRECTOR))["active_job_count"] == 0
    _, empty_meta = validate_paginated(
        client.list_print_jobs(users.DIRECTOR, {"limit": 100}))
    assert empty_meta["total_count"] == 0

    placed = validate_success(
        client.create_print_job(
            f.print_job_payload(vendor_id, sc.style_id, style_version,
                                quantity_ordered=110),
            users.COORDINATOR),
        expected_status=201)
    assert placed["status"] == JOB_PROOF_PENDING
    assert placed["invoice_basis"] is None
    assert placed["style_version_at_creation"] == style_version
    assert placed["quantity_ordered"] == 110
    assert placed["delivered_quantity"] == 0
    assert placed["invoice_total_cents"] == 0

    # Placing an order commits no money (PRD section 3.6).
    assert sc.read_election()["committed_print_cents"] == 0

    # The estimate invoice: 110 * 8450 / 1000 == 929.5, rounded half up to 930,
    # plus the first freight tier for a billing quantity of 110 ballots.
    approved = validate_success(
        client.approve_press_proof(placed["id"], users.DIRECTOR))
    assert approved["invoice_basis"] == INVOICE_ESTIMATE
    assert approved["invoice_subtotal_cents"] == 930
    assert approved["freight_cents"] == FREIGHT_TIER_1_CENTS
    assert approved["defect_credit_cents"] == 0
    assert approved["invoice_total_cents"] == 45930
    assert approved["delivered_quantity"] == 0

    assert sc.read_election()["committed_print_cents"] == 45930
    assert validate_success(
        client.get_print_vendor(vendor_id, users.DIRECTOR))["active_job_count"] == 1


# ---- Two vendor fields collapse onto one refusal ----

def test_val_insecure_and_suspended_vendors_share_one_error_id(client):
    """An uncertified facility and a suspended one refuse the identical order
    with the same error, and only a certified active vendor accepts it.

    PRD Section 3.6: "Guards fire in ascending rank: the vendor and the style must resolve, and a style of another election is `ERR_BALLOT_STYLE_NOT_FOUND`; the presented style version must be current, or `ERR_STALE_BALLOT_STYLE_VERSION`; the election must be in `CONTESTS_CERTIFIED` or `STYLES_LOCKED`; the style must be `APPROVED` or `LOCKED`, or `ERR_STYLE_STATE_INVALID`; the vendor must be `ACTIVE` **and** have `certified_secure` true, or `ERR_VENDOR_NOT_SECURE` — ballots are never printed outside a certified secure facility; the vendor's press capacity must accommodate the window; and the ordered quantity must cover the requirement."

    Design: Corner/validations/val_insecure_or_suspended_vendor_rejected_then_secure_vendor_passes
    """
    sc = fixtures.styles_locked(client)
    style_version = sc.style_version()

    insecure = validate_success(
        client.create_print_vendor(
            f.print_vendor_payload("Backlot Copy Shop", certified_secure=False),
            users.DIRECTOR),
        expected_status=201)
    suspended = validate_success(
        client.create_print_vendor(
            f.print_vendor_payload("Halted Secure Press", status=VENDOR_SUSPENDED),
            users.DIRECTOR),
        expected_status=201)
    secure = validate_success(
        client.create_print_vendor(f.print_vendor_payload(), users.DIRECTOR),
        expected_status=201)

    # An uncertified facility disqualifies itself on certified_secure alone.
    validate_error(
        client.create_print_job(
            f.print_job_payload(insecure["id"], sc.style_id, style_version),
            users.COORDINATOR),
        ERR_VENDOR_NOT_SECURE, expected_status=409)

    # A certified but suspended facility answers with the very same error id.
    validate_error(
        client.create_print_job(
            f.print_job_payload(suspended["id"], sc.style_id, style_version),
            users.COORDINATOR),
        ERR_VENDOR_NOT_SECURE, expected_status=409)

    accepted = validate_success(
        client.create_print_job(
            f.print_job_payload(secure["id"], sc.style_id, style_version),
            users.COORDINATOR),
        expected_status=201)
    assert accepted["status"] == JOB_PROOF_PENDING
    assert accepted["vendor_id"] == secure["id"]

    assert validate_success(
        client.get_print_vendor(insecure["id"], users.DIRECTOR))["active_job_count"] == 0
    assert validate_success(
        client.get_print_vendor(secure["id"], users.DIRECTOR))["active_job_count"] == 1

    rows, meta = validate_paginated(
        client.list_print_jobs(users.DIRECTOR,
                               {"vendor_id": suspended["id"], "limit": 100}))
    assert meta["total_count"] == 0
    assert rows == []


# ---- Receipt checks the seal, and only the seal ----

def test_val_receipt_seal_mismatch_precedes_a_short_count_receipt(client):
    """A pallet presented under the wrong seal is refused, while a counted
    receipt 100 ballots short of the manifest is accepted as data.

    PRD Section 3.7: "Receipt verifies the seal. The lot must be `IN_TRANSIT`, or `ERR_LOT_STATE_INVALID`; the payload's `seal_number` must equal the `seal_number` the vendor declared for that lot in the manifest, or the receipt is refused with `ERR_SEAL_MISMATCH` — the seal on the pallet is not the seal that was shipped; and `quantity_received` must be at least 1."

    Design: Corner/validations/val_seal_mismatch_at_receipt_rejected_then_shortage_receipt_passes
    """
    sc = fixtures.delivered_lot(client)

    wrong_seal = client.receive_lot(sc.lot_id,
                                    f.receive_payload("SEAL-9999", 12500),
                                    users.CUSTODIAN)
    validate_error(wrong_seal, ERR_SEAL_MISMATCH, expected_status=409)

    untouched = sc.read_lot()
    assert untouched["custody_state"] == LOT_IN_TRANSIT
    assert untouched["quantity_received"] == 0

    # The right seal with a short count: the shortage is recorded, not rejected.
    received = validate_success(
        client.receive_lot(sc.lot_id, f.receive_payload(SEAL_1, 12400),
                           users.CUSTODIAN))
    assert received["custody_state"] == LOT_RECEIVED
    assert received["quantity_received"] == 12400
    assert received["unused_quantity"] == 12400
    assert received["quantity_shipped"] == 12500

    assert sc.read_election()["total_ballots_received"] == 12400

    rows, meta = validate_paginated(
        client.list_custody_events(sc.election_id, users.CUSTODIAN,
                                   {"subject_id": sc.lot_id,
                                    "event_type": EVENT_RECEIPT,
                                    "limit": 100}))
    assert meta["total_count"] == 1
    assert_custody_event(rows[0], EVENT_RECEIPT,
                         subject_type=SUBJECT_BALLOT_LOT,
                         subject_id=sc.lot_id,
                         from_state=LOT_IN_TRANSIT,
                         to_state=LOT_RECEIVED,
                         seal_number=SEAL_1)


# ---- A three-lot election taken all the way to the deployed phase ----

def _three_lot_deployed_election(client):
    """Build a deployed election whose three lots were received in full and
    issued at 3000, 2000 and 1 ballots, and return it with its lot ids by code.

    Every step runs through a declared endpoint; the split manifest exists so a
    lot's own accounting can be exercised against a receipt smaller than the
    election's total.
    """
    manifest = [
        f.manifest_line(LOT_CODE_1, 4001, SEAL_1),
        f.manifest_line(LOT_CODE_2, 4001, SEAL_2),
        f.manifest_line(LOT_CODE_3, 4498, SEAL_3),
    ]
    sc = fixtures.delivered_lot(client, lots=manifest)
    lots = {row["lot_code"]: row["id"] for row in sc.lots_of_job()}
    assert sorted(lots) == [LOT_CODE_1, LOT_CODE_2, LOT_CODE_3]

    fixtures.receive_lot(sc, lots[LOT_CODE_1], SEAL_1, 4001)
    fixtures.issue_lot(sc, lots[LOT_CODE_1], issue_quantity=3000)
    fixtures.receive_lot(sc, lots[LOT_CODE_2], SEAL_2, 4001)
    fixtures.issue_lot(sc, lots[LOT_CODE_2], issue_quantity=2000)
    fixtures.receive_lot(sc, lots[LOT_CODE_3], SEAL_3, 4498)
    fixtures.issue_lot(sc, lots[LOT_CODE_3], issue_quantity=1)

    fixtures.add_tabulator(sc)
    fixtures.program_unit(sc)
    fixtures.add_test_deck(sc)
    fixtures.schedule_session(sc)
    fixtures.sign_in_observers(sc)
    fixtures.set_clock(client, SESSION_START)
    fixtures.start_session(sc)
    fixtures.record_matching_results(sc)
    fixtures.deploy_unit(sc)
    validate_success(client.deploy_election(sc.election_id, users.DIRECTOR))
    return sc, lots


# ---- The ceiling on a return is the counted receipt, not the issue ----

def test_val_return_accounting_ceiling_is_the_counted_receipt(client):
    """Return counts are measured against the lot's receipt, so a total above the
    receipt is refused while one far above the issue is accepted.

    PRD Section 3.7: "Their sum may not exceed the lot's `quantity_received`, or the return is refused with `ERR_LOT_ACCOUNTING_EXCEEDS_RECEIPT`."

    Design: Corner/validations/val_lot_accounting_ceiling_is_receipt_not_issue_returns_409
    """
    sc, lots = _three_lot_deployed_election(client)
    lot_id = lots[LOT_CODE_1]

    # 4000 + 1 + 1 == 4002, one ballot above the 4001 that was counted in.
    over = client.return_counts(lot_id,
                                f.return_counts_payload(4000, 1, 1),
                                users.CUSTODIAN)
    validate_error(over, ERR_LOT_ACCOUNTING_EXCEEDS_RECEIPT, expected_status=409)

    rejected = sc.read_lot(lot_id)
    assert rejected["custody_state"] == LOT_ISSUED
    assert rejected["accounted_quantity"] == 0
    assert rejected["issued_quantity"] == 3000

    # 4000 + 1 + 0 == 4001 is exactly the receipt, the inclusive boundary, even
    # though only 3000 ballots were ever issued.
    returned = validate_success(
        client.return_counts(lot_id, f.return_counts_payload(4000, 1, 0),
                             users.CUSTODIAN))
    assert returned["custody_state"] == LOT_RETURNED
    assert returned["accounted_quantity"] == 4001
    assert returned["lot_variance"] == -1001

    # The accounting line cannot be revised once filed: the state gate answers
    # before the fiscal one would.
    revision = client.return_counts(lot_id,
                                    f.return_counts_payload(10, 0, 0),
                                    users.CUSTODIAN)
    validate_error(revision, ERR_LOT_STATE_INVALID, expected_status=409)

    assert sc.read_election()["total_ballots_issued"] == 5001


# ---- The retention seal waits for the reconciliation, then for a free seal ----

def test_val_retention_seal_waits_for_reconciliation_then_seal_uniqueness(client):
    """A returned unit cannot be sealed for retention until its election is
    reconciled, and then only under a seal no lot of that election holds.

    PRD Section 3.9: "This operation is not phase-gated in the ordinary way; instead it carries its own explicit gate, and the guards run in this order: the unit must resolve; its `custody_status` must be `RETURNED`, or `ERR_UNIT_STATE_INVALID`; the election's `status` must be `RECONCILED`, or `ERR_RETENTION_BEFORE_RECONCILIATION` — records are not sealed away before the count they document has been reconciled; and the seal must be unique across the election's lots and tabulators, or `ERR_SEAL_NUMBER_DUPLICATE`."

    Design: Corner/validations/val_retention_seal_requires_reconciled_election_returns_409
    """
    sc, lots = _three_lot_deployed_election(client)
    fixtures.return_lot_counts(sc, lots[LOT_CODE_1], 2900, 30, 20)
    fixtures.return_lot_counts(sc, lots[LOT_CODE_2], 1880, 25, 34)
    validate_success(client.close_polls(sc.election_id, users.DIRECTOR))

    # The unit came home sealed, so it is state-eligible for retention.
    assert sc.read_tabulator()["custody_status"] == CUSTODY_RETURNED

    early = client.seal_retention(
        sc.tabulator_id, f.seal_retention_payload(SEAL_RETENTION_1, 730),
        users.CUSTODIAN)
    validate_error(early, ERR_RETENTION_BEFORE_RECONCILIATION, expected_status=409)
    assert sc.read_tabulator()["retention_until"] is None

    # The last lot reports, so the final canvass becomes available.
    fixtures.return_lot_counts(sc, lots[LOT_CODE_3], 1, 0, 0)
    closed_out = fixtures.reconcile(sc, BASIS_FINAL_CANVASS)
    assert closed_out["status"] == PHASE_RECONCILED
    assert closed_out["reconciliation_basis"] == BASIS_FINAL_CANVASS

    # A seal a ballot lot of the same election already holds is refused: the
    # uniqueness domain spans lots and units together.
    taken = client.seal_retention(sc.tabulator_id,
                                  f.seal_retention_payload(SEAL_1, 730),
                                  users.CUSTODIAN)
    validate_error(taken, ERR_SEAL_NUMBER_DUPLICATE, expected_status=409)

    sealed = validate_success(
        client.seal_retention(sc.tabulator_id,
                              f.seal_retention_payload(SEAL_RETENTION_1, 730),
                              users.CUSTODIAN))
    assert sealed["custody_status"] == CUSTODY_SEALED_RETENTION
    assert sealed["seal_number"] == SEAL_RETENTION_1
    # The window runs from the election date, 2026-11-03, plus 730 days, and not
    # from the logical clock, which still stands at the session instant.
    assert_iso_timestamp(sealed["retention_until"], "retention_until")
    assert sealed["retention_until"].startswith("2028-11-02")

    # The polling-place seal was never counted out at poll close, and the
    # retention seal adds one more.
    assert sc.read_election()["open_seal_count"] == 2

    rows, meta = validate_paginated(
        client.list_custody_events(sc.election_id, users.CUSTODIAN,
                                   {"subject_id": sc.tabulator_id,
                                    "event_type": EVENT_RETENTION_SEAL,
                                    "limit": 100}))
    assert meta["total_count"] == 1
    assert_custody_event(rows[0], EVENT_RETENTION_SEAL,
                         subject_type=SUBJECT_TABULATOR_UNIT,
                         subject_id=sc.tabulator_id,
                         to_state=CUSTODY_SEALED_RETENTION,
                         seal_number=SEAL_RETENTION_1)


# ---- The observer floor is chosen by the kind of session being opened ----

def test_val_observer_minimum_follows_the_session_type(client):
    """One observer is too few to open a public test and enough to open a
    post-election audit on the very same machine.

    PRD Section 3.8: "`observer_count` must meet the minimum for the session type, or `ERR_INSUFFICIENT_OBSERVERS` (rank 110): at least 2 for a `PRE_ELECTION_PUBLIC` session, at least 1 for a `POST_ELECTION_AUDIT`."

    Design: Corner/validations/val_observer_minimum_is_conditional_on_session_type
    """
    sc = fixtures.styles_locked(client)
    fixtures.add_tabulator(sc)
    fixtures.program_unit(sc)
    deck_public = fixtures.add_test_deck(sc, deck_code="DECK-A")
    deck_audit = fixtures.add_test_deck(sc, deck_code="DECK-B")

    public_session = fixtures.schedule_session(sc, deck_id=deck_public)
    audit_session = fixtures.schedule_session(
        sc, deck_id=deck_audit,
        scheduled_start=AUDIT_SESSION_START,
        scheduled_end=AUDIT_SESSION_END,
        session_type=SESSION_TYPE_AUDIT)
    fixtures.sign_in_observers(sc, public_session, ["Obs One"])
    fixtures.sign_in_observers(sc, audit_session, ["Aud One"])

    fixtures.set_clock(client, SESSION_START)

    # One observer is below the public minimum of two.
    short = client.start_session(public_session, users.TECHNICIAN_2)
    validate_error(short, ERR_INSUFFICIENT_OBSERVERS, expected_status=409)

    blocked = sc.read_session(public_session)
    assert blocked["status"] == SESSION_SCHEDULED
    assert blocked["started_at"] is None
    assert blocked["observer_count"] == 1
    decks, _ = validate_paginated(
        client.list_test_decks(sc.style_id, users.TECHNICIAN, {"limit": 100}))
    assert find_by(decks, "id", deck_public)["status"] == DECK_DRAFT

    admitted = validate_success(
        client.add_observer(public_session, f.observer_payload("Obs Two"),
                            users.OBSERVER))
    assert admitted["observer_count"] == MIN_PUBLIC_OBSERVERS
    assert admitted["observer_names"] == ["Obs One", "Obs Two"]

    opened = validate_success(client.start_session(public_session, users.TECHNICIAN_2))
    assert opened["status"] == SESSION_IN_PROGRESS
    assert opened["conducted_by_user_id"] == USER_TECH_2
    assert_iso_timestamp(opened["started_at"], "started_at")
    assert opened["started_at"].startswith("2026-09-01T14:00:00")
    decks, _ = validate_paginated(
        client.list_test_decks(sc.style_id, users.TECHNICIAN, {"limit": 100}))
    assert find_by(decks, "id", deck_public)["status"] == DECK_SEALED

    finished = fixtures.record_matching_results(sc, public_session)
    assert finished["status"] == SESSION_PASSED
    assert finished["discrepancy_count"] == 0

    # The identical observer count opens the audit session.
    fixtures.set_clock(client, AUDIT_SESSION_START)
    audit_opened = validate_success(client.start_session(audit_session, users.TECHNICIAN_2))
    assert audit_opened["status"] == SESSION_IN_PROGRESS
    assert audit_opened["observer_count"] == MIN_AUDIT_OBSERVERS
    assert audit_opened["session_type"] == SESSION_TYPE_AUDIT

    unit = sc.read_tabulator()
    assert unit["program_status"] == UNIT_LA_PASSED
    assert unit["la_session_count"] == 2
