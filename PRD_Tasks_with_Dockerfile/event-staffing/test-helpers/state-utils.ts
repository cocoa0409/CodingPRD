import {
  StaffingContract,
  Event,
  Shift,
  Assignment,
  ContractStatus,
  EventStatus,
  ShiftStatus,
  AssignmentStatus,
} from './types';

const CONTRACT_TRANSITIONS: Record<ContractStatus, ContractStatus[]> = {
  [ContractStatus.PLANNING]: [ContractStatus.ACTIVE],
  [ContractStatus.ACTIVE]: [ContractStatus.PAYROLL_PENDING],
  [ContractStatus.PAYROLL_PENDING]: [ContractStatus.CLOSED],
  [ContractStatus.CLOSED]: [],
};

const EVENT_TRANSITIONS: Record<EventStatus, EventStatus[]> = {
  [EventStatus.PLANNING]: [EventStatus.READY_FOR_EXECUTION, EventStatus.CANCELLED],
  [EventStatus.READY_FOR_EXECUTION]: [EventStatus.PLANNING, EventStatus.CANCELLED],
  [EventStatus.CANCELLED]: [],
};

const SHIFT_TRANSITIONS: Record<ShiftStatus, ShiftStatus[]> = {
  [ShiftStatus.OPEN]: [ShiftStatus.PENDING_CONFIRMATION, ShiftStatus.CANCELLED],
  [ShiftStatus.PENDING_CONFIRMATION]: [ShiftStatus.OPEN, ShiftStatus.FILLED, ShiftStatus.CANCELLED],
  [ShiftStatus.FILLED]: [ShiftStatus.OPEN, ShiftStatus.CANCELLED],
  [ShiftStatus.CANCELLED]: [],
};

const ASSIGNMENT_TRANSITIONS: Record<AssignmentStatus, AssignmentStatus[]> = {
  [AssignmentStatus.PROPOSED]: [AssignmentStatus.ACCEPTED, AssignmentStatus.DECLINED, AssignmentStatus.CANCELLED],
  [AssignmentStatus.ACCEPTED]: [AssignmentStatus.CONFIRMED, AssignmentStatus.CANCELLED],
  [AssignmentStatus.CONFIRMED]: [AssignmentStatus.PAID, AssignmentStatus.CANCELLED],
  [AssignmentStatus.PAID]: [],
  [AssignmentStatus.DECLINED]: [],
  [AssignmentStatus.CANCELLED]: [],
};

export function validateStateTransition<T extends string>(
  currentState: T,
  targetState: T,
  transitions: Record<T, T[]>
): boolean {
  const allowedTransitions = transitions[currentState] || [];
  return allowedTransitions.includes(targetState);
}

export function isValidContractTransition(
  fromStatus: ContractStatus,
  toStatus: ContractStatus
): boolean {
  return validateStateTransition(fromStatus, toStatus, CONTRACT_TRANSITIONS);
}

export function isValidEventTransition(
  fromStatus: EventStatus,
  toStatus: EventStatus
): boolean {
  return validateStateTransition(fromStatus, toStatus, EVENT_TRANSITIONS);
}

export function isValidShiftTransition(
  fromStatus: ShiftStatus,
  toStatus: ShiftStatus
): boolean {
  return validateStateTransition(fromStatus, toStatus, SHIFT_TRANSITIONS);
}

export function isValidAssignmentTransition(
  fromStatus: AssignmentStatus,
  toStatus: AssignmentStatus
): boolean {
  return validateStateTransition(fromStatus, toStatus, ASSIGNMENT_TRANSITIONS);
}

export function assertContractState(
  contract: StaffingContract,
  expectedState: ContractStatus
): void {
  expect(contract.status).toBe(expectedState);
}

export function assertEventState(
  event: Event,
  expectedState: EventStatus
): void {
  expect(event.status).toBe(expectedState);
}

export function assertShiftState(
  shift: Shift,
  expectedState: ShiftStatus
): void {
  expect(shift.status).toBe(expectedState);
}

export function assertAssignmentState(
  assignment: Assignment,
  expectedState: AssignmentStatus
): void {
  expect(assignment.status).toBe(expectedState);
}

export function isTerminalState<T extends string>(
  state: T,
  transitions: Record<T, T[]>
): boolean {
  return (transitions[state] || []).length === 0;
}

export function isContractTerminal(status: ContractStatus): boolean {
  return isTerminalState(status, CONTRACT_TRANSITIONS);
}

export function isEventTerminal(status: EventStatus): boolean {
  return isTerminalState(status, EVENT_TRANSITIONS);
}

export function isShiftTerminal(status: ShiftStatus): boolean {
  return isTerminalState(status, SHIFT_TRANSITIONS);
}

export function isAssignmentTerminal(status: AssignmentStatus): boolean {
  return isTerminalState(status, ASSIGNMENT_TRANSITIONS);
}

export function getNextContractStates(currentStatus: ContractStatus): ContractStatus[] {
  return CONTRACT_TRANSITIONS[currentStatus] || [];
}

export function getNextEventStates(currentStatus: EventStatus): EventStatus[] {
  return EVENT_TRANSITIONS[currentStatus] || [];
}

export function getNextShiftStates(currentStatus: ShiftStatus): ShiftStatus[] {
  return SHIFT_TRANSITIONS[currentStatus] || [];
}

export function getNextAssignmentStates(currentStatus: AssignmentStatus): AssignmentStatus[] {
  return ASSIGNMENT_TRANSITIONS[currentStatus] || [];
}

export function canCreateShift(contractStatus: ContractStatus): boolean {
  return contractStatus === ContractStatus.ACTIVE;
}

export function canCreateAssignment(contractStatus: ContractStatus): boolean {
  return contractStatus === ContractStatus.ACTIVE;
}

export function canMarkEventReady(event: Event, shifts: Shift[]): boolean {
  if (event.status !== EventStatus.PLANNING) return false;

  const eventShifts = shifts.filter(s => s.event_id === event.id);
  if (eventShifts.length === 0) return false;

  return eventShifts.every(s => s.status === ShiftStatus.FILLED);
}

export function canInitiatePayroll(
  contractStatus: ContractStatus,
  assignments: Assignment[]
): boolean {
  if (contractStatus !== ContractStatus.ACTIVE) return false;

  const nonTerminalAssignments = assignments.filter(a =>
    [AssignmentStatus.PROPOSED, AssignmentStatus.ACCEPTED].includes(a.status)
  );

  return nonTerminalAssignments.length === 0;
}

export function canFinalizePayroll(contractStatus: ContractStatus): boolean {
  return contractStatus === ContractStatus.PAYROLL_PENDING;
}

export function validateShiftAssignmentStateConsistency(
  shift: Shift,
  assignment: Assignment | null
): boolean {
  if (!assignment) {
    return shift.status === ShiftStatus.OPEN || shift.status === ShiftStatus.CANCELLED;
  }

  switch (shift.status) {
    case ShiftStatus.OPEN:
      return false;

    case ShiftStatus.PENDING_CONFIRMATION:
      return [AssignmentStatus.PROPOSED, AssignmentStatus.ACCEPTED].includes(assignment.status);

    case ShiftStatus.FILLED:
      return [AssignmentStatus.CONFIRMED, AssignmentStatus.PAID].includes(assignment.status);

    case ShiftStatus.CANCELLED:
      return [AssignmentStatus.CANCELLED, AssignmentStatus.DECLINED].includes(assignment.status);

    default:
      return false;
  }
}

export const stateTestHelpers = {
  getContractInState: (status: ContractStatus) => {
    if (status === ContractStatus.PLANNING) return {};

    const requiredTransitions: string[] = [];
    if (status === ContractStatus.ACTIVE) requiredTransitions.push('activate');
    if (status === ContractStatus.PAYROLL_PENDING) requiredTransitions.push('activate', 'initiate_payroll');
    if (status === ContractStatus.CLOSED) requiredTransitions.push('activate', 'initiate_payroll', 'finalize_payroll');

    return { requiredTransitions };
  },

  getInvalidTransitions: <T extends string>(
    currentState: T,
    allStates: T[],
    validTransitions: Record<T, T[]>
  ): T[] => {
    const valid = validTransitions[currentState] || [];
    return allStates.filter(state => state !== currentState && !valid.includes(state));
  },
};
