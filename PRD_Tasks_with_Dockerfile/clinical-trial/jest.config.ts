import type { Config } from '@jest/types';

/**
 * Detect version from VERSION environment variable
 */
function getVersion(): number | null {
  const version = process.env.VERSION;
  if (!version) return null;
  
  // Extract version number from "v1", "v2", "v3", etc.
  const match = version.match(/^v(\d+)$/);
  return match ? parseInt(match[1], 10) : null;
}

// Determine which test patterns to include
let testPatterns: string[] = [];
let ignorePatterns: string[] = ['/node_modules/'];

const versionNum = getVersion();
const isRegression = process.env.REGRESSION === 'true';

if (versionNum !== null) {
  if (isRegression) {
    // REGRESSION mode: run all tests from v1 through v[N-1] (exclusive of current version)
    const versionsToRun: string[] = [];
    const versionsList: string[] = [];
    for (let v = 1; v < versionNum; v++) {
      versionsToRun.push(`**/versions/v${v}/test_suite/**/*.test.ts`);
      versionsList.push(`v${v}`);
    }
    testPatterns = versionsToRun;
    // Ignore current version
    ignorePatterns.push(`/versions/v${versionNum}/`);
    console.log(`[jest.config] REGRESSION mode: Running tests for ${versionsList.join(' + ')} (testing v${versionNum} implementation)`);
  } else {
    // Normal mode: run only vN tests
    testPatterns = [`**/versions/v${versionNum}/test_suite/**/*.test.ts`];
    console.log(`[jest.config] Normal mode: Running v${versionNum} tests only`);
  }
} else {
  // Default: run only v1 (greenfield) tests
  testPatterns = ['**/versions/v1/test_suite/**/*.test.ts'];
  ignorePatterns.push('/versions/v2/', '/versions/v3/', '/versions/v4/', '/versions/v5/');
  console.log('[jest.config] Default mode: Running v1 tests only (no version detected)');
}

const config: Config.InitialOptions = {
  // Use ts-jest preset for seamless TypeScript support
  preset: 'ts-jest',

  // Run tests in a Node.js environment (suitable for most backend libs/services)
  testEnvironment: 'node',

  // Test patterns based on environment flags
  testMatch: testPatterns,
  
  // Ignore patterns based on what we're running
  testPathIgnorePatterns: ignorePatterns,

  // Point ts-jest at the project's root tsconfig for path mapping & compiler options
  globals: {
    'ts-jest': {
      tsconfig: 'tsconfig.json',
    },
  },

  // Ensure resources spun up in setup are cleaned after the suite finishes
  globalSetup: '<rootDir>/test-helpers/globalSetup.ts',
  globalTeardown: '<rootDir>/test-helpers/teardown.ts',
  setupFilesAfterEnv: ['<rootDir>/console-sanitizer.ts'],

  // Sanitise aggregated results to avoid circular references when --json flag is used
  testResultsProcessor: '<rootDir>/jest-results-processor.js',

  // Set test timeout to 10 seconds (in milliseconds)
  testTimeout: 10000,
};

export default config;
