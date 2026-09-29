"""Revoking a licence and following the five hops plus the compliance fan-out.

One store, one approved licence, one active stage and one armed successor.  The
revocation drives the licence, the store, the cadence, the store's projection and
the engagement's shortfall in turn, and records a strike alongside the chain.
"""
import pytest

from test_helpers import (
    activate_markdown_stage,
    add_inventory_lot,
    add_markdown_stage,
    add_store,
    api_client,
    apply_for_license,
    approve_engagement,
    assert_engagement,
    assert_gob_license,
    assert_markdown_stage,
    assert_recovery_summary,
    assert_store,
    create_engagement,
    create_jurisdiction,
    decide_license,
    make_compliance_headers,
    make_consultant_headers,
    make_controller_headers,
    pin_clock,
    read_engagement,
    read_store,
    revoke_license,
    submit_engagement,
    validate_success,
)

APPAREL_LOT = {
    "category": "APPAREL", "source": "ORIGINAL", "units_initial": 1000,
    "unit_cost_cents": 2000, "unit_retail_cents": 5000,
}
ELECTRONICS_LOT = {
    "category": "ELECTRONICS", "source": "ORIGINAL", "units_initial": 200,
    "unit_cost_cents": 15000, "unit_retail_cents": 30000,
}
NY_RULES = {
    "code": "NY", "name": "New York", "gob_license_required": True,
    "max_sale_days": 60, "license_cooling_off_days": 30,
    "max_augmentation_ratio": 0.1, "augmentation_disclosure_required": True,
    "advertising_disclosure_required": False, "surrender_notice_days": 10,
}
REVOCATION_REASON = "Advertising audit failure"


def _read_stage(stage_id):
    return validate_success(
        api_client.get_markdown_stage(stage_id, make_consultant_headers())
    )


def _read_license(license_id):
    return validate_success(
        api_client.get_gob_license(license_id, make_compliance_headers())
    )


def _read_summary(engagement_id):
    return validate_success(
        api_client.get_recovery_summary(engagement_id, make_controller_headers())
    )


def _selling_store_whose_licence_is_revoked():
    """A guaranteed engagement whose only store loses its licence mid-cadence.

    Stage 1 at 0.20 is in force and stage 2 at 0.40 is armed behind it, so the
    revocation empties the active slot and leaves exactly one stage in the planned
    set.
    """
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**NY_RULES)
    engagement = create_engagement(
        economics_model="GUARANTEED", guaranty_pct=1.5, hybrid_retailer_excess_pct=0,
        expense_responsibility="SHARED", shared_expense_liquidator_pct=0.4,
        sale_start_date="2026-09-15", target_end_date="2026-11-30",
    )
    store = add_store(
        engagement["id"], jurisdiction["id"],
        store_code="S-801", address_line="61 Grand Ave",
    )
    add_inventory_lot(store["id"], **APPAREL_LOT)
    add_inventory_lot(store["id"], **ELECTRONICS_LOT)
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    license_row = apply_for_license(
        store["id"], license_number="NY-GOB-0801",
        period_start_date="2026-09-15", period_end_date="2026-10-14",
        advertising_claim_codes=["EVERYTHING_MUST_GO"],
    )
    decide_license(license_row["id"])
    stage_one = add_markdown_stage(
        store["id"], stage_index=1, discount_pct=0.2, sell_through_target_pct=0.3,
        window_start_date="2026-09-15", window_end_date="2026-09-29",
    )
    stage_two = add_markdown_stage(
        store["id"], stage_index=2, discount_pct=0.4, sell_through_target_pct=0.6,
        window_start_date="2026-09-29", window_end_date="2026-10-13",
    )
    activate_markdown_stage(stage_one["id"])
    before = {
        "store": read_store(store["id"]),
        "engagement": read_engagement(engagement["id"]),
        "summary": _read_summary(engagement["id"]),
    }
    revoked = revoke_license(license_row["id"], revoked_reason=REVOCATION_REASON)
    return {
        "before": before,
        "license": revoked,
        "store": read_store(store["id"]),
        "engagement": read_engagement(engagement["id"]),
        "stage_one": _read_stage(stage_one["id"]),
        "stage_two": _read_stage(stage_two["id"]),
        "summary": _read_summary(engagement["id"]),
    }


class TestLicenseRevocationCascade:
    def test_hop_one_moves_the_licence_and_records_the_mandatory_reason(self):
        """APPROVED to REVOKED with the regulator's reason stored.

        The PRD says: "Hop one moves the licence `APPROVED → REVOKED` and records
        the reason."

        Design: Difficulty/transitive_cascade/license_revoke_five_hop_chain_from_license_to_engagement_shortfall
        """
        scenario = _selling_store_whose_licence_is_revoked()
        license_row = scenario["license"]
        assert_gob_license(license_row)
        assert license_row["license_status"] == "REVOKED"
        assert license_row["revoked_reason"] == REVOCATION_REASON
        assert _read_license(license_row["id"])["license_status"] == "REVOKED"

    def test_hop_two_suspends_the_licensed_store_with_the_licence_reason(self):
        """The store leaves SELLING for SUSPENDED, reason LICENSE_REVOKED.

        The PRD says: "Hop two, caused by hop one, takes the licensed store from
        `SELLING` to `SUSPENDED` with `suspension_reason` set to `LICENSE_REVOKED`."

        Design: Difficulty/transitive_cascade/license_revoke_five_hop_chain_from_license_to_engagement_shortfall
        """
        scenario = _selling_store_whose_licence_is_revoked()
        assert scenario["before"]["store"]["store_status"] == "SELLING"
        store = scenario["store"]
        assert_store(store)
        assert store["store_status"] == "SUSPENDED"
        assert store["suspension_reason"] == "LICENSE_REVOKED"

    def test_hop_three_closes_only_the_active_stage_and_takes_no_checkpoint(self):
        """Stage 1 closes with LICENSE_LOST while the armed successor is untouched.

        The PRD says: "Hop three, caused by the store leaving `SELLING`, closes that
        store's `ACTIVE` markdown stage — `ACTIVE → CLOSED` with `closed_reason` of
        `LICENSE_LOST`, `escalation_applied_pct` of exactly 0.0000, and
        `checkpoint_sell_through_pct` left null, because no checkpoint was taken."

        Design: Difficulty/transitive_cascade/license_revoke_five_hop_chain_from_license_to_engagement_shortfall
        """
        scenario = _selling_store_whose_licence_is_revoked()
        stage_one = scenario["stage_one"]
        assert_markdown_stage(stage_one)
        assert stage_one["stage_status"] == "CLOSED"
        assert stage_one["closed_reason"] == "LICENSE_LOST"
        assert stage_one["escalation_applied_pct"] == pytest.approx(0.0, abs=0.00001)
        assert stage_one["checkpoint_sell_through_pct"] is None
        stage_two = scenario["stage_two"]
        assert stage_two["stage_status"] == "ARMED"
        assert stage_two["closed_reason"] is None

    def test_hop_four_recomputes_the_store_projection_from_the_surviving_stage(self):
        """The planned discount rises to 0.4000 and the projection falls with it.

        The PRD says: "Hop four, caused by that stage leaving the armed-and-active
        set, recomputes the store's `planned_avg_discount_pct`,
        `projected_gross_recovery_cents`, and `projected_recovery_ratio`."

        Design: Difficulty/transitive_cascade/license_revoke_five_hop_chain_from_license_to_engagement_shortfall
        """
        scenario = _selling_store_whose_licence_is_revoked()
        before = scenario["before"]["store"]
        assert before["planned_avg_discount_pct"] == pytest.approx(0.3000, abs=0.00001)
        assert before["projected_gross_recovery_cents"] == 6965000
        store = scenario["store"]
        assert store["planned_avg_discount_pct"] == pytest.approx(0.4000, abs=0.00001)
        assert store["projected_gross_recovery_cents"] == 5970000
        assert store["projected_recovery_ratio"] == pytest.approx(1.1940, abs=0.00001)

    def test_hop_five_widens_the_engagement_shortfall_against_the_guaranty(self):
        """The 7,500,000 guaranty is unmoved, so the shortfall grows to 1,530,000.

        The PRD says: "Hop five, caused by the store's projection moving,
        recomputes the engagement's `projected_gross_recovery_cents` and
        `projected_shortfall_cents`."

        Design: Difficulty/transitive_cascade/license_revoke_five_hop_chain_from_license_to_engagement_shortfall
        """
        scenario = _selling_store_whose_licence_is_revoked()
        before = scenario["before"]["engagement"]
        assert before["projected_gross_recovery_cents"] == 6965000
        assert before["projected_shortfall_cents"] == 535000
        engagement = scenario["engagement"]
        assert_engagement(engagement)
        assert engagement["projected_gross_recovery_cents"] == 5970000
        assert engagement["projected_shortfall_cents"] == 1530000
        assert engagement["guaranty_amount_cents"] == 7500000
        summary = scenario["summary"]
        assert_recovery_summary(summary)
        assert summary["projected_gross_recovery_cents"] == 5970000
        assert summary["projected_recovery_ratio"] == pytest.approx(1.1940, abs=0.00001)
        assert summary["projected_shortfall_cents"] == 1530000
        assert summary["guaranty_amount_cents"] == 7500000

    def test_the_fan_out_records_one_strike_and_restricts_the_engagement(self):
        """A licence lost while the store was selling is a strike, and the first
        strike already restricts.

        The PRD says: "Separately from that chain, as a fan-out rather than a hop,
        the engagement's `compliance_strike_count` increases by 1 and its
        `compliance_posture` is re-derived by the thresholds of §2.8."

        Design: Difficulty/transitive_cascade/license_revoke_five_hop_chain_from_license_to_engagement_shortfall
        """
        scenario = _selling_store_whose_licence_is_revoked()
        before = scenario["before"]["engagement"]
        assert before["compliance_strike_count"] == 0
        assert before["compliance_posture"] == "OPEN"
        engagement = scenario["engagement"]
        assert engagement["compliance_strike_count"] == 1
        assert engagement["compliance_posture"] == "RESTRICTED"
