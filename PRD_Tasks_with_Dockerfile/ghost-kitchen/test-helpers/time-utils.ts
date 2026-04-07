import { CookingStep } from './types';
import { KITCHEN_RULES } from './constants';

export function createUnixTimestamp(hoursFromNow: number): number {
  const now = Date.now();
  const milliseconds = hoursFromNow * 60 * 60 * 1000;
  return Math.floor((now + milliseconds) / 1000);
}

export function addHours(timestamp: number, hours: number): number {
  const seconds = hours * 60 * 60;
  return timestamp + seconds;
}

export function addMinutes(timestamp: number, minutes: number): number {
  const seconds = minutes * 60;
  return timestamp + seconds;
}

export function subtractHours(timestamp: number, hours: number): number {
  const seconds = hours * 60 * 60;
  return timestamp - seconds;
}

export function subtractMinutes(timestamp: number, minutes: number): number {
  const seconds = minutes * 60;
  return timestamp - seconds;
}

export function getHoursBetween(startTimestamp: number, endTimestamp: number): number {
  const seconds = Math.abs(endTimestamp - startTimestamp);
  return seconds / 3600;
}

export function getMinutesBetween(startTimestamp: number, endTimestamp: number): number {
  const seconds = Math.abs(endTimestamp - startTimestamp);
  return seconds / 60;
}

export function createStepTimeRange(
  startOffsetHours: number,
  durationHours: number
): { start_time: number; end_time: number } {
  const start_time = createUnixTimestamp(startOffsetHours);
  const end_time = addHours(start_time, durationHours);
  return { start_time, end_time };
}

export function validateCleaningCycles(steps: Array<{ start_time: number; end_time: number }>): boolean {
  if (steps.length < 2) {
    return true;
  }
  const sortedSteps = [...steps].sort((a, b) => a.start_time - b.start_time);

  for (let i = 0; i < sortedSteps.length - 1; i++) {
    const step1 = sortedSteps[i];
    const step2 = sortedSteps[i + 1];

    if (step1.end_time > step2.start_time) {
      return false;
    }

    const gapMinutes = getMinutesBetween(step1.end_time, step2.start_time);

    if (gapMinutes < KITCHEN_RULES.CLEANING_CYCLE_MINUTES) {
      return false;
    }
  }

  return true;
}

export function checkCleaningCycleViolation(
  newStep: { start_time: number; end_time: number },
  existingSteps: Array<{ start_time: number; end_time: number }>
): boolean {
  for (const existingStep of existingSteps) {
    const gapAfterExisting = Math.abs(newStep.start_time - existingStep.end_time) / 60;

    const gapAfterNew = Math.abs(existingStep.start_time - newStep.end_time) / 60;

    if (gapAfterExisting < KITCHEN_RULES.CLEANING_CYCLE_MINUTES || gapAfterNew < KITCHEN_RULES.CLEANING_CYCLE_MINUTES) {
      return true;
    }
  }

  return false;
}

export function calculateTotalMinutes(steps: Array<{ start_time: number; end_time: number }>): number {
  return steps.reduce((total, step) => {
    const minutes = getMinutesBetween(step.start_time, step.end_time);
    return total + minutes;
  }, 0);
}

export function willStepBeRushed(
  stepStartTime: number,
  orderCreatedTime: number
): boolean {
  const thawTimeSeconds = KITCHEN_RULES.MINIMUM_THAW_TIME_HOURS * 3600;
  const timeSinceOrderCreation = stepStartTime - orderCreatedTime;

  return timeSinceOrderCreation < thawTimeSeconds;
}

export function sortStepsChronologically<T extends { start_time: number; id: string }>(steps: T[]): T[] {
  return [...steps].sort((a, b) => {
    if (a.start_time !== b.start_time) {
      return a.start_time - b.start_time;
    }
    return a.id.localeCompare(b.id);
  });
}

export function groupStepsByRecipe(steps: CookingStep[]): Map<string, CookingStep[]> {
  const grouped = new Map<string, CookingStep[]>();

  for (const step of steps) {
    const recipeSteps = grouped.get(step.recipe_id) || [];
    recipeSteps.push(step);
    grouped.set(step.recipe_id, recipeSteps);
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

  morningStep: (daysFromNow = 1) => createStepTimeRange(daysFromNow * 24 + 8, 8),
  afternoonStep: (daysFromNow = 1) => createStepTimeRange(daysFromNow * 24 + 14, 6),
  eveningStep: (daysFromNow = 1) => createStepTimeRange(daysFromNow * 24 + 20, 4),

  shortStep: (hoursFromNow = 24) => createStepTimeRange(hoursFromNow, 2),
  standardStep: (hoursFromNow = 24) => createStepTimeRange(hoursFromNow, 6),
  longStep: (hoursFromNow = 24) => createStepTimeRange(hoursFromNow, 12),

  backToBackSteps: (startHours = 24) => ({
    step1: createStepTimeRange(startHours, 6),
    step2: createStepTimeRange(startHours + 6, 6),
  }),

  properlySpacedSteps: (startHours = 24) => ({
    step1: createStepTimeRange(startHours, 6),
    step2: createStepTimeRange(startHours + 6.5, 6),
  }),

  cleaningViolatingSteps: (startHours = 24) => ({
    step1: createStepTimeRange(startHours, 6),
    step2: createStepTimeRange(startHours + 6.1, 6),
  }),

  rushedOrderStep: (orderCreatedHours = 0) => {

    const stepStart = createUnixTimestamp(orderCreatedHours + 0.5);
    return {
      start_time: stepStart,
      end_time: addHours(stepStart, 2),
    };
  },

  properlyThawedStep: (orderCreatedHours = 0) => {

    const stepStart = createUnixTimestamp(orderCreatedHours + 2);
    return {
      start_time: stepStart,
      end_time: addHours(stepStart, 2),
    };
  },
};
