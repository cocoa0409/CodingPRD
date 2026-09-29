"""Operations gated by the state of a row other than the one being written."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import ConsultingApiClient
from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_fields,
    assert_money,
    assert_pagination_meta,
    assert_two_dp,
)


def _client_on_credit_hold(api: ConsultingApiClient) -> fx.Scenario:
    """A released document whose buyer has just been put on credit hold."""
    sc = fx.build_sow_client_review(api)
    get_success_data(
        api.set_client_status(sc.client_id, {"status": "CREDIT_HOLD"}, sc.admin)
    )
    return sc


def test_credit_hold_on_the_client_blocks_the_signature(
    api: ConsultingApiClient,
) -> None:
    """The document is ready; the buyer's commercial standing is not.

    PRD 3.5: "A signature additionally requires `signature_name` to be present
    — its absence is an `ERR_INVALID_REQUEST` — requires the client's `status`
    to be `ACTIVE`, since a client on `CREDIT_HOLD` or one that is `INACTIVE`
    is refused with `ERR_CLIENT_NOT_ELIGIBLE_FOR_SIGNATURE`, and requires a
    cleared conflict position."

    Design: Difficulty/cross_entity_state_dependency/sow_signature_blocked_by_client_credit_hold
    """
    sc = _client_on_credit_hold(api)

    response = api.sow_client_decision(
        sc.sow_id,
        {"decision": "SIGN", "signature_name": C.SEED_SIGNATURE_NAME},
        sc.client_contact,
    )

    validate_error(response, E.ERR_CLIENT_NOT_ELIGIBLE_FOR_SIGNATURE)
    sow = fx.read_sow(sc)
    assert_fields(sow, status="CLIENT_REVIEW", signed_at=None, signature_name=None)
    assert_fields(fx.read_opportunity(sc), status="SOW_ISSUED")

    # Signature is the only thing that creates an engagement, so none exists
    _, meta = validate_paginated(
        api.list_engagements(sc.partner, {"sow_id": sc.sow_id})
    )
    assert_pagination_meta(meta, total_count=0, has_more=False)


def test_restoring_the_client_to_active_lets_the_signature_through(
    api: ConsultingApiClient,
) -> None:
    """Nothing about the document changed; only the other row's state did.

    PRD 3.6: "Its `original_fee_cents` and its `contracted_fee_cents` both start
    at the document's `quoted_fee_cents`, its `contracted_hours` starts at the
    pursuit's `total_estimated_hours`, and its `not_to_exceed_cents` starts at
    the document's `not_to_exceed_cents` — which means it starts null for
    anything other than a time-and-materials contract."

    Design: Difficulty/cross_entity_state_dependency/sow_signature_blocked_by_client_credit_hold
    """
    sc = _client_on_credit_hold(api)
    get_success_data(api.set_client_status(sc.client_id, {"status": "ACTIVE"}, sc.admin))

    signed = fx.sign_sow(sc)

    assert_fields(signed, status="SIGNED", signature_name=C.SEED_SIGNATURE_NAME)
    assert signed["signed_at"].startswith("2026-08-03T09:00:00")
    assert_fields(fx.read_opportunity(sc), status="WON")

    rows, meta = validate_paginated(
        api.list_engagements(sc.partner, {"sow_id": sc.sow_id})
    )
    assert_pagination_meta(meta, total_count=1, has_more=False)
    engagement = rows[0]
    assert_fields(
        engagement,
        delivery_state=C.DELIVERY_MOBILIZING,
        economics_state=C.ECONOMICS_ON_TRACK,
        engagement_manager_consultant_id=None,
    )
    assert_money(engagement, "original_fee_cents", C.CANON_FIXED_FEE_QUOTED_CENTS)
    assert_money(engagement, "contracted_fee_cents", C.CANON_FIXED_FEE_QUOTED_CENTS)
    assert_two_dp(engagement, "contracted_hours", C.CANON_TOTAL_ESTIMATED_HOURS)
    # The two rates are pinned so later change pricing never re-reads the chain
    assert_two_dp(engagement, "pinned_scope_discount_pct", C.SCOPE_DISCOUNT_TIER_MID)
    assert_two_dp(engagement, "pinned_risk_premium_pct", C.RISK_PREMIUM_HIGH)


def _engagement_ready_to_close_with_an_open_escalation(
    api: ConsultingApiClient,
) -> fx.Scenario:
    """Every deliverable accepted, but an overrun escalation still unresolved."""
    sc = fx.build_started_engagement(api)
    fx.log_and_approve_time(sc, 60.0, C.SEED_WEEK_1)
    fx.log_and_approve_time(sc, 15.0, C.SEED_WEEK_2)
    fx.accept_deliverable(sc, sc.d1_id)
    fx.start_deliverable(sc, sc.d2_id, lead_id=sc.manager_id)
    fx.accept_deliverable(sc, sc.d2_id)
    fx.begin_closing(sc)
    return sc


def test_an_unresolved_escalation_row_blocks_the_final_close(
    api: ConsultingApiClient,
) -> None:
    """Closure reads a different entity entirely: the escalation register.

    PRD 3.9: "Firm leadership then closes the engagement, moving it
    `CLOSING → CLOSED`, again with no request body. One gate applies: no
    escalation of the engagement may remain in `OPEN`, `ACKNOWLEDGED` or
    `DELIVERY_HELD`, otherwise `ERR_OPEN_ESCALATION_BLOCKS_CLOSE`."

    Design: Difficulty/cross_entity_state_dependency/engagement_close_blocked_by_unresolved_economics_escalation
    """
    sc = _engagement_ready_to_close_with_an_open_escalation(api)

    response = api.close_engagement(sc.engagement_id, {}, sc.leadership)

    validate_error(response, E.ERR_OPEN_ESCALATION_BLOCKS_CLOSE)
    assert_fields(
        fx.read_engagement(sc),
        delivery_state=C.DELIVERY_CLOSING,
        closed_at=None,
    )
    assert_fields(fx.first_escalation(sc), status=C.ESCALATION_OPEN, resolved_at=None)
    assert_fields(fx.read_client(sc), completed_engagement_count=0)


def test_resolving_the_escalation_releases_the_close(
    api: ConsultingApiClient,
) -> None:
    """Writing the other row is what makes this row's transition legal.

    PRD 3.9: "In all three cases the leadership reconciliation runs identically:
    when the engagement's count of unresolved escalations at severity `HIGH` or
    above reaches zero, `leadership_review_required` is written false and the
    client's `at_risk_engagement_count` is decremented by 1 with the client's
    `version` advancing."

    Design: Difficulty/cross_entity_state_dependency/engagement_close_blocked_by_unresolved_economics_escalation
    """
    sc = _engagement_ready_to_close_with_an_open_escalation(api)
    escalation_id = fx.first_escalation(sc)["id"]

    resolved = fx.respond_to_escalation(sc, escalation_id, "RESOLVE")

    assert_fields(resolved, status=C.ESCALATION_RESOLVED, leadership_response="RESOLVE")
    assert resolved["resolved_at"].startswith("2026-09-14T09:00:00")
    assert_fields(fx.read_engagement(sc), leadership_review_required=False)
    assert_fields(fx.read_client(sc), at_risk_engagement_count=0)

    closed = fx.close_engagement(sc)

    assert_fields(closed, delivery_state=C.DELIVERY_CLOSED)
    assert closed["closed_at"].startswith("2026-09-14T09:00:00")
    # Economics is not a closure gate and keeps the value it had
    assert_fields(closed, economics_state=C.ECONOMICS_AT_RISK)
    assert_fields(fx.read_client(sc), completed_engagement_count=1)
