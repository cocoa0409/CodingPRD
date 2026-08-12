# Machine Rebuild & Retrofit Services API — Product Requirements Document

## 1. Introduction

Capital-equipment owners face a recurring dilemma: production machine tools age, positioning accuracy drifts, control generations fall behind, yet outright replacement is expensive and slow. A machine-tool rebuilder answers that dilemma with a disciplined engagement model — assess the as-found condition of the machine, decide between a control retrofit and a mechanical rebuild, source or reverse-engineer the spare parts, execute the work inside tightly planned customer downtime windows, prove the rebuilt accuracy with a geometric acceptance test, train the operators, and stand behind the result with a warranty on rebuilt accuracy. This document specifies the API that runs that engagement end to end.

The system governs the full commercial and technical lifecycle: customer onboarding and machine registration, as-found condition assessment with a computed wear index, the retrofit-versus-rebuild decision, tiered quotation with trade-in credit, spare-part sourcing under obsolescence (including reverse-engineering jobs with segregated fabrication and validation), downtime-window booking and staged shipment planning, acceptance testing with rework and escalation handling, operator training and documentation, delivery into warranty, drift-based warranty claims, and residual-value trade-in offers. All endpoints are mounted under `/api`. Time-dependent behavior is driven by an explicit logical clock rather than wall-clock time, and a segregation-of-duties role model separates the people who perform work from the people who verify it.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply across the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes exactly nine roles, spelled as follows: `Customer`, `Assessor`, `ProjectManager`, `RebuildEngineer`, `QualityInspector`, `Trainer`, `LogisticsCoordinator`, `WarrantyAdministrator`, and `PlatformAdmin`. A request missing either header, or carrying a role name outside this declared set, is rejected with `ERR_MISSING_HEADERS` (HTTP 401). A request whose role is not permitted for the target endpoint, or that fails an entity-backed ownership check, is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). Separately, the segregation-of-duties rules described below reject with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

Role identity is bound to `X-User-ID` in two different ways. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting Customer record; ownership checks on any resource that references a customer compare the resource's customer foreign key — `customer_id` on a machine, downtime window, or trade-in offer, and the denormalized `customer_id` carried on a rebuild project — to `X-User-ID`.

The remaining eight roles carry opaque operator identifiers not tied to any persisted entity, and the server never compares them to any entity's `id`. When `X-User-Role` is `Assessor`, `X-User-ID` is recorded as the `assessor_id` of each assessment that operator creates, and later writes on that record (such as submission) compare against it. When `X-User-Role` is `RebuildEngineer`, `X-User-ID` may be recorded as a project's `assigned_engineer_id` at decision time or as a reverse-engineering job's `fabricated_by_id` at fabrication time, and identity-bound writes compare against those fields. When `X-User-Role` is `QualityInspector`, `X-User-ID` is recorded as an acceptance test's `inspector_id` or a reverse-engineering job's `validated_by_id`. When `X-User-Role` is `Trainer`, `X-User-ID` is recorded as a training record's `trainer_id`. When `X-User-Role` is `ProjectManager`, `LogisticsCoordinator`, `WarrantyAdministrator`, or `PlatformAdmin`, `X-User-ID` is an opaque identifier that authorizes the action but is not pinned to any persisted record.

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

### 2.3. Pagination

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is bounded below by 1 and above by 100. The `offset` parameter states how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. Paginated list responses carry the fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the response envelope.

### 2.4. Common Resource Properties and Mutation Semantics

Every resource in the system — Customer, Machine, Assessment, RebuildProject, Part, ProjectPartLine, ReverseEngineeringJob, DowntimeWindow, ShipmentStage, AcceptanceTest, TrainingRecord, WarrantyClaim, and TradeInOffer — carries a standard set of system-managed properties:

- **`id`** (string): a unique, server-minted UUID with no type prefix.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- **`version`** (integer): a system-managed integer that increments by one on every mutation of the resource.

Mutation is defined broadly. A client-driven write, a state transition, a recomputation of a derived field, and a system-driven cascade all count as mutations: each independently refreshes `updated_at` and increments `version` on every resource it touches. When one operation mutates several resources — for example, a cascade that moves a project, its part lines, and a part's reservation counters together — each affected resource is updated individually.

### 2.5. Money, Microns, and Rounding Discipline

All monetary amounts are represented as integer numbers of cents; there are no fractional cents anywhere in the system. Rounding is always the round-half-up method, applied only at explicitly pinned rounding points: each part line's total is rounded half-up to a whole cent when the line is created; the volume discount is rounded half-up to a whole cent when a quote is computed; the two trade-in valuations are rounded half-up to whole cents when an offer is created; and each rework surcharge is rounded half-up to a whole cent when it is applied. Monetary values appear in API response bodies as numbers, never as strings.

Geometric measurements are expressed in microns. Computed micron quantities — the assessment wear index, an acceptance test's largest absolute sample, the acceptance statistic, and a warranty claim's drift — are rounded half-up to exactly 2 decimal places. Raw input measurements (such as the as-found readings or the five acceptance samples) are stored as supplied, subject to their validation ranges.

### 2.6. Optimistic Concurrency Control

Three write endpoints are protected by optimistic concurrency control against a parent entity's `version`; no other endpoint accepts a version field.

- Creating an assessment via `POST /api/machines/{id}/assessments` requires the request body to carry `expected_machine_version` equal to the target machine's current `version`. If another write has advanced the machine's version since the client last observed it, the create is rejected with `ERR_STALE_MACHINE_VERSION` (HTTP 412). This protection exists because assessment creation legitimately supersedes the machine's prior non-terminal assessment and increments `Machine.version`, so a second create carrying a previously observed version is working from a stale view of the machine.
- Creating a trade-in offer via `POST /api/machines/{id}/trade-in-offers` likewise requires `expected_machine_version` matching the machine's current `version`, with a mismatch rejected as `ERR_STALE_MACHINE_VERSION` (HTTP 412), because offer creation supersedes the machine's prior `OFFERED` offer and increments `Machine.version`.
- Recomputing a quote via `POST /api/projects/{id}/quote` requires `expected_project_version` matching the project's current `version`. Each recomputation produces a new quote revision that supersedes the prior one and increments `RebuildProject.version`; a recompute carrying a previously observed version is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412), preventing the client from overwriting a quote it has not observed.

Endpoints not listed above do not take a version field, and the version check is never optional on the three that do: the expected-version field is a non-optional input on each.

### 2.7. The Logical Clock and Scheduled Sweeps

All time-dependent rules in the system read a server-maintained logical clock, never the host's wall clock. At startup, before any operator intervention, the logical clock reads exactly `2026-05-01T00:00:00Z`, and the server must not fall back to wall-clock time under any circumstances. A `PlatformAdmin` may advance the logical clock to a supplied `to_iso8601` instant through an admin-only test-driving capability; the response reports the resulting `current_utc` value.

Advancing the clock triggers two sweeps. First, every downtime window whose `ends_at` lies strictly before the new clock instant — whether the window is `OPEN` or `LOCKED` — is swept to `CLOSED`. Second, every rebuild project in `WARRANTY_ACTIVE` whose `warranty_end` lies strictly before the new clock instant is swept to `CLOSED`, unless a warranty claim of that project is currently `FILED` or `APPROVED`, in which case the project remains under warranty administration. A window or project sitting exactly at its boundary instant is not swept; the clock must pass it strictly. Trade-in offers are never swept: offer expiry is evaluated lazily at acceptance time, as described in §3.9.

### 2.8. Validation Gates and Their Priority Order

Every request passes through a fixed cascade of validation gates, evaluated in the order below. When several gates would fail, the earliest failing gate's error is the one reported, so higher-priority failures are never masked by lower-priority ones.

1. **Header presence.** `X-User-ID` and `X-User-Role` are present and the role is one of the nine declared names; otherwise `ERR_MISSING_HEADERS` (HTTP 401). Applies to every endpoint.
2. **Role authorization, ownership, and segregation of duties.** The role is permitted for the endpoint, entity-backed ownership holds (a `Customer` caller matches the resource's customer; an `Assessor`, `QualityInspector`, `Trainer`, or `RebuildEngineer` caller matches the record's assigned opaque identifier), and the segregation-of-duties rules hold (the acceptance inspector is not the project's `assigned_engineer_id`; the reverse-engineering validator is not the job's `fabricated_by_id`); otherwise `ERR_UNAUTHORIZED_ROLE` or `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Applies to every endpoint.
3. **Request body shape.** Required fields are present, enum members are valid, and numeric ranges are respected — a `quantity` greater than zero, micron readings at least zero, exactly five acceptance samples; duplicate submissions of unique fields such as `serial_number` or `part_number` also fail here; otherwise `ERR_INVALID_REQUEST` (HTTP 400). Applies to every endpoint with a body.
4. **Identifier existence.** Path identifiers exist, validated left to right, and body-referenced identifiers (`part_id`, `window_id`, `offer_id`) exist; otherwise `ERR_NOT_FOUND` (HTTP 404).
5. **Optimistic concurrency.** `expected_machine_version` matches the machine's `version` on assessment and trade-in-offer creation, and `expected_project_version` matches the project's `version` on quote recomputation; otherwise `ERR_STALE_MACHINE_VERSION` or `ERR_STALE_PROJECT_VERSION` (HTTP 412).
6. **Target state.** The target entity is in the state the action requires per its state machine; otherwise one of `ERR_INVALID_STATE`, `ERR_PROJECT_NOT_IN_WARRANTY`, `ERR_COMMERCIAL_NOT_APPROVED`, `ERR_QUOTE_REQUIRED`, or `ERR_PROJECT_NOT_AWAITING_ACCEPTANCE` (HTTP 409).
7. **Referential compatibility.** Referenced and child entities are in compatible states: the quote is not stale for sending or approving, no `SCHEDULED` acceptance test is open when another is created, a referenced part is not `SUPERSEDED`, a trade-in offer belongs to the project's customer and is unapplied, and the referenced window is still open or locked on stage creation; otherwise `ERR_QUOTE_STALE`, `ERR_OPEN_ACCEPTANCE_TEST`, `ERR_PART_SUPERSEDED`, `ERR_TRADE_IN_NOT_APPLICABLE`, or `ERR_TRADE_IN_ALREADY_APPLIED` (HTTP 409).
8. **Temporal admissibility.** Clock-driven gates: a claim is filed no later than `warranty_end`, an offer is accepted no later than `expires_at`, and a window's `ends_at` is strictly after its `starts_at`; otherwise `ERR_WARRANTY_EXPIRED`, `ERR_TRADE_IN_OFFER_EXPIRED`, or `ERR_WINDOW_EMPTY` (HTTP 409).
9. **Structural constraints.** Window overlap, stage containment and the sibling gap, one open claim per project, accuracy drift beyond tolerance on `ACCURACY_DRIFT` filings (examined only after the temporal gate has passed), stages installed before delivery, training complete before handover, decision-override justification, and session-log overflow; otherwise one of `ERR_WINDOW_OVERLAP`, `ERR_STAGE_OUTSIDE_WINDOW`, `ERR_STAGE_GAP_TOO_SMALL`, `ERR_CLAIM_ALREADY_OPEN`, `ERR_DRIFT_WITHIN_TOLERANCE`, `ERR_STAGES_NOT_INSTALLED`, `ERR_DECISION_OVERRIDE_NEEDS_REASON`, or `ERR_TRAINING_SESSION_OVERFLOW` (HTTP 409).
10. **Stock and money.** A part's `available_quantity` suffices at sourcing time and the quote price sits within the customer's credit limit at approval; otherwise `ERR_INSUFFICIENT_STOCK` or `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 409).

The ordering has observable consequences: a stale version surfaces as a 412 before any state-machine complaint; a claim filed after the warranty has lapsed reports `ERR_WARRANTY_EXPIRED` before its drift magnitude is ever examined; and the credit-limit check at quote approval is the last gate, so every state and referential problem surfaces first.

### 2.9. Spare-Part Stock Conservation

The part ledger obeys a strict conservation law: for every Part, `available_quantity` plus `reserved_quantity` always equals `stock_quantity`. Reserving a line increases `reserved_quantity` by the line's `quantity` (so `available_quantity` recomputes downward). Fulfilling a reserved line decreases both `reserved_quantity` and `stock_quantity` by the line's `quantity`, preserving the invariant as physical stock leaves the shelf. Releasing a reservation — through a line cancellation or a project-level cancellation cascade — decreases `reserved_quantity` alone (so `available_quantity` recomputes upward). Any reservation that would drive a part's `available_quantity` negative is rejected with `ERR_INSUFFICIENT_STOCK`.

### 2.10. Quote Composition and Trade-In Credit Conservation

A rebuild project's commercial terms are pinned by its most recent quote computation. The project counts its computations in `quote_revision` — zero means no quote has ever been computed — and snapshots the results into `base_price_cents`, `parts_total_cents`, `labor_cents`, `discount_cents`, `applied_trade_in_credit_cents`, and `quote_price_cents`, each defaulting to 0 before the first computation. Whenever the set of part lines changes after a quote has been computed, the project raises `quote_stale` (a boolean, initially `false`) to warn that the snapshot no longer reflects the current lines; sending or approving a stale quote is refused. A conservation law ties the snapshot together: `quote_price_cents` plus `applied_trade_in_credit_cents` always equals `base_price_cents` plus `parts_total_cents` plus `labor_cents` minus `discount_cents`. Applying or revoking a trade-in credit moves value between `quote_price_cents` and `applied_trade_in_credit_cents` only; the gross quote on the right-hand side is left unchanged by that pair of operations.

### 2.11. Nested Resource Retrieval

Requests that target nested resources validate path identifiers sequentially, left to right, and reject immediately with a 404 `ERR_NOT_FOUND` naming the first identifier that does not correspond to an existing resource. A request aimed beneath a non-existent machine or project therefore fails on the parent before the child is ever examined. Identifiers referenced inside a request body — `part_id` on a part line, `window_id` on a shipment stage, `offer_id` on a credit application — are checked for existence after the path identifiers have all resolved.

## 3. Business Logic & Workflows

### 3.1. Customer Onboarding and Machine Registration

A `PlatformAdmin` onboards a customer by creating a Customer record with a company `name`, a `credit_limit_cents` ceiling — the maximum approved quote total the customer may commit to, which must be at least zero — and an optional free-form `region` label.

Machines join the fleet through registration by a `Customer` or a `PlatformAdmin`. Registration records the owning `customer_id`, the OEM `serial_number` (unique across all machines; a duplicate submission is rejected with `ERR_INVALID_REQUEST`), the `machine_type` — one of `LATHE`, `MILL`, or `GRINDER` — the `year_of_manufacture` (a four-digit year between 1950 and 2026 inclusive, later feeding the age term of residual valuation), the as-found `control_generation` (`LEGACY` or `MODERN`), and the recorded `spindle_hours` (at least zero). A newly registered machine is born in `REGISTERED` status.

From there the machine's `status` walks a fixed path: `REGISTERED` to `UNDER_ASSESSMENT` when its first assessment is created, `UNDER_ASSESSMENT` to `ASSESSED` when one of its assessments is accepted, `ASSESSED` to `IN_PROJECT` when its rebuild project opens parts sourcing, and `IN_PROJECT` to the terminal `RETURNED` when the project is delivered. A machine may instead leave the fleet early: accepting a trade-in offer for a `REGISTERED` machine moves it to the terminal `TRADED_IN`. Machines can be listed with an optional `customer_id` filter, alongside the standard `limit` and `offset` parameters.

### 3.2. As-Found Assessment and the Wear Index

An `Assessor` captures the as-found condition of a machine by filing an assessment against it, supplying three geometric readings — `positioning_deviation_microns`, `spindle_runout_microns`, and `backlash_microns`, each at least zero — plus free-text `scope_notes` describing the scope of work. Because filing an assessment supersedes the machine's prior assessment and advances the machine's version, the filing must carry `expected_machine_version` per §2.6; a stale value is rejected with `ERR_STALE_MACHINE_VERSION`. The server records the filing operator's identifier as `assessor_id`, computes the `wear_index` and `recommended_path` described below, and stamps the machine relationship onto the new record as `machine_id` taken from the creation path.

Two system side effects accompany every filing. First, any prior assessment of the same machine sitting in `DRAFT`, `SUBMITTED`, or `RETURNED` is moved to the terminal `SUPERSEDED`, so at most one non-terminal assessment exists per machine at a time. Second, the machine's `version` increments by one; on the very first filing for a machine, the machine additionally transitions from `REGISTERED` to `UNDER_ASSESSMENT` — subsequent filings leave the machine's `status` untouched while still bumping its version.

The `wear_index` is a weighted wear score on a 0.00–150.00 scale. The positioning deviation is divided by a 20.0-micron reference and given half the total weight; the spindle runout is divided by a 10.0-micron reference and given three-tenths of the weight; the backlash is divided by a 15.0-micron reference and given one-fifth of the weight. The three weighted terms are summed, and the raw sum is capped at 1.5 — a raw score above the cap is replaced by the cap itself. The capped value is multiplied by 100 and rounded half-up to two decimal places to produce the stored `wear_index`. The `recommended_path` then falls out of fixed thresholds with inclusive boundaries: a `wear_index` of at least 80.00 yields `FULL_REBUILD`; otherwise a `wear_index` of at least 40.00 yields `MECHANICAL_REBUILD`; anything lower yields `RETROFIT_ONLY`.

An assessment is born in `DRAFT`. Its `status` advances to `SUBMITTED` when the recording assessor submits it — the caller's `X-User-ID` must equal the record's `assessor_id`, failing which the submission is rejected with `ERR_UNAUTHORIZED_ROLE`. A `ProjectManager` reviews a submitted assessment and either returns it for rework, moving it to `RETURNED`, or accepts it. A returned assessment may be resubmitted by its assessor, re-entering `SUBMITTED`, and this submit–return cycle may repeat. Acceptance is guarded by the machine's position in its own lifecycle: the machine must still be `UNDER_ASSESSMENT`, otherwise the acceptance fails with `ERR_INVALID_STATE`. Acceptance moves the assessment to the terminal `ACCEPTED`, moves the machine to `ASSESSED`, and — critically — auto-creates the RebuildProject that will carry the engagement: the project is born with `work_status` of `SCOPED`, `commercial_status` of `QUOTE_DRAFT`, `decision` of `NONE`, and its `assessment_id`, `machine_id`, and `customer_id` all linked from the accepted assessment and its machine. The new project's bookkeeping starts clean: `quote_revision` at 0, `quote_stale` at `false`, the six quote money fields at 0, `rework_count`, `consecutive_fail_count`, `rework_cost_cents`, and `escalation_count` all at 0, and `accepted_positioning_microns`, `delivery_date`, and `warranty_end` null until they are earned later in the lifecycle. Assessments can be listed with an optional `machine_id` filter.

### 3.3. The Rebuild Decision and the Commercial Quote

A project cannot leave `SCOPED` until a `ProjectManager` records the control-retrofit-versus-mechanical-rebuild decision. The decision write carries a `decision` of `RETROFIT_ONLY`, `MECHANICAL_REBUILD`, or `FULL_REBUILD` together with the `assigned_engineer_id` of the `RebuildEngineer` who will run the work, and it moves `work_status` from `SCOPED` to `DECIDED`. When the chosen `decision` differs from the accepted assessment's `recommended_path`, a non-empty `decision_reason` is mandatory; omitting the justification on an override is rejected with `ERR_DECISION_OVERRIDE_NEEDS_REASON`, while a matching decision needs no reason. Recording the decision also fixes two downstream classes: the warranty class — 6 months for `RETROFIT_ONLY`, 12 for `MECHANICAL_REBUILD`, 24 for `FULL_REBUILD` — and the operator-training class of one, two, or three required sessions respectively.

With the decision recorded, the commercial machinery engages. A `ProjectManager` may compute — and later recompute — the project's quote, but only while `work_status` is `DECIDED`; attempting a computation in any other work state is rejected with `ERR_INVALID_STATE`. Recomputation is an OCC-protected write per §2.6: the request must carry `expected_project_version` matching the project's current `version`, and a stale value is rejected with `ERR_STALE_PROJECT_VERSION`.

Quote computation follows a pinned evaluation order. First, `parts_total_cents` is formed by summing the `line_total_cents` of every part line of the project whose `status` is not `CANCELLED`; each line's total was already rounded half-up to a whole cent when the line was created, and the quote sums those pinned per-line amounts rather than re-rounding the aggregate. Second, the labor charge is formed: the labor hours are the decision-class configured base-hour allowance plus the greatest whole number not exceeding the accepted assessment's `wear_index`, and `labor_cents` is those hours billed at 14,500 cents — that is, $145.00 — per labor hour. Third, `base_price_cents` is taken from the configured per-decision-class base price. Fourth, the subtotal is the sum of `base_price_cents`, `parts_total_cents`, and `labor_cents`. Fifth, the volume discount is computed on that subtotal with inclusive tier boundaries: a subtotal of at least 100,000,000 cents ($1,000,000) earns a discount of five percent of the subtotal; otherwise a subtotal of at least 50,000,000 cents ($500,000) earns two percent; otherwise there is no discount — and whatever percentage applies, the `discount_cents` result is rounded half-up to a whole cent. Sixth and last, `quote_price_cents` is the subtotal minus `discount_cents` minus the currently `applied_trade_in_credit_cents`; the trade-in credit is always subtracted last.

Every computation increments `quote_revision` by one, clears `quote_stale` to `false`, snapshots all six money fields, and increments the project's `version` by one. If the project's `commercial_status` was `QUOTE_SENT` at the moment of recomputation — a renegotiation — the commercial dimension reverts to `QUOTE_DRAFT`, leaving `work_status` untouched.

Sending the quote to the customer requires that at least one computation exists (`quote_revision` of zero is rejected with `ERR_QUOTE_REQUIRED`) and that the snapshot is current (`quote_stale` must be `false`, else `ERR_QUOTE_STALE`); a successful send moves `commercial_status` from `QUOTE_DRAFT` to `QUOTE_SENT`. Approval is then the customer's act: the caller's `X-User-ID` must equal the project's `customer_id`, the quote must still be unstale (again `ERR_QUOTE_STALE`), and — as the final fiscal gate of the validation cascade — `quote_price_cents` must not exceed the customer's `credit_limit_cents`, failing which the approval is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`. Approval moves `commercial_status` from `QUOTE_SENT` to `APPROVED`, which is the commercial precondition for opening parts sourcing in §3.4. The commercial dimension runs in parallel with the work dimension: quote sends, approvals, and renegotiation reverts never move `work_status`, and work transitions never move `commercial_status`.

While `work_status` is `SCOPED`, `DECIDED`, or `PARTS_SOURCING`, a `ProjectManager` may also cancel the project outright, moving it to the terminal `CANCELLED`: any reserved stock is released, reverse-engineering jobs of lines awaiting fabrication are cancelled, and any not-yet-shipping stages are cancelled, mirroring the escalation-cancellation cascade of §3.6. A project carrying an `ACCEPTED` trade-in offer may also have that credit applied to — or revoked from — its quote via `offer_id`, as detailed in §3.9. Projects can be listed with optional `machine_id`, `customer_id`, and `assessment_id` filters.

### 3.4. Parts Sourcing, Obsolescence, and Reverse Engineering

The spare-part catalog is maintained by a `PlatformAdmin`. Each Part record carries the OEM `part_number` (unique; duplicates are rejected with `ERR_INVALID_REQUEST`), a human-readable `description`, an `oem_status` of `ACTIVE`, `OBSOLETE`, or `SUPERSEDED`, an optional `superseded_by_id` pointing at the replacement part when the part is `SUPERSEDED` (null otherwise), a strictly positive `unit_cost_cents`, a non-negative `stock_quantity` of physical units on the shelf, and a non-negative `lead_time_days` procurement lead time. The reservation counters start clean: `reserved_quantity` begins at 0 and `available_quantity` — always computed as `stock_quantity` minus `reserved_quantity` per the conservation law of §2.9 — initially equals `stock_quantity`. Parts can be listed with an optional `superseded_by_id` filter to trace obsolescence chains.

A `ProjectManager` builds the bill of materials by adding part lines to a project, which is permitted only while the project is `DECIDED`. Each line references a `part_id` and a `quantity` greater than zero. Referencing a part whose `oem_status` is `SUPERSEDED` is rejected with `ERR_PART_SUPERSEDED` — the replacement must be ordered instead. At creation the line snapshots its commercial terms: `unit_price_cents` is pinned to the part's current `unit_cost_cents`, `obs_multiplier` is pinned to 1.8 when the part is `OBSOLETE` at that moment and 1.0 otherwise, and `line_total_cents` is pinned to the quantity times the pinned unit price times the pinned multiplier, rounded half-up to a whole cent. This per-line rounding is the quote's pinned first step, so later price movements on the catalog never rewrite an existing line. The new line is born `PENDING`, and if the project has already computed at least one quote, adding the line raises `quote_stale` to `true`. Part lines can be listed with optional `project_id` and `part_id` filters.

Opening parts sourcing is the pivotal move from `DECIDED` to `PARTS_SOURCING`, performed by a `ProjectManager`, and it enforces its gates in order. The commercial dimension must already be `APPROVED`, otherwise the attempt fails with `ERR_COMMERCIAL_NOT_APPROVED`. At least one part line must exist, otherwise `ERR_LINES_OUTSTANDING`. Then comes the stock gate: for every `PENDING` line on an `ACTIVE` part, examined in ascending order of line creation, the part's `available_quantity` must cover the line's `quantity`; the first line that fails aborts the entire operation with `ERR_INSUFFICIENT_STOCK` and no reservations whatsoever are applied — the check is atomic. When all gates pass, every `PENDING` line on an `ACTIVE` part becomes `RESERVED` and the part's `reserved_quantity` grows by each line's `quantity`; every `PENDING` line on an `OBSOLETE` part instead becomes `RE_PENDING` and the system auto-creates a ReverseEngineeringJob in `REQUESTED` for that line; and the machine under rebuild moves from `ASSESSED` to `IN_PROJECT`.

A reverse-engineering job denormalizes its context onto itself — `part_line_id`, `project_id`, and `part_id` are all copied from the line that spawned it — starts with its `revision_count` at 0 and `validated_by_id` null, and walks a fabrication lifecycle. A `RebuildEngineer` first captures the reverse-engineering specification, moving the job from `REQUESTED` to `SPEC_CAPTURED`. Fabrication follows: the engineer records the actual `re_cost_cents` (at least zero) and the server pins `fabricated_by_id` to the caller's `X-User-ID` as the job moves to `PROTOTYPE_FABRICATED`. Validation belongs to a `QualityInspector` and is segregated: the validator's `X-User-ID` must differ from the job's `fabricated_by_id`, and a self-validation attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`. A passing validation moves the job to the terminal `VALIDATED`, records `validated_by_id`, and flips the parent part line from `RE_PENDING` to `RE_FULFILLED`. A failed validation — under the same segregation rule — cycles the job back from `PROTOTYPE_FABRICATED` to `SPEC_CAPTURED` and increments its `revision_count` by one. Jobs are cancelled to the terminal `CANCELLED` only by the project-level cascades (project cancellation, escalation-cancellation, or trade-in acceptance). Reverse-engineering jobs can be listed with optional `part_line_id`, `project_id`, and `part_id` filters.

Physical issuance is a `LogisticsCoordinator` duty: fulfilling a `RESERVED` line moves it to the terminal `FULFILLED` and applies the conservation ledger — the part's `reserved_quantity` and `stock_quantity` both decrease by the line's `quantity`, leaving `available_quantity` unchanged by the act of issuance itself. A `ProjectManager` may cancel a line instead: a `PENDING` line may be cancelled only while the project is `DECIDED` (and doing so raises `quote_stale`), while a `RESERVED` line may be cancelled while the project is `DECIDED` or `PARTS_SOURCING` (which additionally releases the reservation, decreasing the part's `reserved_quantity` by the line's `quantity`). `CANCELLED` is terminal for a line in either case.

Once every line of the project sits in `FULFILLED`, `RE_FULFILLED`, or `CANCELLED`, a `ProjectManager` may start the physical rebuild; if any line is still `PENDING`, `RESERVED`, or `RE_PENDING`, the attempt fails with `ERR_LINES_OUTSTANDING`. Starting the rebuild moves `work_status` from `PARTS_SOURCING` to `REBUILD_IN_PROGRESS`.

### 3.5. Downtime Windows and Staged Shipment

Customers plan production downtime ahead of the rebuild. A `Customer` or a `LogisticsCoordinator` books a DowntimeWindow with a `customer_id`, a `starts_at` instant (inclusive), and an `ends_at` instant (exclusive) — the window is the half-open interval from `starts_at` up to but not including `ends_at`. An `ends_at` that is not strictly after `starts_at`, including a zero-length window, is rejected with `ERR_WINDOW_EMPTY`. The new window must also not overlap any other window of the same customer whose `status` is `OPEN` or `LOCKED`: under half-open semantics, two intervals overlap when each starts strictly before the other ends, and any such overlap is rejected with `ERR_WINDOW_OVERLAP`; mere adjacency — one window's `starts_at` exactly equal to the other's `ends_at`, or vice versa — is permitted. A window is born `OPEN`. The first shipment stage that references it locks it, moving it to `LOCKED`, which is a one-way ratchet: a `LOCKED` window can no longer be cancelled, while an `OPEN` window may be cancelled to `CANCELLED` by its customer or a logistics coordinator (attempting to cancel a window that is not `OPEN` fails with `ERR_INVALID_STATE`). Independently of any operator action, the clock sweep of §2.7 closes `OPEN` and `LOCKED` windows to `CLOSED` once the logical clock passes `ends_at`. Windows can be listed with an optional `customer_id` filter.

Staged shipments are planned by a `LogisticsCoordinator`, who creates a ShipmentStage on a project by referencing a `window_id` and supplying a positive integer `stage_sequence` ordering the stage within the project, a `planned_ship_date` (the inclusive lower bound of the stage interval), and a `planned_return_date` (the inclusive upper bound — the planned return-to-service instant). The referenced window must still be `OPEN` or `LOCKED` — planning into a `CLOSED` or `CANCELLED` window is rejected with `ERR_INVALID_STATE`. A `planned_return_date` earlier than the `planned_ship_date` is a malformed request, rejected with `ERR_INVALID_REQUEST`. Containment is then checked with closed bounds on both ends: the window's `starts_at` must be at or before the `planned_ship_date`, and the `planned_return_date` must be at or before the window's `ends_at`; any breach is rejected with `ERR_STAGE_OUTSIDE_WINDOW`. Finally, the sibling-gap rule keeps staged shipments apart: against every other non-`CANCELLED` stage of the same project, either this stage's `planned_ship_date` must be at least two full days after that sibling's `planned_return_date`, or the sibling's `planned_ship_date` must be at least two full days after this stage's `planned_return_date`. A gap of exactly two days is allowed; a gap one day shorter is rejected with `ERR_STAGE_GAP_TOO_SMALL`. A stage is born `PLANNED`, and its creation is the act that locks its window. Stages can be listed with optional `project_id` and `window_id` filters.

Logistics execution proceeds once the project is past acceptance. Shipping a stage — `PLANNED` to `SHIPPED` — is permitted only while the project's `work_status` is `ACCEPTED`, `TRAINING_IN_PROGRESS`, or `HANDOVER_READY`; shipping at any other time fails with `ERR_INVALID_STATE`. Receipt at the customer site moves `SHIPPED` to `RECEIVED`, and installation moves `RECEIVED` to the terminal `INSTALLED`. Two cascades can interrupt this path: when the project falls into `REWORK` or `ESCALATED` (§3.6), every `PLANNED` stage of the project is parked `ON_HOLD`; and when the project is cancelled, every stage in `PLANNED` or `ON_HOLD` moves to the terminal `CANCELLED`. A parked stage is recovered by replanning: a `LogisticsCoordinator` supplies a fresh `planned_ship_date` and `planned_return_date`, the containment and two-day sibling-gap checks are revalidated against the new interval, and the stage returns from `ON_HOLD` to `PLANNED`; the same replanning capability may also be used to update the dates of a stage still in `PLANNED`.

### 3.6. Acceptance Testing, Rework, and Escalation

When the assigned `RebuildEngineer` judges the machine ready, they declare readiness, moving `work_status` to `AWAITING_ACCEPTANCE` — from `REBUILD_IN_PROGRESS` on the first pass, or from `REWORK` on each rework cycle. The caller's `X-User-ID` must equal the project's `assigned_engineer_id`, otherwise the declaration is rejected with `ERR_UNAUTHORIZED_ROLE`.

Geometric acceptance is measured by a `QualityInspector`, who schedules an AcceptanceTest on the project. Scheduling requires the project to be `AWAITING_ACCEPTANCE` (otherwise `ERR_PROJECT_NOT_AWAITING_ACCEPTANCE`), requires that no other test of the same project is still `SCHEDULED` (otherwise `ERR_OPEN_ACCEPTANCE_TEST`), and is segregated from the rebuild work: the scheduling inspector must not be the project's `assigned_engineer_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`). The server records the caller as `inspector_id` and computes `attempt_number` as one plus the count of prior tests for the project. The new test is born `SCHEDULED`, and tests can be listed with an optional `project_id` filter.

Recording the result belongs to the same inspector who scheduled the test — the caller's `X-User-ID` must equal the record's `inspector_id`. The inspector supplies `samples_microns`, exactly five signed positioning-deviation samples in microns (any other count is rejected with `ERR_INVALID_REQUEST`), and a non-negative `repeatability_microns` reading. The server first derives `max_abs_sample_microns`, the largest absolute value among the five samples, rounded half-up to two decimal places. It then selects the `evaluation_variant` from the project's `decision` and computes `statistic_value` accordingly, with both branches specified in full. Under `WORST_CASE` — chosen when the decision is `RETROFIT_ONLY` or `MECHANICAL_REBUILD` — the `statistic_value` is simply the `max_abs_sample_microns`; the distribution shape is ignored. Under `ISO_STATISTICAL` — chosen when the decision is `FULL_REBUILD` — the mean of the five samples is computed, then the population standard deviation (the square root of the average squared deviation from that mean, dividing by the sample count of five, not four), and the `statistic_value` is the absolute value of the mean plus two times that standard deviation, rounded half-up to two decimal places; this branch is the stricter one for dispersed samples. The verdict uses inclusive boundaries on both checks: the test passes only when the `statistic_value` is at most 20.0 microns and the `repeatability_microns` is at most 10.0 microns; breaching either tolerance fails the test.

A passing recording moves the test to the terminal `PASSED` and fires the acceptance cascade on the project: `work_status` moves from `AWAITING_ACCEPTANCE` to `ACCEPTED`, `consecutive_fail_count` resets to zero, the project's `accepted_positioning_microns` — null until this moment — is set to the passing test's `max_abs_sample_microns`, and a TrainingRecord is auto-created in `PLANNED` with its `sessions_required` derived from the decision class.

A failing recording moves the test to the terminal `FAILED` and fires the rework cascade. In both outcomes below, the project's `rework_count` increases by one, its `rework_cost_cents` accumulates a surcharge of five percent of the current `quote_price_cents` rounded half-up to a whole cent — the quote price itself is never recomputed by rework, the surcharge accumulates separately — and every `PLANNED` ShipmentStage of the project is parked `ON_HOLD`. The destination depends on the failure streak: the project's `consecutive_fail_count` increases by one, and if that brought the streak below three the project falls back to `REWORK`, from which the engineer may again declare readiness; if the streak thereby reaches exactly three, the project instead falls to `ESCALATED` with `consecutive_fail_count` standing at three.

Escalation is resolved by a `ProjectManager` through an `action` input with two sibling resolutions, each fully specified. A `RETRY` resolution moves the project from `ESCALATED` back to `AWAITING_ACCEPTANCE`, resets `consecutive_fail_count` to zero, increments `escalation_count` by one, and accumulates a steeper surcharge of ten percent of the current `quote_price_cents` rounded half-up to a whole cent into `rework_cost_cents`. A `CANCEL` resolution moves the project to the terminal `CANCELLED` and runs the release cascade: reserved stock of `RESERVED` lines is released, reverse-engineering jobs of `RE_PENDING` lines are cancelled, and stages in `PLANNED` or `ON_HOLD` are cancelled.

### 3.7. Operator Training and Handover

Acceptance of the rebuilt machine triggers a bubble-up: the system auto-creates a TrainingRecord for the project in `PLANNED`, with `sessions_completed` at 0, `documentation_delivered` at `false`, and `sessions_required` fixed by the decision class — one session for `RETROFIT_ONLY`, two for `MECHANICAL_REBUILD`, three for `FULL_REBUILD`.

A `ProjectManager` begins training by assigning the trainer: the begin-training write requires that the project's TrainingRecord exists (it always does by then, having been auto-created at acceptance), pins the supplied `trainer_id` onto the record, and moves `work_status` from `ACCEPTED` to `TRAINING_IN_PROGRESS`.

Sessions are logged by the assigned `Trainer` — the caller's `X-User-ID` must equal the record's `trainer_id`, otherwise the log is rejected with `ERR_UNAUTHORIZED_ROLE`. Each logged session increments `sessions_completed` by one, and the very first logged session moves the record from `PLANNED` to `IN_PROGRESS`. Logging is bounded: when `sessions_completed` has already reached `sessions_required`, a further log attempt is rejected with `ERR_TRAINING_SESSION_OVERFLOW`. Documentation is handed over by the same trainer through a deliver-documentation write, which sets `documentation_delivered` to `true`. Completion is re-evaluated after every session log and every documentation delivery: once `sessions_completed` has reached `sessions_required` and `documentation_delivered` is `true`, the record moves to the terminal `COMPLETED`, and the project bubbles from `TRAINING_IN_PROGRESS` to `HANDOVER_READY`. Because every project requires at least one session, a record in practice always completes from `IN_PROGRESS`. Training records can be listed with an optional `project_id` filter.

### 3.8. Delivery, Warranty, and Claims

Delivery is the `ProjectManager`'s final scheduling act and is permitted only from `HANDOVER_READY`. Every ShipmentStage of the project must by then be `INSTALLED` or `CANCELLED`; any stage in any other state blocks delivery with `ERR_STAGES_NOT_INSTALLED`. Delivery stamps `delivery_date` from the logical clock, computes `warranty_end` as `delivery_date` plus `warranty_months` calendar months landing on the same day-of-month — where `warranty_months` is 6 for `RETROFIT_ONLY`, 12 for `MECHANICAL_REBUILD`, and 24 for `FULL_REBUILD` per the decision — moves the machine from `IN_PROJECT` to the terminal `RETURNED`, and moves `work_status` to `WARRANTY_ACTIVE`. Both `delivery_date` and `warranty_end` are null until this moment.

Warranty closure is clock-driven: per the sweep of §2.7, a `WARRANTY_ACTIVE` project whose `warranty_end` is strictly passed closes to the terminal `CLOSED`, provided no claim of the project is open as `FILED` or `APPROVED`.

While a project is `WARRANTY_ACTIVE`, its `Customer` may file a WarrantyClaim with a `claim_type` of `ACCURACY_DRIFT` or `MECHANICAL_DEFECT`. Filing against a project in any other state is rejected with `ERR_PROJECT_NOT_IN_WARRANTY`, and only one claim may be open at a time — filing while another claim of the same project is `FILED` or `APPROVED` is rejected with `ERR_CLAIM_ALREADY_OPEN`. An `ACCURACY_DRIFT` filing must carry a non-negative `measured_positioning_microns` reading; omitting it is a malformed request rejected with `ERR_INVALID_REQUEST`. The server stamps `filed_at` from the logical clock at filing.

An accuracy-drift claim faces two gates in a fixed order — the temporal gate first, then the drift gate, so an expired warranty surfaces before the drift magnitude is ever examined. The temporal gate requires the filing clock to be no later than the project's `warranty_end`; filing strictly after the end is rejected with `ERR_WARRANTY_EXPIRED`, while filing at exactly the end instant remains admissible. The drift gate then computes `drift_microns` as the filed `measured_positioning_microns` minus the project's `accepted_positioning_microns`, rounded half-up to two decimal places, and admits the claim only when the drift strictly exceeds 15.0 microns — a drift of exactly 15.0 is within tolerance and is rejected with `ERR_DRIFT_WITHIN_TOLERANCE`. A `MECHANICAL_DEFECT` claim carries no drift evaluation at all: its `drift_microns` is null.

Adjudication belongs to a `WarrantyAdministrator`. A filed claim may be approved, moving `FILED` to `APPROVED`, or rejected, moving `FILED` to the terminal `REJECTED`; an approved claim is later closed by a remediate write, moving `APPROVED` to the terminal `CLOSED`. All three adjudication writes accept optional `resolution_notes`. Claims can be listed with an optional `project_id` filter.

### 3.9. Trade-In Valuation and Credit

A `ProjectManager` may raise a TradeInOffer on any machine of a customer — the machine need not be, and typically is not, a project machine. Creation pins the `valuation_variant` to `MARKET_COMPARABLE` or `COST_APPROACH` for the life of the offer and, per §2.6, must carry `expected_machine_version` matching the machine's current `version`; a stale value is rejected with `ERR_STALE_MACHINE_VERSION`. Creation always computes and stores both valuations — `market_value_cents` and `cost_value_cents` — regardless of variant, and then pins `residual_value_cents` to the market value when the variant is `MARKET_COMPARABLE` and to the cost value when it is `COST_APPROACH`. The offer's `expires_at` is set to its `created_at` plus thirty days on the logical clock. Creation also supersedes the machine's prior offer: any existing `OFFERED` offer of the same machine moves to the terminal `SUPERSEDED`, and the machine's `version` increments by one. Offers can be listed with optional `machine_id`, `customer_id`, and `applied_project_id` filters.

Both valuation branches share two inputs. The machine's age is the calendar-year difference between the current year on the logical clock and the `year_of_manufacture`. The condition factor draws on the machine's most recently created assessment, whatever its `status`: it is the larger of 0.25 and one minus that assessment's `wear_index` divided by 200.0, and when the machine has no assessment at all the factor defaults to 0.50.

The `MARKET_COMPARABLE` branch compounds depreciation: the configured market base for the `machine_type` is scaled down by twelve percent per year of age — that is, multiplied once per year of age by 0.88 — then multiplied by the condition factor, and the result is rounded half-up to a whole cent to become `market_value_cents`. The `COST_APPROACH` branch works from replacement economics: the remaining-life fraction is the larger of zero and the quotient of 25 minus the age over 25; the estimated rebuild cost is the configured per-decision-class base price of the latest assessment's `recommended_path`, defaulting to the `MECHANICAL_REBUILD` class when no assessment exists; and `cost_value_cents` is the larger of a scrap floor of 2,000,000 cents ($20,000) and the replacement cost configured for the `machine_type` times the remaining-life fraction minus that estimated rebuild cost, rounded half-up to a whole cent.

Acceptance is the customer's act: the caller's `X-User-ID` must equal the offer's `customer_id`, and the offer must still be `OFFERED`. Expiry is evaluated lazily inside the acceptance attempt — offers are never swept. If the logical clock has passed `expires_at`, the offer flips to the terminal `EXPIRED` and the attempt fails with `ERR_TRADE_IN_OFFER_EXPIRED`; acceptance at exactly the `expires_at` instant still succeeds. A successful acceptance moves the offer to the terminal `ACCEPTED` and fires the trade-in cascade. First, the machine moves from `REGISTERED` to the terminal `TRADED_IN`. Second, every RebuildProject of that machine whose `work_status` is `SCOPED`, `DECIDED`, or `PARTS_SOURCING` is moved to `CANCELLED`. Third, on each such cancelled project, every part line in `PENDING`, `RESERVED`, or `RE_PENDING` moves to `CANCELLED`; the reservation of each `RESERVED` line is released, decreasing the part's `reserved_quantity` by the line's `quantity`; and the reverse-engineering jobs of `RE_PENDING` lines move to `CANCELLED`. A customer may instead decline an `OFFERED` offer — again with `X-User-ID` matching the offer's `customer_id` — moving it to the terminal `DECLINED`.

An accepted offer becomes spendable credit. A `ProjectManager` applies it to a project's quote by passing the `offer_id`: the offer must be `ACCEPTED`, must belong to the same customer as the project, and must not already be applied to another project — any breach is rejected with `ERR_TRADE_IN_NOT_APPLICABLE` — and the project must not already carry an applied credit, otherwise `ERR_TRADE_IN_ALREADY_APPLIED`. Applying sets the project's `applied_trade_in_credit_cents` to the offer's `residual_value_cents`, reduces `quote_price_cents` by that same amount, and stamps the offer's `applied_project_id` with the project. Revoking — the mechanism for backing a credit out before the customer approves the quote — requires a credit to be present, failing which `ERR_TRADE_IN_ALREADY_APPLIED` is returned; it restores `quote_price_cents` by adding the applied amount back, zeroes `applied_trade_in_credit_cents`, and clears the offer's `applied_project_id`. Per the conservation law of §2.10, the apply/revoke pair never alters the gross quote: `quote_price_cents` plus `applied_trade_in_credit_cents` always equals `base_price_cents` plus `parts_total_cents` plus `labor_cents` minus `discount_cents`.

## 4. Endpoint Definitions

Operations that create a new resource — a customer, machine, assessment, part line, acceptance test, shipment stage, downtime window, warranty claim, trade-in offer, or part master — return `201 Created`. Operations that modify or transition an existing resource return `200 OK`, as do all reads. The request and response details of each operation are governed by the narratives of §2 and §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/customers` | Create a customer | PlatformAdmin |
| GET | `/api/customers/{id}` | Get a customer | PlatformAdmin, ProjectManager, Customer |
| POST | `/api/machines` | Register an as-found machine | Customer, PlatformAdmin |
| GET | `/api/machines/{id}` | Get a machine | Customer, PlatformAdmin, ProjectManager, Assessor |
| GET | `/api/machines` | List machines, optional customer filter | Customer, PlatformAdmin, ProjectManager, Assessor |
| POST | `/api/machines/{id}/assessments` | Create an as-found assessment (supersedes the machine's prior non-terminal assessment; OCC on the machine version) | Assessor |
| GET | `/api/assessments/{id}` | Get an assessment | Assessor, ProjectManager, PlatformAdmin, Customer |
| GET | `/api/assessments` | List assessments, optional machine filter | Assessor, ProjectManager, PlatformAdmin, Customer |
| POST | `/api/assessments/{id}/submit` | Submit (or resubmit from RETURNED) an assessment | Assessor |
| POST | `/api/assessments/{id}/return` | Return a submitted assessment for rework | ProjectManager |
| POST | `/api/assessments/{id}/accept` | Accept a submitted assessment; auto-creates the RebuildProject | ProjectManager |
| GET | `/api/projects/{id}` | Get a project | ProjectManager, Customer, PlatformAdmin, RebuildEngineer, QualityInspector |
| GET | `/api/projects` | List projects with optional filters | ProjectManager, Customer, PlatformAdmin |
| POST | `/api/projects/{id}/decision` | Record the control-retrofit vs mechanical-rebuild decision and assign the rebuild engineer | ProjectManager |
| POST | `/api/projects/{id}/quote` | Compute/recompute the quote revision (OCC on the project version; reverts QUOTE_SENT to QUOTE_DRAFT) | ProjectManager |
| POST | `/api/projects/{id}/quote/send` | Send the quote to the customer | ProjectManager |
| POST | `/api/projects/{id}/quote/approve` | Customer approves the sent quote | Customer |
| POST | `/api/projects/{id}/begin-sourcing` | Open parts sourcing: reserve stock for ACTIVE parts, spawn RE jobs for OBSOLETE parts | ProjectManager |
| POST | `/api/projects/{id}/part-lines` | Add a part line to a DECIDED project | ProjectManager |
| POST | `/api/projects/{id}/start-rebuild` | Start mechanical/control work once all lines are fulfilled | ProjectManager |
| POST | `/api/projects/{id}/declare-ready` | Assigned rebuild engineer declares the machine ready for acceptance testing (from REBUILD_IN_PROGRESS or REWORK) | RebuildEngineer |
| POST | `/api/projects/{id}/acceptance-tests` | Schedule a geometric accuracy acceptance test | QualityInspector |
| POST | `/api/projects/{id}/escalation/resolve` | Resolve an ESCALATED project: RETRY (penalty, reset consecutive failures) or CANCEL | ProjectManager |
| POST | `/api/projects/{id}/begin-training` | Assign trainer and begin operator training | ProjectManager |
| POST | `/api/projects/{id}/shipment-stages` | Plan a staged shipment inside a downtime window | LogisticsCoordinator |
| POST | `/api/projects/{id}/deliver` | Deliver into warranty once stages are installed and training complete | ProjectManager |
| POST | `/api/projects/{id}/cancel` | Cancel an early-stage project (SCOPED/DECIDED/PARTS_SOURCING) | ProjectManager |
| POST | `/api/projects/{id}/trade-in/apply` | Apply an ACCEPTED trade-in offer's credit to the quote | ProjectManager |
| POST | `/api/projects/{id}/trade-in/revoke` | Revoke an applied trade-in credit before quote approval | ProjectManager |
| GET | `/api/part-lines/{id}` | Get a part line | ProjectManager, LogisticsCoordinator, PlatformAdmin |
| GET | `/api/part-lines` | List part lines with optional filters | ProjectManager, LogisticsCoordinator, PlatformAdmin |
| POST | `/api/part-lines/{id}/fulfill` | Issue reserved stock to the project | LogisticsCoordinator |
| POST | `/api/part-lines/{id}/cancel` | Cancel a PENDING or RESERVED line (releases reservation) | ProjectManager |
| GET | `/api/re-jobs/{id}` | Get an RE job | RebuildEngineer, QualityInspector, ProjectManager, PlatformAdmin |
| GET | `/api/re-jobs` | List RE jobs with optional filters | RebuildEngineer, QualityInspector, ProjectManager, PlatformAdmin |
| POST | `/api/re-jobs/{id}/capture-spec` | Capture the reverse-engineering specification | RebuildEngineer |
| POST | `/api/re-jobs/{id}/fabricate` | Fabricate the prototype part | RebuildEngineer |
| POST | `/api/re-jobs/{id}/validate` | Quality validation of the prototype (segregated from fabricator) | QualityInspector |
| POST | `/api/re-jobs/{id}/fail` | Fail the prototype; job cycles back to SPEC_CAPTURED | QualityInspector |
| GET | `/api/acceptance-tests/{id}` | Get an acceptance test | QualityInspector, ProjectManager, Customer, PlatformAdmin |
| GET | `/api/acceptance-tests` | List acceptance tests with optional project filter | QualityInspector, ProjectManager, Customer, PlatformAdmin |
| POST | `/api/acceptance-tests/{id}/record` | Record measurements; computes statistic and PASS/FAIL, fires project cascade | QualityInspector |
| GET | `/api/training-records/{id}` | Get a training record | Trainer, ProjectManager, Customer, PlatformAdmin |
| GET | `/api/training-records` | List training records with optional project filter | Trainer, ProjectManager, Customer, PlatformAdmin |
| POST | `/api/training-records/{id}/log-session` | Log one completed operator-training session | Trainer |
| POST | `/api/training-records/{id}/deliver-documentation` | Mark operator documentation delivered | Trainer |
| POST | `/api/downtime-windows` | Book a customer production downtime window (half-open, no same-customer overlap) | Customer, LogisticsCoordinator |
| GET | `/api/downtime-windows/{id}` | Get a downtime window | Customer, LogisticsCoordinator, ProjectManager, PlatformAdmin |
| GET | `/api/downtime-windows` | List downtime windows with optional customer filter | Customer, LogisticsCoordinator, ProjectManager, PlatformAdmin |
| POST | `/api/downtime-windows/{id}/cancel` | Cancel an OPEN window (LOCKED windows cannot be cancelled) | Customer, LogisticsCoordinator |
| GET | `/api/shipment-stages/{id}` | Get a shipment stage | LogisticsCoordinator, ProjectManager, Customer, PlatformAdmin |
| GET | `/api/shipment-stages` | List shipment stages with optional filters | LogisticsCoordinator, ProjectManager, Customer, PlatformAdmin |
| POST | `/api/shipment-stages/{id}/ship` | Ship a PLANNED stage (project must be post-acceptance) | LogisticsCoordinator |
| POST | `/api/shipment-stages/{id}/receive` | Receive a SHIPPED stage at customer site | LogisticsCoordinator |
| POST | `/api/shipment-stages/{id}/install` | Install a RECEIVED stage | LogisticsCoordinator |
| POST | `/api/shipment-stages/{id}/replan` | Replan an ON_HOLD or PLANNED stage with new dates (revalidates window containment and sibling gap) | LogisticsCoordinator |
| POST | `/api/projects/{id}/warranty-claims` | File a warranty claim on rebuilt accuracy or mechanical defect | Customer |
| GET | `/api/warranty-claims/{id}` | Get a warranty claim | Customer, WarrantyAdministrator, ProjectManager, PlatformAdmin |
| GET | `/api/warranty-claims` | List warranty claims with optional project filter | Customer, WarrantyAdministrator, ProjectManager, PlatformAdmin |
| POST | `/api/warranty-claims/{id}/approve` | Approve a filed claim | WarrantyAdministrator |
| POST | `/api/warranty-claims/{id}/reject` | Reject a filed claim | WarrantyAdministrator |
| POST | `/api/warranty-claims/{id}/remediate` | Close an approved claim after remediation | WarrantyAdministrator |
| POST | `/api/machines/{id}/trade-in-offers` | Create a trade-in offer (both valuation variants computed and stored; supersedes prior OFFERED offer; OCC on the machine version) | ProjectManager |
| GET | `/api/trade-in-offers/{id}` | Get a trade-in offer | Customer, ProjectManager, PlatformAdmin |
| GET | `/api/trade-in-offers` | List trade-in offers with optional filters | Customer, ProjectManager, PlatformAdmin |
| POST | `/api/trade-in-offers/{id}/accept` | Customer accepts an offer; machine becomes TRADED_IN (cascade) | Customer |
| POST | `/api/trade-in-offers/{id}/decline` | Customer declines an offer | Customer |
| POST | `/api/parts` | Create a spare-part master record | PlatformAdmin |
| GET | `/api/parts/{id}` | Get a part | PlatformAdmin, ProjectManager, LogisticsCoordinator, RebuildEngineer |
| GET | `/api/parts` | List parts with optional supersession filter | PlatformAdmin, ProjectManager, LogisticsCoordinator, RebuildEngineer |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock (test-driving endpoint; sweeps windows and WARRANTY_ACTIVE projects) | PlatformAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions that trigger each error are defined by the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_HEADERS` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_MACHINE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PROJECT_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PROJECT_NOT_IN_WARRANTY` | 409 Conflict |
| `ERR_COMMERCIAL_NOT_APPROVED` | 409 Conflict |
| `ERR_QUOTE_REQUIRED` | 409 Conflict |
| `ERR_PROJECT_NOT_AWAITING_ACCEPTANCE` | 409 Conflict |
| `ERR_QUOTE_STALE` | 409 Conflict |
| `ERR_OPEN_ACCEPTANCE_TEST` | 409 Conflict |
| `ERR_PART_SUPERSEDED` | 409 Conflict |
| `ERR_TRADE_IN_NOT_APPLICABLE` | 409 Conflict |
| `ERR_TRADE_IN_ALREADY_APPLIED` | 409 Conflict |
| `ERR_WARRANTY_EXPIRED` | 409 Conflict |
| `ERR_TRADE_IN_OFFER_EXPIRED` | 409 Conflict |
| `ERR_WINDOW_EMPTY` | 409 Conflict |
| `ERR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_STAGE_OUTSIDE_WINDOW` | 409 Conflict |
| `ERR_STAGE_GAP_TOO_SMALL` | 409 Conflict |
| `ERR_CLAIM_ALREADY_OPEN` | 409 Conflict |
| `ERR_STAGES_NOT_INSTALLED` | 409 Conflict |
| `ERR_DECISION_OVERRIDE_NEEDS_REASON` | 409 Conflict |
| `ERR_TRAINING_SESSION_OVERFLOW` | 409 Conflict |
| `ERR_LINES_OUTSTANDING` | 409 Conflict |
| `ERR_INSUFFICIENT_STOCK` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_DRIFT_WITHIN_TOLERANCE` | 409 Conflict |
