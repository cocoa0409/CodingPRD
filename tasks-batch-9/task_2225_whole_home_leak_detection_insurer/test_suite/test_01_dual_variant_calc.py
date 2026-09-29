"""Two calculations that each publish two disagreeing variants of one figure.

The premium-credit machinery books a provisional accrual every period and then
recomputes the year once, so the two figures differ by rounding.  The claim
waterfall selects between a mitigated and an unmitigated algebra on the strength
of one derived flag, and the two answers differ by a quarter of a million cents.
"""

import pytest

from test_helpers import (
    ApiClient,
    assert_credit_attestation,
    assert_reimbursement_claim,
)
from test_helpers.fixtures import (
    acknowledge_ticket,
    approve_claim,
    begin_claim_review,
    file_claim,
    finalize_attestation,
    ingest_burst_reading,
    ingest_quiet_readings,
    open_attestation,
    read_attestation_list,
    read_claim,
    read_device_version,
    read_events,
    read_policy,
    read_tickets,
    reopen_valve,
    resolve_event,
    set_clock,
    setup_armed_device_with_policy,
    snooze_device,
)

POLICY_YEAR_START = "2026-08-02T00:00:00Z"
PERIOD_1 = ("2026-08-02T00:00:00Z", "2026-08-02T06:40:00Z")
PERIOD_1_READINGS = (
    "2026-08-02T00:00:00Z",
    "2026-08-02T02:00:00Z",
    "2026-08-02T04:00:00Z",
    "2026-08-02T06:20:00Z",
)
PERIOD_2 = ("2026-08-02T06:40:00Z", "2026-08-02T10:50:00Z")
PERIOD_2_READINGS = ("2026-08-02T06:40:00Z", "2026-08-02T08:40:00Z")


def _award_first_period(api: ApiClient) -> dict:
    """Arm a device under a 149900-cent policy and award its first period."""
    state = setup_armed_device_with_policy(api, POLICY_YEAR_START)
    set_clock(api, "2026-08-02T06:20:00Z")
    ingest_quiet_readings(api, state["device_id"], PERIOD_1_READINGS)
    first = open_attestation(api, state["policy_id"], *PERIOD_1)
    set_clock(api, PERIOD_1[1])
    state["attestation_1"] = finalize_attestation(api, first["id"])
    state["attestation_1_id"] = first["id"]
    return state


def _award_second_period(api: ApiClient, state: dict) -> dict:
    """Award the period that closes the policy year."""
    set_clock(api, "2026-08-02T08:40:00Z")
    ingest_quiet_readings(api, state["device_id"], PERIOD_2_READINGS)
    second = open_attestation(api, state["policy_id"], *PERIOD_2)
    set_clock(api, PERIOD_2[1])
    state["attestation_2"] = finalize_attestation(api, second["id"])
    state["attestation_2_id"] = second["id"]
    return state


class TestPremiumCreditVariants:
    def test_provisional_accrual_books_3748_for_a_95_00_percent_period(
        self, api: ApiClient
    ):
        """Verify the provisional variant on a single 400-minute period.

        "Consider the concrete case of a period running from 2026-08-02T00:00Z to
        2026-08-02T06:40Z — 400 minutes — with readings at 00:00, 02:00, 04:00, and
        06:20: the first three merge into a continuous stretch from 00:00 to 06:00
        and the last contributes a clamped 20 minutes, giving 380 `covered_minutes`
        and a `uptime_pct` of exactly 95.00, while the single 20-minute hole is
        shorter than an hour and so `offline_gap_count` is 0."
        "A tier is selected from `uptime_pct` by the first matching band, with every
        cut inclusive and no interpolation between bands: at least 99.00 percent
        earns a `tier_pct` of 0.12, at least 97.00 percent earns 0.08, at least
        95.00 percent earns 0.05, and anything below 95.00 percent earns nothing."
        "The **provisional period accrual** runs on every finalize:
        `credit_cents_awarded` is the policy's `annual_premium_cents` multiplied by
        `tier_pct`, divided by the two attestation periods that make up a policy
        year, and rounded half up to a whole cent."

        Design: Difficulty/dual_variant_calc/credit_provisional_vs_annual_true_up
        """
        state = _award_first_period(api)
        awarded = state["attestation_1"]
        assert_credit_attestation(awarded)

        assert awarded["period_minutes"] == 400
        assert awarded["covered_minutes"] == 380
        assert awarded["uptime_pct"] == pytest.approx(95.00, abs=0.01)
        assert awarded["offline_gap_count"] == 0
        assert awarded["tier_pct"] == pytest.approx(0.05, abs=0.01)
        assert awarded["credit_cents_awarded"] == 3748
        assert awarded["status"] == "FINALIZED_AWARDED"
        assert awarded["device_snapshot_lifecycle_state"] == "ARMED"

        # One period of two: the year has not closed, so no true-up is computed.
        assert awarded["is_policy_year_close"] is False
        assert awarded["true_up_cents"] == 0

        policy = read_policy(api, state["policy_id"])
        assert policy["credited_cents_total"] == 3748
        assert policy["finalized_period_count"] == 1
        assert policy["avg_uptime_pct"] == pytest.approx(95.00, abs=0.01)
        assert policy["current_credit_tier_pct"] == pytest.approx(0.05, abs=0.01)
        assert policy["credit_state"] == "CREDIT_ACTIVE"
        assert policy["last_attestation_end_at"].startswith("2026-08-02T06:40:00")
        assert policy["clawback_cents_total"] == 0

    def test_annual_true_up_on_the_year_closing_finalize_is_minus_one_cent(
        self, api: ApiClient
    ):
        """Verify the annual variant against the two provisional accruals.

        "The **final annual true-up** runs only on the finalize that brings the
        policy's `finalized_period_count` up to those two periods, at which point
        `is_policy_year_close` becomes true: the tier fractions of all the year's
        finalized periods, this one included, are summed; that sum is multiplied by
        `annual_premium_cents`, divided by two, and rounded half up to a whole cent
        *once*; and `true_up_cents` is that annual figure minus the sum of the
        `credit_cents_awarded` already booked across those same periods."
        "A worked case: an `annual_premium_cents` of 149900 with both periods at
        tier 0.05 books 3748 cents per period (from 3747.5 rounded half up), for
        7496 booked, while the annual close computes 7495 cents from 149900
        multiplied by 0.10 and divided by 2, so `true_up_cents` is −1."

        Design: Difficulty/dual_variant_calc/credit_provisional_vs_annual_true_up
        """
        state = _award_first_period(api)
        state = _award_second_period(api, state)
        closing = state["attestation_2"]
        assert_credit_attestation(closing)

        # 240 covered minutes of a 250-minute period: two samples exactly two
        # hours apart merge into one continuous block.
        assert closing["period_minutes"] == 250
        assert closing["covered_minutes"] == 240
        assert closing["uptime_pct"] == pytest.approx(96.00, abs=0.01)
        assert closing["offline_gap_count"] == 0
        assert closing["tier_pct"] == pytest.approx(0.05, abs=0.01)
        assert closing["credit_cents_awarded"] == 3748
        assert closing["status"] == "FINALIZED_AWARDED"
        assert closing["device_snapshot_lifecycle_state"] == "ARMED"

        assert closing["is_policy_year_close"] is True
        assert closing["true_up_cents"] == -1

        policy = read_policy(api, state["policy_id"])
        assert policy["credited_cents_total"] == 7495
        assert policy["true_up_cents"] == -1
        assert policy["finalized_period_count"] == 2
        assert policy["avg_uptime_pct"] == pytest.approx(95.50, abs=0.01)
        assert policy["credit_state"] == "CREDIT_ACTIVE"
        assert policy["last_attestation_end_at"].startswith("2026-08-02T10:50:00")
        assert policy["clawback_cents_total"] == 0

    def test_year_close_books_the_true_up_without_rewriting_the_earlier_period(
        self, api: ApiClient
    ):
        """The first period's provisional figure survives the annual recomputation.

        "The attestation rows themselves are never rewritten: `credited_cents_total`
        is defined as the sum of `credit_cents_awarded` across awarded periods, plus
        the `true_up_cents` of any policy-year-closing period, minus
        `clawback_cents_total`."
        "On a year-closing finalize the policy's own `true_up_cents` mirrors the
        closing attestation's `true_up_cents`."

        Design: Difficulty/dual_variant_calc/credit_provisional_vs_annual_true_up
        """
        state = _award_first_period(api)
        state = _award_second_period(api, state)

        rows = read_attestation_list(api, state["policy_id"])
        assert len(rows) == 2
        earlier, closing = rows

        assert earlier["id"] == state["attestation_1_id"]
        assert earlier["credit_cents_awarded"] == 3748
        assert earlier["is_policy_year_close"] is False
        assert earlier["true_up_cents"] == 0

        assert closing["id"] == state["attestation_2_id"]
        assert closing["credit_cents_awarded"] == 3748
        assert closing["true_up_cents"] == -1

        policy = read_policy(api, state["policy_id"])
        booked = earlier["credit_cents_awarded"] + closing["credit_cents_awarded"]
        assert booked == 7496
        assert (
            policy["credited_cents_total"]
            == booked + closing["true_up_cents"] - policy["clawback_cents_total"]
        )


CLAIM_POLICY_YEAR_START = "2026-08-01T00:00:00Z"
DOCUMENTED_LOSS_CENTS = 620_000


def _setup_mitigated_claim(api: ApiClient) -> dict:
    """A burst the valve closed on its own, resolved, then a water-damage claim."""
    state = setup_armed_device_with_policy(api, CLAIM_POLICY_YEAR_START)
    set_clock(api, "2026-08-01T07:00:00Z")
    ingest_burst_reading(api, state["device_id"], "2026-08-01T07:00:00Z")
    events = read_events(api, state["device_id"], event_state="ALERTED")
    assert len(events) == 1
    state["mitigated_event"] = events[0]

    claim = file_claim(
        api,
        state["policy_id"],
        state["device_id"],
        "WATER_DAMAGE",
        DOCUMENTED_LOSS_CENTS,
        state["homeowner_id"],
        anomaly_event_id=events[0]["id"],
    )
    state["mitigated_claim_id"] = claim["id"]
    begin_claim_review(api, claim["id"])

    # Resolution needs the ladder's first rung cleared, so the ticket is
    # acknowledged before the event is closed out.
    ticket = read_tickets(api, anomaly_event_id=events[0]["id"])[0]
    acknowledge_ticket(api, ticket["id"], state["homeowner_headers"])
    resolve_event(api, events[0]["id"], state["homeowner_id"])
    return state


def _setup_unmitigated_claim(api: ApiClient, state: dict) -> dict:
    """A second burst arriving mid-snooze, which never closes the valve."""
    reopen_valve(
        api,
        state["device_id"],
        state["homeowner_id"],
        read_device_version(api, state["device_id"], state["homeowner_headers"]),
    )
    set_clock(api, "2026-08-01T07:30:00Z")
    snooze_device(api, state["device_id"], state["homeowner_id"], 60)
    set_clock(api, "2026-08-01T08:00:00Z")
    ingest_burst_reading(
        api,
        state["device_id"],
        "2026-08-01T08:00:00Z",
        static_pressure_psi=28.0,
    )
    suppressed = read_events(api, state["device_id"], event_state="SUPPRESSED")
    assert len(suppressed) == 1
    state["unmitigated_event"] = suppressed[0]

    claim = file_claim(
        api,
        state["policy_id"],
        state["device_id"],
        "WATER_DAMAGE",
        DOCUMENTED_LOSS_CENTS,
        state["homeowner_id"],
        anomaly_event_id=suppressed[0]["id"],
    )
    state["unmitigated_claim_id"] = claim["id"]
    begin_claim_review(api, claim["id"])
    return state


class TestClaimPayoutVariants:
    def test_mitigated_variant_waives_the_deductible_and_pays_the_full_cap(
        self, api: ApiClient
    ):
        """A burst the device stopped by itself pays the water-damage cap.

        "Those two fields feed a derived verdict, `mitigation_credited`, which is
        true only when all three of the following hold: `auto_shutoff_executed` is
        true, `shutoff_latency_minutes` is at most 5 minutes, and
        `override_reopen_at` is still null."
        "Otherwise, if the referenced event's `mitigation_credited` is true —
        meaning the valve closed automatically within 5 minutes of detection and was
        never overridden — the variant is `MITIGATED`."
        "Under `MITIGATED`, `deductible_applied_cents` is 0 — the deductible is
        waived outright as the reward for a device that did its job — and
        `approved_payout_cents` is the smaller of `documented_loss_cents` and a
        water-damage cap of 500000 cents."

        Design: Difficulty/dual_variant_calc/claim_mitigated_vs_unmitigated_payout
        """
        state = _setup_mitigated_claim(api)
        event = state["mitigated_event"]
        assert event["auto_shutoff_executed"] is True
        assert event["shutoff_latency_minutes"] == pytest.approx(0.0, abs=0.01)
        assert event["mitigation_credited"] is True

        approved = approve_claim(api, state["mitigated_claim_id"])
        assert_reimbursement_claim(approved)
        assert approved["status"] == "APPROVED"
        assert approved["payout_variant"] == "MITIGATED"
        assert approved["deductible_applied_cents"] == 0
        assert approved["approved_payout_cents"] == 500_000
        assert approved["decided_by_user_id"] == "adj-01"

    def test_unmitigated_variant_applies_the_deductible_and_halves_the_cap(
        self, api: ApiClient
    ):
        """The identical loss on a snooze-suppressed burst settles at half the cap.

        "A catastrophic burst arriving mid-snooze therefore leaves the valve `OPEN`
        and `auto_shutoff_executed` false — a fact that later matters a great deal
        to the payout variant."
        "Otherwise the variant is `UNMITIGATED`, which covers no shutoff at all, a
        shutoff later than 5 minutes, and a shutoff that a homeowner override
        subsequently defeated."
        "Under `UNMITIGATED`, `deductible_applied_cents` is the smaller of
        `documented_loss_cents` and the policy's `deductible_cents`; the net loss is
        `documented_loss_cents` less that applied deductible; and
        `approved_payout_cents` is the smaller of two independently rounded figures
        — the net loss halved, rounded half up to a whole cent, and the
        500000-cent water-damage cap halved, rounded half up to a whole cent."

        Design: Difficulty/dual_variant_calc/claim_mitigated_vs_unmitigated_payout
        """
        state = _setup_mitigated_claim(api)
        state = _setup_unmitigated_claim(api, state)
        event = state["unmitigated_event"]
        assert event["suppression_reason"] == "SNOOZE_ACTIVE"
        assert event["auto_shutoff_executed"] is False
        assert event["mitigation_credited"] is False

        approved = approve_claim(api, state["unmitigated_claim_id"])
        assert_reimbursement_claim(approved)
        assert approved["status"] == "APPROVED"
        assert approved["payout_variant"] == "UNMITIGATED"
        assert approved["deductible_applied_cents"] == 100_000
        assert approved["approved_payout_cents"] == 250_000
        assert approved["decided_by_user_id"] == "adj-01"

    def test_the_two_variants_of_one_loss_diverge_by_exactly_250000_cents(
        self, api: ApiClient
    ):
        """Both algebras run on the same loss, device and policy.

        "On a documented loss of 620000 cents against a `deductible_cents` of
        100000, the `MITIGATED` path pays 500000 cents with
        `deductible_applied_cents` of 0, while the `UNMITIGATED` path applies the
        full 100000-cent deductible and pays 250000 cents — the smaller of 260000
        (half of the 520000 net) and 250000 (half of the cap)."
        "Because `paid_payout_cents_total` only moves at payment time, two claims
        can each individually clear the cap check at approval and the second can
        then fail the identical check when payment is attempted."

        Design: Difficulty/dual_variant_calc/claim_mitigated_vs_unmitigated_payout
        """
        state = _setup_mitigated_claim(api)
        state = _setup_unmitigated_claim(api, state)

        approve_claim(api, state["mitigated_claim_id"])
        approve_claim(api, state["unmitigated_claim_id"])

        mitigated = read_claim(api, state["mitigated_claim_id"])
        unmitigated = read_claim(api, state["unmitigated_claim_id"])
        assert mitigated["documented_loss_cents"] == unmitigated["documented_loss_cents"]
        assert mitigated["device_id"] == unmitigated["device_id"]
        assert mitigated["policy_id"] == unmitigated["policy_id"]
        assert (
            mitigated["approved_payout_cents"] - unmitigated["approved_payout_cents"]
            == 250_000
        )

        # Approval alone never books money against the policy.
        policy = read_policy(api, state["policy_id"])
        assert policy["paid_payout_cents_total"] == 0
