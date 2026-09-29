"""Endpoint-shaped behaviour of the ballot production service.

These tests exercise the endpoints whose contract is easy to get subtly wrong:
the delivery manifest that fans one call out into several ballot lots and
rebills the job on the final basis, the computed layout read and its optional
basis parameter, the append-only observer roster of a logic-and-accuracy
session, the seal-breaking call that is legal in exactly one custody state, and
the filtered ballot-lot listing.
"""

from typing import Any, Dict, List

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
from test_helpers.assertions import assert_printed_positions


# ─── Private setup helpers (this file only) ──────────────────────────────────

def _qc_passed_job(client, quantity_ordered: int = 12500) -> fx.Scenario:
    """A locked election with one print job on press that passed its inspection.

    The sample of 500 with 6 defects puts the cumulative defect rate at 120
    basis points, below the hold threshold, so the job reaches QC_PASSED with
    the estimate invoice already committed against the election.
    """
    sc = fx.styles_locked(client)
    fx.add_vendor(sc)
    fx.add_print_job(sc, quantity_ordered=quantity_ordered)
    fx.printed_job(sc)
    fx.inspect_job(sc, sample_size=500, defect_count=6)
    return sc


def _manifest_out_of_order() -> List[Dict[str, Any]]:
    """A three-line manifest the vendor typed in a different order than lot code."""
    return [
        f.manifest_line(c.LOT_CODE_3, 2500, c.SEAL_3),
        f.manifest_line(c.LOT_CODE_1, 5000, c.SEAL_1),
        f.manifest_line(c.LOT_CODE_2, 5000, c.SEAL_2),
    ]


def _two_candidate_locked_election(client):
    """A locked election whose contest certified two candidates, one later cut.

    Alvarez stays certified and Brooks is disqualified after the ordering was
    frozen, so the two layout bases disagree about the roster.
    """
    sc = fx.new_election(client)
    fx.add_contest(sc)
    alvarez = fx.add_candidate(sc)
    brooks = fx.add_candidate(
        sc, full_name="Ben Brooks", ballot_name="Brooks",
        filing_received_at="2026-06-02T09:00:00Z", party_code="GRN")
    fx.certify_contest(sc)
    fx.add_style(sc)
    fx.add_precinct(sc)
    validate_success(client.certify_ballot_order(sc.election_id, users.DIRECTOR))
    fx.certify_languages(sc)
    fx.approve_proof_cycle(sc)
    fx.assign_style(sc)
    validate_success(client.lock_styles(sc.election_id, users.DIRECTOR))
    validate_success(
        client.disqualify_candidate(brooks, f.disqualify_payload(), users.DIRECTOR))
    return sc, alvarez, brooks


def _scheduled_public_session(client) -> fx.Scenario:
    """A locked election with a public session scheduled on a programmed unit."""
    sc = fx.styles_locked(client)
    fx.add_tabulator(sc)
    fx.program_unit(sc)
    fx.add_test_deck(sc, ballot_count=1, blank_count=1, expected_marks=[])
    fx.schedule_session(sc)
    return sc


# ---- One delivery call fans out into one ballot lot per manifest line ----

def test_ep_deliver_bills_the_final_invoice_lot_by_lot(client):
    """Delivery rebills the job on the final basis, rounding each lot separately.

    PRD Section 3.6: "`invoice_subtotal_cents` is computed lot by lot rather than in one line: the job's lots whose custody state is not `VOIDED` are taken in `lot_code` ascending order, each lot's shipped quantity is multiplied by the contract rate and divided by 1000 and **rounded half up to a whole cent individually**, and those per-lot amounts are then added together — round-then-sum, rather than the estimate's sum-then-round."

    Design: Corner/endpoints/ep_deliver_manifest_creates_one_lot_per_line_in_lot_code_order
    """
    sc = _qc_passed_job(client)

    job = validate_success(
        client.deliver_print_job(
            sc.job_id, f.deliver_payload(_manifest_out_of_order()), sc.vendor_headers))

    assert job["status"] == c.JOB_DELIVERED
    assert job["invoice_basis"] == c.INVOICE_FINAL
    assert job["delivered_quantity"] == 12500
    assert job["invoice_subtotal_cents"] == 105625
    assert job["defect_credit_cents"] == 1268
    assert job["freight_cents"] == c.FREIGHT_TIER_1_CENTS
    assert job["invoice_total_cents"] == 149357
    assert sc.read_election()["committed_print_cents"] == 149357


def test_ep_deliver_creates_one_lot_per_line_listed_in_lot_code_order(client):
    """Each manifest line becomes one lot at rest, listed in lot code order.

    PRD Section 3.6: "An accepted manifest moves the job `QC_PASSED → DELIVERED` and creates one ballot lot per line, each in `IN_TRANSIT` with `lot_code`, `quantity_shipped` and `seal_number` copied from the line, `election_id` copied from the job, and every accounting figure at rest: `quantity_received` 0, `issued_quantity` 0, `unused_quantity` 0, `voted_quantity` 0, `spoiled_quantity` 0, `returned_unused_quantity` 0, `accounted_quantity` 0, `lot_variance` 0, and `precinct_id` and `issued_by_user_id` null."

    Design: Corner/endpoints/ep_deliver_manifest_creates_one_lot_per_line_in_lot_code_order
    """
    sc = _qc_passed_job(client)
    validate_success(
        client.deliver_print_job(
            sc.job_id, f.deliver_payload(_manifest_out_of_order()), sc.vendor_headers))

    rows, meta = validate_paginated(
        client.list_ballot_lots(users.CUSTODIAN, {"print_job_id": sc.job_id}))
    assert [row["lot_code"] for row in rows] == [c.LOT_CODE_1, c.LOT_CODE_2, c.LOT_CODE_3]
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert rows[0]["quantity_shipped"] == 5000
    assert rows[1]["quantity_shipped"] == 5000
    assert rows[2]["quantity_shipped"] == 2500
    assert rows[0]["seal_number"] == c.SEAL_1
    assert rows[2]["seal_number"] == c.SEAL_3

    first = rows[0]
    assert first["custody_state"] == c.LOT_IN_TRANSIT
    assert first["election_id"] == sc.election_id
    assert first["precinct_id"] is None
    assert first["issued_by_user_id"] is None
    for at_rest in ("quantity_received", "issued_quantity", "unused_quantity",
                    "voted_quantity", "spoiled_quantity", "returned_unused_quantity",
                    "accounted_quantity", "lot_variance"):
        assert first[at_rest] == 0

    assert sc.read_election()["total_ballots_received"] == 0

    events, _ = validate_paginated(
        client.list_custody_events(sc.election_id, users.CUSTODIAN,
                                   {"event_type": c.EVENT_TRANSFER_OUT, "limit": 100}))
    assert len(events) == 3
    assert [event["event_type"] for event in events] == [c.EVENT_TRANSFER_OUT] * 3


# ---- A manifest is validated as a whole before any lot is written ----

def test_ep_deliver_rejects_the_whole_manifest_and_writes_nothing(client):
    """A seal repeated inside one manifest, a repeated lot code and an empty list all reject atomically.

    PRD Section 3.6: "Every line is validated before any lot is created: an empty list, a `lot_code` repeated within the manifest, or a non-positive `quantity_shipped` is `ERR_INVALID_REQUEST`; a `seal_number` repeated within the manifest, or already held by any ballot lot or tabulator of the election, is `ERR_SEAL_NUMBER_DUPLICATE` — because the uniqueness check runs across every manifest line before the first lot exists, a seal repeated inside one manifest collides with itself and rejects the whole call."

    Design: Corner/endpoints/ep_deliver_manifest_with_repeated_seal_rejected_atomically
    """
    sc = _qc_passed_job(client)

    repeated_seal = [
        f.manifest_line(c.LOT_CODE_1, 6000, c.SEAL_1),
        f.manifest_line(c.LOT_CODE_2, 6501, c.SEAL_1),
    ]
    validate_error(
        client.deliver_print_job(sc.job_id, f.deliver_payload(repeated_seal),
                                 sc.vendor_headers),
        errs.ERR_SEAL_NUMBER_DUPLICATE)

    repeated_lot_code = [
        f.manifest_line(c.LOT_CODE_1, 6000, c.SEAL_1),
        f.manifest_line(c.LOT_CODE_1, 6501, c.SEAL_2),
    ]
    validate_error(
        client.deliver_print_job(sc.job_id, f.deliver_payload(repeated_lot_code),
                                 sc.vendor_headers),
        errs.ERR_INVALID_REQUEST)

    validate_error(
        client.deliver_print_job(sc.job_id, f.deliver_payload([]), sc.vendor_headers),
        errs.ERR_INVALID_REQUEST)

    rows, meta = validate_paginated(
        client.list_ballot_lots(users.CUSTODIAN, {"print_job_id": sc.job_id}))
    assert rows == []
    assert meta["total_count"] == 0

    job = sc.read_job()
    assert job["status"] == c.JOB_QC_PASSED
    assert job["delivered_quantity"] == 0
    assert job["invoice_total_cents"] == 150625
    assert sc.read_election()["committed_print_cents"] == 150625


def test_ep_deliver_accepts_one_ballot_more_than_ordered(client):
    """Shipping one ballot above the ordered quantity is billed, not refused.

    PRD Section 3.6: "`delivered_quantity` is the sum of the same lots' shipped quantities, and it is the billing quantity for the freight tier."

    Design: Corner/endpoints/ep_deliver_manifest_with_repeated_seal_rejected_atomically
    """
    sc = _qc_passed_job(client)

    over_shipment = [
        f.manifest_line(c.LOT_CODE_1, 6000, c.SEAL_1),
        f.manifest_line(c.LOT_CODE_2, 6501, c.SEAL_2),
    ]
    job = validate_success(
        client.deliver_print_job(sc.job_id, f.deliver_payload(over_shipment),
                                 sc.vendor_headers))

    assert job["status"] == c.JOB_DELIVERED
    assert job["delivered_quantity"] == 12501
    assert job["invoice_subtotal_cents"] == 105633
    assert job["defect_credit_cents"] == 1268
    assert job["freight_cents"] == c.FREIGHT_TIER_1_CENTS
    assert job["invoice_total_cents"] == 149365
    assert sc.read_election()["committed_print_cents"] == 149365


# ---- The layout read and its optional basis parameter ----

def test_ep_layout_omitted_basis_resolves_to_the_certified_basis(client):
    """An omitted basis parameter returns the certified view, not the as-filed one.

    PRD Section 3.2: "The layout of a style may be read at any time, with the requested `basis` given as a query parameter that defaults to `CERTIFIED_BASIS`."

    PRD Section 4: "Path parameters are not repeated in the description; request-body fields and query parameters are specified in Section 3."

    Design: Corner/endpoints/ep_layout_defaults_to_certified_basis_when_basis_omitted
    """
    sc, alvarez, brooks = _two_candidate_locked_election(client)
    version_before = sc.style_version()

    default_layout = validate_success(client.get_layout(sc.style_id, users.COORDINATOR))
    explicit = validate_success(
        client.get_layout(sc.style_id, users.COORDINATOR,
                          f.layout_params(c.BASIS_CERTIFIED)))

    assert default_layout["basis"] == c.BASIS_CERTIFIED
    assert default_layout["candidate_count"] == 1
    assert default_layout["contest_count"] == 1
    assert default_layout["revision"] == 1
    assert default_layout["rotation_seed_index"] == 0
    assert default_layout["rotation_policy"] == c.ROTATION_NONE
    assert explicit["basis"] == default_layout["basis"]
    assert explicit["candidate_count"] == default_layout["candidate_count"]

    assert_printed_positions(default_layout, sc.contest_id, {alvarez: 1, brooks: None})
    block = next(entry for entry in default_layout["contests"]
                 if entry["contest_id"] == sc.contest_id)
    assert len(block["candidates"]) == 1
    assert block["candidates"][0]["base_order_index"] == 0
    assert block["candidates"][0]["ballot_name"] == "Alvarez"

    assert sc.style_version() == version_before


def test_ep_layout_provisional_basis_shows_the_as_filed_roster(client):
    """The provisional basis still prints the disqualified candidate, and an unknown basis is refused.

    PRD Section 3.2: "On the `PROVISIONAL_BASIS` the candidate set is every candidate who ever filed — those in `FILED`, `CERTIFIED` and `DISQUALIFIED` alike."

    Design: Corner/endpoints/ep_layout_defaults_to_certified_basis_when_basis_omitted
    """
    sc, alvarez, brooks = _two_candidate_locked_election(client)
    version_before = sc.style_version()

    provisional = validate_success(
        client.get_layout(sc.style_id, users.COORDINATOR,
                          f.layout_params(c.BASIS_PROVISIONAL)))
    assert provisional["basis"] == c.BASIS_PROVISIONAL
    assert provisional["candidate_count"] == 2
    assert_printed_positions(provisional, sc.contest_id, {alvarez: 1, brooks: 2})
    block = next(entry for entry in provisional["contests"]
                 if entry["contest_id"] == sc.contest_id)
    by_id = {entry["candidate_id"]: entry for entry in block["candidates"]}
    assert by_id[alvarez]["base_order_index"] == 0
    assert by_id[brooks]["base_order_index"] == 1

    validate_error(
        client.get_layout(sc.style_id, users.COORDINATOR,
                          f.layout_params(c.BASIS_FINAL_CANVASS)),
        errs.ERR_INVALID_REQUEST)

    assert sc.style_version() == version_before


# ---- The observer roster is an append-only list in registration order ----

def test_ep_observer_signin_appends_names_in_registration_order(client):
    """Names land in the order they signed in, duplicates included, and the count is the list length.

    PRD Section 3.8: "The name is appended to `observer_names` in registration order and `observer_count` is recomputed as that array's length."

    Design: Corner/endpoints/ep_observer_signin_appends_in_registration_order
    """
    sc = _scheduled_public_session(client)

    first = validate_success(
        client.add_observer(sc.session_id, f.observer_payload("Zeta Watkins"),
                            users.OBSERVER))
    assert first["observer_count"] == 1

    second = validate_success(
        client.add_observer(sc.session_id, f.observer_payload("Ada Brooks"),
                            users.TECHNICIAN))
    assert second["observer_count"] == 2

    third = validate_success(
        client.add_observer(sc.session_id, f.observer_payload("Ada Brooks"),
                            users.OBSERVER))
    assert third["observer_count"] == 3
    assert third["observer_names"] == ["Zeta Watkins", "Ada Brooks", "Ada Brooks"]
    assert sc.read_session()["observer_names"] == [
        "Zeta Watkins", "Ada Brooks", "Ada Brooks"]


def test_ep_observer_roster_closes_when_the_session_opens(client):
    """Sign-in is a scheduled-only operation, so the roster closes as the test starts.

    PRD Section 3.8: "Either a `VotingSystemTechnician` or a `PublicObserver` may register a person, supplying an `observer_name`; the session must still be `SCHEDULED`, or `ERR_SESSION_STATE_INVALID`."

    Design: Corner/endpoints/ep_observer_signin_appends_in_registration_order
    """
    sc = _scheduled_public_session(client)
    for name in ("Zeta Watkins", "Ada Brooks", "Ada Brooks"):
        validate_success(
            client.add_observer(sc.session_id, f.observer_payload(name), users.OBSERVER))

    fx.set_clock(client, c.SESSION_START)
    started = validate_success(client.start_session(sc.session_id, users.TECHNICIAN_2))
    assert started["status"] == c.SESSION_IN_PROGRESS
    assert started["observer_count"] == 3

    validate_error(
        client.add_observer(sc.session_id, f.observer_payload("Late Arrival"),
                            users.OBSERVER),
        errs.ERR_SESSION_STATE_INVALID)

    session = sc.read_session()
    assert session["observer_count"] == 3
    assert session["observer_names"] == ["Zeta Watkins", "Ada Brooks", "Ada Brooks"]


# ---- Breaking a deployment seal is legal in exactly one custody state ----

def test_ep_break_seal_returns_the_unit_to_the_vault_and_reverses_the_ledger(client):
    """Breaking the seal clears the seal and the precinct link while the test result stands.

    PRD Section 3.9: "The unit moves `DEPLOYED → IN_VAULT`, `seal_number` and `precinct_id` are cleared to null, a custody event of type `SEAL_BROKEN` is appended recording the seal that was broken, and `open_seal_count` is decremented — returning to exactly its pre-deploy value."

    Design: Corner/endpoints/ep_break_seal_is_conditional_on_deployed_custody
    """
    sc = fx.deployed_election(client)
    assert sc.read_election()["open_seal_count"] == 1

    unit = validate_success(
        client.break_seal(
            sc.tabulator_id,
            f.break_seal_payload("Tamper-evident tape lifted during transport"),
            users.CUSTODIAN))
    assert unit["custody_status"] == c.CUSTODY_IN_VAULT
    assert unit["seal_number"] is None
    assert unit["precinct_id"] is None
    assert unit["program_status"] == c.UNIT_LA_PASSED

    election = sc.read_election()
    assert election["open_seal_count"] == 0
    assert election["deployment_readiness"] == c.READINESS_BLOCKED
    assert election["status"] == c.PHASE_DEPLOYED

    precinct = sc.read_precinct()
    assert precinct["deployment_status"] == c.READINESS_NOT_READY
    assert precinct["ballots_received"] == 3000

    broken = [event for event in sc.custody_events()
              if event["event_type"] == c.EVENT_SEAL_BROKEN
              and event["subject_id"] == sc.tabulator_id]
    assert len(broken) == 1
    assert broken[0]["seal_number"] == c.SEAL_TAB_1


def test_ep_break_seal_is_refused_once_the_unit_is_back_in_the_vault(client):
    """The same call is refused on the custody axis alone the second time it is made.

    PRD Section 3.9: "It is a `WarehouseCustodian` action legal while the election is `STYLES_LOCKED` or `DEPLOYED`, carries a free-text `reason`, and requires `custody_status` to be `DEPLOYED`, or `ERR_UNIT_STATE_INVALID`."

    Design: Corner/endpoints/ep_break_seal_is_conditional_on_deployed_custody
    """
    sc = fx.deployed_election(client)
    validate_success(
        client.break_seal(sc.tabulator_id, f.break_seal_payload("First look"),
                          users.CUSTODIAN))

    validate_error(
        client.break_seal(sc.tabulator_id, f.break_seal_payload("Second look"),
                          users.CUSTODIAN),
        errs.ERR_UNIT_STATE_INVALID)

    unit = sc.read_tabulator()
    assert unit["custody_status"] == c.CUSTODY_IN_VAULT
    assert unit["program_status"] == c.UNIT_LA_PASSED
    assert sc.read_election()["open_seal_count"] == 0
    broken = [event for event in sc.custody_events()
              if event["event_type"] == c.EVENT_SEAL_BROKEN]
    assert len(broken) == 1


# ---- Ballot lots are listed in lot code order under every filter ----

def _three_lot_job_partly_issued(client) -> fx.Scenario:
    """A job whose first two lots reached the precinct while the third is still moving."""
    lots = [
        f.manifest_line(c.LOT_CODE_1, 4001, c.SEAL_1),
        f.manifest_line(c.LOT_CODE_2, 4001, c.SEAL_2),
        f.manifest_line(c.LOT_CODE_3, 4498, c.SEAL_3),
    ]
    sc = fx.delivered_lot(client, lots=lots)
    fx.receive_lot(sc, sc.lot_ids[0], c.SEAL_1, 4001)
    fx.issue_lot(sc, sc.lot_ids[0], issue_quantity=3000)
    fx.receive_lot(sc, sc.lot_ids[1], c.SEAL_2, 4001)
    fx.issue_lot(sc, sc.lot_ids[1], issue_quantity=2000)
    return sc


def test_ep_ballot_lots_filters_return_disjoint_slices_in_lot_code_order(client):
    """The job view, the two custody slices and the precinct slice all order by lot code.

    PRD Section 2.3: "Ballot lot lists are ordered by `lot_code` ascending, then by `created_at` ascending."

    Design: Corner/endpoints/ep_ballot_lots_list_filters_by_custody_state_and_precinct
    """
    sc = _three_lot_job_partly_issued(client)

    all_rows, all_meta = validate_paginated(
        client.list_ballot_lots(users.CUSTODIAN, {"print_job_id": sc.job_id}))
    assert [row["lot_code"] for row in all_rows] == [c.LOT_CODE_1, c.LOT_CODE_2, c.LOT_CODE_3]
    assert all_meta["total_count"] == 3
    assert all_meta["has_more"] is False

    issued, issued_meta = validate_paginated(
        client.list_ballot_lots(users.CUSTODIAN, {"custody_state": c.LOT_ISSUED}))
    assert [row["lot_code"] for row in issued] == [c.LOT_CODE_1, c.LOT_CODE_2]
    assert issued_meta["total_count"] == 2
    assert issued[0]["issued_quantity"] == 3000

    in_transit, transit_meta = validate_paginated(
        client.list_ballot_lots(users.CUSTODIAN, {"custody_state": c.LOT_IN_TRANSIT}))
    assert [row["lot_code"] for row in in_transit] == [c.LOT_CODE_3]
    assert transit_meta["total_count"] == 1
    assert in_transit[0]["quantity_shipped"] == 4498
    assert in_transit[0]["quantity_received"] == 0
    assert in_transit[0]["precinct_id"] is None

    at_precinct, precinct_meta = validate_paginated(
        client.list_ballot_lots(users.CUSTODIAN, {"precinct_id": sc.precinct_id}))
    assert [row["lot_code"] for row in at_precinct] == [c.LOT_CODE_1, c.LOT_CODE_2]
    assert precinct_meta["total_count"] == 2


def test_ep_ballot_lots_empty_slice_is_a_page_and_unknown_state_is_refused(client):
    """A filter matching nothing is an empty page, and a value outside the enum is a schema fault.

    PRD Section 2.6: "A schema violation at rank 30 covers: a required field absent or null; a field of the wrong JSON type; an enum field carrying a value outside its declared set; a count, quantity or money field that is negative where its definition requires zero or more, or below one where its definition requires at least one; a window whose end is less than or equal to its start; a timestamp that is not an ISO 8601 UTC instant; a reported defect count larger than the sample size it was drawn from; and a delivery manifest that is empty or repeats a `lot_code`."

    Design: Corner/endpoints/ep_ballot_lots_list_filters_by_custody_state_and_precinct
    """
    sc = _three_lot_job_partly_issued(client)

    voided, voided_meta = validate_paginated(
        client.list_ballot_lots(users.CUSTODIAN, {"custody_state": c.LOT_VOIDED}))
    assert voided == []
    assert voided_meta["total_count"] == 0
    assert voided_meta["has_more"] is False

    validate_error(
        client.list_ballot_lots(users.CUSTODIAN, {"custody_state": "SHREDDED"}),
        errs.ERR_INVALID_REQUEST)

    still_there, _ = validate_paginated(
        client.list_ballot_lots(users.CUSTODIAN, {"print_job_id": sc.job_id}))
    assert len(still_there) == 3
