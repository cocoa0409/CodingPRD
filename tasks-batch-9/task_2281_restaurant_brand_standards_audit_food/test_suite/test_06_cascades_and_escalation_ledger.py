"""Outward cascades from an amendment and from an overdue sweep, and the ledger's symmetry."""
import pytest

from test_helpers import (
    ADMIN_HEADERS,
    AFTER_CRITICAL_DEADLINE,
    api_client,
    assert_escalation_event,
    assert_instant,
    assert_scored_item,
    attach_action_photo,
    resolve_dispute_payload,
    setup_dispute_in_evidence_review,
    setup_escalated_critical_action,
    validate_paginated,
    validate_success,
    verify_payload,
)


def _amendable_dispute():
    return setup_dispute_in_evidence_review(
        item_code="FS-1", requested_points=30,
        with_reviewer=True, health_points=74, health_grade="C",
    )


class TestAmendmentCascade:
    def test_amendment_re_derives_the_scored_item_and_its_visit(self):
        """The granted figure becomes the effective points and re-derives the visit.

        PRD: "`effective_points_awarded` now reads from `amended_points_awarded` rather
        than `points_awarded`, and `is_violation` and `severity` are re-derived from it."

        Design: Difficulty/transitive_cascade/dispute_amendment_cascades_five_levels_to_brand_index
        """
        program = _amendable_dispute()
        assert program["visit"]["composite_score"] == pytest.approx(86.52, abs=0.01)
        assert program["visit"]["grade"] == "CONDITIONAL"

        resolved = validate_success(
            api_client.resolve_dispute(
                program["dispute"]["id"],
                resolve_dispute_payload("AMENDED", granted_points=30),
                program["reviewer_calibration_headers"],
            )
        )
        assert resolved["status"] == "AMENDED"
        assert resolved["resolution_points"] == 30
        assert resolved["resolved_at"] is not None

        item = validate_success(
            api_client.get_scored_item(program["disputed_item"]["id"], ADMIN_HEADERS)
        )
        assert_scored_item(item)
        assert item["status"] == "AMENDED"
        assert item["original_points_awarded"] == 27, \
            "the auditor's first judgement is never overwritten"
        assert item["amended_points_awarded"] == 30
        assert item["effective_points_awarded"] == 30
        assert item["is_violation"] is False
        assert item["severity"] == "NONE"

        visit = validate_success(
            api_client.get_audit_visit(program["visit"]["id"], ADMIN_HEADERS)
        )
        assert visit["food_safety_percent"] == pytest.approx(100.00, abs=0.01)
        assert visit["critical_violation_count"] == 0
        assert visit["critical_penalty_points"] == pytest.approx(0.00, abs=0.01)
        assert visit["composite_score"] == pytest.approx(91.40, abs=0.01), \
            "0.45 * 95.33 + 0.30 * 100.00 + 0.25 * 74.00 rounds to 91.40"
        assert visit["composite_variant"] == "FINAL"
        assert visit["grade"] == "PASS"

    def test_amendment_cascades_out_to_the_location_and_the_brand_index(self):
        """The re-derivation runs outward through the action, the location and the brand.

        PRD: "That re-derivation then propagates outward in the order given in §2.7: the
        parent visit's section percents, `critical_violation_count`,
        `critical_penalty_points`, `FINAL` composite score, and `grade` are recomputed; the
        location's `standing_score`, `latest_grade`, and `repeat_violation_count` follow;
        when the amendment drops the item out of `CRITICAL` severity, the non-terminal
        corrective action on that item is driven to `VOIDED`, which lowers the location's
        `open_corrective_action_count` and, if that action had already escalated, appends a
        `VOID_REVERSAL` ledger entry that steps `escalation_level` back down and re-derives
        `franchise_agreement_status`; and finally the brand's `brand_risk_index` is
        recomputed."

        Design: Difficulty/transitive_cascade/dispute_amendment_cascades_five_levels_to_brand_index
        """
        program = _amendable_dispute()
        location_id = program["location"]["id"]

        before = validate_success(api_client.get_location(location_id, ADMIN_HEADERS))
        assert before["standing_score"] == pytest.approx(86.52, abs=0.01)
        assert before["open_corrective_action_count"] == 3
        risk_before = validate_success(
            api_client.get_brand_risk_index(program["brand"]["id"], ADMIN_HEADERS)
        )
        assert risk_before["brand_risk_index"] == pytest.approx(14.09, abs=0.01)
        assert risk_before["open_critical_action_count"] == 1

        validate_success(
            api_client.resolve_dispute(
                program["dispute"]["id"],
                resolve_dispute_payload("AMENDED", granted_points=30),
                program["reviewer_calibration_headers"],
            )
        )

        location = validate_success(api_client.get_location(location_id, ADMIN_HEADERS))
        assert location["standing_score"] == pytest.approx(91.40, abs=0.01)
        assert location["latest_grade"] == "PASS"
        assert location["open_corrective_action_count"] == 2, \
            "the critical action is voided out of the open pool"

        critical_action = validate_success(
            api_client.get_corrective_action(program["actions"]["FS-1"]["id"], ADMIN_HEADERS)
        )
        assert critical_action["status"] == "VOIDED"

        risk = validate_success(
            api_client.get_brand_risk_index(program["brand"]["id"], ADMIN_HEADERS)
        )
        assert risk["average_standing_score"] == pytest.approx(91.40, abs=0.01)
        assert risk["open_critical_action_count"] == 0
        assert risk["fail_grade_surcharge_applied"] is False
        assert risk["brand_risk_index"] == pytest.approx(5.16, abs=0.01), \
            "only six tenths of the 8.60 standing deficit remains"
        assert risk["brand_risk_tier"] == "BASELINE"


class TestOverdueSweepCascade:
    def test_the_sweep_escalates_the_critical_action_and_ledgers_the_step(self):
        """A critical action never rests in OVERDUE; it continues to ESCALATED.

        PRD: "A `CRITICAL` action never rests in `OVERDUE`: the moment it is swept there it
        immediately continues `OVERDUE → ESCALATED` as a system cascade."

        Design: Difficulty/transitive_cascade/overdue_sweep_cascades_four_levels_to_franchise_agreement
        """
        program = setup_escalated_critical_action()
        sweep = program["sweep"]

        assert sweep["swept_count"] == 1
        assert sweep["overdue_count"] == 1
        assert sweep["escalated_count"] == 1
        assert sweep["escalated_location_count"] == 1

        action = validate_success(
            api_client.get_corrective_action(program["actions"]["FS-1"]["id"], ADMIN_HEADERS)
        )
        assert action["status"] == "ESCALATED"
        assert action["severity"] == "CRITICAL"
        assert_instant(action["escalated_at"], AFTER_CRITICAL_DEADLINE, "escalated_at")

        events, meta = validate_paginated(
            api_client.list_location_escalation_events(program["location"]["id"], ADMIN_HEADERS)
        )
        assert meta["total_count"] == 1
        entry = events[0]
        assert_escalation_event(entry)
        assert entry["event_type"] == "OVERDUE_CRITICAL"
        assert entry["level_delta"] == 1
        assert entry["resulting_escalation_level"] == 1
        assert entry["resulting_agreement_status"] == "NOTICE_OF_DEFAULT"
        assert entry["corrective_action_id"] == action["id"]

        remaining, remaining_meta = validate_paginated(
            api_client.list_corrective_actions(ADMIN_HEADERS, params={"status": "ASSIGNED"})
        )
        assert remaining_meta["total_count"] == 2, "both standard actions are still assigned"
        assert all(row["severity"] == "STANDARD" for row in remaining)

    def test_the_escalation_reaches_the_franchisee_and_the_brand(self):
        """Escalation walks the location, the franchisee and the brand in that order.

        PRD: "That location movement then recomputes
        `Franchisee.open_default_location_count`, `Franchisee.termination_recommended`,
        `Brand.default_location_count`, and `Brand.brand_risk_index`."

        Design: Difficulty/transitive_cascade/overdue_sweep_cascades_four_levels_to_franchise_agreement
        """
        program = setup_escalated_critical_action()

        location = validate_success(
            api_client.get_location(program["location"]["id"], ADMIN_HEADERS)
        )
        assert location["escalation_level"] == 1
        assert location["franchise_agreement_status"] == "NOTICE_OF_DEFAULT"
        assert location["open_corrective_action_count"] == 2, \
            "an escalated action has left the open remediation pool"

        franchisee = validate_success(
            api_client.get_franchisee(program["franchisee"]["id"], ADMIN_HEADERS)
        )
        assert franchisee["open_default_location_count"] == 1
        assert franchisee["termination_recommended"] is False

        risk = validate_success(
            api_client.get_brand_risk_index(program["brand"]["id"], ADMIN_HEADERS)
        )
        assert risk["default_location_count"] == 1
        assert risk["open_critical_action_count"] == 1, \
            "an escalated critical action still counts against the brand"
        assert risk["brand_risk_index"] == pytest.approx(24.09, abs=0.01), \
            "0.60 * 13.48 + 6.00 + 10.00 rounds to 24.09"


class TestEscalationLedgerConservation:
    def test_the_cure_entry_cancels_the_overdue_entry_exactly(self):
        """The level is the signed sum of the ledger, so a cure restores good standing.

        PRD: "To project the level, the ledger is read in `occurred_at` ascending order
        with `created_at` ascending as the tiebreaker, the deltas are summed, and the result
        is floored at zero, so `escalation_level` is never negative."

        Design: Difficulty/compensating_invariant/escalation_ledger_conserves_level_across_escalate_and_cure
        """
        program = setup_escalated_critical_action()
        location_id = program["location"]["id"]

        for code in ("BS-1", "FC-1"):
            action_id = program["actions"][code]["id"]
            attach_action_photo(program, action_id)
            validate_success(
                api_client.submit_corrective_action(
                    action_id, program["franchisee_headers"],
                    {"remediation_note": "Deficiency remediated and photographed."},
                )
            )
            validate_success(
                api_client.verify_corrective_action(
                    action_id, verify_payload("ACCEPTED"), program["auditor_headers"],
                )
            )

        cleared = validate_success(api_client.get_location(location_id, ADMIN_HEADERS))
        assert cleared["open_corrective_action_count"] == 0
        assert cleared["escalation_level"] == 1

        cured = validate_success(
            api_client.accept_cure(
                location_id, ADMIN_HEADERS,
                {"note": "Cure plan accepted by brand counsel"},
            )
        )
        assert cured["escalation_level"] == 0
        assert cured["franchise_agreement_status"] == "GOOD_STANDING"
        assert cured["cure_period_started_at"] is None
        assert cured["standing_score"] == pytest.approx(86.52, abs=0.01), \
            "the cure does not rewrite the audit arithmetic"

        events, meta = validate_paginated(
            api_client.list_location_escalation_events(location_id, ADMIN_HEADERS)
        )
        assert meta["total_count"] == 2, "the ledger is append-only and never pruned"
        assert [row["event_type"] for row in events] == ["OVERDUE_CRITICAL", "CURE_ACCEPTED"]
        assert [row["level_delta"] for row in events] == [1, -1]
        assert events[-1]["resulting_escalation_level"] == 0
        assert events[-1]["resulting_agreement_status"] == "GOOD_STANDING"

    def test_the_cure_restores_the_franchisee_and_brand_counters(self):
        """Accepting a cure from notice of default recomputes the outward counters.

        PRD: "Accepting a cure from `NOTICE_OF_DEFAULT` appends a `CURE_ACCEPTED` entry that
        lowers `escalation_level` to 0, re-derives `franchise_agreement_status` to
        `GOOD_STANDING`, and recomputes `Franchisee.open_default_location_count`,
        `Brand.default_location_count`, and `Brand.brand_risk_index`."

        Design: Difficulty/compensating_invariant/escalation_ledger_conserves_level_across_escalate_and_cure
        """
        program = setup_escalated_critical_action()
        location_id = program["location"]["id"]

        for code in ("BS-1", "FC-1"):
            action_id = program["actions"][code]["id"]
            attach_action_photo(program, action_id)
            validate_success(
                api_client.submit_corrective_action(
                    action_id, program["franchisee_headers"],
                    {"remediation_note": "Deficiency remediated and photographed."},
                )
            )
            validate_success(
                api_client.verify_corrective_action(
                    action_id, verify_payload("ACCEPTED"), program["auditor_headers"],
                )
            )

        validate_success(
            api_client.accept_cure(
                location_id, ADMIN_HEADERS,
                {"note": "Cure plan accepted by brand counsel"},
            )
        )

        franchisee = validate_success(
            api_client.get_franchisee(program["franchisee"]["id"], ADMIN_HEADERS)
        )
        assert franchisee["open_default_location_count"] == 0
        assert franchisee["termination_recommended"] is False

        risk = validate_success(
            api_client.get_brand_risk_index(program["brand"]["id"], ADMIN_HEADERS)
        )
        assert risk["default_location_count"] == 0
        assert risk["open_critical_action_count"] == 1, \
            "the escalated critical action itself is unchanged by the cure"
        assert risk["brand_risk_index"] == pytest.approx(14.09, abs=0.01), \
            "0.60 * 13.48 + 6.00 with no default contribution rounds to 14.09"
