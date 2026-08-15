"""Shift planning and confirmation gates: half-open overlap, state priority,
segregation of duties, skills, and window shape (PRD §2.9, §3.3)."""
from test_helpers import (
    ApiErrorId,
    assert_shift,
    get_success_data,
    make_site_lead_headers,
    plan_shift,
    setup_cancelled_shift_scene,
    setup_opening_site_with_staff,
    setup_shift_overlap_scene,
    validate_error,
    validate_success,
    EOC_HEADERS,
)


class TestHalfOpenOverlap:
    def test_adjacent_shift_confirm_succeeds(self, api):
        """PRD §3.3: "And no other `CONFIRMED` shift of the same staff member
        may intersect this one's half-open window — shifts whose endpoints
        merely touch do not intersect — else `ERR_SHIFT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/staff_shift_half_open_adjacency_allowed_overlap_rejected
        """
        ws = setup_shift_overlap_scene()
        # S2 [04:00, 08:00) touches the CONFIRMED S1 [20:00, 04:00) at 04:00.
        resp = api.confirm_shift(ws["s2"]["id"], ws["lead1_headers"])
        data = validate_success(resp, 200)
        assert data["status"] == "CONFIRMED"

    def test_overlapping_shift_confirm_rejected(self, api):
        """PRD §3.3: "And no other `CONFIRMED` shift of the same staff member
        may intersect this one's half-open window — shifts whose endpoints
        merely touch do not intersect — else `ERR_SHIFT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/staff_shift_half_open_adjacency_allowed_overlap_rejected
        """
        ws = setup_shift_overlap_scene()
        # S3 [03:00, 05:00) genuinely intersects the CONFIRMED S1.
        resp = api.confirm_shift(ws["s3"]["id"], ws["lead1_headers"])
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP, expected_status=409)
        stay = get_success_data(api.get_shift(ws["s3"]["id"], EOC_HEADERS))
        assert stay["status"] == "PLANNED"


class TestStatePriorityOverConstraint:
    def test_confirm_of_cancelled_shift_returns_invalid_state(self, api):
        """PRD §2.9: "Fifth are state guards, evaluated parents-first —
        episode before site activation before stay or dispatch — yielding the
        transition-specific codes (`ERR_INVALID_STATE`, `ERR_EPISODE_NOT_ACTIVE`,
        `ERR_SITE_NOT_OPEN`, `ERR_TRIGGER_NOT_MET`, `ERR_DISPATCH_NOT_ARRIVED`,
        and `ERR_VALIDATION` for a pinned bed capacity below one at open)".
        PRD §2.9: "Seventh are uniqueness and segregation constraints: one
        active stay per guest per episode, one after-action report per
        episode, the three segregated pairs, staff shift overlap, vehicle
        window conflicts, same-episode transfer, the designated-site
        requirement at activation, and the incident/site gates on report
        submission." — the state guard is evaluated before the overlap
        constraint, so confirming a CANCELLED shift that would also overlap
        reports ERR_INVALID_STATE.

        Design: Difficulty/priority_pair_validation_conflict/cancelled_shift_state_outranks_overlap
        """
        ws = setup_cancelled_shift_scene()
        resp = api.confirm_shift(ws["s2"]["id"], ws["lead1_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_cancelled_shift_remains_cancelled_after_rejected_confirm(
            self, api):
        """PRD §2.9: "Fifth are state guards, evaluated parents-first —
        episode before site activation before stay or dispatch — yielding the
        transition-specific codes (`ERR_INVALID_STATE`, ...)" — a rejected
        confirm mutates nothing; the shift stays CANCELLED.

        Design: Difficulty/priority_pair_validation_conflict/cancelled_shift_state_outranks_overlap
        """
        ws = setup_cancelled_shift_scene()
        resp = api.confirm_shift(ws["s2"]["id"], ws["lead1_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        after = get_success_data(api.get_shift(ws["s2"]["id"], EOC_HEADERS))
        assert after["status"] == "CANCELLED"


class TestConfirmationGates:
    def test_sitelead_confirming_own_shift_segregation_rejected(self, api):
        """PRD §3.3: "The caller's `X-User-ID` must differ from the shift's
        `staff_member_id` — nobody confirms their own shift — else
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/sitelead_confirming_own_shift_segregation_rejected
        """
        ws = setup_opening_site_with_staff()
        lead1 = ws["lead1"]
        shift = plan_shift(ws["site_activation"]["id"], lead1["id"],
                           "SITE_LEAD", "2026-08-10T22:00:00Z",
                           "2026-08-11T06:00:00Z",
                           planner_headers=ws["lead1_headers"])
        resp = api.confirm_shift(shift["id"], make_site_lead_headers(lead1["id"]))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
                       expected_status=409)
        after = get_success_data(api.get_shift(shift["id"], EOC_HEADERS))
        assert after["status"] == "PLANNED"

    def test_confirm_shift_with_missing_skill_rejected(self, api):
        """PRD §3.3: "A `role_on_shift` other than `GENERAL` must appear in
        the staff member's `skills`, else `ERR_SKILL_MISMATCH`."

        Design: Corner/validations/confirm_shift_with_missing_skill_rejected
        """
        ws = setup_opening_site_with_staff()  # worker has INTAKE only
        shift = plan_shift(ws["site_activation"]["id"], ws["worker"]["id"],
                           "MEDICAL", "2026-08-10T20:00:00Z",
                           "2026-08-11T04:00:00Z",
                           planner_headers=ws["lead1_headers"])
        resp = api.confirm_shift(shift["id"], ws["lead1_headers"])
        validate_error(resp, ApiErrorId.ERR_SKILL_MISMATCH, expected_status=409)
        after = get_success_data(api.get_shift(shift["id"], EOC_HEADERS))
        assert_shift(after)
        assert after["status"] == "PLANNED"

    def test_shift_end_not_after_start_returns_invalid_window(self, api):
        """PRD §3.3: "A planned shift names the `staff_member_id`, a
        `role_on_shift` of `INTAKE`, `MEDICAL`, `OUTREACH`, `SITE_LEAD` or
        `GENERAL`, and a half-open window from `start_at` (inclusive) to
        `end_at` (exclusive); an `end_at` that is not strictly after
        `start_at` is rejected with `ERR_INVALID_WINDOW`."

        Design: Corner/validations/shift_end_not_after_start_returns_invalid_window
        """
        ws = setup_opening_site_with_staff()
        resp = api.create_shift(
            ws["site_activation"]["id"],
            {"staff_member_id": ws["worker"]["id"], "role_on_shift": "INTAKE",
             "start_at": "2026-08-10T20:00:00Z",
             "end_at": "2026-08-10T20:00:00Z"},
            ws["lead1_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW, expected_status=422)
