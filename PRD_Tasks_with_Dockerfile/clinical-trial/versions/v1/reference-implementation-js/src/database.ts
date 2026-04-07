import {
  ResearchProgram,
  ClinicalTrial,
  TrialPhase,
  ProtocolProcedure,
  PatientCohort,
  ProcedureExecution,
  TreatmentDependency,
  TrialPortfolio,
  IncompatibleCohortPhasePairing,
  EnrollmentBlackoutWindow,
  InstitutionalReviewBoard,
  IRBApproval,
  EthicalComplianceBudget,
  PatientSafetyRisk,
  InvestigatorReputation
} from './types';
import { generateId, now } from './utils/helpers';
import { Errors } from './utils/errors';
import { INITIAL_REPUTATION_SCORE } from './utils/constants';

class Database {
  private programs = new Map<string, ResearchProgram>();
  private trials = new Map<string, ClinicalTrial>();
  private phases = new Map<string, TrialPhase>();
  private procedures = new Map<string, ProtocolProcedure>();
  private cohorts = new Map<string, PatientCohort>();
  private executions = new Map<string, ProcedureExecution>();
  private dependencies = new Map<string, TreatmentDependency>();
  private portfolios = new Map<string, TrialPortfolio>();
  private incompatiblePairings = new Map<string, IncompatibleCohortPhasePairing>();
  private blackoutWindows = new Map<string, EnrollmentBlackoutWindow>();
  private irbs = new Map<string, InstitutionalReviewBoard>();
  private irbApprovals = new Map<string, IRBApproval>();

  private ethicalBudgets = new Map<string, EthicalComplianceBudget>();
  private safetyLedgers = new Map<string, PatientSafetyRisk>();
  private reputationLedgers = new Map<string, InvestigatorReputation>();

  private idempotencyStore = new Map<string, { resource: any; body: string }>();

  private sequenceCounters = new Map<string, number>();

  private getNextSequence(containerId: string): number {
    const current = this.sequenceCounters.get(containerId) || 0;
    const next = current + 1;
    this.sequenceCounters.set(containerId, next);
    return next;
  }

  createProgram(data: {
    name: string;
    description?: string;
  }): ResearchProgram {
    const id = generateId();
    const program: ResearchProgram = {
      id,
      name: data.name,
      description: data.description,
      current_period_index: 0,
      version: 1,
      created_seq: this.getNextSequence('global'),
      created_at: now(),
      updated_at: now()
    };
    this.programs.set(id, program);
    return program;
  }

  getProgram(id: string): ResearchProgram {
    const program = this.programs.get(id);
    if (!program) throw Errors.NOT_FOUND();
    return program;
  }

  listPrograms(): ResearchProgram[] {
    return Array.from(this.programs.values()).sort((a, b) => a.created_seq - b.created_seq);
  }

  updateProgram(id: string, updates: Partial<ResearchProgram>): ResearchProgram {
    const program = this.getProgram(id);
    Object.assign(program, updates);
    program.version++;
    program.updated_at = now();
    return program;
  }

  createTrial(data: {
    research_program_id: string;
    investigator_id: string;
    treatment_name: string;
    total_ethical_compliance_budget: number;
    portfolio_id?: string;
    irb_id: string;
  }): ClinicalTrial {
    const id = generateId();
    const trial: ClinicalTrial = {
      id,
      research_program_id: data.research_program_id,
      investigator_id: data.investigator_id,
      treatment_name: data.treatment_name,
      total_ethical_compliance_budget: data.total_ethical_compliance_budget,
      effective_ethical_compliance_budget: 0,
      ethical_compliance_balance: 0,
      patient_safety_risk: 0,
      portfolio_id: data.portfolio_id,
      is_under_contagion: false,
      deviation_penalty_tier: 0,
      irb_id: data.irb_id,
      status: 'DRAFT',
      version: 1,
      created_seq: this.getNextSequence(data.research_program_id),
      created_at: now(),
      updated_at: now()
    };
    this.trials.set(id, trial);
    return trial;
  }

  getTrial(id: string): ClinicalTrial {
    const trial = this.trials.get(id);
    if (!trial) throw Errors.TRIAL_NOT_FOUND();
    return trial;
  }

  listTrials(programId?: string): ClinicalTrial[] {
    let trials = Array.from(this.trials.values());
    if (programId) {
      trials = trials.filter(t => t.research_program_id === programId);
    }
    return trials.sort((a, b) => a.created_seq - b.created_seq);
  }

  updateTrial(id: string, updates: Partial<ClinicalTrial>): ClinicalTrial {
    const trial = this.getTrial(id);
    Object.assign(trial, updates);
    trial.version++;
    trial.updated_at = now();
    return trial;
  }

  createPhase(data: {
    trial_id: string;
    research_program_id: string;
    name: string;
  }): TrialPhase {
    const id = generateId();
    const phase: TrialPhase = {
      id,
      trial_id: data.trial_id,
      research_program_id: data.research_program_id,
      name: data.name as any,
      status: 'PENDING',
      version: 1,
      created_seq: this.getNextSequence(data.research_program_id),
      created_at: now(),
      updated_at: now()
    };
    this.phases.set(id, phase);
    return phase;
  }

  getPhase(id: string): TrialPhase {
    const phase = this.phases.get(id);
    if (!phase) throw Errors.PHASE_NOT_FOUND();
    return phase;
  }

  listPhases(trialId?: string): TrialPhase[] {
    let phases = Array.from(this.phases.values());
    if (trialId) {
      phases = phases.filter(p => p.trial_id === trialId);
    }
    return phases.sort((a, b) => a.created_seq - b.created_seq);
  }

  updatePhase(id: string, updates: Partial<TrialPhase>): TrialPhase {
    const phase = this.getPhase(id);
    Object.assign(phase, updates);
    phase.version++;
    phase.updated_at = now();
    return phase;
  }

  createProcedure(data: {
    phase_id: string;
    trial_id: string;
    research_program_id: string;
    procedure_type: string;
    required_cohort_tag: string;
    base_risk_cost: number;
    integrity_score_value: number;
  }): ProtocolProcedure {
    const id = generateId();
    const procedure: ProtocolProcedure = {
      id,
      phase_id: data.phase_id,
      trial_id: data.trial_id,
      research_program_id: data.research_program_id,
      procedure_type: data.procedure_type,
      status: 'PENDING',
      required_cohort_tag: data.required_cohort_tag as any,
      base_risk_cost: data.base_risk_cost,
      integrity_score_value: data.integrity_score_value,
      version: 1,
      created_seq: this.getNextSequence(data.research_program_id),
      created_at: now(),
      updated_at: now()
    };
    this.procedures.set(id, procedure);
    return procedure;
  }

  getProcedure(id: string): ProtocolProcedure {
    const procedure = this.procedures.get(id);
    if (!procedure) throw Errors.PROCEDURE_NOT_FOUND();
    return procedure;
  }

  listProcedures(phaseId?: string, trialId?: string): ProtocolProcedure[] {
    let procedures = Array.from(this.procedures.values());
    if (phaseId) {
      procedures = procedures.filter(p => p.phase_id === phaseId);
    }
    if (trialId) {
      procedures = procedures.filter(p => p.trial_id === trialId);
    }
    return procedures.sort((a, b) => a.created_seq - b.created_seq);
  }

  updateProcedure(id: string, updates: Partial<ProtocolProcedure>): ProtocolProcedure {
    const procedure = this.getProcedure(id);
    Object.assign(procedure, updates);
    procedure.version++;
    procedure.updated_at = now();
    return procedure;
  }

  createCohort(data: {
    trial_id: string;
    research_program_id: string;
    cohort_name: string;
    cohort_version: string;
    base_risk_points: number;
    properties: any[];
  }): PatientCohort {
    const id = generateId();
    const cohort: PatientCohort = {
      id,
      trial_id: data.trial_id,
      research_program_id: data.research_program_id,
      cohort_name: data.cohort_name,
      cohort_version: data.cohort_version,
      base_risk_points: data.base_risk_points,
      properties: data.properties.map((p: any) => ({
        property_id: generateId(),
        name: p.name,
        certified_period_index: p.certified_period_index
      })),
      version: 1,
      created_seq: this.getNextSequence(data.research_program_id),
      created_at: now(),
      updated_at: now()
    };
    this.cohorts.set(id, cohort);
    return cohort;
  }

  getCohort(id: string): PatientCohort {
    const cohort = this.cohorts.get(id);
    if (!cohort) throw Errors.COHORT_NOT_FOUND();
    return cohort;
  }

  listCohorts(trialId?: string): PatientCohort[] {
    let cohorts = Array.from(this.cohorts.values());
    if (trialId) {
      cohorts = cohorts.filter(c => c.trial_id === trialId);
    }
    return cohorts.sort((a, b) => a.created_seq - b.created_seq);
  }

  createExecution(data: {
    trial_id: string;
    research_program_id: string;
    procedure_id: string;
    cohort_id: string;
    protocol_deviation: boolean;
    proposing_user_id: string;
    provisional_risk_debit: number;
    is_expedited_review: boolean;
  }): ProcedureExecution {
    const id = generateId();
    const execution: ProcedureExecution = {
      id,
      trial_id: data.trial_id,
      research_program_id: data.research_program_id,
      procedure_id: data.procedure_id,
      cohort_id: data.cohort_id,
      status: 'PENDING_EXECUTION',
      protocol_deviation: data.protocol_deviation,
      deviation_penalty_applied: data.protocol_deviation,
      is_expedited_review: data.is_expedited_review,
      provisional_risk_debit: data.provisional_risk_debit,
      final_risk_debit: 0,
      proposing_user_id: data.proposing_user_id,
      version: 1,
      created_seq: this.getNextSequence(data.research_program_id),
      created_at: now(),
      updated_at: now()
    };
    this.executions.set(id, execution);
    return execution;
  }

  getExecution(id: string): ProcedureExecution {
    const execution = this.executions.get(id);
    if (!execution) throw Errors.EXECUTION_NOT_FOUND();
    return execution;
  }

  listExecutions(trialId?: string, programId?: string): ProcedureExecution[] {
    let executions = Array.from(this.executions.values());
    if (trialId) {
      executions = executions.filter(e => e.trial_id === trialId);
    }
    if (programId) {
      executions = executions.filter(e => e.research_program_id === programId);
    }
    return executions.sort((a, b) => a.created_seq - b.created_seq);
  }

  updateExecution(id: string, updates: Partial<ProcedureExecution>): ProcedureExecution {
    const execution = this.getExecution(id);
    Object.assign(execution, updates);
    execution.version++;
    execution.updated_at = now();
    return execution;
  }

  createDependency(data: {
    source_trial_id: string;
    dependency_trial_id: string;
    research_program_id: string;
    reason?: string;
  }): TreatmentDependency {
    const id = generateId();
    const dependency: TreatmentDependency = {
      id,
      source_trial_id: data.source_trial_id,
      dependency_trial_id: data.dependency_trial_id,
      research_program_id: data.research_program_id,
      reason: data.reason,
      version: 1,
      created_seq: this.getNextSequence(data.research_program_id),
      created_at: now(),
      updated_at: now()
    };
    this.dependencies.set(id, dependency);
    return dependency;
  }

  listDependencies(sourceTrialId?: string): TreatmentDependency[] {
    let dependencies = Array.from(this.dependencies.values());
    if (sourceTrialId) {
      dependencies = dependencies.filter(d => d.source_trial_id === sourceTrialId);
    }
    return dependencies.sort((a, b) => a.created_seq - b.created_seq);
  }

  createPortfolio(data: {
    research_program_id: string;
    name: string;
    description?: string;
    max_total_ethical_budget: number;
  }): TrialPortfolio {
    const id = generateId();
    const portfolio: TrialPortfolio = {
      id,
      research_program_id: data.research_program_id,
      name: data.name,
      description: data.description,
      max_total_ethical_budget: data.max_total_ethical_budget,
      is_risk_saturated: false,
      version: 1,
      created_seq: this.getNextSequence(data.research_program_id),
      created_at: now(),
      updated_at: now()
    };
    this.portfolios.set(id, portfolio);
    return portfolio;
  }

  getPortfolio(id: string): TrialPortfolio {
    const portfolio = this.portfolios.get(id);
    if (!portfolio) throw Errors.PORTFOLIO_NOT_FOUND();
    return portfolio;
  }

  listPortfolios(programId?: string): TrialPortfolio[] {
    let portfolios = Array.from(this.portfolios.values());
    if (programId) {
      portfolios = portfolios.filter(p => p.research_program_id === programId);
    }
    return portfolios.sort((a, b) => a.created_seq - b.created_seq);
  }

  updatePortfolio(id: string, updates: Partial<TrialPortfolio>): TrialPortfolio {
    const portfolio = this.getPortfolio(id);
    Object.assign(portfolio, updates);
    portfolio.version++;
    portfolio.updated_at = now();
    return portfolio;
  }

  createIncompatiblePairing(data: {
    research_program_id: string;
    cohort_property: string;
    phase_name: string;
    reason: string;
  }): IncompatibleCohortPhasePairing {
    const id = generateId();
    const pairing: IncompatibleCohortPhasePairing = {
      id,
      research_program_id: data.research_program_id,
      cohort_property: data.cohort_property as any,
      phase_name: data.phase_name as any,
      reason: data.reason,
      version: 1,
      created_seq: this.getNextSequence(data.research_program_id),
      created_at: now(),
      updated_at: now()
    };
    this.incompatiblePairings.set(id, pairing);
    return pairing;
  }

  getIncompatiblePairing(id: string): IncompatibleCohortPhasePairing {
    const pairing = this.incompatiblePairings.get(id);
    if (!pairing) throw Errors.PAIRING_NOT_FOUND();
    return pairing;
  }

  listIncompatiblePairings(programId?: string): IncompatibleCohortPhasePairing[] {
    let pairings = Array.from(this.incompatiblePairings.values());
    if (programId) {
      pairings = pairings.filter(p => p.research_program_id === programId);
    }
    return pairings.sort((a, b) => a.created_seq - b.created_seq);
  }

  deleteIncompatiblePairing(id: string): void {
    if (!this.incompatiblePairings.has(id)) {
      throw Errors.PAIRING_NOT_FOUND();
    }
    this.incompatiblePairings.delete(id);
  }

  createBlackoutWindow(data: {
    research_program_id: string;
    treatment_name_pattern: string;
    start_period_index: number;
    end_period_index: number;
    reason: string;
  }): EnrollmentBlackoutWindow {
    const id = generateId();
    const window: EnrollmentBlackoutWindow = {
      id,
      research_program_id: data.research_program_id,
      treatment_name_pattern: data.treatment_name_pattern,
      start_period_index: data.start_period_index,
      end_period_index: data.end_period_index,
      reason: data.reason,
      version: 1,
      created_seq: this.getNextSequence(data.research_program_id),
      created_at: now(),
      updated_at: now()
    };
    this.blackoutWindows.set(id, window);
    return window;
  }

  getBlackoutWindow(id: string): EnrollmentBlackoutWindow {
    const window = this.blackoutWindows.get(id);
    if (!window) throw Errors.BLACKOUT_WINDOW_NOT_FOUND();
    return window;
  }

  listBlackoutWindows(programId?: string): EnrollmentBlackoutWindow[] {
    let windows = Array.from(this.blackoutWindows.values());
    if (programId) {
      windows = windows.filter(w => w.research_program_id === programId);
    }
    return windows.sort((a, b) => a.created_seq - b.created_seq);
  }

  deleteBlackoutWindow(id: string): void {
    if (!this.blackoutWindows.has(id)) {
      throw Errors.BLACKOUT_WINDOW_NOT_FOUND();
    }
    this.blackoutWindows.delete(id);
  }

  createIRB(data: {
    research_program_id: string;
    name: string;
    description?: string;
  }): InstitutionalReviewBoard {
    const id = generateId();
    const irb: InstitutionalReviewBoard = {
      id,
      research_program_id: data.research_program_id,
      name: data.name,
      description: data.description,
      version: 1,
      created_seq: this.getNextSequence(data.research_program_id),
      created_at: now(),
      updated_at: now()
    };
    this.irbs.set(id, irb);
    return irb;
  }

  getIRB(id: string): InstitutionalReviewBoard {
    const irb = this.irbs.get(id);
    if (!irb) throw Errors.IRB_NOT_FOUND();
    return irb;
  }

  listIRBs(programId?: string): InstitutionalReviewBoard[] {
    let irbs = Array.from(this.irbs.values());
    if (programId) {
      irbs = irbs.filter(i => i.research_program_id === programId);
    }
    return irbs.sort((a, b) => a.created_seq - b.created_seq);
  }

  createIRBApproval(data: {
    irb_id: string;
    trial_id: string;
    research_program_id: string;
  }): IRBApproval {
    const id = generateId();
    const approval: IRBApproval = {
      id,
      irb_id: data.irb_id,
      trial_id: data.trial_id,
      research_program_id: data.research_program_id,
      status: 'PENDING',
      version: 1,
      created_seq: this.getNextSequence(data.research_program_id),
      created_at: now(),
      updated_at: now()
    };
    this.irbApprovals.set(id, approval);
    return approval;
  }

  getIRBApproval(id: string): IRBApproval {
    const approval = this.irbApprovals.get(id);
    if (!approval) throw Errors.IRB_APPROVAL_NOT_FOUND();
    return approval;
  }

  listIRBApprovals(irbId?: string, trialId?: string): IRBApproval[] {
    let approvals = Array.from(this.irbApprovals.values());
    if (irbId) {
      approvals = approvals.filter(a => a.irb_id === irbId);
    }
    if (trialId) {
      approvals = approvals.filter(a => a.trial_id === trialId);
    }
    return approvals.sort((a, b) => a.created_seq - b.created_seq);
  }

  updateIRBApproval(id: string, updates: Partial<IRBApproval>): IRBApproval {
    const approval = this.getIRBApproval(id);
    Object.assign(approval, updates);
    approval.version++;
    approval.updated_at = now();
    return approval;
  }

  getEthicalBudgetLedger(trialId: string): EthicalComplianceBudget {
    if (!this.ethicalBudgets.has(trialId)) {
      this.ethicalBudgets.set(trialId, {
        provisional_debits: 0,
        finalized_debits: 0
      });
    }
    return this.ethicalBudgets.get(trialId)!;
  }

  getSafetyLedger(trialId: string): PatientSafetyRisk {
    if (!this.safetyLedgers.has(trialId)) {
      this.safetyLedgers.set(trialId, {
        risk_score: 0
      });
    }
    return this.safetyLedgers.get(trialId)!;
  }

  getReputationLedger(programId: string, investigatorId: string): InvestigatorReputation {
    const key = `${programId}:${investigatorId}`;
    if (!this.reputationLedgers.has(key)) {
      this.reputationLedgers.set(key, {
        reputation_score: INITIAL_REPUTATION_SCORE,
        is_on_probation: false
      });
    }
    return this.reputationLedgers.get(key)!;
  }

  checkIdempotency(key: string, body: string): { found: boolean; resource?: any; conflict: boolean } {
    if (!this.idempotencyStore.has(key)) {
      return { found: false, conflict: false };
    }
    const stored = this.idempotencyStore.get(key)!;
    if (stored.body !== body) {
      return { found: true, conflict: true };
    }
    return { found: true, resource: stored.resource, conflict: false };
  }

  storeIdempotency(key: string, body: string, resource: any): void {
    this.idempotencyStore.set(key, { resource, body });
  }
}

export const db = new Database();
