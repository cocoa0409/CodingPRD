import { db } from '../database';
import {
  EXPEDITED_THRESHOLD_POINTS,
  EXPEDITED_MULTIPLIER,
  SATURATION_PERCENT_THRESHOLD,
  PROBATION_THRESHOLD_SCORE
} from '../utils/constants';

export class CalculationService {

  static calculateEffectiveBudget(trialId: string): number {
    const trial = db.getTrial(trialId);
    const reputation = db.getReputationLedger(
      trial.research_program_id,
      trial.investigator_id
    );

    return Math.floor(
      trial.total_ethical_compliance_budget * reputation.reputation_score / 100
    );
  }

  static calculateEthicalBalance(trialId: string): number {
    const effectiveBudget = this.calculateEffectiveBudget(trialId);
    const ledger = db.getEthicalBudgetLedger(trialId);

    return effectiveBudget - ledger.provisional_debits - ledger.finalized_debits;
  }

  static calculateCohortDeviationRiskSum(trialId: string, cohortId: string): number {
    const executions = db.listExecutions(trialId);

    let sum = 0;
    for (const exec of executions) {
      if (
        exec.cohort_id === cohortId &&
        exec.protocol_deviation === true &&
        ['PENDING_EXECUTION', 'EXECUTED', 'PASSED'].includes(exec.status)
      ) {
        const procedure = db.getProcedure(exec.procedure_id);
        sum += procedure.base_risk_cost;
      }
    }

    return sum;
  }

  static isExpedited(totalAfter: number): boolean {
    return totalAfter > EXPEDITED_THRESHOLD_POINTS;
  }

  static calculateProvisionalDebit(base: number, prevTotal: number): number {
    const totalAfter = prevTotal + base;

    const expeditedNew =
      Math.max(0, totalAfter - EXPEDITED_THRESHOLD_POINTS) -
      Math.max(0, prevTotal - EXPEDITED_THRESHOLD_POINTS);

    const standard = base - expeditedNew;

    return Math.floor(standard + expeditedNew * EXPEDITED_MULTIPLIER);
  }

  static calculatePortfolioSaturation(portfolioId: string): boolean {
    const portfolio = db.getPortfolio(portfolioId);
    const trials = db.listTrials().filter(t => t.portfolio_id === portfolioId);

    let consumed = 0;
    for (const trial of trials) {
      const ledger = db.getEthicalBudgetLedger(trial.id);
      consumed += ledger.provisional_debits + ledger.finalized_debits;
    }

    const percentage = (100 * consumed) / portfolio.max_total_ethical_budget;
    return percentage >= SATURATION_PERCENT_THRESHOLD;
  }

  static isOnProbation(programId: string, investigatorId: string): boolean {
    const reputation = db.getReputationLedger(programId, investigatorId);
    return reputation.reputation_score < PROBATION_THRESHOLD_SCORE;
  }

  static syncTrialDerivedFields(trialId: string): void {
    const trial = db.getTrial(trialId);
    const safetyLedger = db.getSafetyLedger(trialId);

    trial.effective_ethical_compliance_budget = this.calculateEffectiveBudget(trialId);

    trial.ethical_compliance_balance = this.calculateEthicalBalance(trialId);

    trial.patient_safety_risk = safetyLedger.risk_score;

  }

  static syncProbationFlag(programId: string, investigatorId: string): void {
    const reputation = db.getReputationLedger(programId, investigatorId);
    reputation.is_on_probation = reputation.reputation_score < PROBATION_THRESHOLD_SCORE;
  }

  static syncPortfolioSaturation(portfolioId: string): void {
    const portfolio = db.getPortfolio(portfolioId);
    portfolio.is_risk_saturated = this.calculatePortfolioSaturation(portfolioId);
  }
}
