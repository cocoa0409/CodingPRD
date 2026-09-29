"""Direct-rate observation banding, the mediation ladder and the escalation cascade."""
from __future__ import annotations

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers.assertions import assert_evidence_common_fields, assert_instant_equals
from test_helpers.fixtures import (
    DEFAULT_INSTANT,
    hotel_agency_offer,
    parity_case_at,
)
from test_helpers.test_users import (
    PARITY_ANALYST,
    PARITY_ANALYST_USER_ID,
    PLATFORM_ADMIN,
    supplier_user_headers,
)


def test_a_breach_just_under_one_hundred_basis_points_opens_no_case(b, client):
    """58 basis points sits inside the tolerance band, so nothing is opened.

    PRD 3.5: "A breach below one percent — below 100 basis points — is `NONE`",
    and PRD 3.5 opens a case only when "the derived `severity` is not `NONE`".

    Design: Difficulty/boundary_precision_check/parity_breach_exactly_at_tolerance_opens_a_minor_case
    """
    ctx = hotel_agency_offer(b)
    assert ctx.offer["display_total_cents"] == 24240

    observation, case = parity_case_at(b, ctx, 24100)

    assert observation["breach_bps"] == 58
    assert observation["severity"] == "NONE"
    assert observation["parity_case_id"] is None
    assert case is None

    _rows, meta = validate_paginated(
        client.list_parity_cases(
            PLATFORM_ADMIN, params={"rate_plan_id": ctx.rate_plan["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_a_breach_exactly_at_one_hundred_basis_points_opens_a_minor_case(b, client):
    """The band's lower edge is inclusive, so exactly 100 bps is already MINOR.

    PRD 3.5: "From 100 basis points up to but not including 300 it is `MINOR`",
    and a new case takes "its `peak_breach_bps` set to this observation's
    `breach_bps`".

    Design: Difficulty/boundary_precision_check/parity_breach_exactly_at_tolerance_opens_a_minor_case
    """
    ctx = hotel_agency_offer(b)

    observation, case = parity_case_at(b, ctx, 24000)

    assert observation["breach_bps"] == 100
    assert observation["severity"] == "MINOR"
    assert case["status"] == "OPEN"
    assert case["severity"] == "MINOR"
    assert case["peak_breach_bps"] == 100
    assert case["opening_observation_id"] == observation["id"]
    assert case["notify_rounds"] == 0

    _rows, meta = validate_paginated(
        client.list_parity_cases(
            PLATFORM_ADMIN, params={"rate_plan_id": ctx.rate_plan["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_direct_rate_observation_is_immutable_evidence_with_no_version(b, client):
    """The observation records who saw the price and carries no mutable bookkeeping.

    PRD 3.5: "The observation is immutable evidence: it records
    `observed_by_user_id` from the acting identity and is never edited."

    Design: Corner/entities/direct_rate_observation_is_immutable_and_carries_no_version
    """
    ctx = hotel_agency_offer(b)

    observation = validate_success(
        client.create_parity_observation(
            ctx.rate_plan["id"],
            {
                "travel_date": ctx.travel_date,
                "channel": "SUPPLIER_WEB",
                "observed_at": "2026-08-06T09:00:00Z",
                "direct_total_cents": 24000,
            },
            PARITY_ANALYST,
        ),
        201,
    )

    assert_evidence_common_fields(observation)
    assert observation["breach_bps"] == 100
    assert observation["severity"] == "MINOR"
    assert observation["compared_offer_id"] == ctx.offer["id"]
    assert observation["observed_by_user_id"] == PARITY_ANALYST_USER_ID
    assert observation["parity_case_id"] is not None

    reread = validate_success(
        client.get_parity_observation(observation["id"], PLATFORM_ADMIN)
    )
    for field in (
        "id",
        "travel_date",
        "channel",
        "direct_total_cents",
        "breach_bps",
        "severity",
        "compared_offer_id",
        "parity_case_id",
        "observed_by_user_id",
        "created_at",
    ):
        assert reread[field] == observation[field], field


def test_no_case_is_opened_when_the_plan_is_not_parity_monitored(b, client):
    """An unmonitored plan still bands the breach but attaches no case.

    PRD 3.5: "Case attachment happens only when the plan's `parity_monitored` flag
    is true and the derived `severity` is not `NONE`."

    Design: Corner/validations/parity_case_is_not_opened_when_the_plan_is_not_monitored
    """
    ctx = hotel_agency_offer(b, publish=False)
    unmonitored = b.rate_plan(
        ctx.supplier["id"],
        ctx.market["id"],
        name="Unmonitored best available",
        tax_fee_pct=0.01,
        parity_monitored=False,
    )
    offer = b.live_offer(
        unmonitored["id"], travel_date="2026-09-25", net_rate_cents=24000
    )
    assert offer["display_total_cents"] == 24240

    observation = validate_success(
        client.create_parity_observation(
            unmonitored["id"],
            {
                "travel_date": "2026-09-25",
                "channel": "META",
                "observed_at": "2026-08-06T10:00:00Z",
                "direct_total_cents": 24000,
            },
            PARITY_ANALYST,
        ),
        201,
    )

    assert observation["breach_bps"] == 100
    assert observation["severity"] == "MINOR"
    assert observation["compared_offer_id"] == offer["id"]
    assert observation["parity_case_id"] is None

    _rows, meta = validate_paginated(
        client.list_parity_cases(PLATFORM_ADMIN, params={"rate_plan_id": unmonitored["id"]})
    )
    assert meta["total_count"] == 0

    plan = b.read_rate_plan(unmonitored["id"])
    assert plan["status"] == "ACTIVE"
    assert plan["parity_hold_case_id"] is None


def test_the_notify_and_respond_cycle_revisits_both_states_for_three_rounds(b, client):
    """Three notify/respond pairs walk the same two states and count the rounds.

    PRD 3.5: notification moves the case "`OPEN → SUPPLIER_NOTIFIED` or
    `SUPPLIER_RESPONDED → SUPPLIER_NOTIFIED` and incrementing `notify_rounds` by
    1", and a response moves it "`SUPPLIER_NOTIFIED → SUPPLIER_RESPONDED`".

    Design: Difficulty/non_linear_state_machine/parity_case_notify_respond_cycle_bounded_at_three_rounds
    """
    ctx = hotel_agency_offer(b)
    _observation, case = parity_case_at(b, ctx, 24000)
    supplier_id = ctx.supplier["id"]

    codes = ("DISPUTED", "NO_ACTION", "RATE_CORRECTED")
    for round_number, code in enumerate(codes, start=1):
        notified = validate_success(
            client.notify_parity_supplier(
                case["id"], {"note": f"round {round_number}"}, PARITY_ANALYST
            )
        )
        assert notified["status"] == "SUPPLIER_NOTIFIED"
        assert notified["notify_rounds"] == round_number

        responded = validate_success(
            client.respond_parity_case(
                case["id"],
                {"supplier_response_code": code, "note": "supplier reply"},
                supplier_user_headers(supplier_id),
            )
        )
        assert responded["status"] == "SUPPLIER_RESPONDED"
        assert responded["notify_rounds"] == round_number

    final = b.read_parity_case(case["id"])
    assert final["supplier_response_code"] == "RATE_CORRECTED"
    assert final["notify_rounds"] == 3


def test_a_fourth_notification_is_refused_at_the_round_limit(b, client):
    """Notification is bounded at three rounds and the refusal changes nothing.

    PRD 3.5: "Notification is bounded: it is available only while `notify_rounds`
    is still below three, and a fourth attempt is rejected with
    `ERR_PARITY_ROUND_LIMIT`."

    Design: Difficulty/non_linear_state_machine/parity_case_notify_respond_cycle_bounded_at_three_rounds
    """
    ctx = hotel_agency_offer(b)
    _observation, case = parity_case_at(b, ctx, 24000)
    supplier_id = ctx.supplier["id"]

    for code in ("DISPUTED", "NO_ACTION", "RATE_CORRECTED"):
        b.notify_parity(case["id"])
        b.respond_parity(case["id"], supplier_id, code=code)

    before = b.read_parity_case(case["id"])
    refused = client.notify_parity_supplier(
        case["id"], {"note": "round 4 must be refused"}, PARITY_ANALYST
    )
    validate_error(refused, E.ERR_PARITY_ROUND_LIMIT, 409)

    after = b.read_parity_case(case["id"])
    assert after["status"] == "SUPPLIER_RESPONDED"
    assert after["notify_rounds"] == 3
    assert after["version"] == before["version"]


def test_escalating_a_severe_case_holds_the_plan_and_suppresses_its_inventory(b, client):
    """Escalation stamps the case, holds the plan and pulls the live offer.

    PRD 3.5: "`escalated_at` is stamped from the logical clock and the cascade
    runs: ... the case's rate plan moves `ACTIVE → PARITY_HOLD` with
    `parity_hold_case_id` set to this case, every `LIVE` offer under that plan
    moves to `SUPPRESSED` with `suppression_reason` `PARITY_HOLD`".

    Design: Difficulty/transitive_cascade/parity_escalation_cascades_plan_hold_offer_suppression_and_strike
    """
    ctx = hotel_agency_offer(b)
    observation, case = parity_case_at(b, ctx, 22400)
    assert observation["breach_bps"] == 821
    assert observation["severity"] == "SEVERE"
    b.notify_parity(case["id"])

    escalated = validate_success(
        client.escalate_parity_case(
            case["id"],
            {"escalation_reason": "no supplier response to a severe breach"},
            PARITY_ANALYST,
        )
    )
    assert escalated["status"] == "ESCALATED"
    assert_instant_equals(escalated["escalated_at"], DEFAULT_INSTANT)

    plan = b.read_rate_plan(ctx.rate_plan["id"])
    assert plan["status"] == "PARITY_HOLD"
    assert plan["parity_hold_case_id"] == case["id"]

    offer = b.read_offer(ctx.offer["id"])
    assert offer["status"] == "SUPPRESSED"
    assert offer["suppression_reason"] == "PARITY_HOLD"


def test_escalation_strikes_the_supplier_without_hiding_it(b, client):
    """The strike counter moves but the supplier stays visible, and the peak holds.

    PRD 3.5: "the supplier's `parity_strikes` counter increments by 1"; the
    cascade in PRD 3.5 never touches `visibility_status`, and PRD 3.5 keeps
    `peak_breach_bps` as the highest observed breach.

    Design: Difficulty/transitive_cascade/parity_escalation_cascades_plan_hold_offer_suppression_and_strike
    """
    ctx = hotel_agency_offer(b)
    assert ctx.supplier["parity_strikes"] == 0
    _observation, case = parity_case_at(b, ctx, 22400)
    b.notify_parity(case["id"])

    b.escalate_parity(case["id"], reason="no supplier response to a severe breach")

    supplier = b.read_supplier(ctx.supplier["id"])
    assert supplier["parity_strikes"] == 1
    assert supplier["visibility_status"] == "ACTIVE"

    closed_case = b.read_parity_case(case["id"])
    assert closed_case["peak_breach_bps"] == 821
    assert closed_case["severity"] == "SEVERE"
