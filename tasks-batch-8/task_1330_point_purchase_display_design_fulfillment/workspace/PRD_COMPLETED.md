# POP Display Fulfillment API — Product Requirements Document

## 1. Introduction

A point-of-purchase display house sits at the intersection of creative services, light manufacturing, and retail logistics. A brand signs a program to place promotional displays into some number of a retailer's stores; the house must shepherd that program through structural and graphic design, retailer-mandated compliance screening on dimensions and materials, a costed production run sized against the store count with deliberate overage, kitting and per-store shipment inside retailer-imposed ship windows and dock appointments, in-store assembly support, damage adjudication, and finally a financial recap that tells the brand whether the program made money. Each of these stages is owned by a different specialist, and a mistake at any boundary — a design approved against the wrong rule set, a truck arriving outside its window, a replacement costed at the wrong tier rate — erodes the thin margin these programs carry.

This document specifies the API that orchestrates that end-to-end workflow. It is written for the engineers who will implement the service and defines the lifecycle of every resource in the system, the state machines that govern them, the calculations that size and cost production, the retailer compliance gates, and the cross-entity cascades that keep a program's many moving parts consistent. All endpoints are mounted under the `/pop` path prefix. Requirements are stated from the business's point of view first; the HTTP contract summary appears in Section 4, and the error catalogue in Section 5.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the entire API, independent of any single workflow.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED`.

The system recognizes nine roles, spelled exactly as follows: `PlatformAdmin`, `ProgramManager`, `Designer`, `ComplianceOfficer`, `ProductionPlanner`, `WarehouseOperator`, `LogisticsCoordinator`, `ClaimsAdjuster`, and `FieldServiceManager`. A `PlatformAdmin` is the operational superuser and alone manages clients and the logical clock. A `ProgramManager` owns the retailer program lifecycle and the store roster. A `Designer` authors and submits display designs and drives revision loops. A `ComplianceOfficer` maintains retailer compliance rules and adjudicates designs. A `ProductionPlanner` authorizes and completes production runs. A `WarehouseOperator` kits displays and fulfills approved replacements. A `LogisticsCoordinator` schedules appointments and moves shipments through their windows. A `ClaimsAdjuster` adjudicates damage claims. A `FieldServiceManager` dispatches and resolves in-store help requests.

Identity in this system is uniformly opaque. When `X-User-Role` is `PlatformAdmin`, `ProgramManager`, `Designer`, `ComplianceOfficer`, `ProductionPlanner`, `WarehouseOperator`, `LogisticsCoordinator`, `ClaimsAdjuster`, or `FieldServiceManager`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes, but it never compares `X-User-ID` against any resource's `id`, and no ownership check against a stored entity is performed for any role.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

---

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. A non-numeric `limit` falls back to the default of 10, a `limit` below 1 is raised to 1, and a `limit` above 100 is reduced to 100 — out-of-range values are clamped, never rejected. The `offset` parameter specifies how many items to skip and defaults to 0; a non-numeric `offset` falls back to 0 and a negative `offset` is raised to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order; resources sharing an identical creation timestamp retain their insertion order. List responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `has_more` is true exactly when `offset` plus the number of items in the returned page is less than `total_count`.

### 2.4. Common Resource Properties

Every primary resource in the system — clients, programs, compliance rules, designs, production runs, stores, kits, shipments, damage claims, and field service requests — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments by one on every mutation of the resource. This is the field on which optimistic concurrency control (§2.7) is built.

The one exception is the program recap. A recap is minted once, at program close, and is immutable thereafter; it carries only `id` and `created_at`, and both `updated_at` and `version` are absent from it.

### 2.5. The Logical Clock

All time-dependent rules in this system — ship-window openings, delivery grace deadlines — are evaluated against a server-side logical clock, never against wall-clock time. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and the server must not fall back to wall-clock time under any circumstance. Every server-generated timestamp — `created_at`, `updated_at`, the `api_request_timestamp` in each response's `meta`, `shipped_at`, `delivered_at`, and the recap's `generated_at` — is read from this logical clock, so timestamps advance only when the clock is advanced. A `PlatformAdmin` may advance the logical clock to a supplied instant using an admin-only test-driving capability whose payload carries the target time in the `to_iso8601` field; the clock is set to exactly the supplied instant, and a missing or unparsable `to_iso8601` is rejected with `ERR_INVALID_REQUEST`. Business workflows read the clock; they never set it.

### 2.6. Money, Precision, and Rounding Discipline

All monetary amounts are represented as integer numbers of cents — program revenue, production run costs, and damage replacement costs alike — so no floating-point drift can enter program accounting. Rates in the production tier table are themselves integer cent values.

Percentages and per-line rollup values follow explicit rounding rules. Return-on-investment percentages are rounded to exactly two decimal places using the round-half-up method. When a kit's component costs are rolled up into a kit-level total, each component price is first rounded half-up to two decimal places on its own line, and the kit total is the sum of those already-rounded line values; the system does not sum raw prices and round once at the end. This per-line-then-sum ordering is pinned and may not be reversed.

### 2.7. Optimistic Concurrency Control

Two write operations in the system are guarded by optimistic concurrency control, and each names the parent entity whose version it guards.

Creating a production run accepts `expected_program_version`, holding the `version` of the parent retailer program as the client last observed it. If the field is supplied and the program's current `version` has advanced beyond that observed value — for example because another writer transitioned the program since the client read it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client cannot build a run on a program state it has not seen. If the field is omitted, no version comparison is performed and the create proceeds.

Approving a display design accepts `expected_design_version`, holding the `version` of the design as the approver last observed it. If the field is supplied and the design's `version` has advanced since — for example because a revision loop bumped it — the approval is rejected with `ERR_STALE_VERSION` (HTTP 412). If the field is omitted, no version comparison is performed and the approval proceeds.

Endpoints not named in this section take no version field at all; clients must not supply one and the server performs no version comparison on them.

### 2.8. Cross-Entity Cascades and Hierarchical Consistency

The aggregate hierarchy runs from client to retailer program, and from a program down to its compliance rules, designs, production runs, and stores; kits belong to production runs, and shipments and damage claims belong to kits. Several operations deliberately mutate more than one resource in a single transaction, and these cascades are part of the contract:

- Completing a production run creates one kit per store of the parent program, each kit born in `PENDING` status.
- Shipping a shipment pushes its parent kit from `KITTED` to `SHIPPED`; delivering a shipment pushes the kit from `SHIPPED` to `DELIVERED`. Kit logistics states are never set directly — they move only as a cascade of shipment events (and of damage approval, below).
- Approving a damage claim whose kit is still in `SHIPPED` status moves that kit to `DAMAGED`, a terminal state for the kit.
- Cancelling a program cascades every non-terminal design of that program to `REJECTED`.
- Closing a program mints its recap (§3.7).

Every mutation, whether directly requested or produced by a cascade, refreshes the affected resource's `updated_at` and increments its `version` independently.

### 2.9. Nested Resource Retrieval and the Validation Cascade

Requests that target nested resources are validated left to right along the path: the existence of each path-referenced resource — program, then design, run, kit, shipment, claim, or field service request, in the order they appear — is confirmed in sequence, and the request is rejected with `ERR_NOT_FOUND` at the first identifier that does not correspond to an existing resource, before any later identifier or any business rule is examined. On creation endpoints, the request body's field-level sanity (required fields present, types correct, enums valid, ranges respected — item 9 below) is evaluated first, and the body-referenced identifiers (`client_id`, `program_id`, `design_id`, `production_run_id`, `store_id`, `kit_id`) are then resolved in the order the workflow names them, each drawing `ERR_NOT_FOUND` when it does not correspond to an existing resource, before any state, compliance, uniqueness, temporal, or referential check is examined. A request whose path matches no route, or whose method is not supported by the matched route, is rejected with `ERR_NOT_FOUND`.

More generally, when several checks apply to a single request they are evaluated in a fixed priority order, and the first failing check determines the error returned:

1. Authentication — the `X-User-Role` and `X-User-ID` headers are present and the role is one of the nine declared roles; otherwise `ERR_UNAUTHENTICATED`.
2. Authorization — the role is permitted for this endpoint; otherwise `ERR_UNAUTHORIZED`.
3. Existence — path-referenced resources exist, left to right; otherwise `ERR_NOT_FOUND`.
4. State — the target resource is in a state that permits the requested transition; otherwise `ERR_INVALID_STATE`.
5. Compliance gating — a design's `compliance_result` is `PASS` before approval, and a program has at least one active compliance rule before design work begins; otherwise `ERR_COMPLIANCE_FAILED`.
6. Uniqueness — no duplicate `design_code` within a program, no duplicate `store_number` within a program, and at most one kit per run-and-store pair; otherwise `ERR_DUPLICATE`.
7. Temporal — appointments, ship events, and deliveries respect the ship window and its grace period; otherwise `ERR_WINDOW_VIOLATION`.
8. Referential integrity — cross-entity references point at resources in acceptable states (an approved design for a run, a shipped or delivered kit for a claim, a program/store match for a field service request); otherwise `ERR_REFERENTIAL`.
9. Field-level and fiscal sanity — required fields present, enums valid, quantities non-negative or positive as specified; otherwise `ERR_INVALID_REQUEST`.
10. Optimistic concurrency — on the two guarded writes of §2.7, the supplied expected version matches the parent's current `version`; otherwise `ERR_STALE_VERSION`.

Because of this ordering, a request that would fail both a compliance gate and a stale-version check surfaces `ERR_COMPLIANCE_FAILED`; a request that would fail both a fiscal field check and a stale-version check surfaces `ERR_INVALID_REQUEST`; and an authorization failure always masks every business rule behind it.

## 3. Business Logic & Workflows

### 3.1. Client Onboarding and the Retailer Program Lifecycle

Work begins when a `PlatformAdmin` registers a **client** — the brand or CPG company buying the program — supplying a `name` and a `contact_email`. A client carries a `status` field whose lifecycle has two values, `ACTIVE` and `SUSPENDED`, and every client starts `ACTIVE`.

With a client in place, a `ProgramManager` creates a **retailer program** under it, passing the `client_id` together with the `retailer_name` identifying the chain the program ships into, a marketing `program_name`, the `store_count` of stores that will receive displays, and the contracted `program_revenue_cents`. The `store_count` must be at least 1 and `program_revenue_cents` at least 0; violations are rejected with `ERR_INVALID_REQUEST`. A program is born in `DRAFT` status and walks a five-stage lifecycle — `DRAFT` → `DESIGN` → `PRODUCTION` → `FULFILLMENT` → `CLOSED` — with an early-exit branch to `CANCELLED`. Each stage transition is driven by the `ProgramManager` and each increments the program's `version`.

Moving a program from `DRAFT` to `DESIGN` — starting design — is gated on retailer compliance groundwork: at least one active compliance rule must already exist for the program. A start-design attempt against a program with no active rule is rejected with `ERR_COMPLIANCE_FAILED`; an attempt against a program no longer in `DRAFT` is rejected with `ERR_INVALID_STATE`. The later gates are simpler: authorizing production moves the program from `DESIGN` to `PRODUCTION` and requires that at least one design of the program has reached `APPROVED`; starting fulfillment moves it from `PRODUCTION` to `FULFILLMENT` and requires that at least one production run has reached `PRODUCED`. In both cases, a program in the wrong stage draws `ERR_INVALID_STATE`, and an unmet prerequisite — no `APPROVED` design for authorize-production, no `PRODUCED` run for start-fulfillment — is likewise rejected with `ERR_INVALID_STATE`.

Closing a program is permitted only from `FULFILLMENT`, and only when every kit of the program has reached a terminal state — each kit must be `DELIVERED` or `DAMAGED`. The close mints the program's recap, described in §3.7, and the close response carries the updated program object (now in `CLOSED`), not the recap. Cancelling, by contrast, is available only while the program is still young: a program in `DRAFT` or `DESIGN` may move to `CANCELLED`, and the cancellation cascades every non-terminal design of the program to `REJECTED`. Once a program has entered `PRODUCTION` it can no longer be cancelled. Anyone may read a program back, and a client's full program roster can be listed through the client's program listing.

### 3.2. Retailer Compliance Rules and the Design Review Cycle

Before design work starts, a `ComplianceOfficer` encodes the retailer's fixture requirements as **compliance rules** on the program. Each rule carries the `program_id` it belongs to, a `dimension` drawn from exactly five values — `MAX_WIDTH_IN`, `MAX_HEIGHT_IN`, `MAX_DEPTH_IN`, `ALLOWED_MATERIAL`, and `MAX_WEIGHT_LB` — and a `limit_value`. For the four `MAX_*` dimensions the `limit_value` is a numeric limit; for `ALLOWED_MATERIAL` it is a material token. The create payload may carry `limit_value` as a JSON number or as a string; a numeric value is normalized to its string form, so the stored and returned `limit_value` is always a string, with numeric limits parsed back out at evaluation time. A rule also carries an `active` flag that defaults to true when omitted, and only active rules are enforced. Because rules gate designs, adding a compliance rule has a program-wide side effect: the `compliance_result` of every non-terminal design in the program is recomputed against the new active rule set. Such recomputation rewrites `compliance_result` in place and does not by itself refresh a design's `updated_at` or increment its `version`.

A `Designer` authors a **display design** inside a program by submitting a payload with the `program_id`, a human-readable `design_code`, the physical dimensions `width_in`, `height_in`, and `depth_in`, the unit `weight_lb`, and the primary structural `material` token — typical values include `CORRUGATE`, `ACRYLIC`, and `METAL`. Each of the three dimensions and the weight must be greater than zero, and `design_code` must be unique within its program: a colliding code is rejected with `ERR_DUPLICATE`, while non-positive measurements are rejected with `ERR_INVALID_REQUEST`. A new design starts in `DRAFT` status with `revision_number` set to 1, and its `compliance_result` — either `PASS` or `FAIL` — is computed from the program's active rules and recomputed whenever the design's dimensions or material change or the active rules change. A design satisfies a `MAX_*` rule when the corresponding measurement does not exceed the rule's numeric limit, and satisfies an `ALLOWED_MATERIAL` rule when its `material` matches the rule's material token; `compliance_result` is `PASS` when every active rule is satisfied and `FAIL` otherwise.

The review cycle runs `DRAFT` → `SUBMITTED` → `COMPLIANCE_REVIEW` → `APPROVED`, with a rejection loop back to the drawing board. Submission is the `Designer`'s act and is permitted only while the parent program is in `DESIGN` — submitting under a program in any other stage is rejected with `ERR_INVALID_STATE` — and it triggers a fresh recomputation of `compliance_result` against the active rules as the design enters `SUBMITTED`. A `ComplianceOfficer` then begins review, moving the design from `SUBMITTED` to `COMPLIANCE_REVIEW`, and from there either approves or rejects it. Approval is the guarded gate of the whole design pipeline: the design must be in `COMPLIANCE_REVIEW` (else `ERR_INVALID_STATE`), its `compliance_result` must be `PASS` (else `ERR_COMPLIANCE_FAILED`), and the request must carry `expected_design_version` matching the design's current `version` (else `ERR_STALE_VERSION`, per §2.7). Rejection needs no such gate: any design in `COMPLIANCE_REVIEW` may be moved to `REJECTED`.

A rejected design is not dead. While the parent program remains in `DESIGN`, the `Designer` may send the design back from `REJECTED` to `DRAFT` through the revision loop, which increments `revision_number` by one — so a design's third pass through review carries `revision_number` 3 — and lets the cycle begin again; a revise attempt against a design not in `REJECTED`, or under a program no longer in `DESIGN`, is rejected with `ERR_INVALID_STATE`. Finally, once a design is `APPROVED` and at least one production run references it, the `ProgramManager` may lock the design, moving it from `APPROVED` to the terminal `LOCKED` state; an approved design with no run referencing it cannot yet be locked, and such an attempt is rejected with `ERR_INVALID_STATE`. `LOCKED` and `REJECTED` are the design machine's terminal states.

### 3.3. Production Runs: Overage, Tiered Costing, and Authorization

When the program reaches `PRODUCTION`, a `ProductionPlanner` creates a **production run** against it. The create payload names the `program_id`, the `design_id` of the design to build, the `overage_pct` to apply over the store count, and — because this is one of the two guarded writes of §2.7 — the `expected_program_version` of the parent program. The referenced design must be in `APPROVED` status at creation time; referencing a design in any other state is rejected with `ERR_REFERENTIAL`. A negative `overage_pct` is rejected with `ERR_INVALID_REQUEST`, and a stale `expected_program_version` is rejected with `ERR_STALE_VERSION`. Creating the run also advances the parent program's `version` by one, which is precisely what makes a second planner's cached program view go stale. A new run starts in `PLANNED` status.

Authorization is where the run gets its numbers. Until authorization, the run's `production_quantity`, `unit_cost_cents`, and `total_cost_cents` are null. Moving a run from `PLANNED` to `AUTHORIZED` requires the run to be `PLANNED`, the parent program to be in `PRODUCTION`, and the referenced design to be `APPROVED`; violations are rejected with `ERR_INVALID_STATE`. At that moment three computed fields are fixed on the run. First, `production_quantity` is determined: the program's `store_count` is scaled by one plus the `overage_pct` divided by one hundred, and the result is rounded up to the next whole unit whenever it is not already an integer — a 120-store program at ten percent overage produces 132 units, and a 101-store program at ten percent produces 112, never 111.1. Second, `unit_cost_cents` is looked up from a tiered rate table driven by that quantity: fewer than 100 units bill at 2500 cents per unit, quantities from 100 up to 499 bill at 2200 cents per unit, and 500 or more units bill at 1950 cents per unit. This is an average-rate-on-whole-quantity scheme — the entire `production_quantity` is billed at the single tier rate it qualifies for, never split marginally across tiers. Third, `total_cost_cents` is the `production_quantity` multiplied by the `unit_cost_cents`, an integer number of cents. All three values are frozen at authorization time and do not drift afterward.

Completion of the run is the `ProductionPlanner`'s declaration that manufacturing finished: a run in `AUTHORIZED` moves to `PRODUCED`, and in the same transaction the system creates one kit in `PENDING` status for every store of the parent program. A run may also be cancelled, but only while still `PLANNED` — cancellation moves it to `CANCELLED`, and an authorized or produced run can no longer be cancelled. `PRODUCED` and `CANCELLED` are the run machine's terminal states. Runs can be read back individually, listed per program, or listed per referenced design.

### 3.4. Stores, Kitting, and the Ship-Window Logistics Chain

The `ProgramManager` registers each receiving location as a **store** of the program, supplying the `program_id`, the retailer's `store_number`, and the ship-to `address`. Store numbers are unique within a program — a duplicate `store_number` is rejected with `ERR_DUPLICATE`.

A **kit** is the bundle of display components destined for one store under one production run. Kits normally arrive through the mark-produced cascade of §3.3, but a `WarehouseOperator` may also create one manually by naming a `production_run_id` and a `store_id`; the two references are validated for existence only — the system does not require the named store to belong to the named run's program — and at most one kit may exist per run-and-store pair, a second attempt being rejected with `ERR_DUPLICATE`. Kits start in `PENDING` and move `PENDING` → `KITTED` → `SHIPPED` → `DELIVERED`, with `DAMAGED` as an alternate terminal state reached only through damage approval (§3.5). The warehouse's kitting step — moving a kit from `PENDING` to `KITTED` — requires the kit's parent run to be in `PRODUCED` status; kitting against a run in any other state is rejected with `ERR_INVALID_STATE`. When a kit's component costs are rolled up, the per-line rounding discipline of §2.6 applies: each component price is rounded half-up to two decimal places first, and those rounded values are then summed.

With a kit in hand, a `LogisticsCoordinator` books a **shipment** for it, supplying the `kit_id`, the retailer-mandated `ship_window_start`, and the `ship_window_end`, which must be later than `ship_window_start` — a window whose end does not follow its start is rejected with `ERR_INVALID_REQUEST`. Booking is not gated on the kit's status — any existing kit may receive a shipment — and a kit may carry any number of shipments over its lifetime. An `appointment_at` may optionally be supplied at creation; it is recorded as supplied, without validation against the ship window — the window bounds are enforced only when the appointment is set through the transition below. The three datetime inputs are echoed back exactly as supplied, while `shipped_at` and `delivered_at` are null until their respective events stamp them. A shipment begins in `SCHEDULED` status.

The retailer receiving appointment is then pinned down: moving a shipment from `SCHEDULED` to `APPOINTMENT_SET` records an `appointment_at` that must fall within the ship window, inclusive of both bounds — an appointment before `ship_window_start` or after `ship_window_end` is rejected with `ERR_WINDOW_VIOLATION`. Releasing the truck moves the shipment from `APPOINTMENT_SET` to `SHIPPED` and carries two further preconditions: the parent kit must be `KITTED` (else `ERR_INVALID_STATE`), and the current logical time must be at or after `ship_window_start` — shipping before the window opens is rejected with `ERR_WINDOW_VIOLATION`. Shipping stamps `shipped_at` and cascades the parent kit from `KITTED` to `SHIPPED`. Confirming receipt moves the shipment from `SHIPPED` to `DELIVERED`, stamps `delivered_at`, and cascades the kit from `SHIPPED` to `DELIVERED`; delivery is accepted while the current logical time is no later than seven days after `ship_window_end` — this seven-day grace is the retailer's allowance for late dock arrivals — and a delivery attempted after the window end plus that grace is rejected with `ERR_WINDOW_VIOLATION`. A shipment that will never make it can instead be moved from `SHIPPED` to the terminal `FAILED` state; failing a shipment touches the shipment alone and leaves the parent kit's status unchanged (the kit remains `SHIPPED`). `DELIVERED` and `FAILED` terminate the shipment machine. Shipments are readable individually and listable per kit.

### 3.5. Damage Claims and Replacement Fulfillment

Displays arrive damaged often enough that adjudication is its own workflow. A **damage claim** against a kit may be reported by either a `ClaimsAdjuster` or a `WarehouseOperator`, supplying the `kit_id`, a free-text `reported_by` naming the reporter, and the `replacement_quantity` of replacement units needed. The referenced kit must be in `SHIPPED` or `DELIVERED` status — a claim against a kit in any other state is rejected with `ERR_REFERENTIAL` — and the `replacement_quantity` must be at least 1, else `ERR_INVALID_REQUEST`. A claim is born in `REPORTED` status.

Adjudication belongs to the `ClaimsAdjuster`. Approval moves a claim from `REPORTED` to `APPROVED` and again requires the parent kit to be in `SHIPPED` or `DELIVERED` at that moment — a kit that has left those states draws `ERR_INVALID_STATE`. A claim carries `replacement_cost_cents` as null from creation until approval fixes it. On approval the system computes `replacement_cost_cents` as the `replacement_quantity` multiplied by the `unit_cost_cents` of the production run that built the kit — replacements inherit the tiered unit rate the original run was authorized at. Approval also carries the workflow's sharpest cascade: if the kit is still in `SHIPPED` status, it moves to the terminal `DAMAGED` state in the same transaction; a claim approved against an already `DELIVERED` kit leaves the kit `DELIVERED`. Rejection moves a `REPORTED` claim to `REJECTED` with no side effects beyond the claim's own version bump. Finally, the physical replacement is fulfilled by a `WarehouseOperator`, moving an `APPROVED` claim to `FULFILLED`; only fulfilled claims count toward the program's final cost basis and recap tallies (§3.7). `FULFILLED` and `REJECTED` terminate the claim machine. Claims are readable individually and listable per kit.

### 3.6. In-Store Field Service

Once displays land in stores, assembly problems surface from the field. A **field service request** can be opened by a `FieldServiceManager` or a `ProgramManager`, naming the `store_id` where help is needed, the `program_id` for program-level reporting, and an `issue_type` drawn from exactly three values: `ASSEMBLY_HELP`, `MISSING_PARTS`, or `INSTRUCTION_CLARIFICATION`. The `program_id` must match the program the named store actually belongs to; a mismatched pairing is rejected with `ERR_REFERENTIAL`. A request opens in `OPEN` status.

From there the `FieldServiceManager` drives a short two-step machine: dispatching moves a request from `OPEN` to `DISPATCHED`, and resolving moves it from `DISPATCHED` to the terminal `RESOLVED` state. Each step is restricted to the appropriate predecessor state, with violations rejected as `ERR_INVALID_STATE`. Requests are readable individually, listable per store, and — thanks to the cross-aggregate `program_id` reference — listable per program for roll-up reporting.

### 3.7. Program Close-Out, Recap, and Return on Investment

The final act of a program is its close. Recall from §3.1 that closing requires the program to be in `FULFILLMENT` with every kit terminal — each `DELIVERED` or `DAMAGED`. At that instant the system mints the program's **recap**, one per program, stamped with a `generated_at` timestamp and keyed by its `program_id`. The recap is immutable: it carries `id` and `created_at` but, as §2.4 notes, no `updated_at` and no `version`.

The recap aggregates the program's physical and financial outcomes. `total_produced` is the sum of `production_quantity` across the program's runs that reached `PRODUCED`. `total_delivered` counts the program's shipments in `DELIVERED` status. `total_damaged` counts the program's damage claims in `FULFILLED` status. `total_cost_cents` is the final cost basis: the sum of `total_cost_cents` across the program's runs that reached `PRODUCED` plus the `replacement_cost_cents` of its approved-and-fulfilled damage claims.

Two return-on-investment variants bookend the program's financial story, both expressed as percentages rounded half-up to two decimal places. The provisional variant, `roi_pct_provisional`, is captured the moment the program's first production run reaches `PRODUCED`: it subtracts from `program_revenue_cents` the committed production cost — the sum of `total_cost_cents` over runs in `PRODUCED` status, deliberately excluding damage replacement actuals — divides that difference by the same committed cost, and multiplies by one hundred. The final variant, `roi_pct_final`, is computed at close on the full actuals: it subtracts from `program_revenue_cents` the final cost basis — produced runs' `total_cost_cents` plus fulfilled claims' `replacement_cost_cents` — divides by that same final cost, and multiplies by one hundred. For either variant, a cost basis of zero yields an ROI percentage of 0.0 rather than a division error. A `PlatformAdmin` or `ProgramManager` reads the recap back through the program's recap listing, which behaves like every other list endpoint and returns a paginated array: empty while the program is unclosed, and containing the single recap once the program is closed.

## 4. Endpoint Definitions

Operations that create a new resource — a client, program, compliance rule, design, production run, store, kit, shipment, damage claim, or field service request — return `201 Created`. Operations that modify an existing resource, including every lifecycle transition, return `200 OK`, as does the logical-clock capability. Readers should reconstruct each endpoint's request body and side effects from the narratives of §2 and §3; this table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/pop/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/pop/clients` | Create a client (brand/CPG) | PlatformAdmin |
| GET | `/pop/clients/{id}` | Get one client | PlatformAdmin, ProgramManager, Designer, ComplianceOfficer, ProductionPlanner, WarehouseOperator, LogisticsCoordinator, ClaimsAdjuster, FieldServiceManager |
| GET | `/pop/clients/{id}/programs` | List programs for a client | PlatformAdmin, ProgramManager |
| POST | `/pop/programs` | Create a retailer program under a client | ProgramManager |
| GET | `/pop/programs/{id}` | Get one program | PlatformAdmin, ProgramManager, Designer, ComplianceOfficer, ProductionPlanner, WarehouseOperator, LogisticsCoordinator, ClaimsAdjuster, FieldServiceManager |
| POST | `/pop/programs/{id}/start-design` | Move a program from DRAFT to DESIGN | ProgramManager |
| POST | `/pop/programs/{id}/authorize-production` | Move a program from DESIGN to PRODUCTION | ProgramManager |
| POST | `/pop/programs/{id}/start-fulfillment` | Move a program from PRODUCTION to FULFILLMENT | ProgramManager |
| POST | `/pop/programs/{id}/close` | Close a program and mint its recap | ProgramManager |
| POST | `/pop/programs/{id}/cancel` | Cancel a program in DRAFT or DESIGN | ProgramManager |
| POST | `/pop/programs/{id}/compliance-rules` | Add a compliance rule to a program | ComplianceOfficer |
| GET | `/pop/programs/{id}/compliance-rules` | List compliance rules for a program | PlatformAdmin, ProgramManager, ComplianceOfficer, Designer |
| POST | `/pop/designs` | Create a design in a program | Designer |
| GET | `/pop/designs/{id}` | Get one design | PlatformAdmin, ProgramManager, Designer, ComplianceOfficer, ProductionPlanner |
| GET | `/pop/programs/{id}/designs` | List designs for a program | PlatformAdmin, ProgramManager, Designer, ComplianceOfficer, ProductionPlanner |
| POST | `/pop/designs/{id}/submit` | Submit a design for review | Designer |
| POST | `/pop/designs/{id}/begin-review` | Begin compliance review of a design | ComplianceOfficer |
| POST | `/pop/designs/{id}/approve` | Approve a design (OCC-guarded) | ComplianceOfficer |
| POST | `/pop/designs/{id}/reject` | Reject a design in review | ComplianceOfficer |
| POST | `/pop/designs/{id}/revise` | Send a rejected design back to draft | Designer |
| POST | `/pop/designs/{id}/lock` | Lock an approved design referenced by a run | ProgramManager |
| POST | `/pop/production-runs` | Create a production run (OCC-guarded on program version) | ProductionPlanner |
| GET | `/pop/production-runs/{id}` | Get one production run | PlatformAdmin, ProgramManager, ProductionPlanner, WarehouseOperator |
| GET | `/pop/programs/{id}/production-runs` | List production runs for a program | PlatformAdmin, ProgramManager, ProductionPlanner |
| GET | `/pop/designs/{id}/production-runs` | List production runs referencing a design | PlatformAdmin, ProgramManager, ProductionPlanner |
| POST | `/pop/production-runs/{id}/authorize` | Authorize a run and compute its costing | ProductionPlanner |
| POST | `/pop/production-runs/{id}/mark-produced` | Mark a run produced and create one kit per store | ProductionPlanner |
| POST | `/pop/production-runs/{id}/cancel` | Cancel a planned run | ProductionPlanner |
| POST | `/pop/stores` | Create a store in a program | ProgramManager |
| GET | `/pop/stores/{id}` | Get one store | PlatformAdmin, ProgramManager, WarehouseOperator, LogisticsCoordinator, FieldServiceManager |
| GET | `/pop/programs/{id}/stores` | List stores for a program | PlatformAdmin, ProgramManager, WarehouseOperator, LogisticsCoordinator, FieldServiceManager |
| POST | `/pop/kits` | Create a kit manually for a run and store | WarehouseOperator |
| GET | `/pop/kits/{id}` | Get one kit | PlatformAdmin, ProgramManager, WarehouseOperator, LogisticsCoordinator, ClaimsAdjuster |
| GET | `/pop/production-runs/{id}/kits` | List kits for a run | PlatformAdmin, ProgramManager, WarehouseOperator, ProductionPlanner |
| GET | `/pop/stores/{id}/kits` | List kits for a store | PlatformAdmin, ProgramManager, WarehouseOperator, LogisticsCoordinator |
| POST | `/pop/kits/{id}/mark-kitted` | Mark a kit kitted | WarehouseOperator |
| POST | `/pop/shipments` | Create a shipment for a kit with a ship window | LogisticsCoordinator |
| GET | `/pop/shipments/{id}` | Get one shipment | PlatformAdmin, ProgramManager, LogisticsCoordinator, WarehouseOperator |
| GET | `/pop/kits/{id}/shipments` | List shipments for a kit | PlatformAdmin, ProgramManager, LogisticsCoordinator, WarehouseOperator |
| POST | `/pop/shipments/{id}/set-appointment` | Set the receiving appointment within the ship window | LogisticsCoordinator |
| POST | `/pop/shipments/{id}/ship` | Ship a shipment once its window opens | LogisticsCoordinator |
| POST | `/pop/shipments/{id}/deliver` | Confirm delivery within the grace period | LogisticsCoordinator |
| POST | `/pop/shipments/{id}/fail` | Fail a shipment in transit | LogisticsCoordinator |
| POST | `/pop/damage-claims` | Report damage on a kit | ClaimsAdjuster, WarehouseOperator |
| GET | `/pop/damage-claims/{id}` | Get one damage claim | PlatformAdmin, ProgramManager, ClaimsAdjuster, WarehouseOperator |
| GET | `/pop/kits/{id}/damage-claims` | List damage claims for a kit | PlatformAdmin, ProgramManager, ClaimsAdjuster, WarehouseOperator |
| POST | `/pop/damage-claims/{id}/approve` | Approve a claim and cost the replacement | ClaimsAdjuster |
| POST | `/pop/damage-claims/{id}/reject` | Reject a claim | ClaimsAdjuster |
| POST | `/pop/damage-claims/{id}/fulfill` | Fulfill an approved claim | WarehouseOperator |
| POST | `/pop/field-service-requests` | Open a field service request for a store | FieldServiceManager, ProgramManager |
| GET | `/pop/field-service-requests/{id}` | Get one field service request | PlatformAdmin, ProgramManager, FieldServiceManager |
| GET | `/pop/stores/{id}/field-service-requests` | List field service requests for a store | PlatformAdmin, ProgramManager, FieldServiceManager |
| GET | `/pop/programs/{id}/field-service-requests` | List field service requests for a program | PlatformAdmin, ProgramManager, FieldServiceManager |
| POST | `/pop/field-service-requests/{id}/dispatch` | Dispatch a field service request | FieldServiceManager |
| POST | `/pop/field-service-requests/{id}/resolve` | Resolve a dispatched field service request | FieldServiceManager |
| GET | `/pop/programs/{id}/recap` | Get the recap for a closed program | PlatformAdmin, ProgramManager |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows they guard in §2 and §3; this catalogue is a lookup of identifiers to statuses only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_COMPLIANCE_FAILED` | 422 |
| `ERR_DUPLICATE` | 409 |
| `ERR_WINDOW_VIOLATION` | 422 |
| `ERR_REFERENTIAL` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
