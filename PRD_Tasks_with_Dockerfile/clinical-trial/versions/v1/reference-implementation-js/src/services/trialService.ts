import { db } from '../database';
import { CalculationService } from './calculations';
import { LedgerService } from './ledgers';
import { StateMachineService } from './stateMachines';
import { ValidationService } from './validators';
import { ClinicalTrial } from '../types';
import {
  PENALTY_ABANDONED_TRIAL,
  PENALTY_DEPENDENCY_RIPPLE,
  HIGH_RISK_COMPLETION_THRESHOLD
} from '../utils/constants';

export class TrialService {

  static createTrial(
    programId: string,
    investigatorId: string,
    treatmentName: string,
    totalBudget: number,
    irbId: string,
    portfolioId?: string
  ): ClinicalTrial {
    ValidationService.validateTrialCreation(
      programId,
      investigatorId,
      irbId,
      portfolioId,
      totalBudget
    );

    const trial = db.createTrial({
      research_program_id: programId,
      investigator_id: investigatorId,
      treatment_name: treatmentName,
      total_ethical_compliance_budget: totalBudget,
      portfolio_id: portfolioId,
      irb_id: irbId
    });

    db.getEthicalBudgetLedger(trial.id);
    db.getSafetyLedger(trial.id);

    CalculationService.syncTrialDerivedFields(trial.id);

    return trial;
  }

  static activateTrial(trialId: string): ClinicalTrial {
    ValidationService.validateTrialActivation(trialId);

    StateMachineService.transitionTrial(trialId, 'ACTIVE');

    return db.getTrial(trialId);
  }

  static completeTrial(trialId: string): ClinicalTrial {
    ValidationService.validateTrialCompletion(trialId);

    ValidationService.validateNoActiveBlackout(trialId);

    StateMachineService.transitionTrial(trialId, 'COMPLETED');

    const completedTrial = db.getTrial(trialId);
    if (completedTrial.patient_safety_risk > HIGH_RISK_COMPLETION_THRESHOLD) {
      this.applyDependencyRipplePenalties(trialId);
    }

    return db.getTrial(trialId);
  }

  private static applyDependencyRipplePenalties(completedTrialId: string): void {
    const completedTrial = db.getTrial(completedTrialId);

    const allDependencies = db.listDependencies();
    const dependentOnThis = allDependencies.filter(
      d => d.dependency_trial_id === completedTrialId &&
           d.research_program_id === completedTrial.research_program_id
    );

    const uniqueInvestigators = new Map<string, string>();
    for (const dep of dependentOnThis) {
      const sourceTrial = db.getTrial(dep.source_trial_id);
      uniqueInvestigators.set(sourceTrial.investigator_id, sourceTrial.research_program_id);
    }
    for (const [investigatorId, programId] of uniqueInvestigators.entries()) {
      LedgerService.applyReputationPenalty(
        programId,
        investigatorId,
        PENALTY_DEPENDENCY_RIPPLE
      );
    }
  }

  static abandonTrial(trialId: string): ClinicalTrial {
    ValidationService.validateTrialAbandonment(trialId);

    LedgerService.reverseAllProvisionalDebits(trialId);

    LedgerService.syncTrialAndPortfolio(trialId);

    StateMachineService.transitionTrial(trialId, 'ABANDONED');

    const abandonedTrial = db.getTrial(trialId);

    LedgerService.applyReputationPenalty(
      abandonedTrial.research_program_id,
      abandonedTrial.investigator_id,
      PENALTY_ABANDONED_TRIAL
    );

    CalculationService.syncTrialDerivedFields(trialId);

    return db.getTrial(trialId);
  }

  static clearEthicalReviewLock(trialId: string): ClinicalTrial {
    StateMachineService.clearEthicalReviewLock(trialId);

    return db.getTrial(trialId);
  }

  static manualRiskAdjustment(
    trialId: string,
    adjustment: number,
    justification: string
  ): ClinicalTrial {
    ValidationService.validateManualRiskAdjustment(trialId, adjustment, justification);

    const safetyLedger = db.getSafetyLedger(trialId);

    const newRisk = Math.max(0, safetyLedger.risk_score + adjustment);
    safetyLedger.risk_score = newRisk;

    LedgerService.syncTrialAndPortfolio(trialId);

    StateMachineService.checkAndApplySafetyLock(trialId);

    return db.getTrial(trialId);
  }
}
