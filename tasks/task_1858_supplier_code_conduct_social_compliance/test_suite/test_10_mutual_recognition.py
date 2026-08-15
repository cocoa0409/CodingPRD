"""Mutual recognition of industry audit programs and the interval formula."""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    OFFICER,
    cap_full_pass_cycle,
    create_claim,
    create_facility,
    decide_claim,
    get_claim,
    get_finding,
    get_scoping,
    parse_instant,
    setup_active_supplier,
    setup_failed_zt_audit,
    validate_error,
)


def interval_scenario():
    """BD / APPAREL / 1200-worker facility whose INITIAL audit FAILED_ZT; the
    zero-tolerance finding is then remediated to VERIFIED_CLOSED, and a fresh
    SMETA claim (score 80, date 2026-07-01) is accepted."""
    ctx = setup_failed_zt_audit(
        sector="APPAREL", supplier_country="BD", facility_country="BD",
        worker_count=1200, zt_category="FORCED_LABOR",
        scheduled_end="2026-09-03T00:00:00Z", auditor_countries=("BD",),
        supplier_name="Delta Textiles", facility_name="Chattogram Knit",
    )
    cap_full_pass_cycle(
        ctx["zt_finding"]["id"], ctx["supplier"]["id"], ctx["verifier"]["id"],
    )
    claim = create_claim(
        ctx["facility"]["id"], ctx["supplier"]["id"], program_name="SMETA",
        external_audit_ref="EXT-2026-118",
        external_audit_date="2026-07-01T00:00:00Z", external_score=80,
    )
    accepted = decide_claim(claim["id"], "ACCEPT")
    assert accepted["status"] == "ACCEPTED"
    return ctx


class TestIntervalTieredMinClamp:
    def test_failed_zt_audit_history_and_retier(self, api):
        """PRD §3.2: "Its history component counts the facility's findings on
        terminal audits that have not been voided, weighted 10 per
        `ZERO_TOLERANCE`, 4 per `MAJOR`, and 1 per `MINOR`, capped at 100. The
        `risk_score_history` is then the blend of one half baseline and one half
        history component, rounded half up to one decimal place."
        PRD §3.2: "`HIGH` at 70 or above, `MEDIUM` at 40 or above, otherwise
        `LOW`, with the band boundaries inclusive on their lower bounds."

        Design: Difficulty/combinatorial_formula/audit_interval_tiered_min_clamp
        """
        ctx = interval_scenario()
        scoping = get_scoping(ctx["facility"]["id"])
        # Baseline 87.0; history component min(100, 10*1) = 10;
        # round_half_up(0.5*87.0 + 0.5*10, 1) = 48.5.
        assert scoping["risk_score_history"] == pytest.approx(48.5, abs=0.01)
        assert scoping["risk_tier"] == "MEDIUM"

    def test_interval_pinned_order_and_due_date(self, api):
        """PRD §3.2: "The `next_audit_interval_months` starts from the tier base
        — `HIGH` 6 months, `MEDIUM` 12, `LOW` 24 — and is then adjusted in a
        pinned order: first, if the facility's latest terminal audit is
        `FAILED_ZT`, the interval is capped down to at most 3 months by taking
        the smaller of the two; second, if a valid accepted mutual-recognition
        claim covers the facility (§3.9), the claim's program validity months
        are added; third, the result is clamped to no fewer than 3 and no more
        than 36 months."
        PRD §3.9: "The facility's `next_audit_interval_months` and
        `next_audit_due_date` recompute with the claim's program validity
        extension — `BSCI` 24 months, `SMETA` 12, `RBA` 24, `WRAP` 12 — added
        into the interval at the pinned position of §3.2, after the tier base
        and any zero-tolerance-failure cap and before the clamp."

        Design: Difficulty/combinatorial_formula/audit_interval_tiered_min_clamp
        """
        ctx = interval_scenario()
        scoping = get_scoping(ctx["facility"]["id"])
        # tier base 12 -> min(12, FAILED_ZT cap 3) = 3 -> + SMETA validity 12
        # = 15 -> clamp [3, 36] keeps 15.
        assert scoping["next_audit_interval_months"] == 15
        # latest terminal audit scheduled_end 2026-09-03 + 15 months.
        assert parse_instant(scoping["next_audit_due_date"]) == datetime(
            2027, 12, 3, tzinfo=timezone.utc
        )


class TestClaimAcceptanceGates:
    def test_claim_accept_blocked_by_open_zt_finding(self, api):
        """PRD §3.9: "Acceptance carries three further preconditions: no `OPEN`
        zero-tolerance finding may exist at the claim's facility
        (`ERR_OPEN_ZT_FINDINGS_EXIST`); the `external_score` must meet the
        program's minimum — `BSCI` 85, `SMETA` 75, `RBA` 80, `WRAP` 80
        (`ERR_EXTERNAL_SCORE_TOO_LOW`, 422); and the `external_audit_date` must
        lie within 12 months of the current logical clock at decision time
        (`ERR_EXTERNAL_AUDIT_STALE`, 422)."

        Design: Difficulty/cross_entity_state_dependency/claim_accept_blocked_by_open_zt_finding
        """
        ctx = setup_failed_zt_audit(supplier_name="November Foods", sector="FOOD",
                                    facility_name="Fresno Pack")
        claim = create_claim(
            ctx["facility"]["id"], ctx["supplier"]["id"], program_name="SMETA",
            external_audit_ref="EXT-900",
            external_audit_date="2026-07-01T00:00:00Z", external_score=80,
        )
        resp = api.decide_mutual_recognition_claim(
            claim["id"], {"decision": "ACCEPT"}, OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_OPEN_ZT_FINDINGS_EXIST, 409)
        assert get_claim(claim["id"])["status"] == "SUBMITTED", (
            "a failed decide leaves the claim untouched"
        )

    def test_claim_accept_succeeds_after_zt_closed(self, api):
        """PRD §3.9: "no `OPEN` zero-tolerance finding may exist at the claim's
        facility (`ERR_OPEN_ZT_FINDINGS_EXIST`)"
        PRD §3.9: "An `ACCEPT` decision moves the claim to `ACCEPTED`"
        PRD §3.5: "When the `outcome` is `PASS`, the plan moves to
        `VERIFIED_PASSED`, which is terminal; the finding flips `OPEN →
        VERIFIED_CLOSED`"

        Design: Difficulty/cross_entity_state_dependency/claim_accept_blocked_by_open_zt_finding
        """
        ctx = setup_failed_zt_audit(supplier_name="November Foods", sector="FOOD",
                                    facility_name="Fresno Pack")
        claim = create_claim(
            ctx["facility"]["id"], ctx["supplier"]["id"], program_name="SMETA",
            external_audit_ref="EXT-900",
            external_audit_date="2026-07-01T00:00:00Z", external_score=80,
        )
        blocked = api.decide_mutual_recognition_claim(
            claim["id"], {"decision": "ACCEPT"}, OFFICER
        )
        validate_error(blocked, ApiErrorId.ERR_OPEN_ZT_FINDINGS_EXIST)

        cap_full_pass_cycle(
            ctx["zt_finding"]["id"], ctx["supplier"]["id"],
            ctx["verifier"]["id"],
        )
        assert get_finding(ctx["zt_finding"]["id"])["status"] == (
            "VERIFIED_CLOSED"
        )
        accepted = decide_claim(claim["id"], "ACCEPT")
        assert accepted["status"] == "ACCEPTED", (
            "with the zero-tolerance finding closed, acceptance proceeds"
        )

    def test_claim_decide_after_rejected_rejected(self, api):
        """PRD §3.9: "A `ComplianceOfficer` decides the claim with a `decision`,
        valid only from `SUBMITTED` (`ERR_CLAIM_INVALID_STATE`)."
        PRD §3.9: "An `ACCEPT` decision moves the claim to `ACCEPTED`; a
        `REJECT` decision moves it to `REJECTED` and stores the payload's
        `decision_reason` on the claim. Both outcomes are terminal."

        Design: Corner/state_machines/claim_decide_after_rejected_rejected
        """
        ctx = setup_active_supplier(legal_name="Echo Goods", sector="FOOD")
        facility = create_facility(ctx["supplier"]["id"], name="Site Q9")
        claim = create_claim(
            facility["id"], ctx["supplier"]["id"], program_name="WRAP",
            external_audit_ref="EXT-1",
            external_audit_date="2026-07-01T00:00:00Z", external_score=60,
        )
        rejected = decide_claim(claim["id"], "REJECT",
                                decision_reason="Insufficient evidence")
        assert rejected["status"] == "REJECTED"
        assert rejected["decision_reason"] == "Insufficient evidence"

        resp = api.decide_mutual_recognition_claim(
            claim["id"], {"decision": "ACCEPT"}, OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_INVALID_STATE, 409)

    def test_claim_score_below_program_minimum_rejected(self, api):
        """PRD §3.9: "the `external_score` must meet the program's minimum —
        `BSCI` 85, `SMETA` 75, `RBA` 80, `WRAP` 80
        (`ERR_EXTERNAL_SCORE_TOO_LOW`, 422)"

        Design: Corner/validations/claim_score_below_program_minimum_rejected
        """
        ctx = setup_active_supplier(legal_name="Golf C", sector="FOOD")
        facility = create_facility(ctx["supplier"]["id"], name="Site R2")
        claim = create_claim(
            facility["id"], ctx["supplier"]["id"], program_name="SMETA",
            external_audit_ref="EXT-2",
            external_audit_date="2026-07-01T00:00:00Z", external_score=70,
        )
        resp = api.decide_mutual_recognition_claim(
            claim["id"], {"decision": "ACCEPT"}, OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_EXTERNAL_SCORE_TOO_LOW, 422)
        assert get_claim(claim["id"])["status"] == "SUBMITTED"

    def test_claim_external_audit_stale_rejected(self, api):
        """PRD §3.9: "the `external_audit_date` must lie within 12 months of the
        current logical clock at decision time (`ERR_EXTERNAL_AUDIT_STALE`,
        422)."

        Design: Corner/validations/claim_external_audit_stale_rejected
        """
        ctx = setup_active_supplier(legal_name="Hotel C", sector="FOOD")
        facility = create_facility(ctx["supplier"]["id"], name="Site Q2")
        # 2025-06-01 is 14 months before the 2026-08-01 default clock; the
        # passing score (90 >= 75) cannot rescue it.
        claim = create_claim(
            facility["id"], ctx["supplier"]["id"], program_name="SMETA",
            external_audit_ref="EXT-3",
            external_audit_date="2025-06-01T00:00:00Z", external_score=90,
        )
        resp = api.decide_mutual_recognition_claim(
            claim["id"], {"decision": "ACCEPT"}, OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_EXTERNAL_AUDIT_STALE, 422)
