import { db } from '../database';
import { LedgerService } from './ledgers';
import { Errors } from '../utils/errors';
import {
  TrialStatus,
  PhaseStatus,
  ProcedureStatus,
  ExecutionStatus,
  IRBApprovalStatus
} from '../types';
import {
  AUDIT_LOCK_THRESHOLD,
  PENALTY_ETHICAL_LOCK,
  CONTAGION_PENALTY
} from '../utils/constants';

export class StateMachineService {

  private static readonly TRIAL_TRANSITIONS: Record<TrialStatus, TrialStatus[]> = {
    'DRAFT': ['ACTIVE', 'ABANDONED'],
    'ACTIVE': ['COMPLETED', 'ABANDONED', 'ETHICAL_REVIEW_LOCK'],
    'ETHICAL_REVIEW_LOCK': ['ACTIVE'],
    'COMPLETED': [],
    'ABANDONED': []
  };

  static transitionTrial(trialId: string, newStatus: TrialStatus): void {
    const trial = db.getTrial(trialId);
    const validTransitions = this.TRIAL_TRANSITIONS[trial.status];

    if (!validTransitions.includes(newStatus)) {
      throw Errors.INVALID_STATE();
    }

    trial.status = newStatus;
    trial.version++;
    trial.updated_at = new Date().toISOString();

    LedgerService.syncTrialAndPortfolio(trialId);
  }

  static checkAndApplySafetyLock(trialId: string): void {
    const trial = db.getTrial(trialId);

    if (trial.status !== 'ACTIVE') return;

    if (trial.patient_safety_risk > AUDIT_LOCK_THRESHOLD) {
      this.transitionTrial(trialId, 'ETHICAL_REVIEW_LOCK');

      LedgerService.applyReputationPenalty(
        trial.research_program_id,
        trial.investigator_id,
        PENALTY_ETHICAL_LOCK
      );

      LedgerService.syncTrialAndPortfolio(trialId);

      this.applyPortfolioContagion(trialId);
    }
  }

  private static applyPortfolioContagion(lockedTrialId: string): void {
    const lockedTrial = db.getTrial(lockedTrialId);

    if (!lockedTrial.portfolio_id) return;

    const peers = db.listTrials(lockedTrial.research_program_id).filter(t =>
      t.id !== lockedTrialId &&
      t.portfolio_id === lockedTrial.portfolio_id &&
      t.status === 'ACTIVE'
    );

    const secondaryLockedTrials: string[] = [];

    for (const peer of peers) {
      LedgerService.incrementSafetyRisk(peer.id, CONTAGION_PENALTY);

      peer.is_under_contagion = true;
      peer.version++;
      peer.updated_at = new Date().toISOString();

      LedgerService.syncTrialAndPortfolio(peer.id);

      const peerAfter = db.getTrial(peer.id);
      if (peerAfter.status === 'ACTIVE' && peerAfter.patient_safety_risk > AUDIT_LOCK_THRESHOLD) {
        this.transitionTrial(peer.id, 'ETHICAL_REVIEW_LOCK');

        LedgerService.applyReputationPenalty(
          peerAfter.research_program_id,
          peerAfter.investigator_id,
          PENALTY_ETHICAL_LOCK
        );

        LedgerService.syncTrialAndPortfolio(peer.id);

        secondaryLockedTrials.push(peer.id);
      }
    }
  }

  static clearEthicalReviewLock(trialId: string): void {
    const trial = db.getTrial(trialId);

    if (trial.status !== 'ETHICAL_REVIEW_LOCK') {
      throw Errors.TRIAL_NOT_IN_ETHICAL_REVIEW_LOCK();
    }

    let otherLocksRemain = false;
    if (trial.portfolio_id) {
      const peers = db
        .listTrials(trial.research_program_id)
        .filter(t => t.portfolio_id === trial.portfolio_id && t.id !== trialId);
      otherLocksRemain = peers.some(t => t.status === 'ETHICAL_REVIEW_LOCK');
    }

    this.transitionTrial(trialId, 'ACTIVE');

    if (trial.portfolio_id && !otherLocksRemain) {
      this.checkAndResetContagionFlags(trial.research_program_id, trial.portfolio_id);
    }
  }

  private static checkAndResetContagionFlags(programId: string, portfolioId: string): void {
    const trials = db
      .listTrials(programId)
      .filter(t => t.portfolio_id === portfolioId);

    const hasLockedTrials = trials.some(t => t.status === 'ETHICAL_REVIEW_LOCK');

    if (!hasLockedTrials) {
      for (const trial of trials) {
        if (trial.is_under_contagion) {
          trial.is_under_contagion = false;
          trial.version++;
          trial.updated_at = new Date().toISOString();
        }
      }
    }
  }

  private static readonly PHASE_TRANSITIONS: Record<PhaseStatus, PhaseStatus[]> = {
    'PENDING': ['READY_FOR_PROCEDURES', 'CANCELLED'],
    'READY_FOR_PROCEDURES': ['COMPLETED', 'CANCELLED', 'REVIEW_REQUIRED'],
    'REVIEW_REQUIRED': ['READY_FOR_PROCEDURES'],
    'COMPLETED': [],
    'CANCELLED': []
  };

  static isValidPhaseTransition(currentStatus: PhaseStatus, newStatus: PhaseStatus): boolean {
    const validTransitions = this.PHASE_TRANSITIONS[currentStatus];
    return validTransitions.includes(newStatus);
  }

  static validatePhaseTransition(phaseId: string, newStatus: PhaseStatus): void {
    const phase = db.getPhase(phaseId);
    if (!this.isValidPhaseTransition(phase.status, newStatus)) {
      throw Errors.ILLEGAL_PHASE_STATE_TRANSITION();
    }
  }

  static transitionPhase(phaseId: string, newStatus: PhaseStatus): void {
    const phase = db.getPhase(phaseId);
    const validTransitions = this.PHASE_TRANSITIONS[phase.status];

    if (!validTransitions.includes(newStatus)) {
      throw Errors.ILLEGAL_PHASE_STATE_TRANSITION();
    }

    phase.status = newStatus;
    phase.version++;
    phase.updated_at = new Date().toISOString();
  }

  private static readonly PROCEDURE_TRANSITIONS: Record<ProcedureStatus, ProcedureStatus[]> = {
    'PENDING': ['AWAITING_EXECUTION', 'CANCELLED'],
    'AWAITING_EXECUTION': ['PASSED', 'FAILED', 'CANCELLED'],
    'PASSED': [],
    'FAILED': [],
    'CANCELLED': []
  };

  static transitionProcedure(procedureId: string, newStatus: ProcedureStatus): void {
    const procedure = db.getProcedure(procedureId);
    const validTransitions = this.PROCEDURE_TRANSITIONS[procedure.status];

    if (!validTransitions.includes(newStatus)) {
      throw Errors.INVALID_STATE();
    }

    procedure.status = newStatus;
    procedure.version++;
    procedure.updated_at = new Date().toISOString();
  }

  private static readonly EXECUTION_TRANSITIONS: Record<ExecutionStatus, ExecutionStatus[]> = {
    'PENDING_EXECUTION': ['EXECUTED', 'REJECTED', 'CANCELLED'],
    'EXECUTED': ['PASSED', 'REJECTED', 'CANCELLED'],
    'PASSED': [],
    'REJECTED': [],
    'CANCELLED': []
  };

  static transitionExecution(executionId: string, newStatus: ExecutionStatus): void {
    const execution = db.getExecution(executionId);
    const validTransitions = this.EXECUTION_TRANSITIONS[execution.status];

    if (!validTransitions.includes(newStatus)) {
      throw Errors.INVALID_STATE();
    }

    execution.status = newStatus;
    execution.version++;
    execution.updated_at = new Date().toISOString();
  }

  private static readonly IRB_TRANSITIONS: Record<IRBApprovalStatus, IRBApprovalStatus[]> = {
    'PENDING': ['APPROVED', 'REJECTED'],
    'APPROVED': [],
    'REJECTED': []
  };

  static transitionIRBApproval(approvalId: string, newStatus: IRBApprovalStatus): void {
    const approval = db.getIRBApproval(approvalId);
    const validTransitions = this.IRB_TRANSITIONS[approval.status];

    if (!validTransitions.includes(newStatus)) {
      throw Errors.INVALID_IRB_STATUS();
    }

    approval.status = newStatus;
    approval.version++;
    approval.updated_at = new Date().toISOString();
  }
}
