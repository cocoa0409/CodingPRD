export const CONCURRENCY_ITERATIONS = parseInt(
  process.env.CONCURRENCY_TEST_ITERATIONS || '10',
  10
);

export async function repeatConcurrencyTest(
  testFn: () => Promise<void>,
  iterations: number = CONCURRENCY_ITERATIONS
): Promise<void> {
  for (let i = 0; i < iterations; i++) {
    await testFn();
  }
}
