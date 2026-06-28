"""Validation-priority and cross-entity-dependency claims, plus the membership
OCC stale-version rejections and series-limit / membership-eligibility errors.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    fixtures,
    factories,
    make_member_headers,
    make_front_desk_headers,
    make_studio_manager_headers,
    make_flexologist_headers,
)

FD = make_front_desk_headers()
SM = make_studio_manager_headers()


# ===========================================================================
# priority_pair_validation_conflict
# ===========================================================================

class TestValidationPriority:
    def test_terminal_state_reported_when_confirm_completed_booking(self, api):
        """PRD §3.4: "Confirming a requested booking is permitted only when its `schedule_status` is `REQUESTED`, the member's `status` is `ACTIVE ..."
        PRD §3.4: "Attempting any transition from a status that does not permit it is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Confirming an already-COMPLETED booking (whose membership wallet also has
        0 available credits) reports the state failure ERR_INVALID_STATE — the
        confirm path enforces state, not a credit re-check.

        Design: Difficulty/priority_pair_validation_conflict/terminal_state_beats_insufficient_credits
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440)
        loc, flex, table, mem = s["loc"], s["flex"], s["table"], s["member"]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=2, list_price_cents=6000)
        ship = fixtures.create_membership(mem["id"], loc["id"], tier="STARTER",
                                          monthly_fee_cents=5000, included_credits=2,
                                          rollover_cap=0)
        bk = fixtures.create_completed_booking(mem["id"], loc["id"], svc["id"], flex["id"], table,
                                               "2026-04-12T10:00:00Z", "MEMBERSHIP", ship["id"],
                                               complete_clock="2026-04-12T10:30:00Z")
        # membership now has 0 available credits AND the booking is COMPLETED
        m = validate_success(api.get_membership(ship["id"], FD))
        assert m["available_credits"] == 0
        validate_error(api.confirm_booking(bk["id"], FD), ApiErrorId.ERR_INVALID_STATE.value)
        again = validate_success(api.get_booking(bk["id"], FD))
        assert again["schedule_status"] == "COMPLETED"

    def test_confirm_cancelled_booking_reports_invalid_state(self, api):
        """PRD §3.4: "Confirming a requested booking is permitted only when its `schedule_status` is `REQUESTED`, the member's `status` is `ACTIVE ..."
        PRD §3.4: "Attempting any transition from a status that does not permit it is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        A free-CANCELLED booking on a membership left with 0 available credits:
        confirm reports the state failure ERR_INVALID_STATE, not a credit error.

        Design: Difficulty/priority_pair_validation_conflict/terminal_state_beats_insufficient_credits
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440,
            n_tables=2, cancel_window_hours=12)
        loc, flex, mem = s["loc"], s["flex"], s["member"]
        t1, t2 = s["tables"][0], s["tables"][1]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=2, list_price_cents=6000)
        ship = fixtures.create_membership(mem["id"], loc["id"], tier="STARTER",
                                          monthly_fee_cents=5000, included_credits=2,
                                          rollover_cap=0)
        # consume the wallet to 0 available with one completed booking
        fixtures.create_completed_booking(mem["id"], loc["id"], svc["id"], flex["id"], t1,
                                          "2026-04-12T10:00:00Z", "MEMBERSHIP", ship["id"],
                                          complete_clock="2026-04-12T10:30:00Z")
        # a separately funded booking we will free-cancel into a terminal state
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        svc1 = fixtures.create_service(loc["id"], name="50m-1", kind="ASSISTED_STRETCH",
                                       duration_minutes=50, credit_cost=1, list_price_cents=6000)
        bk = fixtures.create_booking(mem["id"], loc["id"], svc1["id"], flex["id"], t2,
                                     "2026-04-25T10:00:00Z", "CREDIT_PACK", pack["id"])
        validate_success(api.cancel_booking(bk["id"], FD))  # free CANCELLED
        validate_error(api.confirm_booking(bk["id"], FD), ApiErrorId.ERR_INVALID_STATE.value)

    def test_member_suspended_reported_before_table_overlap(self, api):
        """PRD §3.3: "After that the member's standing is checked — a `SUSPENDED` member cannot create or confirm bookings and is rejected with `ERR_MEMBER_SUSPENDED` (HTTP 409) — followed by the intro gate described in §3.2 (`ERR_INTRO_REQUIRED`, 409). Then come the temporal and resource checks described below".

        A SUSPENDED member booking a slot that also collides on the table gets
        ERR_MEMBER_SUSPENDED (priority before the table overlap check).

        Design: Difficulty/priority_pair_validation_conflict/member_suspended_beats_table_overlap
        """
        # Studio with an occupant on T1 at 2026-04-20T10:00Z and a SUSPENDED member.
        fixtures.set_clock("2026-04-10T00:00:00Z")
        loc = fixtures.create_location(open_minute_of_day=0, close_minute_of_day=1440,
                                       no_show_fee_cents=5000, cancel_window_hours=12)
        flex = fixtures.create_flexologist(loc["id"], certified_intro=True)
        t1 = fixtures.create_table(loc["id"], label="T1")["id"]
        t2 = fixtures.create_table(loc["id"], label="T2")["id"]
        svc_intro = fixtures.create_service(loc["id"], name="Intro", kind="INTRO",
                                            duration_minutes=25, credit_cost=0, list_price_cents=0)
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=2, list_price_cents=6000)
        # occupant member occupies T1
        other = fixtures.create_member(loc["id"], full_name="Otto", email="otto@x.com")
        opack = fixtures.create_credit_pack(other["id"], loc["id"], pack_credits=10,
                                            base_unit_price_cents=100)
        fixtures.complete_intro(other["id"], loc["id"], flex["id"], t2, svc_intro["id"],
                                intro_start="2026-04-11T08:00:00Z",
                                complete_clock="2026-04-11T08:30:00Z", pack_id=opack["id"])
        fixtures.create_confirmed_booking(other["id"], loc["id"], svc["id"], flex["id"], t1,
                                          "2026-04-20T10:00:00Z", "CREDIT_PACK", opack["id"])
        # suspended member: complete intro then drive to 5 strike points
        mem = fixtures.create_member(loc["id"], full_name="Sue", email="sue@x.com")
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        fixtures.complete_intro(mem["id"], loc["id"], flex["id"], t1, svc_intro["id"],
                                intro_start="2026-04-12T08:00:00Z",
                                complete_clock="2026-04-12T08:30:00Z", pack_id=pack["id"])
        # two NO_SHOWs (4 pts)
        fixtures.drive_no_shows(mem["id"], loc["id"], svc["id"], flex["id"], [t1, t2],
                                ["2026-04-13T10:00:00Z", "2026-04-13T12:00:00Z"],
                                "2026-04-13T13:30:00Z", "CREDIT_PACK", pack["id"])
        # one LATE_CANCEL for the 5th point
        lc = fixtures.create_confirmed_booking(mem["id"], loc["id"], svc["id"], flex["id"], t1,
                                               "2026-04-15T10:00:00Z", "CREDIT_PACK", pack["id"])
        fixtures.set_clock("2026-04-14T23:00:00Z")
        validate_success(api.cancel_booking(lc["id"], FD))
        suspended = validate_success(api.get_member(mem["id"], FD))
        assert suspended["status"] == "SUSPENDED"
        # suspended member books T1 overlapping the occupant at 2026-04-20T10:00Z
        validate_error(api.create_booking(
            factories.create_booking_payload(
                mem["id"], loc["id"], svc["id"], flex["id"], t1,
                "2026-04-20T10:00:00Z", "CREDIT_PACK", pack["id"]), FD),
            ApiErrorId.ERR_MEMBER_SUSPENDED.value)

    def test_member_suspended_reported_before_flexologist_overlap(self, api):
        """PRD §3.3: "After that the member's standing is checked — a `SUSPENDED` member cannot create or confirm bookings and is rejected with `ERR_MEMBER_SUSPENDED` (HTTP 409) — followed by the intro gate described in §3.2 (`ERR_INTRO_REQUIRED`, 409). Then come the temporal and resource checks described below".

        The suspended member also collides with the occupant's flexologist
        (different table T2, same flexologist within the buffer); the suspension
        check (priority 7) still pre-empts the flexologist check.

        Design: Difficulty/priority_pair_validation_conflict/member_suspended_beats_table_overlap
        """
        fixtures.set_clock("2026-04-10T00:00:00Z")
        loc = fixtures.create_location(open_minute_of_day=0, close_minute_of_day=1440,
                                       no_show_fee_cents=5000, cancel_window_hours=12,
                                       flexologist_buffer_minutes=15)
        flex = fixtures.create_flexologist(loc["id"], certified_intro=True)
        t1 = fixtures.create_table(loc["id"], label="T1")["id"]
        t2 = fixtures.create_table(loc["id"], label="T2")["id"]
        t3 = fixtures.create_table(loc["id"], label="T3")["id"]
        svc_intro = fixtures.create_service(loc["id"], name="Intro", kind="INTRO",
                                            duration_minutes=25, credit_cost=0, list_price_cents=0)
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=2, list_price_cents=6000)
        # occupant booking holds flex at 2026-04-20T10:00-10:50 on T1
        other = fixtures.create_member(loc["id"], full_name="Otto", email="otto@x.com")
        opack = fixtures.create_credit_pack(other["id"], loc["id"], pack_credits=10,
                                            base_unit_price_cents=100)
        fixtures.complete_intro(other["id"], loc["id"], flex["id"], t2, svc_intro["id"],
                                intro_start="2026-04-11T08:00:00Z",
                                complete_clock="2026-04-11T08:30:00Z", pack_id=opack["id"])
        fixtures.create_confirmed_booking(other["id"], loc["id"], svc["id"], flex["id"], t1,
                                          "2026-04-20T10:00:00Z", "CREDIT_PACK", opack["id"])
        # suspended member
        mem = fixtures.create_member(loc["id"], full_name="Sue", email="sue@x.com")
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        fixtures.complete_intro(mem["id"], loc["id"], flex["id"], t1, svc_intro["id"],
                                intro_start="2026-04-12T08:00:00Z",
                                complete_clock="2026-04-12T08:30:00Z", pack_id=pack["id"])
        fixtures.drive_no_shows(mem["id"], loc["id"], svc["id"], flex["id"], [t1, t2, t3],
                                ["2026-04-13T10:00:00Z", "2026-04-13T12:00:00Z", "2026-04-13T14:00:00Z"],
                                "2026-04-13T15:30:00Z", "CREDIT_PACK", pack["id"])
        suspended = validate_success(api.get_member(mem["id"], FD))
        assert suspended["status"] == "SUSPENDED"
        # books T2 at 11:00 (gap 10 < 15 buffer from the 10:50 occupant end) -> would be
        # ERR_FLEXOLOGIST_UNAVAILABLE, but suspension is reported first.
        validate_error(api.create_booking(
            factories.create_booking_payload(
                mem["id"], loc["id"], svc["id"], flex["id"], t2,
                "2026-04-20T11:00:00Z", "CREDIT_PACK", pack["id"]), FD),
            ApiErrorId.ERR_MEMBER_SUSPENDED.value)


# ===========================================================================
# cross_entity_state_dependency
# ===========================================================================

class TestCrossEntityState:
    def test_confirm_blocked_by_suspended_member(self, api):
        """PRD §3.4: "Confirming a requested booking is permitted only when its `schedule_status` is `REQUESTED`, the member's `status` is `ACTIVE` (a `SUSPENDED` member is blocked with `ERR_MEMBER_SUSPENDED`), and the location's `status` is `OPEN".

        A REQUESTED booking whose member becomes SUSPENDED before confirm is
        refused ERR_MEMBER_SUSPENDED; the booking stays REQUESTED.

        Design: Difficulty/cross_entity_state_dependency/booking_confirm_blocked_by_suspended_member
        """
        fixtures.set_clock("2026-04-10T00:00:00Z")
        loc = fixtures.create_location(open_minute_of_day=0, close_minute_of_day=1440,
                                       no_show_fee_cents=5000)
        flex = fixtures.create_flexologist(loc["id"], certified_intro=True)
        tbls = [fixtures.create_table(loc["id"], label=f"T{i}")["id"] for i in range(4)]
        svc_intro = fixtures.create_service(loc["id"], name="Intro", kind="INTRO",
                                            duration_minutes=25, credit_cost=0, list_price_cents=0)
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=1, list_price_cents=6000)
        mem = fixtures.create_member(loc["id"], full_name="Cee", email="cee@x.com")
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        fixtures.complete_intro(mem["id"], loc["id"], flex["id"], tbls[0], svc_intro["id"],
                                intro_start="2026-04-11T08:00:00Z",
                                complete_clock="2026-04-11T08:30:00Z", pack_id=pack["id"])
        # the future REQUESTED booking we will try to confirm
        target = fixtures.create_booking(mem["id"], loc["id"], svc["id"], flex["id"], tbls[0],
                                         "2026-04-25T10:00:00Z", "CREDIT_PACK", pack["id"])
        # drive three NO_SHOWs to suspend (score 6)
        fixtures.drive_no_shows(mem["id"], loc["id"], svc["id"], flex["id"],
                                [tbls[1], tbls[2], tbls[3]],
                                ["2026-04-12T10:00:00Z", "2026-04-12T12:00:00Z", "2026-04-12T14:00:00Z"],
                                "2026-04-12T15:30:00Z", "CREDIT_PACK", pack["id"])
        suspended = validate_success(api.get_member(mem["id"], FD))
        assert suspended["status"] == "SUSPENDED"
        validate_error(api.confirm_booking(target["id"], FD), ApiErrorId.ERR_MEMBER_SUSPENDED.value)
        again = validate_success(api.get_booking(target["id"], FD))
        assert again["schedule_status"] == "REQUESTED"

    def test_confirm_allowed_after_member_reinstated(self, api):
        """PRD §3.4: "Confirming a requested booking is permitted only when its `schedule_status` is `REQUESTED`, the member's `status` is `ACTIVE` (a `SUSPENDED` member is blocked with `ERR_MEMBER_SUSPENDED`), and the location's `status` is `OPEN".
        PRD §3.6: "A `StudioManager` may also manually reinstate a suspended member, moving `status` from `SUSPENDED` back to `ACTIVE`".

        The same REQUESTED booking that a SUSPENDED member could not confirm
        becomes confirmable once the member's status is ACTIVE again — the
        confirm transition tracks the live Member.status.

        Design: Difficulty/cross_entity_state_dependency/booking_confirm_blocked_by_suspended_member
        """
        fixtures.set_clock("2026-04-10T00:00:00Z")
        loc = fixtures.create_location(open_minute_of_day=0, close_minute_of_day=1440,
                                       no_show_fee_cents=5000)
        flex = fixtures.create_flexologist(loc["id"], certified_intro=True)
        tbls = [fixtures.create_table(loc["id"], label=f"T{i}")["id"] for i in range(4)]
        svc_intro = fixtures.create_service(loc["id"], name="Intro", kind="INTRO",
                                            duration_minutes=25, credit_cost=0, list_price_cents=0)
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=1, list_price_cents=6000)
        mem = fixtures.create_member(loc["id"], full_name="Cee", email="cee@x.com")
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=10,
                                           base_unit_price_cents=100)
        fixtures.complete_intro(mem["id"], loc["id"], flex["id"], tbls[0], svc_intro["id"],
                                intro_start="2026-04-11T08:00:00Z",
                                complete_clock="2026-04-11T08:30:00Z", pack_id=pack["id"])
        target = fixtures.create_booking(mem["id"], loc["id"], svc["id"], flex["id"], tbls[0],
                                         "2026-04-25T10:00:00Z", "CREDIT_PACK", pack["id"])
        fixtures.drive_no_shows(mem["id"], loc["id"], svc["id"], flex["id"],
                                [tbls[1], tbls[2], tbls[3]],
                                ["2026-04-12T10:00:00Z", "2026-04-12T12:00:00Z", "2026-04-12T14:00:00Z"],
                                "2026-04-12T15:30:00Z", "CREDIT_PACK", pack["id"])
        assert validate_success(api.get_member(mem["id"], FD))["status"] == "SUSPENDED"
        validate_error(api.confirm_booking(target["id"], FD), ApiErrorId.ERR_MEMBER_SUSPENDED.value)
        # manager reinstates -> member ACTIVE -> confirm now permitted
        reinstated = validate_success(api.reinstate_member(mem["id"], SM))
        assert reinstated["status"] == "ACTIVE"
        confirmed = validate_success(api.confirm_booking(target["id"], FD))
        assert confirmed["schedule_status"] == "CONFIRMED"

    def test_series_activate_blocked_by_frozen_membership(self, api):
        """PRD §3.9: "Activating a series requires that its `status` be `DRAFT` and that the funding wallet referenced by `funding_id` exist and be usable — a membership that is `ACTIVE` (not `FROZEN` or `CANCELLED`) or a credit pack that is `ACTIVE` (not `EXPIRED`)."
        PRD §3.9: "A series transition attempted from a state that does not allow it is rejected with `ERR_INVALID_STATE`."

        A DRAFT series funded by a FROZEN membership -> activate fails
        ERR_INVALID_STATE; series stays DRAFT.

        Design: Difficulty/cross_entity_state_dependency/series_activate_blocked_by_frozen_membership
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-05-01T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440)
        loc, flex, table, mem = s["loc"], s["flex"], s["table"], s["member"]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=1, list_price_cents=6000)
        ship = fixtures.create_membership(mem["id"], loc["id"], tier="PRO",
                                          monthly_fee_cents=12000, included_credits=8,
                                          rollover_cap=4)
        series = validate_success(api.create_recurring_series(
            factories.create_recurring_series_payload(
                mem["id"], loc["id"], svc["id"], flex["id"], table, "MEMBERSHIP", ship["id"],
                "2026-05-20T10:00:00Z", 7, 4), FD), expected_status=201)
        validate_success(api.freeze_membership(
            ship["id"],
            factories.freeze_payload("2026-05-05T00:00:00Z", "2026-05-08T00:00:00Z",
                                     ship["version"]),
            make_member_headers(mem["id"])))
        validate_error(api.activate_recurring_series(series["id"], FD),
                       ApiErrorId.ERR_INVALID_STATE.value)
        again = validate_success(api.get_recurring_series(series["id"], FD))
        assert again["status"] == "DRAFT"

    def test_series_activate_blocked_by_cancelled_membership(self, api):
        """PRD §3.9: "Activating a series requires that its `status` be `DRAFT` and that the funding wallet referenced by `funding_id` exist and be usable — a membership that is `ACTIVE` (not `FROZEN` or `CANCELLED`) or a credit pack that is `ACTIVE` (not `EXPIRED`)."
        PRD §3.9: "A series transition attempted from a state that does not allow it is rejected with `ERR_INVALID_STATE`."

        A DRAFT series funded by a CANCELLED membership also fails activate with
        ERR_INVALID_STATE; the series stays DRAFT.

        Design: Difficulty/cross_entity_state_dependency/series_activate_blocked_by_frozen_membership
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-05-01T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440)
        loc, flex, table, mem = s["loc"], s["flex"], s["table"], s["member"]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=1, list_price_cents=6000)
        ship = fixtures.create_membership(mem["id"], loc["id"], tier="PRO",
                                          monthly_fee_cents=12000, included_credits=8,
                                          rollover_cap=4)
        series = validate_success(api.create_recurring_series(
            factories.create_recurring_series_payload(
                mem["id"], loc["id"], svc["id"], flex["id"], table, "MEMBERSHIP", ship["id"],
                "2026-05-20T10:00:00Z", 7, 4), FD), expected_status=201)
        validate_success(api.cancel_membership(
            ship["id"], {"expected_membership_version": ship["version"]},
            make_member_headers(mem["id"])))
        validate_error(api.activate_recurring_series(series["id"], FD),
                       ApiErrorId.ERR_INVALID_STATE.value)
        again = validate_success(api.get_recurring_series(series["id"], FD))
        assert again["status"] == "DRAFT"


# ===========================================================================
# Corner: OCC stale version, series limit, membership eligibility, existence
# ===========================================================================

class TestMembershipOCC:
    def test_stale_version_freeze_rejected(self, api):
        """PRD §2.7: "If `expected_membership_version` does not equal the membership's current `version`, the request is rejected with `ERR_STALE_MEMBERSHIP_VERSION` (HTTP 412), and no state change occurs."

        After freeze->unfreeze advances version to 3, a freeze carrying version 2
        is stale -> rejected; membership stays ACTIVE.

        Design: Corner/errors/error_stale_membership_version_on_freeze
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-05-01T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440)
        loc, mem = s["loc"], s["member"]
        hdr = make_member_headers(mem["id"])
        ship = fixtures.create_membership(mem["id"], loc["id"], tier="PLUS",
                                          monthly_fee_cents=9000, included_credits=6,
                                          rollover_cap=2)
        frozen = validate_success(api.freeze_membership(
            ship["id"],
            factories.freeze_payload("2026-05-10T00:00:00Z", "2026-05-12T00:00:00Z",
                                     ship["version"]), hdr))
        reactivated = validate_success(api.unfreeze_membership(
            ship["id"], {"expected_membership_version": frozen["version"]}, hdr))
        stale_version = reactivated["version"] - 1
        validate_error(api.freeze_membership(
            ship["id"],
            factories.freeze_payload("2026-05-14T00:00:00Z", "2026-05-16T00:00:00Z",
                                     stale_version), hdr),
            ApiErrorId.ERR_STALE_MEMBERSHIP_VERSION.value)
        again = validate_success(api.get_membership(ship["id"], FD))
        assert again["status"] == "ACTIVE"

    def test_stale_version_cancel_rejected(self, api):
        """PRD §2.7: "a cancel that carries a stale `expected_membership_version` would supersede the prior membership state while acting on an obsolete view, so it is refused with `ERR_STALE_MEMBERSHIP_VERSION`."

        A freeze advances version 1->2; a cancel carrying version 1 is stale ->
        rejected; membership stays FROZEN.

        Design: Corner/errors/error_cancel_stale_membership_version
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-05-01T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440)
        loc, mem = s["loc"], s["member"]
        hdr = make_member_headers(mem["id"])
        ship = fixtures.create_membership(mem["id"], loc["id"], tier="PLUS",
                                          monthly_fee_cents=9000, included_credits=6,
                                          rollover_cap=2)
        validate_success(api.freeze_membership(
            ship["id"],
            factories.freeze_payload("2026-05-10T00:00:00Z", "2026-05-12T00:00:00Z",
                                     ship["version"]), hdr))
        validate_error(api.cancel_membership(
            ship["id"], {"expected_membership_version": ship["version"]}, hdr),
            ApiErrorId.ERR_STALE_MEMBERSHIP_VERSION.value)
        again = validate_success(api.get_membership(ship["id"], FD))
        assert again["status"] == "FROZEN"


class TestOtherErrors:
    def test_series_occurrence_limit_rejected(self, api):
        """PRD §3.9: "an `occurrence_count` between 1 and 26; an `occurrence_count` outside that range or an `interval_days` of zero or less is rejected with `ERR_SERIES_OCCURRENCE_LIMIT` (HTTP 422)."

        occurrence_count=30 (> 26) -> rejected.

        Design: Corner/errors/error_series_occurrence_limit
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-05-01T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440)
        loc, flex, table, mem = s["loc"], s["flex"], s["table"], s["member"]
        svc = fixtures.create_service(loc["id"], name="50m", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=1, list_price_cents=6000)
        ship = fixtures.create_membership(mem["id"], loc["id"], tier="PRO",
                                          monthly_fee_cents=12000, included_credits=8,
                                          rollover_cap=4)
        validate_error(api.create_recurring_series(
            factories.create_recurring_series_payload(
                mem["id"], loc["id"], svc["id"], flex["id"], table, "MEMBERSHIP", ship["id"],
                "2026-05-20T10:00:00Z", 7, 30), FD),
            ApiErrorId.ERR_SERIES_OCCURRENCE_LIMIT.value)

    def test_membership_without_intro_rejected(self, api):
        """PRD §3.7: "Purchase is allowed only if the member's `intro_completed` is true, and a member may hold at most one membership in `ACTIVE` or `FROZEN` status per location; violating either rule is rejected with `ERR_MEMBERSHIP_NOT_ALLOWED` (HTTP 409)."

        Design: Corner/validations/membership_not_allowed_without_intro
        """
        loc = fixtures.create_location(name="Mn")
        mem = fixtures.create_member(loc["id"], full_name="Mnm", email="mnm@x.com")
        validate_error(api.create_membership(
            factories.create_membership_payload(
                mem["id"], loc["id"], tier="PLUS", monthly_fee_cents=9000,
                included_credits=6, rollover_cap=2), FD),
            ApiErrorId.ERR_MEMBERSHIP_NOT_ALLOWED.value)

    def test_existence_checked_before_state_on_confirm(self, api):
        """PRD §2.5: "a path id that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404) before any deeper lookup or body validation runs."

        Confirming a non-existent booking id returns ERR_NOT_FOUND.

        Design: Corner/validations/priority_existence_beats_state
        """
        validate_error(api.confirm_booking("11111111-1111-4111-8111-111111111111", FD),
                       ApiErrorId.ERR_NOT_FOUND.value)
