"""Queue A — rule_id: transitive_cascade.

Chains in which every link is caused strictly by the previous one: the depth-5
demobilization cascade and the depth-4 advance-void cascade.
"""
from test_helpers import validate_success
from test_helpers.assertions import assert_money_equals
from test_helpers.test_users import (
    make_catastrophe_manager_headers,
    make_claims_examiner_headers,
    make_deployment_coordinator_headers,
)

CM = make_catastrophe_manager_headers("cm_1")
DC = make_deployment_coordinator_headers("dc_1")
CE = make_claims_examiner_headers("ce_1")
CE_ISSUER = make_claims_examiner_headers("ce_5")

_SEVERE_CLAIM_LINES = [
    {
        "coverage_code": "DWELLING",
        "limit_amount": 200000,
        "deductible_amount": 5000,
        "estimated_damage_amount": 250000,
    }
]


# ---------------------------------------------------------------------------
# Instance 1 — demobilize_deployment_chain_depth5_end_to_end
# ---------------------------------------------------------------------------
def _deployed_adjuster_with_three_scheduled_inspections(api):
    """CAT-2026-401 DECLARED @ 0.5000; one STAFF adjuster CONFIRMED onto a FIELD
    deployment 2026-09-01 -> 2026-09-10 drawing 1 of 4 rooms; three CAT_SEVERE
    claims each carrying one SCHEDULED assignment funded by that deployment.
    Clock left at 2026-09-05."""
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-401",
                "peril_type": "HURRICANE",
                "jurisdiction_state": "FL",
                "event_start_utc": "2026-07-29T00:00:00.000Z",
                "exposure_count": 1200,
                "avg_insured_value": 320000,
                "expected_severity_index": 0.5000,
            },
            CM,
        ),
        201,
    )
    validate_success(api.declare_event(event["id"], CM))
    adjuster = validate_success(
        api.create_adjuster(
            {
                "full_name": "Fran Field",
                "employment_type": "STAFF",
                "home_state": "FL",
                "licensed_states": ["FL"],
                "license_expiry_utc": "2027-10-31T00:00:00.000Z",
                "max_open_claims": 10,
                "daily_rate": 1000,
                "per_diem_rate": 100,
                "desk_certified": False,
                "aerial_certified": False,
            },
            DC,
        ),
        201,
    )
    block = validate_success(
        api.create_housing_block(
            {
                "event_id": event["id"],
                "hotel_name": "Coast Motor Inn",
                "city": "Naples",
                "rooms_total": 4,
                "nightly_rate": 200,
                "block_start_date": "2026-09-01T00:00:00.000Z",
                "block_end_date": "2026-09-15T00:00:00.000Z",
            },
            DC,
        ),
        201,
    )
    validate_success(api.open_housing_block(block["id"], DC))
    deployment = validate_success(
        api.create_deployment(
            {
                "event_id": event["id"],
                "role_type": "FIELD",
                "window_start_utc": "2026-09-01T00:00:00.000Z",
                "window_end_utc": "2026-09-10T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
                "housing_block_id": block["id"],
                "rooms_reserved": 1,
            },
            DC,
        ),
        201,
    )
    validate_success(api.confirm_deployment(deployment["id"], DC))

    claims = []
    assignments = []
    windows = [
        ("2026-09-02T00:00:00.000Z", "2026-09-03T00:00:00.000Z"),
        ("2026-09-03T00:00:00.000Z", "2026-09-04T00:00:00.000Z"),
        ("2026-09-04T00:00:00.000Z", "2026-09-05T00:00:00.000Z"),
    ]
    for index, (start, end) in enumerate(windows, start=1):
        claim = validate_success(
            api.create_claim(
                {
                    "policy_number": f"POL-410{index}",
                    "loss_state": "FL",
                    "loss_date_utc": "2026-07-29T00:00:00.000Z",
                    "reported_loss_amount": 200000,
                    "coverage_lines": _SEVERE_CLAIM_LINES,
                    "event_id": event["id"],
                    "access_status": "ACCESSIBLE",
                },
                CE,
            ),
            201,
        )
        triaged = validate_success(api.triage_claim(claim["id"], CE))
        claims.append(triaged)
        assignments.append(
            validate_success(
                api.create_inspection_assignment(
                    {
                        "claim_id": claim["id"],
                        "mode": "FIELD",
                        "window_start_utc": start,
                        "window_end_utc": end,
                        "adjuster_id": adjuster["id"],
                        "deployment_id": deployment["id"],
                    },
                    DC,
                ),
                201,
            )
        )
    validate_success(api.set_clock("2026-09-05T00:00:00.000Z", DC))
    return event, adjuster, block, deployment, claims, assignments


def test_demobilization_settles_the_deployment_and_rests_the_adjuster(api):
    """PRD §3.5: "Link one stamps `demobilized_at_utc` with the current logical-clock
    instant, stamps `final_settled_cost` from the final-settled variant of the cost
    rule, and re-stamps `surge_premium_tier`; the block's `rooms_occupied` falls by the
    deployment's `rooms_reserved`, `rooms_available` is recomputed, and a block that
    was `EXHAUSTED` returns to `ACTIVE` once availability is 1 or more."
    PRD §3.5: "Link two, caused by link one, moves the adjuster `DEPLOYED → RESTING`
    and stamps their `last_demobilized_at_utc` with the same instant."
    PRD §3.3: "The `cumulative_deployed_hours` input is itself computed: the sum, over
    the adjuster's deployments whose status is `ON_SITE` or `DEMOBILIZED`, of the number
    of hours from that deployment's `window_start_utc` to its `window_end_utc`, to 2
    decimal places."

    Design: Difficulty/transitive_cascade/demobilize_deployment_chain_depth5_end_to_end
    """
    event, adjuster, block, deployment, _, _ = _deployed_adjuster_with_three_scheduled_inspections(
        api
    )
    assert validate_success(api.get_event(event["id"], CM))["posture"] == "OPEN"

    settled = validate_success(api.demobilize_deployment(deployment["id"], DC))

    assert settled["status"] == "DEMOBILIZED"
    # settle-end 2026-09-05 -> 4 nights; 4000.00 + 400.00 + 800.00 = 5200.00 subtotal
    # -> TIER_MID 6% -> 312.00.
    assert_money_equals(settled["final_settled_cost"], 5512.00, "final_settled_cost")
    assert settled["surge_premium_tier"] == "TIER_MID"
    assert settled["demobilized_at_utc"] == "2026-09-05T00:00:00.000Z"

    refreshed_block = validate_success(api.get_housing_block(block["id"], DC))
    assert refreshed_block["rooms_occupied"] == 0
    assert refreshed_block["rooms_available"] == 4

    refreshed_adjuster = validate_success(api.get_adjuster(adjuster["id"], DC))
    assert refreshed_adjuster["deployment_status"] == "RESTING"
    assert refreshed_adjuster["last_demobilized_at_utc"] == "2026-09-05T00:00:00.000Z"
    # 2026-09-01 -> 2026-09-10 is 9 days of window.
    assert_money_equals(
        refreshed_adjuster["cumulative_deployed_hours"], 216.00, "cumulative_deployed_hours"
    )


def test_demobilization_cancels_assignments_regresses_claims_and_tightens_posture(api):
    """PRD §3.5: "Link three, caused by the adjuster leaving `DEPLOYED`, cancels every
    inspection assignment of that adjuster still in `SCHEDULED` or `IN_PROGRESS`."
    PRD §3.5: "Link four, caused by those cancellations, regresses each affected claim
    that is `INSPECTION_PENDING` and now has no assignment left in `SCHEDULED` or
    `IN_PROGRESS` back to `TRIAGED`."
    PRD §3.5: "Link five, caused by those regressions raising the count of unassigned
    severe claims, recomputes the parent event's posture, which may flip it from `OPEN`
    to `RESTRICTED`."
    PRD §2.9: "The first term is the number of claims belonging to the event whose
    `triage_tier` is either `COMPLEX` or `CAT_SEVERE` and whose `handling_status` is
    either `TRIAGED` or `REOPENED` — in other words, severe claims that have been
    triaged but have no live inspection work."
    PRD §2.9: "A strain of 8 or more bands as `FROZEN`; a strain of 3 or more but below
    8 bands as `RESTRICTED`; a strain below 3 bands as `OPEN`."

    Design: Difficulty/transitive_cascade/demobilize_deployment_chain_depth5_end_to_end
    """
    (
        event,
        adjuster,
        _,
        deployment,
        claims,
        assignments,
    ) = _deployed_adjuster_with_three_scheduled_inspections(api)
    assert validate_success(api.get_event(event["id"], CM))["posture"] == "OPEN"

    validate_success(api.demobilize_deployment(deployment["id"], DC))

    for assignment in assignments:
        refreshed = validate_success(api.get_inspection_assignment(assignment["id"], DC))
        assert refreshed["status"] == "CANCELLED"
    for claim in claims:
        refreshed = validate_success(api.get_claim(claim["id"], CE))
        assert refreshed["triage_tier"] == "CAT_SEVERE"
        assert refreshed["handling_status"] == "TRIAGED"
        assert_money_equals(refreshed["case_reserve"], 170000.00, "case_reserve")

    refreshed_adjuster = validate_success(api.get_adjuster(adjuster["id"], DC))
    assert refreshed_adjuster["open_assignment_count"] == 0
    # availability 100.00; fatigue floor(216/24) = 9 full days * 3 = 27.00.
    assert_money_equals(
        refreshed_adjuster["surge_capacity_score"], 73.00, "surge_capacity_score"
    )

    refreshed_event = validate_success(api.get_event(event["id"], CM))
    assert refreshed_event["posture"] == "RESTRICTED"
    assert refreshed_event["surge_adjuster_count"] == 0
    assert_money_equals(
        refreshed_event["deployment_settled_cost"], 5512.00, "deployment_settled_cost"
    )
    assert_money_equals(refreshed_event["case_reserve_total"], 510000.00, "case_reserve_total")


# ---------------------------------------------------------------------------
# Instance 2 — void_advance_chain_depth4_end_to_end
# ---------------------------------------------------------------------------
def _issued_advance_with_fresh_snapshot(api):
    """CAT-2026-402 DECLARED; one STANDARD claim; one ISSUED advance of 10000.00
    issued by ce_5; one EXPOSURE_BASED snapshot minted after the advance."""
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-402",
                "peril_type": "HURRICANE",
                "jurisdiction_state": "FL",
                "event_start_utc": "2026-07-30T00:00:00.000Z",
                "exposure_count": 1000,
                "avg_insured_value": 250000,
                "expected_severity_index": 0.0400,
            },
            CM,
        ),
        201,
    )
    validate_success(api.declare_event(event["id"], CM))
    claim = validate_success(
        api.create_claim(
            {
                "policy_number": "POL-4201",
                "loss_state": "FL",
                "loss_date_utc": "2026-07-30T00:00:00.000Z",
                "reported_loss_amount": 120000,
                "coverage_lines": [
                    {
                        "coverage_code": "DWELLING",
                        "limit_amount": 400000,
                        "deductible_amount": 5000,
                        "estimated_damage_amount": 150000,
                    }
                ],
                "event_id": event["id"],
                "access_status": "ACCESSIBLE",
            },
            CE,
        ),
        201,
    )
    validate_success(api.triage_claim(claim["id"], CE))
    advance = validate_success(
        api.create_advance_payment(
            {"claim_id": claim["id"], "requested_amount": 10000, "basis": "ALE_MANDATE"},
            CE_ISSUER,
        ),
        201,
    )
    version = validate_success(api.get_event(event["id"], CM))["version"]
    snapshot = validate_success(
        api.create_loss_estimate(
            {
                "event_id": event["id"],
                "method": "EXPOSURE_BASED",
                "expected_event_version": version,
            },
            CM,
        ),
        201,
    )
    return event, claim, advance, snapshot


def test_void_appends_reversal_row_and_returns_payment_axis_to_none(api):
    """PRD §3.8: "Link two, caused by link one, appends a `REVERSAL` ledger entry whose
    `reverses_entry_id` points at the advance's `reserve_entry_id`, whose paid movement
    is the negation of the issued `amount`, and whose case-reserve movement is the
    positive `amount`, taking the next per-event `sequence_no`; the event's
    `incurred_total` is therefore again unchanged."
    PRD §3.8: "Link two-b, caused by link two, moves the claim `ADVANCE_ISSUED → NONE`
    on the payment axis when `advance_paid_total` returns to exactly 0.00 — and
    `advance_issuing_examiner_user_id` is **retained**, because a void does not erase
    the fact that this user once released money on the file."
    PRD §3.8: "Link one moves the advance `ISSUED → VOIDED` and stamps `voided_at_utc`
    at the current instant."

    Design: Difficulty/transitive_cascade/void_advance_chain_depth4_end_to_end
    """
    event, claim, advance, _ = _issued_advance_with_fresh_snapshot(api)
    payment_entry_id = advance["reserve_entry_id"]

    voided = validate_success(
        api.void_advance_payment(
            advance["id"],
            {"void_reason": "Coverage re-review: ALE advance issued in error"},
            CE_ISSUER,
        )
    )

    assert voided["status"] == "VOIDED"
    assert_money_equals(voided["amount"], 10000.00, "amount")
    assert voided["voided_at_utc"] == "2026-08-01T00:00:00.000Z"

    reversals = validate_success(
        api.list_reserve_entries(CE, params={"claim_id": claim["id"], "entry_type": "REVERSAL"})
    )
    assert len(reversals) == 1
    reversal = reversals[0]
    assert reversal["reverses_entry_id"] == payment_entry_id
    assert_money_equals(reversal["delta_paid"], -10000.00, "delta_paid")
    assert_money_equals(reversal["delta_case_reserve"], 10000.00, "delta_case_reserve")
    assert reversal["sequence_no"] == 3

    refreshed_claim = validate_success(api.get_claim(claim["id"], CE))
    assert refreshed_claim["payment_status"] == "NONE"
    assert_money_equals(refreshed_claim["advance_paid_total"], 0.00, "advance_paid_total")
    assert_money_equals(refreshed_claim["paid_amount"], 0.00, "paid_amount")
    assert_money_equals(refreshed_claim["case_reserve"], 65250.00, "case_reserve")
    assert refreshed_claim["advance_issuing_examiner_user_id"] == "ce_5"
    refreshed_event = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(refreshed_event["paid_total"], 0.00, "paid_total")
    assert_money_equals(refreshed_event["incurred_total"], 65250.00, "incurred_total")


def test_void_stales_the_latest_snapshot_which_tightens_posture(api):
    """PRD §3.8: "Link three, caused by link two raising the event's ledger high-water
    mark, flips every loss-estimate snapshot on the claim's event whose
    `input_reserve_sequence_high_water` is below the new `sequence_no` from non-stale to
    stale."
    PRD §3.8: "Link four, caused by link three staling the latest snapshot, recomputes
    the event's posture, which may flip it from `OPEN` to `RESTRICTED` — three strain
    points arrive purely from the estimate going stale."
    PRD §2.9: "The second term contributes 3 when the event's latest loss-estimate
    snapshot is stale, and 0 otherwise; the latest snapshot is the one with the greatest
    `computed_at_utc`, and if several share that instant, the one with the earliest
    `created_at` wins."

    Design: Difficulty/transitive_cascade/void_advance_chain_depth4_end_to_end
    """
    event, _, advance, snapshot = _issued_advance_with_fresh_snapshot(api)
    assert snapshot["input_reserve_sequence_high_water"] == 2
    assert snapshot["stale"] is False
    assert validate_success(api.get_event(event["id"], CM))["posture"] == "OPEN"

    validate_success(
        api.void_advance_payment(
            advance["id"],
            {"void_reason": "Coverage re-review: ALE advance issued in error"},
            CE_ISSUER,
        )
    )

    refreshed_snapshot = validate_success(api.get_loss_estimate(snapshot["id"], CM))
    assert refreshed_snapshot["stale"] is True
    assert refreshed_snapshot["input_reserve_sequence_high_water"] == 2
    assert validate_success(api.get_event(event["id"], CM))["posture"] == "RESTRICTED"
