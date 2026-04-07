import { v4 as uuidv4 } from 'uuid';
import {
  CreateGardenPlanPayload,
  CreatePlantingSeasonPayload,
  CreatePlantingTaskPayload,
  CreateGardenPlotPayload,
  RequiredAmendment, TaskAssignmentPayload,
  GardenPlan,
  PlantingSeason,
  PlantingTask,
  GardenPlot,
  TaskAssignment,
  UserRole, ApiHeaders
} from './types';
import { createDayOfYear, addDays, buildUserHeaders } from './utils';
import { apiClient } from './api-client';
import { getSuccessData, handleApiResponse } from './validators';

export function generateGardenPlanPayload(): CreateGardenPlanPayload {
  return {
    plan_name: `Test Garden Plan ${uuidv4().slice(0, 8)}`,
    total_water_credits: 10000,
  };
}

export function generatePlantingSeasonPayload(): CreatePlantingSeasonPayload {
  const startDate = createDayOfYear(10);
  return {
    name: `Spring Season ${uuidv4().slice(0, 8)}`,
    start_date: startDate,
    end_date: addDays(startDate, 90),
  };
}

export function generatePlantingTaskPayload(): CreatePlantingTaskPayload {
  const startDate = createDayOfYear(15);
  return {
    plant_type: 'Roma Tomato',
    plant_family: 'Solanaceae',
    required_amendment: RequiredAmendment.NONE,
    start_date: startDate,
    end_date: addDays(startDate, 30),
    water_requirement_liters: 50,
  };
}

export function generateGardenPlotPayload(): CreateGardenPlotPayload {
  return {
    plot_name: `Plot ${uuidv4().slice(0, 8)}`,
    plot_size_sqm: 25,
    water_credits_per_liter: 2.5,
  };
}

export const PLANT_FAMILIES = {
  SOLANACEAE: 'Solanaceae',
  BRASSICACEAE: 'Brassicaceae',
  CUCURBITACEAE: 'Cucurbitaceae',
  FABACEAE: 'Fabaceae',
  APIACEAE: 'Apiaceae',
};

export const TEST_USER_IDS = {
  gardenManager: 'test-garden-manager-001',
  gardener: 'test-gardener-001',
  billingAdmin: 'test-billing-admin-001',
};

export function generateAppliedDate(daysAgo: number = 0): string {
  const date = new Date();
  date.setDate(date.getDate() - daysAgo);
  return date.toISOString().split('T')[0];
}

export function createGardenPlanPayload(overrides: Partial<CreateGardenPlanPayload> = {}): CreateGardenPlanPayload {
  return {
    ...generateGardenPlanPayload(),
    ...overrides
  };
}

export function createPlantingSeasonPayload(overrides: Partial<CreatePlantingSeasonPayload> = {}): CreatePlantingSeasonPayload {
  const startDate = overrides.start_date || createDayOfYear(10);
  return {
    name: `Spring Season ${uuidv4().slice(0, 8)}`,
    start_date: startDate,
    end_date: overrides.end_date || addDays(startDate, 90),
    ...overrides
  };
}

export function createPlantingTaskPayload(overrides: Partial<CreatePlantingTaskPayload> = {}): CreatePlantingTaskPayload {
  const startDate = overrides.start_date || createDayOfYear(15);
  return {
    plant_type: 'Roma Tomato',
    plant_family: 'Solanaceae',
    required_amendment: RequiredAmendment.NONE,
    start_date: startDate,
    end_date: overrides.end_date || addDays(startDate, 30),
    water_requirement_liters: 50,
    ...overrides
  };
}

export function createGardenPlotPayload(overrides: Partial<CreateGardenPlotPayload> = {}): CreateGardenPlotPayload {
  return {
    plot_name: `Plot ${uuidv4().slice(0, 8)}`,
    plot_size_sqm: 25,
    water_credits_per_liter: 2.5,
    ...overrides
  };
}

export function createTaskAssignmentPayload(
  taskId: string,
  plotId: string,
  options: { override_pest_check?: boolean } = {}
): TaskAssignmentPayload {
  return {
    task_id: taskId,
    plot_id: plotId,
    override_pest_check: options.override_pest_check || false,
  };
}

export async function createAndActivateGardenPlan(
  payloadOrCredits?: Partial<CreateGardenPlanPayload> | number,
  headers?: ApiHeaders
): Promise<GardenPlan> {
  const gardenManagerHeaders = headers || buildUserHeaders('test-garden-manager', UserRole.GardenManager);

  let payload: Partial<CreateGardenPlanPayload>;
  if (typeof payloadOrCredits === 'number') {
    payload = { total_water_credits: payloadOrCredits };
  } else {
    payload = payloadOrCredits || {};
  }

  const planRes = await apiClient.createGardenPlan(
    createGardenPlanPayload(payload),
    gardenManagerHeaders
  );
  const plan = handleApiResponse<GardenPlan>(planRes, 201);

  await apiClient.activateGardenPlan(plan.id, gardenManagerHeaders);

  const activatedPlanRes = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders);
  return handleApiResponse<GardenPlan>(activatedPlanRes, 200);
}

export async function setupPlanWithSeason(
  overrides?: {
    planWaterCredits?: number;
    seasonPayload?: Partial<CreatePlantingSeasonPayload>;
  }
) {
  const gardenerHeaders = buildUserHeaders('gardener-1', UserRole.Gardener);

  const plan = await createAndActivateGardenPlan(overrides?.planWaterCredits ? { total_water_credits: overrides.planWaterCredits } : {});

  const seasonRes = await apiClient.createPlantingSeason(
    plan.id,
    createPlantingSeasonPayload(overrides?.seasonPayload || {}),
    gardenerHeaders
  );
  const season = handleApiResponse<PlantingSeason>(seasonRes, 201);

  return { plan, season };
}

export async function createAndConfirmAssignment(
  planId: string,
  seasonId: string,
  plotId: string,
  taskOverrides?: Partial<CreatePlantingTaskPayload>,
  headers?: {
    gardener?: ApiHeaders;
    gardenManager?: ApiHeaders;
  },
  assignmentOverrides?: Partial<TaskAssignmentPayload>
): Promise<{
  plantingTask: PlantingTask;
  assignment: TaskAssignment;
}> {
  const gardenerHeaders = headers?.gardener || buildUserHeaders('test-gardener', UserRole.Gardener);
  const gardenManagerHeaders = headers?.gardenManager || buildUserHeaders('test-garden-manager', UserRole.GardenManager);

  const taskRes = await apiClient.createPlantingTask(
    planId,
    seasonId,
    createPlantingTaskPayload(taskOverrides),
    gardenerHeaders
  );
  const task = handleApiResponse<PlantingTask>(taskRes, 201);

  const assignmentPayload: TaskAssignmentPayload = {
    task_id: task.id,
    plot_id: plotId,
    ...assignmentOverrides
  };

  const assignmentRes = await apiClient.createTaskAssignment(
    planId,
    assignmentPayload,
    gardenerHeaders
  );
  const assignment = handleApiResponse<TaskAssignment>(assignmentRes, 201);

  await apiClient.approveTaskAssignment(planId, assignment.id, gardenManagerHeaders);

  await apiClient.scheduleTaskAssignment(planId, assignment.id, gardenManagerHeaders);

  const finalAssignmentRes = await apiClient.getTaskAssignment(planId, assignment.id, gardenerHeaders);
  const finalAssignment = handleApiResponse<TaskAssignment>(finalAssignmentRes, 200);

  return {
    plantingTask: task,
    assignment: finalAssignment
  };
}

export async function setupBasicGardenProject(
  totalWaterCredits: number = 10000
): Promise<{
  planId: string;
  seasonId: string;
  plotId: string;
}> {
  const gardenerHeaders = buildUserHeaders('test-gardener', UserRole.Gardener);
  const gardenManagerHeaders = buildUserHeaders('test-garden-manager', UserRole.GardenManager);

  const plan = await createAndActivateGardenPlan(
    { total_water_credits: totalWaterCredits },
    gardenManagerHeaders
  );

  const seasonRes = await apiClient.createPlantingSeason(
    plan.id,
    createPlantingSeasonPayload(),
    gardenerHeaders
  );
  const season = handleApiResponse<PlantingSeason>(seasonRes, 201);

  const plotRes = await apiClient.createGardenPlot(
    plan.id,
    createGardenPlotPayload(),
    gardenerHeaders
  );
  const plot = handleApiResponse<GardenPlot>(plotRes, 201);

  return {
    planId: plan.id,
    seasonId: season.id,
    plotId: plot.id
  };
}

export async function setupProjectWithSeasonAndPlot(options: {
  projectBudget?: number;
  plotPayload?: Partial<CreateGardenPlotPayload>;
} = {}): Promise<{
  project: GardenPlan;
  season: PlantingSeason;
  plot: GardenPlot;
}> {
  const gardenerHeaders = buildUserHeaders('gardener-1', UserRole.Gardener);
  const project = await createAndActivateGardenPlan(options.projectBudget ? { total_water_credits: options.projectBudget } : {});

  const seasonRes = await apiClient.createPlantingSeason(
    project.id,
    createPlantingSeasonPayload(),
    gardenerHeaders
  );
  const season = getSuccessData<PlantingSeason>(seasonRes);

  const plotRes = await apiClient.createGardenPlot(
    project.id,
    createGardenPlotPayload(options.plotPayload),
    gardenerHeaders
  );
  const plot = getSuccessData<GardenPlot>(plotRes);

  return { project, season, plot };
}

export async function createPlantingTaskInSeason(
  projectId: string,
  seasonId: string,
  overrides: Partial<CreatePlantingTaskPayload> = {}
): Promise<PlantingTask> {
  const gardenerHeaders = buildUserHeaders('gardener-1', UserRole.Gardener);
  const res = await apiClient.createPlantingTask(
    projectId,
    seasonId,
    createPlantingTaskPayload(overrides),
    gardenerHeaders
  );
  return getSuccessData<PlantingTask>(res);
}

export async function createAndApproveAssignment(
  projectId: string,
  taskId: string,
  plotId: string,
  options: { override_pest_check?: boolean } = {}
): Promise<TaskAssignment> {
  const gardenerHeaders = buildUserHeaders('gardener-1', UserRole.Gardener);
  const managerHeaders = buildUserHeaders('manager-1', UserRole.GardenManager);

  const assignmentRes = await apiClient.createTaskAssignment(
    projectId,
    createTaskAssignmentPayload(taskId, plotId, options),
    gardenerHeaders
  );
  const assignment = getSuccessData<TaskAssignment>(assignmentRes);

  const approveRes = await apiClient.approveTaskAssignment(
    projectId,
    assignment.id,
    managerHeaders
  );
  return getSuccessData<TaskAssignment>(approveRes);
}

export async function createAndScheduleAssignment(
  projectId: string,
  taskId: string,
  plotId: string,
  options: { override_pest_check?: boolean } = {}
): Promise<TaskAssignment> {
  const managerHeaders = buildUserHeaders('manager-1', UserRole.GardenManager);

  const assignment = await createAndApproveAssignment(projectId, taskId, plotId, options);

  const scheduleRes = await apiClient.scheduleTaskAssignment(
    projectId,
    assignment.id,
    managerHeaders
  );
  return getSuccessData<TaskAssignment>(scheduleRes);
}

export async function createAndAssignTasks(
  projectId: string,
  seasonId: string,
  plotId: string,
  options: {
    count: number;
    water_liters: number;
    start_date?: number;
    spacing_days?: number;
  }
): Promise<TaskAssignment[]> {
  const assignments: TaskAssignment[] = [];
  const startDate = options.start_date || createDayOfYear(10);
  const spacing = options.spacing_days || 1;

  for (let i = 0; i < options.count; i++) {
    const task = await createPlantingTaskInSeason(projectId, seasonId, {
      plant_type: `Task ${i + 1}`,
      plant_family: 'Solanaceae',
      water_requirement_liters: options.water_liters,
      start_date: addDays(startDate, i * spacing),
      end_date: addDays(startDate, i * spacing + 7),
    });

    const assignment = await createAndScheduleAssignment(projectId, task.id, plotId);
    assignments.push(assignment);
  }

  return assignments;
}

export async function setupProjectAndIncreasePestRisk(options: {
  numStressedTasks?: number;
  projectBudget?: number;
  plotWaterCreditsPerLiter?: number;
} = {}): Promise<{
  project: GardenPlan;
  plot: GardenPlot;
  season: PlantingSeason;
}> {
  const { project, season, plot } = await setupProjectWithSeasonAndPlot({
    projectBudget: options.projectBudget,
    plotPayload: { water_credits_per_liter: options.plotWaterCreditsPerLiter || 2.0 }
  });

  const gardenerHeaders = buildUserHeaders('gardener-1', UserRole.Gardener);
  const baseDate = season.start_date;

  await createAndAssignTasks(project.id, season.id, plot.id, {
    count: 1,
    water_liters: 100,
    start_date: baseDate,
  });

  const numStressed = options.numStressedTasks || 9;
  for (let i = 0; i < numStressed; i++) {
    const startDate = addDays(baseDate, (101 + i * 10));
    const task = await createPlantingTaskInSeason(project.id, season.id, {
      plant_type: `Water Stressed Task ${i + 1}`,
      plant_family: 'Brassicaceae',
      start_date: startDate,
      end_date: addDays(startDate, 1),
      water_requirement_liters: 1,
    });

    await createAndScheduleAssignment(project.id, task.id, plot.id);
  }

  return { project, plot, season };
}

export function addHours(dayOfYear: number, hours: number): number {

  const daysToAdd = Math.floor(hours / 24);
  return dayOfYear + daysToAdd;
}

export function addMinutes(dayOfYear: number, minutes: number): number {

  const daysToAdd = Math.floor(minutes / (24 * 60));
  return dayOfYear + daysToAdd;
}
