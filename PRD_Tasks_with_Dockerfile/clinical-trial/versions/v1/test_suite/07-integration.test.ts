import {
  createExecution,
  executeExecution,
  markExecutionPassed,
  rejectExecution,
  cancelExecution,
  abandonTrial,
  completeTrial,
  activateTrial,
  manualRiskAdjustment,
  clearEthicalReviewLock,
  getTrial,
  getPortfolio,
  updatePortfolio,
  createPhase,
  createProcedure,
  createCohort,
  createDependency,
  updatePhaseStatus,
  createIncompatiblePairing,
  deleteIncompatiblePairing,
  createBlackoutWindow, createResearchProgram,
  createTrial,
  createPortfolio,
  createIRB,
  createIRBApproval,
  approveIRB,
  rejectIRBApproval, initializeReputation
} from '../../../test-helpers/resources';

import {
  expectSuccess,
  expectError,
  expectNonNegativeBalance
} from '../../../test-helpers/assertions';

import {
  PHASE_NAME,
  PHASE_STATUS,
  AUDIT_LOCK_THRESHOLD,
  CONTAGION_PENALTY, DEVIATION_REJECTION_PENALTY
} from '../../../test-helpers/constants';

import {
  setupActiveTrial,
  setupTrialWithPhase,
  setupTrialWithProcedure,
  setupPortfolioWithTrials,
  setupMultipleTrialsForInvestigator, setupPhaseReadyForCompletion,
  setupTrialNearExpeditedThreshold,
  setupTrialWithActiveDeviations,
  forceTrialIntoLock, executeAndPassProcedure,
  driveInvestigatorIntoProbation,
  setupPhaseWithProcedureAndCohort,
  triggerPhaseReviewRequired
} from '../../../test-helpers/scenarios';

import {
  buildPlaceboCohort,
  generateInvestigatorId,
  generateUserId
} from '../../../test-helpers/builders';

describe('Integration Tests - Cross-Feature Interactions', () => {

  test('should reject deviation after reputation drop reduces budget', async () => {
    const { program, investigatorId, trials } = await setupMultipleTrialsForInvestigator(2);

    const trial = trials[1];

    const { phase, procedure, cohort } = await setupPhaseWithProcedureAndCohort(
      program.id,
      trial.id,
      PHASE_NAME.PHASE_I,
      { base_risk_cost: 5000 }
    );

    const exec1 = await createExecution(program.id, trial.id, {
      procedure_id: procedure.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });
    expectSuccess(exec1, 201);

    const trialAfterExec1 = (await getTrial(program.id, trial.id)).body.data;
    const budgetAfterExec1 = trialAfterExec1.ethical_compliance_balance;

    const abandonResp = await abandonTrial(program.id, trials[0].id);
    expectSuccess(abandonResp, 200);

    const trialAfterAbandon = (await getTrial(program.id, trial.id)).body.data;
    expect(trialAfterAbandon.effective_ethical_compliance_budget).toBeLessThan(
      trial.effective_ethical_compliance_budget
    );

    const proc2Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 5000 });
    expectSuccess(proc2Resp, 201);
    const procedure2 = proc2Resp.body.data;

    const exec2 = await createExecution(program.id, trial.id, {
      procedure_id: procedure2.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });

    expectError(exec2, 402, 'ERR_INSUFFICIENT_ETHICAL_BUDGET');
  });

  test('should block deviation when portfolio becomes saturated', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const portfolioResp = await createPortfolio(program.id, { max_total_ethical_budget: 1000 });
    expectSuccess(portfolioResp, 201);
    const portfolio = portfolioResp.body.data;

    const { trial: trial1 } = await setupActiveTrial({
      program,
      portfolio_id: portfolio.id,
      total_ethical_compliance_budget: 1500
    });
    const { trial: trial2 } = await setupActiveTrial({
      program,
      portfolio_id: portfolio.id,
      total_ethical_compliance_budget: 1500
    });

    const { phase: phase1, procedure: proc1, cohort: cohort1 } = await setupPhaseWithProcedureAndCohort(
      program.id,
      trial1.id,
      PHASE_NAME.PHASE_I,
      { base_risk_cost: 450 }
    );

    await createExecution(program.id, trial1.id, {
      procedure_id: proc1.id,
      cohort_id: cohort1.id,
      protocol_deviation: true
    });

    const { phase: phase2, procedure: proc2, cohort: cohort2 } = await setupPhaseWithProcedureAndCohort(
      program.id,
      trial2.id,
      PHASE_NAME.PHASE_I,
      { base_risk_cost: 450 }
    );

    const exec2 = await createExecution(program.id, trial2.id, {
      procedure_id: proc2.id,
      cohort_id: cohort2.id,
      protocol_deviation: true
    });
    expectSuccess(exec2, 201);

    const portfolioCheck = await getPortfolio(program.id, portfolio.id);
    expect(portfolioCheck.body.data.is_risk_saturated).toBe(true);

    const proc3Resp = await createProcedure(program.id, trial2.id, phase2.id, { base_risk_cost: 50 });
    expectSuccess(proc3Resp, 201);
    const proc3 = proc3Resp.body.data;

    const exec3 = await createExecution(program.id, trial2.id, {
      procedure_id: proc3.id,
      cohort_id: cohort2.id,
      protocol_deviation: true
    });

    expectError(exec3, 403, 'ERR_PORTFOLIO_RISK_SATURATED');
  });

  test('should cascade lock, contagion, and saturation updates', async () => {
    const { program, portfolio, trials } = await setupPortfolioWithTrials(2);

    const trial1 = trials[0];
    const trial2 = trials[1];

    const initialTrial2 = (await getTrial(program.id, trial2.id)).body.data;

    await forceTrialIntoLock(program.id, trial1.id);

    const lockedTrial1 = (await getTrial(program.id, trial1.id)).body.data;
    expect(lockedTrial1.status).toBe('ETHICAL_REVIEW_LOCK');

    const contagionTrial2 = (await getTrial(program.id, trial2.id)).body.data;
    expect(contagionTrial2.is_under_contagion).toBe(true);
    expect(contagionTrial2.patient_safety_risk).toBeGreaterThan(initialTrial2.patient_safety_risk);

    const portfolioResp = await getPortfolio(program.id, portfolio.id);
    expect(portfolioResp.body.data.is_risk_saturated).toBe(false);
  });

  test('should trigger phase REVIEW_REQUIRED after cancellations and block completion', async () => {
    const { program, trial, phase } = await setupTrialWithPhase();

    const cohortResponse = await createCohort(program.id, trial.id);
    const cohort = cohortResponse.body.data;

    const proc1Resp = await createProcedure(program.id, trial.id, phase.id);
    expectSuccess(proc1Resp, 201);

    const readyResp = await updatePhaseStatus(
      program.id,
      trial.id,
      phase.id,
      PHASE_STATUS.READY_FOR_PROCEDURES,
      phase.version
    );
    expectSuccess(readyResp, 200);

    await triggerPhaseReviewRequired(program.id, trial.id, phase.id, cohort.id);

    const updatedTrial = (await getTrial(program.id, trial.id)).body.data;
    expect(updatedTrial.deviation_penalty_tier).toBeGreaterThanOrEqual(3);

    const expectedPhaseVersion = readyResp.body.data.version + 1;

    const completeAttempt = await updatePhaseStatus(
      program.id,
      trial.id,
      phase.id,
      PHASE_STATUS.COMPLETED,
      expectedPhaseVersion
    );
    expectError(completeAttempt, 409, 'ERR_PHASE_IN_REVIEW');
  });

  test('should penalize dependent trial investigators on high-risk completion', async () => {
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

    const { phase: depPhase, procedure: depProc, cohort: depCohort } = await setupPhaseWithProcedureAndCohort(
      program.id,
      depTrial.id
    );

    const readyResp = await updatePhaseStatus(program.id, depTrial.id, depPhase.id, PHASE_STATUS.READY_FOR_PROCEDURES, depPhase.version);
    expectSuccess(readyResp, 200);

    await executeAndPassProcedure(program.id, depTrial.id, depProc.id, depCohort.id);

    const completePhaseResp = await updatePhaseStatus(program.id, depTrial.id, depPhase.id, PHASE_STATUS.COMPLETED, depPhase.version + 1);
    expectSuccess(completePhaseResp, 200);

    const riskResp = await manualRiskAdjustment(program.id, depTrial.id, 80, 'High risk for test');
    expectSuccess(riskResp, 200);

    const completeResp = await completeTrial(program.id, depTrial.id);
    expectSuccess(completeResp, 200);

    const updatedSourceTrial = (await getTrial(program.id, sourceTrial.id)).body.data;

    expect(updatedSourceTrial.effective_ethical_compliance_budget).toBeLessThan(
      sourceTrial.effective_ethical_compliance_budget
    );

    const expectedEffective = Math.floor(sourceTrial.total_ethical_compliance_budget * 0.95);
    expect(updatedSourceTrial.effective_ethical_compliance_budget).toBe(expectedEffective);
  });

  test('should reduce portfolio saturation after abandoning trial with large provisional', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const portfolioResp = await createPortfolio(program.id, { max_total_ethical_budget: 1000 });
    expectSuccess(portfolioResp, 201);
    const portfolio = portfolioResp.body.data;

    const { trial } = await setupActiveTrial({
      program,
      portfolio_id: portfolio.id,
      total_ethical_compliance_budget: 2000
    });

    const { phase, procedure, cohort } = await setupPhaseWithProcedureAndCohort(
      program.id,
      trial.id,
      PHASE_NAME.PHASE_I,
      { base_risk_cost: 850 }
    );

    const execResp = await createExecution(program.id, trial.id, {
      procedure_id: procedure.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });
    expectSuccess(execResp, 201);

    let portfolioCheck = await getPortfolio(program.id, portfolio.id);
    const wasSaturated = portfolioCheck.body.data.is_risk_saturated;

    const abandonResp = await abandonTrial(program.id, trial.id);
    expectSuccess(abandonResp, 200);

    portfolioCheck = await getPortfolio(program.id, portfolio.id);
    expect(portfolioCheck.body.data.is_risk_saturated).toBe(false);
  });

  test('should block phase completion but allow deviation proposals during blackout', async () => {
    const { program, trial } = await setupActiveTrial({
      treatment_name: 'Test Treatment'
    });

    const blackoutResp = await createBlackoutWindow(program.id, {
      treatment_name_pattern: '*',
      start_period_index: 0,
      end_period_index: 100
    });
    expectSuccess(blackoutResp, 201);

    const { phase, procedure, cohort } = await setupPhaseWithProcedureAndCohort(program.id, trial.id);

    const execResp = await createExecution(program.id, trial.id, {
      procedure_id: procedure.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });
    expectSuccess(execResp, 201);
    const execution = execResp.body.data;

    const readyResp = await updatePhaseStatus(
      program.id,
      trial.id,
      phase.id,
      PHASE_STATUS.READY_FOR_PROCEDURES,
      phase.version
    );
    expectSuccess(readyResp, 200);

    await executeExecution(program.id, trial.id, execution.id);
    await markExecutionPassed(program.id, trial.id, execution.id);

    const completeResp = await updatePhaseStatus(
      program.id,
      trial.id,
      phase.id,
      PHASE_STATUS.COMPLETED,
      readyResp.body.data.version
    );

    expectError(completeResp, 403, 'ERR_ENROLLMENT_BLACKOUT_ACTIVE');
  });

  test('should calculate expedited portions for same cohort with PASSED inclusion', async () => {
    const { program, trial, phase, cohort } = await setupTrialWithProcedure();

    const proc1Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 120 });
    expectSuccess(proc1Resp, 201);
    const proc1 = proc1Resp.body.data;

    const exec1Response = await createExecution(program.id, trial.id, {
      procedure_id: proc1.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });
    const exec1 = exec1Response.body.data;
    expect(exec1.is_expedited_review).toBe(false);

    await executeExecution(program.id, trial.id, exec1.id);
    await markExecutionPassed(program.id, trial.id, exec1.id);

    const proc2Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 100 });
    expectSuccess(proc2Resp, 201);
    const proc2 = proc2Resp.body.data;

    const exec2Response = await createExecution(program.id, trial.id, {
      procedure_id: proc2.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });
    const exec2 = exec2Response.body.data;

    expect(exec2.is_expedited_review).toBe(true);

    expect(exec2.provisional_risk_debit).toBe(110);
  });

  test('should trigger lock and contagion when rejection pushes risk over threshold', async () => {
    const { program, portfolio, trials } = await setupPortfolioWithTrials(2);
    const trial1 = trials[0];

    const { phase, procedure, cohort } = await setupPhaseWithProcedureAndCohort(
      program.id,
      trial1.id,
      PHASE_NAME.PHASE_I,
      { base_risk_cost: 50 }
    );

    const riskResp = await manualRiskAdjustment(
      program.id,
      trial1.id,
      AUDIT_LOCK_THRESHOLD - DEVIATION_REJECTION_PENALTY + 1,
      'Set to 96 for threshold test'
    );
    expectSuccess(riskResp, 200);

    const execResp = await createExecution(program.id, trial1.id, {
      procedure_id: procedure.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });
    const execution = execResp.body.data;

    const rejectResp = await rejectExecution(program.id, trial1.id, execution.id);
    expectSuccess(rejectResp, 200);

    const trial1After = (await getTrial(program.id, trial1.id)).body.data;
    expect(trial1After.status).toBe('ETHICAL_REVIEW_LOCK');
    expect(trial1After.patient_safety_risk).toBe(101);

    const trial2After = (await getTrial(program.id, trials[1].id)).body.data;
    expect(trial2After.is_under_contagion).toBe(true);
    expect(trial2After.patient_safety_risk).toBeGreaterThanOrEqual(CONTAGION_PENALTY);
  });

  test('should escalate cancellation tier across multiple cancellations', async () => {
    const { program, trial, phase } = await setupTrialWithPhase();

    const cohortResponse = await createCohort(program.id, trial.id);
    const cohort = cohortResponse.body.data;

    const initialTier = (await getTrial(program.id, trial.id)).body.data.deviation_penalty_tier;

    await triggerPhaseReviewRequired(program.id, trial.id, phase.id, cohort.id);

    const updatedTrial = (await getTrial(program.id, trial.id)).body.data;
    expect(updatedTrial.deviation_penalty_tier).toBe(initialTier + 3);
  });

  test('should enforce probation budget cap', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const investigatorId = generateInvestigatorId();

    const irbResp = await createIRB(program.id);
    expectSuccess(irbResp, 201);
    const irb = irbResp.body.data;

    await driveInvestigatorIntoProbation(program.id, irb.id, investigatorId, 30);

    const repCheck = await initializeReputation(program.id, investigatorId);
    expect(repCheck.body.data.reputation_score).toBe(30);
    expect(repCheck.body.data.is_on_probation).toBe(true);

    const highBudgetResp = await createTrial(program.id, {
      treatment_name: 'High Budget Trial',
      total_ethical_compliance_budget: 600,
      irb_id: irb.id
    }, investigatorId);

    expectError(highBudgetResp, 403, 'ERR_INVESTIGATOR_ON_PROBATION_BUDGET_EXCEEDED');
  });

  test('should handle saturation and contagion independently', async () => {
    const { program, portfolio, trials } = await setupPortfolioWithTrials(2);

    await forceTrialIntoLock(program.id, trials[0].id);

    const trial2 = (await getTrial(program.id, trials[1].id)).body.data;
    expect(trial2.is_under_contagion).toBe(true);

    const portfolioResp = await getPortfolio(program.id, portfolio.id);
    const { is_risk_saturated } = portfolioResp.body.data;

    expect(is_risk_saturated).toBe(false);
    expect(trial2.is_under_contagion).toBe(true);
  });

  test('should not affect portfolio saturation with manual risk adjustment alone', async () => {
    const { program, portfolio, trials } = await setupPortfolioWithTrials(2);
    const trial1 = trials[0];

    const increaseResp = await manualRiskAdjustment(program.id, trial1.id, 100, 'Increase risk');
    expectSuccess(increaseResp, 200);

    const portfolioBefore = (await getPortfolio(program.id, portfolio.id)).body.data;

    const decreaseResp = await manualRiskAdjustment(program.id, trial1.id, -50, 'Decrease risk');
    expectSuccess(decreaseResp, 200);

    const portfolioAfter = (await getPortfolio(program.id, portfolio.id)).body.data;

    expect(portfolioAfter.is_risk_saturated).toBe(portfolioBefore.is_risk_saturated);
  });

  test('should allow completion when all deviations are finalized', async () => {
    const { program, trial, phase } = await setupTrialWithPhase();

    const cohortResponse = await createCohort(program.id, trial.id);
    const cohort = cohortResponse.body.data;

    for (let i = 0; i < 3; i++) {
      const procResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 100 });
      expectSuccess(procResp, 201);
      const proc = procResp.body.data;

      const execResp = await createExecution(program.id, trial.id, {
        procedure_id: proc.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });
      const execution = execResp.body.data;

      const execResp2 = await executeExecution(program.id, trial.id, execution.id);
      expectSuccess(execResp2, 200);

      const passResp = await markExecutionPassed(program.id, trial.id, execution.id);
      expectSuccess(passResp, 200);
    }

    const readyResp = await updatePhaseStatus(
      program.id,
      trial.id,
      phase.id,
      PHASE_STATUS.READY_FOR_PROCEDURES,
      phase.version
    );
    expectSuccess(readyResp, 200);

    const completePhaseResp = await updatePhaseStatus(
      program.id,
      trial.id,
      phase.id,
      PHASE_STATUS.COMPLETED,
      phase.version + 1
    );
    expectSuccess(completePhaseResp, 200);

    const completeResp = await completeTrial(program.id, trial.id);
    expectSuccess(completeResp, 200);
  });

  test('should allow activation even when blackout window is active', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const irbResp = await createIRB(program.id);
    expectSuccess(irbResp, 201);
    const irb = irbResp.body.data;

    const trialResp = await createTrial(program.id, { irb_id: irb.id, treatment_name: 'Test Trial' });
    expectSuccess(trialResp, 201);
    const trial = trialResp.body.data;

    const approvalResp = await createIRBApproval(program.id, irb.id, trial.id);
    expectSuccess(approvalResp, 201);
    const approval = approvalResp.body.data;
    const approveResp = await approveIRB(program.id, irb.id, approval.id, approval.version);
    expectSuccess(approveResp, 200);

    const blackoutResp = await createBlackoutWindow(program.id, {
      treatment_name_pattern: '*',
      start_period_index: 0,
      end_period_index: 100
    });
    expectSuccess(blackoutResp, 201);

    const activateResp = await activateTrial(program.id, trial.id);
    expectSuccess(activateResp, 200);
  });

  test('should accept activation with one APPROVED IRB even if others are REJECTED', async () => {
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

    const approve1Resp = await approveIRB(program.id, irb1.id, approval1.id, approval1.version);
    expectSuccess(approve1Resp, 200);

    const reject2Resp = await rejectIRBApproval(program.id, irb2.id, approval2.id, approval2.version);
    expectSuccess(reject2Resp, 200);

    const response = await activateTrial(program.id, trial.id);
    expectSuccess(response, 200);
  });

  test('should allow execution after removing incompatible pairing', async () => {
    const { program, trial, phase } = await setupTrialWithPhase(PHASE_NAME.PHASE_II);

    const pairingResp = await createIncompatiblePairing(
      program.id,
      'CONTAINS_PLACEBO',
      PHASE_NAME.PHASE_II,
      'Test incompatibility'
    );
    expectSuccess(pairingResp, 201);
    const pairing = pairingResp.body.data;

    const cohortResponse = await createCohort(program.id, trial.id, buildPlaceboCohort());
    const cohort = cohortResponse.body.data;

    const procedureResp = await createProcedure(program.id, trial.id, phase.id);
    expectSuccess(procedureResp, 201);
    const procedure = procedureResp.body.data;

    let execResp = await createExecution(program.id, trial.id, {
      procedure_id: procedure.id,
      cohort_id: cohort.id,
      protocol_deviation: false
    });
    expectError(execResp, 409, 'ERR_INCOMPATIBLE_COHORT_PHASE_PAIRING');

    const deleteResp = await deleteIncompatiblePairing(program.id, pairing.id);
    expect(deleteResp.status).toBe(204);

    const procedure2Resp = await createProcedure(program.id, trial.id, phase.id);
    expectSuccess(procedure2Resp, 201);
    const procedure2 = procedure2Resp.body.data;

    execResp = await createExecution(program.id, trial.id, {
      procedure_id: procedure2.id,
      cohort_id: cohort.id,
      protocol_deviation: false
    });

    expectSuccess(execResp, 201);
  });

  test('should block deviations for probation investigator regardless of budget', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const investigatorId = generateInvestigatorId();

    const irbResp = await createIRB(program.id);
    expectSuccess(irbResp, 201);
    const irb = irbResp.body.data;

    await driveInvestigatorIntoProbation(program.id, irb.id, investigatorId, 30);

    const { trial } = await setupActiveTrial({
      program,
      irb,
      total_ethical_compliance_budget: 400
    }, investigatorId);

    const { phase, procedure, cohort } = await setupPhaseWithProcedureAndCohort(
      program.id,
      trial.id,
      PHASE_NAME.PHASE_I,
      { base_risk_cost: 50 }
    );

    const execResp = await createExecution(program.id, trial.id, {
      procedure_id: procedure.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });

    expectError(execResp, 403, 'ERR_INVESTIGATOR_ON_PROBATION_DEVIATIONS_BLOCKED');
  });

  test('should saturate portfolio after cumulative consumption crosses threshold', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const portfolioResp = await createPortfolio(program.id, { max_total_ethical_budget: 1000 });
    expectSuccess(portfolioResp, 201);
    const portfolio = portfolioResp.body.data;

    const { trial } = await setupActiveTrial({
      program,
      portfolio_id: portfolio.id,
      total_ethical_compliance_budget: 5000
    });

    const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
    expectSuccess(phaseResp, 201);
    const phase = phaseResp.body.data;

    const cohortResponse = await createCohort(program.id, trial.id);
    const cohort = cohortResponse.body.data;

    let totalConsumed = 0;

    for (let i = 0; i < 9; i++) {
      const cohortResp = await createCohort(program.id, trial.id);
      const iterCohort = cohortResp.body.data;
      const procResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 100 });
      expectSuccess(procResp, 201);
      const proc = procResp.body.data;

      await createExecution(program.id, trial.id, {
        procedure_id: proc.id,
        cohort_id: iterCohort.id,
        protocol_deviation: true
      });

      totalConsumed += 100;

      let portfolioCheck = await getPortfolio(program.id, portfolio.id);
      const expectedSaturated = (100 * totalConsumed / 1000) >= 90;
      expect(portfolioCheck.body.data.is_risk_saturated).toBe(expectedSaturated);
    }

    let portfolioCheck = await getPortfolio(program.id, portfolio.id);
    expect(portfolioCheck.body.data.is_risk_saturated).toBe(true);

    const finalCohortResp = await createCohort(program.id, trial.id);
    const finalCohort = finalCohortResp.body.data;
    const finalProcResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 1 });
    expectSuccess(finalProcResp, 201);
    const finalProc = finalProcResp.body.data;

    await createExecution(program.id, trial.id, {
      procedure_id: finalProc.id,
      cohort_id: finalCohort.id,
      protocol_deviation: true
    });

    portfolioCheck = await getPortfolio(program.id, portfolio.id);
    expect(portfolioCheck.body.data.is_risk_saturated).toBe(true);
  });

  test('should maintain contagion flag when portfolio has remaining locks', async () => {
    const { program, portfolio, trials } = await setupPortfolioWithTrials(3);

    await forceTrialIntoLock(program.id, trials[0].id);
    await forceTrialIntoLock(program.id, trials[1].id);

    let trial2 = (await getTrial(program.id, trials[2].id)).body.data;
    expect(trial2.is_under_contagion).toBe(true);

    const clearResp = await clearEthicalReviewLock(program.id, trials[0].id);
    expectSuccess(clearResp, 200);

    trial2 = (await getTrial(program.id, trials[2].id)).body.data;
    expect(trial2.is_under_contagion).toBe(true);
  });

  test('should maintain contagion flag after abandonment without clearing lock', async () => {
    const { program, portfolio, trials } = await setupPortfolioWithTrials(2);

    await forceTrialIntoLock(program.id, trials[0].id);

    const trial1After = (await getTrial(program.id, trials[1].id)).body.data;
    expect(trial1After.is_under_contagion).toBe(true);

    const abandonResp = await abandonTrial(program.id, trials[1].id);
    expectSuccess(abandonResp, 200);

    const trial1Abandoned = (await getTrial(program.id, trials[1].id)).body.data;
    expect(trial1Abandoned.is_under_contagion).toBe(true);
  });

  test('should block phase completion when in REVIEW_REQUIRED state', async () => {
    const { program, trial, phase, cohort } = await setupPhaseReadyForCompletion(2);

    await triggerPhaseReviewRequired(program.id, trial.id, phase.id, cohort.id);

    const expectedVersion = phase.version + 2;

    const completePhaseResp = await updatePhaseStatus(
      program.id,
      trial.id,
      phase.id,
      PHASE_STATUS.COMPLETED,
      expectedVersion
    );
    expectError(completePhaseResp, 409, 'ERR_PHASE_IN_REVIEW');
  });

  test('should validate all completion prerequisites together', async () => {
    const { program, trial } = await setupActiveTrial({
      treatment_name: 'Test Trial'
    });

    const blackoutResp = await createBlackoutWindow(program.id, {
      treatment_name_pattern: '*',
      start_period_index: 0,
      end_period_index: 100
    });
    expectSuccess(blackoutResp, 201);

    const response = await completeTrial(program.id, trial.id);

    expectError(response, 403, 'ERR_ENROLLMENT_BLACKOUT_ACTIVE');
  });

  test('should count zero-cost deviations toward active limit', async () => {
    const userId = generateUserId();
    const { program, trial } = await setupActiveTrial();

    const { phase, cohort } = await setupPhaseWithProcedureAndCohort(program.id, trial.id);

    for (let i = 0; i < 3; i++) {
      const procResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 0 });
      expectSuccess(procResp, 201);
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

    const proc4Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 0 });
    expectSuccess(proc4Resp, 201);
    const proc4 = proc4Resp.body.data;

    const exec4 = await createExecution(
      program.id,
      trial.id,
      {
        procedure_id: proc4.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      },
      userId
    );

    expectError(exec4, 409, 'ERR_MAX_ACTIVE_DEVIATIONS_PER_USER_VIOLATION');
  });

  test('should calculate non-overlapping expedited portions for sequential proposals', async () => {
    const { program, trial, phase, cohort } = await setupTrialNearExpeditedThreshold(10);

    const proc1Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 20 });
    expectSuccess(proc1Resp, 201);
    const proc1 = proc1Resp.body.data;

    const exec1 = await createExecution(program.id, trial.id, {
      procedure_id: proc1.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });

    const debit1 = exec1.body.data.provisional_risk_debit;

    const proc2Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 30 });
    expectSuccess(proc2Resp, 201);
    const proc2 = proc2Resp.body.data;

    const exec2 = await createExecution(program.id, trial.id, {
      procedure_id: proc2.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });

    const debit2 = exec2.body.data.provisional_risk_debit;

    expect(debit1).toBe(25);
    expect(debit2).toBe(45);
  });

  test('should not affect portfolio saturation with reputation change alone', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const investigatorId = generateInvestigatorId();

    const portfolioResp = await createPortfolio(program.id, { max_total_ethical_budget: 1000 });
    expectSuccess(portfolioResp, 201);
    const portfolio = portfolioResp.body.data;

    const irbResp = await createIRB(program.id);
    expectSuccess(irbResp, 201);
    const irb = irbResp.body.data;

    const trial1Resp = await createTrial(program.id, {
      irb_id: irb.id,
      portfolio_id: portfolio.id,
      total_ethical_compliance_budget: 500
    }, investigatorId);
    expectSuccess(trial1Resp, 201);
    const trial1 = trial1Resp.body.data;

    const approval1Resp = await createIRBApproval(program.id, irb.id, trial1.id);
    expectSuccess(approval1Resp, 201);
    const approval1 = approval1Resp.body.data;

    const approve1Resp = await approveIRB(program.id, irb.id, approval1.id, approval1.version);
    expectSuccess(approve1Resp, 200);

    const activate1Resp = await activateTrial(program.id, trial1.id);
    expectSuccess(activate1Resp, 200);

    const { phase, procedure, cohort } = await setupPhaseWithProcedureAndCohort(
      program.id,
      trial1.id,
      PHASE_NAME.PHASE_I,
      { base_risk_cost: 400 }
    );

    const execResp = await createExecution(program.id, trial1.id, {
      procedure_id: procedure.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });
    expectSuccess(execResp, 201);

    const portfolioBefore = (await getPortfolio(program.id, portfolio.id)).body.data;
    const saturationBefore = portfolioBefore.is_risk_saturated;

    const trial2Resp = await createTrial(program.id, {
      irb_id: irb.id,
      total_ethical_compliance_budget: 500
    }, investigatorId);
    expectSuccess(trial2Resp, 201);
    const trial2 = trial2Resp.body.data;

    const approval2Resp = await createIRBApproval(program.id, irb.id, trial2.id);
    expectSuccess(approval2Resp, 201);
    const approval2 = approval2Resp.body.data;

    const approve2Resp = await approveIRB(program.id, irb.id, approval2.id, approval2.version);
    expectSuccess(approve2Resp, 200);

    const activate2Resp = await activateTrial(program.id, trial2.id);
    expectSuccess(activate2Resp, 200);

    const abandon2Resp = await abandonTrial(program.id, trial2.id);
    expectSuccess(abandon2Resp, 200);

    const portfolioAfter = (await getPortfolio(program.id, portfolio.id)).body.data;

    expect(portfolioAfter.is_risk_saturated).toBe(saturationBefore);
  });

  test('should not double-reverse provisional on cancel followed by abandon', async () => {
    const { program, trial, executions } = await setupTrialWithActiveDeviations(2);

    const trialBefore = (await getTrial(program.id, trial.id)).body.data;
    const provisionalBefore = trialBefore.effective_ethical_compliance_budget - trialBefore.ethical_compliance_balance;

    const cancelResp = await cancelExecution(program.id, trial.id, executions[0].id);
    expectSuccess(cancelResp, 200);

    const afterCancel = (await getTrial(program.id, trial.id)).body.data;

    const abandonResp = await abandonTrial(program.id, trial.id);
    expectSuccess(abandonResp, 200);

    const afterAbandon = (await getTrial(program.id, trial.id)).body.data;

    const expectedEffective = Math.floor(trialBefore.total_ethical_compliance_budget * 0.9);
    expect(afterAbandon.effective_ethical_compliance_budget).toBe(expectedEffective);

    expect(afterAbandon.ethical_compliance_balance).toBe(expectedEffective);
    expectNonNegativeBalance(afterAbandon.ethical_compliance_balance);
  });

  test('should apply contagion risk independently of saturation state', async () => {
    const { program, portfolio, trials } = await setupPortfolioWithTrials(2);

    await forceTrialIntoLock(program.id, trials[0].id);

    const trial1 = (await getTrial(program.id, trials[1].id)).body.data;
    expect(trial1.is_under_contagion).toBe(true);
    expect(trial1.patient_safety_risk).toBeGreaterThan(0);

    const portfolioResp = await getPortfolio(program.id, portfolio.id);
    expect(portfolioResp.body.data.is_risk_saturated).toBe(false);
  });

  test('should allow completion after manual risk reduction', async () => {
    const { program, trial } = await setupActiveTrial();

    await forceTrialIntoLock(program.id, trial.id);

    const clearResp = await clearEthicalReviewLock(program.id, trial.id);
    expectSuccess(clearResp, 200);

    const reduceResp = await manualRiskAdjustment(program.id, trial.id, -(AUDIT_LOCK_THRESHOLD + 10), 'Reduce risk');
    expectSuccess(reduceResp, 200);

    const response = await completeTrial(program.id, trial.id);
    expectSuccess(response, 200);
  });

  test('should enforce all gates on deviation proposal immediately after activation', async () => {
    const { program, trial } = await setupActiveTrial();

    const { phase, procedure, cohort } = await setupPhaseWithProcedureAndCohort(program.id, trial.id);

    const execResp = await createExecution(program.id, trial.id, {
      procedure_id: procedure.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });

    expectSuccess(execResp, 201);
  });

  test('should transition procedure state when execution is proposed', async () => {
    const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

    expect(procedure.status).toBe('PENDING');

    const execResp = await createExecution(program.id, trial.id, {
      procedure_id: procedure.id,
      cohort_id: cohort.id,
      protocol_deviation: false
    });

    expectSuccess(execResp, 201);

    const proc2Attempt = await createExecution(program.id, trial.id, {
      procedure_id: procedure.id,
      cohort_id: cohort.id,
      protocol_deviation: false
    });

    expectError(proc2Attempt, 409, 'ERR_PROCEDURE_NOT_PENDING');
  });

  test('should preserve finalized debits after trial completion', async () => {
    const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure({ base_risk_cost: 100 });

    const readyResp = await updatePhaseStatus(program.id, trial.id, phase.id, PHASE_STATUS.READY_FOR_PROCEDURES, phase.version);
    expectSuccess(readyResp, 200);

    const execResponse = await createExecution(program.id, trial.id, {
      procedure_id: procedure.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });

    const exec = execResponse.body.data;

    const execResp = await executeExecution(program.id, trial.id, exec.id);
    expectSuccess(execResp, 200);

    const passResp = await markExecutionPassed(program.id, trial.id, exec.id);
    expectSuccess(passResp, 200);

    const beforeCompletion = (await getTrial(program.id, trial.id)).body.data;
    const balanceBeforeCompletion = beforeCompletion.ethical_compliance_balance;

    const completePhaseResp = await updatePhaseStatus(
      program.id,
      trial.id,
      phase.id,
      PHASE_STATUS.COMPLETED,
      readyResp.body.data.version
    );
    expectSuccess(completePhaseResp, 200);

    const completeResp = await completeTrial(program.id, trial.id);
    expectSuccess(completeResp, 200);

    const afterCompletion = (await getTrial(program.id, trial.id)).body.data;

    expect(afterCompletion.ethical_compliance_balance).toBe(balanceBeforeCompletion);
  });

  test('should recalculate saturation after portfolio cap update', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const portfolioResp = await createPortfolio(program.id, { max_total_ethical_budget: 100 });
    expectSuccess(portfolioResp, 201);
    const portfolio = portfolioResp.body.data;

    const updateResp = await updatePortfolio(program.id, portfolio.id, {
      max_total_ethical_budget: 10000,
      version: portfolio.version
    });
    expectSuccess(updateResp, 200);

    const updated = await getPortfolio(program.id, portfolio.id);
    expect(updated.body.data.max_total_ethical_budget).toBe(10000);
  });

  test('should not use cohort property certification period in validation', async () => {
    const { program, trial, phase } = await setupTrialWithPhase();

    const cohortResponse = await createCohort(program.id, trial.id, {
      cohort_name: 'Test Cohort',
      cohort_version: '1.0',
      base_risk_points: 10,
      properties: [{
        property_id: 'prop-1',
        name: 'HEALTHY_VOLUNTEERS',
        certified_period_index: 9999
      }]
    });
    const cohort = cohortResponse.body.data;

    const procedureResp = await createProcedure(program.id, trial.id, phase.id, {
      required_cohort_tag: 'HEALTHY_VOLUNTEERS'
    });
    expectSuccess(procedureResp, 201);
    const procedure = procedureResp.body.data;

    const response = await createExecution(program.id, trial.id, {
      procedure_id: procedure.id,
      cohort_id: cohort.id,
      protocol_deviation: false
    });

    expectSuccess(response, 201);
  });

  test('should enforce budget atomically across users', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const irbResp = await createIRB(program.id);
    expectSuccess(irbResp, 201);
    const irb = irbResp.body.data;

    const { trial } = await setupActiveTrial({
      program,
      irb,
      total_ethical_compliance_budget: 200
    });

    const { phase, cohort } = await setupPhaseWithProcedureAndCohort(program.id, trial.id);

    const proc1Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 150 });
    expectSuccess(proc1Resp, 201);
    const proc1 = proc1Resp.body.data;

    const proc2Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 150 });
    expectSuccess(proc2Resp, 201);
    const proc2 = proc2Resp.body.data;

    const [exec1, exec2] = await Promise.all([
      createExecution(
        program.id,
        trial.id,
        {
          procedure_id: proc1.id,
          cohort_id: cohort.id,
          protocol_deviation: true
        },
        'user-1'
      ),
      createExecution(
        program.id,
        trial.id,
        {
          procedure_id: proc2.id,
          cohort_id: cohort.id,
          protocol_deviation: true
        },
        'user-2'
      )
    ]);

    const responses = [exec1, exec2];
    const success = responses.filter(r => r.status === 201);
    const failures = responses.filter(r => r.status !== 201);
    expect(success.length).toBe(1);
    expect(failures.length).toBe(1);

    expectError(failures[0], 402, 'ERR_INSUFFICIENT_ETHICAL_BUDGET');
  });

  test('should fail second proposal when reputation penalty occurs between proposals', async () => {
    const { program, investigatorId, trials } = await setupMultipleTrialsForInvestigator(2);

    const trial1 = trials[0];
    const trial2 = trials[1];

    const { phase, cohort } = await setupPhaseWithProcedureAndCohort(program.id, trial2.id);

    const proc1Resp = await createProcedure(program.id, trial2.id, phase.id, { base_risk_cost: 5000 });
    expectSuccess(proc1Resp, 201);
    const proc1 = proc1Resp.body.data;

    const exec1 = await createExecution(program.id, trial2.id, {
      procedure_id: proc1.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });
    expectSuccess(exec1, 201);

    const abandonResp = await abandonTrial(program.id, trial1.id);
    expectSuccess(abandonResp, 200);

    const trial2AfterPenalty = (await getTrial(program.id, trial2.id)).body.data;
    expect(trial2AfterPenalty.effective_ethical_compliance_budget).toBeLessThan(
      trial2.effective_ethical_compliance_budget
    );

    const proc2Resp = await createProcedure(program.id, trial2.id, phase.id, { base_risk_cost: 5000 });
    expectSuccess(proc2Resp, 201);
    const proc2 = proc2Resp.body.data;

    const exec2 = await createExecution(program.id, trial2.id, {
      procedure_id: proc2.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });

    expectError(exec2, 402, 'ERR_INSUFFICIENT_ETHICAL_BUDGET');
  });

  test('should block if any blackout window matches current period', async () => {
    const { program, trial } = await setupActiveTrial({
      treatment_name: 'Test Trial'
    });

    const blackout1Resp = await createBlackoutWindow(program.id, {
      treatment_name_pattern: 'Other*',
      start_period_index: 0,
      end_period_index: 50
    });
    expectSuccess(blackout1Resp, 201);

    const blackout2Resp = await createBlackoutWindow(program.id, {
      treatment_name_pattern: 'Test*',
      start_period_index: 0,
      end_period_index: 100
    });
    expectSuccess(blackout2Resp, 201);

    const response = await completeTrial(program.id, trial.id);
    expectError(response, 403, 'ERR_ENROLLMENT_BLACKOUT_ACTIVE');
  });

  test('should isolate phase REVIEW_REQUIRED without blocking other phases', async () => {
    const { program, trial } = await setupActiveTrial();

    const phaseAResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
    expectSuccess(phaseAResp, 201);
    const phaseA = phaseAResp.body.data;

    const phaseBResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_II);
    expectSuccess(phaseBResp, 201);
    const phaseB = phaseBResp.body.data;

    const cohortResponse = await createCohort(program.id, trial.id);
    const cohort = cohortResponse.body.data;

    const procA1Resp = await createProcedure(program.id, trial.id, phaseA.id);
    expectSuccess(procA1Resp, 201);

    const readyResp = await updatePhaseStatus(program.id, trial.id, phaseA.id, PHASE_STATUS.READY_FOR_PROCEDURES, phaseA.version);
    expectSuccess(readyResp, 200);

    await triggerPhaseReviewRequired(program.id, trial.id, phaseA.id, cohort.id);

    const trialAfter = (await getTrial(program.id, trial.id)).body.data;
    expect(trialAfter.deviation_penalty_tier).toBe(3);
    expect(trialAfter.patient_safety_risk).toBe(70);
    expect(trialAfter.status).toBe('ACTIVE');

    const expectedPhaseAVersion = readyResp.body.data.version + 1;

    const completePhaseA = await updatePhaseStatus(
      program.id,
      trial.id,
      phaseA.id,
      PHASE_STATUS.COMPLETED,
      expectedPhaseAVersion
    );
    expectError(completePhaseA, 409, 'ERR_PHASE_IN_REVIEW');

    const procB1Resp = await createProcedure(program.id, trial.id, phaseB.id);
    expectSuccess(procB1Resp, 201);
    const procB1 = procB1Resp.body.data;

    const execBResponse = await createExecution(program.id, trial.id, {
      procedure_id: procB1.id,
      cohort_id: cohort.id,
      protocol_deviation: false
    });

    expectSuccess(execBResponse, 201);
  });

  test('should apply reputation penalty when peer locks via contagion', async () => {
    const { program, portfolio, trials } = await setupPortfolioWithTrials(2);

    const trial1 = trials[0];
    const trial2 = trials[1];

    await manualRiskAdjustment(program.id, trial2.id, 91, 'Set near threshold for contagion test');

    const trial2Before = (await getTrial(program.id, trial2.id)).body.data;
    expect(trial2Before.patient_safety_risk).toBe(91);
    expect(trial2Before.status).toBe('ACTIVE');

    const initialEffectiveBudget = trial2Before.effective_ethical_compliance_budget;

    await forceTrialIntoLock(program.id, trial1.id);

    const trial2After = (await getTrial(program.id, trial2.id)).body.data;
    expect(trial2After.status).toBe('ETHICAL_REVIEW_LOCK');

    expect(trial2After.effective_ethical_compliance_budget).toBeLessThan(initialEffectiveBudget);
  });

  test('should allow deviations immediately after leaving probation', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const investigatorId = generateInvestigatorId();

    const irbResp = await createIRB(program.id);
    expectSuccess(irbResp, 201);
    const irb = irbResp.body.data;

    await driveInvestigatorIntoProbation(program.id, irb.id, investigatorId, 40);

    const trial40Resp = await createTrial(program.id, { irb_id: irb.id }, investigatorId);
    expectSuccess(trial40Resp, 201);
    const trial40 = trial40Resp.body.data;

    const approval40Resp = await createIRBApproval(program.id, irb.id, trial40.id);
    expectSuccess(approval40Resp, 201);
    const approval40 = approval40Resp.body.data;

    const approve40Resp = await approveIRB(program.id, irb.id, approval40.id, approval40.version);
    expectSuccess(approve40Resp, 200);

    const activate40Resp = await activateTrial(program.id, trial40.id);
    expectSuccess(activate40Resp, 200);

    const phase40Resp = await createPhase(program.id, trial40.id, PHASE_NAME.PHASE_I);
    const phase40 = phase40Resp.body.data;

    const proc40Resp = await createProcedure(program.id, trial40.id, phase40.id, { base_risk_cost: 10 });
    const proc40 = proc40Resp.body.data;

    const cohort40Resp = await createCohort(program.id, trial40.id);
    const cohort40 = cohort40Resp.body.data;

    const deviationAllowed = await createExecution(program.id, trial40.id, {
      procedure_id: proc40.id,
      cohort_id: cohort40.id,
      protocol_deviation: true
    });
    expectSuccess(deviationAllowed, 201);

    const trialDropResp = await createTrial(program.id, { irb_id: irb.id }, investigatorId);
    expectSuccess(trialDropResp, 201);
    const trialDrop = trialDropResp.body.data;

    const abandonDropResp = await abandonTrial(program.id, trialDrop.id);
    expectSuccess(abandonDropResp, 200);

      const trial30Resp = await createTrial(program.id, {
        irb_id: irb.id,
        total_ethical_compliance_budget: 500
      }, investigatorId);
      expectSuccess(trial30Resp, 201);
    const trial30 = trial30Resp.body.data;

    const approval30Resp = await createIRBApproval(program.id, irb.id, trial30.id);
    expectSuccess(approval30Resp, 201);
    const approval30 = approval30Resp.body.data;

    const approve30Resp = await approveIRB(program.id, irb.id, approval30.id, approval30.version);
    expectSuccess(approve30Resp, 200);

    const activate30Resp = await activateTrial(program.id, trial30.id);
    expectSuccess(activate30Resp, 200);

    const phase30Resp = await createPhase(program.id, trial30.id, PHASE_NAME.PHASE_I);
    const phase30 = phase30Resp.body.data;

    const proc30Resp = await createProcedure(program.id, trial30.id, phase30.id, { base_risk_cost: 10 });
    const proc30 = proc30Resp.body.data;

    const cohort30Resp = await createCohort(program.id, trial30.id);
    const cohort30 = cohort30Resp.body.data;

    const deviationBlocked = await createExecution(program.id, trial30.id, {
      procedure_id: proc30.id,
      cohort_id: cohort30.id,
      protocol_deviation: true
    });
    expectError(deviationBlocked, 403, 'ERR_INVESTIGATOR_ON_PROBATION_DEVIATIONS_BLOCKED');
  });

  test('should allow non-deviation proposals even when portfolio saturated', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const portfolioResp = await createPortfolio(program.id, { max_total_ethical_budget: 100 });
    expectSuccess(portfolioResp, 201);
    const portfolio = portfolioResp.body.data;

    const { trial } = await setupActiveTrial({
      program,
      portfolio_id: portfolio.id,
      total_ethical_compliance_budget: 200
    });

    const { phase, cohort } = await setupPhaseWithProcedureAndCohort(program.id, trial.id);

    const proc1Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 90 });
    expectSuccess(proc1Resp, 201);
    const proc1 = proc1Resp.body.data;

    const exec1Resp = await createExecution(program.id, trial.id, {
      procedure_id: proc1.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });
    expectSuccess(exec1Resp, 201);

    const proc2Resp = await createProcedure(program.id, trial.id, phase.id);
    expectSuccess(proc2Resp, 201);
    const proc2 = proc2Resp.body.data;

    const execResp = await createExecution(program.id, trial.id, {
      procedure_id: proc2.id,
      cohort_id: cohort.id,
      protocol_deviation: false
    });

    expectSuccess(execResp, 201);
  });

  test('should calculate portfolio saturation across all trial statuses', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const portfolioResp = await createPortfolio(program.id, { max_total_ethical_budget: 1000 });
    expectSuccess(portfolioResp, 201);
    const portfolio = portfolioResp.body.data;

    const { trial: trial1 } = await setupActiveTrial({ program, portfolio_id: portfolio.id, total_ethical_compliance_budget: 500 });

    const { phase: phase1, procedure: proc1, cohort: cohort1 } = await setupPhaseWithProcedureAndCohort(
      program.id,
      trial1.id,
      PHASE_NAME.PHASE_I,
      { base_risk_cost: 199 }
    );

    await createExecution(program.id, trial1.id, {
      procedure_id: proc1.id,
      cohort_id: cohort1.id,
      protocol_deviation: true
    });

    const { trial: trial2 } = await setupActiveTrial({ program, portfolio_id: portfolio.id, total_ethical_compliance_budget: 500 });

    const { phase: phase2, procedure: proc2, cohort: cohort2 } = await setupPhaseWithProcedureAndCohort(
      program.id,
      trial2.id,
      PHASE_NAME.PHASE_I,
      { base_risk_cost: 199 }
    );

    await createExecution(program.id, trial2.id, {
      procedure_id: proc2.id,
      cohort_id: cohort2.id,
      protocol_deviation: true
    });

    const abandonResp = await abandonTrial(program.id, trial2.id);
    expectSuccess(abandonResp, 200);

    const portfolioCheck = await getPortfolio(program.id, portfolio.id);
    expect(portfolioCheck.body.data.is_risk_saturated).toBe(false);
  });

  test('should apply ripple penalty to investigator even without active trials', async () => {
    const programResp = await createResearchProgram();
    expectSuccess(programResp, 201);
    const program = programResp.body.data;

    const irbResp = await createIRB(program.id);
    expectSuccess(irbResp, 201);
    const irb = irbResp.body.data;

    const inv1 = generateInvestigatorId();
    const inv2 = generateInvestigatorId();

    const depTrialResp = await createTrial(program.id, { irb_id: irb.id }, inv1);
    expectSuccess(depTrialResp, 201);
    const depTrial = depTrialResp.body.data;

    const depApprovalResp = await createIRBApproval(program.id, irb.id, depTrial.id);
    expectSuccess(depApprovalResp, 201);
    const depApproval = depApprovalResp.body.data;

    const approveDepResp = await approveIRB(program.id, irb.id, depApproval.id, depApproval.version);
    expectSuccess(approveDepResp, 200);

    const activateDepResp = await activateTrial(program.id, depTrial.id);
    expectSuccess(activateDepResp, 200);

    const depPhaseResp = await createPhase(program.id, depTrial.id, PHASE_NAME.PHASE_I);
    expectSuccess(depPhaseResp, 201);
    const depPhase = depPhaseResp.body.data;

    const depProcResp = await createProcedure(program.id, depTrial.id, depPhase.id, { base_risk_cost: 10 });
    expectSuccess(depProcResp, 201);
    const depProc = depProcResp.body.data;

    const depCohortResp = await createCohort(program.id, depTrial.id);
    const depCohort = depCohortResp.body.data;

    const readyDepPhaseResp = await updatePhaseStatus(program.id, depTrial.id, depPhase.id, PHASE_STATUS.READY_FOR_PROCEDURES, depPhase.version);
    expectSuccess(readyDepPhaseResp, 200);

    await executeAndPassProcedure(program.id, depTrial.id, depProc.id, depCohort.id);

    const completeDepPhaseResp = await updatePhaseStatus(
      program.id,
      depTrial.id,
      depPhase.id,
      PHASE_STATUS.COMPLETED,
      readyDepPhaseResp.body.data.version
    );
    expectSuccess(completeDepPhaseResp, 200);

    const sourceTrialResp = await createTrial(program.id, { irb_id: irb.id }, inv2);
    expectSuccess(sourceTrialResp, 201);
    const sourceTrial = sourceTrialResp.body.data;

    const depResp = await createDependency(program.id, sourceTrial.id, depTrial.id);
    expectSuccess(depResp, 201);

    const riskResp = await manualRiskAdjustment(program.id, depTrial.id, 76, 'High risk adjustment');
    expectSuccess(riskResp, 200);

    const completeResp = await completeTrial(program.id, depTrial.id);
    expectSuccess(completeResp, 200);

    const sourceApprovalResp = await createIRBApproval(program.id, irb.id, sourceTrial.id);
    expectSuccess(sourceApprovalResp, 201);
    const sourceApproval = sourceApprovalResp.body.data;

    const approveSourceResp = await approveIRB(program.id, irb.id, sourceApproval.id, sourceApproval.version);
    expectSuccess(approveSourceResp, 200);

    const activateSourceResp = await activateTrial(program.id, sourceTrial.id);
    expectSuccess(activateSourceResp, 200);

    const activeSourceTrial = (await getTrial(program.id, sourceTrial.id)).body.data;
    const expectedEffective = Math.floor(sourceTrial.total_ethical_compliance_budget * 0.95);
    expect(activeSourceTrial.effective_ethical_compliance_budget).toBe(expectedEffective);
  });

  test('should update execution and procedure states atomically on PASS', async () => {
    const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

    const execResp = await createExecution(program.id, trial.id, {
      procedure_id: procedure.id,
      cohort_id: cohort.id,
      protocol_deviation: false
    });

    const execution = execResp.body.data;

    const execExecResp = await executeExecution(program.id, trial.id, execution.id);
    expectSuccess(execExecResp, 200);

    const passResp = await markExecutionPassed(program.id, trial.id, execution.id);

    expectSuccess(passResp, 200);
    expect(passResp.body.data.status).toBe('PASSED');
  });

  test('should preserve finalized debits after abandonment', async () => {
    const { program, trial, phase } = await setupTrialWithPhase();

    const cohortResponse = await createCohort(program.id, trial.id);
    const cohort = cohortResponse.body.data;

    const procResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 200 });
    expectSuccess(procResp, 201);
    const proc = procResp.body.data;

    const execResp = await createExecution(program.id, trial.id, {
      procedure_id: proc.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    });

    const exec = execResp.body.data;

    const execExecResp = await executeExecution(program.id, trial.id, exec.id);
    expectSuccess(execExecResp, 200);

    const passResp = await markExecutionPassed(program.id, trial.id, exec.id);
    expectSuccess(passResp, 200);

    const beforeAbandon = (await getTrial(program.id, trial.id)).body.data;
    const balanceBefore = beforeAbandon.ethical_compliance_balance;

    const abandonResp = await abandonTrial(program.id, trial.id);
    expectSuccess(abandonResp, 200);

    const afterAbandon = (await getTrial(program.id, trial.id)).body.data;

    expectNonNegativeBalance(afterAbandon.ethical_compliance_balance);
  });

  test('should allow EthicsAuditor to adjust risk regardless of investigator probation', async () => {
    const { program, trial } = await setupActiveTrial();

    const response = await manualRiskAdjustment(
      program.id,
      trial.id,
      10,
      'Risk adjustment by ethics auditor',
      'auditor-user',
      'EthicsAuditor'
    );

    expectSuccess(response, 200);
  });
});
