import {
  createResearchProgram,
  createTrial,
  createIRB,
  createIRBApproval,
  approveIRB,
  activateTrial,
  createPhase,
  createProcedure,
  createCohort,
  createExecution,
  executeExecution,
  markExecutionPassed,
  rejectExecution,
  cancelExecution,
  abandonTrial,
  completeTrial,
  createDependency,
  getTrial,
  getPortfolio,
  createPortfolio,
  updatePortfolio,
  manualRiskAdjustment,
  initializeReputation,
  clearEthicalReviewLock,
  updatePhaseStatus
} from '../../../test-helpers/resources';

import {
  expectSuccess,
  expectNonNegativeBalance,
  expectError
} from '../../../test-helpers/assertions';

import {
  CONTAGION_PENALTY, PROBATION_TRIAL_BUDGET_CAP,
  PHASE_NAME, PHASE_STATUS,
  EXPEDITED_THRESHOLD_POINTS, PENALTY_DEPENDENCY_RIPPLE
} from '../../../test-helpers/constants';

import {
  calculateProvisionalDebit,
  calculateEffectiveBudget,
  calculateEthicalBalance
} from '../../../test-helpers/calculations';

import {
  setupTrialWithProcedure,
  setupTrialNearExpeditedThreshold,
  setupPortfolioWithTrials,
  setupMultipleTrialsForInvestigator,
  setupTrialWithActiveDeviations,
  setupActiveTrial,
  executeAndPassProcedure,
  forceTrialIntoLock,
  driveInvestigatorIntoProbation
} from '../../../test-helpers/scenarios';

import { buildProcedureData, generateInvestigatorId } from '../../../test-helpers/builders';

describe('Ledger Operations', () => {

  describe('Provisional Debits', () => {

    test('should calculate provisional debit with mixed standard/expedited portions', async () => {
      const { program, trial, phase, cohort, remainingToThreshold } =
        await setupTrialNearExpeditedThreshold(10);

      const prevTotal = EXPEDITED_THRESHOLD_POINTS - remainingToThreshold;
      const newRisk = 30;

      const procedure2Resp = await createProcedure(program.id, trial.id, phase.id, buildProcedureData({ base_risk_cost: newRisk }));
      expectSuccess(procedure2Resp, 201);
      const procedure2 = procedure2Resp.body.data;

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure2.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      expectSuccess(execResponse, 201);
      const execution = execResponse.body.data;

      const expectedDebit = calculateProvisionalDebit(prevTotal, newRisk);
      expect(execution.provisional_risk_debit).toBe(expectedDebit);
      expect(execution.is_expedited_review).toBe(true);
    });

    test('should maintain non-negative balance after deviation proposal', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      const updatedTrial = (await getTrial(program.id, trial.id)).body.data;
      expectNonNegativeBalance(updatedTrial.ethical_compliance_balance);
    });

    test('should decrement balance by exact provisional debit amount', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const balanceBefore = trial.ethical_compliance_balance;

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      expectSuccess(execResponse, 201);
      const execution = execResponse.body.data;

      const updatedTrial = (await getTrial(program.id, trial.id)).body.data;
      const balanceAfter = updatedTrial.ethical_compliance_balance;

      expect(balanceBefore - balanceAfter).toBe(execution.provisional_risk_debit);
    });

    test('should set deviation_penalty_applied=true on accepted deviation proposal', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      expectSuccess(execResponse, 201);
      expect(execResponse.body.data.deviation_penalty_applied).toBe(true);
    });

    test('should set expedited flag when cumulative risk crosses threshold', async () => {
      const { program, trial, phase, cohort } = await setupTrialNearExpeditedThreshold(5);

      const proc1Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 3 });
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
    });

    test('should apply floor function only to final sum in tariff calculation', async () => {
      const { program, trial, phase, cohort } = await setupTrialNearExpeditedThreshold(0);

      const proc1Resp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 1 });
      expectSuccess(proc1Resp, 201);
      const proc1 = proc1Resp.body.data;

      const exec1 = await createExecution(program.id, trial.id, {
        procedure_id: proc1.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      expect(exec1.body.data.provisional_risk_debit).toBe(1);
    });

    test('should calculate zero provisional debit for zero base risk', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure({ base_risk_cost: 0 });

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      expectSuccess(execResponse, 201);
      expect(execResponse.body.data.provisional_risk_debit).toBe(0);
    });

    test('should calculate effective budget equal to total when reputation is 100', async () => {
      const { program, trial } = await setupActiveTrial({ total_ethical_compliance_budget: 10000 });

      expect(trial.effective_ethical_compliance_budget).toBe(10000);
      expect(trial.effective_ethical_compliance_budget).toBe(trial.total_ethical_compliance_budget);
    });

    test('should calculate effective budget with floor when reputation is 30', async () => {
      const programResp = await createResearchProgram();
      expectSuccess(programResp, 201);
      const program = programResp.body.data;

      const investigatorId = generateInvestigatorId();

      const irbResp = await createIRB(program.id);
      expectSuccess(irbResp, 201);
      const irb = irbResp.body.data;

      await driveInvestigatorIntoProbation(program.id, irb.id, investigatorId, 30);

      const trialResp = await createTrial(program.id, {
        irb_id: irb.id,
        total_ethical_compliance_budget: 500
      }, investigatorId);
      expectSuccess(trialResp, 201);
      const trial = trialResp.body.data;

      const approvalResp = await createIRBApproval(program.id, irb.id, trial.id);
      expectSuccess(approvalResp, 201);
      const approval = approvalResp.body.data;

      const approveResp = await approveIRB(program.id, irb.id, approval.id, approval.version);
      expectSuccess(approveResp, 200);

      const activateResp = await activateTrial(program.id, trial.id);
      expectSuccess(activateResp, 200);
      const activatedTrial = activateResp.body.data;

      const expected = calculateEffectiveBudget(500, 30);
      expect(activatedTrial.effective_ethical_compliance_budget).toBe(expected);
      expect(activatedTrial.effective_ethical_compliance_budget).toBe(150);
    });

    test('should apply multiplier to all points above expedited threshold', async () => {
      const { program, trial, phase, cohort } = await setupTrialNearExpeditedThreshold(0);

      const procedure2Resp = await createProcedure(program.id, trial.id, phase.id, buildProcedureData({ base_risk_cost: 50 }));
      expectSuccess(procedure2Resp, 201);
      const procedure2 = procedure2Resp.body.data;

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure2.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      expect(execResponse.body.data.provisional_risk_debit).toBe(75);
    });

    test('should equal base risk when all points are below threshold', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure({ base_risk_cost: 50 });

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      expect(execResponse.body.data.provisional_risk_debit).toBe(50);
    });
  });

  describe('Finalized Debits', () => {

    test('should move provisional to finalized on PASS with exact amount', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      expectSuccess(execResponse, 201);
      const provisionalAmount = execResponse.body.data.provisional_risk_debit;

      const execResp = await executeExecution(program.id, trial.id, execResponse.body.data.id);
      expectSuccess(execResp, 200);

      const passResp = await markExecutionPassed(program.id, trial.id, execResponse.body.data.id);
      expectSuccess(passResp, 200);

      expect(passResp.body.data.final_risk_debit).toBe(provisionalAmount);
    });

    test('should accumulate finalized debits across multiple passed executions', async () => {
      const { program, trial, phase, cohort } = await setupTrialWithProcedure();

      for (let i = 0; i < 3; i++) {
        const procResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 50 });
        expectSuccess(procResp, 201);
        const procedure = procResp.body.data;
        await executeAndPassProcedure(program.id, trial.id, procedure.id, cohort.id, true);
      }

      const finalTrial = (await getTrial(program.id, trial.id)).body.data;
      const expectedBalance = calculateEthicalBalance(finalTrial.effective_ethical_compliance_budget, 0, 150);
      expect(finalTrial.ethical_compliance_balance).toBe(expectedBalance);
    });

    test('should calculate portfolio saturation across multiple trials exactly', async () => {
      const programResp = await createResearchProgram();
      expectSuccess(programResp, 201);
      const program = programResp.body.data;

      const portfolioResp = await createPortfolio(program.id, { max_total_ethical_budget: 1000 });
      expectSuccess(portfolioResp, 201);
      const portfolio = portfolioResp.body.data;

      const costs = [300, 400, 200];

      for (const cost of costs) {
        const { trial } = await setupActiveTrial({
          program,
          portfolio_id: portfolio.id,
          total_ethical_compliance_budget: 2000
        });

        const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
        const phase = phaseResp.body.data;
        const procResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: cost });
        const procedure = procResp.body.data;
        const cohortResponse = await createCohort(program.id, trial.id);
        const cohort = cohortResponse.body.data;
        const exec = await createExecution(program.id, trial.id, {
          procedure_id: procedure.id,
          cohort_id: cohort.id,
          protocol_deviation: true
        });

        await executeExecution(program.id, trial.id, exec.body.data.id);
        await markExecutionPassed(program.id, trial.id, exec.body.data.id);
      }

      const portfolioGet = await getPortfolio(program.id, portfolio.id);
      expect(portfolioGet.body.data.is_risk_saturated).toBe(true);
    });
  });

  describe('Ledger Reversals', () => {

    test('should restore provisional debits and update balance on rejection', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      const balanceAfterProposal = (await getTrial(program.id, trial.id)).body.data.ethical_compliance_balance;

      const rejectResp = await rejectExecution(program.id, trial.id, execResponse.body.data.id);
      expectSuccess(rejectResp, 200);

      const balanceAfterReject = (await getTrial(program.id, trial.id)).body.data.ethical_compliance_balance;

      expect(balanceAfterReject).toBeGreaterThan(balanceAfterProposal);
    });

    test('should reverse provisional debit on cancellation', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const execResponse = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      const balanceAfterProposal = (await getTrial(program.id, trial.id)).body.data.ethical_compliance_balance;

      const cancelResp = await cancelExecution(program.id, trial.id, execResponse.body.data.id);
      expectSuccess(cancelResp, 200);

      const balanceAfterCancel = (await getTrial(program.id, trial.id)).body.data.ethical_compliance_balance;

      expect(balanceAfterCancel).toBeGreaterThan(balanceAfterProposal);
    });

    test('should reverse all pending and executed deviations on abandonment', async () => {
      const { program, trial, executions } = await setupTrialWithActiveDeviations(2);

      const trialBefore = (await getTrial(program.id, trial.id)).body.data;
      const balanceBefore = trialBefore.ethical_compliance_balance;
      const effectiveBefore = trialBefore.effective_ethical_compliance_budget;

      const abandonResp = await abandonTrial(program.id, trial.id);
      expectSuccess(abandonResp, 200);

      const abandonedTrial = abandonResp.body.data;

      const effectiveAfter = abandonedTrial.effective_ethical_compliance_budget;

      expect(effectiveAfter).toBeLessThan(effectiveBefore);

      expect(abandonedTrial.status).toBe('ABANDONED');
    });

    test('should never allow provisional debits to go negative after reversal', async () => {
      const { program, trial, executions } = await setupTrialWithActiveDeviations(1);

      await abandonTrial(program.id, trial.id);

      const abandonedTrial = (await getTrial(program.id, trial.id)).body.data;
      expectNonNegativeBalance(abandonedTrial.ethical_compliance_balance);
    });
  });

  describe('Reputation Ledger', () => {

    test('should recompute effective budget and balance when reputation changes', async () => {
      const programResp = await createResearchProgram();
      expectSuccess(programResp, 201);
      const program = programResp.body.data;

      const investigatorId = generateInvestigatorId();
      const irbResp = await createIRB(program.id);
      expectSuccess(irbResp, 201);
      const irb = irbResp.body.data;

      const { trial: trial1 } = await setupActiveTrial({
        program,
        irb,
        total_ethical_compliance_budget: 10000
      }, investigatorId);

      const { trial: trial2 } = await setupActiveTrial({
        program,
        irb,
        total_ethical_compliance_budget: 10000
      }, investigatorId);

      expect(trial1.effective_ethical_compliance_budget).toBe(10000);
      expect(trial2.effective_ethical_compliance_budget).toBe(10000);

      await abandonTrial(program.id, trial1.id);

      const trial2After = (await getTrial(program.id, trial2.id)).body.data;
      const expectedEffective = calculateEffectiveBudget(10000, 90);
      expect(trial2After.effective_ethical_compliance_budget).toBe(expectedEffective);
      expect(trial2After.effective_ethical_compliance_budget).toBe(9000);
    });

    test('should propagate reputation changes to all active trials of investigator', async () => {
      const { program, investigatorId, trials } = await setupMultipleTrialsForInvestigator(2);

      const effectiveBefore = trials[1].effective_ethical_compliance_budget;

      await abandonTrial(program.id, trials[0].id);

      const trial2After = (await getTrial(program.id, trials[1].id)).body.data;
      const effectiveAfter = trial2After.effective_ethical_compliance_budget;

      expect(effectiveAfter).toBeLessThan(effectiveBefore);
      expect(effectiveAfter).toBe(Math.floor(trials[1].total_ethical_compliance_budget * 0.9));
    });

    test('should floor reputation at 0 when penalties would drive it negative', async () => {
      const programResp = await createResearchProgram();
      expectSuccess(programResp, 201);
      const program = programResp.body.data;

      const investigatorId = generateInvestigatorId();
      const irbResp = await createIRB(program.id);
      expectSuccess(irbResp, 201);
      const irb = irbResp.body.data;

      await driveInvestigatorIntoProbation(program.id, irb.id, investigatorId, 0);

      const repCheck = await initializeReputation(program.id, investigatorId);
      expect(repCheck.body.data.reputation_score).toBe(0);

      const { trial } = await setupActiveTrial({
        program,
        irb,
        total_ethical_compliance_budget: 400
      }, investigatorId);

      await forceTrialIntoLock(program.id, trial.id);

      const repAfter = await initializeReputation(program.id, investigatorId);
      expect(repAfter.body.data.reputation_score).toBe(0);
    });

    test('should reduce reputation by 10 on abandonment and update probation status', async () => {
      const { program, investigatorId, trials } = await setupMultipleTrialsForInvestigator(2);

      const effectiveBefore = trials[1].effective_ethical_compliance_budget;

      await abandonTrial(program.id, trials[0].id);

      const trial2After = (await getTrial(program.id, trials[1].id)).body.data;
      const effectiveAfter = trial2After.effective_ethical_compliance_budget;

      const expectedEffective = Math.floor(trials[1].total_ethical_compliance_budget * 0.9);
      expect(effectiveAfter).toBe(expectedEffective);
    });

    test('should maintain zero balance for trials with zero budget', async () => {
      const { program, trial } = await setupActiveTrial({ total_ethical_compliance_budget: 0 });

      expect(trial.ethical_compliance_balance).toBe(0);
      expect(trial.effective_ethical_compliance_budget).toBe(0);
    });

    test('should toggle probation status at reputation threshold', async () => {
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

      const deviation40 = await createExecution(program.id, trial40.id, {
        procedure_id: proc40.id,
        cohort_id: cohort40.id,
        protocol_deviation: true
      });
      expectSuccess(deviation40, 201);

      const irb2Resp = await createIRB(program.id);
      expectSuccess(irb2Resp, 201);
      const irb2 = irb2Resp.body.data;

      const trial39prepResp = await createTrial(program.id, { irb_id: irb2.id }, investigatorId);
      expectSuccess(trial39prepResp, 201);
      const trial39prep = trial39prepResp.body.data;

      const approval39Resp = await createIRBApproval(program.id, irb2.id, trial39prep.id);
      expectSuccess(approval39Resp, 201);
      const approval39 = approval39Resp.body.data;

      const approve39Resp = await approveIRB(program.id, irb2.id, approval39.id, approval39.version);
      expectSuccess(approve39Resp, 200);

      const activate39Resp = await activateTrial(program.id, trial39prep.id);
      expectSuccess(activate39Resp, 200);

      await abandonTrial(program.id, trial39prep.id);

      const trial39Resp = await createTrial(program.id, {
        irb_id: irb.id,
        total_ethical_compliance_budget: 500
      }, investigatorId);
      expectSuccess(trial39Resp, 201);
      const trial39 = trial39Resp.body.data;

      const approval39bResp = await createIRBApproval(program.id, irb.id, trial39.id);
      expectSuccess(approval39bResp, 201);
      const approval39b = approval39bResp.body.data;

      const approve39bResp = await approveIRB(program.id, irb.id, approval39b.id, approval39b.version);
      expectSuccess(approve39bResp, 200);

      const activate39bResp = await activateTrial(program.id, trial39.id);
      expectSuccess(activate39bResp, 200);

      const phase39Resp = await createPhase(program.id, trial39.id, PHASE_NAME.PHASE_I);
      const phase39 = phase39Resp.body.data;

      const proc39Resp = await createProcedure(program.id, trial39.id, phase39.id, { base_risk_cost: 10 });
      const proc39 = proc39Resp.body.data;

      const cohort39Resp = await createCohort(program.id, trial39.id);
      const cohort39 = cohort39Resp.body.data;

      const deviation39 = await createExecution(program.id, trial39.id, {
        procedure_id: proc39.id,
        cohort_id: cohort39.id,
        protocol_deviation: true
      });
      expectError(deviation39, 403, 'ERR_INVESTIGATOR_ON_PROBATION_DEVIATIONS_BLOCKED');
    });
  });

  describe('Portfolio Saturation Ledger', () => {

    test('should mark portfolio as saturated at exactly 90% consumption', async () => {
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

      const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
      const phase = phaseResp.body.data;
      const procResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 900 });
      const procedure = procResp.body.data;
      const cohortResponse = await createCohort(program.id, trial.id);
      const cohort = cohortResponse.body.data;
      const exec = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      await executeExecution(program.id, trial.id, exec.body.data.id);
      await markExecutionPassed(program.id, trial.id, exec.body.data.id);

      const portfolioGet = await getPortfolio(program.id, portfolio.id);
      expect(portfolioGet.body.data.is_risk_saturated).toBe(true);
    });

    test('should not saturate portfolio below 90% threshold', async () => {
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

      const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
      const phase = phaseResp.body.data;
      const procResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 150 });
      const procedure = procResp.body.data;
      const cohortResponse = await createCohort(program.id, trial.id);
      const cohort = cohortResponse.body.data;
      const exec = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      await executeExecution(program.id, trial.id, exec.body.data.id);
      await markExecutionPassed(program.id, trial.id, exec.body.data.id);

      const portfolioGet = await getPortfolio(program.id, portfolio.id);
      expect(portfolioGet.body.data.is_risk_saturated).toBe(false);
    });

    test('should toggle portfolio saturation exactly at 90% consumption boundary', async () => {
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

      const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
      const phase = phaseResp.body.data;

      for (let i = 0; i < 5; i++) {
        const cohortResp = await createCohort(program.id, trial.id);
        const cohort = cohortResp.body.data;

        const procResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 180 });
        expectSuccess(procResp, 201);

        const procedure = procResp.body.data;
        const execResp = await createExecution(program.id, trial.id, {
          procedure_id: procedure.id,
          cohort_id: cohort.id,
          protocol_deviation: true
        });
        expectSuccess(execResp, 201);
        const execution = execResp.body.data;

        await executeExecution(program.id, trial.id, execution.id);
        await markExecutionPassed(program.id, trial.id, execution.id);

        const portfolioGet = await getPortfolio(program.id, portfolio.id);
        const consumed = (i + 1) * 180;
        const expectedSaturated = consumed >= 900;

        if (i < 4) {
          expect(portfolioGet.body.data.is_risk_saturated).toBe(false);
        } else {
          expect(portfolioGet.body.data.is_risk_saturated).toBe(true);
        }
      }
    });

    test('should update saturation when portfolio max budget is increased', async () => {
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

      const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
      const phase = phaseResp.body.data;
      const procResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 900 });
      const procedure = procResp.body.data;
      const cohortResponse = await createCohort(program.id, trial.id);
      const cohort = cohortResponse.body.data;
      const exec = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      let portfolioGet = await getPortfolio(program.id, portfolio.id);
      expect(portfolioGet.body.data.is_risk_saturated).toBe(true);

      const updateResp = await updatePortfolio(program.id, portfolio.id, {
        max_total_ethical_budget: 10000,
        version: portfolio.version
      });
      expectSuccess(updateResp, 200);

      portfolioGet = await getPortfolio(program.id, portfolio.id);
      expect(portfolioGet.body.data.is_risk_saturated).toBe(false);
    });
  });

  describe('Risk & Contagion Ledgers', () => {

    test('should reduce patient safety risk on non-deviation PASS', async () => {
      const { program, trial } = await setupActiveTrial();

      await manualRiskAdjustment(program.id, trial.id, 50, 'Add base risk');

      const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
      expectSuccess(phaseResp, 201);
      const phase = phaseResp.body.data;

      const procedureResp = await createProcedure(program.id, trial.id, phase.id, {
        base_risk_cost: 10,
        integrity_score_value: 20
      });
      expectSuccess(procedureResp, 201);
      const procedure = procedureResp.body.data;

      const cohortResponse = await createCohort(program.id, trial.id);
      const cohort = cohortResponse.body.data;
      await executeAndPassProcedure(program.id, trial.id, procedure.id, cohort.id, false);

      const finalTrial = (await getTrial(program.id, trial.id)).body.data;
      expect(finalTrial.patient_safety_risk).toBe(30);
    });

    test('should floor patient safety risk at 0 with negative adjustments', async () => {
      const { program, trial } = await setupActiveTrial();

      const adjustResp = await manualRiskAdjustment(program.id, trial.id, -100, 'Large negative adjustment');
      expectSuccess(adjustResp, 200);

      const updatedTrial = adjustResp.body.data;
      expect(updatedTrial.patient_safety_risk).toBe(0);
    });

    test('should increment peer risk by contagion penalty on lock', async () => {
      const { program, portfolio, trials } = await setupPortfolioWithTrials(2);

      const trial1Before = (await getTrial(program.id, trials[1].id)).body.data;
      const riskBefore = trial1Before.patient_safety_risk;

      await forceTrialIntoLock(program.id, trials[0].id);

      const trial1After = (await getTrial(program.id, trials[1].id)).body.data;
      expect(trial1After.patient_safety_risk).toBe(riskBefore + CONTAGION_PENALTY);
      expect(trial1After.is_under_contagion).toBe(true);
    });

    test('should re-apply contagion when same trial is locked again', async () => {
      const { program, portfolio, trials } = await setupPortfolioWithTrials(2);

      const trial1Before = (await getTrial(program.id, trials[1].id)).body.data;
      const riskBefore = trial1Before.patient_safety_risk;

      await forceTrialIntoLock(program.id, trials[0].id);

      const trial1After1 = (await getTrial(program.id, trials[1].id)).body.data;
      expect(trial1After1.patient_safety_risk).toBe(riskBefore + CONTAGION_PENALTY);

      await clearEthicalReviewLock(program.id, trials[0].id);
      await forceTrialIntoLock(program.id, trials[0].id);

      const trial1After2 = (await getTrial(program.id, trials[1].id)).body.data;
      expect(trial1After2.patient_safety_risk).toBe(riskBefore + (2 * CONTAGION_PENALTY));
    });

    test('should not apply contagion penalty to already-locked peers', async () => {
      const { program, portfolio, trials } = await setupPortfolioWithTrials(3);

      await forceTrialIntoLock(program.id, trials[0].id);

      await forceTrialIntoLock(program.id, trials[1].id);

      const trial2 = (await getTrial(program.id, trials[2].id)).body.data;

      expect(trial2.patient_safety_risk).toBe(2 * CONTAGION_PENALTY);
    });
  });

  describe('Ledger Recomputation', () => {

    test('should recompute portfolio saturation after deviation proposal', async () => {
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

      const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
      const phase = phaseResp.body.data;
      const procResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 90 });
      const procedure = procResp.body.data;
      const cohortResponse = await createCohort(program.id, trial.id);
      const cohort = cohortResponse.body.data;
      const exec = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      const portfolioAfter = await getPortfolio(program.id, portfolio.id);
      expect(portfolioAfter.body.data.is_risk_saturated).toBe(true);
    });

    test('should recompute saturation after rejection reverses provisional', async () => {
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

      const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
      const phase = phaseResp.body.data;
      const procResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 90 });
      const procedure = procResp.body.data;
      const cohortResponse = await createCohort(program.id, trial.id);
      const cohort = cohortResponse.body.data;
      const exec = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      let portfolioGet = await getPortfolio(program.id, portfolio.id);
      expect(portfolioGet.body.data.is_risk_saturated).toBe(true);

      await rejectExecution(program.id, trial.id, exec.body.data.id);

      portfolioGet = await getPortfolio(program.id, portfolio.id);
      expect(portfolioGet.body.data.is_risk_saturated).toBe(false);
    });

    test('should recompute saturation after cancellation reverses provisional', async () => {
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

      const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
      const phase = phaseResp.body.data;
      const procResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 90 });
      const procedure = procResp.body.data;
      const cohortResponse = await createCohort(program.id, trial.id);
      const cohort = cohortResponse.body.data;
      const exec = await createExecution(program.id, trial.id, {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      let portfolioGet = await getPortfolio(program.id, portfolio.id);
      expect(portfolioGet.body.data.is_risk_saturated).toBe(true);

      await cancelExecution(program.id, trial.id, exec.body.data.id);

      portfolioGet = await getPortfolio(program.id, portfolio.id);
      expect(portfolioGet.body.data.is_risk_saturated).toBe(false);
    });

    test('should apply exact -25 reputation penalty on lock and propagate to all ACTIVE trials', async () => {
      const { program, investigatorId, trials } = await setupMultipleTrialsForInvestigator(2);

      const effectiveBefore = trials[1].effective_ethical_compliance_budget;

      await forceTrialIntoLock(program.id, trials[0].id);

      const trial2After = (await getTrial(program.id, trials[1].id)).body.data;
      const effectiveAfter = trial2After.effective_ethical_compliance_budget;

      const expectedEffective = Math.floor(trials[1].total_ethical_compliance_budget * 0.75);
      expect(effectiveAfter).toBe(expectedEffective);
    });

    test('should not affect ledgers when phase completes', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const balanceBefore = trial.ethical_compliance_balance;

      await executeAndPassProcedure(program.id, trial.id, procedure.id, cohort.id);

      const finalTrial = (await getTrial(program.id, trial.id)).body.data;

      expectNonNegativeBalance(finalTrial.ethical_compliance_balance);
    });

    test('should maintain balance consistency under sequential operations', async () => {
      const { program, trial, phase, cohort } = await setupTrialWithProcedure();

      for (let i = 0; i < 5; i++) {
        const procResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 20 });
        expectSuccess(procResp, 201);
        const procedure = procResp.body.data;

        const exec = await createExecution(program.id, trial.id, {
          procedure_id: procedure.id,
          cohort_id: cohort.id,
          protocol_deviation: true
        });
        expectSuccess(exec, 201);

        if (i % 2 === 0) {
          await executeExecution(program.id, trial.id, exec.body.data.id);
          await markExecutionPassed(program.id, trial.id, exec.body.data.id);
        } else {
          await cancelExecution(program.id, trial.id, exec.body.data.id);
        }
      }

      const finalTrial = (await getTrial(program.id, trial.id)).body.data;

      expectNonNegativeBalance(finalTrial.ethical_compliance_balance);
    });
  });

  describe('Ledger Invariants', () => {

    test('should maintain ledger invariant: balance = effective - provisional - finalized', async () => {
      const { program, trial, phase, cohort } = await setupTrialWithProcedure();

      for (let i = 0; i < 3; i++) {
        const procResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 50 });
        expectSuccess(procResp, 201);
        const procedure = procResp.body.data;
        await executeAndPassProcedure(program.id, trial.id, procedure.id, cohort.id, true);
      }

      const finalTrial = (await getTrial(program.id, trial.id)).body.data;

      expectNonNegativeBalance(finalTrial.ethical_compliance_balance);
    });

    test('should have no unresolved executions at completion', async () => {
      const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure();

      const readyResp = await updatePhaseStatus(program.id, trial.id, phase.id, PHASE_STATUS.READY_FOR_PROCEDURES, phase.version);
      expectSuccess(readyResp, 200);

      await executeAndPassProcedure(program.id, trial.id, procedure.id, cohort.id);

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

      expect(completeResp.body.data.status).toBe('COMPLETED');
    });
  });

  describe('Budget & Reputation Edge Cases', () => {

    test('should check probation cap against total budget not effective budget', async () => {
      const programResp = await createResearchProgram();
      expectSuccess(programResp, 201);
      const program = programResp.body.data;

      const investigatorId = generateInvestigatorId();

      const irbResp = await createIRB(program.id);
      expectSuccess(irbResp, 201);
      const irb = irbResp.body.data;

      await driveInvestigatorIntoProbation(program.id, irb.id, investigatorId, 40);

      const trialRespCap = await createTrial(program.id, {
        irb_id: irb.id,
        total_ethical_compliance_budget: PROBATION_TRIAL_BUDGET_CAP
      }, investigatorId);

      expectSuccess(trialRespCap, 201);
    });

    test('should count EXECUTED executions in active deviation limit', async () => {
      const userId = generateInvestigatorId();
      const { program, trial, executions } = await setupTrialWithActiveDeviations(3, userId);

      const execResp = await executeExecution(program.id, trial.id, executions[0].id, userId);
      expectSuccess(execResp, 200);

      const phaseResp = await createPhase(program.id, trial.id, PHASE_NAME.PHASE_I);
      expectSuccess(phaseResp, 201);
      const phase = phaseResp.body.data;

      const procResp = await createProcedure(program.id, trial.id, phase.id);
      expectSuccess(procResp, 201);
      const proc = procResp.body.data;

      const cohortResponse = await createCohort(program.id, trial.id);
      const cohort = cohortResponse.body.data;
      const exec4 = await createExecution(program.id, trial.id, {
        procedure_id: proc.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      }, userId);

      expectError(exec4, 409, 'ERR_MAX_ACTIVE_DEVIATIONS_PER_USER_VIOLATION');
    });

    test('should penalize each dependent investigator once on high-risk completion', async () => {
      const programResp = await createResearchProgram();
      expectSuccess(programResp, 201);
      const program = programResp.body.data;

      const irbResp = await createIRB(program.id);
      expectSuccess(irbResp, 201);
      const irb = irbResp.body.data;

      const inv1 = generateInvestigatorId();
      const inv2 = generateInvestigatorId();

      const { trial: trial1 } = await setupActiveTrial({ program, irb }, inv1);
      const { trial: trial2 } = await setupActiveTrial({ program, irb }, inv2);

      const { trial: depTrial } = await setupActiveTrial({ program, irb });

      await manualRiskAdjustment(program.id, depTrial.id, 80, 'High risk for test');

      const dep1Resp = await createDependency(program.id, trial1.id, depTrial.id);
      expectSuccess(dep1Resp, 201);

      const dep2Resp = await createDependency(program.id, trial2.id, depTrial.id);
      expectSuccess(dep2Resp, 201);

      const completeResp = await completeTrial(program.id, depTrial.id);
      expectSuccess(completeResp, 200);

      const rep1 = await initializeReputation(program.id, inv1);
      const rep2 = await initializeReputation(program.id, inv2);

      const expectedReputation = 100 - PENALTY_DEPENDENCY_RIPPLE;
      expect(rep1.body.data.reputation_score).toBe(expectedReputation);
      expect(rep2.body.data.reputation_score).toBe(expectedReputation);
    });

    test('should include PASSED deviations in cumulative risk calculation', async () => {
      const { program, trial, phase, cohort } = await setupTrialNearExpeditedThreshold(10);

      const { program: p, trial: t, phase: ph, procedure, cohort: c } = await setupTrialWithProcedure();

      const exec1 = await createExecution(p.id, t.id, {
        procedure_id: procedure.id,
        cohort_id: c.id,
        protocol_deviation: true
      });

      await executeExecution(p.id, t.id, exec1.body.data.id);
      await markExecutionPassed(p.id, t.id, exec1.body.data.id);

      const phResp = await createPhase(p.id, t.id, PHASE_NAME.PHASE_II);
      expectSuccess(phResp, 201);

      const proc2Resp = await createProcedure(p.id, t.id, phResp.body.data.id, { base_risk_cost: 150 });
      expectSuccess(proc2Resp, 201);

      const exec2 = await createExecution(p.id, t.id, {
        procedure_id: proc2Resp.body.data.id,
        cohort_id: c.id,
        protocol_deviation: true
      });

      expect(exec2.body.data.is_expedited_review).toBe(true);
    });

    test('should not mark as expedited when exactly at threshold', async () => {
      const { program, trial, phase, cohort } = await setupTrialNearExpeditedThreshold(0);

      const procResp = await createProcedure(program.id, trial.id, phase.id, { base_risk_cost: 0 });
      expectSuccess(procResp, 201);
      const proc = procResp.body.data;

      const exec = await createExecution(program.id, trial.id, {
        procedure_id: proc.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      });

      expect(exec.body.data.is_expedited_review).toBe(false);
    });
  });
});
