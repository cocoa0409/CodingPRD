import {
  createExecution,
  executeExecution,
  markExecutionPassed,
  rejectExecution,
  cancelExecution,
  abandonTrial,
  manualRiskAdjustment,
  getTrial,
  updatePhaseStatus,
  createPhase,
  createProcedure,
  createCohort,
  advanceClock,
  createBlackoutWindow,
  updatePortfolio,
  getPortfolio,
  clearEthicalReviewLock,
  createResearchProgram,
  createTrial,
  activateTrial,
  completeTrial,
  createIRB,
  createIRBApproval,
  approveIRB,
  createDependency,
  createPortfolio
} from '../../../test-helpers/resources';

import {
  expectSuccess,
  expectNonNegativeBalance,
  expectError
} from '../../../test-helpers/assertions';

import {
  PHASE_STATUS,
  PHASE_NAME, DEVIATION_REJECTION_PENALTY, CONTAGION_PENALTY,
  EXPEDITED_THRESHOLD_POINTS,
  EXPEDITED_MULTIPLIER
} from '../../../test-helpers/constants';

import {
  calculateProvisionalDebit
} from '../../../test-helpers/calculations';

import {
  setupTrialWithProcedure,
  setupPortfolioWithTrials,
  setupActiveTrial,
  setupTrialWithPhase,
  setupPhaseReadyForCompletion,
  setupMultipleTrialsForInvestigator,
  setupTrialWithActiveDeviations,
  setupTrialNearExpeditedThreshold,
  forceTrialIntoLock,
  setupCompletedTrial,
  executeAndPassProcedure,
  driveInvestigatorIntoProbation,
  triggerPhaseReviewRequired
} from '../../../test-helpers/scenarios';

import { generateUserId, generateInvestigatorId } from '../../../test-helpers/builders';

describe('Complex Workflows', () => {

  test('should complete full deviation lifecycle with correct ledger updates', async () => {
    const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure({
      base_risk_cost: 100
    });

    const initialTrial = (await getTrial(program.id, trial.id)).body.data;
    const initialBalance = initialTrial.ethical_compliance_balance;

    const execResponse = await createExecution(program.id, trial.id, {
      procedure_id: procedure.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });

    const execution = execResponse.body.data;
    const provisionalDebit = execution.provisional_risk_debit;

    const afterProposal = (await getTrial(program.id, trial.id)).body.data;
    expect(afterProposal.ethical_compliance_balance).toBe(initialBalance - provisionalDebit);

    const execResp = await executeExecution(program.id, trial.id, execution.id);
    expectSuccess(execResp, 200);

    const passedResponse = await markExecutionPassed(program.id, trial.id, execution.id);
    const passedExecution = passedResponse.body.data;

    expect(passedExecution.status).toBe('PASSED');
    expect(passedExecution.final_risk_debit).toBe(provisionalDebit);

    const afterPass = (await getTrial(program.id, trial.id)).body.data;
    expect(afterPass.ethical_compliance_balance).toBe(initialBalance - provisionalDebit);
  });

  test('should restore provisional and increase risk on rejection', async () => {
    const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure({
      base_risk_cost: 150
    });

    const initialTrial = (await getTrial(program.id, trial.id)).body.data;
    const initialRisk = initialTrial.patient_safety_risk;
    const initialBalance = initialTrial.ethical_compliance_balance;
    expect(initialRisk).toBe(0);

    const execResponse = await createExecution(program.id, trial.id, {
      procedure_id: procedure.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });

    const execution = execResponse.body.data;
    const provisionalDebit = execution.provisional_risk_debit;

    const afterProposal = (await getTrial(program.id, trial.id)).body.data;
    expect(afterProposal.ethical_compliance_balance).toBe(initialBalance - provisionalDebit);

    const rejectResp = await rejectExecution(program.id, trial.id, execution.id);
    expectSuccess(rejectResp, 200);

    const afterReject = (await getTrial(program.id, trial.id)).body.data;

    expect(afterReject.ethical_compliance_balance).toBe(initialBalance);

    expect(afterReject.patient_safety_risk).toBe(initialRisk + DEVIATION_REJECTION_PENALTY);
    expect(afterReject.patient_safety_risk).toBe(5);

    expect(afterReject.status).toBe('ACTIVE');
  });

  test('should reduce patient safety risk on non-deviation PASS', async () => {
    const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure({
      integrity_score_value: 30
    });

    await manualRiskAdjustment(program.id, trial.id, 50, 'Increase for test');

    const beforeExec = (await getTrial(program.id, trial.id)).body.data;
    const initialRisk = beforeExec.patient_safety_risk;

    await executeAndPassProcedure(program.id, trial.id, procedure.id, cohort.id, false);

    const afterPass = (await getTrial(program.id, trial.id)).body.data;

    expect(afterPass.patient_safety_risk).toBe(Math.max(0, initialRisk - 30));
  });

  test('should complete phase progression workflow', async () => {
    const { program, trial, phase, procedures } = await setupPhaseReadyForCompletion(2);

    const response = await updatePhaseStatus(
      program.id,
      trial.id,
      phase.id,
      PHASE_STATUS.COMPLETED,
      phase.version + 1
    );

    expectSuccess(response, 200);
    expect(response.body.data.status).toBe(PHASE_STATUS.COMPLETED);
  });

  test('should allow phase completion after advancing past blackout', async () => {
    const { program, trial } = await setupActiveTrial({
      treatment_name: 'Test Treatment'
    });

    const blackoutResp = await createBlackoutWindow(program.id, {
      treatment_name_pattern: '*',
      start_period_index: 0,
      end_period_index: 10
    });
    expectSuccess(blackoutResp, 201);

    const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
    expectSuccess(phaseResp, 201);
    const phase = phaseResp.body.data;

    const procResp = await createProcedure(program.id, trial.id, phase.id);
    expectSuccess(procResp, 201);
    const procedure = procResp.body.data;

    const cohortResponse = await createCohort(program.id, trial.id);
    const cohort = cohortResponse.body.data;

    const readyResp = await updatePhaseStatus(
      program.id,
      trial.id,
      phase.id,
      PHASE_STATUS.READY_FOR_PROCEDURES,
      phase.version
    );
    expectSuccess(readyResp, 200);

    await executeAndPassProcedure(program.id, trial.id, procedure.id, cohort.id);

    let completeResponse = await updatePhaseStatus(
      program.id,
      trial.id,
      phase.id,
      PHASE_STATUS.COMPLETED,
      phase.version + 1
    );

    expectError(completeResponse, 403, 'ERR_ENROLLMENT_BLACKOUT_ACTIVE');

    const clockResp = await advanceClock(program.id, 11);
    expectSuccess(clockResp, 200);

    completeResponse = await updatePhaseStatus(
      program.id,
      trial.id,
      phase.id,
      PHASE_STATUS.COMPLETED,
      phase.version + 1
    );

    expectSuccess(completeResponse, 200);
  });

  test('should complete full activation workflow with dependencies', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const irbResp = await createIRB(program.id);
    expectSuccess(irbResp, 201);
    const irb = irbResp.body.data;

    const depTrial = await setupCompletedTrial(program.id, irb.id);

    const mainTrialResp = await createTrial(program.id, { irb_id: irb.id });
    expectSuccess(mainTrialResp, 201);
    const mainTrial = mainTrialResp.body.data;

    const depResp = await createDependency(program.id, mainTrial.id, depTrial.id);
    expectSuccess(depResp, 201);

    const approvalResp = await createIRBApproval(program.id, irb.id, mainTrial.id);
    expectSuccess(approvalResp, 201);
    const approval = approvalResp.body.data;

    const approveResp = await approveIRB(program.id, irb.id, approval.id, approval.version);
    expectSuccess(approveResp, 200);

    const activateResponse = await activateTrial(program.id, mainTrial.id);

    expectSuccess(activateResponse, 200);
    expect(activateResponse.body.data.status).toBe('ACTIVE');
  });

  test('should abandon trial with pending deviations and reverse ledgers', async () => {
    const { program, trial, executions } = await setupTrialWithActiveDeviations(2);

    const beforeAbandon = (await getTrial(program.id, trial.id)).body.data;
    const balanceBefore = beforeAbandon.ethical_compliance_balance;

    const abandonResponse = await abandonTrial(program.id, trial.id);

    expectSuccess(abandonResponse, 200);
    expect(abandonResponse.body.data.status).toBe('ABANDONED');

    const afterAbandon = (await getTrial(program.id, trial.id)).body.data;

    expect(afterAbandon.ethical_compliance_balance).toBe(afterAbandon.effective_ethical_compliance_budget);
    expectNonNegativeBalance(afterAbandon.ethical_compliance_balance);

    const expectedEffective = Math.floor(beforeAbandon.total_ethical_compliance_budget * 0.9);
    expect(afterAbandon.effective_ethical_compliance_budget).toBe(expectedEffective);
  });

  test('should reject deviation after reputation drop shrinks budget', async () => {
    const { program, investigatorId, trials } = await setupMultipleTrialsForInvestigator(2);

    const trial1 = trials[0];
    const trial2 = trials[1];

    const phaseResp = await createPhase(program.id, trial2.id, PHASE_NAME.PHASE_I);
    expectSuccess(phaseResp, 201);
    const phase = phaseResp.body.data;

    const procResp = await createProcedure(program.id, trial2.id, phase.id, {
      base_risk_cost: 5000
    });
    expectSuccess(procResp, 201);
    const procedure = procResp.body.data;

    const cohortResponse = await createCohort(program.id, trial2.id);
    const cohort = cohortResponse.body.data;

    const exec1Response = await createExecution(program.id, trial2.id, {
      procedure_id: procedure.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });
    expectSuccess(exec1Response, 201);

    const abandonResp = await abandonTrial(program.id, trial1.id);
    expectSuccess(abandonResp, 200);

    const updatedTrial2 = (await getTrial(program.id, trial2.id)).body.data;
    expect(updatedTrial2.effective_ethical_compliance_budget).toBeLessThan(
      trial2.effective_ethical_compliance_budget
    );
    const expectedEffective = Math.floor(trial2.total_ethical_compliance_budget * 0.9);
    expect(updatedTrial2.effective_ethical_compliance_budget).toBe(expectedEffective);

    const proc2Resp = await createProcedure(program.id, trial2.id, phase.id, {
      base_risk_cost: 5000
    });
    expectSuccess(proc2Resp, 201);
    const procedure2 = proc2Resp.body.data;

    const exec2Response = await createExecution(program.id, trial2.id, {
      procedure_id: procedure2.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });

    expectError(exec2Response, 402, 'ERR_INSUFFICIENT_ETHICAL_BUDGET');
  });

  test('should block deviation when portfolio becomes saturated', async () => {
    const { program, portfolio, trials } = await setupPortfolioWithTrials(2);

    const trial1 = trials[0];

    const phaseResp = await createPhase(program.id, trial1.id, PHASE_NAME.PHASE_I);
    expectSuccess(phaseResp, 201);
    const phase = phaseResp.body.data;

    const cohortResponse = await createCohort(program.id, trial1.id);
    const cohort = cohortResponse.body.data;

    const updatedPortfolioResp = await updatePortfolio(program.id, portfolio.id, {
      max_total_ethical_budget: 600,
      version: portfolio.version
    });
    expectSuccess(updatedPortfolioResp, 200);

    const largeProcResp = await createProcedure(program.id, trial1.id, phase.id, {
      base_risk_cost: 450
    });
    expectSuccess(largeProcResp, 201);
    const largeProcedure = largeProcResp.body.data;

    const execResponse = await createExecution(program.id, trial1.id, {
      procedure_id: largeProcedure.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });
    expectSuccess(execResponse, 201);
    const execution = execResponse.body.data;

    await executeExecution(program.id, trial1.id, execution.id);
    await markExecutionPassed(program.id, trial1.id, execution.id);

    const portfolioResponse = await getPortfolio(program.id, portfolio.id);
    expect(portfolioResponse.body.data.is_risk_saturated).toBe(true);

    const proc2Resp = await createProcedure(program.id, trial1.id, phase.id, {
      base_risk_cost: 100
    });
    expectSuccess(proc2Resp, 201);
    const procedure2 = proc2Resp.body.data;

    const exec2Response = await createExecution(program.id, trial1.id, {
      procedure_id: procedure2.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });

    expectError(exec2Response, 403, 'ERR_PORTFOLIO_RISK_SATURATED');
  });

  test('should trigger lock and contagion on manual risk increase', async () => {
    const { program, portfolio, trials } = await setupPortfolioWithTrials(2);

    const trial1 = trials[0];
    const trial2 = trials[1];

    const initialTrial2 = (await getTrial(program.id, trial2.id)).body.data;
    const initialRisk2 = initialTrial2.patient_safety_risk;

    await forceTrialIntoLock(program.id, trial1.id);

    const lockedTrial1 = (await getTrial(program.id, trial1.id)).body.data;
    expect(lockedTrial1.status).toBe('ETHICAL_REVIEW_LOCK');

    const contagionTrial2 = (await getTrial(program.id, trial2.id)).body.data;
    expect(contagionTrial2.patient_safety_risk).toBe(initialRisk2 + CONTAGION_PENALTY);
    expect(contagionTrial2.is_under_contagion).toBe(true);
  });

  test('should trigger phase REVIEW_REQUIRED after 3 cancellations and block completion', async () => {
    const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

    const readyPhaseResponse = await updatePhaseStatus(
      program.id,
      trial.id,
      phase.id,
      PHASE_STATUS.READY_FOR_PROCEDURES,
      phase.version
    );
    expectSuccess(readyPhaseResponse, 200);
    let currentPhaseVersion = readyPhaseResponse.body.data.version;

    await executeAndPassProcedure(program.id, trial.id, procedure.id, cohort.id);

    await triggerPhaseReviewRequired(program.id, trial.id, phase.id, cohort.id);

    const updatedTrial = (await getTrial(program.id, trial.id)).body.data;
    expect(updatedTrial.deviation_penalty_tier).toBe(3);

    const phaseCurrentVersion = currentPhaseVersion + 1;

    const completionAttempt = await updatePhaseStatus(
      program.id,
      trial.id,
      phase.id,
      PHASE_STATUS.COMPLETED,
      phaseCurrentVersion
    );
    expectError(completionAttempt, 409, 'ERR_PHASE_IN_REVIEW');

    const clearReview = await updatePhaseStatus(
      program.id,
      trial.id,
      phase.id,
      PHASE_STATUS.READY_FOR_PROCEDURES,
      phaseCurrentVersion
    );
    expectSuccess(clearReview, 200);
    expect(clearReview.body.data.status).toBe('READY_FOR_PROCEDURES');

    const phase2Resp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_II);
    expectSuccess(phase2Resp, 201);
    const phase2 = phase2Resp.body.data;

    const proc2Resp = await createProcedure(program.id, trial.id, phase2.id, { base_risk_cost: 10 });
    expectSuccess(proc2Resp, 201);
    const proc2 = proc2Resp.body.data;

    const ready2Resp = await updatePhaseStatus(program.id, trial.id, phase2.id, PHASE_STATUS.READY_FOR_PROCEDURES, phase2.version);
    expectSuccess(ready2Resp, 200);

    await executeAndPassProcedure(program.id, trial.id, proc2.id, cohort.id);

    const completion = await updatePhaseStatus(
      program.id,
      trial.id,
      phase2.id,
      PHASE_STATUS.COMPLETED,
      ready2Resp.body.data.version
    );
    expectSuccess(completion, 200);
    expect(completion.body.data.status).toBe('COMPLETED');
  });

  test('should reset contagion flags when last lock is cleared', async () => {
    const { program, portfolio, trials } = await setupPortfolioWithTrials(2);

    const trial1 = trials[0];

    await forceTrialIntoLock(program.id, trial1.id);

    const trial2After = (await getTrial(program.id, trials[1].id)).body.data;
    expect(trial2After.is_under_contagion).toBe(true);
    expect(trial2After.status).toBe('ACTIVE');

    const clearResp = await clearEthicalReviewLock(program.id, trial1.id);
    expectSuccess(clearResp, 200);

    const trial2AfterClear = (await getTrial(program.id, trials[1].id)).body.data;
    expect(trial2AfterClear.is_under_contagion).toBe(false);
  });

  test('should enable deviations after increasing portfolio cap', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const portfolioResp = await createPortfolio(program.id, {
      max_total_ethical_budget: 100
    });
    expectSuccess(portfolioResp, 201);
    const portfolio = portfolioResp.body.data;

    const { trial } = await setupActiveTrial({
      program,
      portfolio_id: portfolio.id,
      total_ethical_compliance_budget: 200
    });

    const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
    expectSuccess(phaseResp, 201);
    const phase = phaseResp.body.data;

    const procResp = await createProcedure(program.id, trial.id, phase.id, {
      base_risk_cost: 90
    });
    expectSuccess(procResp, 201);
    const procedure = procResp.body.data;

    const cohortResponse = await createCohort(program.id, trial.id);
    const cohort = cohortResponse.body.data;

    const exec1 = await createExecution(program.id, trial.id, {
      procedure_id: procedure.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });
    expectSuccess(exec1, 201);

    const updateResp = await updatePortfolio(program.id, portfolio.id, {
      max_total_ethical_budget: 10000,
      version: portfolio.version
    });
    expectSuccess(updateResp, 200);

    const proc2Resp = await createProcedure(program.id, trial.id, phase.id, {
      base_risk_cost: 50
    });
    expectSuccess(proc2Resp, 201);
    const procedure2 = proc2Resp.body.data;

    const exec2Response = await createExecution(program.id, trial.id, {
      procedure_id: procedure2.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });

    expectSuccess(exec2Response, 201);
  });

  test('should enforce per-user deviation limit across multiple trials', async () => {
    const userId = generateUserId();

    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const { trial: trial1 } = await setupActiveTrial({ program });
    const { trial: trial2 } = await setupActiveTrial({ program });

    const phase1Resp = await createPhase(program.id, trial1.id, PHASE_NAME.PHASE_I);
    expectSuccess(phase1Resp, 201);
    const phase1 = phase1Resp.body.data;

    const cohort1Response = await createCohort(program.id, trial1.id);
    const cohort1 = cohort1Response.body.data;

    for (let i = 0; i < 2; i++) {
      const procResp = await createProcedure(program.id, trial1.id, phase1.id);
      expectSuccess(procResp, 201);
      const proc = procResp.body.data;

      const execResp = await createExecution(
        program.id,
        trial1.id,
        {
          procedure_id: proc.id,
          cohort_id: cohort1.id,
          protocol_deviation: true
        },
        userId
      );
      expectSuccess(execResp, 201);
    }

    const phase2Resp = await createPhase(program.id, trial2.id, PHASE_NAME.PHASE_I);
    expectSuccess(phase2Resp, 201);
    const phase2 = phase2Resp.body.data;

    const cohort2Response = await createCohort(program.id, trial2.id);
    const cohort2 = cohort2Response.body.data;

    const proc2Resp = await createProcedure(program.id, trial2.id, phase2.id);
    expectSuccess(proc2Resp, 201);
    const proc2 = proc2Resp.body.data;

    const exec3 = await createExecution(
      program.id,
      trial2.id,
      {
        procedure_id: proc2.id,
        cohort_id: cohort2.id,
        protocol_deviation: true
      },
      userId
    );
    expectSuccess(exec3, 201);

    const proc3Resp = await createProcedure(program.id, trial2.id, phase2.id);
    expectSuccess(proc3Resp, 201);
    const proc3 = proc3Resp.body.data;

    const exec4Response = await createExecution(
      program.id,
      trial2.id,
      {
        procedure_id: proc3.id,
        cohort_id: cohort2.id,
        protocol_deviation: true
      },
      userId
    );

    expectError(exec4Response, 409, 'ERR_MAX_ACTIVE_DEVIATIONS_PER_USER_VIOLATION');
  });

  test('should allow completion with only non-deviation procedures', async () => {
    const { program, trial, phase, procedures } = await setupPhaseReadyForCompletion(3);

    const completePhaseResp = await updatePhaseStatus(
      program.id,
      trial.id,
      phase.id,
      PHASE_STATUS.COMPLETED,
      phase.version + 1
    );
    expectSuccess(completePhaseResp, 200);

    const response = await completeTrial(program.id, trial.id);

    expectSuccess(response, 200);
  });

  test('should accept non-deviation proposals regardless of budget', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const { trial } = await setupActiveTrial({
      program,
      total_ethical_compliance_budget: 0
    });

    const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
    expectSuccess(phaseResp, 201);
    const phase = phaseResp.body.data;

    const procResp = await createProcedure(program.id, trial.id, phase.id, {
      base_risk_cost: 1000
    });
    expectSuccess(procResp, 201);
    const procedure = procResp.body.data;

    const cohortResponse = await createCohort(program.id, trial.id);
    const cohort = cohortResponse.body.data;

    const response = await createExecution(program.id, trial.id, {
      procedure_id: procedure.id,
      cohort_id: cohort.id,
      protocol_deviation: false
    });

    expectSuccess(response, 201);
  });

  test('should reject cancellation of passed execution', async () => {
    const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

    const execResponse = await createExecution(program.id, trial.id, {
      procedure_id: procedure.id,
      cohort_id: cohort.id,
      protocol_deviation: false
    });

    const execution = execResponse.body.data;

    const execResp = await executeExecution(program.id, trial.id, execution.id);
    expectSuccess(execResp, 200);

    const passResp = await markExecutionPassed(program.id, trial.id, execution.id);
    expectSuccess(passResp, 200);

    const cancelResponse = await cancelExecution(program.id, trial.id, execution.id);

    expectError(cancelResponse, 409, 'ERR_EXECUTION_NOT_CANCELLABLE');
  });

  test('should reject rejection of passed execution', async () => {
    const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

    const execResponse = await createExecution(program.id, trial.id, {
      procedure_id: procedure.id,
      cohort_id: cohort.id,
      protocol_deviation: false
    });

    const execution = execResponse.body.data;

    const execResp = await executeExecution(program.id, trial.id, execution.id);
    expectSuccess(execResp, 200);

    const passResp = await markExecutionPassed(program.id, trial.id, execution.id);
    expectSuccess(passResp, 200);

    const rejectResponse = await rejectExecution(program.id, trial.id, execution.id);

    expectError(rejectResponse, 409, 'ERR_EXECUTION_NOT_REJECTABLE');
  });

  test('should not allow completion of cancelled phase', async () => {
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
      phase.version + 1
    );
    expectSuccess(cancelResp, 200);

    const response = await updatePhaseStatus(
      program.id,
      trial.id,
      phase.id,
      PHASE_STATUS.COMPLETED,
      phase.version + 2
    );

    expectError(response, 409, 'ERR_ILLEGAL_PHASE_STATE_TRANSITION');
  });

  test('should floor patient safety risk at zero with large negative adjustment', async () => {
    const { program, trial } = await setupActiveTrial();

    const setRiskResp = await manualRiskAdjustment(program.id, trial.id, 30, 'Set initial risk');
    expectSuccess(setRiskResp, 200);

    const response = await manualRiskAdjustment(
      program.id,
      trial.id,
      -1000,
      'Large negative adjustment test'
    );

    expectSuccess(response, 200);
    expect(response.body.data.patient_safety_risk).toBe(0);
  });

  test('should recalculate portfolio saturation after trial abandonment releases provisional', async () => {
    const { program, portfolio, trials } = await setupPortfolioWithTrials(2);

    const trial1 = trials[0];

    const phaseResp = await createPhase(program.id, trial1.id, PHASE_NAME.PHASE_I);
    expectSuccess(phaseResp, 201);
    const phase = phaseResp.body.data;

    const procResp = await createProcedure(program.id, trial1.id, phase.id, {
      base_risk_cost: 199
    });
    expectSuccess(procResp, 201);
    const procedure = procResp.body.data;

    const cohortResponse = await createCohort(program.id, trial1.id);
    const cohort = cohortResponse.body.data;

    const execResp = await createExecution(program.id, trial1.id, {
      procedure_id: procedure.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });
    expectSuccess(execResp, 201);

    let portfolioResponse = await getPortfolio(program.id, portfolio.id);

    const abandonResp = await abandonTrial(program.id, trial1.id);
    expectSuccess(abandonResp, 200);

    portfolioResponse = await getPortfolio(program.id, portfolio.id);
    expect(portfolioResponse.body.data.is_risk_saturated).toBe(false);
  });

  test('should propagate ripple penalties to dependent trial investigators on high-risk completion', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const irbResp = await createIRB(program.id);
    expectSuccess(irbResp, 201);
    const irb = irbResp.body.data;

    const inv1 = generateInvestigatorId();
    const inv2 = generateInvestigatorId();

    const { trial: depTrial } = await setupActiveTrial({ program, irb }, inv1);
    const { trial: sourceTrial } = await setupActiveTrial({ program, irb }, inv2);

    const depResp = await createDependency(program.id, sourceTrial.id, depTrial.id);
    expectSuccess(depResp, 201);

    const riskResp = await manualRiskAdjustment(program.id, depTrial.id, 80, 'High risk for test');
    expectSuccess(riskResp, 200);

    const beforeCompletion = (await getTrial(program.id, sourceTrial.id)).body.data;
    const effectiveBefore = beforeCompletion.effective_ethical_compliance_budget;

    const completeResp = await completeTrial(program.id, depTrial.id);
    expectSuccess(completeResp, 200);

    const afterCompletion = (await getTrial(program.id, sourceTrial.id)).body.data;

    expect(afterCompletion.effective_ethical_compliance_budget).toBeLessThan(effectiveBefore);

    const expectedEffective = Math.floor(sourceTrial.total_ethical_compliance_budget * 0.95);
    expect(afterCompletion.effective_ethical_compliance_budget).toBe(expectedEffective);
  });

  test('should apply one-hop contagion when trial enters ethical review lock', async () => {
    const { program, portfolio, trials } = await setupPortfolioWithTrials(3);

    const trial1Before = (await getTrial(program.id, trials[1].id)).body.data;
    const trial2Before = (await getTrial(program.id, trials[2].id)).body.data;
    const initialRisk1 = trial1Before.patient_safety_risk;
    const initialRisk2 = trial2Before.patient_safety_risk;

    await forceTrialIntoLock(program.id, trials[0].id);

    const lockedTrial = (await getTrial(program.id, trials[0].id)).body.data;
    expect(lockedTrial.status).toBe('ETHICAL_REVIEW_LOCK');

    const trial1After = (await getTrial(program.id, trials[1].id)).body.data;
    const trial2After = (await getTrial(program.id, trials[2].id)).body.data;

    expect(trial1After.patient_safety_risk).toBe(initialRisk1 + CONTAGION_PENALTY);
    expect(trial2After.patient_safety_risk).toBe(initialRisk2 + CONTAGION_PENALTY);
    expect(trial1After.is_under_contagion).toBe(true);
    expect(trial2After.is_under_contagion).toBe(true);
  });

  test('should block deviations when reputation penalty triggers probation', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const investigatorId = generateInvestigatorId();

    const irbResp = await createIRB(program.id);
    expectSuccess(irbResp, 201);
    const irb = irbResp.body.data;

    await driveInvestigatorIntoProbation(program.id, irb.id, investigatorId, 40);

    const { trial } = await setupActiveTrial({
      program,
      irb,
      total_ethical_compliance_budget: 400
    }, investigatorId);

    const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
    expectSuccess(phaseResp, 201);
    const phase = phaseResp.body.data;

    const procResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 50 });
    expectSuccess(procResp, 201);
    const procedure = procResp.body.data;

    const cohortResponse = await createCohort(program.id, trial.id);
    const cohort = cohortResponse.body.data;

    const dev1 = await createExecution(program.id, trial.id, {
      procedure_id: procedure.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });
    expectSuccess(dev1, 201);

    const oneMoreTrialResp = await createTrial(program.id, {
      irb_id: irb.id,
      total_ethical_compliance_budget: 400
    }, investigatorId);
    expectSuccess(oneMoreTrialResp, 201);
    const oneMoreTrial = oneMoreTrialResp.body.data;

    const oneMoreApprovalResp = await createIRBApproval(program.id, irb.id, oneMoreTrial.id);
    expectSuccess(oneMoreApprovalResp, 201);
    const oneMoreApproval = oneMoreApprovalResp.body.data;

    const approveOneMoreResp = await approveIRB(program.id, irb.id, oneMoreApproval.id, oneMoreApproval.version);
    expectSuccess(approveOneMoreResp, 200);

    const activateOneMoreResp = await activateTrial(program.id, oneMoreTrial.id);
    expectSuccess(activateOneMoreResp, 200);

    const abandonOneMoreResp = await abandonTrial(program.id, oneMoreTrial.id);
    expectSuccess(abandonOneMoreResp, 200);

    const proc2Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 50 });
    expectSuccess(proc2Resp, 201);
    const procedure2 = proc2Resp.body.data;

    const dev2 = await createExecution(program.id, trial.id, {
      procedure_id: procedure2.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });

    expectError(dev2, 403, 'ERR_INVESTIGATOR_ON_PROBATION_DEVIATIONS_BLOCKED');
  });

  test('should handle concurrent deviation proposals on same budget atomically', async () => {
    const { trial, program } = await setupActiveTrial({ total_ethical_compliance_budget: 150 });

    const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
    expectSuccess(phaseResp, 201);
    const phase = phaseResp.body.data;

    const cohortResponse = await createCohort(program.id, trial.id);
    const cohort = cohortResponse.body.data;

    const proc1Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 100 });
    expectSuccess(proc1Resp, 201);
    const proc1 = proc1Resp.body.data;

    const proc2Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 100 });
    expectSuccess(proc2Resp, 201);
    const proc2 = proc2Resp.body.data;

    const [resp1, resp2] = await Promise.all([
      createExecution(program.id, trial.id, {
        procedure_id: proc1.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      }),
      createExecution(program.id, trial.id, {
        procedure_id: proc2.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      })
    ]);

    const responses = [resp1, resp2];
    const successResponses = responses.filter(r => r.status === 201);
    const failureResponses = responses.filter(r => r.status === 402);

    expect(successResponses).toHaveLength(1);
    expect(failureResponses).toHaveLength(1);
    expectError(failureResponses[0], 402, 'ERR_INSUFFICIENT_ETHICAL_BUDGET');
  });

  test('should maintain ledger consistency in abandon vs reject race', async () => {
    const { program, trial, executions } = await setupTrialWithActiveDeviations(2);

    await Promise.all([
      abandonTrial(program.id, trial.id),
      rejectExecution(program.id, trial.id, executions[0].id)
    ]);

    const finalTrial = (await getTrial(program.id, trial.id)).body.data;
    expectNonNegativeBalance(finalTrial.ethical_compliance_balance);
  });

  test('should allow phase completion after clearing REVIEW_REQUIRED', async () => {
    const { program, trial, phase } = await setupTrialWithPhase();

    const cohortResponse = await createCohort(program.id, trial.id);
    const cohort = cohortResponse.body.data;

    const proc1Resp = await createProcedure(program.id, trial.id, phase.id);
    expectSuccess(proc1Resp, 201);
    const proc1 = proc1Resp.body.data;

    const readyResp = await updatePhaseStatus(program.id, trial.id, phase.id, PHASE_STATUS.READY_FOR_PROCEDURES, phase.version);
    expectSuccess(readyResp, 200);

    await triggerPhaseReviewRequired(program.id, trial.id, phase.id, cohort.id);

    const trialAfterCancels = (await getTrial(program.id, trial.id)).body.data;
    expect(trialAfterCancels.deviation_penalty_tier).toBe(3);

    await executeAndPassProcedure(program.id, trial.id, proc1.id, cohort.id);

    const phaseVersion = phase.version + 2;

    const completionBlocked = await updatePhaseStatus(
      program.id,
      trial.id,
      phase.id,
      PHASE_STATUS.COMPLETED,
      phaseVersion
    );
    expectError(completionBlocked, 409, 'ERR_PHASE_IN_REVIEW');

    const clearReview = await updatePhaseStatus(
      program.id,
      trial.id,
      phase.id,
      PHASE_STATUS.READY_FOR_PROCEDURES,
      phaseVersion
    );
    expectSuccess(clearReview, 200);
    expect(clearReview.body.data.status).toBe('READY_FOR_PROCEDURES');

    const phase2Resp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_II);
    expectSuccess(phase2Resp, 201);
    const phase2 = phase2Resp.body.data;

    const proc2Resp = await createProcedure(program.id, trial.id, phase2.id, { base_risk_cost: 10 });
    expectSuccess(proc2Resp, 201);
    const proc2 = proc2Resp.body.data;

    const ready2Resp = await updatePhaseStatus(program.id, trial.id, phase2.id, PHASE_STATUS.READY_FOR_PROCEDURES, phase2.version);
    expectSuccess(ready2Resp, 200);

    await executeAndPassProcedure(program.id, trial.id, proc2.id, cohort.id);

    const completion = await updatePhaseStatus(
      program.id,
      trial.id,
      phase2.id,
      PHASE_STATUS.COMPLETED,
      ready2Resp.body.data.version
    );
    expectSuccess(completion, 200);
    expect(completion.body.data.status).toBe('COMPLETED');
  });

  test('should accept activation with approval from any IRB', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const irb1Resp = await createIRB(program.id);
    expectSuccess(irb1Resp, 201);
    const irb1 = irb1Resp.body.data;

    const irb2Resp = await createIRB(program.id);
    expectSuccess(irb2Resp, 201);
    const irb2 = irb2Resp.body.data;

    const trialResp = await createTrial(program.id, { irb_id: irb1.id });
    expectSuccess(trialResp, 201);
    const trial = trialResp.body.data;

    const approval1Resp = await createIRBApproval(program.id, irb1.id, trial.id);
    expectSuccess(approval1Resp, 201);
    const approval1 = approval1Resp.body.data;

    const approval2Resp = await createIRBApproval(program.id, irb2.id, trial.id);
    expectSuccess(approval2Resp, 201);
    const approval2 = approval2Resp.body.data;

    const approveResp = await approveIRB(program.id, irb1.id, approval1.id, approval1.version);
    expectSuccess(approveResp, 200);

    const response = await activateTrial(program.id, trial.id);
    expectSuccess(response, 200);
  });

  test('should emit correct errors for cross-trial resource references', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const irbResp = await createIRB(program.id);
    expectSuccess(irbResp, 201);
    const irb = irbResp.body.data;

    const { trial: trial1 } = await setupActiveTrial({ program, irb });
    const { trial: trial2 } = await setupActiveTrial({ program, irb });

    const cohort1Response = await createCohort(program.id, trial1.id);
    const cohort1 = cohort1Response.body.data;

    const phase2Resp = await createPhase(program.id, trial2.id, PHASE_NAME.PHASE_I);
    expectSuccess(phase2Resp, 201);
    const phase2 = phase2Resp.body.data;

    const proc2Resp = await createProcedure(program.id, trial2.id, phase2.id);
    expectSuccess(proc2Resp, 201);
    const proc2 = proc2Resp.body.data;

    const response = await createExecution(program.id, trial2.id, {
      procedure_id: proc2.id,
      cohort_id: cohort1.id,
      protocol_deviation: false
    });

    expectError(response, 404, 'ERR_COHORT_NOT_FOUND');
  });

  test('should block completion if any blackout window matches', async () => {
    const { program, trial } = await setupActiveTrial({ treatment_name: 'Oncology Trial' });

    const blackout1 = await createBlackoutWindow(program.id, {
      treatment_name_pattern: 'Cardiology*',
      start_period_index: 0,
      end_period_index: 50
    });
    expectSuccess(blackout1, 201);

    const blackout2 = await createBlackoutWindow(program.id, {
      treatment_name_pattern: 'Onc*',
      start_period_index: 0,
      end_period_index: 100
    });
    expectSuccess(blackout2, 201);

    const response = await completeTrial(program.id, trial.id);
    expectError(response, 403, 'ERR_ENROLLMENT_BLACKOUT_ACTIVE');
  });

  test('should not propagate contagion across program boundaries', async () => {
    const program1Resp = await createResearchProgram();
    expectSuccess(program1Resp, 201);
    const program1 = program1Resp.body.data;

    const program2Resp = await createResearchProgram();
    expectSuccess(program2Resp, 201);
    const program2 = program2Resp.body.data;

    const portfolio1Resp = await createPortfolio(program1.id);
    expectSuccess(portfolio1Resp, 201);
    const portfolio1 = portfolio1Resp.body.data;

    const irb1Resp = await createIRB(program1.id);
    expectSuccess(irb1Resp, 201);
    const irb1 = irb1Resp.body.data;

    const irb2Resp = await createIRB(program2.id);
    expectSuccess(irb2Resp, 201);
    const irb2 = irb2Resp.body.data;

    const { trial: trial1 } = await setupActiveTrial({ program: program1, irb: irb1, portfolio_id: portfolio1.id });
    const { trial: trial2 } = await setupActiveTrial({ program: program2, irb: irb2 });

    await forceTrialIntoLock(program1.id, trial1.id);

    const trial2After = (await getTrial(program2.id, trial2.id)).body.data;
    expect(trial2After.is_under_contagion).toBe(false);
  });

  test('should calculate expedited portions correctly across multiple proposals', async () => {
    const { program, trial, phase, cohort } = await setupTrialNearExpeditedThreshold(10);

    const proc1Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 5 });
    expectSuccess(proc1Resp, 201);
    const proc1 = proc1Resp.body.data;

    const exec1 = await createExecution(program.id, trial.id, {
      procedure_id: proc1.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });

    expect(exec1.body.data.is_expedited_review).toBe(false);

    const proc2Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 10 });
    expectSuccess(proc2Resp, 201);
    const proc2 = proc2Resp.body.data;

    const exec2 = await createExecution(program.id, trial.id, {
      procedure_id: proc2.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });

    expect(exec2.body.data.is_expedited_review).toBe(true);

    const expectedDebit = calculateProvisionalDebit(195, 10, EXPEDITED_THRESHOLD_POINTS, EXPEDITED_MULTIPLIER);
    expect(exec2.body.data.provisional_risk_debit).toBe(expectedDebit);
  });

  test('should enforce probation restrictions at threshold boundary', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const irbResp = await createIRB(program.id);
    expectSuccess(irbResp, 201);
    const irb = irbResp.body.data;

    const investigatorId = generateInvestigatorId();

    await driveInvestigatorIntoProbation(program.id, irb.id, investigatorId, 30);

    const { trial } = await setupActiveTrial({ program, irb, total_ethical_compliance_budget: 400 }, investigatorId);

    const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
    expectSuccess(phaseResp, 201);
    const phase = phaseResp.body.data;

    const procResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 10 });
    expectSuccess(procResp, 201);
    const procedure = procResp.body.data;

    const cohortResp = await createCohort(program.id, trial.id);
    const cohort = cohortResp.body.data;

    const deviationBlocked = await createExecution(program.id, trial.id, {
      procedure_id: procedure.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });
    expectError(deviationBlocked, 403, 'ERR_INVESTIGATOR_ON_PROBATION_DEVIATIONS_BLOCKED');
  });

  test('should count zero-cost deviations toward active deviation limit', async () => {
    const userId = generateUserId();
    const { program, trial } = await setupActiveTrial();

    const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
    expectSuccess(phaseResp, 201);
    const phase = phaseResp.body.data;

    const cohortResponse = await createCohort(program.id, trial.id);
    const cohort = cohortResponse.body.data;

    for (let i = 0; i < 3; i++) {
      const procResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 0 });
      expectSuccess(procResp, 201);
      const proc = procResp.body.data;

      const execResp = await createExecution(program.id, trial.id, {
        procedure_id: proc.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      }, userId);
      expectSuccess(execResp, 201);
    }

    const proc4Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 0 });
    expectSuccess(proc4Resp, 201);
    const proc4 = proc4Resp.body.data;

    const exec4 = await createExecution(program.id, trial.id, {
      procedure_id: proc4.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    }, userId);

    expectError(exec4, 409, 'ERR_MAX_ACTIVE_DEVIATIONS_PER_USER_VIOLATION');
  });

  test('should not apply duplicate contagion penalty to already-locked peers', async () => {
    const { program, portfolio, trials } = await setupPortfolioWithTrials(3);

    await manualRiskAdjustment(program.id, trials[1].id, 91, 'Set near threshold');

    const trial1Before = (await getTrial(program.id, trials[1].id)).body.data;
    expect(trial1Before.patient_safety_risk).toBe(91);

    await forceTrialIntoLock(program.id, trials[0].id);

    const trial1AfterFirstLock = (await getTrial(program.id, trials[1].id)).body.data;
    expect(trial1AfterFirstLock.status).toBe('ETHICAL_REVIEW_LOCK');
    const risk1AfterFirstLock = trial1AfterFirstLock.patient_safety_risk;

    await forceTrialIntoLock(program.id, trials[2].id);

    const trial1Final = (await getTrial(program.id, trials[1].id)).body.data;

    expect(trial1Final.patient_safety_risk).toBe(risk1AfterFirstLock);
  });
});
