---
name: prd-bench-implementation-generator
description: >
  Generate a complete REST API server implementation from a PRD benchmark task.
  Each task lives under tasks/<task_name>/ and contains workspace/PRD.md (natural
  language requirements), SCAFFOLD.yaml (structured entity/state-machine/calculation
  definitions), and workspace/INSTRUCTION.md (build constraints including Dockerfile
  requirements). The skill produces a fully working codebase in
  workspace/implementation/ — source code, Dockerfile, and all dependencies — that
  passes the benchmark's automated test suite. Use this skill whenever the user
  wants to implement, build, or code a PRD benchmark task, or asks to generate
  an implementation from a PRD and scaffold. Also trigger when the user mentions
  "implement the e_commerce task", "build the API from PRD", "generate code for
  this benchmark", or similar requests referencing PRD-to-code generation.
---

# PRD Benchmark Implementation Generator

You are building a complete, production-quality REST API server from a PRD benchmark task. The task directory contains all the specifications you need. Your job is to read them carefully, understand every requirement, and produce an implementation that passes the automated test suite.

## Task Structure

Every benchmark task lives under `tasks/<task_name>/` with this layout:

```
tasks/<task_name>/
├── SCAFFOLD.yaml              # Structured spec: entities, state machines, calculations, validations, endpoints, errors, RBAC
├── workspace/
│   ├── PRD.md                 # Natural language requirements document
│   ├── INSTRUCTION.md         # Build constraints (Dockerfile, port, etc.)
│   └── implementation/        # YOUR OUTPUT GOES HERE
```

## How to Use This Skill

### Step 1: Read All Three Input Files

Read them in this order — each layer adds context the next one needs:

1. **`workspace/INSTRUCTION.md`** — Short. Tells you what to produce (Dockerfile + source code in `./implementation/`) and the hard constraints (listen on `PORT` env var, bind `0.0.0.0`, respond within 60s of container start).

2. **`SCAFFOLD.yaml`** — The structured backbone. Contains:
   - `entities` — Every data model, its fields, types, sources (input/computed/system), and parent relationships
   - `state_machines` — Every state transition with triggers, actors, preconditions, and side effects
   - `calculations` — Algorithmic rules (discount stacking, commission tiers, refund allocation, etc.) with formulas, precision requirements, and variant descriptions
   - `validations` — Ordered by priority: auth → existence → state → business rules, each with error_id and HTTP status
   - `endpoints` — Every API route with method, path, roles, status code, input/output, and side effects
   - `errors` — Complete error catalog with IDs, HTTP codes, and trigger conditions
   - `roles` — RBAC matrix listing exclusive and shared operations per role

3. **`workspace/PRD.md`** — The natural language requirements. This is the authoritative spec for behavior, edge cases, and business logic nuances that the SCAFFOLD encodes structurally. When in doubt about intent, the PRD's prose wins. Pay special attention to:
   - Section 2 (Global Specs): response envelope format, pagination, common fields, monetary precision, optimistic concurrency, cascade rules
   - Section 3 (Business Logic): the detailed workflows, especially calculation examples with concrete numbers
   - Sections 4-5: endpoint table and error catalog for cross-referencing

### Step 2: Plan the Architecture

Before writing code, decide on:

- **Language & framework**: Always use **Python + Flask**. This is the mandated stack for all benchmark implementations — it produces correct behavior, is easy to reason about, and the Dockerfile is minimal.
- **Data storage**: In-memory is fine (and recommended). These benchmarks test API correctness, not database durability. Use dictionaries/maps keyed by ID.
- **Code organization**: Ensure the code is strictly modularized — split by concern (entry point, data store, error definitions, response helpers, auth/middleware, per-resource routes, business-logic services) so no single file accumulates unrelated responsibilities. The exact filenames and directory layout are up to you; pick names that match the entities and concerns in the scaffold.

### Step 3: Implement — Follow This Priority Order

Build in this order so each layer can be tested incrementally:

#### 3.1 Foundation — Read From Scaffold, Never Hardcode

**Critical**: Every structural name below must be **read from the scaffold and PRD**, not assumed or defaulted. Different scaffolds use different header names, envelope field names, pagination styles, OCC mechanisms, and error ID patterns. You must faithfully implement whatever the scaffold defines.

**Response envelope** — Read the `response_envelope` section in SCAFFOLD.yaml. It defines:
- `response_envelope.success`: The exact JSON structure for successful responses — field names for the metadata wrapper, the type discriminator, and the data payload. These names vary per scaffold (e.g., one scaffold might use `meta`/`response_type`/`data`, another might use `result`/`kind`/`payload`).
- `response_envelope.error`: The exact JSON structure for error responses — field names for the error code and message. These names vary per scaffold (e.g., `error_id`/`message` vs `code`/`detail`).
- `response_envelope.pagination_fields`: The exact parameter names for pagination (e.g., `limit`/`offset`/`total_count`/`has_more` vs `page_size`/`page_token`/`total_results`/`next_page_token`).
- `response_envelope.pagination_defaults`: Default values, min, max for pagination parameters.

Implement the response helper to produce exactly the structure the scaffold defines. Do NOT assume any fixed field names.

**Error handling** — Custom exception class that carries `error_id`, `message`, `http_status`. The error_id values come from the `errors` table in the scaffold. The error response body must use the exact field names from `response_envelope.error`.

**Auth middleware** — Read `validations[]` entries with `category: auth` in the scaffold. The `check` field describes exactly which HTTP headers must be present and what role values are valid. Extract the exact header names from this description (e.g., one scaffold might use `X-User-ID`/`X-User-Role`, another might use `X-Student-Number`/`X-Instructor-Id`/`X-Registrar-Id`/`X-Caller-Role`). Also read the corresponding `error_id` values for auth failures — do not assume any fixed error ID.

Additionally, cross-reference with **PRD §2.1** (User and Role-Based Access Control) which explicitly states the auth header names and role values. The PRD's description is authoritative.

**In-memory data store** — UUID generation and timestamp management.

**Common fields** — Read `entities[]` in the scaffold to find which fields are `source: system` (auto-populated on create/update). Field names vary per scaffold — one might use `created_at`/`updated_at`/`version`, another might use `opened_on`/`modified_on`/`enrollment_seq`. Never assume fixed names.

#### 3.2 CRUD for Each Entity
- Follow the `entities` table field by field
- Implement `source: system` fields (auto-set by server) using the exact field names from the scaffold
- Implement `source: computed` fields (derived from other data)
- For list endpoints: use the pagination parameter names and defaults from `response_envelope.pagination_fields` and `response_envelope.pagination_defaults` — do NOT hardcode `limit`/`offset` or any other fixed names
- Sort list results by the default sort field specified in the scaffold or PRD

#### 3.3 State Machines
- Implement every transition from the `state_machines` table
- Enforce `preconditions` — return the correct error if violated, using the exact error_id from the scaffold
- Execute `side_effects` — these are where the tricky bugs hide
- For cascading side effects, update each child resource independently (each gets its own timestamp and concurrency field bump, using whatever field names the scaffold defines)
- For parallel state dimensions, track them independently and derive the compound status

#### 3.4 Calculations
- This is the hardest part. Implement each calculation rule from the `calculations` table exactly.
- Read the `formula`, `precision`, and `variants` fields carefully
- Follow the exact algorithm described — stacking order, rounding rules, edge case handling
- When the scaffold specifies precision (decimal places, rounding method), implement it exactly
- For complex multi-step calculations, trace through the scaffold's description step by step

#### 3.5 Validations
- Implement validations in the priority order specified in the `validations` table
- The priority order determines which error is returned when multiple validations fail simultaneously
- Check auth first (lowest priority number), then existence, then state, then business rules
- Use the exact `error_id` and `http_status` from the scaffold for each validation

#### 3.6 RBAC
- Enforce role-based access per the `roles` table
- Use the exact role names from `roles[].name` in the scaffold
- Ownership checks: use the identity header names defined in the scaffold's auth validation rules
- "Any" role (or equivalent) means any authenticated user can access

### Step 4: Get the Details Right

These are the things that differentiate a passing implementation from a failing one:

**Response format** — Every response must use the **exact envelope structure defined in the scaffold's `response_envelope` section and described in PRD §2.2**. Do NOT assume any fixed field names. Read the scaffold to determine:
- What the metadata wrapper field is called and what fields it contains (request ID, timestamp)
- What the type discriminator field is called and what values it takes
- What the data wrapper field is called
- What field names the error response uses for the error code and message
- What pagination fields are added to list responses and where they appear

**Timestamps** — Read the PRD §2 for the exact timestamp format. Typically ISO 8601 UTC, but the precision (fractional digits) may vary per scaffold.

**Monetary/numeric precision** — Read `calculations[].precision` in the scaffold. Use Python's `decimal.Decimal` for precision-sensitive calculations. Never use `float` for money. The rounding method is specified in the scaffold.

**Optimistic concurrency** — Read the scaffold's `validations[]` for the OCC check. The concurrency control field name varies per scaffold (e.g., `version`, `enrollment_seq`, `rev`). The corresponding error ID and HTTP status also vary. When the OCC field is provided in the request, compare against the stored value. Mismatch → the scaffold-defined error. When the field is omitted, skip the check.

**Hierarchical resource validation** — Validate path params left to right. For nested paths like `/parents/{parentId}/children/{childId}`, check parentId exists before childId. Return the first not-found error.

**Nested resource ownership** — For scoped resources, verify the resource belongs to the parent in the URL path.

### Step 5: Build the Dockerfile

Use a Python base image. Follow the constraints from INSTRUCTION.md:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "app.py"]
```

- Server listens on `PORT` env var (default 10000)
- Bind to `0.0.0.0`
- Respond within 60 seconds of container start

### Common Pitfalls to Avoid

1. **Hardcoding structural names** — The #1 cause of test failures. Auth header names, response envelope field names, pagination parameter names, OCC field names, error IDs — ALL of these must be read from the scaffold and PRD, never assumed. If you find yourself typing `X-User-ID`, `meta`, `response_type`, `data`, `limit`, `offset`, `version`, or `ERR_STALE_DATA` without having verified these are the exact names in this scaffold, STOP and re-read the scaffold.
2. **Floating point arithmetic for money** — Always use `from decimal import Decimal, ROUND_HALF_UP`. Never use `float`. `0.1 + 0.2 != 0.3` in IEEE 754.
3. **Wrong rounding** — Python's built-in `round()` uses banker's rounding. When the scaffold specifies a rounding method, use the corresponding `Decimal` rounding mode.
4. **Cascade side effects not updating concurrency fields** — Each cascaded child resource must get its own concurrency field increment (whatever it's called in this scaffold) and timestamp change.
5. **Atomicity violations** — When a multi-step operation must be atomic (e.g., reserving multiple items, bulk state transitions), check ALL preconditions before committing ANY changes. If one fails, roll back all.
6. **State machine precondition ordering** — When multiple validations can fail simultaneously, the scaffold's `validations` table priority order determines which error is returned. Don't just check the first one you think of.
7. **Calculation formula fidelity** — Implement calculations exactly as the scaffold describes. Pay attention to: marginal vs flat tiers, stacking order, proportional allocation with remainder handling, cumulative limits.
8. **Parallel state dimensions** — When an entity has multiple independent state fields (e.g., payment_status and fulfillment_status), track them independently. The derived compound status depends on both.
9. **Auth header semantics** — Some scaffolds use a single identity header for all roles; others use role-specific identity headers (different header per role). Read the scaffold's auth validation rules carefully to understand the expected header scheme.
10. **Pagination mechanism** — Some scaffolds use offset-based pagination (`limit`/`offset`), others use cursor-based (`page_size`/`page_token`). Implement exactly what the scaffold defines, not what you assume.

## Output Checklist

Before declaring done, verify:

- [ ] `implementation/Dockerfile` exists and follows INSTRUCTION.md constraints
- [ ] Server starts and listens on PORT env var, bound to 0.0.0.0
- [ ] All endpoints from the endpoint table are implemented
- [ ] Response envelope matches the scaffold's `response_envelope` exactly — correct field names for metadata, type discriminator, data wrapper, and error body
- [ ] Auth middleware validates the exact headers defined in the scaffold's auth `validations[]` — not hardcoded defaults
- [ ] RBAC enforced per role matrix using the scaffold's exact role names
- [ ] All state machines implemented with preconditions and side effects
- [ ] All calculations implemented with correct precision and rounding as specified in the scaffold
- [ ] All validations enforced in priority order with the scaffold's exact error_ids
- [ ] All error codes return the correct HTTP status from the scaffold's error catalog
- [ ] Optimistic concurrency control uses the scaffold's exact OCC field name and error ID
- [ ] Pagination uses the scaffold's exact parameter names, defaults, min/max from `response_envelope.pagination_fields` and `response_envelope.pagination_defaults`
- [ ] Timestamps match the format specified in the PRD
- [ ] **No structural name was assumed or hardcoded** — every header name, field name, error ID, and parameter name was read from the scaffold or PRD
