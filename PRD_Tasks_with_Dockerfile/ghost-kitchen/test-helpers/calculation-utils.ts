import { CookingStep, CookingStation, MealOrder } from './types';
import { KITCHEN_RULES } from './constants';

export function calculateStepDurationMinutes(step: Pick<CookingStep, 'start_time' | 'end_time'>): number {
  if (step.end_time < step.start_time) {
    return 0;
  }
  return (step.end_time - step.start_time) / 60;
}

export function calculateProvisionalCost(
  station: Pick<CookingStation, 'ingredient_and_energy_cost_per_minute'>,
  step: Pick<CookingStep, 'start_time' | 'end_time'>,
  isRushed: boolean
): number {
  const duration = calculateStepDurationMinutes(step);
  const baseCost = duration * station.ingredient_and_energy_cost_per_minute;
  return isRushed ? baseCost * KITCHEN_RULES.RUSHED_RATE_MULTIPLIER : baseCost;
}

export function isExecutionRushed(
  order: Pick<MealOrder, 'created_at'>,
  step: Pick<CookingStep, 'start_time'>
): boolean {
  const orderCreationTime = Date.parse(order.created_at) / 1000;
  const thawTimeSeconds = KITCHEN_RULES.MINIMUM_THAW_TIME_HOURS * 3600;
  return step.start_time - orderCreationTime < thawTimeSeconds;
}
