/**
 * Domain constants and thresholds used throughout the test suite.
 * These values are derived from the PRD business logic.
 */

export const BUSINESS_THRESHOLDS = {
  /** Bio-risk threshold: resource usage above this triggers high-biorisk flag */
  BIO_RISK_MINUTES: 6000,
  
  /** Sterilization buffer required between different procedure types on same resource */
  STERILIZATION_BUFFER_MINUTES: 30,
  
  /** Maximum safety score allowed without override */
  SAFETY_SCORE_MAX_WITHOUT_OVERRIDE: 450,
  
  /** Hard safety score threshold (cannot exceed even with override) */
  SAFETY_SCORE_HARD_LIMIT: 500,
  
  /** Penalty added to safety score for high bio-risk assignments */
  HIGH_BIORISK_PENALTY: 50,
  
  /** Penalty added to safety score when using protocol override */
  PROTOCOL_OVERRIDE_PENALTY: 100,
} as const;

/**
 * Cost calculation multiplier for high bio-risk assignments.
 * High-biorisk assignments have their cost doubled (2x).
 */
export const HIGH_BIORISK_COST_MULTIPLIER = 2;

/**
 * Common non-existent UUID used for testing 404 scenarios.
 */
export const NON_EXISTENT_UUID = '00000000-0000-0000-0000-000000000000';

/**
 * Default test fixture values
 */
export const TEST_DEFAULTS = {
  PLAN_BUDGET: 250000,
  ROTATION_START: 100,
  ROTATION_DURATION: 240,
  PROCEDURE_DURATION: 60,
  RESOURCE_COST_PER_MINUTE: 10.0,
} as const;
