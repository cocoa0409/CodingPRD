"""Deal-memo multi-round negotiation lifecycle.

Covers the cyclic OFFERED<->COUNTERED negotiation loop with round_count
accumulation, and the cross-entity gate that an offer requires an
OFFER_EXTENDED submission.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    offer_payload,
    counter_payload,
    setup_offered_deal_memo,
    setup_rostered_talent,
    make_casting_director_headers,
    make_talent_headers,
    create_casting_call,
    create_submission,
    create_deal_memo_payload,
)
from test_helpers import api_client

AGENT = TEST_USERS["agent_headers"]


# ─── non_linear_state_machine: deal memo negotiation cycle ───────────────────
def test_deal_memo_reoffer_returns_to_offered_with_incremented_round_count(api):
    """PRD §3.5: "From `COUNTERED`, the director may re-offer, moving
    `COUNTERED → OFFERED` again with a fresh `offer_day_rate_cents` and
    `offer_usage_term_months` and another `round_count` increment — this is the
    negotiation loop, and it can cycle."

    Design: Difficulty/non_linear_state_machine/deal_memo_negotiation_cycle
    """
    base = setup_offered_deal_memo(
        union_status="NON_UNION", media_type="PRINT", usage_term_months=6,
        offer_day_rate_cents=150000,
    )
    dm_id = base["deal_memo"]["id"]
    cd_headers = base["cd_headers"]
    talent_headers = base["talent_headers"]
    # After setup: status OFFERED, round_count 1.
    assert base["deal_memo"]["status"] == "OFFERED"
    assert base["deal_memo"]["round_count"] == 1

    countered = validate_success(
        api.counter_deal_memo(
            dm_id, counter_payload(counter_day_rate_cents=180000,
                                   counter_usage_term_months=6),
            talent_headers,
        ),
        200,
    )
    assert countered["status"] == "COUNTERED"
    assert countered["round_count"] == 2

    reoffered = validate_success(
        api.offer_deal_memo(
            dm_id, offer_payload(offer_day_rate_cents=165000,
                                 offer_usage_term_months=6),
            cd_headers,
        ),
        200,
    )
    assert reoffered["status"] == "OFFERED"
    assert reoffered["round_count"] == 3
    assert reoffered["current_day_rate_cents"] == 165000


def test_deal_memo_counter_overwrites_standing_terms(api):
    """PRD §3.5: "From `OFFERED`, the talent may counter, moving
    `OFFERED → COUNTERED`; a counter supplies `counter_day_rate_cents` and
    `counter_usage_term_months`, which overwrite the standing terms, and likewise
    increments `round_count` by one."

    Design: Difficulty/non_linear_state_machine/deal_memo_negotiation_cycle
    """
    base = setup_offered_deal_memo(
        union_status="NON_UNION", media_type="PRINT", usage_term_months=6,
        offer_day_rate_cents=150000,
    )
    countered = validate_success(
        api.counter_deal_memo(
            base["deal_memo"]["id"],
            counter_payload(counter_day_rate_cents=180000, counter_usage_term_months=6),
            base["talent_headers"],
        ),
        200,
    )
    assert countered["status"] == "COUNTERED"
    assert countered["round_count"] == 2
    assert countered["current_day_rate_cents"] == 180000


# ─── validations: deal offer requires offerable submission ───────────────────
def test_offer_on_deal_memo_with_non_offerable_submission_rejected(api):
    """PRD §3.5: "This first offer is permitted only when the memo's submission
    is in `OFFER_EXTENDED`; otherwise it is refused with
    `ERR_SUBMISSION_NOT_OFFERABLE`."

    Design: Corner/validations/deal_offer_requires_offerable_submission
    """
    # Open a deal memo (advances submission to OFFER_EXTENDED), then withdraw the
    # submission so it is no longer OFFER_EXTENDED, then attempt the first offer.
    base = setup_rostered_talent(union_status="SAG")
    cd_id, talent_id, cc_id = base["cd"]["id"], base["talent"]["id"], base["comp_card"]["id"]
    cd_headers = make_casting_director_headers(cd_id)
    talent_headers = make_talent_headers(talent_id)

    call = create_casting_call(cd_id, media_type="STREAMING")
    submission = create_submission(call["id"], talent_id, cc_id)
    dm = get_success_data(
        api.create_deal_memo(
            create_deal_memo_payload(call["id"], talent_id, submission["id"]),
            cd_headers,
        )
    )
    get_success_data(api.withdraw_submission(submission["id"], talent_headers))

    resp = api.offer_deal_memo(
        dm["id"], offer_payload(offer_day_rate_cents=200000, offer_usage_term_months=12),
        cd_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SUBMISSION_NOT_OFFERABLE.value, 409)
