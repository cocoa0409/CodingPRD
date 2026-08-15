"""Deadline docketing: dual computation variants, timely/late satisfy boundary,
verify segregation, the MISSED jeopardy cascade, extension cap, and listing."""
import pytest

from test_helpers import (
    ApiErrorId,
    assess_alert,
    assert_deadline,
    assert_instant_equal,
    create_alert,
    docket_deadline,
    get_alert,
    get_client,
    get_deadline,
    get_matter,
    make_associate_headers,
    make_paralegal_headers,
    make_partner_headers,
    satisfy_deadline,
    set_clock,
    setup_escalated_matter,
    triage_alert,
    validate_error,
    validate_paginated,
    validate_success,
    verify_deadline,
)


class TestComputationVariants:
    def test_opposition_window_deadline_uses_calendar_roll_forward(self, api):
        """PRD §2.8: "`CALENDAR_ROLL_FORWARD` counts calendar days from the basis
        date and then, while the resulting instant falls on a Saturday or Sunday (in
        UTC), rolls it forward one calendar day at a time until it lands on a
        weekday. A Friday basis with a five-day offset therefore lands on the
        following Wednesday with no roll needed. This variant applies to
        `OPPOSITION_WINDOW` and `RENEWAL` deadlines and to the record's
        `opposition_due_at`."
        PRD §2.8: "The computation variant of a deadline is derived from its
        `deadline_type` at docketing — it is never supplied by the caller — and
        extensions reuse the deadline's own variant, treating the current
        `computed_due_at` as the new basis."

        Design: Difficulty/dual_variant_calc/calendar_rollforward_vs_business_day_deadline
        """
        _, _, _, matter = setup_escalated_matter()
        res = api.docket_deadline(
            matter["id"],
            {
                "deadline_type": "OPPOSITION_WINDOW",
                "statutory_basis": "15 USC 1063",
                "basis_date": "2026-08-07T09:00:00Z",
                "offset_days": 5,
            },
            make_paralegal_headers("para_1"),
        )
        deadline = validate_success(res, 201)
        assert_deadline(deadline)
        assert deadline["computation_variant"] == "CALENDAR_ROLL_FORWARD"
        # Friday 2026-08-07 + 5 calendar days = Wednesday 2026-08-12 (no roll).
        assert_instant_equal(deadline["computed_due_at"], "2026-08-12T09:00:00Z",
                             "computed_due_at")

    def test_response_due_deadline_uses_business_day_count(self, api):
        """PRD §2.8: "`BUSINESS_DAY_COUNT` counts only business days, excluding the
        basis day itself: starting from the basis, advance one calendar day at a
        time, incrementing the count only for Monday-through-Friday days, until the
        count reaches the offset."
        PRD §2.8: "This variant applies to `RESPONSE_DUE`, `OFFICE_ACTION`, and
        `CUSTOM` deadlines and to the letter's `response_due_at`."

        Design: Difficulty/dual_variant_calc/calendar_rollforward_vs_business_day_deadline
        """
        _, _, _, matter = setup_escalated_matter()
        res = api.docket_deadline(
            matter["id"],
            {
                "deadline_type": "RESPONSE_DUE",
                "statutory_basis": "37 CFR 2.196",
                "basis_date": "2026-08-07T09:00:00Z",
                "offset_days": 5,
            },
            make_paralegal_headers("para_1"),
        )
        deadline = validate_success(res, 201)
        assert deadline["computation_variant"] == "BUSINESS_DAY_COUNT"
        # Business days Aug 10, 11, 12, 13, 14 (weekend skipped) -> 2026-08-14.
        assert_instant_equal(deadline["computed_due_at"], "2026-08-14T09:00:00Z",
                             "computed_due_at")

        cal = docket_deadline(matter["id"], deadline_type="OPPOSITION_WINDOW",
                              statutory_basis="15 USC 1063",
                              basis_date="2026-08-07T09:00:00Z", offset_days=5)
        assert deadline["computed_due_at"] != cal["computed_due_at"]


class TestSatisfyTimelinessBoundary:
    def _two_pending_deadlines(self, matter_id):
        dl_a = docket_deadline(matter_id, user_id="para_1")
        dl_b = docket_deadline(matter_id, user_id="para_1")
        verify_deadline(dl_a["id"], user_id="assoc_2")
        verify_deadline(dl_b["id"], user_id="assoc_2")
        return dl_a, dl_b

    def test_satisfy_exactly_at_due_is_timely(self, api, paralegal_headers):
        """PRD §3.5: "From `PENDING` or `EXTENDED`, a timely satisfy by a `Paralegal`
        (or partner) while the clock is at or before `computed_due_at` stamps
        `satisfied_at` and leaves `satisfied_late` false; the deadline reaches its
        terminal `SATISFIED` state."

        Design: Difficulty/boundary_precision_check/deadline_satisfy_exactly_at_due_is_timely
        """
        _, _, _, matter = setup_escalated_matter()
        dl_a, _ = self._two_pending_deadlines(matter["id"])
        # Both deadlines are due 2026-08-14T09:00:00Z (business-day count).
        set_clock("2026-08-14T09:00:00Z")
        res = api.satisfy_deadline(dl_a["id"], {}, paralegal_headers)
        satisfied = validate_success(res, 200)
        assert satisfied["status"] == "SATISFIED"
        assert satisfied["satisfied_late"] is False
        assert satisfied["satisfied_at"] is not None

    def test_one_second_after_due_the_sweep_marks_missed(self, api):
        """PRD §3.5: "The `MISSED` transition itself belongs to the clock sweep: when
        the logical clock passes `computed_due_at` on a `PENDING` or `EXTENDED`
        deadline, the deadline flips to `MISSED` and a jeopardy cascade fires."

        Design: Difficulty/boundary_precision_check/deadline_satisfy_exactly_at_due_is_timely
        """
        _, _, _, matter = setup_escalated_matter()
        _, dl_b = self._two_pending_deadlines(matter["id"])
        set_clock("2026-08-14T09:00:00Z")
        assert get_deadline(dl_b["id"])["status"] == "PENDING"
        set_clock("2026-08-14T09:00:01Z")
        assert get_deadline(dl_b["id"])["status"] == "MISSED"


class TestVerificationAndExtension:
    def test_deadline_verify_twice_returns_invalid_state(self, api):
        """PRD §3.5: "Verification moves a deadline from `DOCKETED` to `PENDING` and
        is performed by an `AssociateAttorney` or `PartnerAttorney` who must not be
        the docketing caller"
        PRD §2.10: "State — the target entity is in a state from which the requested
        transition is declared, including terminal-state lockdown, else
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/deadline_verify_twice_returns_invalid_state
        """
        _, _, _, matter = setup_escalated_matter()
        deadline = docket_deadline(matter["id"], user_id="para_1")
        verified = verify_deadline(deadline["id"], user_id="assoc_2")
        assert verified["status"] == "PENDING"

        res = api.verify_deadline(deadline["id"], make_associate_headers("assoc_2"))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_deadline(deadline["id"])["status"] == "PENDING"

    def test_associate_cannot_verify_own_docketed_deadline(self, api):
        """PRD §3.5: "Verification moves a deadline from `DOCKETED` to `PENDING` and
        is performed by an `AssociateAttorney` or `PartnerAttorney` who must not be
        the docketing caller; a self-verify is rejected with
        `ERR_SEGREGATION_OF_DUTIES`, and a successful verify stamps
        `verified_by_user_id` with the caller."
        PRD §2.1: "the caller verifying a deadline must differ from its
        `docketed_by_user_id`"

        Design: Corner/validations/associate_cannot_verify_own_docketed_deadline
        """
        _, _, _, matter = setup_escalated_matter()
        deadline = docket_deadline(matter["id"], user_id="assoc_1",
                                   role="AssociateAttorney")

        res = api.verify_deadline(deadline["id"], make_associate_headers("assoc_1"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

        verified = validate_success(
            api.verify_deadline(deadline["id"], make_partner_headers("partner_1")), 200)
        assert verified["status"] == "PENDING"
        assert verified["verified_by_user_id"] == "partner_1"

    def test_deadline_extend_cycle_and_cap(self, api, paralegal_headers):
        """PRD §3.5: "Extensions are a `Paralegal` action available from `PENDING`
        and from `EXTENDED` itself, carrying `additional_days`; each extension
        recomputes `computed_due_at` using the deadline's own variant with the
        current `computed_due_at` as the new basis, and increments
        `extension_count`. Once `extension_count` reaches `max_extensions`, further
        extension is rejected with `ERR_EXTENSION_CAP_REACHED`."
        PRD §3.5: "an optional `max_extensions` cap defaulting to 3"

        Design: Corner/state_machines/deadline_extend_cycle_and_cap
        """
        _, _, _, matter = setup_escalated_matter()
        deadline = docket_deadline(matter["id"], user_id="para_1")
        verify_deadline(deadline["id"], user_id="assoc_2")

        first = validate_success(
            api.extend_deadline(deadline["id"], {"additional_days": 3},
                                paralegal_headers), 200)
        # Business-day count from Fri 2026-08-14 09:00: Aug 17, 18, 19.
        assert_instant_equal(first["computed_due_at"], "2026-08-19T09:00:00Z",
                             "first extension computed_due_at")
        assert first["extension_count"] == 1
        assert first["status"] == "EXTENDED"

        validate_success(api.extend_deadline(deadline["id"], {"additional_days": 1},
                                             paralegal_headers), 200)
        third = validate_success(
            api.extend_deadline(deadline["id"], {"additional_days": 1},
                                paralegal_headers), 200)
        assert third["extension_count"] == 3
        assert third["status"] == "EXTENDED"

        res = api.extend_deadline(deadline["id"], {"additional_days": 1},
                                  paralegal_headers)
        validate_error(res, ApiErrorId.ERR_EXTENSION_CAP_REACHED, expected_status=422)
        after = get_deadline(deadline["id"])
        assert after["extension_count"] == 3
        assert after["status"] == "EXTENDED"


class TestMissedJeopardyCascade:
    def test_deadline_auto_missed_jeopardy_cascade(self, api):
        """PRD §3.5: "The `MISSED` transition itself belongs to the clock sweep: when
        the logical clock passes `computed_due_at` on a `PENDING` or `EXTENDED`
        deadline, the deadline flips to `MISSED` and a jeopardy cascade fires. The
        owning matter's `posture` becomes `JEOPARDY`; every sibling deadline of the
        same matter still in `DOCKETED`, `PENDING`, or `EXTENDED` has
        `requires_partner_review` set true; the matter's originating watch alert has
        `escalation_level` raised from `STANDARD` to `URGENT`; and the client's
        `exposure_index` is recomputed with the jeopardy multiplier applied."
        PRD §2.7: "with the weight of any matter in `JEOPARDY` posture multiplied by
        one and a half"

        Design: Corner/state_machines/deadline_auto_missed_jeopardy_cascade
        """
        client, _, alert, matter = setup_escalated_matter(classes=(9,))
        d1 = docket_deadline(matter["id"], basis_date="2026-08-07T09:00:00Z",
                             offset_days=5, user_id="para_1")
        d2 = docket_deadline(matter["id"], basis_date="2026-08-07T09:00:00Z",
                             offset_days=10, user_id="para_1")
        verify_deadline(d1["id"], user_id="assoc_2")
        verify_deadline(d2["id"], user_id="assoc_2")

        set_clock("2026-08-15T00:00:00Z")

        d1_after = get_deadline(d1["id"])
        assert d1_after["status"] == "MISSED"
        d2_after = get_deadline(d2["id"])
        assert d2_after["status"] == "PENDING"
        assert d2_after["requires_partner_review"] is True

        matter_after = get_matter(matter["id"])
        assert matter_after["posture"] == "JEOPARDY"
        assert get_alert(alert["id"])["escalation_level"] == "URGENT"
        # INFRINGEMENT weight 20 x JEOPARDY multiplier 1.5 == 30.
        assert get_client(client["id"])["exposure_index"] == 30


class TestDeadlineListing:
    def test_deadlines_filtered_list_isolated_per_matter(self, api, paralegal_headers):
        """PRD §3.5: "Deadlines are listed with `enforcement_matter_id` and `status`
        filters."

        Design: Corner/endpoints/deadlines_filtered_list_isolated_per_matter
        """
        _, _, _, matter1 = setup_escalated_matter(classes=(9,))
        d1 = docket_deadline(matter1["id"], deadline_type="RESPONSE_DUE",
                             offset_days=5, user_id="para_1")

        # Build a second matter from a second alert on the same record.
        record_id = matter1["trademark_record_id"]
        alert2 = create_alert(record_id, 80, 70, 60, conflicting_mark_text="AKME2")
        alert2 = triage_alert(alert2["id"])
        alert2 = assess_alert(alert2["id"], alert2["version"])
        res2 = api.escalate_alert(alert2["id"], {"matter_type": "INFRINGEMENT"},
                                  make_associate_headers("assoc_1"))
        matter2 = validate_success(res2, 201)
        d2 = docket_deadline(matter2["id"], deadline_type="OFFICE_ACTION",
                             statutory_basis="15 USC 1062", offset_days=10,
                             user_id="para_1")

        res = api.list_deadlines(paralegal_headers,
                                 params={"enforcement_matter_id": matter1["id"]})
        data, meta = validate_paginated(res)
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == d1["id"]
        assert data[0]["id"] != d2["id"]
