"""Nomination, the OCC seat guard, the confirm/reject fork, and confirm gates.

Queue A: appointment_branching_reject_no_term, confirm_seat_fill_depth2_cascade,
         confirm_state_beats_sod.
Queue B: supersede-on-renomination, quorum-not-met, term_end computation, reject SoD,
         stale/correct seat-version.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, iso_equal,
    create_application_payload,
    TEST_USERS, make_authority_headers, make_confirming_headers,
    make_applicant_headers,
    new_board, new_seat, new_applicant, new_vacancy, eligible_application,
    nominate, confirm, seat_version, term_for_seat,
    setup_nominated_appointment, setup_seated_member,
    create_appointment_payload, api_client,
)

CLERK = TEST_USERS["clerk_headers"]


# ─── Queue A: appointment_branching_reject_no_term ─────────────
def test_reject_creates_no_term_seat_stays_vacant(api):
    """PRD §3.3: "A rejection records the rejecting voter in `confirmed_by_user_id`
    along with the reason, but creates no term; the seat's `occupancy_status` is left
    unchanged and any open vacancy stays `OPEN`."

    Design: Difficulty/non_linear_state_machine/appointment_branching_reject_no_term
    """
    scene = setup_nominated_appointment()
    rejected = validate_success(api.reject_appointment(
        scene.appointment["id"], {"reason": "insufficient qualifications"},
        make_confirming_headers("cm-1")), 200)
    assert rejected["status"] == "REJECTED"
    terms = validate_success(api.list_terms(CLERK, params={"appointment_id": scene.appointment["id"]}), 200)
    assert len(terms) == 0
    seat = validate_success(api.get_seat(scene.seat["id"], CLERK), 200)
    assert seat["occupancy_status"] == "VACANT"


def test_reject_records_voter_and_leaves_vacancy_open(api):
    """PRD §3.3: "A rejection records the rejecting voter in `confirmed_by_user_id`
    along with the reason, but creates no term; the seat's `occupancy_status` is left
    unchanged and any open vacancy stays `OPEN`."

    Design: Difficulty/non_linear_state_machine/appointment_branching_reject_no_term
    """
    scene = setup_nominated_appointment()
    validate_success(api.reject_appointment(
        scene.appointment["id"], {"reason": "conflict"}, make_confirming_headers("cm-9")), 200)
    appt = validate_success(api.get_appointment(scene.appointment["id"], CLERK), 200)
    assert appt["confirmed_by_user_id"] == "cm-9"
    vacancy = validate_success(api.get_vacancy(scene.vacancy["id"], CLERK), 200)
    assert vacancy["status"] == "OPEN"


# ─── Queue A: confirm_seat_fill_depth2_cascade ─────────────────
def test_confirm_creates_active_term_and_fills_seat(api):
    """PRD §3.3: "creates a new `Term` in `ACTIVE` status for the seat and applicant ...;
    sets the seat's `occupancy_status` to `FILLED`".

    Design: Difficulty/transitive_cascade/confirm_seat_fill_depth2_cascade
    """
    scene = setup_nominated_appointment()
    confirmed = validate_success(api.confirm_appointment(
        scene.appointment["id"], {"yes_votes": 3, "no_votes": 0},
        make_confirming_headers("cm-1")), 200)
    assert confirmed["status"] == "CONFIRMED"
    terms = validate_success(api.list_terms(
        CLERK, params={"seat_id": scene.seat["id"], "status": "ACTIVE"}), 200)
    assert len(terms) == 1
    seat = validate_success(api.get_seat(scene.seat["id"], CLERK), 200)
    assert seat["occupancy_status"] == "FILLED"


def test_confirm_flips_seat_from_vacant_to_filled(api):
    """PRD §2.6: "Confirming an appointment creates an `ACTIVE` term, sets that seat to
    `FILLED`".
    PRD §2.4: "when confirming an appointment flips a seat's `occupancy_status`, the
    affected seat's `updated_at` and `version` both advance."

    Design: Difficulty/transitive_cascade/confirm_seat_fill_depth2_cascade
    """
    scene = setup_nominated_appointment()
    before = validate_success(api.get_seat(scene.seat["id"], CLERK), 200)
    assert before["occupancy_status"] == "VACANT"
    validate_success(api.confirm_appointment(
        scene.appointment["id"], {"yes_votes": 3, "no_votes": 0},
        make_confirming_headers("cm-1")), 200)
    after = validate_success(api.get_seat(scene.seat["id"], CLERK), 200)
    assert after["occupancy_status"] == "FILLED"
    assert after["version"] > before["version"]


# ─── Queue A: confirm_state_beats_sod ──────────────────────────
def test_reconfirm_confirmed_by_nominator_state_beats_sod(api):
    """PRD §3.3: "Several checks apply, evaluated in order after the appointment is
    confirmed to be in `NOMINATED` state: segregation of duties first".
    PRD §3.3: "Both branches require the appointment to be `NOMINATED`; acting on an
    appointment in any other state is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_sod
    """
    scene = setup_seated_member()  # already CONFIRMED, nominator auth-1
    res = api.confirm_appointment(
        scene.appointment["id"], {"yes_votes": 3, "no_votes": 0},
        make_confirming_headers("auth-1"))  # nominator re-confirms (SoD would also fail)
    validate_error(res, "ERR_INVALID_STATE")


def test_reconfirm_confirmed_state_beats_sod_and_quorum(api):
    """PRD §3.3: "evaluated in order after the appointment is confirmed to be in
    `NOMINATED` state: segregation of duties first ... then quorum".
    PRD §3.3: "acting on an appointment in any other state is rejected with
    `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_sod
    """
    scene = setup_seated_member()  # CONFIRMED, nominator auth-1
    # Nominator re-confirms with a sub-quorum, losing vote: state precedes SoD + quorum.
    res = api.confirm_appointment(
        scene.appointment["id"], {"yes_votes": 1, "no_votes": 5},
        make_confirming_headers("auth-1"))
    validate_error(res, "ERR_INVALID_STATE")


# ─── Queue B ───────────────────────────────────────────────────
def test_appointment_supersede_on_renomination(api):
    """PRD §3.3: "Creating a new nomination for a seat that already has a live
    `NOMINATED` appointment supersedes the earlier one, setting that prior appointment's
    status from `NOMINATED` to `SUPERSEDED`".

    Design: Corner/state_machines/appointment_supersede_on_renomination
    """
    board = new_board()
    seat = new_seat(board["id"])
    ap1 = new_applicant(full_name="Ada Reeves", email="ada@x.com")
    ap2 = new_applicant(full_name="Ben Cole", email="ben@x.com")
    vacancy = new_vacancy(seat["id"])
    app1 = eligible_application(vacancy["id"], ap1["id"])
    app2 = eligible_application(vacancy["id"], ap2["id"])
    appt1 = nominate(app1["id"], seat["id"], "2026-06-01T00:00:00Z", seat["version"])
    v2 = seat_version(seat["id"])
    appt2 = nominate(app2["id"], seat["id"], "2026-06-01T00:00:00Z", v2)
    assert appt2["status"] == "NOMINATED"
    prior = validate_success(api.get_appointment(appt1["id"], CLERK), 200)
    assert prior["status"] == "SUPERSEDED"


def test_confirm_quorum_not_met_rejected(api):
    """PRD §3.3: "the confirmation succeeds only when `yes_votes` is at least the board's
    `quorum_count` and `yes_votes` is strictly greater than `no_votes` ..., and a vote
    that fails either condition is rejected with `ERR_QUORUM_NOT_MET`."

    Design: Corner/calculations/confirm_quorum_not_met_rejected
    """
    scene = setup_nominated_appointment()  # board quorum_count 3
    res = api.confirm_appointment(
        scene.appointment["id"], {"yes_votes": 2, "no_votes": 0},
        make_confirming_headers("cm-1"))
    validate_error(res, "ERR_QUORUM_NOT_MET")


def test_term_end_is_start_plus_48_months(api):
    """PRD §3.3: "`term_end_date`, obtained by adding the board's `term_length_months`
    whole calendar months to `term_start_date`".

    Design: Corner/calculations/term_end_is_start_plus_48_months
    """
    board = new_board()  # term_length_months 48
    seat = new_seat(board["id"])
    applicant = new_applicant()
    vacancy = new_vacancy(seat["id"])
    app = eligible_application(vacancy["id"], applicant["id"])
    appt = validate_success(api.create_appointment(
        create_appointment_payload(app["id"], seat["id"], "2026-06-01T00:00:00Z", seat["version"]),
        make_authority_headers("auth-1")), 201)
    assert iso_equal(appt["term_end_date"], "2030-06-01T00:00:00Z")


def test_reject_by_nominator_segregation_of_duties(api):
    """PRD §3.3: "Segregation of duties applies here too: the rejecting member's
    `X-User-ID` must differ from `nominated_by_user_id`, or the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/reject_by_nominator_segregation_of_duties
    """
    scene = setup_nominated_appointment(auth_id="auth-1")
    res = api.reject_appointment(
        scene.appointment["id"], {"reason": "conflict"}, make_confirming_headers("auth-1"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES")


def test_nominate_stale_seat_version_conflict(api):
    """PRD §2.5: "If another writer has already nominated against that seat since the
    client last read it — advancing the seat's `version` — then the client's
    `expected_seat_version` is stale, and the nomination is rejected with
    `ERR_STALE_SEAT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/nominate_stale_seat_version_conflict
    """
    board = new_board()
    seat = new_seat(board["id"])
    stale_version = seat["version"]
    ap1 = new_applicant(full_name="Ada Reeves", email="ada@x.com")
    ap2 = new_applicant(full_name="Ben Cole", email="ben@x.com")
    vacancy = new_vacancy(seat["id"])
    app1 = eligible_application(vacancy["id"], ap1["id"])
    app2 = eligible_application(vacancy["id"], ap2["id"])
    nominate(app1["id"], seat["id"], "2026-06-01T00:00:00Z", stale_version)  # bumps seat version
    res = api.create_appointment(
        create_appointment_payload(app2["id"], seat["id"], "2026-06-01T00:00:00Z", stale_version),
        make_authority_headers("auth-1"))
    validate_error(res, "ERR_STALE_SEAT_VERSION")


def test_nominate_correct_seat_version_succeeds_and_bumps(api):
    """PRD §2.5: "A nomination request must carry `expected_seat_version` equal to the
    target seat's current `version`. Each accepted nomination increments the seat's
    `version` by 1."

    Design: Corner/cross_cutting/nominate_correct_seat_version_succeeds
    """
    board = new_board()
    seat = new_seat(board["id"])
    applicant = new_applicant()
    vacancy = new_vacancy(seat["id"])
    app = eligible_application(vacancy["id"], applicant["id"])
    appt = validate_success(api.create_appointment(
        create_appointment_payload(app["id"], seat["id"], "2026-06-01T00:00:00Z", seat["version"]),
        make_authority_headers("auth-1")), 201)
    assert appt["status"] == "NOMINATED"
    refreshed = validate_success(api.get_seat(seat["id"], CLERK), 200)
    assert refreshed["version"] == 2
