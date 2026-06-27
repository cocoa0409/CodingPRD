"""Validation-priority conflicts and cross-entity state guards on approval paths.

Covers difficulty instances (priority_pair_validation_conflict, cross_entity_state_dependency).
Each conflict test arranges a scenario where two checks both fail and asserts that the PRD's
fixed priority order (§2.9) determines which error_id is returned.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    create_merchant,
    create_bank_feed,
    create_draft_application,
    create_submitted_application,
    create_active_line_with_draw,
    create_application_payload,
    create_line_increase_request_payload,
    approve_line_increase_payload,
    schedule_remittance,
    settle_remittance,
    set_clock,
    get_line,
    UW1,
    UW2,
    SV1,
    CO1,
)


class TestApprovePriorityConflicts:
    def test_invalid_state_beats_feed_stale_on_approve(self, api):
        """Approving a DRAFT application with a STALE feed returns ERR_INVALID_STATE (state slot
        outranks feed-freshness).

        PRD §2.9: "state legality of the requested transition (ERR_INVALID_STATE); the
        credit-line version guard (ERR_STALE_VERSION); merchant-blocklist
        (ERR_MERCHANT_BLOCKLISTED); feed freshness (ERR_FEED_STALE)"

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_feed_stale_on_approve
        """
        merchant, feed, app = create_draft_application(
            feed_overrides={"pulled_at": "2026-04-20T00:00:00Z"}
        )
        validate_success(api.mark_bank_feed_stale(feed["id"], UW1), 200)
        # Approve while still DRAFT (never submitted) AND feed stale -> state check wins.
        res = api.approve_application(app["id"], UW2)
        validate_error(res, "ERR_INVALID_STATE")
        after = validate_success(api.get_application(app["id"], UW1), 200)
        assert after["status"] == "DRAFT"

    def test_excess_nsf_beats_score_floor_on_approve(self, api):
        """A submitted application with excess NSF and a sub-floor score returns ERR_EXCESS_NSF
        (NSF gate outranks the score floor).

        PRD §2.9: "the NSF underwriting gate (ERR_EXCESS_NSF); the risk-score floor
        (ERR_SCORE_BELOW_FLOOR)"

        Design: Difficulty/priority_pair_validation_conflict/excess_nsf_beats_score_floor_on_approve
        """
        merchant = create_merchant(monthly_revenue_cents=2_000_000)
        feed = create_bank_feed(
            merchant["id"], pulled_at="2026-04-20T00:00:00Z",
            avg_daily_balance_cents=200_000, nsf_count_90d=6, deposit_volume_cents=1_200_000,
        )
        app = validate_success(
            api.create_application(
                create_application_payload(merchant["id"], feed["id"], requested_limit_cents=1_000_000),
                UW1,
            ),
            201,
        )
        submitted = validate_success(api.submit_application(app["id"], UW1), 200)
        assert submitted["risk_score"] == 0  # below floor 50
        res = api.approve_application(app["id"], UW2)
        validate_error(res, "ERR_EXCESS_NSF")
        after = validate_success(api.get_application(app["id"], UW1), 200)
        assert after["status"] == "SUBMITTED"


class TestIncreaseApproveStateGuard:
    def test_increase_approve_on_delinquent_line_returns_invalid_state(self, api):
        """Approving a PENDING increase when the parent line is DELINQUENT returns
        ERR_INVALID_STATE (cross-entity ACTIVE guard).

        PRD §3.7: "The parent line must be ACTIVE (enforced in the state slot, returning
        ERR_INVALID_STATE if not)"

        Design: Difficulty/cross_entity_state_dependency/increase_approve_requires_credit_line_active
        """
        set_clock("2026-05-13T00:00:00Z")
        line, _ = create_active_line_with_draw(
            200_000, cadence="DAILY", feed_overrides={"pulled_at": "2026-05-12T00:00:00Z"}
        )
        # A PENDING increase against a fresh feed.
        merchant_id = line["merchant_id"]
        feed2 = create_bank_feed(
            merchant_id, plaid_item_id="plaid_x2", pulled_at="2026-05-12T12:00:00Z",
            avg_daily_balance_cents=2_000_000, nsf_count_90d=0, deposit_volume_cents=9_000_000,
        )
        lir = validate_success(
            api.create_line_increase_request(
                line["id"],
                create_line_increase_request_payload(feed2["id"], requested_limit_cents=1_500_000),
                SV1,
            ),
            201,
        )
        # Drive the line DELINQUENT via 3 NSF strikes.
        remit = schedule_remittance(line["id"], "2026-05-15T00:00:00Z")
        set_clock("2026-05-15T00:00:00Z")
        f1 = settle_remittance(remit["id"], "NSF")
        r2 = validate_success(api.get_remittance(f1["next_retry_remittance_id"], SV1), 200)
        set_clock("2026-05-17T00:00:00Z")
        f2 = settle_remittance(r2["id"], "NSF")
        r3 = validate_success(api.get_remittance(f2["next_retry_remittance_id"], SV1), 200)
        set_clock("2026-05-19T00:00:00Z")
        settle_remittance(r3["id"], "NSF")
        line_ver = get_line(line["id"])["version"]
        assert get_line(line["id"])["status"] == "DELINQUENT"
        res = api.approve_line_increase_request(
            lir["id"], approve_line_increase_payload(line_ver), CO1
        )
        validate_error(res, "ERR_INVALID_STATE")
        after = validate_success(api.get_line_increase_request(lir["id"], CO1), 200)
        assert after["status"] == "PENDING"
