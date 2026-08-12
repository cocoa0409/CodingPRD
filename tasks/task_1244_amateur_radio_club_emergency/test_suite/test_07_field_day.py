"""Field day events and scoring (PRD §3.6): per-contact points formula,
provisional-vs-final dual scoring, duplicate toggling, and the FINALIZED lock."""
from test_helpers import (
    ApiErrorId,
    assert_field_day_contact,
    assert_field_day_event,
    create_active_member,
    create_field_day_contact_payload,
    create_field_day_event_payload,
    create_open_field_day_event,
    get_success_data,
    log_contact,
    make_member_headers,
    set_clock,
    validate_error,
)


def _open_event_scenario():
    member = create_active_member("K1AAA")
    event = create_open_field_day_event()
    return member, event


class TestContactPoints:
    def test_qrp_cw_vhf_contact_hits_cap(self, api, admin_headers):
        """PRD §3.6: "The base value comes from the mode: two points for `CW`,
        two for `DIGITAL`, one for `PHONE`. That base is multiplied by the
        power factor: five for `QRP`, two for `LOW`, one for `HIGH`. A band
        bonus of two points is added when the band is one of the VHF entries,
        `B6M` or `B2M`; ... The contact's points are the resulting total capped
        at ten."

        Design: Difficulty/combinatorial_formula/contact_points_cap_multiplier_and_band_branch
        """
        member, event = _open_event_scenario()
        # CW(2) * QRP(5) + B2M bonus(2) = 12, capped at 10.
        contact = log_contact(event["id"], member["id"], worked_callsign="W1AW",
                              band="B2M", mode="CW", power_category="QRP")
        assert_field_day_contact(contact)
        assert contact["points"] == 10

    def test_multiplier_and_band_bonus_branches(self, api, admin_headers):
        """PRD §3.6: "That base is multiplied by the power factor: five for
        `QRP`, two for `LOW`, one for `HIGH`. A band bonus of two points is
        added when the band is one of the VHF entries, `B6M` or `B2M`; the HF
        bands `B160M`, `B80M`, `B40M`, `B20M`, `B15M`, and `B10M` earn no
        bonus."

        Design: Difficulty/combinatorial_formula/contact_points_cap_multiplier_and_band_branch
        """
        member, event = _open_event_scenario()
        # CW(2) * LOW(2) + B2M bonus(2) = 6.
        low = log_contact(event["id"], member["id"], worked_callsign="N0CALL",
                          band="B2M", mode="CW", power_category="LOW")
        assert low["points"] == 6
        # PHONE(1) * HIGH(1) + B2M bonus(2) = 3.
        high = log_contact(event["id"], member["id"], worked_callsign="K9XYZ",
                           band="B2M", mode="PHONE", power_category="HIGH")
        assert high["points"] == 3


class TestDualScoreVariants:
    def _three_contact_event(self, api, admin_headers):
        """10-pt contact, 4-pt contact (marked duplicate), 1-pt contact."""
        member, event = _open_event_scenario()
        log_contact(event["id"], member["id"], worked_callsign="W1AW",
                    band="B2M", mode="CW", power_category="QRP")
        dup = log_contact(event["id"], member["id"], worked_callsign="N0CALL",
                          band="B80M", mode="DIGITAL", power_category="LOW")
        log_contact(event["id"], member["id"], worked_callsign="K9XYZ",
                    band="B40M", mode="PHONE", power_category="HIGH")
        get_success_data(api.field_day_contact_set_duplicate(
            dup["id"], {"is_duplicate": True}, admin_headers))
        return event

    def test_provisional_score_counts_duplicates(self, api, admin_headers):
        """PRD §3.6: "The `provisional_score` is optimistic: it sums the points
        of **all** of the event's contacts, duplicates included, and adds a
        100-point bonus when the total contact count reaches 100."

        Design: Difficulty/dual_variant_calc/field_day_provisional_vs_final_score
        """
        event = self._three_contact_event(api, admin_headers)
        detail = get_success_data(api.get_field_day_event(event["id"], admin_headers))
        assert_field_day_event(detail)
        # 10 + 4 + 1 = 15 (bonus threshold 100 not reached).
        assert detail["provisional_score"] == 15
        assert detail["contact_count"] == 3

    def test_final_score_excludes_duplicates(self, api, admin_headers):
        """PRD §3.6: "The `final_score` is strict: it sums only contacts whose
        `is_duplicate` flag is false and adds the same 100-point bonus when the
        count of non-duplicate contacts reaches 100."

        Design: Difficulty/dual_variant_calc/field_day_provisional_vs_final_score
        """
        event = self._three_contact_event(api, admin_headers)
        detail = get_success_data(api.get_field_day_event(event["id"], admin_headers))
        # 10 + 1 = 11; the duplicate-flagged 4-point contact is excluded.
        assert detail["final_score"] == 11


class TestDuplicateToggleRoundtrip:
    def test_marking_duplicate_moves_only_final_score(self, api, admin_headers):
        """PRD §3.6: "toggling leaves `provisional_score` unchanged by design —
        duplicates still count there — while `final_score` is recomputed."

        Design: Difficulty/compensating_invariant/field_day_duplicate_mark_unmark_roundtrip
        """
        member, event = _open_event_scenario()
        contact = log_contact(event["id"], member["id"], worked_callsign="W1AW",
                              band="B2M", mode="CW", power_category="QRP")
        get_success_data(api.field_day_contact_set_duplicate(
            contact["id"], {"is_duplicate": True}, admin_headers))
        marked = get_success_data(api.get_field_day_event(event["id"], admin_headers))
        assert marked["provisional_score"] == 10
        assert marked["final_score"] == 0

    def test_unmarking_restores_final_score(self, api, admin_headers):
        """PRD §3.6: "Both are recomputed live on every contact creation and on
        every duplicate-flag toggle while the event is not `FINALIZED`." and
        "toggling leaves `provisional_score` unchanged by design — duplicates
        still count there — while `final_score` is recomputed."

        Design: Difficulty/compensating_invariant/field_day_duplicate_mark_unmark_roundtrip
        """
        member, event = _open_event_scenario()
        contact = log_contact(event["id"], member["id"], worked_callsign="W1AW",
                              band="B2M", mode="CW", power_category="QRP")
        get_success_data(api.field_day_contact_set_duplicate(
            contact["id"], {"is_duplicate": True}, admin_headers))
        restored = get_success_data(api.field_day_contact_set_duplicate(
            contact["id"], {"is_duplicate": False}, admin_headers))
        assert restored["is_duplicate"] is False
        detail = get_success_data(api.get_field_day_event(event["id"], admin_headers))
        assert detail["provisional_score"] == 10
        assert detail["final_score"] == 10
        assert detail["contact_count"] == 1


class TestFieldDayGating:
    def test_contact_on_planning_event_rejected(self, api, admin_headers):
        """PRD §3.6: "Logging is refused unless the event is `OPEN`
        (`ERR_EVENT_NOT_OPEN`) and the caller's membership is `ACTIVE`."

        Design: Corner/errors/contact_on_planning_event_rejected
        """
        member = create_active_member("K1OPR")
        event = get_success_data(api.create_field_day_event(
            create_field_day_event_payload(), admin_headers))
        assert event["status"] == "PLANNING"
        resp = api.create_field_day_contact(
            create_field_day_contact_payload(event["id"]),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_OPEN)

    def test_points_field_is_read_only(self, api, admin_headers):
        """PRD §3.6: "Each contact's `points` are computed once at creation and
        are immutable afterwards." and §2.10: "a structurally malformed request
        body — a missing required field, a wrong-typed value, an enum value
        outside its declared set, or an unknown or read-only field supplied by
        the client — is rejected with `ERR_VALIDATION`."

        Design: Corner/entities/fieldday_contact_points_input_ignored
        """
        member, event = _open_event_scenario()
        payload = create_field_day_contact_payload(event["id"], points=999)
        resp = api.create_field_day_contact(payload, make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_duplicate_toggle_blocked_after_finalize(self, api, admin_headers):
        """PRD §3.6: "Once the event is `FINALIZED`, toggling is refused with
        `ERR_EVENT_FINALIZED`." and §3.6: "Finalization (`SCORING` →
        `FINALIZED`) locks `final_score`, which is never recomputed afterwards".

        Design: Corner/errors/duplicate_toggle_after_finalize_rejected
        """
        member, event = _open_event_scenario()
        contact = log_contact(event["id"], member["id"], worked_callsign="W1AW",
                              band="B2M", mode="CW", power_category="QRP")
        set_clock("2026-05-04T00:00:00Z")
        get_success_data(api.field_day_event_set_status(
            event["id"], {"to": "SCORING"}, admin_headers))
        get_success_data(api.field_day_event_set_status(
            event["id"], {"to": "FINALIZED"}, admin_headers))
        resp = api.field_day_contact_set_duplicate(
            contact["id"], {"is_duplicate": True}, admin_headers)
        validate_error(resp, ApiErrorId.ERR_EVENT_FINALIZED)
        detail = get_success_data(api.get_field_day_event(event["id"], admin_headers))
        assert detail["final_score"] == 10
