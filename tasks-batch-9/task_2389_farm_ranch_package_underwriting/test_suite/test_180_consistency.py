"""Read-your-write completeness on the two widest cascades: everything the rating
and the completion derive is already in the response that performed them, and the
reads that follow only confirm it."""

from test_helpers import (
    COMPLIANCE,
    UW,
    complete_inspection,
    read_ledger,
    read_policy,
    read_pool,
    read_recommendations,
    register_inspector,
    schedule_inspection_ok,
    setup_draft_policy_with_dwelling,
    validate_success,
)


def test_the_rating_and_the_completion_answer_with_everything_they_derived(api):
    """"If no trigger matches, the policy advances `DRAFT → RATED`,
    `quote_expires_at` is set to `rating_valuation_date` plus 30 days as exact
    instant arithmetic, and `referred_at`, `referred_by_user_id` and
    `referral_reason_code` are cleared." "A reservation row is written in `RESERVED`
    carrying `amount_cents`, `utilization_at_rating` (the prospective utilization
    rounded to six decimal places), `scarcity_factor` and `load_cents`, after which
    the pool's `reserved_cents` grows by `amount_cents`, `available_cents` is
    re-derived, and the pool's `version` climbs by 1." "Hop one advances the
    inspection `SCHEDULED → COMPLETED`, stores `completed_at` at the current clock
    instant along with `findings_summary`, sets `recommendation_count` to the number
    of elements in `findings`, and computes `hazard_score` as the base score for the
    `inspection_type` plus the severity weight of each supplied finding, the whole
    capped at 100." "Hop two moves the policy's compliance axis: with at least one
    finding it advances to `RECS_OPEN` — reachable from `NOT_INSPECTED` or from
    `COMPLIANT` alike — while a completion with an empty `findings` array advances
    it to `COMPLIANT` provided that afterwards no recommendation on any inspection
    of the policy remains in `OPEN`, `OVERDUE` or `SUBMITTED`, a move available from
    `NOT_INSPECTED`, `RECS_OPEN`, `RECS_OVERDUE` or `SUSPENDED`." Each figure is
    already on the writing response, and "a policy's ledger is likewise returned in
    `sequence_no` ascending order rather than by timestamp."

    Design: Corner/consistency_model/corner_every_cascade_effect_is_visible_in_the_same_response
    """
    scenario = setup_draft_policy_with_dwelling()
    inspector = register_inspector()
    inspection = schedule_inspection_ok(scenario.policy_id, inspector["id"])

    rated = validate_success(
        api.rate_farm_policy(scenario.policy_id, {"expected_policy_version": 1}, UW)
    )

    assert rated["uw_status"] == "RATED"
    assert rated["exposed_tiv_cents"] == 40_000_000
    assert rated["property_premium_cents"] == 144_000
    assert rated["cat_load_cents"] == 125_200
    assert rated["total_premium_cents"] == 269_200
    assert rated["rating_valuation_date"].startswith("2026-08-15T00:00:00")
    assert rated["quote_expires_at"].startswith("2026-09-14T00:00:00")
    assert rated["referral_reason_code"] is None
    assert rated["version"] == 2

    pool = read_pool(scenario.hail_pool["id"])
    assert pool["reserved_cents"] == 20_000_000
    assert pool["available_cents"] == 180_000_000
    assert pool["version"] == 2

    completed = validate_success(
        complete_inspection(
            inspection["id"],
            inspector["id"],
            findings_summary="one major deficiency",
            findings=[
                {
                    "severity": "MAJOR",
                    "description": "Replace the shop wiring",
                    "due_date": "2026-09-30",
                }
            ],
        )
    )

    assert completed["status"] == "COMPLETED"
    assert completed["hazard_score"] == 22
    assert completed["recommendation_count"] == 1
    assert completed["findings_summary"] == "one major deficiency"
    assert completed["completed_at"].startswith("2026-08-15T00:00:00")

    policy = read_policy(scenario.policy_id, COMPLIANCE)
    assert policy["compliance_status"] == "RECS_OPEN"
    assert policy["uw_status"] == "RATED"
    assert policy["total_premium_cents"] == 269_200

    raised = read_recommendations(inspection["id"], COMPLIANCE)
    assert len(raised) == 1
    assert raised[0]["sequence_no"] == 1
    assert raised[0]["status"] == "OPEN"
    assert raised[0]["severity"] == "MAJOR"
    assert raised[0]["due_date"] == "2026-09-30"
    assert raised[0]["inspection_id"] == inspection["id"]

    entries = read_ledger(scenario.policy_id)
    assert [(row["sequence_no"], row["txn_type"], row["amount_cents"]) for row in entries] == [
        (1, "BASE_PROPERTY", 144_000),
        (2, "CAT_LOAD", 125_200),
    ]
