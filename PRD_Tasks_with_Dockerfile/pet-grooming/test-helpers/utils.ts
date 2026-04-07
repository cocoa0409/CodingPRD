import { UserRole } from './types';

export const SYSTEM_CONSTANTS = {
  MIN_GROOMER_BREAK_MINUTES: 15,
  PEAK_SESSION_JOB_COUNT: 5,
  PEAK_RATE_MULTIPLIER: 1.5,
  PEAK_SESSION_PENALTY: 10,
  ALLERGY_OVERRIDE_PENALTY: 25,
  ALLERGY_THRESHOLD_LOCK: 50,
} as const;

export interface ApiHeaders {
  'X-User-ID': string;
  'X-User-Role': UserRole;
  [key: string]: string;
}

export function buildUserHeaders(userId: string, userRole: UserRole): ApiHeaders {
  return {
    'X-User-ID': userId,
    'X-User-Role': userRole
  };
}

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

export function calculateDurationMinutes(startTime: number, endTime: number): number {
  return (endTime - startTime) / 60;
}

export function isAllergySafe(allergyScore: number, threshold: number): boolean {

  return allergyScore < threshold;
}

export function wouldBreachAllergyThreshold(currentScore: number, penalty: number, threshold: number = SYSTEM_CONSTANTS.ALLERGY_THRESHOLD_LOCK): boolean {

  return (currentScore + penalty) >= threshold;
}

export function calculateRemainingBudget(totalBudget: number, provisionalCosts: number, finalizedCosts: number): number {
  return totalBudget - provisionalCosts - finalizedCosts;
}

export function hasSufficientBudget(remainingBudget: number, newCost: number): boolean {
  return remainingBudget >= newCost;
}

export function calculatePeakSessionCost(baseCost: number, peakMultiplier: number = SYSTEM_CONSTANTS.PEAK_RATE_MULTIPLIER): number {
  return baseCost * peakMultiplier;
}

export function isPeakSession(activeJobCount: number, peakThreshold: number = SYSTEM_CONSTANTS.PEAK_SESSION_JOB_COUNT): boolean {

  return activeJobCount >= peakThreshold;
}

export function formatDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function getCurrentDate(): string {
  return formatDate(new Date());
}

export function generatePetId(index: number): string {
  return `pet-${String(index).padStart(3, '0')}`;
}
