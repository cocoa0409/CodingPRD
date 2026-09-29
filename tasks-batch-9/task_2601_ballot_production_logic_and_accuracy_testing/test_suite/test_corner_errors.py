"""Error reachability and error envelope shape.

Every not-found identifier in the catalogue belongs to exactly one addressed
collection, every entity that guards its own state answers with its own typed
state identifier, and every refusal — whatever its status class — comes back in
the same envelope. These tests reach each of those identifiers through the
declared endpoints and check that the refusals write nothing.
"""

from typing import Any, Dict

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
from test_helpers.assertions import assert_millisecond_timestamp, find_by

# An identifier of the right shape that no row in the store ever carries.
_MISSING = "00000000-0000-0000-0000-0000000000ff"

# The second session type the scheduling endpoint declares.
_SESSION_TYPE_AUDIT = "POST_ELECTION_AUDIT"


def _assert_error_envelope(response, expected_error_id: str,
                           expected_status: int) -> Dict[str, Any]:
    """Assert the refusal envelope: response_type, the data pair and the meta pair."""
    assert response.status_code == expected_status, (
        f"{expected_error_id} expected HTTP {expected_status}, "
        f"got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["data"].keys()) == {"error_id", "message"}
    assert body["data"]["error_id"] == expected_error_id
    message = body["data"]["message"]
    assert isinstance(message, str) and message
    meta = body["meta"]
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}
    assert meta["api_request_id"].startswith("req_")
    assert_millisecond_timestamp(meta["api_request_timestamp"], "meta.api_request_timestamp")
    return body


# ---- Every addressed collection owns its own not-found identifier ----

def test_err_each_addressed_collection_answers_with_its_own_not_found(client):
    """One unknown identifier fed to eleven routes yields eleven distinct not-found identifiers.

    PRD Section 2.6: "Rank 40 resolves to whichever not-found error belongs to the addressed collection: `ERR_ELECTION_NOT_FOUND`, `ERR_CONTEST_NOT_FOUND`, `ERR_CANDIDATE_NOT_FOUND`, `ERR_PRECINCT_NOT_FOUND`, `ERR_BALLOT_STYLE_NOT_FOUND`, `ERR_PRINT_VENDOR_NOT_FOUND`, `ERR_PRINT_JOB_NOT_FOUND`, `ERR_BALLOT_LOT_NOT_FOUND`, `ERR_TABULATOR_NOT_FOUND`, `ERR_TEST_DECK_NOT_FOUND` or `ERR_LA_SESSION_NOT_FOUND`."

    Design: Corner/errors/err_every_path_not_found_error_id_is_triggerable
    """
    sc = fx.styles_locked(client)
    fx.add_tabulator(sc)
    fx.program_unit(sc)

    probes = [
        (lambda: client.get_election(_MISSING, users.DIRECTOR),
         errs.ERR_ELECTION_NOT_FOUND),
        (lambda: client.get_contest(_MISSING, users.DIRECTOR),
         errs.ERR_CONTEST_NOT_FOUND),
        (lambda: client.disqualify_candidate(_MISSING, f.disqualify_payload(),
                                             users.DIRECTOR),
         errs.ERR_CANDIDATE_NOT_FOUND),
        (lambda: client.get_precinct(_MISSING, users.DIRECTOR),
         errs.ERR_PRECINCT_NOT_FOUND),
        (lambda: client.get_ballot_style(_MISSING, users.DIRECTOR),
         errs.ERR_BALLOT_STYLE_NOT_FOUND),
        (lambda: client.get_print_vendor(_MISSING, users.DIRECTOR),
         errs.ERR_PRINT_VENDOR_NOT_FOUND),
        (lambda: client.get_print_job(_MISSING, users.DIRECTOR),
         errs.ERR_PRINT_JOB_NOT_FOUND),
        (lambda: client.get_ballot_lot(_MISSING, users.CUSTODIAN),
         errs.ERR_BALLOT_LOT_NOT_FOUND),
        (lambda: client.get_tabulator(_MISSING, users.TECHNICIAN),
         errs.ERR_TABULATOR_NOT_FOUND),
        (lambda: client.get_la_session(_MISSING, users.OBSERVER),
         errs.ERR_LA_SESSION_NOT_FOUND),
        (lambda: client.create_la_session(
            f.la_session_payload(sc.tabulator_id, _MISSING), users.TECHNICIAN_2),
         errs.ERR_TEST_DECK_NOT_FOUND),
    ]

    reached = []
    for probe, expected_error_id in probes:
        response = probe()
        assert response.status_code == 404, (
            f"{expected_error_id} expected HTTP 404, got {response.status_code}")
        validate_error(response, expected_error_id)
        reached.append(expected_error_id)

    assert len(reached) == 11
    assert len(set(reached)) == 11

    candidate = find_by(sc.candidates_of(), "id", sc.candidate_id)
    assert candidate["status"] == c.CANDIDATE_CERTIFIED
    assert candidate["base_order_index"] == 0
    assert candidate["disqualified_reason"] is None

    _, sessions_meta = validate_paginated(
        client.list_la_sessions(users.TECHNICIAN, {"tabulator_id": sc.tabulator_id}))
    assert sessions_meta["total_count"] == 0


# ---- One envelope for every status class ----

def test_err_refusals_share_one_envelope_across_status_classes(client):
    """Six refusals from six status classes share one envelope, and the stale-version 412 is honest.

    PRD Section 2.8: "If it does not equal the style's current `version`, the order is rejected with `ERR_STALE_BALLOT_STYLE_VERSION` and HTTP 412."

    Design: Corner/errors/err_error_envelope_is_uniform_across_status_classes
    """
    sc = fx.contests_certified(client)
    fx.certify_languages(sc)
    fx.approve_proof_cycle(sc)
    fx.assign_style(sc)
    stale_version = sc.style_version()
    validate_success(client.lock_styles(sc.election_id, users.DIRECTOR))
    current_version = sc.style_version()
    assert current_version == stale_version + 1
    vendor_id = fx.add_vendor(sc)

    _assert_error_envelope(
        client.create_print_job(
            f.print_job_payload(vendor_id, sc.style_id, current_version,
                                quantity_ordered=-5),
            users.COORDINATOR),
        errs.ERR_INVALID_REQUEST, 400)

    _assert_error_envelope(
        client.get_election(sc.election_id, users.headers_without_role()),
        errs.ERR_UNAUTHENTICATED, 401)

    _assert_error_envelope(
        client.lock_styles(sc.election_id, users.OBSERVER),
        errs.ERR_UNAUTHORIZED, 403)

    _assert_error_envelope(
        client.get_print_job(_MISSING, users.DIRECTOR),
        errs.ERR_PRINT_JOB_NOT_FOUND, 404)

    _assert_error_envelope(
        client.lock_styles(sc.election_id, users.DIRECTOR),
        errs.ERR_ELECTION_PHASE_INVALID, 409)

    _assert_error_envelope(
        client.create_print_job(
            f.print_job_payload(vendor_id, sc.style_id, stale_version),
            users.COORDINATOR),
        errs.ERR_STALE_BALLOT_STYLE_VERSION, 412)

    accepted = client.create_print_job(
        f.print_job_payload(vendor_id, sc.style_id, current_version),
        users.COORDINATOR)
    job = validate_success(accepted, expected_status=201)
    assert accepted.json()["response_type"] == "object"
    assert job["status"] == c.JOB_PROOF_PENDING

    _, jobs_meta = validate_paginated(
        client.list_print_jobs(users.DIRECTOR, {"election_id": sc.election_id}))
    assert jobs_meta["total_count"] == 1
    vendor = validate_success(client.get_print_vendor(vendor_id, users.DIRECTOR))
    assert vendor["active_job_count"] == 1


# ---- Each entity guards its own state with its own identifier ----

def test_err_repeated_actions_answer_with_each_entity_s_own_state_error(client):
    """A finished job, a disqualified candidate and a consumed deck each refuse with their own state identifier.

    PRD Section 3.5: "Quality inspection belongs to the `WarehouseCustodian`, is not gated on the election phase, and requires the job to be `PRINTING` or `QC_HOLD` — inspecting a `PROOF_PENDING`, `QC_PASSED`, `DELIVERED` or `REJECTED` job is `ERR_JOB_STATE_INVALID`."

    PRD Section 3.2: "A candidate already in `DISQUALIFIED` cannot be disqualified again — that is `ERR_CANDIDATE_STATE_INVALID`."

    PRD Section 3.8: "Guards run in ascending rank: the unit must resolve, or `ERR_TABULATOR_NOT_FOUND`, and the deck must resolve, or `ERR_TEST_DECK_NOT_FOUND`, with a deck or unit from another election reported as not found rather than as a business error; the election phase must permit scheduling; the unit's `program_status` must be `PROGRAMMED` or `LA_PASSED`, or `ERR_UNIT_STATE_INVALID` — an `UNPROGRAMMED` or `LA_FAILED` unit has nothing to test; the deck's `status` must be `DRAFT`, or `ERR_DECK_STATE_INVALID`; and the unit's calendar must be free."

    Design: Corner/errors/err_out_of_state_actions_return_typed_state_error_ids
    """
    sc = fx.la_passed_unit(client)

    validate_error(
        client.approve_press_proof(sc.job_id, users.DIRECTOR),
        errs.ERR_JOB_STATE_INVALID)
    validate_error(
        client.inspect_print_job(sc.job_id, f.inspect_payload(), users.CUSTODIAN),
        errs.ERR_JOB_STATE_INVALID)

    disqualified = validate_success(
        client.disqualify_candidate(
            sc.candidate_id,
            f.disqualify_payload("Withdrew after certification"),
            users.DIRECTOR))
    assert disqualified["status"] == c.CANDIDATE_DISQUALIFIED

    validate_error(
        client.disqualify_candidate(
            sc.candidate_id,
            f.disqualify_payload("Duplicate filing of the same disqualification"),
            users.DIRECTOR),
        errs.ERR_CANDIDATE_STATE_INVALID)
    candidate = find_by(sc.candidates_of(), "id", sc.candidate_id)
    assert candidate["disqualified_reason"] == "Withdrew after certification"

    validate_error(
        client.create_la_session(
            f.la_session_payload(
                sc.tabulator_id, sc.deck_id,
                scheduled_start="2026-09-05T10:00:00Z",
                scheduled_end="2026-09-05T12:00:00Z",
                session_type=_SESSION_TYPE_AUDIT),
            users.TECHNICIAN_2),
        errs.ERR_DECK_STATE_INVALID)

    job = sc.read_job()
    assert job["status"] == c.JOB_DELIVERED
    assert job["invoice_basis"] == c.INVOICE_FINAL
    assert job["inspection_count"] == 1

    _, sessions_meta = validate_paginated(
        client.list_la_sessions(users.TECHNICIAN, {"tabulator_id": sc.tabulator_id}))
    assert sessions_meta["total_count"] == 1


# ---- The two ordering errors sit on opposite sides of certification ----

def test_err_empty_ordering_pass_and_duplicate_contest_triples_are_both_refused(client):
    """An empty ordering pass and a pair of identical draft contests are refused, and the measure alone is printed.

    PRD Section 3.1: "It requires at least one `CERTIFIED` contest, or it fails with `ERR_NO_CERTIFIED_CONTESTS` — nothing is written and the election stays in `SETUP`."

    PRD Section 3.2: "Finally, no other contest of the same election in `DRAFT` or `CERTIFIED` may share this contest's combination of `contest_type`, `district_code` and `title`; a duplicate is refused with `ERR_BALLOT_ORDER_COLLISION`."

    PRD Section 3.2: "A `MEASURE` contest is exempt from the candidate test and certifies with no candidates at all, but a `CANDIDATE` contest must have at least as many `FILED` candidates as it has `seats_open`, or the request fails with `ERR_CANDIDATE_STATE_INVALID` — a contest that cannot fill its seats is not certifiable."

    Design: Corner/errors/err_no_certified_contests_and_ballot_order_collision_are_triggerable
    """
    sc = fx.new_election(client)
    twin_a = fx.add_contest(sc, title="County Sheriff", district_code=c.DISTRICT_D12,
                            seats_open=1)
    fx.add_candidate(sc, contest_id=twin_a)
    twin_b = fx.add_contest(sc, title="County Sheriff", district_code=c.DISTRICT_D12,
                            seats_open=1)
    fx.add_candidate(sc, contest_id=twin_b, full_name="Ben Brooks", ballot_name="Brooks",
                     filing_received_at="2026-06-02T09:00:00Z", party_code="GRN")
    under_filled = fx.add_contest(sc, title="County Clerk", district_code=c.DISTRICT_D19,
                                  seats_open=2)
    fx.add_candidate(sc, contest_id=under_filled, full_name="Cara Chen",
                     ballot_name="Chen", filing_received_at="2026-06-03T09:00:00Z",
                     party_code="NPP")
    measure = fx.add_contest(sc, title="Bond Measure A",
                             contest_type=c.CONTEST_TYPE_MEASURE,
                             district_code=c.DISTRICT_D07, seats_open=1)

    validate_error(
        client.certify_ballot_order(sc.election_id, users.DIRECTOR),
        errs.ERR_NO_CERTIFIED_CONTESTS)
    assert sc.read_election()["status"] == c.PHASE_SETUP

    validate_error(client.certify_contest(twin_a, users.DIRECTOR),
                   errs.ERR_BALLOT_ORDER_COLLISION)
    validate_error(client.certify_contest(twin_b, users.DIRECTOR),
                   errs.ERR_BALLOT_ORDER_COLLISION)
    validate_error(client.certify_contest(under_filled, users.DIRECTOR),
                   errs.ERR_CANDIDATE_STATE_INVALID)

    certified = validate_success(client.certify_contest(measure, users.DIRECTOR))
    assert certified["status"] == c.CONTEST_CERTIFIED
    assert certified["certified_candidate_count"] == 0

    election = validate_success(
        client.certify_ballot_order(sc.election_id, users.DIRECTOR))
    assert election["status"] == c.PHASE_CONTESTS_CERTIFIED
    assert election["certified_contest_count"] == 1

    assert sc.read_contest(measure)["ballot_order_index"] == 1
    blocked = sc.read_contest(twin_a)
    assert blocked["status"] == c.CONTEST_DRAFT
    assert blocked["ballot_order_index"] is None
