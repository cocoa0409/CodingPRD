import { KITCHEN_RULES } from "./constants";

export function calculateExecutionCost(
  durationMinutes: number,
  costPerMinute: number,
  isRushed: boolean
): number {
  const baseCost = durationMinutes * costPerMinute;

  if (isRushed) {
    return baseCost * KITCHEN_RULES.RUSHED_RATE_MULTIPLIER;
  }

  return baseCost;
}

export function isStepRushed(
  orderCreatedTimestamp: number,
  stepStartTimestamp: number
): boolean {
  const thawTimeSeconds = KITCHEN_RULES.MINIMUM_THAW_TIME_HOURS * 3600;
  const timeSinceOrderCreation = stepStartTimestamp - orderCreatedTimestamp;

  return timeSinceOrderCreation < thawTimeSeconds;
}
