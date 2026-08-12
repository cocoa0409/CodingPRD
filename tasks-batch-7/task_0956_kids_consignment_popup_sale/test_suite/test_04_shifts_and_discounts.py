"""Volunteer shifts, signups, the discount ladder, and presale pass pinning."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_phase,
    check_in_signup,
    check_out_signup,
    checked_in_shift_signup,
    complete_shift_signup,
    create_event,
    create_shift,
    get_shift,
    get_volunteer,
    issue_passes,
    make_volunteer_headers,
    register_volunteer,
    set_clock,
    sign_up,
    validate_error,
    validate_success,
)


def _walk_to_intake_closed(event_id):
    set_clock("2026-06-03T18:00:00Z")
    advance_phase(event_id, "INTAKE_OPEN")
    advance_phase(event_id, "INTAKE_CLOSED")


class TestShiftSignupOverlap:

    def test_adjacent_shifts_do_not_conflict(self, api, volunteer_headers):
        """PRD §3.6: "Shift windows are half-open, so adjacency is not a conflict: a new shift starting exactly when an existing one ends is allowed."

        Design: Difficulty/resource_temporal_overlap/shift_signup_half_open_adjacency
        """
        event = create_event()
        sam = register_volunteer(event["id"], "Sam")
        shift_a = create_shift(event["id"], start_time="2026-05-28T08:00:00Z",
                               end_time="2026-05-28T12:00:00Z", role_name="Floor")
        shift_b = create_shift(event["id"], start_time="2026-05-28T12:00:00Z",
                               end_time="2026-05-28T14:00:00Z", role_name="Floor")

        su_a = sign_up(shift_a["id"], sam["id"])
        su_b = sign_up(shift_b["id"], sam["id"])
        assert su_a["status"] == "SIGNED_UP"
        assert su_b["status"] == "SIGNED_UP", (
            "A shift starting exactly when the existing one ends (12:00 == 12:00) "
            "is not a conflict under half-open semantics"
        )

    def test_partial_overlap_rejected(self, api, volunteer_headers):
        """PRD §3.6: "a signup is rejected with `ERR_SHIFT_OVERLAP` when the volunteer already holds a signup in `SIGNED_UP` or `CHECKED_IN` whose shift overlaps the requested one — overlap meaning the existing shift's `start_time` falls before the new shift's `end_time` and the new shift's `start_time` falls before the existing shift's `end_time`."

        Design: Difficulty/resource_temporal_overlap/shift_signup_half_open_adjacency
        """
        event = create_event()
        sam = register_volunteer(event["id"], "Sam")
        shift_a = create_shift(event["id"], start_time="2026-05-28T08:00:00Z",
                               end_time="2026-05-28T12:00:00Z", role_name="Floor")
        shift_b = create_shift(event["id"], start_time="2026-05-28T12:00:00Z",
                               end_time="2026-05-28T14:00:00Z", role_name="Floor")
        shift_c = create_shift(event["id"], start_time="2026-05-28T11:00:00Z",
                               end_time="2026-05-28T13:00:00Z", role_name="Floor")
        su_a = sign_up(shift_a["id"], sam["id"])
        su_b = sign_up(shift_b["id"], sam["id"])

        resp = api.create_shift_signup(
            {"shift_id": shift_c["id"], "volunteer_id": sam["id"]},
            make_volunteer_headers(sam["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)
        assert su_a["status"] == "SIGNED_UP" and su_b["status"] == "SIGNED_UP"


class TestSignupLifecycle:

    def test_check_out_without_check_in_rejected(self, api, organizer_headers):
        """PRD §3.6: "Check-out moves `CHECKED_IN` → `COMPLETED` (any other source state yields `ERR_SIGNUP_WRONG_STATE`)".
        PRD §3.6: "A volunteer's `completed_hours` is the sum of `hours_credited` over their signups in `COMPLETED` status".

        Design: Corner/state_machines/signup_check_out_without_check_in_rejected
        """
        event = create_event()
        sam = register_volunteer(event["id"], "Sam")
        shift = create_shift(event["id"])
        signup = sign_up(shift["id"], sam["id"])

        resp = api.check_out_shift_signup(signup["id"], organizer_headers)
        validate_error(resp, ApiErrorId.ERR_SIGNUP_WRONG_STATE)

        after = validate_success(api.get_shift_signup(signup["id"], organizer_headers))
        assert after["status"] == "SIGNED_UP", (
            "A rejected check-out must leave the signup SIGNED_UP"
        )
        assert get_volunteer(sam["id"])["completed_hours"] == 0, (
            "No hours may be credited by a rejected check-out"
        )

    def test_no_show_before_shift_end_rejected(self, api, organizer_headers):
        """PRD §3.6: "An organizer may also mark a `SIGNED_UP` signup as `NO_SHOW`, but only once the logical clock has passed the shift's `end_time`; an earlier attempt is rejected with `ERR_NO_SHOW_TOO_EARLY`. A no-show likewise decrements `signed_up_count`."
        PRD §2.5: "At startup, before any clock call has been made, the logical clock reads exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock time thereafter."

        Design: Corner/errors/no_show_before_shift_end_rejected
        """
        event = create_event()
        sam = register_volunteer(event["id"], "Sam")
        shift = create_shift(event["id"], start_time="2026-05-28T09:00:00Z",
                             end_time="2026-05-28T13:00:00Z", role_name="Floor")
        signup = sign_up(shift["id"], sam["id"])
        # Clock untouched at the 2026-05-01T00:00:00Z startup default.
        resp = api.mark_no_show_shift_signup(signup["id"], organizer_headers)
        validate_error(resp, ApiErrorId.ERR_NO_SHOW_TOO_EARLY)
        assert validate_success(
            api.get_shift_signup(signup["id"], organizer_headers)
        )["status"] == "SIGNED_UP"

        set_clock("2026-05-28T13:00:01Z")  # past the shift's end_time
        no_show = validate_success(
            api.mark_no_show_shift_signup(signup["id"], organizer_headers)
        )
        assert no_show["status"] == "NO_SHOW"
        assert get_shift(shift["id"])["signed_up_count"] == 0, (
            "A no-show decrements signed_up_count"
        )


class TestDiscountTierBoundary:

    def _setup_two_volunteers(self, api):
        """Uma completes two 4h shifts (8.00h); Oda completes 4h + 3.5h (7.50h)."""
        event = create_event()
        uma = register_volunteer(event["id"], "Uma")
        oda = register_volunteer(event["id"], "Oda")
        sh_a = create_shift(event["id"], start_time="2026-05-28T09:00:00Z",
                            end_time="2026-05-28T13:00:00Z")   # 4h
        sh_b = create_shift(event["id"], start_time="2026-05-29T09:00:00Z",
                            end_time="2026-05-29T13:00:00Z")   # 4h
        sh_c = create_shift(event["id"], start_time="2026-05-29T13:00:00Z",
                            end_time="2026-05-29T16:30:00Z")   # 3.5h
        for shift_id, vol_id in ((sh_a["id"], uma["id"]), (sh_b["id"], uma["id"]),
                                 (sh_a["id"], oda["id"]), (sh_c["id"], oda["id"])):
            su = sign_up(shift_id, vol_id)
            check_in_signup(su["id"])
            check_out_signup(su["id"])
        _walk_to_intake_closed(event["id"])
        issue_passes(event["id"])
        return event, uma, oda

    def test_eight_hours_exactly_earns_15_percent(self, api, organizer_headers):
        """PRD §3.6: "The earned tier reads `completed_hours`: twelve hours or more earns a 20 percent discount; eight hours or more earns 15; four hours or more earns 10; anything less earns the 5 percent base."
        PRD §3.7: "A volunteer earns a pass when at least one of their signups is in `CHECKED_IN` or `COMPLETED`, and their pass carries a `discount_pct` equal to the earned discount tier computed from `completed_hours` at the moment of issuance."

        Design: Difficulty/boundary_precision_check/volunteer_discount_eight_hour_boundary
        """
        event, uma, _oda = self._setup_two_volunteers(api)
        uma_after = get_volunteer(uma["id"])
        assert uma_after["completed_hours"] == 8.0

        passes = validate_success(
            api.list_presale_passes(organizer_headers,
                                    params={"sale_event_id": event["id"],
                                            "holder_id": uma["id"]})
        )
        assert len(passes) == 1
        assert passes[0]["discount_pct"] == 15, (
            f"Exactly 8.00 completed hours is inside the '8 or more' tier; "
            f"got {passes[0]['discount_pct']}"
        )

    def test_seven_and_a_half_hours_earns_10_percent(self, api, organizer_headers):
        """PRD §3.6: "The earned tier reads `completed_hours`: twelve hours or more earns a 20 percent discount; eight hours or more earns 15; four hours or more earns 10; anything less earns the 5 percent base."
        PRD §3.7: "their pass carries a `discount_pct` equal to the earned discount tier computed from `completed_hours` at the moment of issuance."

        Design: Difficulty/boundary_precision_check/volunteer_discount_eight_hour_boundary
        """
        event, _uma, oda = self._setup_two_volunteers(api)
        oda_after = get_volunteer(oda["id"])
        assert oda_after["completed_hours"] == 7.5

        passes = validate_success(
            api.list_presale_passes(organizer_headers,
                                    params={"sale_event_id": event["id"],
                                            "holder_id": oda["id"]})
        )
        assert len(passes) == 1
        assert passes[0]["discount_pct"] == 10, (
            f"7.50 completed hours falls in the '4 or more' tier; "
            f"got {passes[0]['discount_pct']}"
        )


class TestProjectedVsEarnedDiscount:

    def _setup_vic(self):
        """Vic: one 4h shift COMPLETED, one 4h shift CHECKED_IN; event INTAKE_CLOSED."""
        event = create_event()
        vic = register_volunteer(event["id"], "Vic")
        complete_shift_signup(event["id"], vic["id"],
                              start_time="2026-05-28T09:00:00Z",
                              end_time="2026-05-28T13:00:00Z")
        checked_in_shift_signup(event["id"], vic["id"],
                                start_time="2026-05-29T09:00:00Z",
                                end_time="2026-05-29T13:00:00Z")
        _walk_to_intake_closed(event["id"])
        return event, vic

    def test_projected_hours_include_checked_in_shifts(self, api, organizer_headers):
        """PRD §3.6: "A volunteer's `completed_hours` is the sum of `hours_credited` over their signups in `COMPLETED` status; their `projected_hours` adds, on top of that, the shift durations of their signups still in `CHECKED_IN`."
        PRD §3.6: "The volunteer's `projected_discount_pct` applies the same ladder to `projected_hours`, giving a forward-looking read model of what the volunteer is on track to hold."

        Design: Difficulty/dual_variant_calc/volunteer_projected_vs_earned_discount
        """
        _event, vic = self._setup_vic()
        vic_after = get_volunteer(vic["id"])
        assert vic_after["completed_hours"] == 4.0
        assert vic_after["projected_hours"] == 8.0, (
            "projected_hours must add the CHECKED_IN shift's 4h on top of the "
            "4.0 completed hours"
        )
        assert vic_after["projected_discount_pct"] == 15, (
            "The projected variant applies the ladder to 8.0 projected hours"
        )

    def test_issued_pass_pins_earned_tier_only(self, api, organizer_headers):
        """PRD §3.7: "A volunteer earns a pass when at least one of their signups is in `CHECKED_IN` or `COMPLETED`, and their pass carries a `discount_pct` equal to the earned discount tier computed from `completed_hours` at the moment of issuance."
        PRD §3.6: "an issued pass pins the earned tier forever, while `projected_discount_pct` keeps moving as shifts are checked in and out."

        Design: Difficulty/dual_variant_calc/volunteer_projected_vs_earned_discount
        """
        event, vic = self._setup_vic()
        issue_passes(event["id"])
        passes = validate_success(
            api.list_presale_passes(organizer_headers,
                                    params={"sale_event_id": event["id"],
                                            "holder_id": vic["id"]})
        )
        assert len(passes) == 1
        assert passes[0]["discount_pct"] == 10, (
            "The pass pins the earned variant (4.0 completed hours -> 10), not "
            f"the projected variant (8.0 -> 15); got {passes[0]['discount_pct']}"
        )
        assert passes[0]["discount_pct"] != get_volunteer(vic["id"])["projected_discount_pct"]


class TestPassPinning:

    def test_pass_discount_pinned_after_more_hours(self, api, organizer_headers):
        """PRD §3.7: "Pinning is absolute: a pass's `discount_pct` never changes after issuance, no matter how many hours the volunteer later completes or forfeits."
        PRD §3.6: "an issued pass pins the earned tier forever, while `projected_discount_pct` keeps moving as shifts are checked in and out."

        Design: Corner/complexity_layers/presale_pass_discount_pinned_after_more_hours
        """
        event = create_event()
        vic = register_volunteer(event["id"], "Vic")
        complete_shift_signup(event["id"], vic["id"],
                              start_time="2026-05-28T09:00:00Z",
                              end_time="2026-05-28T13:00:00Z")  # 4h completed
        _walk_to_intake_closed(event["id"])
        issue_passes(event["id"])
        passes = validate_success(
            api.list_presale_passes(organizer_headers,
                                    params={"sale_event_id": event["id"],
                                            "holder_id": vic["id"]})
        )
        assert len(passes) == 1
        pass_id = passes[0]["id"]
        assert passes[0]["discount_pct"] == 10

        # Second 4h shift completed after issuance.
        complete_shift_signup(event["id"], vic["id"],
                              start_time="2026-05-29T09:00:00Z",
                              end_time="2026-05-29T13:00:00Z")
        vic_after = get_volunteer(vic["id"])
        assert vic_after["completed_hours"] == 8.0
        assert vic_after["projected_discount_pct"] == 15

        pinned = validate_success(api.get_presale_pass(pass_id, organizer_headers))
        assert pinned["discount_pct"] == 10, (
            "An issued pass's discount_pct never changes, even after the "
            "volunteer's earned tier rises to 15"
        )
