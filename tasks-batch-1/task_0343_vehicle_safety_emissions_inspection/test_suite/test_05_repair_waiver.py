"""Failed emissions: the repair-cost ledger and waiver approval.

Covers Difficulty queue: dual_variant_calc (documented-only vs documented+estimated
qualifying spend), boundary_precision_check (qualifying spend exactly at limit
approves), priority_pair_validation_conflict (invalid-state beats repair-limit on a
waiver decide). Covers Corner queue: calculations (qualifying-spend input filtering).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    get_success_data, ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as F

SM = TEST_USERS["station_manager_headers"]
INSP = TEST_USERS["inspector_headers"]
RECEP = TEST_USERS["receptionist_headers"]


# ===========================================================================
# Difficulty: dual_variant_calc — documented-only vs documented+estimated
# ===========================================================================
def test_qualifying_spend_diverges_by_cost_basis(api):
    """PRD §3.7: "Under the `DOCUMENTED_ONLY` basis the qualifying spend is exactly
    that documented total. Under the `DOCUMENTED_PLUS_ESTIMATED` basis the system
    additionally sums `estimated_cost_cents` across the same eligible orders and the
    qualifying spend is the documented total plus the estimated total — a basis that
    can cross the limit on the very same repair set that the documented-only basis
    falls short on."
    PRD §3.7: "It returns `documented_only_spend_cents` and
    `documented_plus_estimated_spend_cents`, the station's `repair_cost_limit_cents`,
    and two booleans, `eligible_documented_only` and
    `eligible_documented_plus_estimated`, each true exactly when the corresponding
    spend reaches the limit."

    Design: Difficulty/dual_variant_calc/repair_spend_documented_only_vs_documented_plus_estimated
    """
    # limit 60000; two VERIFIED emissions repairs: #1 doc 30000, #2 doc 25000 + est 10000.
    station, profile, lane, appt, failed = F.setup_failed_emissions_record(
        api, clock_iso="2026-06-10T09:00:00Z", repair_cost_limit_cents=60000)
    F.submit_and_verify_repair(api, failed["id"], documented_cost_cents=30000,
                               estimated_cost_cents=0, emissions_related=True, shop_name="Acme Auto")
    F.submit_and_verify_repair(api, failed["id"], documented_cost_cents=25000,
                               estimated_cost_cents=10000, emissions_related=True, shop_name="Beta Auto")
    data = validate_success(api.get_waiver_eligibility(failed["id"], SM), 200)
    assert data["documented_only_spend_cents"] == 55000, \
        f"documented-only must be 30000+25000=55000, got {data['documented_only_spend_cents']}"
    assert data["documented_plus_estimated_spend_cents"] == 65000, \
        f"documented+estimated must be 55000+10000=65000, got {data['documented_plus_estimated_spend_cents']}"
    assert data["eligible_documented_only"] is False, "55000 < 60000 must be ineligible"
    assert data["eligible_documented_plus_estimated"] is True, "65000 >= 60000 must be eligible"


def test_documented_plus_estimated_basis_approves_when_documented_only_fails(api):
    """PRD §3.8: "it requires that the qualifying repair spend computed under the
    request's claimed `cost_basis` be greater than or equal to the station's
    `repair_cost_limit_cents`."
    PRD §3.8: "On approval the system freezes `qualifying_spend_cents` to the
    computed amount and advances `REQUESTED → APPROVED`, which unblocks a later
    reinspection-and-decide to pass with `waiver_applied` true."

    Design: Difficulty/dual_variant_calc/repair_spend_documented_only_vs_documented_plus_estimated
    """
    station, profile, lane, appt, failed = F.setup_failed_emissions_record(
        api, clock_iso="2026-06-10T09:00:00Z", repair_cost_limit_cents=60000)
    F.submit_and_verify_repair(api, failed["id"], documented_cost_cents=30000,
                               estimated_cost_cents=0, emissions_related=True)
    F.submit_and_verify_repair(api, failed["id"], documented_cost_cents=25000,
                               estimated_cost_cents=10000, emissions_related=True)
    waiver = F.request_waiver(api, failed["id"], cost_basis="DOCUMENTED_PLUS_ESTIMATED")
    decided = validate_success(
        api.decide_waiver_request(waiver["id"], {"decision": "APPROVE"}, SM), 200)
    assert decided["status"] == "APPROVED"
    assert decided["qualifying_spend_cents"] == 65000, \
        f"frozen qualifying spend must be 65000, got {decided['qualifying_spend_cents']}"


# ===========================================================================
# Corner: calculations — qualifying spend excludes non-verified/non-emissions
# ===========================================================================
def test_qualifying_spend_excludes_non_verified_and_non_emissions_repairs(api):
    """PRD §3.7: "The system first selects the eligible orders: those whose
    `record_id` is the record, whose `emissions_related` is true, and whose `status`
    is `VERIFIED`. Submitted and rejected orders never count."

    Design: Corner/calculations/qualifying_spend_excludes_non_verified_and_non_emissions_repairs
    """
    station, profile, lane, appt, failed = F.setup_failed_emissions_record(
        api, clock_iso="2026-06-10T09:00:00Z", repair_cost_limit_cents=60000)
    # SUBMITTED (unverified) emissions repair — excluded.
    F.submit_repair_order(api, failed["id"], shop_name="Unverified Shop",
                          documented_cost_cents=40000, estimated_cost_cents=0,
                          emissions_related=True)
    # VERIFIED but non-emissions repair — excluded.
    F.submit_and_verify_repair(api, failed["id"], documented_cost_cents=40000,
                               estimated_cost_cents=0, emissions_related=False,
                               shop_name="NonEmissions Shop")
    data = validate_success(api.get_waiver_eligibility(failed["id"], SM), 200)
    assert data["documented_only_spend_cents"] == 0, \
        f"neither repair qualifies, so spend must be 0, got {data['documented_only_spend_cents']}"
    assert data["eligible_documented_only"] is False


# ===========================================================================
# Difficulty: boundary_precision_check — qualifying spend exactly at limit
# ===========================================================================
def test_waiver_qualifying_spend_exactly_at_limit_approves(api):
    """PRD §3.7: "A vehicle is waiver-eligible under a basis precisely when its
    qualifying spend computed that way is greater than or equal to the station's
    `repair_cost_limit_cents`."

    Design: Difficulty/boundary_precision_check/waiver_qualifying_spend_exactly_at_limit_passes
    """
    station, profile, lane, appt, failed = F.setup_failed_emissions_record(
        api, clock_iso="2026-06-10T09:00:00Z", repair_cost_limit_cents=60000)
    F.submit_and_verify_repair(api, failed["id"], documented_cost_cents=60000,
                               estimated_cost_cents=0, emissions_related=True, shop_name="Exact Auto")
    waiver = F.request_waiver(api, failed["id"], cost_basis="DOCUMENTED_ONLY")
    decided = validate_success(
        api.decide_waiver_request(waiver["id"], {"decision": "APPROVE"}, SM), 200)
    assert decided["status"] == "APPROVED", "spend == limit must approve (>= boundary)"
    assert decided["qualifying_spend_cents"] == 60000


def test_waiver_below_limit_denied_with_repair_limit_not_met(api):
    """PRD §3.8: "If the spend is below the limit the approval is rejected with
    `ERR_REPAIR_LIMIT_NOT_MET`."

    Design: Difficulty/boundary_precision_check/waiver_qualifying_spend_exactly_at_limit_passes
    """
    # One cent below the limit: 59999 < 60000.
    station, profile, lane, appt, failed = F.setup_failed_emissions_record(
        api, clock_iso="2026-06-10T09:00:00Z", repair_cost_limit_cents=60000)
    F.submit_and_verify_repair(api, failed["id"], documented_cost_cents=59999,
                               estimated_cost_cents=0, emissions_related=True)
    waiver = F.request_waiver(api, failed["id"], cost_basis="DOCUMENTED_ONLY")
    validate_error(api.decide_waiver_request(waiver["id"], {"decision": "APPROVE"}, SM),
                   ApiErrorId.ERR_REPAIR_LIMIT_NOT_MET.value)


# ===========================================================================
# Difficulty: priority_pair_validation_conflict — state(5) beats fiscal(15)
# ===========================================================================
def test_decide_already_denied_waiver_returns_invalid_state_not_repair_limit(api):
    """PRD §2.9: "State legality is fifth: attempting a transition from a state in
    which it is not defined yields `ERR_INVALID_STATE`."
    PRD §2.9: "Only after all of these pass does the system evaluate the
    operation-specific business rules described in §3."
    PRD §3.8: "both terminal states are reached only from `REQUESTED`; deciding a
    request not in `REQUESTED` is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_repair_limit_on_waiver_decide
    """
    # Emissions-FAILED record; waiver DENIED first (spend 0, below the 60000 limit).
    station, profile, lane, appt, failed = F.setup_failed_emissions_record(
        api, clock_iso="2026-06-10T09:00:00Z", repair_cost_limit_cents=60000)
    waiver = F.request_waiver(api, failed["id"], cost_basis="DOCUMENTED_ONLY")
    get_success_data(api.decide_waiver_request(waiver["id"], {"decision": "DENY"}, SM))
    # Re-deciding (APPROVE) a DENIED request: state precondition outranks fiscal check.
    validate_error(api.decide_waiver_request(waiver["id"], {"decision": "APPROVE"}, SM),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_requested_waiver_below_limit_reaches_fiscal_repair_limit_check(api):
    """PRD §3.8: "it requires that the qualifying repair spend computed under the
    request's claimed `cost_basis` be greater than or equal to the station's
    `repair_cost_limit_cents`. If the spend is below the limit the approval is
    rejected with `ERR_REPAIR_LIMIT_NOT_MET`."
    PRD §2.9: "Only after all of these pass does the system evaluate the
    operation-specific business rules described in §3."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_repair_limit_on_waiver_decide
    """
    # Waiver is still in REQUESTED (state gate passes), spend 0 below the 60000 limit:
    # the fiscal rule is the one that fires, confirming ERR_INVALID_STATE above came
    # specifically from the state gate pre-empting this fiscal gate.
    station, profile, lane, appt, failed = F.setup_failed_emissions_record(
        api, clock_iso="2026-06-10T09:00:00Z", repair_cost_limit_cents=60000)
    waiver = F.request_waiver(api, failed["id"], cost_basis="DOCUMENTED_ONLY")
    validate_error(api.decide_waiver_request(waiver["id"], {"decision": "APPROVE"}, SM),
                   ApiErrorId.ERR_REPAIR_LIMIT_NOT_MET.value)
