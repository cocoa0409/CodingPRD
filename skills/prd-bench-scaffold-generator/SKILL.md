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

entities:        # Table 1: Entity-Relationship Table
state_machines:  # Table 2: State Machine Table
calculations:    # Table 3: Calculation Rules Table
validations:     # Table 4: Validation Rules Table (ordered by priority)
endpoints:       # Table 5: API Endpoint Table
errors:          # Table 6: Error Code Catalog
roles:           # Table 7: RBAC Matrix
```

For completed examples, see the `examples/` directory (22 scaffolds covering diverse domains)
For a blank template, see [examples/seed-tables-template.yaml](examples/seed-tables-template.yaml).

## Generation Checklist

```
- [ ] 0: Select complexity profile (§Step 0)
- [ ] 1.0: Response Envelope — emit the FIXED block verbatim (§1.0)
- [ ] 1.1: Entity-Relationship Table
- [ ] 1.2: State Machine Table
- [ ] 1.2.1: Concurrency Rules
- [ ] 1.3: Calculation Rules Table
- [ ] 1.4: Validation Rules Table (ordered)
- [ ] 1.5: API Endpoint Table
- [ ] 1.6: Error Code Catalog
- [ ] 1.7: RBAC Matrix
- [ ] Final: Quality + Diversity check (§Quality Checklist)
```

---

## Step 0: Complexity Profile Selection

Before generating tables, select the structural DNA of the benchmark. This is the most important step — it determines the fundamental character of the challenge and prevents convergence toward a single template.

### 0.1 Primary Archetypes

Each archetype represents a fundamentally different core challenge. Choose ONE primary archetype, optionally blend with a secondary. The coverage column shows how many of the 22 reference scaffolds use each archetype — prioritize underrepresented ones for diversity.

| Archetype | Core challenge | What makes it hard | Example domains | Coverage |
|-----------|---------------|-------------------|-----------------|----------|
| **Ledger reconciliation** | Same data, two algorithms, different results | Forward-looking vs chronological produce divergent costs for identical inputs | Hospital billing, insurance claims, tax withholding | 9/22 (41%) — OVERREPRESENTED |
| **Quota / allocation** | Finite pool competed for, reserved, committed, released | Fragmentation, over-subscription policies, priority preemption, waterfall fallback | Cloud resource quotas, inventory reservation, seat assignment | 5/22 (23%) |
| **Graph constraint** | Entities form a DAG with dependency/ordering rules | Cycle detection, transitive closure, conditional propagation | Course prerequisites, build pipelines, supply chain BOM | 4/22 (18%) |
| **Posture-driven gating** | Derived aggregate state gates all child operations | Posture computed from children, cascading freezes, ops-run checkpoints | Dock operations, podcast scheduling, sponsorship events | 7/22 (32%) — NEW, observed in real data |
| **Pricing engine** | Dynamic pricing based on multi-dimensional rules | Tiered rates, volume discounts, time-of-use, promotional stacking, rounding traps | Utility billing, SaaS metering, airline yield management | 1/22 (5%) — UNDERREPRESENTED |
| **Event sourcing** | State derived by replaying an ordered event stream | Snapshot invalidation, late-arriving events, retroactive corrections | Order lifecycle + refunds, audit reconstruction, version history | 1/22 (5%) — UNDERREPRESENTED |
| **Access control matrix** | Fine-grained, context-dependent permissions | Attribute-based rules, delegation chains, temporary grants, scope inheritance | Document sharing, healthcare data access, multi-tenant SaaS | 1/22 (5%) — UNDERREPRESENTED |
| **Multi-party negotiation** | Multiple independent actors must reach agreement | Quorum logic, timeout/escalation, conditional delegation, veto power | Contract approval, loan origination, committee voting, peer review | 0/22 — ABSENT |
| **Temporal windowing** | Overlapping/adjacent time intervals with gap rules | Half-open vs closed intervals, merge/split semantics, cross-resource scheduling | Room booking, spectrum allocation, maintenance windows | 0/22 — ABSENT |
| **Workflow orchestration** | Configurable multi-step pipelines with branching | Conditional routing, parallel fan-out/fan-in, compensation on failure, idempotency | CI/CD pipelines, document processing, onboarding flows | 0/22 — ABSENT |
| **Compliance / audit** | Actions constrained by regulatory rules with audit trail | Mandatory cooling-off periods, segregation of duties, tamper-evident logs | Financial trading, pharmaceutical dispensing, government procurement | 0/22 — ABSENT |

**Diversity guidance**: When generating a new scaffold, check the coverage column. If the scenario could fit multiple archetypes, prefer the underrepresented one. The 4 absent archetypes (multi-party negotiation, temporal windowing, workflow orchestration, compliance/audit) are high-priority targets for new scenarios.

### 0.2 Cross-Cutting Complexity Layers

These are independent difficulty dimensions that can be **layered onto any archetype**. Select 2–4 that fit the scenario:

| Layer | What it adds | Difficulty mechanism | Observed in |
|-------|-------------|---------------------|-------------|
| **Optimistic concurrency** | Version-based conflict detection | Stale-data races, retry semantics. OCC alone only covers version-field conflicts on PATCH/PUT. If the scenario also has race-condition constraints (e.g., "at most one delivery per order"), define them explicitly in `concurrency_rules` (see §1.2.1). | 18/22 scaffolds |
| **Cascading side effects** | One mutation triggers chain of dependent updates | N-level propagation, ordering sensitivity, partial failure | 20/22 scaffolds |
| **Dual-variant calculation** | Same inputs, two valid algorithms, different outputs | Provisional vs final, optimistic vs pessimistic, estimate vs actual | 9/22 scaffolds |
| **Rate / threshold triggers** | Behavior changes at configurable breakpoints | Boundary precision (>= vs >), cumulative vs instantaneous, threshold reset | 10/22 scaffolds |
| **Derived field reconciliation** | Denormalized fields must stay consistent with source data | When to recompute, stale cache detection, consistency on partial update | 15/22 scaffolds |
| **Ops-run checkpoint** | Periodic batch operation advances system epoch | Stale expiry, waitlist promotion, posture recalculation per epoch | 7/22 scaffolds — NEW |
| **Contagion / risk propagation** | Side effects cascade with multiplicative risk scoring | Penalty accumulation, threshold breach with override, score floor/ceiling | 6/22 scaffolds — NEW |
| **Version-pinning on approval** | Lock reference object versions when approved | Stale reference detection, re-validation on state change | 3/22 scaffolds — NEW |
| **Scheduled / deferred actions** | Actions take effect at a future time | Clock dependency, cancellation before execution, what-if projections | 4/22 scaffolds |
| **Soft delete / archival** | Resources are deactivated but still queryable | Filter semantics (include archived?), referential integrity with archived parents | 3/22 scaffolds |
| **Idempotency** | Repeated identical requests produce same result | Idempotency keys, at-least-once delivery, duplicate detection | 5/22 scaffolds |
| **Pagination with filtering** | List endpoints support complex query parameters | Filter + sort + paginate interaction, cursor vs offset, consistency under mutation | 22/22 scaffolds |
| **Bulk operations** | Single request affects multiple resources | Partial success/failure, transactional vs best-effort, rollback semantics | 2/22 scaffolds |
| **Multi-tenancy isolation** | Resources partitioned by tenant/scope | Cross-tenant leakage prevention, tenant-scoped uniqueness, shared vs private resources | 3/22 scaffolds |
| **Conditional feature flags** | Behavior varies based on entity-level configuration | Combinatorial explosion of code paths, defaults vs overrides, migration from old behavior | 1/22 scaffolds |

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

Benchmarks exist to stress-test LLM coding ability. Target one of these two difficulty levels:

| Level | Entity count | Endpoint count | Error codes | Calculation variants | State machines | Typical token budget |
|-------|-------------|---------------|-------------|---------------------|---------------|---------------------|
| **Advanced** | 10–16 | 18–40 | 15–40 | 2–3 | 3–5 with reverts + auto-transitions | ~50k |
| **Expert** | 14–30 | 35–65 | 30–60 | 3+ | 4+ with cycles or parallel dimensions | ~80k |

**Default to Advanced.** Only go Expert when the scenario naturally demands it (many entity types, complex cross-entity workflows). An overly simple scaffold fails to discriminate between implementations — never generate fewer than 10 entities or 18 endpoints.

These are guidelines, not hard rules. A 10-entity benchmark with one fiendishly tricky calculation can be harder than a 20-entity CRUD app.

**What actually makes a benchmark hard (in order of impact):**
1. Calculations where two valid interpretations of the same prose produce different numbers
2. Side effect chains that span 3+ entities and depend on execution order
3. Validation priority conflicts where the "correct" error depends on check ordering
4. State transitions where the set of valid next-states depends on sibling/child state
5. Edge cases at exact boundaries (>=  vs >, empty sets, zero quantities)

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
- Entity count follows scenario complexity — don't inflate or compress
- At least one entity with computed fields that derive from cross-entity data
- Field names must be explicit — downstream PRD will reference them in prose
- `common_fields: false` for immutable/append-only resources (event logs, pairings)
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

Each rule must provide a rigorous, testable guarantee:

```yaml
concurrency_rules:
  - scenario: "Two riders assigned to the same order simultaneously"
    guarantee: "At most one delivery per order; second assignment rejected"
    error_id: ERR_DELIVERY_ALREADY_ASSIGNED
    http_status: 409

  - scenario: "Restaurant confirms order while customer cancels simultaneously"
    guarantee: "Exactly one operation succeeds; loser receives ERR_INVALID_STATE"
    serialization: "First-writer-wins on order status"
```

All error codes referenced here must also appear in the Error Catalog (Table 6).

**Consistency with Tables 2 and 4:** When a concurrency scenario involves an operation whose preconditions (Table 2) or validations (Table 4) define multiple possible error codes, Table 2.1 must list **all** error codes the loser could receive — not just one. For example, if operation X can fail with both `ERR_INVALID_STATE` (wrong status) and `ERR_HAS_DEPENDENCIES` (business precondition), and a race could trigger either depending on execution order, the concurrency rule must document both.

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

**Difficulty:**
- [ ] At least one calculation where two valid approaches produce different results
- [ ] At least one side effect chain spanning 3+ entities
- [ ] At least one validation priority conflict testable by dual-failure scenario
- [ ] At least one boundary condition requiring exact precision (>= vs >, zero quantity, empty set)
- [ ] At least one cross-entity state dependency (entity A's valid transitions depend on entity B's state)

**Diversity (compare against the 22 existing example scaffolds in this directory):**

Current gaps to prioritize when creating new scaffolds:
- Archetypes with 0 examples: multi-party negotiation, temporal windowing, workflow orchestration, compliance/audit
- Entity topologies with 0 examples: pure flat, pure graph (all 22 are hybrid)
- State machine shapes with 0 examples: branching (fork/join), cyclic (A→B→A)
- Role models with 0 examples: segregation of duties

Checklist:
- [ ] Primary archetype is underrepresented (check §0.1 coverage column)
- [ ] Entity topology is NOT hybrid (prioritize flat or graph)
- [ ] State machine shape differs from linear (prioritize branching, cyclic, or parallel)
- [ ] At least TWO of the three dimensions above differ from the majority
- [ ] Core calculation challenge is structurally different (not another threshold + aggregation)
- [ ] Role model adds diversity (prioritize segregation_of_duties or delegated_authority)
