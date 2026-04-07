import { v4 as uuidv4 } from 'uuid';
import {
  UrbanRenewalProject,
  RenovationPhase,
  WorkOrder,
  RenovationCrew,
  CrewContract,
  CrewConflictPairing,
  CrewContractPayload,
  Specialization,
  RenovationPhaseStatus,
} from './types';
import { createScheduleHour, addHours, buildAuthHeaders, ApiHeaders } from './utils';
import { getSuccessData } from './validators';
import { apiClient } from './api-client';

const DEFAULTS = {
  PROJECT_NAME: 'Test Project',
  RENOVATION_BUDGET: 500000.0,
  PHASE_NAME: 'Test Renovation Phase',
  WORK_ORDER_TASK_TYPE: 'Test Task',
  CREW_NAME: 'Test Crew',
  COMPANY_NAME: 'Test Company Inc.',
  HOURLY_RATE: 100.0,
  WORK_ORDER_DURATION_HOURS: 8,
  PHASE_DURATION_HOURS: 160,
};

export function createProjectPayload(
  overrides: Partial<{ project_name: string; renovation_budget: number }> = {}
): { project_name: string; renovation_budget: number } {
  return {
    project_name: DEFAULTS.PROJECT_NAME,
    renovation_budget: DEFAULTS.RENOVATION_BUDGET,
    ...overrides,
  };
}

export function createPhasePayload(
  overrides: Partial<{ name: string; start_hour: number; end_hour: number }> = {}
): { name: string; start_hour: number; end_hour: number } {
  const startHour = createScheduleHour(10);
  const endHour = addHours(startHour, DEFAULTS.PHASE_DURATION_HOURS);

  return {
    name: DEFAULTS.PHASE_NAME,
    start_hour: startHour,
    end_hour: endHour,
    ...overrides,
  };
}

export function createWorkOrderPayload(
  overrides: Partial<{ task_type: string; required_specialization: Specialization; required_safety_clearance_level: number; start_hour: number; end_hour: number }> = {}
): { task_type: string; required_specialization: Specialization; required_safety_clearance_level: number; start_hour: number; end_hour: number } {
  const startHour = createScheduleHour(10);
  const endHour = addHours(startHour, DEFAULTS.WORK_ORDER_DURATION_HOURS);

  return {
    task_type: DEFAULTS.WORK_ORDER_TASK_TYPE,
    required_specialization: Specialization.GENERAL,
    required_safety_clearance_level: 1,
    start_hour: Math.floor(startHour),
    end_hour: Math.floor(endHour),
    ...overrides,
  };
}

export function createCrewPayload(
  overrides: Partial<{ crew_name: string; company_name: string; hourly_rate: number }> = {}
): { crew_name: string; company_name: string; hourly_rate: number } {
  return {
    crew_name: DEFAULTS.CREW_NAME,
    company_name: DEFAULTS.COMPANY_NAME,
    hourly_rate: DEFAULTS.HOURLY_RATE,
    ...overrides,
  };
}

export function createCrewCertificationPayload(
  specialization_name: Specialization,
  clearance_level: number = 1
): { specialization_name: string; clearance_level: number } {
  return {
    specialization_name,
    clearance_level,
  };
}

export function createContractPayload(
  workOrderId: string,
  crewId: string,
  overrides: Partial<CrewContractPayload> = {}
): CrewContractPayload {
  return {
    work_order_id: workOrderId,
    crew_id: crewId,
    permit_waiver_used: false,
    ...overrides,
  };
}

export function createCrewConflictPairingPayload(
  crewId1: string,
  crewId2: string,
  overrides: Partial<{ crew_id_1: string; crew_id_2: string; reason?: string }> = {}
): { crew_id_1: string; crew_id_2: string; reason?: string } {
  return {
    crew_id_1: crewId1,
    crew_id_2: crewId2,
    reason: 'Test conflict reason',
    ...overrides,
  };
}

export async function createAndActivateProject(
  budget: number = DEFAULTS.RENOVATION_BUDGET,
  projectName: string = DEFAULTS.PROJECT_NAME
): Promise<UrbanRenewalProject> {
  const authHeaders = buildAuthHeaders('test-user');
  const projectRes = await apiClient.createProject(
    createProjectPayload({ renovation_budget: budget, project_name: projectName }),
    authHeaders
  );
  const project = getSuccessData<UrbanRenewalProject>(projectRes);

  await apiClient.beginWork(project.id, authHeaders);
  return project;
}

export async function setupBasicScenario() {
  const project = await createAndActivateProject();
  const authHeaders = buildAuthHeaders('test-user');

  const phaseRes = await apiClient.createPhase(project.id, createPhasePayload({}), authHeaders);
  const phase = getSuccessData<RenovationPhase>(phaseRes);

  const crewRes = await apiClient.createCrew(project.id, createCrewPayload({}), authHeaders);
  const crew = getSuccessData<RenovationCrew>(crewRes);

  const workOrderRes = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({}), authHeaders);
  const workOrder = getSuccessData<WorkOrder>(workOrderRes);

  return { project, phase, crew, workOrder };
}

export async function setupScenarioWithContractedWorkOrder() {
  const { project, phase, crew } = await setupBasicScenario();
  const workOrder = await createWorkOrderInPhase(project.id, phase.id);
  const contract = await createAndVerifyContract(project.id, workOrder.id, crew.id);
  await apiClient.scheduleWork(project.id, contract.id, buildAuthHeaders('test-user'));
  return { project, phase, crew, workOrder, contract };
}

export async function createAndScheduleWorkOrder(
  projectId: string,
  phaseId: string,
  crewId: string,
  workOrderData: Partial<{ task_type: string; required_specialization: Specialization; required_safety_clearance_level: number; start_hour: number; end_hour: number }>
) {
  const authHeaders = buildAuthHeaders('test-user');

  const workOrderRes = await apiClient.createWorkOrder(
    projectId,
    phaseId,
    createWorkOrderPayload(workOrderData),
    authHeaders
  );
  const workOrder = getSuccessData<WorkOrder>(workOrderRes);

  const contractRes = await apiClient.createContract(
    projectId,
    createContractPayload(workOrder.id, crewId),
    authHeaders
  );
  const contract = getSuccessData<CrewContract>(contractRes);

  await apiClient.verifySpecialization(projectId, contract.id, authHeaders);
  await apiClient.scheduleWork(projectId, contract.id, authHeaders);

  return workOrder;
}

export async function createAndConfirmContract(
  projectId: string,
  phaseId: string,
  crewId: string,
  workOrderOverrides: Partial<{ task_type: string; required_specialization: Specialization; required_safety_clearance_level: number; start_hour: number; end_hour: number }>,
  existingWorkOrder?: WorkOrder,
  contractOverrides: Partial<CrewContractPayload> = {}
): Promise<{ workOrder: WorkOrder; contract: CrewContract }> {
  const authHeaders = buildAuthHeaders('test-user');
  let workOrder: WorkOrder;

  if (existingWorkOrder) {
    workOrder = existingWorkOrder;
  } else {
    const workOrderRes = await apiClient.createWorkOrder(
      projectId,
      phaseId,
      createWorkOrderPayload(workOrderOverrides),
      authHeaders
    );
    workOrder = getSuccessData<WorkOrder>(workOrderRes);
  }

  const contractRes = await apiClient.createContract(
    projectId,
    createContractPayload(workOrder.id, crewId, contractOverrides),
    authHeaders
  );
  const contract = getSuccessData<CrewContract>(contractRes);

  await apiClient.verifySpecialization(projectId, contract.id, authHeaders);
  const confirmedContractRes = await apiClient.scheduleWork(projectId, contract.id, authHeaders);
  getSuccessData(confirmedContractRes);

  const finalContractRes = await apiClient.getContract(projectId, contract.id, authHeaders);
  const confirmedContract = getSuccessData<CrewContract>(finalContractRes);

  return { workOrder: workOrder, contract: confirmedContract };
}

export interface ProjectScenario {
  project: UrbanRenewalProject;
  phases: RenovationPhase[];
  workOrders: WorkOrder[];
  crews: RenovationCrew[];
  contracts: CrewContract[];
  pairings: CrewConflictPairing[];
}

export async function setupBasicProject(options: { renovation_budget?: number; hourly_rate?: number } = {}) {
  const authHeaders = buildAuthHeaders('test-user');

  const projectRes = await apiClient.createProject(
    createProjectPayload({ project_name: 'Advanced Test Project', renovation_budget: options.renovation_budget || 500000.0 }),
    authHeaders
  );
  const project = getSuccessData<UrbanRenewalProject>(projectRes);
  await apiClient.beginWork(project.id, authHeaders);

  const phaseRes = await apiClient.createPhase(project.id, createPhasePayload({ name: 'Advanced Test Phase' }), authHeaders);
  const phase = getSuccessData<RenovationPhase>(phaseRes);

  const crewRes = await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Test Crew', company_name: 'Test Company', hourly_rate: options.hourly_rate || 100.0 }), authHeaders);
  const crew = getSuccessData<RenovationCrew>(crewRes);

  return { projectId: project.id, phaseId: phase.id, crewId: crew.id, authHeaders };
}

export async function setupActiveProject(): Promise<UrbanRenewalProject> {
  const headers = buildAuthHeaders('test-user');
  const createProjectPayloadData = createProjectPayload({});
  const projectResponse = await apiClient.createProject(createProjectPayloadData, headers);
  const project = getSuccessData<UrbanRenewalProject>(projectResponse);
  const activatedProjectResponse = await apiClient.beginWork(project.id, headers);
  return getSuccessData<UrbanRenewalProject>(activatedProjectResponse);
}

export async function setupScheduledWorkOrder() {
  const { project, phase, crew, workOrder } = await setupBasicScenario();
  const headers = buildAuthHeaders('test-user');

  const contractPayload = createContractPayload(workOrder.id, crew.id);
  const contractResponse = await apiClient.createContract(project.id, contractPayload, headers);
  const contract = getSuccessData<CrewContract>(contractResponse);

  const verifyResponse = await apiClient.verifySpecialization(project.id, contract.id, headers);
  getSuccessData(verifyResponse);

  const scheduleResponse = await apiClient.scheduleWork(project.id, contract.id, headers);
  const finalContract = getSuccessData<CrewContract>(scheduleResponse);

  const finalWorkOrderResponse = await apiClient.getWorkOrder(project.id, phase.id, workOrder.id, headers);
  const finalWorkOrder = getSuccessData<WorkOrder>(finalWorkOrderResponse);

  return { project, phase, crew, workOrder: finalWorkOrder, contract: finalContract };
}

export async function setupProjectWithPhaseAndCrew(
  overrides?: {
    projectBudget?: number;
    phasePayload?: Partial<{ name: string; start_hour: number; end_hour: number }>;
    crewPayload?: Partial<{ crew_name: string; company_name: string; hourly_rate: number }>;
  }
) {
  const authHeaders = buildAuthHeaders('test-user');

  const project = await createAndActivateProject(overrides?.projectBudget);

  const phaseRes = await apiClient.createPhase(
    project.id,
    createPhasePayload(overrides?.phasePayload || {}),
    authHeaders
  );
  const phase = getSuccessData<RenovationPhase>(phaseRes);

  const crewRes = await apiClient.createCrew(
    project.id,
    createCrewPayload(overrides?.crewPayload || {}),
    authHeaders
  );
  const crew = getSuccessData<RenovationCrew>(crewRes);

  return { project, phase, crew };
}

export async function setupProjectWithHighUsageCrew(
  hoursUsed: number,
  options: {
    projectId?: string;
    renovation_budget?: number;
    hourly_rate?: number;
  } = {}
) {
  const authHeaders = buildAuthHeaders('test-user');

  let projectId = options.projectId;
  if (!projectId) {
    const projectRes = await apiClient.createProject(
      createProjectPayload({ renovation_budget: options.renovation_budget || 1000000 }),
      authHeaders
    );
    const project = getSuccessData<UrbanRenewalProject>(projectRes);
    await apiClient.beginWork(project.id, authHeaders);
    projectId = project.id;
  }

  const phaseRes = await apiClient.createPhase(projectId, createPhasePayload(), authHeaders);
  const phase = getSuccessData<RenovationPhase>(phaseRes);

  const crewRes = await apiClient.createCrew(
    projectId,
    createCrewPayload({ hourly_rate: options.hourly_rate || 100.0 }),
    authHeaders
  );
  const crew = getSuccessData<RenovationCrew>(crewRes);

  if (hoursUsed > 0) {
    const workOrderRes = await apiClient.createWorkOrder(
      projectId,
      phase.id,
      createWorkOrderPayload({ start_hour: 0, end_hour: hoursUsed }),
      authHeaders
    );
    const workOrder = getSuccessData<WorkOrder>(workOrderRes);
    const contract = await createAndVerifyContract(projectId, workOrder.id, crew.id);
    await apiClient.scheduleWork(projectId, contract.id, authHeaders);
  }

  return {
    projectId,
    phaseId: phase.id,
    crewId: crew.id,
    authHeaders,
  };
}

export async function createAndVerifyContract(
  projectId: string,
  workOrderId: string,
  crewId: string,
  permitWaiverUsed: boolean = false
) {
  const authHeaders = buildAuthHeaders('test-user');

  const contractRes = await apiClient.createContract(
    projectId,
    createContractPayload(workOrderId, crewId, {
      permit_waiver_used: permitWaiverUsed
    }),
    authHeaders
  );
  const contract = getSuccessData<CrewContract>(contractRes);

  await apiClient.verifySpecialization(projectId, contract.id, authHeaders);

  return contract;
}

export async function createWorkOrderInPhase(
  projectId: string,
  phaseId: string,
  workOrderPayload?: Partial<{ task_type: string; required_specialization: Specialization; required_safety_clearance_level: number; start_hour: number; end_hour: number }>
) {
  const authHeaders = buildAuthHeaders('test-user');
  const project = await apiClient.getProject(projectId, authHeaders).then(r => getSuccessData<UrbanRenewalProject>(r));
  if (project.status !== 'IN_PROGRESS') {
    await apiClient.beginWork(projectId, authHeaders);
  }

  const workOrderRes = await apiClient.createWorkOrder(
    projectId,
    phaseId,
    createWorkOrderPayload(workOrderPayload || {}),
    authHeaders
  );

  return getSuccessData<WorkOrder>(workOrderRes);
}

export async function setupProjectWithHighDisruptionIndex(
  targetDisruptionIndex: number = 500,
  projectBudget: number = 20000
) {
  const authHeaders = buildAuthHeaders('test-user');

  const project = await createAndActivateProject(projectBudget);

  const phaseRes = await apiClient.createPhase(
    project.id,
    createPhasePayload(),
    authHeaders
  );
  const phase = getSuccessData<RenovationPhase>(phaseRes);

  const crewRes = await apiClient.createCrew(
    project.id,
    createCrewPayload(),
    authHeaders
  );
  const crew = getSuccessData<RenovationCrew>(crewRes);

  const disruptiveWorkPenalty = 25;
  const initialScore = 0;
  const requiredDisruptiveContracts = Math.ceil((targetDisruptionIndex - initialScore) / disruptiveWorkPenalty);

  for (let i = 0; i < requiredDisruptiveContracts; i++) {
    const workOrderRes = await apiClient.createWorkOrder(
      project.id,
      phase.id,
      createWorkOrderPayload({
        start_hour: i * 200,
        end_hour: i * 200 + 50
      }),
      authHeaders
    );
    const workOrder = getSuccessData<WorkOrder>(workOrderRes);

    await apiClient.createContract(
      project.id,
      createContractPayload(workOrder.id, crew.id),
      authHeaders
    );
  }

  return { project, phase, crew };
}

export async function setupProjectAndRaiseDisruptionIndex({
  projectId,
  numDisruptiveContracts = 10,
  projectBudget = 400000.00,
  crewCost = 100.00,
}: {
  projectId?: string;
  numDisruptiveContracts?: number,
  projectBudget?: number,
  crewCost?: number,
} = {}) {
  let project: UrbanRenewalProject;
  let phase: RenovationPhase;
  const authHeaders = buildAuthHeaders('test-user');

  if (projectId) {
    const projectRes = await apiClient.getProject(projectId, authHeaders);
    project = getSuccessData<UrbanRenewalProject>(projectRes);
    const phaseRes = await apiClient.createPhase(
      project.id,
      createPhasePayload(),
      authHeaders
    );
    phase = getSuccessData<RenovationPhase>(phaseRes);
  } else {
    const setup = await setupProjectWithPhase({
      projectBudget,
    });
    project = setup.project;
    phase = setup.phase;
  }

  const mainCrewRes = await apiClient.createCrew(project.id, createCrewPayload({
    crew_name: 'Main Test Crew',
    hourly_rate: crewCost
  }), authHeaders);
  const crew = getSuccessData<RenovationCrew>(mainCrewRes);

  const penaltyCrewRes = await apiClient.createCrew(project.id, createCrewPayload({
    crew_name: 'Disruption Penalty Crew',
    hourly_rate: crewCost
  }), authHeaders);
  const penaltyCrew = getSuccessData<RenovationCrew>(penaltyCrewRes);

  let currentStartHour = phase.start_hour;
  let currentDisruptionIndex = 0;

  const normalWorkHours = 150;
  const normalWorkOrder = await createWorkOrderInPhase(project.id, phase.id, {
    task_type: 'Setup Work',
    start_hour: currentStartHour,
    end_hour: addHours(currentStartHour, normalWorkHours)
  });
  await createAndConfirmContract(project.id, phase.id, penaltyCrew.id, {}, normalWorkOrder);

  currentStartHour = addHours(currentStartHour, normalWorkHours + 4);

  for (let i = 0; i < numDisruptiveContracts; i++) {
    const workHours = 20;
    const disruptiveWorkOrder = await createWorkOrderInPhase(project.id, phase.id, {
      task_type: `Disruptive Work ${i + 1}`,
      start_hour: currentStartHour,
      end_hour: addHours(currentStartHour, workHours)
    });

    const scoreAfterPenalty = currentDisruptionIndex + 25;
    const needsPermitWaiver = scoreAfterPenalty > 100;

    await createAndConfirmContract(project.id, phase.id, penaltyCrew.id, {}, disruptiveWorkOrder, { permit_waiver_used: needsPermitWaiver });

    currentDisruptionIndex += 25;

    if (needsPermitWaiver) {
      currentDisruptionIndex += 75;
    }

    currentStartHour = addHours(currentStartHour, workHours + 4);
  }

  return { project, crew, phase, crewId: penaltyCrew.id };
}

export async function setupProjectWithFinalizedContract(options?: {
  projectBudget?: number;
  crewCost?: number;
}) {
  const authHeaders = buildAuthHeaders('test-user');

  const { project, phase, crew } = await setupProjectWithPhaseAndCrew({
    projectBudget: options?.projectBudget,
    crewPayload: { hourly_rate: options?.crewCost },
  });

  const workOrderRes = await apiClient.createWorkOrder(
    project.id,
    phase.id,
    createWorkOrderPayload({}),
    authHeaders
  );
  const workOrder = getSuccessData<WorkOrder>(workOrderRes);

  const { contract } = await createAndConfirmContract(project.id, phase.id, crew.id, {}, workOrder);

  await transitionPhaseToReadyForExecution(project.id, phase.id);

  await apiClient.initiateFinalAudit(project.id, authHeaders);
  await apiClient.finalizeProject(project.id, authHeaders);

  const finalProjectRes = await apiClient.getProject(project.id, authHeaders);
  const finalProject = getSuccessData<UrbanRenewalProject>(finalProjectRes);

  return { project: finalProject, contract };
}

export async function setupProjectWithPhase(
  overrides?: {
    projectBudget?: number;
    phasePayload?: Partial<{ name: string; start_hour: number; end_hour: number }>;
  }
) {
  const authHeaders = buildAuthHeaders('test-user');

  const project = await createAndActivateProject(overrides?.projectBudget);

  const phaseRes = await apiClient.createPhase(
    project.id,
    createPhasePayload(overrides?.phasePayload || {}),
    authHeaders
  );
  const phase = getSuccessData<RenovationPhase>(phaseRes);

  return { project, phase };
}

export async function setupDataIsolationScenario() {
  const authHeaders = buildAuthHeaders('test-user');

  const projectA = await createAndActivateProject(20000, 'Project A');
  const projectB = await createAndActivateProject(20000, 'Project B');

  return { projectA, projectB, authHeaders };
}

export async function setupScenarioWithScheduledWorkOrder() {
  const authHeaders = buildAuthHeaders('test-user');

  const project = await createAndActivateProject();
  const phaseRes = await apiClient.createPhase(
    project.id,
    createPhasePayload(),
    authHeaders
  );
  const phase = getSuccessData<RenovationPhase>(phaseRes);

  const workOrderRes = await apiClient.createWorkOrder(
    project.id,
    phase.id,
    createWorkOrderPayload(),
    authHeaders
  );
  const workOrder = getSuccessData<WorkOrder>(workOrderRes);

  const crewRes = await apiClient.createCrew(
    project.id,
    createCrewPayload(),
    authHeaders
  );
  const crew = getSuccessData<RenovationCrew>(crewRes);

  const { contract } = await createAndConfirmContract(project.id, phase.id, crew.id, {}, workOrder);

  await transitionPhaseToReadyForExecution(project.id, phase.id);

  return { project, phase, workOrder, crew, contract, authHeaders };
}

export async function setupScenarioWithPendingWorkOrder() {
  const authHeaders = buildAuthHeaders('test-user');
  const project = await createAndActivateProject();
  const phaseRes = await apiClient.createPhase(
    project.id,
    createPhasePayload(),
    authHeaders
  );
  const phase = getSuccessData<RenovationPhase>(phaseRes);

  const workOrderRes = await apiClient.createWorkOrder(
    project.id,
    phase.id,
    createWorkOrderPayload(),
    authHeaders
  );
  const workOrder = getSuccessData<WorkOrder>(workOrderRes);

  return { project, phase, workOrder, authHeaders };
}

export async function setupScenarioWithProposedContract() {
  const authHeaders = buildAuthHeaders('test-user');
  const project = await createAndActivateProject();
  const phaseRes = await apiClient.createPhase(
    project.id,
    createPhasePayload(),
    authHeaders
  );
  const phase = getSuccessData<RenovationPhase>(phaseRes);
  const workOrderRes = await apiClient.createWorkOrder(
    project.id,
    phase.id,
    createWorkOrderPayload(),
    authHeaders
  );
  const workOrder = getSuccessData<WorkOrder>(workOrderRes);
  const crewRes = await apiClient.createCrew(
    project.id,
    createCrewPayload(),
    authHeaders
  );
  const crew = getSuccessData<RenovationCrew>(crewRes);
  const contractRes = await apiClient.createContract(
    project.id,
    createContractPayload(workOrder.id, crew.id),
    authHeaders
  );
  const contract = getSuccessData<CrewContract>(contractRes);
  return { project, phase, crew, workOrder, contract, authHeaders };
}

export async function setupWithPairedCrews() {
  const { project, phase } = await setupProjectWithPhase();
  const authHeaders = buildAuthHeaders('test-user');

  const crewARes = await apiClient.createCrew(
    project.id,
    createCrewPayload({ crew_name: 'Crew A' }),
    authHeaders
  );
  const crewA = getSuccessData<RenovationCrew>(crewARes);

  const crewBRes = await apiClient.createCrew(
    project.id,
    createCrewPayload({ crew_name: 'Crew B' }),
    authHeaders
  );
  const crewB = getSuccessData<RenovationCrew>(crewBRes);

  await apiClient.createCrewConflictPairing(
    project.id,
    createCrewConflictPairingPayload(crewA.id, crewB.id),
    authHeaders
  );

  return { project, phase, crewA, crewB };
}

export async function setupProjectWithTwoHighUsageCrews() {
  const project = await createAndActivateProject();
  const crewA = await apiClient.createCrew(
    project.id,
    createCrewPayload({ crew_name: 'Crew A', hourly_rate: 100.0 }),
    buildAuthHeaders('test-user')
  ).then(r => getSuccessData<RenovationCrew>(r));
  const crewB = await apiClient.createCrew(
    project.id,
    createCrewPayload({ crew_name: 'Crew B', hourly_rate: 100.0 }),
    buildAuthHeaders('test-user')
  ).then(r => getSuccessData<RenovationCrew>(r));

  return { project, crewA, crewB };
}

export async function setupCrewWithOneScheduledContract() {
  const { project, phase, crew, workOrder, contract, authHeaders } = await setupScenarioWithScheduledWorkOrder();
  return { project, phase, crew, contractToCancel: contract, authHeaders };
}

export async function createAndScheduleContract(
  projectId: string,
  phaseId: string,
  crewId: string,
  workOrderData: Partial<{ task_type: string; required_specialization: Specialization; required_safety_clearance_level: number; start_hour: number; end_hour: number }>,
  options: { permit_waiver_used?: boolean } = {}
) {
  const authHeaders = buildAuthHeaders('test-user');

  const workOrderRes = await apiClient.createWorkOrder(
    projectId,
    phaseId,
    createWorkOrderPayload(workOrderData),
    authHeaders
  );
  const workOrder = getSuccessData<WorkOrder>(workOrderRes);

  const contractRes = await apiClient.createContract(
    projectId,
    createContractPayload(workOrder.id, crewId, options),
    authHeaders
  );
  const contract = getSuccessData<CrewContract>(contractRes);

  await apiClient.verifySpecialization(projectId, contract.id, authHeaders);
  await apiClient.scheduleWork(projectId, contract.id, authHeaders);

  return contract;
}

export async function getContractState(projectId: string, contractId: string) {
  const authHeaders = buildAuthHeaders('test-user');
  const res = await apiClient.getContract(projectId, contractId, authHeaders);
  return getSuccessData<CrewContract>(res);
}

export async function getProjectState(projectId: string) {
  const authHeaders = buildAuthHeaders('test-user');
  const projectRes = await apiClient.getProject(projectId, authHeaders);
  return getSuccessData<UrbanRenewalProject>(projectRes);
}

export async function setupTestEnvironment(options: { budget?: number } = {}) {
  const authHeaders = buildAuthHeaders('test-user');

  const projectRes = await apiClient.createProject(
    createProjectPayload({ renovation_budget: options.budget || 20000 }),
    authHeaders
  );
  const project = getSuccessData<UrbanRenewalProject>(projectRes);
  await apiClient.beginWork(project.id, authHeaders);

  const phaseRes = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders);
  const phase = getSuccessData<RenovationPhase>(phaseRes);

  const crewRes = await apiClient.createCrew(project.id, createCrewPayload(), authHeaders);
  const crew = getSuccessData<RenovationCrew>(crewRes);

  return {
    projectId: project.id,
    phaseId: phase.id,
    crewId: crew.id,
    authHeaders,
  };
}

export async function createProject(
  payload: Partial<{ project_name: string; renovation_budget: number }> = {},
  activate: boolean = true
) {
  const authHeaders = buildAuthHeaders('test-user');
  const createPayload = createProjectPayload(payload);
  const projectRes = await apiClient.createProject(createPayload, authHeaders);
  let project = getSuccessData<UrbanRenewalProject>(projectRes);
  if (activate) {
    const activatedRes = await apiClient.beginWork(project.id, authHeaders);
    project = getSuccessData<UrbanRenewalProject>(activatedRes);
  }
  return project;
}

export async function createPhase(
  projectId: string,
  payload: Partial<{ name: string; start_hour: number; end_hour: number }> = {},
  activate: boolean = true
) {
  const authHeaders = buildAuthHeaders('test-user');
  if (activate) {
    const project = await apiClient.getProject(projectId, authHeaders).then(r => getSuccessData<UrbanRenewalProject>(r));
    if (project.status !== 'IN_PROGRESS') {
      await apiClient.beginWork(projectId, authHeaders);
    }
  }
  const createPayload = createPhasePayload(payload);
  const phaseRes = await apiClient.createPhase(projectId, createPayload, authHeaders);
  return getSuccessData<RenovationPhase>(phaseRes);
}

export async function createWorkOrder(
  projectId: string,
  phaseId: string,
  payload: Partial<{ task_type: string; required_specialization: Specialization; required_safety_clearance_level: number; start_hour: number; end_hour: number }> = {},
  activate: boolean = true
) {
  const authHeaders = buildAuthHeaders('test-user');
  if (activate) {
    const project = await apiClient.getProject(projectId, authHeaders).then(r => getSuccessData<UrbanRenewalProject>(r));
    if (project.status !== 'IN_PROGRESS') {
      await apiClient.beginWork(projectId, authHeaders);
    }
  }
  const createPayload = createWorkOrderPayload(payload);
  const workOrderRes = await apiClient.createWorkOrder(projectId, phaseId, createPayload, authHeaders);
  return getSuccessData<WorkOrder>(workOrderRes);
}

export async function transitionPhaseToReadyForExecution(
  projectId: string,
  phaseId: string
): Promise<RenovationPhase> {
  const authHeaders = buildAuthHeaders('test-user');

  const updateRes = await apiClient.updatePhaseStatus(
    projectId,
    phaseId,
    { status: RenovationPhaseStatus.READY_FOR_EXECUTION },
    authHeaders
  );

  return getSuccessData<RenovationPhase>(updateRes);
}

export async function createAndScheduleWorkOrders(
  projectId: string,
  phaseId: string,
  crewId: string,
  options: {
    count: number;
    hours: number;
    start_hour?: number;
    spacing_hours?: number;
  }
) {
  const { count, hours, start_hour = 100, spacing_hours = 0 } = options;
  const workOrders = [];
  let current_start_hour = start_hour;

  for (let i = 0; i < count; i++) {
    const workOrderData = {
      start_hour: current_start_hour,
      end_hour: addHours(current_start_hour, hours),
    };
    const workOrder = await createAndScheduleWorkOrder(projectId, phaseId, crewId, workOrderData);
    workOrders.push(workOrder);
    current_start_hour = addHours(workOrder.end_hour, spacing_hours);
  }
  return workOrders;
}

export async function completeWorkOrder(projectId: string, phaseId: string, workOrderId: string) {
  const authHeaders = buildAuthHeaders('test-user');

  const crewRes = await apiClient.createCrew(
    projectId,
    createCrewPayload({ crew_name: `Crew for ${workOrderId}` }),
    authHeaders
  );
  const crew = getSuccessData<RenovationCrew>(crewRes);

  const contractRes = await apiClient.createContract(
    projectId,
    createContractPayload(workOrderId, crew.id),
    authHeaders
  );
  const contract = getSuccessData<CrewContract>(contractRes);

  await apiClient.verifySpecialization(projectId, contract.id, authHeaders);
  await apiClient.scheduleWork(projectId, contract.id, authHeaders);

  await apiClient.initiateFinalAudit(projectId, authHeaders);
  await apiClient.finalizeProject(projectId, authHeaders);
}

export async function finalizeProjectComplete(
  projectId: string,
  authHeaders?: ApiHeaders,
  adminHeaders?: ApiHeaders
): Promise<UrbanRenewalProject> {
  const headers = authHeaders || buildAuthHeaders('test-user');
  const adminH = adminHeaders || headers;

  await apiClient.initiateFinalAudit(projectId, headers);
  const finalizeRes = await apiClient.finalizeProject(projectId, adminH);
  return getSuccessData<UrbanRenewalProject>(finalizeRes);
}

export async function setupProjectWithCustomBudgetAndCrew(
  budget: number,
  hourlyRate: number,
  authHeaders?: ApiHeaders
): Promise<{
  project: UrbanRenewalProject;
  phase: RenovationPhase;
  crew: RenovationCrew;
  authHeaders: ApiHeaders;
}> {
  const headers = authHeaders || buildAuthHeaders('test-user');
  const project = await createAndActivateProject(budget);

  const phaseRes = await apiClient.createPhase(
    project.id,
    createPhasePayload(),
    headers
  );
  const phase = getSuccessData<RenovationPhase>(phaseRes);

  const crewRes = await apiClient.createCrew(
    project.id,
    createCrewPayload({ hourly_rate: hourlyRate }),
    headers
  );
  const crew = getSuccessData<RenovationCrew>(crewRes);

  return { project, phase, crew, authHeaders: headers };
}

export async function createAndScheduleStandardContract(
  projectId: string,
  workOrderId: string,
  crewId: string,
  authHeaders?: ApiHeaders,
  contractOverrides?: Partial<CrewContractPayload>
): Promise<CrewContract> {
  const headers = authHeaders || buildAuthHeaders('test-user');

  const contractRes = await apiClient.createContract(
    projectId,
    createContractPayload(workOrderId, crewId, contractOverrides),
    headers
  );
  const contract = getSuccessData<CrewContract>(contractRes);

  await apiClient.verifySpecialization(projectId, contract.id, headers);
  const scheduledRes = await apiClient.scheduleWork(projectId, contract.id, headers);
  return getSuccessData<CrewContract>(scheduledRes);
}

export async function setupCompleteScenarioWithReadyPhase(
  overrides?: {
    projectBudget?: number;
    hourlyRate?: number;
    workOrderHours?: number;
  }
): Promise<{
  project: UrbanRenewalProject;
  phase: RenovationPhase;
  crew: RenovationCrew;
  workOrder: WorkOrder;
  contract: CrewContract;
  authHeaders: ApiHeaders;
}> {
  const authHeaders = buildAuthHeaders('test-user');
  const { project, phase, crew } = await setupProjectWithCustomBudgetAndCrew(
    overrides?.projectBudget || DEFAULTS.RENOVATION_BUDGET,
    overrides?.hourlyRate || DEFAULTS.HOURLY_RATE,
    authHeaders
  );

  const workOrderRes = await apiClient.createWorkOrder(
    project.id,
    phase.id,
    createWorkOrderPayload({
      start_hour: createScheduleHour(0),
      end_hour: addHours(createScheduleHour(0), overrides?.workOrderHours || DEFAULTS.WORK_ORDER_DURATION_HOURS)
    }),
    authHeaders
  );
  const workOrder = getSuccessData<WorkOrder>(workOrderRes);

  const contract = await createAndScheduleStandardContract(
    project.id,
    workOrder.id,
    crew.id,
    authHeaders
  );

  await transitionPhaseToReadyForExecution(project.id, phase.id);

  return { project, phase, crew, workOrder, contract, authHeaders };
}

export async function setupScenarioWithReadyPhase() {
    const projectManagerHeaders = buildAuthHeaders('pm-1');
    const siteEngineerHeaders = buildAuthHeaders('engineer-1');

    const activeProject = await createAndActivateProject(undefined, 'Test Project');

    const phaseRes = await apiClient.createPhase(
        activeProject.id,
        createPhasePayload({ name: 'Test Phase' }),
        siteEngineerHeaders
    );
    const phase = getSuccessData<RenovationPhase>(phaseRes);

    const workOrderRes = await apiClient.createWorkOrder(
        activeProject.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Test Work' }),
        siteEngineerHeaders
    );
    const workOrder = getSuccessData<WorkOrder>(workOrderRes);

    const crewRes = await apiClient.createCrew(
        activeProject.id,
        createCrewPayload({ crew_name: 'Test Crew' }),
        siteEngineerHeaders
    );
    const crew = getSuccessData<RenovationCrew>(crewRes);

    const contractRes = await apiClient.createContract(
        activeProject.id,
        createContractPayload(workOrder.id, crew.id),
        siteEngineerHeaders
    );
    const contract = getSuccessData<CrewContract>(contractRes);

    await apiClient.verifySpecialization(activeProject.id, contract.id, projectManagerHeaders);

    await apiClient.scheduleWork(activeProject.id, contract.id, projectManagerHeaders);

    await transitionPhaseToReadyForExecution(activeProject.id, phase.id);

    return { project: activeProject, phase, workOrder, crew, contract, projectManagerHeaders, siteEngineerHeaders };
}

export async function setupScenarioWithScheduledWorkOrderWithoutPhaseTransition() {
    const projectManagerHeaders = buildAuthHeaders('pm-1');
    const siteEngineerHeaders = buildAuthHeaders('engineer-1');

    const activeProject = await createAndActivateProject(undefined, 'Test Project');

    const phaseRes = await apiClient.createPhase(
        activeProject.id,
        createPhasePayload({ name: 'Test Phase' }),
        siteEngineerHeaders
    );
    const phase = getSuccessData<RenovationPhase>(phaseRes);

    const workOrderRes = await apiClient.createWorkOrder(
        activeProject.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Test Work' }),
        siteEngineerHeaders
    );
    const workOrder = getSuccessData<WorkOrder>(workOrderRes);

    const crewRes = await apiClient.createCrew(
        activeProject.id,
        createCrewPayload({ crew_name: 'Test Crew' }),
        siteEngineerHeaders
    );
    const crew = getSuccessData<RenovationCrew>(crewRes);

    const contractRes = await apiClient.createContract(
        activeProject.id,
        createContractPayload(workOrder.id, crew.id),
        siteEngineerHeaders
    );
    const contract = getSuccessData<CrewContract>(contractRes);

    await apiClient.verifySpecialization(activeProject.id, contract.id, projectManagerHeaders);

    await apiClient.scheduleWork(activeProject.id, contract.id, projectManagerHeaders);

    return { project: activeProject, phase, workOrder, crew, contract, projectManagerHeaders, siteEngineerHeaders };
}
