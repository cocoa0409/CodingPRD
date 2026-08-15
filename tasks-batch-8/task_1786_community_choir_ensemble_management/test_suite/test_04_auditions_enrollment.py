"""Audition booking, scoring, decisions, slot buffering, and section gates."""
from test_helpers import (
    ApiErrorId,
    audition_decision_payload,
    book_audition,
    create_member,
    create_open_season_with_section,
    enroll_member,
    issue_invoice,
    pay_dues,
    run_checkpoint,
    score_audition,
    set_clock,
    validate_error,
    validate_success,
)


class TestAuditionDecisionPreconditions:
    def test_decision_on_unscored_audition_rejected(self, api,
                                                    director_headers):
        """PRD §3.2: "The checks surface in validation-tier order: the audition
        must be `COMPLETED` before any decision, else
        `ERR_AUDITION_NOT_SCORED`"

        Design: Corner/state_machines/decision_on_unscored_audition_rejected
        """
        season, section = create_open_season_with_section()
        member = create_member(season["id"])
        audition = book_audition(member["id"])

        resp = api.decide_audition(
            audition["id"],
            audition_decision_payload("ACCEPT", section["id"]),
            director_headers,
        )
        validate_error(resp, ApiErrorId.ERR_AUDITION_NOT_SCORED)

        member_data = validate_success(api.get_member(member["id"],
                                                      director_headers))
        assert member_data["status"] == "AUDITION_SCHEDULED"

    def test_second_decision_on_decided_audition_rejected(self, api,
                                                          director_headers):
        """PRD §3.2: "a rejection moves them to `REJECTED`, which is terminal."
        PRD §2.8: "Eighth, target-state validity — the resource must be in a
        legal from-state for the requested transition or action, else
        `ERR_INVALID_STATE` or the more specific state-tier error named for
        that operation."

        Design: Corner/state_machines/second_decision_on_decided_audition_rejected
        """
        season, _section = create_open_season_with_section()
        member = create_member(season["id"])
        audition = book_audition(member["id"])
        score_audition(audition["id"])
        decided = validate_success(api.decide_audition(
            audition["id"], audition_decision_payload("REJECT"),
            director_headers))
        assert decided["decision"] == "REJECTED"

        resp = api.decide_audition(
            audition["id"], audition_decision_payload("REJECT"),
            director_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        member_data = validate_success(api.get_member(member["id"],
                                                      director_headers))
        assert member_data["status"] == "REJECTED", \
            "terminal member state unchanged by the rejected second decision"


class TestAuditionCancelAndNoShow:
    def test_audition_cancel_returns_member_to_applicant(self, api,
                                                         director_headers):
        """PRD §3.2: "If the singer cancels, the audition moves to `CANCELLED`
        and the member falls back to `APPLICANT`."
        PRD §3.2: "Audition slots are buffered: any two non-cancelled auditions
        of the same season must start at least `audition_slot_minutes` apart"

        Design: Corner/state_machines/audition_cancel_returns_member_to_applicant
        """
        season, _section = create_open_season_with_section()
        member = create_member(season["id"])
        audition = book_audition(member["id"], "2026-08-02T10:00:00Z")

        cancelled = validate_success(
            api.cancel_audition(audition["id"], director_headers))
        assert cancelled["status"] == "CANCELLED"

        member_data = validate_success(api.get_member(member["id"],
                                                      director_headers))
        assert member_data["status"] == "APPLICANT"

        # A cancelled slot no longer counts as non-cancelled: the same slot
        # is free for a fresh booking.
        rebooked = validate_success(api.create_audition(
            {"member_id": member["id"],
             "scheduled_at": "2026-08-02T10:00:00Z"},
            director_headers), 201)
        assert rebooked["status"] == "SCHEDULED"

    def test_audition_no_show_at_checkpoint(self, api, director_headers):
        """PRD §3.2: "If the slot passes unheld — at a checkpoint, an audition
        whose `scheduled_at` is earlier than the clock and which is still
        `SCHEDULED` — the audition becomes `NO_SHOW` and the member likewise
        returns to `APPLICANT`."

        Design: Corner/state_machines/audition_no_show_at_checkpoint
        """
        season, _section = create_open_season_with_section()
        member = create_member(season["id"])
        audition = book_audition(member["id"], "2026-08-02T10:00:00Z")
        set_clock("2026-08-05T00:00:00Z")

        run_checkpoint(season["id"])

        audition_data = validate_success(
            api.get_audition(audition["id"], director_headers))
        assert audition_data["status"] == "NO_SHOW"
        member_data = validate_success(api.get_member(member["id"],
                                                      director_headers))
        assert member_data["status"] == "APPLICANT"


class TestSectionGatesOnAccept:
    def test_section_full_blocks_accept(self, api, director_headers):
        """PRD §3.2: "and only then is the section's headroom checked, with a
        section whose `active_count` has reached `target_max` rejected as
        `ERR_SECTION_FULL`."
        PRD §3.1: "A section's `active_count` counts its members whose status
        is `ENROLLED`, `ACTIVE`, or `PROBATION`, and is recomputed whenever
        membership changes."

        Design: Corner/validations/section_full_blocks_accept
        """
        season, section = create_open_season_with_section(target_min=1,
                                                          target_max=1)
        # First member fills the single seat (ACTIVE still counts).
        m1 = enroll_member(season["id"], section["id"], "A One", "a1@x.org",
                           "2026-08-02T10:00:00Z")
        issue_invoice(m1["id"])
        pay_dues(m1["id"])
        section_data = validate_success(
            api.get_section(section["id"], director_headers))
        assert section_data["active_count"] == 1

        m2 = create_member(season["id"], "A Two", "a2@x.org")
        a2 = book_audition(m2["id"], "2026-08-02T11:00:00Z")
        score_audition(a2["id"])
        resp = api.decide_audition(
            a2["id"], audition_decision_payload("ACCEPT", section["id"]),
            director_headers)
        validate_error(resp, ApiErrorId.ERR_SECTION_FULL)

        member_data = validate_success(api.get_member(m2["id"],
                                                      director_headers))
        assert member_data["status"] == "AUDITIONED", \
            "rejected ACCEPT leaves the member AUDITIONED"

    def test_closed_section_blocks_accept(self, api, director_headers):
        """PRD §3.2: "for `ACCEPT` the caller names a target `section_id` whose
        status must be `OPEN`, else `ERR_SECTION_CLOSED`"
        PRD §3.1: "the director can later update `target_min` or `target_max`,
        or flip the section between `OPEN` and `CLOSED`. Closing a section both
        exempts it from the `OPEN` → `REHEARSING` balance gate and bars new
        audition acceptances into it."

        Design: Corner/validations/closed_section_blocks_accept
        """
        season, section = create_open_season_with_section()
        member = create_member(season["id"])
        audition = book_audition(member["id"])
        score_audition(audition["id"])
        closed = validate_success(api.patch_section(
            section["id"], {"status": "CLOSED"}, director_headers))
        assert closed["status"] == "CLOSED"

        resp = api.decide_audition(
            audition["id"],
            audition_decision_payload("ACCEPT", section["id"]),
            director_headers)
        validate_error(resp, ApiErrorId.ERR_SECTION_CLOSED)


class TestAuditionSlotBuffering:
    def test_audition_slot_buffered_overlap(self, api, director_headers):
        """PRD §3.2: "Audition slots are buffered: any two non-cancelled
        auditions of the same season must start at least
        `audition_slot_minutes` apart, so a new slot landing closer than that
        to an existing non-cancelled audition — in either direction — is
        rejected with `ERR_AUDITION_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/audition_slot_buffered_overlap
        """
        season, _section = create_open_season_with_section(
            audition_slot_minutes=30)
        m1 = create_member(season["id"], "A One", "a1@x.org")
        m2 = create_member(season["id"], "A Two", "a2@x.org")
        first = book_audition(m1["id"], "2026-08-02T10:00:00Z")
        assert first["status"] == "SCHEDULED"

        # 29 minutes after an existing slot: inside the 30-minute buffer.
        resp = api.create_audition(
            {"member_id": m2["id"], "scheduled_at": "2026-08-02T10:29:00Z"},
            director_headers)
        validate_error(resp, ApiErrorId.ERR_AUDITION_OVERLAP)

        # Exactly 30 minutes later satisfies "at least ... apart" (inclusive).
        second = validate_success(api.create_audition(
            {"member_id": m2["id"], "scheduled_at": "2026-08-02T10:30:00Z"},
            director_headers), 201)
        assert second["status"] == "SCHEDULED"

    def test_audition_slot_buffer_applies_in_either_direction(
            self, api, director_headers):
        """PRD §3.2: "a new slot landing closer than that to an existing
        non-cancelled audition — in either direction — is rejected with
        `ERR_AUDITION_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/audition_slot_buffered_overlap
        """
        season, _section = create_open_season_with_section(
            audition_slot_minutes=30)
        m1 = create_member(season["id"], "A One", "a1@x.org")
        m2 = create_member(season["id"], "A Two", "a2@x.org")
        m3 = create_member(season["id"], "A Three", "a3@x.org")
        book_audition(m1["id"], "2026-08-02T10:00:00Z")

        # Exactly 30 minutes BEFORE the existing slot: boundary is inclusive.
        early_ok = validate_success(api.create_audition(
            {"member_id": m2["id"], "scheduled_at": "2026-08-02T09:30:00Z"},
            director_headers), 201)
        assert early_ok["status"] == "SCHEDULED"

        # One minute inside the buffer in the earlier direction is rejected.
        resp = api.create_audition(
            {"member_id": m3["id"], "scheduled_at": "2026-08-02T09:59:00Z"},
            director_headers)
        validate_error(resp, ApiErrorId.ERR_AUDITION_OVERLAP)
