---
name: prd-bench-scaffold-generator
description: Generate structured seed tables (entity model, state machines, calculations, validations, API endpoints, error catalog, RBAC) from a scenario description. These seed tables serve as the single source of truth for downstream PRD generation, test suite generation, and reference implementation.
---

# PRD Benchmark Scaffold Generator

## Input / Output

### Input

User provides two things:

1. **Scenario description**: A natural-language description of the system to build, including roles and core workflows.

2. **Output directory path**: Where to save the generated YAML files (the skill writes two sibling files into this directory).

### Output

Three YAML files written into the user-specified directory, in this order:

**1. `SCAFFOLD.yaml`** — §1.0 through §1.7 plus preamble keys:

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
```

**2. `SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — single top-level key `scaffold_difficulty_design:` (§1.8: Test Targeting Index — sampled cross-reference of §1.1–§1.7 per Difficulty rule; 2 instances per rule).

**3. `SCAFFOLD_CORNER_DESIGN.yaml`** — single top-level key `scaffold_corner_design:` (§1.9: enumerative coverage of every other testable claim the scaffold's §1.1–§1.7 surface declares, beyond §0.5's nine Difficulty Rules).

Do NOT emit `scaffold_difficulty_design:` or `scaffold_corner_design:` as top-level keys inside `SCAFFOLD.yaml` — they live only in their respective files.

For completed examples, see the `examples/` directory. These examples are format and structure references only; they are NOT normative and may lag behind the current rules in this skill. If an example conflicts with any instruction, hard constraint, or checklist item in this file, the skill text wins and the generated scaffold MUST satisfy the current skill exactly. For a blank template, see [examples/seed-tables-template.yaml](examples/seed-tables-template.yaml).

## Generation Checklist

```
- [ ] 0: Select complexity profile (§0.1–§0.4)
- [ ] 0.5: Internalize the nine Difficulty Rules (§0.5) — keep them in mind while drafting §1.1–§1.7, not as a post-hoc audit
- [ ] 1.0: Response Envelope — emit the FIXED block verbatim (§1.0)
- [ ] 1.1: Entity-Relationship Table
- [ ] 1.2: State Machine Table
- [ ] 1.2.1: Concurrency Rules
- [ ] 1.3: Calculation Rules Table
- [ ] 1.4: Validation Rules Table (ordered)
- [ ] 1.5: API Endpoint Table
- [ ] 1.6: Error Code Catalog
- [ ] 1.7: RBAC Matrix
- [ ] 1.8: Scaffold Difficulty Design (Test Targeting Index) → destination file `SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- [ ] 1.9: Scaffold Corner Design (Coverage Index for Non-Difficulty Tests) → destination file `SCAFFOLD_CORNER_DESIGN.yaml`
- [ ] Setup-chain rule replay across BOTH §1.8 and §1.9 — for every `test_recipe.setup_api_calls` AND `test_recipe.trigger:` chain in BOTH design files, replay each call against the scaffold's own §1.2 / §1.4 / §1.6 (call-by-call: every call's preconditions hold given prior-call cumulative state) AND replay the chain's side-effects forward (end-state: every adjective/cardinality in `setup:` is a consequence of the chain, not a wish). Both design files are test prototypes the unit-test-generator transcribes verbatim — an inconsistency here lands as a broken fixture. See §Quality Checklist → "Test-recipe ↔ endpoint compatibility" for the two replay items.
- [ ] Run `python3 <skill-dir>/scaffold_lint.py <task-dir>`; paste the verdict block verbatim; fix and re-run until clean.
- [ ] Final: Quality + Diversity check (§Quality Checklist) across all three files
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
| **Optimistic concurrency** | Version-based conflict detection on a parent entity's `version` field | Stale-data conflicts on UPDATE and on CREATE-with-supersede patterns. **OCC on the parent's `version` is the only sanctioned mechanism this benchmark uses to resolve write-write conflicts** — see §1.2.1. Other write-write conflicts are NOT concurrency rules; they reduce to state preconditions and belong in §1.2 or §1.4. |
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
| **Selector policy** | Server picks one entity from a candidate pool | Eligibility filter, ranking expression, tie-break when ranks tie, empty-pool fallback, exclusion semantics on retry |

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

Nine hard rules that shape the scaffold's contents. They apply **while you are drafting §1.1–§1.7** (not as an afterthought), are cross-referenced by §1.8 Scaffold Difficulty Design (Test Targeting Index), and are audited at the end by the Quality Checklist. Each rule has a stable `rule_id` that §1.8 uses verbatim.

**Rule 1 — Dual-variant calculations across different entity domains**  (`rule_id: dual_variant_calc`, ≥ 2 instances)
At least two `calculations[]` entries where two valid approaches produce different results. The two calculations MUST operate on different entity domains (e.g., one is cost accounting on an Order, the other is risk scoring on a Customer), so the scaffold exhibits dual-variant logic on more than one subject. A second calculation that repeats the same provisional-vs-final shape on the same entity or metric does NOT count.

**Rule 2 — Combinatorial formulas across different modes**  (`rule_id: combinatorial_formula`, ≥ 2 instances)
At least two calculations with combinatorial complexity, each falling into one of these three modes:
(a) a formula with ≥3 inputs and non-linear interaction (nested `min`/`max`, conditional branches on entity state, tiered-rate selection);
(b) nested rounding where the order matters — "round per-line-item then sum" vs "sum then round" produce different cents; the scaffold MUST pin one order and state it explicitly;
(c) a circular-looking dependency where evaluation order must be explicit (e.g., `total = subtotal + fee`, but `fee` is computed from a discount keyed on the total tier — the scaffold pins the evaluation order so the value is well-defined).
The two instances MUST fall in **different modes** from {(a), (b), (c)}, so the scaffold exercises combinatorial complexity along more than one axis. Two instances that both satisfy only (a) (e.g., two tiered-rate formulas on different metrics) do NOT count. A single-formula `aggregation` + `threshold` calculation does NOT satisfy this.

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

**Rule 8 — Resource temporal-overlap conflicts across different interval semantics**  (`rule_id: resource_temporal_overlap`, ≥ 2 instances)
At least two overlap-detection rules where an interval occupation on a resource is rejected because it collides with another. The two rules MUST differ in **interval semantics** — the geometric treatment of adjacency, buffers, or aggregate capacity — and sit on different resource entities. Two overlap rules with identical interval arithmetic do NOT count.

**Rule 9 — Compensating-action invariants across different conserved quantities**  (`rule_id: compensating_invariant`, ≥ 2 instances)
At least two invariants where a forward action paired with its compensating action MUST leave a named global quantity unchanged, pinned as an explicit formula over entity fields. The two invariants MUST involve different types of conserved quantities. A cascade that runs end-to-end but leaves drift in the named quantity does NOT satisfy this.

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
- `common_fields: true` expands to four fields on the entity: `id` (**server-minted UUID with no type prefix** — e.g., `"8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"`, NOT `"ord_8a3e1c0b-…"`; identity only, strictly forbidden in selector/ranking/tie-break/fallback decisions), `created_at` (ISO 8601 UTC, three fractional digits; use this instead of `id` when a common-field fallback is required), `updated_at` (same format, refreshed on every mutation including cascaded side effects), `version` (integer, starts at `1`, increments by one on every mutation). When `common_fields: false`, the entity carries only `id` and `created_at` with the same rule: `id` identifies resources but MUST NOT decide observable business results.
- **Foreign keys MUST be declared in the canonical `FK -> {ParentEntity}.id[; <optional annotations>]` form.** Every field whose value is the `id` of another entity carries a `description:` that begins with `FK -> <Entity>.id`. Annotations follow after a semicolon — cardinality notes (`unique per Offer`), denormalization notes (`denormalised from Application`), or any other clarification. Prose alternatives ("references the order", "points to Customer", "the parent application's id") are forbidden — the canonical prefix is what `scaffold_lint.py` greps to build the FK graph for the reverse-reachability check (§1.5). The FK ALWAYS lives on the child (the entity that "belongs to" the other); placing it on the parent is forbidden except as a 1:1 performance-optimization escape hatch (`<child>_id` snapshot, `source: system`) that does NOT replace the FK on the child.
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

This section is intentionally narrow. Most write-write conflicts that *look* like races are actually state preconditions in disguise — a second sequential request observes a field changed by the first and is rejected by the existing state-machine or validation logic. Those do not belong here.

**Mandatory filter — apply BEFORE writing any entry:**

> *"If the second request is sent strictly after the first request fully completes (sequential, not parallel), can the second request be rejected because it observes a state field that the first request changed?"*

- **Yes** → NOT a concurrency rule. The behavior is fully covered by a state precondition. Capture it in `state_machines` (as a transition `preconditions:` clause) or in `validations` (`category: state`). Use a domain-specific error such as `ERR_INVALID_STATE`, `ERR_ALREADY_TERMINAL`, `ERR_LOAN_ALREADY_CONSOLIDATED`. **Do NOT write a `concurrency_rules` entry for it.**

- **No** (the second sequential request sees identical state and would itself legitimately succeed under the natural product semantics) → True race. The canonical case is CREATE-with-supersede — e.g., creating a new RepaymentPlan when the product spec allows the new plan to legitimately supersede the prior one. Only true races may appear in `concurrency_rules`.

**True races MUST be resolved via OCC on the parent entity's `version`.** No other mechanism is permitted — wall-clock windows, server-side locks, "first-writer-wins" tie-breakers, and any framing that depends on requests overlapping in time are all forbidden, because none of them yield a deterministic black-box test. OCC reduces the race to a stale-version check that can be triggered by two strictly sequential requests.

Schema:

```yaml
concurrency_rules:
  - rule_id: <kebab-case-id>              # stable handle; §1.8/§1.9 grounds use this id
    parent_entity: EntityName              # the entity whose `version` OCC checks
    write_endpoint: "POST /path"            # the endpoint the rule guards
    occ_field: "expected_<parent>_version"   # required request-body field name
    description: |
      <One sentence: what the loser tried to do and why the system rejects
      it. State the rule in OCC terms (stale version), NOT in terms of
      simultaneous requests, parallel dispatch, or race winners/losers.>
    error_id: ERR_XXX                        # the loser's error_id
    http_status: 412                         # 412 Precondition Failed for OCC mismatch
```

**Hard constraints — every entry MUST satisfy ALL of:**

1. The `parent_entity` has `common_fields: true` in §1.1 (which supplies the `version` integer field starting at 1, incremented on every mutation).
2. The `write_endpoint` in §1.5 lists `expected_<parent>_version` as a required field in its `input:` AND lists "increments `<parent_entity>.version` by 1" in its `side_effects:`. The endpoint must give the OCC check something to observe, and must advance the version on success so the next stale request fails.

**Forbidden vocabulary anywhere in the scaffold** (not just in this section):

- "simultaneously", "at the same time", "concurrently submitted", "in parallel"
- "first-writer-wins", "race winner", "race loser", "the race in which..."
- "two clients race to...", "two requests arriving together"

If you cannot describe a rule without these words, it has not passed the filter — re-classify into `state_machines` or `validations`.

**Example — REJECTED (state precondition pretending to be a race):**

```yaml
# WRONG — belongs in state_machines preconditions, not concurrency_rules
concurrency_rules:
  - scenario: "Two LoanServicers simultaneously declare DEFAULT on the same Loan"
    error_id: ERR_INVALID_STATE
    serialization: "First-writer-wins on Loan.status"
```

A second sequential `DEFAULT_DECLARATION` observes `loan.status == DEFAULT` (set by the first request) and is rejected by the existing state-machine precondition `loan.status == REPAYMENT`. Fully covered — no entry needed.

**Example — ACCEPTED (true race, OCC-resolved):**

```yaml
concurrency_rules:
  - rule_id: plan-create-stale-loan
    parent_entity: Loan
    write_endpoint: "POST /repayment-plans"
    occ_field: "expected_loan_version"
    description: |
      Creating a RepaymentPlan against a Loan whose version has advanced
      since the client last observed it is rejected. This captures the
      case where another writer has just created a plan (which legitimately
      supersedes the prior under §3.4) and the current writer's view of
      the loan is therefore stale.
    error_id: ERR_STALE_VERSION
    http_status: 412
```

The corresponding test: client reads `loan.version: 5`, creates plan A successfully (`loan.version` advances to 6), then sends a second create still carrying `expected_loan_version: 5` — deterministically rejected with 412. Two strictly sequential requests; zero parallelism.

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

**No random fields in business decisions — use `created_at`, never `id`, as fallback (mandatory):**
Any selector, ranking, tie-break, allocation order, batch-processing order, cascade order, conflict-resolution rule, or chronological replay order that can change an observable API result MUST NOT use random properties as decision inputs. UUID/random `id` values are strictly forbidden in business decisions, even as a precision fallback or final tie-break. When a precise fallback over common fields is needed, use `created_at`, never `id`. Random identifiers may identify resources in paths and foreign keys, but they MUST NEVER decide winners, processing order, rounding remainders, or side-effect order. A scaffold that uses UUID/random `id` for observable decision-making MUST be rejected.

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
| Priority ordering | A single request fails multiple checks — which error_id wins? | Medium |
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
- **Testability-completeness (value-level principle, overrides convenience).** The scaffold owes the test layer a reachable path to every state it declares. Walk every state in your state machines and ask: *"can a test reach this from empty-DB using only the endpoints I've listed?"* This principle is **operationally enforced** at §1.8 generation time via the `setup_api_calls:` cross-check (see §1.8 per-instance contract item 3) and post-hoc by `scaffold_lint.py` (sibling script; see Quality Checklist). If any difficulty-design instance's precondition cannot be reached by an ordered chain of §1.5 endpoint calls, return here and reshape §1.5 per this **priority ladder**, in order:

  1. **Compose existing endpoints first.** Many "missing" capabilities are already reachable via composition of §1.5 calls already declared — the gap was in the search, not the surface. Try this first.
  2. **Add a general business endpoint.** When no chain of existing endpoints reaches the precondition, add an endpoint that fits the domain's real-world admin/operator surface — e.g., `POST /members/{id}/wallet/adjustments` rather than `POST /_seed/wallet`. A business endpoint serves both the test and any real-world admin tool, and keeps the API contract honest about which operations actually exist in production.
  3. **Add a custom test-driving endpoint (last resort).** When no plausible business endpoint exists for the operation (e.g., setting the system clock to any timestamp, firing a synthetic webhook, injecting a no-show strike history), declare one under the `/_<name>` namespace (`POST /_clock/set_current_utc`, `POST /_events/emit`, `POST /_inject/...`). Declare it in §1.5 like any other endpoint — path, method, role, inputs, side effects. The leading underscore marks it as outside the public business surface but inside the official scaffold contract; downstream skills (PRD-, unit-test-, and implementation-generator) treat it as a first-class declared endpoint, not a back-door.

  Silently weakening the §1.8 setup or papering over the gap is forbidden.

- **FK reverse-reachability (parent → children discovery is non-negotiable).** For every FK field declared in §1.1 — i.e., every entity field whose `description:` matches `^FK -> <Parent>\.id\b` — §1.5 MUST contain at least one GET endpoint that lets a client enumerate (or fetch, for 1:1) the child entities given the parent's `id`. The FK lives on the child by §1.1 convention; reaching the child from the parent therefore requires an explicit endpoint. Two forms are accepted:

  1. **Sub-resource GET** — `GET /<parent-collection>/{id}/<child-segment>` returning `output: <Child>[]` (1:N) or `output: <Child>` (1:1). Example: `GET /offers/{id}/background-check` (1:1, returns the synthesized BackgroundCheck or 404); `GET /applications/{id}/feedback` (1:N, returns the InterviewFeedback array).
  2. **Filtered list GET** — `GET /<child-collection>` whose `input:` declares the FK field as an optional query parameter using the `<fk_field>?` syntax already used for pagination. Example: `GET /background-checks` with `input: ["limit?", "offset?", "offer_id?"]`, returning `output: BackgroundCheck[]`. A child with multiple FKs (e.g., `Hire` with `application_id`, `requisition_id`, `candidate_id`, `department_id`) economically collapses to a single filtered list with every FK as an optional query param.

  An endpoint whose `output:` returns the child at the moment of its creation (e.g., `POST /hires` returning Hire) does NOT exempt the FK from this rule — reachability is a lifecycle property, not a creation-time property. After the creation response is gone, the parent must still be able to find its child by id. Likewise, an endpoint that cascades a child as a side effect (e.g., `POST /offers/{id}/accept` synthesizing a BackgroundCheck while returning the Offer) MUST be paired with a reverse-reachability endpoint for the cascaded child — otherwise the new resource is unreachable through any PRD-derivable channel, and downstream skills (PRD-, unit-test-, implementation-generator) will be forced into scaffold-aware interpretations to invent a discovery path. 1:1 relationships MAY additionally snapshot `<child>_id` onto the parent as a `source: system` performance escape hatch, but this never replaces the required GET endpoint. Violations are caught by `scaffold_lint.py` check (f) and reported as `FK_REVERSE_UNREACHABLE`.

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
| FK reverse lookup (sub-resource) | GET /parents/{id}/children | Discover children from parent.id (1:N) or 1:1 fetch |
| FK reverse lookup (filtered list) | GET /children?<parent>_id={id} | Discover children from parent.id; multi-FK economical form |

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

- `entity_backed:<EntityName>` — when `X-User-Role` is this role, `X-User-ID` equals the `id` of an instance of `<EntityName>`. Use this for every role that corresponds to a persisted entity the user acts as (e.g., `Customer` → `entity_backed:Customer`, `Restaurant` → `entity_backed:Restaurant`, `Rider` → `entity_backed:Rider`). Ownership checks of the form "the acting X must be the owner of this resource" are then unambiguous: the server compares `X-User-ID` to the resource's foreign-key field for `<EntityName>`.
- `opaque` — `X-User-ID` is an operator identifier not tied to any persisted entity. Use this for purely operational roles like `PlatformAdmin` and `CustomerService`. Scaffold may still reference the opaque id (e.g., store it on a WorkOrder as `assigned_cs_user_id`) but must never require it to equal any entity's `id`.

Why this field is mandatory: without it, the PRD, the test fixtures, and the implementation each invent their own mapping between `X-User-ID` and entity ids. Downstream generators (doc, unit-test, implementation) read this field to produce consistent role-to-resource identity semantics. A scaffold that demands "Restaurant must own the order" but leaves identity unstated forces the three downstream skills to guess — and they guess differently, producing unfair tests or mismatched implementations.

**Role model patterns:**

| Model | Structure | Characteristics | Example |
|-------|-----------|----------------|---------|
| Approval chain | Requester → Reviewer → Approver | Sequential, no role can do previous role's work | Expense reports |
| Peer roles | Role A owns type X, Role B owns type Y | Non-overlapping resource ownership | Nurse vs physician |
| Hierarchical override | User < Manager < Admin | Each level can do everything below + more | IT helpdesk |
| Delegated authority | Roles can grant temporary permissions | Dynamic, time-bound | On-call rotation |
| Segregation of duties | Same person cannot do step A and step B | Compliance-driven | Financial controls |

### 1.8 Scaffold Difficulty Design (Test Targeting Index)

**Output location**: a separate file `SCAFFOLD_DIFFICULTY_DESIGN.yaml` sibling to `SCAFFOLD.yaml`, with `scaffold_difficulty_design:` as its single top-level key. Do NOT emit it inside `SCAFFOLD.yaml`.

**Purpose**: a machine-readable index of every difficulty feature the scaffold claims to exhibit, cross-referenced from §1.1–§1.7 against the nine Difficulty Rules defined in §0.5. Its sole job is to drive the downstream unit-test-generator toward complete coverage. Every `rule_id` below corresponds verbatim to a `rule_id` in §0.5; **§0.5 is authoritative** for each rule's full text, minimum instance count, differentiation clause, and counter-examples. This section does not restate those.

**Critical semantics:**
- **Not an independent rule source.** Every instance MUST ground in elements already declared in §1.1–§1.7. Deleting this file must leave the scaffold's declared behavior identical — it only makes test coverage harder to audit.
- **Every instance MUST be covered** by at least one unit test whose `test_recipe` is realized in code. Uncovered instances are a Stage 2 failure for the unit-test-generator.

**Schema:**

```yaml
scaffold_difficulty_design:
  - rule_id: dual_variant_calc
    instances:
      - name: <instance_1_lower_snake_case>
        grounds:                               # refs into §1.1–§1.6; every ref MUST resolve
          - calculations.<name>                # or: state_machines.<Entity>.<FROM>_to_<TO>
          - validations[priority=<N>]          # or: entities.<Entity>.fields.<name>
          - concurrency_rules[<rule_id>]                # the kebab-case id from §1.2.1
        distinguishing_aspect: |
          <ONE falsifiable sentence pinning what structurally distinguishes this instance,
          naming the specific distinction §0.5 requires of this rule_id.>
        test_recipe:
          setup:                               # natural-language description of the precondition state (entities, statuses, balances, clock position)
            - "<precondition 1>"
          setup_api_calls:                     # ordered chain of §1.5 endpoint calls that drives empty-DB → setup state above; each list entry is a STRUCTURED call object (not a prose string), so every placeholder traces back to a concrete `captures:` produced by an earlier call
            - call: "POST /<path>"             # method + path; path-templated ids reference earlier captures via ${var}
              payload: { field: <literal_or_${var}>, ... }   # field values are LITERALS the author pins UNLESS the value can only come from a prior call's response, in which case ${var} references a captures binding from an earlier line
              as: <RoleName>                   # X-User-Role header, exactly as declared in §1.7
              as_user_id: <literal_or_${var}>  # X-User-ID header; OMIT for opaque roles when the test does not pin an audit id; REQUIRED for entity_backed roles where ownership matters (e.g., Member acting on own resource → as_user_id: ${m_ca_id})
              captures: { <var_name>: <jsonpath> }  # bindings extracted from this call's response envelope (e.g., `m_ca_id: $.data.id`, `tok_ca: $.data.verification_token`); name MUST be unique within this instance; OMIT the whole key when nothing later needs the response
            - call: "POST /<path>"
              payload: { ... }
              as: <RoleName>
          trigger:                             # the API call(s) under test — same structured form as setup_api_calls; captures permitted when later trigger steps or asserts reference the response
            - call: "POST /<path>"
              payload: { ... }
              as: <RoleName>
              as_user_id: <literal_or_${var}>
              captures: { <var_name>: <jsonpath> }
          assert:                              # one pinned observable outcome per line; field references may use ${var} bound earlier
            - "<comparison or invariant 1>"
      - name: <instance_2_lower_snake_case>
        grounds: [<refs>]
        distinguishing_aspect: "<…>"
        test_recipe: { setup: [...], setup_api_calls: [...], trigger: [...], assert: [...] }
  - rule_id: combinatorial_formula
    instances: [ <one or more, per §0.5 minimum> ]
  # … seven more rule_id blocks, each meeting its own §0.5 minimum …
```

**Worked example of the structured form** (this is the format every instance MUST emit):

```yaml
setup_api_calls:
  - call: "POST /subscription-plans"
    payload: { tier: "PLUS", monthly_fee_cents: 6000, included_class_credits: 8, pt_discount_pct: 0.25 }
    as: PlatformAdmin
    captures: { plus_plan_id: $.data.id }
  - call: "POST /stores"
    payload: { name: "CA Store", state_code: "CA", capacity: 100 }
    as: PlatformAdmin
    captures: { store_ca_id: $.data.id }
  - call: "POST /_clock/set_current_utc"
    payload: { to_iso8601: "2026-06-01T00:00:00Z" }
    as: PlatformAdmin
  - call: "POST /members/register"
    payload: { email: "m_ca@x.com", password: "p", full_name: "M CA", state_code: "CA", plan_id: "${plus_plan_id}", home_store_id: "${store_ca_id}", coupon_code: "FLAT10" }
    as: Anonymous
    captures: { m_ca_id: $.data.id, sub_ca_id: $.data.subscription_id, tok_ca: $.data.verification_token }
  - call: "POST /_payments/simulate"
    payload: { subscription_id: "${sub_ca_id}", outcome: "SUCCEEDED" }
    as: PlatformAdmin
  - call: "POST /members/${m_ca_id}/verify"
    payload: { verification_token: "${tok_ca}" }
    as: Anonymous

trigger:
  - call: "POST /members/${m_ca_id}/cancel"
    payload: { refund_destination: "WALLET" }
    as: Member
    as_user_id: "${m_ca_id}"

assert:
  - "Member.${m_ca_id}.wallet_credit_cents == 2733"
  - "Member.${m_ca_id}.status == CANCELLED_PENDING"
```

Two things this form mechanically enforces:

1. **Every `${var}` traces back to a `captures:` line earlier in the same instance.** If `${plus_plan_id}` appears in any `payload:` / `as_user_id:` / path template but no earlier `captures:` binds it, the scaffold has a hole that demands action via the §1.5 priority ladder (compose → business → test-driving). Bare placeholder strings like `<plus_plan_id>` smuggled into prose can no longer hide an absent producing endpoint.
2. **Every captured field is declared in §1.5.** If `captures: { tok_ca: $.data.verification_token }` references `verification_token` but the §1.5 register endpoint's `output:` does not list that field, the scaffold has under-specified its response shape — return to §1.5 and add the field (or, if PRD truly doesn't surface it, add a test-driving endpoint to fetch it).

**Instance counts**: §0.5 is authoritative. Quick reference — every rule has the same minimum: **≥ 2 instances → ≥ 18 instances total**, counted as `- name:` entries nested under `instances:`. A scaffold with 9 `rule_id`s each carrying a single instance = 9 instances = FAIL.

**Per-instance contract:**
1. Every `grounds:` entry MUST resolve to a declared element in §1.1–§1.6. A grounds entry naming a missing calculation, transition, validation, field, or race is a dangling claim — remove it or add the grounding.
2. `test_recipe.setup + setup_api_calls + trigger + assert` together MUST reproduce the scenario from empty-DB state using only endpoints declared in §1.5. No wall-clock waits; time-gated setups use the clock-set endpoint §1.5 already provides.
3. **`setup_api_calls:` is mandatory, structured, and operationalises §1.5's testability-completeness audit.** Write the ordered sequence of API invocations that drives the system from empty-DB into the state described by `setup:`. Each entry MUST be a structured call object with the keys shown in the schema (`call`, `payload`, `as`, optional `as_user_id`, optional `captures`) — not a prose string. Each `call` MUST resolve to an endpoint declared in §1.5 (path, method, role exactly as §1.5 specifies); each `payload:` field MUST conform to that endpoint's `input:` schema. **Placeholder discipline:** every `${var}` referenced in any `payload:`, `as_user_id:`, or path template MUST be bound by a `captures:` block on an earlier line of the same instance. An unbound `${var}` is a missing-endpoint signal — handle it via the §1.5 priority ladder (fallback priority, NOT a sequence to execute — stop at the first rung that resolves the gap): **(1) compose existing endpoints first; (2) only if (1) fails, return to §1.5 and add a general business endpoint, then re-derive the chain; (3) only as last resort, when (1) and (2) both fail, add a test-driving endpoint under `/_<name>`.** Silently omitting `setup_api_calls:`, leaving prose strings instead of structured calls, leaving entries vague (e.g., `"create a member with wallet_credit_cents=500"` instead of the concrete POST chain that produces that balance), or smuggling unbound `${var}` placeholders into payloads are all forbidden — the chain must be directly executable by the downstream unit-test-generator.
3a. **Literal-vs-placeholder discipline inside `payload:`.** A `payload:` field value MUST be a literal whenever the scaffold author can determine it at writing time — `state_code: "CA"`, `monthly_fee_cents: 6000`, `to_iso8601: "2026-06-01T00:00:00Z"`, enum members, fixed coupon codes, fixed dates. **The `${var}` form is reserved for values that can only come from a prior call's response**: server-minted ids, server-stamped timestamps, server-issued tokens. Pushing computable literals into placeholders ("let the test-generator figure it out") is the symmetric failure mode to leaving asserts as `round(...)` expressions (contract item 7) — both propagate "unresolved" downstream and produce broken tests whose wrong fixture silently agrees with a wrong implementation. When in doubt, write the literal.
3b. **`captures:` MUST reference fields declared in §1.5's `output:` for that endpoint.** A capture like `captures: { tok_ca: $.data.verification_token }` is a claim that the §1.5 register endpoint exposes `verification_token` in its response. If §1.5 does not declare that field, either (a) return to §1.5 and add it to the endpoint's `output:`, or (b) add a separate read endpoint that surfaces it, or (c) add a test-driving endpoint that fetches it. Capturing an undeclared field is the same class of failure as referring to an undeclared endpoint — it forces downstream skills (PRD-, unit-test-, implementation-generator) to invent the contract.
3c. **OCC `expected_*_version` payload values MUST reference a `${var}` from an earlier `captures:` — pure or inside an expression — never be bare literals.** OCC version inputs encode "the version the client last observed on the parent"; that value can only originate from a server response. The rule is unconditional: cascades from §1.3 transitions or §1.7 rules silently bump the parent's `version` between its creation and this call, so any literal that "looks right" goes stale. Pure `${var}` is the happy path; an arithmetic expression over a `${var}` (e.g. `${var} - 1`) is the disciplined form for deliberate stale-version negative tests.
4. `distinguishing_aspect` MUST be falsifiable — one sentence the test can turn into a concrete assertion, naming the specific distinction §0.5 requires of this `rule_id` (different entity domain, different error-category pair, etc.). No hedging ("may differ", "could vary").
5. `name` MUST be unique across the whole `scaffold_difficulty_design` and stable across regenerations (tests cite it in their docstrings for audit).
6. `assert:` entries MUST cite exact field names and literal values where possible (e.g., `Order.delivery_fee != Assignment.final_delivery_fee`; `Customer.wallet_balance unchanged after assignment creation`), not paraphrases.
7. **Any `assert:` line referencing a numeric value derived from a formula MUST be a literal the scaffold author actually computed by code.** Pin the inputs in `setup:`, execute the relevant `calculations[].formula` as code (a short Python snippet against the formula and its `constants:`), and write the resulting literal into the assertion — e.g., `Order.delivery_fee == 5.40`, NOT `Order.delivery_fee == round(3.00 + ceil(2.0)*1.20 + 0, 2)` and NOT a rough estimate. Unresolved formulas, estimates, and "let the test-generator compute it" all propagate arithmetic errors into broken tests whose wrong expected value silently agrees with a wrong implementation. When in doubt, execute the formula.

### 1.9 Scaffold Corner Design

**Output**: a separate file `SCAFFOLD_CORNER_DESIGN.yaml` sibling to `SCAFFOLD.yaml`, with `scaffold_corner_design:` as its single top-level key.

**Scope**: enumerate every testable claim the scaffold's §1.1–§1.7 surface declares that §1.8 does not already cover (required-field validation, state-machine invalid-from rejection, RBAC denial, FK integrity, response envelope, computed-field correctness, cross-entity cascade, OCC stale-version conflict, etc.). §1.8 is the depth probe (9 hard reasoning rules × 2 instances); §1.9 is the breadth probe.

**Core value**: §1.9 generation IS a §1.5 audit pass. Same gates as §1.8 — `setup_api_calls` reachability, literal lock, §1.5 priority ladder. §1.9 is breadth, not a weaker tier.

**Taxonomy**: read `references/claim-extraction-guide.md` (sibling to this SKILL.md) first. The guide's nine sections (Entities / State Machines / Calculations / Validations / Endpoints / Errors / RBAC / Cross-Cutting Complexity Layers / Consistency Model) ARE §1.9's `section:` values; the per-section claim-type rows ARE §1.9's `claim_type:` values. Do not invent additional categories or `claim_type:` names.

**Coverage target**: the walk is a *vehicle* for iterating §1.5 against `setup_api_calls` — not an end in itself. As you traverse the guide row-by-row against this scaffold's §1.1–§1.7 surface and author each corner instance (error_id triggers, invalid-from rejections, RBAC denials, FK integrity, response envelope, etc.), the act of writing its `setup_api_calls` chain forces §1.5 to be challenged: every precondition the chain needs must be producible by composing §1.5 calls; every gap triggers the priority ladder. The output is two-way — an enumerated set of corner instances AND a §1.5 surface provably capable of driving empty-DB into each instance's precondition (**test-state reachability**, guaranteed). What makes §1.9 valuable is this iteration, not the enumeration count. Skip non-applicable rows without ceremony; emit `excluded_because:` stubs when §1.8 already covers the corner.

**Schema:**

```yaml
scaffold_corner_design:
  - section: state_machines
    instances:
      - name: cancel_booking_from_already_cancelled_returns_invalid_state
        claim_type: invalid_transition                      # from claim-extraction-guide's per-section table
        grounds: [state_machines.Booking.transitions.CANCELLED_to_CANCELLED]
        distinguishing_aspect: "Booking already CANCELLED — second cancel must fail with ERR_INVALID_STATE; no side effects fire."
        test_recipe:
          setup: ["<precondition prose>"]
          setup_api_calls: [ <structured calls; same form as §1.8> ]
          trigger: [ <structured call> ]
          assert: ["<one observable per line, literal values>"]

      - name: error_subscription_inactive_on_create_booking   # already exercised by §1.8 → stub
        claim_type: violation_to_error
        grounds: [errors[ERR_SUBSCRIPTION_INACTIVE]]
        excluded_because:
          difficulty_instance: cross_entity_state_dependency / booking_requires_subscription_active_or_grace
          rationale: "Asserted as the failure path of the named §1.8 instance."
        # NO test_recipe.
```

**Per-instance contract**: same seven-point contract as §1.8 (clauses 1–7) — grounds resolvability; `setup_api_calls` structured form with placeholder closure, literal-vs-placeholder discipline, captures-resolve-to-§1.5-`output:`; `distinguishing_aspect` falsifiability; `name` uniqueness; `assert:` specificity with exact field names and literal values; formula-derived asserts pre-computed as literals. `name` MUST be unique across the union of `scaffold_difficulty_design` and `scaffold_corner_design`.

**`excluded_because:` stubs**: when a corner is already covered by a §1.8 instance, emit a stub (`name` + `claim_type` + `grounds` + `excluded_because: { difficulty_instance, rationale }`); `test_recipe` is forbidden. The cited `difficulty_instance` MUST exist by `name` in `SCAFFOLD_DIFFICULTY_DESIGN.yaml`.

**§1.5 linkage — same priority ladder as §1.8.** When a corner instance's `setup_api_calls` hits an unreachable precondition (unbound `${var}`, `captures:` referring to a field §1.5 doesn't declare, or a setup state no chain of §1.5 calls can produce), try the ladder in order and **stop at the first rung that resolves the gap** — this is fallback priority, NOT a sequence to execute:
1. **Compose existing endpoints** — re-search §1.5 for a chain you missed; many "missing" capabilities are already reachable via composition.
2. **Only if (1) fails** — return to §1.5 and add a general business endpoint that fits the domain's real-world admin/operator surface, then re-derive the chain.
3. **Only as last resort, when (1) and (2) both fail** — add a `/_<name>` test-driving endpoint to §1.5.

Reshape §1.5 first, then re-derive the chain. Weakening the corner, papering over with prose, or marking it `excluded_because:` when no §1.8 instance covers it are forbidden — treat §1.9 generation as a §1.5 audit pass.

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
- [ ] Every `concurrency_rules` entry passes §1.2.1's serial-observability filter; others moved to `state_machines` or `validations`
- [ ] Each `concurrency_rules.write_endpoint` takes `expected_<parent>_version` as required input and bumps `<parent>.version` in its side effects
- [ ] No "simultaneously" / "first-writer-wins" / "race winner" / "in parallel" vocabulary anywhere in the scaffold
- [ ] File split honored: `scaffold_difficulty_design:` appears only as the top-level key of `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `scaffold_corner_design:` appears only as the top-level key of `SCAFFOLD_CORNER_DESIGN.yaml`, and neither appears inside `SCAFFOLD.yaml`
- [ ] Every `instances[*].grounds[*]` reference (in either `scaffold_difficulty_design` or `scaffold_corner_design`) resolves to a declared element in `SCAFFOLD.yaml`'s §1.1–§1.7

**Self-Consistency:**

Each declaration in the scaffold is an edge; self-consistency means both ends resolve inside the scaffold. Completeness asks whether required fields are filled — these checks ask whether what is filled coheres.

- [ ] **Enum value closure** — Every enum value declared in an entity field's `constraints:` MUST be produced by at least one state-machine transition, calculation output, or system initialization. A declared value that no path writes (e.g., a `WAIVED` settlement status with no waive action) is a dead end; remove it or add the producing transition.
- [ ] **Trigger ↔ side-effect bidirectional match** — Every `calculations[].trigger:` that names a state transition MUST have that transition's `side_effects:` list the calculation's output field. Conversely, every side-effect that says "recompute X" MUST map to a declared calculation. A calc claiming "on Order acceptance" while the ACCEPT transition's side_effects only refresh `updated_at` is unresolved.
- [ ] **Aggregate selection precision** — Every aggregation (`sum of`, `count of`, `max over`, `latest N`) MUST pin three elements: (a) source entity with explicit status filter, (b) time or index window with inclusive/exclusive boundary, (c) tie-break rule when the result is order-sensitive. "Sum of Fine.amount for subject whose settlement_status flipped PENDING→SETTLED" omits which PENDING fines enter the sweep and is insufficient.
- [ ] **No fuzzy adjectives in constraint scopes** — Uniqueness constraints, filter clauses, precondition prose, and selector criteria MUST NOT use adjectives like "active", "valid", "live", "open", "current" as a stand-in for a status filter, nor "best", "next", "preferred", "top", "highest-ranked", "best-ranked" as a stand-in for a ranking rule. Write the enum set explicitly (`status IN {ACTIVE, SUSPENDED}`, not "active restaurants") and pin the ranking expression explicitly (sort key + tie-break, not "best available rider").
- [ ] **Selector determinism** — Whenever the scaffold's prose resolves to "which entity" or "which entities" by description rather than by an explicit id supplied in the request (any field in any table — state_machines, calculations, validations, endpoints, concurrency_rules), the logic MUST pin: (a) the eligibility filter defining the candidate set as an explicit enum/predicate over entity fields; (b) the ranking expression (sort key, also over entity fields); (c) the tie-break rule when the ranking expression ties; (d) the fallback when the candidate set is empty (error_id or deferred-queue behavior). "Best X" / "next Y" / "the preferred Z" without these four elements is under-specified which leading to ambiguity.
- [ ] **No random fields in business decisions — use `created_at`, never `id`, as fallback** — Random properties, especially UUID/random `id`, MUST NOT participate in any selector, ranking, tie-break, allocation order, batch-processing order, cascade order, conflict-resolution rule, or chronological replay order that affects response data or persisted state. This prohibition includes fallback ordering, final tie-breaks, and "deterministic" last resorts. If a precise common-field fallback is required, use `created_at ASC`; never use `id`. Any scaffold that uses UUID/random `id` for observable decision-making fails this checklist.
- [ ] **Cross-entity reference resolvability** — Any precondition or side-effect that references another entity as "a linked X", "a related X", "the associated X", or "the corresponding X" MUST name the foreign-key path or pin the query selector. "A linked WorkOrder is in UNDER_REVIEW" without declaring `WorkOrder.related_order_id == Order.id` forces downstream generators to invent the link.
- [ ] **FK descriptions use the canonical `FK -> {Entity}.id` prefix** — Every entity field whose value is a foreign key has a `description:` that starts with `FK -> <ParentEntity>.id`, optionally followed by `; <annotations>` (cardinality like `unique per Offer`, denormalization notes, etc.). Prose alternatives ("references X", "points to Y") are forbidden — the canonical prefix is what `scaffold_lint.py` parses to build the FK graph for check (f).
- [ ] **Every FK has a reverse-reachability GET endpoint (§1.5)** — For every field whose description matches `^FK -> <Entity>\.id\b`, §1.5 declares at least one GET endpoint that lets a client enumerate (or fetch, for 1:1) the child given the parent's `id`. Either sub-resource form (`GET /<parent-collection>/{id}/<child-segment>` with `output: <Child>` or `<Child>[]`) or filtered-list form (`GET /<child-collection>` with the FK field declared as `<fk_field>?` in `input:`). An endpoint whose `output:` returns the child at creation does NOT exempt the FK — reachability is a lifecycle property. `scaffold_lint.py` check (f) reports violations as `FK_REVERSE_UNREACHABLE` and blocks the lint until fixed.
- [ ] **Computation determinism** — Order-sensitive calculations MUST pin both sort key and tie-break. Multi-step rounding MUST pin the rounding order. Fields referenced inside `formula:` MUST be unambiguous — use the exact field name (`credit_balance_cents`), not paraphrases ("the customer's credit") that could resolve to either a provisional or a finalized field.

**Test-recipe ↔ endpoint compatibility — applies to every `test_recipe` in BOTH `scaffold_difficulty_design` (§1.8) AND `scaffold_corner_design` (§1.9), audited against §1.5.**

§1.8 and §1.9 are transcribed verbatim into pytest fixtures by the downstream unit-test-generator — not re-derived from §1.1–§1.7. A chain that violates this same scaffold's own §1.1–§1.7 declarations therefore lands as a broken fixture which the PRD-faithful implementation correctly rejects, and the test fails for the wrong reason. Run the two replay checks below on every instance in BOTH files.

- [ ] Every `setup_api_calls` and `trigger:` entry is a STRUCTURED call object (keys: `call`, `payload`, `as`, optional `as_user_id`, optional `captures`).
- [ ] Each `call:` resolves to a §1.5 endpoint — path, method, and `as:` role match exactly.
- [ ] Each `payload:` conforms to that endpoint's `input:` schema (no unknown fields, no missing required fields, types match).
- [ ] **Placeholder closure** — every `${var}` referenced in any `payload:`, `as_user_id:`, or path template is bound by a `captures:` block on an earlier line of the same instance. Zero unbound placeholders across both `scaffold_difficulty_design` and `scaffold_corner_design`. An unbound `${var}` means §1.5 is missing a producing endpoint — fix via the priority ladder (compose → business → test-driving), do not paper over.
- [ ] **Captures resolve to §1.5 `output:` fields** — every JSONPath in `captures:` (e.g., `$.data.verification_token`) names a field that the called endpoint actually declares in its `output:`. Capturing an undeclared field is forbidden; declare the field in §1.5 or add a different endpoint that exposes it.
- [ ] **Literal-vs-placeholder discipline** — `payload:` fields that the scaffold author can determine at writing time (state codes, fixed amounts, ISO timestamps, enum members, fixed coupon codes) are LITERALS; `${var}` is used ONLY for values that can only come from a prior call's response (server-minted ids, server-stamped timestamps, server-issued tokens).
- [ ] **OCC `expected_*_version` references a `${var}`, never a bare literal** — every OCC version input in `payload:` is a `${var}` from an earlier `captures:` block, or an expression over one (e.g. `${var} - 1` for deliberate stale-version negative tests). Cascades silently bump the parent's `version` between its creation and this call, so a literal goes stale even when it "looks right".
- [ ] **Call-by-call rule replay** — for every call in `setup_api_calls` AND `trigger:` (both §1.8 and §1.9), the cumulative state from prior calls must satisfy the §1.2 transition's `from:` and `preconditions:`, every §1.4 row whose `applies_to:` covers this endpoint, and every §1.6 `error.condition:`. Fix by reordering/inserting prior calls, or by restructuring the design to observe the property from a reachable state; do not weaken §1.2/§1.4 to fit a broken chain.
- [ ] **End-state replay including side-effects** — every adjective and cardinality in `setup:` must be a consequence of executing the chain, not a wish on top. Replay each call's `side_effects:` forward — cascades, derived-field recomputes, counter/posture updates, §1.3 calculation outputs — and confirm the resulting state matches every claim in `setup:`.
- [ ] No `setup_api_calls` or `trigger:` is empty or placeholder prose. If `setup_api_calls` genuinely cannot be written without an unbound `${var}`, reshape §1.5 per the priority ladder (compose → business → test-driving) rather than papering over.
- [ ] **`scaffold_lint.py` clean run.** Run `python3 <skill-dir>/scaffold_lint.py <task-dir>` after both design files are drafted; it mechanically re-verifies (a) endpoint declared in §1.5, (b) `as:` ∈ roles, (c) `payload:` ⊆ `input:`, (d) `captures:` resolve to `output:`, (e) OCC version inputs reference a `${var}`, not a bare literal, (f) every FK field declared in §1.1 has a reverse-reachability GET endpoint in §1.5 (sub-resource or filtered-list form). **Paste the verdict block verbatim — do not paraphrase or self-report.** Each violation maps to one fix locus: (a) → §1.5 priority ladder, (b) → §1.5/§1.7 roles, (c) → §1.5 `input:`, (d) → §1.1 entity fields or §1.5 `output:`, (e) → add a `captures:` reading `$.data.version` on the parent, then reference `${...}` here, (f) → add either `GET /<parent-collection>/{id}/<child-segment>` or extend `GET /<child-collection>`'s `input:` to include `<fk_field>?` (see §1.5 FK reverse-reachability principle). Re-run until `VERDICT: clean lint`.

**Difficulty (audit — the spec lives at §0.5):**
- [ ] Every §0.5 rule (1–9) is satisfied by §1.1–§1.7, honoring its differentiation clause, and mirrored in `SCAFFOLD_DIFFICULTY_DESIGN.yaml` with ≥2 instances per rule (≥18 instances total)
- [ ] Every instance's `distinguishing_aspect` names the specific distinction §0.5 demands of its `rule_id` — not generic prose
