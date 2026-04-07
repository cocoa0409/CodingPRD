import { Response } from 'supertest';

export function expectError(response: Response, statusCode: number, errorId: string | string[]): void {
  expect(response.status).toBe(statusCode);

  if (response.body.response_type) {
    expect(response.body.response_type).toBe('error');
  }

  const actualErrorId = response.body.data?.error_id || response.body.meta?.error?.code;

  if (Array.isArray(errorId)) {
    expect(errorId).toContain(actualErrorId);
  } else {
    expect(actualErrorId).toBe(errorId);
  }

}

export function expectSuccess(response: Response, expectedStatus?: number): void {
  if (expectedStatus !== undefined) {
    expect(response.status).toBe(expectedStatus);
  } else {
    expect(response.status).toBeGreaterThanOrEqual(200);
    expect(response.status).toBeLessThan(300);
  }

  if (response.status === 204) {
    return;
  }

  if (response.body.response_type) {
    expect(response.body.response_type).toMatch(/^(object|array)$/);
  }

  expect(response.body.data).toBeDefined();
}

export function expectResourceFields(resource: any): void {
  expect(resource.id).toBeDefined();
  expect(typeof resource.id).toBe('string');
  expect(resource.version).toBeDefined();
  expect(typeof resource.version).toBe('number');
  expect(resource.created_seq).toBeDefined();
  expect(typeof resource.created_seq).toBe('number');
}

export function expectSortedByCreatedSeq(items: Array<{ created_seq: number }>): void {
  for (let i = 1; i < items.length; i++) {
    expect(items[i].created_seq).toBeGreaterThanOrEqual(items[i - 1].created_seq);
  }
}

export function expectVersionIncremented(oldVersion: number, newVersion: number): void {
  expect(newVersion).toBe(oldVersion + 1);
}

export function expectExactlyOneSuccess(
  response1: Response,
  response2: Response,
  successCode: number = 201
): void {
  const statuses = [response1.status, response2.status].sort((a, b) => a - b);
  expect(statuses[0]).toBeLessThan(successCode);
  expect(statuses[1]).toBe(successCode);
}

export function expectTrialDerivedFields(trial: any): void {
  expect(trial.effective_ethical_compliance_budget).toBeDefined();
  expect(typeof trial.effective_ethical_compliance_budget).toBe('number');
  expect(trial.ethical_compliance_balance).toBeDefined();
  expect(typeof trial.ethical_compliance_balance).toBe('number');
  expect(trial.patient_safety_risk).toBeDefined();
  expect(typeof trial.patient_safety_risk).toBe('number');
  expect(trial.is_under_contagion).toBeDefined();
  expect(typeof trial.is_under_contagion).toBe('boolean');
}

export function expectNonNegativeBalance(balance: number): void {
  expect(balance).toBeGreaterThanOrEqual(0);
}

export function expectValidReputationScore(score: number): void {
  expect(score).toBeGreaterThanOrEqual(0);
  expect(score).toBeLessThanOrEqual(100);
}

export function expectTrialSuspended(
  trial: any,
  expectedReason: 'FINANCIAL' | 'REGULATORY'
): void {
  expect(trial.status).toBe('SUSPENDED');
  expect(trial.suspension_reason).toBe(expectedReason);
}

export function expectTrialNotSuspended(trial: any): void {
  expect(trial.status).not.toBe('SUSPENDED');
  expect(trial.suspension_reason).toBeUndefined();
}

export function expectOperationalBalance(trial: any, expectedBalance: number): void {
  expect(trial.operational_balance).toBe(expectedBalance);
}

export function expectOperationalOverdraft(trial: any): void {
  expect(trial.operational_balance).toBeLessThan(0);
}

export function expectDualBudgetsRecalculated(
  trial: any,
  expectedEthicalEffective: number,
  expectedOperationalEffective: number
): void {
  expect(trial.effective_ethical_compliance_budget).toBe(expectedEthicalEffective);
  expect(trial.effective_operational_budget).toBe(expectedOperationalEffective);
}

export function expectSiteUtilization(
  trials: any[],
  siteId: string,
  expectedCount: number
): void {
  const activeAtSite = trials.filter(
    t => t.site_id === siteId && (t.status === 'ACTIVE' || t.status === 'SUSPENDED')
  ).length;

  expect(activeAtSite).toBe(expectedCount);
}

export function expectInvestigatorHasCertification(
  certifications: any[],
  certificationName: string
): void {
  const hasCert = certifications.some(c => c.certification_name === certificationName);
  expect(hasCert).toBe(true);
}

export function expectInvestigatorLacksCertification(
  certifications: any[],
  certificationName: string
): void {
  const hasCert = certifications.some(c => c.certification_name === certificationName);
  expect(hasCert).toBe(false);
}

export function expectV2TrialDerivedFields(trial: any): void {

  expect(typeof trial.effective_ethical_compliance_budget).toBe('number');
  expect(typeof trial.ethical_compliance_balance).toBe('number');
  expect(typeof trial.patient_safety_risk).toBe('number');

  expect(typeof trial.total_operational_budget).toBe('number');
  expect(typeof trial.effective_operational_budget).toBe('number');
  expect(typeof trial.operational_balance).toBe('number');

  expect(trial.operational_balance).toBeDefined();

  expect(trial.ethical_compliance_balance).toBeGreaterThanOrEqual(0);
}

export function expectReputationIncreased(
  beforeReputation: number,
  afterReputation: number,
  expectedIncrease: number
): void {
  const actualIncrease = afterReputation - beforeReputation;
  expect(actualIncrease).toBe(expectedIncrease);

  expect(afterReputation).toBeLessThanOrEqual(100);
}

export function expectProbationStatus(reputation: any, expectedOnProbation: boolean): void {
  expect(reputation.is_on_probation).toBe(expectedOnProbation);

  if (expectedOnProbation) {
    expect(reputation.reputation_score).toBeLessThan(40);
  } else {
    expect(reputation.reputation_score).toBeGreaterThanOrEqual(40);
  }
}
