import {
  VoyageManifest,
  PortCall,
  CargoContract,
  StowageLocation,
  StowagePlan,
  ProximityConflict,
  UserRole,
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

export function createScheduleHour(hoursFromBase: number, baseHour: number = 0): number {
  return baseHour + hoursFromBase;
}

export function addHours(scheduleHour: number, hours: number): number {
  return scheduleHour + hours;
}

export function assertVoyageManifest(manifest: any): asserts manifest is VoyageManifest {
  expect(manifest).toBeDefined();
  expect(typeof manifest).toBe('object');

  expect(manifest.id).toBeDefined();
  expect(typeof manifest.id).toBe('string');
  expect(isValidUUID(manifest.id)).toBe(true);

  expect(manifest.voyage_name).toBeDefined();
  expect(typeof manifest.voyage_name).toBe('string');
  expect(manifest.voyage_name.length).toBeGreaterThan(0);

  expect(manifest.status).toBeDefined();
  expect(['PLANNING', 'ACTIVE', 'FINAL_REVIEW_PENDING', 'COMPLETED']).toContain(manifest.status);

  expect(typeof manifest.total_revenue_potential).toBe('number');
  expect(manifest.total_revenue_potential).toBeGreaterThan(0);

  expect(typeof manifest.revenue_balance).toBe('number');
  expect(manifest.revenue_balance).toBeGreaterThanOrEqual(0);
  expect(manifest.revenue_balance).toBeLessThanOrEqual(manifest.total_revenue_potential);

  expect(typeof manifest.compliance_risk_score).toBe('number');
  expect(manifest.compliance_risk_score).toBeGreaterThanOrEqual(0);
  expect(manifest.compliance_risk_score).toBeLessThanOrEqual(1000);

  expect(isISO8601Timestamp(manifest.created_at)).toBe(true);
  expect(isISO8601Timestamp(manifest.updated_at)).toBe(true);
}

export function assertPortCall(portCall: any): asserts portCall is PortCall {
  expect(portCall).toBeDefined();
  expect(typeof portCall).toBe('object');

  expect(isValidUUID(portCall.id)).toBe(true);
  expect(isValidUUID(portCall.manifest_id)).toBe(true);

  expect(portCall.name).toBeDefined();
  expect(typeof portCall.name).toBe('string');
  expect(portCall.name.length).toBeGreaterThan(0);

  expect(['PLANNING', 'READY_FOR_STOWAGE', 'COMPLETED', 'CANCELLED']).toContain(portCall.status);

  expect(typeof portCall.start_hour).toBe('number');
  expect(typeof portCall.end_hour).toBe('number');
  expect(portCall.end_hour).toBeGreaterThan(portCall.start_hour);

  expect(isISO8601Timestamp(portCall.created_at)).toBe(true);
  expect(isISO8601Timestamp(portCall.updated_at)).toBe(true);
}

export function assertCargoContract(contract: any): asserts contract is CargoContract {
  expect(contract).toBeDefined();
  expect(typeof contract).toBe('object');

  expect(isValidUUID(contract.id)).toBe(true);
  expect(isValidUUID(contract.port_call_id)).toBe(true);
  expect(isValidUUID(contract.manifest_id)).toBe(true);

  expect(contract.cargo_type).toBeDefined();
  expect(typeof contract.cargo_type).toBe('string');
  expect(contract.cargo_type.length).toBeGreaterThan(0);

  expect(['GENERAL', 'HAZMAT', 'REEFER']).toContain(contract.cargo_class);

  expect(['PENDING', 'STOWAGE_PROPOSED', 'ASSIGNED', 'COMPLETED', 'CANCELLED']).toContain(contract.status);

  expect(['IMDG_CLASS_1.1', 'IMDG_CLASS_6.1', 'NONE']).toContain(contract.required_imdg_class_code);

  expect(typeof contract.start_hour).toBe('number');
  expect(typeof contract.end_hour).toBe('number');
  expect(contract.end_hour).toBeGreaterThan(contract.start_hour);

  expect(typeof contract.duration_hours).toBe('number');
  const expectedDuration = contract.end_hour - contract.start_hour;
  expect(contract.duration_hours).toBe(expectedDuration);

  expect(isISO8601Timestamp(contract.created_at)).toBe(true);
  expect(isISO8601Timestamp(contract.updated_at)).toBe(true);
}

export function assertLocationCertification(certification: any): void {
  expect(certification).toBeDefined();
  expect(typeof certification).toBe('object');

  expect(isValidUUID(certification.id)).toBe(true);
  expect(['IMDG_CLASS_1.1', 'IMDG_CLASS_6.1']).toContain(certification.name);
  expect(isValidDate(certification.applied_date)).toBe(true);
}

export function assertStowageLocation(location: any): asserts location is StowageLocation {
  expect(location).toBeDefined();
  expect(typeof location).toBe('object');

  expect(isValidUUID(location.id)).toBe(true);
  expect(isValidUUID(location.manifest_id)).toBe(true);

  expect(location.location_code).toBeDefined();
  expect(typeof location.location_code).toBe('string');
  expect(location.location_code.length).toBeGreaterThan(0);

  expect(location.location_model).toBeDefined();
  expect(typeof location.location_model).toBe('string');
  expect(location.location_model.length).toBeGreaterThan(0);

  expect(typeof location.stowage_revenue_per_hour).toBe('number');
  expect(location.stowage_revenue_per_hour).toBeGreaterThan(0);

  expect(Array.isArray(location.location_certifications)).toBe(true);
  location.location_certifications.forEach(assertLocationCertification);

  expect(isISO8601Timestamp(location.created_at)).toBe(true);
  expect(isISO8601Timestamp(location.updated_at)).toBe(true);
}

export function assertStowagePlan(plan: any): asserts plan is StowagePlan {
  expect(plan).toBeDefined();
  expect(typeof plan).toBe('object');

  expect(isValidUUID(plan.id)).toBe(true);
  expect(isValidUUID(plan.manifest_id)).toBe(true);
  expect(isValidUUID(plan.contract_id)).toBe(true);
  expect(isValidUUID(plan.location_id)).toBe(true);

  expect(['PENDING_APPROVAL', 'COMPLIANCE_APPROVED', 'SCHEDULED', 'COMPLETED', 'REJECTED', 'CANCELLED']).toContain(plan.status);

  expect(typeof plan.used_special_permit).toBe('boolean');
  expect(typeof plan.special_permit_penalty_applied).toBe('boolean');
  expect(typeof plan.is_high_stress).toBe('boolean');

  expect(typeof plan.provisional_revenue).toBe('number');
  expect(plan.provisional_revenue).toBeGreaterThanOrEqual(0);

  if (plan.status === 'COMPLETED') {
    expect(typeof plan.final_revenue).toBe('number');
    expect(plan.final_revenue).toBeGreaterThanOrEqual(0);
  }

  expect(isISO8601Timestamp(plan.created_at)).toBe(true);
  expect(isISO8601Timestamp(plan.updated_at)).toBe(true);
}

export function assertProximityConflict(conflict: any): asserts conflict is ProximityConflict {
  expect(conflict).toBeDefined();
  expect(typeof conflict).toBe('object');

  expect(isValidUUID(conflict.id)).toBe(true);
  expect(isValidUUID(conflict.manifest_id)).toBe(true);
  expect(isValidUUID(conflict.location_id_1)).toBe(true);
  expect(isValidUUID(conflict.location_id_2)).toBe(true);

  expect(conflict.location_id_1).not.toBe(conflict.location_id_2);

  if (conflict.reason !== null && conflict.reason !== undefined) {
    expect(typeof conflict.reason).toBe('string');
  }

  expect(isISO8601Timestamp(conflict.created_at)).toBe(true);
}
