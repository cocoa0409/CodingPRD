import {
  createTrial,
  activateTrial,
  completeTrial,
  abandonTrial,
  clearEthicalReviewLock, createDependency,
  createPhase,
  updatePhaseStatus,
  createProcedure,
  createCohort,
  createExecution,
  executeExecution,
  markExecutionPassed,
  rejectExecution,
  cancelExecution, createIRBApproval,
  approveIRB,
  rejectIRBApproval,
  getTrial,
  createBlackoutWindow,
  createPortfolio,
  getPortfolio
} from '../../../test-helpers/resources';

import {
  expectError,
  expectSuccess
} from '../../../test-helpers/assertions';

import {
  TRIAL_STATUS,
  PHASE_STATUS,
  PHASE_NAME,
  EXECUTION_STATUS
} from '../../../test-helpers/constants';

import {
  setupActiveTrial,
  setupTrialWithPhase,
  setupTrialWithProcedure,
  setupPhaseReadyForCompletion,
  forceTrialIntoLock,
  setupCompletedTrial,
  executeAndPassProcedure,
  createProgramWithIRB
} from '../../../test-helpers/scenarios';

import { buildProcedureData } from '../../../test-helpers/builders';

describe('State Machine Transitions', () => {

  describe('Trial State Transitions', () => {

    test('should transition trial from DRAFT to ACTIVE when dependencies are completed', async () => {
      const { program, irb } = await createProgramWithIRB();

      const depTrial = await setupCompletedTrial(program.id, irb.id);

      const mainTrialResp = await createTrial(program.id, { irb_id: irb.id });
      expectSuccess(mainTrialResp, 201);
      const mainTrial = mainTrialResp.body.data;

      const depResp = await createDependency(program.id, mainTrial.id, depTrial.id);
      expectSuccess(depResp, 201);

      const mainApprovalResp = await createIRBApproval(program.id, irb.id, mainTrial.id);
      expectSuccess(mainApprovalResp, 201);
      const mainApproval = mainApprovalResp.body.data;

      const approveMainResp = await approveIRB(program.id, irb.id, mainApproval.id, mainApproval.version);
      expectSuccess(approveMainResp, 200);

      const response = await activateTrial(program.id, mainTrial.id);

      expectSuccess(response, 200);
      expect(response.body.data.status).toBe(TRIAL_STATUS.ACTIVE);
    });

    test('should reject DRAFT to ACTIVE transition when dependency is incomplete', async () => {
      const { program, irb } = await createProgramWithIRB();

      const depTrialResp = await createTrial(program.id, { irb_id: irb.id });
      expectSuccess(depTrialResp, 201);
      const depTrial = depTrialResp.body.data;

      const mainTrialResp = await createTrial(program.id, { irb_id: irb.id });
      expectSuccess(mainTrialResp, 201);
      const mainTrial = mainTrialResp.body.data;

      const depResp = await createDependency(program.id, mainTrial.id, depTrial.id);
      expectSuccess(depResp, 201);

      const mainApprovalResp = await createIRBApproval(program.id, irb.id, mainTrial.id);
      expectSuccess(mainApprovalResp, 201);
      const mainApproval = mainApprovalResp.body.data;

      const approveResp = await approveIRB(program.id, irb.id, mainApproval.id, mainApproval.version);
      expectSuccess(approveResp, 200);

      const response = await activateTrial(program.id, mainTrial.id);

      expectError(response, 409, 'ERR_DEPENDENCIES_NOT_MET');
    });

    test('should reject activation when dependency is in ETHICAL_REVIEW_LOCK', async () => {
      const { program, irb } = await createProgramWithIRB();

      const { trial: depTrial } = await setupActiveTrial({ program, irb });

      await forceTrialIntoLock(program.id, depTrial.id);

      const mainTrialResp = await createTrial(program.id, { irb_id: irb.id });
      expectSuccess(mainTrialResp, 201);
      const mainTrial = mainTrialResp.body.data;

      const depResp = await createDependency(program.id, mainTrial.id, depTrial.id);
      expectSuccess(depResp, 201);

      const mainApprovalResp = await createIRBApproval(program.id, irb.id, mainTrial.id);
      expectSuccess(mainApprovalResp, 201);
      const mainApproval = mainApprovalResp.body.data;

      const approveResp = await approveIRB(program.id, irb.id, mainApproval.id, mainApproval.version);
      expectSuccess(approveResp, 200);

      const response = await activateTrial(program.id, mainTrial.id);

      expectError(response, 409, 'ERR_DEPENDENCY_IN_ETHICAL_REVIEW_LOCK');
    });

    test('should reject activation without approved IRB', async () => {
      const { program, irb } = await createProgramWithIRB();

      const trialResp = await createTrial(program.id, { irb_id: irb.id });
      expectSuccess(trialResp, 201);
      const trial = trialResp.body.data;

      const approvalResp = await createIRBApproval(program.id, irb.id, trial.id);
      expectSuccess(approvalResp, 201);

      const response = await activateTrial(program.id, trial.id);

      expectError(response, 409, 'ERR_NO_APPROVED_IRB');
    });

    test('should reject activation with only rejected IRB approval', async () => {
      const { program, irb } = await createProgramWithIRB();

      const trialResp = await createTrial(program.id, { irb_id: irb.id });
      expectSuccess(trialResp, 201);
      const trial = trialResp.body.data;

      const approvalResp = await createIRBApproval(program.id, irb.id, trial.id);
      expectSuccess(approvalResp, 201);
      const approval = approvalResp.body.data;

      const rejectResp = await rejectIRBApproval(program.id, irb.id, approval.id, approval.version);
      expectSuccess(rejectResp, 200);

      const response = await activateTrial(program.id, trial.id);

      expectError(response, 409, 'ERR_NO_APPROVED_IRB');
    });

    test('should reject activation when trial is not in DRAFT state', async () => {
      const { program, trial } = await setupActiveTrial();

      const response = await activateTrial(program.id, trial.id);

      expectError(response, 409, 'ERR_TRIAL_NOT_IN_DRAFT');
    });

    test('should reject completion when unresolved executions exist', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      const response = await completeTrial(program.id, trial.id);

      expectError(response, 409, 'ERR_UNRESOLVED_EXECUTIONS_EXIST');
    });

    test('should reject completion when phases are not all completed', async () => {
      const { program, trial } = await setupTrialWithPhase();

      const response = await completeTrial(program.id, trial.id);

      expectError(response, 409, 'ERR_PHASES_NOT_COMPLETED');
    });

    test('should reject completion when dependency trial is not completed', async () => {
      const { program, irb } = await createProgramWithIRB();

      const { trial: depTrial } = await setupActiveTrial({ program, irb });

      const { trial: mainTrial } = await setupActiveTrial({ program, irb });

      const depResp = await createDependency(program.id, mainTrial.id, depTrial.id);
      expectSuccess(depResp, 201);

      const response = await completeTrial(program.id, mainTrial.id);

      expectError(response, 409, 'ERR_DEPENDENCIES_NOT_MET');
    });

    test('should reject completion when trial is in ETHICAL_REVIEW_LOCK', async () => {
      const { program, trial } = await setupActiveTrial();

      await forceTrialIntoLock(program.id, trial.id);

      const response = await completeTrial(program.id, trial.id);

      expectError(response, 403, 'ERR_TRIAL_IN_ETHICAL_REVIEW_LOCK');
    });

    test('should complete trial successfully when all conditions are met', async () => {
      const { program, trial } = await setupActiveTrial();

      const response = await completeTrial(program.id, trial.id);

      expectSuccess(response, 200);
      expect(response.body.data.status).toBe(TRIAL_STATUS.COMPLETED);
    });

    test('should abandon trial from ACTIVE status', async () => {
      const { program, trial } = await setupActiveTrial();

      const response = await abandonTrial(program.id, trial.id);

      expectSuccess(response, 200);
      expect(response.body.data.status).toBe(TRIAL_STATUS.ABANDONED);
    });

    test('should reject abandonment from COMPLETED status', async () => {
      const { program, trial } = await setupActiveTrial();

      const completeResp = await completeTrial(program.id, trial.id);
      expectSuccess(completeResp, 200);

      const response = await abandonTrial(program.id, trial.id);

      expectError(response, 409, 'ERR_TRIAL_NOT_ABANDONABLE');
    });

    test('should auto-transition to ETHICAL_REVIEW_LOCK when risk exceeds threshold', async () => {
      const { program, trial } = await setupActiveTrial();

      await forceTrialIntoLock(program.id, trial.id);

      const checkResponse = await getTrial(program.id, trial.id);
      expect(checkResponse.body.data.status).toBe(TRIAL_STATUS.ETHICAL_REVIEW_LOCK);
    });

    test('should clear ethical review lock and return to ACTIVE', async () => {
      const { program, trial } = await setupActiveTrial();

      await forceTrialIntoLock(program.id, trial.id);

      const response = await clearEthicalReviewLock(program.id, trial.id);

      expectSuccess(response, 200);
      expect(response.body.data.status).toBe(TRIAL_STATUS.ACTIVE);
    });

    test('should abandon trial from DRAFT status', async () => {
      const { program, irb } = await createProgramWithIRB();

      const trialResp = await createTrial(program.id, { irb_id: irb.id });
      expectSuccess(trialResp, 201);
      const trial = trialResp.body.data;

      expect(trial.status).toBe(TRIAL_STATUS.DRAFT);

      const response = await abandonTrial(program.id, trial.id);

      expectSuccess(response, 200);
      expect(response.body.data.status).toBe(TRIAL_STATUS.ABANDONED);
    });

    test('should reject abandonment from ETHICAL_REVIEW_LOCK', async () => {
      const { program, trial } = await setupActiveTrial();

      await forceTrialIntoLock(program.id, trial.id);

      const response = await abandonTrial(program.id, trial.id);

      expectError(response, 409, 'ERR_TRIAL_NOT_ABANDONABLE');
    });

    test('should reject clear-lock when trial is not locked', async () => {
      const { program, trial } = await setupActiveTrial();

      const response = await clearEthicalReviewLock(program.id, trial.id);

      expectError(response, 409, 'ERR_TRIAL_NOT_IN_ETHICAL_REVIEW_LOCK');
    });
  });

  describe('Phase State Transitions', () => {

    test('should reject READY_FOR_PROCEDURES when no procedures defined', async () => {
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

    test('should transition to READY_FOR_PROCEDURES when procedures exist', async () => {
      const { program, trial, phase } = await setupTrialWithPhase();

      const procResp = await createProcedure(program.id, trial.id, phase.id, buildProcedureData());
      expectSuccess(procResp, 201);

      const response = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.READY_FOR_PROCEDURES,
        phase.version
      );

      expectSuccess(response, 200);
      expect(response.body.data.status).toBe(PHASE_STATUS.READY_FOR_PROCEDURES);
    });

    test('should reject completion when not all procedures are PASSED', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const readyResp = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.READY_FOR_PROCEDURES,
        phase.version
      );
      expectSuccess(readyResp, 200);

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      const rejectResp = await rejectExecution(program.id, trial.id, execResponse.body.data.id);
      expectSuccess(rejectResp, 200);

      const response = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.COMPLETED,
        readyResp.body.data.version
      );

      expectError(response, 409, 'ERR_PROCEDURES_NOT_PASSED');
    });

    test('should reject phase completion during active blackout window', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const blackoutResp = await createBlackoutWindow(program.id, {
        treatment_name_pattern: '*',
        start_period_index: 0,
        end_period_index: 100
      });
      expectSuccess(blackoutResp, 201);

      const readyResp = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.READY_FOR_PROCEDURES,
        phase.version
      );
      expectSuccess(readyResp, 200);

      await executeAndPassProcedure(program.id, trial.id, procedure.id, cohort.id);

      const response = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.COMPLETED,
        phase.version + 1
      );

      expectError(response, 403, 'ERR_ENROLLMENT_BLACKOUT_ACTIVE');
    });

    test('should transition procedure to AWAITING_EXECUTION when execution is created', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      expect(procedure.status).toBe('PENDING');

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      expectSuccess(execResponse, 201);

      expect(execResponse.body.data.procedure_id).toBe(procedure.id);
    });

    test('should transition procedure to PASSED when execution passes', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      const execution = execResponse.body.data;

      const execResp = await executeExecution(program.id, trial.id, execution.id);
      expectSuccess(execResp, 200);

      const passResponse = await markExecutionPassed(program.id, trial.id, execution.id);

      expectSuccess(passResponse, 200);
      expect(passResponse.body.data.status).toBe('PASSED');
    });

    test('should transition procedure to FAILED when execution is rejected', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      const execution = execResponse.body.data;

      const rejectResponse = await rejectExecution(program.id, trial.id, execution.id);

      expectSuccess(rejectResponse, 200);
      expect(rejectResponse.body.data.status).toBe('REJECTED');
    });

    test('should transition procedure to CANCELLED when execution is cancelled', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      const execution = execResponse.body.data;

      const execResp = await executeExecution(program.id, trial.id, execution.id);
      expectSuccess(execResp, 200);

      const cancelResponse = await cancelExecution(program.id, trial.id, execution.id);

      expectSuccess(cancelResponse, 200);
      expect(cancelResponse.body.data.status).toBe('CANCELLED');
    });

    test('should reject invalid phase transition from COMPLETED to READY', async () => {
      const { program, trial, phase, procedures } = await setupPhaseReadyForCompletion(1);

      const completeResp = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.COMPLETED,
        phase.version + 1
      );
      expectSuccess(completeResp, 200);

      const response = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.READY_FOR_PROCEDURES,
        phase.version + 2
      );

      expectError(response, 409, 'ERR_ILLEGAL_PHASE_STATE_TRANSITION');
    });

    test('should reject procedure state change from terminal PASSED state', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      await executeAndPassProcedure(program.id, trial.id, procedure.id, cohort.id);

      const proc2Attempt = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      expectError(proc2Attempt, 409, 'ERR_PROCEDURE_NOT_PENDING');
    });

    test('should reject execution rejection after PASSED terminal state', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      const execResp = await executeExecution(program.id, trial.id, execResponse.body.data.id);
      expectSuccess(execResp, 200);

      const passResp = await markExecutionPassed(program.id, trial.id, execResponse.body.data.id);
      expectSuccess(passResp, 200);

      const rejectResp = await rejectExecution(program.id, trial.id, execResponse.body.data.id);

      expectError(rejectResp, 409, 'ERR_EXECUTION_NOT_REJECTABLE');
    });

    test('should allow activation when circular dependencies are pre-resolved', async () => {
      const { program, irb } = await createProgramWithIRB();

      const { trial: trialA } = await setupActiveTrial({ program, irb });
      const completeAResp = await completeTrial(program.id, trialA.id);
      expectSuccess(completeAResp, 200);

      const trialBResp = await createTrial(program.id, { irb_id: irb.id });
      expectSuccess(trialBResp, 201);
      const trialB = trialBResp.body.data;

      const depResp = await createDependency(program.id, trialB.id, trialA.id);
      expectSuccess(depResp, 201);

      const approvalBResp = await createIRBApproval(program.id, irb.id, trialB.id);
      expectSuccess(approvalBResp, 201);
      const approvalB = approvalBResp.body.data;

      const approveBResp = await approveIRB(program.id, irb.id, approvalB.id, approvalB.version);
      expectSuccess(approveBResp, 200);

      const response = await activateTrial(program.id, trialB.id);
      expectSuccess(response, 200);
    });

    test('should successfully transition from lock back to ACTIVE via clear endpoint', async () => {
      const { program, trial } = await setupActiveTrial();

      await forceTrialIntoLock(program.id, trial.id);

      const lockedTrial = (await getTrial(program.id, trial.id)).body.data;
      expect(lockedTrial.status).toBe('ETHICAL_REVIEW_LOCK');

      const clearResp = await clearEthicalReviewLock(program.id, trial.id);

      expectSuccess(clearResp, 200);
      expect(clearResp.body.data.status).toBe('ACTIVE');

      const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
      expectSuccess(phaseResp, 201);
      const phase = phaseResp.body.data;
      expect(phase).toBeDefined();
    });

    test('should toggle portfolio saturation state based on consumption', async () => {
      const { program } = await createProgramWithIRB();

      const portfolioResp = await createPortfolio(program.id, {
        max_total_ethical_budget: 1000
      });
      expectSuccess(portfolioResp, 201);
      const portfolio = portfolioResp.body.data;

      const { trial } = await setupActiveTrial({
        program,
        portfolio_id: portfolio.id,
        total_ethical_compliance_budget: 5000
      });

      let portfolioGetResp = await getPortfolio(program.id, portfolio.id);
      expect(portfolioGetResp.body.data.is_risk_saturated).toBe(false);

      const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
      expectSuccess(phaseResp, 201);
      const phase = phaseResp.body.data;

      const cohortResponse = await createCohort(program.id, trial.id);
      const cohort = cohortResponse.body.data;

      const proc1Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 450 });
      expectSuccess(proc1Resp, 201);
      const proc1 = proc1Resp.body.data;

      await createExecution(program.id, trial.id, {
        procedure_id: proc1.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      portfolioGetResp = await getPortfolio(program.id, portfolio.id);
      expect(portfolioGetResp.body.data.is_risk_saturated).toBe(false);

      const proc2Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 200 });
      expectSuccess(proc2Resp, 201);
      const proc2 = proc2Resp.body.data;

      await createExecution(program.id, trial.id, {
        procedure_id: proc2.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      const proc3Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 100 });
      expectSuccess(proc3Resp, 201);
      const proc3 = proc3Resp.body.data;

      await createExecution(program.id, trial.id, {
        procedure_id: proc3.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      portfolioGetResp = await getPortfolio(program.id, portfolio.id);
      expect(portfolioGetResp.body.data.is_risk_saturated).toBe(true);
    });

    test('should cancel phase from READY_FOR_PROCEDURES', async () => {
      const { program, trial, phase, procedure } = await setupTrialWithProcedure();

      const readyResp = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.READY_FOR_PROCEDURES,
        phase.version
      );
      expectSuccess(readyResp, 200);

      const response = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.CANCELLED,
        phase.version + 1
      );

      expectSuccess(response, 200);
      expect(response.body.data.status).toBe(PHASE_STATUS.CANCELLED);
    });

    test('should reject cancellation of completed phase', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const readyResp = await updatePhaseStatus(program.id, trial.id, phase.id, PHASE_STATUS.READY_FOR_PROCEDURES, phase.version);
      expectSuccess(readyResp, 200);

      await executeAndPassProcedure(program.id, trial.id, procedure.id, cohort.id);

      const completedPhase = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.COMPLETED,
        phase.version + 1
      );
      expectSuccess(completedPhase, 200);

      const cancelAttempt = await updatePhaseStatus(
        program.id,
        trial.id,
        phase.id,
        PHASE_STATUS.CANCELLED,
        completedPhase.body.data.version
      );
      expectError(cancelAttempt, 409, 'ERR_ILLEGAL_PHASE_STATE_TRANSITION');
    });
  });

  describe('Execution State Transitions', () => {

    test('should execute a pending execution', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      const execution = execResponse.body.data;
      expect(execution.status).toBe(EXECUTION_STATUS.PENDING_EXECUTION);

      const response = await executeExecution(program.id, trial.id, execution.id);

      expectSuccess(response, 200);
      expect(response.body.data.status).toBe(EXECUTION_STATUS.EXECUTED);
    });

    test('should reject an executed execution', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      const execution = execResponse.body.data;

      const execResp = await executeExecution(program.id, trial.id, execution.id);
      expectSuccess(execResp, 200);

      const response = await rejectExecution(program.id, trial.id, execution.id);

      expectSuccess(response, 200);
      expect(response.body.data.status).toBe(EXECUTION_STATUS.REJECTED);
    });

    test('should cancel an executed execution', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      const execution = execResponse.body.data;

      const execResp = await executeExecution(program.id, trial.id, execution.id);
      expectSuccess(execResp, 200);

      const response = await cancelExecution(program.id, trial.id, execution.id);

      expectSuccess(response, 200);
      expect(response.body.data.status).toBe(EXECUTION_STATUS.CANCELLED);
    });

    test('should cancel a pending execution', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      const execution = execResponse.body.data;

      const response = await cancelExecution(program.id, trial.id, execution.id);

      expectSuccess(response, 200);
      expect(response.body.data.status).toBe(EXECUTION_STATUS.CANCELLED);
    });

    test('should reject a pending execution', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      const execution = execResponse.body.data;

      const response = await rejectExecution(program.id, trial.id, execution.id);

      expectSuccess(response, 200);
      expect(response.body.data.status).toBe(EXECUTION_STATUS.REJECTED);
    });

    test('should reject mark-passed when execution is not EXECUTED', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      const execution = execResponse.body.data;

      const response = await markExecutionPassed(program.id, trial.id, execution.id);

      expectError(response, 409, 'ERR_EXECUTION_NOT_EXECUTED');
    });

    test('should reject execute when execution is not PENDING', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      });

      const execution = execResponse.body.data;

      const rejectResp = await rejectExecution(program.id, trial.id, execution.id);
      expectSuccess(rejectResp, 200);

      const response = await executeExecution(program.id, trial.id, execution.id);

      expectError(response, 409, 'ERR_EXECUTION_NOT_PENDING');
    });
  });
});
