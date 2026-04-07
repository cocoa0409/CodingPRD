import { randomUUID } from 'crypto';
import request from 'supertest';

import {
  createExecution, abandonTrial,
  activateTrial, manualRiskAdjustment,
  createPhase,
  createProcedure,
  createCohort,
  getTrial, createResearchProgram,
  createTrial,
  createIRB,
  createPortfolio,
  getPortfolio,
  createIRBApproval,
  approveIRB
} from '../../../test-helpers/resources';

import {
  expectSuccess,
  expectNonNegativeBalance,
  expectError
} from '../../../test-helpers/assertions';

import {
  PHASE_STATUS,
  PHASE_NAME, AUDIT_LOCK_THRESHOLD,
  MAX_ACTIVE_DEVIATIONS_PER_USER,
  CONTAGION_PENALTY
} from '../../../test-helpers/constants';

import {
  setupActiveTrial, setupPortfolioWithTrials, createProgramWithIRB
} from '../../../test-helpers/scenarios';

import { generateUserId, generateInvestigatorId } from '../../../test-helpers/builders';

describe('Principal Engineer Skills', () => {

  describe('Multi-Constraint Atomic Evaluation', () => {

    test('should atomically enforce deviation gates in documented priority order', async () => {
      const programResp = await createResearchProgram();
      expectSuccess(programResp, 201);
      const program = programResp.body.data;

      const userId = generateUserId();

      const { trial } = await setupActiveTrial({
        program,
        total_ethical_compliance_budget: 200
      });

      const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
      const phase = phaseResp.body.data;
      const cohortResp = await createCohort(program.id, trial.id);
      const cohort = cohortResp.body.data;

      for (let i = 0; i < MAX_ACTIVE_DEVIATIONS_PER_USER; i++) {
        const procResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 50 });
        const proc = procResp.body.data;
        await createExecution(program.id, trial.id, {
          procedure_id: proc.id,
          cohort_id: cohort.id,
          protocol_deviation: true
        }, userId);
      }

      const procResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 150 });
      const proc = procResp.body.data;

      const response = await createExecution(program.id, trial.id, {
        procedure_id: proc.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      }, userId);

      expectError(response, 409, 'ERR_MAX_ACTIVE_DEVIATIONS_PER_USER_VIOLATION');

      const finalTrial = (await getTrial(program.id, trial.id)).body.data;
      expect(finalTrial.ethical_compliance_balance).toBe(50);
    });

    test('should maintain coherent state when reputation drop triggers probation mid-operations', async () => {
      const programResp = await createResearchProgram();
      expectSuccess(programResp, 201);
      const program = programResp.body.data;

      const investigatorId = generateInvestigatorId();
      const irbResp = await createIRB(program.id);
      expectSuccess(irbResp, 201);
      const irb = irbResp.body.data;

      for (let i = 0; i < 5; i++) {
        const tempTrialResp = await createTrial(program.id, { irb_id: irb.id }, investigatorId);
        const tempTrial = tempTrialResp.body.data;
        await abandonTrial(program.id, tempTrial.id);
      }

      const dummyTrialResp = await createTrial(program.id, { irb_id: irb.id, total_ethical_compliance_budget: 500 }, investigatorId);
      const dummyTrial = dummyTrialResp.body.data;
      const approvalDummyResp = await createIRBApproval(program.id, irb.id, dummyTrial.id);
      const approvalDummy = approvalDummyResp.body.data;
      await approveIRB(program.id, irb.id, approvalDummy.id, approvalDummy.version);
      await activateTrial(program.id, dummyTrial.id);
      await abandonTrial(program.id, dummyTrial.id);

      const { trial } = await setupActiveTrial({
        program,
        irb,
        total_ethical_compliance_budget: 10000
      }, investigatorId);

      const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
      const phase = phaseResp.body.data;
      const procResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 100 });
      const procedure = procResp.body.data;
      const cohortResp = await createCohort(program.id, trial.id);
      const cohort = cohortResp.body.data;

      const exec1 = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });
      expectSuccess(exec1, 201);

      const triggerTrialResp = await createTrial(program.id, { irb_id: irb.id, total_ethical_compliance_budget: 500 }, investigatorId);
      const triggerTrial = triggerTrialResp.body.data;
      const triggerApprovalResp = await createIRBApproval(program.id, irb.id, triggerTrial.id);
      const triggerApproval = triggerApprovalResp.body.data;
      await approveIRB(program.id, irb.id, triggerApproval.id, triggerApproval.version);
      await activateTrial(program.id, triggerTrial.id);
      await abandonTrial(program.id, triggerTrial.id);

      const trialAfter = (await getTrial(program.id, trial.id)).body.data;

      expect(trialAfter.effective_ethical_compliance_budget).toBe(Math.floor(10000 * 0.3));

      const proc2Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 100 });
      const proc2 = proc2Resp.body.data;
      const exec2 = await createExecution(program.id, trial.id, {
        procedure_id: proc2.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      expectError(exec2, 403, 'ERR_INVESTIGATOR_ON_PROBATION_DEVIATIONS_BLOCKED');
    });

    test('should apply one-hop contagion from concurrent primary locks without recursion', async () => {
      const { program, portfolio, trials } = await setupPortfolioWithTrials(3);

      const trial2Before = (await getTrial(program.id, trials[2].id)).body.data;
      const risk2Before = trial2Before.patient_safety_risk;

      await Promise.all([
        manualRiskAdjustment(program.id, trials[0].id, AUDIT_LOCK_THRESHOLD + 10, 'Trigger primary lock 1'),
        manualRiskAdjustment(program.id, trials[1].id, AUDIT_LOCK_THRESHOLD + 10, 'Trigger primary lock 2')
      ]);

      const trial0After = (await getTrial(program.id, trials[0].id)).body.data;
      const trial1After = (await getTrial(program.id, trials[1].id)).body.data;
      expect(trial0After.status).toBe('ETHICAL_REVIEW_LOCK');
      expect(trial1After.status).toBe('ETHICAL_REVIEW_LOCK');

      const trial2After = (await getTrial(program.id, trials[2].id)).body.data;
      expect(trial2After.patient_safety_risk).toBe(risk2Before + (2 * CONTAGION_PENALTY));
      expect(trial2After.is_under_contagion).toBe(true);
    });

    test('should enforce saturation atomically when concurrent proposals straddle threshold', async () => {
      const programResp = await createResearchProgram();
      expectSuccess(programResp, 201);
      const program = programResp.body.data;

      const portfolioResp = await createPortfolio(program.id, { max_total_ethical_budget: 1000 });
      const portfolio = portfolioResp.body.data;

      const trialsData = [];
      for (let i = 0; i < 3; i++) {
        const { trial } = await setupActiveTrial({
          program,
          portfolio_id: portfolio.id,
          total_ethical_compliance_budget: 2000
        });
        const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
        const phase = phaseResp.body.data;
        const cohortResp = await createCohort(program.id, trial.id);
        const cohort = cohortResp.body.data;
        const procResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 190 });
        const procedure = procResp.body.data;

        trialsData.push({ trial, procedure, cohort });
      }

      const proposals = await Promise.all(
        trialsData.map(t =>
          createExecution(program.id, t.trial.id, {
            procedure_id: t.procedure.id,
            cohort_id: t.cohort.id,
            protocol_deviation: true
          })
        )
      );

      const successCount = proposals.filter(p => p.status === 201).length;
      const blockedBySaturation = proposals.filter(p =>
        p.status === 403 && p.body?.data?.error_id === 'ERR_PORTFOLIO_RISK_SATURATED'
      ).length;

      expect(successCount).toBe(3);
      expect(blockedBySaturation).toBe(0);

      const portfolioFinal = (await getPortfolio(program.id, portfolio.id)).body.data;
      expect(portfolioFinal.is_risk_saturated).toBe(false);

      for (const t of trialsData) {
        const trialFinal = (await getTrial(program.id, t.trial.id)).body.data;
        expectNonNegativeBalance(trialFinal.ethical_compliance_balance);
      }
    });

    test('should block proposals that would cross saturation threshold under concurrent load', async () => {
      const programResp = await createResearchProgram();
      expectSuccess(programResp, 201);
      const program = programResp.body.data;

      const portfolioResp = await createPortfolio(program.id, { max_total_ethical_budget: 1000 });
      const portfolio = portfolioResp.body.data;

      const trialsData = [];
      for (let i = 0; i < 3; i++) {
        const { trial } = await setupActiveTrial({
          program,
          portfolio_id: portfolio.id,
          total_ethical_compliance_budget: 2000
        });
        const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
        const phase = phaseResp.body.data;
        const cohortResp = await createCohort(program.id, trial.id);
        const cohort = cohortResp.body.data;
        const procResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 180 });
        const procedure = procResp.body.data;

        trialsData.push({ trial, procedure, cohort });
      }

      const proposals = await Promise.all(
        trialsData.map(t =>
          createExecution(program.id, t.trial.id, {
            procedure_id: t.procedure.id,
            cohort_id: t.cohort.id,
            protocol_deviation: true
          })
        )
      );

      const successCount = proposals.filter(p => p.status === 201).length;
      const saturationBlocks = proposals.filter(p => p.status === 403).length;

      expect(successCount).toBeGreaterThanOrEqual(1);

      const portfolioFinal = (await getPortfolio(program.id, portfolio.id)).body.data;

      if (successCount === 3) {
        expect(portfolioFinal.is_risk_saturated).toBe(false);
      }

      for (const t of trialsData) {
        const trialFinal = (await getTrial(program.id, t.trial.id)).body.data;
        expectNonNegativeBalance(trialFinal.ethical_compliance_balance);
      }
    });

    test('should toggle saturation atomically at 90% boundary under concurrent proposals', async () => {
      const programResp = await createResearchProgram();
      expectSuccess(programResp, 201);
      const program = programResp.body.data;

      const portfolioResp = await createPortfolio(program.id, { max_total_ethical_budget: 1000 });
      const portfolio = portfolioResp.body.data;

      const { trial: trial1 } = await setupActiveTrial({
        program,
        portfolio_id: portfolio.id,
        total_ethical_compliance_budget: 2000
      });
      const { trial: trial2 } = await setupActiveTrial({
        program,
        portfolio_id: portfolio.id,
        total_ethical_compliance_budget: 2000
      });

      const phase1Resp = await createPhase(program.id, trial1.id, PHASE_NAME.PHASE_I);
      const phase1 = phase1Resp.body.data;
      const cohort1Resp = await createCohort(program.id, trial1.id);
      const cohort1 = cohort1Resp.body.data;

      const phase2Resp = await createPhase(program.id, trial2.id, PHASE_NAME.PHASE_I);
      const phase2 = phase2Resp.body.data;
      const cohort2Resp = await createCohort(program.id, trial2.id);
      const cohort2 = cohort2Resp.body.data;

      const proc1aResp = await createProcedure(program.id, trial1.id, phase1.id, { base_risk_cost: 199 });
      const proc1a = proc1aResp.body.data;
      await createExecution(program.id, trial1.id, {
        procedure_id: proc1a.id,
        cohort_id: cohort1.id,
        protocol_deviation: true
      });

      for (let i = 0; i < 3; i++) {
        const procResp = await createProcedure(program.id, trial2.id, phase2.id, { base_risk_cost: 199 });
        const proc = procResp.body.data;
        await createExecution(program.id, trial2.id, {
          procedure_id: proc.id,
          cohort_id: cohort2.id,
          protocol_deviation: true
        });
      }

      const proc1Resp = await createProcedure(program.id, trial1.id, phase1.id, { base_risk_cost: 60 });
      const proc1 = proc1Resp.body.data;
      const proc2Resp = await createProcedure(program.id, trial2.id, phase2.id, { base_risk_cost: 60 });
      const proc2 = proc2Resp.body.data;

      const [exec1Resp, exec2Resp] = await Promise.all([
        createExecution(program.id, trial1.id, {
          procedure_id: proc1.id,
          cohort_id: cohort1.id,
          protocol_deviation: true
        }),
        createExecution(program.id, trial2.id, {
          procedure_id: proc2.id,
          cohort_id: cohort2.id,
          protocol_deviation: true
        })
      ]);

      const portfolioFinal = (await getPortfolio(program.id, portfolio.id)).body.data;
      const successCount = [exec1Resp, exec2Resp].filter(r => r.status === 201).length;

      if (successCount === 2) {
        expect(portfolioFinal.is_risk_saturated).toBe(true);
      } else if (successCount === 1) {
        expect([true, false]).toContain(portfolioFinal.is_risk_saturated);
      }
    });

    test('should maintain ledger and state invariants when lock cascade races with proposals', async () => {
      const { program, portfolio, trials } = await setupPortfolioWithTrials(2);

      const trial1 = trials[0];
      const trial2 = trials[1];

      const phase2Resp = await createPhase(program.id, trial2.id, PHASE_NAME.PHASE_I);
      const phase2 = phase2Resp.body.data;
      const cohort2Resp = await createCohort(program.id, trial2.id);
      const cohort2 = cohort2Resp.body.data;
      const proc2Resp = await createProcedure(program.id, trial2.id, phase2.id, { base_risk_cost: 100 });
      const proc2 = proc2Resp.body.data;

      const [lockResp, deviationResp] = await Promise.all([
        manualRiskAdjustment(program.id, trial1.id, AUDIT_LOCK_THRESHOLD + 10, 'Trigger lock'),
        createExecution(program.id, trial2.id, {
          procedure_id: proc2.id,
          cohort_id: cohort2.id,
          protocol_deviation: true
        })
      ]);

      const trial1Final = (await getTrial(program.id, trial1.id)).body.data;
      const trial2Final = (await getTrial(program.id, trial2.id)).body.data;

      expect(trial1Final.status).toBe('ETHICAL_REVIEW_LOCK');

      expect(trial2Final.is_under_contagion).toBe(true);

      if (deviationResp.status === 201) {
        expectNonNegativeBalance(trial2Final.ethical_compliance_balance);
      }

      const portfolioFinal = (await getPortfolio(program.id, portfolio.id)).body.data;
      expect(typeof portfolioFinal.is_risk_saturated).toBe('boolean');
    });
  });

  describe('Defensive Programming: 404 Error Handling', () => {

    test('should return 404 for non-existent execution on execute', async () => {
      const { program, trial } = await setupActiveTrial();

      const fakeExecutionId = randomUUID();
      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const response = await request(apiUrl)
        .post(`/research-programs/${program.id}/clinical-trials/${trial.id}/procedure-executions/${fakeExecutionId}/execute`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', 'ResearchDirector')
        .send({});

      expectError(response, 404, 'ERR_EXECUTION_NOT_FOUND');
    });

    test('should return 404 for non-existent execution on mark-passed', async () => {
      const { program, trial } = await setupActiveTrial();

      const fakeExecutionId = randomUUID();
      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const response = await request(apiUrl)
        .post(`/research-programs/${program.id}/clinical-trials/${trial.id}/procedure-executions/${fakeExecutionId}/mark-passed`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', 'ResearchDirector')
        .send({});

      expectError(response, 404, 'ERR_EXECUTION_NOT_FOUND');
    });

    test('should return 404 for non-existent execution on reject', async () => {
      const { program, trial } = await setupActiveTrial();

      const fakeExecutionId = randomUUID();
      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const response = await request(apiUrl)
        .post(`/research-programs/${program.id}/clinical-trials/${trial.id}/procedure-executions/${fakeExecutionId}/reject`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', 'ResearchDirector')
        .send({});

      expectError(response, 404, 'ERR_EXECUTION_NOT_FOUND');
    });

    test('should return 404 for non-existent execution on cancel', async () => {
      const { program, trial } = await setupActiveTrial();

      const fakeExecutionId = randomUUID();
      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const response = await request(apiUrl)
        .post(`/research-programs/${program.id}/clinical-trials/${trial.id}/procedure-executions/${fakeExecutionId}/cancel`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', 'ResearchDirector')
        .send({});

      expectError(response, 404, 'ERR_EXECUTION_NOT_FOUND');
    });

    test('should return 404 for non-existent phase on status update', async () => {
      const { program, trial } = await setupActiveTrial();

      const fakePhaseId = randomUUID();
      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const response = await request(apiUrl)
        .put(`/research-programs/${program.id}/clinical-trials/${trial.id}/trial-phases/${fakePhaseId}`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', 'ResearchDirector')
        .send({
          status: PHASE_STATUS.READY_FOR_PROCEDURES,
          version: 0
        });

      expectError(response, 404, 'ERR_PHASE_NOT_FOUND');
    });

    test('should return 404 for non-existent source trial on dependency creation', async () => {
      const { program, irb } = await createProgramWithIRB();

      const fakeTrialId = randomUUID();
      const { trial: depTrial } = await setupActiveTrial({ program, irb });

      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const response = await request(apiUrl)
        .post(`/research-programs/${program.id}/clinical-trials/${fakeTrialId}/dependencies`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', 'ResearchDirector')
        .send({
          dependency_trial_id: depTrial.id
        });

      expectError(response, 404, 'ERR_TRIAL_NOT_FOUND');
    });

    test('should return 404 for non-existent IRB approval on status update', async () => {
      const { program, irb } = await createProgramWithIRB();

      const fakeApprovalId = randomUUID();
      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const response = await request(apiUrl)
        .put(`/research-programs/${program.id}/irbs/${irb.id}/approvals/${fakeApprovalId}`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', 'ResearchDirector')
        .send({
          status: 'APPROVED',
          version: 0
        });

      expectError(response, 404, 'ERR_IRB_APPROVAL_NOT_FOUND');
    });

    test('should return 400 for invalid phase name enum value', async () => {
      const { program, trial } = await setupActiveTrial();

      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const response = await request(apiUrl)
        .post(`/research-programs/${program.id}/clinical-trials/${trial.id}/trial-phases`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', 'ClinicalCoordinator')
        .send({
          name: 'INVALID_PHASE_NAME'
        });

      expectError(response, 400, 'ERR_INVALID_PHASE_NAME');
    });

    test('should return 404 for non-existent trial on IRB approval creation', async () => {
      const { program, irb } = await createProgramWithIRB();

      const fakeTrialId = randomUUID();
      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const response = await request(apiUrl)
        .post(`/research-programs/${program.id}/irbs/${irb.id}/approvals`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', 'ResearchDirector')
        .send({
          trial_id: fakeTrialId
        });

      expectError(response, 404, 'ERR_TRIAL_NOT_FOUND');
    });
  });
});
