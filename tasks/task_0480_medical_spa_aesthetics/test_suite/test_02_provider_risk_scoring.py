"""`Provider` risk-scoring tests (§3.8).

The provider's two complication-rate variants share the same denominator
(`committed_session_count`) but differ in numerator: the provisional view counts
open+resolved complications, the settled view counts resolved only. The two
diverge whenever a complication is still open. The PRD describes the variants in
prose but does not name the rate response fields, so these tests pin the
PRD-named count fields that drive the divergence rather than the unnamed rate
fields.
"""
from test_helpers import (
    validate_success,
    make_provider_headers,
    make_clinic_admin_headers,
    setup_open_complication,
    make_injector,
)


def test_provider_counts_diverge_with_open_complication(api):
    """PRD §3.8: "The provisional (live) rate counts both still-open and resolved
    complications — its numerator is `open_complication_count` plus
    `resolved_complication_count` — treating still-open complications as adverse
    pending outcomes, which is the appropriate view before authorizing a new
    session." PRD §3.7: "Opening a case moves the session from `COMMITTED` to
    `COMPLICATION_OPEN`, creates the case in `OPEN` ... and recomputes that
    provider's `open_complication_count`."

    One injector with a committed session and one `OPEN` complication has
    `open_complication_count`==1 but `resolved_complication_count`==0 — the two
    inclusion sets feeding the two rate variants therefore differ.

    Design: Difficulty/dual_variant_calc/provider_complication_rate_provisional_vs_settled_diverges
    """
    sc = setup_open_complication(severity="MODERATE")
    data = validate_success(api.get_provider(
        sc.injector_id, make_provider_headers(sc.injector_id)))
    assert data["committed_session_count"] == 1, (
        f"committed_session_count should be 1, got {data['committed_session_count']}")
    assert data["open_complication_count"] == 1, (
        f"open_complication_count should be 1, got {data['open_complication_count']}")
    assert data["resolved_complication_count"] == 0, (
        f"resolved_complication_count should be 0, got {data['resolved_complication_count']}")


def test_open_complication_counted_separately_from_resolved(api):
    """PRD §3.8: "The settled (credentialing) rate counts only resolved
    complications — its numerator is `resolved_complication_count` alone —
    excluding still-open cases." PRD §3.8: "Because the same inputs feed two
    different inclusion sets, the two rates can differ for the same provider."

    While the case is `OPEN`, `resolved_complication_count` stays 0 even though
    `open_complication_count` is 1 — confirming the settled numerator excludes the
    still-open case.

    Design: Difficulty/dual_variant_calc/provider_complication_rate_provisional_vs_settled_diverges
    """
    sc = setup_open_complication(severity="MODERATE")
    data = validate_success(api.get_provider(
        sc.injector_id, make_provider_headers(sc.injector_id)))
    assert data["open_complication_count"] == 1
    assert data["resolved_complication_count"] == 0, (
        "settled numerator must exclude the still-open complication")


def test_zero_committed_provider_has_zero_counts(api):
    """PRD §3.8: "When `committed_session_count` is 0, the rate is 0 by definition,
    with no division performed." PRD §3.1: "Every provider begins with `status` of
    `ACTIVE`, and the computed counters `open_complication_count`,
    `resolved_complication_count`, and `committed_session_count` all start at 0."

    A freshly registered `INJECTOR` has `committed_session_count`==0 and zero
    complication counts (no division by zero).

    Design: Corner/calculations/provider_complication_rate_zero_committed_boundary
    """
    prov = make_injector(license_number="L-ZERO")
    data = validate_success(api.get_provider(
        prov["id"], make_clinic_admin_headers()))
    assert data["committed_session_count"] == 0, (
        f"committed_session_count should be 0, got {data['committed_session_count']}")
    assert data["open_complication_count"] == 0, (
        f"open_complication_count should be 0, got {data['open_complication_count']}")
    assert data["resolved_complication_count"] == 0
