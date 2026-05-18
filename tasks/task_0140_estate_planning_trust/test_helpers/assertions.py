"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the
PRD contract.

PRD §2.4: every persisted resource carries id + created_at +
updated_at + version EXCEPT BeneficiaryDesignation, which is
append-only and carries ONLY id + created_at.
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    ASSET_CLASSES,
    ASSET_STATUSES,
    BENEFICIARY_STATUSES,
    DESIGNATION_STATUSES,
    DIRECTIVE_STATUSES,
    DIRECTIVE_TYPES,
    DISTRIBUTION_STATUSES,
    ESTATE_ADMIN_PHASES,
    FIDUCIARY_STATUSES,
    FILING_STATUSES,
    FILING_TYPES,
    GUARDIANSHIP_STATUSES,
    HIPAA_SCOPES,
    HIPAA_STATUSES,
    POA_STATUSES,
    POA_TYPES,
    PROBATE_POSTURES,
    RELATIONSHIPS,
    SCOPE_TYPES,
)


# ---------------------------------------------------------------------------
# Common-fields predicates — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: every persisted mutable resource carries
    updated_at and a version integer that begins at 1 and increments
    by exactly 1 on every mutation.
    """
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got "
        f"{data.get('version')!r}"
    )


def assert_version_incremented_by_one(new_version: int,
                                      old_version: int) -> None:
    """PRD §2.4: 'a version integer that begins at 1 and increments
    by exactly 1 on every mutation'."""
    assert new_version == old_version + 1, (
        f"Version must increment by exactly 1: "
        f"{old_version} -> {new_version}"
    )


# ---------------------------------------------------------------------------
# Estate — PRD §3.1, §2.8
# ---------------------------------------------------------------------------
def assert_estate(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("testator_name"), str)
    assert data["testator_name"]
    ds = data.get("domicile_state")
    assert isinstance(ds, str) and len(ds) == 2, (
        f"domicile_state must be 2-letter US state code, got {ds!r}"
    )
    assert isinstance(data.get("filing_court_id"), str)
    assert data.get("admin_phase") in ESTATE_ADMIN_PHASES, (
        f"admin_phase must be one of {ESTATE_ADMIN_PHASES}, "
        f"got {data.get('admin_phase')!r}"
    )
    assert data.get("probate_posture") in PROBATE_POSTURES, (
        f"probate_posture must be one of {PROBATE_POSTURES}, "
        f"got {data.get('probate_posture')!r}"
    )
    # gross_estate_value_cents / net_estate_value_cents — non-negative
    # integer cents when present.
    for fld in ("gross_estate_value_cents", "net_estate_value_cents"):
        v = data.get(fld)
        if v is not None:
            assert isinstance(v, int) and v >= 0, (
                f"{fld} must be non-negative integer, got {v!r}"
            )


# ---------------------------------------------------------------------------
# Asset — PRD §3.1, §3.4
# ---------------------------------------------------------------------------
def assert_asset(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("estate_id"), str)
    assert data.get("asset_class") in ASSET_CLASSES, (
        f"asset_class must be one of {ASSET_CLASSES}, "
        f"got {data.get('asset_class')!r}"
    )
    assert isinstance(data.get("description"), str)
    dv = data.get("declared_value_cents")
    assert isinstance(dv, int) and dv >= 0, (
        f"declared_value_cents must be non-negative integer, got {dv!r}"
    )
    av = data.get("appraised_value_cents")
    assert av is None or (isinstance(av, int) and av >= 0), (
        f"appraised_value_cents must be non-negative int or null, "
        f"got {av!r}"
    )
    assert data.get("status") in ASSET_STATUSES, (
        f"status must be one of {ASSET_STATUSES}, "
        f"got {data.get('status')!r}"
    )
    # PRD §3.1: optional flag, default false.
    if "requires_poa_for_mutation" in data:
        assert isinstance(data["requires_poa_for_mutation"], bool)


# ---------------------------------------------------------------------------
# Beneficiary — PRD §3.1, §3.9
# ---------------------------------------------------------------------------
def assert_beneficiary(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("estate_id"), str)
    assert isinstance(data.get("full_name"), str)
    assert data["full_name"]
    assert data.get("relationship") in RELATIONSHIPS, (
        f"relationship must be one of {RELATIONSHIPS}, "
        f"got {data.get('relationship')!r}"
    )
    if "is_minor" in data:
        assert isinstance(data["is_minor"], bool)
    assert data.get("status") in BENEFICIARY_STATUSES, (
        f"status must be one of {BENEFICIARY_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# BeneficiaryDesignation — PRD §2.4, §3.6
# ---------------------------------------------------------------------------
def assert_designation(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'BeneficiaryDesignation is the single append-only
    allocation record in the model: its rows carry only id and
    created_at — updated_at and version are absent.'
    """
    _assert_id_and_created_at(data)
    # Append-only: updated_at and version must NOT appear (or must be
    # explicit null/absent). The PRD wording forbids them.
    assert (
        "updated_at" not in data or data.get("updated_at") is None
    ), "BeneficiaryDesignation must NOT carry updated_at per PRD §2.4"
    assert (
        "version" not in data or data.get("version") is None
    ), "BeneficiaryDesignation must NOT carry version per PRD §2.4"
    assert isinstance(data.get("estate_id"), str)
    assert isinstance(data.get("asset_id"), str)
    assert isinstance(data.get("beneficiary_id"), str)
    sbp = data.get("share_basis_points")
    assert isinstance(sbp, int) and 0 <= sbp <= 10000, (
        f"share_basis_points must be integer in [0, 10000], got {sbp!r}"
    )
    pr = data.get("priority_rank")
    assert isinstance(pr, int), (
        f"priority_rank must be integer, got {pr!r}"
    )
    assert data.get("status") in DESIGNATION_STATUSES, (
        f"status must be one of {DESIGNATION_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# Fiduciary — PRD §3.1
# ---------------------------------------------------------------------------
def assert_fiduciary(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("estate_id"), str)
    assert data.get("scope_type") in SCOPE_TYPES, (
        f"scope_type must be one of {SCOPE_TYPES}, "
        f"got {data.get('scope_type')!r}"
    )
    assert isinstance(data.get("full_name"), str)
    assert isinstance(data.get("contact_user_id"), str)
    assert data.get("status") in FIDUCIARY_STATUSES, (
        f"status must be one of {FIDUCIARY_STATUSES}, "
        f"got {data.get('status')!r}"
    )
    ba = data.get("bond_amount_cents")
    assert ba is None or (isinstance(ba, int) and ba >= 0), (
        f"bond_amount_cents must be non-negative int or null, got {ba!r}"
    )


# ---------------------------------------------------------------------------
# GuardianshipDirective — PRD §3.1
# ---------------------------------------------------------------------------
def assert_guardianship(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("estate_id"), str)
    assert isinstance(data.get("minor_beneficiary_id"), str)
    assert isinstance(data.get("guardian_fiduciary_id"), str)
    assert isinstance(data.get("effective_at"), str)
    assert data.get("status") in GUARDIANSHIP_STATUSES, (
        f"status must be one of {GUARDIANSHIP_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# HIPAAAuthorization — PRD §3.1, §3.13
# ---------------------------------------------------------------------------
def assert_hipaa(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("estate_id"), str)
    assert isinstance(data.get("authorized_recipient"), str)
    assert data.get("scope") in HIPAA_SCOPES, (
        f"scope must be one of {HIPAA_SCOPES}, "
        f"got {data.get('scope')!r}"
    )
    assert isinstance(data.get("signed_at"), str)
    assert data.get("status") in HIPAA_STATUSES, (
        f"status must be one of {HIPAA_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# PowerOfAttorney — PRD §3.1
# ---------------------------------------------------------------------------
def assert_poa(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("estate_id"), str)
    assert data.get("poa_type") in POA_TYPES, (
        f"poa_type must be one of {POA_TYPES}, "
        f"got {data.get('poa_type')!r}"
    )
    assert isinstance(data.get("agent_fiduciary_id"), str)
    assert isinstance(data.get("asset_class_scope"), list)
    assert isinstance(data.get("effective_at"), str)
    assert data.get("status") in POA_STATUSES, (
        f"status must be one of {POA_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# EndOfLifeDirective — PRD §3.1, §3.13
# ---------------------------------------------------------------------------
def assert_directive(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("estate_id"), str)
    assert data.get("directive_type") in DIRECTIVE_TYPES, (
        f"directive_type must be one of {DIRECTIVE_TYPES}, "
        f"got {data.get('directive_type')!r}"
    )
    assert isinstance(data.get("instructions"), str)
    assert data.get("requires_hipaa_scope") in HIPAA_SCOPES, (
        f"requires_hipaa_scope must be one of {HIPAA_SCOPES}, "
        f"got {data.get('requires_hipaa_scope')!r}"
    )
    assert data.get("status") in DIRECTIVE_STATUSES, (
        f"status must be one of {DIRECTIVE_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# ProbateFiling — PRD §3.7
# ---------------------------------------------------------------------------
def assert_filing(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("estate_id"), str)
    assert data.get("filing_type") in FILING_TYPES, (
        f"filing_type must be one of {FILING_TYPES}, "
        f"got {data.get('filing_type')!r}"
    )
    assert isinstance(data.get("filed_by_fiduciary_id"), str)
    assert data.get("status") in FILING_STATUSES, (
        f"status must be one of {FILING_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# Distribution — PRD §3.11
# ---------------------------------------------------------------------------
def assert_distribution(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("estate_id"), str)
    assert isinstance(data.get("beneficiary_id"), str)
    pa = data.get("planned_amount_cents")
    assert isinstance(pa, int) and pa >= 0, (
        f"planned_amount_cents must be non-negative int, got {pa!r}"
    )
    aa = data.get("actual_amount_cents")
    assert aa is None or (isinstance(aa, int) and aa >= 0), (
        f"actual_amount_cents must be non-negative int or null, got {aa!r}"
    )
    assert data.get("status") in DISTRIBUTION_STATUSES, (
        f"status must be one of {DISTRIBUTION_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# Bond calculation helper — PRD §3.5 banker's-round-per-tier-then-sum
# ---------------------------------------------------------------------------
def banker_round_to_cent(amount: float) -> int:
    """PRD §3.5: 'each per-tier product is rounded to the nearest cent
    using banker's rounding (round half to even)'.

    Python's built-in round() uses banker's rounding for ties.
    """
    # Use Decimal to avoid float drift on x.5 values, then banker's
    # round via round().
    from decimal import Decimal, ROUND_HALF_EVEN
    d = Decimal(str(amount))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))


def compute_required_bond_cents(gross_estate_value_cents: int) -> int:
    """Mirror of PRD §3.5 calculation: per-tier banker's round, sum,
    then add unrounded flat fee.

    PRD §3.5: 'For each tier the corresponding cents portion is
    multiplied by its rate and the result is rounded to the nearest
    cent using banker's rounding (round half to even); the three
    rounded per-tier cent amounts are then summed; finally a flat fee
    of 25,000 cents is added unrounded.'
    """
    from .constants import (
        FLAT_BOND_FEE_CENTS,
        TIER1_LIMIT_CENTS,
        TIER1_RATE,
        TIER2_LIMIT_CENTS,
        TIER2_RATE,
        TIER3_RATE,
    )
    g = max(0, int(gross_estate_value_cents))
    tier1_portion = min(g, TIER1_LIMIT_CENTS)
    tier2_portion = max(0, min(g, TIER2_LIMIT_CENTS) - TIER1_LIMIT_CENTS)
    tier3_portion = max(0, g - TIER2_LIMIT_CENTS)
    t1 = banker_round_to_cent(tier1_portion * TIER1_RATE)
    t2 = banker_round_to_cent(tier2_portion * TIER2_RATE)
    t3 = banker_round_to_cent(tier3_portion * TIER3_RATE)
    return t1 + t2 + t3 + FLAT_BOND_FEE_CENTS


__all__ = [
    "assert_version_incremented_by_one",
    "assert_estate",
    "assert_asset",
    "assert_beneficiary",
    "assert_designation",
    "assert_fiduciary",
    "assert_guardianship",
    "assert_hipaa",
    "assert_poa",
    "assert_directive",
    "assert_filing",
    "assert_distribution",
    "banker_round_to_cent",
    "compute_required_bond_cents",
]
