import { randomUUID } from 'crypto';
import {
  COHORT_PROPERTY,
  COHORT_TAG,
  DEFAULT_BASE_RISK_COST,
  DEFAULT_INTEGRITY_SCORE,
  DEFAULT_COHORT_BASE_RISK
} from './constants';

import type {
  CreateProcedureRequest,
  CreateCohortRequest,
  CohortProperty,
  CreateExecutionRequest,
  CreateTrialRequest,
  CreatePortfolioRequest
} from './types';

export function buildProcedureData(
  overrides: Partial<CreateProcedureRequest> = {}
): CreateProcedureRequest {
  return {
    procedure_type: `Procedure ${Date.now()}`,
    required_cohort_tag: COHORT_TAG.NONE as any,
    base_risk_cost: DEFAULT_BASE_RISK_COST,
    integrity_score_value: DEFAULT_INTEGRITY_SCORE,
    ...overrides
  };
}

export function buildCohortData(overrides: Partial<CreateCohortRequest> = {}): CreateCohortRequest {
  return {
    cohort_name: `Cohort ${Date.now()}`,
    cohort_version: '1.0',
    base_risk_points: DEFAULT_COHORT_BASE_RISK,
    properties: [],
    ...overrides
  };
}

export function buildCohortWithProperty(
  propertyName: string,
  certifiedPeriod: number = 0
): CreateCohortRequest {
  return buildCohortData({
    properties: [
      {
        property_id: `prop-${Date.now()}`,
        name: propertyName as any,
        certified_period_index: certifiedPeriod
      }
    ]
  });
}

export function buildHealthyVolunteersCohort(): CreateCohortRequest {
  return buildCohortWithProperty(COHORT_PROPERTY.HEALTHY_VOLUNTEERS);
}

export function buildHighRiskPatientsCohort(): CreateCohortRequest {
  return buildCohortWithProperty(COHORT_PROPERTY.HIGH_RISK_PATIENTS);
}

export function buildPlaceboCohort(): CreateCohortRequest {
  return buildCohortWithProperty(COHORT_PROPERTY.CONTAINS_PLACEBO);
}

export function buildExecutionData(
  procedureId: string,
  cohortId: string,
  protocolDeviation: boolean = false
): CreateExecutionRequest {
  return {
    procedure_id: procedureId,
    cohort_id: cohortId,
    protocol_deviation: protocolDeviation
  };
}

export function buildTrialData(overrides: Partial<CreateTrialRequest> = {}): Partial<CreateTrialRequest> {
  return {
    treatment_name: `Trial ${Date.now()}`,
    total_ethical_compliance_budget: 10000,
    ...overrides
  };
}

export function buildPortfolioData(overrides: Partial<CreatePortfolioRequest> = {}): CreatePortfolioRequest {
  return {
    name: `Portfolio ${Date.now()}`,
    description: 'Test portfolio',
    max_total_ethical_budget: 50000,
    ...overrides
  };
}

export function buildIRBData(overrides: Partial<{ name: string; description?: string }> = {}) {
  return {
    name: `IRB ${Date.now()}`,
    description: 'Test IRB',
    ...overrides
  };
}

export function buildBlackoutWindowData(overrides: Partial<{
  treatment_name_pattern: string;
  start_period_index: number;
  end_period_index: number;
  reason: string;
}> = {}) {
  return {
    treatment_name_pattern: '*',
    start_period_index: 0,
    end_period_index: 100,
    reason: 'Test blackout',
    ...overrides
  };
}

export function buildIncompatiblePairingData(
  cohortProperty: string,
  phaseName: string,
  reason: string = 'Test incompatibility'
) {
  return {
    cohort_property: cohortProperty,
    phase_name: phaseName,
    reason
  };
}

export function generateInvestigatorId(): string {
  return randomUUID();
}

export function generateUserId(): string {
  return randomUUID();
}

export function generateIdempotencyKey(): string {
  return randomUUID();
}

export function buildTrialWithOperationalBudget(
  irbId: string,
  overrides: Partial<{
    total_operational_budget: number;
    total_ethical_compliance_budget: number;
    site_id?: string;
  }> = {}
): Partial<CreateTrialRequest> {
  return {
    treatment_name: `Trial ${Date.now()}`,
    total_ethical_compliance_budget: overrides.total_ethical_compliance_budget ?? 10000,
    total_operational_budget: overrides.total_operational_budget ?? 1000,
    site_id: overrides.site_id,
    irb_id: irbId
  };
}

export function buildResearchSiteData(overrides: Partial<{
  name: string;
  location: string;
  max_active_trials: number;
}> = {}) {
  return {
    name: overrides.name || `Site ${Date.now()}`,
    location: overrides.location || 'Boston, MA',
    max_active_trials: overrides.max_active_trials ?? 10
  };
}

export function buildIntegrityProcedureData(
  overrides: Partial<CreateProcedureRequest> = {}
): CreateProcedureRequest {
  return {
    procedure_type: `Integrity Procedure ${Date.now()}`,
    required_cohort_tag: COHORT_TAG.NONE as any,
    base_risk_cost: DEFAULT_BASE_RISK_COST,
    integrity_score_value: overrides.integrity_score_value ?? 10,
    is_integrity_procedure: true,
    operational_cost: overrides.operational_cost ?? 0,
    required_certification_id: overrides.required_certification_id,
    ...overrides
  };
}

export function buildProcedureWithOperationalCost(
  operationalCost: number,
  overrides: Partial<CreateProcedureRequest> = {}
): CreateProcedureRequest {
  return {
    ...buildProcedureData(overrides),
    operational_cost: operationalCost
  };
}

export function buildProcedureWithCertification(
  certificationId: string,
  overrides: Partial<CreateProcedureRequest> = {}
): CreateProcedureRequest {
  return {
    ...buildProcedureData(overrides),
    required_certification_id: certificationId
  };
}

export function buildIRBWithLockPolicy(locksOnRejection: boolean = true) {
  return {
    name: `IRB ${Date.now()}`,
    description: 'Test IRB with lock policy',
    locks_on_rejection: locksOnRejection
  };
}

export function buildBudgetAdjustmentData(
  adjustment: number,
  justification: string = 'Valid justification for budget adjustment',
  version?: number
) {
  const data: any = { adjustment, justification };
  if (version !== undefined) {
    data.version = version;
  }
  return data;
}
