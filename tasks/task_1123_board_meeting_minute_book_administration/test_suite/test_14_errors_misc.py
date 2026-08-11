"""Miscellaneous business-rule errors: duplicate ballot, ineligible voter,
adjourn blocked by open vote, cross-corporation references, proxy eligibility,
duplicate attendance, duplicate email, clearing-resolution gate, audit
committee independence, seat capacity, rotation limit."""
from test_helpers import (
    ApiErrorId,
    add_director,
    add_membership,
    cast_ballot,
    convene_meeting,
    create_consent_resolution,
    create_meeting_resolution,
    file_disclosure,
    get_success_data,
    open_vote_as_chair,
    record_attendance,
    schedule_meeting,
    schedule_noticed_meeting,
    set_clock,
    setup_active_committee,
    setup_corporation_with_adopted_bylaws,
    setup_corporation_with_directors,
    setup_in_session_meeting,
    table_resolution,
    validate_error,
    validate_paginated,
    validate_success,
    make_chair_headers,
    make_director_headers,
    SECRETARY,
)
from test_helpers import api_client


class TestDuplicateBallotRejected:
    def test_duplicate_plain_ballot_rejected(self, api):
        """PRD §3.6: "at most one `ACTIVE` record may exist per resolution,
        director, and channel — a second is `ERR_DUPLICATE_VOTE` (HTTP 409)."

        Design: Corner/errors/duplicate_plain_ballot_rejected
        """
        corp, _bylaws, directors = setup_corporation_with_directors(2, name="Corp R2")
        d1, d2 = directors
        m = setup_in_session_meeting(corp["id"], d1["id"], [d1["id"], d2["id"]])
        r = create_meeting_resolution(corp["id"], m["id"], title="R", text="t")
        table_resolution(r["id"])
        open_vote_as_chair(r["id"], d1["id"])
        cast_ballot(r["id"], d1["id"], "FOR")
        resp = api.create_vote_record(
            {"resolution_id": r["id"], "channel": "MEETING_BALLOT", "vote": "AGAINST"},
            make_director_headers(d1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VOTE)
        after = get_success_data(api.get_resolution(r["id"], SECRETARY))
        assert after["for_count"] == 1
        assert after["against_count"] == 0


class TestResignedDirectorVoteRejected:
    def test_resigned_director_vote_rejected(self, api):
        """PRD §3.6: "the caster must be an `ACTIVE` director who is present
        at the meeting — an attendance record in any mode other than `ABSENT`
        — else `ERR_INELIGIBLE_VOTER` (HTTP 422)."

        Design: Corner/errors/resigned_director_vote_rejected
        """
        corp, _bylaws, directors = setup_corporation_with_directors(2, name="Corp R3")
        d1, d2 = directors
        m = setup_in_session_meeting(corp["id"], d1["id"], [d1["id"], d2["id"]])
        r = create_meeting_resolution(corp["id"], m["id"], title="R", text="t")
        table_resolution(r["id"])
        open_vote_as_chair(r["id"], d1["id"])
        # D2 resigns mid-session.
        api.resign_director(d2["id"], SECRETARY)
        resp = api.create_vote_record(
            {"resolution_id": r["id"], "channel": "MEETING_BALLOT", "vote": "FOR"},
            make_director_headers(d2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INELIGIBLE_VOTER)
        after = get_success_data(api.get_resolution(r["id"], SECRETARY))
        assert after["for_count"] == 0


class TestAdjournWithOpenVoteRejected:
    def test_adjourn_with_open_vote_rejected(self, api):
        """PRD §3.4: "Adjournment, again a chair-only act requiring the caller
        to be the meeting's `chair_director_id`, closes an `IN_SESSION`
        meeting — but only when no resolution of the meeting still stands
        `VOTE_OPEN`; adjourning over an open vote is
        `ERR_UNRESOLVED_VOTES_EXIST` (HTTP 409)."

        Design: Corner/errors/adjourn_with_open_vote_rejected
        """
        corp, _bylaws, directors = setup_corporation_with_directors(2, name="Corp R4")
        d1, d2 = directors
        m = setup_in_session_meeting(corp["id"], d1["id"], [d1["id"], d2["id"]])
        r = create_meeting_resolution(corp["id"], m["id"], title="R", text="t")
        table_resolution(r["id"])
        open_vote_as_chair(r["id"], d1["id"])
        resp = api.adjourn_meeting(m["id"], make_chair_headers(d1["id"]))
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_VOTES_EXIST)
        m_after = get_success_data(api.get_meeting(m["id"], SECRETARY))
        assert m_after["status"] == "IN_SESSION"

    def test_failed_adjourn_creates_no_minutes(self, api):
        """PRD §3.4: "The moment a meeting moves `IN_SESSION` → `ADJOURNED`,
        the server auto-creates its Minutes record in `DRAFT`" — a failed
        adjourn leaves the meeting IN_SESSION and materializes no minutes row.

        Design: Corner/errors/adjourn_with_open_vote_rejected
        """
        corp, _bylaws, directors = setup_corporation_with_directors(2, name="Corp R4b")
        d1, d2 = directors
        m = setup_in_session_meeting(corp["id"], d1["id"], [d1["id"], d2["id"]])
        r = create_meeting_resolution(corp["id"], m["id"], title="R", text="t")
        table_resolution(r["id"])
        open_vote_as_chair(r["id"], d1["id"])
        api.adjourn_meeting(m["id"], make_chair_headers(d1["id"]))
        resp = api.list_minutes(SECRETARY, params={"meeting_id": m["id"]})
        _rows, meta = validate_paginated(resp)
        assert meta["total_count"] == 0


class TestConveneBeforeScheduledStart:
    def test_convene_before_scheduled_start_rejected(self, api):
        """PRD §3.4: "the current clock must have reached `scheduled_start` —
        convening early is `ERR_MEETING_NOT_YET` (HTTP 422)."

        Design: Corner/errors/convene_before_scheduled_start_rejected
        """
        corp, _bylaws, directors = setup_corporation_with_directors(1, name="Corp R5")
        d1 = directors[0]
        m = schedule_noticed_meeting(corp["id"], d1["id"])
        set_clock("2026-06-20T09:59:59Z")
        resp = api.convene_meeting(m["id"], make_chair_headers(d1["id"]))
        validate_error(resp, ApiErrorId.ERR_MEETING_NOT_YET)
        after = get_success_data(api.get_meeting(m["id"], SECRETARY))
        assert after["status"] == "NOTICED"


class TestClearDisclosureWithUnadoptedResolution:
    def test_clear_disclosure_with_unadopted_resolution_rejected(self, api):
        """PRD §3.8: "When the filing recorded a `clearing_resolution_id`,
        clearance is blocked until that resolution stands `ADOPTED` or
        `CONSENT_ADOPTED`; clearing early is
        `ERR_CLEARING_RESOLUTION_NOT_ADOPTED` (HTTP 422)."

        Design: Corner/errors/clear_disclosure_with_unadopted_resolution_rejected
        """
        corp, _bylaws, directors = setup_corporation_with_directors(1, name="Corp RB2")
        d1 = directors[0]
        r = create_consent_resolution(corp["id"], title="Clearing res", text="t")
        cd = file_disclosure(
            d1["id"],
            corp["id"],
            related_party="Acme",
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-06-30T00:00:00Z",
            clearing_resolution_id=r["id"],
        )
        resp = api.clear_conflict_disclosure(cd["id"], SECRETARY)
        validate_error(resp, ApiErrorId.ERR_CLEARING_RESOLUTION_NOT_ADOPTED)
        after = get_success_data(api.get_conflict_disclosure(cd["id"], SECRETARY))
        assert after["status"] == "OPEN"


class TestDuplicateAttendance:
    def test_duplicate_attendance_rejected(self, api):
        """PRD §3.4: "Only one record may exist per meeting-and-director pair;
        a second is `ERR_DUPLICATE_ATTENDANCE` (HTTP 409)."

        Design: Corner/errors/duplicate_attendance_rejected
        """
        corp, _bylaws, directors = setup_corporation_with_directors(1, name="Corp RC1")
        d1 = directors[0]
        m = schedule_noticed_meeting(corp["id"], d1["id"])
        record_attendance(m["id"], d1["id"], "IN_PERSON")
        resp = api.create_attendance_record(
            {"meeting_id": m["id"], "director_id": d1["id"], "attendance_mode": "REMOTE"},
            SECRETARY,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ATTENDANCE)


class TestDuplicateEmail:
    def test_duplicate_director_email_rejected_within_corporation(self, api):
        """PRD §3.2: "Email addresses are unique within a corporation, and a
        second appointment reusing one is refused with `ERR_DUPLICATE_EMAIL`
        (HTTP 409)."

        Design: Corner/errors/duplicate_director_email_rejected
        """
        from test_helpers import create_corporation

        corp_a = create_corporation(name="Corp EA")
        add_director(corp_a["id"], "D1", "d1@x.com")
        resp = api.create_director(
            {
                "corporation_id": corp_a["id"],
                "full_name": "D1dup",
                "email": "d1@x.com",
                "term_start": "2026-01-01T00:00:00Z",
                "term_end": "2029-01-01T00:00:00Z",
            },
            SECRETARY,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL)

    def test_same_email_in_another_corporation_succeeds(self, api):
        """PRD §3.2: "Email addresses are unique within a corporation" — the
        uniqueness scope is per-corporation, so another corporation may reuse
        the address.

        Design: Corner/errors/duplicate_director_email_rejected
        """
        from test_helpers import create_corporation

        corp_a = create_corporation(name="Corp EA2")
        corp_b = create_corporation(name="Corp EB2", incorporation_state="CA")
        add_director(corp_a["id"], "D1", "d1@x.com")
        resp = api.create_director(
            {
                "corporation_id": corp_b["id"],
                "full_name": "D1other",
                "email": "d1@x.com",
                "term_start": "2026-01-01T00:00:00Z",
                "term_end": "2029-01-01T00:00:00Z",
            },
            SECRETARY,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ACTIVE"


class TestCrossCorporationReference:
    def test_cross_corporation_reference_rejected(self, api):
        """PRD §2.9: "A payload that points a corporation's resource at
        another corporation's director, committee, meeting, or resolution is
        rejected with `ERR_CROSS_CORPORATION_REFERENCE` (HTTP 422)."

        Design: Corner/validations/cross_corporation_reference_rejected
        """
        from test_helpers import create_corporation

        corp_a = create_corporation(name="Corp A")
        corp_b = create_corporation(name="Corp B", incorporation_state="CA")
        d1 = add_director(corp_a["id"], "D1", "d1@x.com")
        m_a = schedule_meeting(corp_a["id"], d1["id"])
        resp = api.create_resolution(
            {
                "corporation_id": corp_b["id"],
                "meeting_id": m_a["id"],
                "origin": "MEETING",
                "resolution_type": "ORDINARY",
                "title": "X",
                "text": "t",
            },
            SECRETARY,
        )
        validate_error(resp, ApiErrorId.ERR_CROSS_CORPORATION_REFERENCE)


class TestProxyHolderIneligible:
    def _setup(self, api):
        corp, _bylaws, directors = setup_corporation_with_directors(3, name="Corp V6")
        d1, d2, d3 = directors
        m = schedule_noticed_meeting(corp["id"], d1["id"])
        # D2 resigns so that naming D2 as proxy holder is ineligible.
        api.resign_director(d2["id"], SECRETARY)
        return corp, d1, d2, d3, m

    def test_resigned_proxy_holder_rejected(self, api):
        """PRD §3.4: "A `PROXY` record is valid only when
        `proxy_holder_director_id` is present, names someone other than the
        attendee, and names an `ACTIVE` director of the same corporation —
        otherwise `ERR_PROXY_HOLDER_INELIGIBLE` (HTTP 422)."

        Design: Corner/validations/proxy_holder_ineligible_rejected
        """
        _corp, _d1, d2, d3, m = self._setup(api)
        resp = api.create_attendance_record(
            {
                "meeting_id": m["id"],
                "director_id": d3["id"],
                "attendance_mode": "PROXY",
                "proxy_holder_director_id": d2["id"],
            },
            SECRETARY,
        )
        validate_error(resp, ApiErrorId.ERR_PROXY_HOLDER_INELIGIBLE)

    def test_active_proxy_holder_accepted(self, api):
        """PRD §3.4: "A `PROXY` record is valid only when
        `proxy_holder_director_id` is present, names someone other than the
        attendee, and names an `ACTIVE` director of the same corporation."

        Design: Corner/validations/proxy_holder_ineligible_rejected
        """
        _corp, d1, _d2, d3, m = self._setup(api)
        resp = api.create_attendance_record(
            {
                "meeting_id": m["id"],
                "director_id": d3["id"],
                "attendance_mode": "PROXY",
                "proxy_holder_director_id": d1["id"],
            },
            SECRETARY,
        )
        data = validate_success(resp, expected_status=201)
        assert data["attendance_mode"] == "PROXY"


class TestAuditCommitteeIndependence:
    def _setup(self, api):
        corp, _bylaws = setup_corporation_with_adopted_bylaws(name="Corp V3")
        d1 = add_director(corp["id"], "D1", "d1@x.com")
        ca = setup_active_committee(corp["id"], name="Audit", committee_type="AUDIT", quorum_fixed_count=1)
        cn = setup_active_committee(corp["id"], name="Nom", committee_type="NOMINATING", quorum_fixed_count=1)
        return corp, d1, ca, cn

    def test_pending_review_blocked_from_audit_committee(self, api):
        """PRD §3.3: "an `AUDIT` committee admits only directors whose
        `independence_status` is `INDEPENDENT`
        (`ERR_AUDIT_COMMITTEE_INDEPENDENCE`, HTTP 422)."

        Design: Corner/validations/audit_committee_independence_conditional
        """
        _corp, d1, ca, _cn = self._setup(api)
        resp = api.create_committee_membership(
            {
                "committee_id": ca["id"],
                "director_id": d1["id"],
                "committee_role": "MEMBER",
                "term_start": "2026-02-01T00:00:00Z",
                "term_end": "2027-02-01T00:00:00Z",
            },
            SECRETARY,
        )
        validate_error(resp, ApiErrorId.ERR_AUDIT_COMMITTEE_INDEPENDENCE)

    def test_pending_review_accepted_by_non_audit_committee(self, api):
        """PRD §3.3: "an `AUDIT` committee admits only directors whose
        `independence_status` is `INDEPENDENT`" — the gate is conditional on
        committee_type; other committee kinds do not apply it.

        Design: Corner/validations/audit_committee_independence_conditional
        """
        _corp, d1, _ca, cn = self._setup(api)
        resp = api.create_committee_membership(
            {
                "committee_id": cn["id"],
                "director_id": d1["id"],
                "committee_role": "MEMBER",
                "term_start": "2026-02-01T00:00:00Z",
                "term_end": "2027-02-01T00:00:00Z",
            },
            SECRETARY,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ACTIVE"

    def test_independent_director_accepted_by_audit_after_review(self, api):
        """PRD §3.2: "The secretary reviews a director and sets
        `independence_status` to `INDEPENDENT`"; §3.3: the AUDIT gate admits
        INDEPENDENT directors.

        Design: Corner/validations/audit_committee_independence_conditional
        """
        _corp, d1, ca, _cn = self._setup(api)
        api.review_independence(d1["id"], {"independence_status": "INDEPENDENT"}, SECRETARY)
        resp = api.create_committee_membership(
            {
                "committee_id": ca["id"],
                "director_id": d1["id"],
                "committee_role": "MEMBER",
                "term_start": "2026-02-01T00:00:00Z",
                "term_end": "2027-02-01T00:00:00Z",
            },
            SECRETARY,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ACTIVE"


class TestSeatCapacityEnforced:
    def test_seat_capacity_enforced_at_appointment(self, api):
        """PRD §3.2: "if adding the newcomer would push that occupancy above
        the adopted bylaws' `board_seat_count` at any moment, the appointment
        is rejected with `ERR_SEAT_CAPACITY_EXCEEDED` (HTTP 422). Reaching
        exactly the seat ceiling everywhere is permitted — only exceeding it
        fails."

        Design: Corner/validations/seat_capacity_enforced_at_appointment
        """
        corp, _bylaws = setup_corporation_with_adopted_bylaws(name="Corp V1", board_seat_count=2)
        add_director(corp["id"], "D1", "d1@x.com")
        add_director(corp["id"], "D2", "d2@x.com")
        resp = api.create_director(
            {
                "corporation_id": corp["id"],
                "full_name": "D3",
                "email": "d3@x.com",
                "term_start": "2026-06-01T00:00:00Z",
                "term_end": "2028-06-01T00:00:00Z",
            },
            SECRETARY,
        )
        validate_error(resp, ApiErrorId.ERR_SEAT_CAPACITY_EXCEEDED)
        corp_after = get_success_data(api.get_corporation(corp["id"], SECRETARY))
        assert corp_after["active_director_count"] == 2


class TestRotationLimit:
    def _setup(self, api):
        corp, _bylaws = setup_corporation_with_adopted_bylaws(name="Corp V4", rotation_max_years=2)
        d1 = add_director(corp["id"], "D1", "d1@x.com")
        cm = setup_active_committee(corp["id"], name="C", committee_type="SPECIAL", quorum_fixed_count=1)
        # First 365-day membership already ENDED.
        mb0 = add_membership(
            cm["id"], d1["id"], committee_role="MEMBER",
            term_start="2026-01-01T00:00:00Z", term_end="2027-01-01T00:00:00Z",
        )
        api.end_committee_membership(mb0["id"], SECRETARY)
        return corp, d1, cm

    def test_rotation_limit_exceeded(self, api):
        """PRD §3.3: "The running total is rounded half up to two decimal
        places, and if that figure strictly exceeds the adopted bylaws'
        `rotation_max_years` the add is refused with
        `ERR_ROTATION_LIMIT_EXCEEDED` (HTTP 422); a total landing exactly on
        the limit passes."

        Prior 1.00y + proposed 2026-06-01 -> 2027-07-01 (395 days = 1.08y) = 2.08 > 2 -> reject.

        Design: Corner/validations/rotation_limit_enforced_on_reappointment
        """
        _corp, d1, cm = self._setup(api)
        resp = api.create_committee_membership(
            {
                "committee_id": cm["id"],
                "director_id": d1["id"],
                "committee_role": "MEMBER",
                "term_start": "2026-06-01T00:00:00Z",
                "term_end": "2027-07-01T00:00:00Z",
            },
            SECRETARY,
        )
        validate_error(resp, ApiErrorId.ERR_ROTATION_LIMIT_EXCEEDED)

    def test_rotation_exactly_at_limit_allowed(self, api):
        """PRD §3.3: "a total landing exactly on the limit passes." Prior
        1.00y + proposed 2026-06-01 -> 2027-06-01 (365 days = 1.00y) = 2.00 == 2
        -> allowed.

        Design: Corner/validations/rotation_limit_enforced_on_reappointment
        """
        _corp, d1, cm = self._setup(api)
        resp = api.create_committee_membership(
            {
                "committee_id": cm["id"],
                "director_id": d1["id"],
                "committee_role": "MEMBER",
                "term_start": "2026-06-01T00:00:00Z",
                "term_end": "2027-06-01T00:00:00Z",
            },
            SECRETARY,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ACTIVE"


class TestMembershipRequiresDirectorActive:
    def test_membership_requires_director_active(self, api):
        """PRD §3.3: "Four guards protect the add, beyond the schema and
        existence tiers: the director must be `ACTIVE`
        (`ERR_DIRECTOR_NOT_ACTIVE`, HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/membership_requires_director_active
        """
        corp, _bylaws = setup_corporation_with_adopted_bylaws(name="Corp CE2")
        d1 = add_director(corp["id"], "D1", "d1@x.com")
        cm = setup_active_committee(corp["id"], name="Nom", committee_type="NOMINATING", quorum_fixed_count=1)
        api.resign_director(d1["id"], SECRETARY)
        resp = api.create_committee_membership(
            {
                "committee_id": cm["id"],
                "director_id": d1["id"],
                "committee_role": "MEMBER",
                "term_start": "2026-06-01T00:00:00Z",
                "term_end": "2027-06-01T00:00:00Z",
            },
            SECRETARY,
        )
        validate_error(resp, ApiErrorId.ERR_DIRECTOR_NOT_ACTIVE)
        cm_after = get_success_data(api.get_committee(cm["id"], SECRETARY))
        assert cm_after["active_member_count"] == 0
