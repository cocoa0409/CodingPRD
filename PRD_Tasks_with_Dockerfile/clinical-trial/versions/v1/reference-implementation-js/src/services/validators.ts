import { db } from '../database';
import { Errors, ApiError } from '../utils/errors';
import { patternMatch } from '../utils/helpers';
import {
  MAX_ACTIVE_DEVIATIONS_PER_USER,
  PROBATION_TRIAL_BUDGET_CAP,
  MAX_ADVANCE_BY
} from '../utils/constants';

export class ValidationService {

  static validateTrialCreation(
    programId: string,
    investigatorId: string,
    irbId: string,
    portfolioId: string | undefined,
    totalBudget: number
  ): void {
    try {
      const irb = db.getIRB(irbId);
      if (irb.research_program_id !== programId) {
        throw Errors.IRB_PROGRAM_MISMATCH();
      }
    } catch (e) {
      throw Errors.IRB_NOT_FOUND();
    }

    if (portfolioId) {
      try {
        const portfolio = db.getPortfolio(portfolioId);
        if (portfolio.research_program_id !== programId) {
          throw Errors.PORTFOLIO_NOT_FOUND();
        }
      } catch (e) {
        throw Errors.PORTFOLIO_NOT_FOUND();
      }
    }

    const reputation = db.getReputationLedger(programId, investigatorId);
    if (reputation.is_on_probation && totalBudget > PROBATION_TRIAL_BUDGET_CAP) {
      throw Errors.INVESTIGATOR_ON_PROBATION_BUDGET_EXCEEDED();
    }
  }

  static validateTrialActivation(trialId: string): void {
    const trial = db.getTrial(trialId);

    if (trial.status !== 'DRAFT') {
      throw Errors.TRIAL_NOT_IN_DRAFT();
    }

    const dependencies = db.listDependencies(trialId);
    for (const dep of dependencies) {
      const depTrial = db.getTrial(dep.dependency_trial_id);

      if (depTrial.status === 'ETHICAL_REVIEW_LOCK') {
        throw Errors.DEPENDENCY_IN_ETHICAL_REVIEW_LOCK();
      }
      if (depTrial.status !== 'COMPLETED') {
        throw Errors.DEPENDENCIES_NOT_MET();
      }
    }

    const approvals = db.listIRBApprovals(undefined, trialId);
    const hasApproved = approvals.some(a => a.status === 'APPROVED');
    if (!hasApproved) {
      throw Errors.NO_APPROVED_IRB();
    }
  }

  static validateTrialCompletion(trialId: string): void {
    const trial = db.getTrial(trialId);

    if (trial.status !== 'ACTIVE') {
      if (trial.status === 'ETHICAL_REVIEW_LOCK') {
        throw Errors.TRIAL_IN_ETHICAL_REVIEW_LOCK();
      }
      throw Errors.TRIAL_NOT_ACTIVE();
    }

    const executions = db.listExecutions(trialId);
    const unresolved = executions.filter(e =>
      ['PENDING_EXECUTION', 'EXECUTED'].includes(e.status)
    );
    if (unresolved.length > 0) {
      throw Errors.UNRESOLVED_EXECUTIONS_EXIST();
    }

    const phases = db.listPhases(trialId);
    const notCompleted = phases.filter(p => p.status !== 'COMPLETED');
    if (notCompleted.length > 0) {
      throw Errors.PHASES_NOT_COMPLETED();
    }

    const dependencies = db.listDependencies(trialId);
    for (const dep of dependencies) {
      const depTrial = db.getTrial(dep.dependency_trial_id);
      if (depTrial.status !== 'COMPLETED') {
        throw Errors.DEPENDENCIES_NOT_MET();
      }
    }

  }

  static validateTrialAbandonment(trialId: string): void {
    const trial = db.getTrial(trialId);

    if (!['DRAFT', 'ACTIVE'].includes(trial.status)) {
      throw Errors.TRIAL_NOT_ABANDONABLE();
    }
  }

  static validateDependencyCreation(
    sourceTrialId: string,
    dependencyTrialId: string
  ): void {
    const sourceTrial = db.getTrial(sourceTrialId);

    let depTrial;
    try {
      depTrial = db.getTrial(dependencyTrialId);
    } catch (e) {
      throw Errors.DEPENDENCY_TRIAL_NOT_FOUND();
    }

    if (sourceTrialId === dependencyTrialId) {
      throw Errors.SELF_DEPENDENCY();
    }

    if (sourceTrial.research_program_id !== depTrial.research_program_id) {
      throw Errors.CROSS_PROGRAM_DEPENDENCY();
    }

    const existingDeps = db.listDependencies(sourceTrialId);
    const duplicate = existingDeps.some(d =>
      d.source_trial_id === sourceTrialId &&
      d.dependency_trial_id === dependencyTrialId
    );
    if (duplicate) {
      throw new ApiError(409, 'ERR_INVALID_REQUEST', 'Dependency relationship already exists');
    }
  }

  static validatePhaseReady(phaseId: string): void {
    const procedures = db.listProcedures(phaseId);
    if (procedures.length === 0) {
      throw Errors.NO_PROCEDURES_DEFINED();
    }
  }

  static validatePhaseCompletion(phaseId: string): void {
    const phase = db.getPhase(phaseId);

    if (phase.status === 'REVIEW_REQUIRED') {
      throw Errors.PHASE_IN_REVIEW();
    }

    const procedures = db.listProcedures(phaseId);
    const notPassed = procedures.filter(p => p.status !== 'PASSED');
    if (notPassed.length > 0) {
      throw Errors.PROCEDURES_NOT_PASSED();
    }

    this.validateNoActiveBlackout(phase.trial_id);
  }

  static validateNoActiveBlackout(trialId: string): void {
    const trial = db.getTrial(trialId);
    const program = db.getProgram(trial.research_program_id);
    const blackouts = db.listBlackoutWindows(trial.research_program_id);

    const currentPeriod = program.current_period_index;

    for (const blackout of blackouts) {
      if (currentPeriod >= blackout.start_period_index &&
          currentPeriod <= blackout.end_period_index) {
        if (patternMatch(blackout.treatment_name_pattern, trial.treatment_name)) {
          throw Errors.ENROLLMENT_BLACKOUT_ACTIVE();
        }
      }
    }
  }

  static validateDeviationProposal(
    trialId: string,
    procedureId: string,
    cohortId: string,
    protocolDeviation: boolean,
    userId: string,
    provisionalDebit: number
  ): void {
    const trial = db.getTrial(trialId);
    const procedure = db.getProcedure(procedureId);
    const cohort = db.getCohort(cohortId);

    if (trial.status === 'ETHICAL_REVIEW_LOCK') {
      throw Errors.TRIAL_IN_ETHICAL_REVIEW_LOCK();
    }
    if (trial.status !== 'ACTIVE') {
      throw Errors.TRIAL_NOT_ACTIVE();
    }

    if (procedure.status !== 'PENDING') {
      throw Errors.PROCEDURE_NOT_PENDING();
    }

    if (procedure.trial_id !== trialId) {
      throw Errors.PROCEDURE_NOT_FOUND();
    }
    if (cohort.trial_id !== trialId) {
      throw Errors.COHORT_NOT_FOUND();
    }

    if (procedure.required_cohort_tag !== 'NONE') {
      const hasTag = cohort.properties.some(
        p => p.name === procedure.required_cohort_tag
      );
      if (!hasTag) {
        throw Errors.COHORT_TAG_MISMATCH();
      }
    }

    this.validateCohortPhasePairing(cohortId, procedure.phase_id);

    if (protocolDeviation) {
      this.validateDeviationGates(trialId, userId, provisionalDebit);
    }
  }

  private static validateCohortPhasePairing(cohortId: string, phaseId: string): void {
    const cohort = db.getCohort(cohortId);
    const phase = db.getPhase(phaseId);
    const pairings = db.listIncompatiblePairings(cohort.research_program_id);

    for (const pairing of pairings) {
      if (pairing.phase_name === phase.name) {
        const hasProperty = cohort.properties.some(p => p.name === pairing.cohort_property);
        if (hasProperty) {
          throw Errors.INCOMPATIBLE_COHORT_PHASE_PAIRING();
        }
      }
    }
  }

  private static validateDeviationGates(
    trialId: string,
    userId: string,
    provisionalDebit: number
  ): void {
    const trial = db.getTrial(trialId);

    const reputation = db.getReputationLedger(
      trial.research_program_id,
      trial.investigator_id
    );
    if (reputation.is_on_probation) {
      throw Errors.INVESTIGATOR_ON_PROBATION_DEVIATIONS_BLOCKED();
    }

    if (trial.portfolio_id) {
      const portfolio = db.getPortfolio(trial.portfolio_id);
      if (portfolio.is_risk_saturated) {
        throw Errors.PORTFOLIO_RISK_SATURATED();
      }
    }

    this.validateActiveDeviationLimit(userId, trial.research_program_id);

    if (provisionalDebit > trial.ethical_compliance_balance) {
      throw Errors.INSUFFICIENT_ETHICAL_BUDGET();
    }
  }

  private static validateActiveDeviationLimit(userId: string, programId: string): void {
    const executions = db.listExecutions(undefined, programId);

    const activeCount = executions.filter(e =>
      e.proposing_user_id === userId &&
      e.protocol_deviation === true &&
      ['PENDING_EXECUTION', 'EXECUTED'].includes(e.status)
    ).length;

    if (activeCount >= MAX_ACTIVE_DEVIATIONS_PER_USER) {
      throw Errors.MAX_ACTIVE_DEVIATIONS_PER_USER_VIOLATION();
    }
  }

  static validateExecutionExecute(executionId: string): void {
    const execution = db.getExecution(executionId);

    if (execution.status !== 'PENDING_EXECUTION') {
      throw Errors.EXECUTION_NOT_PENDING();
    }
  }

  static validateExecutionMarkPassed(executionId: string): void {
    const execution = db.getExecution(executionId);

    if (execution.status !== 'EXECUTED') {
      throw Errors.EXECUTION_NOT_EXECUTED();
    }

    const procedure = db.getProcedure(execution.procedure_id);
    if (procedure.status !== 'AWAITING_EXECUTION') {
      throw Errors.PROCEDURE_NOT_AWAITING_EXECUTION();
    }
  }

  static validateExecutionReject(executionId: string): void {
    const execution = db.getExecution(executionId);

    if (!['PENDING_EXECUTION', 'EXECUTED'].includes(execution.status)) {
      throw Errors.EXECUTION_NOT_REJECTABLE();
    }

    if (execution.status === 'EXECUTED') {
      const procedure = db.getProcedure(execution.procedure_id);
      if (procedure.status !== 'AWAITING_EXECUTION') {
        throw Errors.PROCEDURE_NOT_AWAITING_EXECUTION();
      }
    }
  }

  static validateExecutionCancel(executionId: string): void {
    const execution = db.getExecution(executionId);

    if (!['PENDING_EXECUTION', 'EXECUTED'].includes(execution.status)) {
      throw Errors.EXECUTION_NOT_CANCELLABLE();
    }
  }

  static validateManualRiskAdjustment(
    trialId: string,
    adjustment: number,
    justification: string
  ): void {
    const trial = db.getTrial(trialId);

    if (trial.status !== 'ACTIVE') {
      throw Errors.TRIAL_NOT_ACTIVE();
    }

    if (adjustment === 0) {
      throw Errors.INVALID_ADJUSTMENT_VALUE();
    }

    if (justification.length < 10) {
      throw Errors.INSUFFICIENT_JUSTIFICATION();
    }
  }

  static validateClockAdvance(byPeriods: number): void {
    if (byPeriods < 1 || byPeriods > MAX_ADVANCE_BY) {
      throw Errors.INVALID_REQUEST('by_periods must be between 1 and ' + MAX_ADVANCE_BY);
    }
  }

  static validateCohortProperties(properties: any[]): void {
    const validNames = ['HEALTHY_VOLUNTEERS', 'HIGH_RISK_PATIENTS', 'CONTAINS_PLACEBO'];

    for (const prop of properties) {
      if (!validNames.includes(prop.name)) {
        throw Errors.INVALID_PROPERTY_NAME();
      }
    }
  }

  static validateIRBApprovalCreation(irbId: string, trialId: string): void {
    const irb = db.getIRB(irbId);
    const trial = db.getTrial(trialId);

    if (irb.research_program_id !== trial.research_program_id) {
      throw Errors.IRB_PROGRAM_MISMATCH();
    }
  }

  static validateIRBApprovalUpdate(status: string): void {
    const validStatuses = ['APPROVED', 'REJECTED'];
    if (!validStatuses.includes(status)) {
      throw Errors.INVALID_IRB_STATUS();
    }
  }

  static validateBlackoutWindow(startPeriod: number, endPeriod: number): void {
    if (startPeriod > endPeriod) {
      throw Errors.INVALID_REQUEST('start_period_index must be <= end_period_index');
    }
  }

  static validatePhaseName(name: string): void {
    const validNames = ['PHASE_I', 'PHASE_II', 'PHASE_III', 'PHASE_IV'];
    if (!validNames.includes(name)) {
      throw Errors.INVALID_PHASE_NAME();
    }
  }
}
