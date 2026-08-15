"""STRICT vs LENIENT partial-credit divergence and request-pipeline ordering."""
from test_helpers import (
    ApiErrorId, constants, create_approved_campaign, make_network_ops_headers,
    make_sales_manager_headers, setup_confirmed_slot,
    setup_showtime_with_reel, validate_error, validate_success,
)
from test_helpers.fixtures import (
    SM_CREATOR, create_showtime_with_reel, dispatch_and_deliver, lock_reel,
    record_playlog, reserve_slot, set_clock, setup_theater_screen_feature,
    submit_and_accept_attendance,
)


class TestPartialCreditModeVariants:
    def _aired_slot(self, api, starts_at, campaign_overrides):
        """Build a full chain up to (but excluding) the playlog, attendance 940
        ACCEPTED. Returns (theater, campaign, slot)."""
        theater, screen, feature = setup_theater_screen_feature()
        showtime, reel = create_showtime_with_reel(screen["id"], feature["id"], starts_at)
        campaign = create_approved_campaign(**campaign_overrides)
        slot = reserve_slot(reel["id"], campaign["id"], reel_version=reel["version"])
        lock_reel(reel["id"])
        dispatch_and_deliver(reel["id"], theater["id"])
        submit_and_accept_attendance(showtime["id"], theater["id"], 940)
        return theater, campaign, slot

    def test_attributed_partial_strict_variant(self, api):
        """PRD §3.4: "On a played slot the system sets `play_factor` — 1.0 for
        `VERIFIED`; for `PARTIAL`, 0.5 when the campaign's `partial_credit_mode`
        is `STRICT` but the full 1.0 when it is `LENIENT`"

        Design: Corner/calculations/attributed_partial_strict_vs_lenient
        """
        theater, campaign, slot = self._aired_slot(api, "2026-08-14T19:00:00Z", {})
        set_clock(constants.AFTER_SHOW_CLOCK_DAY2)
        record_playlog(slot["id"], theater["id"], outcome="PARTIAL")
        resp = api.get_slot(slot["id"], make_sales_manager_headers(SM_CREATOR))
        slot_after = validate_success(resp)
        assert slot_after["play_factor"] == 0.5
        # floor(940 x 0.5) == 470
        assert slot_after["attributed_impressions"] == 470
        resp = api.get_campaign(campaign["id"], make_sales_manager_headers(SM_CREATOR))
        assert validate_success(resp)["delivered_impressions"] == 470

    def test_attributed_partial_lenient_variant(self, api):
        """PRD §3.4: "On a played slot the system sets `play_factor` — 1.0 for
        `VERIFIED`; for `PARTIAL`, 0.5 when the campaign's `partial_credit_mode`
        is `STRICT` but the full 1.0 when it is `LENIENT`"

        Design: Corner/calculations/attributed_partial_strict_vs_lenient
        """
        theater, campaign, slot = self._aired_slot(
            api, "2026-08-15T19:00:00Z", {"partial_credit_mode": "LENIENT", "name": "C-LENIENT"})
        set_clock(constants.AFTER_SHOW_CLOCK_DAY2)
        record_playlog(slot["id"], theater["id"], outcome="PARTIAL")
        resp = api.get_slot(slot["id"], make_sales_manager_headers(SM_CREATOR))
        slot_after = validate_success(resp)
        assert slot_after["play_factor"] == 1.0
        assert slot_after["attributed_impressions"] == 940
        resp = api.get_campaign(campaign["id"], make_sales_manager_headers(SM_CREATOR))
        assert validate_success(resp)["delivered_impressions"] == 940


class TestValidationPipelineOrdering:
    def test_slot_create_missing_required_field_beats_state(self, api):
        """PRD §2.6: "4. **Request shape** — required fields present, types
        valid, enum values in-domain, date fields in ISO form, `period_end_date`
        not earlier than `period_start_date`, and `flight_end_date` not earlier
        than `flight_start_date`, failing as `ERR_INVALID_REQUEST`."

        Design: Corner/validations/slot_create_missing_required_field_beats_state
        """
        ctx = setup_confirmed_slot()  # reel is LOCKED — the state tier would also fail
        payload = {
            "campaign_id": ctx["campaign"]["id"],
            "start_offset_seconds": 120,
            "expected_reel_version": get_fresh_reel_version(api, ctx["reel"]["id"]),
            # duration_seconds deliberately omitted.
        }
        resp = api.create_slot(ctx["reel"]["id"], payload,
                               make_sales_manager_headers(SM_CREATOR))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_existence_checked_before_state_on_lock(self, api):
        """PRD §2.6: "5. **Existence** — every referenced resource must exist,
        failing as `ERR_NOT_FOUND`."

        Design: Corner/validations/existence_checked_before_state_on_lock
        """
        _, _, _, _, reel = setup_showtime_with_reel()
        resp = api.lock_reel("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
                             {"expected_reel_version": reel["version"]},
                             make_network_ops_headers())
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def get_fresh_reel_version(api, reel_id):
    resp = api.get_reel(reel_id, make_sales_manager_headers(SM_CREATOR))
    return validate_success(resp)["version"]
