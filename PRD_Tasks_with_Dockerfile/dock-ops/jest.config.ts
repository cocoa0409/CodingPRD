import type { Config } from '@jest/types';

function getVersion(): number | null {
  const version = process.env.VERSION;
  if (!version) return null;
  const match = version.match(/^v(\d+)$/);
  return match ? parseInt(match[1], 10) : null;
}

let testPatterns: string[] = [];
let ignorePatterns: string[] = ['/node_modules/'];

const versionNum = getVersion();
const isRegression = process.env.REGRESSION === 'true';

if (versionNum !== null) {
  if (isRegression) {
    const versionsToRun: string[] = [];
    for (let v = 1; v < versionNum; v++) {
      versionsToRun.push(`**/versions/v${v}/test_suite/**/*.test.ts`);
    }
    testPatterns = versionsToRun;
    ignorePatterns.push(`/versions/v${versionNum}/`);
  } else {
    testPatterns = [`**/versions/v${versionNum}/test_suite/**/*.test.ts`];
  }
} else {
  testPatterns = ['**/versions/v1/test_suite/**/*.test.ts'];
  ignorePatterns.push('/versions/v2/', '/versions/v3/', '/versions/v4/');
}

const config: Config.InitialOptions = {
  preset: 'ts-jest',
  testEnvironment: 'node',
  testMatch: testPatterns,
  testPathIgnorePatterns: ignorePatterns,
  globals: {
    'ts-jest': {
      tsconfig: 'tsconfig.json',
    },
  },
  globalSetup: '<rootDir>/test-helpers/globalSetup.ts',
  globalTeardown: '<rootDir>/test-helpers/teardown.ts',
  setupFilesAfterEnv: [
    '<rootDir>/console-sanitizer.ts',
  ],
  testResultsProcessor: '<rootDir>/jest-results-processor.js',
  testTimeout: 10000,
  forceExit: true,
};

export default config;
