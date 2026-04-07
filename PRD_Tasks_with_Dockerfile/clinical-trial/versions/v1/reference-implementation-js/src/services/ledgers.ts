import { db } from '../database';
import { CalculationService } from './calculations';
import {
  MIN_REPUTATION_SCORE,
  MAX_REPUTATION_SCORE
} from '../utils/constants';

export class LedgerService {

  static addProvisionalDebit(trialId: string, amount: number): void {
    const ledger = db.getEthicalBudgetLedger(trialId);
    ledger.provisional_debits += amount;
  }

  static removeProvisionalDebit(trialId: string, amount: number): void {
    const ledger = db.getEthicalBudgetLedger(trialId);
    ledger.provisional_debits = Math.max(0, ledger.provisional_debits - amount);
  }

  static finalizeDebit(trialId: string, amount: number): void {
    const ledger = db.getEthicalBudgetLedger(trialId);
    ledger.provisional_debits = Math.max(0, ledger.provisional_debits - amount);
    ledger.finalized_debits += amount;
  }

  static incrementSafetyRisk(trialId: string, amount: number): void {
    const ledger = db.getSafetyLedger(trialId);
    ledger.risk_score += amount;
  }

  static decrementSafetyRisk(trialId: string, amount: number): void {
    const ledger = db.getSafetyLedger(trialId);
    ledger.risk_score = Math.max(0, ledger.risk_score - amount);
  }

  static setSafetyRisk(trialId: string, value: number): void {
    const ledger = db.getSafetyLedger(trialId);
    ledger.risk_score = Math.max(0, value);
  }

  static applyReputationPenalty(
    programId: string,
    investigatorId: string,
    penalty: number
  ): void {
    const reputation = db.getReputationLedger(programId, investigatorId);

    reputation.reputation_score = Math.max(
      MIN_REPUTATION_SCORE,
      Math.min(MAX_REPUTATION_SCORE, reputation.reputation_score - penalty)
    );

    CalculationService.syncProbationFlag(programId, investigatorId);

    this.propagateReputationToTrials(programId, investigatorId);
  }

  static increaseReputation(
    programId: string,
    investigatorId: string,
    amount: number
  ): void {
    const reputation = db.getReputationLedger(programId, investigatorId);

    reputation.reputation_score = Math.max(
      MIN_REPUTATION_SCORE,
      Math.min(MAX_REPUTATION_SCORE, reputation.reputation_score + amount)
    );

    CalculationService.syncProbationFlag(programId, investigatorId);

    this.propagateReputationToTrials(programId, investigatorId);
  }

  private static propagateReputationToTrials(
    programId: string,
    investigatorId: string
  ): void {
    const trials = db.listTrials(programId).filter(
      t => t.investigator_id === investigatorId && t.status === 'ACTIVE'
    );

    for (const trial of trials) {
      CalculationService.syncTrialDerivedFields(trial.id);

      trial.version++;
      trial.updated_at = new Date().toISOString();
    }
  }

  static recomputePortfolioSaturation(portfolioId: string | undefined): void {
    if (!portfolioId) return;

    CalculationService.syncPortfolioSaturation(portfolioId);
  }

  static syncTrialAndPortfolio(trialId: string): void {
    const trial = db.getTrial(trialId);

    CalculationService.syncTrialDerivedFields(trialId);

    if (trial.portfolio_id) {
      this.recomputePortfolioSaturation(trial.portfolio_id);
    }
  }

  static reverseAllProvisionalDebits(trialId: string): void {
    const executions = db.listExecutions(trialId).filter(
      e => e.protocol_deviation === true &&
           ['PENDING_EXECUTION', 'EXECUTED'].includes(e.status)
    );

    let totalToReverse = 0;
    for (const exec of executions) {
      totalToReverse += exec.provisional_risk_debit;
    }

    if (totalToReverse > 0) {
      this.removeProvisionalDebit(trialId, totalToReverse);
    }
  }
}
