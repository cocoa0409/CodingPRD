"""Requests that break two rules at once, where the rejection order decides which
error the client sees. Each pair is then re-sent with the higher-priority defect
repaired so the lower-priority one becomes observable.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId, BCM_HEADERS, COUNSEL_HEADERS, api_client
from test_helpers.factories import (
    chargeback_payload,
    notice_payload,
    policy_withdraw_payload,
)
from test_helpers.fixtures import (
    bootstrap_authorized_channel,
    create_confirmed_trace,
    create_detected_violation,
    create_distributor,
    create_product,
    create_published_policy,
    current_distributor_version,
    current_reseller_version,
    pin_clock,
    read_distributor,
    read_reseller,
    read_violation,
)

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_10 = "2026-08-10T00:00:00Z"
OBSERVED_AUG_05 = "2026-08-05T00:00:00Z"
WITHDRAWN_REASON = "Programme suspended pending outside antitrust counsel review."


# --------------------------------------------------------------------------- #
# Instance 1 — antitrust outranks the unpublished-policy referential check
# --------------------------------------------------------------------------- #
def _setup_detected_violation_under_withdrawn_policy():
    """A detected violation whose cited policy has since been withdrawn."""
    pin_clock(CLOCK_AUG_01)
    world = bootstrap_authorized_channel(
        product_overrides={"msrp_cents": 15000, "standard_map_floor_cents": 10000},
    )
    pin_clock(CLOCK_AUG_10)
    violation, observation, evaluation = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=8000,
        channel="MARKETPLACE",
        observed_at=OBSERVED_AUG_05,
    )
    world.update({"violation": violation, "observation": observation, "evaluation": evaluation})
    world["policy"] = validate_success(
        api_client.withdraw_policy(
            world["policy"]["id"],
            policy_withdraw_payload(withdrawn_reason=WITHDRAWN_REASON),
            COUNSEL_HEADERS,
        )
    )
    return world


def test_a_pricing_discussion_declaration_is_reported_ahead_of_the_unpublished_policy():
    """The antitrust guardrail is checked before the referential precondition.

    PRD: "Note the consequence of this position: an antitrust failure is reported even
    when the request would also have failed a referential, temporal or domain check,
    but a stale-version failure is reported ahead of an antitrust failure."

    Design: Difficulty/priority_pair_validation_conflict/antitrust_pricing_discussion_outranks_unpublished_policy_rejected
    """
    world = _setup_detected_violation_under_withdrawn_policy()
    payload = notice_payload(
        world["reseller"]["id"],
        world["violation"]["id"],
        current_reseller_version(world["reseller"]["id"]),
        contains_pricing_discussion=True,
    )
    validate_error(
        api_client.issue_notice(payload, BCM_HEADERS),
        ApiErrorId.ERR_ANTITRUST_NEGOTIATION_PROHIBITED.value,
    )


def test_the_same_notice_without_the_declaration_reports_the_unpublished_policy():
    """With the antitrust defect repaired the withdrawn citation becomes visible.

    PRD: "What withdrawal does is close the gate on *new* enforcement — a notice may
    not be issued for a violation whose cited policy is no longer `PUBLISHED`, which
    surfaces as `ERR_POLICY_NOT_PUBLISHED`."

    Design: Difficulty/priority_pair_validation_conflict/antitrust_pricing_discussion_outranks_unpublished_policy_rejected
    """
    world = _setup_detected_violation_under_withdrawn_policy()
    assert world["policy"]["status"] == "WITHDRAWN"
    assert world["policy"]["withdrawn_reason"] == WITHDRAWN_REASON

    payload = notice_payload(
        world["reseller"]["id"],
        world["violation"]["id"],
        current_reseller_version(world["reseller"]["id"]),
        contains_pricing_discussion=False,
    )
    validate_error(
        api_client.issue_notice(payload, BCM_HEADERS),
        ApiErrorId.ERR_POLICY_NOT_PUBLISHED.value,
    )


def test_neither_refused_notice_moved_the_violation_or_the_points_ledger():
    """A rejected request is a no-op on every row it would have written.

    PRD: "When a single request violates several rules, exactly one error is returned,
    and which one is fully determined."

    Design: Difficulty/priority_pair_validation_conflict/antitrust_pricing_discussion_outranks_unpublished_policy_rejected
    """
    world = _setup_detected_violation_under_withdrawn_policy()
    version_before = current_reseller_version(world["reseller"]["id"])

    api_client.issue_notice(
        notice_payload(
            world["reseller"]["id"],
            world["violation"]["id"],
            version_before,
            contains_pricing_discussion=True,
        ),
        BCM_HEADERS,
    )
    api_client.issue_notice(
        notice_payload(
            world["reseller"]["id"], world["violation"]["id"], version_before
        ),
        BCM_HEADERS,
    )

    violation = read_violation(world["violation"]["id"])
    assert violation["status"] == "DETECTED"
    assert violation["assessed_points"] is None
    assert violation["assessed_floor_cents"] is None
    assert violation["cure_deadline_at"] is None

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["violation_points_total"] == 0
    assert reseller["version"] == version_before

    rows, meta = validate_paginated(
        api_client.list_notices(BCM_HEADERS, params={"reseller_id": world["reseller"]["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []


# --------------------------------------------------------------------------- #
# Instance 2 — optimistic concurrency outranks the fiscal ceiling
# --------------------------------------------------------------------------- #
def _setup_tiny_cap_distributor():
    """A confirmed trace against a distributor whose annual ceiling is only 5000 cents."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy()
    product = create_product(policy["id"], serialization_enabled=True)
    distributor = create_distributor(
        legal_name="Tiny Distribution", annual_chargeback_cap_cents=5000
    )
    pin_clock(CLOCK_AUG_10)
    purchase, unit, _observation = create_confirmed_trace(
        product["id"], distributor["id"], serial_number="SN-40", lot_code="LOT-E"
    )
    return {
        "product": product,
        "distributor": distributor,
        "purchase": purchase,
        "unit": unit,
    }


def test_a_stale_distributor_version_is_reported_ahead_of_the_fiscal_ceiling():
    """The concurrency check sits at step eight and the ceiling check runs last.

    PRD: "Because this check runs last, a request that both breaches the cap and fails
    any earlier check reports the earlier failure."

    Design: Difficulty/priority_pair_validation_conflict/stale_distributor_version_outranks_chargeback_cap_rejected
    """
    world = _setup_tiny_cap_distributor()
    current = current_distributor_version(world["distributor"]["id"])
    # Registering the serial unit increased shipped_units_total, so the row is on
    # version 2 and the version the client first saw is stale.
    assert current == 2

    validate_error(
        api_client.assess_chargeback(
            chargeback_payload(
                world["distributor"]["id"], world["purchase"]["id"], current - 1, diverted_units=4
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_STALE_DISTRIBUTOR_VERSION.value,
    )


def test_the_same_assessment_at_the_current_version_reports_the_fiscal_ceiling():
    """With the concurrency defect repaired the ceiling breach becomes visible.

    PRD: "The fiscal ceiling is checked last of all, after every other rule has passed:
    the distributor's current `chargeback_balance_cents` plus the new `amount_cents`
    must not exceed its `annual_chargeback_cap_cents`, with equality explicitly
    allowed."

    Design: Difficulty/priority_pair_validation_conflict/stale_distributor_version_outranks_chargeback_cap_rejected
    """
    world = _setup_tiny_cap_distributor()
    validate_error(
        api_client.assess_chargeback(
            chargeback_payload(
                world["distributor"]["id"],
                world["purchase"]["id"],
                current_distributor_version(world["distributor"]["id"]),
                diverted_units=4,
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_CHARGEBACK_CAP_EXCEEDED.value,
    )


def test_neither_refused_assessment_moved_the_distributor_ledgers():
    """Both ledgers, the standing and the version counter are all untouched.

    PRD: "A distributor's `chargeback_balance_cents` equals the sum of `amount_cents`
    over that distributor's chargebacks whose `status` is `ASSESSED`, `DISPUTED` or
    `UPHELD`, and its `diversion_score` equals the sum of `score_delta_applied` over
    the same filtered set."

    Design: Difficulty/priority_pair_validation_conflict/stale_distributor_version_outranks_chargeback_cap_rejected
    """
    world = _setup_tiny_cap_distributor()
    version_before = current_distributor_version(world["distributor"]["id"])

    api_client.assess_chargeback(
        chargeback_payload(
            world["distributor"]["id"], world["purchase"]["id"], version_before - 1, diverted_units=4
        ),
        BCM_HEADERS,
    )
    api_client.assess_chargeback(
        chargeback_payload(
            world["distributor"]["id"], world["purchase"]["id"], version_before, diverted_units=4
        ),
        BCM_HEADERS,
    )

    distributor = read_distributor(world["distributor"]["id"])
    assert distributor["chargeback_balance_cents"] == 0
    assert distributor["diversion_score"] == 0
    assert distributor["standing"] == "GOOD"
    assert distributor["version"] == version_before

    rows, meta = validate_paginated(
        api_client.list_chargebacks(
            BCM_HEADERS, params={"distributor_id": world["distributor"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []
