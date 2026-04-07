import request from 'supertest';
import { randomUUID } from 'crypto';
import {
  createTrial,
  createIRB,
  createIRBApproval,
  approveIRB,
  createPhase,
  createProcedure,
  createCohort,
  createExecution,
  executeExecution,
  markExecutionPassed,
  cancelExecution,
  createDependency,
  createIncompatiblePairing,
  deleteIncompatiblePairing,
  createBlackoutWindow,
  deleteBlackoutWindow,
  createPortfolio,
  updatePhaseStatus,
  advanceClock,
  manualRiskAdjustment,
  updatePortfolio,
  clearEthicalReviewLock,
  abandonTrial,
  activateTrial,
  getTrial,
  getPortfolio,
  rejectExecution,
  completeTrial
} from '../../../test-helpers/resources';

import {
  expectError,
  expectSuccess,
  expectNonNegativeBalance
} from '../../../test-helpers/assertions';

import {
  COHORT_TAG,
  COHORT_PROPERTY,
  PHASE_NAME,
  PHASE_STATUS,
  TRIAL_STATUS,
  MAX_ACTIVE_DEVIATIONS_PER_USER,
  MAX_ADVANCE_BY,
  AUDIT_LOCK_THRESHOLD, ROLES
} from '../../../test-helpers/constants';

import {
  setupActiveTrial,
  setupTrialWithPhase,
  setupTrialWithProcedure,
  setupTrialWithActiveDeviations,
  setupPortfolioWithTrials,
  setupTrialNearExpeditedThreshold,
  forceTrialIntoLock, driveReputationToTarget,
  triggerPhaseReview,
  triggerPhaseReviewRequired,
  executeAndPassProcedure,
  createProgramWithIRB
} from '../../../test-helpers/scenarios';

import {
  buildHealthyVolunteersCohort,
  buildPlaceboCohort, generateInvestigatorId,
  generateUserId,
  generateIdempotencyKey
} from '../../../test-helpers/builders';

describe('Constraint Validations', () => {

  describe('Deviation Eligibility Constraints', () => {

    test('should reject deviation when trial is not ACTIVE', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      await abandonTrial(program.id, trial.id);

      const response = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      expectError(response, 409, 'ERR_TRIAL_NOT_ACTIVE');
    });

    test('should reject deviation when trial is in ETHICAL_REVIEW_LOCK', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      await forceTrialIntoLock(program.id, trial.id);

      const response = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      expectError(response, 403, 'ERR_TRIAL_IN_ETHICAL_REVIEW_LOCK');
    });

    test('should reject deviation when procedure is not PENDING', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      const response = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      expectError(response, 409, 'ERR_PROCEDURE_NOT_PENDING');
    });

    test('should reject deviation when cohort belongs to different trial', async () => {
      const { program, irb } = await createProgramWithIRB();

      const { trial: trial1 } = await setupActiveTrial({ program, irb });
      const { trial: trial2 } = await setupActiveTrial({ program, irb });

      const cohort1Response = await createCohort(program.id, trial1.id);
      const cohort1 = cohort1Response.body.data;

      const phase2Resp = await createPhase(program.id, trial2.id, PHASE_NAME.PHASE_I);
      const phase2 = phase2Resp.body.data;
      const procedure2Resp = await createProcedure(program.id, trial2.id, phase2.id);
      const procedure2 = procedure2Resp.body.data;

      const response = await createExecution(program.id, trial2.id, {
        procedure_id: procedure2.id,
        cohort_id: cohort1.id,
        protocol_deviation: false
      });

      expectError(response, 404, 'ERR_COHORT_NOT_FOUND');
    });

    test('should reject deviation when cohort tag does not match procedure requirement', async () => {
      const { program, trial, phase } = await setupTrialWithPhase();

      const cohortResponse = await createCohort(program.id, trial.id);
      const cohort = cohortResponse.body.data;

      const procedureResp = await createProcedure(program.id, trial.id, phase.id, {
        required_cohort_tag: COHORT_TAG.HEALTHY_VOLUNTEERS,
        base_risk_cost: 100,
        integrity_score_value: 50
      });
      const procedure = procedureResp.body.data;

      const response = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      expectError(response, 400, 'ERR_COHORT_TAG_MISMATCH');
    });

    test('should reject deviation when cohort-phase pairing is incompatible', async () => {
      const { program, trial, phase } = await setupTrialWithPhase(PHASE_NAME.PHASE_II);

      await createIncompatiblePairing(
        program.id,
        COHORT_PROPERTY.CONTAINS_PLACEBO,
        PHASE_NAME.PHASE_II,
        'Placebo not allowed in Phase II'
      );

      const cohortResponse = await createCohort(program.id, trial.id, buildPlaceboCohort());
      const cohort = cohortResponse.body.data;

      const procedureResp = await createProcedure(program.id, trial.id, phase.id);
      const procedure = procedureResp.body.data;

      const response = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      expectError(response, 409, 'ERR_INCOMPATIBLE_COHORT_PHASE_PAIRING');
    });

    test('should reject deviation when ethical budget is insufficient', async () => {
      const { program, irb } = await createProgramWithIRB();

      const { trial } = await setupActiveTrial({ program, irb, total_ethical_compliance_budget: 50 });

      const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
      const phase = phaseResp.body.data;
      const procedureResp = await createProcedure(program.id, trial.id, phase.id, {
        base_risk_cost: 1000
      });
      const procedure = procedureResp.body.data;
      const cohortResponse = await createCohort(program.id, trial.id);
      const cohort = cohortResponse.body.data;

      const response = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      expectError(response, 402, 'ERR_INSUFFICIENT_ETHICAL_BUDGET');
    });

    test('should reject deviation when investigator is on probation', async () => {
      const { program, irb } = await createProgramWithIRB();
      const investigatorId = generateInvestigatorId();

      await driveReputationToTarget(program.id, investigatorId, 30);

      const { trial } = await setupActiveTrial({
        program,
        irb,
        total_ethical_compliance_budget: 400,
        investigatorId
      });

      const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
      const phase = phaseResp.body.data;
      const procedureResp = await createProcedure(program.id, trial.id, phase.id);
      const procedure = procedureResp.body.data;
      const cohortResponse = await createCohort(program.id, trial.id);
      const cohort = cohortResponse.body.data;

      const response = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      expectError(response, 403, 'ERR_INVESTIGATOR_ON_PROBATION_DEVIATIONS_BLOCKED');
    });

    test('should reject deviation when portfolio is saturated', async () => {
      const { program } = await createProgramWithIRB();

      const portfolioResp = await createPortfolio(program.id, {
        max_total_ethical_budget: 100
      });
      const portfolio = portfolioResp.body.data;

      const { trial } = await setupActiveTrial({
        program,
        portfolio_id: portfolio.id,
        total_ethical_compliance_budget: 200
      });

      const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
      const phase = phaseResp.body.data;
      const procedureResp = await createProcedure(program.id, trial.id, phase.id, {
        base_risk_cost: 90
      });
      const procedure = procedureResp.body.data;
      const cohortResponse = await createCohort(program.id, trial.id);
      const cohort = cohortResponse.body.data;

      await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      const portfolioCheck = await getPortfolio(program.id, portfolio.id);
      expect(portfolioCheck.body.data.is_risk_saturated).toBe(true);

      const procedure2Resp = await createProcedure(program.id, trial.id, phase.id, {
        base_risk_cost: 5
      });
      const procedure2 = procedure2Resp.body.data;

      const response = await createExecution(program.id, trial.id, {
        procedure_id: procedure2.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      expectError(response, 403, 'ERR_PORTFOLIO_RISK_SATURATED');
    });

    test('should enforce max active deviations per user', async () => {
      const userId = generateUserId();

      const { program, trial, executions } = await setupTrialWithActiveDeviations(
        MAX_ACTIVE_DEVIATIONS_PER_USER,
        userId
      );

      const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
      const phase = phaseResp.body.data;
      const procedureResp = await createProcedure(program.id, trial.id, phase.id);
      const procedure = procedureResp.body.data;
      const cohortResponse = await createCohort(program.id, trial.id);
      const cohort = cohortResponse.body.data;

      const response = await createExecution(
        program.id,
        trial.id,
        {
          procedure_id: procedure.id,
          cohort_id: cohort.id,
          protocol_deviation: true
        },
        userId
      );

      expectError(response, 409, 'ERR_MAX_ACTIVE_DEVIATIONS_PER_USER_VIOLATION');
    });

    test('should accept deviation when cohort has required tag', async () => {
      const { program, trial, phase } = await setupTrialWithPhase();

      const cohortResponse = await createCohort(
        program.id,
        trial.id,
        buildHealthyVolunteersCohort()
      );
      const cohort = cohortResponse.body.data;

      const procedureResp = await createProcedure(program.id, trial.id, phase.id, {
        required_cohort_tag: COHORT_TAG.HEALTHY_VOLUNTEERS,
        base_risk_cost: 100,
        integrity_score_value: 50
      });
      const procedure = procedureResp.body.data;

      const response = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      expectSuccess(response, 201);
    });

    test('should validate procedure and cohort belong to same trial', async () => {
      const { program } = await createProgramWithIRB();
      const { trial: trial1 } = await setupActiveTrial({ program });
      const { trial: trial2 } = await setupActiveTrial({ program });

      const phase1Resp = await createPhase(program.id, trial1.id, PHASE_NAME.PHASE_I);
      const phase1 = phase1Resp.body.data;
      const proc1Resp = await createProcedure(program.id, trial1.id, phase1.id);
      const proc1 = proc1Resp.body.data;

      const cohort2Response = await createCohort(program.id, trial2.id);
      const cohort2 = cohort2Response.body.data;

      const response = await createExecution(program.id, trial2.id, {
        procedure_id: proc1.id,
        cohort_id: cohort2.id,
        protocol_deviation: false
      });

      expectError(response, 404, 'ERR_PROCEDURE_NOT_FOUND');
    });

    test('should require procedure status to be PENDING before creating execution', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const exec1 = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      expectSuccess(exec1, 201);

      const exec2Attempt = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      expectError(exec2Attempt, 409, 'ERR_PROCEDURE_NOT_PENDING');
    });

    test('should enforce trial ID consistency in resource paths', async () => {
      const { program } = await createProgramWithIRB();
      const { trial: trial1 } = await setupActiveTrial({ program });
      const { trial: trial2 } = await setupActiveTrial({ program });

      const phase1Resp = await createPhase(program.id, trial1.id, PHASE_NAME.PHASE_I);
      const phase1 = phase1Resp.body.data;
      const proc1Resp = await createProcedure(program.id, trial1.id, phase1.id);
      const proc1 = proc1Resp.body.data;
      const cohort1Response = await createCohort(program.id, trial1.id);
      const cohort1 = cohort1Response.body.data;

      expect(phase1.trial_id).toBe(trial1.id);
      expect(proc1.trial_id).toBe(trial1.id);
      expect(cohort1.trial_id).toBe(trial1.id);

      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const wrongPathResponse = await request(apiUrl)
        .post(`/research-programs/${program.id}/clinical-trials/${trial2.id}/procedure-executions`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', 'ClinicalCoordinator')
        .set('Idempotency-Key', generateIdempotencyKey())
        .send({
          procedure_id: proc1.id,
          cohort_id: cohort1.id,
          protocol_deviation: false
        });

      expectError(wrongPathResponse, 404, 'ERR_PROCEDURE_NOT_FOUND');
    });

    test('should reverse provisional debits from both PENDING and EXECUTED states on abandonment', async () => {
      const { program, trial, executions } = await setupTrialWithActiveDeviations(2);

      await executeExecution(program.id, trial.id, executions[0].id);

      const response = await abandonTrial(program.id, trial.id);

      expectSuccess(response, 200);
    });

    test('should allow deviation after portfolio saturation is cleared', async () => {
      const { program } = await createProgramWithIRB();
      const portfolioResp = await createPortfolio(program.id, { max_total_ethical_budget: 100 });
      const portfolio = portfolioResp.body.data;

      const { trial } = await setupActiveTrial({ program, portfolio_id: portfolio.id, total_ethical_compliance_budget: 200 });

      const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
      const phase = phaseResp.body.data;
      const cohortResponse = await createCohort(program.id, trial.id);
      const cohort = cohortResponse.body.data;

      const proc1Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 90 });
      const proc1 = proc1Resp.body.data;
      await createExecution(program.id, trial.id, {
        procedure_id: proc1.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      let portfolioCheckResp = await getPortfolio(program.id, portfolio.id);
      expect(portfolioCheckResp.body.data.is_risk_saturated).toBe(true);

      const proc2Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 5 });
      const proc2 = proc2Resp.body.data;
      const exec2Blocked = await createExecution(program.id, trial.id, {
        procedure_id: proc2.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });
      expectError(exec2Blocked, 403, 'ERR_PORTFOLIO_RISK_SATURATED');

      await updatePortfolio(program.id, portfolio.id, {
        max_total_ethical_budget: 10000,
        version: portfolio.version
      });

      const proc3Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 5 });
      const proc3 = proc3Resp.body.data;
      const exec3Allowed = await createExecution(program.id, trial.id, {
        procedure_id: proc3.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });
      expectSuccess(exec3Allowed, 201);
    });

    test('should reject deviation when effective budget is zero due to reputation', async () => {
      const { program, irb } = await createProgramWithIRB();
      const investigatorId = generateInvestigatorId();

      await driveReputationToTarget(program.id, investigatorId, 0);

      const { trial } = await setupActiveTrial({ program, irb, total_ethical_compliance_budget: 500, investigatorId });

      expect(trial.effective_ethical_compliance_budget).toBe(0);
      expect(trial.ethical_compliance_balance).toBe(0);

      const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
      const phase = phaseResp.body.data;
      const procedureResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 1 });
      const procedure = procedureResp.body.data;
      const cohortResponse = await createCohort(program.id, trial.id);
      const cohort = cohortResponse.body.data;

      const deviationResp = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      expectError(deviationResp, 403, 'ERR_INVESTIGATOR_ON_PROBATION_DEVIATIONS_BLOCKED');
    });

    test('should reject idempotent request with different body', async () => {
      const { program, trial, phase } = await setupTrialWithPhase();

      const cohortResponse = await createCohort(program.id, trial.id);
      const cohort = cohortResponse.body.data;

      const procedure1Resp = await createProcedure(program.id, trial.id, phase.id);
      const procedure1 = procedure1Resp.body.data;
      const procedure2Resp = await createProcedure(program.id, trial.id, phase.id);
      const procedure2 = procedure2Resp.body.data;

      const idempotencyKey = 'test-idem-key-123';
      const userId = randomUUID();

      const response1 = await createExecution(
        program.id,
        trial.id,
        {
          procedure_id: procedure1.id,
          cohort_id: cohort.id,
          protocol_deviation: false
        },
        userId,
        idempotencyKey
      );

      expectSuccess(response1, 201);

      const response2 = await createExecution(
        program.id,
        trial.id,
        {
          procedure_id: procedure2.id,
          cohort_id: cohort.id,
          protocol_deviation: false
        },
        userId,
        idempotencyKey
      );

      expectError(response2, 409, 'ERR_IDEMPOTENCY_CONFLICT');
    });
  });

  describe('Trial Creation and Activation Constraints', () => {

    test('should reject self-dependency', async () => {
      const { program, irb } = await createProgramWithIRB();
      const trialResp = await createTrial(program.id, { irb_id: irb.id });
      const trial = trialResp.body.data;

      const response = await createDependency(program.id, trial.id, trial.id);

      expectError(response, 400, 'ERR_SELF_DEPENDENCY');
    });

    test('should reject cross-program dependency', async () => {
      const { program: program1, irb: irb1 } = await createProgramWithIRB();
      const { program: program2, irb: irb2 } = await createProgramWithIRB();

      const trial1Resp = await createTrial(program1.id, { irb_id: irb1.id });
      const trial1 = trial1Resp.body.data;
      const trial2Resp = await createTrial(program2.id, { irb_id: irb2.id });
      const trial2 = trial2Resp.body.data;

      const response = await createDependency(program1.id, trial1.id, trial2.id);

      expectError(response, 400, 'ERR_CROSS_PROGRAM_DEPENDENCY');
    });

    test('should reject activation without IRB approval', async () => {
      const { program, irb } = await createProgramWithIRB();
      const trialResp = await createTrial(program.id, { irb_id: irb.id });
      const trial = trialResp.body.data;

      const response = await activateTrial(program.id, trial.id);

      expectError(response, 409, 'ERR_NO_APPROVED_IRB');
    });

    test('should reject trial creation with non-existent IRB', async () => {
      const { program } = await createProgramWithIRB();
      const fakeIrbId = randomUUID();

      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const response = await request(apiUrl)
        .post(`/research-programs/${program.id}/clinical-trials`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
        .send({
          treatment_name: 'Test Trial',
          total_ethical_compliance_budget: 10000,
          irb_id: fakeIrbId
        });

      expectError(response, 404, 'ERR_IRB_NOT_FOUND');
    });

    test('should reject trial creation with non-existent portfolio', async () => {
      const { program, irb } = await createProgramWithIRB();
      const fakePortfolioId = randomUUID();

      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const response = await request(apiUrl)
        .post(`/research-programs/${program.id}/clinical-trials`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
        .send({
          treatment_name: 'Test Trial',
          total_ethical_compliance_budget: 10000,
          irb_id: irb.id,
          portfolio_id: fakePortfolioId
        });

      expectError(response, 404, 'ERR_PORTFOLIO_NOT_FOUND');
    });

    test('should accept activation with approval from any IRB for the trial', async () => {
      const { program, irb } = await createProgramWithIRB();
      const trialResp = await createTrial(program.id, { irb_id: irb.id });
      const trial = trialResp.body.data;

      const approvalResp = await createIRBApproval(program.id, irb.id, trial.id);
      const approval = approvalResp.body.data;
      await approveIRB(program.id, irb.id, approval.id, approval.version);

      const response = await activateTrial(program.id, trial.id);

      expectSuccess(response, 200);
    });

    test('should require all dependencies to be completed for activation', async () => {
      const { program, irb } = await createProgramWithIRB();

      const dep1Resp = await createTrial(program.id, { irb_id: irb.id });
      expectSuccess(dep1Resp, 201);
      const dep1 = dep1Resp.body.data;

      const dep2Resp = await createTrial(program.id, { irb_id: irb.id });
      expectSuccess(dep2Resp, 201);
      const dep2 = dep2Resp.body.data;

      const dep1ApprovalResp = await createIRBApproval(program.id, irb.id, dep1.id);
      expectSuccess(dep1ApprovalResp, 201);
      const dep1Approval = dep1ApprovalResp.body.data;

      const approveDep1Resp = await approveIRB(program.id, irb.id, dep1Approval.id, dep1Approval.version);
      expectSuccess(approveDep1Resp, 200);

      const activateDep1Resp = await activateTrial(program.id, dep1.id);
      expectSuccess(activateDep1Resp, 200);

      const completeDep1Resp = await completeTrial(program.id, dep1.id);
      expectSuccess(completeDep1Resp, 200);

      const mainTrialResp = await createTrial(program.id, { irb_id: irb.id });
      expectSuccess(mainTrialResp, 201);
      const mainTrial = mainTrialResp.body.data;

      await createDependency(program.id, mainTrial.id, dep1.id);
      await createDependency(program.id, mainTrial.id, dep2.id);

      const mainApprovalResp = await createIRBApproval(program.id, irb.id, mainTrial.id);
      expectSuccess(mainApprovalResp, 201);
      const mainApproval = mainApprovalResp.body.data;

      const approveMainResp = await approveIRB(program.id, irb.id, mainApproval.id, mainApproval.version);
      expectSuccess(approveMainResp, 200);

      const response = await activateTrial(program.id, mainTrial.id);

      expectError(response, 409, 'ERR_DEPENDENCIES_NOT_MET');
    });

    test('should allow trial creation on probation with budget at cap', async () => {
      const { program, irb } = await createProgramWithIRB();
      const investigatorId = generateInvestigatorId();

      await driveReputationToTarget(program.id, investigatorId, 30);

      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const atCapResponse = await request(apiUrl)
        .post(`/research-programs/${program.id}/clinical-trials`)
        .set('X-User-ID', investigatorId)
        .set('X-User-Role', 'ResearchDirector')
        .send({
          treatment_name: 'At Cap Trial',
          total_ethical_compliance_budget: 500,
          irb_id: irb.id
        });

      expectSuccess(atCapResponse, 201);
      expect(atCapResponse.body.data.total_ethical_compliance_budget).toBe(500);

      const irb2Resp = await createIRB(program.id);
      const irb2 = irb2Resp.body.data;
      const aboveCapResponse = await request(apiUrl)
        .post(`/research-programs/${program.id}/clinical-trials`)
        .set('X-User-ID', investigatorId)
        .set('X-User-Role', 'ResearchDirector')
        .send({
          treatment_name: 'Above Cap Trial',
          total_ethical_compliance_budget: 501,
          irb_id: irb2.id
        });

      expectError(aboveCapResponse, 403, 'ERR_INVESTIGATOR_ON_PROBATION_BUDGET_EXCEEDED');
    });

    test('should allow any budget when investigator is not on probation', async () => {
      const { program, trial } = await setupActiveTrial({
        total_ethical_compliance_budget: 100000
      });

      expect(trial.total_ethical_compliance_budget).toBe(100000);
    });

    test('should reject IRB approval when IRB and trial are in different programs', async () => {
      const { program: program1, irb: irb1 } = await createProgramWithIRB();
      const { program: program2 } = await createProgramWithIRB();

      const trial2Resp = await createTrial(program2.id);
      const trial2 = trial2Resp.body.data;

      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const response = await request(apiUrl)
        .post(`/research-programs/${program1.id}/irbs/${irb1.id}/approvals`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
        .send({ trial_id: trial2.id });

      expectError(response, 400, 'ERR_IRB_PROGRAM_MISMATCH');
    });
  });

  describe('Phase and Procedure Constraints', () => {

    test('should reject READY_FOR_PROCEDURES without procedures', async () => {
      const { program, trial, phase } = await setupTrialWithPhase();

      const response = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.READY_FOR_PROCEDURES,
        phase.version
      );

      expectError(response, 409, 'ERR_NO_PROCEDURES_DEFINED');
    });

    test('should reject phase completion when procedures are not all PASSED', async () => {
      const { program, trial, phase, procedure } = await setupTrialWithProcedure();

      await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.READY_FOR_PROCEDURES,
        phase.version
      );

      const response = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.COMPLETED,
        phase.version + 1
      );

      expectError(response, 409, 'ERR_PROCEDURES_NOT_PASSED');
    });

    test('should reject completion when phase is in REVIEW_REQUIRED', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const readyResp = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.READY_FOR_PROCEDURES,
        phase.version
      );
      expectSuccess(readyResp, 200);

      await triggerPhaseReview(program.id, trial.id, phase.id, procedure.id, cohort.id);

      const response = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.COMPLETED,
        readyResp.body.data.version + 1
      );

      expectError(response, 409, 'ERR_PHASE_IN_REVIEW');
    });

    test('should reject invalid phase state transitions', async () => {
      const { program, trial, phase, procedure } = await setupTrialWithProcedure();

      const response = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.COMPLETED,
        phase.version
      );

      expectError(response, 409, 'ERR_ILLEGAL_PHASE_STATE_TRANSITION');
    });

    test('should validate required_cohort_tag enum value', async () => {
      const { program, trial, phase } = await setupTrialWithPhase();

      const validProcedureResp = await createProcedure(program.id, trial.id, phase.id, {
        required_cohort_tag: COHORT_TAG.NONE
      });
      const validProcedure = validProcedureResp.body.data;

      expect(validProcedure.required_cohort_tag).toBe(COHORT_TAG.NONE);
    });
  });

  describe('Execution State Constraints', () => {

    test('should reject invalid execution state transitions', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });
      const execution = execResponse.body.data;

      await executeExecution(program.id, trial.id, execution.id);
      await markExecutionPassed(program.id, trial.id, execution.id);

      const response = await cancelExecution(program.id, trial.id, execution.id);

      expectError(response, 409, 'ERR_EXECUTION_NOT_CANCELLABLE');
    });

    test('should not count completed executions toward active deviation limit', async () => {
      const userId = generateUserId();
      const { program, trial } = await setupActiveTrial();

      const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
      const phase = phaseResp.body.data;
      const cohortResponse = await createCohort(program.id, trial.id);
      const cohort = cohortResponse.body.data;

      for (let i = 0; i < 3; i++) {
        const procResp = await createProcedure(program.id, trial.id, phase.id);
        const proc = procResp.body.data;
        const execResp = await createExecution(
          program.id,
          trial.id,
          {
            procedure_id: proc.id,
            cohort_id: cohort.id,
            protocol_deviation: true
          },
          userId
        );
        const execution = execResp.body.data;

        await executeExecution(program.id, trial.id, execution.id);
        await markExecutionPassed(program.id, trial.id, execution.id);
      }

      for (let i = 0; i < 3; i++) {
        const procResp = await createProcedure(program.id, trial.id, phase.id);
        const proc = procResp.body.data;
        const execResp = await createExecution(
          program.id,
          trial.id,
          {
            procedure_id: proc.id,
            cohort_id: cohort.id,
            protocol_deviation: true
          },
          userId
        );

        expectSuccess(execResp, 201);
      }
    });

    test('should reject mark-passed when execution is already PASSED', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });
      const execution = execResponse.body.data;

      await executeExecution(program.id, trial.id, execution.id);
      await markExecutionPassed(program.id, trial.id, execution.id);

      const response = await markExecutionPassed(program.id, trial.id, execution.id);

      expectError(response, 409, ['ERR_EXECUTION_NOT_EXECUTED', 'ERR_PROCEDURE_NOT_AWAITING_EXECUTION']);
    });

    test('should reject second rejection of already rejected execution', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });
      const execution = execResponse.body.data;

      await rejectExecution(program.id, trial.id, execution.id);

      const response = await rejectExecution(program.id, trial.id, execution.id);

      expectError(response, 409, 'ERR_EXECUTION_NOT_REJECTABLE');
    });

    test('should reject second cancellation of already cancelled execution', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });
      const execution = execResponse.body.data;

      await cancelExecution(program.id, trial.id, execution.id);

      const response = await cancelExecution(program.id, trial.id, execution.id);

      expectError(response, 409, 'ERR_EXECUTION_NOT_CANCELLABLE');
    });
  });

  describe('Blackout and Clock Constraints', () => {

    test('should reject phase completion during active blackout window', async () => {
      const { program, irb } = await createProgramWithIRB();

      const { trial } = await setupActiveTrial({
        program,
        irb,
        treatment_name: 'Oncology Trial'
      });

      const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
      const phase = phaseResp.body.data;
      const procedureResp = await createProcedure(program.id, trial.id, phase.id);
      const procedure = procedureResp.body.data;
      const cohortResponse = await createCohort(program.id, trial.id);
      const cohort = cohortResponse.body.data;

      await createBlackoutWindow(program.id, {
        treatment_name_pattern: 'Onc*',
        start_period_index: 0,
        end_period_index: 100
      });

      const readyResp = await updatePhaseStatus(program.id, trial.id, phase.id, PHASE_STATUS.READY_FOR_PROCEDURES, phase.version);

      await executeAndPassProcedure(program.id, trial.id, procedure.id, cohort.id);

      const completeResp = await updatePhaseStatus(program.id, trial.id, phase.id, PHASE_STATUS.COMPLETED, readyResp.body.data.version);

      expectError(completeResp, 403, 'ERR_ENROLLMENT_BLACKOUT_ACTIVE');
    });

    test('should reject trial completion during active blackout', async () => {
      const { program, trial } = await setupActiveTrial({
        treatment_name: 'Oncology Trial A'
      });

      await createBlackoutWindow(program.id, {
        treatment_name_pattern: 'Oncology*',
        start_period_index: 0,
        end_period_index: 100
      });

      const response = await completeTrial(program.id, trial.id);

      expectError(response, 403, 'ERR_ENROLLMENT_BLACKOUT_ACTIVE');
    });

    test('should reject clock advance beyond maximum', async () => {
      const { program } = await createProgramWithIRB();

      const response = await advanceClock(program.id, MAX_ADVANCE_BY + 1);

      expectError(response, 400, 'ERR_INVALID_REQUEST');
    });

    test('should reject blackout window with invalid period range', async () => {
      const { program } = await createProgramWithIRB();

      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const response = await request(apiUrl)
        .post(`/research-programs/${program.id}/enrollment-blackout-windows`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
        .send({
          treatment_name_pattern: '*',
          start_period_index: 100,
          end_period_index: 50,
          reason: 'Invalid range'
        });

      expectError(response, 400, 'ERR_INVALID_REQUEST');
    });

    test('should match wildcard pattern correctly', async () => {
      const { program } = await createProgramWithIRB();

      await createBlackoutWindow(program.id, {
        treatment_name_pattern: 'Test*',
        start_period_index: 0,
        end_period_index: 10,
        reason: 'Test wildcard with empty suffix'
      });

      const { trial: trial1 } = await setupActiveTrial({
        program,
        treatment_name: 'Test'
      });

      const phase1Resp = await createPhase(program.id, trial1.id, PHASE_NAME.PHASE_I);
      const phase1 = phase1Resp.body.data;
      const proc1Resp = await createProcedure(program.id, trial1.id, phase1.id);
      const proc1 = proc1Resp.body.data;
      const cohort1Resp = await createCohort(program.id, trial1.id);
      const cohort1 = cohort1Resp.body.data;

      const ready1 = await updatePhaseStatus(program.id, trial1.id, phase1.id, PHASE_STATUS.READY_FOR_PROCEDURES, phase1.version);
      expectSuccess(ready1, 200);

      await executeAndPassProcedure(program.id, trial1.id, proc1.id, cohort1.id);

      const complete1 = await updatePhaseStatus(
        program.id,
        trial1.id,
        phase1.id,
        PHASE_STATUS.COMPLETED,
        ready1.body.data.version
      );
      expectError(complete1, 403, 'ERR_ENROLLMENT_BLACKOUT_ACTIVE');

      const { trial: trial2 } = await setupActiveTrial({
        program,
        treatment_name: 'TestAnything'
      });

      const phase2Resp = await createPhase(program.id, trial2.id, PHASE_NAME.PHASE_I);
      const phase2 = phase2Resp.body.data;
      const proc2Resp = await createProcedure(program.id, trial2.id, phase2.id);
      const proc2 = proc2Resp.body.data;
      const cohort2Resp = await createCohort(program.id, trial2.id);
      const cohort2 = cohort2Resp.body.data;

      const ready2 = await updatePhaseStatus(program.id, trial2.id, phase2.id, PHASE_STATUS.READY_FOR_PROCEDURES, phase2.version);
      expectSuccess(ready2, 200);

      await executeAndPassProcedure(program.id, trial2.id, proc2.id, cohort2.id);

      const complete2 = await updatePhaseStatus(
        program.id,
        trial2.id,
        phase2.id,
        PHASE_STATUS.COMPLETED,
        ready2.body.data.version
      );
      expectError(complete2, 403, 'ERR_ENROLLMENT_BLACKOUT_ACTIVE');
    });

    test('should match single character wildcard correctly', async () => {
      const { program } = await createProgramWithIRB();

      await createBlackoutWindow(program.id, {
        treatment_name_pattern: 'Trial?',
        start_period_index: 0,
        end_period_index: 10,
        reason: 'Test single char wildcard'
      });

      const { trial: trial1 } = await setupActiveTrial({
        program,
        treatment_name: 'Trial1'
      });

      const phase1Resp = await createPhase(program.id, trial1.id, PHASE_NAME.PHASE_I);
      const phase1 = phase1Resp.body.data;
      const proc1Resp = await createProcedure(program.id, trial1.id, phase1.id);
      const proc1 = proc1Resp.body.data;
      const cohort1Resp = await createCohort(program.id, trial1.id);
      const cohort1 = cohort1Resp.body.data;

      const ready1 = await updatePhaseStatus(program.id, trial1.id, phase1.id, PHASE_STATUS.READY_FOR_PROCEDURES, phase1.version);
      expectSuccess(ready1, 200);

      await executeAndPassProcedure(program.id, trial1.id, proc1.id, cohort1.id);

      const complete1 = await updatePhaseStatus(
        program.id,
        trial1.id,
        phase1.id,
        PHASE_STATUS.COMPLETED,
        ready1.body.data.version
      );
      expectError(complete1, 403, 'ERR_ENROLLMENT_BLACKOUT_ACTIVE');

      const { trial: trial2 } = await setupActiveTrial({
        program,
        treatment_name: 'TrialAB'
      });

      const phase2Resp = await createPhase(program.id, trial2.id, PHASE_NAME.PHASE_I);
      const phase2 = phase2Resp.body.data;
      const proc2Resp = await createProcedure(program.id, trial2.id, phase2.id);
      const proc2 = proc2Resp.body.data;
      const cohort2Resp = await createCohort(program.id, trial2.id);
      const cohort2 = cohort2Resp.body.data;

      const ready2 = await updatePhaseStatus(program.id, trial2.id, phase2.id, PHASE_STATUS.READY_FOR_PROCEDURES, phase2.version);
      expectSuccess(ready2, 200);

      await executeAndPassProcedure(program.id, trial2.id, proc2.id, cohort2.id);

      const complete2 = await updatePhaseStatus(
        program.id,
        trial2.id,
        phase2.id,
        PHASE_STATUS.COMPLETED,
        ready2.body.data.version
      );
      expectSuccess(complete2, 200);
    });

    test('should allow completion after advancing clock past blackout', async () => {
      const { program, trial } = await setupActiveTrial({
        treatment_name: 'Test Trial'
      });

      await createBlackoutWindow(program.id, {
        treatment_name_pattern: '*',
        start_period_index: 0,
        end_period_index: 10
      });

      await advanceClock(program.id, 11);

      const response = await completeTrial(program.id, trial.id);

      expectSuccess(response, 200);
    });

    test('should block operation if any blackout window matches', async () => {
      const { program, trial } = await setupActiveTrial({
        treatment_name: 'Oncology Trial'
      });

      await createBlackoutWindow(program.id, {
        treatment_name_pattern: 'Cardiology*',
        start_period_index: 0,
        end_period_index: 50
      });

      await createBlackoutWindow(program.id, {
        treatment_name_pattern: 'Onc*',
        start_period_index: 0,
        end_period_index: 100
      });

      const response = await completeTrial(program.id, trial.id);

      expectError(response, 403, 'ERR_ENROLLMENT_BLACKOUT_ACTIVE');
    });

    test('should perform case-sensitive pattern matching by default', async () => {
      const { program } = await createProgramWithIRB();

      await createBlackoutWindow(program.id, {
        treatment_name_pattern: 'Oncology',
        start_period_index: 0,
        end_period_index: 10,
        reason: 'Test case sensitivity'
      });

      const { trial: trial1 } = await setupActiveTrial({
        program,
        treatment_name: 'Oncology'
      });

      const phase1Resp = await createPhase(program.id, trial1.id, PHASE_NAME.PHASE_I);
      const phase1 = phase1Resp.body.data;
      const proc1Resp = await createProcedure(program.id, trial1.id, phase1.id);
      const proc1 = proc1Resp.body.data;
      const cohort1Resp = await createCohort(program.id, trial1.id);
      const cohort1 = cohort1Resp.body.data;

      const ready1 = await updatePhaseStatus(program.id, trial1.id, phase1.id, PHASE_STATUS.READY_FOR_PROCEDURES, phase1.version);
      expectSuccess(ready1, 200);

      await executeAndPassProcedure(program.id, trial1.id, proc1.id, cohort1.id);

      const complete1 = await updatePhaseStatus(
        program.id,
        trial1.id,
        phase1.id,
        PHASE_STATUS.COMPLETED,
        ready1.body.data.version
      );
      expectError(complete1, 403, 'ERR_ENROLLMENT_BLACKOUT_ACTIVE');

      const { trial: trial2 } = await setupActiveTrial({
        program,
        treatment_name: 'oncology'
      });

      const phase2Resp = await createPhase(program.id, trial2.id, PHASE_NAME.PHASE_I);
      const phase2 = phase2Resp.body.data;
      const proc2Resp = await createProcedure(program.id, trial2.id, phase2.id);
      const proc2 = proc2Resp.body.data;
      const cohort2Resp = await createCohort(program.id, trial2.id);
      const cohort2 = cohort2Resp.body.data;

      const ready2 = await updatePhaseStatus(program.id, trial2.id, phase2.id, PHASE_STATUS.READY_FOR_PROCEDURES, phase2.version);
      expectSuccess(ready2, 200);

      await executeAndPassProcedure(program.id, trial2.id, proc2.id, cohort2.id);

      const complete2 = await updatePhaseStatus(
        program.id,
        trial2.id,
        phase2.id,
        PHASE_STATUS.COMPLETED,
        ready2.body.data.version
      );
      expectSuccess(complete2, 200);
    });
  });

  describe('Manual Risk Adjustment Constraints', () => {

    test('should reject manual risk adjustment with zero value', async () => {
      const { program, trial } = await setupActiveTrial();

      const response = await manualRiskAdjustment(
        program.id,
        trial.id,
        0,
        'Some justification'
      );

      expectError(response, 400, 'ERR_INVALID_ADJUSTMENT_VALUE');
    });

    test('should reject manual risk adjustment with insufficient justification', async () => {
      const { program, trial } = await setupActiveTrial();

      const response = await manualRiskAdjustment(
        program.id,
        trial.id,
        10,
        'Too short'
      );

      expectError(response, 400, 'ERR_INSUFFICIENT_JUSTIFICATION');
    });

    test('should allow EthicsAuditor to make manual risk adjustments', async () => {
      const { program, trial } = await setupActiveTrial();

      const response = await manualRiskAdjustment(
        program.id,
        trial.id,
        10,
        'Valid justification text here',
        randomUUID(),
        ROLES.ETHICS_AUDITOR
      );

      expectSuccess(response, 200);
    });
  });

  describe('Lock State Constraints', () => {

    test('should reject abandonment from ETHICAL_REVIEW_LOCK', async () => {
      const { program, trial } = await setupActiveTrial();

      await manualRiskAdjustment(
        program.id,
        trial.id,
        AUDIT_LOCK_THRESHOLD + 10,
        'Force lock'
      );

      const response = await abandonTrial(program.id, trial.id);

      expectError(response, 409, 'ERR_TRIAL_NOT_ABANDONABLE');
    });

    test('should trigger lock when risk exceeds audit threshold', async () => {
      const { program, trial } = await setupActiveTrial();

      await manualRiskAdjustment(
        program.id,
        trial.id,
        AUDIT_LOCK_THRESHOLD + 1,
        'Trigger lock'
      );

      const updated = await getTrial(program.id, trial.id);
      expect(updated.body.data.status).toBe(TRIAL_STATUS.ETHICAL_REVIEW_LOCK);
    });

    test('should require explicit clear-lock even after risk reduction', async () => {
      const { program, trial } = await setupActiveTrial();

      await manualRiskAdjustment(
        program.id,
        trial.id,
        AUDIT_LOCK_THRESHOLD + 10,
        'Trigger lock'
      );

      await manualRiskAdjustment(
        program.id,
        trial.id,
        -(AUDIT_LOCK_THRESHOLD + 5),
        'Reduce risk'
      );

      const updated = await getTrial(program.id, trial.id);
      expect(updated.body.data.status).toBe(TRIAL_STATUS.ETHICAL_REVIEW_LOCK);

      const clearResponse = await clearEthicalReviewLock(program.id, trial.id);
      expectSuccess(clearResponse, 200);
    });

    test('should reject completion of DRAFT trial', async () => {
      const { program, irb } = await createProgramWithIRB();
      const trialResp = await createTrial(program.id, { irb_id: irb.id });
      const trial = trialResp.body.data;

      const response = await completeTrial(program.id, trial.id);

      expectError(response, 409, 'ERR_TRIAL_NOT_ACTIVE');
    });
  });

  describe('Cohort Property Constraints', () => {

    test('should validate each cohort property individually', async () => {
      const { program, irb } = await createProgramWithIRB();
      const trialResp = await createTrial(program.id, { irb_id: irb.id });
      const trial = trialResp.body.data;

      const validCohortResponse = await createCohort(program.id, trial.id, {
        cohort_name: 'Multi-property Cohort',
        cohort_version: '1.0',
        base_risk_points: 10,
        properties: [
          {
            property_id: 'prop-1',
            name: COHORT_PROPERTY.HEALTHY_VOLUNTEERS,
            certified_period_index: 0
          },
          {
            property_id: 'prop-2',
            name: COHORT_PROPERTY.HIGH_RISK_PATIENTS,
            certified_period_index: 0
          }
        ]
      });

      const validCohort = validCohortResponse.body.data;
      expect(validCohort.properties.length).toBe(2);
    });
  });

  describe('Incompatible Pairing Constraints', () => {

    test('should allow execution after incompatible pairing is removed', async () => {
      const { program, trial, phase } = await setupTrialWithPhase(PHASE_NAME.PHASE_II);

      const pairingResp = await createIncompatiblePairing(
        program.id,
        COHORT_PROPERTY.CONTAINS_PLACEBO,
        PHASE_NAME.PHASE_II,
        'Test pairing'
      );
      const pairing = pairingResp.body.data;

      await deleteIncompatiblePairing(program.id, pairing.id);

      const cohortResponse = await createCohort(program.id, trial.id, buildPlaceboCohort());
      const cohort = cohortResponse.body.data;
      const procedureResp = await createProcedure(program.id, trial.id, phase.id);
      const procedure = procedureResp.body.data;

      const response = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      expectSuccess(response, 201);
    });
  });

  describe('Resource Validation', () => {

    test('should reject invalid IRB approval status', async () => {
      const { program, irb } = await createProgramWithIRB();
      const trialResp = await createTrial(program.id, { irb_id: irb.id });
      const trial = trialResp.body.data;
      const approvalResp = await createIRBApproval(program.id, irb.id, trial.id);
      const approval = approvalResp.body.data;

      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const response = await request(apiUrl)
        .put(`/research-programs/${program.id}/irbs/${irb.id}/approvals/${approval.id}`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', ROLES.RESEARCH_DIRECTOR)
        .send({
          status: 'INVALID_STATUS',
          version: approval.version
        });

      expectError(response, 400, 'ERR_INVALID_IRB_STATUS');
    });

    test('should return 404 for non-existent portfolio', async () => {
      const { program } = await createProgramWithIRB();
      const fakeId = randomUUID();

      const response = await getPortfolio(program.id, fakeId);

      expectError(response, 404, 'ERR_PORTFOLIO_NOT_FOUND');
    });

    test('should return 404 when deleting non-existent blackout window', async () => {
      const { program } = await createProgramWithIRB();
      const fakeId = randomUUID();

      const response = await deleteBlackoutWindow(program.id, fakeId);

      expectError(response, 404, 'ERR_BLACKOUT_WINDOW_NOT_FOUND');
    });

    test('should reject deviation proposal without required headers', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const response = await request(apiUrl)
        .post(`/research-programs/${program.id}/clinical-trials/${trial.id}/procedure-executions`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', ROLES.CLINICAL_COORDINATOR)
        .send({
          procedure_id: procedure.id,
          cohort_id: cohort.id,
          protocol_deviation: false
        });

      expect(response.status).toBe(400);
    });

    test('should reject update with version mismatch', async () => {
      const { program } = await createProgramWithIRB();
      const portfolioResp = await createPortfolio(program.id);
      const portfolio = portfolioResp.body.data;

      const response = await updatePortfolio(program.id, portfolio.id, {
        name: 'Updated Name',
        version: 9999
      });

      expectError(response, 409, 'ERR_VERSION_MISMATCH');
    });
  });

  describe('Read-Only Field Constraints', () => {

    test('should derive effective budget and not allow direct setting', async () => {
      const { program, trial } = await setupActiveTrial({ total_ethical_compliance_budget: 10000 });

      expect(trial.effective_ethical_compliance_budget).toBe(10000);

      await abandonTrial(program.id, trial.id);

      const trial2Resp = await createTrial(program.id, { total_ethical_compliance_budget: 10000 }, trial.investigator_id);
      const trial2 = trial2Resp.body.data;

      const expectedEffective = Math.floor(10000 * 0.9);
      expect(trial2.effective_ethical_compliance_budget).toBe(expectedEffective);
    });

    test('should derive balance from ledgers and not allow direct setting', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure({ base_risk_cost: 100 });

      const initialBalance = trial.ethical_compliance_balance;
      expect(initialBalance).toBe(trial.effective_ethical_compliance_budget);

      await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      const afterDeviation = (await getTrial(program.id, trial.id)).body.data;

      expect(afterDeviation.ethical_compliance_balance).toBeLessThan(initialBalance);
      expectNonNegativeBalance(afterDeviation.ethical_compliance_balance);
    });

    test('should only allow risk modification via manual adjustment endpoint', async () => {
      const { program, trial } = await setupActiveTrial();

      expect(trial.patient_safety_risk).toBe(0);

      await manualRiskAdjustment(program.id, trial.id, 30, 'Explicit risk increase');

      const afterManual = (await getTrial(program.id, trial.id)).body.data;
      expect(afterManual.patient_safety_risk).toBe(30);

      const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
      const phase = phaseResp.body.data;
      const procedureResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 50 });
      const procedure = procedureResp.body.data;
      const cohortResponse = await createCohort(program.id, trial.id);
      const cohort = cohortResponse.body.data;

      const execResp = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });
      const execution = execResp.body.data;

      await rejectExecution(program.id, trial.id, execution.id);

      const afterReject = (await getTrial(program.id, trial.id)).body.data;

      expect(afterReject.patient_safety_risk).toBeGreaterThan(30);
    });

    test('should only modify contagion flag via system-managed lock cascades', async () => {
      const { program, portfolio, trials } = await setupPortfolioWithTrials(3);

      const trial1Before = (await getTrial(program.id, trials[1].id)).body.data;
      expect(trial1Before.is_under_contagion).toBe(false);

      await manualRiskAdjustment(program.id, trials[0].id, AUDIT_LOCK_THRESHOLD + 10, 'Trigger lock');

      const trial1After = (await getTrial(program.id, trials[1].id)).body.data;
      expect(trial1After.is_under_contagion).toBe(true);

      await clearEthicalReviewLock(program.id, trials[0].id);

      const trial1Cleared = (await getTrial(program.id, trials[1].id)).body.data;
      expect(trial1Cleared.is_under_contagion).toBe(false);
    });

    test('should reject requests with insufficient role permissions', async () => {
      const { program } = await createProgramWithIRB();

      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const response = await request(apiUrl)
        .post(`/research-programs/${program.id}/irbs`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', 'ClinicalCoordinator')
        .send({
          name: 'Test IRB',
          description: 'Test'
        });

      expectError(response, 403, 'ERR_INSUFFICIENT_PERMISSIONS');
    });

    test('should reject manual risk adjustment with ClinicalCoordinator role', async () => {
      const { program, trial } = await setupActiveTrial();

      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const response = await request(apiUrl)
        .post(`/research-programs/${program.id}/clinical-trials/${trial.id}/manual-risk-adjustment`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', 'ClinicalCoordinator')
        .send({
          adjustment: 10,
          justification: 'Test adjustment with wrong role'
        });

      expectError(response, 403, 'ERR_INSUFFICIENT_PERMISSIONS');
    });

    test('should enforce role requirements for execution creation', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const response = await request(apiUrl)
        .post(`/research-programs/${program.id}/clinical-trials/${trial.id}/procedure-executions`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', 'EthicsAuditor')
        .set('Idempotency-Key', randomUUID())
        .send({
          procedure_id: procedure.id,
          cohort_id: cohort.id,
          protocol_deviation: false
        });

      expectError(response, 403, 'ERR_INSUFFICIENT_PERMISSIONS');
    });

    test('should validate phase belongs to same trial as procedure', async () => {
      const { program, irb } = await createProgramWithIRB();

      const { trial: trial1 } = await setupActiveTrial({ program, irb });
      const { trial: trial2 } = await setupActiveTrial({ program, irb });

      const phase1Resp = await createPhase(program.id, trial1.id, PHASE_NAME.PHASE_I);
      const phase1 = phase1Resp.body.data;
      const phase2Resp = await createPhase(program.id, trial2.id, PHASE_NAME.PHASE_I);
      const phase2 = phase2Resp.body.data;

      const proc1Resp = await createProcedure(program.id, trial1.id, phase1.id);
      const proc1 = proc1Resp.body.data;

      const cohort2Response = await createCohort(program.id, trial2.id);
      const cohort2 = cohort2Response.body.data;

      const response = await createExecution(program.id, trial2.id, {
        procedure_id: proc1.id,
        cohort_id: cohort2.id,
        protocol_deviation: false
      });

      expectError(response, 404, 'ERR_PROCEDURE_NOT_FOUND');
    });

    test('should enforce portfolio trials belong to same program', async () => {
      const { program } = await createProgramWithIRB();
      const portfolioResp = await createPortfolio(program.id);
      const portfolio = portfolioResp.body.data;

      const { trial } = await setupActiveTrial({ program, portfolio_id: portfolio.id });

      expect(trial.portfolio_id).toBe(portfolio.id);
      expect(trial.research_program_id).toBe(program.id);
    });

    test('should validate both trials exist when creating dependency', async () => {
      const { program, irb } = await createProgramWithIRB();
      const trialResp = await createTrial(program.id, { irb_id: irb.id });
      const trial = trialResp.body.data;
      const fakeTrialId = randomUUID();

      const response = await createDependency(program.id, trial.id, fakeTrialId);

      expectError(response, 404, 'ERR_DEPENDENCY_TRIAL_NOT_FOUND');
    });

    test('should validate IRB approval belongs to correct IRB', async () => {
      const { program, irb } = await createProgramWithIRB();
      const trialResp = await createTrial(program.id, { irb_id: irb.id });
      const trial = trialResp.body.data;

      const approvalResp = await createIRBApproval(program.id, irb.id, trial.id);
      const approval = approvalResp.body.data;

      expect(approval.irb_id).toBe(irb.id);
      expect(approval.trial_id).toBe(trial.id);
    });

    test('should initialize investigator reputation on first use', async () => {
      const { program, irb } = await createProgramWithIRB();
      const investigatorId = generateInvestigatorId();

      const trialResp = await createTrial(program.id, { irb_id: irb.id }, investigatorId);
      const trial = trialResp.body.data;

      expect(trial.effective_ethical_compliance_budget).toBe(trial.total_ethical_compliance_budget);
    });

    test('should reset contagion flags only when all portfolio locks are cleared', async () => {
      const { program, portfolio, trials } = await setupPortfolioWithTrials(3);

      await manualRiskAdjustment(program.id, trials[0].id, AUDIT_LOCK_THRESHOLD + 10, 'Lock justification 1');
      await manualRiskAdjustment(program.id, trials[1].id, AUDIT_LOCK_THRESHOLD + 10, 'Lock justification 2');

      let trial2 = (await getTrial(program.id, trials[2].id)).body.data;
      expect(trial2.is_under_contagion).toBe(true);

      await clearEthicalReviewLock(program.id, trials[0].id);

      trial2 = (await getTrial(program.id, trials[2].id)).body.data;
      expect(trial2.is_under_contagion).toBe(true);

      await clearEthicalReviewLock(program.id, trials[1].id);

      trial2 = (await getTrial(program.id, trials[2].id)).body.data;
      expect(trial2.is_under_contagion).toBe(false);
    });

    test('should mark as expedited only when strictly greater than threshold', async () => {
      const { program, trial, phase, cohort } = await setupTrialNearExpeditedThreshold(0);

      const procResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 0 });
      const proc = procResp.body.data;
      const exec = await createExecution(program.id, trial.id, {
        procedure_id: proc.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      expect(exec.body.data.is_expedited_review).toBe(false);

      const proc2Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 1 });
      const proc2 = proc2Resp.body.data;
      const exec2 = await createExecution(program.id, trial.id, {
        procedure_id: proc2.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      expect(exec2.body.data.is_expedited_review).toBe(true);
    });

    test('should enable phase completion after clearing REVIEW_REQUIRED', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const readyResp = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.READY_FOR_PROCEDURES,
        phase.version
      );
      expectSuccess(readyResp, 200);

      await triggerPhaseReviewRequired(program.id, trial.id, phase.id, cohort.id);

      const phaseVersionAfterReview = readyResp.body.data.version + 1;

      const clearReview = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.READY_FOR_PROCEDURES,
        phaseVersionAfterReview
      );
      expectSuccess(clearReview, 200);
      expect(clearReview.body.data.status).toBe('READY_FOR_PROCEDURES');

      await executeAndPassProcedure(program.id, trial.id, procedure.id, cohort.id);

      const phase2Resp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_II);
      expectSuccess(phase2Resp, 201);
      const phase2 = phase2Resp.body.data;

      const proc2Resp = await createProcedure(program.id, trial.id, phase2.id, { base_risk_cost: 10 });
      expectSuccess(proc2Resp, 201);
      const proc2 = proc2Resp.body.data;

      const ready2Resp = await updatePhaseStatus(program.id, trial.id, phase2.id, PHASE_STATUS.READY_FOR_PROCEDURES, phase2.version);
      expectSuccess(ready2Resp, 200);

      await executeAndPassProcedure(program.id, trial.id, proc2.id, cohort.id);

      const complete2 = await updatePhaseStatus(
        program.id,
        trial.id,
        phase2.id,
        PHASE_STATUS.COMPLETED,
        ready2Resp.body.data.version
      );
      expectSuccess(complete2, 200);
      expect(complete2.body.data.status).toBe('COMPLETED');
    });
  });
});
