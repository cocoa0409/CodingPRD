"""Consistency model: the whole adjudication cascade lands inside one request.

The system is immediately consistent — PRD §2.12 pins every hop of a derived
chain to the same request that triggered it. So the adjudication response body
must itself already carry the stamped threshold, ratio and decision instant,
and the very first read of the owning centre — with no intervening ops
checkpoint — must already show the reserved exposure.

Every precondition is built inside the test through the PRD §4 endpoints,
because the server is restarted against an empty database before each test.
"""

from test_helpers import (
    SCENARIO_CLOCK_UTC,
    SERVICE_AGENT_HEADERS,
    World,
    assert_center_posture,
    assert_claim_decision,
    factories,
    validate_paginated,
    validate_success,
)


def _build_assessed_tent_claim(scenario):
    """A claim in `UNDER_ASSESSMENT` on a 37-month-old own-MSRP TENT_SHELTER unit.

    The centre carries a 5000000-cent ceiling and zero exposure, the Ascent 2P
    is neither discontinued nor pointed at a successor, its single panel lot is
    `AVAILABLE`, and the live finding is `MANUFACTURING_DEFECT` over a
    120-minute `FABRIC` lane with 4200 cents of estimated parts.
    """
    scenario.set_clock(SCENARIO_CLOCK_UTC)
    center = scenario.center()
    model = scenario.model()
    panel_lot = scenario.part_lot(model["id"])
    customer = scenario.customer()
    item = scenario.gear_item(model["id"], customer["id"])
    technician = scenario.technician(
        center["id"],
        employee_code="T-101",
        full_name="Ines Park",
        certifications=[factories.certification("FABRIC", 3)],
    )
    claim = scenario.claim(center["id"], item["id"])
    submitted = scenario.submit(claim["id"])
    assessment = scenario.assess(
        claim["id"], technician["id"], expected_claim_version=submitted["version"]
    )
    return World(
        scenario=scenario,
        center_id=center["id"],
        model_id=model["id"],
        panel_lot_id=panel_lot["id"],
        customer_id=customer["id"],
        item_id=item["id"],
        technician_id=technician["id"],
        claim_id=claim["id"],
        assessment=assessment,
    )


class TestDecisionCascadeIsVisibleInTheSameResponse:
    """The adjudication's derived surface is readable without a second call."""

    def test_decision_response_body_already_carries_the_derived_outcome(
        self, scenario, api
    ):
        """The adjudication response itself stamps WARRANTY_APPROVED, threshold 55, ratio 31.14 and the decision instant — no re-read needed.

        "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        "`repair_ratio_pct` is one hundred multiplied by the claim's `latest_repair_cost_cents`, divided by the unit's `replacement_value_successor_cents`, rounded half up to two decimal places."
        "Whatever the outcome, the claim records `decision`, `decision_threshold_pct`, `repair_ratio_pct`, `decision_by_role` — set to `ServiceAgent` or `ProgramAdmin` according to the acting role — and `decided_at` from the logical clock."

        Design: Corner/consistency_model/decision_cascade_is_visible_in_the_same_response
        """
        world = _build_assessed_tent_claim(scenario)

        claim = validate_success(
            api.decide_claim(world.claim_id, SERVICE_AGENT_HEADERS, {}), 200
        )

        assert_claim_decision(
            claim,
            decision="WARRANTY_REPAIR",
            status="WARRANTY_APPROVED",
            threshold_pct=55,
            ratio_pct=31.14,
        )
        assert claim["decision_by_role"] == "ServiceAgent", claim
        assert claim["latest_repair_cost_cents"] == 22390, claim
        assert claim["decided_at"].startswith("2026-06-15T09:00:00"), claim

    def test_center_liability_and_model_counters_are_rolled_up_on_the_first_read(
        self, scenario, api
    ):
        """The first read after the decision already shows 22390 of exposure, one OPEN REPAIR entry and defect_claim_count 1, with no checkpoint ever run.

        "Every hop in such a chain is a real mutation of the affected row, refreshing its `updated_at` and incrementing its `version`, and every hop is applied within the same request."
        "Second, that new open entry increases the centre's `open_liability_cents` by the reserved amount and recomputes `liability_utilization_pct`."
        "A freshly registered centre starts with `open_liability_cents` at 0, `liability_utilization_pct` at 0, `liability_posture` at `OPEN`, `active_queue_depth` at 0 and `current_surge_multiplier` at 1.0; its `breached_commitment_count` is 0 and its `last_queue_review_at` is null until the first checkpoint runs."

        Design: Corner/consistency_model/decision_cascade_is_visible_in_the_same_response
        """
        world = _build_assessed_tent_claim(scenario)

        scenario.decide(world.claim_id)

        center = scenario.read_center(world.center_id)
        assert_center_posture(center, 22390, 0.45, "OPEN")
        assert center["last_queue_review_at"] is None, center

        rows, meta = validate_paginated(
            api.list_claim_liability_entries(
                world.claim_id, SERVICE_AGENT_HEADERS, status="OPEN"
            )
        )
        assert meta["total_count"] == 1, meta
        assert rows[0]["basis"] == "REPAIR", rows[0]
        assert rows[0]["reserved_amount_cents"] == 22390, rows[0]
        assert rows[0]["status"] == "OPEN", rows[0]

        item = scenario.read_item(world.item_id)
        assert item["disposition_status"] == "AT_CENTER", item
        assert item["age_months"] == 37, item
        assert item["warranty_state"] == "IN_WARRANTY", item
        assert item["replacement_value_depreciated_cents"] == 52430, item
        assert item["replacement_value_successor_cents"] == 71910, item

        model = scenario.read_model(world.model_id)
        assert model["defect_claim_count"] == 1, model
        assert model["repairability_flag"] == "NONE", model
