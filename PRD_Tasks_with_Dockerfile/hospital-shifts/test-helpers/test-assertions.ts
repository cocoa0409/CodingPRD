import { TreatmentPlan } from './types';

export function assertPlanInvariants(plan: TreatmentPlan): void {
  expect(plan.cost_balance).toBeGreaterThanOrEqual(0);
  expect(plan.cost_balance).toBeLessThanOrEqual(plan.total_budget);
  expect(Number(plan.cost_balance.toFixed(2))).toBe(plan.cost_balance);
  expect(plan.patient_safety_score).toBeGreaterThanOrEqual(0);
}

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

export function assertExactlyOneSucceeds<T extends { status: number }>(
  response1: T,
  response2: T
): { success: T; failure: T } {
  const responses = [response1, response2];
  const { successes, failures } = assertRaceOutcome(responses, 1, 1);

  return { success: successes[0], failure: failures[0] };
}

export function assertCostPrecision(cost: number): void {
  expect(Number(cost.toFixed(2))).toBe(cost);
}

export function assertVersionIncremented(
  newVersion: number,
  oldVersion: number,
  minimumIncrement: number = 1
): void {
  expect(newVersion).toBeGreaterThanOrEqual(oldVersion + minimumIncrement);
}

export function assertAtLeastOneSucceeds<T extends { status: number }>(
  ...responses: T[]
): { successes: T[]; failures: T[] } {
  const successes = responses.filter(r => r.status >= 200 && r.status < 300);
  const failures = responses.filter(r => r.status >= 400);

  expect(successes.length).toBeGreaterThanOrEqual(1);
  expect(successes.length + failures.length).toBe(responses.length);

  return { successes, failures };
}

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

export function assertTimestampFormat(timestamp: string): void {
  expect(timestamp).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
}
