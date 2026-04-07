import {
  createResearchProgram,
  createTrial,
  createIRB,
  createIRBApproval,
  approveIRB,
  activateTrial,
  completeTrial,
  abandonTrial,
  createPhase,
  createProcedure,
  createCohort,
  createExecution,
  executeExecution,
  markExecutionPassed,
  cancelExecution,
  createPortfolio,
  updatePhaseStatus,
  manualRiskAdjustment,
  initializeReputation,
  createResearchSite,
  getResearchSite,
  updateResearchProgram,
  createInvestigatorCertification,
  getTrial
} from './resources';

import {
  PHASE_NAME,
  PHASE_STATUS,
  EXPEDITED_THRESHOLD_POINTS,
  AUDIT_LOCK_THRESHOLD
} from './constants';

import {
  buildProcedureData,
  buildCohortData,
  generateInvestigatorId,
  generateUserId
} from './builders';

import type {
  ResearchProgram,
  ClinicalTrial,
  InstitutionalReviewBoard,
  IRBApproval,
  TrialPhase,
  ProtocolProcedure,
  PatientCohort,
  ProcedureExecution,
  TrialPortfolio
} from './types';

interface ActiveTrialSetup {
  program: ResearchProgram;
  trial: ClinicalTrial;
  irb: InstitutionalReviewBoard;
  approval: IRBApproval;
}

interface TrialWithPhaseSetup {
  program: ResearchProgram;
  trial: ClinicalTrial;
  phase: TrialPhase;
  irb: InstitutionalReviewBoard;
}

interface TrialWithProcedureSetup {
  program: ResearchProgram;
  trial: ClinicalTrial;
  phase: TrialPhase;
  procedure: ProtocolProcedure;
  cohort: PatientCohort;
}

interface TrialNearThresholdSetup {
  program: ResearchProgram;
  trial: ClinicalTrial;
  phase: TrialPhase;
  procedure: ProtocolProcedure;
  cohort: PatientCohort;
  execution: ProcedureExecution;
  remainingToThreshold: number;
}

interface PortfolioWithTrialsSetup {
  program: ResearchProgram;
  portfolio: TrialPortfolio;
  trials: ClinicalTrial[];
}

interface TrialWithActiveDeviationsSetup {
  program: ResearchProgram;
  trial: ClinicalTrial;
  executions: ProcedureExecution[];
}

interface CompletedExecutionSetup {
  program: ResearchProgram;
  trial: ClinicalTrial;
  phase: TrialPhase;
  procedure: ProtocolProcedure;
  cohort: PatientCohort;
  execution: ProcedureExecution;
}

interface TrialWithDependencySetup {
  program: ResearchProgram;
  dependency: ClinicalTrial;
  trial: ClinicalTrial;
  irb: InstitutionalReviewBoard;
}

interface PhaseReadyForCompletionSetup {
  program: ResearchProgram;
  trial: ClinicalTrial;
  phase: TrialPhase;
  procedures: ProtocolProcedure[];
  cohort: PatientCohort;
}

interface MultipleTrialsForInvestigatorSetup {
  program: ResearchProgram;
  investigatorId: string;
  trials: ClinicalTrial[];
}

export async function createProgramWithIRB() {
  const programResp = await createResearchProgram();
  const program = programResp.body.data;
  const irbResp = await createIRB(program.id);
  const irb = irbResp.body.data;

  return { program, irb };
}

export async function setupActiveTrial(
  overrides: Record<string, any> = {},
  userId?: string
): Promise<ActiveTrialSetup> {

  const actualUserId = userId || overrides.investigatorId || generateInvestigatorId();

  if (overrides.investigatorId) {
    delete overrides.investigatorId;
  }

  let program: ResearchProgram;
  let irb: InstitutionalReviewBoard;

  if (overrides.programId) {

    const programId = overrides.programId;
    delete overrides.programId;

    program = { id: programId } as ResearchProgram;

    irb = overrides.irbId
      ? { id: overrides.irbId } as InstitutionalReviewBoard
      : (await createIRB(programId, {}, actualUserId)).body.data;

    if (overrides.irbId) {
      delete overrides.irbId;
    }
  } else if (overrides.program) {

    program = overrides.program;
    delete overrides.program;

    irb = overrides.irb
      ? overrides.irb
      : (await createIRB(program.id, {}, actualUserId)).body.data;

    if (overrides.irb) {
      delete overrides.irb;
    }
  } else {

    const programResp = await createResearchProgram({}, actualUserId);
    if (programResp.status !== 201) {
      throw new Error(`Setup failed: createResearchProgram returned ${programResp.status}`);
    }
    program = programResp.body.data;

    const irbResp = await createIRB(program.id, {}, actualUserId);
    if (irbResp.status !== 201) {
      throw new Error(`Setup failed: createIRB returned ${irbResp.status}`);
    }
    irb = irbResp.body.data;
  }

  const trialResp = await createTrial(program.id, {
    irb_id: irb.id,
    ...overrides
  }, actualUserId);
  if (trialResp.status !== 201) {
    throw new Error(`Setup failed: createTrial returned ${trialResp.status}`);
  }
  const trial = trialResp.body.data;

  const approvalResp = await createIRBApproval(program.id, irb.id, trial.id, actualUserId);
  if (approvalResp.status !== 201) {
    throw new Error(`Setup failed: createIRBApproval returned ${approvalResp.status}`);
  }
  const approval = approvalResp.body.data;

  const approveResp = await approveIRB(program.id, irb.id, approval.id, approval.version, actualUserId);
  if (approveResp.status !== 200) {
    throw new Error(`Setup failed: approveIRB returned ${approveResp.status}`);
  }

  const activateResp = await activateTrial(program.id, trial.id, actualUserId);
  if (activateResp.status !== 200) {
    throw new Error(`Setup failed: activateTrial returned ${activateResp.status}`);
  }
  const activatedTrial = activateResp.body.data;

  return { program, trial: activatedTrial, irb, approval };
}

export async function setupTrialWithPhase(
  phaseName: string = PHASE_NAME.PHASE_I,
  userId?: string
): Promise<TrialWithPhaseSetup> {
  const actualUserId = userId || generateInvestigatorId();
  const { program, trial, irb } = await setupActiveTrial({}, actualUserId);

  const phaseResp = await createPhase(program.id, trial.id, phaseName, {}, actualUserId);
  if (phaseResp.status !== 201) {
    throw new Error(`Setup failed: createPhase returned ${phaseResp.status}`);
  }
  const phase = phaseResp.body.data;

  return { program, trial, phase, irb };
}

export async function setupTrialWithProcedure(
  procedureData: Record<string, any> = {},
  userId?: string
): Promise<TrialWithProcedureSetup> {
  const actualUserId = userId || generateInvestigatorId();
  const { program, trial, phase } = await setupTrialWithPhase(PHASE_NAME.PHASE_I, actualUserId);

  const procedureResp = await createProcedure(
    program.id,
    trial.id,
    phase.id,
    buildProcedureData(procedureData),
    actualUserId
  );
  if (procedureResp.status !== 201) {
    throw new Error(`Setup failed: createProcedure returned ${procedureResp.status}`);
  }
  const procedure = procedureResp.body.data;

  const cohortResponse = await createCohort(program.id, trial.id, buildCohortData(), actualUserId);
  const cohort = cohortResponse.body.data;

  return { program, trial, phase, procedure, cohort };
}

export async function setupTrialNearExpeditedThreshold(
  remainingPoints: number = 10,
  userId?: string
): Promise<TrialNearThresholdSetup> {
  const actualUserId = userId || generateInvestigatorId();
  const targetRisk = EXPEDITED_THRESHOLD_POINTS - remainingPoints;

  const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure({
    base_risk_cost: targetRisk
  }, actualUserId);

  const execResponse = await createExecution(
    program.id,
    trial.id,
    {
      procedure_id: procedure.id,
      cohort_id: cohort.id,
      protocol_deviation: true
    },
    actualUserId
  );

  const execution = execResponse.body.data;

  return {
    program,
    trial,
    phase,
    procedure,
    cohort,
    execution,
    remainingToThreshold: remainingPoints
  };
}

export async function setupPortfolioWithTrials(
  trialCount: number = 3,
  userId?: string
): Promise<PortfolioWithTrialsSetup> {
  const actualUserId = userId || generateInvestigatorId();

  const programResp = await createResearchProgram({}, actualUserId);
  if (programResp.status !== 201) {
    throw new Error(`Setup failed: createResearchProgram returned ${programResp.status}`);
  }
  const program = programResp.body.data;

  const portfolioResp = await createPortfolio(program.id, {}, actualUserId);
  if (portfolioResp.status !== 201) {
    throw new Error(`Setup failed: createPortfolio returned ${portfolioResp.status}`);
  }
  const portfolio = portfolioResp.body.data;

  const trials: ClinicalTrial[] = [];
  for (let i = 0; i < trialCount; i++) {

    const trialUserId = generateInvestigatorId();

    const irbResp = await createIRB(program.id, {}, actualUserId);
    if (irbResp.status !== 201) {
      throw new Error(`Setup failed: createIRB returned ${irbResp.status}`);
    }
    const irb = irbResp.body.data;

    const trialResp = await createTrial(program.id, {
      portfolio_id: portfolio.id,
      irb_id: irb.id
    }, trialUserId);
    if (trialResp.status !== 201) {
      throw new Error(`Setup failed: createTrial returned ${trialResp.status}`);
    }
    const trial = trialResp.body.data;

    const approvalResp = await createIRBApproval(program.id, irb.id, trial.id, actualUserId);
    if (approvalResp.status !== 201) {
      throw new Error(`Setup failed: createIRBApproval returned ${approvalResp.status}`);
    }
    const approval = approvalResp.body.data;

    const approveResp = await approveIRB(program.id, irb.id, approval.id, approval.version, actualUserId);
    if (approveResp.status !== 200) {
      throw new Error(`Setup failed: approveIRB returned ${approveResp.status}`);
    }

    const activateResponse = await activateTrial(program.id, trial.id, actualUserId);
    if (activateResponse.status !== 200) {
      throw new Error(`Setup failed: activateTrial returned ${activateResponse.status}`);
    }
    trials.push(activateResponse.body.data);
  }

  return { program, portfolio, trials };
}

export async function setupTrialWithActiveDeviations(
  deviationCount: number = 3,
  userId?: string
): Promise<TrialWithActiveDeviationsSetup> {
  const actualUserId = userId || generateInvestigatorId();
  const { program, trial, phase } = await setupTrialWithPhase(PHASE_NAME.PHASE_I, actualUserId);

  const cohortResponse = await createCohort(program.id, trial.id, buildCohortData(), actualUserId);
  const cohort = cohortResponse.body.data;

  const executions: ProcedureExecution[] = [];
  for (let i = 0; i < deviationCount; i++) {
    const procedureResp = await createProcedure(
      program.id,
      trial.id,
      phase.id,
      buildProcedureData({ base_risk_cost: 50 }),
      actualUserId
    );
    if (procedureResp.status !== 201) {
      throw new Error(`Setup failed: createProcedure returned ${procedureResp.status}`);
    }
    const procedure = procedureResp.body.data;

    const execResponse = await createExecution(
      program.id,
      trial.id,
      {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: true
      },
      actualUserId
    );

    executions.push(execResponse.body.data);
  }

  return { program, trial, executions };
}

export async function setupCompletedExecution(
  protocolDeviation: boolean = true,
  userId?: string
): Promise<CompletedExecutionSetup> {
  const actualUserId = userId || generateInvestigatorId();
  const { program, trial, phase, procedure, cohort } = await setupTrialWithProcedure({}, actualUserId);

  const execResponse = await createExecution(
    program.id,
    trial.id,
    {
      procedure_id: procedure.id,
      cohort_id: cohort.id,
      protocol_deviation: protocolDeviation
    },
    actualUserId
  );

  const execution = execResponse.body.data;

  await executeExecution(program.id, trial.id, execution.id, actualUserId);

  const passedResponse = await markExecutionPassed(program.id, trial.id, execution.id, actualUserId);

  return {
    program,
    trial,
    phase,
    procedure,
    cohort,
    execution: passedResponse.body.data
  };
}

export async function setupTrialWithDependency(
  userId?: string
): Promise<TrialWithDependencySetup> {
  const actualUserId = userId || generateInvestigatorId();

  const programResp = await createResearchProgram({}, actualUserId);
  if (programResp.status !== 201) {
    throw new Error(`Setup failed: createResearchProgram returned ${programResp.status}`);
  }
  const program = programResp.body.data;

  const irbResp = await createIRB(program.id, {}, actualUserId);
  if (irbResp.status !== 201) {
    throw new Error(`Setup failed: createIRB returned ${irbResp.status}`);
  }
  const irb = irbResp.body.data;

  const depUserId = generateInvestigatorId();
  const depTrialResp = await createTrial(program.id, { irb_id: irb.id }, depUserId);
  if (depTrialResp.status !== 201) {
    throw new Error(`Setup failed: createTrial returned ${depTrialResp.status}`);
  }
  const depTrial = depTrialResp.body.data;

  const depApprovalResp = await createIRBApproval(program.id, irb.id, depTrial.id, actualUserId);
  if (depApprovalResp.status !== 201) {
    throw new Error(`Setup failed: createIRBApproval returned ${depApprovalResp.status}`);
  }
  const depApproval = depApprovalResp.body.data;

  const approveDepResp = await approveIRB(program.id, irb.id, depApproval.id, depApproval.version, actualUserId);
  if (approveDepResp.status !== 200) {
    throw new Error(`Setup failed: approveIRB returned ${approveDepResp.status}`);
  }

  const mainUserId = generateInvestigatorId();
  const trialResp = await createTrial(program.id, { irb_id: irb.id }, mainUserId);
  if (trialResp.status !== 201) {
    throw new Error(`Setup failed: createTrial returned ${trialResp.status}`);
  }
  const trial = trialResp.body.data;

  return { program, dependency: depTrial, trial, irb };
}

export async function setupPhaseReadyForCompletion(
  procedureCount: number = 2,
  userId?: string
): Promise<PhaseReadyForCompletionSetup> {
  const actualUserId = userId || generateInvestigatorId();
  const { program, trial, phase } = await setupTrialWithPhase(PHASE_NAME.PHASE_I, actualUserId);
  const cohortResponse = await createCohort(program.id, trial.id, buildCohortData(), actualUserId);
  const cohort = cohortResponse.body.data;

  const procedures: ProtocolProcedure[] = [];

  for (let i = 0; i < procedureCount; i++) {
    const procedureResp = await createProcedure(
      program.id,
      trial.id,
      phase.id,
      buildProcedureData({ base_risk_cost: 10 }),
      actualUserId
    );
    if (procedureResp.status !== 201) {
      throw new Error(`Setup failed: createProcedure returned ${procedureResp.status}`);
    }
    const procedure = procedureResp.body.data;

    procedures.push(procedure);

    const execResponse = await createExecution(
      program.id,
      trial.id,
      {
        procedure_id: procedure.id,
        cohort_id: cohort.id,
        protocol_deviation: false
      },
      actualUserId
    );

    const execution = execResponse.body.data;
    const execResp = await executeExecution(program.id, trial.id, execution.id, actualUserId);
    if (execResp.status !== 200) {
      throw new Error(`Setup failed: executeExecution returned ${execResp.status}`);
    }

    const passResp = await markExecutionPassed(program.id, trial.id, execution.id, actualUserId);
    if (passResp.status !== 200) {
      throw new Error(`Setup failed: markExecutionPassed returned ${passResp.status}`);
    }
  }

  await updatePhaseStatus(
    program.id,
    trial.id,
    phase.id,
    PHASE_STATUS.READY_FOR_PROCEDURES,
    phase.version,
    actualUserId
  );

  return { program, trial, phase, procedures, cohort };
}

export async function setupMultipleTrialsForInvestigator(
  trialCount: number = 2,
  userId?: string
): Promise<MultipleTrialsForInvestigatorSetup> {

  const investigatorId = userId || generateInvestigatorId();

  const programResp = await createResearchProgram({}, investigatorId);
  if (programResp.status !== 201) {
    throw new Error(`Setup failed: createResearchProgram returned ${programResp.status}`);
  }
  const program = programResp.body.data;

  const trials: ClinicalTrial[] = [];
  for (let i = 0; i < trialCount; i++) {

    const { trial } = await setupActiveTrial({ program }, investigatorId);

    trials.push(trial);
  }

  return { program, investigatorId, trials };
}

export async function forceTrialIntoLock(
  programId: string,
  trialId: string,
  userId?: string
): Promise<void> {
  const actualUserId = userId || generateInvestigatorId();
  const resp = await manualRiskAdjustment(
    programId,
    trialId,
    AUDIT_LOCK_THRESHOLD + 10,
    'Force lock for test',
    actualUserId
  );
  if (resp.status !== 200) {
    throw new Error(`Failed to lock trial: ${resp.status}`);
  }
}

export async function triggerPhaseReviewRequired(
  programId: string,
  trialId: string,
  phaseId: string,
  cohortId: string,
  userId?: string
): Promise<void> {
  const actualUserId = userId || generateInvestigatorId();

  for (let i = 0; i < 3; i++) {
    const procResp = await createProcedure(programId, trialId, phaseId, { base_risk_cost: 50 }, actualUserId);
    if (procResp.status !== 201) {
      throw new Error(`Failed to create procedure for review trigger: ${procResp.status}`);
    }
    const proc = procResp.body.data;

    const execResp = await createExecution(programId, trialId, {
      procedure_id: proc.id,
      cohort_id: cohortId,
      protocol_deviation: true
    }, actualUserId);
    if (execResp.status !== 201) {
      throw new Error(`Failed to create execution for review trigger: ${execResp.status}`);
    }

    const cancelResp = await cancelExecution(programId, trialId, execResp.body.data.id, actualUserId);
    if (cancelResp.status !== 200) {
      throw new Error(`Failed to cancel execution for review trigger: ${cancelResp.status}`);
    }
  }
}

export async function setupCompletedTrial(
  programId: string,
  irbId: string,
  data: Partial<{
    treatment_name?: string;
    total_ethical_compliance_budget?: number;
    portfolio_id?: string;
  }> = {},
  userId?: string
): Promise<ClinicalTrial> {
  const actualUserId = userId || generateInvestigatorId();

  const trialResp = await createTrial(programId, { irb_id: irbId, ...data }, actualUserId);
  if (trialResp.status !== 201) {
    throw new Error(`Setup failed: createTrial returned ${trialResp.status}`);
  }
  const trial = trialResp.body.data;

  const approvalResp = await createIRBApproval(programId, irbId, trial.id, actualUserId);
  if (approvalResp.status !== 201) {
    throw new Error(`Setup failed: createIRBApproval returned ${approvalResp.status}`);
  }
  const approval = approvalResp.body.data;

  const approveResp = await approveIRB(programId, irbId, approval.id, approval.version, actualUserId);
  if (approveResp.status !== 200) {
    throw new Error(`Setup failed: approveIRB returned ${approveResp.status}`);
  }

  const activateResp = await activateTrial(programId, trial.id, actualUserId);
  if (activateResp.status !== 200) {
    throw new Error(`Setup failed: activateTrial returned ${activateResp.status}`);
  }

  const completeResp = await completeTrial(programId, trial.id, actualUserId);
  if (completeResp.status !== 200) {
    throw new Error(`Setup failed: completeTrial returned ${completeResp.status}`);
  }

  return completeResp.body.data;
}

export async function executeAndPassProcedure(
  programId: string,
  trialId: string,
  procedureId: string,
  cohortId: string,
  protocolDeviation: boolean = false,
  userId?: string
): Promise<void> {
  const actualUserId = userId || generateInvestigatorId();

  const execResp = await createExecution(programId, trialId, {
    procedure_id: procedureId,
    cohort_id: cohortId,
    protocol_deviation: protocolDeviation
  }, actualUserId);
  if (execResp.status !== 201) {
    throw new Error(`Failed to create execution: ${execResp.status}`);
  }

  const executeResp = await executeExecution(programId, trialId, execResp.body.data.id, actualUserId);
  if (executeResp.status !== 200) {
    throw new Error(`Failed to execute: ${executeResp.status}`);
  }

  const passResp = await markExecutionPassed(programId, trialId, execResp.body.data.id, actualUserId);
  if (passResp.status !== 200) {
    throw new Error(`Failed to pass: ${passResp.status}`);
  }
}

export async function driveInvestigatorIntoProbation(
  programId: string,
  irbId: string,
  investigatorId: string,
  targetReputation: number = 30
): Promise<void> {

  const abandonmentsNeeded = Math.ceil((100 - targetReputation) / 10);

  for (let i = 0; i < abandonmentsNeeded; i++) {
    const trialResp = await createTrial(programId, {
      irb_id: irbId,
      total_ethical_compliance_budget: 400
    }, investigatorId);

    if (trialResp.status !== 201) {
      throw new Error(`Failed to create trial for probation: ${trialResp.status}`);
    }
    const trial = trialResp.body.data;

    const approvalResp = await createIRBApproval(programId, irbId, trial.id);
    if (approvalResp.status !== 201) {
      throw new Error(`Failed to create approval: ${approvalResp.status}`);
    }
    const approval = approvalResp.body.data;

    const approveResp = await approveIRB(programId, irbId, approval.id, approval.version);
    if (approveResp.status !== 200) {
      throw new Error(`Failed to approve: ${approveResp.status}`);
    }

    const activateResp = await activateTrial(programId, trial.id);
    if (activateResp.status !== 200) {
      throw new Error(`Failed to activate: ${activateResp.status}`);
    }

    const abandonResp = await abandonTrial(programId, trial.id);
    if (abandonResp.status !== 200) {
      throw new Error(`Failed to abandon: ${abandonResp.status}`);
    }
  }
}

export async function setupPhaseWithProcedureAndCohort(
  programId: string,
  trialId: string,
  phaseName: string = PHASE_NAME.PHASE_I,
  procedureData: Partial<any> = {},
  userId?: string
): Promise<{ phase: TrialPhase; procedure: ProtocolProcedure; cohort: PatientCohort }> {
  const actualUserId = userId || generateInvestigatorId();

  const phaseResp = await createPhase(programId, trialId, phaseName, {}, actualUserId);
  if (phaseResp.status !== 201) {
    throw new Error(`Setup failed: createPhase returned ${phaseResp.status}`);
  }
  const phase = phaseResp.body.data;

  const procedureResp = await createProcedure(programId, trialId, phase.id, buildProcedureData(procedureData), actualUserId);
  if (procedureResp.status !== 201) {
    throw new Error(`Setup failed: createProcedure returned ${procedureResp.status}`);
  }
  const procedure = procedureResp.body.data;

  const cohortResponse = await createCohort(programId, trialId, buildCohortData(), actualUserId);
  const cohort = cohortResponse.body.data;

  return { phase, procedure, cohort };
}

export async function driveReputationToTarget(
  programId: string,
  investigatorId: string,
  targetReputation: number,
  userId?: string
): Promise<void> {
  const actualUserId = userId || investigatorId;

  const initResp = await initializeReputation(programId, investigatorId, actualUserId);
  if (initResp.status !== 200 && initResp.status !== 201) {
    throw new Error(`Failed to initialize reputation: ${initResp.status}`);
  }

  const currentRep = initResp.body.data.reputation_score;
  const reputationDelta = currentRep - targetReputation;

  if (reputationDelta <= 0) {
    return;
  }

  const abandonsNeeded = Math.max(1, Math.floor(reputationDelta / 10));

  for (let i = 0; i < abandonsNeeded; i++) {
    const irbResp = await createIRB(programId, {}, actualUserId);
    if (irbResp.status !== 201) throw new Error(`Setup failed: createIRB`);
    const irb = irbResp.body.data;

    const trialResp = await createTrial(programId, {
      irb_id: irb.id,
      total_ethical_compliance_budget: 400
    }, investigatorId);
    if (trialResp.status !== 201) throw new Error(`Setup failed: createTrial`);
    const trial = trialResp.body.data;

    const approvalResp = await createIRBApproval(programId, irb.id, trial.id, actualUserId);
    if (approvalResp.status !== 201) throw new Error(`Setup failed`);

    const approveResp = await approveIRB(programId, irb.id, approvalResp.body.data.id, approvalResp.body.data.version, actualUserId);
    if (approveResp.status !== 200) throw new Error(`Setup failed`);

    const activateResp = await activateTrial(programId, trial.id, actualUserId);
    if (activateResp.status !== 200) throw new Error(`Setup failed`);

    const abandonResp = await abandonTrial(programId, trial.id, actualUserId);
    if (abandonResp.status !== 200) throw new Error(`Setup failed`);
  }
}

export async function triggerPhaseReview(
  programId: string,
  trialId: string,
  phaseId: string,
  procedureId: string,
  cohortId: string,
  userId?: string
): Promise<void> {
  const actualUserId = userId || generateInvestigatorId();

  for (let i = 0; i < 3; i++) {

    const procResp = await createProcedure(programId, trialId, phaseId, { base_risk_cost: 50 }, actualUserId);
    if (procResp.status !== 201) {
      throw new Error(`Failed to create procedure for review trigger: ${procResp.status}`);
    }
    const proc = procResp.body.data;

    const execResp = await createExecution(programId, trialId, {
      procedure_id: proc.id,
      cohort_id: cohortId,
      protocol_deviation: true
    }, actualUserId);
    if (execResp.status !== 201) {
      throw new Error(`Failed to create execution for review trigger: ${execResp.status}`);
    }

    const cancelResp = await cancelExecution(programId, trialId, execResp.body.data.id, actualUserId);
    if (cancelResp.status !== 200) {
      throw new Error(`Failed to cancel execution for review trigger: ${cancelResp.status}`);
    }
  }
}

export async function approveAndActivateTrial(
  programId: string,
  irbId: string,
  trialId: string,
  userId: string = generateInvestigatorId()
): Promise<void> {
  const approvalResp = await createIRBApproval(programId, irbId, trialId, userId);
  if (approvalResp.status !== 201) {
    throw new Error(`approveAndActivateTrial: Failed to create IRB approval - ${approvalResp.status}`);
  }
  const approval = approvalResp.body.data;

  const approveResp = await approveIRB(programId, irbId, approval.id, approval.version, userId);
  if (approveResp.status !== 200) {
    throw new Error(`approveAndActivateTrial: Failed to approve IRB - ${approveResp.status}`);
  }

  const activateResp = await activateTrial(programId, trialId, userId);
  if (activateResp.status !== 200) {
    throw new Error(`approveAndActivateTrial: Failed to activate trial - ${activateResp.status}`);
  }
}

export async function completePhase(
  programId: string,
  trialId: string,
  phaseId: string,
  phaseVersion: number,
  userId: string = generateUserId()
): Promise<void> {

  const readyResp = await updatePhaseStatus(programId, trialId, phaseId, 'READY_FOR_PROCEDURES', phaseVersion, userId);
  if (readyResp.status !== 200) {
    throw new Error(`completePhase: Failed to set READY_FOR_PROCEDURES - ${readyResp.status}`);
  }

  const completeResp = await updatePhaseStatus(programId, trialId, phaseId, 'COMPLETED', readyResp.body.data.version, userId);
  if (completeResp.status !== 200) {
    throw new Error(`completePhase: Failed to set COMPLETED - ${completeResp.status}`);
  }
}

export async function createTrialWithOperationalBudget(
  programId: string,
  irbId: string,
  config: {
    total_operational_budget: number;
    total_ethical_compliance_budget?: number;
    site_id?: string;
    investigatorId?: string;
  }
): Promise<any> {
  const trialResp = await createTrial(programId, {
    irb_id: irbId,
    total_operational_budget: config.total_operational_budget,
    total_ethical_compliance_budget: config.total_ethical_compliance_budget ?? 1000,
    site_id: config.site_id
  }, config.investigatorId || generateInvestigatorId());

  if (trialResp.status !== 201) {
    throw new Error(`Failed to create trial with operational budget: ${trialResp.status}`);
  }

  return trialResp.body.data;
}

export async function createSiteWithCapacity(
  programId: string,
  maxActiveTrials: number
): Promise<string> {
  const siteResp = await createResearchSite(programId, { max_active_trials: maxActiveTrials });

  if (siteResp.status !== 201) {
    throw new Error(`Failed to create site: ${siteResp.status}`);
  }

  return siteResp.body.data.id;
}

export async function fillSiteToCapacity(
  programId: string,
  siteId: string,
  irbId: string,
  maxActiveTrials: number
): Promise<string[]> {
  const trialIds: string[] = [];

  for (let i = 0; i < maxActiveTrials; i++) {
    const trialResp = await createTrial(programId, {
      irb_id: irbId,
      site_id: siteId
    });

    if (trialResp.status !== 201) {
      throw new Error(`Failed to create trial ${i}: ${trialResp.status}`);
    }

    const trial = trialResp.body.data;
    trialIds.push(trial.id);

    await approveAndActivateTrial(programId, irbId, trial.id);
  }

  return trialIds;
}

export async function grantCertification(
  programId: string,
  investigatorId: string,
  certificationName: string
): Promise<string> {
  const certResp = await createInvestigatorCertification(
    programId,
    investigatorId,
    { certification_name: certificationName }
  );

  if (certResp.status !== 201) {
    throw new Error(`Failed to grant certification: ${certResp.status}`);
  }

  return certResp.body.data.id;
}

export async function createIntegrityProcedure(
  programId: string,
  trialId: string,
  phaseId: string,
  config?: {
    integrity_score_value?: number;
    operational_cost?: number;
    required_certification_id?: string;
  }
): Promise<any> {
  const procResp = await createProcedure(programId, trialId, phaseId, {
    is_integrity_procedure: true,
    integrity_score_value: config?.integrity_score_value ?? 10,
    operational_cost: config?.operational_cost ?? 0,
    required_certification_id: config?.required_certification_id
  });

  if (procResp.status !== 201) {
    throw new Error(`Failed to create integrity procedure: ${procResp.status}`);
  }

  return procResp.body.data;
}

export async function causeSuspensionViaOverdraft(
  programId: string,
  trialId: string,
  phaseId: string
): Promise<void> {

  const trialResp = await getTrial(programId, trialId);
  const trial = trialResp.body.data;

  const operationalBalance = trial.operational_balance;

  const overdraftCost = operationalBalance + 100;

  const procResp = await createProcedure(programId, trialId, phaseId, {
    operational_cost: overdraftCost
  });

  if (procResp.status !== 201) {
    throw new Error(`Failed to create procedure: ${procResp.status}`);
  }

  const proc = procResp.body.data;

  const cohortResp = await createCohort(programId, trialId);
  if (cohortResp.status !== 201) {
    throw new Error(`Failed to create cohort: ${cohortResp.status}`);
  }
  const cohort = cohortResp.body.data;

  const execResp = await createExecution(programId, trialId, {
    procedure_id: proc.id,
    cohort_id: cohort.id,
    protocol_deviation: false
  });

  if (execResp.status !== 201) {
    throw new Error(`Failed to create execution: ${execResp.status}`);
  }

  const execution = execResp.body.data;

  await executeExecution(programId, trialId, execution.id);
  await markExecutionPassed(programId, trialId, execution.id);

}

export async function fillInvestigatorToCapacity(
  programId: string,
  investigatorId: string,
  irbId: string,
  limit: number
): Promise<string[]> {

  const updateResp = await updateResearchProgram(programId, {
    max_active_trials_per_investigator: limit
  });

  if (updateResp.status !== 200) {
    throw new Error(`Failed to set investigator cap: ${updateResp.status}`);
  }

  const trialIds: string[] = [];

  for (let i = 0; i < limit; i++) {
    const trialResp = await createTrial(programId, { irb_id: irbId }, investigatorId);

    if (trialResp.status !== 201) {
      throw new Error(`Failed to create trial ${i}: ${trialResp.status}`);
    }

    const trial = trialResp.body.data;
    trialIds.push(trial.id);

    await approveAndActivateTrial(programId, irbId, trial.id, investigatorId);
  }

  return trialIds;
}

export async function createProgramWithIRBLockPolicy(
  locksOnRejection: boolean = true
): Promise<{ program: any; irb: any }> {
  const programResp = await createResearchProgram();
  if (programResp.status !== 201) {
    throw new Error('Failed to create program');
  }
  const program = programResp.body.data;

  const irbResp = await createIRB(program.id, {
    name: 'IRB with Lock Policy',
    locks_on_rejection: locksOnRejection
  });

  if (irbResp.status !== 201) {
    throw new Error('Failed to create IRB');
  }
  const irb = irbResp.body.data;

  return { program, irb };
}

export async function createCompleteTrialSetup(config: {
  total_operational_budget?: number;
  total_ethical_compliance_budget?: number;
  max_site_capacity?: number;
  investigatorId?: string;
}): Promise<{
  program: any;
  irb: any;
  site: any;
  trial: any;
  investigatorId: string;
}> {
  const programResp = await createResearchProgram();
  if (programResp.status !== 201) {
    throw new Error('Failed to create program');
  }
  const program = programResp.body.data;

  const irbResp = await createIRB(program.id);
  if (irbResp.status !== 201) {
    throw new Error('Failed to create IRB');
  }
  const irb = irbResp.body.data;

  const siteId = config.max_site_capacity
    ? await createSiteWithCapacity(program.id, config.max_site_capacity)
    : undefined;

  const site = siteId ? (await getResearchSite(program.id, siteId)).body.data : null;

  const investigatorId = config.investigatorId || generateInvestigatorId();

  const trialResp = await createTrial(program.id, {
    irb_id: irb.id,
    total_operational_budget: config.total_operational_budget ?? 0,
    total_ethical_compliance_budget: config.total_ethical_compliance_budget ?? 1000,
    site_id: siteId
  }, investigatorId);

  if (trialResp.status !== 201) {
    throw new Error('Failed to create trial');
  }
  const trial = trialResp.body.data;

  return { program, irb, site, trial, investigatorId };
}
