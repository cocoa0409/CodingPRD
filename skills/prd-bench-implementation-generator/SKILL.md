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
- **Code organization**: Group by concern. Follow this layout:
  ```
  implementation/
  ├── Dockerfile
  ├── requirements.txt
  ├── app.py              # Entry point, error handlers, route registration
  ├── db.py               # In-memory data store
  ├── errors.py           # Error classes and error ID constants
  ├── response.py         # Standard response envelope helpers
  ├── middleware.py        # Auth header extraction, role checking
  ├── routes/             # One file per resource group
  │   ├── shops.py
  │   ├── products.py
  │   └── ...
  └── services/           # Business logic, calculations, state transitions
      ├── shop.py
      ├── discount.py
      └── ...
  ```

### Step 3: Implement — Follow This Priority Order

Build in this order so each layer can be tested incrementally:

#### 3.1 Foundation
- Response envelope (meta with api_request_id, api_request_timestamp; data; response_type)
- Error handling (custom exception class that carries error_id, message, http_status)
- Auth middleware (extract X-User-ID and X-User-Role headers, reject missing/invalid)
- In-memory data store with UUID generation and timestamp management
- Common fields (id, created_at, updated_at, version) auto-populated on create/update

#### 3.2 CRUD for Each Entity
- Follow the `entities` table field by field
- Implement `source: system` fields (auto-set by server)
- Implement `source: computed` fields (derived from other data)
- For list endpoints: support `limit`, `offset` query params with defaults (limit=20, max=100), return `total_count` and `has_more` in meta
- Sort list results by `created_at` ascending

#### 3.3 State Machines
- Implement every transition from the `state_machines` table
- Enforce `preconditions` — return the correct error if violated
- Execute `side_effects` — these are where the tricky bugs hide
- For cascading side effects (e.g., suspending a shop delists all its products), update each child resource independently (each gets its own updated_at and version bump)
- For parallel state dimensions (e.g., payment_status x fulfillment_status), track them independently and derive the compound status

#### 3.4 Calculations
- This is the hardest part. Implement each calculation rule from the `calculations` table exactly.
- **Promotional discount stacking**: Pay close attention to the shop's `discount_strategy` (PERCENTAGE_FIRST vs FIXED_FIRST). The sorting and application order matters. Each step rounds to 2 decimal places (round half up). The running total floors at 0.01.
- **Discount share allocation**: Proportional distribution with last-item remainder. Sort items by order_item_id ascending. The last item absorbs rounding differences.
- **Inventory reservation**: Atomic — if any item fails, roll back all. Track reserved_count and available_count.
- **Commission calculation**: Marginal tiers, not flat rate. An order can span multiple tiers. Calculate based on shop's `monthly_gmv` *before* adding this order.
- **Refund amount calculation**: Proportional discount reallocation with remainder on last item. Track cumulative refunds to prevent exceeding total_amount.
- **Settlement reconciliation**: Aggregate completed orders and processed refunds within the period window.

#### 3.5 Validations
- Implement validations in the priority order specified in the `validations` table
- The priority order determines which error is returned when multiple validations fail simultaneously
- Check auth first (priority 1-2), then existence (3), then state (4), then business rules (5+)

#### 3.6 RBAC
- Enforce role-based access per the `roles` table
- Ownership checks: Seller can only manage their own shop, Customer can only manage their own orders
- "Any" role means any authenticated user can access

### Step 4: Get the Details Right

These are the things that differentiate a passing implementation from a failing one:

**Response format** — Every response must use the exact envelope structure from the PRD:
```json
{
  "meta": {
    "api_request_id": "unique-string",
    "api_request_timestamp": "2026-03-15T14:22:31.847Z"
  },
  "response_type": "object" | "array" | "error",
  "data": { ... }
}
```
List responses add `limit`, `offset`, `total_count`, `has_more` to meta.

**Timestamps** — ISO 8601 UTC with exactly 3 fractional digits: `2026-03-15T14:22:31.847Z`

**Monetary values** — 2 decimal places, round half up. Use Python's `decimal.Decimal` for all money calculations. Never use `float` for money.

**Optimistic concurrency** — When request includes `version`, compare against stored version. Mismatch → `ERR_STALE_DATA` (409). When `version` is omitted, skip the check.

**Hierarchical resource validation** — Validate path params left to right. For `/shops/{shopId}/products/{productId}`, check shopId exists before productId. Return the first not-found error.

**Nested resource ownership** — For shop-scoped resources (products, promotions, settlements), verify the resource belongs to the shop in the URL path.

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

1. **Floating point arithmetic for money** — Always use `from decimal import Decimal, ROUND_HALF_UP`. Never use `float`. `0.1 + 0.2 != 0.3` in IEEE 754.
2. **Wrong rounding** — Python's built-in `round()` uses banker's rounding. Always use `Decimal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)`.
3. **Discount stacking order** — The discount_strategy changes *which promotions are applied first*, not just their priority. PERCENTAGE_FIRST means all percentage promos before all fixed promos, regardless of priority. Within each type group, sort by priority.
4. **Commission tier calculation** — It's marginal, not flat. Don't apply a single rate to the whole order. Split across tier boundaries.
5. **Refund discount share** — When refunding, the discount must be proportionally un-applied. The refund amount is less than the face value because part of it was "discount".
6. **Cascade side effects updating version** — Each cascaded child resource must get its own version increment and updated_at change.
7. **Reservation atomicity** — Check ALL items have sufficient inventory before reserving ANY. If one fails, reserve none.
8. **Promotion filtering** — Time window check, category match, usage count check, stackability rules, and priority selection all interact. Get the order right.
9. **Payment flow** — The order has both payment_status and fulfillment_status. The derived order_status depends on both. Don't conflate them.
10. **Settlement period overlap** — Check against existing non-terminal settlements only. Terminal states (PAID, DISPUTED that's been resolved) don't count... but DISPUTED itself is non-terminal.

## Output Checklist

Before declaring done, verify:

- [ ] `implementation/Dockerfile` exists and follows INSTRUCTION.md constraints
- [ ] Server starts and listens on PORT env var, bound to 0.0.0.0
- [ ] All endpoints from the endpoint table are implemented
- [ ] Response envelope matches PRD format exactly (meta, response_type, data)
- [ ] Auth middleware validates X-User-ID and X-User-Role headers
- [ ] RBAC enforced per role matrix
- [ ] All state machines implemented with preconditions and side effects
- [ ] All calculations implemented with correct precision and rounding
- [ ] All validations enforced in priority order
- [ ] All error codes return correct HTTP status
- [ ] Optimistic concurrency control works when version is provided
- [ ] Pagination works with limit, offset, total_count, has_more
- [ ] Timestamps are ISO 8601 UTC with 3 fractional digits
