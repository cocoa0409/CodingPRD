"""Damage and missing-part hotline: filing gates, adjudication, and the
approval cascade into contingency and wave capacity."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_claim,
    create_delivery,
    make_hotline_agent_headers,
    make_program_manager_headers,
    setup_delivered_scenario,
    setup_released_scenario,
    validate_error,
    validate_success,
)

PM = make_program_manager_headers("pm-suite-5")
HA = make_hotline_agent_headers("ha-suite-5")

ENDCAP_BOM = [{"part_number": "PN-600", "quantity": 1,
               "list_unit_cost_cents": 3000}]
TEN_AT_1000 = [{"part_number": "PN-600", "quantity": 10,
                "unit_cost_cents": 1000}]


def _delivered_ctx(name, **overrides):
    kwargs = dict(
        budget_total_cents=1_000_000,
        fixture_code="ENDCAP",
        bom_lines=ENDCAP_BOM,
        store_code="STORE-E1",
        config_lines=TEN_AT_1000,
        wave_capacity=100,
        estimated_install_hours=4,
    )
    kwargs.update(overrides)
    return setup_delivered_scenario(program_name=name, **kwargs)


class TestClaimFiling:

    def test_claim_type_invalid_enum_rejected(self):
        """PRD §3.6: "A `HotlineAgent` files a **damage claim** against a
        delivery by providing the `delivery_id` (unknown delivery:
        `ERR_DELIVERY_NOT_FOUND`), the affected `part_number`, a `claim_type`
        of `DAMAGED` or `MISSING`, the `replacement_component_count` to
        remanufacture (at least 1), and the quoted `replacement_cost_cents`
        (zero or greater)."
        PRD §2.7: "Malformed or mistyped input in this category reports
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/claim_type_invalid_enum_rejected
        """
        ctx = _delivered_ctx("P-ENUM")
        resp = api_client.create_damage_claim(
            {"delivery_id": ctx["delivery"]["id"], "part_number": "PN-600",
             "claim_type": "SCRATCHED", "replacement_component_count": 1,
             "replacement_cost_cents": 100},
            HA,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_claim_on_scheduled_delivery_rejected(self):
        """PRD §3.6: "Claims may be filed only against deliveries in
        `DELIVERED` or `COMPLETE` status; filing against a delivery in any
        other state is rejected with `ERR_DELIVERY_INVALID_STATE`."

        Design: Corner/validations/claim_on_scheduled_delivery_rejected
        """
        ctx = setup_released_scenario(
            program_name="P-VAL13",
            budget_total_cents=1_000_000,
            fixture_code="ENDCAP",
            bom_lines=ENDCAP_BOM,
            store_code="STORE-V13",
            config_lines=TEN_AT_1000,
            wave_capacity=100,
        )
        delivery = create_delivery(ctx["kit"]["id"], "CREW-V13",
                                   "2026-09-12", 4)
        assert delivery["status"] == "SCHEDULED"
        resp = api_client.create_damage_claim(
            {"delivery_id": delivery["id"], "part_number": "PN-600",
             "claim_type": "DAMAGED", "replacement_component_count": 1,
             "replacement_cost_cents": 500},
            HA,
        )
        validate_error(resp, ApiErrorId.ERR_DELIVERY_INVALID_STATE)


class TestClaimAdjudication:

    def test_claim_approve_rejected_claim_returns_409(self):
        """PRD §3.6: "Rejection is the quiet sibling: a manager may reject any
        `OPEN` claim (`ERR_CLAIM_NOT_OPEN` otherwise), moving it `OPEN →
        REJECTED` with the rejection recorded and with no budget or capacity
        side effects of any kind."
        PRD §3.6: "the claim must still be `OPEN` (`ERR_CLAIM_NOT_OPEN`
        otherwise)".

        Design: Corner/state_machines/claim_approve_rejected_claim_returns_409
        """
        ctx = _delivered_ctx("P-SM6", store_code="STORE-S6")
        claim = create_claim(ctx["delivery"]["id"], "PN-600", "DAMAGED", 1, 100)
        rejected = validate_success(
            api_client.reject_damage_claim(claim["id"], PM))
        assert rejected["status"] == "REJECTED"
        resp = api_client.approve_damage_claim(claim["id"], PM)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_OPEN)
        program_after = validate_success(
            api_client.get_rollout_program(ctx["program"]["id"], PM))
        assert program_after["contingency_spent_cents"] == 0

    def test_claim_safety_beats_fiscal(self):
        """PRD §2.7: "**Segregation of duties and recall holds sixth.** A
        prototype approver who is also its most recent submitter fails with
        `ERR_PROTOTYPE_SELF_APPROVAL`; a signoff approver who submitted it
        fails with `ERR_SIGNOFF_SELF_APPROVAL`; a claim whose part sits on the
        program's recall hold list fails with `ERR_PART_RECALL_HOLD`."
        PRD §2.7: "**Money last.** Only after every category above has passed
        does the server evaluate fiscal constraints: the freeze and release
        budget checks (`ERR_BUDGET_EXCEEDED`), the wave capacity check
        (`ERR_WAVE_CAPACITY_EXCEEDED`), and the contingency check on claim
        approval (`ERR_CONTINGENCY_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/claim_safety_beats_fiscal
        """
        # Recalled part AND cost (5000) over the remaining contingency (100):
        # the recall hold (priority 6) must surface, not the fiscal failure.
        ctx = _delivered_ctx(
            "P-PRIO2", store_code="STORE-P2",
            contingency_budget_cents=100,
            recalled_part_numbers=["PN-900"],
        )
        claim = create_claim(ctx["delivery"]["id"], "PN-900", "MISSING", 2,
                             5_000)
        resp = api_client.approve_damage_claim(claim["id"], PM)
        validate_error(resp, ApiErrorId.ERR_PART_RECALL_HOLD)
        claim_after = validate_success(
            api_client.get_damage_claim(claim["id"], PM))
        assert claim_after["status"] == "OPEN"
        program_after = validate_success(
            api_client.get_rollout_program(ctx["program"]["id"], PM))
        assert program_after["contingency_spent_cents"] == 0

    def test_claim_over_contingency_returns_402_when_recall_passes(self):
        """PRD §3.6: "the `replacement_cost_cents` must fit within the
        program's remaining contingency — that is, within
        `contingency_budget_cents` minus `contingency_spent_cents`, with a
        claim landing exactly on the remaining reserve allowed — else
        `ERR_CONTINGENCY_EXCEEDED` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/claim_safety_beats_fiscal
        """
        # Same recall-armed program, but the claimed part is NOT on the hold
        # list: only the fiscal gate can fail (5000 > 100 remaining).
        ctx = _delivered_ctx(
            "P-PRIO2B", store_code="STORE-P2B",
            contingency_budget_cents=100,
            recalled_part_numbers=["PN-900"],
        )
        claim = create_claim(ctx["delivery"]["id"], "PN-600", "DAMAGED", 2,
                             5_000)
        resp = api_client.approve_damage_claim(claim["id"], PM)
        validate_error(resp, ApiErrorId.ERR_CONTINGENCY_EXCEEDED)
        claim_after = validate_success(
            api_client.get_damage_claim(claim["id"], PM))
        assert claim_after["status"] == "OPEN"
        program_after = validate_success(
            api_client.get_rollout_program(ctx["program"]["id"], PM))
        assert program_after["contingency_spent_cents"] == 0


class TestClaimApprovalCascade:

    def _claim_scenario(self):
        """Kit of 100 components released to a capacity-115 wave (committed
        100, utilization 87.0, NORMAL); DELIVERED delivery; OPEN claim for 20
        replacement components at 5000 cents."""
        ctx = setup_delivered_scenario(
            program_name="P-CLAIM",
            budget_total_cents=2_000_000,
            contingency_budget_cents=100_000,
            fixture_code="GONDOLA-8FT",
            bom_lines=[{"part_number": "PN-300", "quantity": 5,
                        "list_unit_cost_cents": 9000}],
            store_code="STORE-D1",
            config_lines=[{"part_number": "PN-300", "quantity": 100,
                           "unit_cost_cents": 3000}],
            wave_capacity=115,
            estimated_install_hours=6,
            crew_code="CREW-D",
        )
        claim = create_claim(ctx["delivery"]["id"], "PN-300", "DAMAGED", 20,
                             5_000)
        ctx["claim"] = claim
        return ctx

    def test_claim_approval_debits_wave_chain(self):
        """PRD §3.6: "First, the claim's `replacement_cost_cents` is added to
        the program's `contingency_spent_cents`. Second, the wave carrying the
        claim's kit — found by following the claim's `delivery_id` to its
        delivery, the delivery's kit, and the kit's `wave_id` — has the claim's
        `replacement_component_count` added to its `committed_units`; emergency
        replacement deliberately bypasses the release-time capacity check, so
        this addition may push `committed_units` above `capacity_units`. Third,
        that wave's `utilization_pct` and `utilization_posture` are recomputed,
        and the posture may flip `NORMAL → AT_RISK`."

        Design: Difficulty/transitive_cascade/claim_approval_debits_wave_chain
        """
        ctx = self._claim_scenario()
        approved = validate_success(
            api_client.approve_damage_claim(ctx["claim"]["id"], PM))
        assert approved["status"] == "APPROVED"

        program_after = validate_success(
            api_client.get_rollout_program(ctx["program"]["id"], PM))
        assert program_after["contingency_spent_cents"] == 5_000

        wave_after = validate_success(api_client.get_production_wave(
            ctx["wave"]["id"], PM))
        assert wave_after["committed_units"] == 120
        assert wave_after["utilization_pct"] == pytest.approx(104.3, abs=0.001)
        assert wave_after["utilization_posture"] == "AT_RISK"

    def test_claim_approval_may_push_committed_above_capacity(self):
        """PRD §3.6: "Second, the wave carrying the claim's kit — found by
        following the claim's `delivery_id` to its delivery, the delivery's
        kit, and the kit's `wave_id` — has the claim's
        `replacement_component_count` added to its `committed_units`; emergency
        replacement deliberately bypasses the release-time capacity check, so
        this addition may push `committed_units` above `capacity_units`."
        PRD §3.4: "`utilization_pct` divides `committed_units` by
        `capacity_units`, expresses the result as a percentage, and rounds half
        up to one decimal place."

        Design: Difficulty/transitive_cascade/claim_approval_debits_wave_chain
        """
        ctx = self._claim_scenario()
        wave_before = validate_success(api_client.get_production_wave(
            ctx["wave"]["id"], PM))
        assert wave_before["committed_units"] == 100
        assert wave_before["utilization_pct"] == pytest.approx(87.0, abs=0.001)
        assert wave_before["utilization_posture"] == "NORMAL"

        validate_success(api_client.approve_damage_claim(
            ctx["claim"]["id"], PM))
        wave_after = validate_success(api_client.get_production_wave(
            ctx["wave"]["id"], PM))
        assert wave_after["capacity_units"] == 115
        assert wave_after["committed_units"] == 120, (
            "approval must bypass the release-time capacity check: "
            "120 > 115"
        )
        assert wave_after["utilization_posture"] == "AT_RISK"
