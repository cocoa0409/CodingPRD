"""Confidentiality breaches: substantiation cascade, sanction ban cascade,
reporter/adjudicator separation, and reinstatement gating."""
from test_helpers import (
    ApiErrorId,
    book_session,
    create_moderator,
    create_remote_session,
    create_released_build,
    create_study,
    enroll_participant,
    get_booking,
    get_build,
    get_participant,
    get_session,
    get_success_data,
    issue_key,
    list_exposures,
    make_legal_headers,
    make_moderator_headers,
    make_participant_headers,
    open_case,
    register_participant,
    report_breach,
    set_clock,
    setup_study_with_published_nda,
    TEST_USERS,
    validate_error,
    LEGAL_1,
    RESEARCHER_1,
)

ADMIN = TEST_USERS["admin_headers"]
RESEARCHER = TEST_USERS["researcher_headers"]
LEGAL = TEST_USERS["legal_headers"]


def _setup_breach_cascade_scenario(api):
    """A and B ENROLLED; RELEASED build with a key issued to A; capacity-1
    session with A BOOKED and B WAITLISTED; a MAJOR breach case against A in
    UNDER_INVESTIGATION under legal-1."""
    set_clock("2026-08-01T00:00:00Z")
    study, _nda = setup_study_with_published_nda(code="TC1")
    pa = register_participant(email="tc1-a@x.com")
    enroll_participant(study["id"], pa)
    pb = register_participant(email="tc1-b@x.com", age_years=27)
    enroll_participant(study["id"], pb)
    build = create_released_build(study["id"], build_label="0.9.0", max_keys=5)
    key = issue_key(build["id"], pa["id"])
    session = create_remote_session(study["id"], "2026-08-10T10:00:00Z",
                                    "2026-08-10T11:00:00Z", seat_capacity=1)
    bk_a = book_session(session["id"], pa["id"])
    bk_b = book_session(session["id"], pb["id"])
    assert bk_a["status"] == "BOOKED" and bk_b["status"] == "WAITLISTED"
    case = report_breach(pa["id"], study["id"], severity="MAJOR",
                         evidence_summary="Posted build screenshots to a public forum")
    open_case(case["id"], legal_id=LEGAL_1)
    return {"study": study, "pa": pa, "pb": pb, "build": build, "key": key,
            "session": session, "bk_a": bk_a, "bk_b": bk_b, "case": case}


class TestBreachSubstantiationCascade:
    def test_substantiate_suspends_and_revokes_issued_keys(self, api):
        """PRD §3.9: "The participant's `risk_score` increases by the severity
        weight — 10 for a `MINOR` breach, 25 for `MAJOR`, 40 for `CRITICAL` —
        capped at 100 so repeated substantiations never exceed it. The cascade
        then fires: if the participant is `ACTIVE`, they become `SUSPENDED`,
        and the suspension cascade of §3.1 runs in full"
        PRD §3.1: "every access key the participant holds in `ISSUED` is
        revoked, each revocation appending a `KEY_REVOKED` record to the
        exposure journal and decrementing the owning build's
        `keys_active_count` by one."

        Design: Difficulty/transitive_cascade/breach_substantiation_suspends_cancels_promotes
        """
        ctx = _setup_breach_cascade_scenario(api)
        get_success_data(api.substantiate_breach_case(
            ctx["case"]["id"], make_legal_headers(LEGAL_1)))
        participant = get_participant(ctx["pa"]["id"])
        assert participant["status"] == "SUSPENDED", "cascade link 1"
        assert participant["risk_score"] == 25, "MAJOR severity weight"
        key = get_success_data(api.get_access_key(ctx["key"]["id"], ADMIN))
        assert key["status"] == "REVOKED"
        assert get_build(ctx["build"]["id"])["keys_active_count"] == 0
        records = list_exposures(participant_id=ctx["pa"]["id"],
                                 build_id=ctx["build"]["id"])
        assert sorted(r["event_type"] for r in records) == ["KEY_ISSUED", "KEY_REVOKED"]

    def test_suspension_cancels_booking_and_promotes_waitlist(self, api):
        """PRD §3.9: "their bookings in `BOOKED`, `PROMOTED`, and `WAITLISTED`
        are cancelled, each freed seat promoting the earliest-created eligible
        waitlisted booking on that session so a cancel-plus-promotion pair
        leaves the session's `seats_taken` unchanged"
        PRD §3.1: "Suspension runs a full cascade: every booking the
        participant holds in `BOOKED` or `PROMOTED` is cancelled, and each such
        cancellation frees a seat that immediately promotes the earliest-created
        eligible waitlisted booking on the same session under the promotion
        rule of §3.5"

        Design: Difficulty/transitive_cascade/breach_substantiation_suspends_cancels_promotes
        """
        ctx = _setup_breach_cascade_scenario(api)
        get_success_data(api.substantiate_breach_case(
            ctx["case"]["id"], make_legal_headers(LEGAL_1)))
        assert get_booking(ctx["bk_a"]["id"])["status"] == "CANCELLED", (
            "cascade link 2: the suspended participant's booking cancels")
        assert get_booking(ctx["bk_b"]["id"])["status"] == "PROMOTED", (
            "cascade link 3: the freed seat promotes the waitlisted booking")
        assert get_session(ctx["session"]["id"])["seats_taken"] == 1, (
            "the cancel + promote pair conserves occupancy")


def test_sanction_ban_revokes_redeemed_keys(api):
    """PRD §3.4: "One transition exists only inside the ban cascade: `REDEEMED`
    → `REVOKED`, again with its `KEY_REVOKED` record and a one-count decrement,
    fires when the participant is banned."
    PRD §3.9: "A `BAN` drives the participant into `BANNED` and runs the full
    ban cascade of §3.1 — bookings cancelled with promotion, all keys including
    `REDEEMED` ones revoked, signatures voided with enrolled applications
    reverting, and payouts voided with committed budget released."
    PRD §3.9: "The participant's `risk_score` increases by the severity weight
    — 10 for a `MINOR` breach, 25 for `MAJOR`, 40 for `CRITICAL`"

    Design: Corner/state_machines/sanction_ban_revokes_redeemed_keys
    """
    set_clock("2026-08-01T00:00:00Z")
    study, _nda = setup_study_with_published_nda(code="SB1")
    participant = register_participant(email="sb1-p@x.com")
    enroll_participant(study["id"], participant)
    build = create_released_build(study["id"], build_label="4.2.0", max_keys=5)
    key = issue_key(build["id"], participant["id"])
    get_success_data(api.redeem_access_key(key["id"],
                                           make_participant_headers(participant["id"])))
    case = report_breach(participant["id"], study["id"], severity="CRITICAL",
                         reporter="researcher", reporter_id="researcher-9",
                         evidence_summary="Leaked build to video site")
    open_case(case["id"], legal_id=LEGAL_1)
    get_success_data(api.substantiate_breach_case(case["id"],
                                                  make_legal_headers(LEGAL_1)))
    mid = get_success_data(api.get_access_key(key["id"], ADMIN))
    assert mid["status"] == "REDEEMED", (
        "the suspension cascade does not touch redeemed keys")
    sanctioned = get_success_data(api.sanction_breach_case(
        case["id"], "BAN", make_legal_headers(LEGAL_1),
        sanction_note="Repeat offender"))
    assert sanctioned["status"] == "SANCTIONED"
    participant_now = get_participant(participant["id"])
    assert participant_now["status"] == "BANNED"
    assert participant_now["risk_score"] == 40, "CRITICAL severity weight"
    key_now = get_success_data(api.get_access_key(key["id"], ADMIN))
    assert key_now["status"] == "REVOKED", "the ban cascade revokes REDEEMED keys too"
    records = list_exposures(participant_id=participant["id"], build_id=build["id"])
    assert sorted(r["event_type"] for r in records) == [
        "KEY_ISSUED", "KEY_REDEEMED", "KEY_REVOKED"], (
        "exactly one journal record per key lifecycle event")


def test_reporter_cannot_adjudicate_breach(api):
    """PRD §3.9: "A `LegalCounsel` opens the investigation, moving `REPORTED` →
    `UNDER_INVESTIGATION` and recording themselves in `adjudicated_by_user_id`;
    the reporter is barred from adjudicating their own report, and an opener
    whose `X-User-ID` equals `reported_by_user_id` is refused with
    `ERR_REPORTER_CANNOT_ADJUDICATE`."

    Design: Corner/validations/reporter_cannot_adjudicate_breach
    """
    study = create_study(open_recruitment=False, code="RCA1")
    participant = register_participant(email="rca-p@x.com")
    moderator = create_moderator(display_name="Mod RCA")
    case = report_breach(participant["id"], study["id"], severity="MINOR",
                         reporter="moderator", reporter_id=moderator["id"],
                         evidence_summary="Streamed the build")
    assert case["reported_by_user_id"] == moderator["id"]
    # A counsel call carrying the reporter's identity is refused.
    resp = api.open_investigation(case["id"], make_legal_headers(moderator["id"]))
    validate_error(resp, ApiErrorId.ERR_REPORTER_CANNOT_ADJUDICATE)
    # A different counsel can adjudicate.
    opened = get_success_data(api.open_investigation(case["id"],
                                                     make_legal_headers(LEGAL_1)))
    assert opened["status"] == "UNDER_INVESTIGATION"
    assert opened["adjudicated_by_user_id"] == LEGAL_1


def test_reinstate_blocked_with_open_breach(api):
    """PRD §3.1: "Reinstatement moves `SUSPENDED` → `ACTIVE`, resets
    `no_show_strikes` to 0, and is refused with `ERR_OPEN_BREACH_EXISTS` while
    any breach case against the participant sits in `REPORTED`,
    `UNDER_INVESTIGATION`, or `SUBSTANTIATED`."
    PRD §3.9: "Dismissal moves `UNDER_INVESTIGATION` → `DISMISSED`, terminal
    and side-effect free."

    Design: Corner/validations/reinstate_blocked_with_open_breach
    """
    study = create_study(open_recruitment=False, code="OB1")
    participant = register_participant(email="ob-p@x.com")
    case = report_breach(participant["id"], study["id"], severity="MINOR",
                         evidence_summary="Suspected leak under review")
    get_success_data(api.suspend_participant(participant["id"], ADMIN))
    resp = api.reinstate_participant(participant["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_OPEN_BREACH_EXISTS)
    open_case(case["id"], legal_id=LEGAL_1)
    get_success_data(api.dismiss_breach_case(case["id"], make_legal_headers(LEGAL_1)))
    reinstated = get_success_data(api.reinstate_participant(participant["id"], ADMIN))
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["no_show_strikes"] == 0, "reinstatement resets the strike count"


def test_banned_participant_reinstate_returns_invalid_state(api):
    """PRD §3.1: "Banning is terminal and belongs to `LegalCounsel`."
    PRD §3.1: "Reinstatement moves `SUSPENDED` → `ACTIVE`"
    PRD §2.9: "The generic rejection is `ERR_INVALID_STATE`"

    Design: Corner/state_machines/banned_participant_reinstate_returns_invalid_state
    """
    participant = register_participant(email="tl1-p@x.com")
    banned = get_success_data(api.ban_participant(participant["id"], LEGAL))
    assert banned["status"] == "BANNED"
    resp = api.reinstate_participant(participant["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
