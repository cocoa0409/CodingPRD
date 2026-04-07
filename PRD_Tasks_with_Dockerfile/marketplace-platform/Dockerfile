# Marketplace Platform - Black-box Test Suite
#
# Packages the test suite for running against any implementation.
# Both containers should run on the same Docker network.
#
# Usage:
#   docker network create test-net
#   docker run -d --name impl --network test-net <implementation-image>
#   docker run --rm --network test-net -e API_URL=http://impl:3000 -v $(pwd)/output:/app/output marketplace-tests
#
# Results written to: /app/output/results.json
# Exit code: 0 if all tests pass, non-zero otherwise

FROM node:18-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json tsconfig.test.json ./
COPY jest.config.ts ./
COPY console-sanitizer.ts ./
COPY jest-results-processor.js ./
COPY test-helpers/ ./test-helpers/
COPY versions/v1/test_suite/ ./versions/v1/test_suite/

RUN mkdir -p /app/output

ENV API_URL=http://localhost:3000
ENV SKIP_SERVER_LIFECYCLE=true

CMD ["sh", "-c", "npm test 2>&1; cp /app/results.json /app/output/results.json 2>/dev/null || true; exit $?"]
