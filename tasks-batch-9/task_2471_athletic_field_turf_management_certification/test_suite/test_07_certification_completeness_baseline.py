"""The documentation completeness score when every component is satisfied."""

from test_helpers import (
    assert_certification_packet,
    assert_instant_equals,
    assert_two_decimals,
    fixtures,
    validate_paginated,
)
from test_helpers.constants import DEFAULT_CLOCK_UTC


class TestCertificationCompletenessFullScore:
    def test_completeness_scores_full_when_every_component_is_satisfied(
        self, client, roster
    ):
        """Two of the six components are satisfied only by vacuous compliance.

        "the denominator is the set of maintenance tasks on the field whose
        `planned_for_certification_window` is true, whose `status` is anything
        other than `CANCELLED`, and whose `scheduled_start_utc` falls inside the
        window, and the ratio is the proportion of that set whose `status` is
        `COMPLETED` — except that when the set is empty the ratio is 1.00, not
        0.00, because there is nothing to have failed to do."

        "The remediation-closure component is worth 10 points: the denominator is
        the set of remediation orders on the field whose `opened_at_utc` falls
        inside the window, and the ratio is the proportion of that set whose
        `status` is `CLOSED_VERIFIED` or `CANCELLED`, with an empty set again
        scoring 1.00 for vacuous compliance."

        "The surface-specification component is worth 10 points and its ratio
        depends on the surface family: on a `SYNTHETIC_TURF` field it is the
        field's `infill_depth_mm` divided by a required depth of 51.0
        millimetres, capped at 1.00"

        "the final value is the **lesser** of that weighted sum and the safety
        component alone. A field presented for sanctioned competition can never be
        scored above its measured impact attenuation, however pristine its wear and
        age figures are."

        Design: Corner/calculations/certification_completeness_scores_full_when_every_component_is_satisfied
        """
        built = fixtures.build_certifiable_synthetic_field(
            client,
            roster,
            infill_depth_mm=51.0,
            impact_readings=[164.9, 165.0, 165.1],
        )
        field = built["field"]
        current = fixtures.read_field(client, roster, field["id"])
        packet = fixtures.open_packet(
            client,
            roster,
            field["id"],
            built["impact"]["id"],
            current["version"],
            competition_season_label="2026-27 Regional",
        )

        submitted = fixtures.submit_packet(client, roster, packet["id"])
        assert_certification_packet(submitted)
        assert submitted["status"] == "SUBMITTED"
        assert_instant_equals(
            submitted["submitted_at_utc"],
            DEFAULT_CLOCK_UTC,
            "CertificationPacket.submitted_at_utc",
        )
        # 30.00 safety + 20.00 agronomic vacuous + 15.00 striping + 15.00 goal
        # anchoring + 10.00 spec at 51.0 / 51.0 + 10.00 remediation vacuous.
        assert_two_decimals(
            submitted["documentation_completeness_score"],
            100.00,
            "documentation_completeness_score",
        )
        # 100.00 x 0.20 + 0.00 x 0.20 + 31.82 x 0.60 is 39.09, but the variant is
        # capped at the safety component alone.
        assert_two_decimals(
            submitted["condition_index_certification"],
            31.82,
            "condition_index_certification",
        )

        _tasks, task_meta = validate_paginated(
            client.list_maintenance_tasks(
                roster.cert_officer_headers,
                params={
                    "limit": 100,
                    "field_id": field["id"],
                    "planned_for_certification_window": "true",
                },
            )
        )
        assert task_meta["total_count"] == 0, "the agronomic denominator is empty"

        _orders, order_meta = validate_paginated(
            client.list_remediation_orders(
                roster.cert_officer_headers,
                params={"limit": 100, "field_id": field["id"]},
            )
        )
        assert order_meta["total_count"] == 0, "the remediation denominator is empty"

        stored = fixtures.read_packet(client, roster, packet["id"])
        assert stored["return_count"] == 0
        assert stored.get("certified_until_utc") is None
