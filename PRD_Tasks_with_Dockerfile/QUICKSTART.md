# Testing Guide

Each task contains:
- `versions/v1/prd.md` - Product Requirements Document
- `versions/v1/test_suite/` - Black-box HTTP tests
- `Dockerfile` - Container packaging for the test suite

## Running Tests with Docker

### Build the test container

```bash
docker build -t <task-name>-tests .
```

### Run tests against an implementation

Both containers must be on the same Docker network:

```bash
# Create a shared network
docker network create test-net

# Start the implementation container
docker run -d --name impl --network test-net <implementation-image>

# Run tests
docker run --rm --network test-net \
  -e API_URL=http://impl:3000 \
  -v $(pwd)/output:/app/output \
  <task-name>-tests

# Cleanup
docker stop impl && docker rm impl
docker network rm test-net
```

### Implementation Requirements

Your implementation must:
- Listen on port 3000
- Bind to `0.0.0.0` (not `127.0.0.1`) to accept connections from other containers

## Output

Results are written to `output/results.json`:

```json
{
  "numTotalTests": 272,
  "numPassedTests": 272,
  "numFailedTests": 0,
  "testResults": [...]
}
```

Exit code is 0 if all tests pass, non-zero otherwise.
