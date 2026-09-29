"""Two transitive cascades: the door refusal chain and the audit-score chain."""

from test_helpers import (
    ADMIN_HEADERS,
    assert_instant_equal,
    assert_score_equal,
    factories as f,
    fixtures as fx,
    validate_paginated,
    validate_success,
)

DOORSTEP = "2026-08-20T16:00:00Z"
EVENING = "2026-08-20T18:00:00Z"
DECOY_ONE = "2026-08-22T16:00:00Z"
DECOY_TWO = "2026-08-22T17:00:00Z"


def _decoy_probe(api, world, scheduled_at, scenario_type):
    """A decoy order plus the secret-shopper test staged against it."""
    decoy = fx.create_order(
        api,
        world["customer"]["id"],
        world["jurisdiction"]["id"],
        world["partner"]["id"],
        scheduled_at,
        0,
    )
    probe = fx.schedule_shopper_test(
        api,
        world["courier"]["id"],
        decoy["id"],
        scenario_type=scenario_type,
        scheduled_at=scheduled_at,
    )
    return decoy, probe


def _partner_holding_two_open_cases(api):
    """A partner one case short of the three-open-case posture threshold.

    Two orders are then carried to `DISPATCHED`: the first has a courier at the
    door with the identification already verified, the second has no attempt of its
    own and exists purely to observe the fourth cascade link.
    """
    world = fx.build_restricted_world(api, policy_overrides={"unit_scale_factor": 1.15})
    partner_id = world["partner"]["id"]

    decoy_one, probe_one = _decoy_probe(api, world, DECOY_ONE, "NO_ID_PRESENTED")
    fx.open_manual_case(
        api, partner_id, secret_shopper_test_id=probe_one["id"], severity="MAJOR",
        summary="Open case 1 pending investigation",
    )
    decoy_two, probe_two = _decoy_probe(api, world, DECOY_TWO, "EXPIRED_DOCUMENT")
    fx.open_manual_case(
        api, partner_id, secret_shopper_test_id=probe_two["id"], severity="MAJOR",
        summary="Open case 2 pending investigation",
    )

    built_a = fx.add_restricted_order(
        api, world, quantity=3, scheduled_delivery_at=DOORSTEP, delivery_fee_cents=600
    )
    order_a = fx.submit_order(api, built_a["order"])
    fx.dispatch_order(api, order_a)

    built_b = fx.add_restricted_order(
        api, world, quantity=3, scheduled_delivery_at=EVENING, delivery_fee_cents=600
    )
    order_b = fx.submit_order(api, built_b["order"])
    fx.dispatch_order(api, order_b)

    attempt = fx.open_attempt(api, order_a, world["courier"], DOORSTEP)
    verified = fx.record_id_check(
        api, attempt, world["courier"]["id"], scanned_dob=f.ADULT_DOB
    )
    world.update(
        {
            "order_a": order_a,
            "order_b": order_b,
            "attempt": verified,
            "decoys": [decoy_one, decoy_two],
        }
    )
    return world


def test_01_a_compliance_refusal_moves_the_attempt_and_opens_a_case(api):
    """PRD 3.7: "**Link two** fires only when link one recorded a *compliance*
    refusal — that is, when `refusal_reason` is one of `UNDERAGE_RECIPIENT`,
    `ID_MISMATCH`, `NO_ACCEPTABLE_ID` or `INTOXICATED_RECIPIENT` — and opens a
    violation case automatically: its `origin` is `AUTO_REFUSAL`, its
    `delivery_attempt_id` names this attempt, its `delivery_partner_id` copies the
    order's, its `state` opens at `OPEN`, and its `severity` is read off a fixed
    mapping from the refusal reason — `UNDERAGE_RECIPIENT` maps to `CRITICAL`,
    `ID_MISMATCH` to `MAJOR`, `INTOXICATED_RECIPIENT` to `MAJOR` and
    `NO_ACCEPTABLE_ID` to `MINOR`."

    Design: Difficulty/transitive_cascade/door_refusal_cascades_through_case_posture_and_a_second_order
    """
    world = _partner_holding_two_open_cases(api)

    fx.record_refusal(
        api,
        world["attempt"],
        world["courier"]["id"],
        "INTOXICATED_RECIPIENT",
        observed_indicators=["slurred speech"],
    )

    attempt = fx.read_attempt(api, world["attempt"]["id"])
    assert attempt["state"] == "REFUSED"
    order_a = fx.read_order(api, world["order_a"]["id"])
    assert order_a["fulfillment_state"] == "RETURN_IN_TRANSIT"

    cases, _meta = validate_paginated(
        api.list_violation_cases(
            ADMIN_HEADERS, {"delivery_attempt_id": world["attempt"]["id"]}
        )
    )
    assert len(cases) == 1, f"exactly one case must name this attempt; got {len(cases)}"
    case = cases[0]
    assert case["origin"] == "AUTO_REFUSAL"
    assert case["state"] == "OPEN"
    assert case["severity"] == "MAJOR"
    assert case["delivery_partner_id"] == world["partner"]["id"]


def test_02_the_new_case_pushes_the_open_count_over_the_posture_threshold(api):
    """PRD 3.4: "The derivation is a two-step threshold ladder evaluated in this order: if
    the partner's `license_risk_score` is at or above 60.00, **or** its
    `open_critical_case_count` is at least 2, the posture becomes `SUSPENDED`; otherwise, if
    `license_risk_score` is at or above 25.00, **or** `open_case_count` is at least 3, the
    posture becomes `RESTRICTED`; otherwise it becomes `OPEN`."

    Design: Difficulty/transitive_cascade/door_refusal_cascades_through_case_posture_and_a_second_order
    """
    world = _partner_holding_two_open_cases(api)
    before = fx.read_partner(api, world["partner"]["id"])
    assert before["open_case_count"] == 2
    assert before["posture"] == "OPEN"

    fx.record_refusal(
        api,
        world["attempt"],
        world["courier"]["id"],
        "INTOXICATED_RECIPIENT",
        observed_indicators=["slurred speech"],
    )

    partner = fx.read_partner(api, world["partner"]["id"])
    assert partner["open_case_count"] == 3
    assert partner["open_critical_case_count"] == 0
    assert_score_equal(partner["license_risk_score"], 0.00, "license_risk_score")
    assert partner["posture"] == "RESTRICTED", (
        "no case has been substantiated, so the ladder is reached on the open-case "
        f"count alone; got {partner['posture']}"
    )


def test_03_the_worsened_posture_holds_a_second_order_the_refusal_never_named(api):
    """PRD 3.4: "Each order of that partner whose `fulfillment_state` is
    `DISPATCHED`, processed in `created_at` ascending order, is held: its
    `fulfillment_state` moves `DISPATCHED → HELD_AT_HUB`, its `dispatched_at` is
    cleared, and its `hold_reason` is set to the literal prefix `PARTNER_POSTURE_`
    followed by the partner's new posture value."

    Design: Difficulty/transitive_cascade/door_refusal_cascades_through_case_posture_and_a_second_order
    """
    world = _partner_holding_two_open_cases(api)

    fx.record_refusal(
        api,
        world["attempt"],
        world["courier"]["id"],
        "INTOXICATED_RECIPIENT",
        observed_indicators=["slurred speech"],
    )

    order_b = fx.read_order(api, world["order_b"]["id"])
    assert order_b["fulfillment_state"] == "HELD_AT_HUB"
    assert order_b["compliance_state"] == "PENDING_COMPLIANCE_REVIEW"
    assert order_b["hold_reason"] == "PARTNER_POSTURE_RESTRICTED"
    assert order_b["dispatched_at"] is None

    order_a = fx.read_order(api, world["order_a"]["id"])
    assert order_a["compliance_state"] == "PREVERIFIED", (
        "the hold pass reaches only DISPATCHED orders, and this one had already moved "
        f"to OUT_FOR_DELIVERY; got {order_a['compliance_state']}"
    )
    for decoy in world["decoys"]:
        assert fx.read_order(api, decoy["id"])["fulfillment_state"] == "CREATED"


def test_04_the_same_refusal_levies_exactly_one_customer_strike(api):
    """PRD 3.7: "When that count reaches 3, the customer's `blocked_until` is set to
    the strike-triggering attempt's `started_at` plus 30 days, which is what the
    purchaser-eligibility check of 3.3 later reads to raise
    `ERR_CUSTOMER_DELIVERY_BLOCKED`. Below the third strike, `blocked_until` remains
    null."

    Design: Difficulty/transitive_cascade/door_refusal_cascades_through_case_posture_and_a_second_order
    """
    world = _partner_holding_two_open_cases(api)

    fx.record_refusal(
        api,
        world["attempt"],
        world["courier"]["id"],
        "INTOXICATED_RECIPIENT",
        observed_indicators=["slurred speech"],
    )

    customer = fx.read_customer(api, world["customer"]["id"])
    assert customer["refusal_strikes"] == 1
    assert customer["blocked_until"] is None


# ===========================================================================
# The audit cascade: score, then credential, then in-flight work
# ===========================================================================
def _courier_one_failed_probe_from_suspension(api):
    """A courier sitting at 75.00 after one failed probe, with a second probe pending.

    A real customer order is in flight under an `INITIATED` attempt so the third
    cascade link has somewhere to land.
    """
    world = fx.build_restricted_world(api, policy_overrides={"unit_scale_factor": 1.15})

    _decoy_one, probe_one = _decoy_probe(api, world, DECOY_ONE, "NO_ID_PRESENTED")
    fx.record_shopper_outcome(
        api,
        probe_one["id"],
        "HANDOVER",
        findings="Courier handed the package to a shopper who presented no identification",
    )
    _decoy_two, probe_two = _decoy_probe(api, world, DECOY_TWO, "EXPIRED_DOCUMENT")

    built = fx.add_restricted_order(
        api, world, quantity=3, scheduled_delivery_at=DOORSTEP, delivery_fee_cents=600
    )
    order_c = fx.submit_order(api, built["order"])
    fx.dispatch_order(api, order_c)
    attempt = fx.open_attempt(api, order_c, world["courier"], DOORSTEP)

    world.update(
        {"probe_one": probe_one, "probe_two": probe_two, "order_c": order_c, "attempt": attempt}
    )
    return world


def test_05_a_second_failed_probe_rebuilds_the_score_to_fifty(api):
    """PRD 3.8: "Then every secret-shopper test of that courier whose `verdict` is
    `FAIL`, with no time window at all and visited in `recorded_at` ascending then
    `created_at` ascending order, subtracts 25.00."

    Design: Difficulty/transitive_cascade/shopper_fail_cascades_through_score_certification_and_open_attempt
    """
    world = _courier_one_failed_probe_from_suspension(api)
    after_one_fail = fx.read_courier(api, world["courier"]["id"])
    assert_score_equal(after_one_fail["compliance_score"], 75.00, "compliance_score")
    assert after_one_fail["certification_state"] == "CERTIFIED"

    fx.record_shopper_outcome(
        api,
        world["probe_two"]["id"],
        "HANDOVER",
        findings="Courier accepted an expired document without escalating",
    )

    probe = validate_success(
        api.get_secret_shopper_test(world["probe_two"]["id"], ADMIN_HEADERS)
    )
    assert probe["verdict"] == "FAIL"
    assert_instant_equal(probe["recorded_at"], "2026-08-20T12:00:00Z", "recorded_at")
    courier = fx.read_courier(api, world["courier"]["id"])
    assert_score_equal(courier["compliance_score"], 50.00, "compliance_score")


def test_06_the_collapsed_score_suspends_the_certification_and_aborts_the_attempt(api):
    """PRD 3.8: "**Link two** fires only if that recomputed score falls below
    70.00: every certification of that courier whose `state` is `ACTIVE` moves
    `ACTIVE → SUSPENDED`, processed in `created_at` ascending order. **Link three**
    fires only because those certifications were suspended: every delivery attempt
    of that courier in `INITIATED`, `ID_VERIFIED` or `ID_REJECTED` is aborted and its
    order sent back as a return, exactly as 3.7 describes."

    Design: Difficulty/transitive_cascade/shopper_fail_cascades_through_score_certification_and_open_attempt
    """
    world = _courier_one_failed_probe_from_suspension(api)

    fx.record_shopper_outcome(api, world["probe_two"]["id"], "HANDOVER")

    certification = fx.read_certification(api, world["certification"]["id"])
    assert certification["state"] == "SUSPENDED"
    attempt = fx.read_attempt(api, world["attempt"]["id"])
    assert attempt["state"] == "ABORTED"
    assert attempt["abort_reason"] == "CERTIFICATION_SUSPENDED"
    order_c = fx.read_order(api, world["order_c"]["id"])
    assert order_c["fulfillment_state"] == "RETURN_IN_TRANSIT"
    assert order_c["hold_reason"] == "COURIER_CERTIFICATION_SUSPENDED"


def test_07_the_cascade_stops_at_the_courier_and_never_reaches_the_posture(api):
    """PRD 3.5: "Otherwise, with no `ACTIVE` certification but an acceptable score,
    the courier is `UNCERTIFIED`, which is the `CERTIFIED → UNCERTIFIED` edge taken
    when the last live certification expires, is suspended or is revoked."

    Design: Difficulty/transitive_cascade/shopper_fail_cascades_through_score_certification_and_open_attempt
    """
    world = _courier_one_failed_probe_from_suspension(api)

    fx.record_shopper_outcome(api, world["probe_two"]["id"], "HANDOVER")

    courier = fx.read_courier(api, world["courier"]["id"])
    assert courier["certification_state"] == "UNCERTIFIED", (
        "the score 50.00 is still at or above the 40.00 courier-suspension line, so the "
        f"derivation lands on UNCERTIFIED rather than SUSPENDED; got "
        f"{courier['certification_state']}"
    )
    assert courier["dispatch_eligible"] is False
    partner = fx.read_partner(api, world["partner"]["id"])
    assert partner["open_case_count"] == 2
    assert partner["posture"] == "OPEN"
    assert_score_equal(partner["license_risk_score"], 0.00, "license_risk_score")
