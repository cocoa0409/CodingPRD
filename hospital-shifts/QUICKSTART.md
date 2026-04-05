# Testing Guide

Note: Each task comes with a reference implementation in JavaScript that passes all tests (`reference-implementation-js`). Starting implementations are in JavaScript but can be provided in any language.

## Generating an Implementation

### v1 (Greenfield)
Start with an empty environment and provide the agent with `versions/v1/prd.md`. Once complete, test using the commands below.

### v2 and v3 (Brownfield)
1. Copy the `starting-implementation-js` folder from the respective version directory
2. Provide the agent with `versions/v2/prd.md` or `versions/v3/prd.md`
3. The agent should modify the starting implementation to meet the new requirements
4. Test using the commands below

## Quick Start

To test an implementation, place it in the appropriate version folder and run tests with the `API_START_COMMAND` environment variable:

### v1 Implementation
```bash
API_START_COMMAND="cd versions/v1/your-implementation-folder && npm start" npm test
```

### v2 Implementation
```bash
API_START_COMMAND="cd versions/v2/your-implementation-folder && npm start" npm test
```

### v3 Implementation
```bash
API_START_COMMAND="cd versions/v3/your-implementation-folder && npm start" npm test
```

## Test Modes

**Default**: Runs only the tests for that specific version (e.g., v2 tests for a v2 implementation)

**Regression** (`REGRESSION=true`): Runs only previous version tests (v2 and v3 only)
- v2: runs v1 tests
- v3: runs v1 + v2 tests

```bash
API_START_COMMAND="cd versions/v3/your-implementation-folder && npm start" REGRESSION=true npm test
```

**All** (`ALL=true`): Runs all tests up to and including the current version
- v1: runs v1 tests
- v2: runs v1 + v2 tests  
- v3: runs v1 + v2 + v3 tests

```bash
API_START_COMMAND="cd versions/v3/your-implementation-folder && npm start" ALL=true npm test
```

## Optional Configuration

**API_URL**: Override the API server URL (default: `http://localhost:3000`)

```bash
API_URL="http://localhost:8080" API_START_COMMAND="cd versions/v1/your-implementation-folder && npm start" npm test
```

## Examples

```bash
# Test the v1 reference implementation
API_START_COMMAND="cd versions/v1/reference-implementation-js && npm start" npm test

# Test the v2 reference implementation with v2 tests only
API_START_COMMAND="cd versions/v2/reference-implementation-js && npm start" npm test

# Test the v3 reference implementation with regression tests (v1 + v2)
API_START_COMMAND="cd versions/v3/reference-implementation-js && npm start" REGRESSION=true npm test

# Test the v3 reference implementation with all tests (v1 + v2 + v3)
API_START_COMMAND="cd versions/v3/reference-implementation-js && npm start" ALL=true npm test
```
