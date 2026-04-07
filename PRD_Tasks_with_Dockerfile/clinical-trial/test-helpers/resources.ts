import request, { Response } from 'supertest';
import { randomUUID } from 'crypto';
import { ROLES, DEFAULT_TRIAL_BUDGET } from './constants';
import type {
  ResearchProgram,
  ClinicalTrial,
  TrialPortfolio,
  InstitutionalReviewBoard,
  IRBApproval,
  TrialPhase,
  ProtocolProcedure,
  PatientCohort,
  ProcedureExecution,
  TreatmentDependency,
  IncompatibleCohortPhasePairing,
  EnrollmentBlackoutWindow,
  CreateResearchProgramRequest,
  CreateTrialRequest,
  CreatePortfolioRequest,
  CreatePhaseRequest,
  CreateProcedureRequest,
  CreateCohortRequest,
  CreateExecutionRequest,
  ManualRiskAdjustmentRequest,
  CreateDependencyRequest,
  UpdatePhaseRequest,
  UpdatePortfolioRequest,
  UpdateResearchProgramRequest
} from './types';

function getRequest() {
  const apiUrl = process.env.API_URL || 'http://localhost:3000';
  return request(apiUrl);
}

export async function createResearchProgram(
  data: Partial<CreateResearchProgramRequest> = {},
  userId: string = randomUUID()
): Promise<Response> {
  const defaults: CreateResearchProgramRequest = {
    name: `Test Program ${Date.now()}-${Math.random()}`,
    description: 'Test research program'
  };

  return await getRequest()
    .post('/research-programs')
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({ ...defaults, ...data });
}

export async function createIRB(
  programId: string,
  data: Partial<{ name: string; description?: string; locks_on_rejection?: boolean }> = {},
  userId: string = randomUUID()
): Promise<Response> {
  const defaults = {
    name: `Test IRB ${Date.now()}`,
    description: 'Test IRB'
  };

  return await getRequest()
    .post(`/research-programs/${programId}/irbs`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({ ...defaults, ...data });
}

export async function createIRBApproval(
  programId: string,
  irbId: string,
  trialId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .post(`/research-programs/${programId}/irbs/${irbId}/approvals`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({ trial_id: trialId });
}

export async function approveIRB(
  programId: string,
  irbId: string,
  approvalId: string,
  version: number,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .put(`/research-programs/${programId}/irbs/${irbId}/approvals/${approvalId}`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({ status: 'APPROVED', version });
}

export async function rejectIRBApproval(
  programId: string,
  irbId: string,
  approvalId: string,
  version: number,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .put(`/research-programs/${programId}/irbs/${irbId}/approvals/${approvalId}`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({ status: 'REJECTED', version });
}

export async function createPortfolio(
  programId: string,
  data: Partial<CreatePortfolioRequest> = {},
  userId: string = randomUUID()
): Promise<Response> {
  const defaults: CreatePortfolioRequest = {
    name: `Test Portfolio ${Date.now()}`,
    description: 'Test portfolio',
    max_total_ethical_budget: 50000
  };

  return await getRequest()
    .post(`/research-programs/${programId}/trial-portfolios`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({ ...defaults, ...data });
}

export async function createTrial(
  programId: string,
  data: Partial<CreateTrialRequest> = {},
  userId: string = randomUUID()
): Promise<Response> {

  let irbId: string = data.irb_id || '';
  if (!irbId) {
    const irbResponse = await createIRB(programId, {}, userId);
    if (irbResponse.status !== 201) {
      throw new Error(`Failed to auto-create IRB for trial: ${irbResponse.status}`);
    }
    irbId = irbResponse.body.data.id;
  }

  const defaults: CreateTrialRequest = {
    treatment_name: `Test Trial ${Date.now()}`,
    total_ethical_compliance_budget: DEFAULT_TRIAL_BUDGET,
    irb_id: irbId
  };

  return await getRequest()
    .post(`/research-programs/${programId}/clinical-trials`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({ ...defaults, ...data });
}

export async function activateTrial(
  programId: string,
  trialId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .post(`/research-programs/${programId}/clinical-trials/${trialId}/activate`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({});
}

export async function completeTrial(
  programId: string,
  trialId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .post(`/research-programs/${programId}/clinical-trials/${trialId}/complete`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({});
}

export async function abandonTrial(
  programId: string,
  trialId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .post(`/research-programs/${programId}/clinical-trials/${trialId}/abandon`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({});
}

export async function clearEthicalReviewLock(
  programId: string,
  trialId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .post(`/research-programs/${programId}/clinical-trials/${trialId}/clear-ethical-review-lock`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({});
}

export async function manualRiskAdjustment(
  programId: string,
  trialId: string,
  adjustment: number,
  justification: string,
  userId: string = randomUUID(),
  role: string = ROLES.RESEARCH_DIRECTOR
): Promise<Response> {
  return await getRequest()
    .post(`/research-programs/${programId}/clinical-trials/${trialId}/manual-risk-adjustment`)
    .set('X-User-ID', userId)
    .set('X-User-Role', role)
    .send({ adjustment, justification });
}

export async function createDependency(
  programId: string,
  trialId: string,
  dependencyTrialId: string,
  reason: string | null = null,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .post(`/research-programs/${programId}/clinical-trials/${trialId}/dependencies`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({ dependency_trial_id: dependencyTrialId, reason });
}

export async function createPhase(
  programId: string,
  trialId: string,
  phaseName: string,
  data: Partial<{ max_active_executions: number }> = {},
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .post(`/research-programs/${programId}/clinical-trials/${trialId}/trial-phases`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.CLINICAL_COORDINATOR)
    .send({ name: phaseName, ...data });
}

export async function getPhase(
  programId: string,
  trialId: string,
  phaseId: string
): Promise<Response> {
  return await getRequest()
    .get(`/research-programs/${programId}/clinical-trials/${trialId}/trial-phases/${phaseId}`);
}

export const getTrialPhase = getPhase;

export async function updatePhaseStatus(
  programId: string,
  trialId: string,
  phaseId: string,
  status: string,
  version: number,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .put(`/research-programs/${programId}/clinical-trials/${trialId}/trial-phases/${phaseId}`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({ status, version });
}

export async function clearPhaseReview(
  programId: string,
  trialId: string,
  phaseId: string,
  version: number,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .post(`/research-programs/${programId}/clinical-trials/${trialId}/trial-phases/${phaseId}/clear-review`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({ version });
}

export async function createProcedure(
  programId: string,
  trialId: string,
  phaseId: string,
  data: Partial<CreateProcedureRequest> = {},
  userId: string = randomUUID()
): Promise<Response> {
  const defaults: CreateProcedureRequest = {
    procedure_type: `Test Procedure ${Date.now()}`,
    required_cohort_tag: 'NONE',
    base_risk_cost: 100,
    integrity_score_value: 50
  };

  return await getRequest()
    .post(`/research-programs/${programId}/clinical-trials/${trialId}/trial-phases/${phaseId}/protocol-procedures`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.CLINICAL_COORDINATOR)
    .send({ ...defaults, ...data });
}

export async function createCohort(
  programId: string,
  trialId: string,
  data: Partial<CreateCohortRequest> | any = {},
  userId: string = randomUUID()
): Promise<Response> {
  const defaults: CreateCohortRequest = {
    cohort_name: `Test Cohort ${Date.now()}`,
    cohort_version: '1.0',
    base_risk_points: 10,
    properties: []
  };

  return await getRequest()
    .post(`/research-programs/${programId}/clinical-trials/${trialId}/patient-cohorts`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.CLINICAL_COORDINATOR)
    .send({ ...defaults, ...data });
}

export async function createExecution(
  programId: string,
  trialId: string,
  data: CreateExecutionRequest,
  userId: string = randomUUID(),
  idempotencyKey: string | null = null
): Promise<Response> {
  const key = idempotencyKey || `key-${Date.now()}-${Math.random()}`;

  return await getRequest()
    .post(`/research-programs/${programId}/clinical-trials/${trialId}/procedure-executions`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.CLINICAL_COORDINATOR)
    .set('Idempotency-Key', key)
    .send(data);
}

export async function executeExecution(
  programId: string,
  trialId: string,
  executionId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .post(`/research-programs/${programId}/clinical-trials/${trialId}/procedure-executions/${executionId}/execute`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({});
}

export async function markExecutionPassed(
  programId: string,
  trialId: string,
  executionId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .post(`/research-programs/${programId}/clinical-trials/${trialId}/procedure-executions/${executionId}/mark-passed`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({});
}

export async function rejectExecution(
  programId: string,
  trialId: string,
  executionId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .post(`/research-programs/${programId}/clinical-trials/${trialId}/procedure-executions/${executionId}/reject`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({});
}

export async function cancelExecution(
  programId: string,
  trialId: string,
  executionId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .post(`/research-programs/${programId}/clinical-trials/${trialId}/procedure-executions/${executionId}/cancel`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({});
}

export async function getExecutionFlags(
  programId: string,
  trialId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .get(`/research-programs/${programId}/clinical-trials/${trialId}/execution-flags`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR);
}

export async function initializeReputation(
  programId: string,
  investigatorId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .post(`/research-programs/${programId}/investigators/${investigatorId}/reputation/init`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({});
}

export async function advanceClock(
  programId: string,
  byPeriods: number,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .post(`/research-programs/${programId}/clock/advance`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({ by_periods: byPeriods });
}

export async function createIncompatiblePairing(
  programId: string,
  cohortProperty: string,
  phaseName: string,
  reason: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .post(`/research-programs/${programId}/incompatible-cohort-phase-pairings`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({ cohort_property: cohortProperty, phase_name: phaseName, reason });
}

export async function deleteIncompatiblePairing(
  programId: string,
  pairingId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .delete(`/research-programs/${programId}/incompatible-cohort-phase-pairings/${pairingId}`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR);
}

export async function createBlackoutWindow(
  programId: string,
  data: Partial<{
    treatment_name_pattern: string;
    start_period_index: number;
    end_period_index: number;
    reason: string;
  }> = {},
  userId: string = randomUUID()
): Promise<Response> {
  const defaults = {
    treatment_name_pattern: '*',
    start_period_index: 0,
    end_period_index: 100,
    reason: 'Test blackout'
  };

  return await getRequest()
    .post(`/research-programs/${programId}/enrollment-blackout-windows`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({ ...defaults, ...data });
}

export async function deleteBlackoutWindow(
  programId: string,
  windowId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .delete(`/research-programs/${programId}/enrollment-blackout-windows/${windowId}`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR);
}

export async function getResearchProgram(
  programId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .get(`/research-programs/${programId}`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR);
}

export async function getTrial(
  programId: string,
  trialId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .get(`/research-programs/${programId}/clinical-trials/${trialId}`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR);
}

export async function getTrialHistory(
  programId: string,
  trialId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .get(`/research-programs/${programId}/clinical-trials/${trialId}/history`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR);
}

export async function getPortfolio(
  programId: string,
  portfolioId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .get(`/research-programs/${programId}/trial-portfolios/${portfolioId}`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR);
}

export async function updatePortfolio(
  programId: string,
  portfolioId: string,
  data: Partial<UpdatePortfolioRequest>,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .put(`/research-programs/${programId}/trial-portfolios/${portfolioId}`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send(data);
}

export async function listResearchPrograms(userId: string = randomUUID()): Promise<Response> {
  return await getRequest()
    .get('/research-programs')
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR);
}

export async function listPortfolios(
  programId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .get(`/research-programs/${programId}/trial-portfolios`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR);
}

export async function listBlackoutWindows(
  programId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .get(`/research-programs/${programId}/enrollment-blackout-windows`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR);
}

export async function createResearchSite(
  programId: string,
  siteData?: Partial<{
    name: string;
    location: string;
    max_active_trials: number;
  }>,
  userId: string = randomUUID()
): Promise<Response> {
  const data = {
    name: siteData?.name || `Research Site ${randomUUID().slice(0, 8)}`,
    location: siteData?.location || 'Boston, MA',
    max_active_trials: siteData?.max_active_trials ?? 10
  };

  return await getRequest()
    .post(`/research-programs/${programId}/research-sites`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send(data);
}

export async function listResearchSites(
  programId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .get(`/research-programs/${programId}/research-sites`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR);
}

export async function getResearchSite(
  programId: string,
  siteId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .get(`/research-programs/${programId}/research-sites/${siteId}`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR);
}

export async function updateResearchSite(
  programId: string,
  siteId: string,
  updates: Partial<{
    name: string;
    location: string;
    max_active_trials: number;
    version: number;
  }>,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .put(`/research-programs/${programId}/research-sites/${siteId}`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send(updates);
}

export async function createInvestigatorCertification(
  programId: string,
  investigatorId: string,
  certData?: Partial<{ certification_name: string; valid_for_periods?: number }>,
  userId: string = randomUUID()
): Promise<Response> {
  const data = {
    certification_name: certData?.certification_name || `Certification ${randomUUID().slice(0, 8)}`,
    valid_for_periods: certData?.valid_for_periods
  };

  return await getRequest()
    .post(`/research-programs/${programId}/investigators/${investigatorId}/certifications`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send(data);
}

export async function listInvestigatorCertifications(
  programId: string,
  investigatorId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .get(`/research-programs/${programId}/investigators/${investigatorId}/certifications`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR);
}

export async function deleteInvestigatorCertification(
  programId: string,
  investigatorId: string,
  certificationId: string,
  userId: string = randomUUID(),
  expectedVersion?: number
): Promise<Response> {
  const request = getRequest()
    .delete(`/research-programs/${programId}/investigators/${investigatorId}/certifications/${certificationId}`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR);

  if (expectedVersion !== undefined) {
    request.set('If-Match', expectedVersion.toString());
  }

  return await request;
}

export async function renewInvestigatorCertification(
  programId: string,
  investigatorId: string,
  certificationId: string,
  additionalValidForPeriods: number,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .post(
      `/research-programs/${programId}/investigators/${investigatorId}/certifications/${certificationId}/renew`
    )
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({ additional_valid_for_periods: additionalValidForPeriods });
}

export async function getInvestigatorReputation(
  programId: string,
  investigatorId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .get(`/research-programs/${programId}/investigators/${investigatorId}/reputation`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR);
}

export async function suspendTrial(
  programId: string,
  trialId: string,
  reason?: 'REGULATORY' | 'FINANCIAL',
  userId: string = randomUUID()
): Promise<Response> {
  const data = reason ? { reason } : {};

  return await getRequest()
    .post(`/research-programs/${programId}/clinical-trials/${trialId}/suspend`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send(data);
}

export async function clearSuspension(
  programId: string,
  trialId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .post(`/research-programs/${programId}/clinical-trials/${trialId}/clear-suspension`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({});
}

export async function reassignTrial(
  programId: string,
  trialId: string,
  newInvestigatorId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .post(`/research-programs/${programId}/clinical-trials/${trialId}/reassign`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({ new_investigator_id: newInvestigatorId });
}

export async function adjustEthicalBudget(
  programId: string,
  trialId: string,
  adjustment: number,
  justification: string,
  version?: number,
  userId: string = randomUUID()
): Promise<Response> {
  const data: any = { adjustment, justification };
  if (version !== undefined) {
    data.version = version;
  }

  return await getRequest()
    .post(`/research-programs/${programId}/clinical-trials/${trialId}/adjust-ethical-budget`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send(data);
}

export async function updateResearchProgram(
  programId: string,
  updates: Partial<UpdateResearchProgramRequest>,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .put(`/research-programs/${programId}`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send(updates);
}

export async function freezeProgram(
  programId: string,
  reason: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .post(`/research-programs/${programId}/audit-freeze`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({ reason });
}

export async function unfreezeProgram(
  programId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .post(`/research-programs/${programId}/audit-unfreeze`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({});
}

export async function renewCertification(
  programId: string,
  investigatorId: string,
  certificationId: string,
  additionalValidForPeriods: number,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .post(`/research-programs/${programId}/investigators/${investigatorId}/certifications/${certificationId}/renew`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({ additional_valid_for_periods: additionalValidForPeriods });
}

export async function advanceProgramClock(
  programId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .post(`/research-programs/${programId}/clock/advance`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send({ by_periods: 1 });
}

export async function createFundingGrant(
  programId: string,
  grantData?: Partial<{ grant_name: string; total_budget: number }>,
  userId: string = randomUUID()
): Promise<Response> {
  const data = {
    grant_name: grantData?.grant_name ?? `Grant ${randomUUID().slice(0, 8)}`,
    total_budget: grantData?.total_budget ?? 10000
  };

  return await getRequest()
    .post(`/research-programs/${programId}/funding-grants`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send(data);
}

export async function getFundingGrants(
  programId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .get(`/research-programs/${programId}/funding-grants`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR);
}

export async function getFundingGrant(
  programId: string,
  grantId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .get(`/research-programs/${programId}/funding-grants/${grantId}`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR);
}

export async function createExclusionGroup(
  programId: string,
  groupData: { group_name: string; trial_ids: string[] },
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .post(`/research-programs/${programId}/exclusion-groups`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send(groupData);
}

export async function getExclusionGroups(
  programId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .get(`/research-programs/${programId}/exclusion-groups`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR);
}

export async function createInvestigatorCap(
  programId: string,
  siteId: string,
  data: { investigator_id: string; max_active_trials: number },
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .post(`/research-programs/${programId}/research-sites/${siteId}/investigator-caps`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send(data);
}

export async function listInvestigatorCaps(
  programId: string,
  siteId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .get(`/research-programs/${programId}/research-sites/${siteId}/investigator-caps`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR);
}

export async function updateInvestigatorCap(
  programId: string,
  siteId: string,
  capId: string,
  data: { max_active_trials: number; version?: number },
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .put(`/research-programs/${programId}/research-sites/${siteId}/investigator-caps/${capId}`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
    .send(data);
}

export async function deleteInvestigatorCap(
  programId: string,
  siteId: string,
  capId: string,
  userId: string = randomUUID()
): Promise<Response> {
  return await getRequest()
    .delete(`/research-programs/${programId}/research-sites/${siteId}/investigator-caps/${capId}`)
    .set('X-User-ID', userId)
    .set('X-User-Role', ROLES.RESEARCH_DIRECTOR);
}
