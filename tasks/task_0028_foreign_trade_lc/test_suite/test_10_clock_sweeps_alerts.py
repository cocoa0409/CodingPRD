"""Clock-driven sweeps: refusal-deadline, maturity, expiry, alerts
(PRD §2.8, §3.7, §3.8, §3.10)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    advance_clock_days,
    advance_clock_seconds,
    assert_clock,
    count_alerts_of_kind,
    create_settlement_payload,
    get_clock,
    get_lc,
    get_presentation,
    get_success_data,
    iso_z,
    parse_iso,
    record_acceptance,
    setup_active_lc,
    setup_examined_clean_presentation,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §3.10 — Clock test-driving
# ===========================================================================
class TestClock:

    def test_get_clock_returns_now(self, api, operator_headers):
        """PRD §3.10: 'A simple read-only capability returns the current
        Clock value.'"""
        res = api.get_clock(operator_headers)
        clock = validate_success(res)
        assert_clock(clock)

    def test_advance_clock_moves_forward(self, api, operator_headers):
        """PRD §3.10: 'The test-driving capability advances the singleton
        Clock row's now field by a supplied number of seconds.'"""
        before = get_clock()
        advance_clock_seconds(86_400)
        after = get_clock()
        assert parse_iso(after["now"]) > parse_iso(before["now"])


# ===========================================================================
# §3.8 — Maturity sweep transitions ACCEPTED → PAID
# ===========================================================================
class TestMaturitySweep:

    def test_clock_advance_past_maturity_pays_usance(self, api):
        """PRD §3.8: 'From ACCEPTED the system then waits for the
        maturity sweep: on every clock advance, any usance settlement
        whose current clock has reached or passed maturity_date
        automatically advances from ACCEPTED to PAID, with paid_at set
        to the sweep instant and beneficiary_proceeds_minor_units
        computed.'"""
        lc, bundle, presentation, _ = setup_examined_clean_presentation(
            lc_type="USANCE", usance_tenor_days=60,
            amount_minor_units=10_000,
            drawing_amount_minor_units=10_000,
        )
        s = api.create_settlement(
            presentation["id"], create_settlement_payload(),
            bundle["issuing_bank_headers"],
        )
        s = validate_success(s, expected_status=201)
        record_acceptance(s["id"], bundle["issuing_bank_headers"])
        # Advance 61 days — past maturity.
        advance_clock_days(61)
        snapshot = api.get_settlement(s["id"], bundle["issuing_bank_headers"])
        snapshot = validate_success(snapshot)
        assert snapshot["status"] == "PAID", (
            "PRD §3.8: 'on every clock advance, any usance settlement "
            "whose current clock has reached or passed maturity_date "
            "automatically advances from ACCEPTED to PAID'"
        )
        assert snapshot["paid_at"] is not None


# ===========================================================================
# §3.10 — Expiry sweep
# ===========================================================================
class TestExpirySweep:

    def test_clock_advance_past_expiry_promotes_to_expired(self, api):
        """PRD §3.10: 'When days_to_expiry is on or below zero and no
        EXPIRED alert exists, the sweep emits one with alert_kind
        EXPIRED and transitions the LC from ACTIVE to EXPIRED'."""
        now = parse_iso(get_clock()["now"])
        lc, bundle = setup_active_lc(
            amount_minor_units=10_000,
            latest_shipment_date=iso_z(now + timedelta(days=10)),
            expiry_date=iso_z(now + timedelta(days=20)),
        )
        # Advance >20 days — past expiry.
        advance_clock_days(25)
        snapshot = get_lc(lc["id"], bundle["applicant_headers"])
        assert snapshot["lifecycle_status"] == "EXPIRED", (
            "PRD §3.10: '... transitions the LC from ACTIVE to EXPIRED'"
        )

    def test_expiry_alert_emitted_idempotently(self, api):
        """PRD §3.10: 'this alert is idempotent on lc_id.'"""
        now = parse_iso(get_clock()["now"])
        lc, bundle = setup_active_lc(
            amount_minor_units=10_000,
            latest_shipment_date=iso_z(now + timedelta(days=5)),
            expiry_date=iso_z(now + timedelta(days=10)),
        )
        advance_clock_days(15)
        # Run another sweep.
        advance_clock_days(1)
        res = api.list_expiry_alerts(lc["id"], bundle["applicant_headers"])
        alerts, _ = validate_paginated(res)
        # Exactly one EXPIRED alert per LC.
        assert count_alerts_of_kind(alerts, "EXPIRED") == 1, (
            "PRD §3.10: 'this alert is idempotent on lc_id'"
        )


class TestExpiryAlertKinds:

    def test_t_minus_15_emitted_when_15_days_remain(self, api):
        """PRD §3.10: 'When days_to_expiry equals 15 and no T_MINUS_15
        alert exists for the LC, the sweep emits one with alert_kind
        T_MINUS_15.'"""
        now = parse_iso(get_clock()["now"])
        lc, bundle = setup_active_lc(
            amount_minor_units=10_000,
            latest_shipment_date=iso_z(now + timedelta(days=5)),
            expiry_date=iso_z(now + timedelta(days=20)),
        )
        # After advancing 5 days, days_to_expiry should be 15.
        advance_clock_days(5)
        # Trigger sweep with a 0-second advance? PRD says every advance
        # triggers a sweep; advance 1 second to be safe.
        advance_clock_seconds(1)
        res = api.list_expiry_alerts(lc["id"], bundle["applicant_headers"])
        alerts, _ = validate_paginated(res)
        # PRD says emit when days_to_expiry == 15. Time after the first
        # advance leaves slightly less than 15 days, but PRD §3.10 says
        # 'days_to_expiry as the LC's expiry_date minus the current
        # clock divided by 86,400 seconds with the result rounded up to
        # a whole day' — so 14 days + a few seconds rounds up to 15.
        # Both interpretations ('exactly 15' vs '<= 15 and not yet
        # emitted') would emit at this point on advance.
        assert count_alerts_of_kind(alerts, "T_MINUS_15") >= 1, (
            "PRD §3.10: 'When days_to_expiry equals 15 ... the sweep "
            "emits one with alert_kind T_MINUS_15'"
        )

    def test_t_minus_5_emitted_when_5_days_remain(self, api):
        """PRD §3.10: 'When days_to_expiry equals 5 and no T_MINUS_5
        alert exists, the sweep emits one with alert_kind T_MINUS_5.'"""
        now = parse_iso(get_clock()["now"])
        lc, bundle = setup_active_lc(
            amount_minor_units=10_000,
            latest_shipment_date=iso_z(now + timedelta(days=2)),
            expiry_date=iso_z(now + timedelta(days=8)),
        )
        # After advancing 3 days, days_to_expiry is ~5.
        advance_clock_days(3)
        advance_clock_seconds(1)
        res = api.list_expiry_alerts(lc["id"], bundle["applicant_headers"])
        alerts, _ = validate_paginated(res)
        assert count_alerts_of_kind(alerts, "T_MINUS_5") >= 1, (
            "PRD §3.10: 'When days_to_expiry equals 5 ... the sweep "
            "emits one with alert_kind T_MINUS_5'"
        )
