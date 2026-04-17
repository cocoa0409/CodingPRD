---
name: prd-bench-scaffold-generator
description: Generate structured seed tables (entity model, state machines, calculations, validations, API endpoints, error catalog, RBAC) from a scenario description. These seed tables serve as the single source of truth for downstream PRD generation, test suite generation, and reference implementation.
---

# PRD Benchmark Scaffold Generator

## Input / Output

### Input

User provides two things:

1. **Scenario description**: A natural-language description of the system to build, including roles and core workflows.

2. **Output file path**: Where to save the generated YAML file.

### Output

A complete YAML file saved to the user-specified path, containing 7 top-level sections:

```yaml
scenario: "User-provided scenario description"
domain_name: "kebab-case-domain-name"
api_prefix: "/top-level-resource-path"
complexity_profile: { ... }   # Selected archetype and structural dimensions

entities:                    # §1.1: Entity-Relationship Table
state_machines:              # §1.2: State Machine Table
calculations:                # §1.3: Calculation Rules Table
validations:                 # §1.4: Validation Rules Table (ordered by priority)
endpoints:                   # §1.5: API Endpoint Table
errors:                      # §1.6: Error Code Catalog
roles:                       # §1.7: RBAC Matrix
scaffold_difficulty_design:  # §1.8: Test Targeting Index — summary of §1.1–§1.7 cross-referenced per Difficulty rule
```

For completed examples, see the `examples/` directory (22 scaffolds covering diverse domains)
For a blank template, see [examples/seed-tables-template.yaml](examples/seed-tables-template.yaml).

## Generation Checklist

```
- [ ] 0: Select complexity profile (§0.1–§0.4)
- [ ] 0.5: Internalize the seven Difficulty Rules (§0.5) — keep them in mind while drafting §1.1–§1.7, not as a post-hoc audit
- [ ] 1.0: Response Envelope — emit the FIXED block verbatim (§1.0)
- [ ] 1.1: Entity-Relationship Table
- [ ] 1.2: State Machine Table
- [ ] 1.2.1: Concurrency Rules
- [ ] 1.3: Calculation Rules Table
- [ ] 1.4: Validation Rules Table (ordered)
- [ ] 1.5: API Endpoint Table
- [ ] 1.6: Error Code Catalog
- [ ] 1.7: RBAC Matrix
- [ ] 1.8: Scaffold Difficulty Design (Test Targeting Index)
- [ ] Final: Quality + Diversity check (§Quality Checklist)
```

---

## Step 0: Complexity Profile Selection

Before generating tables, select the structural DNA of the benchmark. This is the most important step — it determines the fundamental character of the challenge and prevents convergence toward a single template.

### 0.1 Primary Archetypes

Each archetype represents a fundamentally different core challenge. Choose ONE primary archetype, optionally blend with a secondary.

| Archetype | Core challenge | What makes it hard | Example domains |
|-----------|---------------|-------------------|-----------------|
| **Ledger reconciliation** | Same data, two algorithms, different results | Forward-looking vs chronological produce divergent costs for identical inputs | Hospital billing, insurance claims, tax withholding |
| **Quota / allocation** | Finite pool competed for, reserved, committed, released | Fragmentation, over-subscription policies, priority preemption, waterfall fallback | Cloud resource quotas, inventory reservation, seat assignment |
| **Graph constraint** | Entities form a DAG with dependency/ordering rules | Cycle detection, transitive closure, conditional propagation | Course prerequisites, build pipelines, supply chain BOM |
| **Posture-driven gating** | Derived aggregate state gates all child operations | Posture computed from children, cascading freezes, ops-run checkpoints | Dock operations, podcast scheduling, sponsorship events |
| **Pricing engine** | Dynamic pricing based on multi-dimensional rules | Tiered rates, volume discounts, time-of-use, promotional stacking, rounding traps | Utility billing, SaaS metering, airline yield management |
| **Event sourcing** | State derived by replaying an ordered event stream | Snapshot invalidation, late-arriving events, retroactive corrections | Order lifecycle + refunds, audit reconstruction, version history |
| **Access control matrix** | Fine-grained, context-dependent permissions | Attribute-based rules, delegation chains, temporary grants, scope inheritance | Document sharing, healthcare data access, multi-tenant SaaS |
| **Multi-party negotiation** | Multiple independent actors must reach agreement | Quorum logic, timeout/escalation, conditional delegation, veto power | Contract approval, loan origination, committee voting, peer review |
| **Temporal windowing** | Overlapping/adjacent time intervals with gap rules | Half-open vs closed intervals, merge/split semantics, cross-resource scheduling | Room booking, spectrum allocation, maintenance windows |
| **Workflow orchestration** | Configurable multi-step pipelines with branching | Conditional routing, parallel fan-out/fan-in, compensation on failure, idempotency | CI/CD pipelines, document processing, onboarding flows |
| **Compliance / audit** | Actions constrained by regulatory rules with audit trail | Mandatory cooling-off periods, segregation of duties, tamper-evident logs | Financial trading, pharmaceutical dispensing, government procurement |

**Diversity guidance**: When the scenario could fit multiple archetypes, prefer one that is structurally different from recent scaffolds. Multi-party negotiation, temporal windowing, workflow orchestration, and compliance/audit are high-priority targets for new scenarios.

### 0.2 Cross-Cutting Complexity Layers

These are independent difficulty dimensions that can be **layered onto any archetype**. Select 2–4 that fit the scenario:

| Layer | What it adds | Difficulty mechanism |
|-------|-------------|---------------------|
| **Optimistic concurrency** | Version-based conflict detection | Stale-data races, retry semantics. OCC alone only covers version-field conflicts on PATCH/PUT. If the scenario also has race-condition constraints (e.g., "at most one delivery per order"), define them explicitly in `concurrency_rules` (see §1.2.1). |
| **Cascading side effects** | One mutation triggers chain of dependent updates | N-level propagation, ordering sensitivity, partial failure |
| **Dual-variant calculation** | Same inputs, two valid algorithms, different outputs | Provisional vs final, optimistic vs pessimistic, estimate vs actual |
| **Rate / threshold triggers** | Behavior changes at configurable breakpoints | Boundary precision (>= vs >), cumulative vs instantaneous, threshold reset |
| **Derived field reconciliation** | Denormalized fields must stay consistent with source data | When to recompute, stale cache detection, consistency on partial update |
| **Ops-run checkpoint** | Periodic batch operation advances system epoch | Stale expiry, waitlist promotion, posture recalculation per epoch |
| **Contagion / risk propagation** | Side effects cascade with multiplicative risk scoring | Penalty accumulation, threshold breach with override, score floor/ceiling |
| **Version-pinning on approval** | Lock reference object versions when approved | Stale reference detection, re-validation on state change |
| **Scheduled / deferred actions** | Actions take effect at a future time | Clock dependency, cancellation before execution, what-if projections |
| **Soft delete / archival** | Resources are deactivated but still queryable | Filter semantics (include archived?), referential integrity with archived parents |
| **Idempotency** | Repeated identical requests produce same result | Idempotency keys, at-least-once delivery, duplicate detection |
| **Pagination with filtering** | List endpoints support complex query parameters | Filter + sort + paginate interaction, cursor vs offset, consistency under mutation |
| **Bulk operations** | Single request affects multiple resources | Partial success/failure, transactional vs best-effort, rollback semantics |
| **Multi-tenancy isolation** | Resources partitioned by tenant/scope | Cross-tenant leakage prevention, tenant-scoped uniqueness, shared vs private resources |
| **Conditional feature flags** | Behavior varies based on entity-level configuration | Combinatorial explosion of code paths, defaults vs overrides, migration from old behavior |

### 0.3 Structural Dimensions

Independent axes that shape the scaffold's skeleton. Let the scenario dictate — do NOT default to any single configuration:

```yaml
complexity_profile:
  primary_archetype: <one from §0.1>
  secondary_archetype: null | <another from §0.1>
  complexity_layers: [<2-4 from §0.2>]

  entity_topology: hierarchical | flat | graph | hybrid
  # hierarchical: strict parent-child tree (hospital-shifts)
  # flat: peer entities with foreign key references (no nesting in URL paths) — 0% in current examples, PRIORITIZE
  # graph: many-to-many, DAG, or cyclic references — 0% in current examples, PRIORITIZE
  # hybrid: mix of above (e.g., tree with cross-cutting associations) — 100% of current examples, AVOID for diversity

  state_machine_shape: linear | branching | cyclic | parallel | compound | posture_driven
  # linear: A→B→C (simple pipeline) — 77% of examples
  # branching: fork/join, approve-or-reject — 0%, PRIORITIZE
  # cyclic: A→B→A allowed (revision loops, negotiation rounds) — 0%, PRIORITIZE
  # parallel: independent state dimensions on same entity (payment_status × fulfillment_status) — rare
  # compound: entity state depends on aggregate state of children — 23% of examples
  # posture_driven: derived aggregate field (OPEN/RESTRICTED/FROZEN) gates all child operations — 32% of examples, NEW

  relationship_patterns:
    # Check all that apply:
    # - one_to_many: parent has many children
    # - many_to_many: junction/association entities
    # - self_referential: entity references itself (tree, linked list) — 0% in examples, PRIORITIZE
    # - polymorphic: one field can reference different entity types
    # - cross_aggregate: reference across aggregate boundaries

  role_model: approval_chain | peer_roles | hierarchical_override | delegated_authority | single_role | segregation_of_duties
  # approval_chain: Requester → Reviewer → Approver
  # peer_roles: each role owns different resource types
  # hierarchical_override: admin superset + override power
  # delegated_authority: roles can temporarily grant permissions to others
  # single_role: all operations by any authenticated user (common in simpler PRDs) — 5/22 examples
  # segregation_of_duties: same person cannot do step A and step B — 0%, PRIORITIZE for compliance

  consistency_model: immediate | eventual | saga
  # immediate: all changes atomic in single request
  # eventual: denormalized fields reconciled asynchronously or on read
  # saga: multi-step workflow with compensation on failure
```

### 0.4 Difficulty Calibration

Benchmarks exist to stress-test LLM coding ability. **Difficulty does NOT come from piling on more entities, endpoints, or error codes.** A small, tightly-coupled scaffold is harder than a big, loosely-coupled one — aim for density, not volume. Keep the surface lean so the interesting mechanics dominate.

Target one of these two difficulty levels:

| Level | Entity count | Endpoint count | Error codes | Calculation variants | State machines | Typical token budget |
|-------|-------------|---------------|-------------|---------------------|---------------|---------------------|
| **Advanced** | 6–10 | 12–22 | 10–18 | 2–3 | 3–5 with reverts + auto-transitions | ~25k |
| **Expert** | 10–15 | 20–32 | 18–30 | 3+ | 4+ with cycles or parallel dimensions | ~40k |

**Default to Advanced.** Only go Expert when the scenario genuinely needs more entity types to express the core coupling — not just because there's more to describe. If you find yourself adding a table to pad the count, delete it: use that token budget to make the remaining entities interact more deeply instead. Never generate fewer than 6 entities or 12 endpoints.

These are guidelines, not hard rules. A 6-entity benchmark with one fiendishly tricky calculation and 4 cross-cutting gates is harder than a 20-entity CRUD app.

**What actually makes a benchmark hard (in order of impact):**
1. Calculations where two valid interpretations of the same prose produce different numbers
2. Side effect chains that span 3+ entities and depend on execution order
3. Validation priority conflicts where the "correct" error depends on check ordering
4. State transitions where the set of valid next-states depends on sibling/child state
5. Edge cases at exact boundaries (>=  vs >, empty sets, zero quantities)

### 0.5 Difficulty Rules

Seven hard rules that shape the scaffold's contents. They apply **while you are drafting §1.1–§1.7** (not as an afterthought), are cross-referenced by §1.8 Scaffold Difficulty Design (Test Targeting Index), and are audited at the end by the Quality Checklist. Each rule has a stable `rule_id` that §1.8 uses verbatim.

**Rule 1 — Dual-variant calculations across different entity domains**  (`rule_id: dual_variant_calc`, ≥ 2 instances)
At least two `calculations[]` entries where two valid approaches produce different results. The two calculations MUST operate on different entity domains (e.g., one is cost accounting on an Order, the other is risk scoring on a Customer), so the scaffold exhibits dual-variant logic on more than one subject. A second calculation that repeats the same provisional-vs-final shape on the same entity or metric does NOT count.

**Rule 2 — Combinatorial formula**  (`rule_id: combinatorial_formula`, ≥ 1 instance)
At least one calculation with combinatorial complexity, satisfied by any of:
(a) a formula with ≥3 inputs and non-linear interaction (nested `min`/`max`, conditional branches on entity state, tiered-rate selection);
(b) nested rounding where the order matters — "round per-line-item then sum" vs "sum then round" produce different cents; the scaffold MUST pin one order and state it explicitly;
(c) a circular-looking dependency where evaluation order must be explicit (e.g., `total = subtotal + fee`, but `fee` is computed from a discount keyed on the total tier — the scaffold pins the evaluation order so the value is well-defined).
A single-formula `aggregation` + `threshold` calculation does NOT satisfy this.

**Rule 3 — Non-linear state-machine shape on different entities**  (`rule_id: non_linear_state_machine`, ≥ 2 instances)
At least two state machines with non-linear shape — a cycle (A→B→A, revision loops, negotiation rounds), parallel state dimensions on one entity (e.g., `payment_status × fulfillment_status` evolve independently on the same row), OR branching fork-join (A→{B,C}→D with divergent side-effect sets per branch). The two non-linear machines MUST belong to different entities. A scaffold whose state machines are all linear A→B→C→D pipelines — no matter how long each pipeline is — does NOT satisfy this.

**Rule 4 — Transitive cascade chains from different triggers**  (`rule_id: transitive_cascade`, ≥ 2 instances)
At least two transitive cascades, at least one of depth ≥ 3 and the other of depth ≥ 2. Each cascade chains mutations where an action on entity A mutates B; that mutation on B **itself** triggers a mutation on C; (and so on). Each link MUST be caused by the previous link, not by the original action — a fan-out where one action directly mutates multiple targets in parallel does NOT count. The two cascades MUST originate from different triggering transitions, so the scaffold captures more than one propagation pattern. Spell each chain out in the relevant `state_machines[].transitions[].side_effects` entries so a PRD reader can follow each hop.

**Rule 5 — Validation priority conflicts across different error-category pairs**  (`rule_id: priority_pair_validation_conflict`, ≥ 2 instances)
At least two validation priority conflicts testable by dual-failure scenarios. The two conflicts MUST involve different error-category pairs (e.g., one is `state` vs `business_fiscal`, another is `business_safety` vs `business_referential`), so the scaffold exercises more than a single priority rule. A second copy of the same pairing does NOT count.

**Rule 6 — Boundary-precision checks on different metrics/endpoints**  (`rule_id: boundary_precision_check`, ≥ 2 instances)
At least two boundary conditions requiring exact precision (`>=` vs `>`, zero quantity, empty set). The two boundaries MUST sit on different metrics (e.g., one is a numeric threshold crossing, the other is an empty-collection or zero-count edge), and each MUST be reachable through a distinct endpoint. Two boundaries on the same formula do NOT count.

**Rule 7 — Cross-entity state dependencies across different entity pairs**  (`rule_id: cross_entity_state_dependency`, ≥ 2 instances)
At least two cross-entity state dependencies (entity A's valid transitions depend on entity B's state). The two dependencies MUST cross different entity pairs (e.g., Order→Customer and Shipment→Warehouse), so the scaffold forces reasoning about more than one cross-entity relationship. Two transitions on the same entity pair do NOT count.

---

## Table Specifications

### 1.0 Response Envelope (FIXED — EMIT VERBATIM)

Every scaffold MUST include a top-level `response_envelope:` block with the exact content below. Do not edit field names, key order, pagination defaults, or error-body keys

```yaml
response_envelope:
  success: |
    { "meta": { "api_request_id": "req_xxx", "api_request_timestamp": "ISO8601" },
      "response_type": "object" | "array", "data": {} }
  error: |
    { "meta": { ... }, "response_type": "error",
      "data": { "error_id": "ERR_XXX", "message": "..." } }
  pagination_fields: ["limit", "offset", "total_count", "has_more"]
  pagination_defaults: { limit: 10, min: 1, max: 100, offset: 0 }
```

**Hard rules (copy/paste — no variation):**
Scenario-specific customization goes into entities, endpoints, errors, calculations — NOT into the envelope.

### 1.1 Entity-Relationship Table

```yaml
entities:
  - name: EntityName
    parent: ParentEntity | null
    common_fields: true | false
    fields:
      - name: field_name
        type: string | number | integer | boolean | enum | datetime | array | object
        source: input | computed | system
        description: brief purpose
        default: optional default value
        constraints: optional constraint notes
```

**Design principles:**
- Entity count is bounded below by §0.4 (≥6 entities, ≥12 endpoints). If the scenario is too small to naturally reach that floor, expand scope — add subsidiary workflows, auxiliary entities, or cross-cutting concerns — rather than ship an under-specified benchmark. Do not inflate above what the scenario supports either; pick the Advanced vs Expert band per §0.4, and remember: difficulty comes from how tightly the entities you have interact, not from how many you list.
- At least one entity with computed fields that derive from cross-entity data
- Field names must be explicit — downstream PRD will reference them in prose
- `common_fields: true` expands to four fields on the entity: `id` (**server-minted UUID with no type prefix** — e.g., `"8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"`, NOT `"ord_8a3e1c0b-…"`), `created_at` (ISO 8601 UTC, three fractional digits), `updated_at` (same format, refreshed on every mutation including cascaded side effects), `version` (integer, starts at `1`, increments by one on every mutation). When `common_fields: false`, the entity carries only `id` and `created_at` — use this for immutable or append-only resources (event logs, pairings, ledger entries, configuration snapshots).
- Consider whether the entity is a **resource** (has lifecycle), **event** (append-only log), or **configuration** (rarely changes)

**Topology patterns:**

| Pattern | Structure | URL shape | When to use |
|---------|-----------|-----------|-------------|
| Strict hierarchy | A → B → C (tree) | `/a/{id}/b/{id}/c/{id}` | Clear ownership chain |
| Flat with references | A, B, C (FK links) | `/a/{id}`, `/b/{id}` with `a_id` in body | Peer entities, many-to-many |
| Hybrid | Tree + cross-cutting associations | Mix of nested + flat | When some entities span across the tree |
| Star schema | Central entity with many satellites | `/central/{id}/satellite-type` | Analytics/reporting focused |
| Event log | Append-only children under a parent | `/parent/{id}/events` | Audit trail, sourced state |

### 1.2 State Machine Table

```yaml
state_machines:
  - entity: EntityName
    initial_state: STATE_A
    terminal_states: [STATE_X, STATE_Y]
    transitions:
      - from: STATE_A
        to: STATE_B
        trigger: "POST /endpoint or system event description"
        actor: RoleName | system
        preconditions: [checks that must pass]
        side_effects: [cascading changes to this or other entities]
        note: optional clarification
```

**Shape patterns:**

| Shape | Diagram | Characteristics | When to use |
|-------|---------|----------------|-------------|
| Linear pipeline | A→B→C→D | No branching, no going back | Simple approval, manufacturing steps |
| Diamond (fork-join) | A→{B,C}→D | Parallel paths that converge | Parallel approvals, split-then-merge |
| Branching with revert | A→B→C, B→A | Forward + rollback | Review/reject cycles |
| Cyclic | A→B→C→A | Loops allowed | Negotiation rounds, iterative refinement |
| Parallel dimensions | (payment: P1→P2→P3) × (shipping: S1→S2→S3) | Independent state axes on one entity | Order with payment + fulfillment |
| Compound/aggregate | Parent state = f(children states) | Parent auto-transitions based on child states | Project = f(task statuses) |
| Guarded | A→B only if sibling entity in state X | Cross-entity preconditions | Dependent workflows |

**Side effect patterns:**

| Pattern | Description | Example |
|---------|-------------|---------|
| Cascade down | Parent change → children change | Cancel project → cancel all tasks |
| Bubble up | Child change → parent re-evaluates | All tasks done → project auto-completes |
| Cross-entity | Entity A change → entity B adjusts | Assignment cancel → procedure reverts, rotation demotes |
| Ledger sync | State change → derived field on ancestor recalculated | Assignment created → plan.cost_balance debited |
| Conditional cascade | Side effect depends on child's current state | Only cancel non-terminal children |
| Compensation | Undo side effects of a previous transition | Reject → refund cost + revert safety score |

### 1.2.1 Concurrency Rules

Every scaffold must define explicit concurrency rules for operations where concurrent execution could produce data integrity issues. Version-based OCC alone only detects stale writes — it does not specify what happens when two non-idempotent operations race (e.g., two riders assigned to the same order, or confirm vs cancel on the same resource).

Each rule uses this schema:

```yaml
concurrency_rules:
  - scenario: "<human-readable race condition>"
    guarantee: "<what the serialization guarantees>"
    error_id: ERR_XXX              # required — the loser's error_id
    http_status: 4xx               # required
    serialization: "<optional — tie-breaker rule (e.g., first-writer-wins on field X)>"
```

`error_id` and `http_status` are always required structured fields — downstream skills (doc-generator Pass B, test generator) read them by key and do not parse them out of `guarantee` prose.

**Examples:**

```yaml
concurrency_rules:
  - scenario: "Two riders assigned to the same order simultaneously"
    guarantee: "At most one delivery per order; second assignment rejected"
    error_id: ERR_DELIVERY_ALREADY_ASSIGNED
    http_status: 409
    serialization: "First-writer-wins on assignment creation"

  - scenario: "Restaurant confirms order while customer cancels simultaneously"
    guarantee: "Exactly one operation succeeds; loser is rejected"
    error_id: ERR_INVALID_STATE
    http_status: 409
    serialization: "First-writer-wins on order status"
```

All error codes referenced here must also appear in the Error Catalog (§1.6).

**Consistency with §1.2 and §1.4:** If a single race scenario can legitimately produce more than one loser error (e.g., `ERR_INVALID_STATE` when the status already advanced vs. `ERR_HAS_DEPENDENCIES` when a dependent exists), split it into multiple `concurrency_rules` entries — one per possible loser error — rather than packing alternatives into a single `guarantee`. Downstream tests assert exactly one `error_id` per rule.

### 1.3 Calculation Rules Table

```yaml
calculations:
  - name: rule_name
    trigger: "when this calculation runs"
    algorithm: <algorithm type>
    formula: |
      pseudocode
    input_set: "description of which entities/states are included"
    constants:
      KEY: value
    precision: "2 decimal places, round_half_up"
    variants:
      - name: variant_name
        when: "context where this variant applies"
        difference: "how it diverges from the base"
```

**Algorithm types (extensible — add domain-specific ones):**

| Type | Description | Difficulty source |
|------|-------------|-------------------|
| `forward_looking` | Estimate based on projected future state | What counts as "projected"? Inclusion set ambiguity |
| `chronological` | Process in time order, running accumulator | Order-dependent results, tie-breaking rules |
| `aggregation` | Running totals, sums, counts, averages | Incremental update vs full recompute, consistency |
| `threshold` | Behavior changes at breakpoints | Boundary precision (>= vs >), partial crossing |
| `topological` | Graph traversal order determines result | Cycle handling, disconnected components |
| `projection` | Derive current state from event replay | Late events, snapshot optimization |
| `interval_merge` | Combine overlapping time windows | Boundary semantics, gap detection |
| `tiered_pricing` | Rate changes at volume breakpoints | Marginal vs average rate, tier boundary allocation |
| `weighted_scoring` | Multi-factor score with configurable weights | Normalization, rounding accumulation, weight changes |
| `decay_function` | Value diminishes over time/usage | Continuous vs step decay, reset events |
| `constraint_propagation` | Change in one variable forces changes in others | Propagation order, fixed-point convergence |
| `waterfall_allocation` | Distribute a fixed amount across ordered buckets | Overflow handling, priority ordering, rounding remainders |

**What makes a calculation rule a good benchmark challenge:**
- Two variants (e.g., provisional vs final) that produce **different results for identical data**
- Input set that depends on **state filtering** (which statuses to include/exclude)
- A **reset mechanism** that changes the baseline (servicing resets usage, payment resets balance)
- **Order sensitivity** — processing the same items in different orders yields different results
- **Boundary precision** — exact behavior at threshold boundaries (does 6000 trigger, or 6001?)

### 1.4 Validation Rules Table (Ordered by Priority)

```yaml
validations:
  - priority: 1
    category: auth | existence | state | business_safety | business_fiscal | business_constraint | business_temporal | business_referential
    check: "description of what to validate"
    error_id: ERR_SOMETHING
    http_status: 400 | 401 | 402 | 403 | 404 | 409 | 422
    applies_to: "which endpoints or 'all'"
```

**Standard priority grouping (customize per domain):**

```
1. Authentication (headers present and valid)
2. Authorization (role permitted for this operation)
3. Existence (referenced resources exist, validated left-to-right in path)
4. State preconditions (target resource in correct state for this operation)
5. Business rules — ordered by domain priority:
   a. Safety / compliance / regulatory (if applicable)
   b. Constraint satisfaction (graph deps, temporal conflicts, uniqueness)
   c. Capacity / quota / budget (fiscal checks last)
```

The ordering within business rules is domain-specific. In a hospital system, safety checks precede budget checks. In a financial system, compliance checks might precede fraud checks. In an inventory system, availability checks might precede pricing checks.

**Validation patterns to consider:**

| Pattern | Description | Difficulty |
|---------|-------------|-----------|
| Priority ordering | Two checks fail simultaneously — which error wins? | Medium |
| Cascading validation | Check A depends on result of check B | Medium |
| Cross-entity validation | Validity depends on state of a different entity | High |
| Temporal validation | Valid now but would create future conflict | High |
| Aggregate validation | Valid individually but invalid collectively (e.g., total exceeds limit) | High |
| Conditional validation | Rules change based on entity configuration/flags | High |

### 1.5 API Endpoint Table

```yaml
endpoints:
  - method: POST | GET | PUT | PATCH | DELETE
    path: "/resource-path"
    description: "what it does"
    roles: [RoleA, RoleB]
    code: 200 | 201 | 204
    input: [field_name, other_field?]
    output: ResourceName | ResourceName[] | null
    side_effects: [triggered calculations or state changes]
```

**Design principles:**
- **Testability-completeness (value-level principle, overrides convenience).** The scaffold owes the test layer a reachable path to every state it declares. Walk every state in your state machines and ask: *"can a test reach this from empty-DB using only the endpoints I've listed?"* If a state is gated by wall-clock time, a background sweep, or an external event, you MUST include the test-driving endpoint that makes it reachable — e.g., `POST /_clock/advance` for any time-gated transition (`now() >= X`), `POST /_sweep/run` for any automatic sweep, `POST /_events/emit` for any external-event trigger. Declaring behavior without also declaring the API surface needed to exercise it is an **incomplete contract** — downstream tests will be forced to skip, and skips are forbidden by the unit-test-generator. A scaffold is judged not only by what behavior it specifies, but by whether every specified behavior can be *reached, observed, and asserted* through the declared API.
- URL structure reflects entity topology (nested for hierarchical, flat for peer)
- Include action endpoints (e.g., `/activate`, `/cancel`, `/approve`) — not just CRUD
- Mutation endpoints accept optional `version?` for OCC, unless resource is immutable
- Not every entity needs full CRUD — immutable resources may only have create + read
- Consider whether list endpoints need filtering/sorting parameters

**Endpoint pattern variety:**

| Pattern | Example | When to use |
|---------|---------|-------------|
| Standard CRUD | POST/GET/PUT/DELETE /resources | Basic entity management |
| Action endpoint | POST /resources/{id}/activate | State transition triggers |
| Bulk action | POST /resources/bulk-approve | Multiple resources at once |
| Nested creation | POST /parent/{id}/children | Child within parent context |
| Cross-reference | POST /resources/{id}/link/{otherId} | Association between peers |
| Computed read | GET /resources/{id}/summary | Returns derived/aggregated data |
| Conditional action | POST /resources/{id}/escalate | Only valid under certain conditions |

### 1.6 Error Code Catalog

```yaml
errors:
  - id: ERR_DESCRIPTIVE_NAME
    http: 400 | 401 | 402 | 403 | 404 | 409 | 422
    condition: "concise description of trigger condition"
```

**Design principles:**
- Every error must be triggerable by at least one endpoint
- Use domain-specific names (e.g., `ERR_PREREQUISITE_NOT_MET` not `ERR_INVALID_STATE`)
- Group logically: auth errors, not-found errors, state errors, business errors
- Include boundary-condition errors (e.g., `ERR_BUDGET_EXCEEDED` vs `ERR_BUDGET_WOULD_EXCEED`)

### 1.7 RBAC Matrix

```yaml
roles:
  - name: RoleName
    description: "role purpose"
    identity: "entity_backed:<EntityName>" | "opaque"
    exclusive_operations: [operations only this role can perform]
    shared_operations: [operations shared with other roles]
```

**The `identity:` field is mandatory and takes exactly one of two forms:**

- `entity_backed:<EntityName>` — when `X-User-Role` is this role, `X-User-ID`
  equals the `id` of an instance of `<EntityName>`. Use this for every role
  that corresponds to a persisted entity the user acts as (e.g.,
  `Customer` → `entity_backed:Customer`, `Restaurant` → `entity_backed:Restaurant`,
  `Rider` → `entity_backed:Rider`). Ownership checks of the form "the acting
  X must be the owner of this resource" are then unambiguous: the server
  compares `X-User-ID` to the resource's foreign-key field for `<EntityName>`.
- `opaque` — `X-User-ID` is an operator identifier not tied to any persisted
  entity. Use this for purely operational roles like `PlatformAdmin` and
  `CustomerService`. Scaffold may still reference the opaque id (e.g., store
  it on a WorkOrder as `assigned_cs_user_id`) but must never require it to
  equal any entity's `id`.

Why this field is mandatory: without it, the PRD, the test fixtures, and
the implementation each invent their own mapping between `X-User-ID` and
entity ids. Downstream generators (doc, unit-test, implementation) read
this field to produce consistent role-to-resource identity semantics. A
scaffold that demands "Restaurant must own the order" but leaves identity
unstated forces the three downstream skills to guess — and they guess
differently, producing unfair tests or mismatched implementations.

**Role model patterns:**

| Model | Structure | Characteristics | Example |
|-------|-----------|----------------|---------|
| Approval chain | Requester → Reviewer → Approver | Sequential, no role can do previous role's work | Expense reports |
| Peer roles | Role A owns type X, Role B owns type Y | Non-overlapping resource ownership | Nurse vs physician |
| Hierarchical override | User < Manager < Admin | Each level can do everything below + more | IT helpdesk |
| Delegated authority | Roles can grant temporary permissions | Dynamic, time-bound | On-call rotation |
| Segregation of duties | Same person cannot do step A and step B | Compliance-driven | Financial controls |

### 1.8 Scaffold Difficulty Design (Test Targeting Index)

A machine-readable index of every difficulty feature the scaffold claims to exhibit, cross-referenced from §1.1–§1.7 against the **seven Difficulty Rules defined in §0.5**. Its sole purpose is to drive the downstream unit-test-generator toward complete coverage. Every `rule_id` below corresponds verbatim to a `rule_id` declared in §0.5; consult §0.5 for each rule's full text, differentiation requirements, and counter-examples that do NOT count.

**Critical semantics:**
- **Not an independent rule source.** Every instance MUST ground in elements already declared in §1.1–§1.7. Deleting this section must leave the scaffold's declared behavior identical — it only makes test coverage harder to audit.
- **The doc-generator IGNORES this section.** The PRD must not reference, summarize, or highlight it. Because every instance grounds in other tables (which the PRD losslessly conveys), the rules are already in the PRD through their original tables.
- **The unit-test-generator MUST cover every instance** with at least one test whose `test_recipe` is realized in test code. Uncovered instances are a Stage 2 failure.

**Schema:**

```yaml
scaffold_difficulty_design:
  - rule_id: dual_variant_calc                # each rule_id entry MUST carry the number of instances
    instances:                                 # the quota table below demands — NOT a single instance
      - name: <instance_1_lower_snake_case>    # instance 1 of ≥2 required for dual_variant_calc
        grounds:                               # one or more refs into §1.1–§1.6; every ref MUST resolve
          - calculations.<name>                # or: state_machines.<Entity>.<FROM>_to_<TO>
          - validations[priority=<N>]          # or: entities.<Entity>.fields.<name>
          - concurrency_rules[<scenario-keyword>]
        distinguishing_aspect: |
          <ONE sentence pinning what structurally distinguishes this instance — the specific variant
          delta, the specific cycle edge, the specific cascade chain tail, the specific boundary value.
          Must be falsifiable: a test must be able to turn this sentence into one concrete assertion.>
        test_recipe:
          setup:                               # minimal DB + clock state to reach the scenario from empty DB
            - "<precondition 1>"
          trigger:                             # API call(s) or clock advance(s) that exercise the feature
            - "<endpoint invocation 1>"
          assert:                              # each line = one pinned observable outcome. Any `assert:` line referencing a numeric value derived from a formula MUST be a literal the scaffold author actually computed by code.
            - "<comparison or invariant 1>"
      - name: <instance_2_lower_snake_case>    # instance 2 — MUST cover a different entity domain per Rule 1
        grounds: [<refs>]
        distinguishing_aspect: "<…>"
        test_recipe: { setup: [...], trigger: [...], assert: [...] }
  - rule_id: combinatorial_formula             # repeat for each of the 7 rule_ids; total ≥13 instances
    instances: [ <≥1 instance per §0.5 Rule 2 quota> ]
  # … five more rule_id blocks, each meeting its own minimum from the quota table …
```

**Minimum instance quotas (mirror of §0.5; differentiation requirements are authoritative there, not here). Count is per INSTANCE (the `- name:` entries nested under `instances:`), NOT per `rule_id`. A scaffold with 7 rule_ids each carrying 1 instance = 7 instances = FAIL.**

| rule_id | Minimum | §0.5 ref | Differentiation summary |
|---------|---------|----------|-------------------------|
| `dual_variant_calc` | 2 | Rule 1 | Different entity domains |
| `combinatorial_formula` | 1 | Rule 2 | — |
| `non_linear_state_machine` | 2 | Rule 3 | Different entities |
| `transitive_cascade` | 2 | Rule 4 | Different triggers; one depth ≥ 3, the other ≥ 2 |
| `priority_pair_validation_conflict` | 2 | Rule 5 | Different error-category pairs |
| `boundary_precision_check` | 2 | Rule 6 | Different metrics AND different endpoints |
| `cross_entity_state_dependency` | 2 | Rule 7 | Different ordered entity pairs |
| **total** | **≥ 13 instances** | | |

**Per-instance contract:**
1. Every `grounds:` entry MUST resolve to a declared element in §1.1–§1.6. A grounds entry naming a missing calculation, transition, validation, field, or race is a dangling claim — remove it or add the grounding.
2. `test_recipe.setup + trigger + assert` together MUST reproduce the scenario from empty-DB state using only endpoints declared in §1.5. No wall-clock waits; time-gated setups use the clock-advance endpoint §1.5 already provides.
3. `distinguishing_aspect` MUST be falsifiable — one sentence the test can turn into a concrete assertion. No hedging ("may differ", "could vary").
4. `name` MUST be unique across the whole `scaffold_difficulty_design` and stable across regenerations (tests cite it in their docstrings for audit).
5. `assert:` entries MUST cite exact field names and literal values where possible (e.g., `Order.delivery_fee != Assignment.final_delivery_fee`; `Customer.wallet_balance unchanged after assignment creation`), not paraphrases.
6. **Any `assert:` line referencing a numeric value derived from a formula MUST be a literal the scaffold author actually computed by code.** Pin the inputs in `setup:`, execute the relevant `calculations[].formula` as code (a short Python snippet against the formula and its `constants:`), and write the resulting literal into the assertion — e.g., `Order.delivery_fee == 5.40`, NOT `Order.delivery_fee == round(3.00 + ceil(2.0)*1.20 + 0, 2)` and NOT a rough estimate. Unresolved formulas, estimates, and "let the test-generator compute it" all propagate arithmetic errors into broken tests whose wrong expected value silently agrees with a wrong implementation. When in doubt, execute the formula.

---

## Quality Checklist

Before finalizing the YAML:

**Completeness:**
- [ ] Every entity field has type, source, and description
- [ ] Every state transition has preconditions and side effects
- [ ] Calculation rules specify input sets (which states are included/excluded)
- [ ] Validation priorities are unambiguous per endpoint
- [ ] Every error code is referenced by at least one validation or transition
- [ ] Endpoint roles match RBAC matrix
- [ ] Every role in the RBAC matrix declares an `identity:` field, either `entity_backed:<EntityName>` pointing to a persisted entity, or `opaque` for purely operational roles
- [ ] All automatic/system-triggered transitions are captured
- [ ] Side effect chains are complete (if A→B→C, all three steps are documented)
- [ ] Every non-idempotent operation that can race has a `concurrency_rules` entry with required `error_id` and `http_status`
- [ ] Every error code referenced in `concurrency_rules` also appears in §1.6 Error Catalog
- [ ] `scaffold_difficulty_design` (§1.8) is present, has exactly 7 `rule_id` groups, and carries **≥ 13 instances in total** counted as `- name:` entries nested under `instances:` (per-rule floor 2/1/2/2/2/2/2) — NOT 7 instances at top level
- [ ] Every `scaffold_difficulty_design[*].instances[*].grounds[*]` reference resolves to a declared element in §1.1–§1.6

**Self-Consistency:**

Each declaration in the scaffold is an edge; self-consistency means both ends resolve inside the scaffold. Completeness asks whether required fields are filled — these checks ask whether what is filled coheres.

- [ ] **Enum value closure** — Every enum value declared in an entity field's `constraints:` MUST be produced by at least one state-machine transition, calculation output, or system initialization. A declared value that no path writes (e.g., a `WAIVED` settlement status with no waive action) is a dead end; remove it or add the producing transition.
- [ ] **Trigger ↔ side-effect bidirectional match** — Every `calculations[].trigger:` that names a state transition MUST have that transition's `side_effects:` list the calculation's output field. Conversely, every side-effect that says "recompute X" MUST map to a declared calculation. A calc claiming "on Order acceptance" while the ACCEPT transition's side_effects only refresh `updated_at` is unresolved.
- [ ] **Aggregate selection precision** — Every aggregation (`sum of`, `count of`, `max over`, `latest N`) MUST pin three elements: (a) source entity with explicit status filter, (b) time or index window with inclusive/exclusive boundary, (c) tie-break rule when the result is order-sensitive. "Sum of Fine.amount for subject whose settlement_status flipped PENDING→SETTLED" omits which PENDING fines enter the sweep and is insufficient.
- [ ] **No fuzzy adjectives in constraint scopes** — Uniqueness constraints, filter clauses, and precondition prose MUST NOT use adjectives like "active", "valid", "live", "open", "current" as a stand-in for a status filter. Write the enum set explicitly: `status IN {ACTIVE, SUSPENDED}`, not "active restaurants".
- [ ] **Cross-entity reference resolvability** — Any precondition or side-effect that references another entity as "a linked X", "a related X", "the associated X", or "the corresponding X" MUST name the foreign-key path or pin the query selector. "A linked WorkOrder is in UNDER_REVIEW" without declaring `WorkOrder.related_order_id == Order.id` forces downstream generators to invent the link.
- [ ] **Computation determinism** — Order-sensitive calculations MUST pin both sort key and tie-break. Multi-step rounding MUST pin the rounding order. Fields referenced inside `formula:` MUST be unambiguous — use the exact field name (`credit_balance_cents`), not paraphrases ("the customer's credit") that could resolve to either a provisional or a finalized field.

**Difficulty (audit — the spec lives at §0.5):**
- [ ] Every rule in §0.5 (Rules 1–7) is satisfied by the scaffold's §1.1–§1.7 tables, honoring the differentiation clauses ("different entity domains", "different error-category pairs", "different ordered entity pairs", etc.)
- [ ] `scaffold_difficulty_design` (§1.8) mirrors every §0.5 rule with at least its minimum instance count (2/1/2/2/2/2/2; ≥13 total)
- [ ] Every §1.8 `instances[*].distinguishing_aspect` sentence traces to the differentiation clause of its `rule_id` in §0.5 — i.e., it is not generic prose but a concrete statement of what §0.5 demands be distinct about this instance

**Diversity (compare against the 22 existing example scaffolds in this directory):**

Diversity is a tie-breaker, not an override. §0.3's "let the scenario dictate" is the dominant rule — when a scenario naturally demands a hierarchical topology or a linear state machine, honour the scenario. Apply the preferences below only when the scenario leaves the choice open.

Current gaps, for use when the scenario is underdetermined:
- Archetypes with 0 examples: multi-party negotiation, temporal windowing, workflow orchestration, compliance/audit
- Entity topologies with 0 examples: pure flat, pure graph (all 22 are hybrid)
- State machine shapes with 0 examples: branching (fork/join), cyclic (A→B→A)
- Role models with 0 examples: segregation of duties

Preferences (apply only where the scenario leaves room):
- [ ] Primary archetype chosen from an underrepresented row of §0.1 when the scenario supports it
- [ ] Entity topology, state machine shape, or role model diverges from the hybrid / linear / approval-chain majority where plausible
- [ ] Core calculation challenge is structurally distinct from prior scaffolds (not another threshold + aggregation) when the scenario allows
