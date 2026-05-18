"""Reserve studies — PRD §3.9.

Covers: funded_ratio calculation, posture thresholds, division-by-zero.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_reserve_study,
    create_reserve_study_payload,
    reserve_component,
    TEST_USERS,
    validate_success,
)


class TestReserveStudyCreate:

    def test_study_with_ratio_below_30_pct_has_posture_special_assessment(
        self, api, treasurer_role_headers,
    ):
        """PRD §3.9: "SPECIAL_ASSESSMENT_REQUIRED when the ratio is
        strictly less than 0.30."

        Claim: a study with funded_ratio < 0.30 reports
        posture=SPECIAL_ASSESSMENT_REQUIRED.

        Components: $1000 (100k cents), 0/10 remaining life → accrued
        depreciation = round(100000 * 10/10) = 100000. Balance 20000.
        Ratio = 20000/100000 = 0.2000 < 0.30 → SPECIAL_ASSESSMENT_REQUIRED.
        """
        payload = create_reserve_study_payload(
            study_year=2026,
            components=[reserve_component("Roof", 100_000, 10, 0)],
            current_reserve_balance_cents=20_000,
        )
        resp = api.create_reserve_study(payload, treasurer_role_headers)
        body = validate_success(resp, expected_status=201)
        assert_reserve_study(body)
        assert body["full_funding_target_cents"] == 100_000, (
            f"target should be 100000; got "
            f"{body['full_funding_target_cents']}"
        )
        assert float(body["funded_ratio"]) == pytest.approx(0.2000, abs=1e-4)
        assert body["posture"] == "SPECIAL_ASSESSMENT_REQUIRED"

    def test_study_with_ratio_at_70_pct_has_posture_ok(
        self, api, treasurer_role_headers,
    ):
        """PRD §3.9: "OK when the ratio is at least 0.70".

        Claim: a study at funded_ratio == exactly 0.70 has posture=OK
        (the threshold is inclusive at 0.70).

        Components: $1000 (100k cents), 0/10 remaining → target 100k.
        Balance 70k → ratio 0.7000 → OK.
        """
        payload = create_reserve_study_payload(
            study_year=2026,
            components=[reserve_component("Roof", 100_000, 10, 0)],
            current_reserve_balance_cents=70_000,
        )
        resp = api.create_reserve_study(payload, treasurer_role_headers)
        body = validate_success(resp, expected_status=201)
        assert body["full_funding_target_cents"] == 100_000
        assert float(body["funded_ratio"]) == pytest.approx(0.7000, abs=1e-4)
        assert body["posture"] == "OK", (
            f"funded_ratio 0.7000 must yield posture=OK per PRD §3.9; "
            f"got {body['posture']}"
        )

    def test_study_with_ratio_between_30_and_70_has_posture_restricted(
        self, api, treasurer_role_headers,
    ):
        """PRD §3.9: "RESTRICTED when the ratio is at least 0.30 but
        strictly less than 0.70".

        Claim: a study at funded_ratio 0.5000 has posture=RESTRICTED.
        """
        payload = create_reserve_study_payload(
            study_year=2026,
            components=[reserve_component("Roof", 100_000, 10, 0)],
            current_reserve_balance_cents=50_000,
        )
        resp = api.create_reserve_study(payload, treasurer_role_headers)
        body = validate_success(resp, expected_status=201)
        assert float(body["funded_ratio"]) == pytest.approx(0.5000, abs=1e-4)
        assert body["posture"] == "RESTRICTED"


class TestReserveStudyDivisionByZero:

    def test_zero_target_yields_null_ratio_and_posture_ok(
        self, api, treasurer_role_headers,
    ):
        """PRD §3.9: "When full_funding_target_cents is zero,
        funded_ratio is null (division by zero is not attempted) and
        posture is OK."

        Claim: components that yield target=0 (e.g., useful_life=10,
        remaining_life=10 → factor 0) produce funded_ratio=null,
        posture=OK.
        """
        payload = create_reserve_study_payload(
            study_year=2026,
            components=[reserve_component("Roof", 100_000, 10, 10)],
            current_reserve_balance_cents=50_000,
        )
        resp = api.create_reserve_study(payload, treasurer_role_headers)
        body = validate_success(resp, expected_status=201)
        assert body["full_funding_target_cents"] == 0
        assert body["funded_ratio"] is None, (
            f"with target_cents=0, funded_ratio MUST be null per PRD "
            f"§3.9; got {body['funded_ratio']!r}"
        )
        assert body["posture"] == "OK"
