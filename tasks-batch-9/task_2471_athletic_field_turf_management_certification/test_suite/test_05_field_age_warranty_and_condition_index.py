"""Derived age, the warranty fan-out, the g-max verdict and the condition index."""

from test_helpers import (
    assert_field,
    assert_one_decimal,
    assert_safety_assessment,
    assert_two_decimals,
    factories,
    fixtures,
    validate_paginated,
)


class TestFieldAgeAndWarranty:
    def test_age_and_warranty_boundary_is_inclusive_of_expiry(self, client, roster):
        """Age is a real-day ratio and expiry owns its own boundary instant.

        "`age_years` is the number of whole and fractional days between
        `installed_on_date` and the current logical instant, divided by 365.25,
        rounded half up to two decimal places."

        "`warranty_status` follows a three-way rule: it is `NONE` when
        `warranty_expires_on` is null, `ACTIVE` when the current instant is
        strictly earlier than `warranty_expires_on`, and `EXPIRED` otherwise —
        the boundary belongs to expiry, so at exactly `warranty_expires_on` the
        warranty already reads `EXPIRED`."

        "Before the clock has ever been set, it reads exactly
        `2026-08-01T00:00:00Z`, and it never falls back to real wall-clock time."

        Design: Corner/calculations/field_age_and_warranty_boundary_is_inclusive_of_expiry
        """
        # The clock is left at its default, so the boundary field's warranty
        # expires at exactly the current logical instant.
        boundary = fixtures.register_field(
            client,
            roster,
            factories.make_field_payload(
                name="Grass Boundary 4",
                surface_type="NATURAL_GRASS",
                installed_on_date="2018-04-15",
                expected_life_years=12,
                area_sq_ft=80000,
                sanctioned_level="STATE",
                warranty_expires_on="2026-08-01",
            ),
        )
        young = fixtures.register_grass_practice_3(client, roster)
        no_warranty = fixtures.register_field(
            client,
            roster,
            factories.make_field_payload(
                name="Grass Rec 5",
                surface_type="NATURAL_GRASS",
                installed_on_date="2020-01-01",
                expected_life_years=15,
                area_sq_ft=40000,
                sanctioned_level="NONE",
            ),
        )

        boundary = fixtures.read_field(client, roster, boundary["id"])
        assert_field(boundary)
        # 3030 elapsed days over 365.25 is 8.2957, which rounds to 8.30.
        assert_two_decimals(boundary["age_years"], 8.30, "Grass Boundary 4 age_years")
        assert boundary["warranty_status"] == "EXPIRED"

        young = fixtures.read_field(client, roster, young["id"])
        # 365 elapsed days over 365.25 is 0.99932, which rounds to 1.00.
        assert_two_decimals(young["age_years"], 1.00, "Grass Practice 3 age_years")
        assert young["warranty_status"] == "ACTIVE"

        no_warranty = fixtures.read_field(client, roster, no_warranty["id"])
        # 2404 elapsed days over 365.25 is 6.5822, which rounds to 6.58.
        assert_two_decimals(no_warranty["age_years"], 6.58, "Grass Rec 5 age_years")
        assert no_warranty["warranty_status"] == "NONE"
        assert no_warranty.get("warranty_expires_on") is None

        for field in (boundary, young, no_warranty):
            assert field["play_status"] == "OPEN"
            assert field["certification_status"] == "NOT_CERTIFIED"
            assert_two_decimals(
                field["cumulative_wear_units"], 0.00, "Field.cumulative_wear_units"
            )
            assert_two_decimals(
                field["rest_debt_hours"], 0.00, "Field.rest_debt_hours"
            )


class TestImpactAttenuationVerdict:
    def test_gmax_mean_exactly_at_advisory_limit_is_pass(self, client, roster):
        """The lower band closes inclusively, so 165.0 is still a pass.

        "The verdict is then read off two thresholds, both of which are inclusive
        on the lower side of the band they close: a mean of 165.0 g or less is a
        `PASS`, a mean above 165.0 g but no more than 200.0 g is an `ADVISORY`,
        and a mean strictly above 200.0 g is a `FAIL`. A mean of exactly 165.0 is
        therefore a `PASS` and a mean of exactly 200.0 is an `ADVISORY`."

        "Hop two opens the order: a `result` of `FAIL` opens an order with
        `severity` `MANDATORY`, a `result` of `ADVISORY` opens one with `severity`
        `ADVISORY`, and a `result` of `PASS` opens nothing."

        "otherwise it is the distance from the mandatory g-max limit of 200.0 down
        to the measured mean, divided by the distance from that mandatory limit
        down to an ideal value of 90.0, expressed as a percentage, clamped to lie
        between 0.00 and 100.00, and rounded half up to two decimals."

        Design: Corner/calculations/gmax_mean_exactly_at_advisory_limit_is_pass
        """
        field = fixtures.register_synthetic_stadium_1(client, roster)
        assessment = fixtures.record_impact_test(
            client, roster, field["id"], [164.9, 165.0, 165.1]
        )
        assert_safety_assessment(assessment)
        # (164.9 + 165.0 + 165.1) / 3 is exactly 165.0.
        assert_one_decimal(assessment["gmax_mean_value"], 165.0, "gmax_mean_value")
        assert assessment["result"] == "PASS"
        assert assessment["status"] == "RECORDED"
        assert assessment.get("declared_result") is None

        _orders, order_meta = validate_paginated(
            client.list_remediation_orders(
                roster.inspector_headers,
                params={"limit": 100, "field_id": field["id"]},
            )
        )
        assert order_meta["total_count"] == 0, "a PASS opens no order"

        after = fixtures.read_field(client, roster, field["id"])
        assert_one_decimal(
            after["latest_gmax_mean_value"], 165.0, "Field.latest_gmax_mean_value"
        )
        assert after["open_mandatory_remediation_count"] == 0
        assert after["open_advisory_remediation_count"] == 0
        assert after["play_status"] == "OPEN"
        # The surface is past its nominal life, so age floors at 0.00, and the
        # safety component is (200.0 - 165.0) / (200.0 - 90.0) as a percentage:
        # 100.00 x 0.50 + 0.00 x 0.20 + 31.82 x 0.30 = 59.546.
        assert_two_decimals(
            after["condition_index_agronomic"], 59.55, "Field.condition_index_agronomic"
        )


class TestConditionIndexNoDataFallback:
    def test_condition_index_with_no_gmax_data_uses_the_no_data_safety_component(
        self, client, roster
    ):
        """An untested surface takes the sentinel rather than dropping the term.

        "The safety component depends on the latest impact test: when
        `latest_gmax_mean_value` is null it takes the no-data value of 50.00
        exactly"

        "The `AGRONOMIC` variant then weights the wear component at 0.50, the age
        component at 0.20 and the safety component at 0.30, sums them, and rounds
        half up to two decimal places, applying no cap — an agronomically
        excellent surface can still score well on this variant with a mediocre
        g-max reading."

        "The wear component is 100.00 minus the field's `cumulative_wear_units`
        divided by 4.00 — four wear units cost one index point — floored at 0.00
        and rounded half up to two decimals."

        Design: Corner/calculations/condition_index_with_no_gmax_data_uses_the_no_data_safety_component
        """
        field = fixtures.register_grass_main_1(client, roster)
        current = fixtures.read_field(client, roster, field["id"])

        assert current.get("latest_gmax_mean_value") is None
        # 100.00 x 0.50 + 30.83 x 0.20 + 50.00 x 0.30 = 71.166, which rounds to
        # 71.17 — treating the missing reading as 0.00 would give 56.17 instead.
        assert_two_decimals(
            current["condition_index_agronomic"],
            71.17,
            "Field.condition_index_agronomic",
        )
        assert_two_decimals(current["age_years"], 8.30, "Field.age_years")
        assert_two_decimals(
            current["cumulative_wear_units"], 0.00, "Field.cumulative_wear_units"
        )

        _assessments, meta = validate_paginated(
            client.list_safety_assessments(
                roster.inspector_headers,
                params={"limit": 100, "field_id": field["id"]},
            )
        )
        assert meta["total_count"] == 0
