import type { Config } from '@jest/types';

/**
 * Auto-detect version from API_START_COMMAND if BROWNFIELD_VERSION is not set
 */
function autoDetectVersion(): void {
  // Skip if BROWNFIELD_VERSION is already explicitly set
  if (process.env.BROWNFIELD_VERSION) {
    return;
  }

  const apiCommand = process.env.API_START_COMMAND;
  if (!apiCommand) {
    return;
  }

  // Try to extract version from the command path
  // Matches patterns like: versions/v1/, versions/v2/, versions/v3/
  const versionMatch = apiCommand.match(/versions\/v(\d+)\//);
  
  if (versionMatch) {
    const detectedVersion = `v${versionMatch[1]}`;
    process.env.BROWNFIELD_VERSION = detectedVersion;
    console.log(`[jest.config] Auto-detected version from API_START_COMMAND: ${detectedVersion}`);
  }
}

// Auto-detect version before reading it
autoDetectVersion();

// Detect version from environment variable (set by shell scripts based on implementation path)
function getVersion(): number | null {
  const version = process.env.BROWNFIELD_VERSION;
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
const isAll = process.env.ALL === 'true';

if (versionNum !== null) {
  if (isAll) {
    // ALL mode: run all tests from v1 through v[N] (inclusive)
    const versionsToRun: string[] = [];
    const versionsList: string[] = [];
    for (let v = 1; v <= versionNum; v++) {
      versionsToRun.push(`**/versions/v${v}/test_suite/**/*.test.ts`);
      versionsList.push(`v${v}`);
    }
    testPatterns = versionsToRun;
    console.log(`[jest.config] ALL mode: Running tests for ${versionsList.join(' + ')}`);
  } else if (isRegression) {
    // REGRESSION mode: run v1 (greenfield) + all brownfield tests up to v[N-1]
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
  ignorePatterns.push('/versions/v2/', '/versions/v3/');
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
  setupFilesAfterEnv: ['<rootDir>/console-sanitizer.ts', '<rootDir>/test-helpers/liveness-setup.ts'],

  // Sanitise aggregated results to avoid circular references when --json flag is used
  testResultsProcessor: '<rootDir>/jest-results-processor.js',

  // Set test timeout to 10 seconds (in milliseconds)
  testTimeout: 10000,
};

export default config;