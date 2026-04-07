import { db } from '../database';
import { CalculationService } from './calculations';
import { LedgerService } from './ledgers';
import { StateMachineService } from './stateMachines';
import { ValidationService } from './validators';
import { ProcedureExecution } from '../types';
import {
  DEVIATION_REJECTION_PENALTY,
  CANCEL_TIER0_PENALTY,
  CANCEL_TIER1_PENALTY,
  CANCEL_TIER2PLUS_PENALTY,
  REVIEW_REQUIRED_TIER_THRESHOLD
} from '../utils/constants';

export class ExecutionService {

  static createExecution(
    trialId: string,
    procedureId: string,
    cohortId: string,
    protocolDeviation: boolean,
    userId: string
  ): ProcedureExecution {
    const procedure = db.getProcedure(procedureId);

    let provisionalDebit = 0;
    let isExpedited = false;

    if (protocolDeviation) {
      const prevTotal = CalculationService.calculateCohortDeviationRiskSum(trialId, cohortId);

      provisionalDebit = CalculationService.calculateProvisionalDebit(
        procedure.base_risk_cost,
        prevTotal
      );

      isExpedited = CalculationService.isExpedited(prevTotal + procedure.base_risk_cost);
    }

    ValidationService.validateDeviationProposal(
      trialId,
      procedureId,
      cohortId,
      protocolDeviation,
      userId,
      provisionalDebit
    );

    const execution = db.createExecution({
      trial_id: trialId,
      research_program_id: procedure.research_program_id,
      procedure_id: procedureId,
      cohort_id: cohortId,
      protocol_deviation: protocolDeviation,
      proposing_user_id: userId,
      provisional_risk_debit: provisionalDebit,
      is_expedited_review: isExpedited
    });

    if (protocolDeviation) {
      LedgerService.addProvisionalDebit(trialId, provisionalDebit);

      LedgerService.syncTrialAndPortfolio(trialId);
    }

    StateMachineService.transitionProcedure(procedureId, 'AWAITING_EXECUTION');

    return execution;
  }

  static executeExecution(executionId: string): ProcedureExecution {
    ValidationService.validateExecutionExecute(executionId);

    StateMachineService.transitionExecution(executionId, 'EXECUTED');

    return db.getExecution(executionId);
  }

  static markExecutionPassed(executionId: string): ProcedureExecution {
    ValidationService.validateExecutionMarkPassed(executionId);

    const execution = db.getExecution(executionId);
    const procedure = db.getProcedure(execution.procedure_id);

    StateMachineService.transitionExecution(executionId, 'PASSED');

    StateMachineService.transitionProcedure(execution.procedure_id, 'PASSED');

    if (execution.protocol_deviation) {
      LedgerService.finalizeDebit(execution.trial_id, execution.provisional_risk_debit);

      execution.final_risk_debit = execution.provisional_risk_debit;
    } else {
      LedgerService.decrementSafetyRisk(execution.trial_id, procedure.integrity_score_value);
    }

    LedgerService.syncTrialAndPortfolio(execution.trial_id);

    return execution;
  }

  static rejectExecution(executionId: string): ProcedureExecution {
    ValidationService.validateExecutionReject(executionId);

    const execution = db.getExecution(executionId);

    StateMachineService.transitionExecution(executionId, 'REJECTED');

    StateMachineService.transitionProcedure(execution.procedure_id, 'FAILED');

    if (execution.protocol_deviation) {
      LedgerService.removeProvisionalDebit(execution.trial_id, execution.provisional_risk_debit);
    }

    LedgerService.incrementSafetyRisk(execution.trial_id, DEVIATION_REJECTION_PENALTY);

    LedgerService.syncTrialAndPortfolio(execution.trial_id);
    StateMachineService.checkAndApplySafetyLock(execution.trial_id);

    return execution;
  }

  static cancelExecution(executionId: string): ProcedureExecution {
    ValidationService.validateExecutionCancel(executionId);

    const execution = db.getExecution(executionId);
    const trial = db.getTrial(execution.trial_id);

    StateMachineService.transitionExecution(executionId, 'CANCELLED');

    StateMachineService.transitionProcedure(execution.procedure_id, 'CANCELLED');

    if (execution.protocol_deviation) {
      LedgerService.removeProvisionalDebit(execution.trial_id, execution.provisional_risk_debit);
    }

    const penalty = this.getCancelPenalty(trial.deviation_penalty_tier);
    LedgerService.incrementSafetyRisk(execution.trial_id, penalty);

    trial.deviation_penalty_tier++;

    if (trial.deviation_penalty_tier >= REVIEW_REQUIRED_TIER_THRESHOLD) {
      const procedure = db.getProcedure(execution.procedure_id);
      const phase = db.getPhase(procedure.phase_id);
      if (phase.status === 'READY_FOR_PROCEDURES') {
        StateMachineService.transitionPhase(phase.id, 'REVIEW_REQUIRED');
      }
    }

    LedgerService.syncTrialAndPortfolio(execution.trial_id);
    StateMachineService.checkAndApplySafetyLock(execution.trial_id);

    return execution;
  }

  private static getCancelPenalty(tier: number): number {
    if (tier === 0) return CANCEL_TIER0_PENALTY;
    if (tier === 1) return CANCEL_TIER1_PENALTY;
    return CANCEL_TIER2PLUS_PENALTY;
  }
}
