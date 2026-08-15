"""Salvage manifests: dual-variant valuation, finalize, amend cycle."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_salvage_manifest_payload, create_salvage_item_payload,
    create_project,
)

ESTIMATOR = TEST_USERS["salvage_estimator_headers"]


def _manifest_with_two_lines():
    """Manifest CONSERVATIVE fee 50000 with STEEL 4x(20000/32000) and
    COPPER 2x(550000/700000). Totals: optimistic 1528000, conservative 1180000.
    """
    project = create_project(name="Salvage Lot", address="1 Pine St", lot_area_sqft=30000,
                             required_diversion_rate=0.5)
    m = get_success_data(
        api_client.create_salvage_manifest(
            project["id"], create_salvage_manifest_payload(), ESTIMATOR
        )
    )
    get_success_data(
        api_client.create_salvage_item(
            m["id"],
            create_salvage_item_payload(material="STEEL", description="beams", quantity=4,
                                        unit="TON", low_unit_value_cents=20000,
                                        high_unit_value_cents=32000),
            ESTIMATOR,
        )
    )
    get_success_data(
        api_client.create_salvage_item(
            m["id"],
            create_salvage_item_payload(material="COPPER", description="wire", quantity=2,
                                        unit="TON", low_unit_value_cents=550000,
                                        high_unit_value_cents=700000),
            ESTIMATOR,
        )
    )
    return m


class TestDualVariantValuation:
    def test_salvage_optimistic_vs_conservative_divergence(self):
        """PRD §3.5: "Two totals shadow each other on the manifest at all times:
        `optimistic_total_cents`, the sum of every item's `quantity` times its
        `high_unit_value_cents`, and `conservative_total_cents`, the same sum
        over `low_unit_value_cents`"
        PRD §3.5: "Finalization computes the `net_credit_cents` as the
        policy-selected total minus the `processing_fee_cents` — the optimistic
        total under an `OPTIMISTIC` policy, the conservative total under
        `CONSERVATIVE` — stamps `finalized_at` from the logical clock, and moves
        the manifest from `DRAFT` to `FINALIZED`."

        Design: Difficulty/dual_variant_calc/salvage_optimistic_vs_conservative_divergence
        """
        m = _manifest_with_two_lines()
        finalized = get_success_data(
            api_client.transition_salvage_manifest(m["id"], {"action": "FINALIZE"}, ESTIMATOR)
        )
        assert finalized["optimistic_total_cents"] == 1528000
        assert finalized["conservative_total_cents"] == 1180000
        # CONSERVATIVE policy nets 1180000 - 50000; OPTIMISTIC would net 1478000.
        assert finalized["net_credit_cents"] == 1130000
        assert finalized["status"] == "FINALIZED"

    def test_optimistic_policy_selects_high_values(self):
        """PRD §3.5: "Finalization computes the `net_credit_cents` as the
        policy-selected total minus the `processing_fee_cents` — the optimistic
        total under an `OPTIMISTIC` policy, the conservative total under
        `CONSERVATIVE`"
        PRD §3.5: "the optimistic total is strictly greater whenever any item's
        high value exceeds its low value."

        Design: Difficulty/dual_variant_calc/salvage_optimistic_vs_conservative_divergence
        """
        project = create_project(name="SalvageOpt", address="1B Pine St", lot_area_sqft=30000)
        m = get_success_data(
            api_client.create_salvage_manifest(
                project["id"],
                create_salvage_manifest_payload(valuation_policy="OPTIMISTIC"),
                ESTIMATOR,
            )
        )
        get_success_data(
            api_client.create_salvage_item(
                m["id"],
                create_salvage_item_payload(material="STEEL", description="beams", quantity=4,
                                            unit="TON", low_unit_value_cents=20000,
                                            high_unit_value_cents=32000),
                ESTIMATOR,
            )
        )
        get_success_data(
            api_client.create_salvage_item(
                m["id"],
                create_salvage_item_payload(material="COPPER", description="wire", quantity=2,
                                            unit="TON", low_unit_value_cents=550000,
                                            high_unit_value_cents=700000),
                ESTIMATOR,
            )
        )
        finalized = get_success_data(
            api_client.transition_salvage_manifest(m["id"], {"action": "FINALIZE"}, ESTIMATOR)
        )
        assert finalized["optimistic_total_cents"] == 1528000
        assert finalized["net_credit_cents"] == 1478000  # 1528000 - 50000


class TestManifestLifecycle:
    def test_manifest_finalize_empty_rejected(self):
        """PRD §3.5: "Finalizing the manifest requires at least one line item;
        finalizing an empty manifest is rejected with `ERR_MANIFEST_EMPTY`."
        PRD §3.5: "Finalization computes the `net_credit_cents` as the
        policy-selected total minus the `processing_fee_cents`"

        Design: Corner/validations/manifest_finalize_empty_rejected
        """
        project = create_project(name="EmptyMan", address="58 Pine St", lot_area_sqft=12000)
        m = get_success_data(
            api_client.create_salvage_manifest(project["id"], create_salvage_manifest_payload(),
                                               ESTIMATOR)
        )
        resp = api_client.transition_salvage_manifest(m["id"], {"action": "FINALIZE"}, ESTIMATOR)
        validate_error(resp, ApiErrorId.ERR_MANIFEST_EMPTY)
        get_success_data(
            api_client.create_salvage_item(
                m["id"],
                create_salvage_item_payload(material="BRICK", description="pavers", quantity=100,
                                            unit="EACH", low_unit_value_cents=150,
                                            high_unit_value_cents=300),
                ESTIMATOR,
            )
        )
        ok = get_success_data(
            api_client.transition_salvage_manifest(m["id"], {"action": "FINALIZE"}, ESTIMATOR)
        )
        assert ok["status"] == "FINALIZED"
        # 100 * 150 - 50000 = -35000; negative net is permitted by the formula.
        assert ok["net_credit_cents"] == -35000

    def test_salvage_credit_invariant_through_amend_cycle(self):
        """PRD §3.5: "An invariant holds at all times: the net credit always
        equals the policy-selected total minus the processing fee."
        PRD §3.5: "The amend action moves a `FINALIZED` manifest to `AMENDED` and
        increments `amendment_count` by 1. While the manifest is `AMENDED`, new
        lines are added as amendment lines: their `is_amendment_line` flag is set
        true, and their `quantity` is signed — negative quantities are permitted
        here, and only here, to compensate earlier lines."
        PRD §3.5: "Re-finalizing from `AMENDED` — again requiring at least one
        item, else `ERR_MANIFEST_EMPTY` — recomputes the net credit including the
        amendment lines, refreshes `finalized_at`, and returns the manifest to
        `FINALIZED`, preserving the net-credit invariant across the whole amend
        cycle."

        Design: Difficulty/compensating_invariant/salvage_credit_invariant_through_amend_cycle
        """
        m = _manifest_with_two_lines()
        first = get_success_data(
            api_client.transition_salvage_manifest(m["id"], {"action": "FINALIZE"}, ESTIMATOR)
        )
        assert first["net_credit_cents"] == 1130000
        amended = get_success_data(
            api_client.transition_salvage_manifest(m["id"], {"action": "AMEND"}, ESTIMATOR)
        )
        assert amended["status"] == "AMENDED"
        assert amended["amendment_count"] == 1
        line = get_success_data(
            api_client.create_salvage_item(
                m["id"],
                create_salvage_item_payload(material="STEEL",
                                            description="beams short-count adjustment",
                                            quantity=-1, unit="TON",
                                            low_unit_value_cents=20000,
                                            high_unit_value_cents=32000),
                ESTIMATOR,
            )
        )
        assert line["is_amendment_line"] is True
        assert line["extended_value_cents"] == -20000
        refinalized = get_success_data(
            api_client.transition_salvage_manifest(m["id"], {"action": "FINALIZE"}, ESTIMATOR)
        )
        assert refinalized["conservative_total_cents"] == 1160000
        assert refinalized["net_credit_cents"] == 1110000  # 1160000 - 50000

    def test_amendment_line_negative_quantity_outside_amended_rejected(self):
        """PRD §3.5: "While the manifest is `AMENDED`, new lines are added as
        amendment lines: their `is_amendment_line` flag is set true, and their
        `quantity` is signed — negative quantities are permitted here, and only
        here, to compensate earlier lines."
        PRD §3.5: "While the manifest is in `DRAFT`, quantities must be positive."

        Design: Difficulty/compensating_invariant/salvage_credit_invariant_through_amend_cycle
        """
        m = _manifest_with_two_lines()
        resp = api_client.create_salvage_item(
            m["id"],
            create_salvage_item_payload(material="STEEL", description="sneaky negative",
                                        quantity=-1, unit="TON",
                                        low_unit_value_cents=20000,
                                        high_unit_value_cents=32000),
            ESTIMATOR,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
