"""Domain thresholds and pinned expected values from the PRD calculations."""

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

STARTUP_CLOCK_UTC = "2026-08-01T00:00:00Z"
CLOCK_DURING_INJECTION_YEAR = "2028-02-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Numeric thresholds named by the PRD
# ---------------------------------------------------------------------------

THRESHOLDS = {
    "INJECTION_BUILDUP_COEFFICIENT": 45.0,
    "FRACTURE_MARGIN_FRACTION": 0.90,
    "REFERENCE_SEAL_THICKNESS_M": 30.0,
    "DETERMINISTIC_SAFETY_FACTOR": 1.0,
    "PROBABILISTIC_SAFETY_FACTOR": 1.25,
    "SEAL_PASS_INDEX": 1.500,
    "SEAL_CONDITIONAL_INDEX": 1.000,
    "CO2_DENSITY_KG_PER_M3": 700.0,
    "SWEEP_EFFICIENCY": 0.35,
    "PRESSURE_FRONT_MULTIPLIER": 1.8,
    "WELLBORE_CA_OBLIGATION_RISK": 40.00,
    "WELLBORE_WAIVER_MAX_RISK": 60.00,
    "WELLBORE_BASE_MOBILISATION_USD": 150_000.00,
    "WELLBORE_COST_PER_METRE_USD": 120.00,
    "WELLBORE_COST_PER_RISK_POINT_USD": 2_000.00,
    "MIT_ANNULUS_PRESSURE_LOSS_PASS_MAX_PSI": 3.00,
    "PERMIT_PRESSURE_CEILING_FRACTION": 0.90,
    "MRV_SUBSURFACE_REF_FREQUENCY": 2,
    "MRV_SURFACE_REF_FREQUENCY": 4,
    "MRV_ATMOSPHERIC_REF_FREQUENCY": 12,
    "MRV_SUBSURFACE_REF_DETECTION_TPY": 1000.0,
    "MRV_SURFACE_REF_DETECTION_TPY": 100.0,
    "MRV_ATMOSPHERIC_REF_DETECTION_TPY": 25.0,
    "MRV_SUBSURFACE_WEIGHT": 0.50,
    "MRV_SURFACE_WEIGHT": 0.30,
    "MRV_ATMOSPHERIC_WEIGHT": 0.20,
    "MRV_COVERAGE_MINIMUM": 70.00,
    "MRV_UNCONDITIONED_APPROVAL_SCORE": 85.00,
    "MRV_CONDITIONED_COST_UPLIFT": 1.15,
    "PLUGGING_COST_PER_PERMIT_USD": 850_000.00,
    "EMERGENCY_RESERVE_FLOOR_USD": 2_000_000.00,
    "EMERGENCY_RESERVE_USD_PER_SQ_KM": 500_000.00,
    "ADMIN_FEE_TIER_1_USD": 250_000.00,
    "ADMIN_FEE_TIER_2_USD": 500_000.00,
    "ADMIN_FEE_TIER_3_USD": 900_000.00,
    "ADMIN_FEE_TIER_1_MAX_TPY": 500_000,
    "ADMIN_FEE_TIER_2_MAX_TPY": 1_500_000,
    "CRITICAL_DRAW_FRACTION": 0.25,
    "CREDIT_RATE_TIER_1_USD": 85.00,
    "CREDIT_RATE_TIER_2_USD": 70.00,
    "CREDIT_RATE_TIER_3_USD": 55.00,
    "CREDIT_TIER_1_MAX_TONNES": 500_000,
    "CREDIT_TIER_2_MAX_TONNES": 2_000_000,
    "PISC_DEFAULT_YEARS": 50,
    "PISC_ALTERNATIVE_FLOOR_YEARS": 10,
    "PISC_ALTERNATIVE_CEILING_YEARS": 50,
    "DAYS_PER_YEAR": 365.25,
}

# ---------------------------------------------------------------------------
# Canonical project parameters used by the setups below
# ---------------------------------------------------------------------------

ALPHA_PROJECT = {
    "name": "Alpha Storage Hub",
    "operator_name": "Alpha CCS LLC",
    "basin_code": "ILB-01",
    "total_project_acreage": 4000,
    "requested_annual_injection_rate_tpy": 1000000,
    "annual_monitoring_cost_usd": 200000,
    "required_consent_pct": 60,
    "ca_rig_slots": 2,
}

BRAVO_PROJECT_MINIMAL = {
    "name": "Bravo Storage Hub",
    "operator_name": "Bravo CCS LLC",
    "basin_code": "ILB-02",
    "total_project_acreage": 4000,
    "requested_annual_injection_rate_tpy": 1000000,
    "annual_monitoring_cost_usd": 200000,
}

CHARLIE_PROJECT = {
    "name": "Charlie Storage Hub",
    "operator_name": "Charlie CCS LLC",
    "basin_code": "ILB-03",
    "total_project_acreage": 4000,
    "requested_annual_injection_rate_tpy": 400000,
    "annual_monitoring_cost_usd": 100000,
    "required_consent_pct": 60,
    "ca_rig_slots": 2,
}

# ---------------------------------------------------------------------------
# Canonical geologic model parameters
# ---------------------------------------------------------------------------

M1_MODEL_PARAMS = {
    "model_label": "M1-DET",
    "injection_zone_top_depth_m": 1800,
    "injection_zone_thickness_m": 50,
    "seal_thickness_m": 60,
    "capillary_entry_pressure_psi": 900,
    "p10_seal_thickness_m": 30,
    "p10_capillary_entry_pressure_psi": 700,
    "reservoir_pressure_psi": 3000,
    "fracture_pressure_psi": 4500,
    "permeability_md": 200,
    "porosity_fraction": 0.20,
    "assessment_variant": "DETERMINISTIC",
}

DEFAULT_INJECTION_YEARS = 20

# Derived model outcomes for M1_MODEL_PARAMS against ALPHA_PROJECT.
EXPECTED_MAX_INJECTION_RATE_TPY = 1200000
EXPECTED_EFFECTIVE_INJECTION_RATE_TPY = 1000000
EXPECTED_SEAL_INTEGRITY_INDEX = 1.600
EXPECTED_SEAL_INTEGRITY_INDEX_P10 = 0.498
EXPECTED_PLUME_RADIUS_KM = 1.612
EXPECTED_PRESSURE_FRONT_RADIUS_KM = 2.902
EXPECTED_AOR_RADIUS_KM = 3.0
EXPECTED_MAX_INJECTION_PRESSURE_PSI = 4050.00

# ---------------------------------------------------------------------------
# Canonical monitoring method sets
# ---------------------------------------------------------------------------

MRV_METHODS_SCORE_85 = [
    {
        "domain": "SUBSURFACE",
        "technique": "TIME_LAPSE_SEISMIC",
        "detection_threshold_tpy": 500,
        "frequency_per_year": 2,
        "spatial_coverage_pct": 100,
    },
    {
        "domain": "SURFACE",
        "technique": "SOIL_GAS_FLUX",
        "detection_threshold_tpy": 100,
        "frequency_per_year": 4,
        "spatial_coverage_pct": 80,
    },
    {
        "domain": "ATMOSPHERIC",
        "technique": "EDDY_COVARIANCE",
        "detection_threshold_tpy": 25,
        "frequency_per_year": 12,
        "spatial_coverage_pct": 55,
    },
]

MRV_METHODS_SCORE_70 = [
    {
        "domain": "SUBSURFACE",
        "technique": "TIME_LAPSE_SEISMIC",
        "detection_threshold_tpy": 500,
        "frequency_per_year": 2,
        "spatial_coverage_pct": 100,
    },
    {
        "domain": "SURFACE",
        "technique": "SOIL_GAS_FLUX",
        "detection_threshold_tpy": 100,
        "frequency_per_year": 4,
        "spatial_coverage_pct": 50,
    },
    {
        "domain": "ATMOSPHERIC",
        "technique": "EDDY_COVARIANCE",
        "detection_threshold_tpy": 25,
        "frequency_per_year": 12,
        "spatial_coverage_pct": 25,
    },
]

MRV_METHODS_SCORE_65_NO_ATMOSPHERIC = MRV_METHODS_SCORE_70[:2]

# The same three methods described in free text rather than in code-like labels.
MRV_METHODS_SCORE_70_FREE_TEXT = [
    dict(MRV_METHODS_SCORE_70[0], technique="4D seismic and downhole pressure"),
    dict(MRV_METHODS_SCORE_70[1], technique="soil gas flux survey"),
    dict(MRV_METHODS_SCORE_70[2], technique="tunable diode laser tower"),
]

EXPECTED_COVERAGE_SCORE_85 = 85.00
EXPECTED_COVERAGE_SCORE_70 = 70.00
EXPECTED_COVERAGE_SCORE_65 = 65.00

# ---------------------------------------------------------------------------
# Canonical pore space tracts.  Against a 4000-acre project these three
# executed leases carry secured_acreage to 2400.0000 and therefore
# pore_space_consent_pct to exactly 60.00.
# ---------------------------------------------------------------------------

CANONICAL_TRACT_SPECS = [
    {
        "tract_label": "T1",
        "acreage": 1000,
        "ownership_pct": 33.3333,
        "landowner_user_id": "landowner-1",
    },
    {
        "tract_label": "T2",
        "acreage": 1000,
        "ownership_pct": 66.6667,
        "landowner_user_id": "landowner-2",
    },
    {
        "tract_label": "T3",
        "acreage": 1400,
        "ownership_pct": 100,
        "landowner_user_id": "landowner-3",
    },
]

DEFAULT_BONUS_PER_ACRE_USD = 15.00
DEFAULT_ROYALTY_RATE_PCT = 12.5

# ---------------------------------------------------------------------------
# Legacy wellbore parameter sets, named for the condition they encode
# ---------------------------------------------------------------------------

WELLBORE_SEAL_OPEN_HOLE_NEAR = {
    "distance_from_injector_km": 0.5,
    "total_depth_m": 2000,
    "penetrates_seal": True,
    "plug_condition": "OPEN_HOLE",
    "plug_record_available": False,
}

WELLBORE_PARTIALLY_PLUGGED_MID = {
    "distance_from_injector_km": 1.0,
    "total_depth_m": 1200,
    "penetrates_seal": False,
    "plug_condition": "PARTIALLY_PLUGGED",
    "plug_record_available": False,
}

WELLBORE_CEMENTED_DOCUMENTED_FAR = {
    "distance_from_injector_km": 2.0,
    "total_depth_m": 800,
    "penetrates_seal": False,
    "plug_condition": "CEMENTED",
    "plug_record_available": True,
}

WELLBORE_BEYOND_AOR = {
    "distance_from_injector_km": 5.0,
    "total_depth_m": 1000,
    "penetrates_seal": False,
    "plug_condition": "OPEN_HOLE",
    "plug_record_available": False,
}

WELLBORE_SEAL_CEMENTED_FAR = {
    "distance_from_injector_km": 2.0,
    "total_depth_m": 900,
    "penetrates_seal": True,
    "plug_condition": "CEMENTED",
    "plug_record_available": True,
}

WELLBORE_UNKNOWN_PLUG_MID = {
    "distance_from_injector_km": 1.5,
    "total_depth_m": 1000,
    "penetrates_seal": False,
    "plug_condition": "UNKNOWN",
    "plug_record_available": True,
}

WELLBORE_SEAL_OPEN_HOLE_DEEP_NEAR = {
    "distance_from_injector_km": 0.4,
    "total_depth_m": 2400,
    "penetrates_seal": True,
    "plug_condition": "OPEN_HOLE",
    "plug_record_available": False,
}

# ---------------------------------------------------------------------------
# Canonical permit parameters
# ---------------------------------------------------------------------------

ALPHA_PERMIT = {
    "well_name": "ALPHA-1",
    "casing_program": "LONG_STRING_CEMENTED_TO_SURFACE",
    "corrosion_resistant_material": True,
    "tubing_packer_installed": True,
    "requested_injection_pressure_psi": 4000,
}

# ---------------------------------------------------------------------------
# Canonical financial instrument parameters
# ---------------------------------------------------------------------------

TRUST_FUND_FACE_AMOUNT_USD = 26000000
SURETY_BOND_FACE_AMOUNT_USD = 12500000

# ---------------------------------------------------------------------------
# Canonical lease terms
# ---------------------------------------------------------------------------

LEASE_TERM_START = "2026-09-01T00:00:00Z"
LEASE_TERM_END = "2046-09-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Canonical injection reporting windows
# ---------------------------------------------------------------------------

PERIOD_1_START = "2027-01-01T00:00:00Z"
PERIOD_1_END = "2027-07-01T00:00:00Z"
PERIOD_2_START = "2027-07-01T00:00:00Z"
PERIOD_2_END = "2028-01-01T00:00:00Z"

PERIOD_1_MASS_TONNES = 300000
PERIOD_1_LEAKAGE_TONNES = 500
PERIOD_2_MASS_TONNES = 250000
PERIOD_2_LEAKAGE_TONNES = 0

EXPECTED_PERIOD_1_NET_TONNES = 299500.000
EXPECTED_PERIOD_2_NET_TONNES = 250000.000
EXPECTED_CUMULATIVE_STORED_TONNES = 549500.000

TAX_YEAR = 2027
LCA_UPSTREAM_EMISSIONS_FACTOR = 0.05

# ---------------------------------------------------------------------------
# Non-existent identifiers used for not-found probes
# ---------------------------------------------------------------------------

MISSING_GEOLOGIC_MODEL_ID = "00000000-0000-0000-0000-0000000009ff"
MISSING_CLAIM_ID = "00000000-0000-0000-0000-000000000000"
