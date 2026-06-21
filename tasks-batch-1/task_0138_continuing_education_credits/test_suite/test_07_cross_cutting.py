"""Cross-cutting layers: optimistic concurrency on renew, derived-field
reconciliation after reject, and immediate consistency of earned hours.
"""
import pytest

from test_helpers import (
    validate_error,
    get_success_data,
    ApiErrorId,
    factories as F,
    fixtures as FX,
    make_licensee_headers,
)

ADMIN = FX.ADMIN


def test_occ_stale_renewal_cycle_version_returns_412(api):
    """PRD §2.6: "The server compares it against the cycle's current `version`.
    If a verify cascade, a reciprocity approval, or any other writer has advanced
    the cycle's `version` since the client last read it ... the renew is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_renewal_cycle_version_returns_412
    """
    met = FX.setup_requirements_met_cycle()
    cycle, licensee = met["cycle"], met["licensee"]
    lic = make_licensee_headers(licensee["id"])

    cyc = get_success_data(api.get_renewal_cycle(cycle["id"], lic))
    stale_version = int(cyc["version"]) - 1

    resp = api.renew_cycle(cycle["id"], F.renew_cycle_payload(stale_version), lic)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


def test_provisional_earned_hours_reconciles_after_reject(api):
    """PRD §3.4: "Rejection moves it from `PENDING_VERIFICATION` to `REJECTED`,
    optionally recording a `reason`, recomputes the cycle's provisional tally to
    drop this completion's hours."

    Design: Corner/cross_cutting_complexity_layers/provisional_earned_hours_reconciles_after_reject
    """
    base = FX.setup_board_provider_licensee_cycle(with_requirements=False)
    provider, licensee, cycle = base["provider"], base["licensee"], base["cycle"]
    course = FX.create_course(provider["id"], "ETHICS", 4.0)
    comp = FX.log_completion(licensee["id"], course["id"], cycle["id"])  # provisional 4.0

    get_success_data(api.reject_completion(comp["id"], ADMIN, {"reason": "dup"}))

    cyc = get_success_data(api.get_renewal_cycle(cycle["id"], ADMIN))
    assert float(cyc["provisional_earned_hours"]) == pytest.approx(0.0, abs=0.01), (
        "rejected completion's 4.0h removed")


def test_immediate_consistency_earned_hours_visible_after_verify(api):
    """PRD §2.8: "The system's consistency model is immediate: all derived fields
    and dependent states reflect the new reality before the triggering request
    returns."
    PRD §3.4: "On success the completion moves to `VERIFIED`, the cycle's
    `final_earned_hours` and `provisional_earned_hours` are recomputed."

    Design: Corner/consistency_model/immediate_consistency_earned_hours_visible_in_verify_response_chain
    """
    base = FX.setup_board_provider_licensee_cycle(with_requirements=False)
    provider, licensee, cycle = base["provider"], base["licensee"], base["cycle"]
    course = FX.create_course(provider["id"], "GENERAL", 24.0)
    comp = FX.log_completion(licensee["id"], course["id"], cycle["id"])

    FX.verify_completion(comp["id"])
    # An immediately-following GET reflects the recompute with no lag.
    cyc = get_success_data(api.get_renewal_cycle(cycle["id"], ADMIN))
    assert float(cyc["final_earned_hours"]) == pytest.approx(24.0, abs=0.01), (
        "final_earned_hours updated immediately after verify")
