"""Model registration, initial risk tiering, and the risk-score calculation."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_instant_equal,
    assert_model,
    assert_model_invariants,
    create_model,
    create_model_payload,
    get_model,
    validate_error,
    validate_success,
    create_approvable_model,
    complete_engagement,
    open_engagement,
    create_model_with_approved_doc,
    TEST_USERS,
)

OWNER_A = TEST_USERS["model_owner_a_headers"]
OFFICER = TEST_USERS["risk_officer_headers"]
VALIDATOR = TEST_USERS["model_validator_headers"]


class TestModelRegistration:
    def test_model_registration_computed_defaults(self, api):
        """PRD §3.1: "At registration the server records the caller's `X-User-ID` as
        `owner_user_id`, sets `status` to `REGISTERED`, and leaves `assessed_complexity`,
        `last_validated_at`, and `replaced_by_model_id` unset."
        PRD §3.1: "A freshly registered model starts with `monitoring_posture` of
        `NORMAL` and an `open_findings_count` of zero."
        PRD §3.1: "The developer-declared score is then twenty times the complexity
        points of `declared_complexity`, plus ten times the scope points, plus ten
        times the exposure points, plus the findings penalty".
        PRD §2.4: "Every resource except one also carries a `version`, an integer that
        increments on every mutation of that resource."

        MEDIUM (2 pts) / SINGLE_DESK (0 pts) / exposure 100 (1 pt) -> 20*2 + 10*0 + 10*1 = 50 -> TIER_2.

        Design: Corner/entities/model_registration_computed_defaults
        """
        resp = api.create_model(
            create_model_payload(
                name="Reg M",
                business_unit="Treasury",
                declared_complexity="MEDIUM",
                usage_scope="SINGLE_DESK",
                exposure_amount=100,
            ),
            OWNER_A,
        )
        created = validate_success(resp, expected_status=201)
        assert_model(created)

        data = validate_success(api.get_model(created["id"], OWNER_A))
        assert data["owner_user_id"] == "u_own_a", "owner_user_id must be stamped from X-User-ID"
        assert data["status"] == "REGISTERED"
        assert data["risk_score"] == 50, f"expected 20*2 + 10*0 + 10*1 = 50, got {data['risk_score']}"
        assert data["risk_tier"] == "TIER_2"
        assert data["monitoring_posture"] == "NORMAL"
        assert data["open_findings_count"] == 0
        assert data.get("assessed_complexity") is None
        assert data.get("last_validated_at") is None
        assert data.get("replaced_by_model_id") is None
        assert isinstance(data["version"], int), "a registered model carries an integer version"

    def test_model_is_vendor_model_default_false(self, api):
        """PRD §3.1: "An optional `is_vendor_model` flag, defaulting to false, marks
        the model as externally supplied."
        PRD §3.5: "Assessments exist only for models registered with `is_vendor_model`
        true; recording one for any other model fails with `ERR_NOT_A_VENDOR_MODEL`."

        Design: Corner/entities/model_is_vendor_model_default_false
        """
        payload = create_model_payload(
            name="Default M", declared_complexity="LOW", usage_scope="SINGLE_DESK", exposure_amount=100
        )
        assert "is_vendor_model" not in payload, "this test omits the optional flag"
        created = validate_success(api.create_model(payload, OWNER_A), expected_status=201)
        assert created["is_vendor_model"] is False, "omitted is_vendor_model must default to false"

        err = validate_error(
            api.create_vendor_assessment(
                created["id"], {"completeness_score": 80, "valid_months": 6}, OFFICER
            ),
            ApiErrorId.ERR_NOT_A_VENDOR_MODEL,
        )
        assert err["error_id"] == "ERR_NOT_A_VENDOR_MODEL"

    def test_model_get_returns_stored_entity(self, api):
        """PRD §3.1: "The developer-declared score is then twenty times the complexity
        points of `declared_complexity`, plus ten times the scope points, plus ten
        times the exposure points, plus the findings penalty".
        PRD §2.1: "All four business roles (`ModelOwner`, `ModelValidator`,
        `ModelRiskOfficer`, `RegulatoryReporter`) may use every read endpoint".

        LOW (1) / ENTERPRISE (2) / 20,000,000 (3 pts) -> 20*1 + 10*2 + 10*3 = 70 -> TIER_1.

        Design: Corner/entities/model_get_returns_stored_entity
        """
        created = validate_success(
            api.create_model(
                create_model_payload(
                    name="Gettable M",
                    business_unit="Finance",
                    declared_complexity="LOW",
                    usage_scope="ENTERPRISE",
                    exposure_amount=20000000,
                    is_vendor_model=False,
                ),
                OWNER_A,
            ),
            expected_status=201,
        )
        data = validate_success(api.get_model(created["id"], VALIDATOR))
        assert data["name"] == "Gettable M"
        assert data["risk_score"] == 70
        assert data["risk_tier"] == "TIER_1"
        assert_model_invariants(data)

    def test_model_registration_missing_required_field_rejected(self, api):
        """PRD §2.8: "Required fields must be present, types must be correct, and enum
        values must be in range; this stage also covers the engagement scope rule (at
        least one scope flag selected) and the period rule (period end strictly after
        period start). Violations yield `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "A `ModelOwner` registers a model by supplying its `name`,
        `business_unit`, `declared_complexity` (one of `LOW`, `MEDIUM`, `HIGH`),
        `usage_scope` (one of `SINGLE_DESK`, `MULTI_DESK`, `ENTERPRISE`), and
        `exposure_amount` — the dollar exposure the model drives, an integer number of
        dollars of zero or more."

        Design: Corner/entities/model_registration_missing_required_field_rejected
        """
        payload = {
            "name": "NoExposure M",
            "business_unit": "Risk",
            "declared_complexity": "LOW",
            "usage_scope": "SINGLE_DESK",
        }
        err = validate_error(api.create_model(payload, OWNER_A), ApiErrorId.ERR_INVALID_REQUEST)
        assert err["error_id"] == "ERR_INVALID_REQUEST"

    def test_model_registration_invalid_enum_rejected(self, api):
        """PRD §2.8: "Required fields must be present, types must be correct, and enum
        values must be in range; this stage also covers the engagement scope rule (at
        least one scope flag selected) and the period rule (period end strictly after
        period start). Violations yield `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "`declared_complexity` (one of `LOW`, `MEDIUM`, `HIGH`)".

        Design: Corner/entities/model_registration_invalid_enum_rejected
        """
        payload = create_model_payload(
            name="BadEnum M", declared_complexity="EXTREME", usage_scope="SINGLE_DESK", exposure_amount=100
        )
        err = validate_error(api.create_model(payload, OWNER_A), ApiErrorId.ERR_INVALID_REQUEST)
        assert err["error_id"] == "ERR_INVALID_REQUEST"

    def test_model_exposure_zero_is_valid(self, api):
        """PRD §3.1: "`exposure_amount` — the dollar exposure the model drives, an
        integer number of dollars of zero or more."
        PRD §3.1: "Exposure points come from `exposure_amount`: one point when exposure
        is below one million dollars".

        LOW (1) / SINGLE_DESK (0) / 0 (1 pt) -> 20 + 0 + 10 = 30 -> TIER_3.

        Design: Corner/entities/model_exposure_zero_is_valid
        """
        created = validate_success(
            api.create_model(
                create_model_payload(
                    name="ZeroExp M", declared_complexity="LOW", usage_scope="SINGLE_DESK", exposure_amount=0
                ),
                OWNER_A,
            ),
            expected_status=201,
        )
        assert created["risk_score"] == 30
        assert created["risk_tier"] == "TIER_3"


class TestRiskScoreCalculation:
    def test_risk_score_exposure_band_boundaries(self, api):
        """PRD §3.1: "Exposure points come from `exposure_amount`: one point when
        exposure is below one million dollars; two when it is at least one million but
        below ten million; three when it is at least ten million but below one hundred
        million; four when it is at least one hundred million."

        Declared LOW / SINGLE_DESK throughout (base 20): 999999 -> 30, 1000000 -> 40,
        9999999 -> 40, 10000000 -> 50, 100000000 -> 60.

        Design: Corner/calculations/risk_score_exposure_band_boundaries
        """
        cases = [
            ("Band A", 999999, 30),
            ("Band B", 1000000, 40),
            ("Band C", 9999999, 40),
            ("Band D", 10000000, 50),
            ("Band E", 100000000, 60),
        ]
        for name, exposure, expected in cases:
            created = validate_success(
                api.create_model(
                    create_model_payload(
                        name=name, declared_complexity="LOW", usage_scope="SINGLE_DESK",
                        exposure_amount=exposure,
                    ),
                    OWNER_A,
                ),
                expected_status=201,
            )
            assert created["risk_score"] == expected, (
                f"{name}: exposure {exposure} -> expected score {expected}, got {created['risk_score']}"
            )

    def test_risk_score_findings_penalty_weights(self, api):
        """PRD §3.1: "A findings penalty is added on top: ten points per open finding
        of severity `CRITICAL`, five per `HIGH`, two per `MEDIUM`, and one per `LOW`,
        where a finding counts as open while its status is `OPEN`, `OVERDUE`, or
        `ESCALATED`; `CLOSED` findings never contribute."
        PRD §3.6: "Raising a finding increments the model's `open_findings_count` —
        defined as the number of findings on the model whose status is `OPEN`,
        `OVERDUE`, or `ESCALATED` — by one and recomputes the model's `risk_score` and
        `risk_tier`, since the findings penalty of §3.1 has grown."

        Base 30 (LOW/SINGLE_DESK/100) + 10 (CRITICAL) + 2 (MEDIUM) = 42 -> TIER_2.

        Design: Corner/calculations/risk_score_findings_penalty_weights
        """
        model = create_model(name="Pen M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        assert model["risk_score"] == 30
        validate_success(
            api.create_finding(model["id"], {"severity": "CRITICAL", "title": "crit"}, OFFICER),
            expected_status=201,
        )
        validate_success(
            api.create_finding(model["id"], {"severity": "MEDIUM", "title": "med"}, OFFICER),
            expected_status=201,
        )
        data = validate_success(api.get_model(model["id"], OFFICER))
        assert data["risk_score"] == 42, f"expected 30 + 10 + 2 = 42, got {data['risk_score']}"
        assert data["risk_tier"] == "TIER_2"
        assert data["open_findings_count"] == 2

    def test_risk_score_capped_at_100(self, api):
        """PRD §3.1: "and if that total exceeds the cap of 100, the score is 100."

        HIGH (3) / ENTERPRISE (2) / 100,000,000 (4 pts) -> 60 + 20 + 40 = 120 -> capped
        at 100; an added CRITICAL finding keeps it at 100 (130 -> cap), never above.

        Design: Corner/calculations/risk_score_capped_at_100
        """
        created = validate_success(
            api.create_model(
                create_model_payload(
                    name="Cap M", declared_complexity="HIGH", usage_scope="ENTERPRISE",
                    exposure_amount=100000000,
                ),
                OWNER_A,
            ),
            expected_status=201,
        )
        assert created["risk_score"] == 100, "min(100, 120) at registration"
        validate_success(
            api.create_finding(created["id"], {"severity": "CRITICAL", "title": "cap pressure"}, OFFICER),
            expected_status=201,
        )
        data = validate_success(api.get_model(created["id"], OFFICER))
        assert data["risk_score"] == 100, "min(100, 130) after the CRITICAL finding — cap binds"
        assert data["risk_tier"] == "TIER_1"


class TestDualVariantRiskScore:
    def test_dev_declared_variant_scores_registration(self, api):
        """PRD §3.1: "Registration computes the first `risk_score` under the
        developer-declared variant."
        PRD §3.1: "The developer-declared score is then twenty times the complexity
        points of `declared_complexity`, plus ten times the scope points, plus ten
        times the exposure points, plus the findings penalty".

        HIGH (3) / MULTI_DESK (1) / 500 (1 pt): 20*3 + 10*1 + 10*1 = 80 -> TIER_1.

        Design: Difficulty/dual_variant_calc/model_risk_score_dev_declared_vs_validator_assessed
        """
        created = validate_success(
            api.create_model(
                create_model_payload(
                    name="Score Variant M", business_unit="Treasury", declared_complexity="HIGH",
                    usage_scope="MULTI_DESK", exposure_amount=500, is_vendor_model=False,
                ),
                OWNER_A,
            ),
            expected_status=201,
        )
        assert created["risk_score"] == 80, f"DEV_DECLARED variant: expected 80, got {created['risk_score']}"
        assert created["risk_tier"] == "TIER_1"
        assert created.get("assessed_complexity") is None, "assessed_complexity unset until a validation completes"

    def test_validator_assessed_variant_replaces_after_completion(self, api):
        """PRD §3.1: "Once any validation engagement completes, the validator-assessed
        variant applies from that moment forward: the computation is identical except
        that the complexity term is twenty-five times the complexity points of
        `assessed_complexity` rather than twenty times the declared figure, so the same
        model inputs can yield a different score and tier."
        PRD §3.4: "Completion ripples into the model: the model's `assessed_complexity`
        takes the engagement's value, `last_validated_at` becomes the completion
        timestamp, `risk_score` is recomputed under the validator-assessed variant of
        §3.1, `risk_tier` is re-derived, and `validation_due_at` is reset to the
        completion time plus the new tier's revalidation interval."

        Same model (MULTI_DESK, 500): 80 under DEV_DECLARED (declared HIGH), then
        25*2 + 10*1 + 10*1 = 70 under VALIDATOR_ASSESSED (assessed MEDIUM) -> TIER_1,
        validation_due_at = completed_at (2026-08-01, the logical clock default) + 6
        months = 2027-02-01.

        Design: Difficulty/dual_variant_calc/model_risk_score_dev_declared_vs_validator_assessed
        """
        model, doc = create_model_with_approved_doc(
            name="Score Variant M", business_unit="Treasury", declared_complexity="HIGH",
            usage_scope="MULTI_DESK", exposure_amount=500, is_vendor_model=False,
        )
        assert model["risk_score"] == 80 and model["risk_tier"] == "TIER_1"
        eng = open_engagement(
            model["id"], period_start="2026-08-02T00:00:00Z", period_end="2026-08-20T00:00:00Z"
        )
        validate_success(
            api.complete_engagement(eng["id"], {"outcome": "EFFECTIVE", "assessed_complexity": "MEDIUM"}, VALIDATOR)
        )
        data = validate_success(api.get_model(model["id"], OFFICER))
        assert data["risk_score"] == 70, (
            f"VALIDATOR_ASSESSED variant: expected 25*2 + 10*1 + 10*1 = 70, got {data['risk_score']}"
        )
        assert data["risk_tier"] == "TIER_1"
        assert data["assessed_complexity"] == "MEDIUM"
        assert_instant_equal(data["last_validated_at"], "2026-08-01T00:00:00Z", "last_validated_at")
        assert_instant_equal(data["validation_due_at"], "2027-02-01T00:00:00Z", "validation_due_at")
