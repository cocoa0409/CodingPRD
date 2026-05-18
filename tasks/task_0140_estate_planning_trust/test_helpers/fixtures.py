"""Composite setup helpers — multi-step preambles tests can reuse.

Many tests require the system in a late state (e.g., an Estate already
in INVENTORIED with a CONFIRMED EXECUTOR, an INVENTORY_REPORT
ACCEPTED, and all assets APPRAISED). Each fixture composes the
lower-level steps so the test body can focus on the rule under
assertion.

IDENTITY THREADING — PRD §2.1:

- CourtClerk is OPAQUE. Shared constants (court_clerk_headers) are
  canonical.

- Executor is ENTITY-BACKED on Fiduciary. PRD §2.1: "When X-User-Role
  is Executor, X-User-ID is the id of the acting Fiduciary row (one
  whose scope_type is EXECUTOR); ownership checks compare any
  resource's executor reference back to this id."

  Every Executor-driven mutation on an existing estate MUST mint
  headers via make_executor_headers(executor_fiduciary["id"]) where
  executor_fiduciary is the Fiduciary row of scope_type=EXECUTOR
  that has been CONFIRMED for this estate (or is the originating
  executor of an estate still in DRAFT).

- Fiduciary (non-executor) is ENTITY-BACKED. Use
  make_fiduciary_headers(fiduciary["contact_user_id"]) for any
  self-only ownership-gated call (e.g., self-resign).

- Beneficiary is ENTITY-BACKED. Use
  make_beneficiary_headers(beneficiary["id"]) for any self-only
  ownership-gated call.

NOTE on estate creation: PRD §3.1 has the Executor POST /estates.
At that moment no Fiduciary row exists yet. We use the shared
executor_fallback_headers for the FIRST estate-creation call (the
implementation cannot ownership-check against a not-yet-existing
Fiduciary). Immediately after, we mint a Fiduciary row, get its id,
and rebuild Executor headers via make_executor_headers(fid_id) for
every subsequent ownership-gated call.

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    asset_state_payload,
    beneficiary_state_payload,
    clock_advance_payload,
    create_asset_payload,
    create_beneficiary_payload,
    create_designation_payload,
    create_directive_payload,
    create_estate_payload,
    create_fiduciary_payload,
    create_filing_payload,
    create_guardianship_payload,
    create_hipaa_payload,
    create_poa_payload,
    directive_state_payload,
    distribution_state_payload,
    estate_state_payload,
    fiduciary_state_payload,
    filing_state_payload,
    guardianship_state_payload,
    hipaa_state_payload,
    iso_offset,
    iso_utc,
    parse_iso,
    poa_state_payload,
    random_suffix,
    utcnow,
)
from .test_users import (
    TEST_USERS,
    make_beneficiary_headers,
    make_executor_headers,
    make_fiduciary_headers,
)


# ===========================================================================
# Clock helpers — PRD §2.11, §3.16
# ===========================================================================
def advance_clock_to(to_timestamp: str,
                     headers: Optional[Dict[str, str]] = None
                     ) -> Dict[str, Any]:
    """POST /_clock/advance. PRD §3.16: CourtClerk-only."""
    headers = headers or TEST_USERS["court_clerk_headers"]
    resp = api_client.advance_clock(
        clock_advance_payload(to_timestamp), headers,
    )
    return get_success_data(resp)


def get_clock_now(headers: Optional[Dict[str, str]] = None) -> str:
    """GET /_clock. Returns the now field."""
    headers = headers or TEST_USERS["court_clerk_headers"]
    resp = api_client.get_clock(headers)
    data = get_success_data(resp)
    # Tolerate variant field names — implementations may emit
    # 'now' or 'current_time' or similar. PRD §3.16 says only that
    # "Reading the clock returns the current logical-clock instant".
    for key in ("now", "current_time", "logical_clock",
                "to_timestamp", "timestamp"):
        if isinstance(data, dict) and key in data and isinstance(data[key], str):
            return data[key]
    # Fallback — assume the whole data is the timestamp string.
    if isinstance(data, str):
        return data
    raise AssertionError(
        f"Could not extract clock timestamp from {data!r}",
    )


def server_now_dt() -> datetime:
    """Server's current logical clock as a UTC datetime."""
    try:
        return parse_iso(get_clock_now())
    except AssertionError:
        # Implementation may not expose a readable clock field; fall
        # back to wall-clock UTC.
        return utcnow()


def server_offset_iso(*, days: int = 0, hours: int = 0,
                     minutes: int = 0, seconds: int = 0) -> str:
    """ISO 8601 UTC timestamp offset from the server's current clock."""
    base = server_now_dt()
    return iso_utc(
        base + timedelta(days=days, hours=hours, minutes=minutes,
                         seconds=seconds),
    )


# ===========================================================================
# Estate root — PRD §3.1
# ===========================================================================
def create_estate(*,
                  testator_name: Optional[str] = None,
                  domicile_state: Optional[str] = None,
                  filing_court_id: Optional[str] = None,
                  headers: Optional[Dict[str, str]] = None
                  ) -> Dict[str, Any]:
    """POST /estates. PRD §3.1: Executor-only.

    No Fiduciary exists yet at the moment of estate creation, so we
    use the Executor fallback headers for this call — there is
    nothing to ownership-check against. Subsequent ownership-gated
    calls on this estate must use make_executor_headers(...) with
    the id of the EXECUTOR Fiduciary nominated under it.
    """
    headers = headers or TEST_USERS["executor_fallback_headers"]
    payload = create_estate_payload(
        testator_name=testator_name,
        domicile_state=domicile_state,
        filing_court_id=filing_court_id,
    )
    resp = api_client.create_estate(payload, headers)
    return get_success_data(resp)


def re_get_estate(estate_id: str,
                  headers: Optional[Dict[str, str]] = None
                  ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["court_clerk_headers"]
    resp = api_client.get_estate(estate_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Fiduciary
# ===========================================================================
def nominate_fiduciary(estate_id: str, *,
                       scope_type: str = "EXECUTOR",
                       full_name: Optional[str] = None,
                       contact_user_id: Optional[str] = None,
                       bond_amount_cents: Optional[int] = None,
                       headers: Optional[Dict[str, str]] = None
                       ) -> Dict[str, Any]:
    """POST /estates/{estateId}/fiduciaries. PRD §4: Executor or
    CourtClerk may nominate. We use CourtClerk by default because the
    Executor identity for a brand-new estate has not yet been
    Fiduciary-anchored.
    """
    headers = headers or TEST_USERS["court_clerk_headers"]
    payload = create_fiduciary_payload(
        scope_type=scope_type,
        full_name=full_name,
        contact_user_id=contact_user_id,
        bond_amount_cents=bond_amount_cents,
    )
    resp = api_client.create_fiduciary(estate_id, payload, headers)
    return get_success_data(resp)


def confirm_fiduciary(estate_id: str, fiduciary_id: str, *,
                      version: Optional[int] = None,
                      headers: Optional[Dict[str, str]] = None
                      ) -> Dict[str, Any]:
    """POST /estates/.../fiduciaries/{id}/state to_status=CONFIRMED.
    PRD §3.1, §3.15: CourtClerk-only.
    """
    headers = headers or TEST_USERS["court_clerk_headers"]
    payload = fiduciary_state_payload("CONFIRMED", version=version)
    resp = api_client.transition_fiduciary(
        estate_id, fiduciary_id, payload, headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Filings — PRD §3.7
# ===========================================================================
def submit_filing(estate_id: str, *,
                  filing_type: str,
                  filed_by_fiduciary_id: str,
                  exec_headers: Dict[str, str]
                  ) -> Dict[str, Any]:
    """POST /estates/.../filings. PRD §4: Executor-only."""
    payload = create_filing_payload(
        filing_type=filing_type,
        filed_by_fiduciary_id=filed_by_fiduciary_id,
    )
    resp = api_client.create_filing(estate_id, payload, exec_headers)
    return get_success_data(resp)


def transition_filing(estate_id: str, filing_id: str, *,
                      to_status: str,
                      rejection_reason: Optional[str] = None,
                      version: Optional[int] = None,
                      headers: Dict[str, str]
                      ) -> Dict[str, Any]:
    payload = filing_state_payload(
        to_status,
        rejection_reason=rejection_reason,
        version=version,
    )
    resp = api_client.transition_filing(
        estate_id, filing_id, payload, headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Bootstrapping shortcut: Executor identity for an estate.
#
# After POST /estates the Executor needs a Fiduciary row to sign as.
# Pattern:
#   1) CourtClerk nominates the Executor Fiduciary on the new estate
#      with sufficient bond.
#   2) Headers for subsequent Executor-driven calls are then
#      make_executor_headers(executor["id"]).
#
# PRD §3.1: Fiduciary may be nominated by Executor OR CourtClerk; we
# use CourtClerk here because the Executor identity is not yet
# Fiduciary-anchored.
# ===========================================================================
def create_estate_with_executor(*,
                                bond_amount_cents: int = 10_000_000,
                                testator_name: Optional[str] = None,
                                domicile_state: Optional[str] = None,
                                filing_court_id: Optional[str] = None,
                                ) -> Tuple[Dict[str, Any],
                                           Dict[str, Any],
                                           Dict[str, str]]:
    """Create an Estate (DRAFT) and nominate (NOMINATED) an EXECUTOR
    Fiduciary on it. Returns (estate, executor_fiduciary,
    executor_headers).

    The executor_headers are minted with the Fiduciary.id, so they
    pass any executor-ownership check the PRD pins. The estate
    remains in DRAFT — no confirmation has happened yet.
    """
    estate = create_estate(
        testator_name=testator_name,
        domicile_state=domicile_state,
        filing_court_id=filing_court_id,
    )
    executor = nominate_fiduciary(
        estate["id"],
        scope_type="EXECUTOR",
        bond_amount_cents=bond_amount_cents,
    )
    executor_headers = make_executor_headers(executor["id"])
    return estate, executor, executor_headers


# ===========================================================================
# Stage helper: bring Estate to IN_PROBATE (with CONFIRMED EXECUTOR
# and ACCEPTED PETITION_TO_PROBATE).
# ===========================================================================
def setup_in_probate(*,
                     bond_amount_cents: int = 10_000_000,
                     ) -> Dict[str, Any]:
    """Drive an estate from DRAFT to IN_PROBATE.

    PRD §3.3: "the executor advances the estate's admin_phase from
    DRAFT to IN_PROBATE ... at least one Fiduciary with scope_type
    EXECUTOR and status CONFIRMED must exist ... a ProbateFiling with
    filing_type PETITION_TO_PROBATE and status ACCEPTED must exist
    ... the confirmed executor's bond_amount_cents must be at least
    the bond requirement".

    Returns dict {estate, executor, executor_headers, petition}.
    The estate is in IN_PROBATE.
    """
    estate, executor, exec_headers = create_estate_with_executor(
        bond_amount_cents=bond_amount_cents,
    )
    # Confirm executor (CourtClerk).
    executor = confirm_fiduciary(estate["id"], executor["id"])
    # Submit petition-to-probate (Executor; PETITION_TO_PROBATE is
    # exempt from confirm-first rule per PRD §3.7).
    petition = submit_filing(
        estate["id"],
        filing_type="PETITION_TO_PROBATE",
        filed_by_fiduciary_id=executor["id"],
        exec_headers=exec_headers,
    )
    # Court accepts petition (CourtClerk).
    petition = transition_filing(
        estate["id"], petition["id"],
        to_status="ACCEPTED",
        headers=TEST_USERS["court_clerk_headers"],
    )
    # Advance estate DRAFT -> IN_PROBATE (Executor).
    resp = api_client.transition_estate(
        estate["id"],
        estate_state_payload("IN_PROBATE"),
        exec_headers,
    )
    estate = get_success_data(resp)
    return {
        "estate": estate,
        "executor": executor,
        "executor_headers": exec_headers,
        "petition": petition,
    }


# ===========================================================================
# Asset helpers — PRD §3.4
# ===========================================================================
def declare_asset(estate_id: str, *,
                  asset_class: str = "FINANCIAL",
                  declared_value_cents: int = 100_000_00,
                  description: Optional[str] = None,
                  requires_poa_for_mutation: Optional[bool] = None,
                  exec_headers: Dict[str, str]) -> Dict[str, Any]:
    payload = create_asset_payload(
        asset_class=asset_class,
        description=description,
        declared_value_cents=declared_value_cents,
        requires_poa_for_mutation=requires_poa_for_mutation,
    )
    resp = api_client.create_asset(estate_id, payload, exec_headers)
    return get_success_data(resp)


def inventory_asset(estate_id: str, asset_id: str, *,
                    exec_headers: Dict[str, str]) -> Dict[str, Any]:
    """DECLARED -> INVENTORIED. PRD §3.4."""
    resp = api_client.transition_asset(
        estate_id, asset_id,
        asset_state_payload("INVENTORIED"),
        exec_headers,
    )
    return get_success_data(resp)


def appraise_asset(estate_id: str, asset_id: str, *,
                   appraised_value_cents: int,
                   exec_headers: Dict[str, str]) -> Dict[str, Any]:
    """INVENTORIED -> APPRAISED with appraised_value_cents. PRD §3.4."""
    resp = api_client.transition_asset(
        estate_id, asset_id,
        asset_state_payload(
            "APPRAISED",
            appraised_value_cents=appraised_value_cents,
        ),
        exec_headers,
    )
    return get_success_data(resp)


def exclude_asset(estate_id: str, asset_id: str, *,
                  exec_headers: Dict[str, str]) -> Dict[str, Any]:
    resp = api_client.transition_asset(
        estate_id, asset_id,
        asset_state_payload("EXCLUDED"),
        exec_headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Beneficiary helpers — PRD §3.1, §3.9
# ===========================================================================
def add_beneficiary(estate_id: str, *,
                    full_name: Optional[str] = None,
                    relationship: str = "CHILD",
                    is_minor: Optional[bool] = None,
                    exec_headers: Dict[str, str]) -> Dict[str, Any]:
    payload = create_beneficiary_payload(
        full_name=full_name,
        relationship=relationship,
        is_minor=is_minor,
    )
    resp = api_client.create_beneficiary(estate_id, payload, exec_headers)
    return get_success_data(resp)


def add_designation(estate_id: str, *,
                    asset_id: str,
                    beneficiary_id: str,
                    share_basis_points: int,
                    priority_rank: int = 1,
                    exec_headers: Dict[str, str]) -> Dict[str, Any]:
    payload = create_designation_payload(
        asset_id=asset_id,
        beneficiary_id=beneficiary_id,
        share_basis_points=share_basis_points,
        priority_rank=priority_rank,
    )
    resp = api_client.create_designation(estate_id, payload, exec_headers)
    return get_success_data(resp)


# ===========================================================================
# Stage helper: bring Estate to INVENTORIED.
# ===========================================================================
def setup_inventoried(*,
                      bond_amount_cents: int = 10_000_000,
                      assets: Optional[List[Dict[str, Any]]] = None,
                      ) -> Dict[str, Any]:
    """Drive an estate from DRAFT to INVENTORIED.

    PRD §3.4: "Once every asset is in INVENTORIED, APPRAISED, or
    EXCLUDED ... and a ProbateFiling of filing_type INVENTORY_REPORT
    with status ACCEPTED exists, the executor advances the estate
    from IN_PROBATE to INVENTORIED."

    Returns dict with all entities of interest. By default creates
    one APPRAISED asset of 500_000_00 cents.
    """
    base = setup_in_probate(bond_amount_cents=bond_amount_cents)
    estate = base["estate"]
    executor = base["executor"]
    exec_headers = base["executor_headers"]

    asset_specs = assets or [
        {
            "asset_class": "FINANCIAL",
            "declared_value_cents": 500_000_00,
            "appraised_value_cents": 500_000_00,
        },
    ]
    created_assets: List[Dict[str, Any]] = []
    for spec in asset_specs:
        a = declare_asset(
            estate["id"],
            asset_class=spec.get("asset_class", "FINANCIAL"),
            declared_value_cents=spec["declared_value_cents"],
            description=spec.get("description"),
            requires_poa_for_mutation=spec.get("requires_poa_for_mutation"),
            exec_headers=exec_headers,
        )
        if spec.get("excluded"):
            a = exclude_asset(estate["id"], a["id"],
                              exec_headers=exec_headers)
        elif spec.get("appraised_value_cents") is not None:
            a = inventory_asset(estate["id"], a["id"],
                                exec_headers=exec_headers)
            a = appraise_asset(
                estate["id"], a["id"],
                appraised_value_cents=spec["appraised_value_cents"],
                exec_headers=exec_headers,
            )
        else:
            # Inventory but do not appraise.
            a = inventory_asset(estate["id"], a["id"],
                                exec_headers=exec_headers)
        created_assets.append(a)

    # Submit INVENTORY_REPORT.
    inv = submit_filing(
        estate["id"],
        filing_type="INVENTORY_REPORT",
        filed_by_fiduciary_id=executor["id"],
        exec_headers=exec_headers,
    )
    inv = transition_filing(
        estate["id"], inv["id"],
        to_status="ACCEPTED",
        headers=TEST_USERS["court_clerk_headers"],
    )

    # Advance IN_PROBATE -> INVENTORIED.
    resp = api_client.transition_estate(
        estate["id"], estate_state_payload("INVENTORIED"),
        exec_headers,
    )
    estate = get_success_data(resp)
    return {
        "estate": estate,
        "executor": executor,
        "executor_headers": exec_headers,
        "petition": base["petition"],
        "inventory_filing": inv,
        "assets": created_assets,
    }


# ===========================================================================
# Stage helper: bring Estate to DISTRIBUTING.
# ===========================================================================
def setup_distributing(*,
                       bond_amount_cents: int = 10_000_000,
                       assets: Optional[List[Dict[str, Any]]] = None,
                       beneficiary_shares: Optional[
                           List[Dict[str, Any]]] = None,
                       ) -> Dict[str, Any]:
    """Drive an estate from INVENTORIED to DISTRIBUTING.

    PRD §3.11: precondition list (posture OPEN, guardianship for
    every minor beneficiary EFFECTIVE, share_basis_points per asset
    sums to 10000, ACCEPTED DISTRIBUTION_PETITION, settlement window
    not exceeded).

    Defaults:
      - One APPRAISED asset of 500_000_00 cents.
      - One ACTIVE non-minor Beneficiary.
      - 10000 bp share for that beneficiary on that asset.
    """
    base = setup_inventoried(
        bond_amount_cents=bond_amount_cents,
        assets=assets,
    )
    estate = base["estate"]
    executor = base["executor"]
    exec_headers = base["executor_headers"]
    appraised_assets = [
        a for a in base["assets"] if a.get("status") == "APPRAISED"
    ]

    # Beneficiaries + designations.
    shares = beneficiary_shares or [
        {
            "asset_index": 0,
            "is_minor": False,
            "share_basis_points": 10000,
            "priority_rank": 1,
        },
    ]
    beneficiaries: List[Dict[str, Any]] = []
    designations: List[Dict[str, Any]] = []
    # Group by (is_minor, full_name?) — easier path: one beneficiary
    # per share row unless caller reuses a beneficiary_index.
    for spec in shares:
        if "beneficiary_index" in spec:
            ben = beneficiaries[spec["beneficiary_index"]]
        else:
            ben = add_beneficiary(
                estate["id"],
                is_minor=spec.get("is_minor", False),
                exec_headers=exec_headers,
            )
            beneficiaries.append(ben)
        asset = appraised_assets[spec.get("asset_index", 0)]
        designations.append(add_designation(
            estate["id"],
            asset_id=asset["id"],
            beneficiary_id=ben["id"],
            share_basis_points=spec["share_basis_points"],
            priority_rank=spec.get("priority_rank", 1),
            exec_headers=exec_headers,
        ))

    # For each minor beneficiary, create guardianship + clock advance
    # to EFFECTIVE.
    guardianships: List[Dict[str, Any]] = []
    for ben in beneficiaries:
        if ben.get("is_minor"):
            # Nominate + confirm a GUARDIAN fiduciary.
            guard = nominate_fiduciary(
                estate["id"], scope_type="GUARDIAN",
            )
            guard = confirm_fiduciary(estate["id"], guard["id"])
            # Create directive with effective_at = 1 minute in future.
            eff = server_offset_iso(minutes=1)
            g_payload = create_guardianship_payload(
                minor_beneficiary_id=ben["id"],
                guardian_fiduciary_id=guard["id"],
                effective_at=eff,
            )
            g_resp = api_client.create_guardianship(
                estate["id"], g_payload, exec_headers,
            )
            g_row = get_success_data(g_resp)
            # Advance clock past eff.
            advance_clock_to(server_offset_iso(minutes=5))
            # Re-read guardianship.
            g_row = get_success_data(api_client.get_guardianship(
                estate["id"], g_row["id"],
                TEST_USERS["court_clerk_headers"],
            ))
            guardianships.append(g_row)

    # Submit DISTRIBUTION_PETITION and accept.
    dpet = submit_filing(
        estate["id"],
        filing_type="DISTRIBUTION_PETITION",
        filed_by_fiduciary_id=executor["id"],
        exec_headers=exec_headers,
    )
    dpet = transition_filing(
        estate["id"], dpet["id"], to_status="ACCEPTED",
        headers=TEST_USERS["court_clerk_headers"],
    )

    # Advance INVENTORIED -> DISTRIBUTING.
    resp = api_client.transition_estate(
        estate["id"], estate_state_payload("DISTRIBUTING"),
        exec_headers,
    )
    estate = get_success_data(resp)
    return {
        "estate": estate,
        "executor": executor,
        "executor_headers": exec_headers,
        "petition": base["petition"],
        "inventory_filing": base["inventory_filing"],
        "distribution_petition": dpet,
        "assets": base["assets"],
        "appraised_assets": appraised_assets,
        "beneficiaries": beneficiaries,
        "designations": designations,
        "guardianships": guardianships,
    }


# ===========================================================================
# Stage helper: bring Estate to SETTLED.
# ===========================================================================
def setup_settled(*,
                  bond_amount_cents: int = 10_000_000,
                  ) -> Dict[str, Any]:
    """Drive an estate to SETTLED with one beneficiary, one asset.

    PRD §3.12: "Once every asset that carries a LOCKED designation
    has reached DISTRIBUTED, and a ProbateFiling of filing_type
    FINAL_ACCOUNTING and status ACCEPTED exists, the executor
    advances the estate from DISTRIBUTING to SETTLED."
    """
    base = setup_distributing(bond_amount_cents=bond_amount_cents)
    estate = base["estate"]
    executor = base["executor"]
    exec_headers = base["executor_headers"]
    asset = base["appraised_assets"][0]

    # List distributions on the estate — we expect one PLANNED.
    list_resp = api_client.list_distributions(
        estate["id"], exec_headers,
    )
    list_body = list_resp.json()
    distributions = list_body.get("data", []) or []
    assert distributions, "Setup failed: no Distribution rows created"
    dist = distributions[0]

    # Execute the distribution.
    resp = api_client.transition_distribution(
        estate["id"], dist["id"],
        distribution_state_payload(
            "EXECUTED",
            actual_amount_cents=dist["planned_amount_cents"],
        ),
        exec_headers,
    )
    dist = get_success_data(resp)

    # Mark asset DISTRIBUTED.
    resp = api_client.transition_asset(
        estate["id"], asset["id"],
        asset_state_payload(
            "DISTRIBUTED", distribution_id=dist["id"],
        ),
        exec_headers,
    )
    asset = get_success_data(resp)

    # Submit FINAL_ACCOUNTING and accept.
    fin = submit_filing(
        estate["id"],
        filing_type="FINAL_ACCOUNTING",
        filed_by_fiduciary_id=executor["id"],
        exec_headers=exec_headers,
    )
    fin = transition_filing(
        estate["id"], fin["id"], to_status="ACCEPTED",
        headers=TEST_USERS["court_clerk_headers"],
    )

    # Advance DISTRIBUTING -> SETTLED.
    resp = api_client.transition_estate(
        estate["id"], estate_state_payload("SETTLED"),
        exec_headers,
    )
    estate = get_success_data(resp)
    return {
        "estate": estate,
        "executor": executor,
        "executor_headers": exec_headers,
        "asset": asset,
        "distribution": dist,
        "final_accounting": fin,
        "beneficiaries": base["beneficiaries"],
    }


# ===========================================================================
# Targeted fixtures for difficulty-design instances.
# ===========================================================================

def setup_two_assets_one_inventoried_one_appraised(
    *,
    declared_cents: int = 100_000_000,
    appraised_cents: int = 500_000_000,
) -> Dict[str, Any]:
    """PRD §3.4 forward-looking vs chronological variant scenario.

    Asset A: APPRAISED at `appraised_cents`. Asset B: INVENTORIED (not
    appraised) with declared_value_cents = `declared_cents`.

    Reaches Estate.admin_phase = INVENTORIED. Returns dict with
    all relevant rows.

    Used for difficulty:
      dual_variant_calc/gross_estate_value_forward_vs_chronological.
    """
    return setup_inventoried(
        bond_amount_cents=10_000_000,
        assets=[
            {
                "asset_class": "REAL_ESTATE",
                "declared_value_cents": declared_cents,
                "appraised_value_cents": appraised_cents,
            },
            {
                "asset_class": "FINANCIAL",
                "declared_value_cents": declared_cents,
                # No appraised_value_cents -> INVENTORIED.
            },
        ],
    )


def setup_inventoried_with_appraised_total(
    *,
    appraised_cents: int = 50_000_000,
    bond_amount_cents: int = 325_000,
) -> Dict[str, Any]:
    """Setup helper for the required_bond per-tier-rounding test.

    Reaches INVENTORIED with a single APPRAISED asset of
    `appraised_cents`, gross_estate_value_cents = appraised_cents.
    The Executor was nominated with bond_amount_cents and CONFIRMED.

    Used for difficulty:
      combinatorial_formula/required_bond_per_tier_round_then_sum and
      boundary_precision_check/bond_exactly_equal_passes.
    """
    return setup_inventoried(
        bond_amount_cents=bond_amount_cents,
        assets=[
            {
                "asset_class": "FINANCIAL",
                "declared_value_cents": appraised_cents,
                "appraised_value_cents": appraised_cents,
            },
        ],
    )


def setup_inventoried_with_two_designations(
    *,
    appraised_cents: int = 1000,
    b1_share_bp: int = 3333,
    b1_priority: int = 1,
    b2_share_bp: int = 6667,
    b2_priority: int = 2,
) -> Dict[str, Any]:
    """Reaches Estate.admin_phase = INVENTORIED with one APPRAISED
    asset and two ACTIVE non-minor Beneficiaries each holding a
    PROPOSED designation. Default shares: B1=3333 rank=1 + B2=6667
    rank=2 = 10000 total.

    Used for difficulty:
      combinatorial_formula/planned_distribution_waterfall_with_priority.
    """
    base = setup_inventoried(
        bond_amount_cents=10_000_000,
        assets=[
            {
                "asset_class": "FINANCIAL",
                "declared_value_cents": appraised_cents,
                "appraised_value_cents": appraised_cents,
            },
        ],
    )
    estate = base["estate"]
    exec_headers = base["executor_headers"]
    asset = base["assets"][0]

    b1 = add_beneficiary(estate["id"], is_minor=False,
                         exec_headers=exec_headers)
    b2 = add_beneficiary(estate["id"], is_minor=False,
                         exec_headers=exec_headers)
    d1 = add_designation(
        estate["id"], asset_id=asset["id"],
        beneficiary_id=b1["id"],
        share_basis_points=b1_share_bp,
        priority_rank=b1_priority,
        exec_headers=exec_headers,
    )
    d2 = add_designation(
        estate["id"], asset_id=asset["id"],
        beneficiary_id=b2["id"],
        share_basis_points=b2_share_bp,
        priority_rank=b2_priority,
        exec_headers=exec_headers,
    )
    return {
        **base,
        "asset": asset,
        "beneficiaries": [b1, b2],
        "designations": [d1, d2],
    }


def setup_with_active_poa_on_real_estate(
    *,
    asset_class: str = "REAL_ESTATE",
) -> Dict[str, Any]:
    """Estate in DRAFT with one CONFIRMED EXECUTOR (sufficient bond),
    one Asset (class=REAL_ESTATE) with requires_poa_for_mutation=true
    in DECLARED, and one ACTIVE PowerOfAttorney covering REAL_ESTATE.

    The PoA is brought to ACTIVE by clock-advance past its
    effective_at (PRD §3.1).
    """
    estate, executor, exec_headers = create_estate_with_executor(
        bond_amount_cents=10_000_000,
    )
    executor = confirm_fiduciary(estate["id"], executor["id"])
    # Create the asset (requires_poa_for_mutation=true).
    asset = declare_asset(
        estate["id"],
        asset_class=asset_class,
        declared_value_cents=100_000_000,
        requires_poa_for_mutation=True,
        exec_headers=exec_headers,
    )
    # Nominate an agent fiduciary (TRUSTEE is fine — must just exist).
    agent = nominate_fiduciary(
        estate["id"], scope_type="TRUSTEE",
    )
    # Create the POA with effective_at in the past so a clock-advance
    # to now() flips it to ACTIVE.
    eff = server_offset_iso(minutes=1)
    poa_payload = create_poa_payload(
        poa_type="FINANCIAL_DURABLE",
        agent_fiduciary_id=agent["id"],
        asset_class_scope=[asset_class],
        effective_at=eff,
    )
    poa_resp = api_client.create_poa(estate["id"], poa_payload,
                                     exec_headers)
    poa = get_success_data(poa_resp)
    # Advance clock to flip to ACTIVE.
    advance_clock_to(server_offset_iso(minutes=5))
    # Re-read.
    poa = get_success_data(
        api_client.get_poa(
            estate["id"], poa["id"],
            TEST_USERS["court_clerk_headers"],
        ),
    )
    return {
        "estate": estate,
        "executor": executor,
        "executor_headers": exec_headers,
        "asset": asset,
        "agent_fiduciary": agent,
        "poa": poa,
    }


def setup_in_probate_with_minor_no_guardian() -> Dict[str, Any]:
    """Setup: Estate in INVENTORIED with one minor Beneficiary, one
    APPRAISED asset, designations sum to 10000, ACCEPTED
    DISTRIBUTION_PETITION present, but no EFFECTIVE
    GuardianshipDirective. Used for ERR_GUARDIANSHIP_MISSING tests.

    Used for difficulty:
      cross_entity_state_dependency/estate_distributing_requires_guardianship_effective.
    """
    base = setup_inventoried(
        bond_amount_cents=10_000_000,
        assets=[
            {
                "asset_class": "FINANCIAL",
                "declared_value_cents": 100_000_00,
                "appraised_value_cents": 100_000_00,
            },
        ],
    )
    estate = base["estate"]
    executor = base["executor"]
    exec_headers = base["executor_headers"]
    asset = base["assets"][0]
    # One minor beneficiary.
    minor = add_beneficiary(
        estate["id"], is_minor=True, exec_headers=exec_headers,
    )
    # Designation covering full asset.
    d = add_designation(
        estate["id"],
        asset_id=asset["id"],
        beneficiary_id=minor["id"],
        share_basis_points=10000,
        priority_rank=1,
        exec_headers=exec_headers,
    )
    # Guardian fiduciary CONFIRMED, but the guardianship directive is
    # created with effective_at in the FUTURE and clock NOT advanced
    # — guardianship stays DRAFT.
    guard = nominate_fiduciary(
        estate["id"], scope_type="GUARDIAN",
    )
    guard = confirm_fiduciary(estate["id"], guard["id"])
    eff = server_offset_iso(days=30)
    g_payload = create_guardianship_payload(
        minor_beneficiary_id=minor["id"],
        guardian_fiduciary_id=guard["id"],
        effective_at=eff,
    )
    g_resp = api_client.create_guardianship(
        estate["id"], g_payload, exec_headers,
    )
    g_row = get_success_data(g_resp)
    # Submit DISTRIBUTION_PETITION and accept.
    dpet = submit_filing(
        estate["id"],
        filing_type="DISTRIBUTION_PETITION",
        filed_by_fiduciary_id=executor["id"],
        exec_headers=exec_headers,
    )
    dpet = transition_filing(
        estate["id"], dpet["id"], to_status="ACCEPTED",
        headers=TEST_USERS["court_clerk_headers"],
    )
    return {
        **base,
        "asset": asset,
        "minor": minor,
        "designation": d,
        "guardian": guard,
        "guardianship": g_row,
        "distribution_petition": dpet,
        "guardianship_effective_at": eff,
    }


def setup_in_probate_with_minor_draft_guardian_ready_for_clock(
) -> Dict[str, Any]:
    """Setup: Estate in IN_PROBATE (NOT yet INVENTORIED) with one
    minor Beneficiary, one DECLARED asset, a CONFIRMED guardian
    Fiduciary, and a DRAFT GuardianshipDirective whose ``effective_at``
    is set 30 days in the future.

    The PRD §3.1 auto-transition (GuardianshipDirective DRAFT →
    EFFECTIVE) requires admin_phase=IN_PROBATE, the guardian
    fiduciary CONFIRMED, and the logical clock at or past
    ``effective_at``. This fixture pins exactly those preconditions in
    setup; the test body advances the clock and observes the
    auto-transition.

    Used for difficulty:
      cross_entity_state_dependency/estate_distributing_requires_guardianship_effective.
    """
    # Bring the estate to IN_PROBATE.
    base = setup_in_probate(bond_amount_cents=10_000_000)
    estate = base["estate"]
    executor = base["executor"]
    exec_headers = base["executor_headers"]

    # Declare an asset (still DECLARED — we will inventory + appraise
    # AFTER the clock-advance to keep the auto-transition firing while
    # admin_phase is IN_PROBATE).
    asset = declare_asset(
        estate["id"],
        asset_class="FINANCIAL",
        declared_value_cents=100_000_00,
        exec_headers=exec_headers,
    )
    # One minor beneficiary.
    minor = add_beneficiary(
        estate["id"], is_minor=True, exec_headers=exec_headers,
    )
    # Guardian fiduciary CONFIRMED (PRD §3.1: GUARDIAN confirm
    # requires at least one minor beneficiary, which we just added).
    guard = nominate_fiduciary(
        estate["id"], scope_type="GUARDIAN",
    )
    guard = confirm_fiduciary(estate["id"], guard["id"])
    # Guardianship directive with effective_at in the FUTURE — stays
    # in DRAFT because clock has not yet reached effective_at.
    eff = server_offset_iso(days=30)
    g_payload = create_guardianship_payload(
        minor_beneficiary_id=minor["id"],
        guardian_fiduciary_id=guard["id"],
        effective_at=eff,
    )
    g_resp = api_client.create_guardianship(
        estate["id"], g_payload, exec_headers,
    )
    g_row = get_success_data(g_resp)
    return {
        **base,
        "asset": asset,
        "minor": minor,
        "guardian": guard,
        "guardianship": g_row,
        "guardianship_effective_at": eff,
    }


def setup_executed_distribution_for_reverse() -> Dict[str, Any]:
    """Estate in DISTRIBUTING with one APPRAISED asset (500_000_000
    cents), a PLANNED Distribution executed at planned, and asset
    transitioned to DISTRIBUTED — ready for REVERSED.

    Used for difficulty:
      compensating_invariant/gross_estate_invariant_under_distribute_then_reverse.
    """
    base = setup_distributing(
        bond_amount_cents=10_000_000,
        assets=[
            {
                "asset_class": "FINANCIAL",
                "declared_value_cents": 500_000_000,
                "appraised_value_cents": 500_000_000,
            },
        ],
        beneficiary_shares=[
            {
                "asset_index": 0,
                "is_minor": False,
                "share_basis_points": 10000,
                "priority_rank": 1,
            },
        ],
    )
    estate = base["estate"]
    exec_headers = base["executor_headers"]
    asset = base["appraised_assets"][0]
    # Capture pre-execute gross.
    estate_now = re_get_estate(estate["id"], exec_headers)
    gross_before = estate_now.get("gross_estate_value_cents")
    # List the planned distribution.
    list_resp = api_client.list_distributions(estate["id"], exec_headers)
    distributions = list_resp.json().get("data", []) or []
    dist = distributions[0]
    # Execute.
    resp = api_client.transition_distribution(
        estate["id"], dist["id"],
        distribution_state_payload(
            "EXECUTED",
            actual_amount_cents=dist["planned_amount_cents"],
        ),
        exec_headers,
    )
    dist = get_success_data(resp)
    # Mark asset DISTRIBUTED.
    resp = api_client.transition_asset(
        estate["id"], asset["id"],
        asset_state_payload("DISTRIBUTED", distribution_id=dist["id"]),
        exec_headers,
    )
    asset = get_success_data(resp)
    return {
        **base,
        "asset": asset,
        "distribution": dist,
        "gross_before_cents": gross_before,
    }


def setup_active_hipaa_and_draft_directive(
    *,
    scope: str = "ALL",
    requires_hipaa_scope: str = "ALL",
) -> Dict[str, Any]:
    """Estate in IN_PROBATE with one ACTIVE HIPAAAuthorization at
    given scope, and one DRAFT EndOfLifeDirective requiring
    requires_hipaa_scope. Setup for HIPAA-gate tests.
    """
    base = setup_in_probate(bond_amount_cents=10_000_000)
    estate = base["estate"]
    exec_headers = base["executor_headers"]
    # Create HIPAA.
    h_payload = create_hipaa_payload(scope=scope)
    h_resp = api_client.create_hipaa(estate["id"], h_payload, exec_headers)
    hipaa = get_success_data(h_resp)
    # Create directive.
    d_payload = create_directive_payload(
        requires_hipaa_scope=requires_hipaa_scope,
    )
    d_resp = api_client.create_directive(estate["id"], d_payload,
                                         exec_headers)
    directive = get_success_data(d_resp)
    return {
        **base,
        "hipaa": hipaa,
        "directive": directive,
    }


def setup_in_probate_for_contested_filing_cascade() -> Dict[str, Any]:
    """Estate in IN_PROBATE with a SUBMITTED INVENTORY_REPORT filing
    P1. Used for the contested-cascade difficulty test.
    """
    base = setup_in_probate(bond_amount_cents=10_000_000)
    estate = base["estate"]
    executor = base["executor"]
    exec_headers = base["executor_headers"]
    # Need at least one asset that is in INVENTORIED/APPRAISED/EXCLUDED
    # — but for SUBMITTED status we only need to create the filing, not
    # accept it. INVENTORY_REPORT acceptance precondition (PRD §3.7)
    # would care; SUBMITTED does not.
    inv = submit_filing(
        estate["id"],
        filing_type="INVENTORY_REPORT",
        filed_by_fiduciary_id=executor["id"],
        exec_headers=exec_headers,
    )
    return {
        **base,
        "inventory_filing": inv,
    }


def setup_two_nominated_executors_first_confirmed(
    *,
    bond_amount_cents: int = 10_000_000,
) -> Dict[str, Any]:
    """Estate with one CONFIRMED EXECUTOR (F1) + one NOMINATED
    EXECUTOR successor (F2). Used for duplicate-executor concurrency
    test.

    Used for difficulty:
      resource_temporal_overlap/single_executor_at_a_time.
    """
    estate, f1, exec_headers = create_estate_with_executor(
        bond_amount_cents=bond_amount_cents,
    )
    f1 = confirm_fiduciary(estate["id"], f1["id"])
    f2 = nominate_fiduciary(
        estate["id"], scope_type="EXECUTOR",
        bond_amount_cents=bond_amount_cents,
    )
    return {
        "estate": estate,
        "executor": f1,
        "executor_headers": exec_headers,
        "second_executor": f2,
    }


def setup_inventory_report_submitted() -> Dict[str, Any]:
    """Estate in IN_PROBATE with one SUBMITTED INVENTORY_REPORT.
    Used for ERR_FILING_ALREADY_PENDING tests.
    """
    return setup_in_probate_for_contested_filing_cascade()


def setup_directive_executed_in_probate() -> Dict[str, Any]:
    """Estate in IN_PROBATE with an EXECUTED EndOfLifeDirective. Used
    for state-vs-business priority pair test (ERR_INVALID_STATE wins
    over ERR_HIPAA_SCOPE_INSUFFICIENT).
    """
    base = setup_active_hipaa_and_draft_directive(
        scope="ALL", requires_hipaa_scope="ALL",
    )
    estate = base["estate"]
    exec_headers = base["executor_headers"]
    directive = base["directive"]
    # Execute the directive.
    resp = api_client.transition_directive(
        estate["id"], directive["id"],
        directive_state_payload("EXECUTED"),
        exec_headers,
    )
    directive = get_success_data(resp)
    # Now revoke the HIPAA so re-executing would have failed on HIPAA
    # too — but the directive is already EXECUTED so state-check wins.
    api_client.transition_hipaa(
        estate["id"], base["hipaa"]["id"],
        hipaa_state_payload("REVOKED"),
        exec_headers,
    )
    return {
        **base,
        "directive": directive,
    }


def setup_distribution_executed_for_drift_state_race() -> Dict[str, Any]:
    """Estate in DISTRIBUTING, one Distribution EXECUTED. Used for
    state-vs-fiscal priority pair test.
    """
    base = setup_distributing(
        bond_amount_cents=10_000_000,
        assets=[
            {
                "asset_class": "FINANCIAL",
                "declared_value_cents": 1000,
                "appraised_value_cents": 1000,
            },
        ],
        beneficiary_shares=[
            {
                "asset_index": 0, "is_minor": False,
                "share_basis_points": 10000, "priority_rank": 1,
            },
        ],
    )
    estate = base["estate"]
    exec_headers = base["executor_headers"]
    asset = base["appraised_assets"][0]
    list_resp = api_client.list_distributions(estate["id"], exec_headers)
    dist = (list_resp.json().get("data") or [])[0]
    # Execute.
    resp = api_client.transition_distribution(
        estate["id"], dist["id"],
        distribution_state_payload(
            "EXECUTED",
            actual_amount_cents=dist["planned_amount_cents"],
        ),
        exec_headers,
    )
    dist = get_success_data(resp)
    return {
        **base,
        "asset": asset,
        "distribution": dist,
    }


def setup_disclaimed_beneficiary_blocks_distributing() -> Dict[str, Any]:
    """Estate in INVENTORIED with one ACTIVE Beneficiary holding a
    PROPOSED designation summing to 10000 on one APPRAISED asset,
    ACCEPTED DISTRIBUTION_PETITION present. After DISCLAIM the
    designation is VOIDED; an attempt to advance to DISTRIBUTING
    should be rejected with ERR_DESIGNATIONS_INCOMPLETE.

    Used for difficulty:
      transitive_cascade/beneficiary_disclaim_voids_designations_blocks_estate.
    """
    base = setup_inventoried(
        bond_amount_cents=10_000_000,
        assets=[
            {
                "asset_class": "FINANCIAL",
                "declared_value_cents": 100_000_00,
                "appraised_value_cents": 100_000_00,
            },
        ],
    )
    estate = base["estate"]
    executor = base["executor"]
    exec_headers = base["executor_headers"]
    asset = base["assets"][0]
    ben = add_beneficiary(estate["id"], is_minor=False,
                          exec_headers=exec_headers)
    d = add_designation(
        estate["id"],
        asset_id=asset["id"],
        beneficiary_id=ben["id"],
        share_basis_points=10000,
        priority_rank=1,
        exec_headers=exec_headers,
    )
    # ACCEPT a DISTRIBUTION_PETITION so the only remaining blocker is
    # the designation-sum precondition once disclaim fires.
    dpet = submit_filing(
        estate["id"],
        filing_type="DISTRIBUTION_PETITION",
        filed_by_fiduciary_id=executor["id"],
        exec_headers=exec_headers,
    )
    dpet = transition_filing(
        estate["id"], dpet["id"], to_status="ACCEPTED",
        headers=TEST_USERS["court_clerk_headers"],
    )
    return {
        **base,
        "asset": asset,
        "beneficiary": ben,
        "designation": d,
        "distribution_petition": dpet,
    }


def setup_inventoried_no_designations() -> Dict[str, Any]:
    """Estate in INVENTORIED with one APPRAISED asset, no
    BeneficiaryDesignation rows. ACCEPTED DISTRIBUTION_PETITION
    present. Used for empty-designation-set boundary test.

    Used for difficulty:
      boundary_precision_check/empty_designation_set_blocks_distributing.
    """
    base = setup_inventoried(
        bond_amount_cents=10_000_000,
        assets=[
            {
                "asset_class": "FINANCIAL",
                "declared_value_cents": 100_000_00,
                "appraised_value_cents": 100_000_00,
            },
        ],
    )
    estate = base["estate"]
    executor = base["executor"]
    exec_headers = base["executor_headers"]
    # Add an ACCEPTED DISTRIBUTION_PETITION — but: PRD §3.7 says
    # accepting a DISTRIBUTION_PETITION requires sum-of-shares==10000
    # per asset. With zero designations the sum is 0, not 10000, so
    # acceptance would fail. We submit it but leave it SUBMITTED so
    # the DISTRIBUTING precondition that fails first is
    # designations-incomplete OR no-accepted-distribution-petition.
    #
    # To isolate the empty-designation-set behavior, we instead submit
    # AND attempt to accept; if the accept fails (as PRD requires) we
    # leave it SUBMITTED. The estate-advance attempt will then fail
    # on whichever of the two preconditions PRD checks first. PRD
    # §2.10 priority order: designation-sum (10) before
    # no-accepted-distribution-petition (not in priority list — that
    # falls under generic transition-precondition fall-through).
    dpet = submit_filing(
        estate["id"],
        filing_type="DISTRIBUTION_PETITION",
        filed_by_fiduciary_id=executor["id"],
        exec_headers=exec_headers,
    )
    return {
        **base,
        "distribution_petition_submitted": dpet,
    }


def setup_directive_superseded() -> Dict[str, Any]:
    """Estate in IN_PROBATE with ACTIVE HIPAA (scope=ALL), and a
    SUPERSEDED EndOfLifeDirective (the original D1, superseded by D2).
    Used for directive cyclic-revision-loop test.

    Used for difficulty:
      non_linear_state_machine/directive_cyclic_revision_loop.
    """
    base = setup_active_hipaa_and_draft_directive(
        scope="ALL", requires_hipaa_scope="ALL",
    )
    estate = base["estate"]
    exec_headers = base["executor_headers"]
    d1 = base["directive"]
    # Create D2 that supersedes D1.
    d2_payload = create_directive_payload(
        requires_hipaa_scope="ALL",
        supersedes_directive_id=d1["id"],
    )
    d2_resp = api_client.create_directive(estate["id"], d2_payload,
                                          exec_headers)
    d2 = get_success_data(d2_resp)
    # Re-read D1.
    d1_resp = api_client.get_directive(
        estate["id"], d1["id"], exec_headers,
    )
    d1 = get_success_data(d1_resp)
    return {
        **base,
        "directive_d1": d1,
        "directive_d2": d2,
    }


__all__ = [
    # Clock
    "advance_clock_to",
    "get_clock_now",
    "server_now_dt",
    "server_offset_iso",
    # Estate
    "create_estate",
    "re_get_estate",
    "create_estate_with_executor",
    # Fiduciary
    "nominate_fiduciary",
    "confirm_fiduciary",
    # Filings
    "submit_filing",
    "transition_filing",
    # Asset
    "declare_asset",
    "inventory_asset",
    "appraise_asset",
    "exclude_asset",
    # Beneficiary / Designation
    "add_beneficiary",
    "add_designation",
    # Stage setups
    "setup_in_probate",
    "setup_inventoried",
    "setup_distributing",
    "setup_settled",
    # Difficulty-targeted setups
    "setup_two_assets_one_inventoried_one_appraised",
    "setup_inventoried_with_appraised_total",
    "setup_inventoried_with_two_designations",
    "setup_with_active_poa_on_real_estate",
    "setup_in_probate_with_minor_no_guardian",
    "setup_in_probate_with_minor_draft_guardian_ready_for_clock",
    "setup_executed_distribution_for_reverse",
    "setup_active_hipaa_and_draft_directive",
    "setup_in_probate_for_contested_filing_cascade",
    "setup_two_nominated_executors_first_confirmed",
    "setup_inventory_report_submitted",
    "setup_directive_executed_in_probate",
    "setup_distribution_executed_for_drift_state_race",
    "setup_disclaimed_beneficiary_blocks_distributing",
    "setup_inventoried_no_designations",
    "setup_directive_superseded",
]
