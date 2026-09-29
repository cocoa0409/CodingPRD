"""One write, and every dependent projection already readable.

Nothing here is deferred to a sweep or to a second call: the entry the write returns
already carries the position after the movement, and by the time that response is in
the caller's hands the account has been re-banded, the alert has been opened against
the crossed threshold, and the bank's posture has been re-derived from the new band.
"""

from test_helpers import (
    LIQUIDITY_OFFICER,
    assert_alert,
    assert_ledger_entry,
    assert_pagination_meta,
    assert_position_account_shape,
    list_alerts_with_meta,
    list_ledger_entries_with_meta,
    live_alpha,
    read_account,
    read_participant,
    set_clock,
    withdraw_from_account,
)


def test_one_withdrawal_returns_the_position_and_leaves_every_projection_current(api):
    """The write response, the re-banding, the alert and the posture all land together.

    PRD 3.3: "The entry is appended with the next `sequence_no` and with `balance_after_cents`
    recording the position immediately after it, the account's `last_ledger_sequence_no` advances
    to that ordinal, and the account's balance, reservation and availability are recomputed."

    PRD 2.9: "Immediately after every ledger posting — funding, withdrawal, settlement debit, fee
    debit or return credit — the account's band is recomputed and written to `alert_tier`."

    PRD 2.9: "When the recomputed tier is not `GREEN`, and the account does not already have a
    `LiquidityAlert` whose `tier` equals the recomputed tier and whose `status` is `OPEN`,
    `ACKNOWLEDGED` or `ESCALATED`, one alert row is opened with `status` `OPEN`, its `tier` set to
    the recomputed tier, its `observed_balance_cents` set to the `current_balance_cents` just
    computed, and its `threshold_cents` set to the constant that was crossed —
    `warning_threshold_cents` for an `AMBER` alert, `critical_threshold_cents` for a `RED` alert,
    and `floor_cents` for a `BREACH` alert."

    PRD 2.9: "At the end of any request that changes a participant's `enrollment_status`, changes
    its account's `alert_tier`, or changes any outage event's `status`, the participant's
    `operational_posture` is re-derived."

    PRD 2.9: "Otherwise, if the account's `alert_tier` is `AMBER`, the posture is `THROTTLED`."

    Design: Corner/consistency_model/ledger_adjustment_response_reflects_completed_cascade
    """
    set_clock(api, "2026-08-03T13:00:00Z")
    alpha = live_alpha(api)

    opened = read_account(api, alpha.account_id, LIQUIDITY_OFFICER)
    assert_position_account_shape(opened)
    assert opened["current_balance_cents"] == 1_200_000_000
    assert opened["alert_tier"] == "GREEN"
    assert opened["last_ledger_sequence_no"] == 0
    assert read_participant(api, alpha.id, LIQUIDITY_OFFICER)["operational_posture"] == "NORMAL"

    _seeded, seeded_meta = list_ledger_entries_with_meta(
        api, alpha.account_id, {"limit": 10, "offset": 0}, LIQUIDITY_OFFICER
    )
    assert seeded_meta["total_count"] == 0

    entry = withdraw_from_account(
        api,
        alpha.account_id,
        150_000_000,
        reference="TREASURY-SWEEP-02",
        officer=LIQUIDITY_OFFICER,
    )
    assert_ledger_entry(
        entry,
        entry_type="WITHDRAWAL_DEBIT",
        amount_cents=-150_000_000,
        balance_after_cents=1_050_000_000,
        sequence_no=1,
        business_date="2026-08-03",
    )
    assert entry["reference"] == "TREASURY-SWEEP-02"
    assert entry["related_transfer_id"] is None

    account = read_account(api, alpha.account_id, LIQUIDITY_OFFICER)
    assert account["current_balance_cents"] == 1_050_000_000
    assert account["reserved_cents"] == 0
    assert account["available_cents"] == 1_050_000_000
    assert account["alert_tier"] == "AMBER"
    assert account["last_ledger_sequence_no"] == 1

    alerts, alert_meta = list_alerts_with_meta(
        api, alpha.account_id, {"status": "OPEN", "limit": 10, "offset": 0}, LIQUIDITY_OFFICER
    )
    assert_pagination_meta(alert_meta, total_count=1, has_more=False, limit=10, offset=0)
    assert_alert(
        alerts[0],
        tier="AMBER",
        status="OPEN",
        threshold_cents=1_100_000_000,
        observed_balance_cents=1_050_000_000,
    )
    assert alerts[0]["account_id"] == alpha.account_id
    assert alerts[0]["escalated_at"] is None
    assert alerts[0]["cleared_at"] is None

    participant = read_participant(api, alpha.id, LIQUIDITY_OFFICER)
    assert participant["operational_posture"] == "THROTTLED"
    assert participant["enrollment_status"] == "LIVE"
