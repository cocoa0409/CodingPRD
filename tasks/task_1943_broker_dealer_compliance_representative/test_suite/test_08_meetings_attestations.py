"""Annual compliance meeting and attestations: fan-out, hold gates,
attestation ownership/deadline/state, and the close gate (PRD §3.8, §2.5).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    attestation_map,
    attest_as_owner,
    create_meeting_payload,
    make_branch,
    make_meeting,
    make_registered_rep_headers,
    make_rep,
    set_clock,
    setup_held_meeting,
    validate_error,
    validate_paginated,
    validate_success,
)

PRINCIPAL_A = TEST_USERS["principal_a_headers"]
ANY = TEST_USERS["any_headers"]


# ─── attestation deadline boundary ────────────────────

class TestAttestationDeadlineBoundary:
    def test_attest_on_deadline_day_succeeds(self, api, any_headers):
        """PRD §3.8: "the current clock date must be on or before the
        `attest_deadline` — the deadline day itself is still attestable —
        else `ERR_ATTESTATION_DEADLINE_PASSED` (HTTP 422)". A meeting dated
        2026-03-01 fans out attestations with deadline 2026-03-31; attesting
        at clock 2026-03-31T23:59:59Z succeeds.

        Design: Difficulty/boundary_precision_check/boundary_attestation_deadline
        """
        _branch, reps, _meeting, att_map = setup_held_meeting(
            num_reps=2, meeting_date="2026-03-01",
            hold_clock="2026-03-01T12:00:00Z",
        )
        assert att_map[reps[0]["id"]]["attest_deadline"] == "2026-03-31"

        set_clock("2026-03-31T23:59:59Z")
        attested = attest_as_owner(att_map[reps[0]["id"]]["id"], reps[0]["id"])
        assert attested["status"] == "ATTESTED"

    def test_attest_after_sweep_reports_state_error(self, api, any_headers):
        """PRD §2.5: "Any Attestation in `PENDING` whose `attest_deadline` is
        earlier than the new clock date transitions to `OVERDUE`." PRD §3.8:
        "the attestation must be `PENDING`, else `ERR_ATTESTATION_NOT_PENDING`"
        — after the 2026-04-01 clock set sweeps the second attestation past
        its 2026-03-31 deadline, attest is rejected by the state check.

        Design: Difficulty/boundary_precision_check/boundary_attestation_deadline
        """
        _branch, reps, _meeting, att_map = setup_held_meeting(
            num_reps=2, meeting_date="2026-03-01",
            hold_clock="2026-03-01T12:00:00Z",
        )
        set_clock("2026-04-01T00:00:01Z")
        swept = validate_success(
            api.get_attestation(att_map[reps[1]["id"]]["id"], ANY), 200
        )
        assert swept["status"] == "OVERDUE"

        res = api.attest(att_map[reps[1]["id"]]["id"],
                         make_registered_rep_headers(reps[1]["id"]))
        validate_error(res, ApiErrorId.ERR_ATTESTATION_NOT_PENDING)


# ─── meeting close gate ───────────────────────────────

class TestMeetingCloseBlocked:
    def _setup(self, api):
        """One ACTIVE rep and one rep TERMINATED before the meeting fans
        out; meeting HELD on its date."""
        branch = make_branch(region="N")
        rep_active = make_rep(branch["id"], crd_number="810001",
                              full_name="MC One")
        rep_gone = make_rep(branch["id"], crd_number="810002",
                            full_name="MC Two")
        validate_success(
            api.terminate_representative(rep_gone["id"], PRINCIPAL_A), 200
        )
        meeting = make_meeting(year=2026, meeting_date="2026-06-15")
        set_clock("2026-06-15T12:00:00Z")
        meeting = validate_success(api.hold_meeting(meeting["id"], PRINCIPAL_A),
                                   200)
        return rep_active, rep_gone, meeting

    def test_close_with_pending_attestation_rejected_and_terminated_rep_excluded(
        self, api, any_headers
    ):
        """PRD §3.8: "Closing the meeting requires every one of its
        attestations to have reached a terminal state — `ATTESTED` or
        `OVERDUE`; closing while any attestation remains `PENDING` is
        rejected with `ERR_ATTESTATIONS_STILL_PENDING`." and "Terminated
        representatives receive no attestation."

        Design: Difficulty/cross_cutting/compound_meeting_close_blocked
        """
        rep_active, rep_gone, meeting = self._setup(api)

        res = api.close_meeting(meeting["id"], PRINCIPAL_A)
        validate_error(res, ApiErrorId.ERR_ATTESTATIONS_STILL_PENDING)

        data, _meta = validate_paginated(
            api.list_attestations(ANY, params={"rep_id": rep_gone["id"]})
        )
        assert data == [], "terminated rep must receive no attestation"

    def test_close_succeeds_after_attestation(self, api, any_headers):
        """PRD §3.8: "A meeting with all attestations resolved moves to
        `CLOSED`." The blocked close succeeds once the sole attestation
        reaches ATTESTED.

        Design: Difficulty/cross_cutting/compound_meeting_close_blocked
        """
        rep_active, _rep_gone, meeting = self._setup(api)
        res = api.close_meeting(meeting["id"], PRINCIPAL_A)
        validate_error(res, ApiErrorId.ERR_ATTESTATIONS_STILL_PENDING)

        att_map = attestation_map(meeting["id"])
        attest_as_owner(att_map[rep_active["id"]]["id"], rep_active["id"])

        closed = validate_success(api.close_meeting(meeting["id"], PRINCIPAL_A),
                                  200)
        assert closed["status"] == "CLOSED"


# ─── attestation preconditions ────────────────────────

def test_attest_before_meeting_held_rejected(api, any_headers):
    """PRD §3.8: "the parent meeting must be in `HELD`, else
    `ERR_MEETING_NOT_HELD`". The meeting is SCHEDULED and the attestation
    deadline (2027-01-19) is still in the future, so the meeting-state check
    is the one that fires.

    Design: Corner/state_machines/attest_before_meeting_held_rejected
    """
    branch = make_branch(region="N")
    rep = make_rep(branch["id"], crd_number="910005", full_name="MH Rep")
    meeting = make_meeting(year=2026, meeting_date="2026-12-20")
    att_map = attestation_map(meeting["id"])

    res = api.attest(att_map[rep["id"]]["id"],
                     make_registered_rep_headers(rep["id"]))
    validate_error(res, ApiErrorId.ERR_MEETING_NOT_HELD)


def test_double_attest_rejected(api, any_headers):
    """PRD §3.8: "the attestation must be `PENDING`, else
    `ERR_ATTESTATION_NOT_PENDING`" — a second attest on the same attestation
    is rejected.

    Design: Corner/state_machines/double_attest_rejected
    """
    _branch, reps, _meeting, att_map = setup_held_meeting(
        num_reps=1, meeting_date="2026-08-01"
    )
    att_id = att_map[reps[0]["id"]]["id"]
    first = attest_as_owner(att_id, reps[0]["id"])
    assert first["status"] == "ATTESTED"

    res = api.attest(att_id, make_registered_rep_headers(reps[0]["id"]))
    validate_error(res, ApiErrorId.ERR_ATTESTATION_NOT_PENDING)


def test_attest_after_deadline_rejected(api, any_headers):
    """PRD §3.8: "the current clock date must be on or before the
    `attest_deadline` — the deadline day itself is still attestable — else
    `ERR_ATTESTATION_DEADLINE_PASSED` (HTTP 422)". PRD §2.10 places the
    "Date-versus-clock rules" before the "Business constraints" step, so on
    a still-PENDING attestation (no clock-set sweep ran) whose deadline
    2026-07-30 precedes the default clock date 2026-08-01, the temporal
    error surfaces.

    Design: Corner/state_machines/attest_after_deadline_rejected
    """
    branch = make_branch(region="W")
    rep = make_rep(branch["id"], crd_number="910007", full_name="DL Rep")
    meeting = make_meeting(year=2026, meeting_date="2026-06-30")
    att_map = attestation_map(meeting["id"])
    assert att_map[rep["id"]]["attest_deadline"] == "2026-07-30"
    assert att_map[rep["id"]]["status"] == "PENDING"

    res = api.attest(att_map[rep["id"]]["id"],
                     make_registered_rep_headers(rep["id"]))
    validate_error(res, ApiErrorId.ERR_ATTESTATION_DEADLINE_PASSED)


def test_attest_wrong_rep_forbidden(api, any_headers):
    """PRD §3.8: "The caller's `X-User-ID` must equal the attestation's
    `rep_id`, else `ERR_NOT_ATTESTATION_OWNER` (HTTP 403)" — another rep
    cannot sign; the owning rep can.

    Design: Corner/rbac/attest_wrong_rep_forbidden
    """
    _branch, reps, _meeting, att_map = setup_held_meeting(
        num_reps=2, meeting_date="2026-08-01"
    )
    att_id = att_map[reps[0]["id"]]["id"]

    res = api.attest(att_id, make_registered_rep_headers(reps[1]["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_ATTESTATION_OWNER)

    attested = attest_as_owner(att_id, reps[0]["id"])
    assert attested["status"] == "ATTESTED"


# ─── meeting scheduling rules ─────────────────────────

def test_duplicate_meeting_year_rejected(api, any_headers):
    """PRD §3.8: "only one meeting may exist per calendar year, and a
    duplicate year is rejected with `ERR_DUPLICATE_MEETING_YEAR`".

    Design: Corner/validations/meeting_uniqueness_per_year
    """
    validate_success(
        api.create_meeting(create_meeting_payload(year=2026,
                                                  meeting_date="2026-06-15"),
                           PRINCIPAL_A),
        201,
    )
    res = api.create_meeting(
        create_meeting_payload(year=2026, meeting_date="2026-09-10"),
        PRINCIPAL_A,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_MEETING_YEAR)


def test_hold_before_meeting_date_rejected(api, any_headers):
    """PRD §3.8: "the current clock date must be on or after the
    `meeting_date`, else `ERR_MEETING_DATE_NOT_REACHED` (HTTP 422)" — holding
    is inclusive of the meeting date itself.

    Design: Corner/validations/meeting_hold_before_date_rejected
    """
    meeting = make_meeting(year=2026, meeting_date="2026-12-20")
    set_clock("2026-12-01T09:00:00Z")
    res = api.hold_meeting(meeting["id"], PRINCIPAL_A)
    validate_error(res, ApiErrorId.ERR_MEETING_DATE_NOT_REACHED)

    set_clock("2026-12-20T09:00:00Z")
    held = validate_success(api.hold_meeting(meeting["id"], PRINCIPAL_A), 200)
    assert held["status"] == "HELD"


# ─── fan-out cardinality and deadline math ────────────

def test_meeting_attestation_fanout(api, any_headers):
    """PRD §3.8: "for every representative whose `status` is `ACTIVE` at
    creation time — visited in creation order, earliest first — the system
    creates an Attestation in `PENDING`, binding the `meeting_id` and
    `rep_id` and setting the `attest_deadline` to the `meeting_date` plus 30
    days." Two ACTIVE reps produce exactly two PENDING attestations with
    deadline 2026-12-05 + 30 days = 2027-01-04.

    Design: Corner/calculations/default_meeting_attestation_fanout
    """
    branch = make_branch(region="N")
    reps = [
        make_rep(branch["id"], crd_number="920004", full_name="MF One"),
        make_rep(branch["id"], crd_number="920005", full_name="MF Two"),
    ]
    meeting = make_meeting(year=2026, meeting_date="2026-12-05")

    data, meta = validate_paginated(
        api.list_attestations(ANY, params={"meeting_id": meeting["id"]})
    )
    assert len(data) == 2
    assert meta["total_count"] == 2
    by_rep = {a["rep_id"]: a for a in data}
    assert set(by_rep) == {reps[0]["id"], reps[1]["id"]}
    for att in by_rep.values():
        assert att["status"] == "PENDING"
        assert att["attest_deadline"] == "2027-01-04"
        assert att["meeting_id"] == meeting["id"]
