"""Whether a writing response already carries everything its own rule computed."""

from test_helpers import (
    OFFICER_A_HEADERS,
    assert_attempt_state,
    assert_cents,
    assert_order_states,
    assert_page_meta,
    assert_restriction_types,
    assert_score_equal,
    assert_units_equal,
    factories as f,
    fixtures as fx,
    make_courier_headers,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-20T12:00:00Z"
EVENING = "2026-08-20T18:00:00Z"

# The submit-time figures the PRD derives for two 6800-cent wine lines at 1.50
# restricted units each, carried under a 600-cent delivery fee.
SUBTOTAL_CENTS = 13600
CHARGED_CENTS = 14200
EXPOSURE_UNITS = 3.00

# The fields the submit rule computes; a deferred derivation shows up as a
# disagreement between the writing response and the very next read.
FROZEN_FIELDS = (
    "compliance_state",
    "fulfillment_state",
    "restriction_types",
    "applied_policy_ids",
    "provisional_restricted_units",
    "item_subtotal_cents",
    "charged_cents",
    "submitted_at",
)


def _instant(value):
    """The instant a timestamp names, without the fractional digits of PRD 2.4."""
    assert value is not None, "the timestamp must not be null"
    return value.replace("Z", "").split(".")[0]


def _envelope_of(response):
    """The whole body, so the wrapper of PRD 2.2 can be inspected alongside the row."""
    return response.json()


def test_01_the_writing_response_already_carries_every_field_its_rule_derived(api):
    """PRD 3.3: "On every successful submission — whatever the compliance outcome — the
    physical dimension advances `CREATED → SUBMITTED` and `submitted_at` is stamped from the
    logical clock, `item_subtotal_cents` is frozen as the sum of `line_total_cents` across
    **all** of the order's lines regardless of their `line_state`, and `charged_cents` is
    frozen as `item_subtotal_cents` plus `delivery_fee_cents`."

    PRD 3.3: "A `MATCH` routes `DRAFT_UNVERIFIED → PREVERIFIED`."

    PRD 3.7: "**Link one** moves the attempt `INITIATED → REFUSED`, `ID_VERIFIED → REFUSED` or
    `ID_REJECTED → REFUSED` according to where it stood, and the order `OUT_FOR_DELIVERY →
    RETURN_IN_TRANSIT`; it happens on every refusal without exception."

    PRD 2.2: "The `response_type` is either "object" for a single resource or "array" for a
    list of resources."

    Design: Corner/consistency_model/corner_every_derived_field_is_already_present_in_the_writing_response
    """
    world = fx.build_restricted_world(api)
    built = fx.add_restricted_order(
        api, world, quantity=2, scheduled_delivery_at=EVENING, delivery_fee_cents=600
    )
    order_id = built["order"]["id"]

    submit_response = api.submit_order(order_id, world["customer_headers"])
    submitted = validate_success(submit_response)

    assert_order_states(
        submitted, compliance_state="PREVERIFIED", fulfillment_state="SUBMITTED"
    )
    assert_restriction_types(submitted, ["ALCOHOL"])
    assert_units_equal(submitted["provisional_restricted_units"], EXPOSURE_UNITS)
    assert_cents(submitted["item_subtotal_cents"], SUBTOTAL_CENTS, "item_subtotal_cents")
    assert_cents(submitted["charged_cents"], CHARGED_CENTS, "charged_cents")
    assert _instant(submitted["submitted_at"]) == _instant(CLOCK), (
        f"`submitted_at` is stamped from the logical clock; got {submitted['submitted_at']!r}"
    )
    assert submitted["applied_policy_ids"] == [world["policy"]["id"]]

    read_back = validate_success(api.get_order(order_id, world["customer_headers"]))

    for field in FROZEN_FIELDS:
        assert read_back[field] == submitted[field], (
            f"the read of `{field}` disagrees with the write that computed it: "
            f"{read_back[field]!r} after {submitted[field]!r}"
        )
    envelope = _envelope_of(submit_response)
    assert envelope["response_type"] == "object", (
        f"one order comes back as an object; got {envelope['response_type']!r}"
    )
    assert envelope["meta"]["api_request_id"].startswith("req_")
    assert envelope["meta"]["api_request_timestamp"]

    fx.dispatch_order(api, submitted)
    fx.set_clock(api, EVENING)
    attempt = fx.open_attempt(api, submitted, world["courier"], started_at=EVENING)
    refuse_response = api.record_refusal(
        attempt["id"],
        f.refusal_payload(
            "INTOXICATED_RECIPIENT",
            observed_indicators=["slurred speech", "unsteady gait"],
        ),
        make_courier_headers(world["courier"]["id"]),
    )
    refused = validate_success(refuse_response)

    assert_attempt_state(refused, "REFUSED")
    assert refused["refusal_reason"] == "INTOXICATED_RECIPIENT"
    assert refused["observed_indicators"] == ["slurred speech", "unsteady gait"]

    returning = fx.read_order(api, order_id)

    assert returning["fulfillment_state"] == "RETURN_IN_TRANSIT", (
        "the refusal answered only once its own cascade had landed; the very next read shows "
        f"{returning['fulfillment_state']!r}"
    )
    cases, cases_meta = validate_paginated(
        api.list_violation_cases(
            OFFICER_A_HEADERS, {"delivery_partner_id": world["partner"]["id"]}
        )
    )
    assert_page_meta(cases_meta, total_count=1)
    assert cases[0]["origin"] == "AUTO_REFUSAL"
    assert cases[0]["state"] == "OPEN"
    assessment = validate_success(
        api.get_risk_assessment(world["partner"]["id"], OFFICER_A_HEADERS)
    )
    assert assessment["open_case_count"] == 1
    assert_score_equal(assessment["rolling_90d_score"], 0.00, "rolling_90d_score")
    assert assessment["posture"] == "OPEN", (
        "an unsubstantiated case scores nothing and one open case is below the ladder's "
        f"three-case rung; got {assessment['posture']!r}"
    )
    struck = fx.read_customer(api, world["customer"]["id"])
    assert struck["refusal_strikes"] == 1, (
        f"the strike is visible immediately; got {struck['refusal_strikes']}"
    )
    assert struck["blocked_until"] is None, (
        f"one strike is below the third; got {struck['blocked_until']!r}"
    )
    attempt_read = api.get_delivery_attempt(
        attempt["id"], make_courier_headers(world["courier"]["id"])
    )
    validate_success(attempt_read)
    read_envelope = _envelope_of(attempt_read)
    assert read_envelope["response_type"] == "object"
    assert read_envelope["meta"]["api_request_id"].startswith("req_")
    assert read_envelope["meta"]["api_request_timestamp"]
