"""Domain constants and canonical payload literals drawn from the PRD."""

# ---------------------------------------------------------------------------
# Numeric constants the PRD names outright
# ---------------------------------------------------------------------------
DEPTH_TOLERANCE_IN = 6
PRIOR_OCCUPANCY_CREDIT_PCT = 10
SUBSEQUENT_OCCUPANCY_PENALTY_PCT = 20
PUBLIC_AGENCY_CREDIT_PCT = 25
UNSUPPORTED_CLAIM_PENALTY_PCT = 15
FIELD_CONTRADICTION_PENALTY_PCT = 45
BETTERMENT_RATIO_THRESHOLD = 1.0
RATIO_DECIMALS = 6
TIER_1_CEILING_CENTS = 5_000_000
TIER_2_CEILING_CENTS = 50_000_000
TIER_1_PARTICIPATION_PCT = 100
TIER_2_PARTICIPATION_PCT = 95
TIER_3_PARTICIPATION_PCT = 90
CONTRACTUAL_FLOAT_DAYS = 5
CLEARANCE_WARNING_DAYS = 60
MOBILISATION_BUFFER_DAYS = 3
DELINQUENCY_HOLD_THRESHOLD = 2
MAX_REVISION_ROUNDS = 3
MAX_APPEAL_ROUNDS = 1
MAX_INDIRECT_COST_RATE_PCT = 35

# Cause percentages borne by the utility owner.
DELAY_CAUSE_OWNER_PCT = {
    "UTILITY_OWNER": 100,
    "UTILITY_OWNER_PERMIT_WAIT": 60,
    "THIRD_PARTY": 50,
    "STATE_PERMIT_DELAY": 0,
}

# Base state participation share by occupancy basis (private owner).
BASE_SHARE_BY_BASIS = {
    "FEE_SIMPLE": 100,
    "PRIVATE_EASEMENT": 100,
    "FRANCHISE": 50,
    "PERMIT": 0,
    "UNDOCUMENTED": 0,
}
FRANCHISE_PUBLIC_AGENCY_BASE_SHARE = 0

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# ---------------------------------------------------------------------------
# Fabricated identifiers.  Well formed but never registered.
# ---------------------------------------------------------------------------
ZERO_UUID = "00000000-0000-0000-0000-000000000000"

UNKNOWN_PROJECT_ID = "11111111-1111-4111-8111-111111111101"
UNKNOWN_OWNER_ID = "11111111-1111-4111-8111-111111111102"
UNKNOWN_FACILITY_ID = "11111111-1111-4111-8111-111111111103"
UNKNOWN_INVESTIGATION_ID = "11111111-1111-4111-8111-111111111104"
UNKNOWN_CONFLICT_ID = "11111111-1111-4111-8111-111111111105"
UNKNOWN_DETERMINATION_ID = "11111111-1111-4111-8111-111111111106"
UNKNOWN_PLAN_ID = "11111111-1111-4111-8111-111111111107"
UNKNOWN_PERMIT_ID = "11111111-1111-4111-8111-111111111108"
UNKNOWN_SLOT_ID = "11111111-1111-4111-8111-111111111109"
UNKNOWN_COMMITMENT_ID = "11111111-1111-4111-8111-11111111110a"
UNKNOWN_AGREEMENT_ID = "11111111-1111-4111-8111-11111111110b"
UNKNOWN_DOCUMENT_ID = "11111111-1111-4111-8111-11111111110c"
UNKNOWN_FINDING_ID = "11111111-1111-4111-8111-11111111110d"
UNKNOWN_CLAIM_ID = "11111111-1111-4111-8111-11111111110e"
UNKNOWN_DOCUMENT_ID_ALT = "11111111-1111-4111-8111-11111111110f"

# ---------------------------------------------------------------------------
# Canonical payload literals.  Every design instance builds from these.
# ---------------------------------------------------------------------------
PROJECT_PAYLOAD = {
    "name": "SR-14 Widening Section 3",
    "route_designation": "SR-14",
    "letting_date": "2027-01-15T00:00:00Z",
    "construction_start_date": "2027-03-01T00:00:00Z",
    "construction_end_date": "2028-06-30T00:00:00Z",
    "row_acquisition_year": 1975,
    "reimbursement_authority_cents": 100_000_000,
    "contract_daily_overhead_cents": 250_000,
}

OWNER_PAYLOAD = {
    "legal_name": "Cascade Electric Cooperative",
    "utility_type": "ELECTRIC",
    "is_public_agency": False,
    "indirect_cost_rate_pct": 12.5,
}

FACILITY_PAYLOAD = {
    "facility_type": "BURIED_ELECTRIC",
    "station_begin": 100.0,
    "station_end": 140.0,
    "offset_ft": 12.5,
    "depth_in": 48,
    "material": "PVC duct bank",
    "installed_year": 1968,
    "occupancy_basis": "PRIVATE_EASEMENT",
    "record_source": "AS_BUILT",
}

SECOND_FACILITY_PAYLOAD = {
    "facility_type": "GAS_MAIN",
    "station_begin": 200.0,
    "station_end": 240.0,
    "offset_ft": 14.0,
    "depth_in": 42,
    "material": "Coated steel",
    "installed_year": 1968,
    "occupancy_basis": "FRANCHISE",
    "record_source": "OWNER_ATLAS",
}

THIRD_FACILITY_PAYLOAD = {
    "facility_type": "FIBER_CONDUIT",
    "station_begin": 300.0,
    "station_end": 330.0,
    "offset_ft": 9.0,
    "depth_in": 36,
    "material": "HDPE conduit",
    "installed_year": 1990,
    "occupancy_basis": "PERMIT",
    "record_source": "VERBAL",
}

CONFLICT_PAYLOAD = {
    "conflict_station": 120.0,
    "clearance_deficiency_in": 18,
}

PRIOR_RIGHTS_PAYLOAD = {
    "claimed_basis": "PRIVATE_EASEMENT",
    "narrative": "Recorded private easement predating right-of-way acquisition.",
}

PERMIT_PAYLOAD = {
    "permit_type": "ENCROACHMENT_PERMIT",
    "expires_on": "2028-12-31T00:00:00Z",
}

PLAN_PAYLOAD = {
    "estimated_cost_cents": 40_000_000,
    "replacement_in_kind_cost_cents": 32_000_000,
    "proposed_capacity_ratio": 1.25,
    "work_days": 11,
}

AGREEMENT_NOT_TO_EXCEED_CENTS = 45_000_000

COMMITMENT_PAYLOAD = {
    "window_start": "2027-04-05T00:00:00Z",
    "window_end": "2027-04-20T00:00:00Z",
    "committed_work_days": 11,
    "phase_dependency": "BEFORE_PAVING",
}

# ---------------------------------------------------------------------------
# Derived figures pinned by the canonical literals above.
# ---------------------------------------------------------------------------
# Plan betterment: scope 8,000,000 / 40,000,000 = 0.2 ; capacity (1.25-1)/1.25 = 0.2
# applied to the 0.8 remainder gives 0.16 ; 0.2 + 0.16 = 0.36.
CANON_BETTERMENT_RATIO = 0.36
CANON_BETTERMENT_AMOUNT_CENTS = 14_400_000

# Estimate-basis settlement of the canonical agreement.
CANON_ESTIMATE_ELIGIBLE_CENTS = 40_000_000
CANON_ESTIMATE_INDIRECT_CENTS = 5_000_000
CANON_ESTIMATE_BETTERMENT_CREDIT_CENTS = 14_400_000
CANON_ESTIMATE_NET_ALLOWABLE_CENTS = 30_600_000
CANON_ESTIMATE_PARTICIPATION_TIER_PCT = 95
CANON_ESTIMATE_STATE_SHARE_CENTS = 29_070_000
CANON_ESTIMATE_OWNER_SHARE_CENTS = 1_530_000

# Forward-looking state liability of the canonical conflict at a 100 percent share.
CANON_STATE_LIABILITY_CENTS = 25_600_000

# Canonical commitment window length: 5 April to 20 April with an exclusive end.
CANON_COMMITMENT_DAYS = 15

# ---------------------------------------------------------------------------
# Narrative literals used by action endpoints that require a note.
# ---------------------------------------------------------------------------
CERTIFICATION_NOTE = "Relocation complete, clearance verified in the field."
VOID_REASON = "Owner withdrew from the joint relocation; agreement voided before billing."
CANCELLATION_REASON = "Owner crew reassigned to storm restoration."
COMPLETION_NOTE = "Backfill finished eight days after the committed window."
RELEASE_NOTE = "Owner submitted a corrective schedule; hold released."
CLOSURE_NOTE = "All utility conflicts cleared and agreements settled."
REVISION_NOTE = "Betterment split is not documented."
RETURN_NOTE = "Search the county archive before issuing."
APPEAL_NOTE = "Owner appeals the assigned participation share."
AS_BUILT_REFERENCE = "AB-SR14-003-REV-C"

__all__ = [name for name in dir() if not name.startswith("_")]
