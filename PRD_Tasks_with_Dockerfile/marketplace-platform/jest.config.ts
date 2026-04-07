import type { Config } from '@jest/types';

const config: Config.InitialOptions = {
  // Use ts-jest preset for seamless TypeScript support
  preset: 'ts-jest',

  // Run tests in a Node.js environment
  testEnvironment: 'node',

  // Run all tests in the test suite
  testMatch: ['**/versions/v1/test_suite/**/*.test.ts'],
  
  // Ignore node_modules
  testPathIgnorePatterns: ['/node_modules/'],

  // Point ts-jest at the project's root tsconfig
  globals: {
    'ts-jest': {
      tsconfig: 'tsconfig.json',
    },
  },

  // Setup and teardown
  globalSetup: '<rootDir>/test-helpers/globalSetup.ts',
  globalTeardown: '<rootDir>/test-helpers/teardown.ts',
  setupFilesAfterEnv: ['<rootDir>/console-sanitizer.ts'],

  // Sanitize results for JSON output
  testResultsProcessor: '<rootDir>/jest-results-processor.js',

  // 10 second timeout per test
  testTimeout: 10000,
  
  // Force exit after tests complete
  forceExit: true,
};

export default config;
