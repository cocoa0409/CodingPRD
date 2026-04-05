
import {
  TreatmentPlan,
  WardRotation,
  Procedure,
  MedicalResource,
  Assignment,
  InfectionRiskPairing
} from './types';
import { isISO8601Timestamp } from './validators';

export function isValidUUID(uuid: string): boolean {
  const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  return uuidRegex.test(uuid);
}


export function isValidDate(date: string): boolean {
  const dateRegex = /^\d{4}-\d{2}-\d{2}$/;
  return dateRegex.test(date);
}

export interface ApiHeaders {
  'X-User-ID': string;
  'X-User-Role': string;
  [key: string]: string;
}

export function buildUserHeaders(userId: string, userRole?: string): ApiHeaders {
  return {
    'X-User-ID': userId,
    'X-User-Role': userRole || 'default'
  };
}

/**
 * Creates a schedule minute value X minutes from a base
 */
export function createScheduleMinute(minutesFromBase: number, baseMinute: number = 0): number {
  return baseMinute + minutesFromBase;
}

/**
 * Adds minutes to an existing schedule minute
 */
export function addMinutes(scheduleMinute: number, minutes: number): number {
  return scheduleMinute + minutes;
}

export function assertTreatmentPlan(plan: any): asserts plan is TreatmentPlan {
  expect(plan).toBeDefined();
  expect(typeof plan).toBe('object');

  expect(plan.id).toBeDefined();
  expect(typeof plan.id).toBe('string');
  expect(isValidUUID(plan.id)).toBe(true);

  expect(plan.plan_name).toBeDefined();
  expect(typeof plan.plan_name).toBe('string');
  expect(plan.plan_name.length).toBeGreaterThan(0);

  expect(plan.status).toBeDefined();
  expect(['PLANNING', 'ACTIVE', 'FINAL_REVIEW_PENDING', 'COMPLETED']).toContain(plan.status);

  expect(typeof plan.total_budget).toBe('number');
  expect(plan.total_budget).toBeGreaterThan(0);

  expect(typeof plan.cost_balance).toBe('number');
  expect(plan.cost_balance).toBeLessThanOrEqual(plan.total_budget);

  expect(typeof plan.patient_safety_score).toBe('number');
  expect(plan.patient_safety_score).toBeGreaterThanOrEqual(0);

  expect(isISO8601Timestamp(plan.created_at)).toBe(true);
  expect(isISO8601Timestamp(plan.updated_at)).toBe(true);
}

export function assertWardRotation(rotation: any): asserts rotation is WardRotation {
  expect(rotation).toBeDefined();
  expect(typeof rotation).toBe('object');

  expect(isValidUUID(rotation.id)).toBe(true);
  expect(isValidUUID(rotation.plan_id)).toBe(true);

  expect(rotation.name).toBeDefined();
  expect(typeof rotation.name).toBe('string');
  expect(rotation.name.length).toBeGreaterThan(0);

  expect(['PLANNING', 'READY_FOR_ASSIGNMENT', 'COMPLETED', 'CANCELLED']).toContain(rotation.status);

  expect(typeof rotation.start_minute).toBe('number');
  expect(typeof rotation.end_minute).toBe('number');
  expect(rotation.end_minute).toBeGreaterThan(rotation.start_minute);

  expect(isISO8601Timestamp(rotation.created_at)).toBe(true);
  expect(isISO8601Timestamp(rotation.updated_at)).toBe(true);
}

export function assertProcedure(procedure: any): asserts procedure is Procedure {
  expect(procedure).toBeDefined();
  expect(typeof procedure).toBe('object');

  expect(isValidUUID(procedure.id)).toBe(true);
  expect(isValidUUID(procedure.rotation_id)).toBe(true);
  expect(isValidUUID(procedure.plan_id)).toBe(true);

  expect(procedure.procedure_type).toBeDefined();
  expect(typeof procedure.procedure_type).toBe('string');
  expect(procedure.procedure_type.length).toBeGreaterThan(0);

  expect(['PENDING', 'SCHEDULED', 'ASSIGNED', 'COMPLETED', 'CANCELLED']).toContain(procedure.status);

  expect(['BSL-3_CERTIFIED', 'CARDIAC_CATHETERIZATION_LAB', 'NONE']).toContain(procedure.required_certification);

  expect(typeof procedure.start_minute).toBe('number');
  expect(typeof procedure.end_minute).toBe('number');
  expect(procedure.end_minute).toBeGreaterThan(procedure.start_minute);

  expect(typeof procedure.duration_minutes).toBe('number');
  const expectedDuration = procedure.end_minute - procedure.start_minute;
  expect(procedure.duration_minutes).toBe(expectedDuration);

  expect(isISO8601Timestamp(procedure.created_at)).toBe(true);
  expect(isISO8601Timestamp(procedure.updated_at)).toBe(true);
}

export function assertResourceCertification(certification: any): void {
  expect(certification).toBeDefined();
  expect(typeof certification).toBe('object');

  expect(isValidUUID(certification.id)).toBe(true);
  expect(['BSL-3_CERTIFIED', 'CARDIAC_CATHETERIZATION_LAB']).toContain(certification.name);
  expect(isValidDate(certification.applied_date)).toBe(true);
}

export function assertMedicalResource(resource: any): asserts resource is MedicalResource {
  expect(resource).toBeDefined();
  expect(typeof resource).toBe('object');

  expect(isValidUUID(resource.id)).toBe(true);
  expect(isValidUUID(resource.plan_id)).toBe(true);

  expect(resource.resource_name).toBeDefined();
  expect(typeof resource.resource_name).toBe('string');
  expect(resource.resource_name.length).toBeGreaterThan(0);

  expect(resource.resource_model).toBeDefined();
  expect(typeof resource.resource_model).toBe('string');
  expect(resource.resource_model.length).toBeGreaterThan(0);

  expect(typeof resource.operating_cost_per_minute).toBe('number');
  expect(resource.operating_cost_per_minute).toBeGreaterThan(0);

  expect(Array.isArray(resource.resource_certifications)).toBe(true);
  resource.resource_certifications.forEach(assertResourceCertification);

  expect(isISO8601Timestamp(resource.created_at)).toBe(true);
  expect(isISO8601Timestamp(resource.updated_at)).toBe(true);
}

export function assertAssignment(assignment: any): asserts assignment is Assignment {
  expect(assignment).toBeDefined();
  expect(typeof assignment).toBe('object');

  expect(isValidUUID(assignment.id)).toBe(true);
  expect(isValidUUID(assignment.plan_id)).toBe(true);
  expect(isValidUUID(assignment.procedure_id)).toBe(true);
  expect(isValidUUID(assignment.resource_id)).toBe(true);

  expect(['PENDING_SCHEDULE', 'PROTOCOL_APPROVED', 'SCHEDULED', 'COMPLETED', 'REJECTED', 'CANCELLED']).toContain(assignment.status);

  expect(typeof assignment.override_protocol_check).toBe('boolean');
  expect(typeof assignment.protocol_override_penalty_applied).toBe('boolean');
  expect(typeof assignment.is_high_biorisk).toBe('boolean');

  expect(typeof assignment.provisional_cost).toBe('number');
  expect(assignment.provisional_cost).toBeGreaterThanOrEqual(0);

  if (assignment.status === 'COMPLETED') {
    expect(typeof assignment.final_cost).toBe('number');
    expect(assignment.final_cost).toBeGreaterThanOrEqual(0);
  }

  expect(isISO8601Timestamp(assignment.created_at)).toBe(true);
  expect(isISO8601Timestamp(assignment.updated_at)).toBe(true);
}

export function assertInfectionRiskPairing(pairing: any): asserts pairing is InfectionRiskPairing {
  expect(pairing).toBeDefined();
  expect(typeof pairing).toBe('object');

  expect(isValidUUID(pairing.id)).toBe(true);
  expect(isValidUUID(pairing.plan_id)).toBe(true);
  expect(isValidUUID(pairing.resource_id_1)).toBe(true);
  expect(isValidUUID(pairing.resource_id_2)).toBe(true);

  expect(pairing.resource_id_1).not.toBe(pairing.resource_id_2);

  if (pairing.reason !== null && pairing.reason !== undefined) {
    expect(typeof pairing.reason).toBe('string');
  }

  expect(isISO8601Timestamp(pairing.created_at)).toBe(true);
}
