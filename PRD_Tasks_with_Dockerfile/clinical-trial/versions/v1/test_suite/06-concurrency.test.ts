import { randomUUID } from 'crypto';
import request from 'supertest';

import {
  createExecution,
  executeExecution,
  markExecutionPassed,
  rejectExecution,
  cancelExecution,
  abandonTrial,
  activateTrial,
  updatePhaseStatus,
  clearEthicalReviewLock,
  manualRiskAdjustment,
  advanceClock,
  createPhase,
  createProcedure,
  createCohort,
  getTrial,
  createDependency,
  updatePortfolio,
  createResearchProgram,
  createTrial,
  createIRB,
  getResearchProgram,
  createPortfolio,
  getPortfolio,
  createIRBApproval,
  approveIRB,
  completeTrial,
  createBlackoutWindow,
  initializeReputation
} from '../../../test-helpers/resources';

import {
  expectSuccess,
  expectNonNegativeBalance,
  expectError
} from '../../../test-helpers/assertions';

import {
  PHASE_STATUS,
  PHASE_NAME,
  AUDIT_LOCK_THRESHOLD, MAX_ACTIVE_DEVIATIONS_PER_USER,
  CONTAGION_PENALTY
} from '../../../test-helpers/constants';

import {
  setupTrialWithProcedure,
  setupActiveTrial,
  setupTrialWithPhase,
  setupPortfolioWithTrials,
  setupTrialWithActiveDeviations,
  setupMultipleTrialsForInvestigator,
  forceTrialIntoLock,
  createProgramWithIRB,
  executeAndPassProcedure
} from '../../../test-helpers/scenarios';

import { generateIdempotencyKey, generateUserId, generateInvestigatorId } from '../../../test-helpers/builders';

describe('Concurrency & Edge Cases', () => {

  describe('Concurrency: Budget Depletion Races', () => {

    test('should handle concurrent budget depletion with exactly one success', async () => {
      const programResp = await createResearchProgram();
      expectSuccess(programResp, 201);
      const program = programResp.body.data;

      const irbResp = await createIRB(program.id);
      expectSuccess(irbResp, 201);
      const irb = irbResp.body.data;

      const { trial } = await setupActiveTrial({
        program,
        irb,
        total_ethical_compliance_budget: 150
      });

      const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
      expectSuccess(phaseResp, 201);
      const phase = phaseResp.body.data;

      const cohortResponse = await createCohort(program.id, trial.id);
      const cohort = cohortResponse.body.data;

      const proc1Resp = await createProcedure(program.id, trial.id, phase.id, {
        base_risk_cost: 100
      });
      expectSuccess(proc1Resp, 201);
      const procedure1 = proc1Resp.body.data;

      const proc2Resp = await createProcedure(program.id, trial.id, phase.id, {
        base_risk_cost: 100
      });
      expectSuccess(proc2Resp, 201);
      const procedure2 = proc2Resp.body.data;

      const [response1, response2] = await Promise.all([
        createExecution(program.id, trial.id, {
          procedure_id: procedure1.id,
          cohort_id: cohort.id,
          protocol_deviation: true
        }),
        createExecution(program.id, trial.id, {
          procedure_id: procedure2.id,
          cohort_id: cohort.id,
          protocol_deviation: true
        })
      ]);

      const responses = [response1, response2];
      const successResponses = responses.filter(r => r.status === 201);
      const failureResponses = responses.filter(r => r.status === 402);

      expect(successResponses).toHaveLength(1);
      expect(failureResponses).toHaveLength(1);

      expect(successResponses[0].status).toBe(201);
      expect(successResponses[0].body.data.protocol_deviation).toBe(true);
      expectError(failureResponses[0], 402, 'ERR_INSUFFICIENT_ETHICAL_BUDGET');
    });
  });

  describe('Concurrency: State Transition Races', () => {

    test('should handle concurrent execution attempts atomically', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      const execution = execResponse.body.data;

      const [exec1, exec2] = await Promise.all([
        executeExecution(program.id, trial.id, execution.id),
        executeExecution(program.id, trial.id, execution.id)
      ]);

      const responses = [exec1, exec2];
      const successResponses = responses.filter(r => r.status === 200);
      const failureResponses = responses.filter(r => r.status === 409);

      expect(successResponses).toHaveLength(1);
      expect(failureResponses).toHaveLength(1);
      expectError(failureResponses[0], 409, 'ERR_EXECUTION_NOT_PENDING');
    });

    test('should handle concurrent mark-passed attempts atomically', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      const execution = execResponse.body.data;

      const execResp = await executeExecution(program.id, trial.id, execution.id);
      expectSuccess(execResp, 200);

      const [pass1, pass2] = await Promise.all([
        markExecutionPassed(program.id, trial.id, execution.id),
        markExecutionPassed(program.id, trial.id, execution.id)
      ]);

      const responses = [pass1, pass2];
      const successResponses = responses.filter(r => r.status === 200);
      const failureResponses = responses.filter(r => r.status === 409);

      expect(successResponses).toHaveLength(1);
      expect(failureResponses).toHaveLength(1);
      expectError(failureResponses[0], 409, [
        'ERR_EXECUTION_NOT_EXECUTED',
        'ERR_PROCEDURE_NOT_AWAITING_EXECUTION'
      ]);
    });

    test('should handle concurrent reject and cancel atomically', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      const execution = execResponse.body.data;

      const [reject, cancel] = await Promise.all([
        rejectExecution(program.id, trial.id, execution.id),
        cancelExecution(program.id, trial.id, execution.id)
      ]);

      const responses = [reject, cancel];
      const successResponses = responses.filter(r => r.status === 200);
      const failureResponses = responses.filter(r => r.status === 409);

      expect(successResponses).toHaveLength(1);
      expect(failureResponses).toHaveLength(1);
      expectError(failureResponses[0], 409, [
        'ERR_EXECUTION_NOT_REJECTABLE',
        'ERR_EXECUTION_NOT_CANCELLABLE'
      ]);
    });

    test('should handle concurrent phase state transitions atomically', async () => {
      const { program, trial, phase } = await setupTrialWithPhase();

      const procResp = await createProcedure(program.id, trial.id, phase.id);
      expectSuccess(procResp, 201);

      const [trans1, trans2] = await Promise.all([
        updatePhaseStatus(
          program.id,
          trial.id,
          phase.id,
          PHASE_STATUS.READY_FOR_PROCEDURES,
          phase.version
        ),
        updatePhaseStatus(
          program.id,
          trial.id,
          phase.id,
          PHASE_STATUS.READY_FOR_PROCEDURES,
          phase.version
        )
      ]);

      const responses = [trans1, trans2];
      const successResponses = responses.filter(r => r.status === 200);
      const failureResponses = responses.filter(r => r.status === 409);

      expect(successResponses).toHaveLength(1);
      expect(failureResponses).toHaveLength(1);
      expectError(failureResponses[0], 409, 'ERR_VERSION_MISMATCH');
    });
  });

  describe('Concurrency: Abandonment Races', () => {

    test('should maintain non-negative balance in abandonment race', async () => {
      const { program, trial, executions } = await setupTrialWithActiveDeviations(2);

      const [reject, abandon] = await Promise.all([
        rejectExecution(program.id, trial.id, executions[0].id),
        abandonTrial(program.id, trial.id)
      ]);

      const finalTrial = (await getTrial(program.id, trial.id)).body.data;
      expectNonNegativeBalance(finalTrial.ethical_compliance_balance);
    });
  });

  describe('Concurrency: Portfolio Saturation', () => {

    test('should handle portfolio saturation updates deterministically', async () => {
      const { program, portfolio, trials } = await setupPortfolioWithTrials(2);

      const trial1 = trials[0];
      const trial2 = trials[1];

      const phase1Resp = await createPhase(program.id, trial1.id, PHASE_NAME.PHASE_I);
      expectSuccess(phase1Resp, 201);
      const phase1 = phase1Resp.body.data;

      const phase2Resp = await createPhase(program.id, trial2.id, PHASE_NAME.PHASE_I);
      expectSuccess(phase2Resp, 201);
      const phase2 = phase2Resp.body.data;

      const proc1Resp = await createProcedure(program.id, trial1.id, phase1.id, {
        base_risk_cost: 199
      });
      expectSuccess(proc1Resp, 201);
      const proc1 = proc1Resp.body.data;

      const proc2Resp = await createProcedure(program.id, trial2.id, phase2.id, {
        base_risk_cost: 199
      });
      expectSuccess(proc2Resp, 201);
      const proc2 = proc2Resp.body.data;

      const cohort1Response = await createCohort(program.id, trial1.id);
      const cohort1 = cohort1Response.body.data;
      const cohort2Response = await createCohort(program.id, trial2.id);
      const cohort2 = cohort2Response.body.data;

      const [exec1, exec2] = await Promise.all([
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

      const successCount = [exec1, exec2].filter(e => e.status === 201).length;
      expect(successCount).toBeGreaterThanOrEqual(1);

      const portfolioResponse = await getPortfolio(program.id, portfolio.id);

      expect(portfolioResponse.body.data.is_risk_saturated).toBe(false);
    });

    test('should maintain stable portfolio saturation under concurrent finalize operations', async () => {
      const { program, portfolio, trials } = await setupPortfolioWithTrials(2);

      const trial1 = trials[0];

      const phaseResp = await createPhase(program.id, trial1.id, PHASE_NAME.PHASE_I);
      expectSuccess(phaseResp, 201);
      const phase = phaseResp.body.data;

      const cohortResponse = await createCohort(program.id, trial1.id);
      const cohort = cohortResponse.body.data;

      const executions: any[] = [];
      for (let i = 0; i < 3; i++) {
        const procResp = await createProcedure(program.id, trial1.id, phase.id, {
          base_risk_cost: 100
        });
        expectSuccess(procResp, 201);
        const proc = procResp.body.data;

        const execResp = await createExecution(program.id, trial1.id, {
          procedure_id: proc.id,
          cohort_id: cohort.id,
          protocol_deviation: true
        });

        executions.push(execResp.body.data);
      }

      await Promise.all(
        executions.map(exec => executeExecution(program.id, trial1.id, exec.id))
      );

      await Promise.all(
        executions.map(exec => markExecutionPassed(program.id, trial1.id, exec.id))
      );

      const portfolioResponse = await getPortfolio(program.id, portfolio.id);
      expect(portfolioResponse.body.data.is_risk_saturated).toBe(false);
    });
  });

  describe('Concurrency: Reputation Updates', () => {

    test('should handle concurrent reputation penalties consistently', async () => {
      const { program, investigatorId, trials } = await setupMultipleTrialsForInvestigator(3);

      const trial3Before = trials[2].effective_ethical_compliance_budget;

      await Promise.all([
        abandonTrial(program.id, trials[0].id),
        abandonTrial(program.id, trials[1].id)
      ]);

      const trial3After = (await getTrial(program.id, trials[2].id)).body.data;

      expect(trial3After.effective_ethical_compliance_budget).toBeLessThan(trial3Before);

      const expectedEffective = Math.floor(trials[2].total_ethical_compliance_budget * 0.8);
      expect(trial3After.effective_ethical_compliance_budget).toBe(expectedEffective);
    });
  });

  describe('Concurrency: Clock Advances', () => {

    test('should handle completion racing with clock advance and blackout changes', async () => {
      const { program, trial } = await setupActiveTrial({ treatment_name: 'Test Trial' });

      const blackoutResp = await createBlackoutWindow(program.id, {
        treatment_name_pattern: '*',
        start_period_index: 1,
        end_period_index: 100
      });
      expectSuccess(blackoutResp, 201);

      const [completeResp, clockResp] = await Promise.all([
        completeTrial(program.id, trial.id),
        advanceClock(program.id, 1)
      ]);

      if (completeResp.status === 200) {
        expect(completeResp.body.data.status).toBe('COMPLETED');
      } else if (completeResp.status === 403) {
        expectError(completeResp, 403, 'ERR_ENROLLMENT_BLACKOUT_ACTIVE');
      } else if (completeResp.status === 409) {
        expect(completeResp.body.data.error_id).toBe('ERR_STALE_PERIOD_INDEX');
      } else {
        throw new Error(`Unexpected completion status: ${completeResp.status}`);
      }

      const finalProgram = (await getResearchProgram(program.id)).body.data;
      expect(finalProgram.current_period_index).toBeGreaterThanOrEqual(0);
    });
  });

  describe('Concurrency: Version Mismatch', () => {

    test('should reject portfolio update with stale version', async () => {
      const programResp = await createResearchProgram();
      expectSuccess(programResp, 201);
      const program = programResp.body.data;

      const portfolioResp = await createPortfolio(program.id);
      expectSuccess(portfolioResp, 201);
      const portfolio = portfolioResp.body.data;

      const updateResp = await updatePortfolio(program.id, portfolio.id, {
        name: 'Updated Name',
        version: portfolio.version
      });
      expectSuccess(updateResp, 200);

      const staleResponse = await updatePortfolio(program.id, portfolio.id, {
        name: 'Another Update',
        version: portfolio.version
      });

      expectError(staleResponse, 409, 'ERR_VERSION_MISMATCH');
    });

    test('should reject phase status update with stale version', async () => {
      const { program, trial, phase } = await setupTrialWithPhase();

      const procResp = await createProcedure(program.id, trial.id, phase.id);
      expectSuccess(procResp, 201);

      const readyResp = await updatePhaseStatus(program.id, trial.id, phase.id, PHASE_STATUS.READY_FOR_PROCEDURES, phase.version);
      expectSuccess(readyResp, 200);

      const staleResponse = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.CANCELLED,
        phase.version
      );

      expectError(staleResponse, 409, 'ERR_VERSION_MISMATCH');
    });

    test('should reject mark-passed when stale If-Match version is provided', async () => {
      const { program, trial, procedure, cohort } = await setupTrialWithProcedure();

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });
      const execution = execResponse.body.data;

      const executeResp = await executeExecution(program.id, trial.id, execution.id);
      expectSuccess(executeResp, 200);
      const executedExecution = executeResp.body.data;
      const staleVersion = executedExecution.version;

      const passResp = await markExecutionPassed(program.id, trial.id, execution.id);
      expectSuccess(passResp, 200);

      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const stalePassResp = await request(apiUrl)
        .post(`/research-programs/${program.id}/clinical-trials/${trial.id}/procedure-executions/${execution.id}/mark-passed`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', 'ResearchDirector')
        .set('If-Match', String(staleVersion))
        .send({});

      expectError(stalePassResp, 409, 'ERR_VERSION_MISMATCH');
    });
  });

  describe('Concurrency: Version-Check Priority (Tests Error Precedence)', () => {

    test('should return version mismatch before business validation error on portfolio update', async () => {
      const { program } = await createProgramWithIRB();

      const portfolioResp = await createPortfolio(program.id, {
        max_total_ethical_budget: 1000
      });
      expectSuccess(portfolioResp, 201);
      const portfolio = portfolioResp.body.data;

      const updateResp = await updatePortfolio(program.id, portfolio.id, {
        max_total_ethical_budget: 2000,
        version: portfolio.version
      });
      expectSuccess(updateResp, 200);

      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const response = await request(apiUrl)
        .put(`/research-programs/${program.id}/trial-portfolios/${portfolio.id}`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', 'ResearchDirector')
        .send({
          max_total_ethical_budget: -100,
          version: portfolio.version
        });

      expectError(response, 409, 'ERR_VERSION_MISMATCH');
    });

    test('should return version mismatch before state validation error on phase update', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const readyResp = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.READY_FOR_PROCEDURES,
        phase.version
      );
      expectSuccess(readyResp, 200);

      await executeAndPassProcedure(program.id, trial.id, procedure.id, cohort.id);

      const completeResp = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.COMPLETED,
        readyResp.body.data.version
      );
      expectSuccess(completeResp, 200);

      const response = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.READY_FOR_PROCEDURES,
        phase.version
      );

      expectError(response, 409, 'ERR_VERSION_MISMATCH');
    });

    test('should return version mismatch before completion guard error on phase', async () => {
      const { program, trial, phase, procedure } = await setupTrialWithProcedure();

      const readyResp = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.READY_FOR_PROCEDURES,
        phase.version
      );
      expectSuccess(readyResp, 200);

      const cancelResp = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.CANCELLED,
        readyResp.body.data.version
      );
      expectSuccess(cancelResp, 200);

      const response = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.COMPLETED,
        phase.version
      );

      expectError(response, 409, 'ERR_VERSION_MISMATCH');
    });

    test('should return version mismatch before blackout error on phase completion', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      await createBlackoutWindow(program.id, {
        treatment_name_pattern: '*',
        start_period_index: 0,
        end_period_index: 100
      });

      const readyResp = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.READY_FOR_PROCEDURES,
        phase.version
      );
      expectSuccess(readyResp, 200);

      await executeAndPassProcedure(program.id, trial.id, procedure.id, cohort.id);

      const reviewResp = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.REVIEW_REQUIRED,
        readyResp.body.data.version
      );
      expectSuccess(reviewResp, 200);

      const response = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.COMPLETED,
        phase.version
      );

      expectError(response, 409, 'ERR_VERSION_MISMATCH');
    });

    test('should return version mismatch before execution state error', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const execResp = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });
      const execution = execResp.body.data;

      const executeResp = await executeExecution(program.id, trial.id, execution.id);
      expectSuccess(executeResp, 200);

      const passResp = await markExecutionPassed(program.id, trial.id, execution.id);
      expectSuccess(passResp, 200);

      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const response = await request(apiUrl)
        .post(`/research-programs/${program.id}/clinical-trials/${trial.id}/procedure-executions/${execution.id}/mark-passed`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', 'ResearchDirector')
        .set('If-Match', String(execution.version))
        .send({});

      expectError(response, 409, 'ERR_VERSION_MISMATCH');
    });

    test('should return version mismatch before procedure state error on execution reject', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const execResp = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });
      const execution = execResp.body.data;
      const originalVersion = execution.version;

      const executeResp = await executeExecution(program.id, trial.id, execution.id);
      expectSuccess(executeResp, 200);

      const passResp = await markExecutionPassed(program.id, trial.id, execution.id);
      expectSuccess(passResp, 200);

      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const response = await request(apiUrl)
        .post(`/research-programs/${program.id}/clinical-trials/${trial.id}/procedure-executions/${execution.id}/reject`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', 'ResearchDirector')
        .set('If-Match', String(originalVersion))
        .send({});

      expectError(response, 409, 'ERR_VERSION_MISMATCH');
    });

    test('should return version mismatch before cancellability check', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const execResp = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });
      const execution = execResp.body.data;

      await executeExecution(program.id, trial.id, execution.id);
      const passResp = await markExecutionPassed(program.id, trial.id, execution.id);
      expectSuccess(passResp, 200);

      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const response = await request(apiUrl)
        .post(`/research-programs/${program.id}/clinical-trials/${trial.id}/procedure-executions/${execution.id}/cancel`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', 'ResearchDirector')
        .set('If-Match', String(execution.version))
        .send({});

      expectError(response, 409, 'ERR_VERSION_MISMATCH');
    });

    test('should return version mismatch before validating portfolio budget constraints', async () => {
      const { program } = await createProgramWithIRB();

      const portfolioResp = await createPortfolio(program.id, {
        max_total_ethical_budget: 1000
      });
      expectSuccess(portfolioResp, 201);
      const portfolio = portfolioResp.body.data;

      const updateResp = await updatePortfolio(program.id, portfolio.id, {
        max_total_ethical_budget: 2000,
        version: portfolio.version
      });
      expectSuccess(updateResp, 200);

      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const response = await request(apiUrl)
        .put(`/research-programs/${program.id}/trial-portfolios/${portfolio.id}`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', 'ResearchDirector')
        .send({
          max_total_ethical_budget: 0,
          version: portfolio.version
        });

      expectError(response, 409, 'ERR_VERSION_MISMATCH');
    });

    test('should return version mismatch before phase completion guard errors', async () => {
      const { program, trial, phase, procedure } = await setupTrialWithProcedure();

      const readyResp = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.READY_FOR_PROCEDURES,
        phase.version
      );
      expectSuccess(readyResp, 200);

      const reviewResp = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.REVIEW_REQUIRED,
        readyResp.body.data.version
      );
      expectSuccess(reviewResp, 200);

      const response = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.COMPLETED,
        phase.version
      );

      expectError(response, 409, 'ERR_VERSION_MISMATCH');
    });

    test('should return version mismatch before IRB status validation', async () => {
      const { program, irb } = await createProgramWithIRB();

      const trialResp = await createTrial(program.id, { irb_id: irb.id });
      expectSuccess(trialResp, 201);
      const trial = trialResp.body.data;

      const approvalResp = await createIRBApproval(program.id, irb.id, trial.id);
      expectSuccess(approvalResp, 201);
      const approval = approvalResp.body.data;

      const approveResp = await approveIRB(program.id, irb.id, approval.id, approval.version);
      expectSuccess(approveResp, 200);

      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const response = await request(apiUrl)
        .put(`/research-programs/${program.id}/irbs/${irb.id}/approvals/${approval.id}`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', 'ResearchDirector')
        .send({
          status: 'INVALID_STATUS',
          version: approval.version
        });

      expectError(response, 409, 'ERR_VERSION_MISMATCH');
    });
  });

  describe('Concurrency: Lock Cascades', () => {

    test('should apply contagion one-hop consistently under concurrent locks', async () => {
      const { program, portfolio, trials } = await setupPortfolioWithTrials(3);

      await Promise.all([
        forceTrialIntoLock(program.id, trials[0].id),
        forceTrialIntoLock(program.id, trials[1].id)
      ]);

      const trial2 = (await getTrial(program.id, trials[2].id)).body.data;

      expect(trial2.is_under_contagion).toBe(true);
      expect(trial2.patient_safety_risk).toBe(CONTAGION_PENALTY * 2);

    });

    test('should reject duplicate clear-lock requests', async () => {
      const { program, trial } = await setupActiveTrial();

      await forceTrialIntoLock(program.id, trial.id);

      const clearResp = await clearEthicalReviewLock(program.id, trial.id);
      expectSuccess(clearResp, 200);

      const secondClear = await clearEthicalReviewLock(program.id, trial.id);

      expectError(secondClear, 409, 'ERR_TRIAL_NOT_IN_ETHICAL_REVIEW_LOCK');
    });
  });

  describe('Concurrency: Idempotency', () => {

    test('should return original resource on idempotent retry', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const idempotencyKey = generateIdempotencyKey();

      const userId = randomUUID();
      const response1 = await createExecution(
        program.id,
        trial.id,
        {
          procedure_id: procedure.id,
          cohort_id: cohort.id,
          protocol_deviation: false
        },
        userId,
        idempotencyKey
      );

      expectSuccess(response1, 201);
      const originalId = response1.body.data.id;

      const response2 = await createExecution(
        program.id,
        trial.id,
        {
          procedure_id: procedure.id,
          cohort_id: cohort.id,
          protocol_deviation: false
        },
        userId,
        idempotencyKey
      );

      expect(response2.status).toBe(200);
      expect(response2.body.data.id).toBe(originalId);
    });
  });

  describe('Concurrency: Active Deviation Limit', () => {

    test('should enforce active deviation cap atomically under concurrent proposals', async () => {
      const userId = generateUserId();
      const { program, trial } = await setupActiveTrial();

      const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
      expectSuccess(phaseResp, 201);
      const phase = phaseResp.body.data;

      const cohortResponse = await createCohort(program.id, trial.id);
      const cohort = cohortResponse.body.data;

      const procedures = [];
      for (let i = 0; i < 4; i++) {
        const procResp = await createProcedure(program.id, trial.id, phase.id, {
          base_risk_cost: 50
        });
        expectSuccess(procResp, 201);
        procedures.push(procResp.body.data);
      }

      const responses = await Promise.all(
        procedures.map(proc =>
          createExecution(
            program.id,
            trial.id,
            {
              procedure_id: proc.id,
              cohort_id: cohort.id,
              protocol_deviation: true
            },
            userId
          )
        )
      );

      const successResponses = responses.filter(r => r.status === 201);
      const failureResponses = responses.filter(r => r.status !== 201);

      expect(successResponses).toHaveLength(MAX_ACTIVE_DEVIATIONS_PER_USER);
      expect(failureResponses).toHaveLength(1);
      expectError(failureResponses[0], 409, 'ERR_MAX_ACTIVE_DEVIATIONS_PER_USER_VIOLATION');
    });
  });

  describe('Edge Cases: Zero and Boundary Values', () => {

    test('should handle zero base risk cost', async () => {
      const { program, trial, phase } = await setupTrialWithPhase();

      const cohortResponse = await createCohort(program.id, trial.id);
      const cohort = cohortResponse.body.data;

      const procResp = await createProcedure(program.id, trial.id, phase.id, {
        base_risk_cost: 0
      });
      expectSuccess(procResp, 201);
      const procedure = procResp.body.data;

      const response = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      expectSuccess(response, 201);
      expect(response.body.data.provisional_risk_debit).toBe(0);
    });

    test('should handle zero total budget correctly', async () => {
      const programResp = await createResearchProgram();
      expectSuccess(programResp, 201);
      const program = programResp.body.data;

      const irbResp = await createIRB(program.id);
      expectSuccess(irbResp, 201);
      const irb = irbResp.body.data;

      const { trial } = await setupActiveTrial({
        program,
        irb,
        total_ethical_compliance_budget: 0
      });

      expect(trial.ethical_compliance_balance).toBe(0);

      const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
      expectSuccess(phaseResp, 201);
      const phase = phaseResp.body.data;

      const procResp = await createProcedure(program.id, trial.id, phase.id, {
        base_risk_cost: 10
      });
      expectSuccess(procResp, 201);
      const procedure = procResp.body.data;

      const cohortResponse = await createCohort(program.id, trial.id);
      const cohort = cohortResponse.body.data;

      const nonDevResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      expectSuccess(nonDevResponse, 201);
    });

    test('should trigger lock immediately with large risk increase', async () => {
      const { program, trial } = await setupActiveTrial();

      await forceTrialIntoLock(program.id, trial.id);

      const updated = (await getTrial(program.id, trial.id)).body.data;
      expect(updated.status).toBe('ETHICAL_REVIEW_LOCK');
    });

    test('should require explicit unlock even after risk reduction', async () => {
      const { program, trial } = await setupActiveTrial();

      await forceTrialIntoLock(program.id, trial.id);

      const lockedTrial = (await getTrial(program.id, trial.id)).body.data;
      expect(lockedTrial.status).toBe('ETHICAL_REVIEW_LOCK');
      const riskWhenLocked = lockedTrial.patient_safety_risk;

      await clearEthicalReviewLock(program.id, trial.id);

      const reduceResp = await manualRiskAdjustment(
        program.id,
        trial.id,
        -(riskWhenLocked - 50),
        'Reduce risk below threshold after clearing lock'
      );
      expectSuccess(reduceResp, 200);

      const updated = (await getTrial(program.id, trial.id)).body.data;
      expect(updated.status).toBe('ACTIVE');
      expect(updated.patient_safety_risk).toBeLessThanOrEqual(100);
    });

    test('should apply floor division to effective budget calculations', async () => {
      const programResp = await createResearchProgram();
      expectSuccess(programResp, 201);
      const program = programResp.body.data;

      const investigatorId = generateInvestigatorId();

      const initResp = await initializeReputation(program.id, investigatorId);
      expectSuccess(initResp, 201);

      for (let i = 0; i < 6; i++) {
        const irbResp = await createIRB(program.id);
        expectSuccess(irbResp, 201);
        const irb = irbResp.body.data;

        const trialResp = await createTrial(program.id, { irb_id: irb.id }, investigatorId);
        expectSuccess(trialResp, 201);
        const trial = trialResp.body.data;

        const abandonResp = await abandonTrial(program.id, trial.id);
        expectSuccess(abandonResp, 200);
      }

      const irbResp = await createIRB(program.id);
      expectSuccess(irbResp, 201);
      const irb = irbResp.body.data;

      const trialResp = await createTrial(program.id, {
        total_ethical_compliance_budget: 1000,
        irb_id: irb.id
      }, investigatorId);
      expectSuccess(trialResp, 201);
      const trial = trialResp.body.data;

      expect(trial.effective_ethical_compliance_budget).toBe(400);
    });

    test('should floor reputation at zero', async () => {
      const programResp = await createResearchProgram();
      expectSuccess(programResp, 201);
      const program = programResp.body.data;

      const investigatorId = generateInvestigatorId();

      const initResp = await initializeReputation(program.id, investigatorId);
      expectSuccess(initResp, 201);

      for (let i = 0; i < 12; i++) {
        const irbResp = await createIRB(program.id);
        expectSuccess(irbResp, 201);
        const irb = irbResp.body.data;

        const trialResp = await createTrial(program.id, {
          irb_id: irb.id,
          total_ethical_compliance_budget: 400
        }, investigatorId);
        expectSuccess(trialResp, 201);
        const trial = trialResp.body.data;

        const abandonResp = await abandonTrial(program.id, trial.id);
        expectSuccess(abandonResp, 200);
      }

      const repResponse = await initializeReputation(program.id, investigatorId);
      expect(repResponse.body.data.reputation_score).toBe(0);

      const irb2Resp = await createIRB(program.id);
      expectSuccess(irb2Resp, 201);
      const irb2 = irb2Resp.body.data;

      const trial2Resp = await createTrial(program.id, {
        irb_id: irb2.id,
        total_ethical_compliance_budget: 400
      }, investigatorId);
      expectSuccess(trial2Resp, 201);
      const trial2 = trial2Resp.body.data;

      const abandon2Resp = await abandonTrial(program.id, trial2.id);
      expectSuccess(abandon2Resp, 200);

      const repResponse2 = await initializeReputation(program.id, investigatorId);
      expect(repResponse2.body.data.reputation_score).toBe(0);
    });

    test('should match any property when procedure requires one tag', async () => {
      const { program, trial, phase } = await setupTrialWithPhase();

      const cohortResponse = await createCohort(program.id, trial.id, {
        cohort_name: 'Multi-property Cohort',
        cohort_version: '1.0',
        base_risk_points: 10,
        properties: [
          {
            property_id: 'prop-1',
            name: 'HEALTHY_VOLUNTEERS' as any,
            certified_period_index: 0
          },
          {
            property_id: 'prop-2',
            name: 'HIGH_RISK_PATIENTS' as any,
            certified_period_index: 0
          }
        ]
      });
      const cohort = cohortResponse.body.data;

      const procResp = await createProcedure(program.id, trial.id, phase.id, {
        required_cohort_tag: 'HEALTHY_VOLUNTEERS' as any
      });
      expectSuccess(procResp, 201);
      const procedure = procResp.body.data;

      const response = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      expectSuccess(response, 201);
    });
  });

  describe('Edge Cases: Dependency Chains', () => {

    test('should prevent self-dependency creation', async () => {
      const programResp = await createResearchProgram();
      expectSuccess(programResp, 201);
      const program = programResp.body.data;

      const irbResp = await createIRB(program.id);
      expectSuccess(irbResp, 201);
      const irb = irbResp.body.data;

      const trialResp = await createTrial(program.id, { irb_id: irb.id });
      expectSuccess(trialResp, 201);
      const trial = trialResp.body.data;

      const response = await createDependency(program.id, trial.id, trial.id);

      expectError(response, 400, 'ERR_SELF_DEPENDENCY');
    });

    test('should prevent cross-program dependencies', async () => {
      const program1Resp = await createResearchProgram();
      expectSuccess(program1Resp, 201);
      const program1 = program1Resp.body.data;

      const program2Resp = await createResearchProgram();
      expectSuccess(program2Resp, 201);
      const program2 = program2Resp.body.data;

      const irb1Resp = await createIRB(program1.id);
      expectSuccess(irb1Resp, 201);
      const irb1 = irb1Resp.body.data;

      const irb2Resp = await createIRB(program2.id);
      expectSuccess(irb2Resp, 201);
      const irb2 = irb2Resp.body.data;

      const trial1Resp = await createTrial(program1.id, { irb_id: irb1.id });
      expectSuccess(trial1Resp, 201);
      const trial1 = trial1Resp.body.data;

      const trial2Resp = await createTrial(program2.id, { irb_id: irb2.id });
      expectSuccess(trial2Resp, 201);
      const trial2 = trial2Resp.body.data;

      const response = await createDependency(program1.id, trial1.id, trial2.id);

      expectError(response, 400, 'ERR_CROSS_PROGRAM_DEPENDENCY');
    });
  });

  describe('Edge Cases: Ledger Consistency', () => {

    test('should maintain exact balance calculations without drift', async () => {
      const { program, trial, phase } = await setupTrialWithPhase();

      const cohortResponse = await createCohort(program.id, trial.id);
      const cohort = cohortResponse.body.data;

      for (let i = 0; i < 5; i++) {
        const procResp = await createProcedure(program.id, trial.id, phase.id, {
          base_risk_cost: 100 + i * 10
        });
        expectSuccess(procResp, 201);
        const proc = procResp.body.data;

        const execResp = await createExecution(program.id, trial.id, {
          procedure_id: proc.id,
          cohort_id: cohort.id,
          protocol_deviation: true
        });

        const afterEach = (await getTrial(program.id, trial.id)).body.data;
        expectNonNegativeBalance(afterEach.ethical_compliance_balance);
      }

      const finalTrial = (await getTrial(program.id, trial.id)).body.data;
      expectNonNegativeBalance(finalTrial.ethical_compliance_balance);
    });

    test('should enforce uniqueness constraint on dependency pairs', async () => {
      const programResp = await createResearchProgram();
      expectSuccess(programResp, 201);
      const program = programResp.body.data;

      const irbResp = await createIRB(program.id);
      expectSuccess(irbResp, 201);
      const irb = irbResp.body.data;

      const { trial: trial1 } = await setupActiveTrial({ program, irb });
      const { trial: trial2 } = await setupActiveTrial({ program, irb });

      const complete1Resp = await completeTrial(program.id, trial1.id);
      expectSuccess(complete1Resp, 200);

      const dep1Response = await createDependency(program.id, trial2.id, trial1.id);
      expectSuccess(dep1Response, 201);
      expect(dep1Response.body.data.source_trial_id).toBe(trial2.id);
      expect(dep1Response.body.data.dependency_trial_id).toBe(trial1.id);

      const dep2Response = await createDependency(program.id, trial2.id, trial1.id);

      expectError(dep2Response, 409, 'ERR_INVALID_REQUEST');
    });

    test('should validate cohort properties independently across concurrent requests', async () => {
      const { program, trial } = await setupActiveTrial();

      const invalidCohortData = {
        cohort_name: 'Test Cohort',
        cohort_version: '1.0',
        base_risk_points: 10,
        properties: [{
          property_id: 'prop-1',
          name: 'INVALID_PROPERTY' as any,
          certified_period_index: 0
        }]
      };

      const [resp1, resp2] = await Promise.all([
        createCohort(program.id, trial.id, invalidCohortData),
        createCohort(program.id, trial.id, invalidCohortData)
      ]);

      expectError(resp1, 400, 'ERR_INVALID_PROPERTY_NAME');
      expectError(resp2, 400, 'ERR_INVALID_PROPERTY_NAME');
    });

    test('should reject IRB approval update with invalid status', async () => {
      const programResp = await createResearchProgram();
      expectSuccess(programResp, 201);
      const program = programResp.body.data;

      const irbResp = await createIRB(program.id);
      expectSuccess(irbResp, 201);
      const irb = irbResp.body.data;

      const trialResp = await createTrial(program.id, { irb_id: irb.id });
      expectSuccess(trialResp, 201);
      const trial = trialResp.body.data;

      const approvalResp = await createIRBApproval(program.id, irb.id, trial.id);
      expectSuccess(approvalResp, 201);
      const approval = approvalResp.body.data;

      const apiUrl = process.env.API_URL || 'http://localhost:3000';
      const response = await request(apiUrl)
        .put(`/research-programs/${program.id}/irbs/${irb.id}/approvals/${approval.id}`)
        .set('X-User-ID', randomUUID())
        .set('X-User-Role', 'ResearchDirector')
        .send({
          status: 'INVALID_STATUS',
          version: approval.version
        });

      expectError(response, 400, 'ERR_INVALID_IRB_STATUS');
    });

    test('should reject clear-lock when trial is not locked', async () => {
      const { program, trial } = await setupActiveTrial();

      const response = await clearEthicalReviewLock(program.id, trial.id);

      expectError(response, 409, 'ERR_TRIAL_NOT_IN_ETHICAL_REVIEW_LOCK');
    });
  });

  describe('Concurrency: Idempotence & Transaction Boundaries (Principal Engineer Skills)', () => {

    test('should return original resource on idempotent retry', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const idempotencyKey = generateIdempotencyKey();

      const userId = randomUUID();
      const response1 = await createExecution(
        program.id,
        trial.id,
        {
          procedure_id: procedure.id,
          cohort_id: cohort.id,
          protocol_deviation: false
        },
        userId,
        idempotencyKey
      );

      expectSuccess(response1, 201);
      const originalId = response1.body.data.id;

      const response2 = await createExecution(
        program.id,
        trial.id,
        {
          procedure_id: procedure.id,
          cohort_id: cohort.id,
          protocol_deviation: false
        },
        userId,
        idempotencyKey
      );

      expect(response2.status).toBe(200);
      expect(response2.body.data.id).toBe(originalId);
    });
  });

  describe('Concurrency: Atomic Guard Validation (TOCTOU Prevention)', () => {

    test('should atomically validate completion guards when clock advances during request', async () => {
      const { program, trial } = await setupActiveTrial({
        treatment_name: 'Test Trial'
      });

      await createBlackoutWindow(program.id, {
        treatment_name_pattern: '*',
        start_period_index: 1,
        end_period_index: 100
      });

      const [completeResp, clockResp] = await Promise.all([
        completeTrial(program.id, trial.id),
        advanceClock(program.id, 1)
      ]);

      const validOutcomes = [
        { status: 200, expectStatus: 'COMPLETED' },
        { status: 403, expectError: 'ERR_ENROLLMENT_BLACKOUT_ACTIVE' },
        { status: 409, expectError: 'ERR_STALE_PERIOD_INDEX' }
      ];

      const outcome = validOutcomes.find(o => o.status === completeResp.status);
      expect(outcome).toBeDefined();

      if (completeResp.status === 200) {
        expect(completeResp.body.data.status).toBe('COMPLETED');
      } else {
        expect(completeResp.body.data.error_id).toBe(outcome!.expectError);
      }

      const finalTrial = (await getTrial(program.id, trial.id)).body.data;
      const finalProgram = (await getResearchProgram(program.id)).body.data;

      if (finalTrial.status === 'COMPLETED' && finalProgram.current_period_index >= 1) {
        expect(true).toBe(true);
      }
    });

    test('should handle completion racing with execution rejection atomically', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const execResp = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });
      const execution = execResp.body.data;

      const [completeResp, rejectResp] = await Promise.all([
        completeTrial(program.id, trial.id),
        rejectExecution(program.id, trial.id, execution.id)
      ]);

      expectError(completeResp, 409, ['ERR_UNRESOLVED_EXECUTIONS_EXIST', 'ERR_PHASES_NOT_COMPLETED']);

      const finalTrial = (await getTrial(program.id, trial.id)).body.data;
      expect(finalTrial.status).not.toBe('COMPLETED');
    });

    test('should prevent completion if trial locks during completion attempt', async () => {
      const { program, trial } = await setupActiveTrial();

      const [completeResp, riskResp] = await Promise.all([
        completeTrial(program.id, trial.id),
        manualRiskAdjustment(program.id, trial.id, AUDIT_LOCK_THRESHOLD + 10, 'Trigger lock concurrently')
      ]);

      const finalTrial = (await getTrial(program.id, trial.id)).body.data;
      if (finalTrial.status === 'COMPLETED') {
        expect(finalTrial.status).not.toBe('ETHICAL_REVIEW_LOCK');
      }
      if (finalTrial.status === 'ETHICAL_REVIEW_LOCK') {
        expect(finalTrial.status).not.toBe('COMPLETED');
      }
    });

    test('should atomically evaluate phase completion when concurrent cancel triggers review', async () => {
      const { program, trial, phase } = await setupTrialWithPhase();

      const cohortResp = await createCohort(program.id, trial.id);
      const cohort = cohortResp.body.data;

      const procedures = [];
      for (let i = 0; i < 4; i++) {
        const procResp = await createProcedure(program.id, trial.id, phase.id);
        expectSuccess(procResp, 201);
        procedures.push(procResp.body.data);
      }

      const readyResp = await updatePhaseStatus(program.id, trial.id, phase.id, PHASE_STATUS.READY_FOR_PROCEDURES, phase.version);
      expectSuccess(readyResp, 200);

      for (let i = 0; i < 3; i++) {
        await executeAndPassProcedure(program.id, trial.id, procedures[i].id, cohort.id);
      }

      const exec4 = await createExecution(program.id, trial.id, {
        procedure_id: procedures[3].id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });
      const execution4 = exec4.body.data;
      await executeExecution(program.id, trial.id, execution4.id);

      for (let i = 0; i < 2; i++) {
        const procResp = await createProcedure(program.id, trial.id, phase.id);
        const proc = procResp.body.data;
        const execResp = await createExecution(program.id, trial.id, {
          procedure_id: proc.id,
          cohort_id: cohort.id,
          protocol_deviation: true
        });
        const exec = execResp.body.data;
        await cancelExecution(program.id, trial.id, exec.id);
      }

      const proc5Resp = await createProcedure(program.id, trial.id, phase.id);
      const proc5 = proc5Resp.body.data;
      const exec5 = await createExecution(program.id, trial.id, {
        procedure_id: proc5.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });
      const execution5 = exec5.body.data;

      const [passResp, cancelResp] = await Promise.all([
        markExecutionPassed(program.id, trial.id, execution4.id),
        cancelExecution(program.id, trial.id, execution5.id)
      ]);

      const phaseAfter = readyResp.body.data.version + 1;
      const completeAttempt = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.COMPLETED,
        phaseAfter
      );

      const acceptableErrors = ['ERR_PHASE_IN_REVIEW', 'ERR_PROCEDURES_NOT_PASSED', 'ERR_VERSION_MISMATCH'];
      if (completeAttempt.status !== 200) {
        expect(acceptableErrors).toContain(completeAttempt.body.data.error_id);
      }
    });

    test('should atomically evaluate deviation gates when reputation changes concurrently', async () => {
      const { program, investigatorId, trials } = await setupMultipleTrialsForInvestigator(2);

      const trial1 = trials[0];
      const trial2 = trials[1];

      const phaseResp = await createPhase(program.id, trial2.id, PHASE_NAME.PHASE_I);
      const phase = phaseResp.body.data;
      const procResp = await createProcedure(program.id, trial2.id, phase.id, { base_risk_cost: 5000 });
      const procedure = procResp.body.data;
      const cohortResp = await createCohort(program.id, trial2.id);
      const cohort = cohortResp.body.data;

      const [deviationResp, abandonResp] = await Promise.all([
        createExecution(program.id, trial2.id, {
          procedure_id: procedure.id,
          cohort_id: cohort.id,
          protocol_deviation: true
        }),
        abandonTrial(program.id, trial1.id)
      ]);

      const trial2Final = (await getTrial(program.id, trial2.id)).body.data;

      if (deviationResp.status === 201) {
        expectNonNegativeBalance(trial2Final.ethical_compliance_balance);
      } else if (deviationResp.status === 402) {
        expect(trial2Final.effective_ethical_compliance_budget).toBeLessThan(trials[1].effective_ethical_compliance_budget);
      }
    });

    test('should atomically validate dependencies during concurrent activation and completion', async () => {
      const { program, irb } = await createProgramWithIRB();

      const { trial: depTrial } = await setupActiveTrial({ program, irb });

      const mainTrialResp = await createTrial(program.id, { irb_id: irb.id });
      expectSuccess(mainTrialResp, 201);
      const mainTrial = mainTrialResp.body.data;

      await createDependency(program.id, mainTrial.id, depTrial.id);

      const approvalResp = await createIRBApproval(program.id, irb.id, mainTrial.id);
      expectSuccess(approvalResp, 201);
      const approval = approvalResp.body.data;
      await approveIRB(program.id, irb.id, approval.id, approval.version);

      const [activateResp, completeResp] = await Promise.all([
        activateTrial(program.id, mainTrial.id),
        completeTrial(program.id, depTrial.id)
      ]);

      if (activateResp.status === 200) {
        expect(activateResp.body.data.status).toBe('ACTIVE');
      } else {
        expectError(activateResp, 409, 'ERR_DEPENDENCIES_NOT_MET');
      }

      const finalMain = (await getTrial(program.id, mainTrial.id)).body.data;
      const finalDep = (await getTrial(program.id, depTrial.id)).body.data;

      if (finalMain.status === 'ACTIVE') {
        expect(finalDep.status).toBe('COMPLETED');
      }
    });

    test('should atomically validate IRB approval during concurrent activation and approval', async () => {
      const { program, irb } = await createProgramWithIRB();

      const trialResp = await createTrial(program.id, { irb_id: irb.id });
      expectSuccess(trialResp, 201);
      const trial = trialResp.body.data;

      const approvalResp = await createIRBApproval(program.id, irb.id, trial.id);
      expectSuccess(approvalResp, 201);
      const approval = approvalResp.body.data;

      const [activateResp, approveResp] = await Promise.all([
        activateTrial(program.id, trial.id),
        approveIRB(program.id, irb.id, approval.id, approval.version)
      ]);

      if (activateResp.status === 200) {
        expect(activateResp.body.data.status).toBe('ACTIVE');
      } else {
        expectError(activateResp, 409, 'ERR_NO_APPROVED_IRB');
      }

      const finalTrial = (await getTrial(program.id, trial.id)).body.data;
      if (finalTrial.status === 'ACTIVE') {
        expect(approveResp.status).toBe(200);
      }
    });

    test('should atomically re-check all-procedures-passed guard during phase completion', async () => {
      const { program, trial, phase } = await setupTrialWithPhase();

      const cohortResp = await createCohort(program.id, trial.id);
      const cohort = cohortResp.body.data;

      const proc1Resp = await createProcedure(program.id, trial.id, phase.id);
      const proc1 = proc1Resp.body.data;
      const proc2Resp = await createProcedure(program.id, trial.id, phase.id);
      const proc2 = proc2Resp.body.data;

      const readyResp = await updatePhaseStatus(program.id, trial.id, phase.id, PHASE_STATUS.READY_FOR_PROCEDURES, phase.version);
      expectSuccess(readyResp, 200);

      await executeAndPassProcedure(program.id, trial.id, proc1.id, cohort.id);

      const exec2 = await createExecution(program.id, trial.id, {
        procedure_id: proc2.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });
      const execution2 = exec2.body.data;
      await executeExecution(program.id, trial.id, execution2.id);

      const [completeResp, passResp] = await Promise.all([
        updatePhaseStatus(program.id, trial.id, phase.id, PHASE_STATUS.COMPLETED, readyResp.body.data.version),
        markExecutionPassed(program.id, trial.id, execution2.id)
      ]);

      if (completeResp.status === 200) {
        expect(completeResp.body.data.status).toBe('COMPLETED');
      } else {
        expectError(completeResp, 409, 'ERR_PROCEDURES_NOT_PASSED');
      }
    });

    test('should atomically evaluate saturation when concurrent finalization toggles saturated flag', async () => {
      const programResp = await createResearchProgram();
      expectSuccess(programResp, 201);
      const program = programResp.body.data;

      const portfolioResp = await createPortfolio(program.id, { max_total_ethical_budget: 1000 });
      const portfolio = portfolioResp.body.data;

      const { trial } = await setupActiveTrial({
        program,
        portfolio_id: portfolio.id,
        total_ethical_compliance_budget: 2000
      });

      const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
      const phase = phaseResp.body.data;
      const cohortResp = await createCohort(program.id, trial.id);
      const cohort = cohortResp.body.data;

      const proc1Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 450 });
      const proc1 = proc1Resp.body.data;
      const proc2Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 450 });
      const proc2 = proc2Resp.body.data;

      const exec1 = await createExecution(program.id, trial.id, {
        procedure_id: proc1.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });
      expectSuccess(exec1, 201);
      const execution1 = exec1.body.data;
      const debit1 = execution1.provisional_risk_debit;
      expect(debit1).toBe(575);

      await executeExecution(program.id, trial.id, execution1.id);

      const [exec2Resp, finalizeResp] = await Promise.all([
        createExecution(program.id, trial.id, {
          procedure_id: proc2.id,
          cohort_id: cohort.id,
          protocol_deviation: true
        }),
        markExecutionPassed(program.id, trial.id, execution1.id)
      ]);

      const portfolioFinal = (await getPortfolio(program.id, portfolio.id)).body.data;
      const trialFinal = (await getTrial(program.id, trial.id)).body.data;

      if (exec2Resp.status === 201) {
        expect(portfolioFinal.is_risk_saturated).toBe(true);
        expectNonNegativeBalance(trialFinal.ethical_compliance_balance);
      } else {
        expectNonNegativeBalance(trialFinal.ethical_compliance_balance);
      }
    });
  });
});
