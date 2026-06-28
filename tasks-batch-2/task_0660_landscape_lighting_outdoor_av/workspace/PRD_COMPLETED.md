# Landscape Lighting & Outdoor AV API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Landscape Lighting & Outdoor AV platform, a back-office system that carries an outdoor-lighting project from first sketch to long-term service. A property's lighting is not an arbitrary collection of fixtures: every path light, spotlight, well light, and step light draws continuous power from a transformer whose usable capacity is a finite, derated budget. The platform's central discipline is therefore allocation — ensuring that the load committed across the zones a transformer feeds never overruns the power that transformer can safely deliver.

Around that allocation core, the system coordinates the rest of the trade. Designers lay out zones and fixtures, build priced quotes with optional night demonstrations, and lock a design once it is complete. Installers wire transformers and mount fixtures through a two-branch install job, decommission hardware, and run dated crew routes of service visits. Control programmers schedule lighting scenes within non-conflicting time windows and bring audio or security add-ons online. Customers accept quotes, prepay annual service plans, request seasonal visits, and file warranty claims when a fixture fails. An operations administrator registers customers, approves or denies warranty claims, closes finished projects, and drives the platform's logical clock.

Because money, power, and time all flow through interdependent records, the system favors immediate consistency: a single action frequently cascades across several resources — a warranty approval re-energizes a fixture and credits a wallet; an install completion energizes transformers and mounts every zoned fixture at once. The specifications below describe these cascades, the calculations that price and refund them, and the validation order that keeps them honest.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules and contracts that govern every endpoint. The business workflows in Section 3 assume everything described here.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly five roles: `LightingDesigner`, `InstallTech`, `ControlProgrammer`, `Customer`, and `OperationsAdmin`. If either header is absent or present but empty, or `X-User-Role` is not one of these five role names, the request is rejected with `ERR_UNAUTHENTICATED`. When a recognized role attempts an operation it is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`.

Four of the five roles are opaque operators. When `X-User-Role` is `LightingDesigner`, `InstallTech`, `ControlProgrammer`, or `OperationsAdmin`, the value of `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it where a workflow captures an operator handle (for example, an `InstallTech` may supply a `technician_id` when opening a crew route), but it is never compared against any entity's `id`. The `Customer` role is different: when `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity, and ownership checks on any resource that references a customer (for example, a project's `customer_id` or the customer a service plan and its claims ultimately belong to) compare that resource's customer reference to `X-User-ID`.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_` followed by twenty random alphanumeric characters.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, drawn from real wall-clock time (it is not the logical clock of §2.8).
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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it must fall between a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0; it must be a non-negative integer, and a negative offset is rejected as an invalid request. A `limit` outside the inclusive range of 1 to 100 — or a `limit` or `offset` that is not a parseable integer — is likewise rejected as an invalid request (`ERR_INVALID_REQUEST`).

Unless an endpoint states otherwise, list results are sorted by their `created_at` timestamp in ascending order. The list endpoint for projects additionally accepts an optional `customer_id` query parameter to restrict results to one customer.

Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` is the size of the full filtered result set and `has_more` is true exactly when `offset + limit < total_count`.

### 2.4. Common Resource Properties and Mutation Semantics

Every resource in the system is addressed by an `id`, a server-minted UUID (version 4, no type prefix). Every resource also records a `created_at` timestamp — an ISO 8601 UTC value with three fractional digits — fixed at creation. These `created_at`/`updated_at` audit timestamps are stamped from real wall-clock time, not from the logical clock of §2.8 (which governs only the business determinations §2.8 enumerates). All resources in this domain are mutable and therefore additionally carry an `updated_at` timestamp (same ISO 8601 UTC format), refreshed on every change, and a `version`, an integer that begins at 1 on creation and increments by one on every mutation. There are no immutable-after-creation resources here; `updated_at` and `version` are always present.

A "mutation" includes not only direct edits but also the recomputation of derived fields. When a fixture assignment changes a transformer's `committed_load_va`, or a state transition refreshes a project's parallel statuses, the affected resource's `updated_at` is refreshed and its `version` is incremented. This is the basis for the optimistic-concurrency protection described in §2.6: the `version` a client last read is the value it must echo back when the contract demands it. Most entities expose a single lifecycle enumeration in a `status` field whose permitted values are listed alongside each workflow in §3; the lone exception is the `LightingProject`, whose lifecycle is split across the two parallel fields `design_status` and `commercial_status` rather than a single `status`.

### 2.5. Capacity as a Finite Power Budget

The defining constraint of the platform is that a transformer's power is a finite pool. When a transformer is created with a nameplate `rated_capacity_va`, the system immediately derives its `usable_capacity_va` by taking eighty percent of the rated value and discarding any fractional VA — that is, multiplying `rated_capacity_va` by 0.80 and flooring the result to a whole number of VA. This derated figure, not the nameplate rating, is the continuous-load budget that the zones fed by the transformer may draw against.

Against that budget the system tracks `committed_load_va`, the exact integer sum of two contributions, taken with no rounding. The first contribution is the `wattage_w` of every fixture whose zone is fed by this transformer and whose status is either `PLANNED` or `INSTALLED`; fixtures that are `FAILED` or `REMOVED` are excluded. (One watt is treated as one VA for budgeting.) The second contribution is the `power_draw_va` of every add-on module whose `zone_id` is set to a zone fed by this transformer and whose status is `ACTIVE`; add-ons that are `PROPOSED` or `REMOVED`, and self-powered add-ons with no `zone_id`, contribute nothing. A `Zone` separately tracks its own `zone_load_va`, the sum of `wattage_w` over its `PLANNED` or `INSTALLED` fixtures. A project surfaces `total_committed_load_va`, the sum of `committed_load_va` across all transformers belonging to that project, and `fixture_count`, the count of fixtures on the project whose status is `PLANNED` or `INSTALLED`.

The budget is a hard ceiling at the moment load is added. Any operation that would push a transformer's post-action `committed_load_va` strictly above its `usable_capacity_va` is rejected with `ERR_TRANSFORMER_CAPACITY_EXCEEDED`; the boundary case where the resulting committed load lands exactly equal to the usable capacity is permitted. This ceiling guards two operations — assigning a fixture to a zone, and activating a zone-powered add-on — and the prose in §3 describes each in its workflow.

### 2.6. Optimistic Concurrency on Transformer Load

Assigning a fixture into a zone draws additional VA against that zone's transformer, and the system protects that draw with optimistic concurrency control on the transformer. A request to assign a planned fixture to a zone must include `expected_transformer_version`, carrying the `version` the client last observed on the zone's transformer. The server compares this value against the transformer's current `version`. If they match, the assignment proceeds (subject to the capacity gate) and the transformer's `version` is incremented by one. If they do not match — because another assignment or an add-on activation has already drawn load the client never saw — the request is rejected with `ERR_STALE_TRANSFORMER_VERSION` and an HTTP 412 status, forcing the client to re-read the transformer and retry against its current load. This `expected_transformer_version` field is required on the assign-zone operation; no other endpoint takes a version field, and no other endpoint performs an OCC check.

### 2.7. Monetary Precision and Rounding

All monetary amounts are integer cents and are stored and returned as integers. Where a calculation produces a fractional cent, the system applies one of two pinned rules depending on the step, and §3 states which rule applies where: volume discounts are floored (the fractional cent is discarded), while tax, service-plan refunds, and warranty replacement credits are rounded half up to the nearest whole cent. Load figures (`usable_capacity_va`, `committed_load_va`, `zone_load_va`) are whole VA; the usable capacity is floored as described in §2.5 and the committed sums are exact.

### 2.8. Time, Windows, and the Logical Clock

The platform runs on a logical clock rather than wall-clock time. On startup the clock reads exactly `2026-04-01T00:00:00Z`, and it never falls back to real time; until an administrator advances it, every read returns that default. All deadlines, expiries, proration, and warranty-age arithmetic consult this clock. An administrator can advance the clock to any instant by supplying the target value as `to_iso8601`.

Two distinct kinds of time window appear in the system, and they obey deliberately different adjacency rules. Both a schedule program and a service visit define a window as minutes after midnight, with `window_start_min` inclusive and `window_end_min` exclusive; in both cases `window_end_min` must be strictly greater than `window_start_min`, and a window failing that condition (or falling outside the valid minute range) is rejected with `ERR_INVALID_WINDOW`. Service-visit windows on a crew route use **half-open overlap**: two windows conflict only if they actually overlap, so windows that merely touch at a boundary (one ending exactly where the next begins) are compatible. Schedule-program windows on a project's controller use a stricter **closed-with-buffer** rule: a separation of at least `TRANSITION_BUFFER_MIN` minutes — five minutes — is required on both sides between the new window and any active program's window, so merely touching is not enough. The §3 narratives for routing and for scene activation spell out how each rule rejects a conflict.

### 2.9. Nested Resource Retrieval and Referential Integrity

Many reads are reached through a parent path — for instance, the zones fed by a transformer, the lines on a quote, or the visits on a route. When a path carries an identifier, the system resolves it before doing anything else; an identifier in a path or body that does not resolve to an existing resource yields `ERR_RESOURCE_NOT_FOUND`. When more than one identifier appears, they are validated left to right, and the first one that fails to resolve produces the not-found error before any later identifier or business rule is considered.

Beyond mere existence, several references must stay within a single project. A zone's `transformer_id` must point at a transformer belonging to the same project as the zone; a fixture's `zone_id` must point at a zone belonging to the fixture's own project; and a quote line must belong to a quote on the same project the actor is operating against. A reference that crosses a project boundary in any of these three ways is rejected with `ERR_CROSS_PROJECT_REFERENCE`. (One reference deliberately crosses the project boundary by design — a warranty claim names a fixture and is permitted to span the project edge — and is not subject to this rule.)

### 2.10. Validation Ordering

When several checks could apply to one request, they are evaluated in a fixed priority so that the rejection a client sees is deterministic. Authentication comes first: a missing or unknown-role credential (`ERR_UNAUTHENTICATED`) is detected before anything else, and role authorization (`ERR_FORBIDDEN_ROLE`) is checked next. Existence of every referenced identifier (`ERR_RESOURCE_NOT_FOUND`) is checked third. Request-shape validation comes fourth — required fields present, correct types, valid enum membership, and a pagination `limit` within 1 to 100, all surfaced as `ERR_INVALID_REQUEST`. Cross-project referential integrity (`ERR_CROSS_PROJECT_REFERENCE`) is checked fifth. The state-machine guard that the target is in a state from which the requested transition is defined (`ERR_INVALID_STATE`) is checked sixth, and the transformer OCC check (`ERR_STALE_TRANSFORMER_VERSION`) seventh. The remaining business rules — wiring-before-fixtures, unzoned-fixture lock, visit-window overlap, scene-window buffer, capacity ceiling, warranty age, window validity, demo-time presence, and email uniqueness — are evaluated after these foundational checks, each guarding the specific operations named in §3. Within this ordering, a foundational failure always masks a later business failure on the same request.

### 2.11. Parallel and Cyclic State, and Cascading Side Effects

A `LightingProject` carries two independent state dimensions that evolve separately: a `design_status` (one of `DRAFT`, `ZONED`, `DESIGN_LOCKED`) and a `commercial_status` (one of `PRE_QUOTE`, `QUOTED`, `ACCEPTED`, `INSTALLED`, `CLOSED`). A change along one dimension does not by itself move the other. Several entities cycle: a quote loops `DRAFT → SENT → DRAFT` across revisions, and a service plan loops `ACTIVE → ADJUSTING → ACTIVE` across seasons. Each such loop keeps a counter, described with its workflow in §3.

Many operations mutate more than one resource. The system performs every cascade synchronously and immediately, refreshing `updated_at` and incrementing `version` on each mutated resource as described in §2.4. The §3 workflows enumerate the secondary effects of each cascading operation — fixture-load recomputation rippling up to zone and transformer and project, wallet debits and credits, the install join that flips a project to `INSTALLED`, and the route completion that closes its visits — and the implementer must apply all of them, not merely the primary state change.

## 3. Business Logic & Workflows

### 3.1. Founding a Project: Customers, Transformers, and Zones

Work begins with a `Customer`, registered by an operations administrator with a `full_name` and an `email`. Email is unique across customers without regard to case; registering an address that already exists (ignoring case) is rejected with `ERR_DUPLICATE_EMAIL`. A new customer's `wallet_credit_cents` ledger starts at zero and is moved only by the debits and credits described later — quote acceptance and plan activation debit it, while plan refunds and warranty credits add to it. The ledger is an unbounded signed integer: a debit is never blocked or clamped for insufficient balance, so the balance may go negative.

A `LightingProject` is opened against a customer by a lighting designer (or an administrator), carrying the `customer_id` of the owning customer and the `property_address` of the site. A fresh project starts with `design_status` of `DRAFT` and `commercial_status` of `PRE_QUOTE`. Before any zone can exist, the designer stages the power hardware: each `Transformer` is created on the project with its `project_id`, a `model_code`, and a nameplate `rated_capacity_va` of at least one VA, whereupon the system derives the transformer's `usable_capacity_va` (per §2.5) and places it in `STAGED` status.

Zones come next. Creating the first `Zone` on a project advances its `design_status` from `DRAFT` to `ZONED` and increments the project's `version`. A zone is created under its project with a `transformer_id` naming the transformer that will feed it and a human `label` such as "Front Path". The named transformer must already exist and belong to the same project — the system requires at least one transformer on the project before the first zone may reference one — and a zone pointing at a transformer in another project is rejected for crossing the project boundary. Each zone tracks its own `zone_load_va`, initially zero.

### 3.2. Fixtures and the Load Budget

A `Fixture` is created on a project in `PLANNED` status and, by default, unassigned — its `zone_id` is null until a designer places it. Creation captures the fixture's `project_id`, its `model_code` (such as "PATH-3W" or "SPOT-9W"), its `category` (one of `PATH`, `SPOT`, `WELL`, `STEP`, `AUDIO`, `SECURITY`), its continuous `wattage_w` draw (a non-negative integer), its `purchase_price_cents` (a non-negative integer that later forms the basis of any warranty credit), and an optional `warranty_months` term that defaults to 60 months and must be at least one. Its `installed_at` timestamp is null while the fixture is `PLANNED`.

Placing a fixture is the platform's most carefully guarded write. Assigning a `PLANNED` fixture to a zone is a self-loop that leaves the fixture in `PLANNED` but sets its `zone_id`; it carries the target `zone_id` and the `expected_transformer_version` for the zone's transformer. Several conditions must all hold. The fixture must currently be `PLANNED`. The target zone must exist and belong to the same project as the fixture, or the request is rejected for a cross-project reference. The owning project must not be in `DESIGN_LOCKED` — once a design is locked, no further zone creation or fixture-to-zone reassignment is permitted while the project's commercial side has not yet reached `INSTALLED`. The transformer version supplied must match (per §2.6), or the assignment is stale. And the capacity gate must hold: adding this fixture's `wattage_w` must not push the zone's transformer's `committed_load_va` strictly above its `usable_capacity_va` — landing exactly at the usable figure is allowed, but exceeding it yields `ERR_TRANSFORMER_CAPACITY_EXCEEDED`. When all conditions pass, the fixture's `zone_id` is set, the zone's `zone_load_va` is recomputed upward by the fixture's wattage, the transformer's `committed_load_va` is recomputed, the project's `total_committed_load_va` is recomputed, and the target transformer's `version` is incremented by one.

### 3.3. Quoting, Revising, and Demonstrating

A designer drafts a `Quote` for a project. Creation records the `project_id`, an optional `night_demo_requested` flag (defaulting to false), and an optional `night_demo_at` scheduled timestamp. The night-demo time is mandatory whenever a demo is requested: if `night_demo_requested` is true but `night_demo_at` is missing, the create is rejected with `ERR_DEMO_TIME_REQUIRED`. Only the presence of `night_demo_at` is enforced; when supplied it is stored verbatim as a string and is not parsed or range-checked as a timestamp. A new quote sits in `DRAFT` with `revision_round` at zero and all computed money fields at zero.

Lines are added to a draft quote. Each `QuoteLine` records its `quote_id`, the `model_code` of the fixture or add-on being quoted, a `quantity` of at least one, and a `unit_price_cents` of at least zero; the system computes that line's `line_total_cents` as the quantity multiplied by the unit price. A line must belong to a quote on the project the designer is operating on, or it is rejected for crossing the project boundary.

Sending a quote moves it from `DRAFT` to `SENT` and recomputes its pricing first. A send requires that the quote is in `DRAFT`, that it has at least one line (a send with zero lines is rejected with `ERR_QUOTE_NO_LINES`), and that the owning project's design is locked — sending against a project whose `design_status` is not `DESIGN_LOCKED` is rejected with `ERR_DESIGN_NOT_LOCKED`. The very first send for a project is also the trigger that advances the project's `commercial_status` from `PRE_QUOTE` to `QUOTED` and increments the project's `version`. A sent quote is valid for fourteen days from that send; on any read of the quote, or on an attempt to send, revise, accept, or reject it, the system lazily checks the clock, and once the logical clock reaches or passes the instant exactly fourteen days after the last send (the boundary instant itself counting as expired) the quote transitions to `EXPIRED`. Acting on a quote that has expired this way is rejected with `ERR_QUOTE_EXPIRED` only on accept and reject; the lazy check also fires on send and revise but, since those require the `DRAFT` and `SENT` states respectively, an expired quote there surfaces `ERR_INVALID_STATE`.

The pricing computation runs in a pinned order — sum, then discount, then demo fee, then tax — and a reader must be able to reproduce it exactly. First, `subtotal_cents` is the sum over all of the quote's lines of each line's `line_total_cents`. Second, the system totals the fixture quantity across all lines and selects a volume-discount rate by that total: a combined quantity below 10 earns no discount; from 10 up to but not including 25 earns five percent; from 25 up to but not including 50 earns ten percent; and 50 or more earns fifteen percent (the breakpoints at 10, 25, and 50 fall into the higher tier). The `discount_cents` is that rate applied to the summed `subtotal_cents`, with the fractional cent floored away. Third, a demo fee is added if and only if the quote requested a night demo: when `night_demo_requested` is true the fee is 15000 cents, otherwise it is zero. The taxable base is the subtotal minus the discount plus the demo fee. Fourth, `tax_cents` is computed exactly once on that taxable base at a rate of 8.25 percent, rounded half up to a whole cent — never per line. Finally, `grand_total_cents` is the taxable base plus the tax. This `grand_total_cents` is the amount the customer commits to on acceptance.

A designer may cycle a quote for revision: returning a `SENT` quote to `DRAFT` increments its `revision_round` by one and reopens it so new lines can be added before re-sending. A customer acting on a sent quote either accepts or rejects it. Acceptance requires the quote to be `SENT` and the project to be `QUOTED`; it moves the quote to `ACCEPTED` (terminal), advances the project's `commercial_status` from `QUOTED` to `ACCEPTED` with a project `version` increment, and debits the customer's `wallet_credit_cents` by the quote's `grand_total_cents`. Rejection requires the quote to be `SENT` and moves it to `REJECTED` (terminal).

### 3.4. Locking the Design

Before a project can be quoted, its design must be locked. A designer locks the design of a project whose `design_status` is `ZONED`, advancing it to `DESIGN_LOCKED` and incrementing the project's `version`. The lock has a precondition that protects the load budget's integrity: every fixture on the project that is still `PLANNED` must have a non-null `zone_id`. If any planned fixture remains unzoned, the lock is rejected with `ERR_UNZONED_FIXTURE`. Once locked, the design is frozen — no new zones and no fixture-to-zone reassignments — until the commercial side has reached `INSTALLED`, as noted in §3.2.

### 3.5. Installation: Wiring, Mounting, and the Energize Join

An accepted quote authorizes installation. An installer creates an `InstallJob` carrying the `project_id` and the `quote_id` of the accepted quote; it begins `SCHEDULED` with both its `wiring_status` and `fixtures_status` at `PENDING`. Creation only requires that both referenced ids resolve to existing resources — it does not itself verify the quote is `ACCEPTED` nor that the quote and project share a project boundary; the accepted-quote requirement is enforced at start, below. Starting the job moves it from `SCHEDULED` to `IN_PROGRESS` and requires the referenced quote to be in `ACCEPTED`. A scheduled job may instead be cancelled, moving it to `CANCELLED` (terminal). The install proceeds as two branches that must both finish before the job energizes.

The wiring branch runs first. Completing wiring is allowed only while the job is `IN_PROGRESS` and `wiring_status` is `PENDING`; it sets `wiring_status` to `WIRED` and, as a cascade, energizes every transformer on the job's project that is currently `STAGED`, moving each from `STAGED` to `ENERGIZED`. The fixtures branch runs second and depends on the first: completing the fixtures branch is allowed only while the job is `IN_PROGRESS` and `fixtures_status` is `PENDING`, and it additionally requires that `wiring_status` already be `WIRED`, since fixtures may only be mounted onto energized wiring. An attempt to complete fixtures before wiring is complete is rejected with `ERR_WIRING_NOT_COMPLETE`. Completing fixtures sets `fixtures_status` to `MOUNTED` and, as a cascade, transitions every fixture on the project that is `PLANNED` and has a non-null `zone_id` from `PLANNED` to `INSTALLED`, stamping each fixture's `installed_at` from the logical clock.

When both branches have completed — `wiring_status` is `WIRED` and `fixtures_status` is `MOUNTED` — the join fires: the install job moves from `IN_PROGRESS` to `ENERGIZED` (terminal), and as a cascade the project's `commercial_status` advances from `ACCEPTED` to `INSTALLED` (with the usual project `version` increment). Reaching `INSTALLED` is the gate that later unlocks service plans, schedule programs, and add-on activation.

### 3.6. Decommissioning Transformers and Removing Fixtures

An installer may remove an `INSTALLED` fixture, moving it to `REMOVED` (terminal); the removal recomputes the zone's `zone_load_va` downward and the transformer's `committed_load_va` downward by that fixture's wattage, since a `REMOVED` fixture no longer counts toward the budget. An installer may also decommission a transformer that is `ENERGIZED`, moving it to `DECOMMISSIONED` (terminal) — but only when no zone fed by that transformer still has a fixture in `PLANNED` or `INSTALLED` status. A decommission attempted on a transformer that is not `ENERGIZED`, or while a zone it feeds still holds a planned or installed fixture, is rejected with `ERR_TRANSFORMER_NOT_ENERGIZED`.

### 3.7. Smart-Control Scenes

Once a project is installed, a control programmer authors lighting scenes as schedule programs. A `ScheduleProgram` is created with its `project_id`, a `scene_label` such as "Evening Warm" or "Security Flash", and a `window_start_min`/`window_end_min` pair defining when the scene runs (minutes after midnight, start inclusive and end exclusive, end strictly greater than start, both within the valid 0-to-1440 minute span). It begins in `DRAFT`. Activating a program moves it from `DRAFT` to `ACTIVE` and is permitted only when the owning project's `commercial_status` is `INSTALLED`; activating against a project that is not installed is rejected with `ERR_PROJECT_NOT_INSTALLED`. Activation also enforces the buffered window rule of §2.8: the new program's window must be separated by at least five minutes on both sides from the window of any other program on the same project that is already `ACTIVE`. If any active program's window sits within five minutes of this one — including the case where the windows merely touch — activation is rejected with `ERR_SCENE_WINDOW_TOO_CLOSE`. An active program may later be disabled, moving it from `ACTIVE` to `DISABLED` (terminal).

### 3.8. Audio and Security Add-Ons

A control programmer or designer proposes an `AddOnModule` for a project, recording its `project_id`, its `kind` (either `AUDIO` or `SECURITY`), its `power_draw_va` (a non-negative integer), and an optional `zone_id`. When `zone_id` is set, the add-on draws its power from that zone's transformer; when it is null the module is self-powered and draws nothing from any transformer budget. A new module sits in `PROPOSED`.

A control programmer activates a proposed module, moving it from `PROPOSED` to `ACTIVE`, but only when the owning project's `commercial_status` is `INSTALLED` (otherwise `ERR_PROJECT_NOT_INSTALLED`). If the module is zone-powered, activation is also subject to the same capacity ceiling as fixture assignment: bringing the module online must not push the zone's transformer's `committed_load_va` strictly above its `usable_capacity_va`, with the exact-equal boundary allowed and any overage rejected with `ERR_TRANSFORMER_CAPACITY_EXCEEDED`. On activation of a zone-powered module, the transformer's `committed_load_va` is recomputed to include this module's `power_draw_va`. Removing an active module moves it from `ACTIVE` to `REMOVED` (terminal); if it was zone-powered, the transformer's `committed_load_va` is recomputed downward by its `power_draw_va`.

### 3.9. Service Plans and the Seasonal Loop

A service plan is sold against an installed project. A `ServicePlan` is created (by a customer or an administrator) with its `project_id`, a `tier` of either `BASIC` or `PREMIUM`, a prepaid `annual_fee_cents` (a non-negative integer), and an optional `refundable` flag that defaults to false. It begins `PENDING` with its `season_cycle_count` at zero and its `activated_at` null. A customer activates the plan, moving it from `PENDING` to `ACTIVE`, which is allowed only when the project's `commercial_status` is `INSTALLED` (otherwise `ERR_PROJECT_NOT_INSTALLED`); activation stamps `activated_at` from the logical clock and debits the customer's `wallet_credit_cents` by the `annual_fee_cents`.

While active, a plan goes through seasonal adjustments driven by an installer. Beginning a seasonal adjustment moves the plan from `ACTIVE` to `ADJUSTING`; completing one moves it back from `ADJUSTING` to `ACTIVE` and increments `season_cycle_count` by one — this is the cyclic seasonal loop.

A customer may cancel an active plan, moving it from `ACTIVE` to `CANCELLED` (terminal) and crediting the customer's `wallet_credit_cents` by a refund computed in one of two variants. The system first measures elapsed time as the number of whole days between the plan's `activated_at` and the current clock (the difference floored to whole days), and the unused remainder as 365 minus the elapsed days, never less than zero. If the plan's `refundable` flag is true, or the elapsed days are at most the 30-day grace period (`REFUND_GRACE_DAYS`), the refund is **PRORATED**: the `annual_fee_cents` multiplied by the unused days, divided by 365, rounded half up to a whole cent. Otherwise — the plan is not refundable and more than 30 days have elapsed — the refund is **FORFEIT** and equals zero, the whole prepaid fee being given up.

### 3.10. Service Visits and Crew Routes

A customer or installer requests a `ServiceVisit` under a plan, supplying the `service_plan_id`, the `project_id` for project-scoped listing, a `visit_date` as a YYYY-MM-DD calendar date, and a requested arrival window as `window_start_min`/`window_end_min` (minutes after midnight, end exclusive and strictly greater than start, within the valid minute range; a bad window yields `ERR_INVALID_WINDOW`). Requesting a visit only requires that the `service_plan_id` and `project_id` both resolve to existing resources; it imposes no precondition on the plan's status (a visit may be requested against a plan in any status) and does not check that the plan and project share a project. A visit begins `REQUESTED` with its `route_id` null. If the logical clock's date moves past a visit's `visit_date` while the visit is still `REQUESTED` and unrouted, the visit lazily transitions to `MISSED` (terminal); this is evaluated when the visit is read.

Installers organize visits onto a `CrewRoute`, created for a given crew with a `technician_id` (the opaque operator handle) and a `route_date` as a YYYY-MM-DD calendar date; it opens in `OPEN` with `visit_count` zero. Adding a requested visit to a route identifies the visit to sequence by its `visit_id` in the request body and sequences it: the route must be `OPEN`, the visit must be `REQUESTED`, and the visit's `visit_date` must equal the route's `route_date` — a mismatch is rejected with `ERR_ROUTE_DATE_MISMATCH`. The route's date-matching aside, the visit's window must not overlap any already-`ROUTED` visit's window on the same route, applying the half-open overlap rule of §2.8: windows that merely touch at a boundary are fine, but any genuine overlap is rejected with `ERR_VISIT_WINDOW_OVERLAP`. A successful add sets the visit's `route_id` to the route, moves the visit from `REQUESTED` to `ROUTED`, and recomputes the route's `visit_count` (the count of visits on the route whose status is `ROUTED` or `COMPLETED`).

A route is dispatched only from `OPEN` to `DISPATCHED`, and only once at least one visit on it is `ROUTED`. Completing a dispatched route moves it from `DISPATCHED` to `COMPLETED` (terminal) and, as a cascade, transitions every visit on the route that is still `ROUTED` to `COMPLETED`.

### 3.11. Warranty Claims and Replacement Credit

When an installed fixture fails, a customer files a `WarrantyClaim`. Submission records the `fixture_id` of the failed fixture, the `project_id` it belongs to, and a free-text `reason`; the claim opens in `SUBMITTED`. Submitting a claim requires the fixture to be `INSTALLED`, and as a cascade it immediately moves that fixture from `INSTALLED` to `FAILED`, which drops the fixture out of the load set: the zone's `zone_load_va` and the transformer's `committed_load_va` are recomputed downward by the fixture's wattage. A claim notably may reference a fixture across the project boundary and is not subject to the cross-project rule. The claim's `credit_variant` is null and its `credit_cents` zero until it is resolved.

An operations administrator resolves a submitted claim by either denying or approving it. Denial moves the claim from `SUBMITTED` to `DENIED` (terminal); the fixture stays `FAILED` and no credit is granted. Approval is gated on warranty age. The system computes the fixture's age in months as the number of whole 30-day months between the fixture's `installed_at` and the current clock (the elapsed time divided by 30 days and floored). If that age is at least the fixture's `warranty_months`, the fixture is out of warranty and approval is rejected with `ERR_OUT_OF_WARRANTY` — the boundary where age equals the warranty term is itself out and rejected. Otherwise the approval proceeds: it moves the claim from `SUBMITTED` to `APPROVED`, computes the replacement credit and its variant, credits the customer's `wallet_credit_cents` by that credit, and re-energizes the fixture by moving it from `FAILED` back to `INSTALLED`, re-stamping its `installed_at` from the clock and recomputing the zone's `zone_load_va` and the transformer's `committed_load_va` upward by the fixture's wattage.

The replacement credit comes in two variants keyed off the same floored age in months. When the age is at most the 12-month full-coverage window (`FULL_WINDOW_MONTHS`), the variant is **FULL** and the `credit_cents` equals the fixture's full `purchase_price_cents`. When the age is greater than 12 months but still strictly less than the warranty term — the only other case the gate permits, which guarantees at least one remaining month — the variant is **DEPRECIATED**: the system computes the remaining months as the warranty term minus the age, and the `credit_cents` is the `purchase_price_cents` multiplied by those remaining months, divided by the `warranty_months` term, rounded half up to a whole cent. The chosen variant is recorded in `credit_variant` as either `FULL` or `DEPRECIATED`.

### 3.12. Closing a Project

An operations administrator closes a project whose `commercial_status` is `INSTALLED`, advancing it to `CLOSED` (terminal) and incrementing the project's `version`. A project cannot be closed while it still carries an obligation: if any service plan on the project is in `PENDING` or `ADJUSTING`, the close is rejected with `ERR_PLAN_BLOCKS_CLOSE`. Closing is the terminal commercial state of the project lifecycle.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify or transition an existing resource, including the test-clock control, return `200 OK`. Every endpoint requires the authentication headers of §2.1 and is subject to the validation ordering of §2.10; refer back to the §3 narratives for each operation's request body, preconditions, and cascading side effects.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Register a customer | OperationsAdmin |
| GET | `/customers/{id}` | Read a customer including wallet credit | OperationsAdmin, Customer |
| POST | `/projects` | Create a lighting project | LightingDesigner, OperationsAdmin |
| GET | `/projects/{id}` | Read a project including computed load fields | LightingDesigner, InstallTech, ControlProgrammer, Customer, OperationsAdmin |
| GET | `/projects` | List projects, filterable by customer | OperationsAdmin, LightingDesigner |
| POST | `/projects/{id}/lock-design` | Lock the design | LightingDesigner |
| POST | `/projects/{id}/close` | Close an installed project | OperationsAdmin |
| POST | `/transformers` | Create a transformer for a project | LightingDesigner |
| GET | `/transformers/{id}` | Read a transformer including capacity, committed load, version | LightingDesigner, InstallTech, OperationsAdmin |
| GET | `/projects/{id}/transformers` | List transformers for a project | LightingDesigner, InstallTech, OperationsAdmin |
| GET | `/transformers/{id}/zones` | List zones fed by a transformer | LightingDesigner, InstallTech, OperationsAdmin |
| POST | `/transformers/{id}/decommission` | Decommission a transformer | InstallTech |
| POST | `/projects/{id}/zones` | Create a zone under a project | LightingDesigner |
| GET | `/zones/{id}` | Read a zone including zone load | LightingDesigner, InstallTech, OperationsAdmin |
| GET | `/projects/{id}/zones` | List zones for a project | LightingDesigner, InstallTech, OperationsAdmin |
| GET | `/zones/{id}/fixtures` | List fixtures assigned to a zone | LightingDesigner, InstallTech, OperationsAdmin |
| POST | `/fixtures` | Create a planned fixture | LightingDesigner |
| GET | `/fixtures/{id}` | Read a fixture | LightingDesigner, InstallTech, Customer, OperationsAdmin |
| GET | `/projects/{id}/fixtures` | List fixtures for a project | LightingDesigner, InstallTech, Customer, OperationsAdmin |
| POST | `/fixtures/{id}/assign-zone` | Assign a planned fixture to a zone | LightingDesigner |
| POST | `/fixtures/{id}/remove` | Remove an installed fixture | InstallTech |
| POST | `/quotes` | Create a draft quote for a project | LightingDesigner |
| GET | `/quotes/{id}` | Read a quote including computed pricing | LightingDesigner, Customer, OperationsAdmin |
| GET | `/projects/{id}/quotes` | List quotes for a project | LightingDesigner, Customer, OperationsAdmin |
| POST | `/quotes/{id}/lines` | Add a line to a draft quote | LightingDesigner |
| GET | `/quotes/{id}/lines` | List a quote's lines | LightingDesigner, Customer, OperationsAdmin |
| POST | `/quotes/{id}/send` | Send a draft quote | LightingDesigner |
| POST | `/quotes/{id}/revise` | Return a sent quote to draft | LightingDesigner |
| POST | `/quotes/{id}/accept` | Accept a sent quote | Customer |
| POST | `/quotes/{id}/reject` | Reject a sent quote | Customer |
| POST | `/install-jobs` | Create an install job against an accepted quote | InstallTech |
| GET | `/install-jobs/{id}` | Read an install job | InstallTech, LightingDesigner, OperationsAdmin |
| GET | `/projects/{id}/install-jobs` | List install jobs for a project | InstallTech, LightingDesigner, OperationsAdmin |
| GET | `/quotes/{id}/install-jobs` | List install jobs authorized by a quote | InstallTech, LightingDesigner, OperationsAdmin |
| POST | `/install-jobs/{id}/start` | Start an install job | InstallTech |
| POST | `/install-jobs/{id}/complete-wiring` | Complete the wiring branch | InstallTech |
| POST | `/install-jobs/{id}/complete-fixtures` | Complete the fixtures branch | InstallTech |
| POST | `/install-jobs/{id}/cancel` | Cancel a scheduled install job | InstallTech |
| POST | `/schedule-programs` | Create a draft schedule program | ControlProgrammer |
| GET | `/schedule-programs/{id}` | Read a schedule program | ControlProgrammer, OperationsAdmin |
| GET | `/projects/{id}/schedule-programs` | List schedule programs for a project | ControlProgrammer, OperationsAdmin |
| POST | `/schedule-programs/{id}/activate` | Activate a program | ControlProgrammer |
| POST | `/schedule-programs/{id}/disable` | Disable an active program | ControlProgrammer |
| POST | `/service-plans` | Create a pending service plan | OperationsAdmin, Customer |
| GET | `/service-plans/{id}` | Read a service plan | OperationsAdmin, Customer, InstallTech |
| GET | `/projects/{id}/service-plans` | List service plans for a project | OperationsAdmin, Customer, InstallTech |
| POST | `/service-plans/{id}/activate` | Activate a plan | Customer |
| POST | `/service-plans/{id}/begin-seasonal-adjustment` | Begin a seasonal adjustment | InstallTech |
| POST | `/service-plans/{id}/complete-seasonal-adjustment` | Complete a seasonal adjustment | InstallTech |
| POST | `/service-plans/{id}/cancel` | Cancel an active plan | Customer |
| POST | `/service-visits` | Request a service visit under a plan | Customer, InstallTech |
| GET | `/service-visits/{id}` | Read a service visit | Customer, InstallTech, OperationsAdmin |
| GET | `/service-plans/{id}/service-visits` | List visits under a plan | Customer, InstallTech, OperationsAdmin |
| GET | `/projects/{id}/service-visits` | List visits for a project | Customer, InstallTech, OperationsAdmin |
| POST | `/crew-routes` | Create an open crew route | InstallTech |
| GET | `/crew-routes/{id}` | Read a crew route including visit count | InstallTech, OperationsAdmin |
| GET | `/crew-routes/{id}/visits` | List visits sequenced on a route | InstallTech, OperationsAdmin |
| POST | `/crew-routes/{id}/add-visit` | Add a requested visit to an open route | InstallTech |
| POST | `/crew-routes/{id}/dispatch` | Dispatch a route | InstallTech |
| POST | `/crew-routes/{id}/complete` | Complete a dispatched route | InstallTech |
| POST | `/warranty-claims` | Submit a warranty claim against an installed fixture | Customer |
| GET | `/warranty-claims/{id}` | Read a warranty claim including credit fields | Customer, OperationsAdmin |
| GET | `/projects/{id}/warranty-claims` | List warranty claims for a project | Customer, OperationsAdmin |
| GET | `/fixtures/{id}/warranty-claims` | List warranty claims against a fixture | Customer, OperationsAdmin |
| POST | `/warranty-claims/{id}/approve` | Approve a claim, credit customer, re-energize fixture | OperationsAdmin |
| POST | `/warranty-claims/{id}/deny` | Deny a claim | OperationsAdmin |
| POST | `/add-ons` | Propose an audio/security add-on module | ControlProgrammer, LightingDesigner |
| GET | `/add-ons/{id}` | Read an add-on module | ControlProgrammer, LightingDesigner, OperationsAdmin |
| GET | `/projects/{id}/add-ons` | List add-ons for a project | ControlProgrammer, LightingDesigner, OperationsAdmin |
| GET | `/zones/{id}/add-ons` | List add-ons powered by a zone | ControlProgrammer, LightingDesigner, OperationsAdmin |
| POST | `/add-ons/{id}/activate` | Activate an add-on | ControlProgrammer |
| POST | `/add-ons/{id}/remove` | Remove an active add-on | ControlProgrammer |
| POST | `/_clock/set_current_utc` | Set the logical clock | OperationsAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_CROSS_PROJECT_REFERENCE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_TRANSFORMER_VERSION` | 412 |
| `ERR_WIRING_NOT_COMPLETE` | 409 |
| `ERR_UNZONED_FIXTURE` | 409 |
| `ERR_VISIT_WINDOW_OVERLAP` | 409 |
| `ERR_SCENE_WINDOW_TOO_CLOSE` | 409 |
| `ERR_TRANSFORMER_CAPACITY_EXCEEDED` | 409 |
| `ERR_OUT_OF_WARRANTY` | 409 |
| `ERR_INVALID_WINDOW` | 400 |
| `ERR_DEMO_TIME_REQUIRED` | 400 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_TRANSFORMER_NOT_ENERGIZED` | 409 |
| `ERR_QUOTE_NO_LINES` | 409 |
| `ERR_DESIGN_NOT_LOCKED` | 409 |
| `ERR_PROJECT_NOT_INSTALLED` | 409 |
| `ERR_QUOTE_EXPIRED` | 409 |
| `ERR_ROUTE_DATE_MISMATCH` | 409 |
| `ERR_PLAN_BLOCKS_CLOSE` | 409 |
