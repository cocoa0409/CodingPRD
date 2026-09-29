"""Domain thresholds and canonical fixture data drawn from the PRD.

THRESHOLDS holds every numeric policy constant the PRD states.
COMPANIES / EXECUTIVES / METRICS hold the reusable fixture payload bodies so
that expected values stay pinned across the whole suite.
"""

# ---------------------------------------------------------------------------
# Policy thresholds stated by the PRD
# ---------------------------------------------------------------------------
THRESHOLDS = {
    # size banding
    "REVENUE_BAND_LOW": 0.5,
    "REVENUE_BAND_HIGH": 2.0,
    "MCAP_BAND_LOW": 0.25,
    "MCAP_BAND_HIGH": 4.0,
    # benchmark
    "ADJ_FACTOR_LOW": 0.5,
    "ADJ_FACTOR_HIGH": 2.0,
    "PERCENTILE": 0.50,
    # target total direct compensation
    "RATIO_TIER_MID": 0.80,
    "RATIO_TIER_HIGH": 1.20,
    "LTI_MULTIPLE_LOW_TIER": 4.0,
    "LTI_MULTIPLE_MID_TIER": 3.0,
    "LTI_MULTIPLE_HIGH_TIER": 2.0,
    "POSTURE_HIGH": 1.20,
    "POSTURE_LOW": 0.80,
    "BENCHMARK_CAP_MULTIPLE": 1.50,
    # realized / realizable
    "ASSUMED_TARGET_FACTOR_PCT": 100.00,
    # alignment verdict bands
    "ALIGNED_FLOOR": -10.00,
    "WATCH_FLOOR": -30.00,
    # proxy advisor concern score
    "MISALIGN_PIVOT": 50.00,
    "RIGOR_PER_ADJUSTMENT": 25.00,
    "ISS_W_ALIGN": 0.50,
    "ISS_W_MIX": 0.30,
    "ISS_W_RIGOR": 0.20,
    "GL_W_ALIGN": 0.35,
    "GL_W_MIX": 0.15,
    "GL_W_RIGOR": 0.30,
    "GL_W_OUTREACH": 0.20,
    "LEVEL_MEDIUM_FLOOR": 30.00,
    "LEVEL_HIGH_FLOOR": 60.00,
    # goal adjustment
    "ADJUSTMENT_LIMIT_PCT": 15.00,
    # say-on-pay
    "PASS_FLOOR_PCT": 50.00,
    "RESPONSIVENESS_FLOOR_PCT": 70.00,
    # outreach
    "REMEDIATION_COVERAGE_FLOOR_PCT": 30.00,
    "QUIET_PERIOD_DAYS": 10,
    # restatement
    "LOOKBACK_BUFFER_DAYS": 1,
    # pay mix
    "MIX_TOTAL_PCT": 100.00,
    "MIX_COMPONENT_MIN": 5.00,
    "MIX_COMPONENT_MAX": 80.00,
}

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
COLD_START_UTC = "2026-08-01T00:00:00Z"
DEFAULT_MEETING_DATE = "2027-05-12T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination defaults the PRD declares
# ---------------------------------------------------------------------------
PAGINATION = {"default_limit": 10, "min_limit": 1, "max_limit": 100, "default_offset": 0}

# ---------------------------------------------------------------------------
# Canonical company catalogue. ACME is the issuer; the rest are candidate peers.
# ---------------------------------------------------------------------------
COMPANIES = {
    "ACME": {
        "legal_name": "Acme Industries Inc",
        "ticker": "ACME",
        "is_issuer": True,
        "gics_sector": "TECH",
        "revenue_usd": 10000000000,
        "market_cap_usd": 20000000000,
        "share_price_usd": 50.00,
        "ceo_tdc_usd": 15000000,
    },
    "BRVO": {
        "legal_name": "Bravo Corp",
        "ticker": "BRVO",
        "is_issuer": False,
        "gics_sector": "TECH",
        "revenue_usd": 8000000000,
        "market_cap_usd": 16000000000,
        "share_price_usd": 40.00,
        "ceo_tdc_usd": 12000000,
    },
    "CHRL": {
        "legal_name": "Charlie Group",
        "ticker": "CHRL",
        "is_issuer": False,
        "gics_sector": "TECH",
        "revenue_usd": 12000000000,
        "market_cap_usd": 30000000000,
        "share_price_usd": 60.00,
        "ceo_tdc_usd": 18000000,
    },
    "DLTA": {
        "legal_name": "Delta Systems",
        "ticker": "DLTA",
        "is_issuer": False,
        "gics_sector": "TECH",
        "revenue_usd": 20000000000,
        "market_cap_usd": 40000000000,
        "share_price_usd": 80.00,
        "ceo_tdc_usd": 24000000,
    },
    "ECHO": {
        "legal_name": "Echo Holdings",
        "ticker": "ECHO",
        "is_issuer": False,
        "gics_sector": "TECH",
        "revenue_usd": 6000000000,
        "market_cap_usd": 10000000000,
        "share_price_usd": 30.00,
        "ceo_tdc_usd": 9000000,
    },
    "FOXT": {
        "legal_name": "Foxtrot Materials",
        "ticker": "FOXT",
        "is_issuer": False,
        "gics_sector": "TECH",
        "revenue_usd": 4000000000,
        "market_cap_usd": 8000000000,
        "share_price_usd": 20.00,
        "ceo_tdc_usd": 5000000,
    },
    "GOLF": {
        "legal_name": "Golf Energy Partners",
        "ticker": "GOLF",
        "is_issuer": False,
        "gics_sector": "TECH",
        "revenue_usd": 25000000000,
        "market_cap_usd": 50000000000,
        "share_price_usd": 100.00,
        "ceo_tdc_usd": 30000000,
    },
    # Band-edge probes: true revenue ratios 2.00004 and 2.00005 against ACME.
    "GAMM": {
        "legal_name": "Gamma Networks",
        "ticker": "GAMM",
        "is_issuer": False,
        "gics_sector": "TECH",
        "revenue_usd": 20000400000,
        "market_cap_usd": 40000000000,
        "share_price_usd": 80.00,
        "ceo_tdc_usd": 24000000,
    },
    "HOTL": {
        "legal_name": "Hotel Data Corp",
        "ticker": "HOTL",
        "is_issuer": False,
        "gics_sector": "TECH",
        "revenue_usd": 20000500000,
        "market_cap_usd": 40000000000,
        "share_price_usd": 80.00,
        "ceo_tdc_usd": 24000000,
    },
}

# ---------------------------------------------------------------------------
# Canonical executives
# ---------------------------------------------------------------------------
EXECUTIVES = {
    # fixed_leg_usd == 1,200,000 + 1,200,000 * 150.00 / 100 == 3,000,000.00
    "CEO": {
        "full_name": "Dana Reyes",
        "role_title": "CEO",
        "is_neo": True,
        "base_salary_usd": 1200000,
        "sti_target_pct": 150.00,
    },
    # fixed_leg_usd == 800,000 + 800,000 * 100.00 / 100 == 1,600,000.00
    "CFO": {
        "full_name": "Sam Ortiz",
        "role_title": "CFO",
        "is_neo": True,
        "base_salary_usd": 800000,
        "sti_target_pct": 100.00,
    },
    # fixed_leg_usd == 3,000,000 + 3,000,000 * 100.00 / 100 == 6,000,000.00
    "CEO_LARGE": {
        "full_name": "Morgan Vale",
        "role_title": "CEO",
        "is_neo": True,
        "base_salary_usd": 3000000,
        "sti_target_pct": 100.00,
    },
}

# ---------------------------------------------------------------------------
# Canonical pay-mix / program body
# ---------------------------------------------------------------------------
PROGRAM_MIX_15_25_60 = {
    "salary_pct": 15.00,
    "sti_pct": 25.00,
    "lti_pct": 60.00,
    "lti_performance_share_pct": 60.00,
    "sti_max_multiple": 2.0,
    "tsr_percentile_rank": 30.00,
}

# ---------------------------------------------------------------------------
# Canonical incentive-metric goal curves
# ---------------------------------------------------------------------------
METRICS = {
    # HIGHER_IS_BETTER / LINEAR: achievement 5.50 -> payout_factor_pct 150.00
    "ADJ_EPS_LINEAR": {
        "metric_code": "ADJ_EPS",
        "vehicle": "ANNUAL_INCENTIVE",
        "direction": "HIGHER_IS_BETTER",
        "weight_pct": 60.00,
        "threshold_value": 4.00,
        "target_value": 5.00,
        "maximum_value": 6.00,
        "threshold_payout_pct": 50.00,
        "target_payout_pct": 100.00,
        "maximum_payout_pct": 200.00,
        "interpolation": "LINEAR",
    },
    # LOWER_IS_BETTER / STEP: achievement 0.63 -> payout_factor_pct 100.00
    "COST_RATIO_STEP": {
        "metric_code": "COST_RATIO",
        "vehicle": "ANNUAL_INCENTIVE",
        "direction": "LOWER_IS_BETTER",
        "weight_pct": 40.00,
        "threshold_value": 0.70,
        "target_value": 0.65,
        "maximum_value": 0.60,
        "threshold_payout_pct": 50.00,
        "target_payout_pct": 100.00,
        "maximum_payout_pct": 200.00,
        "interpolation": "STEP",
    },
    # HIGHER_IS_BETTER / STEP: achievement 4.50 -> payout_factor_pct 50.00
    "REVENUE_GROWTH_STEP": {
        "metric_code": "REVENUE_GROWTH",
        "vehicle": "ANNUAL_INCENTIVE",
        "direction": "HIGHER_IS_BETTER",
        "weight_pct": 25.00,
        "threshold_value": 4.00,
        "target_value": 5.00,
        "maximum_value": 6.00,
        "threshold_payout_pct": 50.00,
        "target_payout_pct": 100.00,
        "maximum_payout_pct": 200.00,
        "interpolation": "STEP",
    },
    # LOWER_IS_BETTER / LINEAR
    "ROIC_LINEAR": {
        "metric_code": "ROIC",
        "vehicle": "ANNUAL_INCENTIVE",
        "direction": "LOWER_IS_BETTER",
        "weight_pct": 25.00,
        "threshold_value": 0.70,
        "target_value": 0.65,
        "maximum_value": 0.60,
        "threshold_payout_pct": 50.00,
        "target_payout_pct": 100.00,
        "maximum_payout_pct": 200.00,
        "interpolation": "LINEAR",
    },
}

# Reusable free-text bodies
REASONS = {
    "exclusion": "Peer diverged from the issuer's business model after a divestiture.",
    "goal_adjustment": "Divestiture of the payments unit removed 0.75 of budgeted adjusted EPS.",
    "restatement": "Revenue recognition error overstating adjusted EPS.",
    "reversal": "The restatement was withdrawn after the auditor accepted the original revenue treatment.",
    "cda_feedback": "Required tables are missing and the section is under the 1500-word floor.",
    "remediation": "The committee cut the discretionary bonus pool and added a relative TSR modifier.",
}
