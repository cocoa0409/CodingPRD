"""Asset reasonable-measures scoring, protection posture, and the posture report.

Covers the operational/documentary score variants (PRD §2.7), posture
thresholds, and input-set filtering of PLANNED/LAPSED measures.
"""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    ApiErrorId,
    create_registered_asset,
    add_verified_measure,
    add_implemented_measure,
    create_measure_payload,
    create_asset_payload,
    setup_adequate_asset,
    TEST_USERS,
)

IP = TEST_USERS["ip_counsel_headers"]
SEC = TEST_USERS["security_officer_headers"]
SENIOR = TEST_USERS["senior_counsel_headers"]


def _setup_dual_variant_asset(api):
    """REGISTERED asset: TECHNICAL(25)+CONTRACTUAL(20)+POLICY(10) VERIFIED,
    PHYSICAL(15) IMPLEMENTED only."""
    asset = create_registered_asset(
        title="Firmware signing process",
        description="HSM key ceremony",
        classification="RESTRICTED",
        owner_department="ENG",
        exposure_estimate_cents=500000,
    )
    add_verified_measure(asset["id"], "TECHNICAL", title="HSM access control",
                         evidence_uri="s3://ev/hsm.pdf")
    add_verified_measure(asset["id"], "CONTRACTUAL", title="Vendor NDAs",
                         evidence_uri="s3://ev/nda.pdf")
    add_verified_measure(asset["id"], "POLICY", title="TS handling policy",
                         evidence_uri="s3://ev/pol.pdf")
    add_implemented_measure(asset["id"], "PHYSICAL", title="Badge-controlled lab",
                            evidence_uri="s3://ev/lab.pdf")
    return asset


class TestAssetScoreDualVariant:
    def test_operational_counts_implemented_at_sixty_percent(self, api):
        """PRD §2.7: "The operational variant, `score_operational`, sums
        `points_effective` across all of the asset's measures — verified measures
        count at full weight, implemented-but-unverified measures count at sixty
        percent, and everything else counts zero."

        Design: Difficulty/dual_variant_calc/asset_score_operational_vs_documentary
        """
        asset = _setup_dual_variant_asset(api)
        data = validate_success(api.get_asset(asset["id"], IP))
        assert data["score_operational"] == pytest.approx(64.0, abs=0.01), \
            f"expected operational 64 (25+20+10+15*0.6), got {data['score_operational']}"

    def test_documentary_ignores_implemented_and_posture_uses_operational(self, api):
        """PRD §2.7: "The documentary variant, `score_documentary`, sums the
        weight of `VERIFIED` measures only: implemented-but-unverified measures
        are not court-presentable, so identical rows always yield a documentary
        score equal to or lower than the operational one."
        PRD §2.7: "The posture derivation uses the operational variant alone:
        `protection_posture` is `STRONG` when the operational score reaches 70
        or more, `ADEQUATE` when it is at least 40 but below 70, and `DEFICIENT`
        below 40."

        Design: Difficulty/dual_variant_calc/asset_score_operational_vs_documentary
        """
        asset = _setup_dual_variant_asset(api)
        data = validate_success(api.get_asset(asset["id"], IP))
        assert data["score_documentary"] == pytest.approx(55.0, abs=0.01), \
            f"expected documentary 55 (25+20+10+0), got {data['score_documentary']}"
        assert data["score_operational"] != data["score_documentary"]
        assert data["protection_posture"] == "ADEQUATE", \
            "operational 64 in [40,70) must yield ADEQUATE"


class TestPostureThresholdBoundary:
    def _setup_boundary_asset(self, api):
        """TECHNICAL(25)+CONTRACTUAL(20)+PHYSICAL(15)+POLICY(10) all VERIFIED = 70."""
        asset = create_registered_asset(
            title="Boundary asset",
            description="threshold probe",
            classification="RESTRICTED",
            owner_department="ENG",
            exposure_estimate_cents=100000,
        )
        add_verified_measure(asset["id"], "TECHNICAL", title="m1", evidence_uri="s3://ev/1.pdf")
        add_verified_measure(asset["id"], "CONTRACTUAL", title="m2", evidence_uri="s3://ev/2.pdf")
        add_verified_measure(asset["id"], "PHYSICAL", title="m3", evidence_uri="s3://ev/3.pdf")
        pol = add_verified_measure(asset["id"], "POLICY", title="m4", evidence_uri="s3://ev/4.pdf")
        return asset, pol

    def test_exactly_70_is_strong(self, api):
        """PRD §2.7: "`protection_posture` is `STRONG` when the operational score
        reaches 70 or more, `ADEQUATE` when it is at least 40 but below 70, and
        `DEFICIENT` below 40."

        Design: Difficulty/boundary_precision_check/posture_threshold_exactly_70_strong
        """
        asset, _pol = self._setup_boundary_asset(api)
        data = validate_success(api.get_asset(asset["id"], IP))
        assert data["score_operational"] == pytest.approx(70.0, abs=0.01)
        assert data["protection_posture"] == "STRONG", \
            "exactly 70 must be STRONG (>= 70 boundary inclusive)"

    def test_lapse_drops_70_to_60_adequate(self, api):
        """PRD §2.7: "`protection_posture` is `STRONG` when the operational score
        reaches 70 or more, `ADEQUATE` when it is at least 40 but below 70, and
        `DEFICIENT` below 40."
        PRD §3.1: "`VERIFIED → LAPSED` and `IMPLEMENTED → LAPSED` both zero its
        effective points and recompute the parent's scores and posture."

        Design: Difficulty/boundary_precision_check/posture_threshold_exactly_70_strong
        """
        asset, pol = self._setup_boundary_asset(api)
        validate_success(api.transition_measure(pol["id"], {"to_status": "LAPSED"}, IP))
        data = validate_success(api.get_asset(asset["id"], IP))
        assert data["score_operational"] == pytest.approx(60.0, abs=0.01)
        assert data["protection_posture"] == "ADEQUATE", \
            "60 is below the STRONG threshold, so ADEQUATE"


class TestScoreInputSetFiltering:
    def test_planned_and_lapsed_contribute_zero(self, api):
        """PRD §2.7: "Each measure also has a `points_effective` value: its weight
        multiplied by 1.0 while `VERIFIED`, by 0.6 while `IMPLEMENTED`, and by 0
        in any other status (`PLANNED`, `LAPSED`, or `ABANDONED`)."

        Design: Corner/calculations/score_ignores_planned_and_lapsed_measures
        """
        asset = create_registered_asset(
            title="Filter probe", description="x", classification="CONFIDENTIAL",
            owner_department="ENG", exposure_estimate_cents=3000,
        )
        add_verified_measure(asset["id"], "TECHNICAL", title="t", evidence_uri="s3://ev/t.pdf")
        # PLANNED CONTRACTUAL (no transitions)
        api.create_measure(create_measure_payload(asset["id"], measure_type="CONTRACTUAL",
                                                  title="c", evidence_uri=""), SEC)
        # PHYSICAL VERIFIED then LAPSED
        m3 = add_verified_measure(asset["id"], "PHYSICAL", title="p", evidence_uri="s3://ev/p.pdf")
        validate_success(api.transition_measure(m3["id"], {"to_status": "LAPSED"}, IP))

        data = validate_success(api.get_asset(asset["id"], IP))
        assert data["score_operational"] == pytest.approx(25.0, abs=0.01)
        assert data["score_documentary"] == pytest.approx(25.0, abs=0.01)
        assert data["protection_posture"] == "DEFICIENT"


class TestPostureReport:
    def test_posture_report_returns_both_variants_and_measure_breakdown(self, api):
        """PRD §3.1: "A litigation-readiness posture report, available to counsel,
        returns the asset's `id`, both `score_operational` and `score_documentary`,
        the `protection_posture`, and a per-measure breakdown carrying each
        measure's `weight_points` and `points_effective`."

        Design: Corner/endpoints/posture_report_returns_both_variants
        """
        asset = create_registered_asset(
            title="Report probe", description="x", classification="RESTRICTED",
            owner_department="ENG", exposure_estimate_cents=1000,
        )
        add_verified_measure(asset["id"], "TECHNICAL", title="t", evidence_uri="s3://ev/t.pdf")
        add_implemented_measure(asset["id"], "PHYSICAL", title="p", evidence_uri="s3://ev/p.pdf")

        data = validate_success(api.get_posture_report(asset["id"], SENIOR))
        assert data["score_operational"] == pytest.approx(34.0, abs=0.01), \
            f"expected 34 (25 + 15*0.6), got {data['score_operational']}"
        assert data["score_documentary"] == pytest.approx(25.0, abs=0.01)
        assert data["protection_posture"] == "DEFICIENT"
        weights = sorted(m["weight_points"] for m in data["measures"])
        assert weights == [15, 25], f"per-measure breakdown must carry weight_points: {weights}"
