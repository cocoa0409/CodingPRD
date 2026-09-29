"""Version pins and a time-based counter, where the refusal is about the caller's view.

Optimistic concurrency here is not about lost updates: the funding that advanced the
account version made liquidity strictly better, and the second policy publication was
individually legitimate, yet both writes are refused because the caller quoted a number
it no longer holds. The velocity gate is the mirror image — nothing about the stored
rows changes, but the window slides off them and the same customer is admitted again.
"""

from test_helpers import (
    account_version,
    alpha_scenario,
    assert_instant,
    assert_ledger_entry,
    credit_transfer_payload,
    ERR_STALE_PARTICIPANT_VERSION,
    ERR_STALE_POSITION_VERSION,
    ERR_VELOCITY_LIMIT_EXCEEDED,
    fund_account,
    get_success_data,
    list_segment_policies_with_meta,
    list_transfers_with_meta,
    live_alpha,
    make_participant_admin_headers,
    participant_version,
    PAYMENT_OPERATOR_ALPHA,
    publish_segment_policy,
    read_account,
    read_transfer,
    segment_policy_payload,
    send_from_alpha,
    set_clock,
    validate_error,
    VELOCITY_WINDOW_MINUTES,
)

VELOCITY_TWO_SENDS_POLICY = {"rolling_window_count_limit": 2}


def test_a_send_quoting_the_pre_funding_version_is_refused_on_a_better_position(api):
    """Better liquidity is no excuse: the writer never observed the position it quotes.

    PRD 2.6: "Originating a credit transfer requires the non-optional field
    `expected_position_account_version`, carrying the client's last observed `version` of the
    originating participant's `PrefundedPositionAccount`."

    PRD 2.6: "Every accepted transfer origination, funding adjustment, withdrawal, settlement
    debit, fee debit and return credit increments that account's `version`, so a caller holding
    an older value is reasoning about liquidity headroom that no longer exists."

    PRD 2.6: "If the supplied value does not equal the account's current `version`, the
    origination is rejected with `ERR_STALE_POSITION_VERSION` (HTTP 412) — including the case
    where the transfer would comfortably fit under fresh liquidity, because admitting it on a
    stale view is exactly what this control forbids."

    PRD 2.11: "6. **Optimistic concurrency.** `expected_position_account_version` on
    origination, yielding `ERR_STALE_POSITION_VERSION`; `expected_participant_version` on
    segment-policy publication, yielding `ERR_STALE_PARTICIPANT_VERSION`."

    Design: Corner/cross_cutting_complexity_layers/stale_position_version_after_funding_rejected
    """
    scenario = alpha_scenario(api)
    stale_version = account_version(api, scenario.alpha.account_id)

    entry = fund_account(
        api, scenario.alpha.account_id, 100_000_000, reference="Intraday top-up"
    )
    assert_ledger_entry(
        entry,
        entry_type="FUNDING_CREDIT",
        amount_cents=100_000_000,
        balance_after_cents=1_300_000_000,
        sequence_no=1,
        business_date="2026-08-03",
    )
    fresh_version = account_version(api, scenario.alpha.account_id)
    assert fresh_version == stale_version + 1

    body = credit_transfer_payload(
        scenario.alpha.id,
        scenario.alpha.customer_account_id,
        50_000_000,
        stale_version,
    )
    validate_error(
        api.create_credit_transfer(body, PAYMENT_OPERATOR_ALPHA), ERR_STALE_POSITION_VERSION
    )

    _rows, meta = list_transfers_with_meta(api)
    assert meta["total_count"] == 0
    funded = read_account(api, scenario.alpha.account_id)
    assert funded["current_balance_cents"] == 1_300_000_000
    assert funded["reserved_cents"] == 0
    assert funded["alert_tier"] == "GREEN"

    body["expected_position_account_version"] = fresh_version
    admitted = get_success_data(
        api.create_credit_transfer(body, PAYMENT_OPERATOR_ALPHA), expected_status=201
    )
    assert admitted["clearing_status"] == "INITIATED"
    assert admitted["amount_cents"] == 50_000_000
    assert read_account(api, scenario.alpha.account_id)["reserved_cents"] == 50_000_000


def test_a_supersede_quoting_the_pre_publication_version_closes_nothing(api):
    """Both publications are legitimate, so only the pin stops the unobserved closure.

    PRD 2.6: "Publishing a segment policy requires the non-optional field
    `expected_participant_version`, carrying the client's last observed `version` of the
    `Participant` the policy is scoped to."

    PRD 2.6: "A mismatch with the participant's current `version` is rejected with
    `ERR_STALE_PARTICIPANT_VERSION` (HTTP 412)."

    PRD 2.6: "Because a successful publication itself increments `Participant.version`, a caller
    publishing two policies in a row must re-read the participant between them."

    PRD 3.2: "That flag closes the incumbent by writing the new policy's `effective_from` into
    the incumbent's `effective_to` and stamping the incumbent's `superseded_at` with the current
    logical clock, turning what would have been an overlap into adjacency."

    PRD 2.11: "These are checked before any state, compliance, limit or liquidity rule, so a
    caller with a stale view is told its view is stale rather than being told about a downstream
    condition it cannot yet see."

    Design: Corner/cross_cutting_complexity_layers/stale_participant_version_on_policy_supersede_rejected
    """
    set_clock(api, "2026-08-03T13:00:00Z")
    alpha = live_alpha(api)
    admin = make_participant_admin_headers(alpha.id)
    stale_version = participant_version(api, alpha.id)

    incumbent = publish_segment_policy(
        api,
        alpha.id,
        expected_participant_version=stale_version,
        segment="CORPORATE",
        effective_from="2026-08-01T00:00:00Z",
    )
    assert incumbent["per_transaction_limit_cents"] == 250_000_000
    assert incumbent["effective_to"] is None
    assert incumbent["superseded_at"] is None

    fresh_version = participant_version(api, alpha.id)
    assert fresh_version == stale_version + 1

    successor = dict(
        segment="CORPORATE",
        per_transaction_limit_cents=300_000_000,
        daily_aggregate_limit_cents=600_000_000,
        rolling_window_count_limit=6,
        rolling_window_amount_limit_cents=500_000_000,
        effective_from="2026-08-03T00:00:00Z",
        supersede_open_ended=True,
    )
    validate_error(
        api.create_segment_policy(
            segment_policy_payload(
                alpha.id, expected_participant_version=stale_version, **successor
            ),
            admin,
        ),
        ERR_STALE_PARTICIPANT_VERSION,
    )

    rows, meta = list_segment_policies_with_meta(api, alpha.id)
    assert meta["total_count"] == 1
    assert rows[0]["id"] == incumbent["id"]
    assert rows[0]["superseded_at"] is None
    assert rows[0]["effective_to"] is None
    assert rows[0]["per_transaction_limit_cents"] == 250_000_000
    assert rows[0]["version"] == 1
    assert participant_version(api, alpha.id) == fresh_version

    published = get_success_data(
        api.create_segment_policy(
            segment_policy_payload(
                alpha.id, expected_participant_version=fresh_version, **successor
            ),
            admin,
        ),
        expected_status=201,
    )
    assert published["per_transaction_limit_cents"] == 300_000_000
    assert_instant(published["effective_from"], "2026-08-03T00:00:00Z", "effective_from")
    assert published["effective_to"] is None
    assert published["superseded_at"] is None

    after, after_meta = list_segment_policies_with_meta(api, alpha.id)
    assert after_meta["total_count"] == 2
    assert [row["id"] for row in after] == [published["id"], incumbent["id"]]
    closed = after[1]
    assert_instant(closed["effective_to"], "2026-08-03T00:00:00Z", "effective_to")
    assert_instant(closed["superseded_at"], "2026-08-03T13:00:00Z", "superseded_at")
    governing = [row for row in after if row["superseded_at"] is None]
    assert [row["id"] for row in governing] == [published["id"]]


def test_the_velocity_counter_resets_by_time_rather_than_by_an_operator(api):
    """Admitted exactly on the limit, refused one past it, admitted again once the window slides.

    PRD 3.4: "**Velocity** is measured over the rolling 60-minute half-open window that ends at
    the current logical clock: a transfer created exactly at the window's start instant counts,
    and one created exactly at the clock does not."

    PRD 3.4: "The countable rows are the debtor customer account's own outbound transfers in one
    of five clearing states — `INITIATED`, `FRAUD_HOLD`, `QUEUED_THROTTLED`, `ACCEPTED` or
    `SETTLED`."

    PRD 3.4: "Two comparisons follow, and **count is checked before amount**: the number of
    countable prior rows plus one for this send must not exceed `rolling_window_count_limit`, and
    their summed `amount_cents` plus this amount must not exceed
    `rolling_window_amount_limit_cents`."

    PRD 3.4: "The *velocity term* takes the countable window count over the rolling 60-minute
    window described above, subtracts a free allowance of 3, treats any negative result as zero,
    and multiplies by a weight of 4."

    Design: Corner/cross_cutting_complexity_layers/velocity_count_threshold_boundary_and_window_reset
    """
    assert VELOCITY_WINDOW_MINUTES == 60
    scenario = alpha_scenario(api, policy=VELOCITY_TWO_SENDS_POLICY)
    assert scenario.alpha.policy["rolling_window_count_limit"] == 2

    first = send_from_alpha(api, scenario, 5_000_000)
    assert first["clearing_status"] == "INITIATED"
    assert first["fraud_score"] == 57

    set_clock(api, "2026-08-03T13:10:00Z")
    second = send_from_alpha(api, scenario, 5_000_000)
    assert second["clearing_status"] == "INITIATED"
    assert second["fraud_score"] == 57

    set_clock(api, "2026-08-03T13:20:00Z")
    validate_error(
        api.create_credit_transfer(
            credit_transfer_payload(
                scenario.alpha.id,
                scenario.alpha.customer_account_id,
                5_000_000,
                account_version(api, scenario.alpha.account_id),
            ),
            PAYMENT_OPERATOR_ALPHA,
        ),
        ERR_VELOCITY_LIMIT_EXCEEDED,
    )

    _rows, meta = list_transfers_with_meta(api)
    assert meta["total_count"] == 2
    for transfer in (first, second):
        assert read_transfer(api, transfer["id"])["clearing_status"] == "INITIATED"
    assert read_account(api, scenario.alpha.account_id)["reserved_cents"] == 10_000_000

    set_clock(api, "2026-08-03T14:11:00Z")
    third = send_from_alpha(api, scenario, 5_000_000)
    assert third["clearing_status"] == "INITIATED"
    assert third["fraud_score"] == 57
    assert third["fraud_reason_codes"] == ["AMOUNT_BAND", "NEW_BENEFICIARY"]

    account = read_account(api, scenario.alpha.account_id)
    assert account["reserved_cents"] == 15_000_000
    assert account["available_cents"] == 1_185_000_000
    assert account["current_balance_cents"] == 1_200_000_000
