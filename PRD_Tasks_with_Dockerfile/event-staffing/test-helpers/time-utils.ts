import { Shift } from './types';

export const MANDATORY_REST_PERIOD_HOURS = 8;
export const OVERTIME_THRESHOLD_HOURS = 40;

export function createUnixTimestamp(hoursFromNow: number): number {
  const now = Date.now();
  const milliseconds = hoursFromNow * 60 * 60 * 1000;
  return Math.floor((now + milliseconds) / 1000);
}

export function addHours(timestamp: number, hours: number): number {
  const seconds = hours * 60 * 60;
  return timestamp + seconds;
}

export function subtractHours(timestamp: number, hours: number): number {
  const seconds = hours * 60 * 60;
  return timestamp - seconds;
}

export function getHoursBetween(startTimestamp: number, endTimestamp: number): number {
  const seconds = Math.abs(endTimestamp - startTimestamp);
  return seconds / 3600;
}

export function createShiftTimeRange(
  startOffsetHours: number,
  durationHours: number
): { start_time: number; end_time: number } {
  const start_time = createUnixTimestamp(startOffsetHours);
  const end_time = addHours(start_time, durationHours);
  return { start_time, end_time };
}

export function validateRestPeriods(shifts: Array<{ start_time: number; end_time: number }>): boolean {
  const sortedShifts = [...shifts].sort((a, b) => a.start_time - b.start_time);

  for (let i = 0; i < sortedShifts.length; i++) {
    for (let j = i + 1; j < sortedShifts.length; j++) {
      const shift1 = sortedShifts[i];
      const shift2 = sortedShifts[j];

      const gapAfterShift1 = getHoursBetween(shift1.end_time, shift2.start_time);

      const gapAfterShift2 = getHoursBetween(shift2.end_time, shift1.start_time);

      if (gapAfterShift1 < MANDATORY_REST_PERIOD_HOURS && gapAfterShift2 < MANDATORY_REST_PERIOD_HOURS) {
        return false;
      }
    }
  }

  return true;
}

export function checkRestPeriodViolation(
  newShift: { start_time: number; end_time: number },
  existingShifts: Array<{ start_time: number; end_time: number }>
): boolean {
  for (const existingShift of existingShifts) {
    const gapAfterExisting = Math.abs(newShift.start_time - existingShift.end_time) / 3600;

    const gapAfterNew = Math.abs(existingShift.start_time - newShift.end_time) / 3600;

    if (gapAfterExisting < MANDATORY_REST_PERIOD_HOURS || gapAfterNew < MANDATORY_REST_PERIOD_HOURS) {
      return true;
    }
  }

  return false;
}

export function calculateTotalHours(shifts: Array<{ start_time: number; end_time: number }>): number {
  return shifts.reduce((total, shift) => {
    const hours = getHoursBetween(shift.start_time, shift.end_time);
    return total + hours;
  }, 0);
}

export function calculateOvertimeHours(totalHours: number): number {
  return Math.max(0, totalHours - OVERTIME_THRESHOLD_HOURS);
}

export function willShiftCauseOvertime(
  shiftDurationHours: number,
  previousHoursWorked: number
): boolean {
  const totalHours = previousHoursWorked + shiftDurationHours;
  return totalHours > OVERTIME_THRESHOLD_HOURS;
}

export function calculateShiftOvertimeHours(
  shiftDurationHours: number,
  totalHoursIncludingShift: number
): number {
  const previousHours = totalHoursIncludingShift - shiftDurationHours;
  const overtimeHoursTotal = Math.max(0, totalHoursIncludingShift - OVERTIME_THRESHOLD_HOURS);
  const overtimeHoursPrevious = Math.max(0, previousHours - OVERTIME_THRESHOLD_HOURS);
  return overtimeHoursTotal - overtimeHoursPrevious;
}

export function sortShiftsChronologically<T extends { start_time: number; id: string }>(shifts: T[]): T[] {
  return [...shifts].sort((a, b) => {
    if (a.start_time !== b.start_time) {
      return a.start_time - b.start_time;
    }
    return a.id.localeCompare(b.id);
  });
}

export function groupShiftsByEvent(shifts: Shift[]): Map<string, Shift[]> {
  const grouped = new Map<string, Shift[]>();

  for (const shift of shifts) {
    const eventShifts = grouped.get(shift.event_id) || [];
    eventShifts.push(shift);
    grouped.set(shift.event_id, eventShifts);
  }

  return grouped;
}

export function doTimeRangesOverlap(
  range1: { start_time: number; end_time: number },
  range2: { start_time: number; end_time: number }
): boolean {
  return range1.start_time < range2.end_time && range2.start_time < range1.end_time;
}

export const testTimeHelpers = {
  tomorrow: () => createUnixTimestamp(24),
  nextWeek: () => createUnixTimestamp(24 * 7),

  morningShift: (daysFromNow = 1) => createShiftTimeRange(daysFromNow * 24 + 8, 8),
  eveningShift: (daysFromNow = 1) => createShiftTimeRange(daysFromNow * 24 + 16, 8),
  nightShift: (daysFromNow = 1) => createShiftTimeRange(daysFromNow * 24 + 22, 8),

  shortShift: (hoursFromNow = 24) => createShiftTimeRange(hoursFromNow, 4),
  longShift: (hoursFromNow = 24) => createShiftTimeRange(hoursFromNow, 12),

  backToBackShifts: (startHours = 24) => ({
    shift1: createShiftTimeRange(startHours, 8),
    shift2: createShiftTimeRange(startHours + 8, 8),
  }),

  properlySpacedShifts: (startHours = 24) => ({
    shift1: createShiftTimeRange(startHours, 8),
    shift2: createShiftTimeRange(startHours + 16, 8),
  }),
};
