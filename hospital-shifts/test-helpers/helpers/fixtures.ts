import { v4 as uuidv4 } from 'uuid';
import {
  TreatmentPlan,
  WardRotation,
  Procedure,
  MedicalResource,
  Assignment,
  InfectionRiskPairing,
  AssignmentPayload,
  WardRotationStatus,
} from './types';
import { createScheduleMinute, addMinutes, buildUserHeaders } from './utils';
import { getSuccessData } from './validators';
import { apiClient } from './api-client';
import { TEST_USERS } from './test-users';

const DEFAULTS = {
  PLAN_NAME: 'Test Treatment Plan',
  TOTAL_BUDGET: 250000.00,
  ROTATION_NAME: 'Test Ward Rotation',
  PROCEDURE_TYPE: 'Test Procedure',
  RESOURCE_NAME: 'Test Resource',
  RESOURCE_MODEL: 'standard-resource',
  OPERATING_COST_PER_MINUTE: 10.0,
  PROCEDURE_DURATION_MINUTES: 60,
  ROTATION_DURATION_MINUTES: 240,
};

/**
 * Generates a test treatment plan payload
 */
export function createTreatmentPlanPayload(
  overrides: Partial<{ plan_name: string; total_budget: number }> = {}
): { plan_name: string; total_budget: number } {
  return {
    plan_name: DEFAULTS.PLAN_NAME,
    total_budget: DEFAULTS.TOTAL_BUDGET,
    ...overrides,
  };
}

/**
 * Generates a test ward rotation payload
 */
export function createWardRotationPayload(
  overrides: Partial<{ name: string; start_minute: number; end_minute: number }> = {}
): { name: string; start_minute: number; end_minute: number } {
  const startMinute = createScheduleMinute(100);
  const endMinute = addMinutes(startMinute, DEFAULTS.ROTATION_DURATION_MINUTES);

  return {
    name: DEFAULTS.ROTATION_NAME,
    start_minute: startMinute,
    end_minute: endMinute,
    ...overrides,
  };
}

/**
 * Generates a test procedure payload
 */
export function createProcedurePayload(
  overrides: Partial<{ procedure_type: string; required_certification: string; start_minute: number; end_minute: number; secondary_resource_requirements?: string[] }> = {}
): { procedure_type: string; required_certification: string; start_minute: number; end_minute: number; secondary_resource_requirements?: string[] } {
  const startMinute = createScheduleMinute(100);
  const endMinute = addMinutes(startMinute, DEFAULTS.PROCEDURE_DURATION_MINUTES);

  const base: any = {
    procedure_type: DEFAULTS.PROCEDURE_TYPE,
    required_certification: 'NONE',
    start_minute: startMinute,
    end_minute: endMinute,
  };

  if (overrides.secondary_resource_requirements !== undefined) {
    base.secondary_resource_requirements = overrides.secondary_resource_requirements;
  }

  return { ...base, ...overrides };
}

/**
 * Generates a test medical resource payload
 */
export function createMedicalResourcePayload(
  overrides: Partial<{ resource_name: string; resource_model: string; operating_cost_per_minute: number; maintenance_threshold_override?: number | null; sterilization_buffer_override?: number | null; setup_overhead_minutes?: number; teardown_overhead_minutes?: number }> = {}
): { resource_name: string; resource_model: string; operating_cost_per_minute: number; maintenance_threshold_override?: number | null; sterilization_buffer_override?: number | null; setup_overhead_minutes?: number; teardown_overhead_minutes?: number } {
  const base: any = {
    resource_name: DEFAULTS.RESOURCE_NAME,
    resource_model: DEFAULTS.RESOURCE_MODEL,
    operating_cost_per_minute: DEFAULTS.OPERATING_COST_PER_MINUTE,
  };
  
  if (overrides.maintenance_threshold_override !== undefined) {
    base.maintenance_threshold_override = overrides.maintenance_threshold_override;
  }
  
  if (overrides.sterilization_buffer_override !== undefined) {
    base.sterilization_buffer_override = overrides.sterilization_buffer_override;
  }

  if (overrides.setup_overhead_minutes !== undefined) {
    base.setup_overhead_minutes = overrides.setup_overhead_minutes;
  }

  if (overrides.teardown_overhead_minutes !== undefined) {
    base.teardown_overhead_minutes = overrides.teardown_overhead_minutes;
  }
  
  return { ...base, ...overrides };
}

/**
 * Generates a test resource certification
 */
export function createResourceCertification(
  name: 'BSL-3_CERTIFIED' | 'CARDIAC_CATHETERIZATION_LAB',
  overrides: Partial<{ id: string; applied_date: string }> = {}
): { id: string; name: 'BSL-3_CERTIFIED' | 'CARDIAC_CATHETERIZATION_LAB'; applied_date: string } {
  const today = new Date();
  const appliedDate = new Date(today.getFullYear(), today.getMonth(), today.getDate());

  return {
    id: uuidv4(),
    name: name,
    applied_date: appliedDate.toISOString().split('T')[0],
    ...overrides,
  };
}

/**
 * Generates a test resource certification payload
 */
export function createResourceCertificationPayload(
  name: 'BSL-3_CERTIFIED' | 'CARDIAC_CATHETERIZATION_LAB',
  applied_date: string = '2023-01-01'
): { name: string, applied_date: string } {
  return {
    name: name,
    applied_date: applied_date
  };
}

/**
 * Generates a test assignment payload
 */
export function createAssignmentPayload(
  procedureId: string,
  resourceId: string,
  overrides: Partial<AssignmentPayload> = {}
): AssignmentPayload {
  return {
    procedure_id: procedureId,
    resource_id: resourceId,
    override_protocol_check: false,
    ...overrides,
  };
}

/**
 * Generates a test infection risk pairing payload
 */
export function createInfectionRiskPairingPayload(
  resourceId1: string,
  resourceId2: string,
  overrides: Partial<{ resource_id_1: string; resource_id_2: string; reason?: string }> = {}
): { resource_id_1: string; resource_id_2: string; reason?: string } {
  return {
    resource_id_1: resourceId1,
    resource_id_2: resourceId2,
    reason: 'Test infection risk reason',
    ...overrides,
  };
}

/**
 * Complex scenario builders
 */

export interface PlanScenario {
  plan: TreatmentPlan;
  rotations: WardRotation[];
  procedures: Procedure[];
  resources: MedicalResource[];
  assignments: Assignment[];
  pairings: InfectionRiskPairing[];
}

/**
 * Helper function to set up a basic plan with one medical resource for tests.
 */
export async function setupBasicPlan(options: { total_budget?: number; operating_cost_per_minute?: number } = {}) {
  const planRes = await apiClient.createTreatmentPlan(
    createTreatmentPlanPayload({ plan_name: 'Advanced Test Plan', total_budget: options.total_budget || 250000.00 }),
    TEST_USERS.chargeNurseHeaders
  );
  const plan = getSuccessData<TreatmentPlan>(planRes);
  await apiClient.activateTreatmentPlan(plan.id, TEST_USERS.chargeNurseHeaders);

  const rotationRes = await apiClient.createWardRotation(plan.id, createWardRotationPayload({ name: 'Advanced Test Rotation' }), TEST_USERS.physicianHeaders);
  const rotation = getSuccessData<WardRotation>(rotationRes);

  const resourceRes = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'Test Resource', resource_model: 'standard-resource', operating_cost_per_minute: options.operating_cost_per_minute || 10.0 }), TEST_USERS.physicianHeaders);
  const resource = getSuccessData<MedicalResource>(resourceRes);

  return { planId: plan.id, rotationId: rotation.id, resourceId: resource.id, physicianHeaders: TEST_USERS.physicianHeaders, chargeNurseHeaders: TEST_USERS.chargeNurseHeaders };
}

export async function createAndScheduleProcedure(planId: string, rotationId: string, resourceId: string, procedureData: Partial<{ procedure_type: string; required_certification: string; start_minute: number; end_minute: number }>) {
  const procedureRes = await apiClient.createProcedure(
    planId,
    rotationId,
    createProcedurePayload(procedureData),
    TEST_USERS.physicianHeaders
  );
  const procedure = getSuccessData<Procedure>(procedureRes);

  const assignmentRes = await apiClient.createAssignment(
    planId,
    createAssignmentPayload(procedure.id, resourceId),
    TEST_USERS.physicianHeaders
  );
  const assignment = getSuccessData<Assignment>(assignmentRes);

  await apiClient.protocolApproveAssignment(planId, assignment.id, TEST_USERS.chargeNurseHeaders);
  await apiClient.scheduleAssignment(planId, assignment.id, TEST_USERS.chargeNurseHeaders);

  return procedure;
}

export async function createAndScheduleProcedures(
  planId: string,
  rotationId: string,
  resourceId: string,
  options: {
    count: number;
    minutes: number;
    start_minute?: number;
    spacing_minutes?: number;
  }
) {
  const { count, minutes, start_minute = 1000, spacing_minutes = 0 } = options;
  const procedures = [];
  let current_start_minute = start_minute;

  for (let i = 0; i < count; i++) {
    const procedureData = {
      start_minute: current_start_minute,
      end_minute: addMinutes(current_start_minute, minutes),
    };
    const procedure = await createAndScheduleProcedure(planId, rotationId, resourceId, procedureData);
    procedures.push(procedure);
    current_start_minute = addMinutes(procedure.end_minute, spacing_minutes);
  }
  return procedures;
}

export async function completeProcedure(planId: string, rotationId: string, procedureId: string) {
  const resourceRes = await apiClient.createMedicalResource(
    planId,
    createMedicalResourcePayload({ resource_name: `Resource for ${procedureId}` }),
    TEST_USERS.physicianHeaders
  );
  const resource = getSuccessData<MedicalResource>(resourceRes);

  const assignmentRes = await apiClient.createAssignment(
    planId,
    createAssignmentPayload(procedureId, resource.id),
    TEST_USERS.physicianHeaders
  );
  const assignment = getSuccessData<Assignment>(assignmentRes);

  await apiClient.protocolApproveAssignment(planId, assignment.id, TEST_USERS.chargeNurseHeaders);
  await apiClient.scheduleAssignment(planId, assignment.id, TEST_USERS.chargeNurseHeaders);

  await apiClient.initiateFinalReview(planId, TEST_USERS.chargeNurseHeaders);
  await apiClient.finalizePlan(planId, TEST_USERS.adminHeaders);
}

export async function createAndActivatePlan(
  budget: number = 250000.00,
  planName: string = DEFAULTS.PLAN_NAME
): Promise<TreatmentPlan> {
  const planRes = await apiClient.createTreatmentPlan(
    createTreatmentPlanPayload({ total_budget: budget, plan_name: planName }),
    TEST_USERS.chargeNurseHeaders
  );
  const plan = getSuccessData<TreatmentPlan>(planRes);

  const activateRes = await apiClient.activateTreatmentPlan(plan.id, TEST_USERS.chargeNurseHeaders);
  return getSuccessData<TreatmentPlan>(activateRes);
}

export async function createAndConfirmAssignment(
  planId: string,
  rotationId: string,
  resourceId: string,
  procedureOverrides: Partial<{ procedure_type: string; required_certification: string; start_minute: number; end_minute: number }>,
  existingProcedure?: Procedure,
  assignmentOverrides: Partial<AssignmentPayload> = {}
): Promise<{ procedure: Procedure; assignment: Assignment }> {
  let procedure: Procedure;

  if (existingProcedure) {
    procedure = existingProcedure;
  } else {
    const procedureRes = await apiClient.createProcedure(
      planId,
      rotationId,
      createProcedurePayload(procedureOverrides),
      TEST_USERS.physicianHeaders
    );
    procedure = getSuccessData<Procedure>(procedureRes);
  }

  const assignmentRes = await apiClient.createAssignment(
    planId,
    createAssignmentPayload(procedure.id, resourceId, assignmentOverrides),
    TEST_USERS.physicianHeaders
  );
  const assignment = getSuccessData<Assignment>(assignmentRes);

  await apiClient.protocolApproveAssignment(planId, assignment.id, TEST_USERS.chargeNurseHeaders);
  const confirmedAssignmentRes = await apiClient.scheduleAssignment(planId, assignment.id, TEST_USERS.chargeNurseHeaders);
  getSuccessData(confirmedAssignmentRes);

  const finalAssignmentRes = await apiClient.getAssignment(planId, assignment.id, TEST_USERS.physicianHeaders);
  const confirmedAssignment = getSuccessData<Assignment>(finalAssignmentRes);

  return { procedure: procedure, assignment: confirmedAssignment };
}

/**
 * Creates a new, active treatment plan.
 * @returns The created TreatmentPlan.
 */
export async function setupActivePlan(): Promise<TreatmentPlan> {
  const createPlanPayload = createTreatmentPlanPayload({});
  const planResponse = await apiClient.createTreatmentPlan(createPlanPayload, TEST_USERS.chargeNurseHeaders);
  const plan = getSuccessData<TreatmentPlan>(planResponse);
  const activatedPlanResponse = await apiClient.activateTreatmentPlan(plan.id, TEST_USERS.chargeNurseHeaders);
  return getSuccessData<TreatmentPlan>(activatedPlanResponse);
}

/**
 * Creates a plan, a rotation, a procedure, and a medical resource.
 * @returns An object containing the created resources.
 */
export async function setupBasicScenario() {
  const plan = await setupActivePlan();

  const createRotationPayload = createWardRotationPayload({});
  const rotationResponse = await apiClient.createWardRotation(plan.id, createRotationPayload, TEST_USERS.physicianHeaders);
  const rotation = getSuccessData<WardRotation>(rotationResponse);

  const createResourcePayload = createMedicalResourcePayload({});
  const resourceResponse = await apiClient.createMedicalResource(plan.id, createResourcePayload, TEST_USERS.physicianHeaders);
  const resource = getSuccessData<MedicalResource>(resourceResponse);

  const procedurePayload = createProcedurePayload({});
  const procedureResponse = await apiClient.createProcedure(plan.id, rotation.id, procedurePayload, TEST_USERS.physicianHeaders);
  const procedure = getSuccessData<Procedure>(procedureResponse);

  return { plan, rotation, resource, procedure };
}

/**
 * Creates a fully scheduled procedure, ready for final review.
 * @returns An object containing the created and scheduled resources.
 */
export async function setupScheduledProcedure() {
  const { plan, rotation, resource, procedure } = await setupBasicScenario();

  const assignmentPayload = createAssignmentPayload(procedure.id, resource.id);
  const assignmentResponse = await apiClient.createAssignment(plan.id, assignmentPayload, TEST_USERS.physicianHeaders);
  const assignment = getSuccessData<Assignment>(assignmentResponse);

  const protocolResponse = await apiClient.protocolApproveAssignment(plan.id, assignment.id, TEST_USERS.chargeNurseHeaders);
  getSuccessData(protocolResponse);

  const scheduleResponse = await apiClient.scheduleAssignment(plan.id, assignment.id, TEST_USERS.chargeNurseHeaders);
  const finalAssignment = getSuccessData<Assignment>(scheduleResponse);

  const finalProcedureResponse = await apiClient.getProcedure(plan.id, rotation.id, procedure.id, TEST_USERS.adminHeaders);
  const finalProcedure = getSuccessData<Procedure>(finalProcedureResponse);

  return { plan, rotation, resource, procedure: finalProcedure, assignment: finalAssignment };
}

/**
 * Creates an active plan with a ward rotation and a medical resource.
 * This is a common pattern used in many business logic tests.
 */
export async function setupPlanWithRotationAndResource(
  overrides?: {
    planBudget?: number;
    rotationPayload?: Partial<{ name: string; start_minute: number; end_minute: number }>;
    resourcePayload?: Partial<{ resource_name: string; resource_model: string; operating_cost_per_minute: number }>;
  }
) {
  const plan = await createAndActivatePlan(overrides?.planBudget);

  const rotationRes = await apiClient.createWardRotation(
    plan.id,
    createWardRotationPayload(overrides?.rotationPayload || {}),
    TEST_USERS.physicianHeaders
  );
  const rotation = getSuccessData<WardRotation>(rotationRes);

  const resourceRes = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload(overrides?.resourcePayload || {}),
    TEST_USERS.physicianHeaders
  );
  const resource = getSuccessData<MedicalResource>(resourceRes);

  return { plan, rotation, resource };
}

/**
 * Sets up a plan with a resource that has a specified amount of minutes already used.
 */
export async function setupPlanWithHighUsageResource(
  minutesUsed: number,
  options: {
    planId?: string;
    total_budget?: number;
    operating_cost_per_minute?: number;
  } = {}
) {
  let planId = options.planId;
  if (!planId) {
    const planRes = await apiClient.createTreatmentPlan(
      createTreatmentPlanPayload({ total_budget: options.total_budget || 1000000 }),
      TEST_USERS.chargeNurseHeaders
    );
    const plan = getSuccessData<TreatmentPlan>(planRes);
    await apiClient.activateTreatmentPlan(plan.id, TEST_USERS.chargeNurseHeaders);
    planId = plan.id;
  }

  const rotationRes = await apiClient.createWardRotation(planId, createWardRotationPayload(), TEST_USERS.physicianHeaders);
  const rotation = getSuccessData<WardRotation>(rotationRes);

  const resourceRes = await apiClient.createMedicalResource(
    planId,
    createMedicalResourcePayload({ operating_cost_per_minute: options.operating_cost_per_minute || 1.0 }),
    TEST_USERS.physicianHeaders
  );
  const resource = getSuccessData<MedicalResource>(resourceRes);

  if (minutesUsed > 0) {
    const procedureRes = await apiClient.createProcedure(
      planId,
      rotation.id,
      createProcedurePayload({ start_minute: 0, end_minute: minutesUsed }),
      TEST_USERS.physicianHeaders
    );
    const procedure = getSuccessData<Procedure>(procedureRes);
    const assignment = await createAndProtocolApproveAssignment(planId, procedure.id, resource.id);
    await apiClient.scheduleAssignment(planId, assignment.id, TEST_USERS.chargeNurseHeaders);
  }

  return {
    planId,
    rotationId: rotation.id,
    resourceId: resource.id,
    physicianHeaders: TEST_USERS.physicianHeaders,
    chargeNurseHeaders: TEST_USERS.chargeNurseHeaders,
    adminHeaders: TEST_USERS.adminHeaders,
  };
}

/**
 * Creates an assignment and gets it protocol approved.
 * This is a common pattern in assignment-related tests.
 */
export async function createAndProtocolApproveAssignment(
  planId: string,
  procedureId: string,
  resourceId: string,
  overrideProtocolCheck: boolean = false
) {
  const assignmentRes = await apiClient.createAssignment(
    planId,
    createAssignmentPayload(procedureId, resourceId, {
      override_protocol_check: overrideProtocolCheck
    }),
    TEST_USERS.physicianHeaders
  );
  const assignment = getSuccessData<Assignment>(assignmentRes);

  await apiClient.protocolApproveAssignment(planId, assignment.id, TEST_USERS.chargeNurseHeaders);

  return assignment;
}

/**
 * Creates a procedure with the given payload.
 * Simplifies procedure creation in tests.
 */
export async function createProcedureInRotation(
  planId: string,
  rotationId: string,
  procedurePayload?: Partial<{ procedure_type: string; required_certification: string; start_minute: number; end_minute: number }>
) {
  const plan = await apiClient.getTreatmentPlan(planId, TEST_USERS.chargeNurseHeaders).then(r => getSuccessData<TreatmentPlan>(r));
  if (plan.status !== 'ACTIVE') {
    await apiClient.activateTreatmentPlan(planId, TEST_USERS.chargeNurseHeaders);
  }

  const procedureRes = await apiClient.createProcedure(
    planId,
    rotationId,
    createProcedurePayload(procedurePayload || {}),
    TEST_USERS.physicianHeaders
  );

  return getSuccessData<Procedure>(procedureRes);
}

/**
 * Sets up a plan with low patient safety score by creating multiple high bio-risk assignments.
 * Useful for testing patient safety score threshold scenarios.
 * NOTE: Logic inversion - lower patient safety score is better in the hospital domain
 * @param targetSafetyScore - The desired patient safety score (default: 500)
 * @param planBudget - The plan budget (default: 10000)
 * @returns Plan with high patient safety score (which is bad), rotation, and medical resource
 */
export async function setupPlanWithHighSafetyScore(
  targetSafetyScore: number = 500,
  planBudget: number = 10000
) {
  const plan = await createAndActivatePlan(planBudget);

  const rotationRes = await apiClient.createWardRotation(
    plan.id,
    createWardRotationPayload(),
    TEST_USERS.physicianHeaders
  );
  const rotation = getSuccessData<WardRotation>(rotationRes);

  const resourceRes = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload(),
    TEST_USERS.physicianHeaders
  );
  const resource = getSuccessData<MedicalResource>(resourceRes);

  const bioriskPenalty = 50;
  const initialScore = 0;
  const requiredBioriskAssignments = Math.ceil((targetSafetyScore - initialScore) / bioriskPenalty);

  for (let i = 0; i < requiredBioriskAssignments; i++) {
    const procedureRes = await apiClient.createProcedure(
      plan.id,
      rotation.id,
      createProcedurePayload({
        start_minute: 7000 + (i * 200),
        end_minute: 7000 + (i * 200) + 50
      }),
      TEST_USERS.physicianHeaders
    );
    const procedure = getSuccessData<Procedure>(procedureRes);

    await apiClient.createAssignment(
      plan.id,
      createAssignmentPayload(procedure.id, resource.id),
      TEST_USERS.physicianHeaders
    );
  }

  return { plan, rotation, resource };
}

/**
 * Sets up a plan and intentionally raises its patient safety score by creating a specified
 * number of high bio-risk procedures. This is a fixture for testing scenarios where
 * a high patient safety score (which is bad) is a precondition.
 * NOTE: Logic inversion - in hospital domain, lower score is better
 *
 * @param {object} options - The configuration options for the setup.
 * @param {number} [options.numBioriskProcedures=10] - The number of bio-risk procedures to create to raise the score.
 * @param {number} [options.planBudget=20000.00] - The initial budget for the plan.
 * @param {number} [options.resourceCost=2.00] - The cost per minute for the medical resource.
 * @returns {Promise<{plan: TreatmentPlan, resource: MedicalResource, rotation: WardRotation}>}
 *          A promise that resolves to an object containing the created plan, medical resource, and ward rotation.
 */
export async function setupPlanAndRaiseSafetyScore({
  planId,
  numBioriskProcedures = 10,
  planBudget = 200000.00,
  resourceCost = 2.00,
}: {
  planId?: string;
  numBioriskProcedures?: number,
  planBudget?: number,
  resourceCost?: number,
} = {}) {
  let plan: TreatmentPlan;
  let rotation: WardRotation;

  if (planId) {
    const planRes = await apiClient.getTreatmentPlan(planId, TEST_USERS.physicianHeaders);
    plan = getSuccessData<TreatmentPlan>(planRes);
    const rotationRes = await apiClient.createWardRotation(
      plan.id,
      createWardRotationPayload(),
      TEST_USERS.physicianHeaders
    );
    rotation = getSuccessData<WardRotation>(rotationRes);
  } else {
    const setup = await setupPlanWithRotation({
      planBudget,
    });
    plan = setup.plan;
    rotation = setup.rotation;
  }

  const mainResourceRes = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({
    resource_name: 'Main Test Resource',
    operating_cost_per_minute: resourceCost
  }), TEST_USERS.physicianHeaders);
  const resource = getSuccessData<MedicalResource>(mainResourceRes);

  const penaltyResourceRes = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({
    resource_name: 'Safety Penalty Resource',
    operating_cost_per_minute: resourceCost
  }), TEST_USERS.physicianHeaders);
  const penaltyResource = getSuccessData<MedicalResource>(penaltyResourceRes);


  let currentStartMinute = rotation.start_minute;
  let currentSafetyScore = 0;

  const normalProcedureMinutes = 5950;
  const normalProcedure = await createProcedureInRotation(plan.id, rotation.id, {
    procedure_type: 'SAME_TYPE',
    start_minute: currentStartMinute,
    end_minute: addMinutes(currentStartMinute, normalProcedureMinutes)
  });
  await createAndConfirmAssignment(plan.id, rotation.id, penaltyResource.id, {}, normalProcedure);

  currentStartMinute = addMinutes(currentStartMinute, normalProcedureMinutes + 30);

  for (let i = 0; i < numBioriskProcedures; i++) {
    const procedureMinutes = 101;
    const bioriskProcedure = await createProcedureInRotation(plan.id, rotation.id, {
      procedure_type: 'SAME_TYPE',
      start_minute: currentStartMinute,
      end_minute: addMinutes(currentStartMinute, procedureMinutes)
    });

    const scoreAfterPenalty = currentSafetyScore + 50;
    const needsOverride = scoreAfterPenalty >= 500;

    await createAndConfirmAssignment(plan.id, rotation.id, penaltyResource.id, {}, bioriskProcedure, { override_protocol_check: needsOverride });

    if (needsOverride) {
      currentSafetyScore += (50 + 100);
    } else {
      currentSafetyScore += 50;
    }

    currentStartMinute = addMinutes(currentStartMinute, procedureMinutes + 30);
  }

  return { plan, resource, rotation, resourceId: penaltyResource.id };
}

/**
 * Sets up a plan with a single procedure that has been fully scheduled, finalized,
 * and is ready for post-finalization assertions.
 *
 * @param {object} [options] - Optional setup parameters.
 * @param {number} [options.planBudget=1000.00] - The budget for the plan.
 * @param {number} [options.resourceCost=20.00] - The per-minute cost for the resource.
 * @returns {Promise<{plan: TreatmentPlan, assignment: Assignment}>}
 *          A promise resolving to the final plan state and the finalized assignment.
 */
export async function setupPlanWithFinalizedAssignment(options?: {
  planBudget?: number;
  resourceCost?: number;
}) {
  const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
    planBudget: options?.planBudget,
    resourcePayload: { operating_cost_per_minute: options?.resourceCost },
  });

  const procedureRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload({}),
    TEST_USERS.physicianHeaders
  );
  const procedure = getSuccessData<Procedure>(procedureRes);

  const { assignment } = await createAndConfirmAssignment(plan.id, rotation.id, resource.id, {}, procedure);

  await transitionRotationToReadyForAssignment(plan.id, rotation.id);

  await apiClient.initiateFinalReview(plan.id, TEST_USERS.chargeNurseHeaders);
  await apiClient.finalizePlan(plan.id, TEST_USERS.adminHeaders);

  const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, TEST_USERS.chargeNurseHeaders);
  const finalPlan = getSuccessData<TreatmentPlan>(finalPlanRes);

  return { plan: finalPlan, assignment };
}

/**
 * Creates a plan, a rotation, a procedure, and a medical resource.
 * @returns An object containing the created resources.
 */
export async function setupPlanWithRotation(
  overrides?: {
    planBudget?: number;
    rotationPayload?: Partial<{ name: string; start_minute: number; end_minute: number }>;
  }
) {
  const plan = await createAndActivatePlan(overrides?.planBudget);

  const rotationRes = await apiClient.createWardRotation(
    plan.id,
    createWardRotationPayload(overrides?.rotationPayload || {}),
    TEST_USERS.physicianHeaders
  );
  const rotation = getSuccessData<WardRotation>(rotationRes);

  return { plan, rotation };
}

/**
 * Creates two separate, active plans for data isolation testing.
 * @returns An object containing both created plans.
 */
export async function setupDataIsolationScenario() {
  const planA = await createAndActivatePlan(10000, 'Plan A');
  const planB = await createAndActivatePlan(10000, 'Plan B');

  return { planA, planB, chargeNurseHeaders: TEST_USERS.chargeNurseHeaders, physicianHeaders: TEST_USERS.physicianHeaders };
}

/**
 * Creates a plan with a rotation, a procedure, a resource, and a fully scheduled procedure.
 * @returns An object containing the created resources.
 */
export async function setupScenarioWithScheduledProcedure() {
  const plan = await createAndActivatePlan();
  const rotationRes = await apiClient.createWardRotation(
    plan.id,
    createWardRotationPayload(),
    TEST_USERS.physicianHeaders
  );
  const rotation = getSuccessData<WardRotation>(rotationRes);

  const procedureRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload(),
    TEST_USERS.physicianHeaders
  );
  const procedure = getSuccessData<Procedure>(procedureRes);

  const resourceRes = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload(),
    TEST_USERS.physicianHeaders
  );
  const resource = getSuccessData<MedicalResource>(resourceRes);

  const { assignment } = await createAndConfirmAssignment(plan.id, rotation.id, resource.id, {}, procedure);

  await transitionRotationToReadyForAssignment(plan.id, rotation.id);

  return { plan, rotation, procedure, resource, assignment, chargeNurseHeaders: TEST_USERS.chargeNurseHeaders, physicianHeaders: TEST_USERS.physicianHeaders, adminHeaders: TEST_USERS.adminHeaders };
}

/**
 * Creates multiple bio-risk assignments to reach a target safety score.
 * This is a common pattern for setting up tests that need specific safety score thresholds.
 */
export async function createBulkBioRiskAssignments(
  planId: string,
  rotationId: string,
  resources: MedicalResource[],
  targetScore: number,
  options: {
    procedureType?: string;
    startMinute?: number;
    procedureDuration?: number;
    spacing?: number;
    override?: boolean;
  } = {}
): Promise<Assignment[]> {
  const {
    procedureType = 'BioRiskProc',
    startMinute = 10000,
    procedureDuration = 50,
    spacing = 200,
    override = false,
  } = options;

  const assignments: Assignment[] = [];
  const plan = await apiClient.getTreatmentPlan(planId, TEST_USERS.chargeNurseHeaders)
    .then(r => getSuccessData<TreatmentPlan>(r));

  let currentScore = plan.patient_safety_score;
  let assignmentIndex = 0;
  let currentMinute = startMinute;

  const pointsPerAssignment = override ? 100 : 50;
  const neededAssignments = Math.ceil((targetScore - currentScore) / pointsPerAssignment);

  for (let i = 0; i < neededAssignments && assignmentIndex < resources.length; i++) {
    const resource = resources[assignmentIndex % resources.length];

    const procedureRes = await apiClient.createProcedure(
      planId,
      rotationId,
      createProcedurePayload({
        procedure_type: `${procedureType}${i}`,
        start_minute: currentMinute,
        end_minute: currentMinute + procedureDuration,
      }),
      TEST_USERS.physicianHeaders
    );
    const procedure = getSuccessData<Procedure>(procedureRes);

    const assignmentRes = await apiClient.createAssignment(
      planId,
      createAssignmentPayload(procedure.id, resource.id, { override_protocol_check: override }),
      TEST_USERS.physicianHeaders
    );
    const assignment = getSuccessData<Assignment>(assignmentRes);

    if (assignment.is_high_biorisk || override) {
      await apiClient.protocolApproveAssignment(planId, assignment.id, TEST_USERS.chargeNurseHeaders);
      await apiClient.scheduleAssignment(planId, assignment.id, TEST_USERS.chargeNurseHeaders);
      assignments.push(assignment);
    }

    assignmentIndex++;
    currentMinute += spacing;
  }

  return assignments;
}

/**
 * Creates a procedure and an assignment that is approved and scheduled.
 * This is the most common pattern in concurrency tests.
 */
export async function createScheduledAssignment(
  planId: string,
  rotationId: string,
  resourceId: string,
  procedureOptions?: Partial<{ procedure_type: string; required_certification: string; start_minute: number; end_minute: number }>,
  assignmentOptions?: { override_protocol_check?: boolean }
): Promise<{ procedure: Procedure; assignment: Assignment }> {
  const procedureRes = await apiClient.createProcedure(
    planId,
    rotationId,
    createProcedurePayload(procedureOptions || {}),
    TEST_USERS.physicianHeaders
  );
  const procedure = getSuccessData<Procedure>(procedureRes);

  const assignmentRes = await apiClient.createAssignment(
    planId,
    createAssignmentPayload(procedure.id, resourceId, assignmentOptions),
    TEST_USERS.physicianHeaders
  );
  const assignment = getSuccessData<Assignment>(assignmentRes);

  await apiClient.protocolApproveAssignment(planId, assignment.id, TEST_USERS.chargeNurseHeaders);
  const scheduledRes = await apiClient.scheduleAssignment(planId, assignment.id, TEST_USERS.chargeNurseHeaders);
  const scheduledAssignment = getSuccessData<Assignment>(scheduledRes);

  return { procedure, assignment: scheduledAssignment };
}

/**
 * Creates multiple scheduled assignments in a loop.
 * Common pattern for setting up many assignments for cascade/finalization tests.
 */
export async function createMultipleScheduledAssignments(
  planId: string,
  rotationId: string,
  resourceId: string,
  count: number,
  options: {
    procedureType?: string;
    startMinute?: number;
    procedureDuration?: number;
    spacing?: number;
    override?: boolean;
  } = {}
): Promise<Array<{ procedure: Procedure; assignment: Assignment }>> {
  const {
    procedureType = 'SAME_TYPE',
    startMinute = 100,
    procedureDuration = 60,
    spacing = 100,
    override = false,
  } = options;

  const results: Array<{ procedure: Procedure; assignment: Assignment }> = [];
  let currentMinute = startMinute;

  for (let i = 0; i < count; i++) {
    const procedureRes = await apiClient.createProcedure(
      planId,
      rotationId,
      createProcedurePayload({
        procedure_type: `${procedureType}`,
        start_minute: currentMinute,
        end_minute: currentMinute + procedureDuration,
      }),
      TEST_USERS.physicianHeaders
    );
    const procedure = getSuccessData<Procedure>(procedureRes);

    const assignmentRes = await apiClient.createAssignment(
      planId,
      createAssignmentPayload(procedure.id, resourceId, { override_protocol_check: override }),
      TEST_USERS.physicianHeaders
    );
    const assignment = getSuccessData<Assignment>(assignmentRes);

    await apiClient.protocolApproveAssignment(planId, assignment.id, TEST_USERS.chargeNurseHeaders);
    await apiClient.scheduleAssignment(planId, assignment.id, TEST_USERS.chargeNurseHeaders);

    results.push({ procedure, assignment });
    currentMinute += spacing;
  }

  return results;
}

/**
 * Sets up a plan ready for finalization testing.
 * Creates plan, rotation, resource, and scheduled assignments, then transitions to FINAL_REVIEW_PENDING.
 */
export async function setupFinalizationReadyScenario(options: {
  planBudget?: number;
  numAssignments?: number;
  resourceCostPerMinute?: number;
} = {}): Promise<{
  plan: TreatmentPlan;
  rotation: WardRotation;
  resource: MedicalResource;
  assignments: Assignment[];
  procedures: Procedure[];
}> {
  const { planBudget = 10000, numAssignments = 3, resourceCostPerMinute = 2 } = options;

  const { plan, rotation } = await setupPlanWithRotationAndResource({
    planBudget,
    resourcePayload: { operating_cost_per_minute: resourceCostPerMinute },
  });

  const resourceRes = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload({ operating_cost_per_minute: resourceCostPerMinute }),
    TEST_USERS.physicianHeaders
  );
  const resource = getSuccessData<MedicalResource>(resourceRes);

  const results = await createMultipleScheduledAssignments(plan.id, rotation.id, resource.id, numAssignments, {
    startMinute: 100,
    procedureDuration: 30,
    spacing: 50,
  });

  await transitionRotationToReadyForAssignment(plan.id, rotation.id);
  await apiClient.initiateFinalReview(plan.id, TEST_USERS.chargeNurseHeaders);

  return {
    plan,
    rotation,
    resource,
    assignments: results.map(r => r.assignment),
    procedures: results.map(r => r.procedure),
  };
}

/**
 * Creates a full test scenario: plan + rotation + resource + scheduled assignment.
 * Returns all entities for use in race condition tests.
 */
export async function setupRaceTestScenario(options: {
  planBudget?: number;
  resourceCostPerMinute?: number;
  procedureOptions?: Partial<{ procedure_type: string; start_minute: number; end_minute: number }>;
  includeScheduledAssignment?: boolean;
} = {}) {
  const {
    planBudget = 10000,
    resourceCostPerMinute = 10,
    procedureOptions = {},
    includeScheduledAssignment = false,
  } = options;

  const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
    planBudget,
    resourcePayload: { operating_cost_per_minute: resourceCostPerMinute },
  });

  const procedureRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload(procedureOptions),
    TEST_USERS.physicianHeaders
  );
  const procedure = getSuccessData<Procedure>(procedureRes);

  let assignment: Assignment | undefined;
  
  if (includeScheduledAssignment) {
    const assignmentRes = await apiClient.createAssignment(
      plan.id,
      createAssignmentPayload(procedure.id, resource.id),
      TEST_USERS.physicianHeaders
    );
    assignment = getSuccessData<Assignment>(assignmentRes);

    await apiClient.protocolApproveAssignment(plan.id, assignment.id, TEST_USERS.chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, assignment.id, TEST_USERS.chargeNurseHeaders);
  } else {
    const assignmentRes = await apiClient.createAssignment(
      plan.id,
      createAssignmentPayload(procedure.id, resource.id),
      TEST_USERS.physicianHeaders
    );
    assignment = getSuccessData<Assignment>(assignmentRes);
  }

  return {
    plan,
    rotation,
    resource,
    procedure,
    assignment,
    chargeNurseHeaders: TEST_USERS.chargeNurseHeaders,
    physicianHeaders: TEST_USERS.physicianHeaders,
    adminHeaders: TEST_USERS.adminHeaders,
  };
}

/**
 * Verifies the final state of entities after concurrent operations.
 * This is a common pattern for checking that race conditions resolve correctly.
 */
export async function verifyFinalEntityStates(
  planId: string,
  rotationId: string,
  procedureId: string,
  assignmentId: string,
  expectedStates: {
    planStatus?: string;
    rotationStatus?: string;
    procedureStatus?: string;
    assignmentStatus?: string;
  } = {}
): Promise<{
  plan: TreatmentPlan;
  rotation: WardRotation;
  procedure: Procedure;
  assignment: Assignment;
}> {
  const [planRes, rotationRes, procedureRes, assignmentRes] = await Promise.all([
    apiClient.getTreatmentPlan(planId, TEST_USERS.chargeNurseHeaders),
    apiClient.getWardRotation(planId, rotationId, TEST_USERS.chargeNurseHeaders),
    apiClient.getProcedure(planId, rotationId, procedureId, TEST_USERS.chargeNurseHeaders),
    apiClient.getAssignment(planId, assignmentId, TEST_USERS.chargeNurseHeaders),
  ]);

  const plan = getSuccessData<TreatmentPlan>(planRes);
  const rotation = getSuccessData<WardRotation>(rotationRes);
  const procedure = getSuccessData<Procedure>(procedureRes);
  const assignment = getSuccessData<Assignment>(assignmentRes);

  if (expectedStates.planStatus) {
    expect(plan.status).toBe(expectedStates.planStatus);
  }
  if (expectedStates.rotationStatus) {
    expect(rotation.status).toBe(expectedStates.rotationStatus);
  }
  if (expectedStates.procedureStatus) {
    expect(procedure.status).toBe(expectedStates.procedureStatus);
  }
  if (expectedStates.assignmentStatus) {
    expect(assignment.status).toBe(expectedStates.assignmentStatus);
  }

  return { plan, rotation, procedure, assignment };
}

export async function setupScenarioWithPendingProcedure() {
  const plan = await createAndActivatePlan();
  const rotationRes = await apiClient.createWardRotation(
    plan.id,
    createWardRotationPayload(),
    TEST_USERS.physicianHeaders
  );
  const rotation = getSuccessData<WardRotation>(rotationRes);

  const procedureRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload(),
    TEST_USERS.physicianHeaders
  );
  const procedure = getSuccessData<Procedure>(procedureRes);

  return { plan, rotation, procedure, chargeNurseHeaders: TEST_USERS.chargeNurseHeaders };
}

export async function setupScenarioWithProposedAssignment() {
  const plan = await createAndActivatePlan();
  const rotationRes = await apiClient.createWardRotation(
    plan.id,
    createWardRotationPayload(),
    TEST_USERS.physicianHeaders
  );
  const rotation = getSuccessData<WardRotation>(rotationRes);
  const procedureRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload(),
    TEST_USERS.physicianHeaders
  );
  const procedure = getSuccessData<Procedure>(procedureRes);
  const resourceRes = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload(),
    TEST_USERS.physicianHeaders
  );
  const resource = getSuccessData<MedicalResource>(resourceRes);
  const assignmentRes = await apiClient.createAssignment(
    plan.id,
    createAssignmentPayload(procedure.id, resource.id),
    TEST_USERS.physicianHeaders
  );
  const assignment = getSuccessData<Assignment>(assignmentRes);
  return { plan, rotation, resource, procedure, assignment, chargeNurseHeaders: TEST_USERS.chargeNurseHeaders, physicianHeaders: TEST_USERS.physicianHeaders };
}

export async function setupWithPairedResources() {
  const { plan, rotation } = await setupPlanWithRotation();

  const resourceARes = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload({ resource_name: 'Resource A' }),
    TEST_USERS.physicianHeaders
  );
  const resourceA = getSuccessData<MedicalResource>(resourceARes);

  const resourceBRes = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload({ resource_name: 'Resource B' }),
    TEST_USERS.physicianHeaders
  );
  const resourceB = getSuccessData<MedicalResource>(resourceBRes);

  await apiClient.createInfectionRiskPairing(
    plan.id,
    createInfectionRiskPairingPayload(resourceA.id, resourceB.id),
    TEST_USERS.chargeNurseHeaders
  );

  return { plan, rotation, resourceA, resourceB };
}

export async function setupPlanWithTwoHighUsageResources() {
  const plan = await createAndActivatePlan();
  const resourceA = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload({ resource_name: 'Resource A', operating_cost_per_minute: 10.0 }),
    TEST_USERS.physicianHeaders
  ).then(r => getSuccessData<MedicalResource>(r));
  const resourceB = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload({ resource_name: 'Resource B', operating_cost_per_minute: 10.0 }),
    TEST_USERS.physicianHeaders
  ).then(r => getSuccessData<MedicalResource>(r));


  return { plan, resourceA, resourceB };
}

export async function setupResourceWithOneScheduledAssignment() {
  const { plan, rotation, resource, procedure, assignment, chargeNurseHeaders, physicianHeaders } = await setupScenarioWithScheduledProcedure();
  return { plan, rotation, resource, assignmentToCancel: assignment, chargeNurseHeaders, physicianHeaders };
}

/**
 * Creates a plan, rotation, resource, and a fully scheduled assignment - the most common test setup pattern.
 * This combines setupPlanWithRotationAndResource with procedure and assignment creation.
 */
export async function setupBasicScheduledScenario(options: {
  planBudget?: number;
  rotationPayload?: Partial<{ name: string; start_minute: number; end_minute: number }>;
  resourcePayload?: Partial<{ resource_name: string; resource_model: string; operating_cost_per_minute: number }>;
  procedurePayload?: Partial<{ procedure_type: string; required_certification: string; start_minute: number; end_minute: number }>;
} = {}) {
  const { plan, rotation, resource } = await setupPlanWithRotationAndResource(options);

  const procedureRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload(options.procedurePayload || {}),
    TEST_USERS.physicianHeaders
  );
  const procedure = getSuccessData<Procedure>(procedureRes);

  const assignmentRes = await apiClient.createAssignment(
    plan.id,
    createAssignmentPayload(procedure.id, resource.id),
    TEST_USERS.physicianHeaders
  );
  const assignment = getSuccessData<Assignment>(assignmentRes);

  await apiClient.protocolApproveAssignment(plan.id, assignment.id, TEST_USERS.chargeNurseHeaders);
  await apiClient.scheduleAssignment(plan.id, assignment.id, TEST_USERS.chargeNurseHeaders);

  return {
    plan,
    rotation,
    resource,
    procedure,
    assignment,
    chargeNurseHeaders: TEST_USERS.chargeNurseHeaders,
    physicianHeaders: TEST_USERS.physicianHeaders,
    adminHeaders: TEST_USERS.adminHeaders,
  };
}

export async function createAndScheduleAssignment(
  planId: string,
  rotationId: string,
  resourceId: string,
  procedureData: Partial<{ procedure_type: string; required_certification: string; start_minute: number; end_minute: number }>,
  options: { override_protocol_check?: boolean } = {}
) {
  const procedureRes = await apiClient.createProcedure(
    planId,
    rotationId,
    createProcedurePayload(procedureData),
    TEST_USERS.physicianHeaders
  );
  const procedure = getSuccessData<Procedure>(procedureRes);

  const assignmentRes = await apiClient.createAssignment(
    planId,
    createAssignmentPayload(procedure.id, resourceId, options),
    TEST_USERS.physicianHeaders
  );
  const assignment = getSuccessData<Assignment>(assignmentRes);

  await apiClient.protocolApproveAssignment(planId, assignment.id, TEST_USERS.chargeNurseHeaders);
  await apiClient.scheduleAssignment(planId, assignment.id, TEST_USERS.chargeNurseHeaders);

  return assignment;
}

export async function getAssignmentState(planId: string, assignmentId: string) {
  const res = await apiClient.getAssignment(planId, assignmentId, TEST_USERS.physicianHeaders);
  return getSuccessData<Assignment>(res);
}

export async function getPlanState(planId: string) {
  const planRes = await apiClient.getTreatmentPlan(planId, TEST_USERS.chargeNurseHeaders);
  return getSuccessData<TreatmentPlan>(planRes);
}

export async function setupTestEnvironment(options: { budget?: number } = {}) {
  const planRes = await apiClient.createTreatmentPlan(
    createTreatmentPlanPayload({ total_budget: options.budget || 10000 }),
    TEST_USERS.chargeNurseHeaders
  );
  const plan = getSuccessData<TreatmentPlan>(planRes);
  await apiClient.activateTreatmentPlan(plan.id, TEST_USERS.chargeNurseHeaders);

  const rotationRes = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), TEST_USERS.physicianHeaders);
  const rotation = getSuccessData<WardRotation>(rotationRes);

  const resourceRes = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload(), TEST_USERS.physicianHeaders);
  const resource = getSuccessData<MedicalResource>(resourceRes);

  return {
    planId: plan.id,
    rotationId: rotation.id,
    resourceId: resource.id,
    physicianHeaders: TEST_USERS.physicianHeaders,
    chargeNurseHeaders: TEST_USERS.chargeNurseHeaders,
    adminHeaders: TEST_USERS.adminHeaders,
  };
}

export async function createTreatmentPlan(
  payload: Partial<{ plan_name: string; total_budget: number }> = {},
  activate: boolean = true
) {
  const createPayload = createTreatmentPlanPayload(payload);
  const planRes = await apiClient.createTreatmentPlan(createPayload, TEST_USERS.chargeNurseHeaders);
  let plan = getSuccessData<TreatmentPlan>(planRes);
  if (activate) {
    const activatedRes = await apiClient.activateTreatmentPlan(plan.id, TEST_USERS.chargeNurseHeaders);
    plan = getSuccessData<TreatmentPlan>(activatedRes);
  }
  return plan;
}

export async function createWardRotation(
  planId: string,
  payload: Partial<{ name: string; start_minute: number; end_minute: number }> = {},
  activate: boolean = true
) {
  if (activate) {
    const plan = await apiClient.getTreatmentPlan(planId, TEST_USERS.chargeNurseHeaders).then(r => getSuccessData<TreatmentPlan>(r));
    if (plan.status !== 'ACTIVE') {
      await apiClient.activateTreatmentPlan(planId, TEST_USERS.chargeNurseHeaders);
    }
  }
  const createPayload = createWardRotationPayload(payload);
  const rotationRes = await apiClient.createWardRotation(planId, createPayload, TEST_USERS.physicianHeaders);
  return getSuccessData<WardRotation>(rotationRes);
}

export async function createProcedure(
  planId: string,
  rotationId: string,
  payload: Partial<{ procedure_type: string; required_certification: string; start_minute: number; end_minute: number }> = {},
  activate: boolean = true
) {
  if (activate) {
    const plan = await apiClient.getTreatmentPlan(planId, TEST_USERS.chargeNurseHeaders).then(r => getSuccessData<TreatmentPlan>(r));
    if (plan.status !== 'ACTIVE') {
      await apiClient.activateTreatmentPlan(planId, TEST_USERS.chargeNurseHeaders);
    }
  }
  const createPayload = createProcedurePayload(payload);
  const procedureRes = await apiClient.createProcedure(planId, rotationId, createPayload, TEST_USERS.physicianHeaders);
  return getSuccessData<Procedure>(procedureRes);
}

/**
 * Transitions a ward rotation to READY_FOR_ASSIGNMENT status.
 * This should be called after all procedures in the rotation have been assigned.
 * @param planId - The ID of the treatment plan
 * @param rotationId - The ID of the ward rotation
 * @returns The updated ward rotation
 */
export async function transitionRotationToReadyForAssignment(
  planId: string,
  rotationId: string
): Promise<WardRotation> {
  const updateRes = await apiClient.updateWardRotationStatus(
    planId,
    rotationId,
    { status: WardRotationStatus.READY_FOR_ASSIGNMENT },
    TEST_USERS.chargeNurseHeaders
  );

  return getSuccessData<WardRotation>(updateRes);
}

/**
 * Creates a maintenance event payload
 */
export function createMaintenanceEventPayload(
  resourceId: string,
  atMinute: number
): { resource_id: string; at_minute: number } {
  return {
    resource_id: resourceId,
    at_minute: atMinute,
  };
}

/**
 * Creates a resource hold payload
 */
export function createResourceHoldPayload(
  resourceId: string,
  startMinute: number,
  endMinute: number,
  reason?: string
): { resource_id: string; start_minute: number; end_minute: number; reason?: string } {
  const payload: any = {
    resource_id: resourceId,
    start_minute: startMinute,
    end_minute: endMinute,
  };
  if (reason !== undefined) {
    payload.reason = reason;
  }
  return payload;
}

/**
 * Creates a treatment plan with policies
 */
export function createTreatmentPlanWithPoliciesPayload(
  overrides: Partial<{ plan_name: string; total_budget: number; policies: { require_admin_auth_for_overrides: boolean } }> = {}
): { plan_name: string; total_budget: number; policies?: { require_admin_auth_for_overrides: boolean } } {
  const payload: any = {
    plan_name: overrides.plan_name || DEFAULTS.PLAN_NAME,
    total_budget: overrides.total_budget || DEFAULTS.TOTAL_BUDGET,
  };
  if (overrides.policies) {
    payload.policies = overrides.policies;
  }
  return payload;
}

/**
 * Helper to accumulate minutes on a resource by creating and scheduling assignments
 */
export async function accumulateMinutesOnResource(
  planId: string,
  rotationId: string,
  resourceId: string,
  totalMinutes: number,
  startMinute: number = 0
): Promise<Assignment[]> {
  const assignments: Assignment[] = [];

  const procedureRes = await apiClient.createProcedure(
    planId,
    rotationId,
    createProcedurePayload({
      procedure_type: 'AccumulationProcedure',
      start_minute: startMinute,
      end_minute: startMinute + totalMinutes,
    }),
    TEST_USERS.physicianHeaders
  );
  const procedure = getSuccessData<Procedure>(procedureRes);

  const assignmentRes = await apiClient.createAssignment(
    planId,
    createAssignmentPayload(procedure.id, resourceId),
    TEST_USERS.physicianHeaders
  );
  const assignment = getSuccessData<Assignment>(assignmentRes);

  await apiClient.protocolApproveAssignment(planId, assignment.id, TEST_USERS.chargeNurseHeaders);
  await apiClient.scheduleAssignment(planId, assignment.id, TEST_USERS.chargeNurseHeaders);

  const scheduledAssignment = await apiClient.getAssignment(planId, assignment.id, TEST_USERS.chargeNurseHeaders)
    .then(r => getSuccessData<Assignment>(r));
  
  assignments.push(scheduledAssignment);

  return assignments;
}

/**
 * Primes the PatientSafetyScoreLedger by creating minimal high-biorisk proposals.
 * Assumptions:
 *  - The resource has already accumulated usage beyond the maintenance threshold
 *    (e.g., via accumulateMinutesOnResource), so any new 1-minute proposal will be high-biorisk
 *    under forward-looking semantics.
 *  - Uses non-overlapping 1-minute windows far in the future to avoid conflicts.
 */
export async function primeSafetyScoreTo(
  planId: string,
  rotationId: string,
  resourceId: string,
  targetScore: number = 450,
  startMinute: number = 100000
): Promise<void> {
  const plan = await apiClient.getTreatmentPlan(planId, TEST_USERS.chargeNurseHeaders)
    .then(r => getSuccessData<TreatmentPlan>(r));

  let current = plan.patient_safety_score;
  if (current >= targetScore) return;

  const neededIncrements = Math.ceil((targetScore - current) / 50);

  for (let i = 0; i < neededIncrements; i++) {
    const s = startMinute + i * 3;
    const e = s + 1;

    const procRes = await apiClient.createProcedure(
      planId,
      rotationId,
      createProcedurePayload({ start_minute: s, end_minute: e }),
      TEST_USERS.physicianHeaders
    );
    const proc = getSuccessData<Procedure>(procRes);

    const assignRes = await apiClient.createAssignment(
      planId,
      createAssignmentPayload(proc.id, resourceId),
      TEST_USERS.physicianHeaders
    );
    getSuccessData<Assignment>(assignRes);
  }
}

/**
 * Creates a scheduled assignment that brings a resource to exactly 6000 minutes of usage.
 * This is commonly used to set up resources at the bio-risk threshold for testing.
 * 
 * @param planId - The treatment plan ID
 * @param rotationId - The ward rotation ID
 * @param resourceId - The medical resource ID
 * @param startMinute - Starting minute for the procedure (default: 0)
 * @param procedureType - Type of procedure (default: 'Setup')
 * @returns The created and scheduled assignment
 */
export async function createBioRiskThresholdAssignment(
  planId: string,
  rotationId: string,
  resourceId: string,
  startMinute: number = 0,
  procedureType: string = 'Setup'
): Promise<Assignment> {
  const procedureRes = await apiClient.createProcedure(
    planId,
    rotationId,
    createProcedurePayload({
      procedure_type: procedureType,
      start_minute: startMinute,
      end_minute: startMinute + 6000,
    }),
    TEST_USERS.physicianHeaders
  );
  const procedure = getSuccessData<Procedure>(procedureRes);

  const assignmentRes = await apiClient.createAssignment(
    planId,
    createAssignmentPayload(procedure.id, resourceId),
    TEST_USERS.physicianHeaders
  );
  const assignment = getSuccessData<Assignment>(assignmentRes);

  await apiClient.protocolApproveAssignment(planId, assignment.id, TEST_USERS.chargeNurseHeaders);
  await apiClient.scheduleAssignment(planId, assignment.id, TEST_USERS.chargeNurseHeaders);

  return assignment;
}

/**
 * Creates a high-risk assignment (assumes resource already at 6000+ minutes).
 * Optionally applies protocol override and/or schedules the assignment.
 * 
 * @param planId - The treatment plan ID
 * @param rotationId - The ward rotation ID  
 * @param resourceId - The medical resource ID
 * @param startMinute - Starting minute for the procedure
 * @param endMinute - Ending minute for the procedure
 * @param options - Additional options (override, procedureType, shouldSchedule)
 * @returns The created high-risk assignment
 */
export async function createHighRiskAssignment(
  planId: string,
  rotationId: string,
  resourceId: string,
  startMinute: number,
  endMinute: number,
  options: {
    override?: boolean;
    procedureType?: string;
    shouldSchedule?: boolean;
  } = {}
): Promise<Assignment> {
  const procedureRes = await apiClient.createProcedure(
    planId,
    rotationId,
    createProcedurePayload({
      procedure_type: options.procedureType || 'HighRisk',
      start_minute: startMinute,
      end_minute: endMinute,
    }),
    TEST_USERS.physicianHeaders
  );
  const procedure = getSuccessData<Procedure>(procedureRes);

  const assignmentRes = await apiClient.createAssignment(
    planId,
    createAssignmentPayload(procedure.id, resourceId, {
      override_protocol_check: options.override || false,
    }),
    TEST_USERS.physicianHeaders
  );
  const assignment = getSuccessData<Assignment>(assignmentRes);

  if (options.shouldSchedule) {
    await apiClient.protocolApproveAssignment(planId, assignment.id, TEST_USERS.chargeNurseHeaders);
    await apiClient.scheduleAssignment(planId, assignment.id, TEST_USERS.chargeNurseHeaders);
    
    return await apiClient.getAssignment(planId, assignment.id, TEST_USERS.chargeNurseHeaders)
      .then(r => getSuccessData<Assignment>(r));
  }

  return assignment;
}

/**
 * Creates multiple medical resources in bulk.
 * Common pattern for concurrency tests that need many resources.
 * 
 * @param planId - The treatment plan ID
 * @param count - Number of resources to create
 * @param options - Configuration options for resources
 * @returns Array of created medical resources
 */
export async function createMultipleResources(
  planId: string,
  count: number,
  options: {
    costPerMinute?: number;
    namePrefix?: string;
  } = {}
): Promise<MedicalResource[]> {
  const { costPerMinute = 1, namePrefix = 'Resource' } = options;

  const resourcePromises = Array(count).fill(null).map((_, i) =>
    apiClient.createMedicalResource(
      planId,
      createMedicalResourcePayload({
        resource_name: `${namePrefix}${i}`,
        operating_cost_per_minute: costPerMinute,
      }),
      TEST_USERS.physicianHeaders
    )
  );

  const results = await Promise.all(resourcePromises);
  return results.map(r => getSuccessData<MedicalResource>(r));
}

/**
 * Creates a medical resource with custom sterilization buffer.
 * V3 brownfield helper for testing sterilization buffer override feature.
 * 
 * @param planId - The treatment plan ID
 * @param bufferMinutes - The sterilization buffer override value (null for default)
 * @param options - Additional resource options
 * @returns The created medical resource
 */
export async function createResourceWithSterilizationBuffer(
  planId: string,
  bufferMinutes: number | null,
  options: {
    resourceName?: string;
    costPerMinute?: number;
  } = {}
): Promise<MedicalResource> {
  const { resourceName = 'Test Resource', costPerMinute = 10.0 } = options;

  const resourceRes = await apiClient.createMedicalResource(
    planId,
    createMedicalResourcePayload({
      resource_name: resourceName,
      operating_cost_per_minute: costPerMinute,
      sterilization_buffer_override: bufferMinutes,
    }),
    TEST_USERS.physicianHeaders
  );

  return getSuccessData<MedicalResource>(resourceRes);
}

/**
 * Sets a resource to DECOMMISSIONING_PENDING by creating an assignment first.
 * V3 brownfield helper for testing decommissioning workflows.
 * 
 * @param planId - The treatment plan ID
 * @param rotationId - The ward rotation ID
 * @param resourceId - The resource to decommission
 * @returns The updated resource and the created assignment
 */
export async function setResourceToPendingDecommissioning(
  planId: string,
  rotationId: string,
  resourceId: string
): Promise<{ resource: MedicalResource; assignment: Assignment }> {
  const procRes = await apiClient.createProcedure(
    planId,
    rotationId,
    createProcedurePayload(),
    TEST_USERS.physicianHeaders
  );
  const proc = getSuccessData<Procedure>(procRes);

  const assignmentRes = await apiClient.createAssignment(
    planId,
    createAssignmentPayload(proc.id, resourceId),
    TEST_USERS.physicianHeaders
  );
  const assignment = getSuccessData<Assignment>(assignmentRes);

  const decommissionRes = await apiClient.decommissionResource(
    planId,
    resourceId,
    {},
    TEST_USERS.adminHeaders
  );
  const resource = getSuccessData<MedicalResource>(decommissionRes);

  return { resource, assignment };
}

/**
 * Fetches final states of related entities after race conditions.
 * Common pattern to verify final state consistency.
 * 
 * @param planId - The treatment plan ID
 * @param rotationId - The ward rotation ID
 * @param procedureId - The procedure ID
 * @param assignmentId - The assignment ID
 * @returns Object with final states of plan, rotation, procedure, and assignment
 */
export async function fetchFinalStates(
  planId: string,
  rotationId: string,
  procedureId: string,
  assignmentId: string
): Promise<{
  plan: TreatmentPlan;
  rotation: WardRotation;
  procedure: Procedure;
  assignment: Assignment;
}> {
  const [planRes, rotationRes, procedureRes, assignmentRes] = await Promise.all([
    apiClient.getTreatmentPlan(planId, TEST_USERS.chargeNurseHeaders),
    apiClient.getWardRotation(planId, rotationId, TEST_USERS.chargeNurseHeaders),
    apiClient.getProcedure(planId, rotationId, procedureId, TEST_USERS.chargeNurseHeaders),
    apiClient.getAssignment(planId, assignmentId, TEST_USERS.chargeNurseHeaders),
  ]);

  return {
    plan: getSuccessData<TreatmentPlan>(planRes),
    rotation: getSuccessData<WardRotation>(rotationRes),
    procedure: getSuccessData<Procedure>(procedureRes),
    assignment: getSuccessData<Assignment>(assignmentRes),
  };
}

/**
 * Sets up a plan at a specific safety score threshold for testing race conditions.
 * This is a common setup pattern where tests need the plan to be at 400, 450, or 600 safety score.
 * 
 * The function:
 * 1. Creates plan, rotation, and specified number of resources
 * 2. For each resource, creates a 6000-minute assignment to reach bio-risk threshold
 * 3. Creates additional high-risk assignments to reach target safety score
 * 
 * @param targetScore - Target safety score (typically 400, 450, or 600)
 * @param options - Configuration options
 * @returns Plan, rotation, and array of resources at the threshold
 */
export async function setupPlanAtSafetyThreshold(options: {
  targetScore: number;
  planBudget?: number;
  numResources?: number;
  resourceCostPerMinute?: number;
}): Promise<{
  plan: TreatmentPlan;
  rotation: WardRotation;
  resources: MedicalResource[];
}> {
  const {
    targetScore,
    planBudget = 200000,
    numResources = 11,
    resourceCostPerMinute = 1,
  } = options;

  const plan = await createAndActivatePlan(planBudget);

  const rotationRes = await apiClient.createWardRotation(
    plan.id,
    createWardRotationPayload(),
    TEST_USERS.physicianHeaders
  );
  const rotation = getSuccessData<WardRotation>(rotationRes);

  const resources = await createMultipleResources(plan.id, numResources, {
    costPerMinute: resourceCostPerMinute,
    namePrefix: 'ThresholdResource',
  });

  const numHighRiskNeeded = Math.floor(targetScore / 50);
  
  const numOverrideNeeded = targetScore > 450 ? Math.floor((targetScore - 450) / 100) : 0;
  const numRegularHighRisk = numHighRiskNeeded - numOverrideNeeded;

  let resourceIndex = 0;

  for (let i = 0; i < numRegularHighRisk; i++) {
    const resource = resources[resourceIndex % numResources];
    
    await createBioRiskThresholdAssignment(
      plan.id,
      rotation.id,
      resource.id,
      i * 7000,
      `Setup${i}`
    );

    await createHighRiskAssignment(
      plan.id,
      rotation.id,
      resource.id,
      i * 7000 + 6100,
      i * 7000 + 6150,
      { procedureType: `HighRisk${i}`, shouldSchedule: true }
    );

    resourceIndex++;
  }

  for (let i = 0; i < numOverrideNeeded; i++) {
    const resource = resources[resourceIndex % numResources];
    
    await createBioRiskThresholdAssignment(
      plan.id,
      rotation.id,
      resource.id,
      resourceIndex * 7000,
      `OverrideSetup${i}`
    );

    await createHighRiskAssignment(
      plan.id,
      rotation.id,
      resource.id,
      resourceIndex * 7000 + 6100,
      resourceIndex * 7000 + 6150,
      { procedureType: `Override${i}`, override: true, shouldSchedule: true }
    );

    resourceIndex++;
  }

  return { plan, rotation, resources };
}
