import { TreatmentPlan } from './types';

/**
 * Asserts global plan invariants that must hold after any operation.
 * This checks:
 * - Budget balance is non-negative and within total budget
 * - Cost balance uses at most 2 decimal places
 * - Patient safety score is non-negative
 */
export function assertPlanInvariants(plan: TreatmentPlan): void {
  expect(plan.cost_balance).toBeGreaterThanOrEqual(0);
  expect(plan.cost_balance).toBeLessThanOrEqual(plan.total_budget);
  expect(Number(plan.cost_balance.toFixed(2))).toBe(plan.cost_balance);
  expect(plan.patient_safety_score).toBeGreaterThanOrEqual(0);
}

/**
 * Validates the outcome of a race condition between two operations.
 * Returns separated success and failure responses for further assertions.
 * 
 * @param responses Array of responses from parallel operations
 * @param expectedSuccesses Number of operations expected to succeed
 * @param expectedFailures Number of operations expected to fail
 * @returns Object with separated success and failure responses
 */
export function assertRaceOutcome<T extends { status: number }>(
  responses: T[],
  expectedSuccesses: number,
  expectedFailures: number
): { successes: T[]; failures: T[] } {
  const successes = responses.filter(r => r.status >= 200 && r.status < 300);
  const failures = responses.filter(r => r.status >= 400);

  expect(successes.length).toBe(expectedSuccesses);
  expect(failures.length).toBe(expectedFailures);

  return { successes, failures };
}

/**
 * Validates exactly one success and one failure in a binary race condition.
 * Common pattern for OCC and state transition races.
 */
export function assertExactlyOneSucceeds<T extends { status: number }>(
  response1: T,
  response2: T
): { success: T; failure: T } {
  const responses = [response1, response2];
  const { successes, failures } = assertRaceOutcome(responses, 1, 1);
  
  return { success: successes[0], failure: failures[0] };
}

/**
 * Asserts that cost values use at most 2 decimal places (precision requirement).
 */
export function assertCostPrecision(cost: number): void {
  expect(Number(cost.toFixed(2))).toBe(cost);
}

/**
 * Asserts version monotonicity: new version must be >= old version.
 * Used to validate OCC version increments.
 */
export function assertVersionIncremented(
  newVersion: number,
  oldVersion: number,
  minimumIncrement: number = 1
): void {
  expect(newVersion).toBeGreaterThanOrEqual(oldVersion + minimumIncrement);
}

/**
 * Asserts that at least one operation succeeds in a race condition.
 * Common for races where both operations might succeed or one might fail.
 */
export function assertAtLeastOneSucceeds<T extends { status: number }>(
  ...responses: T[]
): { successes: T[]; failures: T[] } {
  const successes = responses.filter(r => r.status >= 200 && r.status < 300);
  const failures = responses.filter(r => r.status >= 400);

  expect(successes.length).toBeGreaterThanOrEqual(1);
  expect(successes.length + failures.length).toBe(responses.length);

  return { successes, failures };
}

/**
 * Asserts flexible race outcome: 1-2 successes allowed.
 * Common for races where both might succeed or race to completion.
 */
export function assertOneOrBothSucceed<T extends { status: number }>(
  response1: T,
  response2: T
): { successes: T[]; failures: T[] } {
  const responses = [response1, response2];
  const successes = responses.filter(r => r.status >= 200 && r.status < 300);
  const failures = responses.filter(r => r.status >= 400);

  expect(successes.length).toBeGreaterThanOrEqual(1);
  expect(successes.length).toBeLessThanOrEqual(2);
  expect(successes.length + failures.length).toBe(2);

  return { successes, failures };
}

/**
 * Helper for testing concurrent race conditions between two operations.
 * Executes both operations concurrently and validates the race outcome.
 */
export async function testRaceCondition<T1 extends { status: number }, T2 extends { status: number }>(
  operation1: () => Promise<T1>,
  operation2: () => Promise<T2>,
  expectedPattern: 'exactly-one' | 'one-or-both' | 'both-must-succeed'
): Promise<{ result1: T1; result2: T2; successes: (T1 | T2)[]; failures: (T1 | T2)[] }> {
  const [result1, result2] = await Promise.all([operation1(), operation2()]);

  const responses = [result1, result2];
  const successes = responses.filter(r => r.status >= 200 && r.status < 300);
  const failures = responses.filter(r => r.status >= 400);

  switch (expectedPattern) {
    case 'exactly-one':
      expect(successes.length).toBe(1);
      expect(failures.length).toBe(1);
      break;
    case 'one-or-both':
      expect(successes.length).toBeGreaterThanOrEqual(1);
      expect(successes.length).toBeLessThanOrEqual(2);
      break;
    case 'both-must-succeed':
      expect(successes.length).toBe(2);
      expect(failures.length).toBe(0);
      break;
  }

  return { result1, result2, successes, failures };
}

/**
 * Asserts ISO 8601 timestamp format with milliseconds.
 */
export function assertTimestampFormat(timestamp: string): void {
  expect(timestamp).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
}
