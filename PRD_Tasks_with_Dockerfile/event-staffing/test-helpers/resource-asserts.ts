import {
  StaffingContract,
  Event,
  Shift,
  StaffProfile,
  Assignment,
  ConflictPairing,
  ContractStatus,
  EventStatus,
  ShiftStatus,
  AssignmentStatus,
  CertificationType,
  Certification,
} from './types';

function isValidUUID(uuid: string): boolean {
  const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  return uuidRegex.test(uuid);
}

function isValidISO8601(timestamp: string): boolean {
  const iso8601Regex = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{3})?Z$/;
  return iso8601Regex.test(timestamp);
}

function isValidDate(date: string): boolean {
  const dateRegex = /^\d{4}-\d{2}-\d{2}$/;
  return dateRegex.test(date);
}

export function assertStaffingContract(contract: any): asserts contract is StaffingContract {
  expect(contract).toBeDefined();
  expect(typeof contract).toBe('object');

  expect(contract.id).toBeDefined();
  expect(typeof contract.id).toBe('string');
  expect(isValidUUID(contract.id)).toBe(true);

  expect(contract.client_name).toBeDefined();
  expect(typeof contract.client_name).toBe('string');
  expect(contract.client_name.length).toBeGreaterThan(0);

  expect(contract.status).toBeDefined();
  expect(Object.values(ContractStatus)).toContain(contract.status);

  expect(typeof contract.total_budget).toBe('number');
  expect(contract.total_budget).toBeGreaterThan(0);

  expect(typeof contract.budget_balance).toBe('number');
  expect(contract.budget_balance).toBeLessThanOrEqual(contract.total_budget);

  expect(typeof contract.compliance_risk_score).toBe('number');
  expect(contract.compliance_risk_score).toBeGreaterThanOrEqual(0);

  expect(isValidISO8601(contract.created_at)).toBe(true);
  expect(isValidISO8601(contract.updated_at)).toBe(true);
}

export function assertEvent(event: any): asserts event is Event {
  expect(event).toBeDefined();
  expect(typeof event).toBe('object');

  expect(isValidUUID(event.id)).toBe(true);
  expect(isValidUUID(event.contract_id)).toBe(true);

  expect(event.name).toBeDefined();
  expect(typeof event.name).toBe('string');
  expect(event.name.length).toBeGreaterThan(0);

  expect(Object.values(EventStatus)).toContain(event.status);

  expect(typeof event.start_time).toBe('number');
  expect(typeof event.end_time).toBe('number');
  expect(event.end_time).toBeGreaterThan(event.start_time);

  expect(isValidISO8601(event.created_at)).toBe(true);
  expect(isValidISO8601(event.updated_at)).toBe(true);
}

export function assertShift(shift: any): asserts shift is Shift {
  expect(shift).toBeDefined();
  expect(typeof shift).toBe('object');

  expect(isValidUUID(shift.id)).toBe(true);
  expect(isValidUUID(shift.event_id)).toBe(true);
  expect(isValidUUID(shift.contract_id)).toBe(true);

  expect(shift.role_name).toBeDefined();
  expect(typeof shift.role_name).toBe('string');
  expect(shift.role_name.length).toBeGreaterThan(0);

  expect(Object.values(ShiftStatus)).toContain(shift.status);

  expect(Object.values(CertificationType)).toContain(shift.certification_needed);

  expect(typeof shift.start_time).toBe('number');
  expect(typeof shift.end_time).toBe('number');
  expect(shift.end_time).toBeGreaterThan(shift.start_time);

  expect(typeof shift.duration_hours).toBe('number');
  const expectedDuration = (shift.end_time - shift.start_time) / 3600;
  expect(shift.duration_hours).toBeCloseTo(expectedDuration, 2);

  expect(isValidISO8601(shift.created_at)).toBe(true);
  expect(isValidISO8601(shift.updated_at)).toBe(true);
}

export function assertCertification(cert: any): asserts cert is Certification {
  expect(cert).toBeDefined();
  expect(typeof cert).toBe('object');

  expect(isValidUUID(cert.id)).toBe(true);
  expect([CertificationType.FOOD_HANDLER_PERMIT, CertificationType.ALCOHOL_SERVICE_LICENSE]).toContain(cert.name);
  expect(isValidDate(cert.issued_date)).toBe(true);
  expect(isValidDate(cert.expiry_date)).toBe(true);
}

export function assertStaffProfile(profile: any): asserts profile is StaffProfile {
  expect(profile).toBeDefined();
  expect(typeof profile).toBe('object');

  expect(isValidUUID(profile.id)).toBe(true);
  expect(isValidUUID(profile.contract_id)).toBe(true);

  expect(profile.first_name).toBeDefined();
  expect(typeof profile.first_name).toBe('string');
  expect(profile.first_name.length).toBeGreaterThan(0);

  expect(profile.last_name).toBeDefined();
  expect(typeof profile.last_name).toBe('string');
  expect(profile.last_name.length).toBeGreaterThan(0);

  expect(typeof profile.base_pay_rate_per_hour).toBe('number');
  expect(profile.base_pay_rate_per_hour).toBeGreaterThan(0);

  expect(Array.isArray(profile.certifications)).toBe(true);
  profile.certifications.forEach(assertCertification);

  expect(isValidISO8601(profile.created_at)).toBe(true);
  expect(isValidISO8601(profile.updated_at)).toBe(true);
}

export function assertAssignment(assignment: any): asserts assignment is Assignment {
  expect(assignment).toBeDefined();
  expect(typeof assignment).toBe('object');

  expect(isValidUUID(assignment.id)).toBe(true);
  expect(isValidUUID(assignment.contract_id)).toBe(true);
  expect(isValidUUID(assignment.shift_id)).toBe(true);
  expect(isValidUUID(assignment.staff_profile_id)).toBe(true);

  expect(Object.values(AssignmentStatus)).toContain(assignment.status);

  expect(typeof assignment.override_risk_check).toBe('boolean');
  expect(typeof assignment.risk_override_penalty_applied).toBe('boolean');
  expect(typeof assignment.is_overtime_eligible).toBe('boolean');

  expect(typeof assignment.provisional_cost).toBe('number');
  expect(assignment.provisional_cost).toBeGreaterThanOrEqual(0);

  if (assignment.status === AssignmentStatus.PAID) {
    expect(typeof assignment.final_payout).toBe('number');
    expect(assignment.final_payout).toBeGreaterThanOrEqual(0);
  } else {
    expect(assignment.final_payout === undefined || assignment.final_payout === null).toBe(true);
  }

  expect(isValidISO8601(assignment.created_at)).toBe(true);
  expect(isValidISO8601(assignment.updated_at)).toBe(true);
}

export function assertConflictPairing(pairing: any): asserts pairing is ConflictPairing {
  expect(pairing).toBeDefined();
  expect(typeof pairing).toBe('object');

  expect(isValidUUID(pairing.id)).toBe(true);
  expect(isValidUUID(pairing.contract_id)).toBe(true);
  expect(isValidUUID(pairing.staff_profile_id_1)).toBe(true);
  expect(isValidUUID(pairing.staff_profile_id_2)).toBe(true);

  expect(pairing.staff_profile_id_1).not.toBe(pairing.staff_profile_id_2);

  if (pairing.reason !== null && pairing.reason !== undefined) {
    expect(typeof pairing.reason).toBe('string');
  }

  expect(isValidISO8601(pairing.created_at)).toBe(true);
}

export function assertContractBudgetConsistency(contract: StaffingContract, assignments: Assignment[]) {
  const provisionalTotal = assignments
    .filter(a => [AssignmentStatus.PROPOSED, AssignmentStatus.ACCEPTED, AssignmentStatus.CONFIRMED].includes(a.status))
    .reduce((sum, a) => sum + a.provisional_cost, 0);

  const finalizedTotal = assignments
    .filter(a => a.status === AssignmentStatus.PAID)
    .reduce((sum, a) => sum + (a.final_payout || 0), 0);

  const expectedBalance = contract.total_budget - provisionalTotal - finalizedTotal;
  expect(contract.budget_balance).toBeCloseTo(expectedBalance, 2);
}

export function assertEventReadiness(event: Event, shifts: Shift[]) {
  const eventShifts = shifts.filter(s => s.event_id === event.id);

  if (event.status === EventStatus.READY_FOR_EXECUTION) {
    expect(eventShifts.length).toBeGreaterThan(0);
    expect(eventShifts.every(s => s.status === ShiftStatus.FILLED)).toBe(true);
  }
}

export function assertShiftAssignmentConsistency(shift: Shift, assignments: Assignment[]) {
  const shiftAssignments = assignments.filter(a => a.shift_id === shift.id);
  const activeAssignments = shiftAssignments.filter(a =>
    [AssignmentStatus.PROPOSED, AssignmentStatus.ACCEPTED, AssignmentStatus.CONFIRMED, AssignmentStatus.PAID].includes(a.status)
  );

  switch (shift.status) {
    case ShiftStatus.OPEN:
      expect(activeAssignments.length).toBe(0);
      break;
    case ShiftStatus.PENDING_CONFIRMATION:
      expect(activeAssignments.length).toBe(1);
      expect([AssignmentStatus.PROPOSED, AssignmentStatus.ACCEPTED]).toContain(activeAssignments[0].status);
      break;
    case ShiftStatus.FILLED:
      expect(activeAssignments.length).toBe(1);
      expect([AssignmentStatus.CONFIRMED, AssignmentStatus.PAID]).toContain(activeAssignments[0].status);
      break;
  }
}
