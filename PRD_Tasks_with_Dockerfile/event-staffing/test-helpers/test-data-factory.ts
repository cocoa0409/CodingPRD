import { v4 as uuidv4 } from 'uuid';
import {
  StaffingContract,
  Event,
  Shift,
  StaffProfile,
  Assignment,
  ConflictPairing,
  Certification,
  ContractStatus,
  EventStatus,
  ShiftStatus,
  AssignmentStatus,
  CertificationType,
  CreateContractPayload,
  CreateEventPayload,
  CreateShiftPayload,
  CreateStaffProfilePayload,
  CreateAssignmentPayload,
  CreateConflictPairingPayload,
  AddCertificationPayload,
  UserRole,
} from './types';
import { createUnixTimestamp, addHours } from './time-utils';
import { handleApiResponse } from './validators';
import { apiClient } from './api-client';
import { buildUserHeaders } from './header-utils';

const DEFAULTS = {
  CLIENT_NAME: 'Test Client Inc.',
  TOTAL_BUDGET: 50000.00,
  EVENT_NAME: 'Test Event',
  SHIFT_ROLE: 'Test Role',
  STAFF_FIRST_NAME: 'Test',
  STAFF_LAST_NAME: 'Staff',
  BASE_PAY_RATE: 25.00,
  SHIFT_DURATION_HOURS: 8,
  EVENT_DURATION_HOURS: 6,
};

export function createContractPayload(
  overrides: Partial<CreateContractPayload> = {}
): CreateContractPayload {
  return {
    client_name: DEFAULTS.CLIENT_NAME,
    total_budget: DEFAULTS.TOTAL_BUDGET,
    ...overrides,
  };
}

export function createContract(
  overrides: Partial<StaffingContract> = {}
): StaffingContract {
  const now = new Date().toISOString();
  const budget = overrides.total_budget || DEFAULTS.TOTAL_BUDGET;

  return {
    id: uuidv4(),
    client_name: DEFAULTS.CLIENT_NAME,
    status: ContractStatus.PLANNING,
    total_budget: budget,
    budget_balance: budget,
    compliance_risk_score: 0,
    created_at: now,
    updated_at: now,
    ...overrides,
  };
}

export function createEventPayload(
  overrides: Partial<CreateEventPayload> = {}
): CreateEventPayload {
  const startTime = createUnixTimestamp(24);
  const endTime = addHours(startTime, DEFAULTS.EVENT_DURATION_HOURS);

  return {
    name: DEFAULTS.EVENT_NAME,
    start_time: startTime,
    end_time: endTime,
    ...overrides,
  };
}

export function createEvent(
  contractId: string,
  overrides: Partial<Event> = {}
): Event {
  const now = new Date().toISOString();
  const { start_time, end_time } = createEventPayload();

  return {
    id: uuidv4(),
    contract_id: contractId,
    name: DEFAULTS.EVENT_NAME,
    status: EventStatus.PLANNING,
    start_time,
    end_time,
    created_at: now,
    updated_at: now,
    ...overrides,
  };
}

export function createShiftPayload(
  overrides: Partial<CreateShiftPayload> = {}
): CreateShiftPayload {
  const startTime = createUnixTimestamp(24);
  const endTime = addHours(startTime, DEFAULTS.SHIFT_DURATION_HOURS);

  return {
    role_name: DEFAULTS.SHIFT_ROLE,
    start_time: startTime,
    end_time: endTime,
    ...overrides,
  };
}

export function createShift(
  eventId: string,
  contractId: string,
  overrides: Partial<Shift> = {}
): Shift {
  const now = new Date().toISOString();
  const payload = createShiftPayload(overrides);
  const duration = (payload.end_time - payload.start_time) / 3600;

  return {
    id: uuidv4(),
    event_id: eventId,
    contract_id: contractId,
    role_name: payload.role_name,
    status: ShiftStatus.OPEN,
    certification_needed: payload.certification_needed || CertificationType.NONE,
    start_time: payload.start_time,
    end_time: payload.end_time,
    duration_hours: duration,
    created_at: now,
    updated_at: now,
    ...overrides,
  };
}

export function createStaffProfilePayload(
  overrides: Partial<CreateStaffProfilePayload> = {}
): CreateStaffProfilePayload {
  return {
    first_name: DEFAULTS.STAFF_FIRST_NAME,
    last_name: DEFAULTS.STAFF_LAST_NAME,
    base_pay_rate_per_hour: DEFAULTS.BASE_PAY_RATE,
    ...overrides,
  };
}

export function createCertification(
  type: CertificationType.FOOD_HANDLER_PERMIT | CertificationType.ALCOHOL_SERVICE_LICENSE,
  overrides: Partial<Certification> = {}
): Certification {
  const today = new Date();
  const issueDate = new Date(today.getFullYear() - 1, today.getMonth(), today.getDate());
  const expiryDate = new Date(today.getFullYear() + 1, today.getMonth(), today.getDate());

  return {
    id: uuidv4(),
    name: type,
    issued_date: issueDate.toISOString().split('T')[0],
    expiry_date: expiryDate.toISOString().split('T')[0],
    ...overrides,
  };
}

export function createCertificationPayload(
  type: CertificationType.FOOD_HANDLER_PERMIT | CertificationType.ALCOHOL_SERVICE_LICENSE,
  overrides: Partial<AddCertificationPayload> = {}
): AddCertificationPayload {
  const cert = createCertification(type);

  return {
    name: type,
    issued_date: cert.issued_date,
    expiry_date: cert.expiry_date,
    ...overrides,
  };
}

export function createStaffProfile(
  contractId: string,
  overrides: Partial<StaffProfile> = {}
): StaffProfile {
  const now = new Date().toISOString();
  const payload = createStaffProfilePayload(overrides);

  return {
    id: uuidv4(),
    contract_id: contractId,
    first_name: payload.first_name,
    last_name: payload.last_name,
    base_pay_rate_per_hour: payload.base_pay_rate_per_hour,
    certifications: [],
    created_at: now,
    updated_at: now,
    ...overrides,
  };
}

export function createAssignmentPayload(
  shiftId: string,
  staffProfileId: string,
  overrides: Partial<CreateAssignmentPayload> = {}
): CreateAssignmentPayload {
  return {
    shift_id: shiftId,
    staff_profile_id: staffProfileId,
    override_risk_check: false,
    ...overrides,
  };
}

export function createAssignment(
  contractId: string,
  shiftId: string,
  staffProfileId: string,
  overrides: Partial<Assignment> = {}
): Assignment {
  const now = new Date().toISOString();

  return {
    id: uuidv4(),
    contract_id: contractId,
    shift_id: shiftId,
    staff_profile_id: staffProfileId,
    status: AssignmentStatus.PROPOSED,
    override_risk_check: false,
    risk_override_penalty_applied: false,
    is_overtime_eligible: false,
    provisional_cost: 200.00,
    created_at: now,
    updated_at: now,
    ...overrides,
  };
}

export function createConflictPairingPayload(
  staff1Id: string,
  staff2Id: string,
  overrides: Partial<CreateConflictPairingPayload> = {}
): CreateConflictPairingPayload {
  return {
    staff_profile_id_1: staff1Id,
    staff_profile_id_2: staff2Id,
    reason: 'Test conflict reason',
    ...overrides,
  };
}

export function createConflictPairing(
  contractId: string,
  staff1Id: string,
  staff2Id: string,
  overrides: Partial<ConflictPairing> = {}
): ConflictPairing {
  const now = new Date().toISOString();

  return {
    id: uuidv4(),
    contract_id: contractId,
    staff_profile_id_1: staff1Id,
    staff_profile_id_2: staff2Id,
    reason: 'Test conflict reason',
    created_at: now,
    ...overrides,
  };
}

export interface ContractScenario {
  contract: StaffingContract;
  events: Event[];
  shifts: Shift[];
  staffProfiles: StaffProfile[];
  assignments: Assignment[];
  conflictPairings: ConflictPairing[];
}

export function createContractWithEvents(
  eventCount: number = 2,
  shiftsPerEvent: number = 3
): ContractScenario {
  const contract = createContract({ status: ContractStatus.ACTIVE });
  const events: Event[] = [];
  const shifts: Shift[] = [];
  const staffProfiles: StaffProfile[] = [];
  const assignments: Assignment[] = [];
  const conflictPairings: ConflictPairing[] = [];

  for (let i = 0; i < eventCount; i++) {
    const event = createEvent(contract.id, {
      name: `Event ${i + 1}`,
      start_time: createUnixTimestamp(24 * (i + 1)),
      end_time: createUnixTimestamp(24 * (i + 1) + 6),
    });
    events.push(event);

    for (let j = 0; j < shiftsPerEvent; j++) {
      const shift = createShift(event.id, contract.id, {
        role_name: `Role ${j + 1}`,
        start_time: addHours(event.start_time, j * 2),
        end_time: addHours(event.start_time, (j + 1) * 2),
      });
      shifts.push(shift);
    }
  }

  return { contract, events, shifts, staffProfiles, assignments, conflictPairings };
}

export function createFullyStaffedEvent(): ContractScenario {
  const scenario = createContractWithEvents(1, 3);
  const { contract, events, shifts } = scenario;

  for (let i = 0; i < shifts.length; i++) {
    const staff = createStaffProfile(contract.id, {
      first_name: `Staff${i + 1}`,
      last_name: `Member${i + 1}`,
    });
    scenario.staffProfiles.push(staff);

    const assignment = createAssignment(contract.id, shifts[i].id, staff.id, {
      status: AssignmentStatus.CONFIRMED,
    });
    scenario.assignments.push(assignment);

    shifts[i].status = ShiftStatus.FILLED;
  }

  events[0].status = EventStatus.READY_FOR_EXECUTION;

  return scenario;
}

export function createOvertimeScenario(
  staffId: string = uuidv4(),
  shiftsCount: number = 6
): { shifts: Shift[]; totalHours: number; overtimeHours: number } {
  const contractId = uuidv4();
  const eventId = uuidv4();
  const shifts: Shift[] = [];

  for (let i = 0; i < shiftsCount; i++) {
    const shift = createShift(eventId, contractId, {
      start_time: createUnixTimestamp(i * 24),
      end_time: createUnixTimestamp(i * 24 + 8),
    });
    shifts.push(shift);
  }

  const totalHours = shiftsCount * 8;
  const overtimeHours = Math.max(0, totalHours - 40);

  return { shifts, totalHours, overtimeHours };
}

export const testDataGenerators = {
  generateStaffProfiles: (contractId: string, count: number): StaffProfile[] => {
    return Array.from({ length: count }, (_, i) =>
      createStaffProfile(contractId, {
        first_name: `Staff${i + 1}`,
        last_name: `Member${i + 1}`,
        base_pay_rate_per_hour: 20 + (i * 5),
      })
    );
  },

  generateSequentialShifts: (
    eventId: string,
    contractId: string,
    count: number,
    hoursApart: number = 0
  ): Shift[] => {
    const shifts: Shift[] = [];
    let currentTime = createUnixTimestamp(24);

    for (let i = 0; i < count; i++) {
      const shift = createShift(eventId, contractId, {
        role_name: `Shift ${i + 1}`,
        start_time: currentTime,
        end_time: addHours(currentTime, 8),
      });
      shifts.push(shift);
      currentTime = addHours(currentTime, 8 + hoursApart);
    }

    return shifts;
  },

  generateCertifiedShifts: (
    eventId: string,
    contractId: string,
    certifications: CertificationType[]
  ): Shift[] => {
    return certifications.map((cert, i) =>
      createShift(eventId, contractId, {
        role_name: `${cert} Required Role`,
        certification_needed: cert,
        start_time: createUnixTimestamp(24 + i * 12),
        end_time: createUnixTimestamp(24 + i * 12 + 8),
      })
    );
  },
};

export async function setupBasicContract(totalBudget: number = 10000.00, payRate: number = 20.00) {
  const coordinatorHeaders = buildUserHeaders('coordinator-1', UserRole.StaffingCoordinator);

  const contractRes = await apiClient.createContract(
      createContractPayload({ client_name: 'Advanced Test Contract', total_budget: totalBudget }),
      coordinatorHeaders
  );
  const contract = handleApiResponse<StaffingContract>(contractRes, 201);
  await apiClient.activateContract(contract.id, coordinatorHeaders);

  const eventRes = await apiClient.createEvent(contract.id, createEventPayload({ name: 'Advanced Test Event' }), coordinatorHeaders);
  const event = handleApiResponse<Event>(eventRes, 201);

  const staffRes = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ first_name: 'Test', last_name: 'User', base_pay_rate_per_hour: payRate }), coordinatorHeaders);
  const staff = handleApiResponse<StaffProfile>(staffRes, 201);

  return { contractId: contract.id, eventId: event.id, staffId: staff.id };
}

export async function createAndConfirmShift(contractId: string, eventId: string, staffId: string, shiftData: Partial<Shift>) {
  const coordinatorHeaders = buildUserHeaders('coordinator-1', UserRole.StaffingCoordinator);
  const accountManagerHeaders = buildUserHeaders('manager-1', UserRole.AccountManager);
  const staffMemberHeaders = buildUserHeaders('staff-1', UserRole.StaffMember);

  const shiftRes = await apiClient.createShift(
      contractId,
      eventId,
      createShiftPayload(shiftData),
      coordinatorHeaders
  );
  const shift = handleApiResponse<Shift>(shiftRes, 201);

  const assignmentRes = await apiClient.createAssignment(
      contractId,
      createAssignmentPayload(shift.id, staffId),
      accountManagerHeaders
  );
  const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

  await apiClient.acceptAssignment(contractId, assignment.id, staffMemberHeaders);
  await apiClient.confirmAssignment(contractId, assignment.id, coordinatorHeaders);

  return shift;
}

export async function createAndActivateContract(budget: number = 50000.00): Promise<StaffingContract> {
  const coordinatorHeaders = buildUserHeaders('coordinator-1', UserRole.StaffingCoordinator);
  const contractRes = await apiClient.createContract(
    createContractPayload({ total_budget: budget }),
    coordinatorHeaders
  );
  const contract = handleApiResponse<StaffingContract>(contractRes, 201);

  const activateRes = await apiClient.activateContract(contract.id, coordinatorHeaders);
  return handleApiResponse<StaffingContract>(activateRes, 200);
}
