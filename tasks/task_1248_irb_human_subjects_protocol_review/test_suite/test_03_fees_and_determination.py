"""Review-fee calculation variants, per-line rounding, and coordinator
determination rules (PRD §2.7, §3.2, §3.5, §3.9).
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_consent_document,
    assert_timestamp_equals,
    create_draft_protocol,
    create_reliance,
    execute_reliance_ok,
    get_protocol,
    get_reliance,
    register_chair,
    register_investigator,
    setup_approved_protocol,
    submit_protocol_ok,
    unique_email,
    upload_consent,
    validate_error,
    validate_paginated,
    validate_success,
)

COORDINATOR = TEST_USERS["coordinator_headers"]


def _submit_industry_protocol(claimed_level, risk_level="GREATER_THAN_MINIMAL"):
    """Investigator + chair + industry-sponsored protocol with an APPROVED
    consent document, submitted once. Returns (inv, chair, protocol)."""
    inv = register_investigator()
    chair = register_chair(email=unique_email("chair"))
    proto = create_draft_protocol(
        inv["id"], title="Fee Study", claimed_review_level=claimed_level,
        risk_level=risk_level, is_industry_sponsored=True,
    )
    cd = upload_consent(proto["id"], inv["id"], file_ref="s3://consent/fee-v1.pdf")
    approve_consent_document(cd["id"], chair["id"])
    submit_protocol_ok(proto["id"], inv["id"])
    return inv, chair, proto


class TestFeeProvisionalVsSettledDivergence:
    def test_fee_divergence_claimed_full_board_determined_expedited(self, api):
        """PRD §3.2: "The very first submission — the `DRAFT` → `SUBMITTED`
        crossing — is also the billing event: the system computes
        `provisional_fee_cents` exactly once, taking the base fee for the
        `claimed_review_level` (50,000 cents for `EXEMPT`, 150,000 cents for
        `EXPEDITED`, 250,000 cents for `FULL_BOARD`), multiplying by the
        industry multiplier, and rounding the product half-up to a whole number
        of cents per §2.7." PRD §3.2: "Every determination stamps
        `determined_review_level` and settles the fee base: `settled_fee_cents`
        becomes the rounded base line for the determined level, and
        `fee_delta_cents` is recomputed as the settled assessment minus the
        provisional one."

        Design: Difficulty/dual_variant_calc/fee_provisional_vs_settled_divergence_on_level_mismatch
        """
        _inv, _chair, proto = _submit_industry_protocol("FULL_BOARD")

        # Claimed FULL_BOARD industry: round(250000 * 1.5) = 375000.
        submitted = get_protocol(proto["id"])
        assert submitted["provisional_fee_cents"] == 375000

        resp = api.record_determination(
            proto["id"], {"determined_review_level": "EXPEDITED"}, COORDINATOR
        )
        data = validate_success(resp)
        # Determined EXPEDITED industry: round(150000 * 1.5) = 225000.
        assert data["settled_fee_cents"] == 225000
        assert data["provisional_fee_cents"] == 375000
        assert data["fee_delta_cents"] == -150000
        assert data["determined_review_level"] == "EXPEDITED"
        assert data["status"] == "UNDER_EXPEDITED_REVIEW"

    def test_fee_divergence_claimed_expedited_determined_full_board(self, api):
        """PRD §3.2: "the system computes `provisional_fee_cents` exactly once,
        taking the base fee for the `claimed_review_level`" and
        "`settled_fee_cents` becomes the rounded base line for the determined
        level, and `fee_delta_cents` is recomputed as the settled assessment
        minus the provisional one." The two variants diverge in the opposite
        direction when the determined level exceeds the claimed one.

        Design: Difficulty/dual_variant_calc/fee_provisional_vs_settled_divergence_on_level_mismatch
        """
        _inv, _chair, proto = _submit_industry_protocol("EXPEDITED")

        # Claimed EXPEDITED industry: round(150000 * 1.5) = 225000.
        submitted = get_protocol(proto["id"])
        assert submitted["provisional_fee_cents"] == 225000

        resp = api.record_determination(
            proto["id"], {"determined_review_level": "FULL_BOARD"}, COORDINATOR
        )
        data = validate_success(resp)
        # Determined FULL_BOARD industry: round(250000 * 1.5) = 375000.
        assert data["settled_fee_cents"] == 375000
        assert data["fee_delta_cents"] == 150000
        assert data["status"] == "AWAITING_FULL_BOARD"


class TestFeePerLineRoundingOrder:
    def _setup_approved_industry_protocol(self):
        return setup_approved_protocol(
            risk_level="MINIMAL", is_industry_sponsored=True,
            claimed_review_level="EXPEDITED", title="Rounding Study",
        )

    def test_fee_per_line_rounding_two_reliance_executes(self, api):
        """PRD §2.7: "The rounding order is pinned and not negotiable: each fee
        line is first computed by multiplying its base amount by the protocol's
        industry multiplier, and that product is rounded half-up to a whole
        number of cents; only then are the rounded lines summed into a fee
        total." PRD §3.9: "one rounded site line — the 74,999-cent reliance
        base multiplied by the protocol's industry multiplier and rounded
        half-up — is added onto the protocol's `settled_fee_cents`".

        Design: Difficulty/combinatorial_formula/fee_per_line_rounding_order_pinned
        """
        scenario = self._setup_approved_industry_protocol()
        proto = scenario["protocol"]

        # settled base after EXPEDITED determination: round(150000*1.5) = 225000.
        rel_a = create_reliance(proto["id"], ceding_institution_code="INST_A")
        rel_b = create_reliance(proto["id"], ceding_institution_code="INST_B")
        execute_reliance_ok(rel_a["id"])
        execute_reliance_ok(rel_b["id"])

        # Per-line rounding: round(74999*1.5) = 112499 per site line;
        # 225000 + 112499 + 112499 = 449998 (sum-then-round would give 449997).
        after = get_protocol(proto["id"])
        assert after["settled_fee_cents"] == 449998, (
            f"Expected per-line rounding to yield 449998, got {after['settled_fee_cents']}"
        )
        assert after["provisional_fee_cents"] == 225000
        assert after["fee_delta_cents"] == 224998
        assert get_reliance(rel_a["id"])["status"] == "EXECUTED"
        assert get_reliance(rel_b["id"])["status"] == "EXECUTED"

    def test_fee_per_line_rounding_first_execute_incremental(self, api):
        """PRD §3.9: "Each execution is also a billing event per §2.7: one
        rounded site line — the 74,999-cent reliance base multiplied by the
        protocol's industry multiplier and rounded half-up — is added onto the
        protocol's `settled_fee_cents`, and `fee_delta_cents` is recomputed
        against `provisional_fee_cents`."

        Design: Difficulty/combinatorial_formula/fee_per_line_rounding_order_pinned
        """
        scenario = self._setup_approved_industry_protocol()
        proto = scenario["protocol"]

        rel_a = create_reliance(proto["id"], ceding_institution_code="INST_A")
        execute_reliance_ok(rel_a["id"])

        # After exactly one execution: 225000 + round(74999*1.5) = 337499.
        after = get_protocol(proto["id"])
        assert after["settled_fee_cents"] == 337499, (
            f"Expected 337499 after one site line, got {after['settled_fee_cents']}"
        )
        assert after["fee_delta_cents"] == 112499


class TestDeterminationRules:
    def test_determination_exempt_requires_minimal_risk(self, api):
        """PRD §3.2: "`EXEMPT` is legal only when the protocol's `risk_level`
        is `MINIMAL` — an exempt determination on a `GREATER_THAN_MINIMAL`
        protocol is rejected with `ERR_EXEMPT_REQUIRES_MINIMAL_RISK`".

        Design: Corner/validations/determination_exempt_requires_minimal_risk
        """
        inv = register_investigator()

        p_high = create_draft_protocol(
            inv["id"], title="High", claimed_review_level="FULL_BOARD",
            risk_level="GREATER_THAN_MINIMAL",
        )
        upload_consent(p_high["id"], inv["id"], file_ref="s3://consent/xh.pdf")
        submit_protocol_ok(p_high["id"], inv["id"])

        p_min = create_draft_protocol(
            inv["id"], title="Min", claimed_review_level="EXEMPT",
            risk_level="MINIMAL",
        )
        upload_consent(p_min["id"], inv["id"], file_ref="s3://consent/xm.pdf")
        submit_protocol_ok(p_min["id"], inv["id"])

        resp = api.record_determination(
            p_high["id"], {"determined_review_level": "EXEMPT"}, COORDINATOR
        )
        validate_error(resp, ApiErrorId.ERR_EXEMPT_REQUIRES_MINIMAL_RISK)
        assert get_protocol(p_high["id"])["status"] == "SUBMITTED"

        data = validate_success(
            api.record_determination(
                p_min["id"], {"determined_review_level": "EXEMPT"}, COORDINATOR
            )
        )
        assert data["status"] == "EXEMPT_ACTIVE"

    def test_exempt_protocol_has_no_continuing_review_cadence(self, api):
        """PRD §3.2: "Exempt studies carry no continuing-review cadence — no
        continuing review is created and `approval_expires_at` stays null."
        PRD §3.2: "Every determination stamps `determined_review_level` and
        settles the fee base: `settled_fee_cents` becomes the rounded base line
        for the determined level".

        Design: Corner/calculations/exempt_protocol_has_no_continuing_review_cadence
        """
        inv = register_investigator()
        chair = register_chair(email=unique_email("chair"))
        proto = create_draft_protocol(
            inv["id"], title="Exempt Study", claimed_review_level="EXEMPT",
            risk_level="MINIMAL",
        )
        cd = upload_consent(proto["id"], inv["id"], file_ref="s3://consent/ex.pdf")
        approve_consent_document(cd["id"], chair["id"])
        submit_protocol_ok(proto["id"], inv["id"])

        data = validate_success(
            api.record_determination(
                proto["id"], {"determined_review_level": "EXEMPT"}, COORDINATOR
            )
        )
        assert data["status"] == "EXEMPT_ACTIVE"
        assert data["approval_expires_at"] is None
        # EXEMPT base fee, non-industry: 50000 * 1.0 = 50000.
        assert data["settled_fee_cents"] == 50000

        rows, _meta = validate_paginated(
            api.list_continuing_reviews(proto["id"], COORDINATOR)
        )
        assert rows == [], f"Exempt protocol must hold no continuing reviews, got {rows}"

    def test_continuing_review_interval_depends_on_risk_level(self, api):
        """PRD §3.5: "A successful approval writes
        `continuing_review_interval_days` as 180 when the protocol's
        `risk_level` is `GREATER_THAN_MINIMAL` and 365 when it is `MINIMAL`,
        sets `approval_expires_at` to the approval instant plus that interval".

        Design: Corner/calculations/continuing_review_interval_depends_on_risk_level
        """
        # Both approvals happen at the startup clock 2026-05-01T00:00:00Z.
        minimal = setup_approved_protocol(risk_level="MINIMAL", title="Min Risk")
        high = setup_approved_protocol(
            risk_level="GREATER_THAN_MINIMAL", title="High Risk"
        )

        p_min = get_protocol(minimal["protocol"]["id"])
        assert p_min["continuing_review_interval_days"] == 365
        assert_timestamp_equals(p_min["approval_expires_at"], "2027-05-01T00:00:00Z")

        p_high = get_protocol(high["protocol"]["id"])
        assert p_high["continuing_review_interval_days"] == 180
        assert_timestamp_equals(p_high["approval_expires_at"], "2026-10-28T00:00:00Z")
