---
name: prd-bench-generator
description: Generate PRD-based coding benchmarks from a scenario description. Produces structured seed tables (entity model, state machines, calculations, validations, API endpoints, error catalog), a natural-language PRD, and black-box test suite. Use when the user wants to create a new PRD benchmark, coding challenge, or LLM evaluation task.
---

# PRD Benchmark Generator

## Input / Output

### Input

User provides two things:

1. **场景简述**（scenario）：一段自然语言描述，说明要构建什么系统、涉及哪些角色和核心流程。例如："医院排班调度系统，管理治疗计划、轮班、手术操作和医疗资源分配，需要预算控制和患者安全评分。"

2. **输出文件路径**（output_path）：生成的 YAML 文件要保存到哪里。例如：`./benchmarks/hospital-shifts.yaml`

### Output

一个完整的 YAML 文件，保存到用户指定的路径，包含以下 7 个顶层 section：

```yaml
scenario: "用户提供的场景简述"
domain_name: "短横线命名的领域名"
api_prefix: "/顶层资源路径"

entities:        # 表1: 实体关系表 — 所有实体、字段、类型、层级
state_machines:  # 表2: 状态机表 — 每个有状态的实体的完整状态图
calculations:    # 表3: 计算规则表 — 所有公式、常量、变体
validations:     # 表4: 验证规则表 — 按优先级排序的校验链
endpoints:       # 表5: API端点表 — 所有端点的方法、路径、角色、输入输出
errors:          # 表6: 错误码目录 — 所有错误码及触发条件
roles:           # 表7: RBAC矩阵 — 角色和专属/共享权限
```

每个 section 的详细结构见下方 Phase 1。完整示例参见 [example-hospital-shifts.yaml](example-hospital-shifts.yaml)。

## Workflow

```
Phase 1: Seed Tables    → 从场景生成 7 张结构化表，输出为 YAML 文件
Phase 2: PRD            → 从 YAML 生成自然语言 PRD（后续步骤，非本 skill 直接输出）
Phase 3: Test Artifacts → 从 YAML 生成类型定义、API client、测试用例（后续步骤）
```

本 skill 的核心产出是 **Phase 1 的 YAML 文件**。Phase 2 和 Phase 3 是基于该文件的下游加工。

Copy this checklist and track progress:

```
Benchmark Generation Progress:
- [ ] Phase 1.1: Entity-Relationship Table
- [ ] Phase 1.2: State Machine Table
- [ ] Phase 1.3: Calculation Rules Table
- [ ] Phase 1.4: Validation Rules Table (ordered)
- [ ] Phase 1.5: API Endpoint Table
- [ ] Phase 1.6: Error Code Catalog
- [ ] Phase 1.7: RBAC Matrix
- [ ] Phase 2: PRD generation (downstream)
- [ ] Phase 3: Test artifacts (downstream)
```

---

## Phase 1: Generate Seed Tables

From the user's scenario, generate these tables. They are the **single source of truth** — all downstream artifacts derive from them.

### 1.1 Entity-Relationship Table

Define every entity, its fields, types, and hierarchy.

```yaml
entities:
  - name: EntityName
    parent: ParentEntity | null
    fields:
      - name: field_name
        type: string | number | boolean | enum | datetime
        source: input | computed | system
        description: brief purpose
        constraints: optional validation rules
    common_fields: true  # auto-include id, created_at, updated_at, version
```

**Design principles:**
- 4–8 entities (enough for hierarchy, not overwhelming)
- At least one entity with computed fields (forces LLM to implement calculation)
- At least one entity with a ledger/balance pattern (running total that updates on events)
- Field names must be explicit — these will appear as backticked terms in PRD

### 1.2 State Machine Table

For each entity with a `status` field, define the full state graph.

```yaml
state_machines:
  - entity: EntityName
    states: [STATE_A, STATE_B, STATE_C]
    transitions:
      - from: STATE_A
        to: STATE_B
        trigger: endpoint_name
        actor: RoleName
        preconditions: [list of checks]
        side_effects: [list of cascading changes]
```

**Design principles:**
- Each entity should have 3–6 states
- At least one "cascade" transition (parent state change affects children)
- At least one "revert" transition (e.g., cancel → reopen parent)
- Terminal states should be clearly marked

### 1.3 Calculation Rules Table

Define every formula the system must compute. This is the core difficulty source.

```yaml
calculations:
  - name: rule_name
    trigger: when this calculation runs
    algorithm: forward_looking | chronological | aggregation | threshold
    formula: |
      pseudocode or mathematical expression
    constants:
      THRESHOLD: 6000
      MULTIPLIER: 2
      PRECISION: 2 decimal places, round_half_up
    variants:
      - name: variant_name (e.g., provisional vs final)
        difference: how this variant diverges
```

**Design principles:**
- At least one calculation with two variants that produce different results for the same data (core difficulty)
- Include specific numerical constants (LLM must extract these from prose)
- Define precision/rounding rules explicitly

### 1.4 Validation Rules Table (Ordered by Priority)

```yaml
validations:
  - priority: 1
    check: header_presence
    error: ERR_MISSING_HEADER
    http_status: 400
  - priority: 2
    check: role_permission
    error: ERR_INSUFFICIENT_PERMISSIONS
    http_status: 403
  # ... safety checks before fiscal checks ...
```

**Design principles:**
- Order matters — tests will verify "when two conditions fail, which error wins"
- Group: auth → existence → state → business-safety → business-fiscal
- 15–30 error codes total

### 1.5 API Endpoint Table

```yaml
endpoints:
  - method: POST
    path: /resource-name
    description: Create a new resource
    authorized_roles: [RoleA]
    request_body: [field_name: type]
    response_body: ResourceName object
    success_code: 201
    side_effects: [triggered calculations or state changes]
```

**Design principles:**
- RESTful nested paths reflecting entity hierarchy
- 20–30 endpoints
- Include both CRUD and action endpoints (e.g., `/activate`, `/cancel`)
- Define response envelope format (meta + data pattern)

### 1.6 Error Code Catalog

```yaml
errors:
  - id: ERR_DESCRIPTIVE_NAME
    http_status: 400 | 402 | 403 | 404 | 409
    triggered_by: concise description of condition
```

### 1.7 RBAC Matrix

```yaml
roles:
  - name: RoleName
    exclusive_operations: [operations only this role can do]
    shared_operations: [operations shared with others]
```

**Design principles:**
- 3 roles is the sweet spot
- Each role should have exclusive operations (not just a superset hierarchy)

---

## Phase 2: Generate PRD

Transform the seed tables into a natural-language PRD document.

### PRD Structure Template

```markdown
# {System Name} API — Product Requirements Document

## 1. Introduction
[1 paragraph: what the system does, why it exists]

## 2. Global Specifications & System-Wide Principles
### 2.1 Authentication & Authorization
### 2.2 Response Format
[JSON envelope example with meta, response_type, data]
### 2.3 Pagination
### 2.4–2.N [One subsection per cross-cutting concern]

## 3. Business Logic & Workflows
### 3.1–3.N [One subsection per workflow/lifecycle]

## 4. Endpoint Definitions
[Table: Method | Path | Description | Authorized Roles]
— DO NOT include request/response body columns

## 5. Error Code Catalogue
[Table: Error ID | HTTP Status Code]
— DO NOT include triggering conditions
```

### Information Scattering Rules (Critical for Difficulty)

These rules control how hard the PRD is to implement:

1. **Field names in prose**: Embed using backticks in business narrative, never in a schema table
   - ✅ "A `ChargeNurse` provides a `plan_name` and a `total_budget`"
   - ❌ A table listing all fields

2. **Split across sections**: Put different fields of the same endpoint in different sections
   - e.g., `procedure_id` in §3.3, but `override_protocol_check` in §3.5

3. **Algorithms in prose**: Describe calculation logic as narrative, never as pseudocode
   - ✅ "the system conservatively estimates future usage..."
   - ❌ `cost = sum(minutes) * rate * multiplier`

4. **Constants inline**: Embed thresholds in explanatory sentences
   - ✅ "requiring deep cleaning after 100 hours of operation"
   - ❌ `MAINTENANCE_THRESHOLD = 6000 minutes`

5. **Implicit relationships**: Don't state foreign keys explicitly
   - ✅ "proposes an Assignment via a payload containing the `procedure_id`"
   - ❌ "Assignment has a foreign key to Procedure"

6. **Endpoint table is minimal**: Only Method, Path, Description, Authorized Roles
   - Request/response bodies must be inferred from §3

---

## Phase 3: Generate Test Artifacts

### 3.1 Type Definitions

Mechanically derive from Entity-Relationship Table — create an interface per entity, an enum per status/role.

### 3.2 API Client

Mechanically derive from API Endpoint Table — one typed method per endpoint.

### 3.3 Test Scenario Design

Design test cases across these categories:

**Category A — CRUD & Structure (~25%)**
- Create each resource, verify response structure
- List with pagination, verify meta fields
- Get by ID, 404 for non-existent

**Category B — State Machines (~25%)**
- Each valid transition: verify status changes
- Each invalid transition: verify correct error
- Cascade/revert effects on parent-child hierarchy

**Category C — Calculations (~25%)**
- Control all inputs precisely (cost=10.0, duration=round numbers)
- At least one scenario where calculation variants diverge
- Verify intermediate AND final values

**Category D — Validation & Security (~15%)**
- Dual-failure → assert higher-priority error wins
- Boundary values: exactly at threshold, ±1
- SQL injection, mass assignment of read-only fields

**Category E — Concurrency (~10%)**
- Race conditions on shared state
- OCC version mismatch detection

### Test Design Principles

- Every test builds its own environment via API calls (pure black-box)
- Each test creates a unique top-level resource (UUID isolation, no cleanup needed)
- Ground truth is hand-calculated from controlled inputs, hardcoded in assertions
- Tests must not depend on data from other tests

---

## Quality Checklist

Before finalizing:

- [ ] Every backticked field in PRD maps to exactly one field in Entity table
- [ ] Every state transition has a test (positive + negative)
- [ ] Every calculation rule has a test with hand-calculated ground truth
- [ ] At least one test where calculation variants diverge
- [ ] Every error code has at least one test that triggers it
- [ ] Validation priority is tested (dual-failure scenarios)
- [ ] No test depends on data from another test
- [ ] All tests use API calls for setup (no DB access)
- [ ] PRD does NOT contain schema tables or pseudocode

---

## Reference Materials

- Blank seed tables template: [seed-tables-template.yaml](seed-tables-template.yaml)
- Completed example (hospital-shifts): [example-hospital-shifts.yaml](example-hospital-shifts.yaml)
